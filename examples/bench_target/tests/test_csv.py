from report import sales_csv


def test_empty():
    assert sales_csv([]) == "sku,qty,price\n"


def test_prices_have_two_decimals():
    rows = [{"sku": "A", "qty": 1, "price_cents": 1000},
            {"sku": "B", "qty": 2, "price_cents": 5}]
    assert sales_csv(rows) == "sku,qty,price\nA,1,10.00\nB,2,0.05\n"


def test_comma_and_quote_in_sku_are_escaped():
    rows = [{"sku": 'Cable, USB "C"', "qty": 1, "price_cents": 1250}]
    assert sales_csv(rows) == 'sku,qty,price\n"Cable, USB ""C""",1,12.50\n'


def test_newline_in_sku_is_quoted():
    rows = [{"sku": "a\nb", "qty": 1, "price_cents": 100}]
    assert sales_csv(rows) == 'sku,qty,price\n"a\nb",1,1.00\n'
