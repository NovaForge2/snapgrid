#!/usr/bin/env python3
"""An example snapgrid plugin.

It reads data.json next to it and prints it as CSV. A real plugin would call a
command, query an API or read a database instead, but the shape is the same:
get some rows from somewhere, print them as CSV.

The rules for any plugin, in any language:

  * write CSV to standard output, starting with a header line
  * write progress or warnings to standard error, never to standard output
  * exit with code 0 when it worked, anything else when it did not

Run it by hand to see exactly what snapgrid sees:

    python3 main.py
"""

import csv
import json
import sys
from pathlib import Path

# Which keys become columns, and in which order. Anything else in the file is
# ignored, so adding a field to the data does not change the table by accident.
COLUMNS = ["service", "team", "environment", "version", "instances", "cpu_percent", "last_deploy"]


def main() -> int:
    # Plugins run with their own folder as the working directory, so a file
    # next to the script can be opened by name.
    source = Path(__file__).with_name("data.json")
    print(f"reading {source.name}", file=sys.stderr)

    try:
        records = json.loads(source.read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"{source} is missing", file=sys.stderr)
        return 1
    except json.JSONDecodeError as exc:
        print(f"{source.name} is not valid JSON: {exc}", file=sys.stderr)
        return 1

    writer = csv.writer(sys.stdout, lineterminator="\n")
    writer.writerow(COLUMNS)
    for record in records:
        writer.writerow([record.get(column, "") for column in COLUMNS])

    print(f"{len(records)} rows", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
