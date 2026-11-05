from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")
    model_api_key: SecretStr = SecretStr("")
    mock_models: bool = False
    demo_mode: bool = True
    database_url: str = "sqlite:///./data/tapegrade.db"
    max_candidates: int = Field(3, ge=1, le=6)
    max_clips_per_candidate: int = Field(2, ge=1, le=2)
    max_sam_retries: int = Field(2, ge=0, le=2)
    max_live_model_calls_per_scan: int = Field(15, ge=1, le=50)
    max_clip_seconds: int = Field(30, ge=1, le=30)
    max_upload_mb: int = Field(100, ge=1, le=200)
    meta_base_url: str = "https://api.meta.ai"
    spark_model: str = "muse-spark-1.3"
    spark_max_completion_tokens: int = Field(2048, ge=128, le=16384)
    spark_reasoning_effort: Literal["minimal", "low", "medium", "high", "xhigh", "max"] = "low"
    sam_model: str = "sam-3.1"
    image_model: str = "muse-image-1.0"
    model_timeout_seconds: int = 120
    perception_quality_threshold: float = Field(0.75, ge=0, le=1)
    scheduler_enabled: bool = False
    worker_poll_seconds: float = 1
    nba_stats_provider: Literal["none", "balldontlie", "sportradar", "import"] = "none"
    balldontlie_api_key: SecretStr = SecretStr("")
    sportradar_api_key: SecretStr = SecretStr("")
    sportradar_access_level: Literal["trial", "production"] = "trial"
    sportradar_min_interval_seconds: float = Field(4.0, ge=1.05, le=10)
    stats_window_days: int = Field(30, ge=7, le=30)
    stats_max_pages: int = Field(60, ge=1, le=100)
    stats_timeout_seconds: int = Field(90, ge=5, le=180)
    stats_fresh_hours: int = Field(24, ge=1, le=48)
    stats_auto_refresh_minutes: int = Field(60, ge=5, le=1440)
    footage_catalog_path: Path | None = None
    footage_media_root: Path | None = None
    footage_allowed_hosts: list[str] = Field(default_factory=list)
    footage_max_age_days: int = Field(7, ge=1, le=30)
    footage_discovery_enabled: bool = True
    public_footage_analysis_enabled: bool = False
    # Heartbeats/leases are refreshed by the worker around each expensive operation.
    job_lease_seconds: int = 600

    @field_validator("footage_catalog_path", "footage_media_root", mode="before")
    @classmethod
    def optional_path(cls, value):
        return None if value in (None, "") else value

    @property
    def data_dir(self) -> Path:
        return ROOT / "data"


settings = Settings()
