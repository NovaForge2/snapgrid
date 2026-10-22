# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 NovaForge2
"""The optional helper is independent, explicit, and never saves a key."""

import base64
import contextlib
import getpass
import hashlib
import hmac
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import warnings
from pathlib import Path
from unittest.mock import Mock, patch

from tools import encrypt as helper

if os.name == "posix":
    import pty
    import select
    import termios

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "tools" / "encrypt.py"
KEY = bytes(range(32))
ENCODED_KEY = base64.b64encode(KEY).decode("ascii")
VALUE = "  üñïçödé\t🔑\n "
# Produced by the former snapgrid.secrets_store with bytes(range(16, 32))
# as the nonce, before that framework module was removed. These fixtures
# check the existing wire format without importing framework crypto.
LEGACY_TOKENS = {
    16: "enc:EBESExQVFhcYGRobHB0eH7oRh8bQ+0E/pLCWCIZMi42tmuK20eZQ2J1gWJ4vZIb6ILnxQlG+oPHuvACcsPQIoJ0FKFiswQ==",
    32: "enc:EBESExQVFhcYGRobHB0eH+uZI4EmSnzpUo63mtPFh4meu5aWgUaS3rivlI9qEwrLEwY/HF5up2qAlEnMl1Rzi3cZ+vsrLA==",
    48: "enc:EBESExQVFhcYGRobHB0eH+RIvcpX6fhHWscFiyjo9QgIxgh5v6n/9c2G0845GWNEUxwg8yyf71FwhLDK8EKsutkcq1sJ8Q==",
}


class Crypto(unittest.TestCase):
    def test_unicode_whitespace_and_long_values_survive_round_trip(self):
        for value in ("", "secret", VALUE, " \t ", "x" * 10000, "=;#'\"\\"):
            with self.subTest(value=value[:20]):
                self.assertEqual(helper.decrypt(helper.encrypt(value, KEY), KEY), value)

    def test_old_tokens_and_key_lengths_remain_compatible(self):
        for length, token in LEGACY_TOKENS.items():
            with self.subTest(length=length):
                self.assertEqual(helper.decrypt(token, bytes(range(length))), VALUE)

    def test_new_tokens_match_old_algorithm_exactly(self):
        for length, token in LEGACY_TOKENS.items():
            with self.subTest(length=length):
                with patch.object(helper.secrets, "token_bytes",
                                  return_value=bytes(range(16, 32))) as random:
                    self.assertEqual(helper.encrypt(VALUE, bytes(range(length))), token)
                random.assert_called_once_with(16)

    def test_each_encryption_uses_a_fresh_nonce(self):
        first = helper.encrypt(VALUE, KEY)
        second = helper.encrypt(VALUE, KEY)
        self.assertNotEqual(first, second)
        self.assertEqual(helper.decrypt(first, KEY), helper.decrypt(second, KEY))

    def test_a_wrong_key_is_rejected_without_revealing_values(self):
        token = helper.encrypt(VALUE, KEY)
        with self.assertRaises(helper.SecretError) as raised:
            helper.decrypt(token, bytes(32))
        self.assertIn("wrong key", str(raised.exception))
        self.assertNotIn(VALUE, str(raised.exception))
        self.assertNotIn(token, str(raised.exception))

    def test_every_nonce_ciphertext_and_tag_byte_is_authenticated(self):
        raw = base64.b64decode(helper.encrypt(VALUE, KEY)[4:])
        for index in range(len(raw)):
            edited = bytearray(raw)
            edited[index] ^= 1
            token = "enc:" + base64.b64encode(edited).decode("ascii")
            with self.subTest(index=index), self.assertRaises(helper.SecretError):
                helper.decrypt(token, KEY)

    def test_authentication_happens_before_decryption(self):
        token = helper.encrypt("secret", KEY)
        with patch.object(helper, "_keystream") as keystream:
            with self.assertRaises(helper.SecretError):
                helper.decrypt(token, bytes(32))
        keystream.assert_not_called()

    def test_bad_base64_and_truncated_tokens_are_rejected(self):
        for token in ("enc:", "enc:?!", "enc:🔑", "enc:YQ==", "enc:" + "A" * 60):
            with self.subTest(token=token), self.assertRaises(helper.SecretError):
                helper.decrypt(token, KEY)

    def test_authenticated_invalid_utf8_has_a_safe_error(self):
        nonce = bytes(16)
        enc_key, mac_key = helper._subkeys(KEY)
        ciphertext = helper._xor(b"\xff", helper._keystream(enc_key, nonce, 1))
        tag = hmac.new(mac_key, nonce + ciphertext, hashlib.sha256).digest()
        token = "enc:" + base64.b64encode(nonce + ciphertext + tag).decode("ascii")
        with self.assertRaisesRegex(helper.SecretError, "not valid UTF-8"):
            helper.decrypt(token, KEY)

    def test_plaintext_is_passed_through_with_an_explicit_key(self):
        self.assertEqual(helper.decrypt(VALUE, KEY), VALUE)

    def test_api_requires_a_decoded_key_of_at_least_16_bytes(self):
        for key in (b"", b"short", bytes(15), ENCODED_KEY, None):
            with self.subTest(key=type(key).__name__):
                with self.assertRaises(helper.SecretError):
                    helper.encrypt("secret", key)
                with self.assertRaises(helper.SecretError):
                    helper.decrypt("plain", key)

    def test_functions_have_no_implicit_key_argument(self):
        for operation in (helper.encrypt, helper.decrypt, helper.load_key):
            with self.subTest(operation=operation.__name__), self.assertRaises(TypeError):
                operation() if operation is helper.load_key else operation("value")

    def test_decode_key_is_strict_and_accepts_legacy_lengths(self):
        for length in (16, 32, 48):
            key = bytes(range(length))
            self.assertEqual(helper.decode_key(" \n" + base64.b64encode(key).decode() + "\n"), key)
        for encoded in ("", "!secret!", "ü", "c2hvcnQ=", ENCODED_KEY + "garbage"):
            with self.subTest(encoded=encoded), self.assertRaises(helper.SecretError):
                helper.decode_key(encoded)


class WithKeyFile(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.key_file = self.root / "explicit-key.txt"
        self.key_file.write_text("key=" + ENCODED_KEY + "\n", encoding="utf-8")

    def run_main(self, arguments, **patches):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.ExitStack() as stack:
            stack.enter_context(contextlib.redirect_stdout(stdout))
            stack.enter_context(contextlib.redirect_stderr(stderr))
            for name, value in patches.items():
                stack.enter_context(patch.object(helper, name, value))
            code = helper.main(arguments)
        return code, stdout.getvalue(), stderr.getvalue()

    def encrypt_args(self):
        return ["encrypt", "--key-file", str(self.key_file)]


class KeyFiles(WithKeyFile):
    def test_load_reads_only_the_explicit_file(self):
        with patch.dict(os.environ, {"SNAPGRID_KEY_FILE": "must-not-open",
                                     "HOME": "must-not-open", "USERPROFILE": "must-not-open"}):
            self.assertEqual(helper.load_key(self.key_file), KEY)

    def test_comments_blank_lines_crlf_and_assignment_spaces_are_allowed(self):
        self.key_file.write_text("# private key\r\n\r\n key = " + ENCODED_KEY + " \r\n",
                                 encoding="utf-8")
        self.assertEqual(helper.load_key(self.key_file), KEY)

    def test_missing_key_file_is_not_created(self):
        path = self.root / "missing"
        with self.assertRaisesRegex(helper.SecretError, "cannot read key file"):
            helper.load_key(path)
        self.assertFalse(path.exists())

    def test_unreadable_key_file_has_no_contents_in_error(self):
        with patch("builtins.open", side_effect=PermissionError("sensitive detail")):
            with self.assertRaisesRegex(helper.SecretError, "^cannot read key file$"):
                helper.load_key(self.key_file)

    def test_invalid_utf8_key_file_has_a_safe_error(self):
        self.key_file.write_bytes(b"key=\xff")
        with self.assertRaisesRegex(helper.SecretError, "^cannot read key file$"):
            helper.load_key(self.key_file)

    def test_malformed_missing_duplicate_or_short_keys_are_rejected(self):
        valid = "key=" + ENCODED_KEY
        for content in ("", "\n# no key\n", "key=", "key=\n" + valid,
                        ENCODED_KEY, "KEY=" + ENCODED_KEY, "password=secret-marker",
                        valid + "\n" + valid, valid + "\nother=secret-marker",
                        "key=not-base64-secret-marker", "key=c2hvcnQ="):
            with self.subTest(content=content):
                self.key_file.write_text(content, encoding="utf-8")
                with self.assertRaises(helper.SecretError) as raised:
                    helper.load_key(self.key_file)
                self.assertNotIn(ENCODED_KEY, str(raised.exception))
                self.assertNotIn("secret-marker", str(raised.exception))
                self.assertEqual(self.key_file.read_text(encoding="utf-8"), content)

    def test_bad_key_fails_before_prompt_or_randomness(self):
        self.key_file.write_text("key=secret-marker!", encoding="utf-8")
        prompt = Mock()
        with patch.object(helper.secrets, "token_bytes") as random:
            code, stdout, stderr = self.run_main(self.encrypt_args(), prompt_secret=prompt)
        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        self.assertNotIn("secret-marker", stderr)
        prompt.assert_not_called()
        random.assert_not_called()

    def test_encrypt_prints_only_token_and_does_not_modify_file(self):
        before = self.key_file.read_bytes()
        code, stdout, stderr = self.run_main(self.encrypt_args(), prompt_secret=Mock(return_value=VALUE))
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertTrue(stdout.startswith("enc:"))
        self.assertEqual(len(stdout.splitlines()), 1)
        self.assertEqual(helper.decrypt(stdout.rstrip("\n"), KEY), VALUE)
        self.assertEqual(self.key_file.read_bytes(), before)

    def test_whitespace_only_plaintext_is_not_stripped(self):
        code, stdout, _ = self.run_main(self.encrypt_args(), prompt_secret=Mock(return_value=" \t "))
        self.assertEqual(code, 0)
        self.assertEqual(helper.decrypt(stdout.rstrip("\n"), KEY), " \t ")

    def test_empty_value_creates_no_token_or_random_nonce(self):
        with patch.object(helper.secrets, "token_bytes") as random:
            code, stdout, stderr = self.run_main(self.encrypt_args(), prompt_secret=Mock(return_value=""))
        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        self.assertIn("nothing to encrypt", stderr)
        random.assert_not_called()

    def test_ctrl_c_and_eof_are_handled_without_tracebacks(self):
        for exception in (KeyboardInterrupt, EOFError):
            with self.subTest(exception=exception.__name__):
                prompt = Mock(side_effect=exception)
                with patch.object(helper.secrets, "token_bytes") as random:
                    code, stdout, stderr = self.run_main(self.encrypt_args(), prompt_secret=prompt)
                self.assertEqual(code, 1)
                self.assertEqual(stdout, "")
                self.assertIn("cancelled", stderr)
                self.assertNotIn("Traceback", stderr)
                random.assert_not_called()


class HiddenPrompt(unittest.TestCase):
    def test_windows_non_tty_fails_before_getpass(self):
        stdin = Mock()
        stdin.isatty.return_value = False
        with patch.object(helper.os, "name", "nt"), patch.object(helper.sys, "stdin", stdin):
            with patch.object(helper.getpass, "getpass") as prompt:
                with self.assertRaises(helper.SecretError) as raised:
                    helper.prompt_secret()
        prompt.assert_not_called()
        self.assertIn("winpty python tools/encrypt.py encrypt --key-file PATH", str(raised.exception))
        self.assertIn("PowerShell", str(raised.exception))

    def test_windows_missing_or_broken_stdin_is_rejected(self):
        candidates = [None, object()]
        for exception in (OSError, ValueError, AttributeError):
            stdin = Mock()
            stdin.isatty.side_effect = exception
            candidates.append(stdin)
        for stdin in candidates:
            with self.subTest(stdin=type(stdin).__name__):
                with patch.object(helper.os, "name", "nt"), patch.object(helper.sys, "stdin", stdin):
                    with patch.object(helper.getpass, "getpass") as prompt:
                        with self.assertRaises(helper.SecretError):
                            helper.prompt_secret()
                prompt.assert_not_called()

    def test_windows_tty_including_git_bash_conpty_continues(self):
        stdin = Mock()
        stdin.isatty.return_value = True
        with patch.object(helper.os, "name", "nt"), patch.object(helper.sys, "stdin", stdin):
            with patch.dict(os.environ, {"MSYSTEM": "MINGW64", "TERM": "xterm"}):
                with patch.object(helper.getpass, "getpass", return_value=VALUE) as prompt:
                    self.assertEqual(helper.prompt_secret(), VALUE)
        prompt.assert_called_once_with("value to encrypt (not shown): ", stream=sys.stderr)

    def test_unix_redirected_stdin_may_still_use_controlling_terminal(self):
        stdin = Mock()
        stdin.isatty.return_value = False
        with patch.object(helper.os, "name", "posix"), patch.object(helper.sys, "stdin", stdin):
            with patch.object(helper.getpass, "getpass", return_value=VALUE) as prompt:
                self.assertEqual(helper.prompt_secret(), VALUE)
        prompt.assert_called_once()

    def test_real_fallback_is_stopped_before_any_read_or_echo(self):
        stdin = Mock()
        stdin.readline.side_effect = AssertionError("must not read visible input")
        stderr = io.StringIO()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", getpass.GetPassWarning)
            with patch.object(helper.os, "name", "posix"), patch.object(helper.sys, "stdin", stdin):
                with contextlib.redirect_stderr(stderr):
                    with patch.object(helper.getpass, "getpass", helper.getpass.fallback_getpass):
                        with self.assertRaisesRegex(helper.SecretError, "cannot hide input"):
                            helper.prompt_secret()
        stdin.readline.assert_not_called()
        self.assertEqual(stderr.getvalue(), "")

    def test_terminal_error_does_not_reveal_exception_detail(self):
        with patch.object(helper.os, "name", "posix"):
            with patch.object(helper.getpass, "getpass", side_effect=OSError("secret-marker")):
                with self.assertRaises(helper.SecretError) as raised:
                    helper.prompt_secret()
        self.assertNotIn("secret-marker", str(raised.exception))


class Standalone(WithKeyFile):
    def run_script(self, arguments, *, script=SCRIPT, input="", cwd=None, env=None):
        # No inherited controlling terminal: a pipeline must terminate rather
        # than quietly prompting the developer who is running the tests.
        extra = {"start_new_session": True} if os.name == "posix" else {}
        return subprocess.run([sys.executable, str(script), *arguments],
                              input=input, capture_output=True, text=True, encoding="utf-8",
                              cwd=cwd or self.root, env=env, timeout=5, **extra)

    def test_generation_uses_32_random_bytes_and_never_opens_a_file_or_prompts(self):
        with patch.object(helper.secrets, "token_bytes", return_value=KEY) as random:
            with patch("builtins.open", side_effect=AssertionError("must not open a file")):
                with patch.object(helper, "load_key") as load, patch.object(helper, "prompt_secret") as prompt:
                    code, stdout, stderr = self.run_main(["generate-key"])
        self.assertEqual((code, stdout, stderr), (0, "key=" + ENCODED_KEY + "\n", ""))
        random.assert_called_once_with(32)
        load.assert_not_called()
        prompt.assert_not_called()

    def test_fresh_copy_generates_stdout_only_without_any_file_tree_changes(self):
        standalone = self.root / "custom-plugin" / "encrypt.py"
        standalone.parent.mkdir()
        shutil.copyfile(SCRIPT, standalone)
        env = dict(os.environ, HOME=str(self.root / "new-home"),
                   USERPROFILE=str(self.root / "new-profile"),
                   SNAPGRID_KEY_FILE=str(self.root / "must-not-create.key"))
        env.pop("PYTHONDONTWRITEBYTECODE", None)
        # Do not redirect interpreter startup caches into the fixture: Python
        # imports its own encodings before the script can disable bytecode.
        env.pop("PYTHONPYCACHEPREFIX", None)
        before = self.snapshot()
        first = self.run_script(["generate-key"], script=standalone, env=env)
        second = self.run_script(["generate-key"], script=standalone, env=env)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(first.stderr + second.stderr, "")
        for result in (first, second):
            self.assertEqual(len(result.stdout.splitlines()), 1)
            self.assertTrue(result.stdout.startswith("key="))
            self.assertEqual(len(base64.b64decode(result.stdout[4:].strip(), validate=True)), 32)
        self.assertNotEqual(first.stdout, second.stdout)
        self.assertEqual(self.snapshot(), before)

    def snapshot(self):
        return {str(path.relative_to(self.root)): path.read_bytes() if path.is_file() else None
                for path in self.root.rglob("*")}

    def test_generate_output_is_accepted_as_an_explicit_key_file(self):
        result = self.run_script(["generate-key"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.key_file.write_text(result.stdout, encoding="utf-8")
        self.assertEqual(len(helper.load_key(self.key_file)), 32)

    def test_copied_module_works_without_the_repository_on_the_python_path(self):
        script = self.root / "encrypt.py"
        shutil.copyfile(SCRIPT, script)
        code = ("import encrypt; "
                "key = encrypt.load_key('explicit-key.txt'); "
                "print(encrypt.decrypt(encrypt.encrypt('standalone value', key), key))")
        result = subprocess.run([sys.executable, "-B", "-S", "-c", code], cwd=self.root,
                                capture_output=True, text=True, timeout=5,
                                env={**os.environ, "PYTHONPATH": ""})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "standalone value\n")
        self.assertEqual(result.stderr, "")

    def test_noninteractive_encrypt_exits_without_echo_read_or_file_changes(self):
        before = self.snapshot()
        result = self.run_script(self.encrypt_args(), input="secret-marker-do-not-echo\n")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertIn("cannot hide input", result.stderr)
        self.assertNotIn("secret-marker", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertNotIn("Password input may be echoed", result.stderr)
        self.assertEqual(self.snapshot(), before)

    @unittest.skipUnless(os.name == "posix", "requires a POSIX pseudo-terminal")
    def test_real_terminal_hides_unicode_input_and_prints_only_a_token(self):
        script = self.root / "encrypt.py"
        shutil.copyfile(SCRIPT, script)
        before = self.snapshot()
        value = "  hidden üñïçödé 🔑\t "
        master, slave = pty.openpty()
        try:
            original_flags = termios.tcgetattr(slave)
            with subprocess.Popen(
                    [sys.executable, str(script), *self.encrypt_args()],
                    stdin=slave, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    cwd=self.root, start_new_session=True,
                    env={**os.environ, "PYTHONIOENCODING": "utf-8"}) as process:
                try:
                    ready, _, _ = select.select([process.stderr], [], [], 5)
                    self.assertTrue(ready, "hidden prompt never appeared")
                    prompt = os.read(process.stderr.fileno(), 4096)
                    self.assertIn(b"value to encrypt (not shown): ", prompt)
                    self.assertFalse(termios.tcgetattr(slave)[3] & termios.ECHO,
                                     "input echo must be disabled before asking for the value")
                    os.write(master, value.encode("utf-8") + b"\n")
                    stdout, stderr = process.communicate(timeout=5)
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.communicate(timeout=5)
                self.assertEqual(process.returncode, 0, stderr.decode("utf-8"))
            self.assertEqual(termios.tcgetattr(slave), original_flags)
            echoed, _, _ = select.select([master], [], [], 0)
            self.assertEqual(echoed, [], "plaintext must not be echoed to the terminal")
        finally:
            os.close(master)
            os.close(slave)
        self.assertEqual(len(stdout.splitlines()), 1)
        self.assertTrue(stdout.startswith(b"enc:"))
        self.assertEqual(helper.decrypt(stdout.decode("ascii").rstrip("\n"), KEY), value)
        self.assertNotIn(value.encode("utf-8"), prompt + stderr + stdout)
        self.assertEqual(self.snapshot(), before)

    def test_key_file_is_required_even_when_a_default_looking_key_exists(self):
        (self.root / ".snapgrid_key").write_text("key=" + ENCODED_KEY, encoding="utf-8")
        env = dict(os.environ, HOME=str(self.root), USERPROFILE=str(self.root),
                   SNAPGRID_KEY_FILE=str(self.key_file))
        before = self.snapshot()
        result = self.run_script(["encrypt"], env=env)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertIn("--key-file", result.stderr)
        self.assertEqual(self.snapshot(), before)

    def test_bad_arguments_never_echo_a_mistakenly_pasted_secret(self):
        for arguments in (["secret-marker"], ["encrypt", "secret-marker"],
                          ["encrypt", "--key", "secret-marker"],
                          ["encrypt", "--value", "secret-marker"],
                          ["generate-key", "secret-marker"],
                          self.encrypt_args() + ["secret-marker"]):
            with self.subTest(arguments=arguments):
                result = self.run_script(arguments)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, "")
                self.assertNotIn("secret-marker", result.stderr)

    def test_malformed_key_file_error_does_not_expose_its_contents(self):
        self.key_file.write_text("key=secret-marker!", encoding="utf-8")
        result = self.run_script(self.encrypt_args())
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertNotIn("secret-marker", result.stderr)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
