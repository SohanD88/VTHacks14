from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="SPATIAL_", extra="ignore")

    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
        "http://localhost:5177",
        "http://127.0.0.1:5177",
    ]
    blender_binary: str = "blender"
    blender_transport: Literal["headless", "mcp", "container"] = "headless"
    blender_jobs_dir: Path = Path("/jobs")
    blender_mcp_command: str = "blender-mcp"
    blender_mcp_python: str = "python3"
    blender_timeout_seconds: int = Field(default=300, ge=10, le=1800)
    blender_api_key: str = Field(default="", repr=False)
    blender_provider: Literal["openai", "gemini"] = "openai"
    gemini_keychain_service: str = ""
    blender_planner_model: str = ""
    blender_visual_review: bool = True
    blender_api_base: str = "https://api.openai.com/v1"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    max_stored_scans: int = 20
    max_upload_bytes: int = 250 * 1024**2
    max_storage_bytes: int = 2 * 1024**3
    data_dir: Path = Path(__file__).resolve().parents[2] / ".spatial-data"
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
