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
        # What this proxy last set on each input. Used only to make a
        # redundant set cheap — see `set_input_edid`. Never a claim about
        # what the device is actually using.
        self._last_edid_set: dict[int, str] = {}

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

        `payload` is one of the select's `options[]` (`SYS 8 · UHD4K60`,
        `USER 1`). We resolve it against the catalogue rather than parsing it,
        so an option we never offered is rejected instead of becoming a
        command the device would answer and then ignore.

        Input 0 is rejected: the command topic's numeric segment can match it,
        and 0 is the device's all-inputs sentinel — which must never be
        reachable from an entity.

        State is published **only when the device confirmed the write**, and
        only what we set — the matrix has no endpoint reporting an input's
        EDID assignment, so there is nothing to poll for and
        `trigger_immediate_poll` is deliberately not called.
        """
        if not 1 <= input_number <= 8:
            raise ControllerError(f"invalid input number: {input_number}")

        if not self.edid_catalogue.loaded:
            raise ControllerError(
                "EDID catalogue not built yet; the poller builds it on a cycle "
                "that reaches the matrix"
            )
        option = self.edid_catalogue.resolve(payload)
        if option is None:
            raise ControllerError(
                f"unknown EDID option {payload!r}; known: {self.edid_catalogue.labels}"
            )

        prefix = self.settings.mqtt_topic_prefix.strip("/")

        if self._last_edid_set.get(input_number) == option.label:
            # Scenes set the EDID explicitly *and* an HA automation watches
            # the selects, so this handler is called redundantly on purpose,
            # to minimise blank-screen time. Re-sending would be harmless but
            # the re-handshake after it is not: resetting the input port drops
            # video for a moment, so a redundant call would cause the very
            # blink the belt-and-braces approach exists to avoid. Skip both
            # and re-publish the state we already claim.
            log.debug("mqtt_edid_already_set", input=input_number, label=option.label)
            await self.mqtt.publish(
                f"{prefix}/edid/input/{input_number}/state", option.label, retain=True
            )
            return

        log.info(
            "mqtt_edid_set",
            input=input_number,
            source=option.source,
            index=option.index,
            label=option.label,
            rehandshake=self.settings.matrix_edid_rehandshake,
        )
        ok = await self.matrix.set_input_edid(
            option.source,
            option.index,
            input_number,
            rehandshake=self.settings.matrix_edid_rehandshake,
        )
        if not ok:
            # The device refused it. Publishing anyway would put an
            # authoritative-looking value in HA for a command that did not
            # take — exactly the failure the multiviewer's HDCP select showed
            # when it accepted `Off` and kept its old value.
            raise ControllerError(f"matrix refused EDID {option.label!r} for input {input_number}")

        self._last_edid_set[input_number] = option.label
        # Retained: nothing is published at boot, so the broker replays this.
        await self.mqtt.publish(
            f"{prefix}/edid/input/{input_number}/state",
            option.label,
            retain=True,
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
