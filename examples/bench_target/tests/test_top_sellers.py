from report import top_sellers

ROWS = [
    {"sku": "B", "qty": 2, "price_cents": 100},
    {"sku": "A", "qty": 2, "price_cents": 100},
    {"sku": "C", "qty": 1, "price_cents": 100},
    {"sku": "C", "qty": 4, "price_cents": 100},
]


def test_duplicates_are_added_and_sorted():
    assert top_sellers(ROWS, 3) == [("C", 5), ("A", 2), ("B", 2)]


def test_ties_are_sorted_by_sku():
    assert top_sellers(ROWS[:2], 2) == [("A", 2), ("B", 2)]


def test_n_limits_the_result():
    assert top_sellers(ROWS, 1) == [("C", 5)]


def test_n_zero_or_negative():
    assert top_sellers(ROWS, 0) == []
    assert top_sellers(ROWS, -3) == []


def test_empty_rows():
    assert top_sellers([], 5) == []


def test_input_is_not_changed():
    rows = [dict(r) for r in ROWS]
    top_sellers(rows, 2)
    assert rows == ROWS
