# =============================================================================
# FILE:    tests/test_orchestrator.py
# PURPOSE: The whole loop, end to end, with the mock models: escalation,
#          dependencies, blocking, and git commits.
# =============================================================================

import shutil
import subprocess
from pathlib import Path

from farm import db, orchestrator
from farm.config import load_models

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "examples" / "demo_target"


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True,
                          capture_output=True, text=True).stdout.strip()


def setup_demo(tmp_path):
    repo = tmp_path / "repo"
    shutil.copytree(DEMO, repo, ignore=shutil.ignore_patterns("mock", "tasks.json", "__pycache__"))
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.name", "Test")
    git(repo, "config", "user.email", "test@example.invalid")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "start")
    cfg = load_models(ROOT / "models.mock.yaml")
    cfg["mock_dir"] = str(DEMO / "mock")
    conn = db.connect(tmp_path / "farm.db")
    return repo, cfg, conn


def add_demo_tasks(conn):
    import json
    for t in json.loads((DEMO / "tasks.json").read_text())["tasks"]:
        db.add_task(conn, t)


def test_full_demo_passes_with_escalation_and_one_commit_per_task(tmp_path):
    repo, cfg, conn = setup_demo(tmp_path)
    add_demo_tasks(conn)
    summary = orchestrator.run_all(conn, cfg, repo, "farm/test")
    assert summary["done"] == 4 and summary["failed"] == 0

    # weak model first, strong model only after a rejection
    first = conn.execute("SELECT model FROM attempts WHERE task_id='fix-slugify' "
                         "AND attempt_no=1").fetchone()
    assert first["model"] == "mock/weak"
    reasons = {r["reason"] for r in conn.execute("SELECT reason FROM attempts")}
    assert {"tests_failed", "placeholder", "not_allowed", "ok"} <= reasons

    log = git(repo, "log", "--format=%s", "farm/test").splitlines()
    assert len(log) == 5                                  # 4 tasks + the start commit
    assert git(repo, "rev-parse", "main") != git(repo, "rev-parse", "farm/test")
    # nobody sneaked a change into the tests
    assert "always_passes" not in (repo / "tests" / "test_palindrome.py").read_text()


def test_task_with_a_failed_dependency_is_blocked_not_attempted(tmp_path):
    repo, cfg, conn = setup_demo(tmp_path)
    cfg["settings"]["outage_wait_s"] = 0
    # A real failure: the "model" answers, but the check can never pass.
    cfg["roles"]["coder"]["chain"] = ["mock/strong"]
    db.add_task(conn, {"id": "fix-slugify", "title": "x", "description": "x",
                       "files_allowed": ["textutils.py"],
                       "test_cmd": "python -c \"import sys; sys.exit(1)\"", "depends_on": []})
    db.add_task(conn, {"id": "child", "title": "y", "description": "y",
                       "files_allowed": ["textutils.py"],
                       "test_cmd": "python -c \"pass\"", "depends_on": ["fix-slugify"]})
    summary = orchestrator.run_all(conn, cfg, repo, "farm/test")
    assert summary["failed"] == 1 and summary["blocked"] == 1
    child_attempts = conn.execute("SELECT COUNT(*) AS n FROM attempts "
                                  "WHERE task_id='child'").fetchone()["n"]
    assert child_attempts == 0


def test_outage_is_not_a_failure_and_the_next_run_continues(tmp_path):
    """No answer available = API down. The task becomes 'unavailable' (no attempt
    is counted) and a later run picks it up again."""
    repo, cfg, conn = setup_demo(tmp_path)
    cfg["settings"]["outage_wait_s"] = 0
    cfg["roles"]["coder"]["chain"] = ["mock/error"]          # always raises
    add_demo_tasks(conn)
    summary = orchestrator.run_all(conn, cfg, repo, "farm/test")
    assert summary["failed"] == 0 and summary["done"] == 0
    assert summary["unavailable"] >= 1
    assert conn.execute("SELECT COUNT(*) AS n FROM attempts").fetchone()["n"] == 0

    # the API "comes back": same queue, working models
    cfg2 = load_models(ROOT / "models.mock.yaml")
    cfg2["mock_dir"] = str(DEMO / "mock")
    summary = orchestrator.run_all(conn, cfg2, repo, "farm/test")
    assert summary["done"] == 4 and summary["unavailable"] == 0


def test_rejected_answer_keeps_its_start_in_the_log(tmp_path):
    repo, cfg, conn = setup_demo(tmp_path)
    add_demo_tasks(conn)
    orchestrator.run_all(conn, cfg, repo, "farm/test")
    rows = conn.execute("SELECT passed, detail FROM attempts").fetchall()
    assert any(r["passed"] == 0 and r["detail"] for r in rows)
    assert all(r["detail"] is None for r in rows if r["passed"] == 1)


def test_second_run_keeps_the_commits_of_the_first_run(tmp_path):
    """Review feedback: re-running after checking out main must not reset the branch,
    and a task that depends on earlier work must be tested WITH that work."""
    import json
    repo, cfg, conn = setup_demo(tmp_path)
    cfg["settings"]["outage_wait_s"] = 0
    tasks = json.loads((DEMO / "tasks.json").read_text())["tasks"]
    for t in tasks[:1]:                                   # run 1: only fix-slugify
        db.add_task(conn, t)
    orchestrator.run_all(conn, cfg, repo, "farm/test")
    first_commit = git(repo, "rev-parse", "farm/test")

    git(repo, "checkout", "main")                         # the user goes to review
    for t in tasks[1:]:                                   # run 2: the rest, incl. add-palindrome
        db.add_task(conn, t)                              # (it needs fix-slugify's work)
    summary = orchestrator.run_all(conn, cfg, repo, "farm/test")

    assert summary["done"] == 4 and summary["failed"] == 0
    log = git(repo, "log", "--format=%s", "farm/test").splitlines()
    assert len(log) == 5                                  # start + 4 tasks
    subprocess.run(["git", "-C", str(repo), "merge-base", "--is-ancestor",
                    first_commit, "farm/test"], check=True)
