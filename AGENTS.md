# Writing a snapgrid plugin

Instructions for an AI agent asked to write a plugin for snapgrid. Follow them
literally. If a rule here conflicts with what the user asked for, say so rather
than silently breaking the rule.

## What you are producing

A **folder**. Nothing else. snapgrid watches a plugins directory and every
sub-folder containing a `plugin.toml` becomes a page in a web UI.

```
my-plugin/
    plugin.toml     required - what it is called and how to run it
    main.py         required - the program, in any language
    data.json       optional - anything else the program needs
    .env            optional - secrets, never committed
```

The program gets some rows from somewhere and prints them as CSV. snapgrid runs
it on a schedule, stores the result, and shows it as a sortable, filterable
table.

## The contract

These five rules are the whole interface. Getting any of them wrong makes the
plugin fail.

1. **Standard output is the table, and nothing else.** CSV, starting with a
   header line. No progress messages, no banners, no blank leading lines.
2. **Standard error is the log.** Progress, warnings, diagnostics go here. It is
   shown in the UI and stored with the run.
3. **The exit code decides.** `0` means success. Anything else marks the run
   failed and the previous good result stays on screen.
4. **There is no shell.** `command` is a list of arguments, executed directly.
   Pipes, `&&`, globs, redirects and `$VARIABLES` do not work. If you need them,
   write a shell script and run that.
5. **The working directory is the plugin folder**, so a file next to the script
   can be opened by name.

## plugin.toml

Only `[plugin] name` and `[run] command` are required.

```toml
[plugin]
name        = "OpenShift Image Versions"   # required, shown in the left panel
description = "Image version per repo per environment"
group       = "OpenShift"                  # heading the plugin appears under
enabled     = true

[run]
command = ["python", "main.py"]            # required, argument list, no shell
timeout = 300
every   = "15m"

[table]
columns = ["environment", "image", "version"]

[history]
keep = 20
```

| Key | Type | Default | Notes |
|---|---|---|---|
| `plugin.name` | string | **required** | shown in the left panel |
| `plugin.description` | string | `""` | one line, shown above the table |
| `plugin.group` | string | `""` | plugins with the same group are listed together |
| `plugin.enabled` | bool | `true` | `false` hides it completely and stops it running |
| `run.command` | list of strings | **required** | argument list. A bare `python` or `python3` means the interpreter running snapgrid |
| `run.timeout` | int seconds | `300` | the process and its children are killed at this point |
| `run.every` | string | `"15m"` | `"30s"`, `"15m"`, `"2h"`, or `"off"` for manual only. Measured from the end of the previous run |
| `table.columns` | list of strings | none | when present, the header line must match it exactly. Omit it and the header defines the columns |
| `history.keep` | int | `0` | how many *differing* results to keep. Omit for latest only |

Choose `every` by how fast the underlying data really changes. A plugin hitting
a live API every 30 seconds is a bad neighbour; most reporting plugins
want `"15m"` or `"1h"`.

Set `history.keep` when looking back matters — versions, counts, anything you
would ask "when did that change?" about. A run producing an identical table does
not consume a slot, so `keep = 20` means the last twenty real changes.

## Output format

```
environment,image,version
ENV1,payments-api,2.14.1
ENV2,payments-api,2.15.0-SNAPSHOT
```

- The **first line is the header**. Column names come from it.
- Use a **CSV writer from the standard library**, never string concatenation. A
  value containing a comma or a quote must be quoted correctly, and hand-rolled
  joining gets this wrong.
- **Keep the column order stable** between runs. Changing it silently reshapes
  the table and breaks history comparison.
- A missing value is an **empty field**, not the text `None`, `null` or `N/A`.
- Emit **plain values**: `2.14.1`, `41.5`, `2026-09-14 10:22`. No units, no
  thousands separators, no ANSI colour. A column where every value is a number
  sorts numerically; a column of dotted versions sorts by version; anything else
  sorts as text.
- Dates as `YYYY-MM-DD` or `YYYY-MM-DD HH:MM`, so they sort correctly as text.
- **One table per plugin.** If you have two unrelated shapes of data, that is two
  plugins.
- Zero rows is valid: print the header and exit `0`.

## Secrets

Read them from environment variables. snapgrid loads a `.env` file from the
plugin folder before running:

```
OC_URL=https://api.env1.example
OC_USER=svc_reporting
OC_PASSWORD=enc:u8Vj97KHcvUDrRuIj2ND...
```

```python
password = os.environ.get("OC_PASSWORD")
if not password:
    print("OC_PASSWORD is not set - add it to .env", file=sys.stderr)
    return 1
```

- **Never hardcode a secret in the script or in `plugin.toml`.**
- **Never pass a secret as a command line argument** — arguments are visible to
  anyone who can list processes, and they appear in the UI's Config panel.
- Encrypted values (`enc:...`) are decrypted by snapgrid before the plugin runs,
  so the plugin always sees the real value and needs no crypto code. They are
  produced by `./server.py encrypt`.
- Fail with a clear message on stderr when a variable is missing. Do not fall
  back to a default credential.

## Worked examples

**Python, reading a file next to it**

```python
#!/usr/bin/env python3
import csv, json, sys
from pathlib import Path

def main() -> int:
    source = Path(__file__).with_name("data.json")
    print(f"reading {source.name}", file=sys.stderr)
    rows = json.loads(source.read_text(encoding="utf-8"))

    writer = csv.writer(sys.stdout, lineterminator="\n")
    writer.writerow(["service", "environment", "version"])
    for row in rows:
        writer.writerow([row["service"], row["environment"], row["version"]])

    print(f"{len(rows)} rows", file=sys.stderr)
    return 0

if __name__ == "__main__":
    sys.exit(main())
```

**Python, calling a command**

```python
result = subprocess.run(
    ["oc", "get", "deployment", "-n", namespace, "-o", "json"],
    capture_output=True, text=True, timeout=60,
)
if result.returncode != 0:
    print(result.stderr.strip(), file=sys.stderr)   # stderr, not stdout
    return 1
data = json.loads(result.stdout)
```

**A shell script**, when the work is genuinely a pipeline

```bash
#!/usr/bin/env bash
set -euo pipefail
echo "filesystem,used,available"
df -h | tail -n +2 | awk '{print $1","$3","$4}'
```

```toml
[run]
command = ["bash", "report.sh"]
```

**One row per thing, one column per environment** — the shape to use when
comparing the same item across places:

```
repo,ENV1,ENV2,ENV3,ENV4
payments-api,2.14.1,2.15.0,2.13.0,2.12.6
orders-api,1.9.3,1.9.3,1.9.2,1.9.0
```

This reads far better than a long `repo,environment,version` table when the
question is "where do these differ?", and it is what the filters and history are
most useful on.

## Before you finish

Run the program directly. What it prints is exactly what snapgrid sees.

```bash
cd my-plugin && python3 main.py
```

Check every line:

- [ ] first line of stdout is the header
- [ ] every other stdout line is a data row, and nothing else is on stdout
- [ ] progress and warnings went to stderr
- [ ] `echo $?` is `0` on success, non-zero when it fails
- [ ] column count is identical on every row
- [ ] it finishes well inside `run.timeout`
- [ ] no secret is hardcoded, and none is passed as an argument
- [ ] it needs no input typed at it, and never prompts
- [ ] running it twice gives the same table when nothing changed

Then check the failure path deliberately: break the credential or the URL and
confirm it exits non-zero with a useful message on stderr rather than printing a
half table and exiting `0`. A plugin that reports success with missing rows is
worse than one that fails.

## What the errors mean

| Message in the UI | Cause |
|---|---|
| `plugin.toml is not valid TOML` | syntax error in the manifest |
| `cannot run 'x': no such program` | `run.command[0]` is not on PATH |
| `the header line does not match [table] columns` | the script's header changed, or `columns` is wrong |
| `line 4 has 5 values but there are 4 columns` | an unquoted comma in a value — use a CSV writer |
| `the script printed nothing on standard output` | everything went to stderr, or the script produced nothing |
| `the plugin exited with code 1` | the script failed; its last stderr line is shown |
| `the plugin was stopped after N seconds` | exceeded `run.timeout` |
| `cannot decrypt value` | wrong or missing key for an `enc:` value in `.env` |

## Do not

- **Do not modify snapgrid itself.** A plugin is self-contained; if it seems to
  need a framework change, say so instead of making one.
- **Do not add a dependency that has to be installed.** snapgrid exists to run
  where nothing can be installed. Use the standard library and commands already
  present on the machine. If a plugin genuinely requires something else, state
  that plainly as a requirement.
- **Do not write outside the plugin folder**, and do not change anything on a
  remote system. Plugins read and report; they do not deploy, restart or delete.
- **Do not print a table to stdout when the run failed.** Exit non-zero and let
  the previous good result stand.
- **Do not cache results yourself.** snapgrid stores every run and serves the
  last one instantly. Fetch fresh data each time.
- **Do not invent data.** If a value cannot be determined, leave the field empty.
