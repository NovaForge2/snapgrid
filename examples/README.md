<!-- Part of the snapgrid documentation: https://github.com/NovaForge2/snapgrid -->

# Examples

Seven plugins that run anywhere, with nothing to configure and no credentials.

```bash
./server.py --dir examples
```

That points snapgrid at this folder instead of `plugins/`, so your own work is
untouched and nothing is copied anywhere. It gets its own database and its own
port: one plugins folder is one workspace.

To keep one, copy the folder:

```bash
cp -r examples/disk-space plugins/
```

It appears in the page within ten seconds. No restart.

## What is here

| Example | What it does | Worth reading it for |
|---|---|---|
| [disk-space](disk-space/) | free space on every filesystem | the simplest useful plugin; plain numbers with no units |
| [certificate-expiry](certificate-expiry/) | when each TLS certificate runs out | network calls with their own timeout; one row failing without failing the run |
| [endpoint-health](endpoint-health/) | status and response time per URL | why a 404 belongs in the table and not the log |
| [team-directory](team-directory/) | who owns what | **a plugin with no program at all** - a manifest and a CSV |
| [hello-table](hello-table/) | reads `data.json` next to it | the smallest complete script |
| [version-matrix](version-matrix/) | invented versions that drift | watching the history and the comparison fill up |
| [notes](notes/) | a list you keep yourself | **colouring a value** with `[colour]`, and why a hand-set status needs a date |

Each folder has its own README with a picture of it running, an explanation of
how it works, what to change, and which part of the contract it demonstrates.

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="certificate-expiry/screenshot-dark.png">
    <img src="certificate-expiry/screenshot.png" alt="One of the examples running in snapgrid: certificate expiry dates for three hosts, sortable by days remaining" width="900">
  </picture>
</p>

## Read them in this order

**[hello-table](hello-table/)** first, to see the shape: get rows from
somewhere, print CSV, exit 0.

**[disk-space](disk-space/)** next. It is the same shape doing something real,
and it introduces the two rules that catch people out: emit plain numbers with
no units, and fail the run rather than print an empty table.

**[endpoint-health](endpoint-health/)** or
**[certificate-expiry](certificate-expiry/)** when your plugin has to talk to
something. Both are mostly about what to do when part of the work fails, which
is most of what a real plugin's code turns out to be.

**[team-directory](team-directory/)** when the data is not computed at all.

**[notes](notes/)** for the same shape put to a different use, and for
`[colour]` - which has nothing to do with notes and belongs on any column with
a small fixed set of values.

## Then write your own

[AGENTS.md](../AGENTS.md) in the repository root is the full contract, written
so it can be handed to an AI agent as the brief for a new plugin. It is just as
readable by a person.
