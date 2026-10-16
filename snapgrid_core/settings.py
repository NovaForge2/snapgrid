# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 NovaForge2
"""The settings file.

One file, `snapgrid.toml`, in the folder snapgrid was cloned into. It configures
the server; a `plugin.toml` inside a plugin folder configures one plugin.

Every key is optional and the defaults apply without the file. A command line
option beats the file.

The title and the banner are read again on every request, so editing them shows
up immediately. Port and concurrency are read once at startup, because changing
either means restarting anyway.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

SETTINGS_NAME = "snapgrid.toml"
BANNER_LEVELS = ("info", "warning", "error")

DEFAULTS = {
    "title": "snapgrid",
    "port": 8765,
    "max_concurrent": 3,
    "banner_text": "",
    "banner_level": "info",
}


SETTINGS_PATH = Path(__file__).resolve().parent.parent / SETTINGS_NAME


def load_settings() -> dict:
    """Read snapgrid.toml if it is there. Never raises."""
    settings = dict(DEFAULTS)
    if SETTINGS_PATH.is_file():
        _apply_file(SETTINGS_PATH, settings)
    return settings


def _apply_file(path: Path, settings: dict) -> None:
    """Overlay one file onto the settings so far.

    A broken file turns into a banner saying so, which is more useful than a
    server that refuses to start or, worse, quietly ignores the file.
    """
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        settings["banner_text"] = f"{path} could not be read: {exc}"
        settings["banner_level"] = "error"
        return

    server = data.get("server") or {}
    if isinstance(server, dict):
        title = server.get("title")
        if isinstance(title, str) and title.strip():
            settings["title"] = title.strip()
        port = server.get("port")
        if isinstance(port, int) and not isinstance(port, bool) and 1 <= port <= 65535:
            settings["port"] = port
        limit = server.get("max_concurrent")
        if isinstance(limit, int) and not isinstance(limit, bool) and limit >= 1:
            settings["max_concurrent"] = limit

    banner = data.get("banner") or {}
    if isinstance(banner, dict):
        text = banner.get("text")
        if isinstance(text, str):
            settings["banner_text"] = text.strip()
        level = banner.get("level")
        if isinstance(level, str) and level.strip().lower() in BANNER_LEVELS:
            settings["banner_level"] = level.strip().lower()
