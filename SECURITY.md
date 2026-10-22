<!-- Part of the snapgrid documentation: https://github.com/NovaForge2/snapgrid -->

# Security

## What snapgrid is, in one sentence

snapgrid runs programs you put in a folder, on a schedule, with your
credentials, and shows what they print. **It is not a sandbox and does not try
to be one.**

## The boundary that matters most

**Installing a plugin is exactly as serious as running a script yourself.**

A plugin is a program. snapgrid starts it as your user account, with your
environment, your network access, your files and whatever is in its `.env`. A
plugin can do anything you can do.

That means:

- **Read a plugin before you add it**, the way you would read any script
  somebody sent you. "It only reports things" is a convention in
  [AGENTS.md](AGENTS.md), not something enforced by snapgrid.
- **Anyone who can write into your plugins folder can run code as you.**
  Filesystem permissions on that folder are a stronger control than anything in
  the HTTP layer.
- **If the plugins folder is a shared repository**, whoever can push to it can
  run code on every machine that pulls it, arriving silently on the next
  `git pull`. Branch protection and review on that repository are worth more
  than any feature in this project.

There is no plugin sandbox, no permission model, no resource limit beyond
`[run] timeout`, and no review of what a plugin does. Adding one would mean
depending on container or OS facilities that are not available on the locked
down machines this is built for.

## The network

- The server listens on **127.0.0.1** only. Plain HTTP is used deliberately:
  loopback traffic never reaches a network interface, so there is nothing on a
  wire to encrypt.
- **It refuses to listen anywhere else.** There is no authentication of any
  kind, so on any other address whoever reaches the port could read every table
  and start every plugin. `SNAPGRID_ALLOW_ANY_HOST=1` overrides the refusal and
  warns at every startup.
- Every request must be **addressed to this machine**, which closes DNS
  rebinding. A page cannot forge the `Host` header.
- Anything that starts or stops a run is a **POST with a header a cross-site
  page cannot add**, and its `Origin` is checked.
- Plugin output reaches the page as **text, never as HTML**, and commands run
  **without a shell**.

## Secrets belong to plugins

snapgrid loads `.env` values into the plugin environment without interpreting
them. An `enc:` prefix has no special meaning to the framework. It does not
load encryption keys, provide key configuration, decrypt values, or import the
optional encryption tool. The Config panel and its API expose `.env` variable
names only, never their values or an inferred encryption status.

A plugin that needs encryption must explicitly obtain its key and decrypt its
values. **Never print plaintext secrets in tables, logs, output files or error
messages.** snapgrid stores and displays plugin output and cannot recognize
secrets a plugin decrypts internally. There is no automatic decrypted-secret
masking guarantee.

## The encryption is written in this project

The optional, self-contained `tools/encrypt.py` produces `enc:` tokens and can
be copied into a plugin that explicitly opts into using it. It is **custom,
unaudited code**, not a vetted cryptographic library. It uses only the Python
standard library, so nothing needs to be installed.

The helper preserves the existing token format. It derives separate encryption
and authentication keys, uses a random nonce per value, builds a keystream from
HMAC-SHA256, and verifies a tag over nonce and ciphertext before decrypting.
Custom cryptography is worth less trust than a reviewed library regardless of
how the construction looks.

Key generation prints one `key=<base64 key>` line for a new 32-byte random key
and creates no files, including key files or `__pycache__` directories.
Encryption requires an explicit `--key-file` containing `key=<base64 key>` and prompts for plaintext
without echoing it. Neither command chooses a key location, creates a key file,
or changes existing files. There is no default key path or `SNAPGRID_KEY_FILE`
lookup. The framework also never reads any existing key file.

**What it is for:** reducing casual exposure of a password in a screen share,
over your shoulder or in a file someone glances at. A displayed generated key
is itself a secret: keep it out of screenshots and logs.

**What it is not for:** protecting a secret from someone who can access its key
or run code in the plugin's account. Choosing separate storage does not create
a sandbox around the plugin or its decrypted data.

If that is not enough for a particular secret, do not put that secret in a
`.env` file. See [docs/secrets.md](docs/secrets.md) for the explicit key-file
workflow and the migration required for plugins that previously relied on
framework decryption.

## What snapgrid itself connects to

**Nothing but this machine.** Audited rather than asserted:

- The server **listens** on 127.0.0.1 and refuses to listen anywhere else.
- The only outbound request anywhere in the package asks `http://<host>:<port>/api/plugins`
  before starting, to tell "a snapgrid is already running here" apart from
  "something else has this port". `<host>` is the address it is about to bind,
  which is loopback.
- The page loads **no external anything**: no CDN, no fonts, no analytics, no
  telemetry. Its only requests are relative `/api/...` paths to the server you
  opened. The favicon is an inline `data:` URI.
- Reading an `.xlsx` **does not resolve external entities**, so a spreadsheet
  containing `<!ENTITY x SYSTEM "http://...">` is refused rather than fetched.
  There is a test for that.
- `--open` opens a browser at the local address and nothing else.

You can check this yourself on a running instance:

```bash
lsof -p "$(python3 -c "import json;print(json.load(open('plugins/.snapgrid/server.json'))['pid'])")" -a -i -P
```

**Your plugins are a different matter.** They are your programs and they do
whatever you wrote them to do - two of the shipped examples deliberately reach
the internet, one to read certificate expiry dates and one to time HTTP
endpoints. That is the point of them, and it is also why reading a plugin
before adding it matters.

## What is checked automatically

- **The tests** run on every push and pull request, on Linux, macOS and Windows
  against Python 3.11 to 3.13, and a build fails if anything starts importing a
  module that would have to be installed.
- **CodeQL** analyses the source on every push and once a week, with the
  extended security rules.
- **Secret scanning with push protection** is on, so a commit containing a
  credential is refused before it reaches the repository.
- **Dependabot** watches the versions of the actions used by those workflows.

None of that inspects your plugins. They are your code, on your machine.

## Reporting something

Open an issue at
<https://github.com/NovaForge2/snapgrid/issues>. If you would rather not
describe it publicly, open an issue saying only that you have found something
and how to reach you.

This is a small project maintained by one person. There is no guaranteed
response time and no bounty.

## Supported versions

The latest commit on `main`. This is version 0.1 and there are no maintained
release branches.
