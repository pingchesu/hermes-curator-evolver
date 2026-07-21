"""Filesystem paths for Hermes Curator Evolver."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PLUGIN_NAME = "curator-evolver"


def _platform_default_hermes_home() -> Path:
    """Mirror Hermes' platform-native fallback when its constants are unavailable."""

    if sys.platform == "win32":
        local_appdata = os.getenv("LOCALAPPDATA", "").strip()
        base = Path(local_appdata) if local_appdata else Path.home() / "AppData" / "Local"
        return base / "hermes"
    return Path.home() / ".hermes"


def hermes_home() -> Path:
    """Return Hermes home, profile-aware when running inside Hermes."""
    try:
        from hermes_constants import get_hermes_home
    except ImportError:
        env_home = os.getenv("HERMES_HOME")
        if env_home:
            return Path(env_home).expanduser()
        return _platform_default_hermes_home()
    return Path(get_hermes_home())


def data_dir() -> Path:
    """Return plugin data directory and create it if needed."""
    path = hermes_home() / "plugins" / PLUGIN_NAME / "data"
    path.mkdir(parents=True, exist_ok=True)
    return path


def default_db_path() -> Path:
    """Return the configured SQLite database path."""
    override = os.getenv("HERMES_CURATOR_EVOLVER_DB")
    if override:
        path = Path(override).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        return path
    return data_dir() / "evidence.sqlite"
