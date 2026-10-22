<!-- Part of the snapgrid documentation: https://github.com/NovaForge2/snapgrid -->

# Secrets

## The framework passes values through

A `.env` file in a plugin folder is loaded automatically and given to that
plugin only:

```dotenv
API_USER=myuser
API_PASSWORD=your-password
```

The plugin reads these ordinary environment variables. snapgrid does not
interpret their contents: an `enc:` value is passed through unchanged too.
There is no framework encryption, decryption, key lookup or key configuration,
and the framework never imports `tools/encrypt.py`.

The Config panel and its API show `.env` **variable names only, never values**.
They do not label a value as encrypted, because the framework does not know
what that value means to its plugin.

**A plugin owns its secrets.** If it needs encrypted values, it must explicitly
obtain its key and decrypt them. It must never print plaintext secrets to
stdout, stderr, table files or error messages. snapgrid stores and displays
plugin output; it cannot recognize secrets decrypted inside a plugin, so do
not rely on automatic masking.

## Optional standalone encryption tool

`tools/encrypt.py` is self-contained and uses only the Python standard library.
You can run it directly, or copy it into a plugin that chooses to use its
helpers. It is not required to run snapgrid or to use ordinary `.env` values.

> **This is custom, unaudited cryptography, not a vetted library.** It is meant
> to reduce casual exposure of a password over your shoulder, in a screen share
> or in a file someone glances at. It does not protect a secret from someone who
> can access its key or run code in the plugin's account.
> [SECURITY.md](../SECURITY.md#the-encryption-is-written-in-this-project) explains
> the limits.

### 1. Generate a key explicitly

```bash
python tools/encrypt.py generate-key
```

This prints exactly one line to standard output:

```text
key=<base64-encoded random key>
```

The value is 32 random bytes from the operating system's cryptographic random
source, encoded as base64. It is not a passphrase you invent.

**Generation creates no files**, including key files, `.env` files or
`__pycache__` directories. It does not save the key, choose a location, or modify
existing files. The printed key is a secret; keep it out of screenshots,
recordings and logs.

Save that line yourself in a key file at a location you choose, outside the
repository, with access restricted to the account that needs it. Keep a secure
backup: losing the key makes the corresponding tokens unreadable. The tool
does not manage storage or permissions for you. Shell output redirection would
create a file because you explicitly asked the shell to do so, not because key
generation saves one automatically.

### 2. Encrypt with an explicitly selected key file

The file must contain a `key=` assignment whose value is the base64 key:

```text
key=<your base64 key>
```

Blank lines and lines beginning with `#` are allowed. Duplicate assignments,
other entries and invalid key values are rejected.

```bash
python tools/encrypt.py encrypt --key-file "/path/outside/repo/plugin.key"
```

The file path is required. There is no default path, no `SNAPGRID_KEY_FILE`
lookup, no raw-key command-line argument, and no automatic key generation.
The tool reads only the key file you name, prompts for the plaintext with echo
disabled, and prints only the resulting `enc:` token to standard output.
Errors go to standard error. Neither the key file nor `.env` is written or
changed.

Paste the complete token into the plugin's `.env` yourself, for example:

```dotenv
API_PASSWORD=enc:<the complete token printed by the tool>
```

This alone does not enable decryption. The plugin must implement the explicit
step below before it can use that value as a password.

**Do not put the key or plaintext in command-line arguments or shell commands.**
They can end up in shell history or a process listing. Only the key-file path
belongs in the command; enter plaintext at the hidden prompt.

### Git Bash and hidden input

Some Git Bash terminals do not expose the terminal interface Python needs for
hidden input. The tool stops with an error if it cannot read securely; it does
not fall back to echoing the plaintext or wait on an unusable prompt.

Use a terminal bridge when available:

```bash
winpty python tools/encrypt.py encrypt --key-file "C:/private/plugin.key"
```

Or run the same command without `winpty` in PowerShell:

```powershell
python tools/encrypt.py encrypt --key-file "C:/private/plugin.key"
```

Key generation needs no prompt and does not need this workaround. Do not work
around a prompt failure by putting the plaintext or key in a shell command.

## Explicit decryption inside a plugin

A plugin can use its own solution, or copy `tools/encrypt.py` beside its script
and import the helpers. There is no dependency on the snapgrid package:

```python
import os
from encrypt import decrypt, load_key  # the copy inside this plugin


def read_password(key_file_path: str) -> str:
    key = load_key(key_file_path)
    return decrypt(os.environ["API_PASSWORD"], key)
```

The caller supplies `key_file_path` through the plugin's own chosen mechanism.
It is not a snapgrid setting. `load_key(path)` reads the explicitly selected
`key=<base64 key>` file; `decrypt(token, key)` checks and decrypts the token.
`decode_key(encoded)` and `encrypt(value, key)` are also available if a plugin
needs them. Imports do not generate or load keys automatically.

Plugins run without interactive input. Missing keys, malformed tokens and
failed authentication must fail the run with a safe diagnostic and a non-zero
exit code, without including the key, token or plaintext. Use the decrypted
value only where needed and keep it out of output, logs and exception text.

`.env` is read again at the start of each run, so editing a token does not
require a framework restart. When and how a plugin reloads its key is the
plugin's responsibility.

## Migrating from framework decryption

**This is a breaking change for plugins that use `enc:` values.** Previously,
the framework decrypted them before starting a plugin. Now the plugin receives
the original token, just as it receives every other `.env` value. Plain-value
plugins do not need encryption code.

1. Update each affected plugin to obtain its key and decrypt the values it
   needs, using its own code or an explicit copy/import of the optional helper.
   Never log the decrypted values or assume snapgrid will mask them.
2. Keep the original key for existing tokens. The token algorithm is unchanged;
   generating a different key will not decrypt an old token. If an old key file
   contains only bare base64, prepare a file at a location you choose with the
   same value prefixed by `key=` for the new `load_key`/`--key-file` format.
3. Supply that file explicitly to your plugin and to
   `python tools/encrypt.py encrypt --key-file PATH`. The former
   `./server.py encrypt` command is removed. Neither `~/.snapgrid_key` nor
   `SNAPGRID_KEY_FILE` is used as an automatic key source. Existing key files
   are left untouched; this update does not delete them.
4. Test success and failure paths before resuming scheduled runs. A wrong or
   missing key must produce a useful, secret-free plugin error. The framework
   no longer validates encryption or reports decryption errors on a plugin's
   behalf.

Changing a password means encrypting its new value with the chosen key. If a
key is exposed, choose a new key and re-encrypt every affected value, then
update the plugin's key access. The tool does not rotate, overwrite or remove
keys for you.

## How the optional tool is built

The token format and construction are preserved for compatibility:

- Separate encryption and authentication keys are derived from the supplied
  key so the same derived bytes are not used for both jobs.
- Each value gets a random nonce, so encrypting the same password twice gives
  different tokens.
- The keystream is HMAC-SHA256 in counter mode, XORed with the value.
- A tag over nonce and ciphertext is checked with a constant-time comparison
  before decryption. Modified tokens and wrong keys are rejected.
- The primitives come from `hmac`, `hashlib` and `secrets` in the standard
  library. Newly generated keys are 32 bytes; decoding retains support for
  legacy keys of at least 16 bytes.

The construction remains **unaudited custom code**. Preserving compatibility
and requiring no installation are not substitutes for a cryptographic review.
