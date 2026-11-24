import json
import logging
from typing import Literal

import aio_pika
from pydantic import BaseModel, ConfigDict, Field


class RunJob(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal[1] = 1
    run_id: str = Field(pattern=r"^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$")


class RabbitBroker:
    def __init__(self, settings):
        self.settings = settings
        self.connection = self.channel = self.queue = None
        # Connection exceptions can contain credential-bearing AMQP URLs.
        for name in ("aio_pika", "aiormq"):
            logging.getLogger(name).setLevel(logging.CRITICAL)

    async def connect(self):
        if self.connection is not None and self.connection.connected.is_set():
            return
        await self.close()
        self.connection = await aio_pika.connect_robust(
            host=self.settings.rabbitmq_host,
            port=self.settings.rabbitmq_port,
            login=self.settings.rabbitmq_user,
            password=self.settings.rabbitmq_password.get_secret_value(),
            virtualhost=self.settings.rabbitmq_vhost,
            timeout=5,
            fail_fast=True,
            reconnect_interval=2,
        )
        self.channel = await self.connection.channel(publisher_confirms=True, on_return_raises=True)
        await self.channel.set_qos(prefetch_count=self.settings.worker_concurrency)
        self.queue = await self.channel.declare_queue(
            self.settings.rabbitmq_queue,
            durable=True,
            arguments={"x-queue-type": "quorum"},
            timeout=5,
        )

    async def publish(self, run_id):
        await self.connect()
        await self.channel.default_exchange.publish(
            aio_pika.Message(
                body=json.dumps({"version": 1, "run_id": run_id}).encode(),
                message_id=run_id,
                content_type="application/json",
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            ),
            routing_key=self.settings.rabbitmq_queue,
            mandatory=True,
            timeout=5,
        )

    @property
    def connected(self):
        return bool(self.connection and self.connection.connected.is_set())

    async def close(self):
        if self.connection is not None:
            await self.connection.close()
        self.connection = self.channel = self.queue = None
