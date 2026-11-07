"""Write the run's outputs: JSON (full detail), CSV (for editors), Markdown report (for humans)."""
from __future__ import annotations

import csv
import json
from pathlib import Path


def seg_str(segs: list[dict]) -> str:
    return " + ".join(f"Ep{s['episode']} {s['start']}-{s['end']}" for s in segs)


def write_outputs(result: dict, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "promos_ranked.json").write_text(json.dumps(result["ranked"], indent=2, ensure_ascii=False), encoding="utf-8")
    (out / "launch_plan.json").write_text(json.dumps(result["plan"], indent=2, ensure_ascii=False), encoding="utf-8")
    (out / "candidates_all.json").write_text(json.dumps(result["all"], indent=2, ensure_ascii=False), encoding="utf-8")
    (out / "show_bible.json").write_text(json.dumps(result["bible"], indent=2, ensure_ascii=False), encoding="utf-8")
    summary = {k: result[k] for k in ("show", "stats", "usage", "models")}
    (out / "run_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    with (out / "promos_ranked.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["rank", "id", "episodes", "segments (episode start-end, in order)", "duration_s", "hook",
                    "cliffhanger", "why_it_works", "trope", "score", "hook_score", "cliffhanger_score",
                    "standalone_score", "emotion", "spoiler", "confidence", "warnings"])
        for p in result["ranked"]:
            s = p["subscores"]
            w.writerow([p["rank"], p["id"], ";".join(map(str, p["episodes"])), seg_str(p["segments"]),
                        p["duration_s"], p["hook"], p["cliffhanger"], p["why"], p["trope"], p["score"],
                        s.get("hook"), s.get("cliffhanger"), s.get("standalone"), s.get("emotion"),
                        s.get("spoiler"), p["confidence"], " | ".join(p["warnings"])])

    (out / "report.md").write_text(render_markdown(result), encoding="utf-8")


def render_markdown(result: dict) -> str:
    st, us, show = result["stats"], result["usage"], result["show"]
    by_id = {p["id"]: p for p in result["ranked"]}
    L = [f"# Promo Finder report",
         f"{show['episodes']} episodes, {show['minutes']} min of script. Premise: {show['premise']}", "",
         f"Models: {', '.join(f'{k}={v}' for k, v in result['models'].items())}",
         f"Proposed {st.get('proposed', 0)} | failed rules first try {st.get('failed_rules_first_try', 0)} | "
         f"repaired {st.get('repaired_ok', 0)} | valid promos judged {len(result['all'])} | ranked {len(result['ranked'])}",
         f"Model calls {us['calls']} | tokens in {us['prompt_tokens']:,} / out {us['output_tokens']:,} | "
         f"est. cost at paid rates ${us['cost_usd_this_run']:.3f}", ""]
    plan = result.get("plan") or {}
    if plan.get("order"):
        L += ["## Post first (launch plan)", plan.get("strategy", ""), "",
              "| # | Promo | Clip | Why first |", "|---|---|---|---|"]
        for i, o in enumerate(plan["order"], 1):
            p = by_id.get(o["id"])
            if p:
                L.append(f"| {i} | {p['id']} {p['title']} | {seg_str(p['segments'])} ({p['duration_s']:.0f}s) | {o.get('reason', '')} |")
        L.append("")
    L += ["## Ranked promos", ""]
    for p in result["ranked"]:
        s = p["subscores"]
        L += [f"### #{p['rank']} {p['id']}: {p['title']}  (score {p['score']:.2f}, confidence {p['confidence']})",
              f"- Segments: {seg_str(p['segments'])}, {p['duration_s']:.1f}s total; hook line at +{p['hook_at_s']}s",
              f"- Hook: {p['hook']}",
              f"- Cliffhanger: {p['cliffhanger']}",
              f"- Why it works: {p['why']}",
              f"- Scores: hook {s['hook']} / cliffhanger {s['cliffhanger']} / standalone {s['standalone']} / "
              f"emotion {s['emotion']} / spoiler {s['spoiler']}",
              f"- Cold viewer: \"{(p.get('cold_viewer') or {}).get('what_happened', '')}\" "
              f"Open question: \"{(p.get('cold_viewer') or {}).get('open_question', '')}\""
              + (f" Confused by: {(p.get('cold_viewer') or {}).get('confused_by')}" if (p.get('cold_viewer') or {}).get('confused_by') else ""),
              f"- Risk: {p.get('weakness', '')}" + (f" | Warnings: {'; '.join(p['warnings'])}" if p["warnings"] else ""),
              ""]
    return "\n".join(L)
