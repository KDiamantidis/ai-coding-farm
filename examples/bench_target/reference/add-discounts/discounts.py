"""Discount codes. All money is integer cents."""

CODES = {
    "SAVE10": ("percent", 10),
    "FIVE": ("flat", 500),
}


def apply_discount(total_cents, code):
    key = str(code).upper()
    if key not in CODES:
        raise ValueError(f"unknown code: {code}")
    kind, value = CODES[key]
    if kind == "percent":
        off = (total_cents * value + 50) // 100  # half up, integers only
    else:
        off = value
    return max(0, total_cents - off)
