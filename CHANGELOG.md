<!-- Part of the snapgrid documentation: https://github.com/NovaForge2/snapgrid -->

# Changelog

What changed, and why it might matter to you. Newest first.

The version lives in one place, `snapgrid/__init__.py`, and `./server.py
--version` prints it.

## Unreleased

### Added

- **Comparing runs.** A second picker in the toolbar compares the result on
  screen with the last 2 to 5 runs. Every cell shows what it held in each one,
  newest on top; a dot means the same as the line above, so only what moved is
  written out. A cell that never moved is written once. Rows that appeared are marked `NEW`, rows that have gone are
  marked `GONE` and are shown even though they are absent from the current
  result. **Only what changed** narrows the table to the rows that moved.
- **The history of one cell.** Clicking a value shows what it has been across
  the stored snapshots, with repeats collapsed.
- **`[table] key`**, naming the column that identifies a row so two runs can be
  lined up. Defaults to the first column.
- **Excel export.** The download is now a formatted `.xlsx`: frozen header row,
  a filter on every column, borders, banded rows and column widths. Values are
  stored as numbers only when writing them back gives the identical text, so
  `1.10` stays `1.10` rather than becoming `1.1`.
- **The view is in the address**: `?plugin=…&compare=…&changed=1&theme=…`, so a
  link means the same thing to whoever you send it to.
- **Four more examples**, each with a picture and its own README: disk space,
  certificate expiry, endpoint health, and a directory with no program at all.
- **Continuous integration**: the tests run on Linux, macOS and Windows against
  Python 3.11 to 3.13, with CodeQL and a check that nothing has started
  importing a module that would have to be installed.
- **`SECURITY.md`**, stating plainly that a plugin is code that runs as you.

### Changed

- **The CSV download is gone**, replaced by the Excel one. Excel interprets a
  CSV as it opens it, and a version number is not something to be interpreted.
  CSV remains what a plugin *prints*; it is no longer what you are handed.
- **`Refresh` is now `Run now`**, which is what it does.
- **The theme control moved into the toolbar.** Hiding the left panel used to
  take the only way of changing the theme with it.
- **Columns can be hidden and their widths dragged**; both panels can be
  resized, and the left one hidden entirely.
- **Only the cells that moved are stacked** while comparing. Every cell used to
  hold one line per run, which filled most of the table with dots meaning
  "nothing happened" and buried the values that had actually changed.
- **An edge round the table**, so a narrow one on a wide screen has something
  to sit in; digits of one width, so versions and dates line up; and a heading
  that says it can be clicked to sort.
- **Reset widths** in the Columns menu. Dragged widths are remembered, and
  undoing them meant double-clicking every heading in turn - so a column left
  wide weeks ago made the table look broken with no way back.
- **The toolbar is in groups**, with one button carrying weight and the rest
  quiet until wanted, and it no longer wraps onto a second line.
- **How a plugin stands is next to its name** - when it last ran, when it runs
  next, how much history is kept - rather than in the opposite corner in the
  smallest type on the page.
- **The table is only as wide as its contents.** Each column is the width of
  the widest value in it, and the table stops there. It used to be stretched to
  fill the window, and everything it gained that way became empty space inside
  the columns.
- **`[run] timeout` accepts a duration** such as `"10m"` as well as a number of
  seconds, and `[run] every` understands days and weeks.

### Fixed

- **A key written under the wrong section header is refused** rather than
  ignored. In TOML a key belongs to the section above it, so `timeout = 600`
  appended to the end of a file quietly became `history.timeout` and did
  nothing at all.
- **Editing `plugin.toml` clears the failure backoff.** A plugin that had been
  failing was slowed to hourly retries, and fixing it did not bring it back -
  deleting the database was the only way out. The page now also says when a
  plugin is being tried less often, and when it is next due.
- **A stopped run keeps what it printed.** A timeout used to discard the
  output, which was the only evidence of where it got to.
- **Standard input is closed**, so a script that prompts fails immediately
  instead of hanging until its timeout.
- **The cell history reads columns by name**, not by position. A plugin that
  reordered its columns had old values read out of whichever column now sat at
  that index and reported as this column's history.
- **A column keeps the width you drag it to.** While a plugin was running the
  table was rebuilt once a second, which threw away the heading under the
  pointer and laid the columns out from the stored widths again - so a column
  being narrowed sprang back and the rest of the drag did nothing. The redraw
  now waits for the pointer to come up.
- **Sorting works while comparing.**
- **The comparison follows the result on screen.** Choosing an older snapshot
  used to leave it comparing that result with itself and reporting that nothing
  had changed.
- **Every request is addressed to this machine**, which closes DNS rebinding,
  and `--host` anything but loopback now refuses to start rather than putting
  an unauthenticated tool on the network.

## 0.1.0

First release. Plugins as folders, a schedule, stored history, a sortable and
filterable table, secrets in `.env` with optional encryption, and reading a
table from a CSV file or a spreadsheet as well as from standard output.
