import time

from fastapi.testclient import TestClient

from app.core.security import token_digest
from app.db.database import Database
from app.main import create_app


def test_health_openapi_and_migration_are_ready(client):
    assert client.get("/health/live").json()["status"] == "ok"
    assert client.get("/health/ready").json()["database"] == "sqlite"
    assert "/api/v1/runs/{run_id}" in client.get("/openapi.json").json()["paths"]
    client.app.state.database.migrate()
    with client.app.state.database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == 1
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_password_token_storage_logout_and_expiry(client, login):
    headers = login()
    raw_token = headers["Authorization"].split()[1]
    assert client.get("/api/v1/me", headers=headers).json()["username"] == "alice"
    with client.app.state.database.connect() as connection:
        row = connection.execute("SELECT password_hash FROM users").fetchone()
        assert row[0].startswith("$argon2id$")
        stored = connection.execute("SELECT token_hash FROM auth_tokens").fetchone()[0]
        assert stored != raw_token
        assert stored == token_digest(raw_token)
    assert client.post("/api/v1/auth/logout", headers=headers).status_code == 204
    assert client.get("/api/v1/me", headers=headers).status_code == 401
    headers = login("bob")
    with client.app.state.database.connect(write=True) as connection:
        connection.execute("UPDATE auth_tokens SET expires_at = ?", (time.time() - 1,))
    assert client.get("/api/v1/me", headers=headers).status_code == 401


def test_login_throttle_is_persisted(client):
    payload = {"username": "unknown", "password": "incorrect-password"}
    for _ in range(5):
        assert client.post("/api/v1/auth/login", json=payload).status_code == 401
    response = client.post("/api/v1/auth/login", json=payload)
    assert response.status_code == 429
    assert response.json()["error"]["code"] == "RATE_LIMITED"


def test_validation_does_not_echo_password_or_accept_user_identity(client, login):
    response = client.post("/api/v1/auth/register", json={"username": "a", "password": "secret"})
    assert response.status_code == 422
    assert "secret" not in response.text
    response = client.post(
        "/api/v1/conversations", headers=login(), json={"title": "test", "user_id": "forged"}
    )
    assert response.status_code == 422


def test_message_run_idempotency_and_failure_are_explicit(client, login):
    headers = login()
    session = client.post("/api/v1/conversations", headers=headers, json={}).json()["id"]
    path = f"/api/v1/conversations/{session}/messages"
    body = {"content": "安排周末游玩", "client_message_id": "client-001"}
    response = client.post(path, headers=headers, json=body)
    assert response.status_code == 202
    run_id = response.json()["id"]
    run = client.get(f"/api/v1/runs/{run_id}", headers=headers).json()
    assert run["status"] == "failed"
    assert run["error_code"] == "WORKFLOW_NOT_IMPLEMENTED"
    assert run["tool_calls"] == run["llm_calls"] == run["external_requests"] == 0
    assert client.post(path, headers=headers, json=body).json()["id"] == run_id
    response = client.post(path, headers=headers, json={**body, "content": "different"})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    history = client.get(path, headers=headers).json()
    assert len(history) == 1
    assert history[0]["content"] == body["content"]
    assert client.get(path, headers=headers, params={"after": history[0]["id"]}).json() == []


def test_restart_interrupts_previous_process_tasks(settings, login, client):
    headers = login()
    session = client.post("/api/v1/conversations", headers=headers, json={}).json()["id"]
    from app.core.identity import AuthContext
    from app.db.repositories import AuthRepository, RunRepository

    token = headers["Authorization"].split()[1]
    user = AuthRepository(Database(settings.database_path)).authenticate(token_digest(token))
    repository = RunRepository(Database(settings.database_path), AuthContext(user["id"], "alice"))
    run, _ = repository.accept(session, "pending", "pending message", settings)
    with TestClient(create_app(settings)) as restarted:
        result = restarted.get(f"/api/v1/runs/{run['id']}", headers=headers).json()
        assert result["status"] == "interrupted"
        # Pending user messages survive the worker restart.
        history = restarted.get(f"/api/v1/conversations/{session}/messages", headers=headers).json()
        assert history[0]["content"] == "pending message"
