# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 NovaForge2
"""Encrypted values in .env files.

A plugin folder may contain a .env file. Every KEY=VALUE line in it is added to
the environment of that plugin, and only that plugin. A value may be stored
encrypted so that it is not readable over someone's shoulder during a demo:

    OC_USER=myuser
    OC_PASSWORD=enc:Zm9vYmFyLi4u

Encrypted values are protected by a single key file, by default ~/.snapgrid_key.
This hides secrets from a screen, a screenshot or a casual look at the file. It
is not protection against someone who can read the machine: the key sits on the
same disk, and anything running as you can read it.

The construction is deliberately boring and uses only the standard library:
a random nonce per value, a keystream from HMAC-SHA256, and an HMAC tag that is
checked before anything is decrypted, so a wrong key fails loudly instead of
returning nonsense.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets as _secrets
import stat
from pathlib import Path

PREFIX = "enc:"
NONCE_LEN = 16
TAG_LEN = 32
KEY_LEN = 32
KEY_FILE_ENV = "SNAPGRID_KEY_FILE"


class SecretError(Exception):
    """Something is wrong with the key or with an encrypted value."""


def key_path() -> Path:
    override = os.environ.get(KEY_FILE_ENV)
    if override:
        return Path(override).expanduser()
    return Path.home() / ".snapgrid_key"


def load_key(create: bool = False) -> bytes:
    path = key_path()
    if not path.exists():
        if not create:
            raise SecretError(
                f"no key file at {path}. Run 'python -m snapgrid encrypt' once "
                f"to create one."
            )
        key = _secrets.token_bytes(KEY_LEN)
        path.write_text(base64.b64encode(key).decode() + "\n", encoding="utf-8")
        try:
            path.chmod(stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            # Not every filesystem supports this, and that is acceptable.
            pass
        return key

    raw = path.read_text(encoding="utf-8").strip()
    try:
        key = base64.b64decode(raw, validate=True)
    except Exception as exc:
        raise SecretError(f"key file {path} is not valid base64") from exc
    if len(key) < 16:
        raise SecretError(f"key file {path} is too short to be a key")
    return key


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
    enc_key, mac_key = _subkeys(key)
    nonce = _secrets.token_bytes(NONCE_LEN)
    plaintext = value.encode("utf-8")
    ciphertext = _xor(plaintext, _keystream(enc_key, nonce, len(plaintext)))
    tag = hmac.new(mac_key, nonce + ciphertext, hashlib.sha256).digest()
    return PREFIX + base64.b64encode(nonce + ciphertext + tag).decode()


def decrypt(token: str, key: bytes) -> str:
    if not token.startswith(PREFIX):
        return token
    try:
        raw = base64.b64decode(token[len(PREFIX):], validate=True)
    except Exception as exc:
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
    return _xor(ciphertext, _keystream(enc_key, nonce, len(ciphertext))).decode("utf-8")


def parse_env_file(text: str) -> list[tuple[str, str]]:
    """Read KEY=VALUE lines, ignoring blanks and comments."""
    pairs: list[tuple[str, str]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        key, sep, value = line.partition("=")
        if not sep:
            continue
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key:
            pairs.append((key, value))
    return pairs


def load_env(env_file: Path) -> tuple[dict[str, str], list[str]]:
    """Return the variables from a .env file, plus the values that were secret.

    The second list is what has to be masked before anything is shown or stored.
    """
    if not env_file.exists():
        return {}, []

    pairs = parse_env_file(env_file.read_text(encoding="utf-8"))
    values: dict[str, str] = {}
    secret_values: list[str] = []
    key: bytes | None = None

    for name, value in pairs:
        if value.startswith(PREFIX):
            if key is None:
                key = load_key()
            try:
                value = decrypt(value, key)
            except SecretError as exc:
                raise SecretError(f"{name}: {exc}") from exc
            if value:
                secret_values.append(value)
        values[name] = value

    return values, secret_values


def mask(text: str, secret_values: list[str]) -> str:
    """Replace known secret values with **** so they never reach a screen or the database."""
    if not text or not secret_values:
        return text
    for value in sorted(secret_values, key=len, reverse=True):
        if len(value) >= 4:
            text = text.replace(value, "****")
    return text
