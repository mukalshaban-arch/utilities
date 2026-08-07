from app.models import Allocation
from tests.conftest import make_user, make_utility_type, make_beneficiary, make_meter, login


def test_allocation_saved_per_meter(client, db):
    admin = make_user(db, "Ada", "ada@example.com", "pw", "admin")
    power = make_utility_type(db, "Power")
    water = make_utility_type(db, "Water")
    beneficiary = make_beneficiary(db, "Jane Doe")
    power_1 = make_meter(db, beneficiary, power, "PM-001")
    power_2 = make_meter(db, beneficiary, power, "PM-002")
    water_1 = make_meter(db, beneficiary, water, "WM-001")
    login(client, "ada@example.com", "pw")

    resp = client.post(
        "/admin/allocations/new",
        data={
            "beneficiary_id": beneficiary.id,
            "quarter": 3,
            "year": 2026,
            f"amount_{power_1.id}": "500000",
            f"amount_{power_2.id}": "250000",
            f"amount_{water_1.id}": "",  # blank leaves this meter unallocated
        },
        follow_redirects=True,
    )

    assert resp.status_code == 200
    assert Allocation.query.count() == 2
    assert float(Allocation.query.filter_by(meter_id=power_1.id).one().amount) == 500000
    assert float(Allocation.query.filter_by(meter_id=power_2.id).one().amount) == 250000
    assert Allocation.query.filter_by(meter_id=water_1.id).first() is None


def test_resubmitting_updates_the_existing_allocation(client, db):
    make_user(db, "Ada", "ada@example.com", "pw", "admin")
    power = make_utility_type(db, "Power")
    beneficiary = make_beneficiary(db, "Jane Doe")
    meter = make_meter(db, beneficiary, power, "PM-001")
    login(client, "ada@example.com", "pw")

    payload = {"beneficiary_id": beneficiary.id, "quarter": 3, "year": 2026}
    client.post("/admin/allocations/new", data={**payload, f"amount_{meter.id}": "100000"}, follow_redirects=True)
    client.post("/admin/allocations/new", data={**payload, f"amount_{meter.id}": "180000"}, follow_redirects=True)

    allocation = Allocation.query.filter_by(meter_id=meter.id, quarter=3, year=2026).one()
    assert float(allocation.amount) == 180000
    assert Allocation.query.count() == 1


def test_unregistered_beneficiary_is_rejected(client, db):
    make_user(db, "Ada", "ada@example.com", "pw", "admin")
    login(client, "ada@example.com", "pw")

    resp = client.post(
        "/admin/allocations/new",
        data={"beneficiary_id": "", "quarter": 3, "year": 2026},
        follow_redirects=True,
    )

    assert b"registered beneficiary" in resp.data
    assert Allocation.query.count() == 0
