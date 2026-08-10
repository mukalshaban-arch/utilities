import re
from datetime import datetime, timedelta

from app.models import PasswordResetRequest, User, lockout_seconds_remaining
from tests.conftest import make_user, login


def request_reset(client, email):
    return client.post("/auth/forgot", data={"email": email}, follow_redirects=True)


def issue_passkey(client, db, request_id):
    """Admin generates the passkey; it is shown once in the flash message."""
    resp = client.post(f"/admin/password-resets/{request_id}/issue", follow_redirects=True)
    match = re.search(r"([A-Z2-9]{8})", resp.data.decode())
    return match.group(1)


def test_user_requests_a_reset_and_admin_is_alerted(client, db):
    make_user(db, "Ada", "ada@example.com", "pw", "admin")
    make_user(db, "Bob", "bob@example.com", "pw", "admin")

    request_reset(client, "bob@example.com")

    reset = PasswordResetRequest.query.one()
    assert reset.user.email == "bob@example.com"
    assert reset.status == "pending"
    assert reset.passkey_hash is None  # nothing issued yet

    login(client, "ada@example.com", "pw")
    dashboard = client.get("/admin/").data.decode()
    assert "awaiting a passkey" in dashboard
    assert "Awaiting passkey" in client.get("/admin/password-resets").data.decode()


def test_unknown_email_does_not_reveal_itself(client, db):
    resp = request_reset(client, "nobody@example.com")

    assert b"If that email is registered" in resp.data  # same message either way
    assert PasswordResetRequest.query.count() == 0


def test_full_reset_flow_ends_at_login_with_the_new_password(client, db):
    make_user(db, "Ada", "ada@example.com", "pw", "admin")
    make_user(db, "Bob", "bob@example.com", "old-password", "admin")

    request_reset(client, "bob@example.com")
    reset = PasswordResetRequest.query.one()

    login(client, "ada@example.com", "pw")
    passkey = issue_passkey(client, db, reset.id)
    client.get("/auth/logout")

    assert reset.status == "issued"
    assert reset.passkey_hash != passkey  # only the hash is stored

    # Bob enters the passkey and is prompted for a new password
    resp = client.post(
        "/auth/reset",
        data={"email": "bob@example.com", "passkey": passkey},
        follow_redirects=True,
    )
    assert b"Set new password" in resp.data

    resp = client.post(
        "/auth/reset/password",
        data={"password": "brand-new-pass", "confirm": "brand-new-pass"},
        follow_redirects=True,
    )
    assert b"Your password has been changed. Please log in." in resp.data
    assert b"Log In" in resp.data  # back at the login page

    assert PasswordResetRequest.query.one().status == "used"
    assert User.query.filter_by(email="bob@example.com").one().check_password("brand-new-pass")

    resp = login(client, "bob@example.com", "brand-new-pass")
    assert b"Outstanding balance" in resp.data


def test_wrong_passkey_is_rejected(client, db):
    make_user(db, "Ada", "ada@example.com", "pw", "admin")
    make_user(db, "Bob", "bob@example.com", "old", "admin")
    request_reset(client, "bob@example.com")
    login(client, "ada@example.com", "pw")
    issue_passkey(client, db, PasswordResetRequest.query.one().id)
    client.get("/auth/logout")

    resp = client.post(
        "/auth/reset", data={"email": "bob@example.com", "passkey": "WRONGKEY"}, follow_redirects=True
    )

    assert b"not valid" in resp.data
    assert User.query.filter_by(email="bob@example.com").one().check_password("old")


def test_expired_passkey_is_rejected(client, db):
    make_user(db, "Ada", "ada@example.com", "pw", "admin")
    make_user(db, "Bob", "bob@example.com", "old", "admin")
    request_reset(client, "bob@example.com")
    login(client, "ada@example.com", "pw")
    reset = PasswordResetRequest.query.one()
    passkey = issue_passkey(client, db, reset.id)
    client.get("/auth/logout")

    reset.expires_at = datetime.utcnow() - timedelta(minutes=1)
    db.session.commit()

    resp = client.post(
        "/auth/reset", data={"email": "bob@example.com", "passkey": passkey}, follow_redirects=True
    )

    assert b"expired" in resp.data
    assert User.query.filter_by(email="bob@example.com").one().check_password("old")


def test_passkey_cannot_be_reused(client, db):
    make_user(db, "Ada", "ada@example.com", "pw", "admin")
    make_user(db, "Bob", "bob@example.com", "old", "admin")
    request_reset(client, "bob@example.com")
    login(client, "ada@example.com", "pw")
    passkey = issue_passkey(client, db, PasswordResetRequest.query.one().id)
    client.get("/auth/logout")

    client.post("/auth/reset", data={"email": "bob@example.com", "passkey": passkey}, follow_redirects=True)
    client.post(
        "/auth/reset/password",
        data={"password": "first-new-pw", "confirm": "first-new-pw"},
        follow_redirects=True,
    )

    # the same passkey a second time must not work
    resp = client.post(
        "/auth/reset", data={"email": "bob@example.com", "passkey": passkey}, follow_redirects=True
    )
    assert b"not valid" in resp.data


def test_mismatched_passwords_are_rejected(client, db):
    make_user(db, "Ada", "ada@example.com", "pw", "admin")
    make_user(db, "Bob", "bob@example.com", "old", "admin")
    request_reset(client, "bob@example.com")
    login(client, "ada@example.com", "pw")
    passkey = issue_passkey(client, db, PasswordResetRequest.query.one().id)
    client.get("/auth/logout")
    client.post("/auth/reset", data={"email": "bob@example.com", "passkey": passkey}, follow_redirects=True)

    resp = client.post(
        "/auth/reset/password",
        data={"password": "password-one", "confirm": "password-two"},
        follow_redirects=True,
    )

    assert b"Passwords do not match" in resp.data
    assert User.query.filter_by(email="bob@example.com").one().check_password("old")


def test_reset_clears_an_existing_lockout(client, db):
    """A user locked out by failed attempts can get straight back in after a reset."""
    make_user(db, "Ada", "ada@example.com", "pw", "admin")
    make_user(db, "Bob", "bob@example.com", "old", "admin")
    for _ in range(4):
        login(client, "bob@example.com", "wrong")
    assert lockout_seconds_remaining("bob@example.com") > 0

    request_reset(client, "bob@example.com")
    login(client, "ada@example.com", "pw")
    passkey = issue_passkey(client, db, PasswordResetRequest.query.one().id)
    client.get("/auth/logout")

    client.post("/auth/reset", data={"email": "bob@example.com", "passkey": passkey}, follow_redirects=True)
    client.post(
        "/auth/reset/password",
        data={"password": "brand-new-pw", "confirm": "brand-new-pw"},
        follow_redirects=True,
    )

    assert lockout_seconds_remaining("bob@example.com") == 0
    resp = login(client, "bob@example.com", "brand-new-pw")
    assert b"Outstanding balance" in resp.data


def test_login_page_links_to_forgot_password(client, db):
    body = client.get("/auth/login").data.decode()
    assert "Forgot password?" in body
    assert "/auth/forgot" in body
