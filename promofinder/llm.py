"""One place for every model call.

Swap models by editing config.toml (or env vars) - no code changes:
  provider = "gemini"  -> Google AI Studio REST API (free tier works)
  provider = "openai"  -> any OpenAI-compatible endpoint (OpenAI, Groq, OpenRouter,
                          vLLM, Together, Gemini's own OpenAI endpoint, an in-house gateway...)
  provider = "mock"    -> offline deterministic stand-in, for tests / no key

Every call is cached on disk (re-runs cost nothing), rate-limited per model,
retried with backoff on 429/5xx, and logged with token counts + estimated cost.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import requests


class LLMError(RuntimeError):
    pass


class QuotaExhausted(LLMError):
    """Daily quota for a model is used up: retrying today is pointless, switch model."""


class ModelUnavailable(QuotaExhausted):
    """Model retired/renamed (HTTP 404): switch to the fallback, same as an exhausted quota."""


@dataclass
class ModelSpec:
    provider: str
    model: str
    temperature: float = 0.2
    rpm: int = 10                      # requests/minute cap (free-tier friendly)
    price_in: float = 0.0              # USD per 1M input tokens (for cost estimates)
    price_out: float = 0.0             # USD per 1M output tokens (incl. thinking)
    base_url: str = ""                 # openai-compatible only
    api_key_env: str = ""
    thinking_budget: int | None = None # gemini 2.5+: None=model default, 0=off
    fallback: list[str] = field(default_factory=list)  # models to switch to if the daily quota runs out

    @property
    def label(self) -> str:
        return f"{self.provider}:{self.model}"


@dataclass
class CallRecord:
    stage: str
    model: str
    prompt_tokens: int
    output_tokens: int
    cost_usd: float
    seconds: float
    cached: bool
    cache_key: str


class _RateLimiter:
    def __init__(self):
        self._lock = threading.Lock()
        self._last: dict[str, list[float]] = {}

    def wait(self, key: str, rpm: int):
        if rpm <= 0:
            return
        while True:
            with self._lock:
                now = time.time()
                hist = [t for t in self._last.get(key, []) if now - t < 60]
                if len(hist) < rpm:
                    hist.append(now)
                    self._last[key] = hist
                    return
                sleep_for = 60 - (now - hist[0]) + 0.05
            time.sleep(max(sleep_for, 0.05))


_LIMITER = _RateLimiter()


def extract_json(text: str) -> Any:
    """Parse JSON from a model reply, tolerating ```json fences and stray prose."""
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass
    for open_, close in (("{", "}"), ("[", "]")):
        a, b = t.find(open_), t.rfind(close)
        if a != -1 and b > a:
            try:
                return json.loads(t[a:b + 1])
            except json.JSONDecodeError:
                continue
    raise LLMError(f"model did not return valid JSON: {text[:300]!r}")


class LLM:
    def __init__(self, cache_dir: str | Path = ".cache/llm", log_path: str | Path | None = None,
                 mock_fn: Callable[[str, str, str], str] | None = None, prices: dict | None = None,
                 log: Callable[[str], None] = print):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = Path(log_path) if log_path else None
        self.records: list[CallRecord] = []
        self.mock_fn = mock_fn
        self._lock = threading.Lock()
        self.prices = prices or {}
        self.log = log
        self.exhausted: set[str] = set()   # models whose daily quota ran out during this run
        self.fallbacks_used: list[str] = []

    # ------------------------------------------------------------------ public
    def json(self, spec: ModelSpec, system: str, prompt: str, stage: str,
             validate: Callable[[Any], Any] | None = None, retries: int = 2) -> Any:
        """Call the model, parse JSON, optionally validate; re-ask on bad output."""
        last_err = None
        attempt_prompt = prompt
        for attempt in range(retries + 1):
            text = self.text(spec, system, attempt_prompt, stage, salt=str(attempt) if attempt else "")
            try:
                data = extract_json(text)
                return validate(data) if validate else data
            except Exception as e:  # noqa: BLE001 - feed the error back to the model
                last_err = e
                attempt_prompt = (prompt + "\n\nYOUR PREVIOUS REPLY WAS INVALID: " + str(e)[:400] +
                                  "\nReply again with ONLY valid JSON matching the requested schema.")
        raise LLMError(f"[{stage}] invalid output after {retries + 1} tries: {last_err}")

    def text(self, spec: ModelSpec, system: str, prompt: str, stage: str, salt: str = "") -> str:
        """Try the stage's model, then its fallbacks if a daily quota is exhausted."""
        chain = [spec.model] + [m for m in spec.fallback if m != spec.model]
        specs = []
        for m in chain:
            s = spec
            if m != spec.model:
                pin, pout = self.prices.get(m, (spec.price_in, spec.price_out))
                # a thinking budget is model-specific (e.g. 3.5 Flash-Lite rejects 0), so fallbacks use the model default
                s = ModelSpec(**{**spec.__dict__, "model": m, "fallback": [], "price_in": pin, "price_out": pout,
                                 "thinking_budget": None})
            specs.append(s)
        # resume: if any model in the chain already answered this exact prompt, reuse it (no new call)
        for s in specs:
            if (self.cache_dir / f"{self._key(s, system, prompt, salt)}.json").exists():
                return self._text_one(s, system, prompt, stage, salt)
        last: Exception | None = None
        for m, s in zip(chain, specs):
            if s.label in self.exhausted and m != chain[-1]:
                continue
            try:
                return self._text_one(s, system, prompt, stage, salt)
            except QuotaExhausted as e:
                last = e
                with self._lock:
                    if s.label not in self.exhausted:
                        self.exhausted.add(s.label)
                        why = "not available (retired?)" if isinstance(e, ModelUnavailable) else str(e)[:120]
                        self.fallbacks_used.append(f"{stage}: {s.label} {why}")
                        self.log(f"      ! {s.label}: {why} -> switching to fallback")
        raise last or LLMError("no model available")

    @staticmethod
    def _key(spec: ModelSpec, system: str, prompt: str, salt: str = "") -> str:
        parts = [spec.provider, spec.model, spec.temperature, spec.thinking_budget, system, prompt, salt]
        if spec.base_url:          # same model name at two services must not share answers
            parts.append(spec.base_url.rstrip("/"))
        return hashlib.sha256(json.dumps(parts).encode()).hexdigest()[:24]

    def _text_one(self, spec: ModelSpec, system: str, prompt: str, stage: str, salt: str = "") -> str:
        key = self._key(spec, system, prompt, salt)
        cpath = self.cache_dir / f"{key}.json"
        if cpath.exists():
            c = json.loads(cpath.read_text(encoding="utf-8"))
            self._record(CallRecord(stage, spec.label, c["pt"], c["ot"], 0.0, 0.0, True, key), spec, system, prompt, c["text"])
            return c["text"]
        t0 = time.time()
        if spec.provider == "mock":
            text, pt, ot = self._mock(system, prompt, stage)
        else:
            _LIMITER.wait(spec.label, spec.rpm)
            if spec.provider == "gemini":
                text, pt, ot = self._gemini(spec, system, prompt)
            elif spec.provider in ("openai", "openai_compatible"):
                text, pt, ot = self._openai(spec, system, prompt)
            else:
                raise LLMError(f"unknown provider {spec.provider!r}")
        dt = time.time() - t0
        cpath.write_text(json.dumps({"text": text, "pt": pt, "ot": ot, "model": spec.label}), encoding="utf-8")
        cost = pt / 1e6 * spec.price_in + ot / 1e6 * spec.price_out
        self._record(CallRecord(stage, spec.label, pt, ot, cost, dt, False, key), spec, system, prompt, text)
        return text

    def summary(self) -> dict:
        out: dict[str, Any] = {"calls": len(self.records), "cached_calls": sum(r.cached for r in self.records),
                               "by_stage": {}}
        for r in self.records:
            s = out["by_stage"].setdefault(r.stage, {"calls": 0, "prompt_tokens": 0, "output_tokens": 0,
                                                     "cost_usd": 0.0, "model": r.model})
            s["calls"] += 1
            s["prompt_tokens"] += r.prompt_tokens
            s["output_tokens"] += r.output_tokens
            s["cost_usd"] = round(s["cost_usd"] + r.cost_usd, 6)
            if r.model not in s["model"].split(", "):
                s["model"] += ", " + r.model
            s.setdefault("models", {})
            s["models"][r.model] = s["models"].get(r.model, 0) + 1   # calls answered by each model
            s.setdefault("cached", 0)
            s["cached"] += int(r.cached)
        out["prompt_tokens"] = sum(r.prompt_tokens for r in self.records)
        out["output_tokens"] = sum(r.output_tokens for r in self.records)
        out["cost_usd_this_run"] = round(sum(r.cost_usd for r in self.records), 4)
        out["fallbacks_used"] = self.fallbacks_used
        return out

    # ----------------------------------------------------------------- private
    def _record(self, rec: CallRecord, spec: ModelSpec, system: str, prompt: str, reply: str):
        # cached calls still count their tokens so "cost per show" is honest
        if rec.cached:
            rec.cost_usd = rec.prompt_tokens / 1e6 * spec.price_in + rec.output_tokens / 1e6 * spec.price_out
        with self._lock:
            self.records.append(rec)
            if self.log_path:
                self.log_path.parent.mkdir(parents=True, exist_ok=True)
                with self.log_path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps({"stage": rec.stage, "model": rec.model, "cached": rec.cached,
                                        "prompt_tokens": rec.prompt_tokens, "output_tokens": rec.output_tokens,
                                        "seconds": round(rec.seconds, 2), "system": system, "prompt": prompt,
                                        "reply": reply}, ensure_ascii=False) + "\n")

    def _post(self, url: str, headers: dict, body: dict, max_tries: int = 6, label: str = "") -> dict:
        delay = 4.0
        for attempt in range(max_tries):
            try:
                r = requests.post(url, headers=headers, json=body, timeout=(15, 240))
            except requests.RequestException as e:
                if attempt == max_tries - 1:
                    raise LLMError(f"network error: {e}") from e
                self.log(f"      ... {label}: network problem ({type(e).__name__}); retry {attempt + 1}/{max_tries - 1} in {delay:.0f}s")
                time.sleep(delay); delay *= 2
                continue
            if r.status_code == 200:
                return r.json()
            if r.status_code == 429:
                # Only a violated *per-day* quota means "switch model". The body can mention daily quotas
                # while the actual violation is per-minute; treating that as daily wrongly abandons a model.
                ids = re.findall(r'"quotaId":\s*"([^"]+)"', r.text)
                if ids and all("PerDay" in i for i in ids):
                    raise QuotaExhausted(f"daily quota exhausted ({', '.join(sorted(set(ids)))})")
            if r.status_code == 404:
                raise ModelUnavailable(f"model not available: {r.text[:200]}")  # retired/renamed model -> fallback
            if r.status_code in (429, 500, 502, 503, 504) and attempt < max_tries - 1:
                wait = delay
                m = re.search(r'"retryDelay":\s*"(\d+)s"', r.text)
                if m:
                    wait = max(wait, float(m.group(1)) + 1)
                wait = min(wait, 90)
                why = "rate limited (too many requests per minute)" if r.status_code == 429 else "server busy"
                self.log(f"      ... {label}: HTTP {r.status_code} {why}; retry {attempt + 1}/{max_tries - 1} in {wait:.0f}s")
                time.sleep(wait); delay *= 2
                continue
            raise LLMError(f"HTTP {r.status_code}: {r.text[:500]}")
        raise LLMError("exhausted retries")

    def _gemini(self, spec: ModelSpec, system: str, prompt: str) -> tuple[str, int, int]:
        key = os.environ.get(spec.api_key_env or "GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not key:
            raise LLMError("GEMINI_API_KEY is not set (get a free key at aistudio.google.com)")
        base = spec.base_url or "https://generativelanguage.googleapis.com/v1beta"
        url = f"{base}/models/{spec.model}:generateContent"
        gen: dict[str, Any] = {"temperature": spec.temperature, "responseMimeType": "application/json"}
        if spec.thinking_budget is not None:
            gen["thinkingConfig"] = {"thinkingBudget": spec.thinking_budget}
        body = {"systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": gen}
        data = self._post(url, {"x-goog-api-key": key, "Content-Type": "application/json"}, body, label=spec.label)
        cands = data.get("candidates") or []
        if not cands:
            raise LLMError(f"gemini returned no candidates: {json.dumps(data)[:300]}")
        parts = cands[0].get("content", {}).get("parts", [])
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        u = data.get("usageMetadata", {})
        pt = int(u.get("promptTokenCount", 0))
        ot = int(u.get("candidatesTokenCount", 0)) + int(u.get("thoughtsTokenCount", 0))
        return text, pt, ot

    def _openai(self, spec: ModelSpec, system: str, prompt: str) -> tuple[str, int, int]:
        """Any OpenAI-compatible chat API: OpenAI, Anthropic (compat layer), GitHub Models, OpenRouter, Groq, ...

        Providers differ in which optional settings they accept (e.g. newer OpenAI models reject a custom
        temperature; some reject response_format). If one is refused, retry once without it."""
        key = os.environ.get(spec.api_key_env or "OPENAI_API_KEY", "")
        base = (spec.base_url or "https://api.openai.com/v1").rstrip("/")
        body = {"model": spec.model, "temperature": spec.temperature,
                "response_format": {"type": "json_object"},
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]}
        if "anthropic.com" in base:
            body["max_tokens"] = 16000          # Claude requires an output limit
        refused = getattr(self, "_refused", {}).get((base, spec.model), set())
        for k in refused:                       # settings this provider/model already refused once
            body.pop(k, None)
        headers = {"Content-Type": "application/json"}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        for _ in range(3):
            try:
                data = self._post(f"{base}/chat/completions", headers, body, label=spec.label)
                break
            except LLMError as e:
                msg = str(e)
                if msg.startswith(("HTTP 401", "HTTP 403")):
                    raise LLMError(f"the provider rejected the key or this model isn't allowed for it ({msg[:160]})") from e
                dropped = [k for k in ("temperature", "response_format") if k in body and k in msg]
                if not msg.startswith(("HTTP 400", "HTTP 422")) or not dropped:
                    raise
                for k in dropped:
                    body.pop(k)
                if not hasattr(self, "_refused"):
                    self._refused = {}
                self._refused.setdefault((base, spec.model), set()).update(dropped)
                self.log(f"      ... {spec.label}: provider doesn't accept {', '.join(dropped)}; retrying without it")
        text = data["choices"][0]["message"]["content"] or ""
        u = data.get("usage", {})
        return text, int(u.get("prompt_tokens", 0)), int(u.get("completion_tokens", 0))

    def _mock(self, system: str, prompt: str, stage: str) -> tuple[str, int, int]:
        if not self.mock_fn:
            raise LLMError("mock provider selected but no mock function registered")
        text = self.mock_fn(stage, system, prompt)
        return text, len(prompt) // 4, len(text) // 4
