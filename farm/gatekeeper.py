# =============================================================================
# FILE:    farm/gatekeeper.py
# PURPOSE: Decide, WITHOUT any LLM, whether a patch is allowed into the repo.
#          This is the part that makes a weak model safe to use.
#
# EXPORTS:
#   Verdict                      dataclass: passed, reason, feedback
#   evaluate(repo, task, files)  -> Verdict
#
# CHECKS, cheapest first (the first failure stops the pipeline):
#   1. empty_patch   the model returned no files
#   2. bad_path      absolute path or ".." escape
#   3. not_allowed   file is not in the task's files_allowed list
#   4. placeholder   "rest of the code" style laziness
#   5. shrunk        a big file lost more than 40% of its lines
#   6. tests_failed / timeout   the task's test command, run in a COPY of the repo
#                               (optionally inside a Docker container, see sandbox.py)
#
# DESIGN NOTES:
#   - The tests run in a temporary copy. The real repo is never touched until
#     everything passes (the orchestrator writes the files afterwards).
#   - Reasons are short codes, so stats.py can count them. The `feedback` text
#     is what the next attempt sees: trimmed to the last lines of test output,
#     never the whole log.
#   - The test command runs with the same Python that runs the farm, so the
#     demo works on Windows, Linux and macOS with no extra setup.
# =============================================================================

from __future__ import annotations

import posixpath
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path

from . import sandbox as docker_sandbox

MIN_LINES_FOR_SHRINK_CHECK = 20   # tiny files may legitimately shrink a lot
MAX_SHRINK_FRACTION = 0.60        # new file must keep at least 60% of the lines
FEEDBACK_MAX_LINES = 30
FEEDBACK_MAX_CHARS = 2000

# Phrases that mean the model skipped writing code.
PLACEHOLDER_RE = re.compile(
    r"rest of (the )?(code|file)|existing code|remaining (code|implementation)|"
    r"^\s*(#|//)\s*\.\.\.\s*$|\.\.\.\s*(unchanged|omitted)",
    re.IGNORECASE | re.MULTILINE,
)

IGNORE_ON_COPY = shutil.ignore_patterns(
    ".git", "__pycache__", ".pytest_cache", ".farm", "venv", ".venv", "node_modules"
)


@dataclass
class Verdict:
    passed: bool
    reason: str      # short code, see header
    feedback: str    # human text fed to the next attempt ("" when passed)


def _fail(reason: str, feedback: str) -> Verdict:
    return Verdict(False, reason, feedback)


def _normalize(path: str) -> str | None:
    """Clean a repo-relative path. None means it is unsafe."""
    p = path.replace("\\", "/").strip()
    if not p or p.startswith("/") or re.match(r"^[A-Za-z]:", p):
        return None
    p = posixpath.normpath(p)
    if p == ".." or p.startswith("../"):
        return None
    return p


def check_patch(repo: Path, task: dict, files: dict[str, str]) -> Verdict | None:
    """Run the cheap static checks. Returns a failing Verdict, or None if OK."""
    if not files:
        return _fail("empty_patch",
                     "Your answer contained no files in the required "
                     "'### FILE: path' + code block format.")

    allowed = {_normalize(p) for p in task["files_allowed"]}
    for raw_path, content in files.items():
        path = _normalize(raw_path)
        if path is None:
            return _fail("bad_path", f"Unsafe path: {raw_path}")
        if path not in allowed:
            return _fail("not_allowed",
                         f"You edited {raw_path}, which is not allowed. "
                         f"Allowed files: {sorted(a for a in allowed if a)}")
        if PLACEHOLDER_RE.search(content):
            return _fail("placeholder",
                         f"{raw_path} contains a placeholder like 'rest of the code'. "
                         "Write the complete file.")
        old = repo / path
        if old.is_file():
            old_lines = len(old.read_text(encoding="utf-8").splitlines())
            new_lines = len(content.splitlines())
            if old_lines >= MIN_LINES_FOR_SHRINK_CHECK and \
                    new_lines < old_lines * MAX_SHRINK_FRACTION:
                return _fail("shrunk",
                             f"{raw_path} went from {old_lines} to {new_lines} lines. "
                             "Do not delete existing code. Return the complete file.")
    return None


def _trim(output: str) -> str:
    lines = output.strip().splitlines()[-FEEDBACK_MAX_LINES:]
    return "\n".join(lines)[-FEEDBACK_MAX_CHARS:]


def run_tests(sandbox: Path, test_cmd: str, timeout_s: int,
              docker: dict | None = None) -> Verdict:
    """Run the task's test command inside the sandbox copy.

    With `docker` (see sandbox.py) the command runs in a container with no
    network and limited memory; otherwise on the host, as before.
    """
    argv = shlex.split(test_cmd)
    if docker is None and argv and argv[0] in ("python", "python3"):
        argv[0] = sys.executable
    try:
        if docker is not None:
            proc = docker_sandbox.run(docker, sandbox, argv, timeout_s)
        else:
            proc = subprocess.run(argv, cwd=sandbox, capture_output=True, text=True,
                                  timeout=timeout_s)
    except subprocess.TimeoutExpired:
        return _fail("timeout", f"The tests did not finish within {timeout_s} seconds.")
    except FileNotFoundError:
        return _fail("tests_failed", f"Test command not found: {argv[0]}")

    if proc.returncode == 0:
        return Verdict(True, "ok", "")
    return _fail("tests_failed", _trim(proc.stdout + "\n" + proc.stderr))


def evaluate(repo: str | Path, task: dict, files: dict[str, str],
             timeout_s: int = 60, docker: dict | None = None,
             repo_lock: threading.RLock | None = None) -> Verdict:
    """Full gatekeeper pipeline. Never modifies `repo`."""
    repo = Path(repo)
    early = check_patch(repo, task, files)
    if early is not None:
        return early

    with tempfile.TemporaryDirectory(prefix="farm-sandbox-") as tmp:
        sandbox = Path(tmp) / "repo"
        with repo_lock or threading.RLock():   # no commit may happen while we copy
            shutil.copytree(repo, sandbox, ignore=IGNORE_ON_COPY)
        for raw_path, content in files.items():
            target = sandbox / _normalize(raw_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        return run_tests(sandbox, task["test_cmd"], timeout_s, docker)
