import re

from app.models import Allocation
from tests.conftest import make_user, make_utility_type, make_beneficiary, make_meter, login


def rows_of(html):
    """Beneficiary column values from the report table body, in display order."""
    body = html.split("<tbody>")[1].split("</tbody>")[0]
    return re.findall(r"<td>([^<]+)</td>", body)[::6]  # 6 columns per row


def seed(db):
    admin = make_user(db, "Ada", "ada@example.com", "pw", "admin")
    power = make_utility_type(db, "Power")
    water = make_utility_type(db, "Water")

    director = make_beneficiary(db, "Zara Director", position="Director")
    head = make_beneficiary(db, "Alan Head", position="Section Head")
    hq = make_beneficiary(db, "HQ Account", position="Major Accounts", facility="HQ")

    meters = {
        "zara_power": make_meter(db, director, power, "PM-Z1"),
        "alan_water": make_meter(db, head, water, "WM-A1"),
        "hq_power": make_meter(db, hq, power, "PM-H1"),
    }
    amounts = {"zara_power": 300000, "alan_water": 100000, "hq_power": 500000}
    for key, meter in meters.items():
        db.session.add(
            Allocation(meter_id=meter.id, quarter=2, year=2026, amount=amounts[key], created_by_id=admin.id)
        )
    # a different quarter, to prove the quarter filter bites
    db.session.add(
        Allocation(meter_id=meters["zara_power"].id, quarter=3, year=2026, amount=777000, created_by_id=admin.id)
    )
    db.session.commit()
    return power, water


def test_report_filters_by_utility(client, db):
    power, _ = seed(db)
    login(client, "ada@example.com", "pw")

    body = client.get(f"/reports/quarterly?year=2026&quarter=2&utility_type_id={power.id}").data.decode()

    assert "PM-Z1" in body
    assert "PM-H1" in body
    assert "WM-A1" not in body  # water excluded
    assert "UGX 800,000" in body  # total of the two power rows


def test_report_filters_by_position(client, db):
    seed(db)
    login(client, "ada@example.com", "pw")

    body = client.get("/reports/quarterly?year=2026&quarter=2&position=Major+Accounts").data.decode()

    assert "HQ Account - HQ" in body
    assert "Zara Director" not in body
    assert "Alan Head" not in body


def test_report_filters_by_name(client, db):
    seed(db)
    login(client, "ada@example.com", "pw")

    body = client.get("/reports/quarterly?year=2026&quarter=2&name=zara").data.decode()

    assert "Zara Director" in body
    assert "Alan Head" not in body


def test_report_filters_by_quarter_and_all_quarters(client, db):
    seed(db)
    login(client, "ada@example.com", "pw")

    q2 = client.get("/reports/quarterly?year=2026&quarter=2").data.decode()
    assert "UGX 777,000" not in q2

    all_quarters = client.get("/reports/quarterly?year=2026&quarter=0").data.decode()
    assert "UGX 777,000" in all_quarters
    assert "all quarters" in all_quarters


def test_report_sorting_by_allocated(client, db):
    seed(db)
    login(client, "ada@example.com", "pw")

    asc = rows_of(client.get("/reports/quarterly?year=2026&quarter=2&sort=allocated&direction=asc").data.decode())
    desc = rows_of(client.get("/reports/quarterly?year=2026&quarter=2&sort=allocated&direction=desc").data.decode())

    assert asc == ["Alan Head", "Zara Director", "HQ Account - HQ"]  # 100k, 300k, 500k
    assert desc == list(reversed(asc))


def test_report_sorting_by_name(client, db):
    seed(db)
    login(client, "ada@example.com", "pw")

    asc = rows_of(client.get("/reports/quarterly?year=2026&quarter=2&sort=beneficiary&direction=asc").data.decode())
    assert asc == ["Alan Head", "HQ Account - HQ", "Zara Director"]


def test_summary_totals_respect_filters(client, db):
    power, _ = seed(db)
    login(client, "ada@example.com", "pw")

    body = client.get(f"/admin/summary?year=2026&quarter=2&utility_type_id={power.id}").data.decode()

    assert "UGX 800,000" in body  # only power allocations counted
    assert "Alan Head" not in body or "UGX 100,000" not in body


def test_summary_filters_by_position(client, db):
    seed(db)
    login(client, "ada@example.com", "pw")

    body = client.get("/admin/summary?year=2026&quarter=2&position=Director").data.decode()

    assert "Zara Director" in body
    assert "HQ Account" not in body
    assert "UGX 300,000" in body
