# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 NovaForge2
"""Server settings and filesystem layout.

There are two separate places, and they are deliberately not the same one:

* the **plugins folder**, which is yours. It can be anywhere - inside this
  checkout, or a completely different repository of your own plugins.
* the **web folder**, which belongs to the framework and always sits next to
  this package, so pointing snapgrid at a different plugins folder cannot
  leave it without a user interface.

Everything snapgrid itself writes - the database, the log, the port it chose -
goes into a hidden `.snapgrid` folder inside the plugins folder, so one
workspace is one self-contained thing. Folders whose name begins with a dot are
never treated as plugins, so it stays out of the way.
"""

from dataclasses import dataclass, field
from pathlib import Path

# How often the scheduler looks for plugins that are due, in seconds.
TICK_SECONDS = 5

# How often the plugins folder is re-read, in seconds.
SCAN_SECONDS = 10

# Interval used when a plugin does not set one itself.
DEFAULT_EVERY = "15m"

# A plugin that keeps failing is slowed down instead of retried at full rate.
BACKOFF_AFTER_FAILURES = 3
BACKOFF_MAX_SECONDS = 3600

# Kept per plugin so a long history of runs cannot grow without limit.
RUNS_KEPT_PER_PLUGIN = 200

# Lines of stderr kept for a finished run, and while it is still running.
LOG_LINES = 400

DATA_DIR_NAME = ".snapgrid"


def display_path(path: Path) -> str:
    """A path as someone would type it, from where they are standing.

    Relative when it is nearby, which is shorter and sidesteps the question of
    which slash to use, and forward slashes otherwise, so that a printed path
    can be pasted straight back into a shell.
    """
    try:
        relative = Path(path).relative_to(Path.cwd())
    except ValueError:
        return Path(path).as_posix()
    return relative.as_posix() or "."


@dataclass
class Config:
    plugins_dir: Path
    data_dir: Path | None = None
    host: str = "127.0.0.1"
    port: int = 8765
    max_concurrent: int = 3
    web_dir: Path = field(init=False)
    db_path: Path = field(init=False)
    state_file: Path = field(init=False)
    log_file: Path = field(init=False)

    def __post_init__(self) -> None:
        self.plugins_dir = Path(self.plugins_dir).expanduser().resolve()
        self.data_dir = (
            Path(self.data_dir).expanduser().resolve()
            if self.data_dir
            else self.plugins_dir / DATA_DIR_NAME
        )
        # Ships with the code, not with the workspace.
        self.web_dir = Path(__file__).resolve().parent.parent / "web"
        self.db_path = self.data_dir / "snapgrid.db"
        # Where a running server records its pid and port, so that stop and
        # status never have to go looking for either.
        self.state_file = self.data_dir / "server.json"
        self.log_file = self.data_dir / "server.log"

    def prepare(self) -> None:
        self.plugins_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)
