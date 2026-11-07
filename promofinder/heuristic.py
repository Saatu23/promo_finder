"""Keyword baseline + offline mock model.

1) `baseline_promos` is a no-AI promo picker (punctuation + drama keywords). It is the
   yardstick in the evaluation: the AI pipeline has to beat it to justify its cost.
2) `make_mock` returns a fake model that answers every pipeline stage in the right JSON
   shape, so the whole tool runs and is testable without an API key.
"""
from __future__ import annotations

import json
import re

from .parser import Episode, Event

STRONG = re.compile(r"\b(slap\w*|strik\w*|struck|blood\w*|kill\w*|hang\w*|gallows|poison\w*|witch\w*|dead|die|"
                    r"death|liar|betray\w*|disown\w*|revok\w*|duke|duchess|arrest\w*|burn\w*|fire|chain\w*|"
                    r"execut\w*|thief|steal|stole|murder\w*|traitor|treason|never|hate|kneel\w*|beg\w*|"
                    r"explosion|explod\w*|seiz\w*|drag\w*|throw\w*|threw|fling\w*|flung|grab\w*|collaps\w*|"
                    r"scream\w*|sword|knife|blade|gun|wife|husband|marry|married|wedding)\b", re.I)


def line_intensity(e: Event) -> float:
    t = e.text
    s = 0.0
    if e.kind == "dialogue":
        s += 1.0 + 1.5 * t.count("!") + 1.0 * ("?" in t) + 1.2 * len(STRONG.findall(t))
        d = e.delivery.lower()
        s += 1.0 * any(w in d for w in ("scream", "furious", "venom", "cruel", "shout", "desperate", "lethal",
                                         "threat", "menac", "shock", "horrif", "outrag"))
    elif e.kind == "action":
        s += 0.8 * len(STRONG.findall(t))
    elif e.kind == "sfx":
        s += 0.5 * len(STRONG.findall(t))
    return s


def baseline_promos(ep: Episode, n: int = 4) -> list[dict]:
    evs = ep.events
    lines = [e for e in evs if e.kind in ("dialogue", "action")]
    cands = []
    for h in lines:
        hs = line_intensity(h)
        if hs < 2.5:
            continue
        best = None
        for c in lines:
            if c.idx <= h.idx:
                continue
            dur = c.end - h.start
            if dur < 22 or dur > 55:
                continue
            cs = line_intensity(c) + (2.0 if c.kind == "dialogue" and c.text.rstrip('"').endswith(("?", "!", "...")) else 0)
            if best is None or cs > best[0]:
                best = (cs, c)
        if best:
            cands.append((hs + best[0], h, best[1]))
    cands.sort(key=lambda x: -x[0])
    picked: list[tuple[float, Event, Event]] = []
    for sc, h, c in cands:
        if any(not (c.end <= p[1].start or h.start >= p[2].end) for p in picked):
            continue
        picked.append((sc, h, c))
        if len(picked) >= n:
            break
    out = []
    for sc, h, c in picked:
        out.append({"title": f"Keyword pick @{h.start:.0f}s",
                    "segments": [{"start_ref": h.ref, "end_ref": c.ref}],
                    "hook_ref": h.ref, "hook": h.text[:80], "cliffhanger_ref": c.ref,
                    "cliffhanger": c.text[:80], "why": "high keyword/punctuation intensity at open and close",
                    "trope": "danger", "context_risk": "unknown (heuristic)", "_score": round(sc, 2)})
    return out


def make_mock(episodes: list[Episode]):
    eps = {e.number: e for e in episodes}

    def clamp(x):
        return int(max(1, min(10, round(x))))

    def fn(stage: str, system: str, prompt: str) -> str:
        if stage == "bible":
            labels = re.findall(r"^- (.+?): ", prompt, re.M)
            chars = [{"name": l.title(), "role": "character", "labels": [l]} for l in labels]
            return json.dumps({"premise": "A humiliated noblewoman marries a scarred stranger who is secretly a duke.",
                               "characters": chars, "reveals": []})
        if stage.startswith("propose"):
            out = []
            for n in re.findall(r"=== EPISODE (\d+) \(find promos here\)", prompt):
                for r in baseline_promos(eps[int(n)]):
                    out.append({**r, "episode": int(n)})
            return json.dumps({"promos": out})
        if stage == "repair":
            return json.dumps({"promos": []})
        if stage == "blind":
            first = prompt.split("FULL CLIP")[0]
            clip = prompt.split("FULL CLIP")[1]
            hook = 3 + 1.5 * first.count("!") + 1.0 * len(STRONG.findall(first))
            und = 8 - 0.5 * len(set(re.findall(r"\n[\d:.]+ ([A-Z][A-Z' ]+)[ (:]", clip)))
            last = clip.strip().splitlines()[-1] if clip.strip() else ""
            need = 4 + 2 * ("?" in last) + 1.5 * len(STRONG.findall(last))
            return json.dumps({"stopped_scrolling": clamp(hook), "understood": clamp(und), "need_to_know": clamp(need),
                               "what_happened": "(mock) a confrontation", "open_question": "(mock) what next?",
                               "confused_by": [], "would_tap": need >= 6})
        if stage == "judge":
            ids = re.findall(r"^ID: (\S+)", prompt, re.M)
            reviews = []
            for k, i in enumerate(ids):
                block = prompt.split(f"ID: {i}")[1].split("\nID: ")[0]
                inten = len(STRONG.findall(block))
                reviews.append({"id": i, "hook": clamp(4 + inten / 4), "cliffhanger": clamp(4 + block.count("?") / 2),
                                "standalone": clamp(6), "emotion": clamp(4 + inten / 3), "spoiler": 0,
                                "rank_in_episode": k + 1, "hook_text": "(mock)", "cliffhanger_text": "(mock)",
                                "why": "(mock) high-conflict exchange", "weakness": "(mock)"})
            return json.dumps({"reviews": reviews})
        if stage == "plan":
            ids = re.findall(r"^ID: (\S+)", prompt, re.M)
            k = int(re.search(r"Choose the first (\d+)", prompt).group(1))
            return json.dumps({"strategy": "(mock) post in score order.",
                               "order": [{"id": i, "reason": "(mock) high score"} for i in ids[:k]]})
        return "{}"

    return fn
