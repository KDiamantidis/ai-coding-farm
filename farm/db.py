# =============================================================================
# FILE:    farm/db.py
# PURPOSE: The SQLite database: task queue + a log of every attempt and call.
#
# TABLES:
#   tasks     one row per unit of work (status: pending/done/failed/blocked)
#   attempts  one row per try at a task (model, passed?, why, tokens, time)
#   calls     one row per raw model call, including API errors
#
# DESIGN NOTES:
#   - Plain sqlite3 from the standard library. No ORM: three tables, so the SQL
#     is shorter than the setup code an ORM would need.
#   - The log IS the dataset. report/dashboard only read these tables. Nothing
#     else keeps statistics, so numbers cannot drift apart.
#   - JSON lists (files_allowed, depends_on) are stored as TEXT and decoded in
#     get_task(). SQLite has no array type and we never query inside them.
# =============================================================================

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id            TEXT PRIMARY KEY,
    title         TEXT NOT NULL,
    description   TEXT NOT NULL,
    files_allowed TEXT NOT NULL,          -- JSON list of repo-relative paths
    context_files TEXT NOT NULL DEFAULT '[]',
    test_cmd      TEXT NOT NULL,
    depends_on    TEXT NOT NULL DEFAULT '[]',
    status        TEXT NOT NULL DEFAULT 'pending',
    created_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS attempts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id     TEXT NOT NULL REFERENCES tasks(id),
    attempt_no  INTEGER NOT NULL,
    role        TEXT NOT NULL,
    model       TEXT NOT NULL,
    passed      INTEGER NOT NULL,         -- 0 or 1
    reason      TEXT NOT NULL,            -- ok / tests_failed / not_allowed ...
    tokens_in   INTEGER NOT NULL DEFAULT 0,
    tokens_out  INTEGER NOT NULL DEFAULT 0,
    latency_s   REAL    NOT NULL DEFAULT 0,
    detail      TEXT,                     -- start of the model's answer when it was rejected
    created_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS calls (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id     TEXT,
    attempt_no  INTEGER,
    role        TEXT NOT NULL,
    model       TEXT NOT NULL,
    ok          INTEGER NOT NULL,         -- 0 = API error / outage
    error       TEXT,
    tokens_in   INTEGER NOT NULL DEFAULT 0,
    tokens_out  INTEGER NOT NULL DEFAULT 0,
    latency_s   REAL    NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


def connect(path: str | Path) -> sqlite3.Connection:
    """Open (and create if needed) the database. Rows behave like dicts."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    # Older database files have no 'detail' column yet.
    cols = [r[1] for r in conn.execute("PRAGMA table_info(attempts)")]
    if "detail" not in cols:
        conn.execute("ALTER TABLE attempts ADD COLUMN detail TEXT")
        conn.commit()
    return conn


def add_task(conn: sqlite3.Connection, task: dict) -> None:
    """Insert one task. Re-adding the same id is a no-op (idempotent)."""
    for key in ("id", "title", "description", "files_allowed", "test_cmd"):
        if key not in task:
            raise ValueError(f"task is missing '{key}': {task.get('id', task)}")
    conn.execute(
        "INSERT OR IGNORE INTO tasks "
        "(id, title, description, files_allowed, context_files, test_cmd, depends_on) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            task["id"],
            task["title"],
            task["description"],
            json.dumps(task["files_allowed"]),
            json.dumps(task.get("context_files", [])),
            task["test_cmd"],
            json.dumps(task.get("depends_on", [])),
        ),
    )
    conn.commit()


def get_task(conn: sqlite3.Connection, task_id: str) -> dict:
    """Return one task as a plain dict with the JSON columns decoded."""
    row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if row is None:
        raise KeyError(task_id)
    task = dict(row)
    for key in ("files_allowed", "context_files", "depends_on"):
        task[key] = json.loads(task[key])
    return task


def all_tasks(conn: sqlite3.Connection) -> list[dict]:
    """All tasks in creation order."""
    ids = [r["id"] for r in conn.execute("SELECT id FROM tasks ORDER BY rowid")]
    return [get_task(conn, i) for i in ids]


def set_status(conn: sqlite3.Connection, task_id: str, status: str) -> None:
    conn.execute("UPDATE tasks SET status = ? WHERE id = ?", (status, task_id))
    conn.commit()


def log_attempt(conn, *, task_id, attempt_no, role, model, passed, reason,
                tokens_in=0, tokens_out=0, latency_s=0.0, detail=None) -> None:
    conn.execute(
        "INSERT INTO attempts (task_id, attempt_no, role, model, passed, reason, "
        "tokens_in, tokens_out, latency_s, detail) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (task_id, attempt_no, role, model, int(passed), reason,
         tokens_in, tokens_out, latency_s, detail),
    )
    conn.commit()


def log_call(conn, *, task_id, attempt_no, role, model, ok, error=None,
             tokens_in=0, tokens_out=0, latency_s=0.0) -> None:
    conn.execute(
        "INSERT INTO calls (task_id, attempt_no, role, model, ok, error, "
        "tokens_in, tokens_out, latency_s) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (task_id, attempt_no, role, model, int(ok), error,
         tokens_in, tokens_out, latency_s),
    )
    conn.commit()
