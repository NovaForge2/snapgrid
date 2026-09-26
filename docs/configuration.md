<!-- Part of the snapgrid documentation: https://github.com/NovaForge2/snapgrid -->

# Configuration

One file, in the folder you cloned into. It configures the server, where a
`plugin.toml` inside a plugin folder configures one plugin.

Nothing here applies to a single plugin. How long a plugin may run
(`timeout`), how often it runs (`every`), what it runs and where its table
comes from are all in that plugin's own manifest - see
[plugin-toml.md](plugin-toml.md).

It ships with the repository, ready to edit, and applies whichever plugins
folder you point at. A command line option beats it. Everything in it is
optional - delete the file and the defaults still apply.

```toml
[server]
title          = "Reports"             # shown in the corner and the browser tab
port           = 8765
max_concurrent = 3

[banner]
text  = "ENV2 is temporarily unavailable; ignore its versions."
level = "warning"                      # info | warning | error
```

Every key, and what it does:

| Key | Default | Meaning |
|---|---|---|
| `server.title` | `snapgrid` | shown in the corner and the browser tab. Worth setting when you run more than one instance |
| `server.port` | `8765` | the address does not move, so it can be bookmarked. Needs a restart to change |
| `server.max_concurrent` | `3` | how many plugins may run at once. The rest queue. Needs a restart to change |
| `banner.text` | none | the message across the top of the page. Remove it and nothing is shown |
| `banner.level` | `info` | the colour of that message, see below |

The **banner** is a message across the top of the page, for whoever is looking
at this instance: a warning that the data is not to be trusted today, a note
that the tool itself is new, anything worth saying once rather than in person.
Remove `text` and it disappears.

There are three levels:

| `level` | Colour | For |
|---|---|---|
| `info` | blue | neutral notices: "new plugin added", "this is the read-only copy" |
| `warning` | amber | something to be careful about: "ENV2 is temporarily unavailable, ignore its versions" |
| `error` | red | do not trust what you are looking at: "credentials expired, these numbers are from yesterday" |

A level that is not one of those three is ignored and you get `info`. The
message still appears, just not in the colour you meant - better than a banner
that vanishes because of a typo.

The banner has a close button. Hiding it lasts until the server restarts or the
message changes, so a message you dismissed this morning is in front of you
again tomorrow, and a new message is never hidden by an old dismissal. Hiding is
per browser and is not shared with anyone else looking at the same instance.

The title and the banner are read again on every request, so editing them shows
up within a few seconds without restarting. Port and concurrency are read at
startup, because changing those means restarting anyway. A command line option
always wins over the file, and the file wins over the defaults.

If the file has a mistake in it, the page says so in a red banner rather than
the server refusing to start or quietly ignoring it.

Useful options:

```bash
./server.py --port 9000 --max-concurrent 5 --dir ~/my-plugins
```


## Keeping plugins somewhere else

`--dir` is the folder holding your plugins. It does not have to be inside this
checkout - it can be a repository of your own, which is the tidiest arrangement:
the framework stays exactly as cloned, and `git pull` can never touch your work.

```bash
./server.py --dir ~/my-plugins
```

```bash
./server.py --dir ~/my-plugins status
```

snapgrid keeps everything it writes in a hidden `.snapgrid` folder inside that
same folder, so one workspace is one self-contained thing - see below.

One server per plugins folder. Starting a second one on the same folder is
refused, because both would share a database and schedule the same plugins.
Different folders are independent, and each gets its own port.


## What is on disk

snapgrid creates one folder, on first start, inside whatever plugins folder it
is pointed at. Nothing else on the machine is written to, and nothing is ever
written into a plugin's own folder.

**One database for the whole server, not one per plugin.** Every row carries
the plugin it belongs to, which is how they are kept apart. A second database
exists only if you point a second server at a different plugins folder.

```
plugins/.snapgrid/
    snapgrid.db      every run and every result
    server.log       the server's own log, not the plugins'
    server.json      the pid and port of the running server
```

| File | What it is | If you delete it |
|---|---|---|
| `snapgrid.db` | a SQLite database: runs, results and per-plugin state | history is lost, everything else still works |
| `server.log` | what the server itself printed, including startup problems | nothing |
| `server.json` | how `stop` and `status` find the running server without searching | `stop` cannot find it; kill it by hand |

While the server is running you may also see `snapgrid.db-wal` and
`snapgrid.db-shm`. Those are SQLite's own working files - it runs in WAL mode
so that reading never blocks a plugin finishing - and they go away on a clean
shutdown.

`--data` puts the folder somewhere else. If your plugins folder is a repository
of your own, add `.snapgrid/` to its `.gitignore`.

### Why SQLite, when the front page says no database

There is nothing to install and nothing to run. SQLite is part of Python
itself, and the database is one ordinary file that the server opens. What the
project avoids is a database *server* - something to provision, start, keep
running and get permission for, which is exactly what is impossible on a locked
down machine.

Flat files would have meant writing concurrent access, partial-write recovery
and querying by hand, none of which would end up better than what is already in
the standard library.

### The tables

Three of them, and reading them directly is a fair way to answer a question the
page does not:

**`runs`** - one row per run. `status`, `trigger` (the schedule or the Run now
button), `queued_at`, `started_at`, `finished_at`, `exit_code`, `error`, the
`log`, the `snapshot_id` it produced, and whether it `changed` anything.

**`snapshots`** - the tables themselves: `columns_json`, `rows_json`,
`row_count`, a `content_hash`, and `first_seen`, `last_seen`, `seen_count`. The
hash is what makes `[history] keep = 20` mean twenty *changes*: an identical
result updates `last_seen` and `seen_count` instead of taking a slot. This is
also what the page compares when you ask it what changed, and what the history
of a single cell is read from.

**`state`** - per plugin, `last_finished` and `consecutive_failures`. This is
why `every = "10d"` survives a restart rather than starting its ten days again,
and why the backoff after repeated failures is not forgotten when the server
restarts.

Times are Unix timestamps, so `datetime(finished_at, 'unixepoch', 'localtime')`
makes them readable.

```bash
sqlite3 plugins/.snapgrid/snapgrid.db \
  "select plugin_id, status,
          datetime(finished_at,'unixepoch','localtime') as finished, error
     from runs order by id desc limit 10"
```

```bash
sqlite3 plugins/.snapgrid/snapgrid.db \
  "select datetime(first_seen,'unixepoch','localtime') as changed, row_count
     from snapshots where plugin_id = 'my-plugin' order by id desc"
```

If the `sqlite3` command is not on the machine - it often is not, and the
project does not assume it - Python reads the same file:

```bash
python3 -c "import sqlite3; print(*sqlite3.connect('plugins/.snapgrid/snapgrid.db').execute('select plugin_id, status, error from runs order by id desc limit 10'), sep=chr(10))"
```

Read it while the server is running by all means. Writing to it is not
supported: the server holds its own connections and expects to be the only one
making changes.
