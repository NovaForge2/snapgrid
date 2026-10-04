# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 NovaForge2
"""When a plugin is due, and how a broken one is slowed down."""

import tempfile
import time
import unittest
from pathlib import Path

from snapgrid.config import BACKOFF_MAX_SECONDS
from snapgrid.manifest import Plugin, Registry
from snapgrid.scheduler import Scheduler, interval_for
from snapgrid.store import Store


class Backoff(unittest.TestCase):
    def test_a_healthy_plugin_keeps_its_interval(self):
        for failures in range(3):
            self.assertEqual(interval_for(900, failures), 900)

    def test_the_interval_doubles_after_a_run_of_failures(self):
        # One expired password should not produce hundreds of identical
        # failures overnight.
        self.assertEqual(interval_for(900, 3), 1800)
        self.assertEqual(interval_for(900, 4), 3600)

    def test_it_stops_doubling_at_an_hour(self):
        for failures in range(5, 40):
            self.assertLessEqual(interval_for(900, failures), BACKOFF_MAX_SECONDS)

    def test_backing_off_never_makes_a_plugin_run_more_often(self):
        for every in (30, 900, 3600, 7200):
            for failures in range(0, 20):
                self.assertGreaterEqual(interval_for(every, failures), every)

    def test_a_slow_plugin_is_not_sped_up_by_the_cap(self):
        # Its own interval is longer than the cap, so the cap must not win.
        self.assertGreaterEqual(interval_for(7200, 10), 7200)


class NothingRunning:
    """The runner the scheduler talks to, reduced to what it is asked."""

    def __init__(self):
        self.submitted = []

    def is_busy(self, plugin_id):
        return False

    def submit(self, plugin, trigger):
        self.submitted.append((plugin.id, trigger))


class EditingClearsTheBackoff(unittest.TestCase):
    """The bug this exists to prevent.

    A plugin that had been failing all morning sits at the one hour cap. You
    edit plugin.toml to fix it, and nothing happens for an hour, while the
    panel still shows the error from before the edit. Deleting the database
    was the only way out, which is not an answer.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.store = Store(root / "test.db")
        self.addCleanup(self.store.close)
        self.registry = Registry(root / "plugins")
        self.runner = NothingRunning()
        self.scheduler = Scheduler(self.store, self.registry, self.runner)
        # The plugins are put there by hand, so a real scan would only wipe
        # them. What is being tested is what the scheduler does with what it
        # finds, not the finding.
        self.registry.scan = lambda: None

    def fail_a_few_times(self, plugin_id: str, times: int) -> None:
        for _ in range(times):
            run_id = self.store.create_run(plugin_id, "schedule")
            self.store.finish_run(run_id, plugin_id, "failed", error="no")

    def test_failures_are_counted_and_slow_the_plugin_down(self):
        self.fail_a_few_times("p", 4)
        _, failures = self.store.get_state("p")
        self.assertEqual(failures, 4)
        self.assertGreater(interval_for(900, failures), 900)

    def test_an_edited_manifest_clears_them(self):
        self.fail_a_few_times("p", 4)
        plugin = Plugin(id="p", dir=Path("."), name="P", command=["x"], every=900, mtime=100.0)
        self.registry._plugins = {"p": plugin}

        self.scheduler._tick()                      # first sight of it
        self.assertEqual(self.store.get_state("p")[1], 4)

        plugin.mtime = 200.0                        # the file was edited
        self.scheduler._tick()
        self.assertEqual(self.store.get_state("p")[1], 0,
                         "editing plugin.toml should not leave the plugin throttled")

    def test_an_untouched_manifest_keeps_them(self):
        # Otherwise every scan would clear the backoff and it would never work.
        self.fail_a_few_times("p", 4)
        plugin = Plugin(id="p", dir=Path("."), name="P", command=["x"], every=900, mtime=100.0)
        self.registry._plugins = {"p": plugin}
        for _ in range(3):
            self.scheduler._tick()
        self.assertEqual(self.store.get_state("p")[1], 4)

    def test_a_success_clears_them_too(self):
        self.fail_a_few_times("p", 4)
        run_id = self.store.create_run("p", "manual")
        self.store.finish_run(run_id, "p", "ok")
        self.assertEqual(self.store.get_state("p")[1], 0)

    def test_clearing_does_not_disturb_when_it_last_ran(self):
        # Otherwise clearing the backoff would also restart the interval.
        self.fail_a_few_times("p", 4)
        before, _ = self.store.get_state("p")
        time.sleep(0.01)
        self.store.clear_failures("p")
        after, failures = self.store.get_state("p")
        self.assertEqual(after, before)
        self.assertEqual(failures, 0)


if __name__ == "__main__":
    unittest.main()


class Pausing(unittest.TestCase):
    """A plugin the schedule is to leave alone.

    Ten plugins on a machine with little to spare, two of them worth running
    this fortnight. Pausing is snapgrid's own state and never touches
    plugin.toml, so a plugins folder under git stays clean.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.store = Store(root / "test.db")
        self.addCleanup(self.store.close)
        self.registry = Registry(root / "plugins")
        self.runner = NothingRunning()
        self.scheduler = Scheduler(self.store, self.registry, self.runner)
        self.registry.scan = lambda: None
        self.plugin = Plugin(id="p", dir=Path("."), name="P", command=["x"],
                             every=1, mtime=100.0)
        self.registry._plugins = {"p": self.plugin}

    def test_an_unpaused_plugin_is_submitted(self):
        self.scheduler._tick()
        self.assertEqual(self.runner.submitted, [("p", "schedule")])

    def test_a_paused_plugin_is_not(self):
        self.store.set_paused("p", True)
        self.scheduler._tick()
        self.assertEqual(self.runner.submitted, [], "paused means the schedule leaves it")

    def test_resuming_puts_it_back(self):
        self.store.set_paused("p", True)
        self.scheduler._tick()
        self.store.set_paused("p", False)
        self.scheduler._tick()
        self.assertEqual(self.runner.submitted, [("p", "schedule")])

    def test_pausing_one_does_not_pause_another(self):
        self.registry._plugins["q"] = Plugin(id="q", dir=Path("."), name="Q",
                                             command=["x"], every=1, mtime=100.0)
        self.store.set_paused("p", True)
        self.scheduler._tick()
        self.assertEqual([one for one, _ in self.runner.submitted], ["q"])

    def test_pausing_twice_does_not_restart_the_clock(self):
        # How long it has been quiet is the thing worth knowing, so pressing
        # pause again - or Pause all over something already paused - must not
        # make it look like it just happened.
        first = self.store.set_paused("p", True)
        again = self.store.set_paused("p", True)
        self.assertEqual(first, again)

    def test_an_edit_does_not_resume_it(self):
        # Editing a manifest clears the failure backoff. Pausing is not a
        # failure, and a plugin paused for a fortnight must not come back
        # because it was tidied up in the meantime.
        self.store.set_paused("p", True)
        self.plugin.mtime = 200.0
        self.scheduler._tick()
        self.assertEqual(self.runner.submitted, [])
        self.assertIn("p", self.store.paused_plugins())


class PausingEverythingKeepsTheOnesYouChose(unittest.TestCase):
    """The bug this exists to prevent.

    Two plugins are put aside for a fortnight. A week later the machine is
    needed for something heavy, so everything is paused for an hour and then
    let go again - and the two come back with it. Nobody notices for days,
    because a plugin running is not an event.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / "test.db")
        self.addCleanup(self.store.close)

    def test_resuming_everything_leaves_the_hand_paused_alone(self):
        self.store.set_paused("set-aside", True, by="hand")
        for name in ("a", "b"):
            self.store.set_paused(name, True, by="all")

        released = self.store.resume_all()
        self.assertEqual(sorted(released), ["a", "b"])
        self.assertEqual(sorted(self.store.paused_plugins()), ["set-aside"])

    def test_a_sweep_does_not_take_over_one_already_set_aside(self):
        self.store.set_paused("set-aside", True, by="hand")
        self.store.set_paused("set-aside", True, by="all")   # swept over it
        self.assertEqual(self.store.paused_by_hand(), {"set-aside"})
        self.store.resume_all()
        self.assertIn("set-aside", self.store.paused_plugins())

    def test_resuming_one_by_hand_releases_it_whatever_paused_it(self):
        # Pressing a plugin's own control is explicit, and beats whatever
        # bookkeeping says about how it came to be paused.
        self.store.set_paused("a", True, by="all")
        self.store.set_paused("a", False)
        self.assertEqual(self.store.paused_plugins(), {})

    def test_an_older_database_gains_the_column(self):
        # Pausing shipped before this, so a database already in use has rows
        # with no 'by'. They are read as paused by hand, which is the safe
        # reading of a pause nobody can ask about any more.
        import sqlite3
        path = Path(self.tmp.name) / "old.db"
        old = sqlite3.connect(path)
        old.executescript(
            "CREATE TABLE paused (plugin_id TEXT PRIMARY KEY, since REAL NOT NULL);"
            "INSERT INTO paused VALUES ('ancient', 1.0);")
        old.commit()
        old.close()

        store = Store(path)
        self.addCleanup(store.close)
        self.assertEqual(store.paused_by_hand(), {"ancient"})
        self.assertEqual(store.resume_all(), [], "it was not swept, so it stays")
