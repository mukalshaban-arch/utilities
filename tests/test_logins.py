from datetime import timedelta

from app.models import LoginLog, lockout_seconds_remaining
from tests.conftest import make_user, login


def test_successful_login_is_recorded(client, db):
    make_user(db, "Ada Admin", "ada@example.com", "pw", "admin")

    login(client, "ada@example.com", "pw")

    entry = LoginLog.query.one()
    assert entry.success is True
    assert entry.email == "ada@example.com"
    assert entry.user.name == "Ada Admin"
    assert entry.attempts == 1  # got in first try
    assert entry.created_at is not None


def test_failed_attempt_is_recorded(client, db):
    make_user(db, "Ada", "ada@example.com", "pw", "admin")

    login(client, "ada@example.com", "wrong")

    entry = LoginLog.query.one()
    assert entry.success is False
    assert entry.user_id is not None  # the account exists, the password was wrong
    assert entry.attempts == 1


def test_attempts_are_counted_until_a_success(client, db):
    make_user(db, "Ada", "ada@example.com", "pw", "admin")

    login(client, "ada@example.com", "wrong")
    login(client, "ada@example.com", "wrong-again")
    login(client, "ada@example.com", "pw")

    entries = LoginLog.query.order_by(LoginLog.id).all()
    assert [e.success for e in entries] == [False, False, True]
    assert [e.attempts for e in entries] == [1, 2, 3]  # took 3 tries to get in


def test_attempt_counter_resets_after_a_success(client, db):
    make_user(db, "Ada", "ada@example.com", "pw", "admin")

    login(client, "ada@example.com", "wrong")
    login(client, "ada@example.com", "pw")       # attempts == 2
    client.get("/auth/logout")
    login(client, "ada@example.com", "wrong")    # new run starts back at 1
    login(client, "ada@example.com", "pw")

    entries = LoginLog.query.order_by(LoginLog.id).all()
    assert [e.attempts for e in entries] == [1, 2, 1, 2]


def test_unknown_email_is_recorded_without_a_user(client, db):
    login(client, "intruder@example.com", "guess")

    entry = LoginLog.query.one()
    assert entry.success is False
    assert entry.email == "intruder@example.com"
    assert entry.user_id is None  # no such account


def test_login_page_lists_attempts_and_filters(client, db):
    make_user(db, "Ada", "ada@example.com", "pw", "admin")
    login(client, "ada@example.com", "wrong")
    login(client, "intruder@example.com", "guess")
    login(client, "ada@example.com", "pw")

    body = client.get("/admin/logins").data.decode()
    assert "intruder@example.com" in body
    assert "Success" in body and "Failed" in body
    assert "got in on try 2" in body

    failed_only = client.get("/admin/logins?result=failed").data.decode()
    assert "intruder@example.com" in failed_only
    assert "got in on try 2" not in failed_only

    by_email = client.get("/admin/logins?email=intruder").data.decode()
    assert "intruder@example.com" in by_email
    assert "ada@example.com" not in by_email


def test_account_locks_after_four_failed_attempts(client, db):
    make_user(db, "Ada", "ada@example.com", "pw", "admin")

    for _ in range(3):
        resp = login(client, "ada@example.com", "wrong")
        assert b"attempt" in resp.data and b"remaining" in resp.data  # warns as they go

    resp = login(client, "ada@example.com", "wrong")  # 4th failure
    assert b"now locked for 10 minutes" in resp.data

    # even the CORRECT password is refused while locked
    resp = login(client, "ada@example.com", "pw")
    assert b"Too many failed attempts" in resp.data
    assert b"contact your administrator" in resp.data
    assert LoginLog.query.filter_by(success=True).count() == 0


def test_blocked_attempts_do_not_extend_the_lockout(client, db):
    """Hammering a locked account must not keep a legitimate user out forever."""
    make_user(db, "Ada", "ada@example.com", "pw", "admin")
    for _ in range(4):
        login(client, "ada@example.com", "wrong")

    before = lockout_seconds_remaining("ada@example.com")
    for _ in range(5):
        login(client, "ada@example.com", "guessing")  # all turned away
    after = lockout_seconds_remaining("ada@example.com")

    assert after <= before  # the clock keeps running down, it is not reset
    assert LoginLog.query.filter_by(blocked=True).count() == 5
    # blocked rows are recorded but not counted as failures
    assert LoginLog.query.filter_by(success=False, blocked=False).count() == 4


def test_lockout_expires_after_the_window(client, db):
    make_user(db, "Ada", "ada@example.com", "pw", "admin")
    for _ in range(4):
        login(client, "ada@example.com", "wrong")
    assert lockout_seconds_remaining("ada@example.com") > 0

    # age the failures past the 10 minute window
    for entry in LoginLog.query.all():
        entry.created_at -= timedelta(minutes=11)
    db.session.commit()

    assert lockout_seconds_remaining("ada@example.com") == 0
    resp = login(client, "ada@example.com", "pw")
    assert b"Outstanding balance" in resp.data  # can get back in


def test_a_success_clears_the_failure_count(client, db):
    make_user(db, "Ada", "ada@example.com", "pw", "admin")
    for _ in range(3):
        login(client, "ada@example.com", "wrong")
    login(client, "ada@example.com", "pw")
    client.get("/auth/logout")

    # three more failures must not tip it over, because the success reset the count
    for _ in range(3):
        login(client, "ada@example.com", "wrong")

    assert lockout_seconds_remaining("ada@example.com") == 0


def test_lockout_is_per_account(client, db):
    make_user(db, "Ada", "ada@example.com", "pw", "admin")
    make_user(db, "Bob", "bob@example.com", "pw", "admin")
    for _ in range(4):
        login(client, "ada@example.com", "wrong")

    assert lockout_seconds_remaining("ada@example.com") > 0
    assert lockout_seconds_remaining("bob@example.com") == 0
    resp = login(client, "bob@example.com", "pw")
    assert b"Outstanding balance" in resp.data  # Bob is unaffected


def test_login_log_requires_admin(client, db):
    resp = client.get("/admin/logins", follow_redirects=True)
    assert b"Log In" in resp.data  # anonymous visitors are bounced to the login page
