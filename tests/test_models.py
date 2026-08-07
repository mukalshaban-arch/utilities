from app.models import Allocation
from tests.conftest import make_user, make_utility_type, make_beneficiary, make_meter


def test_allocations_are_per_meter(db):
    admin = make_user(db, "Ada", "ada@example.com", "pw", "admin")
    beneficiary = make_beneficiary(db, "Jane Doe")
    power = make_utility_type(db, "Power")

    meter_1 = make_meter(db, beneficiary, power, "PM-001")
    meter_2 = make_meter(db, beneficiary, power, "PM-002")

    db.session.add(Allocation(meter_id=meter_1.id, quarter=2, year=2026, amount=100, created_by_id=admin.id))
    db.session.add(Allocation(meter_id=meter_2.id, quarter=2, year=2026, amount=250, created_by_id=admin.id))
    db.session.commit()

    assert float(Allocation.query.filter_by(meter_id=meter_1.id).one().amount) == 100
    assert float(Allocation.query.filter_by(meter_id=meter_2.id).one().amount) == 250


def test_major_account_label_includes_facility(db):
    beneficiary = make_beneficiary(db, "HQ Account", position="Major Accounts", facility="HQ")
    assert beneficiary.label == "HQ Account - HQ"
