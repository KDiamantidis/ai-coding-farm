# =============================================================================
# FILE:    tests/test_gatekeeper.py
# PURPOSE: Pin down every way the gatekeeper can say no, and the one way it
#          says yes. These are the rules that make a weak model safe.
# =============================================================================

from farm import gatekeeper

BIG_FILE = "\n".join(f"line_{i} = {i}" for i in range(30)) + "\n"


def make_repo(tmp_path, files):
    for name, content in files.items():
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return tmp_path


def task(allowed=("app.py",), cmd="python -c \"import app\""):
    return {"id": "t", "files_allowed": list(allowed), "test_cmd": cmd}


def test_empty_patch_is_rejected(tmp_path):
    repo = make_repo(tmp_path, {"app.py": "x = 1\n"})
    assert gatekeeper.evaluate(repo, task(), {}).reason == "empty_patch"


def test_path_escape_is_rejected(tmp_path):
    repo = make_repo(tmp_path, {"app.py": "x = 1\n"})
    for bad in ("../evil.py", "/etc/passwd", "C:/Windows/x.py"):
        assert gatekeeper.evaluate(repo, task(), {bad: "x = 1\n"}).reason == "bad_path"


def test_file_outside_the_allowed_list_is_rejected(tmp_path):
    repo = make_repo(tmp_path, {"app.py": "x = 1\n"})
    verdict = gatekeeper.evaluate(repo, task(), {"tests/test_x.py": "x = 1\n"})
    assert verdict.reason == "not_allowed"
    assert "app.py" in verdict.feedback   # the next attempt is told what IS allowed


def test_placeholder_is_rejected(tmp_path):
    repo = make_repo(tmp_path, {"app.py": "x = 1\n"})
    verdict = gatekeeper.evaluate(repo, task(), {"app.py": "# ... rest of the code\n"})
    assert verdict.reason == "placeholder"


def test_big_file_that_shrinks_is_rejected(tmp_path):
    repo = make_repo(tmp_path, {"app.py": BIG_FILE})
    verdict = gatekeeper.evaluate(repo, task(), {"app.py": "x = 1\n"})
    assert verdict.reason == "shrunk"


def test_small_file_may_shrink(tmp_path):
    repo = make_repo(tmp_path, {"app.py": "a = 1\nb = 2\nc = 3\n"})
    assert gatekeeper.evaluate(repo, task(), {"app.py": "a = 1\n"}).passed


def test_failing_tests_give_trimmed_feedback(tmp_path):
    repo = make_repo(tmp_path, {"app.py": "x = 1\n"})
    t = task(cmd="python -c \"import app; assert app.x == 2\"")
    verdict = gatekeeper.evaluate(repo, t, {"app.py": "x = 1\n"})
    assert verdict.reason == "tests_failed"
    assert "AssertionError" in verdict.feedback
    assert len(verdict.feedback) <= gatekeeper.FEEDBACK_MAX_CHARS


def test_passing_patch_is_accepted_and_real_repo_is_untouched(tmp_path):
    repo = make_repo(tmp_path, {"app.py": "x = 1\n"})
    t = task(cmd="python -c \"import app; assert app.x == 2\"")
    verdict = gatekeeper.evaluate(repo, t, {"app.py": "x = 2\n"})
    assert verdict.passed and verdict.reason == "ok"
    # The gatekeeper only tests. Writing is the orchestrator's job.
    assert (repo / "app.py").read_text() == "x = 1\n"


def test_slow_tests_time_out(tmp_path):
    repo = make_repo(tmp_path, {"app.py": "x = 1\n"})
    t = task(cmd="python -c \"import time; time.sleep(5)\"")
    verdict = gatekeeper.evaluate(repo, t, {"app.py": "x = 1\n"}, timeout_s=1)
    assert verdict.reason == "timeout"
