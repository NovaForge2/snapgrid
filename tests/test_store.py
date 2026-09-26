# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 NovaForge2
"""What is kept, what is thrown away, and what counts as a change."""

import tempfile
import unittest
from pathlib import Path

from snapgrid.store import FAILED, OK, TIMEOUT, Store

COLUMNS = ["environment", "image", "version"]
ROWS_A = [["ENV1", "payments-api", "2.14.1"]]
ROWS_B = [["ENV1", "payments-api", "2.15.0"]]


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / "test.db")
        self.addCleanup(self.store.close)

    def record(self, rows, keep=10, status=OK):
        """One complete run, the way the runner does it."""
        run_id = self.store.create_run("p", "manual")
        self.store.mark_running(run_id)
        snapshot_id, changed = self.store.save_snapshot("p", COLUMNS, rows, keep)
        self.store.finish_run(run_id, "p", status, exit_code=0, snapshot_id=snapshot_id,
                              row_count=len(rows), changed=changed)
        return snapshot_id, changed


class Snapshots(StoreTest):
    def test_the_first_result_is_a_change(self):
        _, changed = self.record(ROWS_A)
        self.assertTrue(changed)
        self.assertEqual(self.store.latest_snapshot("p")["rows"], ROWS_A)

    def test_an_identical_result_does_not_make_a_second_snapshot(self):
        # This is what makes "keep 20" mean twenty real changes rather than
        # twenty copies of the same table.
        first, _ = self.record(ROWS_A)
        second, changed = self.record(ROWS_A)
        self.assertEqual(first, second)
        self.assertFalse(changed)
        self.assertEqual(len(self.store.list_snapshots("p")), 1)
        self.assertEqual(self.store.list_snapshots("p")[0]["seen_count"], 2)

    def test_a_different_result_makes_a_new_snapshot(self):
        first, _ = self.record(ROWS_A)
        second, changed = self.record(ROWS_B)
        self.assertNotEqual(first, second)
        self.assertTrue(changed)
        self.assertEqual(len(self.store.list_snapshots("p")), 2)

    def test_a_reordered_row_counts_as_a_change(self):
        self.record([["a", "b", "1"], ["c", "d", "2"]])
        _, changed = self.record([["c", "d", "2"], ["a", "b", "1"]])
        self.assertTrue(changed)

    def test_column_changes_count_too(self):
        self.record(ROWS_A)
        snapshot_id, changed = self.store.save_snapshot("p", ["a"], [["1"]], 10)
        self.assertTrue(changed)
        self.assertEqual(self.store.get_snapshot(snapshot_id)["columns"], ["a"])

    def test_only_the_last_few_are_kept(self):
        for number in range(6):
            self.record([["x", "y", str(number)]], keep=3)
        kept = self.store.list_snapshots("p")
        self.assertEqual(len(kept), 3)
        self.assertEqual(self.store.latest_snapshot("p")["rows"], [["x", "y", "5"]])

    def test_keep_zero_still_keeps_the_latest(self):
        self.record(ROWS_A, keep=0)
        self.record(ROWS_B, keep=0)
        self.assertEqual(len(self.store.list_snapshots("p")), 1)
        self.assertEqual(self.store.latest_snapshot("p")["rows"], ROWS_B)

    def test_plugins_do_not_see_each_others_snapshots(self):
        self.store.save_snapshot("one", COLUMNS, ROWS_A, 5)
        self.store.save_snapshot("two", COLUMNS, ROWS_B, 5)
        self.assertEqual(self.store.latest_snapshot("one")["rows"], ROWS_A)
        self.assertEqual(self.store.latest_snapshot("two")["rows"], ROWS_B)

    def test_nothing_recorded_yet(self):
        self.assertIsNone(self.store.latest_snapshot("never-run"))
        self.assertEqual(self.store.list_snapshots("never-run"), [])

    def test_a_failure_does_not_lose_the_last_good_table(self):
        self.record(ROWS_A)
        run_id = self.store.create_run("p", "schedule")
        self.store.finish_run(run_id, "p", FAILED, exit_code=1, error="boom")
        self.assertEqual(self.store.latest_snapshot("p")["rows"], ROWS_A)


class Runs(StoreTest):
    def test_runs_are_listed_newest_first(self):
        for _ in range(3):
            self.record(ROWS_A)
        runs = self.store.list_runs("p")
        self.assertEqual(len(runs), 3)
        self.assertGreater(runs[0]["id"], runs[-1]["id"])

    def test_old_runs_are_pruned(self):
        for _ in range(8):
            self.record(ROWS_A)
        self.store.prune_runs("p", keep=3)
        self.assertEqual(len(self.store.list_runs("p")), 3)

    def test_last_finished_run_ignores_one_still_going(self):
        self.record(ROWS_A)
        self.store.mark_running(self.store.create_run("p", "manual"))
        self.assertEqual(self.store.last_finished_run("p")["status"], OK)


class FailureCounting(StoreTest):
    def test_failures_accumulate_and_a_success_clears_them(self):
        for expected in (1, 2, 3):
            run_id = self.store.create_run("p", "schedule")
            self.store.finish_run(run_id, "p", FAILED, exit_code=1)
            self.assertEqual(self.store.get_state("p")[1], expected)

        self.record(ROWS_A)
        self.assertEqual(self.store.get_state("p")[1], 0)

    def test_a_timeout_counts_as_a_failure(self):
        run_id = self.store.create_run("p", "schedule")
        self.store.finish_run(run_id, "p", TIMEOUT)
        self.assertEqual(self.store.get_state("p")[1], 1)

    def test_last_finished_time_is_recorded(self):
        self.assertEqual(self.store.get_state("p"), (0.0, 0))
        self.record(ROWS_A)
        self.assertGreater(self.store.get_state("p")[0], 0)


if __name__ == "__main__":
    unittest.main()


class CellHistory(StoreTest):
    """Answering "when did that change?" for one value.

    Done in the store rather than in the page, because otherwise the browser
    would download every stored snapshot in full to read one value out of each.
    """

    COLUMNS = ["repo", "ENV1"]

    def save(self, rows):
        self.store.save_snapshot("p", self.COLUMNS, rows, 20)

    def history(self, repo="payments-api", column=1):
        return self.store.cell_history("p", 0, repo, column)

    def test_one_snapshot_gives_one_entry(self):
        self.save([["payments-api", "2.14.1"]])
        self.assertEqual([e["value"] for e in self.history()], ["2.14.1"])

    def test_newest_first(self):
        self.save([["payments-api", "2.14.1"]])
        self.save([["payments-api", "2.15.0"]])
        self.assertEqual([e["value"] for e in self.history()], ["2.15.0", "2.14.1"])

    def test_a_value_seen_again_is_not_repeated(self):
        # Twenty identical readings are one fact, not twenty.
        self.save([["payments-api", "2.14.1"]])
        self.save([["payments-api", "2.15.0"]])
        self.save([["payments-api", "2.15.0"], ["orders-api", "1.0.0"]])
        self.assertEqual([e["value"] for e in self.history()], ["2.15.0", "2.14.1"])

    def test_a_repeat_stretches_back_to_when_it_first_appeared(self):
        self.save([["payments-api", "2.15.0"]])
        first = self.history()[0]["since"]
        self.save([["payments-api", "2.15.0"], ["orders-api", "1.0.0"]])
        self.assertEqual(self.history()[0]["since"], first,
                         "the value has been the same since the earlier run")

    def test_runs_where_the_row_did_not_exist_are_skipped(self):
        self.save([["orders-api", "1.0.0"]])
        self.save([["payments-api", "2.15.0"], ["orders-api", "1.0.0"]])
        self.assertEqual([e["value"] for e in self.history()], ["2.15.0"])

    def test_a_snapshot_with_a_different_shape_is_skipped(self):
        self.save([["payments-api", "2.14.1"]])
        self.store.save_snapshot("p", ["repo"], [["payments-api"]], 20)
        self.assertEqual([e["value"] for e in self.history()], ["2.14.1"])

    def test_an_unknown_row_has_no_history(self):
        self.save([["payments-api", "2.14.1"]])
        self.assertEqual(self.history("never-existed"), [])
