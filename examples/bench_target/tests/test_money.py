import pytest

from money import format_price, parse_price


def test_thousands_separator():
    assert parse_price("€1,234.50") == 123450


def test_float_trap():
    # 19.99 * 100 is 1998.999... in floating point
    assert parse_price(" 19.99 ") == 1999


def test_short_fraction_and_plain_number():
    assert parse_price("€0.1") == 10
    assert parse_price("7") == 700


def test_half_cent_rounds_up():
    assert parse_price("€0.005") == 1


def test_negative():
    assert parse_price("-€2.50") == -250


def test_bad_text():
    with pytest.raises(ValueError):
        parse_price("abc")


def test_format():
    assert format_price(123450) == "€1,234.50"
    assert format_price(5) == "€0.05"
    assert format_price(0) == "€0.00"
    assert format_price(-250) == "-€2.50"
