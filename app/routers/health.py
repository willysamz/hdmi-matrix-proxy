"""Health check endpoints."""

from datetime import UTC, datetime

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from app.dependencies import get_matrix_client, get_startup_time
from app.models import ConnectionState, HealthResponse

router = APIRouter()


@router.get(
    "/healthz/live",
    status_code=status.HTTP_200_OK,
    tags=["Health"],
    summary="Liveness probe",
)
async def liveness() -> JSONResponse:
    """Liveness probe for Kubernetes.

    Returns 200 if the application is running.
    """
    return JSONResponse({"status": "ok"})


@router.get(
    "/healthz/ready",
    response_model=HealthResponse,
    tags=["Health"],
    summary="Readiness probe",
)
async def readiness() -> HealthResponse:
    """Readiness probe for Kubernetes.

    Returns:
        Health status including matrix connection state
    """
    client = get_matrix_client()
    startup_time = get_startup_time()
    uptime = (datetime.now(UTC) - startup_time).total_seconds()

    matrix_connected = client.connection_state == ConnectionState.CONNECTED
    last_check = client.last_command_time

    # Determine overall status
    if matrix_connected:
        health_status: str = "ok"
    elif client.connection_state == ConnectionState.ERROR:
        health_status = "error"
    else:
        health_status = "degraded"

    return HealthResponse(
        status=health_status,  # type: ignore[arg-type]
        matrix_connected=matrix_connected,
        last_health_check=last_check,
        uptime_seconds=uptime,
    )
