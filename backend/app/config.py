from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="SPATIAL_", extra="ignore")

    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    max_stored_scans: int = 100
    detection_confidence: float = Field(
        default=0.5,
        ge=0,
        le=1,
        validation_alias=AliasChoices("SPATIAL_DETECTION_CONFIDENCE", "DETECTION_CONFIDENCE"),
    )
    model_cache: Path = Path(__file__).resolve().parents[2] / ".model-cache"


@lru_cache
def get_settings() -> Settings:
    return Settings()
