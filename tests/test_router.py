# =============================================================================
# FILE:    tests/test_router.py
# PURPOSE: API fallback and call logging, using the mock models only.
# =============================================================================

import pytest

from farm import db
from farm.mockmodel import ModelError
from farm.router import Router


def make_router(tmp_path, chain):
    (tmp_path / "t1.good.txt").write_text("hello", encoding="utf-8")
    cfg = {
        "roles": {"coder": {"chain": chain}},
        "settings": {"call_timeout_s": 5},
        "mock_dir": str(tmp_path),
    }
    conn = db.connect(tmp_path / "test.db")
    return Router(cfg, conn), conn


MESSAGES = [{"role": "user", "content": "TASK_ID: t1"}]


def test_outage_falls_back_to_the_next_model_and_is_logged(tmp_path):
    router, conn = make_router(tmp_path, ["mock/error", "mock/good"])
    reply = router.call("coder", MESSAGES)
    assert reply.model == "mock/good"
    rows = conn.execute("SELECT model, ok FROM calls ORDER BY id").fetchall()
    assert [(r["model"], r["ok"]) for r in rows] == [("mock/error", 0), ("mock/good", 1)]


def test_level_starts_higher_in_the_chain(tmp_path):
    router, _ = make_router(tmp_path, ["mock/error", "mock/good"])
    assert router.call("coder", MESSAGES, level=1).model == "mock/good"


def test_level_beyond_the_chain_uses_the_last_model(tmp_path):
    router, _ = make_router(tmp_path, ["mock/error", "mock/good"])
    assert router.call("coder", MESSAGES, level=9).model == "mock/good"


def test_all_models_failing_raises(tmp_path):
    router, _ = make_router(tmp_path, ["mock/error", "mock/error"])
    with pytest.raises(ModelError):
        router.call("coder", MESSAGES)


def test_real_provider_path_uses_litellm_and_reads_usage(tmp_path, monkeypatch):
    """No network: a fake `litellm` module stands in for the real one."""
    import sys
    import types
    from types import SimpleNamespace

    seen = {}

    def fake_completion(**kwargs):
        seen.update(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="answer"))],
            usage=SimpleNamespace(prompt_tokens=11, completion_tokens=7),
        )

    monkeypatch.setitem(sys.modules, "litellm",
                        types.SimpleNamespace(completion=fake_completion))
    router, conn = make_router(tmp_path, ["groq/some-model"])
    reply = router.call("coder", MESSAGES)
    assert (reply.text, reply.tokens_in, reply.tokens_out) == ("answer", 11, 7)
    assert seen["model"] == "groq/some-model" and seen["timeout"] == 5


def test_model_params_are_passed_to_litellm(tmp_path, monkeypatch):
    import sys
    import types
    from types import SimpleNamespace

    seen = {}

    def fake_completion(**kwargs):
        seen.update(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="x"), finish_reason="stop")],
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1))

    monkeypatch.setitem(sys.modules, "litellm", types.SimpleNamespace(completion=fake_completion))
    router, _ = make_router(tmp_path, ["groq/a"])
    router.cfg["model_params"] = {"groq/a": {"reasoning_effort": "low"}}
    reply = router.call("coder", MESSAGES)
    assert seen["reasoning_effort"] == "low"
    assert reply.finish_reason == "stop"


def test_provider_wait_hint_is_used():
    from farm.router import _retry_wait
    assert _retry_wait("Please try again in 50ms.", 5) == 1.0         # at least 1 s
    assert _retry_wait("Please retry in11.09s.", 5) == 11.59
    assert _retry_wait("try again in 600s", 5) == 60.0               # capped
    assert _retry_wait("no hint here", 7) == 7


def test_transient_error_is_retried_once(monkeypatch, tmp_path):
    """A 503 is retried on the same model before moving on."""
    from farm import db, router
    conn = db.connect(str(tmp_path / "t.db"))
    cfg = {"roles": {"coder": {"chain": ["fake/m"]}},
           "settings": {"call_timeout_s": 5, "retry_wait_s": 0}}
    r = router.Router(cfg, conn)
    calls = {"n": 0}

    def fake(model, messages):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("503 high demand")
        return "ok", 1, 1

    monkeypatch.setattr(r, "_complete", fake)
    assert r.call("coder", []).text == "ok"
    assert calls["n"] == 2


def test_missing_litellm_is_a_setup_error_not_an_outage(tmp_path, monkeypatch):
    """Review feedback: no litellm must stop with a clear message, not 'API down'."""
    import sys

    import pytest

    from farm.config import ConfigError

    monkeypatch.setitem(sys.modules, "litellm", None)   # makes `import litellm` fail
    router, _ = make_router(tmp_path, ["groq/some-model"])
    with pytest.raises(ConfigError):
        router.call("coder", MESSAGES)
