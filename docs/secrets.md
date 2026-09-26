<!-- Part of the snapgrid documentation: https://github.com/NovaForge2/snapgrid -->

# Secrets

> **The encryption here is written in this project, not taken from a library.**
> snapgrid cannot depend on anything that has to be installed, so there is no
> `cryptography` package behind this. It has not been audited.
>
> It is meant to stop a password being readable **over your shoulder, in a
> screen share, or by someone glancing at a file**. It is not meant to protect
> a secret from someone who already has your account - the key sits in
> `~/.snapgrid_key`, so anything running as you can read anything you can.
>
> If a particular secret needs more than that, do not put it in a `.env` file.
> [SECURITY.md](../SECURITY.md) has the reasoning in full.

A `.env` file in a plugin folder is loaded automatically and given to that
plugin only:

```
OC_USER=myuser
OC_PASSWORD=hunter2
```

Plain values work. But a password sitting in a file is readable by anyone
looking at your screen during a demo, so values can be stored encrypted:

```bash
./server.py encrypt
```

It asks for the value without echoing it, and prints a line to paste into
`.env`:

```
OC_PASSWORD=enc:u8Vj97KHcvUDrRuIj2NDwkkYQwY93c/T77JwVZvFvtDvCydOTtV...
```

The plugin reads `OC_PASSWORD` from its environment as normal and knows nothing
about any of this.

## The key

**You do not choose the key and you never type one.** The first time you run
`./server.py encrypt`, snapgrid generates one: 32 random bytes from the
operating system's cryptographic random source, stored base64 in
`~/.snapgrid_key` with permissions that keep it to your account.

A passphrase you invented would be the weak point - people pick memorable
things, and a memorable key is a guessable key. A random 32 byte key cannot be
guessed, and since you never have to remember it, there is no reason for it to
be anything else.

Every later `encrypt` reuses that same key. Values encrypted with it can be
decrypted only by it.

- It lives outside the repository, so it cannot be committed by accident.
  Override the location with `SNAPGRID_KEY_FILE` if you need it elsewhere.
- **Back it up.** If the file is lost, every encrypted value is unreadable and
  must be re-encrypted from the original passwords. Copy it into a password
  manager the first time it appears.
- If the key is ever exposed, delete it, run `encrypt` again to generate a new
  one, and re-encrypt every value.
- Changing a password means re-encrypting **that one value** with the same key.
  You only need a new key if the key itself is exposed, and then everything
  encrypted with it has to be redone.
- No restart is needed. `.env` and `plugin.toml` are read again at the start of
  every run, so you edit and click Run now.
- A wrong or missing key fails the run with a clear message instead of handing
  the script nonsense.
- Decrypted values are **masked** as `****` anywhere they would otherwise be
  shown or stored, so a script that logs its own command line does not put your
  password in the run log and keep it there.

**What this protects against, honestly:** someone reading your screen. It is not
protection against someone who can use your machine - the key is on the same
disk, and anything running as you can read it.

## How it is built, for anyone reviewing it

Set out plainly so it can be judged rather than taken on trust:

- Two separate keys are derived from the stored 32 byte key, one for the
  keystream and one for authentication, so the same bytes are never used for
  both jobs.
- Each value gets a **random nonce**, so encrypting the same password twice
  gives different output.
- The keystream is **HMAC-SHA256** in counter mode, xored with the value.
- A **tag over nonce and ciphertext** is checked before anything is decrypted,
  and compared with a constant time comparison, so a modified value is rejected
  rather than silently producing rubbish.
- Everything comes from `hmac`, `hashlib` and `secrets` in the standard
  library. Nothing is invented at the primitive level.

The shapes are right, and it is still **unaudited code written for this
project**. That is the trade for needing no installation, and it is why the
paragraph above describes what it is actually for.

