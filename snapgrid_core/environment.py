# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 NovaForge2
"""Read plugin environment variables without interpreting their values."""

from pathlib import Path


def parse_env_file(text: str) -> list[tuple[str, str]]:
    """Read KEY=VALUE lines, ignoring blanks and comments."""
    pairs: list[tuple[str, str]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        key, sep, value = line.partition("=")
        if not sep:
            continue
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key:
            pairs.append((key, value))
    return pairs


def load_env(env_file: Path) -> dict[str, str]:
    """Load literal .env values; decoding and credentials belong to the plugin."""
    if not env_file.exists():
        return {}
    return dict(parse_env_file(env_file.read_text(encoding="utf-8")))
