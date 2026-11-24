import asyncio
import json
import time
from dataclasses import dataclass
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.identity import AuthContext
from app.db.repositories import AuthRepository, ConversationRepository, RunRepository
from app.jobs.dispatcher import QueueDispatcher
from app.jobs.repository import QueueRepository
from app.main import create_app
from app.services.chat import ChatService
from app.worker import QueueWorker


class FakeBroker:
    def __init__(self, settings=None):
        self.sent, self.fail = [], False

    async def publish(self, run_id):
        if self.fail:
            raise ConnectionError("test broker offline")
        self.sent.append(run_id)

    async def close(self):
        pass


@pytest.fixture
def queued_settings(settings, monkeypatch):
    settings.task_execution_mode = "queue"
    monkeypatch.setattr("app.jobs.dispatcher.RabbitBroker", FakeBroker)
    return settings


def login(client, username="queue_user"):
    credentials = {"username": username, "password": "queue-test-password"}
    assert client.post("/api/v1/auth/register", json=credentials).status_code == 201
    token = client.post("/api/v1/auth/login", json=credentials).json()["access_token"]
    return {"Authorization": "Bearer " + token}


def submit(client, headers):
    session = client.post("/api/v1/conversations", headers=headers, json={}).json()["id"]
    path = f"/api/v1/conversations/{session}/messages"
    body = {"content": "后台继续生成", "client_message_id": "queue-one"}
    response = client.post(path, headers=headers, json=body)
    assert response.status_code == 202
    return response.json(), path, body


def context(database, settings):
    user = AuthRepository(database).register("queue_worker", "test-only-hash")
    auth = AuthContext(user["id"], user["username"])
    session = ConversationRepository(database, auth).create("queue")["id"]
    repository = RunRepository(database, auth)
    run, _ = repository.accept(session, "job", "后台任务", settings)
    return auth, repository, run


def test_acceptance_outbox_idempotency_latest_and_ownership(queued_settings):
    with TestClient(create_app(queued_settings)) as client:
        headers = login(client)
        run, path, body = submit(client, headers)
        assert run["status"] == "queued" and run["llm_calls"] == 0
        assert client.post(path, headers=headers, json=body).json()["id"] == run["id"]
        latest_path = path.replace("/messages", "/runs/latest")
        latest = client.get(latest_path, headers=headers)
        assert latest.json()["id"] == run["id"]
        assert latest.headers["cache-control"] == "no-store"
        assert client.get(latest_path).status_code == 401
        other = login(client, "other")
        assert client.get(latest_path, headers=other).status_code == 404
        with client.app.state.database.connect() as connection:
            assert connection.execute("SELECT COUNT(*) FROM run_jobs").fetchone()[0] == 1
            assert connection.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 1


def test_api_restart_does_not_interrupt_independent_worker(queued_settings):
    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()

        class Model:
            async def complete(self, prompt, budget, **kwargs):
                await budget.reserve("llm")
                await budget.reserve("external")
                entered.set()
                await release.wait()
                return json.dumps({"kind": "answer", "answer": "后台生成完成"})

        with TestClient(create_app(queued_settings)) as first:
            headers = login(first)
            run, path, _ = submit(first, headers)
            database = first.app.state.database
            identity = QueueRepository(database).identity(run["id"])
            service = ChatService(database, queued_settings, Model())
            job = asyncio.create_task(service.run(identity, run["id"], worker_id="independent"))
            await asyncio.wait_for(entered.wait(), 2)
        with TestClient(create_app(queued_settings)) as second:
            assert (
                second.get("/api/v1/runs/" + run["id"], headers=headers).json()["status"]
                == "running"
            )
            assert (
                second.get(path.replace("/messages", "/runs/latest"), headers=headers).json()[
                    "status"
                ]
                == "running"
            )
            release.set()
            await asyncio.wait_for(job, 2)
            messages = second.get(path, headers=headers).json()
            assert len(messages) == 2 and messages[-1]["content"] == "后台生成完成"
            assert second.get("/api/v1/runs/" + run["id"], headers=headers).json()["llm_calls"] == 1

    asyncio.run(scenario())


def test_failed_publish_remains_in_outbox_until_confirmation(queued_settings):
    app = create_app(queued_settings)
    app.state.database.migrate()
    _, _, run = context(app.state.database, queued_settings)
    repository = QueueRepository(app.state.database)
    first = repository.claim_publication()
    assert first[0] == run["id"] and repository.claim_publication() is None
    repository.publication_failed(*first)
    second = repository.claim_publication()
    assert second[0] == run["id"] and second[1] != first[1]
    repository.publication_done(*first)
    with app.state.database.connect() as connection:
        assert connection.execute("SELECT published_at FROM run_jobs").fetchone()[0] is None
    repository.publication_done(*second)
    assert repository.claim_publication() is None


def test_dispatcher_retries_broker_failure_without_running_model(queued_settings):
    app = create_app(queued_settings)
    app.state.database.migrate()
    _, repository, run = context(app.state.database, queued_settings)
    broker = FakeBroker()
    broker.fail = True
    dispatcher = QueueDispatcher(app.state.database, queued_settings, broker=broker)

    async def scenario():
        dispatcher.start()
        for _ in range(100):
            if dispatcher.state == "retrying":
                break
            await asyncio.sleep(0.01)
        assert dispatcher.state == "retrying"
        await dispatcher.close()
        broker.fail = False
        dispatcher.start()
        for _ in range(100):
            if broker.sent:
                break
            await asyncio.sleep(0.01)
        await dispatcher.close()
        assert broker.sent == [run["id"]]

    asyncio.run(scenario())
    assert repository.get(run["id"])["status"] == "queued"
    assert repository.get(run["id"])["llm_calls"] == 0


@dataclass
class Delivery:
    body: bytes
    acked: int = 0
    rejected: int = 0
    nacked: int = 0

    async def ack(self):
        self.acked += 1

    async def reject(self, **kwargs):
        self.rejected += 1

    async def nack(self, **kwargs):
        self.nacked += 1


def delivery(run_id):
    return Delivery(json.dumps({"version": 1, "run_id": run_id}).encode())


def test_duplicate_delivery_executes_once_and_does_not_remove_live_owner(queued_settings):
    app = create_app(queued_settings)
    database = app.state.database
    database.migrate()
    auth, repository, run = context(database, queued_settings)

    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()

        class Model:
            calls = 0

            async def complete(self, prompt, budget, **kwargs):
                self.calls += 1
                await budget.reserve("llm")
                await budget.reserve("external")
                entered.set()
                await release.wait()
                return '{"kind":"answer","answer":"only once"}'

        model = Model()
        service = ChatService(database, queued_settings, model)
        worker = QueueWorker(database, queued_settings, service=service, broker=FakeBroker())
        first, duplicate = delivery(run["id"]), delivery(run["id"])
        job = asyncio.create_task(worker.process(first))
        await asyncio.wait_for(entered.wait(), 2)
        await worker.process(duplicate)
        assert len(worker.active) == 1 and duplicate.acked == 1
        release.set()
        await asyncio.wait_for(job, 2)
        assert model.calls == 1 and first.acked == 1 and not worker.active
        redelivery = delivery(run["id"])
        await worker.process(redelivery)
        assert model.calls == 1 and redelivery.acked == 1

    asyncio.run(scenario())
    assert repository.get(run["id"])["status"] == "succeeded"
    assert len(ConversationRepository(database, auth).messages(run["session_id"], 100, None)) == 2


def test_stale_worker_is_interrupted_without_replaying_spent_budget(queued_settings):
    app = create_app(queued_settings)
    database = app.state.database
    database.migrate()
    _, repository, run = context(database, queued_settings)
    claimed = repository.start(run["id"], "dead-worker")
    repository.progress(
        run["id"], claimed["fencing_token"], [], {"llm": 2, "tool": 1, "external": 2}
    )
    with database.connect(write=True) as connection:
        connection.execute("UPDATE run_jobs SET heartbeat_at = ?", (time.time() - 60,))
    QueueRepository(database).maintain(30)
    result = repository.get(run["id"])
    assert result["status"] == "interrupted" and result["error_code"] == "WORKER_LOST"
    assert result["llm_calls"] == 2 and repository.start(run["id"], "new-worker") is None


def test_cancel_before_consumption_or_missing_resource_is_acknowledged(queued_settings):
    app = create_app(queued_settings)
    database = app.state.database
    database.migrate()
    _, repository, run = context(database, queued_settings)
    repository.cancel(run["id"])
    worker = QueueWorker(database, queued_settings, service=app.state.chat, broker=FakeBroker())
    cancelled, missing = delivery(run["id"]), delivery(str(uuid4()))
    malformed = Delivery(
        json.dumps({"version": 1, "run_id": run["id"], "user_id": "forged"}).encode()
    )

    async def scenario():
        await worker.process(cancelled)
        await worker.process(missing)
        await worker.process(malformed)

    asyncio.run(scenario())
    assert cancelled.acked == missing.acked == malformed.rejected == 1
    assert repository.get(run["id"])["llm_calls"] == 0


def test_outbox_queued_deadline_is_enforced_without_a_worker(queued_settings):
    app = create_app(queued_settings)
    database = app.state.database
    database.migrate()
    _, repository, run = context(database, queued_settings)
    with database.connect(write=True) as connection:
        connection.execute("UPDATE runs SET deadline = ?", (time.time() - 1,))
    QueueRepository(database).maintain(30)
    assert repository.get(run["id"])["status"] == "timed_out"
    assert QueueRepository(database).claim_publication() is None
