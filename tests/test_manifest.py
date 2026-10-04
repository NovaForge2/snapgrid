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
    shade_for,
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


class Colours(unittest.TestCase):
    """[colour.<column>] - a value a plugin wants shown in a colour."""

    BASE = '[plugin]\nname = "X"\n[run]\ncommand = ["x"]\n'

    def test_a_manifest_without_colours_has_none(self):
        self.assertEqual(parse(self.BASE).colours, {})

    def test_values_are_matched_without_case(self):
        plugin = parse(self.BASE + '[colour.status]\nOK = "green"\n"Expiring Soon" = "amber"\n')
        # Stored lowered, because the match happens on a lowered value too.
        self.assertEqual(plugin.colours, {"status": [
            {"is": "ok", "colour": "green"},
            {"is": "expiring soon", "colour": "amber"},
        ]})

    def test_every_colour_there_is(self):
        lines = "".join(f'v{n} = "{name}"\n' for n, name
                        in enumerate(("red", "amber", "green", "blue", "grey")))
        plugin = parse(self.BASE + "[colour.status]\n" + lines)
        self.assertEqual(sorted(rule["colour"] for rule in plugin.colours["status"]),
                         ["amber", "blue", "green", "grey", "red"])

    def test_rules_keep_the_order_they_were_written_in(self):
        # The first match wins, so the order in the file is the meaning.
        plugin = parse(self.BASE + '[colour.n]\n"> 90" = "red"\n"> 80" = "amber"\n')
        self.assertEqual([rule["n"] for rule in plugin.colours["n"]], [90.0, 80.0])


class Thresholds(unittest.TestCase):
    """A comparison against a number, rather than a value matched whole."""

    BASE = Colours.BASE
    DISK = '[colour.used]\n"> 90" = "red"\n"> 80" = "amber"\n'

    def rules(self, written=None):
        return parse(self.BASE + (written or self.DISK)).colours["used"]

    def test_the_first_rule_that_matches_wins(self):
        rules = self.rules()
        self.assertEqual(shade_for(rules, "95"), "red")
        self.assertEqual(shade_for(rules, "85"), "amber")
        self.assertEqual(shade_for(rules, "70"), "")

    def test_the_boundary_is_not_included_by_a_strict_comparison(self):
        self.assertEqual(shade_for(self.rules(), "90"), "amber")

    def test_a_blank_cell_is_not_zero(self):
        # float("") raises, but a careless implementation reads it as 0 and
        # paints every empty cell in a column with "< 10" on it.
        rules = self.rules('[colour.used]\n"< 10" = "red"\n')
        for blank in ("", "   "):
            self.assertEqual(shade_for(rules, blank), "")

    def test_a_word_is_not_a_number(self):
        self.assertEqual(shade_for(self.rules(), "n/a"), "")

    def test_decimals_and_negatives(self):
        self.assertEqual(shade_for(self.rules(), "90.5"), "red")
        self.assertEqual(shade_for(self.rules('[colour.used]\n"< 0" = "red"\n'), "-3"), "red")

    def test_every_operator(self):
        for written, value in (("> 5", "6"), (">= 5", "5"), ("< 5", "4"),
                               ("<= 5", "5"), ("= 5", "5"), ("!= 5", "6")):
            rules = self.rules(f'[colour.used]\n"{written}" = "red"\n')
            self.assertEqual(shade_for(rules, value), "red", written)

    def test_words_and_numbers_in_one_column(self):
        rules = self.rules('[colour.used]\nunknown = "grey"\n"> 90" = "red"\n')
        self.assertEqual(shade_for(rules, "unknown"), "grey")
        self.assertEqual(shade_for(rules, "95"), "red")

    def test_something_that_starts_like_a_comparison_but_is_not_one(self):
        with self.assertRaises(ManifestError) as caught:
            parse(self.BASE + '[colour.used]\n"> eighty" = "red"\n')
        self.assertIn("starts like a comparison", str(caught.exception))

    def test_the_spacing_around_the_operator_does_not_matter(self):
        for written in (">90", "> 90", ">  90"):
            rules = self.rules(f'[colour.used]\n"{written}" = "red"\n')
            self.assertEqual(shade_for(rules, "95"), "red", written)

    def test_no_rules_means_no_colour(self):
        self.assertEqual(shade_for([], "95"), "")
        self.assertEqual(shade_for(None, "95"), "")

    def test_a_colour_that_does_not_exist_is_refused_and_lists_the_ones_that_do(self):
        with self.assertRaises(ManifestError) as caught:
            parse(self.BASE + '[colour.status]\nok = "purple"\n')
        self.assertIn("purple", str(caught.exception))
        self.assertIn("red, amber, green, blue, grey", str(caught.exception))

    def test_the_american_spelling_says_where_to_look(self):
        with self.assertRaises(ManifestError) as caught:
            parse(self.BASE + '[color.status]\nok = "green"\n')
        self.assertIn("[colour]", str(caught.exception))

    def test_a_colour_for_a_column_that_is_not_declared_is_refused(self):
        # Only catchable when the columns are declared; otherwise the result
        # decides them and this cannot be known until the plugin has run.
        with self.assertRaises(ManifestError) as caught:
            parse(self.BASE + '[table]\ncolumns = ["a", "b"]\n[colour.c]\nok = "green"\n')
        self.assertIn("a, b", str(caught.exception))

    def test_a_colour_for_an_undeclared_column_is_allowed(self):
        plugin = parse(self.BASE + '[colour.status]\nok = "green"\n')
        self.assertIn("status", plugin.colours)

    def test_a_column_mapping_has_to_be_a_section(self):
        with self.assertRaises(ManifestError) as caught:
            parse(self.BASE + '[colour]\nstatus = "green"\n')
        self.assertIn("[colour.status]", str(caught.exception))

    def test_an_empty_mapping_is_dropped_rather_than_kept(self):
        self.assertEqual(parse(self.BASE + "[colour.status]\n").colours, {})


class TheSameAnswerAsTheBrowser(unittest.TestCase):
    """shade_for and web/colour.js shadeFor have to agree on every case.

    A workbook that colours different cells from the screen it came from is
    worse than one with no colour at all. The cases below are the ones the two
    languages disagree about naturally, and tests/colour.test.js runs the
    identical list.
    """

    RULES = [{"op": "!=", "n": 200, "colour": "red"}]

    def test_not_a_real_number_is_not_compared(self):
        # float() takes all of these; a browser's Number() does not treat them
        # as numbers to compare against.
        for odd in ("NaN", "nan", "inf", "-inf", "Infinity"):
            self.assertEqual(shade_for(self.RULES, odd), "", odd)

    def test_a_real_number_still_counts(self):
        self.assertEqual(shade_for(self.RULES, "503"), "red")

    def test_blank_and_space_are_not_zero(self):
        for blank in ("", "   ", None):
            self.assertEqual(shade_for([{"op": "<", "n": 10, "colour": "red"}], blank), "")
