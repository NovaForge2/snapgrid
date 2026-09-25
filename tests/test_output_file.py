# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 NovaForge2
"""Plugins that write their table to a file rather than printing it."""

import os
import time
import unittest

from snapgrid import store as store_module

from .test_running import RunningPlugins


class WritesAFile(RunningPlugins):
    def make_file_plugin(self, name, script, *, output="report.csv", timeout=30):
        return self.make_plugin(
            name, script,
            manifest_extra=f'[output]\nfile = "{output}"\n',
            timeout=timeout,
        )

    def test_the_table_is_read_from_the_file(self):
        plugin = self.make_file_plugin(
            "writes",
            'open("report.csv", "w").write("a,b\\n1,2\\n")\n',
        )
        run = self.run_now(plugin)
        self.assertEqual(run["status"], store_module.OK)
        snapshot = self.store.get_snapshot(run["snapshot_id"])
        self.assertEqual(snapshot["columns"], ["a", "b"])
        self.assertEqual(snapshot["rows"], [["1", "2"]])

    def test_whatever_it_prints_becomes_the_log(self):
        # The point of the file mode: a script may print freely, to either
        # stream, without any of it reaching the table.
        plugin = self.make_file_plugin(
            "noisy",
            'import sys\n'
            'print("INFO connecting")\n'                       # stdout
            'print("INFO 14 rows fetched", file=sys.stderr)\n'  # stderr
            'open("report.csv", "w").write("a\\n1\\n")\n',
        )
        run = self.run_now(plugin)
        self.assertEqual(run["status"], store_module.OK)
        self.assertIn("INFO connecting", run["log"])
        self.assertIn("INFO 14 rows fetched", run["log"])
        self.assertEqual(self.store.get_snapshot(run["snapshot_id"])["rows"], [["1"]])

    def test_a_file_the_run_did_not_write_is_refused(self):
        # The dangerous case: the run fails to produce anything and the file
        # from last time is still there. Showing it would be presenting old
        # data as current.
        plugin = self.make_file_plugin("stale", 'print("did nothing useful")\n')
        stale = plugin.dir / "report.csv"
        stale.write_text("a\nold value\n", encoding="utf-8")
        old = time.time() - 3600
        os.utime(stale, (old, old))

        run = self.run_now(plugin)
        self.assertEqual(run["status"], store_module.FAILED)
        self.assertIn("left over from an earlier one", run["error"])
        self.assertIsNone(self.store.latest_snapshot("stale"))

    def test_a_file_rewritten_by_this_run_is_accepted(self):
        plugin = self.make_file_plugin(
            "refreshed", 'open("report.csv", "w").write("a\\nfresh\\n")\n'
        )
        stale = plugin.dir / "report.csv"
        stale.write_text("a\nold\n", encoding="utf-8")
        old = time.time() - 3600
        os.utime(stale, (old, old))

        run = self.run_now(plugin)
        self.assertEqual(run["status"], store_module.OK)
        self.assertEqual(self.store.get_snapshot(run["snapshot_id"])["rows"], [["fresh"]])

    def test_a_missing_file_says_which_one(self):
        plugin = self.make_file_plugin("forgot", 'print("nothing written")\n')
        run = self.run_now(plugin)
        self.assertEqual(run["status"], store_module.FAILED)
        self.assertIn("report.csv", run["error"])

    def test_a_failing_plugin_is_still_a_failure(self):
        plugin = self.make_file_plugin(
            "fails",
            'import sys\nopen("report.csv", "w").write("a\\n1\\n")\nsys.exit(2)\n',
        )
        run = self.run_now(plugin)
        self.assertEqual(run["status"], store_module.FAILED)
        self.assertEqual(run["exit_code"], 2)
        self.assertIsNone(self.store.latest_snapshot("fails"))

    def test_declared_columns_are_checked_the_same_way(self):
        plugin = self.make_plugin(
            "checked",
            'open("report.csv", "w").write("x,y\\n1,2\\n")\n',
            manifest_extra='[table]\ncolumns = ["a", "b"]\n[output]\nfile = "report.csv"\n',
        )
        run = self.run_now(plugin)
        self.assertEqual(run["status"], store_module.FAILED)
        self.assertIn("does not match", run["error"])

    def test_a_file_in_a_sub_folder(self):
        plugin = self.make_file_plugin(
            "nested",
            'import os\nos.makedirs("out", exist_ok=True)\n'
            'open("out/report.csv", "w").write("a\\n1\\n")\n',
            output="out/report.csv",
        )
        run = self.run_now(plugin)
        self.assertEqual(run["status"], store_module.OK)

    def test_secrets_in_the_file_are_masked(self):
        from snapgrid.secrets_store import encrypt, load_key
        os.environ["SNAPGRID_KEY_FILE"] = str(self.root / "key")
        self.addCleanup(os.environ.pop, "SNAPGRID_KEY_FILE", None)
        key = load_key(create=True)

        plugin = self.make_plugin(
            "leaky-file",
            'import os\nopen("report.csv", "w").write("value\\n" + os.environ["TOKEN"] + "\\n")\n',
            manifest_extra='[output]\nfile = "report.csv"\n',
            env=f"TOKEN={encrypt('hunter2', key)}\n",
        )
        run = self.run_now(plugin)
        self.assertEqual(run["status"], store_module.OK)
        self.assertEqual(self.store.get_snapshot(run["snapshot_id"])["rows"], [["****"]])


if __name__ == "__main__":
    unittest.main()


class NoScriptAtAll(RunningPlugins):
    """A folder holding a manifest and a file, with nothing to run."""

    def make_static(self, name, filename, contents, extra=""):
        folder = self.config.plugins_dir / name
        folder.mkdir(parents=True)
        if isinstance(contents, bytes):
            (folder / filename).write_bytes(contents)
        else:
            (folder / filename).write_text(contents, encoding="utf-8")
        (folder / "plugin.toml").write_text(
            f'[plugin]\nname = "{name}"\n[run]\nevery = "off"\n'
            f'[output]\nfile = "{filename}"\n{extra}',
            encoding="utf-8",
        )
        self.registry.scan()
        return self.registry.get(name)

    def test_a_csv_file_on_its_own_becomes_a_table(self):
        plugin = self.make_static("just-a-file", "data.csv", "a,b\n1,2\n3,4\n")
        run = self.run_now(plugin)
        self.assertEqual(run["status"], store_module.OK)
        snapshot = self.store.get_snapshot(run["snapshot_id"])
        self.assertEqual(snapshot["columns"], ["a", "b"])
        self.assertEqual(snapshot["rows"], [["1", "2"], ["3", "4"]])

    def test_editing_the_file_shows_up_on_the_next_run(self):
        plugin = self.make_static("editable", "data.csv", "a\n1\n")
        self.run_now(plugin)
        (plugin.dir / "data.csv").write_text("a\n2\n", encoding="utf-8")
        run = self.run_now(plugin)
        self.assertEqual(self.store.get_snapshot(run["snapshot_id"])["rows"], [["2"]])
        self.assertTrue(run["changed"])

    def test_an_unchanged_file_is_not_a_new_snapshot(self):
        plugin = self.make_static("unchanged", "data.csv", "a\n1\n")
        self.run_now(plugin)
        run = self.run_now(plugin)
        self.assertFalse(run["changed"])
        self.assertEqual(len(self.store.list_snapshots("unchanged")), 1)

    def test_no_staleness_complaint_when_nothing_ran(self):
        # The file is old by definition - nobody wrote it during this run.
        plugin = self.make_static("old-file", "data.csv", "a\n1\n")
        import os, time
        old = time.time() - 86400
        os.utime(plugin.dir / "data.csv", (old, old))
        self.assertEqual(self.run_now(plugin)["status"], store_module.OK)

    def test_a_missing_file_is_a_clear_failure(self):
        plugin = self.make_static("gone", "data.csv", "a\n1\n")
        (plugin.dir / "data.csv").unlink()
        run = self.run_now(plugin)
        self.assertEqual(run["status"], store_module.FAILED)
        self.assertIn("data.csv", run["error"])


class Spreadsheets(RunningPlugins):
    def build_workbook(self, path, rows):
        """A minimal real .xlsx, same shape a spreadsheet program writes."""
        import zipfile
        from tests.test_spreadsheet import (
            CONTENT_TYPES, ROOT_RELS, sheet_xml, workbook_rels, workbook_xml,
        )
        cells = []
        for number, row in enumerate(rows, start=1):
            cells.append([
                f'<c r="{chr(ord("A") + i)}{number}" t="inlineStr"><is><t>{v}</t></is></c>'
                for i, v in enumerate(row)
            ])
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("[Content_Types].xml", CONTENT_TYPES)
            archive.writestr("_rels/.rels", ROOT_RELS)
            archive.writestr("xl/workbook.xml", workbook_xml(["Sheet1"]))
            archive.writestr("xl/_rels/workbook.xml.rels", workbook_rels(1))
            archive.writestr("xl/worksheets/sheet1.xml", sheet_xml(cells))

    def test_a_spreadsheet_on_its_own_becomes_a_table(self):
        folder = self.config.plugins_dir / "from-excel"
        folder.mkdir(parents=True)
        self.build_workbook(folder / "report.xlsx",
                            [["service", "owner"], ["payments-api", "Falcon"]])
        (folder / "plugin.toml").write_text(
            '[plugin]\nname = "from-excel"\n[run]\nevery = "off"\n'
            '[output]\nfile = "report.xlsx"\n', encoding="utf-8")
        self.registry.scan()

        run = self.run_now(self.registry.get("from-excel"))
        self.assertEqual(run["status"], store_module.OK)
        snapshot = self.store.get_snapshot(run["snapshot_id"])
        self.assertEqual(snapshot["columns"], ["service", "owner"])
        self.assertEqual(snapshot["rows"], [["payments-api", "Falcon"]])

    def test_a_script_may_write_a_spreadsheet_too(self):
        folder = self.config.plugins_dir / "writes-excel"
        folder.mkdir(parents=True)
        self.build_workbook(folder / "out.xlsx", [["a"], ["1"]])
        # The script only touches the file so it counts as written by this run.
        (folder / "main.py").write_text(
            'import os, time\nos.utime("out.xlsx", None)\nprint("done")\n', encoding="utf-8")
        (folder / "plugin.toml").write_text(
            '[plugin]\nname = "writes-excel"\n'
            '[run]\ncommand = ["python", "main.py"]\nevery = "off"\n'
            '[output]\nfile = "out.xlsx"\n', encoding="utf-8")
        self.registry.scan()

        run = self.run_now(self.registry.get("writes-excel"))
        self.assertEqual(run["status"], store_module.OK)
        self.assertEqual(self.store.get_snapshot(run["snapshot_id"])["rows"], [["1"]])
        self.assertIn("done", run["log"])


class FreshEnoughToSkip(RunningPlugins):
    """[output] fresh_for - do not run the plugin if the file is recent."""

    def make_counting_plugin(self, name, fresh_for="1h"):
        # Appends a line every time it actually runs, so the test can tell
        # whether it ran at all.
        return self.make_plugin(
            name,
            'from pathlib import Path\n'
            'count = Path("runs.txt")\n'
            'count.write_text(str(int(count.read_text() or 0) + 1) if count.exists() else "1")\n'
            'Path("report.csv").write_text("a\\n" + count.read_text() + "\\n")\n',
            manifest_extra=f'[output]\nfile = "report.csv"\nfresh_for = "{fresh_for}"\n',
        )

    def runs_so_far(self, plugin):
        counter = plugin.dir / "runs.txt"
        return int(counter.read_text()) if counter.exists() else 0

    def test_a_fresh_file_is_used_and_the_plugin_is_not_run(self):
        plugin = self.make_counting_plugin("cached")
        self.run_now(plugin)                       # manual, so it runs
        self.assertEqual(self.runs_so_far(plugin), 1)

        run_id = self.runner.submit(plugin, "schedule")
        self.wait_for(run_id)
        self.assertEqual(self.runs_so_far(plugin), 1, "it ran again despite a fresh file")
        run = self.store.get_run(run_id)
        self.assertEqual(run["status"], store_module.OK)
        self.assertIn("was not run", run["log"])

    def test_an_old_file_means_the_plugin_runs(self):
        plugin = self.make_counting_plugin("expired", fresh_for="30s")
        self.run_now(plugin)
        self.assertEqual(self.runs_so_far(plugin), 1)

        old = time.time() - 600
        os.utime(plugin.dir / "report.csv", (old, old))
        run_id = self.runner.submit(plugin, "schedule")
        self.wait_for(run_id)
        self.assertEqual(self.runs_so_far(plugin), 2)

    def test_refresh_always_runs_it(self):
        # Pressing Refresh means wanting new data, not the file again.
        plugin = self.make_counting_plugin("forced")
        self.run_now(plugin)
        self.run_now(plugin)
        self.assertEqual(self.runs_so_far(plugin), 2)

    def test_a_missing_file_means_the_plugin_runs(self):
        plugin = self.make_counting_plugin("absent")
        self.run_now(plugin)
        (plugin.dir / "report.csv").unlink()
        run_id = self.runner.submit(plugin, "schedule")
        self.wait_for(run_id)
        self.assertEqual(self.runs_so_far(plugin), 2)

    def test_an_unreadable_file_means_the_plugin_runs(self):
        plugin = self.make_counting_plugin("broken")
        self.run_now(plugin)
        (plugin.dir / "report.csv").write_text("", encoding="utf-8")
        run_id = self.runner.submit(plugin, "schedule")
        self.wait_for(run_id)
        self.assertEqual(self.runs_so_far(plugin), 2)

    def test_fresh_for_without_a_file_is_refused(self):
        folder = self.config.plugins_dir / "no-file"
        folder.mkdir(parents=True)
        (folder / "plugin.toml").write_text(
            '[plugin]\nname = "no-file"\n[run]\ncommand = ["x"]\n'
            '[output]\nfresh_for = "1h"\n', encoding="utf-8")
        self.registry.scan()
        self.assertIn("only means something with", self.registry.get("no-file").error)
