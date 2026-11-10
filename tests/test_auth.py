from datetime import UTC, datetime, timedelta

import pytest
from conftest import PASSPHRASE
from fastapi import Depends
from fastapi.testclient import TestClient

from today.app import create_app
from today.auth import COOKIE_NAME, LoginLimiter, require_session
from today.config import Settings


@pytest.fixture
def client(settings: Settings) -> TestClient:
    app = create_app(settings)

    @app.get("/_protected", dependencies=[Depends(require_session)])
    def protected() -> dict:
        return {"ok": True}

    return TestClient(app, base_url="https://testserver", follow_redirects=False)


def login(client: TestClient, passphrase: str = PASSPHRASE):
    return client.post("/login", data={"passphrase": passphrase})


def test_healthz_is_public(client: TestClient):
    assert client.get("/healthz").json() == {"status": "ok"}


def test_login_page_is_public(client: TestClient):
    response = client.get("/login")
    assert response.status_code == 200
    assert 'name="passphrase"' in response.text


def test_login_success_sets_cookie(client: TestClient):
    response = login(client)
    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert COOKIE_NAME in response.cookies
    assert client.get("/_protected").json() == {"ok": True}


def test_login_wrong_passphrase_401(client: TestClient):
    response = login(client, "wrong")
    assert response.status_code == 401
    assert "Wrong passphrase" in response.text
    assert COOKIE_NAME not in response.cookies


def test_login_rate_limited_after_5_failures(client: TestClient):
    for _ in range(5):
        assert login(client, "wrong").status_code == 401
    assert login(client).status_code == 429


def test_limiter_window_expires():
    limiter = LoginLimiter()
    t0 = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)
    for _ in range(5):
        limiter.record_failure("1.2.3.4", t0)
    assert limiter.is_blocked("1.2.3.4", t0 + timedelta(minutes=9))
    assert not limiter.is_blocked("1.2.3.4", t0 + timedelta(minutes=11))
    assert not limiter.is_blocked("5.6.7.8", t0)


def test_session_cookie_flags(client: TestClient):
    header = login(client).headers["set-cookie"].lower()
    assert "httponly" in header
    assert "secure" in header
    assert "samesite=lax" in header
    assert f"max-age={90 * 24 * 3600}" in header


def test_cookie_secure_can_be_disabled_for_local_dev(settings: Settings):
    local = Settings(**{**settings.__dict__, "cookie_secure": False})
    client = TestClient(create_app(local), follow_redirects=False)
    header = login(client).headers["set-cookie"].lower()
    assert "secure" not in header


def test_protected_route_without_session_redirects(client: TestClient):
    response = client.get("/_protected")
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_htmx_request_without_session_redirects(client: TestClient):
    response = client.get("/_protected", headers={"HX-Request": "true"})
    assert response.status_code == 200
    assert response.headers["HX-Redirect"] == "/login"
    assert response.text == ""


def test_tampered_cookie_rejected(client: TestClient):
    client.cookies.set(COOKIE_NAME, "owner.forged-signature")
    assert client.get("/_protected").status_code == 303


def test_logout_clears_cookie(client: TestClient):
    login(client)
    response = client.post("/logout")
    assert response.status_code == 303
    assert response.headers["location"] == "/login"
    assert client.get("/_protected").status_code == 303
