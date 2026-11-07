"""Promo Finder - Streamlit app.  Run: streamlit run app.py"""
from __future__ import annotations

import csv
import html
import io
import json
import os
import sys
import tempfile
import time
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from promofinder.config import load_config  # noqa: E402
from promofinder.heuristic import make_mock  # noqa: E402
from promofinder.llm import LLM  # noqa: E402
from promofinder.parser import load_inputs  # noqa: E402
from promofinder.pipeline import Pipeline  # noqa: E402

SAMPLE_DIR = ROOT / "data" / "i-married-a-broken-soldier"
SAMPLE_TITLE = "I Married a Broken Soldier"
PRECOMPUTED = ROOT / "outputs" / "final"

st.set_page_config(page_title="Promo Finder", page_icon="🎬", layout="wide")

# --------------------------------------------------------------------------- look
# A restrained editorial look: familiar system type, clear reading sizes, and a single serif display face.
st.markdown("""
<style>
.stApp, .stApp button, .stApp input, .stApp textarea {
    font-family: "Segoe UI", "Helvetica Neue", Arial, sans-serif;
    font-size: 15px;
}
[data-testid="stIconMaterial"] { font-family: 'Material Symbols Rounded' !important; }
.block-container { padding-top: 1.4rem; max-width: 1280px; }
[data-testid="stHeader"] { background: transparent; }

/* side panel */
[data-testid="stSidebar"] { background: #E9E1D2; border-right: none; }
[data-testid="stSidebarUserContent"] { padding-top: .5rem !important; }
.side-title { font-family: Georgia, "Times New Roman", serif; font-size: 1.2rem; color: #1F2747; margin: .2rem 0 .2rem; }
.side-sub { color: #514B40; font-size: .9rem; margin: 0 0 .9rem; line-height: 1.5; }
[data-testid="stSidebar"] [data-testid="stVerticalBlock"] [data-testid="stVerticalBlock"] { background: #FFFFFF; border-color: #FFFFFF !important; border-radius: 12px; }
[data-testid="stSidebar"] .stButton button { background: #1F2747; color: #FFFFFF; border: none; border-radius: 10px; font-weight: 600; }
[data-testid="stSidebar"] .stButton button:hover { background: #2C3866; color: #FFFFFF; }
.side-note { color: #514B40; font-size: .85rem; line-height: 1.5; margin-top: .5rem; }

/* top bar */
.topbar { display: flex; align-items: baseline; gap: .65rem; padding-bottom: .8rem; border-bottom: 1px solid #DEDDD7; margin-bottom: 1.5rem; }
.brand { font-size: 1.3rem; font-weight: 650; letter-spacing: -.025em; color: #1F2747; }
.tagline { color: #626775; font-size: .9rem; }

.show-title, .stMarkdown .show-title, h1.show-title { font-family: Georgia, "Times New Roman", serif !important; font-weight: 700 !important; font-size: 1.9rem !important; letter-spacing: -.025em; padding: 0 !important; line-height: 1.25; color: #1F2747; margin: 0; }
.show-premise { color: #3B4152; font-size: 1rem; line-height: 1.55; max-width: 66ch; margin: .55rem 0 0; }
.show-facts { display: flex; flex-wrap: wrap; gap: .45rem; margin: .9rem 0 .2rem; }
.fact { background: #FFFFFF; border: 1px solid #E2E1DA; color: #3B4152; border-radius: 7px; padding: .25rem .65rem; font-size: .85rem; }
.fact b { color: #1F2747; }
.source { color: #6A7080; font-size: .85rem; margin-top: .5rem; }

.stTabs [role="tablist"] { gap: .4rem; border-bottom: none !important; margin-top: 1.1rem; }
.stTabs [role="tab"] { background: #FFFFFF !important; border: 1px solid #DCDBD3 !important; border-radius: 7px !important;
           padding: .35rem .85rem !important; height: auto !important; margin: 0 !important; }
.stTabs [role="tab"] p { font-size: .9rem !important; font-weight: 600; color: #1F2747; }
.stTabs [role="tab"][aria-selected="true"] { background: #1F2747 !important; border-color: #1F2747 !important; }
.stTabs [role="tab"][aria-selected="true"] p { color: #FFFFFF !important; }
.stTabs [data-baseweb="tab-highlight"], .stTabs [data-baseweb="tab-border"] { display: none !important; }

.lead { color: #3B4152; font-size: 1rem; line-height: 1.6; max-width: 70ch; margin: .3rem 0 1rem; }
.muted { color: #6A7080; font-size: .9rem; }
.warnline { color: #8A5A0B; font-size: .9rem; }

/* promo card */
.pc { background: #FFFFFF; border: 1px solid #E2E1DA; border-radius: 10px; padding: .9rem 1rem 1rem; min-height: 16rem;
      display: flex; flex-direction: column; box-shadow: inset 0 3px 0 var(--g1); padding-top: 1rem; }
.pc-top { display: flex; align-items: center; gap: .5rem; }
.pc-rank { font-weight: 700; color: #1F2747; font-size: .95rem; }
.pc-kind { font-size: .78rem; color: var(--g1); background: color-mix(in srgb, var(--g1) 10%, white); border-radius: 5px; padding: .05rem .45rem; }
.pc-len { margin-left: auto; font-size: .84rem; color: #555B6B; }
.pc-title { font-family: Georgia, "Times New Roman", serif; font-weight: 700; font-size: 1.08rem; color: #1F2747; margin-top: .55rem; line-height: 1.35; }
.pc-meta { font-size: .84rem; color: #6A7080; margin-top: .15rem; }
.pc-hook { font-size: .95rem; color: #1F2433; line-height: 1.5; margin-top: .6rem;
           display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }
.pc-cliff { font-size: .9rem; color: #3B4152; line-height: 1.5; margin-top: auto; padding-top: .6rem;
            display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.pc-hook b, .pc-cliff b { color: #1F2747; font-weight: 700; }
.pc-mark { font-size: .78rem; font-weight: 700; border-radius: 5px; padding: .05rem .45rem; }
.pc-mark.ok { background: #DDF1E2; color: #1C6234; } .pc-mark.no { background: #F9DDE0; color: #92202F; }
[data-testid="stMain"] .stButton button { border-radius: 7px; border: 1px solid #1F2747; background: #FFFFFF;
           color: #1F2747; font-weight: 600; margin-top: .35rem; }
[data-testid="stMain"] .stButton button:hover { background: #1F2747; color: #FFFFFF; }

/* pop-up */
div[role="dialog"] { background: #FFFFFF !important; }
[data-testid="stDialog"] h2, div[role="dialog"] h2 { font-family: Georgia, "Times New Roman", serif !important; color: #1F2747 !important; font-size: 1.3rem !important; }
.dl-meta { color: #555B6B; font-size: .9rem; margin: -.6rem 0 .8rem; }
.dl-pair { display: grid; grid-template-columns: 1fr 1fr; gap: .8rem; margin: .4rem 0 1rem; }
.dl-box { border-radius: 12px; padding: .75rem .95rem; }
.dl-box.open { background: #EEF6EA; border: 1px solid #CFE6C4; }
.dl-box.end { background: #FBEEEE; border: 1px solid #F0CDD1; }
.dl-k { font-size: .85rem; font-weight: 700; margin-bottom: .2rem; }
.dl-box.open .dl-k { color: #2F6B21; } .dl-box.end .dl-k { color: #9A2232; }
.dl-big { font-size: 1rem; line-height: 1.55; color: #1F2433; }
.dl-why { color: #1F2433; font-size: 1rem; line-height: 1.6; margin: 0; }
.dl-risk { color: #8A5A0B; font-size: .92rem; margin: .45rem 0 0; }
.dl-cut { display: inline-block; background: #F1F1EE; border-radius: 6px; padding: .3rem .7rem; font-size: .9rem; color: #1F2433; margin-top: .7rem; }
.dl-wonder { color: #3B4152; font-size: .95rem; line-height: 1.5; margin: .8rem 0 .5rem; }
.pf-bar { display: grid; grid-template-columns: 8.5rem 1fr 1.8rem; align-items: center; gap: .55rem; margin: .35rem 0; font-size: .9rem; color: #3B4152; }
.pf-track { height: 7px; background: #E7E6E0; border-radius: 4px; overflow: hidden; }
.pf-fill { height: 100%; background: #2E7D4A; border-radius: 4px; }
.pf-k3 { color: #6A7080; font-size: .85rem; margin-bottom: .2rem; }
.tag { display: inline-block; font-size: .82rem; padding: .08rem .5rem; border-radius: 5px; margin: 0 .3rem .3rem 0; background: #F1F1EE; color: #3B4152; }
.tag.good { background: #DDF1E2; color: #1C6234; } .tag.mid { background: #FBEFD6; color: #7A5408; } .tag.warn { background: #F9DDE0; color: #92202F; }

/* script */
.pf-script { background: #FFFFFF; border: 1px solid #E2E1DA; border-radius: 12px; padding: .9rem 1.1rem .6rem; margin-top: .5rem; }
.pf-line { display: grid; grid-template-columns: 3rem 1fr; gap: .7rem; padding: .25rem 0; }
.pf-t { color: #8A909C; font-size: .76rem; padding-top: .15rem; border-right: 3px solid transparent; font-variant-numeric: tabular-nums; }
.pf-line.first3 .pf-t { border-right-color: #7CBF5E; color: #2F6B21; }
.pf-who { font-weight: 700; font-size: .86rem; color: #1F2747; }
.pf-say { padding-left: 1rem; font-size: .96rem; line-height: 1.5; color: #1F2433; }
.pf-act { font-size: .95rem; line-height: 1.5; color: #3B4152; }
.pf-cam { color: #6A7080; font-style: italic; font-size: .9rem; }
.pf-hook { background: #DCF2C4; border-radius: 3px; padding: 0 .15rem; }
.pf-cliff { text-decoration: underline wavy #C62B3B; text-underline-offset: 4px; text-decoration-thickness: 1.5px; }
.pf-cut { border-top: 2px dashed #C62B3B; margin: .5rem 0 .1rem; padding-top: .2rem; color: #C62B3B; font-size: .85rem; text-align: right; }
.pf-jump { color: #1F2747; font-size: .88rem; margin: .4rem 0; border-top: 1px dotted #C9CDD5; padding-top: .3rem; }

/* how it was made */
.pf-table { width: 100%; border-collapse: collapse; font-size: .95rem; background: #FFFFFF; border-radius: 10px; overflow: hidden; border: 1px solid #E2E1DA; }
.pf-table th { text-align: left; color: #6A7080; font-weight: 600; padding: .5rem .8rem; border-bottom: 1px solid #E2E1DA; background: #FAFAF8; }
.pf-table td { padding: .5rem .8rem; border-bottom: 1px solid #EEEDE8; vertical-align: top; color: #1F2433; }
.pf-table tr:last-child td { border-bottom: none; }
h4 { font-family: Georgia, "Times New Roman", serif !important; color: #1F2747 !important; font-size: 1.12rem !important; }
.pf-note { color: #1F2433; font-size: .98rem; line-height: 1.65; max-width: 78ch; }
@media (max-width: 760px) { .dl-pair { grid-template-columns: 1fr; } .show-title { font-size: 1.6rem; } }
</style>""", unsafe_allow_html=True)

TROPE_COLORS = {   # one accent colour per kind of story (card top edge and tag)
    "betrayal": ("#B3123B", ""), "danger": ("#C2410C", ""), "romance": ("#BE2F7A", ""),
    "humiliation": ("#A16207", ""), "protector": ("#0F766E", ""), "reveal": ("#4338CA", ""),
    "villain_scheme": ("#7E22CE", ""), "revenge": ("#B91C1C", ""), "rescue": ("#15803D", ""),
    "secret": ("#1D4ED8", ""), "jealousy": ("#4D7C0F", ""), "comeback": ("#0E7490", ""),
}
DEFAULT_COLORS = ("#475569", "")

STEP_INFO = {
    "bible": ("Read the whole show", "Works out who is who, the premise and the big twists"),
    "propose": ("Suggest promos", "Picks candidate moments, 4 per episode"),
    "repair": ("Fix rule breaks", "Sends rule-breaking promos back once with the exact problem"),
    "blind": ("Stranger test", "Sees only the clip, like someone scrolling, and says what they understood"),
    "judge": ("Score promos", "Rates hook, cliffhanger, stands-alone and emotion"),
    "plan": ("Plan the launch", "Chooses the first 10 to post and their order"),
}
BARS = [("hook", "Stops the scroll"), ("cliffhanger", "Leaves you hanging"),
        ("standalone", "Makes sense alone"), ("emotion", "Emotional punch")]
CONF = {"high": ("good", "Reviewers agree"), "medium": ("mid", "Reviewers mostly agree"),
        "low": ("warn", "Reviewers disagree")}


def load_dotenv():
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8-sig", errors="ignore").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"'))


load_dotenv()


def load_precomputed(folder: Path) -> dict | None:
    try:
        r = {"ranked": json.loads((folder / "promos_ranked.json").read_text(encoding="utf-8")),
             "plan": json.loads((folder / "launch_plan.json").read_text(encoding="utf-8")),
             "all": json.loads((folder / "candidates_all.json").read_text(encoding="utf-8"))}
        r.update(json.loads((folder / "run_summary.json").read_text(encoding="utf-8")))
        return r
    except FileNotFoundError:
        return None


def secret(name: str) -> str:
    try:
        v = st.secrets.get(name, "")  # type: ignore[attr-defined]
        if v:
            return v
    except Exception:  # noqa: BLE001
        pass
    return os.environ.get(name, "")


def esc(x) -> str:
    return html.escape(str(x or ""))


def ts(s: str) -> str:
    """'02:10.80' -> '2:10.8'"""
    try:
        m, sec = s.split(":")
        return f"{int(m)}:{float(sec):04.1f}"
    except ValueError:
        return s


def seg_text(p) -> str:
    return " + ".join(f"Ep {s['episode']}, {ts(s['start'])}–{ts(s['end'])}" for s in p["segments"])


def model_name(label: str) -> str:
    m = label.split(":", 1)[-1]
    return m.replace("gemini-", "Gemini ").replace("-flash-lite", " Flash-Lite").replace("-flash-preview", " Flash (preview)") \
            .replace("-flash", " Flash").replace("-pro", " Pro")


# ------------------------------------------------------------------------ sidebar
with st.sidebar:
    st.markdown("<div class='side-title'>Try another show</div>"
                "<p class='side-sub'>Pick the screenplays and press the button. The tool finds the promos for you.</p>",
                unsafe_allow_html=True)
    with st.container(border=True):
        src = st.radio("Which show?", ["The sample show", "My own screenplays"], index=0)
        uploads = None
        if src == "My own screenplays":
            uploads = st.file_uploader("Add episode files (.txt) or one .zip", type=["txt", "zip"],
                                       accept_multiple_files=True)
        ep_range = st.text_input("Which episodes?", "", placeholder="All of them, or e.g. 1-10")
    with st.container(border=True):
        demo = st.checkbox("Try without a key (rough demo picks)", value=False)
        prov = "mock" if demo else "gemini"
        key, model, base_url = "", "", ""
        if not demo:
            have = bool(secret("GEMINI_API_KEY"))
            key = st.text_input("Your Gemini key", type="password", value="",
                                placeholder="Saved key will be used" if have else "Paste it here",
                                help="Get a free key at aistudio.google.com. It's only used for this run.")
    go = st.button("Find promos", type="primary", width="stretch")
    st.markdown("<p class='side-note'>Takes about 5 minutes for 10 episodes, or 20 to 25 minutes for a whole show.</p>",
                unsafe_allow_html=True)

# ---------------------------------------------------------------------------- run
if go:
    if src == "My own screenplays":
        if not uploads:
            st.error("Add at least one screenplay (.txt) or a .zip of episodes, then press Find promos.")
            st.stop()
        episodes = load_inputs(files=[(u.name, u.getvalue()) for u in uploads])
        title = "Your show"
    else:
        episodes = load_inputs(SAMPLE_DIR)
        title = SAMPLE_TITLE
    if ep_range.strip():
        want = set()
        try:
            for part in ep_range.replace(" ", "").split(","):
                if "-" in part:
                    a, b = part.split("-")
                    want |= set(range(int(a), int(b) + 1))
                elif part:
                    want.add(int(part))
        except ValueError:
            st.error("Write episodes like 1-10 or 3,5,9.")
            st.stop()
        episodes = [e for e in episodes if e.number in want]
    if not episodes:
        st.error("No episodes found. Check the files, or the episode range.")
        st.stop()
    if prov == "gemini":
        k = key or secret("GEMINI_API_KEY")
        if not k:
            st.error("Paste a Gemini API key in the sidebar (free at aistudio.google.com), "
                     "or choose the offline demo.")
            st.stop()
        os.environ["GEMINI_API_KEY"] = k
    elif prov == "openai":
        os.environ["PROMO_APP_KEY"] = key
    cfg = load_config(provider=prov, model=model or None, base_url=base_url or None,
                      api_key_env="PROMO_APP_KEY" if prov == "openai" else None)
    out = Path(tempfile.mkdtemp(prefix="promos-"))
    llm = LLM(cache_dir=ROOT / ".cache" / "llm", log_path=out / "llm_calls.jsonl", mock_fn=make_mock(episodes),
              prices=cfg.get("prices"))
    names = {"bible": "Reading the whole show", "propose": "Suggesting promos", "blind": "Running the stranger test",
             "judge": "Scoring promos", "plan": "Planning the launch"}
    bar = st.progress(0.0, text="Starting")
    with st.expander("Progress log", expanded=False):
        log_box = st.empty()
    lines: list[str] = []
    stage_w = {"bible": (0.0, 0.05), "propose": (0.05, 0.45), "blind": (0.45, 0.75), "judge": (0.75, 0.95), "plan": (0.95, 1.0)}

    def progress(stage, done, total):
        a, b = stage_w.get(stage, (0, 1))
        bar.progress(min(1.0, a + (b - a) * done / max(1, total)), text=f"{names.get(stage, stage)}: {done} of {total}")

    def log(msg):
        lines.append(msg)
        log_box.code("\n".join(lines[-12:]))

    t0 = time.time()
    try:
        result = Pipeline(cfg, llm, log=log, progress=progress).run(episodes, out)
    except Exception as e:  # noqa: BLE001
        st.error(f"The run stopped: {e}")
        st.stop()
    bar.empty()
    st.session_state["result"] = result
    st.session_state["source"] = (f"Live run on {len(episodes)} episodes of {title}, finished in "
                                  f"{(time.time() - t0) / 60:.1f} min. Download the results below before closing this tab.")
    st.session_state["title"] = title

result = st.session_state.get("result")
if result is None:
    result = load_precomputed(PRECOMPUTED)
    st.session_state["source"] = ("Showing the saved results for all 50 episodes. To try another show, use the panel on the left.")
    st.session_state["title"] = SAMPLE_TITLE
if result is None:
    st.markdown("<div class='pf-title' role='heading' aria-level='1'>Promo Finder</div>", unsafe_allow_html=True)
    st.info("Choose a show in the sidebar and press **Find promos**. No key? Pick the offline demo.")
    st.stop()

ranked = result["ranked"]
show, stats, usage = result["show"], result["stats"], result["usage"]
title = st.session_state.get("title", SAMPLE_TITLE)

# ------------------------------------------------------------------------- header
n_plan = len((result.get("plan") or {}).get("order", []))
facts = [f"<b>{show['episodes']}</b> episodes", f"<b>{show['minutes']:.0f}</b> minutes",
         f"<b>{stats.get('proposed', 0)}</b> promo ideas checked", f"<b>{len(ranked)}</b> worth posting",
         f"<b>{n_plan}</b> to post first"]
st.markdown(
    "<div class='topbar'><span class='brand'>Promo Finder</span>"
    "<span class='tagline'>find the moments worth posting</span></div>"
    f"<h1 class='show-title'>{esc(title)}</h1>"
    + (f"<p class='show-premise'>{esc(show['premise'])}</p>" if show.get("premise") else "")
    + "<div class='show-facts'>" + "".join(f"<span class='fact'>{f}</span>" for f in facts) + "</div>"
    + f"<p class='source'>{esc(st.session_state.get('source', ''))}</p>", unsafe_allow_html=True)


# -------------------------------------------------------------------------- pieces
def script_page(p) -> str:
    out, last_ep = [], None
    for l in p.get("clip", []):
        if l["kind"] == "camera" and not l["cliff"]:
            continue
        if last_ep is not None and l["episode"] != last_ep:
            out.append(f"<div class='pf-jump'>Cut to episode {l['episode']}</div>")
        last_ep = l["episode"]
        cls = "pf-line first3" if l["first3"] else "pf-line"
        text = esc(l["text"])
        if l["hook"]:
            text = f"<span class='pf-hook'>{text}</span>"
        if l["cliff"]:
            text = f"<span class='pf-cliff'>{text}</span>"
        if l["kind"] == "dialogue":
            body = f"<div><div class='pf-who'>{esc(l['speaker'].title())}</div><div class='pf-say'>{text}</div></div>"
        elif l["kind"] == "camera":
            body = f"<div class='pf-cam'>{text}</div>"
        else:
            body = f"<div class='pf-act'>{text}</div>"
        out.append(f"<div class='{cls}'><div class='pf-t'>{l['t']:.1f}s</div>{body}</div>")
    out.append(f"<div class='pf-cut'>cut at {p['duration_s']:.1f}s</div>")
    return "<div class='pf-script'>" + "".join(out) + "</div>"


def score_bars(p) -> str:
    s = p["subscores"]
    rows = ["<div class='pf-k3'>Scores out of 10</div>"]
    for k, label in BARS:
        v = float(s.get(k, 0) or 0)
        rows.append(f"<div class='pf-bar'><span>{label}</span><div class='pf-track'>"
                    f"<div class='pf-fill' style='width:{max(3, min(100, v * 10)):.0f}%'></div></div><span>{v:.1f}</span></div>")
    return "".join(rows)


def tags(p) -> str:
    s = p["subscores"]
    kind, text = CONF.get(p["confidence"], ("", p["confidence"]))
    out = [f"<span class='tag {kind}'>{text}</span>"]
    if s.get("spoiler"):
        out.append(f"<span class='tag warn'>{'mild spoiler' if s['spoiler'] == 1 else 'spoiler'}</span>")
    if s.get("resolved_judge") or s.get("resolved_cold_viewer"):
        out.append("<span class='tag warn'>ending may answer itself</span>")
    if s.get("not_standalone"):
        out.append("<span class='tag warn'>strangers may not follow it</span>")
    return "".join(out)


def mmss(sec: float) -> str:
    return f"{int(sec // 60)}:{int(round(sec % 60)):02d}"


def poster(p, n: int) -> str:
    g1, g2 = TROPE_COLORS.get(p.get("trope", ""), DEFAULT_COLORS)
    d = st.session_state.get("decisions", {}).get(p["id"], ("",))[0]
    mark = {"approved": "<span class='pc-mark ok'>Approved</span>",
            "rejected": "<span class='pc-mark no'>Rejected</span>"}.get(d, "")
    s0 = p["segments"][0]
    where = f"Episode {s0['episode']}, from {ts(s0['start'])}" + (f" (+{len(p['segments']) - 1} more)" if len(p["segments"]) > 1 else "")
    kind = p.get("trope", "").replace("_", " ")
    return (f"<div class='pc' style='--g1:{g1}'>"
            f"<div class='pc-top'><span class='pc-rank'>{n}</span><span class='pc-kind'>{esc(kind)}</span>{mark}"
            f"<span class='pc-len'>{mmss(p['duration_s'])}</span></div>"
            f"<div class='pc-title'>{esc(p.get('title', ''))}</div><div class='pc-meta'>{where}</div>"
            f"<div class='pc-hook'><b>Opens on</b> {esc(p['hook'])}</div>"
            f"<div class='pc-cliff'><b>Cuts on</b> {esc(p['cliffhanger'])}</div></div>")


def _decide(pid: str, key: str):
    d = st.session_state.setdefault("decisions", {})
    v = st.session_state.get(key)
    if v == "Approve":
        d[pid] = ("approved", "")
    elif v == "Reject":
        d[pid] = ("rejected", d.get(pid, ("", ""))[1] if d.get(pid, ("",))[0] == "rejected" else "")
    else:
        d.pop(pid, None)


def open_promo(p, n: int):
    st.dialog(f"{n}. {p.get('title', 'Promo')}", width="large", on_dismiss="rerun")(_promo_body)(p)


def _promo_body(p):
    d = st.session_state.setdefault("decisions", {})
    st.markdown(f"<p class='dl-meta'>{esc(seg_text(p))}, {p['duration_s']:.0f} seconds</p>", unsafe_allow_html=True)
    st.markdown(f"<div>{tags(p)}</div><div class='dl-pair'>"
                f"<div class='dl-box open'><div class='dl-k'>Opens on</div><div class='dl-big'>{esc(p['hook'])}</div></div>"
                f"<div class='dl-box end'><div class='dl-k'>Cuts on</div><div class='dl-big'>{esc(p['cliffhanger'])}</div></div>"
                f"</div>", unsafe_allow_html=True)
    a, b = st.columns([1, 1], gap="large")
    with a:
        cut = " + ".join(f"Episode {s['episode']}, {ts(s['start'])} to {ts(s['end'])}" for s in p["segments"])
        st.markdown(f"<p class='dl-why'>{esc(p['why'])}</p>"
                    + (f"<p class='dl-risk'>Watch out: {esc(p['weakness'])}</p>" if p.get("weakness") else "")
                    + f"<div class='dl-cut'>Cut {cut} ({p['duration_s']:.1f}s)</div>", unsafe_allow_html=True)
        q = (p.get("cold_viewer") or {}).get("open_question", "")
        if q and q.lower() != "none":
            st.markdown(f"<p class='dl-wonder'>A first-time viewer was left wondering: <i>“{esc(q)}”</i></p>",
                        unsafe_allow_html=True)
    with b:
        st.markdown(score_bars(p), unsafe_allow_html=True)
        k = f"dec-{p['id']}"
        current = {"approved": "Approve", "rejected": "Reject"}.get(d.get(p["id"], ("",))[0])
        if st.session_state.get(k) != current:
            st.session_state[k] = current
        st.segmented_control("Your call", ["Approve", "Reject"], key=k, on_change=_decide, args=(p["id"], k))
        if d.get(p["id"], ("",))[0] == "rejected":
            rk_ = f"why-{p['id']}"
            if rk_ not in st.session_state:
                st.session_state[rk_] = d[p["id"]][1]
            reason = st.text_input("Why reject it?", key=rk_, label_visibility="collapsed",
                                   placeholder="Why reject it? (e.g. needs context, weak hook)")
            d[p["id"]] = ("rejected", reason)
    if st.toggle("Read the script", value=False, key=f"script-{p['id']}"):
        st.markdown(script_page(p), unsafe_allow_html=True)


def poster_grid(promos: list, numbers: list[int], where: str):
    per_row = 3
    for i in range(0, len(promos), per_row):
        cols = st.columns(per_row, gap="medium")
        for c, p, n in zip(cols, promos[i:i + per_row], numbers[i:i + per_row]):
            with c:
                st.markdown(poster(p, n), unsafe_allow_html=True)
                if st.button("View promo", key=f"view-{where}-{p['id']}", width="stretch"):
                    open_promo(p, n)


# --------------------------------------------------------------------------- tabs
tab_plan, tab_rank, tab_all, tab_how = st.tabs(["Post these first", "All ranked", "Every candidate", "How it was made"])

with tab_plan:
    plan = result.get("plan") or {}
    rk = {p["id"]: p for p in ranked}
    picks = [rk[o["id"]] for o in plan.get("order", []) if o["id"] in rk]
    if picks:
        early = sum(1 for p in picks if p["episode"] <= 10)
        kinds = sorted({p.get("trope", "").replace("_", " ") for p in picks if p.get("trope")})
        intro = f"Post these {len(picks)} in this order. "
        if early:
            intro += (f"{early} {'comes' if early == 1 else 'come'} from the first 10 episodes, so someone who taps "
                      f"through lands on a story they already recognise. ")
        if len(picks) - early:
            intro += "The rest are the strongest moments from later in the show, each checked for spoilers. "
        if len(kinds) > 1:
            intro += f"They cover {len(kinds)} kinds of story, so the first week shows which kind this audience stops for."
        st.markdown(f"<p class='lead'>{esc(intro)}</p>", unsafe_allow_html=True)
        poster_grid(picks, list(range(1, len(picks) + 1)), "plan")

with tab_rank:
    f1, f2 = st.columns(2)
    conf_opts = {"Reviewers agree": "high", "Mostly agree": "medium", "Disagree": "low"}
    conf = f1.multiselect("Show promos where", list(conf_opts), default=list(conf_opts))
    tropes = sorted({p.get("trope", "") for p in ranked})
    tsel = f2.multiselect("Kind of story", tropes, default=tropes, format_func=lambda t: t.replace("_", " "))
    want = {conf_opts[c] for c in conf}
    shown = [p for p in ranked if p["confidence"] in want and p.get("trope", "") in tsel]
    st.markdown(f"<p class='muted'>{len(shown)} of {len(ranked)} promos, best first.</p>", unsafe_allow_html=True)
    poster_grid(shown, [p["rank"] for p in shown], "rank")

with tab_all:
    st.markdown("<p class='lead'>Every promo that passed the rule checks, including the ones left out of the ranking "
                "and why.</p>", unsafe_allow_html=True)
    status_txt = {"ranked": "Ranked", "duplicate": "Left out: overlaps a better promo",
                  "unranked": "Left out: scored below the top 40"}
    order = sorted(result["all"], key=lambda x: (x["rank"] is None, x["rank"] or 0, -x["score"]))
    rows = [{"Rank": str(p["rank"]) if p["rank"] else "", "Promo": p.get("title", ""), "Where": seg_text(p),
             "Length (s)": round(p["duration_s"]), "Score": round(p["score"], 2),
             "Status": status_txt.get(p["status"], p["status"]) +
             (f" ({p['note'].replace('overlaps higher-ranked ', '')})" if p["status"] == "duplicate" else "")}
            for p in order]
    st.dataframe(rows, width="stretch", hide_index=True, height=560,
                 column_config={"Rank": st.column_config.TextColumn(width="small"),
                                "Length (s)": st.column_config.NumberColumn(width="small"),
                                "Score": st.column_config.NumberColumn(width="small"),
                                "Status": st.column_config.TextColumn(width="large")})

with tab_how:
    bys = usage.get("by_stage", {})
    cached = usage.get("cached_calls", 0)
    calls = usage.get("calls", 0)
    st.markdown(f"<p class='lead'>The tool read {show['episodes']} episodes ({show['minutes']:.0f} minutes of story) "
                f"and asked an AI model {calls} questions. The AI judges the drama; ordinary code turns its picks "
                f"into exact cut points and checks every rule.</p>", unsafe_allow_html=True)
    st.markdown("#### Who did each step")
    trs = []
    for stage in ("bible", "propose", "repair", "blind", "judge", "plan"):
        if stage not in bys:
            continue
        b = bys[stage]
        ms = b.get("models") or {m.strip(): None for m in b.get("model", "").split(",") if m.strip()}
        planned = (result.get("models") or {}).get("propose" if stage == "repair" else stage, "")
        used = ", ".join(f"{esc(model_name(m))}{f' ({n})' if n is not None and len(ms) > 1 else ''}"
                         for m, n in sorted(ms.items(), key=lambda kv: -(kv[1] or 0)))
        if planned and planned not in ms:
            used += f"<br><span class='warnline'>planned: {esc(model_name(planned))}</span>"
        elif len(ms) > 1:
            used += "<br><span class='warnline'>switched model when a daily free limit ran out</span>"
        name, what = STEP_INFO.get(stage, (stage, ""))
        trs.append(f"<tr><td><b>{name}</b><br><span class='muted'>{what}</span></td>"
                   f"<td>{used}</td><td>{b['calls']}</td><td>${b['cost_usd']:.2f}</td></tr>")
    st.markdown("<table class='pf-table'><tr><th>Step</th><th>AI model that answered (calls)</th><th>Calls</th>"
                "<th>Cost at paid prices</th></tr>" + "".join(trs) + "</table>", unsafe_allow_html=True)

    st.markdown("#### Rule checks")
    prop = stats.get("proposed", 0)
    fails = stats.get("failed_rules_first_try", 0)
    rf = stats.get("rule_failures", {})
    rf_txt = ", ".join(f"{k} ({v})" for k, v in sorted(rf.items(), key=lambda kv: -kv[1]))
    st.markdown(
        f"<p class='pf-note'>Of {prop} first suggestions, <b>{fails} ({fails / max(1, prop):.0%}) broke a rule</b>"
        f"{': ' + esc(rf_txt) if rf_txt else ''}. Each was sent back once with the exact problem; "
        f"<b>{stats.get('repaired_ok', 0)}</b> valid promos came back and "
        f"{stats.get('repair_still_invalid', 0)} could not be fixed. "
        f"{stats.get('near_duplicates_in_episode', 0)} near-identical clips were removed.</p>", unsafe_allow_html=True)

    st.markdown("#### Time and cost")
    secs = stats.get("seconds", 0)
    fresh = stats.get("fresh_run_seconds")
    if calls and cached == calls:
        took = "under a second" if secs < 1 else f"{secs:.0f} seconds"
        t_txt = (f"Every answer in this run was reused from an earlier run, so it took {took}. "
                 + (f"The first full run, with no saved answers, took <b>{fresh / 60:.0f} minutes</b> on a free key."
                    if fresh else "A fresh full run takes about 20-25 minutes on a free key."))
    else:
        t_txt = (f"This run took <b>{secs / 60:.1f} minutes</b> ({calls - cached} new AI calls"
                 f"{f', {cached} reused from earlier runs' if cached else ''}).")
    cost = usage.get("cost_usd_this_run", 0)
    prices = load_config().get("prices", {})
    pf_in, pf_out = prices.get("gemini-3.5-flash", (1.5, 9.0))
    pb_in, pb_out = prices.get("gemini-3.1-flash-lite", (0.25, 1.5))
    full = sum((b["prompt_tokens"] * (pb_in if s == "blind" else pf_in) + b["output_tokens"] * (pb_out if s == "blind" else pf_out)) / 1e6
               for s, b in bys.items())
    st.markdown(
        f"<p class='pf-note'>{t_txt}</p><p class='pf-note'>On a <b>free key it costs nothing</b>. At paid prices this run "
        f"would cost <b>${cost:.2f}</b> with the models that actually answered, or about <b>${full:.2f}</b> "
        f"(${full / max(1, show['episodes']):.2f} per episode) if every step ran on Gemini 3.5 Flash.</p>",
        unsafe_allow_html=True)
    with st.expander("Raw numbers (JSON)"):
        st.json({"models_planned": result.get("models"), "stats": stats, "usage": usage})

# ---------------------------------------------------------------------- downloads
st.markdown("<div style='height:2rem'></div>", unsafe_allow_html=True)
st.markdown("#### Take the results with you")
d1, d2, d3 = st.columns(3)
d1.download_button("Ranked promos (JSON)", json.dumps(ranked, indent=2), "promos_ranked.json", "application/json",
                   width="stretch")
buf = io.StringIO()
w = csv.writer(buf)
w.writerow(["rank", "id", "title", "segments", "duration_s", "hook", "cliffhanger", "why", "score", "confidence"])
for p in ranked:
    w.writerow([p["rank"], p["id"], p.get("title", ""), seg_text(p), p["duration_s"], p["hook"], p["cliffhanger"],
                p["why"], p["score"], p["confidence"]])
d2.download_button("Ranked promos (spreadsheet)", buf.getvalue(), "promos_ranked.csv", "text/csv", width="stretch")
dec = st.session_state.get("decisions", {})
dbuf = io.StringIO()
dw = csv.writer(dbuf)
dw.writerow(["id", "decision", "reason"])
for k, (v, r) in dec.items():
    dw.writerow([k, v, r])
d3.download_button(f"My approve/reject decisions ({len(dec)})", dbuf.getvalue(), "editor_decisions.csv", "text/csv",
                   width="stretch")
