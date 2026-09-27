# Team directory

**A plugin with no program at all.**

There is no script in this folder. There is a manifest and a CSV file, and that
is a complete plugin: snapgrid re-reads the file on every run, so editing the
file updates the table.

```
service,team,owner,on_call,runbook
payments-api,Payments,A. Novak,payments-oncall,https://wiki.example.internal/payments
orders-api,Orders,R. Silva,orders-oncall,https://wiki.example.internal/orders
```

## Try it

```bash
cp -r examples/team-directory plugins/
```

Open the page, then edit `plugins/team-directory/directory.csv` in any editor
and save. The table updates within the hour — or press **Run now** to see it
immediately.

## The manifest

```toml
[run]
every = "1h"          # no command, only how often to re-read the file

[output]
file = "directory.csv"
```

`[run] command` is missing, and that is the whole trick. When `[output] file`
names a file and there is no command, snapgrid has nothing to run and simply
reads the file.

## When to use this

When the data is something **somebody maintains** rather than something to
compute. Ownership, contacts, runbook links, a list of environments, which
team is responsible for what — things that live in somebody's head, or in a
spreadsheet attached to an email from March.

Putting it here gets you the same sortable, filterable table as any other
plugin, alongside the ones that are generated, without writing any code.

## A spreadsheet works too

The same folder, with the manifest pointing at a workbook:

```toml
[output]
file  = "directory.xlsx"
sheet = "Current"        # optional; the first sheet otherwise
```

This is the case for a file a colleague keeps up to date. They edit the
spreadsheet where they always have, and it appears as a searchable table
without anybody writing anything. Dates, numbers and formula results are all
read; the old binary `.xls` is not supported.

## What this example shows

- **A plugin need not run anything.** The four ways a table can arrive are set
  out in [where the table comes from](../../docs/where-the-table-comes-from.md).
- **A missing value is an empty field.** `notifications-api` has no owner, so
  that field is empty — not `None`, not `N/A`, not `-`. An empty cell reads as
  "nobody has said", and the filter can find them all at once. `N/A` is a value
  that sorts among the names.
- **No staleness check here.** Nothing was supposed to write this file, so its
  age means nothing. That check only applies when a script was meant to produce
  the file during the run.
- **`[history] keep = 20`** records who owned what and when it changed — which
  turns out to be the question people actually ask of a directory.

## One thing to be careful of

This file is data, but it is still inside a plugin folder. Anyone who can write
into your plugins folder can run code as you, so the same care applies as to
any other plugin — see [SECURITY.md](../../SECURITY.md). A CSV cannot execute,
but a `main.py` appearing next to it can.
