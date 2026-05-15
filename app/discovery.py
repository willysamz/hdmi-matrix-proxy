"""Home Assistant MQTT discovery payload + topic builders.

HA's MQTT discovery convention is:
    {prefix}/{component}/{node_id}/{object_id}/config

We publish discovery payloads on startup (retained) and re-publish
the affected entity's payload whenever the input/output names change
upstream in the matrix's web UI.

Entities exposed:
- One `select` per output (1..8) — options are the configured input
  names. The `select` is the primary control surface and its state
  reflects the currently-routed input name.
- One `binary_sensor` for matrix health (online when proxy can reach
  the matrix).
"""

from __future__ import annotations

import re
from typing import Any

DEVICE_MANUFACTURER = "MT-VIKI"
DEVICE_MODEL = "MT-H8M88 8x8 HDMI Matrix"


def _slug(value: str) -> str:
    """Lowercase alphanumeric+underscore slug for IDs / topics."""
    value = value.strip().lower()
    return re.sub(r"[^a-z0-9_]+", "_", value).strip("_") or "matrix"


def device_block(device_id: str, device_name: str) -> dict[str, Any]:
    """The `device` field repeated on every entity — pins them all to
    one HA device card."""
    return {
        "identifiers": [device_id],
        "name": device_name,
        "manufacturer": DEVICE_MANUFACTURER,
        "model": DEVICE_MODEL,
    }


def output_select_payload(
    *,
    discovery_prefix: str,
    device_id: str,
    device_name: str,
    state_topic: str,
    command_topic: str,
    availability_topic: str,
    output_number: int,
    output_name: str | None,
    input_names: list[str],
) -> tuple[str, dict[str, Any]]:
    """Discovery topic + payload for a `select` entity per output.

    `options[]` is the list of configured input names (in 1..8 order).
    HA shows them as a dropdown; selecting one publishes the chosen
    name to `command_topic`; the controller translates the name back
    to an input number and calls the matrix.
    """
    object_id = f"hdmi_matrix_output_{output_number}_source"
    topic = f"{discovery_prefix}/select/{object_id}/config"
    name = (output_name or f"Output {output_number}") + " Source"
    payload: dict[str, Any] = {
        "name": name,
        "unique_id": object_id,
        "object_id": object_id,
        "state_topic": state_topic,
        "command_topic": command_topic,
        "options": input_names,
        "availability_topic": availability_topic,
        "payload_available": "online",
        "payload_not_available": "offline",
        "icon": "mdi:video-switch",
        "device": device_block(device_id, device_name),
    }
    return topic, payload


def health_binary_sensor_payload(
    *,
    discovery_prefix: str,
    device_id: str,
    device_name: str,
    state_topic: str,
    availability_topic: str,
) -> tuple[str, dict[str, Any]]:
    """Discovery topic + payload for the matrix health binary_sensor.

    State payloads `ON` / `OFF` indicating whether the proxy can reach
    the matrix on its HTTP API.
    """
    object_id = f"{device_id}_matrix_reachable"
    topic = f"{discovery_prefix}/binary_sensor/{object_id}/config"
    payload: dict[str, Any] = {
        "name": "Matrix reachable",
        "unique_id": object_id,
        "object_id": object_id,
        "state_topic": state_topic,
        "payload_on": "ON",
        "payload_off": "OFF",
        "device_class": "connectivity",
        "availability_topic": availability_topic,
        "payload_available": "online",
        "payload_not_available": "offline",
        "device": device_block(device_id, device_name),
    }
    return topic, payload
