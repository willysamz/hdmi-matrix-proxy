"""Application dependencies and shared state."""

from datetime import UTC, datetime

from app.edid import EdidCatalogue
from app.matrix_client import MatrixClient

# Global state
_matrix_client: MatrixClient | None = None
_startup_time: datetime | None = None
# One catalogue for the whole process. The poller fills it on a cycle that
# reached the matrix; the controller and the REST router read it.
_edid_catalogue = EdidCatalogue()


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


def get_edid_catalogue() -> EdidCatalogue:
    """Get the process-wide EDID catalogue.

    May be empty (`loaded is False`) until the poller has had a cycle that
    reached the matrix — or forever, if MQTT is disabled, in which case the
    REST router builds it on demand.
    """
    return _edid_catalogue
