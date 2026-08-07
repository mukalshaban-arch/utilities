from app.models import ActivityLog
from tests.conftest import make_user, make_utility_type, make_beneficiary, make_meter, login


def test_allocating_records_who_when_and_where(client, db):
    make_user(db, "Ada Admin", "ada@example.com", "pw", "admin")
    power = make_utility_type(db, "Power")
    beneficiary = make_beneficiary(db, "Jane Doe", position="Section Head")
    beneficiary.department = "DAF"
    db.session.commit()
    meter = make_meter(db, beneficiary, power, "PM-001")
    login(client, "ada@example.com", "pw")

    client.post(
        "/admin/allocations/new",
        data={"beneficiary_id": beneficiary.id, "quarter": 3, "year": 2026, f"amount_{meter.id}": "500000"},
        follow_redirects=True,
    )

    entry = ActivityLog.query.filter_by(action="Allocated").one()
    assert entry.user.name == "Ada Admin"      # who
    assert entry.created_at is not None        # when
    assert entry.beneficiary_name == "Jane Doe"
    assert entry.unit == "DAF"                 # department
    assert entry.utility == "Power"
    assert entry.number == "PM-001"
    assert entry.quarter == 3 and entry.year == 2026
    assert float(entry.amount) == 500000


def test_major_account_activity_shows_facility_as_unit(client, db):
    make_user(db, "Ada", "ada@example.com", "pw", "admin")
    power = make_utility_type(db, "Power")
    beneficiary = make_beneficiary(db, "HQ Account", position="Major Accounts", facility="Katonga")
    meter = make_meter(db, beneficiary, power, "PM-H1")
    login(client, "ada@example.com", "pw")

    client.post(
        "/admin/allocations/new",
        data={"beneficiary_id": beneficiary.id, "quarter": 3, "year": 2026, f"amount_{meter.id}": "100000"},
        follow_redirects=True,
    )

    assert ActivityLog.query.filter_by(action="Allocated").one().unit == "Katonga"


def test_unchanged_figures_are_not_logged(client, db):
    """Re-saving the form must only log the meter whose figure actually moved."""
    make_user(db, "Ada", "ada@example.com", "pw", "admin")
    power = make_utility_type(db, "Power")
    water = make_utility_type(db, "Water")
    beneficiary = make_beneficiary(db, "Jane Doe", position="Director")
    beneficiary.department = "DAF"
    db.session.commit()
    power_meter = make_meter(db, beneficiary, power, "PM-001")
    water_meter = make_meter(db, beneficiary, water, "WM-001")
    login(client, "ada@example.com", "pw")

    base = {"beneficiary_id": beneficiary.id, "quarter": 3, "year": 2026}
    client.post(
        "/admin/allocations/new",
        data={**base, f"amount_{power_meter.id}": "300000", f"amount_{water_meter.id}": "100000"},
        follow_redirects=True,
    )
    assert ActivityLog.query.count() == 2  # both newly allocated

    # resubmit with water changed and power identical
    client.post(
        "/admin/allocations/new",
        data={**base, f"amount_{power_meter.id}": "300000", f"amount_{water_meter.id}": "150000"},
        follow_redirects=True,
    )

    updates = ActivityLog.query.filter_by(action="Updated allocation").all()
    assert len(updates) == 1  # only the water bill, not the untouched power meter
    assert updates[0].utility == "Water"
    assert float(updates[0].previous_amount) == 100000
    assert float(updates[0].amount) == 150000
    assert ActivityLog.query.count() == 3


def test_resaving_with_no_changes_logs_nothing(client, db):
    make_user(db, "Ada", "ada@example.com", "pw", "admin")
    power = make_utility_type(db, "Power")
    beneficiary = make_beneficiary(db, "Jane Doe", position="Director")
    beneficiary.department = "DAF"
    db.session.commit()
    meter = make_meter(db, beneficiary, power, "PM-001")
    login(client, "ada@example.com", "pw")

    base = {"beneficiary_id": beneficiary.id, "quarter": 3, "year": 2026}
    client.post("/admin/allocations/new", data={**base, f"amount_{meter.id}": "300000"}, follow_redirects=True)
    resp = client.post(
        "/admin/allocations/new", data={**base, f"amount_{meter.id}": "300000"}, follow_redirects=True
    )

    assert b"No figures were changed" in resp.data
    assert ActivityLog.query.count() == 1  # the original allocation only


def test_activity_times_render_in_local_zone(client, db):
    """Stored UTC must be displayed in the configured zone (Africa/Kampala, UTC+3)."""
    from datetime import datetime

    make_user(db, "Ada", "ada@example.com", "pw", "admin")
    beneficiary = make_beneficiary(db, "Jane Doe", position="Director")
    entry = ActivityLog(
        user_id=1,
        action="Allocated",
        beneficiary_name=beneficiary.name,
        created_at=datetime(2026, 7, 12, 14, 17),  # 14:17 UTC
    )
    db.session.add(entry)
    db.session.commit()
    login(client, "ada@example.com", "pw")

    body = client.get("/admin/activity").data.decode()

    assert "17:17" in body  # shown as EAT
    assert "14:17" not in body


def test_updating_an_allocation_is_logged_separately(client, db):
    make_user(db, "Ada", "ada@example.com", "pw", "admin")
    power = make_utility_type(db, "Power")
    beneficiary = make_beneficiary(db, "Jane Doe", position="Director")
    beneficiary.department = "DTI"
    db.session.commit()
    meter = make_meter(db, beneficiary, power, "PM-001")
    login(client, "ada@example.com", "pw")

    payload = {"beneficiary_id": beneficiary.id, "quarter": 3, "year": 2026}
    client.post("/admin/allocations/new", data={**payload, f"amount_{meter.id}": "100000"}, follow_redirects=True)
    client.post("/admin/allocations/new", data={**payload, f"amount_{meter.id}": "180000"}, follow_redirects=True)

    # the original amount survives in the log even though the allocation was overwritten
    assert float(ActivityLog.query.filter_by(action="Allocated").one().amount) == 100000
    assert float(ActivityLog.query.filter_by(action="Updated allocation").one().amount) == 180000


def test_registering_a_beneficiary_is_logged(client, db):
    make_user(db, "Ada", "ada@example.com", "pw", "admin")
    login(client, "ada@example.com", "pw")

    client.post(
        "/admin/beneficiaries/new",
        data={"name": "Jane Doe", "position": "Director", "department": "DLP"},
        follow_redirects=True,
    )

    entry = ActivityLog.query.filter_by(action="Registered beneficiary").one()
    assert entry.beneficiary_name == "Jane Doe"
    assert entry.unit == "DLP"
    assert entry.amount is None


def test_activity_page_shows_entries_and_filters(client, db):
    make_user(db, "Ada", "ada@example.com", "pw", "admin")
    login(client, "ada@example.com", "pw")
    for name, dept in (("Jane Doe", "DAF"), ("John Roe", "DIC")):
        client.post(
            "/admin/beneficiaries/new",
            data={"name": name, "position": "Director", "department": dept},
            follow_redirects=True,
        )

    body = client.get("/admin/activity").data.decode()
    assert "Jane Doe" in body and "John Roe" in body
    assert "Registered beneficiary" in body

    filtered = client.get("/admin/activity?name=jane").data.decode()
    assert "Jane Doe" in filtered
    assert "John Roe" not in filtered


def test_saving_an_allocation_returns_to_the_dashboard_not_the_log(client, db):
    make_user(db, "Ada", "ada@example.com", "pw", "admin")
    power = make_utility_type(db, "Power")
    beneficiary = make_beneficiary(db, "Jane Doe", position="Director")
    beneficiary.department = "DAF"
    db.session.commit()
    meter = make_meter(db, beneficiary, power, "PM-001")
    login(client, "ada@example.com", "pw")

    resp = client.post(
        "/admin/allocations/new",
        data={"beneficiary_id": beneficiary.id, "quarter": 3, "year": 2026, f"amount_{meter.id}": "300000"},
    )

    assert resp.headers["Location"].endswith("/admin/")  # not /admin/activity
    assert ActivityLog.query.count() == 1  # it still logged, just didn't show the log


def test_pdf_report_generation_is_logged(client, db):
    make_user(db, "Ada Admin", "ada@example.com", "pw", "admin")
    power = make_utility_type(db, "Power")
    login(client, "ada@example.com", "pw")

    client.get(f"/reports/quarterly.pdf?year=2026&quarter=3&utility_type_id={power.id}")

    entry = ActivityLog.query.filter_by(action="Generated PDF report").one()
    assert entry.user.name == "Ada Admin"
    assert entry.quarter == 3 and entry.year == 2026
    assert entry.utility == "Power"       # records which filter was exported
    assert entry.beneficiary_name is None  # system-wide action, not tied to one person
    assert entry.amount is None


def test_csv_report_generation_is_logged(client, db):
    make_user(db, "Ada", "ada@example.com", "pw", "admin")
    login(client, "ada@example.com", "pw")

    client.get("/reports/quarterly.csv?year=2026&quarter=2")

    entry = ActivityLog.query.filter_by(action="Generated CSV report").one()
    assert entry.quarter == 2 and entry.year == 2026
    assert entry.utility is None  # no utility filter was applied


def test_viewing_a_report_on_screen_is_not_logged(client, db):
    """Only exports leave the system, so only exports are recorded."""
    make_user(db, "Ada", "ada@example.com", "pw", "admin")
    login(client, "ada@example.com", "pw")

    client.get("/reports/quarterly?year=2026&quarter=3")

    assert ActivityLog.query.count() == 0


def test_dashboard_no_longer_lists_recent_allocations(client, db):
    make_user(db, "Ada", "ada@example.com", "pw", "admin")
    login(client, "ada@example.com", "pw")

    body = client.get("/admin/").data.decode()

    assert "Recent Allocations" not in body
    assert "Activity Log" in body
