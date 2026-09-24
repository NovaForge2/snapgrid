# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 NovaForge2
"""Running plugins.

Runs happen in the background on a small pool of worker threads, so the web
page never waits for one. A few rules keep this predictable:

* only a few runs happen at once, because plugins usually talk to the same
  system with the same credentials, and twenty at once is how you get
  throttled;
* the same plugin never runs twice at the same time. Clicking Refresh while it
  is already running attaches to the run in progress instead of starting
  another;
* a run started by a click goes to the front of the queue, because someone is
  watching it. Scheduled runs can wait;
* standard output is the table, standard error is the log, and the exit code
  decides whether the run succeeded.
"""

from __future__ import annotations

import csv
import io
import os
import queue
import signal
import subprocess
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

from . import store as store_module
from .config import Config, LOG_LINES
from .manifest import Plugin, load_plugin
from .secrets_store import SecretError, load_env, mask
from .store import Store

MAX_OUTPUT_BYTES = 32 * 1024 * 1024

PRIORITY_MANUAL = 0
PRIORITY_SCHEDULE = 1


class OutputError(Exception):
    """The script ran, but what it printed is not a table we can use."""


def parse_csv(text: str, expected_columns: list[str] | None) -> tuple[list[str], list[list[str]]]:
    text = text.lstrip("﻿")
    rows = [row for row in csv.reader(io.StringIO(text))]
    while rows and (not rows[-1] or all(cell.strip() == "" for cell in rows[-1])):
        rows.pop()
    if not rows:
        raise OutputError("the script printed nothing on standard output")

    header = [cell.strip() for cell in rows[0]]
    if not any(header):
        raise OutputError("the first line of the output should be the column names")

    if expected_columns is not None and header != expected_columns:
        raise OutputError(
            "the header line does not match [table] columns in plugin.toml.\n"
            f"  plugin.toml says: {expected_columns}\n"
            f"  the script printed: {header}"
        )

    width = len(header)
    data: list[list[str]] = []
    for number, row in enumerate(rows[1:], start=2):
        if not row or all(cell.strip() == "" for cell in row):
            continue
        if len(row) > width:
            raise OutputError(
                f"line {number} has {len(row)} values but there are {width} columns. "
                "A value containing a comma has to be quoted."
            )
        if len(row) < width:
            row = row + [""] * (width - len(row))
        data.append(row)
    return header, data


def resolve_command(command: list[str]) -> list[str]:
    """Make a bare "python" or "python3" mean the interpreter running snapgrid.

    Which of the two names exists depends on the machine, and a plugin that
    works on one and not the other is a pointless thing to debug. It also means
    a plugin always runs on the same Python as the server, which is what you
    want when the whole point is the standard library.

    Give a full path if you deliberately want a different interpreter.
    """
    if command and command[0] in ("python", "python3"):
        return [sys.executable] + list(command[1:])
    return list(command)


def _kill_tree(proc: subprocess.Popen) -> None:
    """Stop the process and anything it started.

    Signals are not available everywhere, so the platform's own tool is used
    where they are not.
    """
    if proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True,
                check=False,
            )
        else:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (OSError, ProcessLookupError):
        pass
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass


@dataclass
class _Active:
    run_id: int
    plugin_id: str
    started_at: float
    proc: subprocess.Popen | None = None
    tail: deque = field(default_factory=lambda: deque(maxlen=LOG_LINES))
    cancelled: bool = False


class Runner:
    def __init__(self, store: Store, registry, config: Config) -> None:
        self.store = store
        self.registry = registry
        self.config = config
        self._queue: queue.PriorityQueue = queue.PriorityQueue()
        self._lock = threading.RLock()
        self._active: dict[str, _Active] = {}
        self._queued: dict[str, int] = {}
        self._cancelled_before_start: set[int] = set()
        self._seq = 0
        self._workers: list[threading.Thread] = []
        self._stopping = threading.Event()

    # ----- lifecycle ----------------------------------------------------

    def start(self) -> None:
        for index in range(self.config.max_concurrent):
            worker = threading.Thread(target=self._work, name=f"snapgrid-worker-{index}", daemon=True)
            worker.start()
            self._workers.append(worker)

    def stop(self) -> None:
        self._stopping.set()
        with self._lock:
            for active in self._active.values():
                active.cancelled = True
                if active.proc:
                    _kill_tree(active.proc)

    # ----- public state -------------------------------------------------

    def is_busy(self, plugin_id: str) -> bool:
        with self._lock:
            return plugin_id in self._active or plugin_id in self._queued

    def live(self, plugin_id: str) -> dict | None:
        with self._lock:
            active = self._active.get(plugin_id)
            if active:
                return {
                    "run_id": active.run_id,
                    "status": store_module.RUNNING,
                    "started_at": active.started_at,
                    "elapsed": time.time() - active.started_at,
                    "log": "\n".join(active.tail),
                }
            run_id = self._queued.get(plugin_id)
            if run_id is not None:
                return {"run_id": run_id, "status": store_module.QUEUED, "elapsed": 0, "log": ""}
        return None

    def submit(self, plugin: Plugin, trigger: str) -> int:
        """Ask for a run. If one is already happening or waiting, return that one."""
        with self._lock:
            if plugin.id in self._active:
                return self._active[plugin.id].run_id
            if plugin.id in self._queued:
                return self._queued[plugin.id]

            run_id = self.store.create_run(plugin.id, trigger)
            self._queued[plugin.id] = run_id
            self._seq += 1
            priority = PRIORITY_MANUAL if trigger == "manual" else PRIORITY_SCHEDULE
            self._queue.put((priority, self._seq, run_id, plugin.id))
            return run_id

    def cancel(self, run_id: int) -> bool:
        with self._lock:
            for active in self._active.values():
                if active.run_id == run_id:
                    active.cancelled = True
                    if active.proc:
                        _kill_tree(active.proc)
                    return True
            for plugin_id, queued_id in list(self._queued.items()):
                if queued_id == run_id:
                    self._cancelled_before_start.add(run_id)
                    del self._queued[plugin_id]
                    self.store.finish_run(
                        run_id, plugin_id, store_module.CANCELLED, error="cancelled before it started"
                    )
                    return True
        return False

    # ----- worker -------------------------------------------------------

    def _work(self) -> None:
        while not self._stopping.is_set():
            try:
                priority, seq, run_id, plugin_id = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue

            try:
                with self._lock:
                    if run_id in self._cancelled_before_start:
                        self._cancelled_before_start.discard(run_id)
                        continue
                    if self._queued.get(plugin_id) == run_id:
                        del self._queued[plugin_id]
                    if plugin_id in self._active:
                        continue
                    active = _Active(run_id=run_id, plugin_id=plugin_id, started_at=time.time())
                    self._active[plugin_id] = active

                try:
                    self._execute(plugin_id, active)
                finally:
                    with self._lock:
                        self._active.pop(plugin_id, None)
            finally:
                self._queue.task_done()

    def _execute(self, plugin_id: str, active: _Active) -> None:
        run_id = active.run_id
        base = self.registry.get(plugin_id)
        # Read the folder again so edits to plugin.toml and .env take effect
        # without restarting the server.
        plugin = load_plugin(base.dir) if base else None
        if plugin is None:
            self.store.finish_run(run_id, plugin_id, store_module.FAILED, error="plugin no longer exists")
            return
        if plugin.error:
            self.store.finish_run(run_id, plugin_id, store_module.FAILED, error=plugin.error)
            return

        self.store.mark_running(run_id)

        try:
            env_values, secret_values = load_env(plugin.env_file)
        except SecretError as exc:
            self.store.finish_run(run_id, plugin_id, store_module.FAILED, error=str(exc))
            return
        except OSError as exc:
            self.store.finish_run(run_id, plugin_id, store_module.FAILED, error=f"cannot read .env: {exc}")
            return

        environment = os.environ.copy()
        environment.update(env_values)
        environment["SNAPGRID_PLUGIN"] = plugin.id
        environment["PYTHONUNBUFFERED"] = "1"

        popen_kwargs: dict = {}
        if os.name == "nt":
            popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            popen_kwargs["start_new_session"] = True

        try:
            proc = subprocess.Popen(
                resolve_command(plugin.command),
                cwd=str(plugin.dir),
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                **popen_kwargs,
            )
        except FileNotFoundError:
            self.store.finish_run(
                run_id,
                plugin_id,
                store_module.FAILED,
                error=f"cannot run {plugin.command[0]!r}: no such program. "
                f"Check [run] command in plugin.toml.",
            )
            return
        except OSError as exc:
            self.store.finish_run(run_id, plugin_id, store_module.FAILED, error=f"cannot start the plugin: {exc}")
            return

        with self._lock:
            active.proc = proc

        stdout_chunks: list[bytes] = []

        def read_stdout() -> None:
            assert proc.stdout is not None
            stdout_chunks.append(proc.stdout.read(MAX_OUTPUT_BYTES + 1))

        def read_stderr() -> None:
            assert proc.stderr is not None
            for raw in proc.stderr:
                line = raw.decode("utf-8", "replace").rstrip("\r\n")
                line = mask(line, secret_values)
                with self._lock:
                    active.tail.append(line)

        out_thread = threading.Thread(target=read_stdout, daemon=True)
        err_thread = threading.Thread(target=read_stderr, daemon=True)
        out_thread.start()
        err_thread.start()

        deadline = time.time() + plugin.timeout
        status = store_module.OK
        while proc.poll() is None:
            if active.cancelled:
                _kill_tree(proc)
                status = store_module.CANCELLED
                break
            if time.time() > deadline:
                _kill_tree(proc)
                status = store_module.TIMEOUT
                break
            time.sleep(0.1)

        proc.wait()
        # Killing the process makes it exit on its own, so the loop above can
        # fall out before it notices the flag. Check again, otherwise a cancel
        # is recorded as a crash.
        if active.cancelled and status == store_module.OK:
            status = store_module.CANCELLED
        out_thread.join(timeout=5)
        err_thread.join(timeout=5)

        # A server that runs plugins on a schedule for weeks cannot afford to
        # leak two file handles per run.
        for stream in (proc.stdout, proc.stderr):
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    pass

        with self._lock:
            log = "\n".join(active.tail)

        if status == store_module.CANCELLED:
            self.store.finish_run(run_id, plugin_id, status, error="cancelled", log=log)
            return
        if status == store_module.TIMEOUT:
            self.store.finish_run(
                run_id,
                plugin_id,
                status,
                error=f"the plugin was stopped after {plugin.timeout} seconds ([run] timeout)",
                log=log,
            )
            return

        exit_code = proc.returncode
        if exit_code != 0:
            last_line = active.tail[-1] if active.tail else ""
            detail = f": {last_line}" if last_line else ""
            self.store.finish_run(
                run_id, plugin_id, store_module.FAILED, exit_code=exit_code,
                error=f"the plugin exited with code {exit_code}{detail}", log=log,
            )
            return

        raw = stdout_chunks[0] if stdout_chunks else b""
        if len(raw) > MAX_OUTPUT_BYTES:
            self.store.finish_run(
                run_id, plugin_id, store_module.FAILED, exit_code=exit_code,
                error="the plugin printed more than 32 MB, which is too much for a table", log=log,
            )
            return

        text = mask(raw.decode("utf-8", "replace"), secret_values)
        try:
            columns, rows = parse_csv(text, plugin.columns)
        except OutputError as exc:
            self.store.finish_run(
                run_id, plugin_id, store_module.FAILED, exit_code=exit_code, error=str(exc), log=log
            )
            return

        snapshot_id, changed = self.store.save_snapshot(plugin.id, columns, rows, plugin.history_keep or 1)
        self.store.finish_run(
            run_id, plugin_id, store_module.OK, exit_code=exit_code, log=log,
            snapshot_id=snapshot_id, row_count=len(rows), changed=changed,
        )
        self.store.prune_runs(plugin.id, keep=200)
