"""Stages: bible -> propose (+repair) -> validate -> blind viewer -> judge -> score/rank -> launch plan."""
from __future__ import annotations

import json
import threading
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from . import prompts as P
from .llm import LLM, LLMError
from .parser import Episode, fmt_ts
from .validate import Checked, check_promo, clip_events, iou, parse_ref, render_clip


@dataclass
class Promo:
    id: str
    episode: int
    raw: dict
    checked: Checked
    origin: str = "model"            # model | repaired
    blind: dict | None = None
    review: dict | None = None
    sub: dict = field(default_factory=dict)
    score: float = 0.0
    confidence: str = ""
    status: str = "candidate"        # candidate | ranked | duplicate | unranked
    note: str = ""
    rank: int | None = None
    cast: list[str] = field(default_factory=list)
    clip: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        r = self.review or {}
        return {
            "rank": self.rank, "id": self.id, "status": self.status, "note": self.note,
            "title": self.raw.get("title", ""), "episode": self.episode,
            "episodes": sorted({s.episode for s in self.checked.segments}),
            "segments": [s.to_dict() for s in self.checked.segments],
            "duration_s": self.checked.duration,
            "hook": r.get("hook_text") or self.raw.get("hook", ""),
            "hook_at_s": self.checked.hook_at,
            "cliffhanger": r.get("cliffhanger_text") or self.raw.get("cliffhanger", ""),
            "why": r.get("why") or self.raw.get("why", ""),
            "weakness": r.get("weakness", ""),
            "trope": self.raw.get("trope", ""), "cast": self.cast, "clip": self.clip,
            "score": round(self.score, 2), "subscores": self.sub, "confidence": self.confidence,
            "warnings": self.checked.warnings, "origin": self.origin,
            "cold_viewer": self.blind, "judge": self.review,
            "model_proposal": {k: v for k, v in self.raw.items() if not k.startswith("_")},
        }


def _as_int(x, lo=0, hi=10, default=5) -> int:
    try:
        return int(max(lo, min(hi, round(float(x)))))
    except (TypeError, ValueError):
        return default


def _failure_type(err: str) -> str:
    """Group rule errors by kind ('hook line starts 3.9s into...' and '...8.8s...' are the same failure)."""
    for key, label in (("hook line starts", "hook later than 3s"), ("is not inside the first", "hook outside first segment"),
                       ("too short", "too short (<20s)"), ("too long", "too long (>60s)"),
                       ("cliffhanger line", "cliffhanger outside last segment"), ("overlap", "segments overlap/out of order"),
                       ("out of range", "line ID out of range"), ("unreadable", "unreadable line ID"),
                       ("hook_ref", "missing hook line ID")):
        if key in err:
            return label
    return err.split(":")[0][:40]


def _pct(values: list[float]) -> list[float]:
    """Percentile rank 0..1 (ties averaged). Puts two scorers with different scales on one footing."""
    order = sorted(values)
    n = len(values)
    if n < 2:
        return [0.5] * n
    out = []
    for v in values:
        lo = order.index(v)
        hi = n - 1 - order[::-1].index(v)
        out.append((lo + hi) / 2 / (n - 1))
    return out


class Pipeline:
    def __init__(self, cfg: dict, llm: LLM, log: Callable[[str], None] = print,
                 progress: Callable[[str, int, int], None] | None = None):
        self.cfg, self.llm, self.log = cfg, llm, log
        self.progress = progress or (lambda s, d, t: None)
        self.specs = cfg["specs"]
        self.stats: dict[str, Any] = defaultdict(int)
        self.failures: Counter = Counter()
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ helpers
    def _pmap(self, fn, items, stage):
        out, done = [None] * len(items), 0
        with ThreadPoolExecutor(max_workers=self.cfg["run"].get("workers", 4)) as ex:
            futs = {ex.submit(fn, it): i for i, it in enumerate(items)}
            for f, i in futs.items():
                try:
                    out[i] = f.result()
                except Exception as e:  # noqa: BLE001 - one bad episode must not kill the run
                    self.log(f"  ! {stage} item {i} failed: {e}")
                    self.stats[f"{stage}_errors"] += 1
                    self.first_error = getattr(self, "first_error", "") or str(e)
                done += 1
                self.progress(stage, done, len(items))
                if len(items) > 1 and (done == len(items) or done % max(1, len(items) // 10) == 0):
                    self.log(f"      {stage}: {done}/{len(items)}")
        return out

    # -------------------------------------------------------------------- bible
    def bible(self, episodes: list[Episode]) -> dict:
        labels: dict[str, list[int]] = defaultdict(list)
        for ep in episodes:
            for d in ep.dialogue:
                lab = d.speaker.upper()
                if ep.number not in labels[lab]:
                    labels[lab].append(ep.number)
        label_txt = "\n".join(f"- {l}: {', '.join(map(str, eps[:12]))}{' ...' if len(eps) > 12 else ''}"
                              for l, eps in sorted(labels.items(), key=lambda kv: kv[1][0]))
        tr = []
        for ep in episodes:
            tr.append(f"\n## EPISODE {ep.number}: {ep.logline}")
            tr += [f"{d.speaker}: {d.text}" for d in ep.dialogue]
        prompt = P.BIBLE_PROMPT.format(labels=label_txt, transcript="\n".join(tr))
        self.log(f"      one call to {self.specs['bible'].label}, ~{len(prompt) // 4:,} tokens in; usually 20-90s")

        def v(d):
            if not isinstance(d, dict) or not isinstance(d.get("characters"), list):
                raise ValueError("need {'characters': [...]}")
            return d
        try:
            bible = self.llm.json(self.specs["bible"], P.BIBLE_SYSTEM, prompt, "bible", v)
        except LLMError as e:
            self.log(f"  ! bible failed ({e}); continuing with raw speaker labels")
            bible = {"premise": "", "characters": [], "reveals": []}
        alias = {}
        for c in bible.get("characters", []):
            for l in c.get("labels", []) or []:
                alias[str(l).upper().strip()] = {"name": c.get("name", l), "role": c.get("role", "")}
        missing = [l for l in labels if l not in alias]
        for l in missing:
            alias[l] = {"name": l.title(), "role": ""}
        bible["alias"] = alias
        bible["unmapped_labels"] = missing
        self.stats["speaker_labels"] = len(labels)
        self.stats["speaker_labels_unmapped"] = len(missing)
        return bible

    def _cast(self, promo: Promo, eps: dict[int, Episode], alias: dict) -> list[str]:
        names = []
        for s in promo.checked.segments:
            for d in eps[s.episode].dialogue:
                if d.start >= s.start - 0.05 and d.start < s.end:
                    a = alias.get(d.speaker.upper(), {"name": d.speaker.title(), "role": ""})
                    tag = a["name"] + (f" ({a['role']})" if a.get("role") else "")
                    if tag not in names:
                        names.append(tag)
        return names

    def _clip(self, p: Promo, eps: dict[int, Episode]) -> list[dict]:
        hk = parse_ref(p.raw.get("hook_ref"), p.episode)
        ck = parse_ref(p.raw.get("cliffhanger_ref"), p.episode)
        out, seg_starts = [], {}
        for t, e in clip_events(p.checked.segments, eps):
            out.append({"t": t, "ref": e.ref, "episode": e.episode, "at": fmt_ts(e.start), "kind": e.kind,
                        "speaker": e.speaker, "text": e.text, "first3": t < 3.0,
                        "hook": (e.episode, e.idx) == hk, "cliff": (e.episode, e.idx) == ck})
        return out

    # ------------------------------------------------------------------ propose
    def _characters_line(self, bible: dict) -> str:
        parts = []
        for c in bible.get("characters", [])[:25]:
            labs = [l for l in (c.get("labels") or []) if str(l).upper() != str(c.get("name", "")).upper()]
            aka = f" (labelled {', '.join(labs[:4])})" if labs else ""
            parts.append(f"{c.get('name')}{aka}: {c.get('role', '')}")
        return "; ".join(parts) or "(not available)"

    def propose(self, group: list[Episode], eps: dict[int, Episode], bible: dict) -> list[Promo]:
        """One call proposes promos for a batch of consecutive episodes (batch size in config)."""
        run = self.cfg["run"]
        targets = [e.number for e in group]
        blocks = []
        for e in group:
            blocks.append(f"\n=== EPISODE {e.number} (find promos here) ===\nLogline: {e.logline}\n{e.render(with_ep=True)}")
        nxt = eps.get(targets[-1] + 1) if run.get("use_next_episode", True) else None
        if nxt:
            blocks.append(f"\n=== EPISODE {nxt.number} (continuation - use only to complete or join a promo) ===\n"
                          f"Logline: {nxt.logline}\n{nxt.render(with_ep=True)}")
        prev = eps.get(targets[0] - 1)
        prompt = P.PROPOSE_PROMPT.format(
            definition=P.PROMO_DEFINITION, premise=bible.get("premise", ""),
            characters=self._characters_line(bible),
            prev_logline=f"Episode {prev.number}: {prev.logline}" if prev else "(this is the first episode)",
            ep=targets[0], targets=", ".join(map(str, targets)), blocks="\n".join(blocks),
            n=run.get("promos_per_episode", 4), tropes=json.dumps(P.TROPES))

        def v(d):
            if not isinstance(d, dict) or not isinstance(d.get("promos"), list):
                raise ValueError("need {'promos': [...]}")
            return [p for p in d["promos"] if isinstance(p, dict)]

        def home(r) -> int:
            try:
                n = int(r.get("episode"))
                if n in targets:
                    return n
            except (TypeError, ValueError):
                pass
            ref = parse_ref((r.get("segments") or [{}])[0].get("start_ref"), targets[0])
            return ref[0] if ref and ref[0] in targets else targets[0]

        raws = self.llm.json(self.specs["propose"], P.PROPOSE_SYSTEM, prompt, "propose", v)
        good: list[tuple[dict, Checked, str]] = []
        bad: list[tuple[dict, Checked]] = []
        for r in raws:
            c = check_promo(r, eps, home(r))
            self.stats["proposed"] += 1
            if c.ok:
                good.append((r, c, "model"))
            else:
                bad.append((r, c))
                for e in c.errors:
                    self.failures[_failure_type(e)] += 1
        with self._lock:
            self.stats["failed_rules_first_try"] += len(bad)
        if bad:
            fail_txt = "\n".join(f"- {json.dumps({k: v for k, v in r.items() if not k.startswith('_')})}\n"
                                 f"  ERRORS: {'; '.join(c.errors)} (measured length {c.duration:.1f}s)"
                                 for r, c in bad)
            try:
                fixed = self.llm.json(self.specs["propose"], P.PROPOSE_SYSTEM,
                                      prompt + "\n\n" + P.REPAIR_PROMPT.format(failures=fail_txt), "repair", v)
            except LLMError as e:
                self.log(f"  ! repair failed for episodes {targets}: {e}")
                fixed = []
            seen = [c.segments for _, c, _ in good]
            for r in fixed:   # the model sometimes re-sends promos that already passed: skip those
                c = check_promo(r, eps, home(r))
                if c.ok and any(iou(c.segments, s) > 0.6 for s in seen):
                    self.stats["repair_resent_passing"] += 1
                    continue
                if c.ok:
                    seen.append(c.segments)
                    good.append((r, c, "repaired"))
                    self.stats["repaired_ok"] += 1
                else:
                    self.stats["repair_still_invalid"] += 1
        promos: list[Promo] = []
        count: dict[int, int] = defaultdict(int)
        for r, c, origin in good:
            ep_n = home(r)
            moved = ep_n not in {sg.episode for sg in c.segments}
            if moved:
                # the model built the promo entirely inside the continuation episode: label it by where it plays
                # (v3 bug: 'E06-4' played wholly in episode 7 and duplicated an episode-7 promo)
                ep_n = c.segments[0].episode
                self.stats["relabelled_to_continuation_episode"] += 1
            same = [q for q in promos if q.episode == ep_n]
            if any(iou(c.segments, q.checked.segments) > 0.6 for q in same):
                self.stats["near_duplicates_in_episode"] += 1
                continue
            count[ep_n] += 1
            # another batch numbers its own promos for ep_n, so a moved promo gets a distinct id ('E07-x1')
            pid = f"E{ep_n:02d}-{'x' if moved else ''}{count[ep_n]}"
            promos.append(Promo(pid, ep_n, r, c, origin))
        return promos

    # -------------------------------------------------------------------- blind
    def blind(self, p: Promo, eps: dict[int, Episode]) -> dict:
        prompt = P.BLIND_PROMPT.format(first3=render_clip(p.checked.segments, eps, until=3.0) or "(nothing)",
                                       clip=render_clip(p.checked.segments, eps), duration=p.checked.duration)

        def v(d):
            if not isinstance(d, dict) or "understood" not in d:
                raise ValueError("missing scores")
            for k in ("stopped_scrolling", "understood", "need_to_know"):
                d[k] = _as_int(d.get(k), 1, 10)
            return d
        return self.llm.json(self.specs["blind"], P.BLIND_SYSTEM, prompt, "blind", v)

    # -------------------------------------------------------------------- judge
    def judge(self, group: list[Episode], promos: list[Promo], eps: dict[int, Episode], bible: dict) -> None:
        if not promos:
            return
        blocks = []
        for p in promos:
            b = p.blind or {}
            segs = ", ".join(f"Ep{s.episode} {fmt_ts(s.start)}-{fmt_ts(s.end)}" for s in p.checked.segments)
            blocks.append(
                f"ID: {p.id}\nTitle: {p.raw.get('title', '')} | length {p.checked.duration:.1f}s | {segs}\n"
                f"Proposed hook: {p.raw.get('hook', '')}\nProposed cliffhanger: {p.raw.get('cliffhanger', '')}\n"
                f"Rule warnings: {'; '.join(p.checked.warnings) or 'none'}\n"
                f"CLIP:\n{render_clip(p.checked.segments, eps)}\n"
                f"COLD VIEWER: stopped_scrolling={b.get('stopped_scrolling')} understood={b.get('understood')} "
                f"need_to_know={b.get('need_to_know')} would_tap={b.get('would_tap')}\n"
                f"  said: {b.get('what_happened', '')} | open question: {b.get('open_question', '')} | "
                f"confused by: {b.get('confused_by', [])}\n")
        reveals = "; ".join(f"ep{r.get('episode')}: {r.get('reveal')}" for r in bible.get("reveals", [])) or "unknown"
        script = "\n\n".join(f"=== EPISODE {e.number} ===\n{e.render(kinds={'dialogue', 'action'})}" for e in group)
        prompt = P.JUDGE_PROMPT.format(definition=P.PROMO_DEFINITION, premise=bible.get("premise", ""),
                                       reveals=reveals, script=script, promos="\n".join(blocks))
        ids = {p.id for p in promos}

        def v(d):
            if not isinstance(d, dict) or not isinstance(d.get("reviews"), list):
                raise ValueError("need {'reviews': [...]}")
            got = {str(r.get("id")) for r in d["reviews"] if isinstance(r, dict)}
            if not ids <= got:
                raise ValueError(f"missing reviews for {sorted(ids - got)}")
            return d["reviews"]
        try:
            reviews = self.llm.json(self.specs["judge"], P.JUDGE_SYSTEM, prompt, "judge", v)
        except LLMError as e:
            self.log(f"  ! judge failed for episodes {[e.number for e in group]}: {e}")
            reviews = []
        by_id = {str(r.get("id")): r for r in reviews if isinstance(r, dict)}
        for p in promos:
            r = by_id.get(p.id)
            if r:
                for k in ("hook", "cliffhanger", "standalone", "emotion"):
                    r[k] = _as_int(r.get(k), 1, 10)
                r["spoiler"] = _as_int(r.get("spoiler"), 0, 2, 0)
            p.review = r

    # -------------------------------------------------------------------- score
    @staticmethod
    def _resolved(p: Promo) -> tuple[bool, bool]:
        """(judge says resolved, cold viewer says it felt finished)."""
        r, b = p.review or {}, p.blind or {}
        j = str(r.get("resolved_in_clip", "")).lower() == "true"
        oq = str(b.get("open_question", "")).strip().lower()
        v = str(b.get("ended_unresolved", "true")).lower() == "false" or oq in ("", "none", "n/a", "nothing")
        return j, v

    def score_all(self, promos: list[Promo], max_ep: int) -> None:
        """Weighted score per promo.

        The judge (strong model, sees the show) and the cold viewer (cheap model, sees only the clip) use
        different scales: v3 found the judge gave cliffhanger 8-10 to almost everything while the cold viewer
        gave need-to-know 1-4. Blending raw numbers let the generous scorer dominate and made 'confidence'
        almost always low. So each sub-score is turned into a percentile within the show first.
        """
        w = self.cfg["weights"]
        sh = w["blind_share"]
        cols = {"jh": ("review", "hook"), "jc": ("review", "cliffhanger"), "js": ("review", "standalone"),
                "je": ("review", "emotion"), "bh": ("blind", "stopped_scrolling"), "bn": ("blind", "need_to_know"),
                "bu": ("blind", "understood")}
        raw = {k: [((getattr(p, src) or {}).get(f, 5)) for p in promos] for k, (src, f) in cols.items()}
        pct = {k: _pct([float(x) for x in v]) for k, v in raw.items()}
        cap = w.get("resolved_cliff_cap", 3.0)
        for i, p in enumerate(promos):
            r, b = p.review or {}, p.blind or {}
            P_ = {k: pct[k][i] for k in pct}
            hook = 10 * ((1 - sh) * P_["jh"] + sh * P_["bh"])
            cliff = 10 * ((1 - sh) * P_["jc"] + sh * P_["bn"])
            stand = 10 * ((1 - sh) * P_["js"] + sh * P_["bu"])
            emo = 10 * P_["je"]
            j_res, v_res = self._resolved(p)
            if j_res or v_res:
                # either scorer says the clip answers its own question: not a cliffhanger. Tested a softer
                # one-vote cap (6.0): ranked recall vs the reference set fell 0.61 -> 0.50, so kept the hard cap.
                cliff = min(cliff, cap)
            base = w["hook"] * hook + w["cliffhanger"] * cliff + w["standalone"] * stand + w["emotion"] * emo
            pen = w["spoiler_penalty"] * r.get("spoiler", 0) + w["warning_penalty"] * min(3, len(p.checked.warnings))
            # the brief makes standalone a requirement: if BOTH scorers say a stranger would not follow it, penalise
            lost = r.get("standalone", 5) <= 4 and b.get("understood", 5) <= 4
            if lost:
                pen += w.get("not_standalone_penalty", 1.5)
            funnel = w["funnel_bonus_max"] * (1 - (p.episode - 1) / max(1, max_ep - 1))
            p.score = round(base - pen + funnel, 3)
            p.sub = {"hook": round(hook, 1), "cliffhanger": round(cliff, 1), "standalone": round(stand, 1),
                     "emotion": round(emo, 1), "spoiler": r.get("spoiler", 0), "penalty": round(pen, 2),
                     "funnel_bonus": round(funnel, 2), "not_standalone": lost, "resolved_judge": j_res, "resolved_cold_viewer": v_res,
                     "judge": {k: r.get(k) for k in ("hook", "cliffhanger", "standalone", "emotion")},
                     "cold_viewer": {k: b.get(k) for k in ("stopped_scrolling", "understood", "need_to_know")}}
            # confidence = do the two independent scorers agree (on the same percentile scale)?
            if not r or not b:
                p.confidence = "low"
                continue
            gap = max(abs(P_["jh"] - P_["bh"]), abs(P_["jc"] - P_["bn"]), abs(P_["js"] - P_["bu"]))
            agree_end = j_res == v_res
            if gap <= 0.30 and agree_end and not b.get("confused_by") and len(p.checked.warnings) == 0:
                p.confidence = "high"
            elif gap <= 0.45 and agree_end:
                p.confidence = "medium"
            else:
                p.confidence = "low"
            p.sub["agreement_gap"] = round(gap, 2)

    def rank(self, promos: list[Promo]) -> list[Promo]:
        w = self.cfg["weights"]
        pool = sorted(promos, key=lambda p: -p.score)
        chosen: list[Promo] = []
        limit = self.cfg["run"].get("max_ranked", 40)
        while pool and len(chosen) < limit:
            def adj(p):
                same_ep = sum(1 for q in chosen if q.episode == p.episode)
                same_tr = min(3, sum(1 for q in chosen if q.raw.get("trope") == p.raw.get("trope")))
                return p.score - w["same_episode_penalty"] * same_ep - w["same_trope_penalty"] * same_tr
            best = max(pool, key=adj)
            pool.remove(best)
            clash = next((q for q in chosen if iou(best.checked.segments, q.checked.segments) > w["max_overlap_iou"]), None)
            if clash:
                best.status, best.note = "duplicate", f"overlaps higher-ranked {clash.id}"
                continue
            best.status, best.rank = "ranked", len(chosen) + 1
            chosen.append(best)
        for p in pool:
            p.status, p.note = "unranked", "below the ranked-list cut-off"
        return chosen

    # --------------------------------------------------------------------- plan
    def plan(self, ranked: list[Promo], bible: dict) -> dict:
        k = min(self.cfg["run"].get("plan_top_k", 10), len(ranked))
        if k == 0:
            return {"strategy": "", "order": []}
        top = ranked[:max(k * 2, 15)]
        block = "\n".join(
            f"ID: {p.id} | score {p.score:.2f} | episode {p.episode} | {p.checked.duration:.0f}s | trope {p.raw.get('trope')}"
            f" | spoiler {p.sub.get('spoiler')} | confidence {p.confidence}"
            f"{' | ENDING RESOLVES ITSELF (weak cliffhanger)' if p.sub.get('resolved_judge') or p.sub.get('resolved_cold_viewer') else ''}"
            f"{' | STRANGERS MAY NOT FOLLOW IT' if p.sub.get('not_standalone') else ''}\n  hook: {(p.review or {}).get('hook_text') or p.raw.get('hook')}"
            f"\n  cliffhanger: {(p.review or {}).get('cliffhanger_text') or p.raw.get('cliffhanger')}"
            f"\n  why: {(p.review or {}).get('why') or p.raw.get('why')}" for p in top)
        ids = {p.id for p in top}

        def v(d):
            if not isinstance(d, dict) or not isinstance(d.get("order"), list):
                raise ValueError("need {'order': [...]}")
            d["order"] = [o for o in d["order"] if isinstance(o, dict) and str(o.get("id")) in ids][:k]
            if len(d["order"]) < min(k, 3):
                raise ValueError(f"order must contain {k} ids from the list")
            return d
        try:
            return self.llm.json(self.specs["plan"], P.PLAN_SYSTEM,
                                 P.PLAN_PROMPT.format(premise=bible.get("premise", ""), promos=block, k=k), "plan", v)
        except LLMError as e:
            self.log(f"  ! plan failed: {e}; falling back to score order")
            return {"strategy": "Fallback: score order.", "order": [{"id": p.id, "reason": "score"} for p in ranked[:k]]}

    # ---------------------------------------------------------------------- run
    def run(self, episodes: list[Episode], out_dir: str | Path) -> dict:
        t0 = time.time()
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        eps = {e.number: e for e in episodes}
        max_ep = max(eps) if eps else 1
        self.log(f"[1/6] show bible ({len(episodes)} episodes)")
        bible = self.bible(episodes)
        self.progress("bible", 1, 1)
        self.log(f"      bible: {len(bible.get('characters', []))} characters, {len(bible.get('reveals', []))} reveals")
        self.log("[2/6] proposing promos per episode (+ rule checks and repair)")
        k = max(1, int(self.cfg["run"].get("episodes_per_call", 1)))
        groups = [episodes[i:i + k] for i in range(0, len(episodes), k)]
        per_ep = self._pmap(lambda g: self.propose(g, eps, bible), groups, "propose")
        promos = [p for lst in per_ep if lst for p in lst]
        for p in promos:
            p.cast = self._cast(p, eps, bible["alias"])
            p.clip = self._clip(p, eps)
        self.log(f"      {len(promos)} valid promos")
        if not promos and getattr(self, "first_error", ""):
            # every proposal call failed (bad key, wrong model name, unreachable service): say so instead of
            # finishing with an empty result
            raise LLMError(f"no promos could be made; the AI service said: {self.first_error[:300]}")
        self.log("[3/6] cold-viewer test (model sees only the clip)")
        blinds = self._pmap(lambda p: self.blind(p, eps), promos, "blind")
        for p, b in zip(promos, blinds):
            p.blind = b
        self.log("[4/6] judging with rubric")
        by_ep: dict[int, list[Promo]] = defaultdict(list)
        for p in promos:
            by_ep[p.episode].append(p)
        self._pmap(lambda g: self.judge(g, [p for e in g for p in by_ep.get(e.number, [])], eps, bible), groups, "judge")
        self.log("[5/6] scoring and ranking")
        self.score_all(promos, max_ep)
        ranked = self.rank(promos)
        self.log("[6/6] launch plan")
        plan = self.plan(ranked, bible)
        self.progress("plan", 1, 1)
        result = {
            "show": {"episodes": len(episodes), "minutes": round(sum(e.duration for e in episodes) / 60, 1),
                     "premise": bible.get("premise", "")},
            "ranked": [p.to_dict() for p in ranked],
            "plan": plan,
            "all": [p.to_dict() for p in promos],
            "bible": bible,
            "stats": {**dict(self.stats), "rule_failures": dict(self.failures), "seconds": round(time.time() - t0, 1),
                      "data_warnings": {e.number: e.warnings for e in episodes if e.warnings}},
            "usage": self.llm.summary(),
            "models": {k: v.label for k, v in self.specs.items()},
        }
        from .report import write_outputs
        write_outputs(result, out)
        self.log(f"done in {result['stats']['seconds']}s -> {out}")
        return result
