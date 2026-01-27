"""Application dependencies and shared state."""

from datetime import UTC, datetime

from app.matrix_client import MatrixClient

# Global state
_matrix_client: MatrixClient | None = None
_startup_time: datetime | None = None


def set_matrix_client(client: MatrixClient) -> None:
    """Set the global matrix client instance."""
    global _matrix_client
    _matrix_client = client


def get_matrix_client() -> MatrixClient:
    """Get the matrix client instance."""
    if _matrix_client is None:
        raise RuntimeError("Matrix client not initialized")
    return _matrix_client


def set_startup_time(time: datetime) -> None:
    """Set the application startup time."""
    global _startup_time
    _startup_time = time


def get_startup_time() -> datetime:
    """Get the application startup time."""
    if _startup_time is None:
        return datetime.now(UTC)
    return _startup_time
