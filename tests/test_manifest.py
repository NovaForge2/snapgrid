# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 NovaForge2
"""Reading plugin.toml: what is accepted, what is refused, and what it says."""

import tempfile
import unittest
from pathlib import Path

from snapgrid.manifest import (
    ManifestError,
    Registry,
    load_plugin,
    parse_duration,
    parse_manifest,
)

HERE = Path(".")


def parse(text: str):
    return parse_manifest(text, "example", HERE, 0.0)


class Defaults(unittest.TestCase):
    def test_minimal_manifest_needs_only_a_name_and_a_command(self):
        plugin = parse('[plugin]\nname = "X"\n[run]\ncommand = ["echo", "hi"]\n')
        self.assertEqual(plugin.name, "X")
        self.assertEqual(plugin.command, ["echo", "hi"])
        self.assertEqual(plugin.timeout, 300)
        self.assertEqual(plugin.every, 900)      # 15m
        self.assertTrue(plugin.enabled)
        self.assertIsNone(plugin.columns)        # taken from the output
        self.assertEqual(plugin.history_keep, 0)
        self.assertEqual(plugin.description, "")
        self.assertEqual(plugin.group, "")

    def test_name_falls_back_to_the_folder_name(self):
        self.assertEqual(parse('[run]\ncommand = ["x"]\n').name, "example")

    def test_every_settings(self):
        for text, expected in [("30s", 30), ("15m", 900), ("2h", 7200), ("off", None)]:
            plugin = parse(f'[plugin]\nname="X"\n[run]\ncommand=["x"]\nevery="{text}"\n')
            self.assertEqual(plugin.every, expected, text)

    def test_everything_set(self):
        plugin = parse(
            '[plugin]\n'
            'name = "Versions"\ndescription = "d"\ngroup = "g"\nenabled = false\n'
            '[run]\ncommand = ["python", "main.py"]\ntimeout = 30\nevery = "1h"\n'
            '[table]\ncolumns = ["a", "b"]\n'
            '[history]\nkeep = 5\n'
        )
        self.assertEqual(plugin.description, "d")
        self.assertEqual(plugin.group, "g")
        self.assertFalse(plugin.enabled)
        self.assertFalse(plugin.runnable)       # disabled plugins do not run
        self.assertEqual(plugin.timeout, 30)
        self.assertEqual(plugin.every, 3600)
        self.assertEqual(plugin.columns, ["a", "b"])
        self.assertEqual(plugin.history_keep, 5)


class Refusals(unittest.TestCase):
    """A bad manifest must say what is wrong with it."""

    def assert_refused(self, text: str, expected_words: str):
        with self.assertRaises(ManifestError) as caught:
            parse(text)
        self.assertIn(expected_words, str(caught.exception).lower())

    def test_command_is_required(self):
        self.assert_refused('[plugin]\nname = "X"\n', "command is required")

    def test_command_cannot_be_empty(self):
        self.assert_refused('[run]\ncommand = []\n', "cannot be empty")

    def test_command_must_be_a_list_of_text(self):
        self.assert_refused('[run]\ncommand = "python main.py"\n', "list of text")

    def test_timeout_must_be_a_positive_whole_number(self):
        self.assert_refused('[run]\ncommand=["x"]\ntimeout = 0\n', "whole number")
        self.assert_refused('[run]\ncommand=["x"]\ntimeout = "30"\n', "whole number")

    def test_every_must_look_like_a_duration(self):
        self.assert_refused('[run]\ncommand=["x"]\nevery = "15 weeks"\n', "30s")
        self.assert_refused('[run]\ncommand=["x"]\nevery = "soon"\n', "30s")

    def test_columns_cannot_be_an_empty_list(self):
        self.assert_refused('[run]\ncommand=["x"]\n[table]\ncolumns = []\n', "empty list")

    def test_history_keep_cannot_be_negative(self):
        self.assert_refused('[run]\ncommand=["x"]\n[history]\nkeep = -1\n', "0 or more")

    def test_enabled_must_be_a_boolean(self):
        self.assert_refused('[plugin]\nname="X"\nenabled = "yes"\n[run]\ncommand=["x"]\n',
                            "true or false")

    def test_invalid_toml_is_reported_as_such(self):
        self.assert_refused('[plugin\nname = "X"\n', "not valid toml")


class Durations(unittest.TestCase):
    def test_off_and_blank_mean_no_schedule(self):
        for value in ("off", "OFF", "", "never", "manual", None):
            self.assertIsNone(parse_duration(value, "x"), repr(value))

    def test_plain_numbers_are_seconds(self):
        self.assertEqual(parse_duration(45, "x"), 45)
        self.assertIsNone(parse_duration(0, "x"))


class LoadingFromDisk(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def make(self, name: str, manifest: str | None) -> Path:
        folder = self.root / name
        folder.mkdir()
        if manifest is not None:
            (folder / "plugin.toml").write_text(manifest, encoding="utf-8")
        return folder

    def test_a_folder_without_a_manifest_is_not_a_plugin(self):
        self.assertIsNone(load_plugin(self.make("notes", None)))

    def test_a_broken_manifest_is_kept_with_its_error(self):
        # Hiding it would leave the user wondering where their plugin went.
        plugin = load_plugin(self.make("broken", "[plugin\n"))
        self.assertIsNotNone(plugin)
        self.assertIn("not valid TOML", plugin.error)
        self.assertFalse(plugin.runnable)

    def test_folder_name_must_be_usable_in_a_url(self):
        plugin = load_plugin(self.make("has space", '[run]\ncommand=["x"]\n'))
        self.assertIn("folder name", plugin.error)

    def test_registry_finds_plugins_and_ignores_other_things(self):
        self.make("one", '[plugin]\nname="One"\ngroup="B"\n[run]\ncommand=["x"]\n')
        self.make("two", '[plugin]\nname="Two"\ngroup="A"\n[run]\ncommand=["x"]\n')
        self.make("notes", None)
        (self.root / ".hidden").mkdir()
        (self.root / "snapgrid.toml").write_text("", encoding="utf-8")

        registry = Registry(self.root)
        registry.scan()
        self.assertEqual([p.id for p in registry.all()], ["two", "one"])  # sorted by group
        self.assertIsNotNone(registry.get("one"))
        self.assertIsNone(registry.get("notes"))

    def test_rescanning_picks_up_a_new_folder(self):
        registry = Registry(self.root)
        registry.scan()
        self.assertEqual(registry.all(), [])
        self.make("later", '[plugin]\nname="Later"\n[run]\ncommand=["x"]\n')
        registry.scan()
        self.assertEqual([p.id for p in registry.all()], ["later"])


if __name__ == "__main__":
    unittest.main()
