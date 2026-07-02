from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration. All values overridable via OVERWATCH_* env vars."""

    model_config = SettingsConfigDict(env_prefix="OVERWATCH_", env_file=".env", extra="ignore")

    database_url: str = "postgresql://overwatch:overwatch_dev@postgis:5432/overwatch"
    redis_url: str = "redis://redis:6379/0"
    anthropic_api_key: str | None = None
    fusion_enabled: bool = True


settings = Settings()
