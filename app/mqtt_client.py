"""Async MQTT publisher + control-topic subscriber on aiomqtt.

Mirrors the pattern in cyberpower-pdu-mqtt-bridge.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import aiomqtt
import structlog

log = structlog.get_logger()


class MqttClient:
    """Long-lived MQTT client used by both the poller (publish) and the
    control loop (subscribe)."""

    def __init__(
        self,
        host: str,
        port: int = 1883,
        username: str | None = None,
        password: str | None = None,
        client_id: str = "hdmi-matrix-proxy",
        keepalive: int = 60,
        qos: int = 0,
        availability_topic: str = "matrix/bridge/available",
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password or None
        self.client_id = client_id
        self.keepalive = keepalive
        self.qos = qos
        self.availability_topic = availability_topic
        self._client: aiomqtt.Client | None = None
        self._lock = asyncio.Lock()

    def _new_client(self) -> aiomqtt.Client:
        will = aiomqtt.Will(
            topic=self.availability_topic, payload=b"offline", qos=self.qos, retain=True
        )
        return aiomqtt.Client(
            hostname=self.host,
            port=self.port,
            username=self.username,
            password=self.password,
            identifier=self.client_id,
            keepalive=self.keepalive,
            will=will,
        )

    @asynccontextmanager
    async def session(self) -> AsyncIterator[MqttClient]:
        """Open the MQTT connection for the lifetime of the proxy.

        Use:
            async with mqtt.session():
                await mqtt.publish(...)
        """
        async with self._new_client() as client:
            self._client = client
            try:
                await client.publish(
                    self.availability_topic, payload=b"online", qos=self.qos, retain=True
                )
                log.info("mqtt_connected", host=self.host, port=self.port)
                yield self
            finally:
                try:
                    await client.publish(
                        self.availability_topic,
                        payload=b"offline",
                        qos=self.qos,
                        retain=True,
                    )
                except Exception:  # pragma: no cover
                    pass
                self._client = None

    async def publish(
        self, topic: str, payload: str | bytes | dict[str, Any], retain: bool = False
    ) -> None:
        """Publish a single MQTT message. JSON-encodes dict payloads."""
        if self._client is None:
            raise RuntimeError("MqttClient.publish called outside session()")
        if isinstance(payload, dict):
            import json

            data = json.dumps(payload).encode()
        elif isinstance(payload, str):
            data = payload.encode()
        else:
            data = payload
        await self._client.publish(topic, payload=data, qos=self.qos, retain=retain)

    async def subscribe(self, topic_filter: str) -> None:
        """Subscribe to a topic filter."""
        if self._client is None:
            raise RuntimeError("MqttClient.subscribe called outside session()")
        await self._client.subscribe(topic_filter, qos=self.qos)

    @property
    def messages(self) -> AsyncIterator[aiomqtt.Message]:
        """Async iterator over subscribed messages."""
        if self._client is None:
            raise RuntimeError("MqttClient.messages used outside session()")
        return self._client.messages
