from app.models import Allocation, Beneficiary
from tests.conftest import make_user, make_utility_type, make_beneficiary, make_meter, login


def test_search_matches_partial_name(client, db):
    make_user(db, "Ada", "ada@example.com", "pw", "admin")
    make_beneficiary(db, "Jane Doe", position="Director")
    make_beneficiary(db, "HQ Account", position="Major Accounts", facility="HQ")
    login(client, "ada@example.com", "pw")

    results = client.get("/admin/beneficiaries/search?q=jan").get_json()

    assert len(results) == 1
    assert results[0]["name"] == "Jane Doe"
    assert results[0]["position"] == "Director"


def test_search_is_capped_so_the_register_can_grow(client, db):
    make_user(db, "Ada", "ada@example.com", "pw", "admin")
    for i in range(60):
        db.session.add(Beneficiary(name=f"Person {i:03d}", position="Other"))
    db.session.commit()
    login(client, "ada@example.com", "pw")

    results = client.get("/admin/beneficiaries/search?q=person").get_json()
    assert len(results) == 10  # capped, not 60


def test_search_empty_term_returns_nothing(client, db):
    make_user(db, "Ada", "ada@example.com", "pw", "admin")
    make_beneficiary(db, "Jane Doe")
    login(client, "ada@example.com", "pw")

    assert client.get("/admin/beneficiaries/search?q=").get_json() == []


def test_meters_endpoint_returns_numbers_with_existing_amounts(client, db):
    admin = make_user(db, "Ada", "ada@example.com", "pw", "admin")
    power = make_utility_type(db, "Power")
    water = make_utility_type(db, "Water")
    beneficiary = make_beneficiary(db, "Jane Doe")
    power_meter = make_meter(db, beneficiary, power, "PM-001")
    water_meter = make_meter(db, beneficiary, water, "WM-001")
    db.session.add(
        Allocation(meter_id=power_meter.id, quarter=3, year=2026, amount=500000, created_by_id=admin.id)
    )
    db.session.commit()
    login(client, "ada@example.com", "pw")

    meters = client.get(
        f"/admin/beneficiaries/{beneficiary.id}/meters?quarter=3&year=2026"
    ).get_json()

    by_number = {m["number"]: m for m in meters}
    assert by_number["PM-001"]["utility"] == "Power"
    assert by_number["PM-001"]["amount"] == "500000.00"  # prefilled from the existing allocation
    assert by_number["WM-001"]["amount"] == ""  # not yet allocated
    assert by_number["PM-001"]["id"] == power_meter.id


def test_meters_endpoint_amounts_are_period_specific(client, db):
    admin = make_user(db, "Ada", "ada@example.com", "pw", "admin")
    power = make_utility_type(db, "Power")
    beneficiary = make_beneficiary(db, "Jane Doe")
    meter = make_meter(db, beneficiary, power, "PM-001")
    db.session.add(Allocation(meter_id=meter.id, quarter=3, year=2026, amount=500000, created_by_id=admin.id))
    db.session.commit()
    login(client, "ada@example.com", "pw")

    q3 = client.get(f"/admin/beneficiaries/{beneficiary.id}/meters?quarter=3&year=2026").get_json()
    q4 = client.get(f"/admin/beneficiaries/{beneficiary.id}/meters?quarter=4&year=2026").get_json()

    assert q3[0]["amount"] == "500000.00"
    assert q4[0]["amount"] == ""  # different quarter, nothing allocated yet


def test_allocation_page_no_longer_embeds_the_register(client, db):
    make_user(db, "Ada", "ada@example.com", "pw", "admin")
    make_beneficiary(db, "Jane Doe")
    login(client, "ada@example.com", "pw")

    body = client.get("/admin/allocations/new").data.decode()

    assert "Jane Doe" not in body  # fetched on demand instead
