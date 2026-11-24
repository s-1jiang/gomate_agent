"""Real RabbitMQ smoke with isolated SQLite, a separate worker process and no provider calls.

Run only against a test broker. The script creates a unique durable queue and deletes it at exit.
"""

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.db.database import Database
from app.jobs.broker import RabbitBroker
from app.main import create_app
from app.services.chat import ChatService
from app.worker import QueueWorker


def configuration(directory, queue):
    return Settings(
        _env_file=None,
        database_path=Path(directory) / "queue.db",
        task_execution_mode="queue",
        rabbitmq_queue=queue,
        deepseek_api_key="",
        amap_web_service_key="",
        tavily_api_key="",
        run_timeout_seconds=120,
    )


async def worker_process(directory, queue):
    config = configuration(directory, queue)
    database = Database(config.database_path)

    class Model:
        async def complete(self, prompt, budget, **kwargs):
            await budget.reserve("llm")
            await budget.reserve("external")
            with (Path(directory) / "executions").open("a") as output:
                output.write("model-call\n")
            (Path(directory) / "entered").touch()
            while not (Path(directory) / "release").exists():
                await asyncio.sleep(0.05)
            return json.dumps({"kind": "answer", "answer": "QUEUED_RESULT"})

    worker = QueueWorker(database, config, service=ChatService(database, config, Model()))
    await worker.run()


def wait_until(check, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(0.05)
    raise AssertionError("Queue smoke timed out")


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "worker":
        asyncio.run(worker_process(sys.argv[2], sys.argv[3]))
        return
    queue = "gomate.smoke." + uuid4().hex
    child = None
    with tempfile.TemporaryDirectory(prefix="gomate-queue-") as directory:
        config = configuration(directory, queue)
        database = Database(config.database_path)
        database.migrate()
        try:
            with TestClient(create_app(config)) as first:
                credentials = {"username": "queue_smoke", "password": "test-only-password"}
                assert first.post("/api/v1/auth/register", json=credentials).status_code == 201
                token = first.post("/api/v1/auth/login", json=credentials).json()["access_token"]
                headers = {"Authorization": "Bearer " + token}
                session = first.post("/api/v1/conversations", headers=headers, json={}).json()["id"]
                path = f"/api/v1/conversations/{session}/messages"
                body = {"content": "后台任务", "client_message_id": "one"}
                accepted = first.post(path, headers=headers, json=body)
                assert accepted.status_code == 202 and accepted.json()["status"] == "queued"
                run_id = accepted.json()["id"]

                def confirmed():
                    with database.connect() as connection:
                        row = connection.execute(
                            "SELECT published_at FROM run_jobs WHERE run_id = ?", (run_id,)
                        ).fetchone()
                        return row and row[0]

                wait_until(confirmed)
            # The API is closed while the confirmed message waits durably without a consumer.
            assert not (Path(directory) / "entered").exists()
            if os.getenv("SMOKE_BROKER_RESTART") == "1":
                print("READY_FOR_BROKER_RESTART", flush=True)
                wait_until(lambda: Path("/tmp/broker-restarted").exists(), timeout=60)
            child = subprocess.Popen([sys.executable, __file__, "worker", directory, queue])
            wait_until(lambda: (Path(directory) / "entered").exists())
            with TestClient(create_app(config)) as second:
                status_path = "/api/v1/runs/" + run_id
                assert second.get(status_path, headers=headers).json()["status"] == "running"
                assert (
                    second.get(path.replace("/messages", "/runs/latest"), headers=headers).json()[
                        "id"
                    ]
                    == run_id
                )
                assert second.post(path, headers=headers, json=body).json()["id"] == run_id

                # A duplicate broker delivery must not start a second generation.
                async def duplicate():
                    broker = RabbitBroker(config)
                    await broker.publish(run_id)
                    await broker.close()

                asyncio.run(duplicate())
                (Path(directory) / "release").touch()
                wait_until(
                    lambda: second.get(status_path, headers=headers).json()["status"] == "succeeded"
                )
                assert second.get(path, headers=headers).json()[-1]["content"] == "QUEUED_RESULT"
                assert (Path(directory) / "executions").read_text().splitlines() == ["model-call"]
                assert second.get(status_path, headers=headers).json()["llm_calls"] == 1
            with TestClient(create_app(config)) as third:
                assert third.get(path, headers=headers).json()[-1]["content"] == "QUEUED_RESULT"
            print("PASS: durable RabbitMQ delivery across API restart and delayed worker start")
            print(
                "PASS: independent worker, persisted recovery, duplicate delivery "
                "and one generation"
            )
        finally:
            if child:
                child.terminate()
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()

            async def cleanup():
                broker = RabbitBroker(config)
                await broker.connect()
                await broker.queue.delete(if_unused=False, if_empty=False)
                await broker.close()

            asyncio.run(cleanup())


if __name__ == "__main__":
    main()
