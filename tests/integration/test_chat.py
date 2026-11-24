import asyncio
import json
import sqlite3
import time
from pathlib import Path

import httpx
import pytest

from app.core.identity import AuthContext
from app.db.database import Database
from app.db.repositories import AuthRepository, ConversationRepository, RunRepository
from app.integrations.deepseek import DeepSeekClient
from app.retrieval.repository import KnowledgeRepository, digest
from app.schemas.knowledge import DocumentCreate


@pytest.fixture
def provider(client, settings):
    settings.deepseek_api_key = "fake-test-key"
    calls, answers = [], ["这是文字回复。"]

    async def handler(request):
        calls.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {"kind": "answer", "answer": answers[-1], "tasks": []}
                            )
                        },
                        "finish_reason": "stop",
                    }
                ],
            },
        )

    client.app.state.chat.model = DeepSeekClient(settings, transport=httpx.MockTransport(handler))
    return calls, answers


def conversation(client, headers):
    return client.post("/api/v1/conversations", headers=headers, json={}).json()["id"]


def send(client, headers, session, text="你好", key="one"):
    path = f"/api/v1/conversations/{session}/messages"
    response = client.post(
        path,
        headers=headers,
        json={
            "content": text,
            "client_message_id": key,
        },
    )
    assert response.status_code == 202
    run = client.get(f"/api/v1/runs/{response.json()['id']}", headers=headers).json()
    messages = client.get(path, headers=headers).json()
    return run, messages


def document(client, headers, session, **overrides):
    payload = {
        "title": "散步笔记",
        "source_ref": "我的笔记.md",
        "scope": "session",
        "session_id": session,
        "content": "周末散步建议走河边。\n咖啡馆适合午后休息。\n",
    }
    response = client.post(
        "/api/v1/knowledge/documents", headers=headers, json={**payload, **overrides}
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_text_chat_history_idempotency_and_persistence(client, login, provider):
    calls, answers = provider
    headers = login()
    session = conversation(client, headers)
    run, messages = send(client, headers, session, "我的名字是小王")
    assert run["status"] == "succeeded"
    assert (run["llm_calls"], run["external_requests"], run["tool_calls"]) == (1, 1, 1)
    assert [message["role"] for message in messages] == ["user", "assistant"]
    assert messages[-1]["content"] == "这是文字回复。"
    assert messages[-1]["retrieval_status"] == "no_matches"
    assert messages[-1]["sources"] == []
    send(client, headers, session, "我的名字是小王")
    assert len(calls) == 1  # Same request ID does not produce another paid model call.
    answers.append("你叫小王。")
    run, messages = send(client, headers, session, "我叫什么名字？", "two")
    assert run["status"] == "succeeded"
    prompt = calls[-1]["messages"]
    assert [item["role"] for item in prompt] == ["system", "user", "assistant", "user"]
    assert "我的名字是小王" in prompt[1]["content"]
    assert messages[-1]["content"] == "你叫小王。"
    second = conversation(client, headers)
    send(client, headers, second, "你好", "three")
    assert "小王" not in json.dumps(calls[-1], ensure_ascii=False)


def test_retrieved_evidence_labels_hashes_and_deleted_source_redaction(client, login, provider):
    calls, answers = provider
    answers.append("可以沿河边散步。[R1] 未知依据[R99]")
    headers = login()
    session = conversation(client, headers)
    original = "\n# 河边散步\r\n周末散步建议走河边。\r\n"
    doc = document(client, headers, session, content=original)
    run, messages = send(client, headers, session, "周末散步有什么建议？")
    assert run["status"] == "succeeded"
    answer = messages[-1]
    assert answer["retrieval_status"] == "retrieved"
    assert "[R1]" in answer["content"] and "[R99]" not in answer["content"]
    assert "来源未核实" in answer["content"]
    source = answer["sources"][0]
    assert source["cited"] and source["available"]
    assert source["document_id"] == doc["id"]
    assert source["document_version"] == 1
    assert source["source_ref"] == "我的笔记.md"
    assert source["retrieval_method"] == "lexical"
    assert (source["start_line"], source["end_line"]) == (1, 3)
    assert source["excerpt"] == original.replace("\r\n", "\n")
    assert source["content_hash"] == digest(source["excerpt"])
    assert source["document_hash"] == doc["content_hash"]
    assert "周末散步建议走河边" in calls[0]["messages"][-1]["content"]
    assert (
        client.delete(f"/api/v1/knowledge/documents/{doc['id']}", headers=headers).status_code
        == 204
    )
    history = client.get(f"/api/v1/conversations/{session}/messages", headers=headers).json()
    tombstone = history[-1]["sources"][0]
    assert not tombstone["available"]
    assert tombstone["excerpt"] is None and tombstone["source_ref"] is None
    with client.app.state.database.connect() as connection:
        snapshot = connection.execute(
            "SELECT sources_json FROM messages WHERE role = 'assistant'"
        ).fetchone()[0]
        assert "周末散步建议走河边" not in snapshot
    assert (
        client.post(
            "/api/v1/knowledge/search",
            headers=headers,
            json={
                "session_id": session,
                "query": "周末散步",
            },
        ).json()
        == []
    )


def test_recalled_but_uncited_source_is_not_claimed_as_citation(client, login, provider):
    headers = login()
    session = conversation(client, headers)
    document(client, headers, session)
    _, messages = send(client, headers, session, "周末散步")
    assert messages[-1]["sources"]
    assert not any(source["cited"] for source in messages[-1]["sources"])


def test_scope_filter_before_top_k_and_direct_access_checks(client, login, provider):
    alice, bob = login("alice"), login("bob")
    first, second = conversation(client, alice), conversation(client, alice)
    bob_session = conversation(client, bob)
    doc = document(client, alice, first, content="河边散步 ALICE_SESSION_CANARY")
    shared = document(client, alice, None, scope="user", content="河边散步 ALICE_USER_NOTE")
    document(client, bob, bob_session, content="河边散步 BOB_PRIVATE_CANARY")
    result = client.post(
        "/api/v1/knowledge/search",
        headers=alice,
        json={"session_id": second, "query": "河边散步", "limit": 1},
    )
    assert result.status_code == 200
    assert [item["document_id"] for item in result.json()] == [shared["id"]]
    assert doc["id"] not in client.get("/api/v1/knowledge/documents", headers=bob).text
    for method, path, body in [
        ("GET", f"/api/v1/knowledge/documents?session_id={first}", None),
        ("POST", "/api/v1/knowledge/search", {"session_id": first, "query": "河边散步"}),
        ("DELETE", f"/api/v1/knowledge/documents/{doc['id']}", None),
        (
            "POST",
            "/api/v1/knowledge/documents",
            {
                "title": "forged",
                "content": "forged",
                "scope": "session",
                "session_id": first,
            },
        ),
    ]:
        assert client.request(method, path, headers=bob, json=body).status_code == 404
    calls, _ = provider
    send(client, alice, second, "河边散步")
    prompt = json.dumps(calls[-1], ensure_ascii=False)
    assert "ALICE_USER_NOTE" in prompt
    assert "ALICE_SESSION_CANARY" not in prompt and "BOB_PRIVATE_CANARY" not in prompt


@pytest.mark.parametrize(
    "body",
    [
        {"scope": "session", "session_id": None},
        {"scope": "user", "session_id": "forged"},
        {"scope": "public", "session_id": None},
        {"content": "   "},
        {"user_id": "forged"},
    ],
)
def test_invalid_document_scope_or_identity_is_rejected(client, login, body):
    response = client.post(
        "/api/v1/knowledge/documents",
        headers=login(),
        json={
            "title": "test",
            "content": "text",
            "scope": "user",
            **body,
        },
    )
    assert response.status_code == 422


def execution_context(client, settings):
    database = client.app.state.database
    user = AuthRepository(database).register("runner", "test-only-hash")
    auth = AuthContext(user["id"], "runner")
    session = ConversationRepository(database, auth).create("chat")["id"]
    repository = RunRepository(database, auth)
    run, _ = repository.accept(session, "run-one", "河边散步", settings)
    return database, auth, session, repository, run


@pytest.mark.parametrize("stop", ["cancel", "deadline", "delete"])
def test_inflight_model_is_cancelled_and_late_answer_is_not_saved(client, settings, stop):
    database, auth, session, repository, run = execution_context(client, settings)

    async def scenario():
        entered, cancelled = asyncio.Event(), asyncio.Event()

        class SlowModel:
            async def complete(self, messages, budget, **kwargs):
                await budget.reserve("llm")
                await budget.reserve("external")
                entered.set()
                try:
                    await asyncio.sleep(30)
                except asyncio.CancelledError:
                    cancelled.set()
                    raise
                return "LATE_ANSWER_CANARY"

        service = client.app.state.chat
        service.model = SlowModel()
        if stop == "deadline":
            with database.connect(write=True) as connection:
                connection.execute(
                    "UPDATE runs SET deadline = ? WHERE id = ?", (time.time() + 0.2, run["id"])
                )
        job = asyncio.create_task(service.run(auth, run["id"]))
        await asyncio.wait_for(entered.wait(), 2)
        if stop == "cancel":
            repository.cancel(run["id"])
            service.cancel(auth, run["id"])
        elif stop == "delete":
            ConversationRepository(database, auth).delete(session)
        await asyncio.wait_for(job, 3)
        assert cancelled.is_set()
        assert not service.tasks

    asyncio.run(scenario())
    with database.connect() as connection:
        assert (
            connection.execute("SELECT COUNT(*) FROM messages WHERE role='assistant'").fetchone()[0]
            == 0
        )
    if stop != "delete":
        result = repository.get(run["id"])
        assert result["status"] == ("cancelled" if stop == "cancel" else "timed_out")
        assert result["llm_calls"] == result["external_requests"] == 1


def test_deleting_evidence_during_inference_discards_answer(client, settings):
    database, auth, session, repository, run = execution_context(client, settings)
    knowledge = KnowledgeRepository(database, auth)
    doc = knowledge.create(
        DocumentCreate(
            title="散步",
            content="河边散步",
            session_id=session,
        )
    )

    class DeletingModel:
        async def complete(self, messages, budget, **kwargs):
            knowledge.delete(doc["id"])
            return json.dumps({"kind": "answer", "answer": "依据旧资料。[R1]", "tasks": []})

    service = client.app.state.chat
    service.model = DeletingModel()
    asyncio.run(service.run(auth, run["id"]))
    assert repository.get(run["id"])["error_code"] == "KNOWLEDGE_CHANGED"
    assert len(ConversationRepository(database, auth).messages(session, 100, None)) == 1


def test_upgrade_preserves_existing_messages_and_is_repeatable(tmp_path):
    path = tmp_path / "upgrade.db"
    migration = Path(__file__).parents[2] / "app/db/migrations/0001_foundation.sql"
    with sqlite3.connect(path) as connection:
        connection.executescript(migration.read_text(encoding="utf-8"))
        connection.execute("CREATE TABLE schema_migrations(version TEXT PRIMARY KEY)")
        connection.execute("INSERT INTO schema_migrations VALUES ('0001_foundation')")
        connection.execute("INSERT INTO users VALUES ('user', 'user', 'hash', '2026-11-21')")
        connection.execute(
            "INSERT INTO conversations VALUES ('session', 'user', 'old', '2026-11-21')"
        )
        connection.execute(
            "INSERT INTO messages VALUES "
            "('message','user','session','user','old content',NULL,'2026-11-21')"
        )
    database = Database(path)
    database.migrate()
    database.migrate()
    with database.connect() as connection:
        row = connection.execute("SELECT * FROM messages").fetchone()
        assert row["content"] == "old content"
        assert row["sources_json"] == "[]" and row["retrieval_status"] is None
        assert connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == 3
