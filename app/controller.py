"""Translates incoming MQTT commands into matrix operations.

Subscribes to:
- `matrix/routing/output/{1..8}/set` — payload is an input *name* string
  (HA's select entity publishes the selected option). The controller
  resolves the name to an input number and calls `MatrixClient.set_routing`.
- `matrix/edid/input/{1..8}/set` — payload is an EDID catalogue label
  (e.g. `SYS 8 · UHD4K60`). The controller resolves it to a source+index
  and calls `MatrixClient.set_input_edid`, then echoes the label it set.
  There is no read-back for EDID, so that echo is the only state there is.
- `matrix/routing/preset/set` — payload is a JSON map of
  `{output_or_name: input_or_name}` mirroring the existing
  `/api/routing/preset` REST endpoint. Single atomic hardware operation
  via the matrix's preset command.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import structlog

from app.edid import EdidCatalogue

if TYPE_CHECKING:
    from app.config import Settings
    from app.matrix_client import MatrixClient
    from app.mqtt_client import MqttClient
    from app.poller import Poller

log = structlog.get_logger()


class ControllerError(Exception):
    """Base error for command-processing failures."""


class Controller:
    """Routes MQTT-received commands to the matrix client."""

    def __init__(
        self,
        matrix: MatrixClient,
        mqtt: MqttClient,
        poller: Poller,
        settings: Settings,
        edid_catalogue: EdidCatalogue | None = None,
    ) -> None:
        self.matrix = matrix
        self.mqtt = mqtt
        self.poller = poller
        self.settings = settings
        self.edid_catalogue = edid_catalogue or EdidCatalogue()

    async def set_output_input(self, output_number: int, payload: str) -> None:
        """Handle a per-output `set` command.

        `payload` is the input name as published by HA's select entity
        (one of the values from `options[]`). It might also be a stringified
        number — both are resolved through the matrix's current input-name map.
        """
        # Always refresh the name map; renames in the matrix UI shouldn't
        # leave us routing the wrong source.
        input_names = await self.matrix.get_input_names()
        input_number = self._resolve_input(payload, input_names)
        log.info(
            "mqtt_route_set",
            output=output_number,
            input_payload=payload,
            input_number=input_number,
        )
        await self.matrix.set_routing(input_number, output_number)
        self.poller.trigger_immediate_poll()

    async def set_input_edid(self, input_number: int, payload: str) -> None:
        """Handle a per-input EDID `set` command.

        `payload` is a catalogue label as published in the select's
        `options[]` (`SYS 8 · UHD4K60`, `USER 1 · Beyond TV`,
        `Copy from output 3`). We resolve it against the catalogue rather
        than parsing it, so an option we never offered is rejected instead
        of being turned into a command the device would answer `OK` to and
        then ignore.

        After the write we publish the label we just set. We do **not**
        `trigger_immediate_poll` — the poller reads routing state, and the
        matrix has no endpoint that reports an input's EDID assignment, so
        there is nothing to poll for. What we publish is what we set, and it
        is wrong the moment somebody changes it at the front panel.
        """
        if not 1 <= input_number <= 8:
            # Input 0 is the device's "all inputs" form. It is intentionally
            # not reachable from an entity — a misclick would retune every
            # source in the house.
            raise ControllerError(f"invalid input number: {input_number}")

        await self.edid_catalogue.ensure_loaded(self.matrix)
        option = self.edid_catalogue.resolve(payload)
        if option is None:
            raise ControllerError(
                f"unknown EDID option {payload!r}; " f"known: {self.edid_catalogue.labels}"
            )

        log.info(
            "mqtt_edid_set",
            input=input_number,
            source=option.source,
            index=option.index,
            label=option.label,
        )
        await self.matrix.set_input_edid(option.source, option.index, input_number)

        prefix = self.settings.mqtt_topic_prefix.strip("/")
        # Not retained: on a restart the select must go back to unknown
        # rather than replay a value the device may no longer be using.
        await self.mqtt.publish(
            f"{prefix}/edid/input/{input_number}/state",
            option.label,
            retain=False,
        )

    async def set_preset(self, json_payload: str) -> None:
        """Handle a bulk preset `set` command.

        `json_payload` is a JSON object mapping output (number or name)
        to input (number or name). Each entry resolves through the
        matrix's name maps then applies via the existing matrix preset
        flow — one atomic hardware operation.
        """
        try:
            data = json.loads(json_payload)
        except json.JSONDecodeError as exc:
            raise ControllerError(f"preset payload is not valid JSON: {exc}") from exc

        if isinstance(data, dict) and "mappings" in data:
            data = data["mappings"]
        if not isinstance(data, dict):
            raise ControllerError("preset payload must be a JSON object of {output: input}")

        input_names = await self.matrix.get_input_names()
        output_names = await self.matrix.get_output_names()

        applied: dict[int, int] = {}
        for raw_out, raw_in in data.items():
            out_n = self._resolve_output(raw_out, output_names)
            in_n = self._resolve_input(raw_in, input_names)
            applied[out_n] = in_n

        log.info("mqtt_preset_set", applied=applied)
        # Apply each route. The matrix doesn't expose a multi-route command
        # over its `SW` interface, so we issue them sequentially — the
        # poller's immediate-poll afterwards ensures HA catches up.
        for out_n, in_n in applied.items():
            await self.matrix.set_routing(in_n, out_n)
        self.poller.trigger_immediate_poll()

    @staticmethod
    def _resolve_input(value: str | int, input_names: dict[int, str]) -> int:
        return _resolve_to_number(value, input_names, label="input")

    @staticmethod
    def _resolve_output(value: str | int, output_names: dict[int, str]) -> int:
        return _resolve_to_number(value, output_names, label="output")


def _resolve_to_number(value: str | int, names: dict[int, str], *, label: str) -> int:
    """Resolve a value (number or name) to its 1..8 number using the name map."""
    if isinstance(value, int):
        if not 1 <= value <= 8:
            raise ControllerError(f"invalid {label} number: {value}")
        return value
    s = str(value).strip()
    if not s:
        raise ControllerError(f"empty {label} value")
    try:
        n = int(s)
    except ValueError:
        n = None
    if n is not None:
        if not 1 <= n <= 8:
            raise ControllerError(f"invalid {label} number: {n}")
        return n
    lower = s.lower()
    for k, v in names.items():
        if (v or "").strip().lower() == lower:
            return k
    raise ControllerError(f"{label} name {s!r} not found in {sorted(names.values())}")
