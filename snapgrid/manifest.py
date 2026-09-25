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
from pathlib import PurePosixPath
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
DURATION_RE = re.compile(r"^(\d+)\s*([smhdw])$")


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
    output_file: str = ""             # read the table from this file instead of stdout
    output_sheet: str = ""            # which sheet of a workbook, if not the first
    fresh_for: int | None = None      # skip the run while the file is younger than this
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
    """Turn "15m" into 900. "off" and "" mean no schedule.

    Seconds, minutes, hours, days and weeks, so that something checked twice a
    day and something checked twice a month are both sayable.
    """
    if value is None:
        return None
    if isinstance(value, int) and not isinstance(value, bool):
        return value if value > 0 else None
    if not isinstance(value, str):
        raise ManifestError(f"{field_name} must be text like \"15m\" or \"10d\", or \"off\"")

    text = value.strip().lower()
    if text in ("", "off", "never", "manual"):
        return None
    match = DURATION_RE.match(text)
    if not match:
        raise ManifestError(
            f"{field_name} is \"{value}\" but should look like \"30s\", \"15m\", \"2h\", "
            f"\"10d\", \"2w\" or \"off\""
        )
    amount, unit = int(match.group(1)), match.group(2)
    seconds = amount * {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}[unit]
    if seconds <= 0:
        return None
    return seconds


def _output_file(output_table: dict) -> str:
    value = output_table.get("file", "")
    if not isinstance(value, str):
        raise ManifestError('[output] file must be text, for example file = "report.csv"')
    value = value.strip()
    if value:
        # The plugin folder is the plugin's world; reading outside it would let
        # a manifest reach anywhere on the machine.
        candidate = PurePosixPath(value.replace("\\", "/"))
        if candidate.is_absolute() or ".." in candidate.parts:
            raise ManifestError(
                "[output] file must be inside the plugin folder, "
                "so it cannot start with / or contain .."
            )
    return value


# What belongs where. A key in the wrong section is accepted by TOML and would
# otherwise be ignored in silence: "timeout = 600" written after [history]
# belongs to [history], and the plugin quietly keeps the default.
KNOWN_KEYS = {
    "plugin": {"name", "description", "group", "enabled"},
    "run": {"command", "timeout", "every"},
    "table": {"columns"},
    "output": {"file", "sheet", "fresh_for"},
    "history": {"keep"},
}
BELONGS_TO = {key: section for section, keys in KNOWN_KEYS.items() for key in keys}


def _check_keys(data: dict) -> None:
    """Refuse a key that is misplaced or misspelt, rather than ignoring it."""
    for section in data:
        if section not in KNOWN_KEYS:
            known = ", ".join(f"[{name}]" for name in KNOWN_KEYS)
            raise ManifestError(f"[{section}] is not a section snapgrid knows. "
                                f"The sections are {known}")

    for section, keys in KNOWN_KEYS.items():
        for key in data.get(section, {}):
            if key in keys:
                continue
            home = BELONGS_TO.get(key)
            if home:
                raise ManifestError(
                    f"{key} is in [{section}], but it belongs in [{home}]. "
                    f"In TOML a key belongs to the section above it, so "
                    f"\"{key} = ...\" has to be written under [{home}] to have "
                    f"any effect"
                )
            raise ManifestError(
                f"[{section}] {key} is not a setting snapgrid knows. "
                f"In [{section}] there is {', '.join(sorted(keys))}"
            )


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

    _check_keys(data)

    plugin_table = _table(data, "plugin")
    run_table = _table(data, "run")
    table_table = _table(data, "table")
    output_table = _table(data, "output")
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

    # A plugin normally runs something. One that only reads a file does not
    # need to, so the command is optional when [output] file says where to look.
    output_file = _output_file(output_table)
    if "command" in run_table:
        command = _string_list(run_table["command"], "[run] command")
        if not command:
            raise ManifestError("[run] command cannot be empty")
    elif output_file:
        command = []
    else:
        raise ManifestError(
            '[run] command is required, for example command = ["python", "main.py"] - '
            'unless [output] file names a file to read instead'
        )

    # Seconds as a number, or the same units as every: timeout = "30m".
    raw_timeout = run_table.get("timeout", 300)
    if isinstance(raw_timeout, str):
        timeout = parse_duration(raw_timeout, "[run] timeout")
        if timeout is None:
            raise ManifestError('[run] timeout cannot be "off" - a plugin that never '
                                "stops would hold a worker for ever")
    elif isinstance(raw_timeout, int) and not isinstance(raw_timeout, bool) and raw_timeout > 0:
        timeout = raw_timeout
    else:
        raise ManifestError('[run] timeout must be a number of seconds, or text '
                            'like "30m" or "2h"')

    every = parse_duration(run_table.get("every", DEFAULT_EVERY), "[run] every")

    columns = None
    if "columns" in table_table:
        columns = _string_list(table_table["columns"], "[table] columns")
        if not columns:
            raise ManifestError("[table] columns cannot be an empty list")

    output_sheet = output_table.get("sheet", "")
    if not isinstance(output_sheet, str):
        raise ManifestError('[output] sheet must be text, for example sheet = "Summary"')

    fresh_for = parse_duration(output_table.get("fresh_for"), "[output] fresh_for")
    if fresh_for is not None and not output_file:
        raise ManifestError(
            "[output] fresh_for only means something with [output] file, "
            "since it is the age of that file"
        )

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
        output_file=output_file,
        output_sheet=output_sheet.strip(),
        fresh_for=fresh_for,
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
