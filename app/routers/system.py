"""System information endpoints."""

from fastapi import APIRouter

from app.config import settings
from app.dependencies import get_matrix_client
from app.models import MatrixStatus

router = APIRouter()


@router.get(
    "/status",
    response_model=MatrixStatus,
    summary="Get matrix status",
)
async def get_status() -> MatrixStatus:
    """Get current matrix connection status.

    Returns:
        Matrix connection status and last command info
    """
    client = get_matrix_client()

    return MatrixStatus(
        connection=client.connection_state,
        url=settings.matrix_url,
        last_command=client.last_command_time,
        last_response=client.last_response,
    )
