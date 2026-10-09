# HesabAI - quota protection in the LLM wrapper (no network)
import json

import llm


def test_cache_save_merges_instead_of_overwriting(tmp_path, monkeypatch):
    # the app and evaluate.py run at the same time; one must not delete the other's paid-for answers
    f = tmp_path / "cache.json"
    f.write_text(json.dumps({"other-process": "kept"}), encoding="utf-8")
    monkeypatch.setattr(llm, "CACHE_FILE", str(f))
    monkeypatch.setattr(llm, "cache", {"this-process": "new"})
    llm.save_cache()
    assert json.loads(f.read_text(encoding="utf-8")) == {"other-process": "kept", "this-process": "new"}


def test_call_budget_stops_real_requests(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    monkeypatch.setattr(llm, "OPENAI_BASE_URL", "https://api.groq.com/openai/v1")
    monkeypatch.setattr(llm, "OPENAI_MODEL", "some-model")
    monkeypatch.setattr(llm, "MAX_CALLS", 3)
    monkeypatch.setattr(llm, "cache", {})
    monkeypatch.setitem(llm.stats, "calls", 3)
    for k in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    try:
        llm.complete("new prompt")
        assert False, "budget should have stopped the request"
    except RuntimeError as e:
        assert "budget" in str(e)


def test_reasoning_text_is_ignored():
    assert llm.parse_json('<think>{"x": 1}</think>{"ok": true}') == {"ok": True}
