"""Pydantic models for API requests and responses."""

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


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
    """Set routing for a single output."""

    input: int = Field(ge=1, le=8, description="Input number to route (1-8)")


class SetRoutingResponse(BaseModel):
    """Response after setting routing."""

    output: int
    input: int
    success: bool
    message: str | None = None


class PresetRoutingRequest(BaseModel):
    """Set multiple output routings at once."""

    mappings: dict[int, int] = Field(
        description="Dictionary of output->input mappings (e.g., {1: 1, 2: 2, 3: 3})"
    )


class PresetRoutingResponse(BaseModel):
    """Response after setting preset routing."""

    success: bool
    applied: dict[int, int]
    failed: dict[int, str] = {}


# Mappings for friendly names
INPUT_NAMES = {
    1: "hdmi_1",
    2: "hdmi_2",
    3: "hdmi_3",
    4: "hdmi_4",
    5: "hdmi_5",
    6: "hdmi_6",
    7: "hdmi_7",
    8: "hdmi_8",
}

OUTPUT_NAMES = {
    1: "output_1",
    2: "output_2",
    3: "output_3",
    4: "output_4",
    5: "output_5",
    6: "output_6",
    7: "output_7",
    8: "output_8",
}
