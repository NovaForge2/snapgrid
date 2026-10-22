# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 NovaForge2
"""Plugin environment values are opaque to the framework."""

import contextlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from snapgrid_core.environment import load_env, parse_env_file


class EnvFiles(unittest.TestCase):
    def test_lines_are_read_the_way_a_shell_would(self):
        self.assertEqual(
            parse_env_file(
                "# a comment\n"
                "\n"
                "PLAIN=value\n"
                "export EXPORTED=value\n"
                'QUOTED="in quotes"\n'
                "SINGLE='in quotes'\n"
                "SPACED = padded \n"
                "WITH_EQUALS=a=b=c\n"
                "EMPTY=\n"
                "no_equals_sign\n"
            ),
            [
                ("PLAIN", "value"),
                ("EXPORTED", "value"),
                ("QUOTED", "in quotes"),
                ("SINGLE", "in quotes"),
                ("SPACED", "padded"),
                ("WITH_EQUALS", "a=b=c"),
                ("EMPTY", ""),
            ],
        )


class LoadingEnv(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.env_file = self.root / ".env"

    def test_missing_env_is_an_empty_mapping(self):
        self.assertEqual(load_env(self.env_file), {})

    def test_values_are_not_decoded_or_interpreted(self):
        self.env_file.write_text(
            "PLAIN=ordinary\nTOKEN=enc:this is not base64\nEMPTY=enc:\n",
            encoding="utf-8",
        )
        with mock.patch.object(Path, "home", side_effect=AssertionError("no key lookup")), \
             mock.patch.dict(os.environ, SNAPGRID_KEY_FILE=str(self.root / "absent")):
            self.assertEqual(load_env(self.env_file), {
                "PLAIN": "ordinary", "TOKEN": "enc:this is not base64", "EMPTY": "enc:",
            })
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), [".env"])

    def test_existing_key_file_is_never_read_or_changed(self):
        key_file = self.root / "key"
        key_file.write_text("not a valid key", encoding="utf-8")
        self.env_file.write_text("TOKEN=enc:not-encrypted\n", encoding="utf-8")
        with mock.patch.dict(os.environ, SNAPGRID_KEY_FILE=str(key_file)):
            self.assertEqual(load_env(self.env_file), {"TOKEN": "enc:not-encrypted"})
        self.assertEqual(key_file.read_text(encoding="utf-8"), "not a valid key")

    def test_last_assignment_wins_and_quoted_spaces_survive(self):
        self.env_file.write_text('NAME=first\nNAME=last\nVALUE="  value  "\n', encoding="utf-8")
        self.assertEqual(load_env(self.env_file), {"NAME": "last", "VALUE": "  value  "})


class FrameworkBoundary(unittest.TestCase):
    def test_server_has_no_encrypt_command(self):
        from snapgrid_core import __main__ as cli
        self.assertNotIn('encrypt', cli.COMMANDS)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
            cli.build_parser().parse_args(['encrypt'])
        self.assertEqual(caught.exception.code, 2)

    def test_importing_framework_does_not_load_optional_crypto(self):
        root = Path(__file__).resolve().parent.parent
        result = subprocess.run(
            [sys.executable, '-c',
             'import sys; import snapgrid_core.__main__; '
             'assert "snapgrid_core.secrets_store" not in sys.modules; '
             'assert "tools.encrypt" not in sys.modules; '
             'assert "getpass" not in sys.modules'],
            cwd=root, capture_output=True, encoding='utf-8', timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
