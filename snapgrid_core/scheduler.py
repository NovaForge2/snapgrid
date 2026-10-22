# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 NovaForge2
"""Deciding when a plugin should run again.

A plugin runs on one of two schedules, unless it is disabled or sets
every = "off".

`every` is measured from the moment the last run finished, not from a wall
clock, so a plugin can never overlap with itself and a slow plugin does not
fall behind. It is right for "look at this every so often" and wrong for
"this has to exist by nine": fifteen minutes that start when the last run
ended drift by the length of the run, every run.

`cron` names the wall clock instead - `"0 9 * * 1-5"` - and the question
asked of it is whether a named moment has gone by since the last run. A nine
o'clock the machine slept through has gone by, so it runs once when snapgrid
comes back; once, however long it was away.

A plugin that keeps failing is slowed down instead of retried at full speed:
after a few failures in a row the interval doubles each time, up to an hour.
Otherwise a single expired password fills the history with hundreds of
identical failures overnight. The first success puts it back to normal.
"""

from __future__ import annotations

import threading
import time

from .config import BACKOFF_AFTER_FAILURES, BACKOFF_MAX_SECONDS, SCAN_SECONDS, TICK_SECONDS

# What the doubling starts from for a plugin with no interval of its own.
# A cron schedule has no gap to double, so the backoff needs one to count in.
BACKOFF_FLOOR_SECONDS = 60


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

        # Read once per tick rather than per plugin: ten plugins would be ten
        # queries for something that changes when somebody presses a button.
        paused = self.store.paused_plugins()

        for plugin in self.registry.all():
            # An edited manifest clears the backoff. Someone changing a plugin
            # is trying to fix it, and should not have to wait out an hour of
            # doubling - or delete the database - to see whether it worked.
            if self._seen_mtime.get(plugin.id, plugin.mtime) != plugin.mtime:
                self.store.clear_failures(plugin.id)
            self._seen_mtime[plugin.id] = plugin.mtime

            if not plugin.runnable or (plugin.every is None and plugin.cron is None):
                continue
            # Paused means the schedule leaves it alone. Run now still works:
            # pressing it is saying so deliberately, which is different from
            # a timer going off.
            if plugin.id in paused:
                continue
            if self.runner.is_busy(plugin.id):
                continue
            last_finished, failures = self.store.get_state(plugin.id)
            if self._due(plugin, last_finished, failures, now):
                self.runner.submit(plugin, "schedule")

    def _due(self, plugin, last_finished: float, failures: int, now: float) -> bool:
        """Whether the schedule asks for a run now.

        A wall clock schedule asks a different question from an interval: not
        "has long enough passed" but "has a named moment gone by since the
        last run". Catching up after the machine was asleep falls out of that
        - a nine o'clock nobody was awake for has still gone by - and so does
        running it only once however long the gap was.
        """
        if plugin.cron is None:
            return now - last_finished >= interval_for(plugin.every, failures)

        # The slowdown after repeated failures still applies. A broken plugin
        # on a one minute schedule would otherwise fill the history overnight
        # exactly as it used to, and the backoff exists to stop that. The
        # missed times are not queued up: when the wait is over, the next
        # named moment runs it.
        if failures >= BACKOFF_AFTER_FAILURES:
            waited = interval_for(BACKOFF_FLOOR_SECONDS, failures)
            if now - last_finished < waited:
                return False
        return plugin.cron.due_since(last_finished, now)
