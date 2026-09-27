#!/usr/bin/env python3
"""How much room is left on each disk.

The simplest useful plugin there is: no network, no credentials, nothing to
configure. Copy the folder and it works.

The rules for any plugin, in any language:

  * write CSV to standard output, starting with a header line
  * write progress or warnings to standard error, never to standard output
  * exit with code 0 when it worked, anything else when it did not

Run it by hand to see exactly what snapgrid sees:

    python3 main.py
"""

import csv
import os
import shutil
import string
import sys
from pathlib import Path

# Virtual filesystems report sizes that mean nothing to a human - a squashfs
# image is always 100% full, which would sit at the top of the table for ever.
IGNORED_TYPES = {
    "proc", "sysfs", "devtmpfs", "devpts", "tmpfs", "squashfs", "overlay",
    "cgroup", "cgroup2", "debugfs", "tracefs", "securityfs", "pstore",
    "autofs", "mqueue", "hugetlbfs", "fusectl", "configfs", "binfmt_misc",
}

GIGABYTE = 1024 ** 3


def places_to_measure() -> list[str]:
    """Every disk worth reporting on, on whichever system this is.

    Deliberately three small cases rather than one clever one: the list of
    mounted filesystems lives in a different place on each, and guessing
    wrongly would silently report nothing.
    """
    if os.name == "nt":
        return [f"{letter}:\\" for letter in string.ascii_uppercase
                if Path(f"{letter}:\\").exists()]

    mounts = Path("/proc/mounts")           # Linux
    if mounts.is_file():
        found = []
        for line in mounts.read_text(encoding="utf-8", errors="replace").splitlines():
            parts = line.split()
            if len(parts) < 3 or parts[2] in IGNORED_TYPES:
                continue
            if parts[1] in found:
                continue
            found.append(parts[1])
        if found:
            return found

    return ["/"]                            # macOS, and anything unexpected


def main() -> int:
    places = places_to_measure()
    print(f"measuring {len(places)} place(s)", file=sys.stderr)

    writer = csv.writer(sys.stdout, lineterminator="\n")
    # Column order is part of the contract: changing it reshapes the table and
    # makes comparing two runs impossible.
    writer.writerow(["filesystem", "size_gb", "used_gb", "free_gb", "used_percent"])

    measured = 0
    for place in places:
        try:
            usage = shutil.disk_usage(place)
        except OSError as exc:
            # One unreadable mount is not a failed run. Say so and carry on.
            print(f"{place}: {exc}", file=sys.stderr)
            continue

        # Plain numbers, no units and no thousands separators, so the column
        # sorts as numbers rather than as text.
        percent = round(usage.used / usage.total * 100, 1) if usage.total else ""
        writer.writerow([
            place,
            round(usage.total / GIGABYTE, 1),
            round(usage.used / GIGABYTE, 1),
            round(usage.free / GIGABYTE, 1),
            percent,
        ])
        measured += 1

    if not measured:
        # Nothing measured is a failure, not an empty table. Exiting 0 here
        # would replace yesterday's good result with nothing at all.
        print("no filesystem could be measured", file=sys.stderr)
        return 1

    print(f"{measured} filesystem(s)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
