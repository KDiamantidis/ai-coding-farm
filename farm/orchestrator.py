# =============================================================================
# FILE:    farm/orchestrator.py
# PURPOSE: Run the queue. Pick ready tasks, ask a model, let the gatekeeper
#          judge, retry with a stronger model, commit what passes.
#
# EXPORTS:
#   run_all(conn, cfg, repo, branch)  -> dict summary
#
# THE LOOP (per task):
#   attempt 1 -> chain[0]. Rejected? attempt 2 -> chain[1] (escalation).
#   ... up to settings.max_attempts. The last level repeats if the chain is short.
#   Only the trimmed failure text is passed to the next attempt, no history.
#
# TASK ORDER (a small DAG):
#   A task is READY when every id in depends_on is 'done'. If a dependency
#   failed, the task becomes 'blocked' and is never attempted.
#
# GIT:
#   Passing patches are committed to ONE branch, one commit per task. The farm
#   never touches main. A human reviews and merges (pull request style).
#   Commit identity comes from the repo's own git config. No author lines are
#   added by the farm.
# =============================================================================

from __future__ import annotations

import subprocess
import time
from pathlib import Path

from . import db, gatekeeper, worker
from .mockmodel import ModelError
from .router import Router


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout.strip()


def _is_git_repo(repo: Path) -> bool:
    return (repo / ".git").exists()


def _switch_to_branch(repo: Path, branch: str) -> None:
    """Be on the farm branch. Create it if it is new. NEVER reset an existing one:
    it holds the earlier farm commits, and later tasks depend on that work."""
    if not _is_git_repo(repo):
        return
    if _git(repo, "rev-parse", "--abbrev-ref", "HEAD") == branch:
        return
    exists = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"],
        capture_output=True).returncode == 0
    if exists:
        _git(repo, "checkout", branch)
    else:
        _git(repo, "checkout", "-b", branch)


def _apply_and_commit(repo: Path, task: dict, files: dict[str, str], branch: str) -> None:
    """Write the passing files into the real repo and commit them."""
    use_git = _is_git_repo(repo)
    _switch_to_branch(repo, branch)
    for raw_path, content in files.items():
        target = repo / gatekeeper._normalize(raw_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    if use_git:
        _git(repo, "add", "--", *[gatekeeper._normalize(p) for p in files])
        _git(repo, "commit", "-m", f"farm: {task['id']} - {task['title']}")


def ready_tasks(conn) -> list[dict]:
    """Pending tasks whose dependencies are all done. Marks blocked ones."""
    tasks = db.all_tasks(conn)
    status = {t["id"]: t["status"] for t in tasks}
    ready = []
    for t in tasks:
        if t["status"] != "pending":
            continue
        deps = t["depends_on"]
        if any(status.get(d) in ("failed", "blocked", "unavailable") for d in deps):
            db.set_status(conn, t["id"], "blocked")
            status[t["id"]] = "blocked"
        elif all(status.get(d) == "done" for d in deps):
            ready.append(t)
    return ready


def run_task(conn, router: Router, cfg: dict, repo: Path, task: dict, branch: str) -> str:
    """Try one task. Returns 'done', 'failed' or 'unavailable'.

    Only answers that reached the gatekeeper count as attempts. If every model
    is down (outage, rate limit) we wait and retry the SAME attempt; the task is
    not blamed for it. When the outage lasts too long the result is
    'unavailable', which is not a verdict on the model or the task.
    """
    settings = cfg["settings"]
    feedback: str | None = None
    attempt_no = 1
    outages = 0

    while attempt_no <= settings["max_attempts"]:
        level = attempt_no - 1  # escalation: each attempt starts one model higher
        messages = worker.build_messages(task, repo, feedback)
        try:
            reply = router.call("coder", messages, level=level,
                                task_id=task["id"], attempt_no=attempt_no)
        except ModelError:
            outages += 1
            if outages > settings["outage_retries"]:
                return "unavailable"
            time.sleep(settings["outage_wait_s"])
            continue

        files = worker.parse_files(reply.text)
        verdict = gatekeeper.evaluate(repo, task, files, settings["test_timeout_s"])
        db.log_attempt(conn, task_id=task["id"], attempt_no=attempt_no, role="coder",
                       model=reply.model, passed=verdict.passed, reason=verdict.reason,
                       tokens_in=reply.tokens_in, tokens_out=reply.tokens_out,
                       latency_s=reply.latency_s,
                       detail=None if verdict.passed else f"[finish={reply.finish_reason or '?'}] " + reply.text[:500])
        if verdict.passed:
            _apply_and_commit(repo, task, files, branch)
            return "done"
        feedback = verdict.feedback
        attempt_no += 1

    return "failed"


def run_all(conn, cfg: dict, repo: str | Path, branch: str = "farm/run") -> dict:
    """Process the whole queue. Returns counts per status.

    Running again CONTINUES: tasks that were 'unavailable' (API down) or
    'blocked' by them are put back in the queue. Real failures stay failed.
    """
    repo = Path(repo)
    router = Router(cfg, conn)
    _switch_to_branch(repo, branch)  # tests must see the work of earlier runs
    for t in db.all_tasks(conn):
        if t["status"] in ("unavailable", "blocked"):
            db.set_status(conn, t["id"], "pending")

    in_a_row = 0
    while True:
        ready = ready_tasks(conn)
        if not ready:
            break
        task = ready[0]
        result = run_task(conn, router, cfg, repo, task, branch)
        db.set_status(conn, task["id"], result)
        in_a_row = in_a_row + 1 if result == "unavailable" else 0
        if in_a_row >= 2:  # the APIs are down: stop, do not burn time. Run again later.
            break

    summary = {"done": 0, "failed": 0, "blocked": 0, "unavailable": 0, "pending": 0}
    for t in db.all_tasks(conn):
        summary[t["status"]] = summary.get(t["status"], 0) + 1
    return summary
