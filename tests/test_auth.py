from tests.conftest import make_user, login


def test_login_success(client, db):
    make_user(db, "Ada", "ada@example.com", "pw", "admin")
    resp = login(client, "ada@example.com", "pw")
    assert resp.status_code == 200
    assert b"Outstanding balance" in resp.data


def test_login_failure(client, db):
    make_user(db, "Ada", "ada@example.com", "pw", "admin")
    resp = login(client, "ada@example.com", "wrong-password")
    assert b"Invalid email or password" in resp.data


def test_anonymous_is_redirected_to_login(client, db):
    resp = client.get("/admin/", follow_redirects=True)
    assert b"Log In" in resp.data
