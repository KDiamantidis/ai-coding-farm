# =============================================================================
# FILE:    dashboard.py
# PURPOSE: A small web page that shows how the models perform. It only READS
#          the SQLite log. All numbers come from farm/stats.py.
#
# RUN:     streamlit run dashboard.py -- --db .farm/demo.db
#
# DESIGN NOTES:
#   - No calculations here. If the dashboard and the terminal report ever
#     disagreed, one of them would be wrong; this way they cannot disagree.
#   - The interval column is a 95% Wilson interval. With few attempts it is
#     wide on purpose. Read it before you trust a pass rate.
# =============================================================================

from __future__ import annotations

import argparse
import sys

import pandas as pd
import streamlit as st

from farm import db, stats


def parse_args() -> argparse.Namespace:
    # Streamlit passes our own flags after "--".
    p = argparse.ArgumentParser()
    p.add_argument("--db", default="farm.db")
    args, _ = p.parse_known_args(sys.argv[1:])
    return args


def main() -> None:
    args = parse_args()
    st.set_page_config(page_title="AI Coding Farm", layout="wide")
    st.title("AI Coding Farm")
    st.caption(f"Data source: {args.db}")

    conn = db.connect(args.db)
    tasks = stats.task_table(conn)
    if not tasks:
        st.info("No tasks yet. Run `python -m farm demo` first.")
        return

    done = sum(t["status"] == "done" for t in tasks)
    attempts = sum(t["attempts"] for t in tasks)
    c1, c2, c3 = st.columns(3)
    c1.metric("Tasks done", f"{done} / {len(tasks)}")
    c2.metric("Attempts used", attempts)
    c3.metric("Attempts per task", f"{attempts / len(tasks):.1f}")

    st.subheader("Models")
    models = pd.DataFrame(stats.model_table(conn))
    if models.empty:
        st.write("No attempts logged yet.")
    else:
        models["95% interval"] = models.apply(
            lambda r: f"{r['ci_low']:.0%} - {r['ci_high']:.0%}", axis=1)
        models["pass_rate_pct"] = models["pass_rate"] * 100  # 0-1 -> 0-100 for display
        shown = models[["model", "attempts", "passes", "pass_rate_pct",
                        "95% interval", "median_latency_s", "tokens_per_pass"]]
        st.dataframe(
            shown,
            hide_index=True,
            column_config={"pass_rate_pct": st.column_config.ProgressColumn(
                "pass rate", min_value=0, max_value=100, format="%.0f%%")},
        )
        st.bar_chart(models.set_index("model")["pass_rate"])
        st.caption("A short run gives wide intervals. Do not rank two models "
                   "whose intervals overlap.")

    left, right = st.columns(2)
    with left:
        st.subheader("Why attempts failed")
        reasons = pd.DataFrame(stats.reason_table(conn))
        if reasons.empty:
            st.write("No failures.")
        else:
            st.bar_chart(reasons.set_index("reason")["n"])
    with right:
        st.subheader("API errors")
        errors = pd.DataFrame(stats.call_errors(conn))
        st.dataframe(errors, hide_index=True)

    st.subheader("Tasks")
    st.dataframe(pd.DataFrame(tasks), hide_index=True)


main()
