import pytest

from inventory import Inventory


def make():
    inv = Inventory()
    inv.add_stock("A", 5)
    return inv


def test_reserve_ok():
    inv = make()
    assert inv.reserve("A", 3) is True
    assert inv.available("A") == 2


def test_reserve_too_much_changes_nothing():
    inv = make()
    assert inv.reserve("A", 6) is False
    assert inv.available("A") == 5


def test_reserve_exact_amount():
    inv = make()
    assert inv.reserve("A", 5) is True
    assert inv.available("A") == 0


def test_unknown_sku():
    inv = make()
    assert inv.reserve("ZZZ", 1) is False
    assert inv.available("ZZZ") == 0
    assert "ZZZ" not in inv.stock


def test_quantity_must_be_positive():
    inv = make()
    with pytest.raises(ValueError):
        inv.reserve("A", 0)
    with pytest.raises(ValueError):
        inv.reserve("A", -2)
