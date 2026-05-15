"""Background poll loop: matrix → publish state + discovery to MQTT.

Polls the matrix on a fixed cadence for routing state + input/output
names; publishes deltas to MQTT and (on first cycle + on any name
change) re-publishes HA discovery payloads.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import structlog

from app.discovery import (
    health_binary_sensor_payload,
    output_select_payload,
)

if TYPE_CHECKING:
    from app.config import Settings
    from app.matrix_client import MatrixClient
    from app.mqtt_client import MqttClient

log = structlog.get_logger()


class Poller:
    """Polls the matrix on a fixed cadence and publishes to MQTT."""

    def __init__(
        self,
        matrix: MatrixClient,
        mqtt: MqttClient,
        settings: Settings,
    ) -> None:
        self.matrix = matrix
        self.mqtt = mqtt
        self.settings = settings

        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()
        self._immediate_event = asyncio.Event()

        # State cached so we publish deltas, not the full world every cycle.
        self._discovery_published = False
        self._published_input_names: dict[int, str] | None = None
        self._published_output_names: dict[int, str] | None = None
        self._published_routing: dict[int, int] | None = None

    def trigger_immediate_poll(self) -> None:
        """Signal the run loop to skip the sleep and poll right now.

        Called by the Controller after a successful matrix `set_routing`
        so HA reflects the actual confirmed state quickly.
        """
        self._immediate_event.set()

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=5)
            except TimeoutError:
                self._task.cancel()

    async def _run(self) -> None:
        # Small initial jitter — let the matrix client finish its first
        # health probe before we hit it for routing state.
        await asyncio.sleep(2)
        while not self._stop_event.is_set():
            try:
                await self.poll_once()
            except Exception as exc:  # broad: any failure → log + keep looping
                log.warning("poll_cycle_failed", error=str(exc))
                await self._publish_health(False)

            # Sleep until poll_interval elapses OR an immediate-poll
            # signal arrives (Controller fires this after a successful set).
            self._immediate_event.clear()
            stop_task = asyncio.create_task(self._stop_event.wait())
            immediate_task = asyncio.create_task(self._immediate_event.wait())
            done, pending = await asyncio.wait(
                {stop_task, immediate_task},
                timeout=self.settings.poll_interval,
                return_when=asyncio.FIRST_COMPLETED,
            )
            for t in pending:
                t.cancel()
            if not done:  # pragma: no cover
                continue

    async def poll_once(self) -> None:
        """One poll cycle: fetch routing + names, publish state + (maybe) discovery."""
        # Fetch names (cheap; the MatrixClient caches httpx connections).
        input_names = await self.matrix.get_input_names()
        output_names = await self.matrix.get_output_names()
        routing = await self.matrix.get_routing_state()

        # Reachability — empty routing means the matrix is unreachable.
        reachable = bool(routing)
        await self._publish_health(reachable)

        if not reachable:
            log.debug("poll_unreachable")
            return

        # Discovery: publish on first successful cycle, then re-publish if
        # input/output names change (HA picks up renames on the fly).
        names_changed = (
            self._published_input_names != input_names
            or self._published_output_names != output_names
        )
        if not self._discovery_published or names_changed:
            await self._publish_discovery(input_names, output_names)
            self._published_input_names = dict(input_names)
            self._published_output_names = dict(output_names)
            self._discovery_published = True

        # State: publish only outputs whose routed input has changed
        # since the last cycle. Each select's state is the input *name*
        # (so HA's dropdown selection reflects correctly).
        prefix = self.settings.mqtt_topic_prefix.strip("/")
        for output_n in range(1, 9):
            current_input = routing.get(output_n)
            if current_input is None:
                continue
            prev = (self._published_routing or {}).get(output_n)
            # Always publish on first cycle (prev is None means we haven't
            # published yet for this output).
            if prev != current_input or self._published_routing is None:
                input_name = input_names.get(current_input, f"HDMI {current_input}")
                await self.mqtt.publish(
                    f"{prefix}/routing/output/{output_n}/state",
                    input_name,
                    retain=True,
                )
        self._published_routing = dict(routing)

    async def _publish_health(self, reachable: bool) -> None:
        if not self.settings.ha_discovery_enabled:
            return
        prefix = self.settings.mqtt_topic_prefix.strip("/")
        await self.mqtt.publish(
            f"{prefix}/health/state",
            "ON" if reachable else "OFF",
            retain=True,
        )

    async def _publish_discovery(
        self,
        input_names: dict[int, str],
        output_names: dict[int, str],
    ) -> None:
        """Emit HA discovery payloads for the 8 output selects + 1 health binary_sensor."""
        if not self.settings.ha_discovery_enabled:
            return

        prefix = self.settings.mqtt_topic_prefix.strip("/")
        device_id = self.settings.ha_device_id
        device_name = self.settings.ha_device_name
        availability_topic = self.mqtt.availability_topic

        # Ordered list of input names (used as the select dropdown options).
        # Always 8 entries; fall back to "HDMI N" for any gap.
        options = [input_names.get(i, f"HDMI {i}") for i in range(1, 9)]

        # Per-output select entities.
        for output_n in range(1, 9):
            topic, payload = output_select_payload(
                discovery_prefix=self.settings.ha_discovery_prefix,
                device_id=device_id,
                device_name=device_name,
                state_topic=f"{prefix}/routing/output/{output_n}/state",
                command_topic=f"{prefix}/routing/output/{output_n}/set",
                availability_topic=availability_topic,
                output_number=output_n,
                output_name=output_names.get(output_n),
                input_names=options,
            )
            await self.mqtt.publish(topic, payload, retain=True)

        # Health binary_sensor.
        topic, payload = health_binary_sensor_payload(
            discovery_prefix=self.settings.ha_discovery_prefix,
            device_id=device_id,
            device_name=device_name,
            state_topic=f"{prefix}/health/state",
            availability_topic=availability_topic,
        )
        await self.mqtt.publish(topic, payload, retain=True)

        log.info(
            "ha_discovery_published",
            device_id=device_id,
            outputs=8,
            input_options=options,
        )
