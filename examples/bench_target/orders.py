"""Parse order lines typed by a person."""
from money import parse_price


def parse_line(line):
    """'2 x SKU-1 @ €3.50' -> ('SKU-1', 2, 350)"""
    qty_part, rest = line.split(" x ")
    sku, price = rest.split(" @ ")
    return sku, int(qty_part), parse_price(price)
