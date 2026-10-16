# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 NovaForge2
"""Check a plugin and existing data without executing its command."""

from pathlib import Path

from .manifest import load_plugin
from .runner import OutputError, parse_csv, parse_table, read_output_file, MAX_OUTPUT_BYTES


def validate_plugin(folder: Path, csv_path: Path | None = None) -> str:
    plugin = load_plugin(folder)
    if plugin is None:
        raise OutputError("no plugin.toml in this folder")
    if plugin.error:
        raise OutputError(plugin.error)
    if csv_path is None and not plugin.output_file:
        return "manifest valid; table not checked (capture stdout and pass --csv FILE)"
    try:
        if csv_path is not None:
            with csv_path.open("rb") as stream:
                raw = stream.read(MAX_OUTPUT_BYTES + 1)
            if len(raw) > MAX_OUTPUT_BYTES:
                raise OutputError("the table is larger than 32 MB")
            columns, rows = parse_csv(raw.decode("utf-8", "replace"), plugin.columns)
        else:
            columns, rows = parse_table(read_output_file(plugin, 0), plugin)
        if any(not name for name in columns) or len(set(columns)) != len(columns):
            raise OutputError("column names must be non-empty and unique")
        key = plugin.key or columns[0]
        if key not in columns:
            raise OutputError(f"key column {key!r} is missing")
        index = columns.index(key)
        seen = set()
        for row in rows:
            value = row[index]
            if not value.strip() or value in seen:
                raise OutputError(f"key column {key!r} must contain non-empty, unique values")
            seen.add(value)
    except Exception as exc:
        raise OutputError(str(exc)) from exc
    return f"manifest and table valid ({len(rows)} rows)"
