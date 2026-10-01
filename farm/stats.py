# =============================================================================
# FILE:    farm/stats.py
# PURPOSE: Turn the attempt log into numbers. The ONLY place statistics are
#          computed. The CLI report and the dashboard both call these functions.
#
# EXPORTS:
#   wilson(passes, n)        -> (low, high) 95% interval for a pass rate
#   model_table(conn)        -> per-model rows
#   reason_table(conn)       -> why attempts failed (counts)
#   task_table(conn)         -> per-task outcome
#   call_errors(conn)        -> API errors per model
#
# DESIGN NOTES:
#   - A pass rate on 3 tasks is not a measurement. So every rate comes with a
#     Wilson 95% interval. With few attempts the interval is wide, and that
#     is the honest answer ("we cannot tell these two models apart yet").
#   - "tokens per pass" = all tokens a model spent / how many attempts passed.
#     It is cost-per-success, which is what you actually care about when the
#     budget is zero and free-tier limits are the real currency.
# =============================================================================

from __future__ import annotations

import math
import statistics


def wilson(passes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a proportion. (0, 0) when n == 0."""
    if n == 0:
        return (0.0, 0.0)
    p = passes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def model_table(conn) -> list[dict]:
    """One row per model: attempts, passes, rate with interval, speed, cost."""
    rows = conn.execute(
        "SELECT model, passed, tokens_in + tokens_out AS tokens, latency_s "
        "FROM attempts WHERE model != '(none)'"
    ).fetchall()

    by_model: dict[str, list] = {}
    for r in rows:
        by_model.setdefault(r["model"], []).append(r)

    table = []
    for model, items in sorted(by_model.items()):
        n = len(items)
        passes = sum(i["passed"] for i in items)
        lo, hi = wilson(passes, n)
        total_tokens = sum(i["tokens"] for i in items)
        table.append({
            "model": model,
            "attempts": n,
            "passes": passes,
            "pass_rate": passes / n,
            "ci_low": lo,
            "ci_high": hi,
            "median_latency_s": statistics.median(i["latency_s"] for i in items),
            "tokens_per_pass": (total_tokens / passes) if passes else None,
        })
    return table


def reason_table(conn) -> list[dict]:
    """Failure reasons, most common first. Passing attempts are excluded."""
    rows = conn.execute(
        "SELECT reason, COUNT(*) AS n FROM attempts WHERE passed = 0 "
        "GROUP BY reason ORDER BY n DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def task_table(conn) -> list[dict]:
    """Per task: final status, attempts used, which model finally passed it."""
    out = []
    for t in conn.execute("SELECT id, title, status FROM tasks ORDER BY rowid"):
        attempts = conn.execute(
            "SELECT model, passed FROM attempts WHERE task_id = ? ORDER BY attempt_no",
            (t["id"],),
        ).fetchall()
        winner = next((a["model"] for a in attempts if a["passed"]), None)
        out.append({
            "id": t["id"],
            "title": t["title"],
            "status": t["status"],
            "attempts": len(attempts),
            "passed_by": winner,
        })
    return out


def call_errors(conn) -> list[dict]:
    """API failures per model (outages, rate limits). Separate from bad patches."""
    rows = conn.execute(
        "SELECT model, COUNT(*) AS calls, SUM(1 - ok) AS errors "
        "FROM calls GROUP BY model ORDER BY errors DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def format_report(conn) -> str:
    """Plain-text report for the terminal."""
    lines = ["", "MODELS", "-" * 78,
             f"{'model':<28}{'att':>5}{'pass':>6}{'rate':>7}  {'95% CI':<13}"
             f"{'med s':>7}{'tok/pass':>10}"]
    for m in model_table(conn):
        tpp = f"{m['tokens_per_pass']:.0f}" if m["tokens_per_pass"] else "-"
        lines.append(
            f"{m['model']:<28}{m['attempts']:>5}{m['passes']:>6}"
            f"{m['pass_rate']:>7.0%}  "
            f"[{m['ci_low']:.2f}-{m['ci_high']:.2f}]".ljust(61)
            + f"{m['median_latency_s']:>7.2f}{tpp:>10}"
        )
    lines += ["", "WHY ATTEMPTS FAILED", "-" * 78]
    for r in reason_table(conn) or [{"reason": "(no failures)", "n": 0}]:
        lines.append(f"{r['reason']:<28}{r['n']:>5}")
    lines += ["", "TASKS", "-" * 78]
    for t in task_table(conn):
        lines.append(f"{t['id']:<22}{t['status']:<9}{t['attempts']:>2} attempt(s)"
                     f"   passed by: {t['passed_by'] or '-'}")
    errs = [e for e in call_errors(conn) if e["errors"]]
    if errs:
        lines += ["", "API ERRORS", "-" * 78]
        lines += [f"{e['model']:<28}{e['errors']:>5} of {e['calls']} calls" for e in errs]
    lines.append("")
    return "\n".join(lines)
