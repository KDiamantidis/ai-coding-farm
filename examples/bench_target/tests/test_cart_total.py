import pytest

from cart import Cart


def make():
    c = Cart()
    c.add("A", 1005)
    return c


def test_total_without_code_is_unchanged():
    assert make().total() == 1005


def test_total_with_code():
    assert make().total("SAVE10") == 904
    assert make().total(code="FIVE") == 505


def test_unknown_code_raises():
    with pytest.raises(ValueError):
        make().total("BOGUS")
