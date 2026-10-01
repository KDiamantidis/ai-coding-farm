"""Parse order lines typed by a person."""
import re

from money import parse_price

LINE_RE = re.compile(r"^\s*(\d+)\s*[xX]\s*(\S+)\s*@\s*(\S+)\s*$")


def parse_line(line):
    """'2 x SKU-1 @ €3.50' -> ('SKU-1', 2, 350)"""
    m = LINE_RE.match(line)
    if not m:
        raise ValueError(f"bad order line: {line!r}")
    qty = int(m.group(1))
    if qty <= 0:
        raise ValueError("qty must be positive")
    return m.group(2), qty, parse_price(m.group(3))
