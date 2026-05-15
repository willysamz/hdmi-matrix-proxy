"""Application configuration."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_prefix="",
        env_nested_delimiter="__",
        case_sensitive=False,
    )

    # --- Matrix HTTP settings ---
    matrix_url: str = "http://192.168.1.200"
    matrix_timeout: float = 5.0
    matrix_verify_ssl: bool = False

    # --- Health / poll cadence ---
    # The matrix-side health check (existing). Used by the existing health
    # monitor task to probe the matrix's reachability.
    matrix_health_interval: int = 30  # seconds between matrix-reachability checks
    # Routing-state poll interval. With MQTT enabled the proxy itself
    # polls the matrix for routing/name deltas and publishes changes;
    # this replaces HA's per-sensor REST polling.
    poll_interval: float = 10.0  # seconds between routing-state polls

    # --- MQTT broker (v0.2+) ---
    # If `mqtt_enabled` is False the MQTT path is fully off and the
    # service behaves like v0.1.x (REST-only). When True, the poller
    # publishes routing state + discovery; the controller subscribes
    # to command topics.
    mqtt_enabled: bool = False
    mqtt_host: str = "mqtt"
    mqtt_port: int = 1883
    mqtt_username: str | None = None
    mqtt_password: str | None = None
    mqtt_client_id: str = "hdmi-matrix-proxy"
    mqtt_topic_prefix: str = "matrix"
    mqtt_keepalive: int = 60
    mqtt_qos: int = 0  # 0|1|2

    # --- Home Assistant MQTT discovery (v0.2+) ---
    ha_discovery_enabled: bool = True
    ha_discovery_prefix: str = "homeassistant"
    ha_device_name: str = "HDMI Matrix"
    # Stable device identifier used in unique_id + the device card.
    # Pinned default keeps entity_ids predictable across reinstalls.
    ha_device_id: str = "hdmi_matrix"

    # --- Server settings ---
    server_host: str = "0.0.0.0"  # noqa: S104 — binding all interfaces is intended inside a pod
    server_port: int = 8080

    # --- Logging ---
    log_level: str = "INFO"
    log_json: bool = True


settings = Settings()
