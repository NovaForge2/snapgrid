# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 NovaForge2
"""Deciding when a plugin should run again.

Every plugin runs on a schedule unless it is disabled or sets every = "off".
The interval is measured from the moment the last run finished, not from a
wall clock, so a plugin can never overlap with itself and a slow plugin does
not fall behind.

A plugin that keeps failing is slowed down instead of retried at full speed:
after a few failures in a row the interval doubles each time, up to an hour.
Otherwise a single expired password fills the history with hundreds of
identical failures overnight. The first success puts it back to normal.
"""

from __future__ import annotations

import threading
import time

from .config import BACKOFF_AFTER_FAILURES, BACKOFF_MAX_SECONDS, SCAN_SECONDS, TICK_SECONDS


def interval_for(every: int, failures: int) -> int:
    if failures < BACKOFF_AFTER_FAILURES:
        return every
    factor = 2 ** (failures - BACKOFF_AFTER_FAILURES + 1)
    return min(every * factor, max(every, BACKOFF_MAX_SECONDS))


class Scheduler(threading.Thread):
    def __init__(self, store, registry, runner) -> None:
        super().__init__(name="snapgrid-scheduler", daemon=True)
        self.store = store
        self.registry = registry
        self.runner = runner
        self._stop = threading.Event()
        self._last_scan = 0.0
        self._seen_mtime: dict[str, float] = {}

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception as exc:  # keep the scheduler alive whatever happens
                print(f"snapgrid: scheduler error: {exc}")
            self._stop.wait(TICK_SECONDS)

    def _tick(self) -> None:
        now = time.time()
        if now - self._last_scan >= SCAN_SECONDS:
            self.registry.scan()
            self._last_scan = now

        for plugin in self.registry.all():
            # An edited manifest clears the backoff. Someone changing a plugin
            # is trying to fix it, and should not have to wait out an hour of
            # doubling - or delete the database - to see whether it worked.
            if self._seen_mtime.get(plugin.id, plugin.mtime) != plugin.mtime:
                self.store.clear_failures(plugin.id)
            self._seen_mtime[plugin.id] = plugin.mtime

            if not plugin.runnable or plugin.every is None:
                continue
            if self.runner.is_busy(plugin.id):
                continue
            last_finished, failures = self.store.get_state(plugin.id)
            if now - last_finished >= interval_for(plugin.every, failures):
                self.runner.submit(plugin, "schedule")
