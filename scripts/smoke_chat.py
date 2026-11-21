"""Offline HTTP chat smoke: fake key, loopback provider and temporary SQLite only."""

import hashlib
import json
import secrets
import socket
import tempfile
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import uvicorn

from app.core.config import Settings
from app.main import create_app


def main():
    calls = []

    class Provider(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            assert self.path == "/chat/completions"
            assert self.headers["Authorization"] == "Bearer fake-smoke-key"
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            calls.append(body)
            payload = json.dumps(
                {
                    "choices": [
                        {
                            "message": {
                                "content": "The riverside path is suitable for walking. [R1]"
                            },
                            "finish_reason": "stop",
                        }
                    ]
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    provider = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    provider_thread = threading.Thread(target=provider.serve_forever, daemon=True)
    provider_thread.start()
    api_socket = socket.socket()
    api_socket.bind(("127.0.0.1", 0))
    base = f"http://127.0.0.1:{api_socket.getsockname()[1]}"
    token = None

    def request(path, body=None, method=None):
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        req = urllib.request.Request(
            base + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers=headers,
            method=method or ("POST" if body is not None else "GET"),
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            data = response.read()
            return json.loads(data) if data else None

    with tempfile.TemporaryDirectory(prefix="gomate-chat-") as temporary:
        app = create_app(
            Settings(
                _env_file=None,
                database_path=Path(temporary) / "smoke.db",
                deepseek_api_key="fake-smoke-key",
                deepseek_base_url=f"http://127.0.0.1:{provider.server_port}",
            )
        )
        server = uvicorn.Server(uvicorn.Config(app, log_level="error", access_log=False))
        api_thread = threading.Thread(target=lambda: server.run(sockets=[api_socket]), daemon=True)
        api_thread.start()
        try:
            deadline = time.monotonic() + 10
            while not server.started:
                if time.monotonic() > deadline:
                    raise RuntimeError("Smoke API startup timed out")
                time.sleep(0.02)
            credentials = {"username": "smoke_user", "password": secrets.token_urlsafe(24)}
            request("/api/v1/auth/register", credentials)
            token = request("/api/v1/auth/login", credentials)["access_token"]
            session = request("/api/v1/conversations", {"title": "smoke"})["id"]
            doc = request(
                "/api/v1/knowledge/documents",
                {
                    "title": "Walk notes",
                    "source_ref": "walk.txt",
                    "scope": "session",
                    "session_id": session,
                    "content": "The riverside path is suitable for walking.\n",
                },
            )
            path = f"/api/v1/conversations/{session}/messages"
            body = {"client_message_id": "one", "content": "Where can I go walking?"}
            run = request(path, body)

            def finished(run_id):
                deadline = time.monotonic() + 5
                while True:
                    result = request(f"/api/v1/runs/{run_id}")
                    if result["status"] not in ("queued", "running"):
                        assert result["status"] == "succeeded", result["error_code"]
                        return
                    assert time.monotonic() < deadline
                    time.sleep(0.02)

            finished(run["id"])
            assert request(path, body)["id"] == run["id"]
            assert len(calls) == 1
            messages = request(path)
            assert len(messages) == 2 and messages[-1]["role"] == "assistant"
            source = messages[-1]["sources"][0]
            assert source["document_id"] == doc["id"] and source["cited"]
            assert source["content_hash"] == hashlib.sha256(source["excerpt"].encode()).hexdigest()
            assert source["source_ref"] == "walk.txt" and source["start_line"] == 1
            print("PASS: HTTP chat, provider protocol, persistence, idempotency and evidence")
            second = request(path, {"client_message_id": "two", "content": "More about walking"})
            finished(second["id"])
            assert any(item["role"] == "assistant" for item in calls[-1]["messages"])
            request(f"/api/v1/knowledge/documents/{doc['id']}", method="DELETE")
            source = request(path)[1]["sources"][0]
            assert not source["available"] and source["excerpt"] is None
            print("PASS: multi-turn context and deleted evidence redaction; no external calls")
        finally:
            server.should_exit = True
            api_thread.join(timeout=10)
            api_socket.close()
            provider.shutdown()
            provider.server_close()
            provider_thread.join(timeout=5)
            assert not api_thread.is_alive()


if __name__ == "__main__":
    main()
