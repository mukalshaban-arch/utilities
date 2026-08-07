from datetime import date

from app.fiscal import current_period, quarter_span


def test_financial_quarters_map_to_the_right_months():
    # Q1 = Jul-Sep
    assert current_period(date(2026, 7, 1)) == (2026, 1)
    assert current_period(date(2026, 9, 30)) == (2026, 1)
    # Q2 = Oct-Dec
    assert current_period(date(2026, 10, 1)) == (2026, 2)
    assert current_period(date(2026, 12, 31)) == (2026, 2)
    # Q3 = Jan-Mar (still the financial year that started the previous July)
    assert current_period(date(2027, 1, 1)) == (2026, 3)
    assert current_period(date(2027, 3, 31)) == (2026, 3)
    # Q4 = Apr-Jun
    assert current_period(date(2027, 4, 1)) == (2026, 4)
    assert current_period(date(2027, 6, 30)) == (2026, 4)


def test_financial_year_is_labelled_by_its_start_year():
    # A whole financial year (Jul 2026 - Jun 2027) is year 2026 throughout.
    assert current_period(date(2026, 8, 15))[0] == 2026
    assert current_period(date(2027, 2, 15))[0] == 2026
    # The next financial year begins in July.
    assert current_period(date(2027, 7, 1)) == (2027, 1)


def test_quarter_span_labels():
    assert quarter_span(1) == "Jul-Sep"
    assert quarter_span(2) == "Oct-Dec"
    assert quarter_span(3) == "Jan-Mar"
    assert quarter_span(4) == "Apr-Jun"
