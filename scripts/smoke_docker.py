"""Exercise the local Compose stack through its frontend proxy; no external providers."""

import argparse
import json
import secrets
import subprocess
import time
import urllib.error
import urllib.request
from uuid import uuid4


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--check-restart", action="store_true")
    options = parser.parse_args()
    base = options.base_url.rstrip("/")
    token = None
    session_id = None

    def request(path, *, method="GET", body=None):
        headers = {"Accept": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if body is not None:
            headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(base + path, data=data, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=15) as response:
            payload = response.read()
            return json.loads(payload) if payload else None

    def ready():
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            try:
                if request("/health/ready")["status"] == "ok":
                    return
            except (OSError, urllib.error.URLError):
                pass
            time.sleep(0.5)
        raise RuntimeError("Backend not ready")

    ready()
    with urllib.request.urlopen(base + "/", timeout=10) as response:
        assert "GoMate" in response.read().decode()
    credentials = {
        "username": "smoke_" + uuid4().hex[:12],
        "password": secrets.token_urlsafe(24),
    }
    request("/api/v1/auth/register", method="POST", body=credentials)
    try:
        token = request("/api/v1/auth/login", method="POST", body=credentials)["access_token"]
        assert request("/api/v1/me")["username"] == credentials["username"]
        session_id = request(
            "/api/v1/conversations", method="POST", body={"title": "Docker smoke"}
        )["id"]
        doc = request(
            "/api/v1/knowledge/documents",
            method="POST",
            body={
                "title": "Docker smoke note",
                "source_ref": "smoke.txt",
                "content": "smokewalk riverside",
                "scope": "session",
                "session_id": session_id,
            },
        )
        hits = request(
            "/api/v1/knowledge/search",
            method="POST",
            body={
                "query": "smokewalk",
                "session_id": session_id,
            },
        )
        assert hits[0]["document_id"] == doc["id"] and hits[0]["label"] == "R1"
        if options.check_restart:
            subprocess.run(["docker", "compose", "restart", "backend"], check=True)
            ready()
        docs = request(f"/api/v1/knowledge/documents?session_id={session_id}")
        assert docs[0]["id"] == doc["id"]
        assert request("/api/v1/knowledge/documents") == []
        request(f"/api/v1/knowledge/documents/{doc['id']}", method="DELETE")
        print("PASS: frontend, proxy, auth, knowledge import, retrieval evidence and session scope")
        if options.check_restart:
            print("PASS: SQLite knowledge and login survive backend container restart")
    finally:
        if token:
            if session_id:
                request(f"/api/v1/conversations/{session_id}", method="DELETE")
            request("/api/v1/auth/logout", method="POST")
            try:
                request("/api/v1/me")
                raise AssertionError("Revoked token was accepted")
            except urllib.error.HTTPError as exc:
                assert exc.code == 401
            print("PASS: test conversation removed and login revoked")


if __name__ == "__main__":
    main()
