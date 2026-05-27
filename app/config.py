from functools import lru_cache
import subprocess
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
    audio_discovery_timeout_seconds: float = 1.0
    audio_playback_timeout_seconds: float = 3.0
    pigeonater_version: str = "dev"
    pigeonater_commit: str = "unknown"
    pigeonater_build_date: str = "unknown"


def resolve_version(config: AppConfig) -> dict[str, str]:
    commit = config.pigeonater_commit
    build_date = config.pigeonater_build_date
    version = config.pigeonater_version

    if commit == "unknown":
        commit = _git_output(["git", "rev-parse", "--short", "HEAD"]) or commit
    if build_date == "unknown":
        build_date = _git_output(["git", "show", "-s", "--format=%cs", "HEAD"]) or build_date
    if version == "dev" and commit != "unknown" and build_date != "unknown":
        version = f"{build_date}-{commit[:7]}"

    return {"version": version, "commit": commit, "build_date": build_date}


def _git_output(command: list[str]) -> str | None:
    try:
        result = subprocess.run(command, capture_output=True, check=False, text=True, timeout=1.0)
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


@lru_cache
def get_config() -> AppConfig:
    return AppConfig()
