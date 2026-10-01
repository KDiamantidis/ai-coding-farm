"""All-or-nothing checkout."""


class OutOfStock(Exception):
    def __init__(self, sku):
        super().__init__(f"out of stock: {sku}")
        self.sku = sku


def checkout(cart, inventory, code=None):
    total = cart.total(code)  # raises ValueError for a bad code, before any reserve
    reserved = []
    for sku, (_price, qty) in cart.items.items():
        if not inventory.reserve(sku, qty):
            for done_sku, done_qty in reserved:
                inventory.add_stock(done_sku, done_qty)
            raise OutOfStock(sku)
        reserved.append((sku, qty))
    return {"total": total, "reserved": reserved}
