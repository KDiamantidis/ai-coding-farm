import pytest

from cart import Cart
from checkout import OutOfStock, checkout
from inventory import Inventory


def setup():
    inv = Inventory()
    inv.add_stock("A", 5)
    inv.add_stock("B", 1)
    cart = Cart()
    cart.add("A", 1000, 2)
    cart.add("B", 500, 1)
    return cart, inv


def test_success_reserves_stock_and_returns_total():
    cart, inv = setup()
    result = checkout(cart, inv)
    assert result["total"] == 2500
    assert inv.available("A") == 3
    assert inv.available("B") == 0


def test_code_is_applied():
    cart, inv = setup()
    assert checkout(cart, inv, "SAVE10")["total"] == 2250


def test_out_of_stock_rolls_back_everything():
    cart, inv = setup()
    cart.add("B", 500, 1)          # now 2 of B, but only 1 in stock
    with pytest.raises(OutOfStock) as err:
        checkout(cart, inv)
    assert err.value.sku == "B"
    assert inv.available("A") == 5  # A was reserved first, must be given back
    assert inv.available("B") == 1


def test_bad_code_reserves_nothing():
    cart, inv = setup()
    with pytest.raises(ValueError):
        checkout(cart, inv, "BOGUS")
    assert inv.available("A") == 5
    assert inv.available("B") == 1


def test_empty_cart():
    result = checkout(Cart(), Inventory())
    assert result["total"] == 0
    assert result["reserved"] == []
