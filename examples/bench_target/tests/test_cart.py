import pytest

from cart import Cart


def test_adding_same_sku_adds_quantity():
    c = Cart()
    c.add("A", 100, 2)
    c.add("A", 100, 3)
    assert c.total() == 500


def test_price_change_is_rejected():
    c = Cart()
    c.add("A", 100)
    with pytest.raises(ValueError):
        c.add("A", 150)


def test_quantity_must_be_positive():
    c = Cart()
    with pytest.raises(ValueError):
        c.add("A", 100, 0)
    with pytest.raises(ValueError):
        c.add("A", 100, -1)


def test_remove_missing_sku_is_ignored():
    c = Cart()
    c.remove("nope")
    assert c.total() == 0


def test_remove_existing():
    c = Cart()
    c.add("A", 100, 2)
    c.add("B", 50)
    c.remove("A")
    assert c.total() == 50
