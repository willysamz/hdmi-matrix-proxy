"""Pydantic models for API requests and responses."""

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

# EDID source families supported by the matrix's `@EDID-SW-*` commands.
# "out" copies the EDID read from an output, "sys" is a built-in slot,
# "user" is a writable user slot.
EdidSource = Literal["out", "sys", "user"]


# Enums for API
class ConnectionState(str, Enum):
    """Matrix connection state."""

    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    ERROR = "error"


# Health Models
class HealthResponse(BaseModel):
    """Health check response."""

    status: Literal["ok", "degraded", "error"]
    matrix_connected: bool
    last_health_check: datetime | None
    uptime_seconds: float


# Error Models
class ErrorResponse(BaseModel):
    """Error response."""

    error: str
    message: str
    retry_after: int | None = None


# System Models
class MatrixStatus(BaseModel):
    """Matrix status response."""

    connection: ConnectionState
    url: str
    last_command: datetime | None = None
    last_response: str | None = None


# Routing Models
class OutputRouting(BaseModel):
    """Single output routing."""

    output: int = Field(ge=1, le=8, description="Output number (1-8)")
    output_name: str | None = None
    input: int | None = Field(None, ge=1, le=8, description="Input number (1-8)")
    input_name: str | None = None


class RoutingState(BaseModel):
    """All output routing state."""

    outputs: list[OutputRouting]
    input_names: dict[int, str] | None = Field(
        None, description="Custom names for all inputs (1-8)"
    )
    output_names: dict[int, str] | None = Field(
        None, description="Custom names for all outputs (1-8)"
    )


class SetRoutingRequest(BaseModel):
    """Set routing for a single output.

    Accepts either an input number (1-8) or an input name (e.g., "PlayStation 5").
    When using a name, it must match a configured input name in the matrix.
    """

    input: int | str = Field(description="Input number (1-8) or input name (e.g., 'PlayStation 5')")


class SetRoutingResponse(BaseModel):
    """Response after setting routing."""

    output: int
    output_name: str | None = None
    input: int
    input_name: str | None = None
    success: bool
    message: str | None = None


class PresetRoutingRequest(BaseModel):
    """Set multiple output routings at once.

    Both outputs and inputs can be specified by number or name.
    """

    mappings: dict[int | str, int | str] = Field(
        description="Dictionary of output->input mappings. "
        "Both outputs and inputs can be numbers or names "
        '(e.g., {"Living Room TV": "Apple TV", "2": "PlayStation 5", "3": 3})'
    )


class PresetRoutingResponse(BaseModel):
    """Response after setting preset routing."""

    success: bool
    applied: dict[int, int] = Field(
        description="Successfully applied mappings (output_num -> input_num)"
    )
    failed: dict[str, str] = Field(
        default={},
        description="Failed mappings with error messages (original_key -> error)",
    )


class InputInfo(BaseModel):
    """Information about a single input."""

    number: int = Field(ge=1, le=8, description="Input number (1-8)")
    name: str = Field(description="Input name (configured in matrix)")


class OutputInfo(BaseModel):
    """Information about a single output."""

    number: int = Field(ge=1, le=8, description="Output number (1-8)")
    name: str = Field(description="Output name (configured in matrix)")


class InputListResponse(BaseModel):
    """List of all inputs with their names."""

    inputs: list[InputInfo]
    names: list[str] = Field(description="Just the names (for dropdown options)")


class OutputListResponse(BaseModel):
    """List of all outputs with their names."""

    outputs: list[OutputInfo]
    names: list[str] = Field(description="Just the names (for dropdown options)")


# EDID Models
class SetInputEdidRequest(BaseModel):
    """Assign an EDID to one input.

    Identified by source + index rather than by the option label, so the
    REST path does not depend on the MQTT poller having built the catalogue.

    `input` is required and 1-8. It is deliberately **not** nullable: the
    device treats 0 as "all inputs", and a `{"input": null}` body silently
    retuning every source in the house is not an acceptable accident. The
    all-inputs form stays in the client API only.
    """

    source: Literal["out", "sys", "user"] = Field(
        description="EDID family: 'sys' (built-in), 'user' (user slot), "
        "'out' (copy the EDID read from an output)"
    )
    index: int = Field(ge=1, description="Slot number: sys 1-10, user 1-5, out 1-8")
    input: int = Field(ge=1, le=8, description="Input number (1-8)")
    rehandshake: bool = Field(
        True,
        description="Reset the input port afterwards so the source re-reads "
        "the EDID. UNVERIFIED mechanism — see MatrixClient.reset_input_port.",
    )


class SetInputEdidResponse(BaseModel):
    """Response after assigning an EDID to an input."""

    input: int
    input_name: str | None = None
    source: str
    index: int
    label: str | None = Field(
        None, description="Catalogue label, when the catalogue has been built"
    )
    rehandshake: bool
    success: bool
    message: str | None = None


class EdidOptionInfo(BaseModel):
    """One catalogue entry."""

    source: str
    index: int
    label: str = Field(description="Code-owned option string, stable across restarts")
    device_name: str | None = Field(
        None, description="What the device reported; diagnostics only, never an identifier"
    )


class EdidCatalogueResponse(BaseModel):
    """The EDID catalogue.

    Note there is no current-assignment field: the matrix has no endpoint that
    reports which EDID an input is using, so nothing here is read back.
    """

    loaded: bool
    options: list[EdidOptionInfo]
    labels: list[str] = Field(description="Just the labels (for dropdown options)")
