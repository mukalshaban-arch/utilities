from app.models import Beneficiary, Meter
from tests.conftest import make_user, make_utility_type, make_beneficiary, make_meter, login


def test_register_beneficiary_with_multiple_meters_per_utility(client, db):
    make_user(db, "Ada", "ada@example.com", "pw", "admin")
    power = make_utility_type(db, "Power")
    phone = make_utility_type(db, "Office Phone Airtime")
    login(client, "ada@example.com", "pw")

    resp = client.post(
        "/admin/beneficiaries/new",
        data={
            "name": "Jane Doe",
            "position": "Director",
            "department": "DAF",
            "meter_id": ["", "", ""],
            "meter_utility": [power.id, power.id, phone.id],
            "meter_number": ["PM-001", "PM-002", "0700111222"],
        },
        follow_redirects=True,
    )

    assert resp.status_code == 200
    beneficiary = Beneficiary.query.filter_by(name="Jane Doe").one()
    assert beneficiary.department == "DAF"
    assert beneficiary.facility is None
    numbers = sorted(m.number for m in beneficiary.meters)
    assert numbers == ["0700111222", "PM-001", "PM-002"]


def test_staff_position_requires_a_department(client, db):
    make_user(db, "Ada", "ada@example.com", "pw", "admin")
    login(client, "ada@example.com", "pw")

    resp = client.post(
        "/admin/beneficiaries/new",
        data={"name": "Jane Doe", "position": "Director", "department": ""},
        follow_redirects=True,
    )

    assert b"Select a department" in resp.data
    assert Beneficiary.query.count() == 0


def test_major_account_gets_facility_not_department(client, db):
    make_user(db, "Ada", "ada@example.com", "pw", "admin")
    login(client, "ada@example.com", "pw")

    client.post(
        "/admin/beneficiaries/new",
        data={
            "name": "HQ Account",
            "position": "Major Accounts",
            "facility": "Katonga",
            "department": "DAF",  # ignored - major accounts sit in a facility
        },
        follow_redirects=True,
    )

    beneficiary = Beneficiary.query.filter_by(name="HQ Account").one()
    assert beneficiary.facility == "Katonga"
    assert beneficiary.department is None


def test_admin_can_change_a_beneficiarys_department(client, db):
    make_user(db, "Ada", "ada@example.com", "pw", "admin")
    beneficiary = make_beneficiary(db, "Jane Doe", position="Section Head")
    beneficiary.department = "DAF"
    db.session.commit()
    login(client, "ada@example.com", "pw")

    client.post(
        f"/admin/beneficiaries/{beneficiary.id}",
        data={"name": "Jane Doe", "position": "Section Head", "department": "DTI"},
        follow_redirects=True,
    )

    assert Beneficiary.query.filter_by(name="Jane Doe").one().department == "DTI"


def test_beneficiary_list_filters_by_department(client, db):
    make_user(db, "Ada", "ada@example.com", "pw", "admin")
    for name, dept in (("Jane Doe", "DAF"), ("John Roe", "DLP")):
        b = make_beneficiary(db, name, position="Director")
        b.department = dept
    db.session.commit()
    login(client, "ada@example.com", "pw")

    body = client.get("/admin/beneficiaries?department=DLP").data.decode()

    assert "John Roe" in body
    assert "Jane Doe" not in body


def test_major_account_requires_facility(client, db):
    make_user(db, "Ada", "ada@example.com", "pw", "admin")
    login(client, "ada@example.com", "pw")

    resp = client.post(
        "/admin/beneficiaries/new",
        data={"name": "HQ Account", "position": "Major Accounts", "facility": ""},
        follow_redirects=True,
    )

    assert b"must have a facility" in resp.data
    assert Beneficiary.query.count() == 0


def test_major_account_with_facility_is_registered(client, db):
    make_user(db, "Ada", "ada@example.com", "pw", "admin")
    login(client, "ada@example.com", "pw")

    client.post(
        "/admin/beneficiaries/new",
        data={"name": "HQ Account", "position": "Major Accounts", "facility": "Rubaga House"},
        follow_redirects=True,
    )

    beneficiary = Beneficiary.query.filter_by(name="HQ Account").one()
    assert beneficiary.facility == "Rubaga House"
    assert beneficiary.label == "HQ Account - Rubaga House"


def test_admin_can_change_a_meter_number_and_add_another(client, db):
    make_user(db, "Ada", "ada@example.com", "pw", "admin")
    power = make_utility_type(db, "Power")
    beneficiary = make_beneficiary(db, "Jane Doe")
    meter = make_meter(db, beneficiary, power, "OLD-123")
    login(client, "ada@example.com", "pw")

    client.post(
        f"/admin/beneficiaries/{beneficiary.id}",
        data={
            "name": "Jane Doe",
            "position": "Director",
            "department": "DAF",
            "meter_id": [str(meter.id), ""],
            "meter_utility": [power.id, power.id],
            "meter_number": ["NEW-456", "PM-999"],
        },
        follow_redirects=True,
    )

    assert Meter.query.get(meter.id).number == "NEW-456"
    assert {m.number for m in beneficiary.meters} == {"NEW-456", "PM-999"}


def test_only_admin_role_exists(client, db):
    """The system tracks allocations only - no expense/approval workflow."""
    from app.models import ROLES

    assert ROLES == ("admin",)
