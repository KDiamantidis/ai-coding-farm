from textutils import truncate


def test_long_text_is_cut_to_the_limit():
    result = truncate("hello world", 8)
    assert result == "hello..."
    assert len(result) == 8


def test_short_text_is_unchanged():
    assert truncate("short", 10) == "short"


def test_text_exactly_at_the_limit_is_unchanged():
    assert truncate("hello world", 11) == "hello world"
