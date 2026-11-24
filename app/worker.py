import asyncio
import signal
import tempfile
import time
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from app.core.config import Settings
from app.db.database import Database
from app.integrations.deepseek import DeepSeekClient
from app.jobs.broker import RabbitBroker, RunJob
from app.jobs.repository import QueueRepository
from app.services.chat import ChatService


class QueueWorker:
    def __init__(self, database, settings, *, service=None, broker=None):
        self.settings = settings
        self.repository = QueueRepository(database)
        self.service = service or ChatService(database, settings, DeepSeekClient(settings))
        self.broker = broker or RabbitBroker(settings)
        self.id = str(uuid4())
        self.active, self.tasks = {}, set()
        self.stop = asyncio.Event()
        self.semaphore = asyncio.Semaphore(settings.worker_concurrency)

    async def process(self, message):
        task = asyncio.current_task()
        self.tasks.add(task)
        run_id = None
        try:
            try:
                if len(message.body) > 512:
                    raise ValueError("Oversized job")
                job = RunJob.model_validate_json(message.body)
            except (ValueError, ValidationError):
                await message.reject(requeue=False)
                return
            run_id = job.run_id
            async with self.semaphore:
                auth = await asyncio.to_thread(self.repository.identity, run_id)
                if auth is not None:
                    self.active[task] = run_id
                    await self.service.run(auth, run_id, worker_id=self.id)
            # The database holds the terminal result before acknowledging a delivered message.
            await message.ack()
        except asyncio.CancelledError:
            raise
        except Exception:
            # A failed ACK is safe to redeliver: the DB claim prevents duplicate model execution.
            try:
                await message.nack(requeue=True)
            except Exception:
                pass
        finally:
            self.active.pop(task, None)
            self.tasks.discard(task)

    async def run(self):
        monitor = asyncio.create_task(self.monitor())
        try:
            while not self.stop.is_set():
                try:
                    await self.broker.connect()
                    tag = await self.broker.queue.consume(self.process, no_ack=False)
                    while not self.stop.is_set() and self.broker.connected:
                        try:
                            await asyncio.wait_for(self.stop.wait(), 2)
                        except TimeoutError:
                            pass
                    if self.broker.connected:
                        await self.broker.queue.cancel(tag)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    # Keep credentials/AMQP URLs out of logs while reconnecting.
                    await asyncio.sleep(2)
        finally:
            await self.service.close()
            pending = list(self.tasks)
            if pending:
                _, unfinished = await asyncio.wait(pending, timeout=5)
                for task in unfinished:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
            await self.broker.close()
            monitor.cancel()
            await asyncio.gather(monitor, return_exceptions=True)

    async def monitor(self):
        while True:
            try:
                await asyncio.to_thread(
                    self.repository.heartbeat, self.id, set(self.active.values())
                )
                await asyncio.to_thread(
                    self.repository.maintain, self.settings.worker_stale_seconds
                )
                if self.broker.connected:
                    (Path(tempfile.gettempdir()) / "gomate-worker-heartbeat").write_text(
                        str(time.time())
                    )
            except asyncio.CancelledError:
                raise
            except Exception:
                pass
            await asyncio.sleep(2)


async def main():
    settings = Settings()
    database = Database(settings.database_path)
    database.migrate()
    worker = QueueWorker(database, settings)
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signum, worker.stop.set)
        except NotImplementedError:
            signal.signal(signum, lambda *_: loop.call_soon_threadsafe(worker.stop.set))
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
