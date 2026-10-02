# =============================================================================
# FILE:    tests/test_bench_target.py
# PURPOSE: Prove that the benchmark tasks are fair. For every task, in order:
#            1. its tests FAIL on the starting code
#            2. after the reference solution is applied, its tests PASS
#          If a task fails step 1 it is already solved (useless). If it fails
#          step 2 the task is broken (no model could ever pass it).
# =============================================================================

import json
import shutil
import subprocess
import sys
from pathlib import Path

BENCH = Path(__file__).resolve().parent.parent / "examples" / "bench_target"


def _run(repo: Path, test_cmd: str) -> bool:
    cmd = test_cmd.replace("python", sys.executable, 1)
    proc = subprocess.run(cmd.split(), cwd=repo, capture_output=True, text=True, timeout=60)
    return proc.returncode == 0


def test_every_task_fails_before_and_passes_after_reference(tmp_path):
    repo = tmp_path / "repo"
    shutil.copytree(BENCH, repo, ignore=shutil.ignore_patterns("reference", "tasks.json", "__pycache__"))
    tasks = json.loads((BENCH / "tasks.json").read_text(encoding="utf-8"))["tasks"]

    for task in tasks:
        assert not _run(repo, task["test_cmd"]), f"{task['id']}: tests already pass before the fix"
        ref_dir = BENCH / "reference" / task["id"]
        for ref_file in ref_dir.iterdir():
            assert ref_file.name in task["files_allowed"], f"{task['id']}: reference edits a file that is not allowed"
            shutil.copy(ref_file, repo / ref_file.name)
        assert _run(repo, task["test_cmd"]), f"{task['id']}: tests fail with the reference solution"


def test_dependencies_point_to_real_tasks_and_come_first():
    tasks = json.loads((BENCH / "tasks.json").read_text(encoding="utf-8"))["tasks"]
    seen = set()
    for task in tasks:
        assert set(task["depends_on"]) <= seen, f"{task['id']} depends on a task that comes later"
        seen.add(task["id"])


def test_whole_farm_solves_the_benchmark_offline(tmp_path):
    """End to end: queue, router, worker, gatekeeper, dependencies, git commits.
    The 'model' is mock/strong, which answers with the reference solutions."""
    from farm import cli, db, orchestrator

    repo = tmp_path / "repo"
    cli._prepare_repo(BENCH, repo)
    cfg = {"roles": {"coder": {"chain": ["mock/strong"]}},
           "settings": {"max_attempts": 1, "test_timeout_s": 60, "call_timeout_s": 5},
           "mock_dir": str(BENCH / "mock")}
    conn = db.connect(str(tmp_path / "bench.db"))
    for t in json.loads((BENCH / "tasks.json").read_text(encoding="utf-8"))["tasks"]:
        db.add_task(conn, t)

    summary = orchestrator.run_all(conn, cfg, repo, "farm/test")
    assert summary["done"] == 10 and summary["failed"] == 0 and summary["blocked"] == 0
    log = subprocess.run(["git", "-C", str(repo), "log", "--oneline", "farm/test"],
                         capture_output=True, text=True).stdout
    assert log.count("farm:") == 10


def test_parallel_workers_give_the_same_result_as_one_worker(tmp_path):
    """4 threads, same 10 tasks: same files, 10 commits, dependencies respected."""
    from farm import cli, db, orchestrator

    tasks = json.loads((BENCH / "tasks.json").read_text(encoding="utf-8"))["tasks"]
    contents = {}
    for n in (1, 4):
        repo = tmp_path / f"repo{n}"
        cli._prepare_repo(BENCH, repo)
        cfg = {"roles": {"coder": {"chain": ["mock/strong"]}},
               "settings": {"max_attempts": 1, "test_timeout_s": 60, "call_timeout_s": 5},
               "mock_dir": str(BENCH / "mock")}
        conn = db.connect(str(tmp_path / f"bench{n}.db"))
        for t in tasks:
            db.add_task(conn, t)
        summary = orchestrator.run_all(conn, cfg, repo, "farm/test", workers=n)
        assert summary["done"] == 10 and summary["failed"] == 0 and summary["blocked"] == 0
        log = subprocess.run(["git", "-C", str(repo), "log", "--format=%s", "farm/test"],
                             capture_output=True, text=True).stdout.splitlines()
        assert sum(1 for line in log if line.startswith("farm:")) == 10
        order = [line.split()[1] for line in reversed(log) if line.startswith("farm:")]
        for t in tasks:   # a task is committed after everything it depends on
            assert all(order.index(d) < order.index(t["id"]) for d in t["depends_on"])
        contents[n] = {p.name: p.read_text() for p in repo.glob("*.py")}
    assert contents[1] == contents[4]


def test_tasks_that_share_a_file_never_run_together():
    from farm.orchestrator import _conflict
    a = {"files_allowed": ["cart.py"], "context_files": []}
    b = {"files_allowed": ["./cart.py"], "context_files": []}
    c = {"files_allowed": ["money.py"], "context_files": ["cart.py"]}
    d = {"files_allowed": ["money.py"], "context_files": []}
    assert _conflict(a, b) and _conflict(a, c) and _conflict(c, a)
    assert not _conflict(a, d)
