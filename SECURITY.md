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

## The encryption is written in this project

Values in `.env` can be stored as `enc:...`. That encryption is **custom code
in this repository**, not a vetted library, because the project cannot depend
on anything that has to be installed.

It derives separate encryption and authentication keys from a random 32 byte
key, uses a random nonce per value, builds a keystream from HMAC-SHA256, and
verifies a tag over nonce and ciphertext before decrypting. Those are the right
shapes. It has not been audited, and custom cryptography is worth less trust
than a reviewed library regardless of how it looks.

**What it is for:** stopping a password being readable over your shoulder, in a
screen share, or by someone glancing at a file. It raises the cost of casual
exposure.

**What it is not for:** protecting a secret from someone who already has access
to your account. The key lives in `~/.snapgrid_key`, readable by you, so
anything running as you can decrypt anything you can.

If that is not enough for a particular secret, do not put that secret in a
`.env` file.

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
