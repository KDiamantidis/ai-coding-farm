# =============================================================================
# FILE:    tests/test_worker.py
# PURPOSE: The answer parser and the prompt builder.
# =============================================================================

from farm import worker


def test_parse_single_file():
    text = "### FILE: a.py\n```python\nx = 1\n```\n"
    assert worker.parse_files(text) == {"a.py": "x = 1\n"}


def test_parse_two_files_and_ignore_chatter():
    text = (
        "Sure, here you go!\n"
        "### FILE: a.py\n```python\nx = 1\n```\n"
        "some words\n"
        "### FILE: dir/b.py\n```\ny = 2\n```\n"
    )
    assert worker.parse_files(text) == {"a.py": "x = 1\n", "dir/b.py": "y = 2\n"}


def test_answer_without_the_format_gives_no_files():
    assert worker.parse_files("here is some code: x = 1") == {}


def test_prompt_contains_task_id_files_and_feedback(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n")
    task = {"id": "t1", "title": "T", "description": "D",
            "files_allowed": ["a.py"], "context_files": [], "test_cmd": "pytest"}
    text = "\n".join(m["content"] for m in
                     worker.build_messages(task, tmp_path, feedback="boom"))
    assert "TASK_ID: t1" in text
    assert "x = 1" in text
    assert "boom" in text
