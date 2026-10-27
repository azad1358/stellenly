import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import llm_client  # noqa: E402


class Resp:
    def __init__(self, status, payload=None, text="", headers=None):
        self.status_code, self._payload, self.text, self.headers = status, payload, text, headers or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


def ok(content):
    return Resp(200, {"choices": [{"message": {"content": content}}]})


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "AIza-test")
    monkeypatch.setenv("LLM_MODEL", "gemini-test-flash")
    monkeypatch.setenv("LLM_PAUSE", "0")
    monkeypatch.setattr(llm_client.time, "sleep", lambda s: None)
    monkeypatch.setattr(llm_client, "_model_override", None)
    monkeypatch.setattr(llm_client, "_json_mode", True)


def queue(monkeypatch, responses, calls=None):
    it = iter(responses)

    def post(url, **kw):
        if calls is not None:
            calls.append(kw["json"])
        return next(it)
    monkeypatch.setattr(llm_client.requests, "post", post)


def test_retries_busy_server_then_succeeds(monkeypatch):
    queue(monkeypatch, [Resp(503, text="overloaded"), Resp(429, text="rate limit per minute"), ok('{"a": 1}')])
    assert llm_client.chat_json("hi") == {"a": 1}


def test_daily_quota_stops_the_run(monkeypatch):
    queue(monkeypatch, [Resp(429, text='{"error": {"quotaId": "GenerateRequestsPerDayPerProjectPerModel"}}')])
    with pytest.raises(llm_client.LLMQuotaExhausted):
        llm_client.chat_json("hi")


def test_gives_up_after_retries(monkeypatch):
    monkeypatch.setenv("LLM_RETRIES", "2")
    queue(monkeypatch, [Resp(503)] * 3)
    with pytest.raises(llm_client.LLMUnavailable):
        llm_client.chat_json("hi")


def test_reads_fenced_or_wrapped_json(monkeypatch):
    queue(monkeypatch, [ok('```json\n{"german": "required"}\n```')])
    assert llm_client.chat_json("hi") == {"german": "required"}
    queue(monkeypatch, [ok('Here you go: {"x": 2} hope it helps')])
    assert llm_client.chat_json("hi") == {"x": 2}


def test_invalid_json_is_retried(monkeypatch):
    queue(monkeypatch, [ok("not json at all"), ok('{"ok": true}')])
    assert llm_client.chat_json("hi") == {"ok": True}


def test_unknown_model_falls_back_to_newest_flash(monkeypatch):
    calls = []
    queue(monkeypatch, [Resp(404, text="model gemini-test-flash is not found"), ok('{"ok": 1}')], calls)
    monkeypatch.setattr(llm_client.requests, "get", lambda url, **kw: Resp(200, {"data": [
        {"id": "models/gemini-2.5-flash"}, {"id": "models/gemini-3.8-flash"}, {"id": "models/gemini-3.8-flash-lite"}]}))
    assert llm_client.chat_json("hi") == {"ok": 1}
    assert calls[-1]["model"] == "gemini-3.8-flash"


def test_rejected_json_mode_is_dropped(monkeypatch):
    calls = []
    queue(monkeypatch, [Resp(400, text="Invalid value for response_format"), ok('{"ok": 1}')], calls)
    assert llm_client.chat_json("hi") == {"ok": 1}
    assert "response_format" not in calls[-1]


def test_bad_key_is_a_config_error(monkeypatch):
    queue(monkeypatch, [Resp(403, text="API key not valid")])
    with pytest.raises(llm_client.LLMConfigError):
        llm_client.chat_json("hi")
