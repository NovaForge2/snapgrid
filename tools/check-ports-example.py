#!/bin/sh
''''true
for candidate in python3 python py; do
    command -v "$candidate" >/dev/null 2>&1 || continue
    "$candidate" -c "" >/dev/null 2>&1 || continue
    exec "$candidate" "$0" "$@"
done
echo "check-ports-example: no working python found." >&2
exit 1
# '''
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 NovaForge2
"""Run the listening ports example for real and check what it printed.

    ./tools/check-ports-example.py --kill-flag //F

Three bugs in that example got past a green test suite in one week, and all
three had the same shape: the unit tests fed it output written by hand, which
agreed with the parser because the same person wrote both. Only a real run on
a real machine disagrees.

This is what CI runs on Windows, once under Git Bash and once under cmd, and
on the Unix runners too. It is a maintainer's tool: nobody running snapgrid
ever runs it.

What it checks is not the data - a runner's listening sockets are its own
business - but the shape of the answer:

* the run succeeded and printed a header with the columns the plugin promises;
* the log said which way it asked and what came back, with no silent exit;
* every row with a pid has a command line, because an empty column on a run
  that reports success is exactly how this went wrong twice;
* the kill command is spelled for the shell this was started from.
"""

import argparse
import csv
import io
import os
import subprocess
import sys
from pathlib import Path

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "listening-ports"
COLUMNS = ["listener", "port", "pid", "user", "program", "kill", "command"]


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kill-flag", default="",
                        help="the spelling the kill command must use, '/F' or '//F'")
    parser.add_argument("--want-command-lines", action="store_true",
                        help="fail when a row with a pid has no command line")
    asked = parser.parse_args(argv)

    print(f"python {sys.version.split()[0]} on {sys.platform}, os.name={os.name}, "
          f"MSYSTEM={os.environ.get('MSYSTEM', '(unset)')}")

    done = subprocess.run([sys.executable, "main.py"], cwd=EXAMPLE,
                          capture_output=True, text=True, timeout=120)
    print("----- log -----")
    print(done.stderr.rstrip())
    print("---------------")

    problems = []
    if done.returncode != 0:
        problems.append(f"the plugin exited with {done.returncode}")

    rows = list(csv.reader(io.StringIO(done.stdout)))
    if not rows:
        problems.append("it printed nothing on standard output")
        return report(problems)
    if rows[0] != COLUMNS:
        problems.append(f"the header is {rows[0]}, not {COLUMNS}")
        return report(problems)

    body = [row for row in rows[1:] if row]
    print(f"{len(body)} rows")
    for number, row in enumerate(body[:5], start=2):
        print(f"  {row}")

    at = {name: COLUMNS.index(name) for name in COLUMNS}
    for number, row in enumerate(body, start=2):
        if len(row) != len(COLUMNS):
            problems.append(f"line {number} has {len(row)} values, not {len(COLUMNS)}")

    with_pid = [row for row in body if len(row) == len(COLUMNS) and row[at["pid"]]]
    print(f"{len(with_pid)} of them name an owner")

    # The silent failure, twice over: a table that looks complete with one
    # column empty the whole way down.
    if asked.want_command_lines and with_pid:
        blank = [row for row in with_pid if not row[at["command"]]]
        if len(blank) == len(with_pid):
            problems.append("every row with a pid has an empty command line - "
                            "the lookup found nothing at all")

    if asked.kill_flag and with_pid:
        wanted = f"taskkill {asked.kill_flag} "
        wrong = [row[at["kill"]] for row in with_pid
                 if not row[at["kill"]].startswith(wanted)]
        if wrong:
            problems.append(f"the kill command should start {wanted!r} in this "
                            f"shell, and one says {wrong[0]!r}")

    return report(problems)


def report(problems: list[str]) -> int:
    if not problems:
        print("ok")
        return 0
    for problem in problems:
        print(f"FAILED: {problem}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
