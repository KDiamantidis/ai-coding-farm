# =============================================================================
# FILE:    farm/mockmodel.py
# PURPOSE: A fake model for the offline demo and the tests. Costs nothing and
#          needs no API key, so anyone can run the whole farm in a minute.
#
# HOW IT WORKS:
#   Model name "mock/<name>" answers with the text file
#       <mock_dir>/<task_id>.<name>.txt
#   The task id is read from the line "TASK_ID: <id>" in the prompt.
#   The special model "mock/error" always raises, to simulate an API outage.
#
# DESIGN NOTES:
#   The demo uses a "weak" and a "strong" mock. The weak one is wrong on some
#   tasks, so the report has real failures to show (not just a green wall).
# =============================================================================

from __future__ import annotations

import re
from pathlib import Path


class ModelError(Exception):
    """A model call failed (API error, timeout, missing mock file)."""


TASK_ID_RE = re.compile(r"TASK_ID:\s*(\S+)")


def complete(model: str, messages: list[dict], mock_dir: str | Path) -> tuple[str, int, int]:
    """Return (text, tokens_in, tokens_out) for a mock/<name> model."""
    name = model.split("/", 1)[1] if "/" in model else model
    if name == "error":
        raise ModelError("simulated outage (mock/error)")

    prompt = "\n".join(m["content"] for m in messages)
    match = TASK_ID_RE.search(prompt)
    if not match:
        raise ModelError("mock model could not find 'TASK_ID:' in the prompt")

    path = Path(mock_dir) / f"{match.group(1)}.{name}.txt"
    if not path.is_file():
        raise ModelError(f"no mock answer file: {path}")

    text = path.read_text(encoding="utf-8")
    # Rough token estimate (4 chars ~ 1 token). Good enough for a demo.
    return text, max(1, len(prompt) // 4), max(1, len(text) // 4)
