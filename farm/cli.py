# =============================================================================
# FILE:    farm/cli.py
# PURPOSE: The command line: python -m farm <command>
#
# COMMANDS:
#   add TASKS.json     put tasks into the queue
#   run  --repo PATH   work through the queue, commit passes to a branch
#   report             print the statistics
#   demo               run everything offline with mock models (no API keys)
#   debug              show the API error messages and the start of rejected answers
#   bench [--tag T]    run the 10 harder tasks in examples/bench_target with the
#                      models in models.yaml (needs API keys). Starts clean each time.
#
# DESIGN NOTES:
#   - The demo copies examples/demo_target into .farm/demo_repo and runs there,
#     so your real files are never touched and you can run it again and again.
#   - The demo repo gets a throw-away git identity set LOCALLY (not global).
# =============================================================================

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

from . import db, orchestrator, sandbox, stats
from .config import ConfigError, load_env, load_models

ROOT = Path(__file__).resolve().parent.parent
DEMO_SOURCE = ROOT / "examples" / "demo_target"
DEMO_WORK = ROOT / ".farm" / "demo_repo"
DEMO_DB = ROOT / ".farm" / "demo.db"
DEMO_MODELS = ROOT / "models.mock.yaml"
BENCH_SOURCE = ROOT / "examples" / "bench_target"


def _load_tasks(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    tasks = data["tasks"] if isinstance(data, dict) else data
    if not isinstance(tasks, list):
        raise ValueError("tasks file must be a list or {\"tasks\": [...]}")
    return tasks


def cmd_add(args) -> int:
    conn = db.connect(args.db)
    tasks = _load_tasks(Path(args.tasks))
    for t in tasks:
        db.add_task(conn, t)
    print(f"added {len(tasks)} task(s) to {args.db}")
    return 0


def cmd_run(args) -> int:
    load_env(args.env)
    cfg = load_models(args.models)
    conn = db.connect(args.db)
    summary = orchestrator.run_all(conn, cfg, args.repo, args.branch)
    print("summary:", summary)
    print(f"review the work with:  git -C {args.repo} log {args.branch}")
    if summary.get("unavailable"):
        print("some tasks could not run because the model APIs were down. "
              "Run the same command again to continue.")
    ok = summary["failed"] == 0 and summary["blocked"] == 0 and not summary.get("unavailable")
    return 0 if ok else 1


def cmd_sandbox_build(args) -> int:
    cfg = sandbox.from_settings({"sandbox": "docker"})
    return sandbox.build_image(cfg)


def cmd_report(args) -> int:
    conn = db.connect(args.db)
    print(stats.format_report(conn))
    return 0


def _remove(path: Path) -> None:
    """Delete a file or folder if it exists. Git marks some files read-only on
    Windows, so the folder delete clears that flag first."""
    import os
    import stat

    def _unlock(func, p, _exc):
        os.chmod(p, stat.S_IWRITE)
        func(p)

    if path.is_dir():
        shutil.rmtree(path, onerror=_unlock)
    elif path.exists():
        path.unlink()


def _prepare_repo(source: Path, work: Path) -> None:
    """Fresh copy of a target project as a git repo with a throw-away identity.

    The mock answers, the reference solutions and tasks.json are NOT copied:
    the model must never see the answers.
    """
    _remove(work)
    shutil.copytree(source, work,
                    ignore=shutil.ignore_patterns("mock", "reference", "tasks.json",
                                                  "__pycache__", ".pytest_cache"))
    for cmd in (
        ["init", "-q", "-b", "main"],
        ["config", "user.name", "Farm Demo"],
        ["config", "user.email", "demo@example.invalid"],
        ["add", "-A"],
        ["commit", "-q", "-m", "start: broken starting point"],
    ):
        subprocess.run(["git", "-C", str(work), *cmd], check=True)


def cmd_debug(args) -> int:
    """Print what went wrong, in plain text (no SQL typing needed)."""
    conn = db.connect(args.db)
    print("API ERRORS (grouped, first 900 characters of the message)")
    print("-" * 78)
    rows = conn.execute(
        "SELECT model, substr(replace(error, char(10), ' '), 1, 900) AS msg, COUNT(*) AS n "
        "FROM calls WHERE ok = 0 GROUP BY model, msg ORDER BY n DESC").fetchall()
    for r in rows:
        print(f"{r['n']:>3} x {r['model']}\n      {r['msg']}")
    if not rows:
        print("none")
    print()
    print("REJECTED ANSWERS (reason, task, first 300 characters of the answer)")
    print("-" * 78)
    rows = conn.execute(
        "SELECT task_id, model, reason, substr(replace(detail, char(10), ' | '), 1, 300) AS d "
        "FROM attempts WHERE passed = 0 ORDER BY id").fetchall()
    for r in rows:
        print(f"{r['reason']} | {r['task_id']} | {r['model']}\n      {r['d']!r}")
    if not rows:
        print("none")
    return 0


def cmd_demo(args) -> int:
    _remove(DEMO_DB)
    _prepare_repo(DEMO_SOURCE, DEMO_WORK)

    cfg = load_models(DEMO_MODELS)
    cfg["mock_dir"] = str(DEMO_SOURCE / "mock")
    conn = db.connect(DEMO_DB)
    for t in _load_tasks(DEMO_SOURCE / "tasks.json"):
        db.add_task(conn, t)

    summary = orchestrator.run_all(conn, cfg, DEMO_WORK, "farm/demo")
    print("summary:", summary)
    print(stats.format_report(conn))
    print(f"commits made by the farm:  git -C {DEMO_WORK} log --oneline farm/demo")
    print(f"dashboard:  streamlit run dashboard.py -- --db {DEMO_DB}")
    return 0


def cmd_bench(args) -> int:
    """Run the harder benchmark with the real models from models.yaml."""
    work = ROOT / ".farm" / f"bench_{args.tag}_repo"
    db_path = ROOT / ".farm" / f"bench_{args.tag}.db"
    _remove(db_path)
    _prepare_repo(BENCH_SOURCE, work)

    load_env(args.env)
    cfg = load_models(args.models)
    conn = db.connect(str(db_path))
    for t in _load_tasks(BENCH_SOURCE / "tasks.json"):
        db.add_task(conn, t)

    summary = orchestrator.run_all(conn, cfg, work, f"farm/bench-{args.tag}")
    print("summary:", summary)
    print(stats.format_report(conn))
    print(f"commits:    git -C {work} log --oneline farm/bench-{args.tag}")
    print(f"dashboard:  streamlit run dashboard.py -- --db {db_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="farm", description="AI coding farm")
    p.add_argument("--db", default="farm.db", help="SQLite file (default: farm.db)")
    sub = p.add_subparsers(dest="command", required=True)

    a = sub.add_parser("add", help="add tasks from a JSON file")
    a.add_argument("tasks")
    a.set_defaults(func=cmd_add)

    r = sub.add_parser("run", help="process the queue")
    r.add_argument("--repo", required=True, help="path to the target git repo")
    r.add_argument("--models", default="models.yaml")
    r.add_argument("--env", default=".env")
    r.add_argument("--branch", default="farm/run")
    r.set_defaults(func=cmd_run)

    sb = sub.add_parser("sandbox-build", help="build the Docker image for settings.sandbox: docker")
    sb.set_defaults(func=cmd_sandbox_build)

    s = sub.add_parser("report", help="print statistics")
    s.set_defaults(func=cmd_report)

    d = sub.add_parser("demo", help="offline demo with mock models")
    d.set_defaults(func=cmd_demo)

    x = sub.add_parser("debug", help="show API errors and rejected answers")
    x.set_defaults(func=cmd_debug)

    b = sub.add_parser("bench", help="10 harder tasks with the real models")
    b.add_argument("--models", default="models.yaml")
    b.add_argument("--env", default=".env")
    b.add_argument("--tag", default="main", help="name of this run (separate repo and db)")
    b.set_defaults(func=cmd_bench)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (ConfigError, ValueError, KeyError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
