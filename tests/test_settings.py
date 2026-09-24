# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 NovaForge2
"""snapgrid.toml, and what happens when it is wrong."""

import tempfile
import unittest
from pathlib import Path

from snapgrid import settings as settings_module
from snapgrid.settings import DEFAULTS, load_settings


class Settings(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.file = Path(self.tmp.name) / "snapgrid.toml"
        original = settings_module.SETTINGS_PATH
        settings_module.SETTINGS_PATH = self.file
        self.addCleanup(setattr, settings_module, "SETTINGS_PATH", original)

    def write(self, text: str) -> dict:
        self.file.write_text(text, encoding="utf-8")
        return load_settings()

    def test_no_file_means_the_defaults(self):
        self.assertEqual(load_settings(), DEFAULTS)

    def test_an_empty_file_means_the_defaults(self):
        self.assertEqual(self.write(""), DEFAULTS)

    def test_values_are_read(self):
        result = self.write(
            '[server]\ntitle = "Reports"\nport = 9000\nmax_concurrent = 7\n'
            '[banner]\ntext = "careful"\nlevel = "error"\n'
        )
        self.assertEqual(result["title"], "Reports")
        self.assertEqual(result["port"], 9000)
        self.assertEqual(result["max_concurrent"], 7)
        self.assertEqual(result["banner_text"], "careful")
        self.assertEqual(result["banner_level"], "error")

    def test_keys_left_out_keep_their_defaults(self):
        result = self.write('[server]\ntitle = "Only the title"\n')
        self.assertEqual(result["title"], "Only the title")
        self.assertEqual(result["port"], DEFAULTS["port"])
        self.assertEqual(result["max_concurrent"], DEFAULTS["max_concurrent"])

    def test_a_banner_with_no_level_is_informational(self):
        self.assertEqual(self.write('[banner]\ntext = "hello"\n')["banner_level"], "info")

    def test_an_unknown_level_falls_back_without_losing_the_message(self):
        result = self.write('[banner]\ntext = "hello"\nlevel = "critical"\n')
        self.assertEqual(result["banner_text"], "hello")
        self.assertEqual(result["banner_level"], "info")

    def test_levels_are_case_insensitive(self):
        self.assertEqual(self.write('[banner]\nlevel = "WARNING"\n')["banner_level"], "warning")

    def test_nonsense_values_are_ignored_rather_than_obeyed(self):
        result = self.write(
            '[server]\nport = 99999\nmax_concurrent = 0\ntitle = "   "\n'
        )
        self.assertEqual(result["port"], DEFAULTS["port"])
        self.assertEqual(result["max_concurrent"], DEFAULTS["max_concurrent"])
        self.assertEqual(result["title"], DEFAULTS["title"])

    def test_a_port_of_the_wrong_type_is_ignored(self):
        self.assertEqual(self.write('[server]\nport = "9000"\n')["port"], DEFAULTS["port"])

    def test_true_is_not_a_number(self):
        # bool is an int in Python, and that must not leak into settings.
        self.assertEqual(self.write("[server]\nport = true\n")["port"], DEFAULTS["port"])

    def test_a_broken_file_becomes_a_message_on_the_page(self):
        # Refusing to start would be worse, and ignoring it silently worse still.
        result = self.write("[server\ntitle = broken\n")
        self.assertEqual(result["banner_level"], "error")
        self.assertIn("could not be read", result["banner_text"])
        self.assertEqual(result["port"], DEFAULTS["port"])

    def test_unknown_sections_and_keys_are_harmless(self):
        result = self.write('[server]\ntitle = "X"\nnonsense = 1\n[future]\nthing = true\n')
        self.assertEqual(result["title"], "X")


if __name__ == "__main__":
    unittest.main()
