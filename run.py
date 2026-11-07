#!/usr/bin/env python3
"""Find promos in microdrama screenplays.

  python run.py data/i-married-a-broken-soldier          # folder of .txt episodes
  python run.py my_show.zip --out outputs/my_show         # a zip works too
  python run.py data/... --provider mock                  # offline dry run, no key needed
  python run.py data/... --provider openai --model gpt-4.1 --base-url https://api.openai.com/v1 --api-key-env OPENAI_API_KEY
  python run.py --list-models                             # which Gemini models your key can use
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from promofinder.config import load_config  # noqa: E402
from promofinder.heuristic import make_mock  # noqa: E402
from promofinder.llm import LLM  # noqa: E402
from promofinder.parser import load_inputs  # noqa: E402
from promofinder.pipeline import Pipeline  # noqa: E402


def load_dotenv():
    env = ROOT / ".env"
    if env.exists():
        raw = env.read_bytes()
        # PowerShell's `echo x > .env` writes UTF-16; accept that too
        text = raw.decode("utf-16") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else raw.decode("utf-8-sig")
        for line in text.splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"'))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", nargs="?", help="folder, .zip or .txt of episode screenplays")
    ap.add_argument("--out", help="output folder (default outputs/<input-name>-<time>)")
    ap.add_argument("--config", help="config.toml path")
    ap.add_argument("--provider", help="gemini | openai | mock (overrides config for every stage)")
    ap.add_argument("--model", help="model name for every stage")
    ap.add_argument("--base-url", help="OpenAI-compatible base URL")
    ap.add_argument("--api-key-env", help="name of the env var holding the API key")
    ap.add_argument("--episodes", help="subset, e.g. 1-10 or 3,5,9")
    ap.add_argument("--list-models", action="store_true")
    ap.add_argument("--check", action="store_true", help="send one tiny request per configured model and report")
    a = ap.parse_args()
    load_dotenv()

    if a.list_models:
        import requests
        key = os.environ.get("GEMINI_API_KEY", "")
        r = requests.get("https://generativelanguage.googleapis.com/v1beta/models?pageSize=200",
                         headers={"x-goog-api-key": key}, timeout=30)
        r.raise_for_status()
        for m in r.json().get("models", []):
            if "generateContent" in m.get("supportedGenerationMethods", []):
                print(m["name"].split("/", 1)[-1], "-", m.get("displayName", ""))
        return
    cfg = load_config(a.config, a.provider, a.model, a.base_url, a.api_key_env)
    if a.check:
        import tempfile
        llm = LLM(cache_dir=Path(tempfile.mkdtemp()), prices=cfg.get("prices"))
        for st in ("propose", "blind"):
            spec = cfg["specs"][st]
            t = time.time()
            try:
                out = llm.text(spec, "Reply with JSON only.", 'Reply exactly {"ok": true}', "check")
                used = llm.records[-1].model if llm.records else spec.label
                print(f"OK   {st:8s} {used:35s} {time.time() - t:5.1f}s  reply={out.strip()[:40]}"
                      + (f"  (fallback for {spec.label})" if used != spec.label else ""))
            except Exception as e:  # noqa: BLE001
                print(f"FAIL {st:8s} {spec.label:35s} {time.time() - t:5.1f}s  {str(e)[:300]}")
        if llm.fallbacks_used:
            print("fallbacks:", llm.fallbacks_used)
        return
    if not a.input:
        ap.error("input is required")

    episodes = load_inputs(a.input)
    if a.episodes:
        want = set()
        for part in a.episodes.split(","):
            if "-" in part:
                x, y = part.split("-")
                want |= set(range(int(x), int(y) + 1))
            else:
                want.add(int(part))
        episodes = [e for e in episodes if e.number in want]
    if not episodes:
        sys.exit("no episodes found")
    name = Path(a.input).stem.replace(" ", "_")
    out = Path(a.out) if a.out else ROOT / "outputs" / f"{name}-{time.strftime('%Y%m%d-%H%M%S')}"
    llm = LLM(cache_dir=ROOT / ".cache" / "llm", log_path=out / "llm_calls.jsonl", mock_fn=make_mock(episodes), prices=cfg.get("prices"))
    print(f"models: {', '.join(f'{k}={v.label}' for k, v in cfg['specs'].items())}")
    Pipeline(cfg, llm).run(episodes, out)


if __name__ == "__main__":
    main()
