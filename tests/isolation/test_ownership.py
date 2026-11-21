import sqlite3

import pytest

from app.core.identity import AuthContext
from app.db.repositories import AuthRepository, ConversationRepository, RunRepository


def test_foreign_sessions_runs_and_cursors_are_inaccessible(client, login):
    alice, bob = login("alice"), login("bob")
    session = client.post("/api/v1/conversations", headers=alice, json={}).json()["id"]
    path = f"/api/v1/conversations/{session}/messages"
    run = client.post(
        path, headers=alice, json={"content": "ALICE_PRIVATE_CANARY", "client_message_id": "1"}
    ).json()
    assert client.get("/api/v1/conversations", headers=bob).json() == []
    for method, url, body in [
        ("GET", path, None),
        ("POST", path, {"content": "forged", "client_message_id": "1"}),
        ("DELETE", f"/api/v1/conversations/{session}", None),
        ("GET", f"/api/v1/runs/{run['id']}", None),
        ("POST", f"/api/v1/runs/{run['id']}/cancel", None),
    ]:
        response = client.request(method, url, headers=bob, json=body)
        assert response.status_code == 404
        assert "ALICE_PRIVATE_CANARY" not in response.text
    second = client.post("/api/v1/conversations", headers=alice, json={}).json()["id"]
    message = client.get(path, headers=alice).json()[0]["id"]
    response = client.get(
        f"/api/v1/conversations/{second}/messages", headers=alice, params={"after": message}
    )
    assert response.status_code == 404


def test_composite_foreign_key_rejects_mismatched_owner(client):
    database = client.app.state.database
    auth_repository = AuthRepository(database)
    alice = auth_repository.register("alice", "test-only-hash")
    bob = auth_repository.register("bob", "test-only-hash")
    session = ConversationRepository(database, AuthContext(alice["id"], "alice")).create("private")
    with pytest.raises(sqlite3.IntegrityError), database.connect(write=True) as connection:
        connection.execute(
            "INSERT INTO messages(id, user_id, session_id, role, content, created_at) "
            "VALUES ('forged', ?, ?, 'user', 'secret', '2026-11-21')",
            (bob["id"], session["id"]),
        )


def test_lease_busy_expiry_fencing_and_late_result(client, settings):
    database = client.app.state.database
    user = AuthRepository(database).register("alice", "test-only-hash")
    auth = AuthContext(user["id"], "alice")
    session = ConversationRepository(database, auth).create("private")["id"]
    repository = RunRepository(database, auth)
    first, _ = repository.accept(session, "one", "first", settings)
    from app.core.errors import AppError

    with pytest.raises(AppError, match="此会话已有运行中的任务"):
        repository.accept(session, "two", "second", settings)
    with database.connect(write=True) as connection:
        connection.execute("UPDATE runs SET deadline = 0")
        connection.execute("UPDATE session_leases SET expires_at = 0")
    second, _ = repository.accept(session, "two", "second", settings)
    repository.finish_scaffold(first["id"])
    with database.connect() as connection:
        lease = connection.execute("SELECT * FROM session_leases").fetchone()
        assert lease["run_id"] == second["id"]
        assert lease["fencing_token"] == 2
    assert repository.get(first["id"])["status"] == "timed_out"
    assert repository.cancel(second["id"])["status"] == "cancelled"
    repository.finish_scaffold(second["id"])
    assert repository.get(second["id"])["status"] == "cancelled"


def test_delete_cascades_messages_runs_and_lease(client, login):
    headers = login()
    session = client.post("/api/v1/conversations", headers=headers, json={}).json()["id"]
    client.post(
        f"/api/v1/conversations/{session}/messages",
        headers=headers,
        json={"content": "private", "client_message_id": "one"},
    )
    assert client.delete(f"/api/v1/conversations/{session}", headers=headers).status_code == 204
    with client.app.state.database.connect() as connection:
        for table in ("messages", "runs", "session_leases"):
            assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
