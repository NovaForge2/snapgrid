# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 NovaForge2
"""Encrypted values in .env, and keeping them off the screen."""

import os
import tempfile
import unittest
from pathlib import Path

from snapgrid import secrets_store
from snapgrid.secrets_store import (
    PREFIX,
    SecretError,
    decrypt,
    encrypt,
    load_env,
    load_key,
    mask,
    parse_env_file,
)


class WithAKey(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.key_file = self.root / "key"
        os.environ["SNAPGRID_KEY_FILE"] = str(self.key_file)
        self.addCleanup(os.environ.pop, "SNAPGRID_KEY_FILE", None)
        self.key = load_key(create=True)


class Encryption(WithAKey):
    def test_a_value_survives_the_round_trip(self):
        for value in ["hunter2", "", "a" * 500, "with spaces", "üñïçödé", "=;#'\"\\"]:
            self.assertEqual(decrypt(encrypt(value, self.key), self.key), value, repr(value))

    def test_the_same_value_encrypts_differently_every_time(self):
        # Otherwise two accounts sharing a password would be obvious at a glance.
        first = encrypt("hunter2", self.key)
        second = encrypt("hunter2", self.key)
        self.assertNotEqual(first, second)
        self.assertEqual(decrypt(first, self.key), decrypt(second, self.key))

    def test_the_plaintext_does_not_appear_in_the_output(self):
        self.assertNotIn("hunter2", encrypt("hunter2", self.key))

    def test_a_wrong_key_fails_loudly_rather_than_returning_rubbish(self):
        token = encrypt("hunter2", self.key)
        other = bytes(32)
        with self.assertRaises(SecretError) as caught:
            decrypt(token, other)
        self.assertIn("wrong key", str(caught.exception))

    def test_an_edited_value_is_detected(self):
        token = encrypt("hunter2", self.key)
        body = list(token[len(PREFIX):])
        body[10] = "A" if body[10] != "A" else "B"
        with self.assertRaises(SecretError):
            decrypt(PREFIX + "".join(body), self.key)

    def test_nonsense_is_refused(self):
        with self.assertRaises(SecretError):
            decrypt(PREFIX + "not base64 at all!!", self.key)
        with self.assertRaises(SecretError):
            decrypt(PREFIX + "c2hvcnQ=", self.key)     # too short to hold a tag

    def test_a_value_without_the_marker_is_left_alone(self):
        self.assertEqual(decrypt("plain text", self.key), "plain text")

    def test_the_key_is_reused_not_regenerated(self):
        self.assertEqual(load_key(), self.key)

    def test_a_missing_key_says_what_to_run(self):
        os.environ["SNAPGRID_KEY_FILE"] = str(self.root / "absent")
        with self.assertRaises(SecretError) as caught:
            load_key()
        self.assertIn("encrypt", str(caught.exception))

    def test_a_damaged_key_file_is_reported(self):
        self.key_file.write_text("not base64 !!", encoding="utf-8")
        with self.assertRaises(SecretError):
            load_key()


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


class LoadingEnv(WithAKey):
    def test_encrypted_values_arrive_decrypted_and_are_marked_secret(self):
        env_file = self.root / ".env"
        env_file.write_text(
            f"USER=me\nPASSWORD={encrypt('hunter2', self.key)}\n", encoding="utf-8"
        )
        values, secret_values = load_env(env_file)
        self.assertEqual(values, {"USER": "me", "PASSWORD": "hunter2"})
        self.assertEqual(secret_values, ["hunter2"])      # only the encrypted one

    def test_a_missing_file_is_not_an_error(self):
        self.assertEqual(load_env(self.root / "nothing"), ({}, []))

    def test_a_bad_value_names_the_variable(self):
        env_file = self.root / ".env"
        env_file.write_text(f"PASSWORD={PREFIX}bm9wZQ==\n", encoding="utf-8")
        with self.assertRaises(SecretError) as caught:
            load_env(env_file)
        self.assertIn("PASSWORD", str(caught.exception))


class Masking(unittest.TestCase):
    def test_a_secret_is_replaced_wherever_it_appears(self):
        self.assertEqual(
            mask("connecting with hunter2, then hunter2 again", ["hunter2"]),
            "connecting with ****, then **** again",
        )

    def test_very_short_values_are_left_alone(self):
        # Masking "1" would turn any text containing a digit into asterisks.
        self.assertEqual(mask("value is 1 today", ["1"]), "value is 1 today")

    def test_the_longest_secret_is_masked_first(self):
        self.assertEqual(mask("abcdefgh", ["abcd", "abcdefgh"]), "****")

    def test_nothing_to_do(self):
        self.assertEqual(mask("text", []), "text")
        self.assertEqual(mask("", ["secret"]), "")


if __name__ == "__main__":
    unittest.main()
