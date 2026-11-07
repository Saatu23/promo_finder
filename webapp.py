"""Promo Finder - web app (Flask).

Run locally:   python webapp.py            then open http://localhost:5000
Production:    gunicorn webapp:app --workers 1 --threads 8 --timeout 120

One worker on purpose: live runs happen in a background thread and their progress is kept in memory.
"""
from __future__ import annotations

import csv
import io
import json
import os
import tempfile
import threading
import time
import uuid
from pathlib import Path

from flask import Flask, Response, abort, jsonify, redirect, render_template, request, url_for

from promofinder.config import load_config
from promofinder.heuristic import make_mock
from promofinder.llm import LLM
from promofinder.parser import load_inputs
from promofinder.pipeline import Pipeline

ROOT = Path(__file__).resolve().parent
SAMPLE_DIR = ROOT / "data" / "i-married-a-broken-soldier"
SAMPLE_TITLE = "I Married a Broken Soldier"
SAVED_RUN = ROOT / "outputs" / "final"
RUNS_DIR = Path(os.environ.get("PROMO_RUNS_DIR", tempfile.gettempdir())) / "promo-finder-runs"

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024


def load_dotenv():
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8-sig", errors="ignore").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"'))


load_dotenv()

# ----------------------------------------------------------------------------- data
KIND_COLOURS = {
    "betrayal": "#B3123B", "danger": "#C2410C", "romance": "#BE2F7A", "humiliation": "#A16207",
    "protector": "#0F766E", "reveal": "#4338CA", "villain_scheme": "#7E22CE", "revenge": "#B91C1C",
    "rescue": "#15803D", "secret": "#1D4ED8", "jealousy": "#4D7C0F", "comeback": "#0E7490",
}
AGREE = {"high": "The two AI reviewers agree", "medium": "The two AI reviewers mostly agree",
         "low": "The two AI reviewers disagree, so check this one yourself"}
BARS = [("hook", "Stops the scroll"), ("cliffhanger", "Leaves you hanging"),
        ("standalone", "Makes sense on its own"), ("emotion", "Emotional punch")]
STEPS = {
    "bible": ("Read the whole show", "works out who is who, the premise and the big twists"),
    "propose": ("Suggest promos", "picks candidate moments, about 4 per episode"),
    "repair": ("Fix rule breaks", "sends rule-breaking promos back once with the exact problem"),
    "blind": ("Stranger test", "sees only the clip, like someone scrolling, and says what they understood"),
    "judge": ("Score promos", "rates the hook, the cliffhanger, whether it stands alone, and emotion"),
    "plan": ("Plan the launch", "chooses the first 10 to post and their order"),
}

# AI providers for live runs. All but Gemini use the OpenAI-compatible chat API; the model name is editable.
PROVIDERS = {
    "gemini": {"label": "Google Gemini", "base": "", "env": "GEMINI_API_KEY", "key_hint": "Free at aistudio.google.com",
               "models": [("", "Recommended: a suitable Gemini model for each step"),
                          ("gemini-3.5-flash", "Gemini 3.5 Flash"), ("gemini-3.5-flash-lite", "Gemini 3.5 Flash-Lite (cheaper)"),
                          ("gemini-3.1-flash-lite", "Gemini 3.1 Flash-Lite (cheapest)"),
                          ("gemini-3-flash-preview", "Gemini 3 Flash (preview)")]},
    "openai": {"label": "OpenAI (ChatGPT models)", "base": "https://api.openai.com/v1", "env": "OPENAI_API_KEY",
               "key_hint": "From platform.openai.com/api-keys",
               "models": [("gpt-5.4-mini", "GPT-5.4 mini (recommended: good and low cost)"), ("gpt-5.4", "GPT-5.4 (strongest)"),
                          ("gpt-5.4-nano", "GPT-5.4 nano (cheapest)"), ("gpt-5.2", "GPT-5.2"), ("gpt-5-mini", "GPT-5 mini"),
                          ("gpt-4.1-mini", "GPT-4.1 mini")]},
    "anthropic": {"label": "Anthropic (Claude)", "base": "https://api.anthropic.com/v1", "env": "ANTHROPIC_API_KEY",
                  "key_hint": "From platform.claude.com, under API keys",
                  "models": [("claude-sonnet-5-5", "Claude Sonnet 5.5 (recommended)"), ("claude-opus-5-5", "Claude Opus 5.5 (strongest)"),
                             ("claude-haiku-5-5", "Claude Haiku 5.5 (fastest, cheapest)")]},
    "github": {"label": "GitHub Models (for Copilot / GitHub users)", "base": "https://models.github.ai/inference",
               "env": "GITHUB_TOKEN",
               "key_hint": "A GitHub personal access token with the 'models: read' permission. Free requests are small, "
                           "so start with a few episodes",
               "models": [("openai/gpt-4.1", "OpenAI GPT-4.1 (recommended)"), ("openai/gpt-4.1-mini", "OpenAI GPT-4.1 mini")]},
    "openrouter": {"label": "OpenRouter (many models, one key)", "base": "https://openrouter.ai/api/v1",
                   "env": "OPENROUTER_API_KEY", "key_hint": "From openrouter.ai/keys",
                   "models": [("openai/gpt-5.4-mini", "OpenAI GPT-5.4 mini (recommended)"), ("openai/gpt-5.4", "OpenAI GPT-5.4")]},
    "groq": {"label": "Groq", "base": "https://api.groq.com/openai/v1", "env": "GROQ_API_KEY",
             "key_hint": "From console.groq.com/keys",
             "models": [("llama-3.3-70b-versatile", "Llama 3.3 70B (recommended)"), ("openai/gpt-oss-120b", "GPT-OSS 120B"),
                        ("llama-3.1-8b-instant", "Llama 3.1 8B (fastest)")]},
    "other": {"label": "Other (any OpenAI-compatible service)", "base": "", "env": "PROMO_API_KEY",
              "key_hint": "The key for that service", "models": []},
}
CUSTOM = "__custom__"   # dropdown value for "type another model name"

STATE = {"run_dir": SAVED_RUN, "title": SAMPLE_TITLE, "live": False}
JOBS: dict[str, dict] = {}
LOCK = threading.Lock()


def ts(s: str) -> str:
    """'02:10.80' -> '2:10.8'"""
    try:
        m, sec = s.split(":")
        return f"{int(m)}:{float(sec):04.1f}"
    except ValueError:
        return s


def mmss(sec: float) -> str:
    return f"{int(sec // 60)}:{int(round(sec % 60)):02d}"


def model_name(label: str) -> str:
    m = label.split(":", 1)[-1]
    return (m.replace("gemini-", "Gemini ").replace("-flash-lite", " Flash-Lite").replace("-flash-preview", " Flash (preview)")
             .replace("-flash", " Flash").replace("-pro", " Pro"))


def load_run(folder: Path) -> dict | None:
    try:
        r = {"ranked": json.loads((folder / "promos_ranked.json").read_text(encoding="utf-8")),
             "plan": json.loads((folder / "launch_plan.json").read_text(encoding="utf-8")),
             "all": json.loads((folder / "candidates_all.json").read_text(encoding="utf-8"))}
        r.update(json.loads((folder / "run_summary.json").read_text(encoding="utf-8")))
    except FileNotFoundError:
        return None
    by_id = {p["id"]: p for p in r["all"]}
    for p in r["ranked"]:
        by_id[p["id"]] = p
    r["by_id"] = by_id
    r["picks"] = [by_id[o["id"]] for o in r["plan"].get("order", []) if o["id"] in by_id]
    r["reasons"] = {o["id"]: o.get("reason", "") for o in r["plan"].get("order", [])}
    return r


def current() -> dict:
    r = load_run(STATE["run_dir"])
    if r is None:
        abort(Response("No results yet. Run: python run.py data/i-married-a-broken-soldier --out outputs/final", 503))
    return r


def decisions_path() -> Path:
    return STATE["run_dir"] / "decisions.json"


def decisions() -> dict:
    try:
        return json.loads(decisions_path().read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def view(p: dict, n: int | None = None) -> dict:
    """Everything a template needs about one promo, in plain words."""
    s = p.get("subscores", {})
    kind = p.get("trope", "")
    first = p["segments"][0]
    warnings = []
    if s.get("spoiler"):
        warnings.append("May give away a twist" if s["spoiler"] >= 2 else "Hints at a later twist")
    if s.get("resolved_judge") or s.get("resolved_cold_viewer"):
        warnings.append("The ending may answer its own question")
    if s.get("not_standalone"):
        warnings.append("People new to the show may not follow it")
    cv = p.get("cold_viewer") or {}
    q = cv.get("open_question", "")
    return {
        "id": p["id"], "n": n if n is not None else p.get("rank"), "title": p.get("title", "Untitled"),
        "kind": kind.replace("_", " "), "colour": KIND_COLOURS.get(kind, "#475569"),
        "length": mmss(p["duration_s"]), "seconds": round(p["duration_s"]),
        "where": f"Episode {first['episode']}, from {ts(first['start'])}",
        "cuts": [{"episode": g["episode"], "start": ts(g["start"]), "end": ts(g["end"]), "secs": round(g["duration_s"], 1)}
                 for g in p["segments"]],
        "hook": p.get("hook", ""), "cliff": p.get("cliffhanger", ""), "why": p.get("why", ""),
        "risk": p.get("weakness", ""), "agree": AGREE.get(p.get("confidence", ""), ""), "conf": p.get("confidence", ""),
        "warnings": warnings,
        "bars": [{"label": label, "value": float(s.get(k, 0) or 0)} for k, label in BARS],
        "wonder": q if q and q.lower() not in ("none", "n/a") else "",
        "tap": cv.get("would_tap"),
        "clip": [l for l in p.get("clip", []) if l["kind"] != "camera" or l["cliff"]],
        "rank": p.get("rank"), "status": p.get("status", "ranked"),
    }


@app.context_processor
def common():
    return {"run_title": STATE["title"], "live": STATE["live"]}


# --------------------------------------------------------------------------- pages
@app.get("/")
def home():
    r = current()
    dec = decisions()
    picks = [view(p, i) for i, p in enumerate(r["picks"], 1)]
    for v in picks:
        v["decision"] = dec.get(v["id"], {}).get("decision")
    early = sum(1 for p in r["picks"] if p["episode"] <= 10)
    return render_template("home.html", show=r["show"], picks=picks, early=early, total=len(r["ranked"]),
                           decided=sum(1 for v in picks if v["decision"]))


@app.get("/promo/<pid>")
def promo(pid):
    r = current()
    p = r["by_id"].get(pid) or abort(404)
    order = [x["id"] for x in r["picks"]] if pid in r["reasons"] else [x["id"] for x in r["ranked"]]
    n = order.index(pid) + 1 if pid in order else p.get("rank")
    i = order.index(pid) if pid in order else -1
    nav = {"prev": order[i - 1] if i > 0 else None, "next": order[i + 1] if 0 <= i < len(order) - 1 else None,
           "list": "Post these first" if pid in r["reasons"] else "All promos",
           "back": url_for("home") if pid in r["reasons"] else url_for("all_promos")}
    d = decisions().get(pid, {})
    return render_template("promo.html", p=view(p, n), reason=r["reasons"].get(pid, ""), nav=nav, decision=d)


@app.post("/promo/<pid>/decide")
def decide(pid):
    r = current()
    if pid not in r["by_id"]:
        abort(404)
    with LOCK:
        dec = decisions()
        choice = request.form.get("decision")
        if choice in ("approved", "rejected"):
            dec[pid] = {"decision": choice, "reason": request.form.get("reason", "").strip()[:300]}
        else:
            dec.pop(pid, None)
        decisions_path().write_text(json.dumps(dec, indent=2), encoding="utf-8")
    return redirect(url_for("promo", pid=pid) + "#decide")


@app.get("/all")
def all_promos():
    r = current()
    dec = decisions()
    kind = request.args.get("kind", "")
    rows = [view(p) for p in r["ranked"]]
    kinds = sorted({v["kind"] for v in rows if v["kind"]})
    if kind:
        rows = [v for v in rows if v["kind"] == kind]
    for v in rows:
        v["decision"] = dec.get(v["id"], {}).get("decision")
    left_out = [view(p) for p in sorted(r["all"], key=lambda x: -x["score"]) if p.get("status") != "ranked"]
    return render_template("all.html", rows=rows, kinds=kinds, kind=kind, left_out=left_out,
                           total=len(r["ranked"]), all_count=len(r["all"]))


@app.get("/how")
def how():
    r = current()
    stats, usage, show = r["stats"], r["usage"], r["show"]
    steps = []
    planned = r.get("models") or {}
    for key in ("bible", "propose", "repair", "blind", "judge", "plan"):
        b = usage.get("by_stage", {}).get(key)
        if not b:
            continue
        ms = b.get("models") or {m.strip(): None for m in b.get("model", "").split(",") if m.strip()}
        plan_m = planned.get("propose" if key == "repair" else key, "")
        used = [f"{model_name(m)}" + (f" ({c})" if c is not None and len(ms) > 1 else "")
                for m, c in sorted(ms.items(), key=lambda kv: -(kv[1] or 0))]
        note = ""
        if plan_m and plan_m not in ms:
            note = f"planned: {model_name(plan_m)}"
        elif len(ms) > 1:
            note = "switched model when a free daily limit ran out"
        name, what = STEPS.get(key, (key, ""))
        steps.append({"name": name, "what": what, "used": ", ".join(used), "note": note,
                      "calls": b["calls"], "cost": b["cost_usd"]})
    calls, cached = usage.get("calls", 0), usage.get("cached_calls", 0)
    prices = load_config().get("prices", {})
    fi, fo = prices.get("gemini-3.5-flash", (1.5, 9.0))
    bi, bo = prices.get("gemini-3.1-flash-lite", (0.25, 1.5))
    full = sum((b["prompt_tokens"] * (bi if k == "blind" else fi) + b["output_tokens"] * (bo if k == "blind" else fo)) / 1e6
               for k, b in usage.get("by_stage", {}).items())
    rf = sorted(stats.get("rule_failures", {}).items(), key=lambda kv: -kv[1])
    return render_template("how.html", show=show, stats=stats, steps=steps, calls=calls, cached=cached,
                           cost=usage.get("cost_usd_this_run", 0), full=full, rule_failures=rf,
                           fresh=stats.get("fresh_run_seconds"), secs=stats.get("seconds", 0))


@app.get("/download/<what>")
def download(what):
    r = current()
    if what == "promos.csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["rank", "title", "segments", "seconds", "opens on", "cuts on", "why it works", "agreement"])
        for p in r["ranked"]:
            v = view(p)
            w.writerow([v["rank"], v["title"], " + ".join(f"Ep {c['episode']} {c['start']}-{c['end']}" for c in v["cuts"]),
                        v["seconds"], v["hook"], v["cliff"], v["why"], p.get("confidence", "")])
        return Response(buf.getvalue(), mimetype="text/csv",
                        headers={"Content-Disposition": "attachment; filename=promos_ranked.csv"})
    if what == "promos.json":
        return Response(json.dumps(r["ranked"], indent=2), mimetype="application/json",
                        headers={"Content-Disposition": "attachment; filename=promos_ranked.json"})
    if what == "decisions.csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["id", "title", "decision", "reason"])
        for pid, d in decisions().items():
            w.writerow([pid, r["by_id"].get(pid, {}).get("title", ""), d.get("decision"), d.get("reason", "")])
        return Response(buf.getvalue(), mimetype="text/csv",
                        headers={"Content-Disposition": "attachment; filename=editor_decisions.csv"})
    abort(404)


# ----------------------------------------------------------------------- live runs
@app.get("/run")
def run_form():
    saved = {k: bool(os.environ.get(v["env"])) for k, v in PROVIDERS.items()}
    return render_template("run.html", providers=PROVIDERS, saved=saved, custom=CUSTOM, error=request.args.get("error"))


def _parse_range(text: str) -> set[int] | None:
    text = text.replace(" ", "")
    if not text:
        return None
    want: set[int] = set()
    for part in text.split(","):
        if "-" in part:
            a, b = part.split("-")
            want |= set(range(int(a), int(b) + 1))
        elif part:
            want.add(int(part))
    return want


@app.post("/run")
def run_start():
    which = request.form.get("which", "sample")
    demo = request.form.get("demo") == "on"
    try:
        want = _parse_range(request.form.get("episodes", ""))
    except ValueError:
        return redirect(url_for("run_form", error="Write episodes like 1-10 or 3,5,9."))
    if which == "own":
        files = [(f.filename, f.read()) for f in request.files.getlist("files") if f and f.filename]
        if not files:
            return redirect(url_for("run_form", error="Add at least one screenplay (.txt) or a .zip of episodes."))
        episodes = load_inputs(files=files)
        title = "Your show"
    else:
        episodes = load_inputs(SAMPLE_DIR)
        title = SAMPLE_TITLE
    if want:
        episodes = [e for e in episodes if e.number in want]
    if not episodes:
        return redirect(url_for("run_form", error="No episodes found. Check the files or the episode range."))
    prov = request.form.get("provider", "gemini")
    if prov not in PROVIDERS:
        prov = "gemini"
    P = PROVIDERS[prov]
    choice = request.form.get("model_choice", "")
    if choice == CUSTOM or not P["models"]:
        model = request.form.get("model", "").strip()
    elif choice in {m for m, _ in P["models"]}:
        model = choice
    else:
        model = P["models"][0][0]
    base = (request.form.get("base_url", "").strip() if prov == "other" else P["base"]).rstrip("/")
    key = request.form.get("key", "").strip() or os.environ.get(P["env"], "")
    if not demo:
        if not key:
            return redirect(url_for("run_form", error=f"Paste your {P['label']} key, or tick 'Try without a key'."))
        if prov == "other" and not base.startswith("http"):
            return redirect(url_for("run_form", error="For 'Other', enter the service's address (it usually ends in /v1)."))
        if prov != "gemini" and not model:
            return redirect(url_for("run_form", error="Choose a model, or type its name."))
    ai = {"provider": prov, "model": model, "base": base, "key": key, "label": P["label"]}

    job = uuid.uuid4().hex[:10]
    out = RUNS_DIR / job
    out.mkdir(parents=True, exist_ok=True)
    who = "a quick demo (no AI)" if demo else f"{P['label']}" + (f", {model}" if model else "")
    JOBS[job] = {"status": "running", "stage": "Starting", "done": 0, "total": 1, "pct": 0, "title": title,
                 "episodes": len(episodes), "started": time.time(), "error": "", "out": str(out), "who": who}
    threading.Thread(target=_work, args=(job, episodes, out, demo, ai, title), daemon=True).start()
    return redirect(url_for("job_page", job=job))


STAGE_NAMES = {"bible": "Reading the whole show", "propose": "Suggesting promos", "blind": "Running the stranger test",
               "judge": "Scoring promos", "plan": "Planning the launch"}
STAGE_SPAN = {"bible": (0, 5), "propose": (5, 45), "blind": (45, 75), "judge": (75, 95), "plan": (95, 100)}


def _work(job, episodes, out, demo, ai, title):
    J = JOBS[job]
    try:
        if demo:
            cfg = load_config(provider="mock")
        elif ai["provider"] == "gemini":
            os.environ["GEMINI_API_KEY"] = ai["key"]
            cfg = load_config(provider="gemini", model=ai["model"] or None)
        else:
            os.environ["PROMO_APP_KEY"] = ai["key"]      # same model for every step on other providers
            cfg = load_config(provider="openai", model=ai["model"], base_url=ai["base"], api_key_env="PROMO_APP_KEY")
        llm = LLM(cache_dir=ROOT / ".cache" / "llm", log_path=out / "llm_calls.jsonl", mock_fn=make_mock(episodes),
                  prices=cfg.get("prices"))

        def progress(stage, done, total):
            a, b = STAGE_SPAN.get(stage, (0, 100))
            J.update(stage=STAGE_NAMES.get(stage, stage), done=done, total=total,
                     pct=round(a + (b - a) * done / max(1, total)))

        Pipeline(cfg, llm, log=lambda m: None, progress=progress).run(episodes, out)
        J.update(status="done", pct=100, stage="Done", minutes=round((time.time() - J["started"]) / 60, 1))
    except Exception as e:  # noqa: BLE001
        J.update(status="error", error=str(e)[:400])


@app.get("/run/<job>")
def job_page(job):
    J = JOBS.get(job) or abort(404)
    return render_template("job.html", job=job, J=J)


@app.get("/api/run/<job>")
def job_status(job):
    J = JOBS.get(job) or abort(404)
    return jsonify({k: J[k] for k in ("status", "stage", "done", "total", "pct", "error")})


@app.post("/run/<job>/open")
def job_open(job):
    J = JOBS.get(job) or abort(404)
    if J["status"] != "done":
        return redirect(url_for("job_page", job=job))
    STATE.update(run_dir=Path(J["out"]), title=J["title"], live=True)
    return redirect(url_for("home"))


@app.post("/saved")
def back_to_saved():
    STATE.update(run_dir=SAVED_RUN, title=SAMPLE_TITLE, live=False)
    return redirect(url_for("home"))


@app.template_filter("money")
def money(x):
    return f"${x:,.2f}"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False, threaded=True)
