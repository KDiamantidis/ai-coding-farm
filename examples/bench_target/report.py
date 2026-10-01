"""Simple sales reports."""


def sales_csv(rows):
    """rows: list of dicts with sku, qty, price_cents. Returns CSV text."""
    lines = ["sku,qty,price"]
    for r in rows:
        lines.append(f"{r['sku']},{r['qty']},{r['price_cents'] / 100}")
    return "\n".join(lines) + "\n"
