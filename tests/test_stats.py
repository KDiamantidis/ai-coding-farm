# =============================================================================
# FILE:    tests/test_stats.py
# PURPOSE: The interval maths and the per-model table.
#
# The Wilson numbers below are standard reference values:
#   8 of 10 -> [0.490, 0.943]      0 of 0 -> (0, 0)
# If the code disagrees with these, the code is wrong. Never edit the numbers.
# =============================================================================

from farm import db, stats


def test_wilson_reference_values():
    lo, hi = stats.wilson(8, 10)
    assert round(lo, 3) == 0.490
    assert round(hi, 3) == 0.943


def test_wilson_with_no_data():
    assert stats.wilson(0, 0) == (0.0, 0.0)


def test_wilson_stays_inside_zero_and_one():
    lo, hi = stats.wilson(10, 10)
    assert 0.0 <= lo <= hi <= 1.0
    lo, hi = stats.wilson(0, 10)
    assert lo == 0.0 and hi < 0.35


def test_model_table_counts_and_cost_per_pass(tmp_path):
    conn = db.connect(tmp_path / "s.db")
    db.add_task(conn, {"id": "a", "title": "A", "description": "d",
                       "files_allowed": ["x.py"], "test_cmd": "true"})
    for passed, reason in [(0, "tests_failed"), (1, "ok")]:
        db.log_attempt(conn, task_id="a", attempt_no=1, role="coder", model="m1",
                       passed=passed, reason=reason, tokens_in=100, tokens_out=50)
    row = stats.model_table(conn)[0]
    assert (row["attempts"], row["passes"], row["pass_rate"]) == (2, 1, 0.5)
    assert row["tokens_per_pass"] == 300          # 2 attempts x 150 tokens / 1 pass
    assert stats.reason_table(conn) == [{"reason": "tests_failed", "n": 1}]
