# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 NovaForge2
"""Everything that is kept on disk, in one SQLite file.

Three kinds of thing are stored:

runs        one row per execution: when it started, how it ended, its log.
snapshots   the table a run produced. A run that produces exactly the same
            table as the one before it does not create a new snapshot, it
            only updates how recently that snapshot was seen. So a plugin on
            a 15 minute schedule that rarely changes keeps a short history of
            real changes instead of hundreds of identical copies.
state       when a plugin last finished, and how many times it has failed in
            a row, which the scheduler uses to slow down broken plugins.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    plugin_id    TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    columns_json TEXT NOT NULL,
    rows_json    TEXT NOT NULL,
    row_count    INTEGER NOT NULL,
    first_seen   REAL NOT NULL,
    last_seen    REAL NOT NULL,
    seen_count   INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS snapshots_by_plugin ON snapshots (plugin_id, id DESC);

CREATE TABLE IF NOT EXISTS runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    plugin_id   TEXT NOT NULL,
    status      TEXT NOT NULL,
    trigger     TEXT NOT NULL,
    queued_at   REAL NOT NULL,
    started_at  REAL,
    finished_at REAL,
    exit_code   INTEGER,
    error       TEXT,
    log         TEXT,
    snapshot_id INTEGER,
    row_count   INTEGER,
    changed     INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS runs_by_plugin ON runs (plugin_id, id DESC);

CREATE TABLE IF NOT EXISTS state (
    plugin_id            TEXT PRIMARY KEY,
    last_finished        REAL,
    consecutive_failures INTEGER NOT NULL DEFAULT 0
);
"""

# Statuses a run can end in. "ok" is the only one that produces a snapshot.
QUEUED = "queued"
RUNNING = "running"
OK = "ok"
FAILED = "failed"
TIMEOUT = "timeout"
CANCELLED = "cancelled"


def _hash(columns: list[str], rows: list[list[str]]) -> str:
    payload = json.dumps([columns, rows], separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class Store:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        with self._lock:
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA synchronous=NORMAL")
            self._db.executescript(SCHEMA)
            self._db.commit()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    # ----- runs ---------------------------------------------------------

    def create_run(self, plugin_id: str, trigger: str) -> int:
        with self._lock:
            cur = self._db.execute(
                "INSERT INTO runs (plugin_id, status, trigger, queued_at) VALUES (?,?,?,?)",
                (plugin_id, QUEUED, trigger, time.time()),
            )
            self._db.commit()
            return int(cur.lastrowid)

    def mark_running(self, run_id: int) -> None:
        with self._lock:
            self._db.execute(
                "UPDATE runs SET status=?, started_at=? WHERE id=?",
                (RUNNING, time.time(), run_id),
            )
            self._db.commit()

    def finish_run(
        self,
        run_id: int,
        plugin_id: str,
        status: str,
        exit_code: int | None = None,
        error: str = "",
        log: str = "",
        snapshot_id: int | None = None,
        row_count: int | None = None,
        changed: bool = False,
    ) -> None:
        now = time.time()
        with self._lock:
            self._db.execute(
                """UPDATE runs
                      SET status=?, finished_at=?, exit_code=?, error=?, log=?,
                          snapshot_id=?, row_count=?, changed=?
                    WHERE id=?""",
                (status, now, exit_code, error, log, snapshot_id, row_count, int(changed), run_id),
            )
            failed = status in (FAILED, TIMEOUT)
            row = self._db.execute(
                "SELECT consecutive_failures FROM state WHERE plugin_id=?", (plugin_id,)
            ).fetchone()
            previous = int(row["consecutive_failures"]) if row else 0
            failures = previous + 1 if failed else 0
            self._db.execute(
                """INSERT INTO state (plugin_id, last_finished, consecutive_failures)
                        VALUES (?,?,?)
                   ON CONFLICT(plugin_id) DO UPDATE
                        SET last_finished=excluded.last_finished,
                            consecutive_failures=excluded.consecutive_failures""",
                (plugin_id, now, failures),
            )
            self._db.commit()

    def get_run(self, run_id: int) -> dict[str, Any] | None:
        with self._lock:
            row = self._db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        return dict(row) if row else None

    def list_runs(self, plugin_id: str, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute(
                """SELECT id, plugin_id, status, trigger, queued_at, started_at, finished_at,
                          exit_code, error, row_count, changed, snapshot_id
                     FROM runs WHERE plugin_id=? ORDER BY id DESC LIMIT ?""",
                (plugin_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def prune_runs(self, plugin_id: str, keep: int) -> None:
        with self._lock:
            self._db.execute(
                """DELETE FROM runs
                    WHERE plugin_id=? AND id NOT IN (
                        SELECT id FROM runs WHERE plugin_id=? ORDER BY id DESC LIMIT ?
                    )""",
                (plugin_id, plugin_id, keep),
            )
            self._db.commit()

    def last_finished_run(self, plugin_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._db.execute(
                """SELECT * FROM runs
                    WHERE plugin_id=? AND finished_at IS NOT NULL
                    ORDER BY id DESC LIMIT 1""",
                (plugin_id,),
            ).fetchone()
        return dict(row) if row else None

    # ----- snapshots ----------------------------------------------------

    def save_snapshot(
        self, plugin_id: str, columns: list[str], rows: list[list[str]], keep: int
    ) -> tuple[int, bool]:
        """Store a table. Returns the snapshot id and whether it differs from the last one."""
        content_hash = _hash(columns, rows)
        now = time.time()
        with self._lock:
            latest = self._db.execute(
                "SELECT id, content_hash FROM snapshots WHERE plugin_id=? ORDER BY id DESC LIMIT 1",
                (plugin_id,),
            ).fetchone()

            if latest and latest["content_hash"] == content_hash:
                self._db.execute(
                    "UPDATE snapshots SET last_seen=?, seen_count=seen_count+1 WHERE id=?",
                    (now, latest["id"]),
                )
                self._db.commit()
                return int(latest["id"]), False

            cur = self._db.execute(
                """INSERT INTO snapshots
                       (plugin_id, content_hash, columns_json, rows_json, row_count,
                        first_seen, last_seen, seen_count)
                   VALUES (?,?,?,?,?,?,?,1)""",
                (
                    plugin_id,
                    content_hash,
                    json.dumps(columns, ensure_ascii=False),
                    json.dumps(rows, ensure_ascii=False),
                    len(rows),
                    now,
                    now,
                ),
            )
            snapshot_id = int(cur.lastrowid)
            self._db.execute(
                """DELETE FROM snapshots
                    WHERE plugin_id=? AND id NOT IN (
                        SELECT id FROM snapshots WHERE plugin_id=? ORDER BY id DESC LIMIT ?
                    )""",
                (plugin_id, plugin_id, max(1, keep)),
            )
            self._db.commit()
            return snapshot_id, True

    def get_snapshot(self, snapshot_id: int) -> dict[str, Any] | None:
        with self._lock:
            row = self._db.execute("SELECT * FROM snapshots WHERE id=?", (snapshot_id,)).fetchone()
        if not row:
            return None
        data = dict(row)
        data["columns"] = json.loads(data.pop("columns_json"))
        data["rows"] = json.loads(data.pop("rows_json"))
        return data

    def latest_snapshot(self, plugin_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._db.execute(
                "SELECT id FROM snapshots WHERE plugin_id=? ORDER BY id DESC LIMIT 1",
                (plugin_id,),
            ).fetchone()
        return self.get_snapshot(int(row["id"])) if row else None

    def list_snapshots(self, plugin_id: str, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute(
                """SELECT id, row_count, first_seen, last_seen, seen_count
                     FROM snapshots WHERE plugin_id=? ORDER BY id DESC LIMIT ?""",
                (plugin_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    # ----- scheduler state ----------------------------------------------

    def clear_failures(self, plugin_id: str) -> None:
        """Forget the run of failures, without touching when it last ran.

        Called when plugin.toml changes: editing a plugin is how someone fixes
        a failing one, and making them wait out an hour of backoff to find out
        whether it worked is the wrong answer.
        """
        with self._lock:
            self._db.execute(
                "UPDATE state SET consecutive_failures=0 WHERE plugin_id=?", (plugin_id,)
            )
            self._db.commit()

    def get_state(self, plugin_id: str) -> tuple[float, int]:
        with self._lock:
            row = self._db.execute(
                "SELECT last_finished, consecutive_failures FROM state WHERE plugin_id=?",
                (plugin_id,),
            ).fetchone()
        if not row:
            return 0.0, 0
        return float(row["last_finished"] or 0.0), int(row["consecutive_failures"] or 0)
