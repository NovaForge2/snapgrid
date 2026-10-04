#!/bin/sh
''''true
for candidate in python3 python py; do
    command -v "$candidate" >/dev/null 2>&1 || continue
    "$candidate" -c "" >/dev/null 2>&1 || continue
    exec "$candidate" "$0" "$@"
done
echo "run-tests: no working python found. Tried python3, python and py." >&2
exit 1
# '''
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 NovaForge2
"""Run the tests: ./run-tests.py   (or: python -m unittest discover -s tests -t .)

Nothing to install. Warnings are treated as errors, so a leaked file handle or
an unclosed socket fails the run rather than scrolling past.

Prints what was covered and what was slow, because "OK" on its own tells you
that nothing failed and nothing else at all - not what ran, nor whether the
part you just changed was among it.

    ./run-tests.py           summary by area
    ./run-tests.py -v        every test name
    ./run-tests.py store     only files matching "store"
"""

import shutil
import subprocess
import sys
import time
import unittest
import warnings

# snapgrid needs 3.11 for tomllib. Without this the first thing an older
# Python hits is a type annotation it cannot parse, and the error is about
# unsupported operands rather than about the version - which sends people
# looking in the wrong place. A "python3" on PATH can easily be 3.9.
if sys.version_info < (3, 11):
    raise SystemExit(
        f"snapgrid needs Python 3.11 or newer. This is "
        f"{sys.version.split()[0]} at {sys.executable}.\n"
        f"  Try: python3.11 run-tests.py"
    )
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

# What each test file is actually about, for the summary.
AREAS = {
    "test_manifest": "reading plugin.toml",
    "test_output": "the CSV contract",
    "test_output_file": "files and spreadsheets as the source",
    "test_running": "running real plugins",
    "test_spreadsheet": "reading .xlsx",
    "test_store": "storage and history",
    "test_secrets": "encryption and masking",
    "test_settings": "snapgrid.toml",
    "test_scheduling": "when plugins run",
    "test_api": "the HTTP interface",
    "test_gif": "the GIF in the README",
    "test_no_dependencies": "nothing to install",
    "test_workbook": "writing .xlsx",
}


class Timed(unittest.TextTestResult):
    """Remembers how long each test took and which file it came from."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.timings: list[tuple[str, str, float]] = []
        self._started = 0.0

    def startTest(self, test):
        self._started = time.perf_counter()
        super().startTest(test)

    def addSuccess(self, test):
        super().addSuccess(test)
        module = type(test).__module__.rsplit(".", 1)[-1]
        self.timings.append((module, test.id().rsplit(".", 1)[-1],
                             time.perf_counter() - self._started))


def summarise(result: Timed, seconds: float) -> None:
    by_area: dict[str, list[float]] = {}
    for module, _, taken in result.timings:
        by_area.setdefault(module, []).append(taken)

    print()
    for module in sorted(by_area):
        times = by_area[module]
        print(f"  {len(times):>4} {AREAS.get(module, module):<38} {sum(times):>5.1f}s")

    slowest = sorted(result.timings, key=lambda row: -row[2])[:3]
    if slowest and slowest[0][2] > 0.2:
        print("\n  slowest:")
        for module, name, taken in slowest:
            print(f"    {taken:>5.2f}s  {name}")

    counts = [f"{result.testsRun} tests"]
    if result.failures:
        counts.append(f"{len(result.failures)} failed")
    if result.errors:
        counts.append(f"{len(result.errors)} errors")
    if result.skipped:
        counts.append(f"{len(result.skipped)} skipped")
    print(f"\n  {', '.join(counts)} in {seconds:.1f}s - "
          f"{'all passed' if result.wasSuccessful() else 'FAILED'}")


def browser_tests(pattern: str | None) -> int | None:
    """Run the JavaScript tests, if node is here.

    What changed between two runs, and which cell gets which colour, are both
    worked out in the browser, so the tests for them have to run there too. node's own test runner needs nothing
    installed, and node is not required to *use* snapgrid - only to run this
    part of its suite. A machine without it gets a clear line saying which
    tests did not run, rather than a green total that quietly covered less.
    """
    if pattern and pattern not in "compare":
        return None

    found = sorted((ROOT / "tests").glob("*.test.js"))
    if not found:
        return None

    node = shutil.which("node")
    if node is None:
        print("\n  browser tests: skipped, node was not found. "
              "They cover comparing runs, and CI runs them.")
        return None

    print()
    finished = subprocess.run(
        [node, "--test", *[str(path) for path in found]],
        cwd=str(ROOT), capture_output=True, text=True,
    )
    passed = failed = 0
    for line in finished.stdout.splitlines():
        if line.startswith("# pass ") or line.startswith("\u2139 pass "):
            passed = int(line.rsplit(" ", 1)[1])
        elif line.startswith("# fail ") or line.startswith("\u2139 fail "):
            failed = int(line.rsplit(" ", 1)[1])

    if finished.returncode != 0:
        print(finished.stdout)
        print(finished.stderr, file=sys.stderr)
    print(f"  {passed} browser tests (what changed, and what gets a colour) - "
          f"{'all passed' if failed == 0 else f'{failed} FAILED'}")
    return finished.returncode


def main() -> int:
    warnings.simplefilter("error", ResourceWarning)
    pattern = next((arg for arg in sys.argv[1:] if not arg.startswith("-")), None)

    tests = unittest.defaultTestLoader.discover(
        str(ROOT / "tests"),
        pattern=f"*{pattern}*.py" if pattern else "test*.py",
        top_level_dir=str(ROOT),
    )

    started = time.perf_counter()
    runner = unittest.TextTestRunner(
        verbosity=2 if "-v" in sys.argv else 1, resultclass=Timed)
    result = runner.run(tests)
    summarise(result, time.perf_counter() - started)

    browser = browser_tests(pattern)
    if not result.wasSuccessful():
        return 1
    return 1 if browser else 0


if __name__ == "__main__":
    raise SystemExit(main())
