"""Application configuration."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_prefix="",
        env_nested_delimiter="__",
        case_sensitive=False,
    )

    # Matrix HTTP settings
    matrix_url: str = "http://matrix.home.willysamz.com"
    matrix_timeout: float = 5.0
    matrix_verify_ssl: bool = False

    # Health check settings
    matrix_health_interval: int = 30  # seconds between health checks

    # Server settings
    server_host: str = "0.0.0.0"
    server_port: int = 8080

    # Logging
    log_level: str = "INFO"
    log_json: bool = True


settings = Settings()
