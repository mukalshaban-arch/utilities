"""Financial-year quarters.

The financial year runs 1 July - 30 June:

    Q1 = Jul, Aug, Sep
    Q2 = Oct, Nov, Dec
    Q3 = Jan, Feb, Mar
    Q4 = Apr, May, Jun

A financial year is labelled by the calendar year in which it starts, so any
date from July 2026 to June 2027 belongs to financial year 2026.
"""

from datetime import date

QUARTER_MONTHS = {
    1: ("Jul", "Aug", "Sep"),
    2: ("Oct", "Nov", "Dec"),
    3: ("Jan", "Feb", "Mar"),
    4: ("Apr", "May", "Jun"),
}


def current_period(today=None):
    """Return (financial_year, quarter) for a calendar date (defaults to today)."""
    today = today or date.today()
    quarter = ((today.month - 7) % 12) // 3 + 1
    year = today.year if today.month >= 7 else today.year - 1
    return year, quarter


def quarter_span(quarter):
    """Short label of the months in a quarter, e.g. 'Jul-Sep'."""
    months = QUARTER_MONTHS.get(quarter)
    return f"{months[0]}-{months[2]}" if months else ""
