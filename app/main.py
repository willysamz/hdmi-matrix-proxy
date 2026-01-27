"""FastAPI application entry point."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import structlog
from fastapi import FastAPI

from app import __version__
from app.config import settings
from app.dependencies import set_matrix_client, set_startup_time
from app.matrix_client import MatrixClient
from app.routers import health, routing, system

# Configure structured logging
LOG_LEVELS = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}
_renderer = (
    structlog.processors.JSONRenderer() if settings.log_json else structlog.dev.ConsoleRenderer()
)
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        _renderer,  # type: ignore[list-item]
    ],
    wrapper_class=structlog.make_filtering_bound_logger(
        LOG_LEVELS.get(settings.log_level.upper(), 20)
    ),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True,
)

log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan manager."""
    set_startup_time(datetime.now(UTC))
    log.info("starting_application", version=__version__, port=settings.server_port)

    # Initialize matrix client
    matrix_client = MatrixClient(
        base_url=settings.matrix_url,
        timeout=settings.matrix_timeout,
        verify_ssl=settings.matrix_verify_ssl,
        health_interval=settings.matrix_health_interval,
    )
    set_matrix_client(matrix_client)

    # Start the matrix client
    await matrix_client.start()

    yield

    # Cleanup
    log.info("shutting_down_application")
    await matrix_client.stop()


app = FastAPI(
    title="HDMI Matrix Proxy",
    description="REST API for controlling MT-VIKI MT-H8M88 8x8 HDMI matrix",
    version=__version__,
    lifespan=lifespan,
)

# Include routers
app.include_router(health.router, tags=["Health"])
app.include_router(system.router, prefix="/api", tags=["System"])
app.include_router(routing.router, prefix="/api", tags=["Routing"])


@app.get("/")
async def root() -> dict:
    """Root endpoint with API info."""
    return {
        "name": "HDMI Matrix Proxy",
        "version": __version__,
        "docs": "/docs",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.server_host,
        port=settings.server_port,
        reload=True,
    )
