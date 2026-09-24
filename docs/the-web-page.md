<!-- Part of the snapgrid documentation: https://github.com/NovaForge2/snapgrid -->

# The web page

- **Left panel** - plugins grouped by `group`, with a status dot: green for a
  good run, red for a failure or a broken `plugin.toml`, blue while running.
- **Refresh** starts a run in the background. You can go to another plugin while
  it works. **Cancel** stops it, including anything it started.
- **The table** does what a spreadsheet does: click a heading to sort, click the
  small arrow next to it for a checkbox list of every value in that column with
  counts, and use the search box to search everything at once. Columns holding
  only numbers sort as numbers, and columns holding only version numbers sort so
  that `2.9.0` comes before `2.14.1`.
- **Export CSV** downloads exactly what you are looking at.
- **The dropdown next to Refresh** appears once there is history, and shows any
  earlier result.
- **Log** and **Config** are buttons at the right of the toolbar. They open a
  panel over the right of the table, with a tab for each and a close button, so
  a panel you are not using costs the grid no space at all. Escape closes it.
- **Log** is the plugin's standard error, updating while it runs.
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

