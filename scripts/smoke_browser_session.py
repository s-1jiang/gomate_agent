"""Exercise persistent login through the local proxy without external provider calls."""

import argparse
import copy
import json
import secrets
import urllib.error
import urllib.request
from http.cookiejar import CookieJar
from uuid import uuid4


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    options = parser.parse_args()
    base = options.base_url.rstrip("/")
    cookies = CookieJar()
    browser = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookies))
    session = None

    def request(opener, path, body=None, *, method=None, web=True):
        headers = {"Content-Type": "application/json"}
        if web:
            headers["X-GoMate-Request"] = "web"
        req = urllib.request.Request(
            base + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers=headers,
            method=method or ("POST" if body is not None else "GET"),
        )
        with opener.open(req, timeout=10) as response:
            data = response.read()
            return (json.loads(data) if data else None), response.headers

    credentials = {
        "username": "remember_" + uuid4().hex[:12],
        "password": secrets.token_urlsafe(24),
    }
    request(browser, "/api/v1/auth/register", credentials)
    try:
        _, headers = request(browser, "/api/v1/auth/login", {**credentials, "remember_me": True})
        cookie_header = headers.get("Set-Cookie", "")
        assert "HttpOnly" in cookie_header and "SameSite=lax" in cookie_header
        assert "Max-Age=" in cookie_header and "Path=/api/v1" in cookie_header
        restored_cookies = CookieJar()
        for cookie in cookies:
            restored_cookies.set_cookie(copy.copy(cookie))
        reopened = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(restored_cookies))
        user, _ = request(reopened, "/api/v1/me")
        assert user["username"] == credentials["username"]
        print("PASS: persistent HttpOnly cookie restores login in a new client")
        try:
            request(reopened, "/api/v1/conversations", {"title": "denied"}, web=False)
            raise AssertionError("Cookie write without request header was accepted")
        except urllib.error.HTTPError as exc:
            assert exc.code == 403
        conversation, _ = request(reopened, "/api/v1/conversations", {"title": "Login smoke"})
        session = conversation["id"]
        request(reopened, f"/api/v1/conversations/{session}", method="DELETE")
        session = None
        request(reopened, "/api/v1/auth/logout", method="POST")
        for client in (browser, reopened):
            try:
                request(client, "/api/v1/me")
                raise AssertionError("Login was restored after explicit logout")
            except urllib.error.HTTPError as exc:
                assert exc.code == 401
        print("PASS: protected cookie writes and server-side logout revocation")
    finally:
        if session:
            request(browser, f"/api/v1/conversations/{session}", method="DELETE")
        try:
            request(browser, "/api/v1/auth/logout", method="POST")
        except urllib.error.HTTPError as exc:
            assert exc.code == 401


if __name__ == "__main__":
    main()
