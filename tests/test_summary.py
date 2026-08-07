from app.models import Allocation
from tests.conftest import make_user, make_utility_type, make_beneficiary, make_meter, login


def test_summary_shows_allocations_only(client, db):
    admin = make_user(db, "Ada", "ada@example.com", "pw", "admin")
    power = make_utility_type(db, "Power")
    water = make_utility_type(db, "Water")
    beneficiary = make_beneficiary(db, "Jane Doe")
    power_meter = make_meter(db, beneficiary, power, "PM-001")
    water_meter = make_meter(db, beneficiary, water, "WM-001")

    db.session.add(Allocation(meter_id=power_meter.id, quarter=2, year=2026, amount=300000, created_by_id=admin.id))
    db.session.add(Allocation(meter_id=water_meter.id, quarter=2, year=2026, amount=100000, created_by_id=admin.id))
    # another quarter - must be excluded
    db.session.add(Allocation(meter_id=power_meter.id, quarter=3, year=2026, amount=999000, created_by_id=admin.id))
    db.session.commit()

    login(client, "ada@example.com", "pw")
    body = client.get("/admin/summary?year=2026&quarter=2").data.decode()

    assert "UGX 400,000" in body  # total allocated
    assert "UGX 300,000" in body  # power
    assert "999,000" not in body
    assert "Spent" not in body
    assert "Balance" not in body
    assert "Awaiting Approval" not in body
