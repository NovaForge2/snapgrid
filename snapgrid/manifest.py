# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 NovaForge2
"""Reading plugin.toml files and finding plugins on disk.

A plugin is a folder inside plugins/ that contains a plugin.toml and something
to run. A plugin that cannot be read is not hidden: it is kept with an error
message so the web page can show what is wrong with it.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - only on Python older than 3.11
    print(
        "snapgrid needs Python 3.11 or newer (for tomllib). "
        f"This is Python {sys.version.split()[0]}.",
        file=sys.stderr,
    )
    raise

from .config import DEFAULT_EVERY

MANIFEST_NAME = "plugin.toml"
ENV_NAME = ".env"
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
DURATION_RE = re.compile(r"^(\d+)\s*([smh])$")


class ManifestError(Exception):
    """plugin.toml is missing something or says something impossible."""


@dataclass
class Plugin:
    id: str
    dir: Path
    name: str
    description: str = ""
    group: str = ""
    enabled: bool = True
    command: list[str] = field(default_factory=list)
    timeout: int = 300
    every: int | None = None          # seconds between runs, None means manual only
    columns: list[str] | None = None  # expected header, None means take it from the output
    history_keep: int = 0             # how many different snapshots to keep
    mtime: float = 0.0
    error: str = ""                   # set when the manifest could not be read

    @property
    def env_file(self) -> Path:
        return self.dir / ENV_NAME

    @property
    def runnable(self) -> bool:
        return self.enabled and not self.error


def parse_duration(value: object, field_name: str) -> int | None:
    """Turn "15m" into 900. "off" and "" mean no schedule."""
    if value is None:
        return None
    if isinstance(value, int) and not isinstance(value, bool):
        return value if value > 0 else None
    if not isinstance(value, str):
        raise ManifestError(f"{field_name} must be text like \"15m\", or \"off\"")

    text = value.strip().lower()
    if text in ("", "off", "never", "manual"):
        return None
    match = DURATION_RE.match(text)
    if not match:
        raise ManifestError(
            f"{field_name} is \"{value}\" but should look like \"30s\", \"15m\", \"2h\" or \"off\""
        )
    amount, unit = int(match.group(1)), match.group(2)
    seconds = amount * {"s": 1, "m": 60, "h": 3600}[unit]
    if seconds <= 0:
        return None
    return seconds


def _table(data: dict, name: str) -> dict:
    value = data.get(name, {})
    if not isinstance(value, dict):
        raise ManifestError(f"[{name}] must be a section")
    return value


def _string_list(value: object, field_name: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ManifestError(f"{field_name} must be a list of text values")
    return list(value)


def parse_manifest(text: str, plugin_id: str, directory: Path, mtime: float) -> Plugin:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ManifestError(f"plugin.toml is not valid TOML: {exc}") from exc

    plugin_table = _table(data, "plugin")
    run_table = _table(data, "run")
    table_table = _table(data, "table")
    history_table = _table(data, "history")

    name = plugin_table.get("name", plugin_id)
    if not isinstance(name, str) or not name.strip():
        raise ManifestError("[plugin] name must be a non-empty text value")

    description = plugin_table.get("description", "")
    group = plugin_table.get("group", "")
    enabled = plugin_table.get("enabled", True)
    if not isinstance(description, str) or not isinstance(group, str):
        raise ManifestError("[plugin] description and group must be text values")
    if not isinstance(enabled, bool):
        raise ManifestError("[plugin] enabled must be true or false")

    if "command" not in run_table:
        raise ManifestError('[run] command is required, for example command = ["python", "main.py"]')
    command = _string_list(run_table["command"], "[run] command")
    if not command:
        raise ManifestError("[run] command cannot be empty")

    timeout = run_table.get("timeout", 300)
    if not isinstance(timeout, int) or isinstance(timeout, bool) or timeout <= 0:
        raise ManifestError("[run] timeout must be a whole number of seconds")

    every = parse_duration(run_table.get("every", DEFAULT_EVERY), "[run] every")

    columns = None
    if "columns" in table_table:
        columns = _string_list(table_table["columns"], "[table] columns")
        if not columns:
            raise ManifestError("[table] columns cannot be an empty list")

    history_keep = history_table.get("keep", 0)
    if not isinstance(history_keep, int) or isinstance(history_keep, bool) or history_keep < 0:
        raise ManifestError("[history] keep must be 0 or more")

    return Plugin(
        id=plugin_id,
        dir=directory,
        name=name.strip(),
        description=description.strip(),
        group=group.strip(),
        enabled=enabled,
        command=command,
        timeout=timeout,
        every=every,
        columns=columns,
        history_keep=history_keep,
        mtime=mtime,
    )


def load_plugin(directory: Path) -> Plugin | None:
    """Read one plugin folder. Returns None if it is not a plugin at all."""
    manifest = directory / MANIFEST_NAME
    if not manifest.is_file():
        return None

    plugin_id = directory.name
    mtime = manifest.stat().st_mtime
    if not ID_RE.match(plugin_id):
        return Plugin(
            id=plugin_id,
            dir=directory,
            name=plugin_id,
            mtime=mtime,
            error="folder name may only contain letters, digits, dot, dash and underscore",
        )

    try:
        return parse_manifest(manifest.read_text(encoding="utf-8"), plugin_id, directory, mtime)
    except ManifestError as exc:
        return Plugin(id=plugin_id, dir=directory, name=plugin_id, mtime=mtime, error=str(exc))
    except OSError as exc:
        return Plugin(id=plugin_id, dir=directory, name=plugin_id, mtime=mtime, error=f"cannot read plugin.toml: {exc}")


class Registry:
    """Keeps the current list of plugins, re-read from disk when files change."""

    def __init__(self, plugins_dir: Path) -> None:
        self.plugins_dir = plugins_dir
        self._plugins: dict[str, Plugin] = {}

    def scan(self) -> None:
        found: dict[str, Plugin] = {}
        if self.plugins_dir.is_dir():
            for entry in sorted(self.plugins_dir.iterdir()):
                if not entry.is_dir() or entry.name.startswith("."):
                    continue
                plugin = load_plugin(entry)
                if plugin is not None:
                    found[plugin.id] = plugin
        self._plugins = found

    def all(self) -> list[Plugin]:
        return sorted(self._plugins.values(), key=lambda p: (p.group.lower(), p.name.lower()))

    def get(self, plugin_id: str) -> Plugin | None:
        return self._plugins.get(plugin_id)
