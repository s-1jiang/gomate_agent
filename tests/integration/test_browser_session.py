import time

from fastapi.testclient import TestClient

from app.core.browser_session import BROWSER_HEADER, COOKIE_PATH, SESSION_COOKIE
from app.core.security import token_digest
from app.main import create_app

CREDENTIALS = {"username": "remember_user", "password": "remember-test-password-123"}
WEB_HEADERS = {BROWSER_HEADER: "web"}


def sign_in(client, *, remember=True):
    assert client.post("/api/v1/auth/register", json=CREDENTIALS).status_code == 201
    response = client.post("/api/v1/auth/login", json={**CREDENTIALS, "remember_me": remember})
    assert response.status_code == 200
    return response


def test_persistent_cookie_restores_login_in_a_new_client_and_revokes_on_logout(client, settings):
    response = sign_in(client)
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie
    assert f"Path={COOKIE_PATH}" in cookie
    assert f"Max-Age={settings.remember_token_ttl_seconds}" in cookie
    assert response.json()["expires_in"] == settings.remember_token_ttl_seconds
    token = response.json()["access_token"]
    assert client.get("/api/v1/me").json()["username"] == CREDENTIALS["username"]
    assert client.get("/api/v1/me").headers["cache-control"] == "no-store"
    with client.app.state.database.connect() as connection:
        row = connection.execute("SELECT token_hash, expires_at FROM auth_tokens").fetchone()
        assert row["token_hash"] == token_digest(token)
        assert abs(row["expires_at"] - time.time() - settings.remember_token_ttl_seconds) < 5
    with TestClient(create_app(settings)) as reopened:
        reopened.cookies.update(client.cookies)
        assert reopened.get("/api/v1/me").status_code == 200
        assert reopened.post("/api/v1/auth/logout", headers=WEB_HEADERS).status_code == 204
        assert reopened.cookies.get(SESSION_COOKIE) is None
        assert reopened.get("/api/v1/me").status_code == 401
        assert (
            reopened.get(
                "/api/v1/me",
                headers={
                    "Authorization": f"Bearer {token}",
                },
            ).status_code
            == 401
        )
    assert (
        client.get("/api/v1/me").status_code == 401
    )  # Another tab cannot reuse the revoked cookie.


def test_without_remember_uses_normal_token_ttl_and_does_not_create_cookie(client, settings):
    response = sign_in(client, remember=False)
    assert response.json()["expires_in"] == settings.token_ttl_seconds
    assert client.cookies.get(SESSION_COOKIE) is None
    assert client.get("/api/v1/me").status_code == 401
    assert (
        client.get(
            "/api/v1/me",
            headers={
                "Authorization": f"Bearer {response.json()['access_token']}",
            },
        ).status_code
        == 200
    )


def test_cookie_writes_require_custom_header_and_cross_site_login_is_rejected(client):
    sign_in(client)
    body = {"title": "cookie session"}
    response = client.post("/api/v1/conversations", json=body)
    assert response.status_code == 403 and response.json()["error"]["code"] == "CSRF_REQUIRED"
    response = client.post(
        "/api/v1/conversations",
        json=body,
        headers={
            **WEB_HEADERS,
            "Sec-Fetch-Site": "cross-site",
        },
    )
    assert response.status_code == 403
    assert client.post("/api/v1/conversations", json=body, headers=WEB_HEADERS).status_code == 201
    assert (
        client.post(
            "/api/v1/auth/login",
            json=CREDENTIALS,
            headers={
                "Sec-Fetch-Site": "cross-site",
            },
        ).status_code
        == 403
    )


def test_expired_cookie_is_cleared_and_cannot_restore_login(client):
    sign_in(client)
    with client.app.state.database.connect(write=True) as connection:
        connection.execute("UPDATE auth_tokens SET expires_at = ?", (time.time() - 1,))
    response = client.get("/api/v1/me")
    assert response.status_code == 401
    assert "Max-Age=0" in response.headers["set-cookie"]
    assert client.cookies.get(SESSION_COOKIE) is None


def test_disabling_remember_revokes_previous_persistent_session(client):
    previous = sign_in(client).json()["access_token"]
    response = client.post("/api/v1/auth/login", json={**CREDENTIALS, "remember_me": False})
    assert response.status_code == 200 and client.cookies.get(SESSION_COOKIE) is None
    assert (
        client.get("/api/v1/me", headers={"Authorization": f"Bearer {previous}"}).status_code == 401
    )
    assert (
        client.get(
            "/api/v1/me",
            headers={
                "Authorization": f"Bearer {response.json()['access_token']}",
            },
        ).status_code
        == 200
    )


def test_failed_login_does_not_destroy_an_existing_session(client):
    sign_in(client)
    response = client.post(
        "/api/v1/auth/login",
        json={
            **CREDENTIALS,
            "password": "incorrect-password-123",
            "remember_me": False,
        },
    )
    assert response.status_code == 401
    assert client.cookies.get(SESSION_COOKIE) is not None
    assert client.get("/api/v1/me").status_code == 200


def test_secure_cookie_when_https_enabled(client, settings):
    settings.auth_cookie_secure = True
    response = sign_in(client)
    assert "Secure" in response.headers["set-cookie"]
    assert client.get("https://testserver/api/v1/me").status_code == 200


def test_invalid_bearer_never_falls_back_to_a_valid_cookie(client):
    sign_in(client)
    assert client.get("/api/v1/me", headers={"Authorization": "Bearer invalid"}).status_code == 401
