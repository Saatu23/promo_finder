from __future__ import annotations

import ast
import os
import re
from copy import deepcopy
from dataclasses import fields
from pathlib import Path

from .llm import ModelSpec

try:  # Python 3.11+
    import tomllib as _toml
except ImportError:  # older Python: use tomli if installed, else the small parser below
    try:
        import tomli as _toml  # type: ignore
    except ImportError:
        _toml = None

STAGES = ("bible", "propose", "blind", "judge", "plan")


def _mini_toml(text: str) -> dict:
    """Enough TOML for config.toml (tables, quoted keys, strings, numbers, booleans, flat arrays)."""
    root: dict = {}
    cur = root
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        # strip a trailing comment that is outside quotes
        out, q = [], None
        for ch in line:
            if ch in "\"'" and q in (None, ch):
                q = None if q == ch else ch
            if ch == "#" and q is None:
                break
            out.append(ch)
        line = "".join(out).strip()
        m = re.fullmatch(r"\[([^\]]+)\]", line)
        if m:
            cur = root
            for part in m.group(1).split("."):
                cur = cur.setdefault(part.strip().strip('"'), {})
            continue
        k, v = line.split("=", 1)
        v = v.strip().replace("true", "True").replace("false", "False")
        cur[k.strip().strip('"')] = ast.literal_eval(v)
    return root


def _parse_toml(text: str) -> dict:
    return _toml.loads(text) if _toml else _mini_toml(text)
DEFAULT_PATH = Path(__file__).resolve().parent.parent / "config.toml"


def load_config(path: str | Path | None = None, provider: str | None = None, model: str | None = None,
                base_url: str | None = None, api_key_env: str | None = None) -> dict:
    """Load config.toml. CLI/env overrides apply one provider/model to every stage,
    which is the 'plug in a stronger model' switch:
        PROMO_PROVIDER=openai PROMO_MODEL=gpt-x PROMO_BASE_URL=https://.../v1 PROMO_API_KEY_ENV=MY_KEY
    """
    p = Path(path) if path else DEFAULT_PATH
    cfg = _parse_toml(p.read_text(encoding="utf-8"))
    provider = provider or os.environ.get("PROMO_PROVIDER")
    model = model or os.environ.get("PROMO_MODEL")
    base_url = base_url or os.environ.get("PROMO_BASE_URL")
    api_key_env = api_key_env or os.environ.get("PROMO_API_KEY_ENV")
    default = cfg["models"]["default"]
    specs: dict[str, ModelSpec] = {}
    allowed = {f.name for f in fields(ModelSpec)}
    for st in STAGES:
        d = deepcopy(default)
        d.update(cfg["models"].get(st, {}))
        if provider:
            d["provider"] = provider
            if provider != default.get("provider"):
                # stage-specific gemini model names don't apply to another provider
                d["model"] = model or d["model"]
                d.pop("thinking_budget", None)
        if model:
            d["model"] = model
        if base_url:
            d["base_url"] = base_url
        if api_key_env:
            d["api_key_env"] = api_key_env
        price = cfg.get("prices", {}).get(d["model"])
        if price and "price_in" not in cfg["models"].get(st, {}):
            d["price_in"], d["price_out"] = price
        if provider and provider != default.get("provider"):
            d["fallback"] = []
        specs[st] = ModelSpec(**{k: v for k, v in d.items() if k in allowed})
    cfg["specs"] = specs
    return cfg
