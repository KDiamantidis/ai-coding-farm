# =============================================================================
# FILE:    farm/worker.py
# PURPOSE: Build the prompt for one task and turn the model's answer into
#          {path: new_file_content}. It does NOT judge the answer (gatekeeper).
#
# EXPORTS:
#   build_messages(task, repo, feedback)  -> list of chat messages
#   parse_files(text)                     -> dict[str, str]
#
# ANSWER FORMAT the model must use (whole files, no diffs):
#
#   ### FILE: path/to/file.py
#   ```python
#   <full new content of the file>
#   ```
#
# DESIGN NOTES:
#   - Whole-file answers, not diffs. Small models are bad at writing correct
#     diffs. The price is that a model can quietly delete code, which is why
#     the gatekeeper rejects files that shrink or contain "rest of code".
#   - Every worker gets the same context: the task, the files it may edit, and
#     optional context files. No chat history is passed between attempts, only
#     the trimmed test output of the last failure.
# =============================================================================

from __future__ import annotations

import re
from pathlib import Path

SYSTEM_PROMPT = """You are a careful software engineer working inside an automated pipeline.
Rules:
- Change ONLY the files listed under "Files you may edit".
- Answer with the COMPLETE new content of each changed file. Never use "..." or
  comments like "rest of the code". Never shorten a file.
- Use exactly this format for each file, and write nothing else:

### FILE: path/to/file.py
```python
<complete file content>
```
"""

# ### FILE: <path> newline ```lang newline <content> newline ```
FILE_RE = re.compile(
    r"###\s*FILE:\s*(?P<path>\S+)\s*\r?\n```[a-zA-Z0-9_+-]*\r?\n(?P<body>.*?)\r?\n```",
    re.DOTALL,
)


def _read(repo: Path, rel: str) -> str:
    p = repo / rel
    return p.read_text(encoding="utf-8") if p.is_file() else "(file does not exist yet)"


def build_messages(task: dict, repo: str | Path, feedback: str | None = None) -> list[dict]:
    """Create the chat messages for one attempt."""
    repo = Path(repo)
    parts = [
        f"TASK_ID: {task['id']}",
        f"Title: {task['title']}",
        f"Description:\n{task['description']}",
        "Files you may edit:",
    ]
    for rel in task["files_allowed"]:
        parts.append(f"--- {rel} ---\n{_read(repo, rel)}")

    if task.get("context_files"):
        parts.append("Read-only context files (do not change them):")
        for rel in task["context_files"]:
            parts.append(f"--- {rel} ---\n{_read(repo, rel)}")

    parts.append(f"The change is checked by running: {task['test_cmd']}")

    if feedback:
        parts.append(
            "Your previous attempt was rejected. Fix exactly this problem:\n" + feedback
        )

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "\n\n".join(parts)},
    ]


def parse_files(text: str) -> dict[str, str]:
    """Extract {path: content} from a model answer. Empty dict if none found."""
    files: dict[str, str] = {}
    for m in FILE_RE.finditer(text):
        # If a model repeats a path, the last block wins.
        files[m.group("path").strip()] = m.group("body") + "\n"
    return files
