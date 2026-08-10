from app.models import Allocation, Usage, ActivityLog, is_carryforward_meter
from app.ledger import carry_in, meter_ledger
from tests.conftest import make_user, make_utility_type, make_beneficiary, make_meter, login


def allocate(db, meter, quarter, year, amount, admin_id=1):
    db.session.add(
        Allocation(meter_id=meter.id, quarter=quarter, year=year, amount=amount, created_by_id=admin_id)
    )
    db.session.commit()


def use(db, meter, quarter, year, amount, admin_id=1):
    db.session.add(
        Usage(meter_id=meter.id, quarter=quarter, year=year, amount=amount, created_by_id=admin_id)
    )
    db.session.commit()


def test_the_users_worked_example(db):
    """HQ water meter: Q1 alloc 5M, used 2.5M -> balance 2.5M carries; Q2 alloc 5M -> pool 7.5M."""
    make_user(db, "Ada", "ada@example.com", "pw", "admin")
    hq = make_beneficiary(db, "HQ", position="Major Accounts", facility="HQ")
    water = make_utility_type(db, "Water")
    meter = make_meter(db, hq, water, "WM-HQ-1")

    allocate(db, meter, 1, 2026, 5_000_000)
    use(db, meter, 1, 2026, 2_500_000)

    q1 = meter_ledger(meter.id, 2026, 1)
    assert q1["pool"] == 5_000_000  # carry-in 0 + allocation 5M
    assert q1["usage"] == 2_500_000
    assert q1["balance"] == 2_500_000  # carries forward

    # Q2: admin allocates another 5M
    allocate(db, meter, 2, 2026, 5_000_000)
    q2 = meter_ledger(meter.id, 2026, 2)
    assert q2["carry_in"] == 2_500_000
    assert q2["pool"] == 7_500_000  # 2.5M carried + 5M fresh
    assert q2["balance"] == 7_500_000  # no usage yet this quarter


def test_deficit_carries_as_negative(db):
    make_user(db, "Ada", "ada@example.com", "pw", "admin")
    hq = make_beneficiary(db, "HQ", position="Major Accounts", facility="HQ")
    power = make_utility_type(db, "Power")
    meter = make_meter(db, hq, power, "PM-HQ-1")

    allocate(db, meter, 1, 2026, 5_000_000)
    use(db, meter, 1, 2026, 6_000_000)  # overspend

    assert meter_ledger(meter.id, 2026, 1)["balance"] == -1_000_000
    # next quarter starts 1M in the hole; a fresh 5M nets to 4M
    allocate(db, meter, 2, 2026, 5_000_000)
    assert meter_ledger(meter.id, 2026, 2)["pool"] == 4_000_000


def test_ledger_rolls_continuously_across_years(db):
    make_user(db, "Ada", "ada@example.com", "pw", "admin")
    hq = make_beneficiary(db, "HQ", position="Major Accounts", facility="HQ")
    water = make_utility_type(db, "Water")
    meter = make_meter(db, hq, water, "WM-HQ-1")

    allocate(db, meter, 4, 2026, 3_000_000)
    use(db, meter, 4, 2026, 1_000_000)  # balance 2M at end of 2026

    assert carry_in(meter.id, 2027, 1) == 2_000_000  # crosses into next year


def test_eligibility_rules(db):
    make_beneficiary(db, "HQ", position="Major Accounts", facility="HQ")
    staff = make_beneficiary(db, "Jane", position="Director")
    staff.department = "DAF"
    db.session.commit()
    hq = make_beneficiary(db, "HQ2", position="Major Accounts", facility="Katonga")
    water = make_utility_type(db, "Water")
    phone = make_utility_type(db, "Office Phone Airtime")

    hq_water = make_meter(db, hq, water, "WM-1")
    hq_phone = make_meter(db, hq, phone, "0700111222")
    staff_water = make_meter(db, staff, water, "WM-2")

    assert is_carryforward_meter(hq_water) is True
    assert is_carryforward_meter(hq_phone) is False  # phone is excluded
    assert is_carryforward_meter(staff_water) is False  # not a major account


def test_major_accounts_page_records_usage_and_logs_it(client, db):
    make_user(db, "Ada", "ada@example.com", "pw", "admin")
    hq = make_beneficiary(db, "HQ", position="Major Accounts", facility="HQ")
    water = make_utility_type(db, "Water")
    meter = make_meter(db, hq, water, "WM-HQ-1")
    allocate(db, meter, 3, 2026, 5_000_000)
    login(client, "ada@example.com", "pw")

    client.post(
        "/admin/major-accounts",
        data={"year": 2026, "quarter": 3, f"usage_{meter.id}": "2500000"},
        follow_redirects=True,
    )

    assert Usage.query.filter_by(meter_id=meter.id, quarter=3, year=2026).one().amount == 2_500_000
    assert ActivityLog.query.filter_by(action="Recorded usage").count() == 1
    assert meter_ledger(meter.id, 2026, 3)["balance"] == 2_500_000


def test_major_accounts_page_only_lists_eligible_meters(client, db):
    make_user(db, "Ada", "ada@example.com", "pw", "admin")
    hq = make_beneficiary(db, "HQ Account", position="Major Accounts", facility="HQ")
    water = make_utility_type(db, "Water")
    phone = make_utility_type(db, "Office Phone Airtime")
    make_meter(db, hq, water, "WM-HQ-1")
    make_meter(db, hq, phone, "0700111222")
    login(client, "ada@example.com", "pw")

    body = client.get("/admin/major-accounts?year=2026&quarter=3").data.decode()

    assert "WM-HQ-1" in body  # water shows
    assert "0700111222" not in body  # phone does not


def setup_two_accounts(db):
    make_user(db, "Ada", "ada@example.com", "pw", "admin")
    water = make_utility_type(db, "Water")
    power = make_utility_type(db, "Power")

    hq = make_beneficiary(db, "HQ", position="Major Accounts", facility="HQ")
    katonga = make_beneficiary(db, "Katonga", position="Major Accounts", facility="Katonga")

    hq_water = make_meter(db, hq, water, "HQ-WM-1")
    hq_power = make_meter(db, hq, power, "HQ-PM-1")
    kat_water = make_meter(db, katonga, water, "KAT-WM-1")

    allocate(db, hq_water, 3, 2026, 5_000_000)
    use(db, hq_water, 3, 2026, 2_000_000)
    allocate(db, hq_power, 3, 2026, 4_000_000)
    allocate(db, kat_water, 3, 2026, 1_000_000)
    return hq, katonga


def test_ledger_csv_export_includes_all_columns_and_total(client, db):
    setup_two_accounts(db)
    login(client, "ada@example.com", "pw")

    resp = client.get("/admin/major-accounts/report.csv?year=2026&quarter=3")

    assert resp.status_code == 200
    assert resp.mimetype == "text/csv"
    body = resp.data.decode()
    assert "Carried In,Allocation,Pool,Usage,Balance" in body
    assert "HQ-WM-1" in body and "HQ-PM-1" in body and "KAT-WM-1" in body
    assert "Total" in body


def test_ledger_report_filters_by_account(client, db):
    hq, katonga = setup_two_accounts(db)
    login(client, "ada@example.com", "pw")

    body = client.get(f"/admin/major-accounts/report.csv?year=2026&quarter=3&account={hq.id}").data.decode()

    assert "HQ-WM-1" in body
    assert "KAT-WM-1" not in body  # other account excluded


def test_ledger_report_filters_by_utility(client, db):
    setup_two_accounts(db)
    login(client, "ada@example.com", "pw")

    body = client.get("/admin/major-accounts/report.csv?year=2026&quarter=3&utility=Water").data.decode()

    assert "HQ-WM-1" in body and "KAT-WM-1" in body
    assert "HQ-PM-1" not in body  # power excluded


def test_all_quarters_report_shows_progression_with_carryforward(client, db):
    setup_two_accounts(db)  # activity only in Q3 2026
    login(client, "ada@example.com", "pw")

    body = client.get("/admin/major-accounts/report.csv?year=2026&quarter=0").data.decode()

    assert "Quarter" in body  # the extra column
    assert "Q3 2026" in body  # the quarter with allocation/usage
    assert "Q4 2026" in body  # carry-forward keeps Q4 non-empty
    assert "Q1 2026" not in body  # empty quarters are skipped
    assert "Q2 2026" not in body


def test_all_quarters_total_balance_is_year_end_standing(client, db):
    # setup_two_accounts activity (Q3 2026): hq_water 5M/-2M->3M, hq_power 4M->4M, kat_water 1M->1M
    setup_two_accounts(db)
    login(client, "ada@example.com", "pw")

    body = client.get("/admin/major-accounts/report.csv?year=2026&quarter=0").data.decode()
    total_line = [line for line in body.splitlines() if line.startswith("Total")][-1]

    # Total row: allocation 10M, usage 2M, year-end balance 3M+4M+1M = 8M
    assert total_line == "Total,,,,,10000000.00,,2000000.00,8000000.00"


def test_single_quarter_total_row_has_allocation_and_balance(client, db):
    setup_two_accounts(db)
    login(client, "ada@example.com", "pw")

    body = client.get("/admin/major-accounts/report.csv?year=2026&quarter=3").data.decode()
    total_line = [line for line in body.splitlines() if line.startswith("Total")][-1]

    # Q3: allocation 10M, usage 2M, balance 8M
    assert total_line == "Total,,,,,10000000.00,,2000000.00,8000000.00"


def test_all_quarters_download_name(client, db):
    setup_two_accounts(db)
    login(client, "ada@example.com", "pw")

    resp = client.get("/admin/major-accounts/report.pdf?year=2026&quarter=0")

    assert resp.status_code == 200
    assert "ledger_2026_all-quarters.pdf" in resp.headers["Content-Disposition"]


def test_all_quarters_page_is_read_only(client, db):
    setup_two_accounts(db)
    login(client, "ada@example.com", "pw")

    body = client.get("/admin/major-accounts?year=2026&quarter=0").data.decode()

    assert "Q3 2026" in body
    assert 'name="usage_' not in body  # no usage inputs in the all-quarters view
    assert "Save Usage" not in body


def test_ledger_pdf_export(client, db):
    setup_two_accounts(db)
    login(client, "ada@example.com", "pw")

    resp = client.get("/admin/major-accounts/report.pdf?year=2026&quarter=3&utility=Water")

    assert resp.status_code == 200
    assert resp.mimetype == "application/pdf"
    assert resp.data.startswith(b"%PDF-")
    assert "ledger_2026_Q3_water.pdf" in resp.headers["Content-Disposition"]


def test_ledger_export_is_logged(client, db):
    from app.models import ActivityLog

    setup_two_accounts(db)
    login(client, "ada@example.com", "pw")

    client.get("/admin/major-accounts/report.pdf?year=2026&quarter=3")

    assert ActivityLog.query.filter_by(action="Generated ledger PDF report").count() == 1


def test_major_accounts_page_embeds_chart_data(client, db):
    setup_two_accounts(db)  # Q3 2026: HQ water used 2M, others 0
    login(client, "ada@example.com", "pw")

    body = client.get("/admin/major-accounts?year=2026&quarter=3").data.decode()

    assert 'id="chart-trend"' in body
    assert 'id="chart-utility-usage"' in body
    assert "charts.js" in body
    assert "chart.umd.min.js" in body
    assert "2000000" in body  # the Q3 usage figure is embedded for the chart


def test_major_accounts_charts_hidden_when_no_meters(client, db):
    make_user(db, "Ada", "ada@example.com", "pw", "admin")
    login(client, "ada@example.com", "pw")

    body = client.get("/admin/major-accounts?year=2026&quarter=3").data.decode()

    assert 'id="chart-trend"' not in body  # nothing to chart


def test_ledger_charts_trend_and_utility_split(client, db):
    from app.admin.routes import ledger_charts, filter_major_account_groups

    setup_two_accounts(db)  # HQ water 5M/2M, HQ power 4M, Katonga water 1M, all in Q3
    groups = filter_major_account_groups(0, "")
    data = ledger_charts(groups, 2026)

    assert data["trend"]["labels"] == ["Q1 2026", "Q2 2026", "Q3 2026", "Q4 2026"]
    assert data["trend"]["usage"] == [0.0, 0.0, 2_000_000.0, 0.0]
    assert data["trend"]["allocation"] == [0.0, 0.0, 10_000_000.0, 0.0]
    # Q3 balance = 5-2 + 4 + 1 = 8M, and it carries into Q4 unchanged
    assert data["trend"]["balance"] == [0.0, 0.0, 8_000_000.0, 8_000_000.0]
    # usage split: only HQ water was used
    zipped = dict(zip(data["utility_usage"]["labels"], data["utility_usage"]["values"], strict=True))
    assert zipped["Water"] == 2_000_000.0


def test_ledger_charts_respect_utility_filter(client, db):
    from app.admin.routes import ledger_charts, filter_major_account_groups

    setup_two_accounts(db)
    groups = filter_major_account_groups(0, "Power")  # power meters only
    data = ledger_charts(groups, 2026)

    assert list(data["utility_usage"]["labels"]) == ["Power"]
    assert data["trend"]["allocation"] == [0.0, 0.0, 4_000_000.0, 0.0]  # only HQ power's 4M


def test_summary_page_embeds_charts(client, db):
    make_user(db, "Ada", "ada@example.com", "pw", "admin")
    water = make_utility_type(db, "Water")
    beneficiary = make_beneficiary(db, "HQ", position="Major Accounts", facility="HQ")
    meter = make_meter(db, beneficiary, water, "WM-1")
    allocate(db, meter, 3, 2026, 5_000_000)
    login(client, "ada@example.com", "pw")

    body = client.get("/admin/summary?year=2026&quarter=3").data.decode()

    assert 'id="chart-utility"' in body
    assert 'id="chart-beneficiary"' in body
    assert "5000000" in body


def test_allocation_form_meters_endpoint_exposes_carry_forward(client, db):
    make_user(db, "Ada", "ada@example.com", "pw", "admin")
    hq = make_beneficiary(db, "HQ", position="Major Accounts", facility="HQ")
    water = make_utility_type(db, "Water")
    phone = make_utility_type(db, "Office Phone Airtime")
    water_meter = make_meter(db, hq, water, "WM-1")
    make_meter(db, hq, phone, "0700111222")  # registered but excluded from carry-forward
    allocate(db, water_meter, 1, 2026, 5_000_000)
    use(db, water_meter, 1, 2026, 2_500_000)
    login(client, "ada@example.com", "pw")

    meters = client.get(f"/admin/beneficiaries/{hq.id}/meters?quarter=2&year=2026").get_json()
    by_number = {m["number"]: m for m in meters}

    assert by_number["WM-1"]["carry_forward"] == "2500000.00"  # water carries
    assert by_number["0700111222"]["carry_forward"] is None  # phone does not
