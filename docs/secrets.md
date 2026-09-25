<!-- Part of the snapgrid documentation: https://github.com/NovaForge2/snapgrid -->

# Secrets

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
  every run, so you edit and click Refresh.
- A wrong or missing key fails the run with a clear message instead of handing
  the script nonsense.
- Decrypted values are **masked** as `****` anywhere they would otherwise be
  shown or stored, so a script that logs its own command line does not put your
  password in the run log and keep it there.

**What this protects against, honestly:** someone reading your screen. It is not
protection against someone who can use your machine - the key is on the same
disk, and anything running as you can read it.

