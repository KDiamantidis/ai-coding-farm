from textutils import word_count


def test_any_whitespace_counts_as_a_separator():
    assert word_count("a  b\nc") == 3


def test_empty_string_has_no_words():
    assert word_count("") == 0


def test_single_word():
    assert word_count("one") == 1
