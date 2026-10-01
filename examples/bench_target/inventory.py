"""Stock levels per SKU."""


class Inventory:
    def __init__(self):
        self.stock = {}  # sku -> quantity

    def add_stock(self, sku, qty):
        self.stock[sku] = self.stock.get(sku, 0) + qty

    def reserve(self, sku, qty):
        self.stock[sku] -= qty
        return True
