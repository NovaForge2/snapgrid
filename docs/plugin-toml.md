<!-- Part of the snapgrid documentation: https://github.com/NovaForge2/snapgrid -->

# plugin.toml

Every setting a plugin has, what it defaults to, and what it accepts.

**There are two configuration files and they do different jobs.**

| File | Where | Configures |
|---|---|---|
| `snapgrid.toml` | the folder you cloned into, one of them | the **server**: title, port, how many plugins run at once, the banner. See [configuration.md](configuration.md) |
| `plugin.toml` | inside each plugin folder, one per plugin | that **one plugin**: what to run, how often, how long to allow, where its table comes from, how much history to keep |

Anything about a single plugin - including `timeout` - lives in that plugin's
own `plugin.toml`. Nothing about an individual plugin is set server-wide.

Only `[run] command` is required, and even that is optional when
`[output] file` says where to read the table instead.

```toml
[plugin]
name        = "Image versions"
description = "Version per repo per environment"
group       = "Platform"
enabled     = true

[run]
command = ["python", "main.py"]
timeout = "10m"
every   = "15m"

[table]
columns = ["repo", "ENV1", "ENV2"]

[output]
file      = "report.csv"
sheet     = "Summary"
fresh_for = "5m"

[history]
keep = 20
```

## Every key

| Key | Type | Default | Meaning |
|---|---|---|---|
| `plugin.name` | text | the folder name | shown in the left panel and at the top of the table |
| `plugin.description` | text | none | one line under the title |
| `plugin.group` | text | none | heading it is listed under. Same string, same heading |
| `plugin.enabled` | `true` / `false` | `true` | `false` hides it and stops it running |
| `run.command` | list of text | **required**\* | the program and its arguments. No shell |
| `run.timeout` | seconds, or a duration | `300` (5 minutes) | how long a run may take before it is killed |
| `run.every` | duration, or `"off"` | `"15m"` | how long after one run finishes the next starts |
| `table.columns` | list of text | none | if present, the header must match exactly |
| `table.key` | text | the first column | which column names a row, used to line runs up when comparing |
| `output.file` | text | none | read the table from this file instead of stdout |
| `output.sheet` | text | the first sheet | which sheet of an `.xlsx` |
| `output.fresh_for` | duration | none | skip the run while the file is younger than this |
| `history.keep` | whole number | `0` | how many **differing** results to keep |

\* not required when `output.file` is set - a folder with a manifest and a file
is a valid plugin with nothing to run.

## A key has to be in its own section

In TOML a key belongs to the **section header above it**, so a setting appended
to the end of the file lands in whatever section happens to be last:

```toml
[run]
command = ["python", "main.py"]

[history]
keep    = 20
timeout = 600        # this is history.timeout, and does nothing at all
```

That is valid TOML, which is why it is worth knowing about. snapgrid refuses it
rather than ignoring it:

```
timeout is in [history], but it belongs in [run]. In TOML a key belongs to the
section above it, so "timeout = ..." has to be written under [run] to have any
effect
```

Written where it belongs, with the section headers in any order you like:

```toml
[run]
command = ["python", "main.py"]
timeout = 600

[history]
keep = 20
```

A misspelt key is refused the same way, listing the ones that exist:

```
[run] timout is not a setting snapgrid knows. In [run] there is command, every, timeout
```

## Durations

`run.timeout`, `run.every` and `output.fresh_for` all take the same form: a
number and a single letter.

| Unit | Means | Example |
|---|---|---|
| `s` | seconds | `"30s"` |
| `m` | minutes | `"15m"` |
| `h` | hours | `"2h"` |
| `d` | days | `"10d"` |
| `w` | weeks | `"2w"` |

A plain number with no quotes is seconds, so `timeout = 300` and
`timeout = "5m"` are the same thing. `"off"` means no schedule and is accepted
by `every` only.

Anything else is refused when the manifest is read, with a message naming the
key and showing the forms it accepts, rather than being silently ignored.

## `[run] timeout`

How long one run of this plugin may take. When it is exceeded the process **and
any children it started** are killed, the run is marked failed, and the
previous good table stays on screen.

```toml
[run]
timeout = "10m"        # or 600
```

The default is **300 seconds**, which is deliberately short: most plugins
finish in a second or two, and a plugin that hangs occupies one of the few
worker slots until it is stopped. If yours genuinely needs longer, say so
explicitly.

It is per-plugin because it depends entirely on the work. A disk check wants
thirty seconds and a sweep across a dozen environments might want half an hour;
a single server-wide number would have to be the largest of them, which would
let a stuck plugin hold a worker for that long.

When a run is stopped you get, in the log:

```
the plugin was stopped after 600 seconds ([run] timeout).
Last thing it printed: connecting to ENV4
```

or, when it produced nothing at all:

```
the plugin was stopped after 600 seconds ([run] timeout).
It printed nothing at all, so it was stuck before its first output.
```

Whatever it had written to standard output before it was stopped is kept in the
log too, under `--- printed before it was stopped ---`. The half-finished table
is never shown as a result, but it is usually the fastest way to see how far it
got.

**A plugin that hits its timeout every time is usually stuck, not slow.**
Before raising the number, check the three common causes:

- **It is waiting for input.** Nothing is typed at a plugin - standard input is
  closed, so anything that prompts gets an immediate end-of-file rather than
  hanging. An older version of snapgrid left it open; if a plugin of yours used
  to hang for exactly the timeout, this is why.
- **A network call with no timeout of its own.** An unreachable host can block
  for minutes. Pass a timeout to whatever you call out with.
- **It really is slow.** Time it by hand first - what it takes at the command
  line is what it takes here:

  ```bash
  cd plugins/my-plugin && time python3 main.py > /tmp/table.csv
  ```

There is no way to say "no timeout". A plugin that never stops holds a worker
for ever, so `timeout = "off"` is refused.

## `[run] every`

How long after a run **finishes** before the next one starts, so a plugin can
never overlap with itself and a slow one does not fall behind. `"off"` means it
only runs when you press Run now.

The last finish time is stored rather than held in memory, so `every = "10d"`
survives a restart instead of starting its ten days again. If the server was
off when a run came due, it happens once at the next start, not once for every
interval that passed.

This is an interval, not a clock: `"1d"` means "a day after the last one
finished", not "at nine every morning".

After three failures in a row the interval doubles each time, up to an hour,
and the first success puts it back to normal.

Choose it by how fast the underlying data actually changes. Something hitting a
live API every thirty seconds is a bad neighbour; most reporting plugins want
`"15m"` or `"1h"`.

## `[table] columns`

Leave it out and the header line of the output decides the columns and their
order.

When present, the header must match it exactly, in names and order. A mismatch
fails the run and shows both lists - which catches a script that quietly
changed its output instead of putting data under the wrong headings.

## `[table] key`

Which column says **what a row is about**, as opposed to what its values are.
It is what lets two runs be lined up, so that a version changing reads as "this
row changed" rather than "one row left and another arrived".

```toml
[table]
key = "repo"
```

The **first column is the key** unless this says otherwise, which is why it is
rarely needed. Set it when the identifying column is not first:

```
environment,repo,version     ->  key = "repo"
```

Two rules follow from it:

- **The key column is never compared.** A different value there is a different
  row, not a changed one.
- **Keys should be unique.** If two rows are called the same thing, cell by cell
  comparison is impossible, so it falls back to whole rows appearing and
  disappearing, and the page says so rather than guessing.

If `[table] columns` is declared, the key has to be one of them, or the manifest
is refused.

## `[output]`

Where the table comes from when it is not standard output, covered in full in
[where the table comes from](where-the-table-comes-from.md). In short:

- `file` - a `.csv` or `.xlsx` inside the plugin folder. Everything the script
  prints then becomes the log, to either stream.
- `sheet` - which sheet of a workbook, the first one otherwise.
- `fresh_for` - do not run the script at all while the file is younger than
  this. Pressing Run now ignores it.

The file has to be inside the plugin folder: a path starting with `/` or
containing `..` is refused when the manifest is read.

## `[history] keep`

Without it, only the latest result is kept.

With `keep = 20`, the last twenty **different** results are kept. A run
producing exactly the same table as the one before does not use a slot, it just
updates when that result was last seen - so on a fifteen minute schedule,
twenty snapshots means the last twenty times something actually changed, not
the last five hours.

The most recent successful result is always kept even if every run since has
failed, so a broken credential never costs you the last good table.

## When it is wrong

A manifest that cannot be read does not make the plugin disappear - it is
listed with the error, because a plugin vanishing silently is worse than one
that says what is wrong with it.

| Message | Cause |
|---|---|
| `plugin.toml is not valid TOML` | a syntax error in the file |
| `[run] command is required` | no `command` and no `[output] file` either |
| `[run] command cannot be empty` | `command = []` |
| `[run] command must be a list of text values` | a string instead of a list: `command = "python main.py"` |
| `[run] timeout must be a number of seconds, or text like "30m"` | a negative, zero, or something that is neither |
| `[run] timeout cannot be "off"` | a run has to end eventually |
| `[run] every is "..." but should look like "30s", "15m", "2h", "10d", "2w" or "off"` | a unit that does not exist, or words |
| `[table] columns cannot be an empty list` | `columns = []` |
| `[output] file must be inside the plugin folder` | a path starting with `/` or containing `..` |
| `[output] fresh_for only means something with [output] file` | the age of a file that was never named |
| `[history] keep must be 0 or more` | a negative number |
| `[plugin] enabled must be true or false` | `enabled = "yes"` |
| `[table] key is "x", which is not one of the columns` | the key names a column that is not declared |
| `timeout is in [history], but it belongs in [run]` | a key written under the wrong section header |
| `[run] timout is not a setting snapgrid knows` | a misspelt key |
| `[runn] is not a section snapgrid knows` | a misspelt section header |
