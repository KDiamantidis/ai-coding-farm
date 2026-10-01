import pytest

from orders import parse_line


def test_basic_line():
    assert parse_line("2 x SKU-1 @ €3.50") == ("SKU-1", 2, 350)


def test_compact_and_without_euro_sign():
    assert parse_line("2x SKU-1 @ 3.50") == ("SKU-1", 2, 350)


def test_capital_x_spaces_and_thousands():
    assert parse_line("  3 X abc @ €1,200.00 ") == ("abc", 3, 120000)


def test_zero_quantity():
    with pytest.raises(ValueError):
        parse_line("0 x A @ 1")


def test_garbage():
    with pytest.raises(ValueError):
        parse_line("hello")


def test_bad_price():
    with pytest.raises(ValueError):
        parse_line("2 x A @ abc")
