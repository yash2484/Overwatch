from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration. All values overridable via OVERWATCH_* env vars."""

    model_config = SettingsConfigDict(env_prefix="OVERWATCH_", env_file=".env", extra="ignore")

    database_url: str = "postgresql://overwatch:overwatch_dev@postgis:5432/overwatch"
    redis_url: str = "redis://redis:6379/0"
    stac_api_url: str = "https://earth-search.aws.element84.com/v1"
    anthropic_api_key: str | None = None
    fusion_enabled: bool = True
    max_aoi_km2: float = 500.0  # design spec §6 — reject larger AOIs at the API


settings = Settings()
