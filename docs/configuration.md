<!-- Part of the snapgrid documentation: https://github.com/NovaForge2/snapgrid -->

# Configuration

One file, in the folder you cloned into. It configures the server, where a
`plugin.toml` inside a plugin folder configures one plugin.

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

snapgrid keeps its database, log and chosen port in a hidden `.snapgrid` folder
inside that same folder, so one workspace is one self-contained thing. If your
plugins folder is a git repository, add `.snapgrid/` to its `.gitignore`. Use
`--data` to put that elsewhere.

One server per plugins folder. Starting a second one on the same folder is
refused, because both would share a database and schedule the same plugins.
Different folders are independent, and each gets its own port.

