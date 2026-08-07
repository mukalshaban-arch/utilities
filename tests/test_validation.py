"""Validation, duplicate-guard, and error-path coverage for admin routes."""
from unittest.mock import patch

from app.backup import BackupError
from app.models import Allocation, Beneficiary, QuarterBudget, User, Usage, UtilityType
from tests.conftest import (
    make_user, make_utility_type, make_beneficiary, make_meter, login,
)


# --- user & utility-type creation -------------------------------------------------

def test_create_user_and_reject_duplicate_email(client, db):
    make_user(db, "Ada", "ada@example.com", "pw", "admin")
    login(client, "ada@example.com", "pw")

    resp = client.post(
        "/admin/users/new",
        data={"name": "Bea", "email": "bea@example.com", "password": "pw123456", "role": "admin"},
        follow_redirects=True,
    )
    assert b"created" in resp.data
    assert User.query.filter_by(email="bea@example.com").count() == 1

    dupe = client.post(
        "/admin/users/new",
        data={"name": "Other", "email": "bea@example.com", "password": "pw123456", "role": "admin"},
        follow_redirects=True,
    )
    assert b"already exists" in dupe.data
    assert User.query.filter_by(email="bea@example.com").count() == 1


def test_create_utility_type_and_reject_duplicate(client, db):
    make_user(db, "Ada", "ada@example.com", "pw", "admin")
    login(client, "ada@example.com", "pw")

    client.post("/admin/utility-types/new", data={"name": "Solar"}, follow_redirects=True)
    assert UtilityType.query.filter_by(name="Solar").count() == 1

    dupe = client.post("/admin/utility-types/new", data={"name": "Solar"}, follow_redirects=True)
    assert b"already exists" in dupe.data
    assert UtilityType.query.filter_by(name="Solar").count() == 1


# --- beneficiary field validation --------------------------------------------------

def test_beneficiary_requires_a_name(client, db):
    make_user(db, "Ada", "ada@example.com", "pw", "admin")
    login(client, "ada@example.com", "pw")

    resp = client.post(
        "/admin/beneficiaries/new",
        data={"name": "   ", "position": "Director", "department": "DAF"},
        follow_redirects=True,
    )
    assert b"Name is required" in resp.data
    assert Beneficiary.query.count() == 0


def test_beneficiary_rejects_an_invalid_position(client, db):
    make_user(db, "Ada", "ada@example.com", "pw", "admin")
    login(client, "ada@example.com", "pw")

    resp = client.post(
        "/admin/beneficiaries/new",
        data={"name": "Jane", "position": "Supreme Overlord"},
        follow_redirects=True,
    )
    assert b"valid position" in resp.data
    assert Beneficiary.query.count() == 0


def test_duplicate_beneficiary_name_is_rejected(client, db):
    make_user(db, "Ada", "ada@example.com", "pw", "admin")
    make_beneficiary(db, "Jane Doe", position="Director")
    login(client, "ada@example.com", "pw")

    resp = client.post(
        "/admin/beneficiaries/new",
        data={"name": "Jane Doe", "position": "Director", "department": "DAF"},
        follow_redirects=True,
    )
    assert b"already registered" in resp.data
    assert Beneficiary.query.filter_by(name="Jane Doe").count() == 1


# --- allocation validation ---------------------------------------------------------

def setup_meter(db):
    admin = make_user(db, "Ada", "ada@example.com", "pw", "admin")
    power = make_utility_type(db, "Power")
    beneficiary = make_beneficiary(db, "Jane", position="Director")
    beneficiary.department = "DAF"
    db.session.commit()
    return admin, beneficiary, make_meter(db, beneficiary, power, "PM-1")


def test_allocation_rejects_an_invalid_quarter(client, db):
    _, beneficiary, meter = setup_meter(db)
    login(client, "ada@example.com", "pw")

    resp = client.post(
        "/admin/allocations/new",
        data={"beneficiary_id": beneficiary.id, "quarter": 9, "year": 2026, f"amount_{meter.id}": "100"},
        follow_redirects=True,
    )
    assert b"valid quarter" in resp.data
    assert Allocation.query.count() == 0


def test_allocation_rejects_a_non_numeric_amount(client, db):
    _, beneficiary, meter = setup_meter(db)
    login(client, "ada@example.com", "pw")

    resp = client.post(
        "/admin/allocations/new",
        data={"beneficiary_id": beneficiary.id, "quarter": 1, "year": 2026, f"amount_{meter.id}": "abc"},
        follow_redirects=True,
    )
    assert b"not a valid amount" in resp.data
    assert Allocation.query.count() == 0


def test_allocation_rejects_a_negative_amount(client, db):
    _, beneficiary, meter = setup_meter(db)
    login(client, "ada@example.com", "pw")

    resp = client.post(
        "/admin/allocations/new",
        data={"beneficiary_id": beneficiary.id, "quarter": 1, "year": 2026, f"amount_{meter.id}": "-50"},
        follow_redirects=True,
    )
    assert b"cannot be negative" in resp.data
    assert Allocation.query.count() == 0


# --- budget validation -------------------------------------------------------------

def test_budget_rejects_a_non_numeric_amount(client, db):
    make_user(db, "Ada", "ada@example.com", "pw", "admin")
    login(client, "ada@example.com", "pw")

    resp = client.post("/admin/budgets", data={"year": 2026, "budget_1": "lots"}, follow_redirects=True)
    assert b"not a valid amount" in resp.data
    assert QuarterBudget.query.count() == 0


def test_budget_rejects_a_negative_amount(client, db):
    make_user(db, "Ada", "ada@example.com", "pw", "admin")
    login(client, "ada@example.com", "pw")

    resp = client.post("/admin/budgets", data={"year": 2026, "budget_1": "-5"}, follow_redirects=True)
    assert b"cannot be negative" in resp.data
    assert QuarterBudget.query.count() == 0


def test_budget_remaining_endpoint_handles_a_bad_period(client, db):
    make_user(db, "Ada", "ada@example.com", "pw", "admin")
    login(client, "ada@example.com", "pw")

    data = client.get("/admin/budget-remaining?year=2026&quarter=99").get_json()
    assert data == {"has_budget": False, "budget": 0, "allocated": 0, "remaining": 0}


# --- usage validation --------------------------------------------------------------

def setup_major_account(db):
    admin = make_user(db, "Ada", "ada@example.com", "pw", "admin")
    water = make_utility_type(db, "Water")
    hq = make_beneficiary(db, "HQ", position="Major Accounts", facility="HQ")
    return admin, make_meter(db, hq, water, "WM-1")


def test_usage_rejects_a_non_numeric_amount(client, db):
    _, meter = setup_major_account(db)
    login(client, "ada@example.com", "pw")

    resp = client.post(
        "/admin/major-accounts",
        data={"year": 2026, "quarter": 1, "account": 0, "utility": "", f"usage_{meter.id}": "none"},
        follow_redirects=True,
    )
    assert b"not a valid amount" in resp.data
    assert Usage.query.count() == 0


def test_usage_rejects_a_negative_amount(client, db):
    _, meter = setup_major_account(db)
    login(client, "ada@example.com", "pw")

    resp = client.post(
        "/admin/major-accounts",
        data={"year": 2026, "quarter": 1, "account": 0, "utility": "", f"usage_{meter.id}": "-1"},
        follow_redirects=True,
    )
    assert b"cannot be negative" in resp.data
    assert Usage.query.count() == 0


def test_usage_needs_a_single_quarter(client, db):
    setup_major_account(db)
    login(client, "ada@example.com", "pw")

    resp = client.post(
        "/admin/major-accounts",
        data={"year": 2026, "quarter": 0, "account": 0, "utility": ""},
        follow_redirects=True,
    )
    assert b"single quarter" in resp.data


# --- backup route error handling ---------------------------------------------------

def test_backup_route_reports_failure(client, db):
    make_user(db, "Ada", "ada@example.com", "pw", "admin")
    login(client, "ada@example.com", "pw")

    with patch("app.admin.routes.create_backup", side_effect=BackupError("pg_dump missing")):
        resp = client.post("/admin/backups/create", follow_redirects=True)

    assert b"pg_dump missing" in resp.data
