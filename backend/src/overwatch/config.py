from pathlib import Path

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
    anthropic_model: str = "claude-opus-4-8"  # design spec §3; override for cost via env
    brief_max_attempts: int = 3  # design spec §4 — bounded regeneration
    brief_max_prompt_detections: int = 50  # design spec §3 — prompt cap, truncation logged

    # --- Phase 6 console imagery (design §4) ---
    # Deterministic on-disk path for scene PNGs ({aoi_slug}_{stac_id}.png). Deterministic ⇒
    # serving imagery needs no schema change; a cache miss renders on demand and backfills
    # every scene ingested before Phase 6.
    scene_image_dir: Path = Path("/app/data/scenes")

    # --- OSINT fusion (Phase 5 design §6) ---
    # DOC 2.0 is the ONLY usable GDELT surface: GEO 2.0 404s and returns no coordinates
    # anyway (design §2.1/§2.2). Do not point this at /geo/geo.
    gdelt_api_url: str = "https://api.gdeltproject.org/api/v2/doc/doc"
    gdelt_max_records: int = 250  # DOC 2.0 hard cap
    gdelt_min_interval_s: float = 6.0  # spike: >=5s documented; 429s below that (§2.6)
    # v0.1 filters on the record's OWN `language` field — never the unverified
    # `sourcelang:` operator (design decision 7).
    fusion_languages: list[str] = ["English"]
    fusion_max_prompt_articles: int = 10  # prompt-size discipline, carried from Phase 4


settings = Settings()
