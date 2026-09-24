# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 NovaForge2
"""Running real plugins: what succeeds, what fails, and what it says about it.

These start actual processes, so they are slower than the rest, but they are
the tests that would have caught most of what went wrong in practice.
"""

import os
import tempfile
import time
import unittest
from pathlib import Path

from snapgrid import store as store_module
from snapgrid.config import Config
from snapgrid.manifest import Registry
from snapgrid.runner import Runner, resolve_command
from snapgrid.secrets_store import encrypt, load_key
from snapgrid.store import Store


class RunningPlugins(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.config = Config(plugins_dir=self.root / "plugins")
        self.config.prepare()
        self.store = Store(self.config.db_path)
        self.addCleanup(self.store.close)
        self.registry = Registry(self.config.plugins_dir)
        self.runner = Runner(self.store, self.registry, self.config)
        self.runner.start()
        self.addCleanup(self.runner.stop)

    def make_plugin(self, name, script, *, manifest_extra="", env=None, timeout=30):
        folder = self.config.plugins_dir / name
        folder.mkdir(parents=True)
        (folder / "main.py").write_text(script, encoding="utf-8")
        (folder / "plugin.toml").write_text(
            f'[plugin]\nname = "{name}"\n'
            f'[run]\ncommand = ["python", "main.py"]\ntimeout = {timeout}\nevery = "off"\n'
            f"{manifest_extra}",
            encoding="utf-8",
        )
        if env is not None:
            (folder / ".env").write_text(env, encoding="utf-8")
        self.registry.scan()
        return self.registry.get(name)

    def run_now(self, plugin, seconds=30):
        """Run it and wait for the result, the way the page does."""
        run_id = self.runner.submit(plugin, "manual")
        deadline = time.time() + seconds
        while time.time() < deadline:
            run = self.store.get_run(run_id)
            if run and run["finished_at"]:
                return run
            time.sleep(0.05)
        self.fail(f"plugin {plugin.id} did not finish within {seconds}s")


class Success(RunningPlugins):
    def test_a_plugin_that_prints_a_table(self):
        plugin = self.make_plugin("good", 'print("a,b")\nprint("1,2")\n')
        run = self.run_now(plugin)
        self.assertEqual(run["status"], store_module.OK)
        self.assertEqual(run["exit_code"], 0)
        self.assertEqual(run["row_count"], 1)
        snapshot = self.store.get_snapshot(run["snapshot_id"])
        self.assertEqual(snapshot["columns"], ["a", "b"])
        self.assertEqual(snapshot["rows"], [["1", "2"]])

    def test_standard_error_is_kept_as_the_log(self):
        plugin = self.make_plugin(
            "logs", 'import sys\nprint("working", file=sys.stderr)\nprint("a")\nprint("1")\n'
        )
        run = self.run_now(plugin)
        self.assertEqual(run["status"], store_module.OK)
        self.assertIn("working", run["log"])

    def test_the_plugin_folder_is_the_working_directory(self):
        plugin = self.make_plugin(
            "cwd", 'print("name")\nprint(open("data.txt").read().strip())\n'
        )
        (plugin.dir / "data.txt").write_text("found me", encoding="utf-8")
        run = self.run_now(plugin)
        self.assertEqual(run["status"], store_module.OK)
        self.assertEqual(self.store.get_snapshot(run["snapshot_id"])["rows"], [["found me"]])

    def test_non_ascii_output(self):
        plugin = self.make_plugin(
            "unicode",
            'import sys\nsys.stdout.reconfigure(encoding="utf-8")\n'
            'print("name")\nprint("José")\nprint("naïve")\n',
        )
        run = self.run_now(plugin)
        self.assertEqual(run["status"], store_module.OK)
        self.assertEqual(
            self.store.get_snapshot(run["snapshot_id"])["rows"], [["José"], ["naïve"]]
        )

    def test_a_plugin_with_no_rows_is_still_a_success(self):
        plugin = self.make_plugin("empty", 'print("a,b")\n')
        run = self.run_now(plugin)
        self.assertEqual(run["status"], store_module.OK)
        self.assertEqual(run["row_count"], 0)


class Failure(RunningPlugins):
    def test_a_non_zero_exit_is_a_failure_and_the_last_line_is_shown(self):
        plugin = self.make_plugin(
            "fails",
            'import sys\nprint("cannot reach the cluster", file=sys.stderr)\nsys.exit(3)\n',
        )
        run = self.run_now(plugin)
        self.assertEqual(run["status"], store_module.FAILED)
        self.assertEqual(run["exit_code"], 3)
        self.assertIn("cannot reach the cluster", run["error"])

    def test_output_that_is_not_a_table(self):
        plugin = self.make_plugin("silent", 'import sys\nprint("busy", file=sys.stderr)\n')
        run = self.run_now(plugin)
        self.assertEqual(run["status"], store_module.FAILED)
        self.assertIn("printed nothing", run["error"])

    def test_a_header_that_does_not_match_the_manifest(self):
        plugin = self.make_plugin(
            "mismatch", 'print("x,y")\nprint("1,2")\n',
            manifest_extra='[table]\ncolumns = ["a", "b"]\n',
        )
        run = self.run_now(plugin)
        self.assertEqual(run["status"], store_module.FAILED)
        self.assertIn("does not match", run["error"])

    def test_a_program_that_does_not_exist(self):
        folder = self.config.plugins_dir / "missing"
        folder.mkdir(parents=True)
        (folder / "plugin.toml").write_text(
            '[plugin]\nname = "missing"\n'
            '[run]\ncommand = ["definitely-not-a-program-xyz"]\nevery = "off"\n',
            encoding="utf-8",
        )
        self.registry.scan()
        run = self.run_now(self.registry.get("missing"))
        self.assertEqual(run["status"], store_module.FAILED)
        self.assertIn("no such program", run["error"])

    def test_a_failure_leaves_the_previous_result_in_place(self):
        plugin = self.make_plugin("flaky", 'print("a")\nprint("1")\n')
        self.run_now(plugin)
        (plugin.dir / "main.py").write_text("import sys\nsys.exit(1)\n", encoding="utf-8")
        run = self.run_now(plugin)
        self.assertEqual(run["status"], store_module.FAILED)
        self.assertEqual(self.store.latest_snapshot("flaky")["rows"], [["1"]])

    def test_a_plugin_that_never_finishes_is_stopped(self):
        plugin = self.make_plugin("slow", "import time\ntime.sleep(60)\n", timeout=1)
        started = time.time()
        run = self.run_now(plugin, seconds=20)
        self.assertEqual(run["status"], store_module.TIMEOUT)
        self.assertIn("1 seconds", run["error"])
        self.assertLess(time.time() - started, 15)


class Secrets(RunningPlugins):
    def setUp(self):
        super().setUp()
        key_file = self.root / "key"
        os.environ["SNAPGRID_KEY_FILE"] = str(key_file)
        self.addCleanup(os.environ.pop, "SNAPGRID_KEY_FILE", None)
        self.key = load_key(create=True)

    def test_an_encrypted_value_reaches_the_plugin_decrypted(self):
        plugin = self.make_plugin(
            "secret",
            'import os\nprint("name,length")\n'
            'print(f"password,{len(os.environ[\'PASSWORD\'])}")\n',
            env=f"PASSWORD={encrypt('hunter2', self.key)}\n",
        )
        run = self.run_now(plugin)
        self.assertEqual(run["status"], store_module.OK)
        self.assertEqual(
            self.store.get_snapshot(run["snapshot_id"])["rows"], [["password", "7"]]
        )

    def test_a_secret_printed_by_the_plugin_is_masked_before_it_is_stored(self):
        # A script logging its own command line must not put a password into
        # the database for ever.
        plugin = self.make_plugin(
            "leaky",
            'import os, sys\n'
            'print(f"logging in with {os.environ[\'PASSWORD\']}", file=sys.stderr)\n'
            'print("a")\nprint("1")\n',
            env=f"PASSWORD={encrypt('hunter2', self.key)}\n",
        )
        run = self.run_now(plugin)
        self.assertNotIn("hunter2", run["log"])
        self.assertIn("****", run["log"])

    def test_a_secret_printed_into_the_table_is_masked_too(self):
        plugin = self.make_plugin(
            "leaky-table",
            'import os\nprint("value")\nprint(os.environ["PASSWORD"])\n',
            env=f"PASSWORD={encrypt('hunter2', self.key)}\n",
        )
        run = self.run_now(plugin)
        rows = self.store.get_snapshot(run["snapshot_id"])["rows"]
        self.assertEqual(rows, [["****"]])

    def test_a_key_that_cannot_decrypt_stops_the_run_with_a_clear_message(self):
        plugin = self.make_plugin(
            "bad-key", 'print("a")\nprint("1")\n',
            env="PASSWORD=enc:bm90IGEgcmVhbCB0b2tlbiBhdCBhbGwsIHJlYWxseQ==\n",
        )
        run = self.run_now(plugin)
        self.assertEqual(run["status"], store_module.FAILED)
        self.assertIn("PASSWORD", run["error"])


class Queueing(RunningPlugins):
    def test_one_plugin_does_not_run_twice_at_once(self):
        plugin = self.make_plugin("busy", 'import time\ntime.sleep(2)\nprint("a")\nprint("1")\n')
        first = self.runner.submit(plugin, "manual")
        second = self.runner.submit(plugin, "manual")
        self.assertEqual(first, second)
        self.run_now(plugin)

    def test_a_queued_run_can_be_cancelled_before_it_starts(self):
        plugin = self.make_plugin("later", 'import time\ntime.sleep(5)\n')
        run_id = self.runner.submit(plugin, "schedule")
        self.assertTrue(self.runner.cancel(run_id))
        deadline = time.time() + 10
        while time.time() < deadline:
            run = self.store.get_run(run_id)
            if run["status"] == store_module.CANCELLED:
                return
            time.sleep(0.05)
        self.fail("the run was not recorded as cancelled")


class InterpreterNames(unittest.TestCase):
    def test_a_bare_python_means_the_one_running_snapgrid(self):
        import sys
        self.assertEqual(resolve_command(["python", "x.py"]), [sys.executable, "x.py"])
        self.assertEqual(resolve_command(["python3", "x.py"]), [sys.executable, "x.py"])

    def test_anything_else_is_left_alone(self):
        self.assertEqual(resolve_command(["bash", "run.sh"]), ["bash", "run.sh"])
        self.assertEqual(
            resolve_command(["/usr/bin/python3", "x.py"]), ["/usr/bin/python3", "x.py"]
        )


if __name__ == "__main__":
    unittest.main()
