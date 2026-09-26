<!-- Part of the snapgrid documentation: https://github.com/NovaForge2/snapgrid -->

# The web page

**Light or dark:** the button in the bottom left corner cycles `auto`, `light`
and `dark`. `auto` follows your operating system, which is the default. The
choice is remembered in your browser and is not shared with anyone else looking
at the same instance.

- **Left panel** - plugins grouped by `group`, with a status dot: green for a
  good run, red for a failure or a broken `plugin.toml`, blue while running.
  The **&#171;** in its corner hides it, and the **&#187;** that appears brings
  it back; `[` does both from the keyboard. Worth it on a laptop, where 260px
  of plugin names is 260px not spent on the table.
- **Run now** runs the plugin **now**, in the background, whatever the schedule
  says. It jumps the queue ahead of anything waiting, ignores `fresh_for`, and
  ignores the slowdown after repeated failures - asking by hand means wanting
  new data. You can go to another plugin while it works. **Cancel** stops it,
  including anything it started, and the previous good table stays.
- **The table** does what a spreadsheet does: click a heading to sort, click the
  small arrow next to it for a checkbox list of every value in that column with
  counts, and use the search box to search everything at once. Columns holding
  only numbers sort as numbers, and columns holding only version numbers sort so
  that `2.9.0` comes before `2.14.1`.
- **Columns** chooses which columns to show. Unticking one takes it off the
  screen without taking it out of the table: filters, sorting and the search
  box still see it, and it comes straight back. The row count says how many are
  hidden, and the button is highlighted while any are. **Show all** puts them
  back. The last visible column cannot be hidden - an empty table is not a view
  of anything.
- **Column widths** are dragged by the edge of a heading. Double-click an edge
  to let that column size itself again. Both the widths and the hidden columns
  are remembered per plugin, in your browser only.
- **Export CSV** downloads exactly what you are looking at.
- **The dropdown next to Run now** appears once there is history, and shows any
  earlier result.
- **The second dropdown compares runs** - see below.
- **Log** and **Config** are buttons at the right of the toolbar. They open a
  panel over the right of the table, with a tab for each and a close button, so
  a panel you are not using costs the grid no space at all. Escape closes it.
- **Log** is the plugin's standard error, updating while it runs.
  **Following** keeps the newest line in view. Scrolling up turns it off, so
  reading something is never fought over; scrolling back to the bottom turns it
  on again. The button does the same thing deliberately, and the choice is
  remembered.
- **Config** shows what this plugin is set up to do:

  | | |
  |---|---|
  | folder | where the plugin lives, so you can go and edit it |
  | runs | the exact command, after `python` has become a real interpreter. This is the line that answers "why does it work in my terminal but not here?" |
  | .env | which variables it loads and which are encrypted - **names only, never values** |
  | plugin.toml | the file itself, read from disk each time you open the panel, with comments, headings, keys, strings and numbers coloured |

  It opens by itself for a plugin whose `plugin.toml` cannot be read, since the
  file is exactly what you need to see at that moment.

  This panel is not a permission boundary. Anyone who can reach the page can
  read it, and can already run the plugin and see its output, which reveals far
  more than its configuration does. Keep secrets in `.env`, never as arguments
  in `command` - arguments are visible to anyone who can list processes,
  and they would be shown here too.

## Comparing runs

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="diff-dark.png">
    <img src="diff.png" alt="A table comparing four runs" width="900">
  </picture>
</p>

The second dropdown chooses how far back to look: **off**, **the one before**,
or the **last 3, 4 or 5 runs**. It only offers as many as have been stored, and
it is off until you ask.

With it on, every cell in a row holds one line per run, newest on top. That is
deliberate: if one cell stacked and its neighbour did not, line two would not
mean the same thing across the row and you could not read sideways.

| What you see | What it means |
|---|---|
| a value in bold, on top | what it is now |
| a smaller, quieter value below | what it was in that earlier run |
| **a dot** | the same as the line above - nothing happened |
| a tinted cell | something moved in that cell |
| `NEW` and a green edge | the row was not there in the earlier runs |
| `GONE` and a red edge | the row is not in the current result. It is shown anyway, because a thing disappearing is worth noticing |
| `not there` | the row did not exist in that particular run |

**Nothing is struck through.** An older value was not deleted; it is just older.

**Which run is which** is written once in the strip above the table -
`1 now · 2 25 Sep 23:27 · 3 25 Sep 20:40` - because there is no room for a date
inside a cell and every cell shares the same runs. The strip also counts what
moved, and holds the **Only what changed** tick, which narrows a forty row table
to the rows that did something.

**Click any value** to see the history of that one cell, which goes back as far
as the stored snapshots rather than as far as the comparison:

```
now            2.17.0
25 Sep 23:27   2.16.0
25 Sep 20:40   2.15.0
22 Sep 11:30   2.14.1
```

Two things it will refuse to do, rather than guess:

- **Columns that differ between runs.** If a run had four environments and the
  next had five, there is no honest way to line the columns up, so it says so.
- **Rows that cannot be told apart.** Rows are matched by the column that names
  them - the first one, or whichever `[table] key` names. If two rows share a
  name, it falls back to whole rows appearing and disappearing.

Five runs is the most, and that is a limit of height rather than arithmetic:
five runs of a forty row table is a very tall page.

## The address bar

What you are looking at is kept in the address, so a link means something to
whoever you send it to:

```
http://127.0.0.1:8765/?plugin=image-versions&compare=3&changed=1&theme=dark
```

| | |
|---|---|
| `plugin` | which plugin to open |
| `compare` | how many runs to show in each cell, 1 to 5. 1 is off |
| `changed` | `1` to start with **Only what changed** ticked |
| `theme` | `light`, `dark` or `auto`, for a link that looks the same on any machine |

The theme button still overrides it, and your own choice is what is remembered
afterwards.

## Resizing

Three things can be dragged: the left panel, the Log/Config panel, and the edge
of any column heading. The two panels are dragged by the edge between them and
the table. Double-click an edge to put it back where it started, and
arrow keys move it once it has focus - shift for bigger steps. Widths are
remembered in your browser, per panel, and are not shared with anyone else
looking at the same instance.

## When nothing seems to be happening

A plugin that fails three times in a row is tried less often, doubling up to an
hour, so that one expired password does not fill the history with hundreds of
identical failures overnight.

That used to be invisible. The line under the plugin's name now says so -
`slowed after 4 failures, next try in 38 min` - and the error message says what
to do about it. Two things clear it:

- **Run now**, which runs the plugin immediately whatever it is waiting for.
- **Editing `plugin.toml`**, which clears the count within seconds. Changing a
  plugin is how someone fixes a failing one, and waiting out an hour to find
  out whether it worked is no answer.

The first success puts it back to its normal interval.
