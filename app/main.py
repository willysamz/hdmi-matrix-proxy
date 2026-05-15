"""FastAPI application entry point."""

import asyncio
import re
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import structlog
from fastapi import FastAPI

from app import __version__
from app.config import settings
from app.controller import Controller, ControllerError
from app.dependencies import set_matrix_client, set_startup_time
from app.matrix_client import MatrixClient
from app.mqtt_client import MqttClient
from app.poller import Poller
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
    """Application lifespan manager.

    v0.2+: alongside the existing matrix client, we optionally bring up
    an MQTT session, a routing-state poller that publishes to MQTT, and
    a command subscriber that translates HA select changes back into
    matrix `set_routing` calls.
    """
    set_startup_time(datetime.now(UTC))
    log.info(
        "starting_application",
        version=__version__,
        port=settings.server_port,
        mqtt_enabled=settings.mqtt_enabled,
    )

    # Existing matrix REST client.
    matrix_client = MatrixClient(
        base_url=settings.matrix_url,
        timeout=settings.matrix_timeout,
        verify_ssl=settings.matrix_verify_ssl,
        health_interval=settings.matrix_health_interval,
    )
    set_matrix_client(matrix_client)
    await matrix_client.start()

    # MQTT path is opt-in. Without it the proxy behaves like v0.1.x.
    mqtt_ctx = None
    poller: Poller | None = None
    command_task: asyncio.Task | None = None

    if settings.mqtt_enabled:
        mqtt = MqttClient(
            host=settings.mqtt_host,
            port=settings.mqtt_port,
            username=settings.mqtt_username,
            password=settings.mqtt_password,
            client_id=settings.mqtt_client_id,
            keepalive=settings.mqtt_keepalive,
            qos=settings.mqtt_qos,
            availability_topic=f"{settings.mqtt_topic_prefix.strip('/')}/bridge/available",
        )
        poller = Poller(matrix=matrix_client, mqtt=mqtt, settings=settings)
        controller = Controller(
            matrix=matrix_client, mqtt=mqtt, poller=poller, settings=settings
        )

        mqtt_ctx = mqtt.session()
        await mqtt_ctx.__aenter__()
        await poller.start()
        command_task = asyncio.create_task(
            _command_subscriber(mqtt, controller, settings.mqtt_topic_prefix)
        )

    try:
        yield
    finally:
        log.info("shutting_down_application")
        if command_task is not None:
            command_task.cancel()
        if poller is not None:
            await poller.stop()
        if mqtt_ctx is not None:
            await mqtt_ctx.__aexit__(None, None, None)
        await matrix_client.stop()


_OUTPUT_SET_RE = re.compile(r"^[^/]+/routing/output/(?P<n>\d+)/set$")
_PRESET_SET_RE = re.compile(r"^[^/]+/routing/preset/set$")


async def _command_subscriber(
    mqtt: MqttClient, controller: Controller, topic_prefix: str
) -> None:
    """Subscribe to per-output + preset command topics and route them."""
    prefix = topic_prefix.strip("/")
    output_filter = f"{prefix}/routing/output/+/set"
    preset_filter = f"{prefix}/routing/preset/set"
    await mqtt.subscribe(output_filter)
    await mqtt.subscribe(preset_filter)
    log.info("command_subscriber_started", topics=[output_filter, preset_filter])

    async for msg in mqtt.messages:
        topic_str = str(msg.topic)
        raw = msg.payload
        if isinstance(raw, bytes | bytearray):
            payload = bytes(raw).decode("utf-8", errors="replace").strip()
        elif isinstance(raw, str):
            payload = raw.strip()
        else:
            log.warning("command_subscriber_bad_payload", topic=topic_str, type=type(raw).__name__)
            continue

        m = _OUTPUT_SET_RE.match(topic_str)
        if m:
            output_n = int(m.group("n"))
            try:
                await controller.set_output_input(output_n, payload)
            except ControllerError as exc:
                log.warning("command_output_rejected", output=output_n, error=str(exc))
            except Exception as exc:
                log.warning("command_output_failed", output=output_n, error=str(exc))
            continue

        if _PRESET_SET_RE.match(topic_str):
            try:
                await controller.set_preset(payload)
            except ControllerError as exc:
                log.warning("command_preset_rejected", error=str(exc))
            except Exception as exc:
                log.warning("command_preset_failed", error=str(exc))
            continue

        log.warning("command_subscriber_unmatched_topic", topic=topic_str)


app = FastAPI(
    title="HDMI Matrix Proxy",
    description=(
        "REST + MQTT proxy for MT-VIKI MT-H8M88 8x8 HDMI matrix. v0.2 "
        "adds optional MQTT publishing with Home Assistant discovery; "
        "the REST endpoints stay available for direct scripting + debug."
    ),
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
