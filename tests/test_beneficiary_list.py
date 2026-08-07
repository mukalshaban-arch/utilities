from app.models import Beneficiary
from tests.conftest import make_user, make_utility_type, make_beneficiary, make_meter, login


def test_dashboard_does_not_list_beneficiaries(client, db):
    make_user(db, "Ada", "ada@example.com", "pw", "admin")
    make_beneficiary(db, "Jane Doe", position="Director")
    login(client, "ada@example.com", "pw")

    body = client.get("/admin/").data.decode()

    assert "Jane Doe" not in body  # the register lives on its own page now
    assert "Beneficiaries" in body  # sidebar nav link


def test_beneficiary_page_lists_position_facility_and_numbers(client, db):
    make_user(db, "Ada", "ada@example.com", "pw", "admin")
    power = make_utility_type(db, "Power")
    hq = make_beneficiary(db, "HQ Account", position="Major Accounts", facility="Rubaga House")
    make_meter(db, hq, power, "PM-7001")
    login(client, "ada@example.com", "pw")

    body = client.get("/admin/beneficiaries").data.decode()

    assert "HQ Account" in body
    assert "Major Accounts" in body
    assert "Rubaga House" in body
    assert "PM-7001" in body


def test_beneficiary_page_search_and_filters(client, db):
    make_user(db, "Ada", "ada@example.com", "pw", "admin")
    make_beneficiary(db, "Jane Doe", position="Director")
    make_beneficiary(db, "HQ Account", position="Major Accounts", facility="HQ")
    login(client, "ada@example.com", "pw")

    by_name = client.get("/admin/beneficiaries?name=jane").data.decode()
    assert "Jane Doe" in by_name
    assert "HQ Account" not in by_name

    by_position = client.get("/admin/beneficiaries?position=Major+Accounts").data.decode()
    assert "HQ Account" in by_position
    assert "Jane Doe" not in by_position

    by_facility = client.get("/admin/beneficiaries?facility=HQ").data.decode()
    assert "HQ Account" in by_facility
    assert "Jane Doe" not in by_facility


def test_beneficiary_page_paginates(client, db):
    make_user(db, "Ada", "ada@example.com", "pw", "admin")
    for i in range(120):
        db.session.add(Beneficiary(name=f"Person {i:03d}", position="Other"))
    db.session.commit()
    login(client, "ada@example.com", "pw")

    page_1 = client.get("/admin/beneficiaries").data.decode()
    page_3 = client.get("/admin/beneficiaries?page=3").data.decode()

    assert "Person 000" in page_1
    assert "Person 049" in page_1
    assert "Person 050" not in page_1  # 50 per page
    assert "Person 100" in page_3
