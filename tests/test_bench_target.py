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
