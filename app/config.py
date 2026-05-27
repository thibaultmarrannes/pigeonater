from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppConfig(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    data_dir: Path = Path("data")
    snapshot_dir: Path = Path("data/snapshots")
    database_path: Path = Path("data/pigeonater.sqlite3")
    model_name: str = "yolo11n.pt"
    action_webhook_url: str | None = None
    detector_poll_seconds: float = 0.2
    camera_discovery_timeout_seconds: float = 1.0
    camera_open_timeout_seconds: float = 3.0
    camera_read_timeout_seconds: float = 2.0
    model_detect_timeout_seconds: float = 10.0
    detector_stop_timeout_seconds: float = 2.0


@lru_cache
def get_config() -> AppConfig:
    return AppConfig()
