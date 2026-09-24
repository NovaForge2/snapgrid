# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 NovaForge2
"""When a plugin is due, and how a broken one is slowed down."""

import unittest

from snapgrid.config import BACKOFF_MAX_SECONDS
from snapgrid.scheduler import interval_for


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


if __name__ == "__main__":
    unittest.main()
