import pytest

from discounts import apply_discount


def test_percent_discount():
    assert apply_discount(1000, "SAVE10") == 900


def test_percent_rounds_half_up():
    # 10% of 1005 is 100.5 cents. Half rounds UP, so the discount is 101.
    assert apply_discount(1005, "SAVE10") == 904
    assert apply_discount(5, "SAVE10") == 4
    assert apply_discount(1004, "SAVE10") == 904
    assert apply_discount(1006, "SAVE10") == 905


def test_flat_discount_never_goes_below_zero():
    assert apply_discount(1000, "FIVE") == 500
    assert apply_discount(300, "FIVE") == 0


def test_code_is_case_insensitive():
    assert apply_discount(1000, "save10") == 900


def test_unknown_code():
    with pytest.raises(ValueError):
        apply_discount(1000, "BOGUS")


def test_zero_total():
    assert apply_discount(0, "SAVE10") == 0
