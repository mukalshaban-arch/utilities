from datetime import timedelta

from tests.conftest import make_user, login


def test_session_lifetime_is_five_minutes(app):
    assert app.config["PERMANENT_SESSION_LIFETIME"] == timedelta(minutes=5)
    assert app.config["SESSION_REFRESH_EACH_REQUEST"] is True


def test_ping_keepalive_when_logged_in(client, db):
    make_user(db, "Ada", "ada@example.com", "pw", "admin")
    login(client, "ada@example.com", "pw")

    resp = client.get("/auth/ping")

    assert resp.status_code == 204
    assert resp.data == b""


def test_ping_requires_login(client, db):
    resp = client.get("/auth/ping")
    assert resp.status_code == 302
    assert "/auth/login" in resp.headers["Location"]


def test_pages_embed_the_inactivity_timer(client, db):
    make_user(db, "Ada", "ada@example.com", "pw", "admin")
    login(client, "ada@example.com", "pw")

    body = client.get("/admin/").data.decode()

    assert "setTimeout(expire" in body  # the idle timer is wired
    assert "/auth/ping" in body  # keepalive target
    assert "300 * 1000" in body  # 5 minutes in milliseconds


def test_login_page_has_no_inactivity_timer(client, db):
    body = client.get("/auth/login").data.decode()
    assert "setTimeout(expire" not in body  # only runs once authenticated
