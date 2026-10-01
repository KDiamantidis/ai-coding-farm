"""A shopping cart. Prices are integer cents."""


class Cart:
    def __init__(self):
        self.items = {}  # sku -> [price_cents, qty]

    def add(self, sku, price_cents, qty=1):
        self.items[sku] = [price_cents, qty]

    def remove(self, sku):
        del self.items[sku]

    def total(self):
        return sum(price * qty for price, qty in self.items.values())
