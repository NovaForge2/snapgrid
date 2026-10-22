# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 NovaForge2
"""Explicit workspaces own their database, log, and running-server record."""

import argparse
import contextlib
import io
import os
import shlex
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from snapgrid_core import __main__ as cli
from snapgrid_core import settings
from snapgrid_core.config import Config


class WorkspaceStorage(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.plugins = self.root / "my plugins"

    def test_all_server_files_belong_to_the_selected_plugins_root(self):
        config = Config(self.plugins)
        self.assertEqual(config.data_dir, self.plugins / ".snapgrid")
        self.assertEqual(config.db_path, self.plugins / ".snapgrid" / "snapgrid.db")
        self.assertEqual(config.log_file.parent, config.data_dir)
        self.assertEqual(config.state_file.parent, config.data_dir)
        config.prepare()
        self.assertTrue(config.data_dir.is_dir())
        self.assertFalse((self.root / ".snapgrid").exists())

    def test_relative_paths_use_the_callers_directory(self):
        with contextlib.chdir(self.root):
            config = Config(Path("my plugins"))
        self.assertEqual(config.plugins_dir, self.plugins)
        self.assertEqual(config.db_path, self.plugins / ".snapgrid" / "snapgrid.db")

    def test_home_paths_are_expanded(self):
        with mock.patch.dict(os.environ, HOME=str(self.root), USERPROFILE=str(self.root)):
            config = Config(Path("~/my plugins"))
        self.assertEqual(config.plugins_dir, self.plugins)

    def test_a_second_workspace_gets_a_separate_database(self):
        first = Config(self.plugins)
        second = Config(self.root / "other plugins")
        self.assertNotEqual(first.db_path, second.db_path)

    def test_command_hints_quote_workspace_paths_with_spaces(self):
        command = cli.command_hint(Config(self.plugins), "stop")
        self.assertEqual(shlex.split(command),
                         ["./server.py", "--dir", self.plugins.as_posix(), "stop"])

    def test_an_independent_data_directory_is_no_longer_a_config_option(self):
        with self.assertRaises(TypeError):
            Config(self.plugins, data_dir=self.root / "elsewhere")

    def test_legacy_settings_cannot_override_the_explicit_root(self):
        path = self.root / "snapgrid.toml"
        path.write_text('[server]\nport = 9011\ndir = "old-plugins"\n'
                        'data = "old-data"\ndb_path = "old.db"\n', encoding="utf-8")
        args = cli.build_parser().parse_args(["serve", "--dir", str(self.plugins)])
        with mock.patch.object(settings, "SETTINGS_PATH", path):
            config = cli.config_from(args, require_dir=True)
        self.assertEqual(config.port, 9011)
        self.assertEqual(config.db_path, self.plugins / ".snapgrid" / "snapgrid.db")

    def test_a_symlink_cannot_redirect_server_writes_outside_the_root(self):
        self.plugins.mkdir()
        outside = self.root / "old-data"
        outside.mkdir()
        names = (".snapgrid", "snapgrid.db", "snapgrid.db-wal", "snapgrid.db-shm",
                 "snapgrid.db-journal", "server.log", "server.json")
        for name in names:
            with self.subTest(name=name):
                config = Config(self.plugins)
                link = (config.data_dir if name == ".snapgrid"
                        else config.data_dir / name)
                if name != ".snapgrid":
                    config.data_dir.mkdir(exist_ok=True)
                try:
                    link.symlink_to(outside if name == ".snapgrid" else outside / name,
                                    target_is_directory=name == ".snapgrid")
                except (OSError, NotImplementedError) as exc:
                    self.skipTest(f"symlinks are unavailable: {exc}")
                try:
                    with self.assertRaisesRegex(ValueError, "outside --dir"):
                        config.prepare()
                    self.assertEqual(list(outside.iterdir()), [])
                finally:
                    link.unlink()

    def test_an_external_symlink_fails_startup_without_a_traceback(self):
        self.plugins.mkdir()
        config = Config(self.plugins)
        try:
            config.data_dir.symlink_to(self.root / "outside", target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"symlinks are unavailable: {exc}")
        with self.assertRaisesRegex(SystemExit, "cannot prepare plugins folder"):
            cli.command_serve(argparse.Namespace(dir=self.plugins, open=False))
        self.assertFalse((self.root / "outside").exists())

    def test_foreground_start_creates_database_only_in_the_selected_root(self):
        legacy = self.root / "installation" / "plugins"
        old_database = legacy / ".snapgrid" / "snapgrid.db"
        old_database.parent.mkdir(parents=True)
        old_database.write_bytes(b"old database must remain untouched")
        args = argparse.Namespace(dir=self.plugins, open=False)
        httpd = mock.Mock()
        httpd.serve_forever.side_effect = KeyboardInterrupt
        with mock.patch.object(cli, "DEFAULT_PLUGINS_DIR", legacy), \
             mock.patch.object(cli, "require_port"), \
             mock.patch.object(cli, "Runner"), \
             mock.patch.object(cli, "Scheduler"), \
             mock.patch.object(cli, "make_server", return_value=httpd), \
             mock.patch.object(cli.signal, "signal"), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.command_serve(args), 0)
        database = self.plugins / ".snapgrid" / "snapgrid.db"
        self.assertTrue(database.is_file())
        with contextlib.closing(sqlite3.connect(str(database))) as connection:
            tables = {row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertTrue({"runs", "snapshots", "state"}.issubset(tables))
        self.assertEqual(old_database.read_bytes(), b"old database must remain untouched")
        self.assertFalse((self.root / ".snapgrid").exists())
        self.assertFalse((self.plugins / ".snapgrid" / "server.json").exists())

    def test_background_child_gets_an_absolute_dir_and_no_data_override(self):
        args = argparse.Namespace(dir=Path("my plugins"), open=False)
        state = {"url": "http://127.0.0.1:8765"}
        with contextlib.chdir(self.root), \
             mock.patch.object(cli, "running_state", side_effect=[None, state]), \
             mock.patch.object(cli.subprocess, "Popen") as launch, \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.command_start(args), 0)
        command = launch.call_args.args[0]
        self.assertEqual(command[command.index("--dir") + 1], str(self.plugins))
        self.assertNotIn("--data", command)
        self.assertTrue((self.plugins / ".snapgrid" / "server.log").is_file())
        self.assertFalse((self.root / ".snapgrid").exists())


class ExplicitStartupDirectory(unittest.TestCase):
    def parse(self, argv):
        return cli.build_parser().parse_args(cli.normalise(argv))

    def test_every_startup_form_requires_dir_before_any_work(self):
        for argv in ([], ["start"], ["serve"], ["--port", "9000"],
                     ["start", "--open"], ["serve", "--dir", ""], ["--dir="]):
            with self.subTest(argv=argv), \
                 mock.patch.object(cli, "Config") as config, \
                 mock.patch.object(cli.subprocess, "Popen") as launch, \
                 contextlib.redirect_stderr(io.StringIO()) as error:
                with self.assertRaises(SystemExit) as caught:
                    cli.main(argv)
                self.assertEqual(caught.exception.code, 2)
                self.assertIn("--dir", error.getvalue())
                config.assert_not_called()
                launch.assert_not_called()

    def test_start_commands_cannot_bypass_the_parser_requirement(self):
        for command in (cli.command_start, cli.command_serve):
            with self.subTest(command=command.__name__), \
                 mock.patch.object(cli, "Config") as config:
                with self.assertRaisesRegex(SystemExit, "--dir is required"):
                    command(argparse.Namespace())
                config.assert_not_called()

    def test_dir_works_before_or_after_the_command_and_with_equals(self):
        for argv in (["--dir", "my plugins", "serve"],
                     ["serve", "--dir", "my plugins"],
                     ["--dir=my plugins", "serve"], ["--dir", "my plugins"]):
            with self.subTest(argv=argv):
                self.assertEqual(self.parse(argv).dir, Path("my plugins"))

    def test_a_folder_named_stop_is_still_a_folder(self):
        parsed = self.parse(["--dir", "stop"])
        self.assertEqual(parsed.command, cli.DEFAULT_COMMAND)
        self.assertEqual(parsed.dir, Path("stop"))

    def test_data_override_is_rejected_rather_than_silently_relocated(self):
        for command in ("start", "serve", "stop", "status"):
            with self.subTest(command=command), \
                 contextlib.redirect_stderr(io.StringIO()) as error:
                with self.assertRaises(SystemExit) as caught:
                    self.parse([command, "--dir", "plugins", "--data", "elsewhere"])
                self.assertEqual(caught.exception.code, 2)
                self.assertIn("--data", error.getvalue())

    def test_stale_programmatic_data_override_is_rejected_too(self):
        with self.assertRaisesRegex(SystemExit, "--data is no longer supported"):
            cli.config_from(argparse.Namespace(dir="plugins", data="elsewhere"))

    def test_read_only_commands_and_validation_do_not_require_dir(self):
        self.assertEqual(self.parse(["stop"]).command, "stop")
        self.assertEqual(self.parse(["status"]).command, "status")
        self.assertEqual(self.parse(["validate", "my-plugin"]).path, Path("my-plugin"))

    def test_help_and_version_work_without_dir(self):
        for argv in (["--help"], ["start", "--help"], ["serve", "--help"], ["--version"]):
            with self.subTest(argv=argv), contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(SystemExit) as caught:
                    cli.main(argv)
                self.assertEqual(caught.exception.code, 0)

    def test_even_the_old_default_workspace_is_explicit_in_command_hints(self):
        hint = cli.command_hint(Config(cli.DEFAULT_PLUGINS_DIR), "start")
        self.assertIn("--dir", hint)
        self.assertTrue(hint.endswith(" start"))


if __name__ == "__main__":
    unittest.main()
