import asyncio

from app.jobs.broker import RabbitBroker
from app.jobs.repository import QueueRepository


class QueueDispatcher:
    def __init__(self, database, settings, *, broker=None):
        self.settings = settings
        self.repository = QueueRepository(database)
        self.broker = broker or RabbitBroker(settings)
        self.task = None
        self.state = "starting"
        self.pending = None

    def start(self):
        self.task = asyncio.create_task(self.run())

    async def run(self):
        try:
            while True:
                try:
                    await asyncio.to_thread(
                        self.repository.maintain, self.settings.worker_stale_seconds
                    )
                    item = await asyncio.to_thread(self.repository.claim_publication)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    self.state = "retrying"
                    await asyncio.sleep(2)
                    continue
                if item is None:
                    await asyncio.sleep(0.5)
                    continue
                run_id, token = item
                self.pending = item
                try:
                    await self.broker.publish(run_id)
                    await asyncio.to_thread(self.repository.publication_done, run_id, token)
                    self.pending = None
                    self.state = "online"
                except asyncio.CancelledError:
                    raise
                except Exception:
                    self.state = "retrying"
                    await asyncio.to_thread(self.repository.publication_failed, run_id, token)
                    await asyncio.sleep(2)
        finally:
            if self.pending:
                await asyncio.to_thread(self.repository.publication_failed, *self.pending)
                self.pending = None
            await self.broker.close()

    async def close(self):
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
