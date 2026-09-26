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
        for text, expected in [("30s", 30), ("15m", 900), ("2h", 7200),
                               ("1d", 86400), ("10d", 864000), ("2w", 1209600),
                               ("off", None)]:
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

    def test_timeout_must_be_a_number_or_a_duration(self):
        self.assert_refused('[run]\ncommand=["x"]\ntimeout = 0\n', "number of seconds")
        self.assert_refused('[run]\ncommand=["x"]\ntimeout = "soon"\n', "30s")
        self.assert_refused('[run]\ncommand=["x"]\ntimeout = "off"\n', "for ever")

    def test_timeout_may_be_written_as_a_duration(self):
        for text, expected in [("300", 300), ('"30m"', 1800), ('"2h"', 7200)]:
            plugin = parse(f'[plugin]\nname="X"\n[run]\ncommand=["x"]\ntimeout = {text}\n')
            self.assertEqual(plugin.timeout, expected, text)

    def test_every_must_look_like_a_duration(self):
        self.assert_refused('[run]\ncommand=["x"]\nevery = "15 weeks"\n', "30s")
        self.assert_refused('[run]\ncommand=["x"]\nevery = "soon"\n', "30s")
        self.assert_refused('[run]\ncommand=["x"]\nevery = "10 days"\n', "10d")

    def test_a_long_interval_survives_a_restart(self):
        # Ten days between runs only works because the last finish time is
        # stored, not held in memory.
        plugin = parse('[plugin]\nname="X"\n[run]\ncommand=["x"]\nevery="10d"\n')
        self.assertEqual(plugin.every, 10 * 24 * 3600)

    def test_columns_cannot_be_an_empty_list(self):
        self.assert_refused('[run]\ncommand=["x"]\n[table]\ncolumns = []\n', "empty list")

    def test_history_keep_cannot_be_negative(self):
        self.assert_refused('[run]\ncommand=["x"]\n[history]\nkeep = -1\n', "0 or more")

    def test_enabled_must_be_a_boolean(self):
        self.assert_refused('[plugin]\nname="X"\nenabled = "yes"\n[run]\ncommand=["x"]\n',
                            "true or false")

    def test_invalid_toml_is_reported_as_such(self):
        self.assert_refused('[plugin\nname = "X"\n', "not valid toml")


class MisplacedKeys(unittest.TestCase):
    """A key in the wrong section is legal TOML and would otherwise do nothing.

    Writing timeout = 600 at the end of a file puts it in whatever section came
    last, and the plugin keeps the default while looking as though it was
    changed. Silence is the worst possible answer here.
    """

    def assert_refused(self, text: str, expected_words: str):
        with self.assertRaises(ManifestError) as caught:
            parse(text)
        self.assertIn(expected_words, str(caught.exception).lower())

    def test_timeout_under_the_wrong_section_says_where_it_belongs(self):
        self.assert_refused(
            '[plugin]\nname="X"\n[run]\ncommand=["x"]\n[history]\nkeep=20\ntimeout=600\n',
            "belongs in [run]",
        )

    def test_a_setting_in_plugin_that_belongs_in_run(self):
        self.assert_refused('[plugin]\nname="X"\nevery="1h"\n[run]\ncommand=["x"]\n',
                            "belongs in [run]")

    def test_columns_outside_its_section(self):
        self.assert_refused('[run]\ncommand=["x"]\ncolumns=["a"]\n', "belongs in [table]")

    def test_a_misspelt_key_lists_the_real_ones(self):
        self.assert_refused('[run]\ncommand=["x"]\ntimout=600\n', "not a setting")

    def test_an_unknown_section_is_refused(self):
        self.assert_refused('[plugin]\nname="X"\n[runn]\ncommand=["x"]\n',
                            "not a section")

    def test_everything_in_its_proper_place_is_accepted(self):
        plugin = parse(
            '[plugin]\nname="X"\ndescription="d"\ngroup="g"\nenabled=true\n'
            '[run]\ncommand=["x"]\ntimeout=600\nevery="1h"\n'
            '[table]\ncolumns=["a"]\n'
            '[output]\nfile="r.csv"\nsheet="S"\nfresh_for="5m"\n'
            '[history]\nkeep=5\n'
        )
        self.assertEqual(plugin.timeout, 600)


class TheKeyColumn(unittest.TestCase):
    """[table] key says which column names a row, for comparing two runs."""

    def test_it_defaults_to_empty_meaning_the_first_column(self):
        self.assertEqual(parse('[run]\ncommand=["x"]\n').key, "")

    def test_it_can_be_named(self):
        plugin = parse('[run]\ncommand=["x"]\n[table]\nkey = "repo"\n')
        self.assertEqual(plugin.key, "repo")

    def test_it_must_be_one_of_the_declared_columns(self):
        with self.assertRaises(ManifestError) as caught:
            parse('[run]\ncommand=["x"]\n[table]\ncolumns=["a","b"]\nkey="repo"\n')
        self.assertIn("not one of the columns", str(caught.exception))

    def test_it_is_not_checked_when_the_columns_are_not_declared(self):
        # The header decides the columns then, and it is not known until a run.
        self.assertEqual(parse('[run]\ncommand=["x"]\n[table]\nkey="repo"\n').key, "repo")


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
