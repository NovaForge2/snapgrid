#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 NovaForge2
"""Optional, standalone encryption helper for custom plugins.

    python tools/encrypt.py generate-key
    python tools/encrypt.py encrypt --key-file my-key.txt

generate-key prints one ``key=<base64>`` line containing 32 random bytes. It
does not read or write a key file. Encrypt reads only the explicitly supplied
file, prompts for a hidden value, and prints only its ``enc:`` token to stdout.
Neither command saves anything; key storage and distribution belong to you.

Copy this file into a custom plugin to use load_key(path), encrypt(value, key)
and decrypt(token, key). Keys passed to encrypt/decrypt are bytes, not base64.
The token format is compatible with older snapgrid encrypted values. This
helper has no connection to snapgrid's runner or environment-file loading.

The legacy construction uses an HMAC-SHA256 keystream and authenticates the
nonce and ciphertext before decryption. It is kept for compatibility, not as
a replacement for a dedicated secrets manager. Anyone who obtains the key
can decrypt the values; keep it separate from values you share or commit.
"""

import sys

# Running this copyable script must not create local bytecode caches, even
# when a standard-library import has not been compiled on this machine yet.
# Importing it as a plugin module does not change the host's interpreter flags.
if __name__ == "__main__":
    sys.dont_write_bytecode = True

import argparse
import base64
import binascii
import getpass
import hashlib
import hmac
import os
import secrets
import warnings

PREFIX = "enc:"
KEY_LEN = 32
NONCE_LEN = 16
TAG_LEN = 32


class SecretError(Exception):
    """A key, token or hidden-input problem, without revealing its contents."""


def _check_key(key: bytes) -> None:
    # Older versions accepted keys of at least 16 bytes. Keep those usable,
    # while generate-key always makes a fresh 32-byte key.
    if not isinstance(key, bytes) or len(key) < 16:
        raise SecretError("key must contain at least 16 decoded bytes")


def decode_key(encoded: str) -> bytes:
    """Decode an explicitly supplied base64 key; never look one up."""
    try:
        key = base64.b64decode(encoded.strip(), validate=True)
    except (ValueError, binascii.Error) as exc:
        raise SecretError("key is not valid base64") from exc
    _check_key(key)
    return key


def load_key(path: str | os.PathLike[str]) -> bytes:
    """Read one key=<base64> assignment from an explicitly supplied file.

    Blank lines and lines beginning with # are allowed. Missing, duplicate
    or other assignments are errors. This never creates or changes the file.
    """
    try:
        with open(path, encoding="utf-8") as source:
            lines = source.read().splitlines()
    except (OSError, UnicodeError) as exc:
        raise SecretError("cannot read key file") from exc

    encoded: str | None = None
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, separator, value = line.partition("=")
        if not separator or name.strip() != "key":
            raise SecretError("key file must contain one key=<base64> assignment")
        if encoded is not None:
            raise SecretError("key file contains more than one key assignment")
        encoded = value.strip()
    if not encoded:
        raise SecretError("key file has no key value")
    return decode_key(encoded)


def _subkeys(key: bytes) -> tuple[bytes, bytes]:
    enc = hmac.new(key, b"snapgrid-encryption", hashlib.sha256).digest()
    mac = hmac.new(key, b"snapgrid-authentication", hashlib.sha256).digest()
    return enc, mac


def _keystream(key: bytes, nonce: bytes, length: int) -> bytes:
    out = bytearray()
    counter = 0
    while len(out) < length:
        block = nonce + counter.to_bytes(4, "big")
        out += hmac.new(key, block, hashlib.sha256).digest()
        counter += 1
    return bytes(out[:length])


def _xor(data: bytes, stream: bytes) -> bytes:
    return bytes(a ^ b for a, b in zip(data, stream))


def encrypt(value: str, key: bytes) -> str:
    """Encrypt a UTF-8 value with an explicit decoded key and fresh nonce."""
    _check_key(key)
    enc_key, mac_key = _subkeys(key)
    nonce = secrets.token_bytes(NONCE_LEN)
    plaintext = value.encode("utf-8")
    ciphertext = _xor(plaintext, _keystream(enc_key, nonce, len(plaintext)))
    tag = hmac.new(mac_key, nonce + ciphertext, hashlib.sha256).digest()
    return PREFIX + base64.b64encode(nonce + ciphertext + tag).decode("ascii")


def decrypt(token: str, key: bytes) -> str:
    """Decrypt an enc: value with an explicit key; pass plain values through."""
    _check_key(key)
    if not token.startswith(PREFIX):
        return token
    try:
        raw = base64.b64decode(token[len(PREFIX):], validate=True)
    except (ValueError, binascii.Error) as exc:
        raise SecretError("encrypted value is not valid base64") from exc
    if len(raw) < NONCE_LEN + TAG_LEN:
        raise SecretError("encrypted value is too short")

    nonce = raw[:NONCE_LEN]
    ciphertext = raw[NONCE_LEN:-TAG_LEN]
    tag = raw[-TAG_LEN:]
    enc_key, mac_key = _subkeys(key)
    expected = hmac.new(mac_key, nonce + ciphertext, hashlib.sha256).digest()
    if not hmac.compare_digest(expected, tag):
        raise SecretError("cannot decrypt value (wrong key, or value was edited)")
    try:
        return _xor(ciphertext, _keystream(enc_key, nonce, len(ciphertext))).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SecretError("decrypted value is not valid UTF-8") from exc


def prompt_secret() -> str:
    """Read hidden input, or stop before getpass can hang or echo it."""
    if os.name == "nt":
        # Native Windows getpass uses console I/O. Mintty (Git Bash) may
        # instead provide a pipe, leaving getpass stuck at an invisible
        # console. Check stdin, not MSYSTEM: winpty and ConPTY can work.
        try:
            is_tty = sys.stdin is not None and sys.stdin.isatty()
        except (AttributeError, OSError, ValueError):
            is_tty = False
        if not is_tty:
            raise SecretError(
                "cannot hide input in this Windows terminal.\n"
                "  In Git Bash, try: winpty python tools/encrypt.py encrypt --key-file PATH\n"
                "  Or run: python tools/encrypt.py encrypt --key-file PATH "
                "in PowerShell or Command Prompt."
            )

    # Treat the warning as an error before getpass's fallback reads anything,
    # even when warnings are globally disabled. On Unix, getpass may use
    # /dev/tty with redirected stdin, so don't apply the Windows check there.
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        try:
            return getpass.getpass("value to encrypt (not shown): ", stream=sys.stderr)
        except getpass.GetPassWarning as exc:
            raise SecretError(
                "cannot hide input in this terminal. Run 'python tools/encrypt.py "
                "encrypt --key-file PATH' in an interactive terminal."
            ) from exc
        except OSError as exc:
            raise SecretError("cannot read hidden input in this terminal") from exc


class _ArgumentParser(argparse.ArgumentParser):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, allow_abbrev=False, **kwargs)

    def error(self, message: str) -> None:
        # argparse normally repeats invalid arguments, which could contain a
        # secret someone mistakenly pasted after the command. Never echo them.
        self.print_usage(sys.stderr)
        self.exit(2, "encrypt.py: invalid arguments; use 'generate-key' or "
                  "'encrypt --key-file PATH'. Enter values only at the hidden prompt.\n")


def main(argv: list[str] | None = None) -> int:
    parser = _ArgumentParser(description="Optional encryption helper for custom plugins.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("generate-key", help="print key=<base64>; never save it")
    encrypt_parser = subparsers.add_parser("encrypt", help="encrypt a hidden value")
    encrypt_parser.add_argument("--key-file", required=True, metavar="PATH",
                                help="read key=<base64> from this file only")
    args = parser.parse_args(argv)

    if args.command == "generate-key":
        print("key=" + base64.b64encode(secrets.token_bytes(KEY_LEN)).decode("ascii"))
        return 0

    try:
        key = load_key(args.key_file)
        value = prompt_secret()
        if not value:
            raise SecretError("nothing to encrypt")
        token = encrypt(value, key)
    except (EOFError, KeyboardInterrupt):
        print("\nencrypt.py: encryption cancelled", file=sys.stderr)
        return 1
    except SecretError as exc:
        print(f"encrypt.py: {exc}", file=sys.stderr)
        return 1
    print(token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
