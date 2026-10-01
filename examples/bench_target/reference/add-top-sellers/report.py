"""Simple sales reports."""


def _cell(value):
    text = str(value)
    if any(ch in text for ch in ',"\n'):
        text = '"' + text.replace('"', '""') + '"'
    return text


def sales_csv(rows):
    """rows: list of dicts with sku, qty, price_cents. Returns CSV text."""
    lines = ["sku,qty,price"]
    for r in rows:
        cents = r["price_cents"]
        price = f"{cents // 100}.{cents % 100:02d}"
        lines.append(",".join([_cell(r["sku"]), _cell(r["qty"]), price]))
    return "\n".join(lines) + "\n"


def top_sellers(rows, n):
    """Return the first n (sku, total_qty) pairs, best seller first."""
    totals = {}
    for r in rows:
        totals[r["sku"]] = totals.get(r["sku"], 0) + r["qty"]
    ranked = sorted(totals.items(), key=lambda pair: (-pair[1], pair[0]))
    return ranked[:max(n, 0)]
