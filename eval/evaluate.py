#!/usr/bin/env python3
"""Score a run against the reference promos, the keyword baseline, and itself.

  python eval/evaluate.py outputs/final                      # one run
  python eval/evaluate.py outputs/final --repeat outputs/rerun  # + run-to-run consistency
"""
from __future__ import annotations

import argparse
import json
import statistics as stats
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from promofinder.heuristic import baseline_promos  # noqa: E402
from promofinder.parser import load_inputs  # noqa: E402
from promofinder.validate import Segment, build_segments, check_promo, iou, parse_ref  # noqa: E402

DATA = ROOT / "data" / "i-married-a-broken-soldier"


def segs_from_dicts(ds: list[dict]) -> list[Segment]:
    return [Segment(d["episode"], d["start_s"], d["end_s"], d["start_ref"], d["end_ref"]) for d in ds]


def contains(segs: list[Segment], ep: int, t: float) -> bool:
    return any(s.episode == ep and s.start - 0.05 <= t <= s.end + 0.05 for s in segs)


def match(gold, gsegs, core, cand_segs) -> tuple[bool, float]:
    best, hit = 0.0, False
    for cs in cand_segs:
        v = iou(gsegs, cs)
        has_core = contains(cs, core[0], core[1])
        if v >= 0.35 or (has_core and v >= 0.20):
            hit = True
        best = max(best, v)
    return hit, best


def edit_ready(gsegs, cand_segs, tol=3.0) -> bool:
    """Same moment AND cut like an editor would: start and end each within tol seconds."""
    g0, g1 = gsegs[0], gsegs[-1]
    for cs in cand_segs:
        c0, c1 = cs[0], cs[-1]
        if c0.episode == g0.episode and c1.episode == g1.episode and \
                abs(c0.start - g0.start) <= tol and abs(c1.end - g1.end) <= tol:
            return True
    return False


def corr(xs, ys):
    if len(xs) < 3:
        return None
    mx, my = stats.mean(xs), stats.mean(ys)
    sx = sum((x - mx) ** 2 for x in xs) ** 0.5
    sy = sum((y - my) ** 2 for y in ys) ** 0.5
    return round(sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy), 2) if sx and sy else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("--repeat", help="a second run folder, for consistency")
    a = ap.parse_args()
    run = Path(a.run)
    eps = {e.number: e for e in load_inputs(DATA)}
    gold = json.loads((ROOT / "eval" / "gold.json").read_text(encoding="utf-8"))["promos"]
    allp = json.loads((run / "candidates_all.json").read_text(encoding="utf-8"))
    ranked = json.loads((run / "promos_ranked.json").read_text(encoding="utf-8"))
    summary = json.loads((run / "run_summary.json").read_text(encoding="utf-8"))
    gold_eps = sorted({parse_ref(g["start_ref"], 0)[0] for g in gold})

    # keyword baseline on the same episodes, same validator
    base = []
    for n in gold_eps:
        for r in baseline_promos(eps[n], 4):
            c = check_promo(r, eps, n)
            if c.ok:
                base.append(c.segments)

    rows, out = [], {}
    for g in gold:
        gsegs, _ = build_segments([{"start_ref": g["start_ref"], "end_ref": g["end_ref"]}], eps, 0)
        ce, ci = parse_ref(g["core_ref"], 0)
        core = (ce, eps[ce].events[ci].start)
        ep = gsegs[0].episode
        cand_all = [segs_from_dicts(p["segments"]) for p in allp if ep in p["episodes"]]
        cand_rank = [segs_from_dicts(p["segments"]) for p in ranked if ep in p["episodes"]]
        top10 = [segs_from_dicts(p["segments"]) for p in ranked[:10]]
        b = [s for s in base if any(x.episode == ep for x in s)]
        h_all, iou_all = match(g, gsegs, core, cand_all)
        h_rank, _ = match(g, gsegs, core, cand_rank)
        h_base, iou_base = match(g, gsegs, core, b)
        rows.append({"id": g["id"], "episode": ep, "found": h_all, "in_ranked": h_rank, "best_iou": round(iou_all, 2),
                     "edit_ready": edit_ready(gsegs, cand_all), "baseline_edit_ready": edit_ready(gsegs, b),
                     "baseline_found": h_base, "baseline_iou": round(iou_base, 2), "note": g["note"]})
    n = len(rows)
    out["reference_recall_all_candidates"] = round(sum(r["found"] for r in rows) / n, 2)
    out["reference_recall_ranked_list"] = round(sum(r["in_ranked"] for r in rows) / n, 2)
    out["reference_mean_best_iou"] = round(stats.mean(r["best_iou"] for r in rows), 2)
    out["reference_edit_ready_rate"] = round(sum(r["edit_ready"] for r in rows) / n, 2)
    out["baseline_edit_ready_rate"] = round(sum(r["baseline_edit_ready"] for r in rows) / n, 2)
    out["baseline_recall"] = round(sum(r["baseline_found"] for r in rows) / n, 2)
    out["baseline_mean_best_iou"] = round(stats.mean(r["baseline_iou"] for r in rows), 2)

    # precision proxy: tool promos in reference episodes that match some reference promo
    gsets = []
    for g in gold:
        gs, _ = build_segments([{"start_ref": g["start_ref"], "end_ref": g["end_ref"]}], eps, 0)
        ce, ci = parse_ref(g["core_ref"], 0)
        gsets.append((gs, (ce, eps[ce].events[ci].start)))
    in_gold_eps = [p for p in ranked if p["episode"] in gold_eps]
    matched = sum(1 for p in in_gold_eps if any(match(None, gs, core, [segs_from_dicts(p["segments"])])[0] for gs, core in gsets))
    out["ranked_promos_in_reference_episodes"] = len(in_gold_eps)
    out["of_which_match_a_reference_promo"] = matched

    # rule compliance + repair loop
    st = summary["stats"]
    out["proposed"] = st.get("proposed", 0)
    out["failed_rules_first_try"] = st.get("failed_rules_first_try", 0)
    out["first_try_rule_pass_rate"] = round(1 - st.get("failed_rules_first_try", 0) / max(1, st.get("proposed", 1)), 2)
    out["repaired_ok"] = st.get("repaired_ok", 0)
    out["rule_failures_by_type"] = st.get("rule_failures", {})

    # judge vs cold viewer agreement
    js, bs, jh, bh = [], [], [], []
    for p in allp:
        j, b = p.get("judge") or {}, p.get("cold_viewer") or {}
        if j and b:
            js.append(j["standalone"]); bs.append(b["understood"]); jh.append(j["hook"]); bh.append(b["stopped_scrolling"])
    out["judge_vs_cold_viewer"] = {"n": len(js), "standalone_vs_understood_r": corr(js, bs),
                                   "hook_vs_stopped_r": corr(jh, bh),
                                   "mean_abs_gap_standalone": round(stats.mean(abs(x - y) for x, y in zip(js, bs)), 2) if js else None}
    conf = {}
    for p in ranked:
        conf[p["confidence"]] = conf.get(p["confidence"], 0) + 1
    out["ranked_confidence_mix"] = conf
    out["ranked_spread"] = {"episodes_covered": len({p["episode"] for p in ranked}),
                            "tropes": sorted({p.get("trope", "") for p in ranked})}

    if a.repeat:
        r2 = json.loads((Path(a.repeat) / "promos_ranked.json").read_text(encoding="utf-8"))
        top_a = [segs_from_dicts(p["segments"]) for p in ranked[:10]]
        top_b = [segs_from_dicts(p["segments"]) for p in r2[:20]]
        same = sum(1 for s in top_a if any(iou(s, t) >= 0.35 for t in top_b))
        out["consistency_top10_found_in_rerun_top20"] = f"{same}/10"

    (run / "eval.json").write_text(json.dumps({"summary": out, "per_reference_promo": rows}, indent=2), encoding="utf-8")
    lines = ["# Evaluation", "", "| metric | value |", "|---|---|"]
    for k, v in out.items():
        lines.append(f"| {k} | {v} |")
    lines += ["", "## Reference promos", "", "| id | ep | found by tool | edit-ready cut | in ranked list | best IoU | keyword baseline | note |",
              "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['id']} | {r['episode']} | {'yes' if r['found'] else 'NO'} | {'yes' if r['edit_ready'] else 'no'} | {'yes' if r['in_ranked'] else 'no'} | "
                     f"{r['best_iou']} | {'yes' if r['baseline_found'] else 'no'} ({r['baseline_iou']}) | {r['note']} |")
    (run / "eval.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines[:4 + len(out)]))


if __name__ == "__main__":
    main()
