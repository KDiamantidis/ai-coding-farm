from inventory import Inventory


def test_low_stock_includes_equal_and_zero_sorted():
    inv = Inventory()
    inv.add_stock("C", 3)
    inv.add_stock("A", 10)
    inv.add_stock("B", 0)
    inv.add_stock("D", 4)
    assert inv.low_stock(3) == ["B", "C"]


def test_nothing_low():
    inv = Inventory()
    inv.add_stock("A", 10)
    assert inv.low_stock(2) == []


def test_empty_inventory():
    assert Inventory().low_stock(5) == []
