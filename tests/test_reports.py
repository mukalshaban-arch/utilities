from app.models import Allocation
from tests.conftest import make_user, make_utility_type, make_beneficiary, make_meter, login


def test_quarterly_report_lists_each_allocated_number(client, db):
    admin = make_user(db, "Ada", "ada@example.com", "pw", "admin")
    power = make_utility_type(db, "Power")
    beneficiary = make_beneficiary(db, "Jane Doe")
    meter_1 = make_meter(db, beneficiary, power, "PM-001")
    meter_2 = make_meter(db, beneficiary, power, "PM-002")

    db.session.add(Allocation(meter_id=meter_1.id, quarter=2, year=2026, amount=200000, created_by_id=admin.id))
    db.session.add(Allocation(meter_id=meter_2.id, quarter=2, year=2026, amount=100000, created_by_id=admin.id))
    db.session.commit()

    login(client, "ada@example.com", "pw")
    body = client.get("/reports/quarterly?year=2026&quarter=2").data.decode()

    assert "PM-001" in body
    assert "PM-002" in body
    assert "UGX 200,000" in body
    assert "UGX 300,000" in body  # total row
    assert "Spent" not in body
    assert "Balance" not in body


def test_quarterly_pdf_export(client, db):
    admin = make_user(db, "Ada", "ada@example.com", "pw", "admin")
    power = make_utility_type(db, "Power")
    beneficiary = make_beneficiary(db, "Jane Doe")
    meter = make_meter(db, beneficiary, power, "PM-001")
    db.session.add(Allocation(meter_id=meter.id, quarter=2, year=2026, amount=100000, created_by_id=admin.id))
    db.session.commit()

    login(client, "ada@example.com", "pw")
    resp = client.get("/reports/quarterly.pdf?year=2026&quarter=2")

    assert resp.status_code == 200
    assert resp.mimetype == "application/pdf"
    assert resp.data.startswith(b"%PDF-")
    assert "allocations_2026_Q2.pdf" in resp.headers["Content-Disposition"]


def test_pdf_respects_filters(client, db):
    admin = make_user(db, "Ada", "ada@example.com", "pw", "admin")
    power = make_utility_type(db, "Power")
    water = make_utility_type(db, "Water")
    beneficiary = make_beneficiary(db, "Jane Doe")
    power_meter = make_meter(db, beneficiary, power, "PM-001")
    water_meter = make_meter(db, beneficiary, water, "WM-001")
    db.session.add(Allocation(meter_id=power_meter.id, quarter=2, year=2026, amount=100000, created_by_id=admin.id))
    db.session.add(Allocation(meter_id=water_meter.id, quarter=2, year=2026, amount=50000, created_by_id=admin.id))
    db.session.commit()

    login(client, "ada@example.com", "pw")
    unfiltered = client.get("/reports/quarterly.pdf?year=2026&quarter=2")
    filtered = client.get(f"/reports/quarterly.pdf?year=2026&quarter=2&utility_type_id={power.id}")

    assert filtered.status_code == 200
    # the filtered PDF has one fewer row, so it must be a different document
    assert len(filtered.data) < len(unfiltered.data)


def test_quarterly_csv_export(client, db):
    admin = make_user(db, "Ada", "ada@example.com", "pw", "admin")
    power = make_utility_type(db, "Power")
    beneficiary = make_beneficiary(db, "HQ Account", position="Major Accounts", facility="HQ")
    meter = make_meter(db, beneficiary, power, "PM-001")
    db.session.add(Allocation(meter_id=meter.id, quarter=2, year=2026, amount=100000, created_by_id=admin.id))
    db.session.commit()

    login(client, "ada@example.com", "pw")
    resp = client.get("/reports/quarterly.csv?year=2026&quarter=2")

    assert resp.status_code == 200
    assert resp.mimetype == "text/csv"
    assert b"HQ Account - HQ" in resp.data
    assert b"PM-001" in resp.data
    assert b"Spent" not in resp.data
