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
- **`[colour]`**, which colours a value worth noticing: a disk `"> 90"` percent
  full in red, a certificate with `"< 7"` days left in red, a `status` of
  `expired` in red. Either a comparison against a number or a value matched
  whole, tried in the order written, with the first match winning. Five colours
  and no more - red, amber, green, blue, grey - and anything no rule matches is
  left plain, including empty cells and words tested against a number. The
  colour follows the value into the Excel export, and a column of numbers keeps
  its alignment. The disk space, certificate expiry and endpoint health
  examples all use it.
- **An eighth example, `listening-ports`**: what holds which port, with the
  pid and the command that ends it - `kill -9 n` or `taskkill /F /PID n`,
  whichever this machine uses. It asks `lsof`, then `ss`, then `netstat`,
  trying what is there rather than deciding by the name of the operating
  system. It reports and does not act: the command is text in a cell.
- **A seventh example, `notes`**: a list you keep yourself in a CSV, coloured
  by status. It is where to write down *why* a table says what it says - and
  it is deliberately not a comment system, since snapgrid has no second user
  to comment to.
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
- **Pausing.** A pause control in front of every plugin in the left panel takes
  it off the schedule, and one at the head of the panel does the lot. The same
  control, as a play triangle, puts them back. For a machine with little to
  spare and more plugins than you need running this fortnight. The last result
  stays, `Run now` still works, and nothing is written to `plugin.toml` - the
  plugin folder is yours and is often a repository. Because a paused plugin
  looks exactly like a current one, it is marked in the list, in the heading
  and in the plugin count.
- **The text in the table can be made bigger or smaller**, 10px to 20px, with
  `A-` and `A+` in the toolbar. The browser's own zoom moves the whole page,
  including the panels that were already right; this is the grid alone, and
  the padding and row heights scale with it. Smaller text fits more columns on
  screen at once, which is usually why anybody wants it.
- **One vocabulary for time.** The page said `every 15m` in one place,
  `5 min ago` in the next and `in 12 min` in a third. It is now `s`, `m`, `h`
  and `d` everywhere - the same letters `plugin.toml` uses - and an hour reads
  as `1h` rather than `60m`, a day as `1d` rather than `24h`. A run due after
  today carries its date, where it used to show a bare clock time that read as
  this afternoon.
- **A Stop button**, at the foot of the left panel. The terminal snapgrid was
  started from is usually somewhere else by the time you want it closed. It
  asks first, stops as cleanly as Ctrl+C does, and then shows the command to
  start it again - there being nothing left on the page that works. It is
  behind the same guards as every other write, so no other site can reach it.
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
- **The pictures show what the program does now.** Every screenshot and the
  comparison animation were of the older interface. `tools/make-screenshots.py`
  rebuilds all of them from a running server in one go, so they can be redone
  with the change that makes them wrong rather than drifting.
- **"1 row"**, not "1 rows".
- **Every example declares the same things.** Three of the six set `[table]
  key`, three did not; one kept no history; two wrote the timeout as a bare
  number. Copying one as a starting point gave a different template each time.
  They all now set a key and a history, and only one declares `[table] columns`
  - which is a guard against a script changing its output, not a declaration of
  the columns, and the documentation now says so.
- **`[run] timeout` accepts a duration** such as `"10m"` as well as a number of
  seconds, and `[run] every` understands days and weeks.

### Changed

- **The toolbar is shorter.** It holds what is done to the table - Run now,
  which result to show, what to compare it with, search, Export Excel - and
  ends with a **More** menu holding the text size, the theme, Log and Config.
  **Columns** and **Clear filters** have moved down beside the table, with the
  row count next to them, because they are about what this table shows rather
  than about snapgrid. Nothing was removed and nothing works differently.
- **A compared row is ruled across.** Every line in every cell of the row is
  now the same height and carries a faint guide, including the cells written
  once, so a value can be traced back to the run it belongs to in the strip
  above. That strip now also says what a dot means, which was being guessed at
  - and the two guesses, "the same" and "nothing there", are opposites.
- **A paused plugin says `Paused · Manual runs available.`** as a chip under
  its name, with how long it has been paused on hover. The old sentence said
  the schedule was leaving it alone, which is the half nobody was asking
  about.
- **The keyboard reaches the table.** A heading can be focused and sorted with
  Enter or Space, and keeps the focus afterwards; every control draws the same
  accent focus ring; the pause controls say what state they are in as well as
  what pressing them would do, and name the plugin they belong to.

### Fixed

- **The listening ports example now fills in the command line on Windows.** It
  was empty on every row there, which also left the `program` column saying
  `java.exe` and `python.exe` - the real name is read out of the command line,
  and there was none. `wmic` is asked, or PowerShell where `wmic` has been
  removed, and a quoted program path with a space in it is kept in one piece.
  All the ways of asking are tried rather than one being picked by the name of
  the operating system: a Python under Git Bash reports a Windows machine as
  `posix`, and its `ps` answers nothing about a Windows pid.
- **A key written under the wrong section header is refused** rather than
  ignored. In TOML a key belongs to the section above it, so `timeout = 600`
  appended to the end of a file quietly became `history.timeout` and did
  nothing at all.
- **Editing `plugin.toml` clears the failure backoff.** A plugin that had been
  failing was slowed to hourly retries, and fixing it did not bring it back -
  deleting the database was the only way out. The page now also says when a
  plugin is being tried less often, and when it is next due.
- **`stop` matches the host the server wrote down**, not the one on the
  command line. For a server bound to something other than loopback, the
  check looked for a listener on 127.0.0.1 and would have stopped whatever
  answered there instead.
- **A host given by name is recognised.** `start --host localhost` records
  that name, while the operating system reports numbers - so the listener was
  rejected as a stranger and `stop` said "snapgrid is not running" while it
  ran. Names are resolved before they are compared.
- **`stop` never stops the wrong thing.** Finding the server by port picked
  whichever process the operating system listed first, so with something else
  listening on the same port on a different address, `stop` could end that
  instead and report success while snapgrid carried on. The listening address
  has to match now, and where two cannot be told apart nothing is stopped.
- **Resume all works when a plugin is disabled.** The page counted a disabled
  plugin as one the schedule would run; the server did not. "Everything is
  paused" never became true, so the control stayed on Pause and there was no
  way back.
- **A value that is not a real number is not compared.** `NaN`, `inf` and
  `Infinity` are numbers to Python and not to a browser, so a cell saying `NaN`
  came out coloured in the Excel export and plain on the page - the one thing
  colouring in two places must never do.
- **The command the stopped page shows can be typed.** A plugins folder with a
  space in its name produced a command that fails, and the port was dropped
  whenever it happened to be 8765 - even with `snapgrid.toml` saying something
  else, in which case following the instruction moved the address. The port is
  now named whenever a bare restart would land somewhere different.
- **`stop` stops the server it can see.** It read the state file inside the
  plugins folder, so `./server.py stop` typed without the `--dir` that
  `start` was given looked in the wrong place, printed "snapgrid is not
  running" and left it running. `status` said the same. Both now fall back to
  asking whatever is on the port, and `status` names the folder that server
  was actually started from. Only something that answers as snapgrid is ever
  acted on, so another program on 8765 is still left alone.
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
- **The headings stay put while the rows scroll.** They were declared sticky
  and then quietly un-stuck: a later rule gave them `position: relative` so the
  resize grip had something to anchor to, which replaced the sticky position
  set above it. Both rules read correctly on their own, and the headings
  scrolled away for ten days without anything looking broken. There is now a
  test that reads the stylesheet and refuses a later rule that takes the
  property away again.
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
