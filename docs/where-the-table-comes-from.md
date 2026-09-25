<!-- Part of the snapgrid documentation: https://github.com/NovaForge2/snapgrid -->

# Where the table comes from

There are five ways a plugin can produce its table, and they are combinations
of two questions: **is there a program to run**, and **where does the data
end up**. Everything else follows from those.

| You have | `plugin.toml` needs | The table is | Everything printed becomes |
|---|---|---|---|
| a script that prints CSV | `[run] command` | its standard output | the log (standard error only) |
| a script that writes a CSV file | `[run] command` + `[output] file` | that file | the log (both streams) |
| a script that writes a spreadsheet | `[run] command` + `[output] file` ending `.xlsx` | that sheet | the log (both streams) |
| a CSV file somebody maintains | `[output] file` only | that file, re-read each run | - |
| a spreadsheet somebody maintains | `[output] file` only, ending `.xlsx` | that sheet, re-read each run | - |

## 1. A script that prints CSV

The default, and the simplest thing that works.

```toml
[plugin]
name = "Expiring certificates"

[run]
command = ["bash", "check.sh"]
```

Standard output is the table and must contain nothing else. Standard error is
the log. Exit `0` means success.

## 2. A script that writes a CSV file

For a script that already writes a file, or prints progress you would rather
not have to silence.

```toml
[plugin]
name = "Nightly report"

[run]
command = ["python", "report.py"]

[output]
file = "report.csv"
```

The script's own output no longer matters: **everything it prints, to either
stream, becomes the log**. Only the file is the table.

The file must be written by the run that is happening. If a run produces
nothing and an older file is still sitting there, it is refused rather than
shown, with the time it was actually written:

```
'report.csv' was last written at 2026-09-23 14:02, before this run started,
so it is left over from an earlier one. Refusing to show stale data as if it
were current.
```

## 3. A script that writes a spreadsheet

Identical to the above; the extension decides how the file is read.

```toml
[run]
command = ["python", "export.py"]

[output]
file  = "report.xlsx"
sheet = "Summary"        # optional, the first sheet otherwise
```

## 4. A CSV file somebody maintains

No program at all. A folder containing a manifest and a file is a plugin.

```toml
[plugin]
name = "Contact list"

[run]
every = "1h"

[output]
file = "contacts.csv"
```

The file is re-read on each run, so editing it updates the table within the
interval. An unchanged file does not count as a change, so history stays
meaningful. There is no staleness check here - nothing is supposed to have
written the file, so its age means nothing.

## 5. A spreadsheet somebody maintains

The same, with a workbook.

```toml
[plugin]
name = "Team owners"

[run]
every = "6h"

[output]
file  = "owners.xlsx"
sheet = "Current"
```

This is the case for a file a colleague keeps up to date: they edit the
spreadsheet where they always have, and it appears as a searchable, filterable
table without anyone writing any code.

## What is true in every case

- **The first row is the header.** Column names come from it.
- **`[table] columns` is checked if present**, against that first row, whatever
  the source. A mismatch fails the run and shows both lists.
- **History works the same way.** Identical results do not use a slot, so
  `[history] keep = 20` means the last twenty times something actually changed.
- **Secrets are masked** in the table and in the log, whether they came from
  stdout or from a file.
- **The file must be inside the plugin folder.** A path starting with `/` or
  containing `..` is refused when the manifest is read.

## Spreadsheets in detail

No library is required: an `.xlsx` is a zip archive of XML, and the standard
library reads both.

**Handled:** text, numbers, booleans, dates and times, shared strings, inline
strings, text with mixed formatting, the stored result of a formula, rows with
gaps, columns past Z, and choosing a sheet by name.

**Dates** deserve a note. Excel stores a date as a count of days, and whether a
number is a date is decided by the format applied to the cell rather than by
the value. snapgrid reads the workbook's styles to tell the two apart, and
writes dates as `YYYY-MM-DD` (or `YYYY-MM-DD HH:MM`) so they sort correctly as
text.

**Not handled:** the old binary `.xls` format, charts, images, and formulas
that have never been calculated and so have no stored value. An `.xls` is
refused with a message saying to save it as `.xlsx` or `.csv`.

## Choosing between them

If you are writing something new, **print CSV to standard output**. It is the
least to go wrong, it needs no manifest section, and the script can be run by
hand to see exactly what snapgrid will see.

Use `[output] file` when the script already exists and writing to a file is
what it already does. Rewriting a working script to satisfy a contract is the
wrong way round.

Use a plugin with no program when the data is a file somebody maintains rather
than something to compute.
