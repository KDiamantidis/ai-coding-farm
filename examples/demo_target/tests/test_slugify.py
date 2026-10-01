from textutils import slugify


def test_punctuation_is_removed():
    assert slugify("Hello, World!") == "hello-world"


def test_extra_spaces_collapse():
    assert slugify("  Multiple   spaces ") == "multiple-spaces"


def test_symbols_become_one_dash():
    assert slugify("C++ & Rust") == "c-rust"
