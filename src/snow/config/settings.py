"""Where Snow keeps config, data and run state; loads TOML config (CORE-04)."""

import os
import tomllib
from pathlib import Path

from pydantic import BaseModel


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def config_dir() -> Path:
    override = os.environ.get("SNOW_CONFIG_DIR")
    return Path(override) if override else repo_root() / "config"


def data_dir() -> Path:
    override = os.environ.get("SNOW_DATA_DIR")
    if override:
        return Path(override)
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Snow"


def run_dir() -> Path:
    return data_dir() / "run"


def load_config[M: BaseModel](filename: str, model_cls: type[M]) -> M:
    """Parse `<config_dir>/<filename>` into `model_cls` (raises OSError, ValueError)."""
    with (config_dir() / filename).open("rb") as f:
        return model_cls.model_validate(tomllib.load(f))
