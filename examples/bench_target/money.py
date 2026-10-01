"""Money helpers. Prices are stored as integer cents."""


def parse_price(text):
    """'€12.50' -> 1250"""
    return int(float(text.replace("€", "")) * 100)


def format_price(cents):
    """1250 -> '€12.50'"""
    return "€" + str(cents / 100)
