"""One robust JSON call to an OpenAI-compatible chat API (Google Gemini, Groq, ...), made for crowded free tiers.

    chat_json(prompt) -> dict

- Retries rate limits (429), overloads (500/502/503/504), timeouts and dropped connections with exponential
  backoff + jitter, honouring Retry-After. A used-up *daily* quota stops the run instead (LLMUnavailable).
- Paces calls (LLM_PAUSE seconds between requests) so we stay under per-minute limits in the first place.
- Accepts answers wrapped in ```json fences or with extra text; retries unreadable answers.
- If LLM_MODEL doesn't exist, lists the available models and falls back to the newest "gemini-…-flash".

Env: LLM_API_KEY (required), LLM_API_URL, LLM_MODEL, LLM_PAUSE, LLM_RETRIES.
A key starting with "AIza" (Google AI Studio) uses Gemini's OpenAI-compatible endpoint automatically.
"""
from __future__ import annotations

import json
import os
import random
import re
import time

import requests

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
RETRY_STATUS = {429, 500, 502, 503, 504}
stats = {"calls": 0, "retries": 0, "failed": 0}
_last_call = 0.0
_model_override: str | None = None
_json_mode = True  # turned off if the endpoint rejects response_format


class LLMUnavailable(Exception):
    """This call still failed after all retries (service overloaded). Skip the job; stop after several in a row."""


class LLMQuotaExhausted(LLMUnavailable):
    """The daily free quota is used up: stop for this run, the rest waits for the next one."""


class LLMConfigError(Exception):
    """Key rejected or no usable model — retrying won't help."""


def _key() -> str:
    return os.environ.get("LLM_API_KEY", "")


def _is_gemini() -> bool:
    return _key().startswith("AIza") or "generativelanguage" in (os.environ.get("LLM_API_URL") or "")


def _url() -> str:
    return os.environ.get("LLM_API_URL") or (GEMINI_URL if _is_gemini() else GROQ_URL)


def _model() -> str:
    return _model_override or os.environ.get("LLM_MODEL") or ("gemini-flash-latest" if _is_gemini() else "llama-3.1-8b-instant")


def _pace() -> None:
    global _last_call
    pause = float(os.environ.get("LLM_PAUSE") or (6.0 if _is_gemini() else 2.1))
    time.sleep(max(0.0, pause - (time.monotonic() - _last_call)))
    _last_call = time.monotonic()


def _backoff(attempt: int, response: requests.Response | None = None) -> float:
    if response is not None:
        ra = response.headers.get("Retry-After", "")
        if ra.replace(".", "", 1).isdigit():
            return min(120.0, float(ra))
        m = re.search(r'"retryDelay"\s*:\s*"(\d+)', response.text or "")  # Gemini puts it in the error body
        if m:
            return min(120.0, float(m.group(1)) + 1)
    return min(60.0, 2.0 * 2 ** attempt) + random.uniform(0, 1.5)


def _daily_quota_gone(r: requests.Response) -> bool:
    body = (r.text or "").lower()
    return r.status_code == 429 and ("perday" in body or "per day" in body or "daily" in body)


def parse_json(content: str) -> dict:
    """The model's answer as a dict, also when it is wrapped in ```json fences or surrounded by text."""
    s = (content or "").strip()
    s = re.sub(r"^```(?:json)?\s*|\s*```$", "", s)
    try:
        out = json.loads(s)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", s, re.S)
        if not m:
            raise
        out = json.loads(m.group(0))
    if not isinstance(out, dict):
        raise json.JSONDecodeError("not an object", s, 0)
    return out


def available_models() -> list[str]:
    try:
        r = requests.get(_url().rsplit("/chat/completions", 1)[0] + "/models",
                         headers={"Authorization": f"Bearer {_key()}"}, timeout=30)
        r.raise_for_status()
        return sorted(m["id"].split("/")[-1] for m in r.json().get("data", []))
    except Exception as e:  # noqa: BLE001 — only used for a helpful message
        print(f"  ! could not list models: {e}")
        return []


def _fallback_model() -> str | None:
    """Newest plain 'gemini-X.Y-flash' model this key can use."""
    def version(name: str) -> tuple:
        m = re.fullmatch(r"gemini-(\d+(?:\.\d+)?)-flash", name)
        return tuple(int(x) for x in m.group(1).split(".")) if m else ()
    names = available_models()
    print("  available models:", ", ".join(n for n in names if "gemini" in n or "llama" in n)[:600])
    flash = sorted((n for n in names if version(n)), key=version)
    return flash[-1] if flash else None


def chat_json(prompt: str) -> dict:
    """Send one prompt, return the JSON answer. Raises LLMUnavailable / LLMConfigError when it should stop."""
    global _model_override, _json_mode
    if not _key():
        raise LLMConfigError("LLM_API_KEY is not set")
    retries = int(os.environ.get("LLM_RETRIES") or 6)
    for attempt in range(retries + 1):
        _pace()
        stats["calls"] += 1
        body = {"model": _model(), "temperature": 0, "messages": [{"role": "user", "content": prompt}]}
        if _json_mode:
            body["response_format"] = {"type": "json_object"}
        try:
            r = requests.post(_url(), timeout=120, headers={"Authorization": f"Bearer {_key()}"}, json=body)
        except (requests.Timeout, requests.ConnectionError) as e:
            wait = _backoff(attempt)
            print(f"  LLM {type(e).__name__}, retry {attempt + 1}/{retries} in {wait:.0f}s")
            stats["retries"] += 1
            time.sleep(wait)
            continue

        if r.status_code in RETRY_STATUS:
            if _daily_quota_gone(r):
                raise LLMQuotaExhausted("daily quota used up")
            if attempt == retries:
                break
            wait = _backoff(attempt, r)
            print(f"  LLM {r.status_code} (busy), retry {attempt + 1}/{retries} in {wait:.0f}s")
            stats["retries"] += 1
            time.sleep(wait)
            continue
        if r.status_code in (401, 403):
            raise LLMConfigError(f"API key rejected ({r.status_code}): {r.text[:200]}")
        if r.status_code == 400 and _json_mode and "response_format" in r.text:
            _json_mode = False  # the prompt asks for JSON anyway; parse_json copes with extra text
            continue
        if r.status_code in (400, 404) and "model" in r.text.lower() and not _model_override:
            print(f"  ! model '{_model()}' not usable ({r.status_code}): {r.text[:200]}")
            _model_override = _fallback_model()
            if not _model_override:
                raise LLMConfigError("no usable model; set LLM_MODEL to one of the models listed above")
            print(f"  -> using '{_model_override}' instead (set LLM_MODEL to choose another)")
            continue
        if r.status_code >= 400:
            raise LLMConfigError(f"LLM request failed ({r.status_code}): {r.text[:300]}")

        try:
            content = r.json()["choices"][0]["message"]["content"]
            return parse_json(content)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError):
            if attempt == retries:
                break
            print(f"  LLM answer was not valid JSON, retry {attempt + 1}/{retries}")
            stats["retries"] += 1
    stats["failed"] += 1
    raise LLMUnavailable("still failing after retries")
