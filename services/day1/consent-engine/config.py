"""Configuration and database layer for Consent Engine."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    db_host: str = "postgres"
    db_port: int = 5432
    db_user: str = "compliance"
    db_password: str = "compliance"
    db_name: str = "compliance"

    redis_host: str = "redis"
    redis_port: int = 6379

    kafka_bootstrap: str = "kafka:9092"
    kafka_consent_topic: str = "consent.events"

    otel_exporter_otlp_endpoint: str = "http://otel-collector:4317"
    service_name: str = "consent-engine"

    @property
    def db_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )
