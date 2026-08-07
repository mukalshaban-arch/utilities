from app.models import Allocation, QuarterBudget, ActivityLog
from tests.conftest import make_user, make_utility_type, make_beneficiary, make_meter, login


def allocate(db, meter, quarter, year, amount, admin_id=1):
    db.session.add(Allocation(meter_id=meter.id, quarter=quarter, year=year, amount=amount, created_by_id=admin_id))
    db.session.commit()


def test_admin_sets_a_quarter_budget(client, db):
    make_user(db, "Ada", "ada@example.com", "pw", "admin")
    login(client, "ada@example.com", "pw")

    client.post(
        "/admin/budgets",
        data={"year": 2026, "budget_3": "10000000"},
        follow_redirects=True,
    )

    budget = QuarterBudget.query.filter_by(year=2026, quarter=3).one()
    assert float(budget.amount) == 10_000_000
    assert ActivityLog.query.filter_by(action="Set quarter budget").count() == 1


def test_balance_reduces_as_allocations_are_made(client, db):
    admin = make_user(db, "Ada", "ada@example.com", "pw", "admin")
    power = make_utility_type(db, "Power")
    beneficiary = make_beneficiary(db, "Jane", position="Director")
    beneficiary.department = "DAF"
    db.session.commit()
    meter = make_meter(db, beneficiary, power, "PM-1")
    db.session.add(QuarterBudget(year=2026, quarter=3, amount=10_000_000, created_by_id=admin.id))
    allocate(db, meter, 3, 2026, 3_000_000)
    db.session.commit()
    login(client, "ada@example.com", "pw")

    body = client.get("/admin/budgets?year=2026").data.decode()

    assert "UGX 10,000,000" in body  # budget
    assert "UGX 3,000,000" in body   # allocated
    assert "UGX 7,000,000" in body   # balance = 10M - 3M


def test_updating_a_budget_is_logged_with_previous(client, db):
    admin = make_user(db, "Ada", "ada@example.com", "pw", "admin")
    db.session.add(QuarterBudget(year=2026, quarter=1, amount=5_000_000, created_by_id=admin.id))
    db.session.commit()
    login(client, "ada@example.com", "pw")

    client.post("/admin/budgets", data={"year": 2026, "budget_1": "8000000"}, follow_redirects=True)

    entry = ActivityLog.query.filter_by(action="Updated quarter budget").one()
    assert float(entry.previous_amount) == 5_000_000
    assert float(entry.amount) == 8_000_000
    assert float(QuarterBudget.query.filter_by(year=2026, quarter=1).one().amount) == 8_000_000


def test_dashboard_shows_budget_and_balance_cards(client, db):
    admin = make_user(db, "Ada", "ada@example.com", "pw", "admin")
    power = make_utility_type(db, "Power")
    beneficiary = make_beneficiary(db, "Jane", position="Director")
    beneficiary.department = "DAF"
    db.session.commit()
    meter = make_meter(db, beneficiary, power, "PM-1")
    from app.fiscal import current_period
    y, q = current_period()
    db.session.add(QuarterBudget(year=y, quarter=q, amount=10_000_000, created_by_id=admin.id))
    allocate(db, meter, q, y, 4_000_000)
    db.session.commit()
    login(client, "ada@example.com", "pw")

    body = client.get("/admin/").data.decode()

    assert "Quarter Budget" in body
    assert "Budget Balance" in body
    assert "UGX 10,000,000" in body  # budget card
    assert "UGX 6,000,000" in body   # balance card (10M - 4M)


def test_blank_budget_leaves_it_unchanged(client, db):
    admin = make_user(db, "Ada", "ada@example.com", "pw", "admin")
    db.session.add(QuarterBudget(year=2026, quarter=2, amount=5_000_000, created_by_id=admin.id))
    db.session.commit()
    login(client, "ada@example.com", "pw")

    resp = client.post("/admin/budgets", data={"year": 2026, "budget_2": ""}, follow_redirects=True)

    assert b"No budgets were changed" in resp.data
    assert float(QuarterBudget.query.filter_by(year=2026, quarter=2).one().amount) == 5_000_000
