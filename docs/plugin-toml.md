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
| `colour.<column>` | section of text | none | a colour for values past a threshold, or matched whole |

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

**The page uses the same letters.** `every 15m`, `5m ago`, `next run in 12m`,
`paused 3d ago` - one vocabulary, whether the number came from a manifest or
from a clock. Beyond a couple of days it shows the date instead, since `21d
ago` is not something anyone reads as a date.

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

`"off"` is the permanent way of saying "do not run this on a schedule". For
"not this fortnight", use **Pause** on the page instead - it does the same
thing without editing the manifest, and says on screen that it is in force.
See [the-web-page.md](the-web-page.md).

After three failures in a row the interval doubles each time, up to an hour,
and the first success puts it back to normal.

Choose it by how fast the underlying data actually changes. Something hitting a
live API every thirty seconds is a bad neighbour; most reporting plugins want
`"15m"` or `"1h"`.

## `[table] columns`

**Most plugins do not need this.** The header line of the output always decides
the columns and their order; this does not declare them.

What it is, is a guard. When present, the header must match it exactly, in
names and order. A mismatch fails the run and shows both lists - which catches
a script that quietly changed its output instead of putting data under the
wrong headings, and leaves the last good result on screen.

The cost is that the list and the script have to agree for ever: rename a
column in one and the plugin stops until you rename it in the other. Worth it
for a plugin whose output other people depend on, not worth it for most.

`[table] key` is the one that changes what snapgrid does, and belongs in
every manifest.

## `[plugin] group`

Plugins naming the same group are listed together under one heading. There is
nothing to declare anywhere else and no list of groups to maintain: a group
exists because a plugin names it, and stops existing when the last plugin that
named it is gone.

```toml
# plugins/cert-expiry/plugin.toml
[plugin]
name  = "Expiring certificates"
group = "Platform"
```

```toml
# plugins/pod-restarts/plugin.toml
[plugin]
name  = "Pod restarts"
group = "Platform"        # the same string, so the same heading
```

**Groups are ordered alphabetically, and the plugins inside them likewise** -
not by folder name, and not by the order you created them. Plugins with no
group sit together at the top under **Plugins**.

If you want a particular order, put it in the names: a group called
`1 Platform` sorts before `2 Delivery`. That is a workaround rather than a
feature, and if it turns out to matter, explicit ordering is worth adding
properly.

## `[run] command`

A list of arguments, never a command line. There is no shell involved, so
quoting, `&&`, pipes, redirects and `$VARIABLES` do not work - put those in a
script and run the script.

```toml
command = ["python", "main.py"]            # Python
command = ["bash", "report.sh"]            # a shell script
command = ["java", "-jar", "report.jar"]   # Java
command = ["python", "main.py", "--all"]   # fixed arguments are fine
```

**A bare `python` or `python3` means the same interpreter that is running
snapgrid**, whichever of the two names exists. That is what stops a plugin
working in your terminal and failing here because the two found different
Pythons. Use a full path when you deliberately want a different one.

Never pass a secret as an argument: arguments are visible to anyone who can
list processes, and they are shown in the page's Config panel. Use `.env`.

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

## `[colour]`

A number past a limit, or a value out of a small fixed set, reads far faster
with a colour on it than without.

```toml
[colour.used_percent]
"> 90" = "red"
"> 80" = "amber"

[colour.status]
ok      = "green"
expired = "red"
```

The section is named after the column, then one line per rule: what to look
for, and what colour it gets.

### What can be on the left

**A comparison against a number** - `> 90`, `>= 90`, `< 7`, `<= 7`, `= 0`,
`!= 0`. Spacing around the operator does not matter. It has to be in quotes,
because TOML keys with spaces and symbols in them do.

**A value matched whole**, ignoring case and surrounding space. `OK`, `Ok` and
`ok` are the same thing. There is no partial matching and no pattern: a value
either is that word or it is not, so `expired` does not match `expired soon`.

The two can be mixed in one section - useful for a column that is numbers most
of the time and says `unknown` when it cannot tell.

### The first rule that matches wins

**Rules are tried in the order they are written**, which is why `> 90` goes
above `> 80`. The other way round, everything over 90 would be amber, because
it is over 80 too and that rule was reached first.

### What is never coloured

- **Anything no rule matches.** This is what makes it safe on a column that can
  say anything: the values worth noticing stand out, the rest reads normally.
- **An empty cell, against a comparison.** A blank is not zero, so `"< 10"`
  does not paint every row that has no value yet.
- **A word, against a comparison.** `n/a` is not a number and is left alone.

### One section per column

Several columns can be coloured, each with its own section: `[colour.status]`,
`[colour.ms]`. A column of numbers keeps its alignment - the colour goes on
the figures rather than into a badge, so a coloured row still lines up with
the plain ones.

### The colours there are

**`red`, `amber`, `green`, `blue`, `grey`.** That is the whole set, and a
manifest naming anything else is refused with the list.

They are fixed on purpose. A plugin choosing its own shades would be a plugin
deciding what the page looks like, and whatever it picked would have to work in
the light theme and the dark one, against banded rows, and next to the marks
the comparison already uses.

| Colour | What it is for |
|---|---|
| `red` | wrong now, and somebody has to do something |
| `amber` | not wrong yet |
| `green` | right, and worth saying so |
| `blue` | neither good nor bad - a note, a category, something informational |
| `grey` | finished, dismissed, or no longer interesting |

### Where it shows

In the table, and in **Export Excel** - a workbook keeps the colours, so what
you send somebody says what the screen said. A coloured cell also keeps its
colour in a comparison, where an older value's is quieter, as the value is.

The spelling is `colour` throughout, as in the rest of snapgrid; `[color]` is
refused with a message saying so rather than being silently ignored.

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
| `[colour.x] y is '...', which is not a colour snapgrid has` | a colour outside the five. The message lists them |
| `[colour.x] "> eighty" starts like a comparison but is not one` | an operator followed by something that is not a number |
| `[colour.x] names a column that is not in [table] columns` | only catchable when the columns are declared |
| `[colour] x must be a section of its own` | `[colour]` then `status = "green"`, instead of `[colour.status]` |
| `[color] is spelt [colour] here` | the other spelling |
| `[output] fresh_for only means something with [output] file` | the age of a file that was never named |
| `[history] keep must be 0 or more` | a negative number |
| `[plugin] enabled must be true or false` | `enabled = "yes"` |
| `[table] key is "x", which is not one of the columns` | the key names a column that is not declared |
| `timeout is in [history], but it belongs in [run]` | a key written under the wrong section header |
| `[run] timout is not a setting snapgrid knows` | a misspelt key |
| `[runn] is not a section snapgrid knows` | a misspelt section header |
