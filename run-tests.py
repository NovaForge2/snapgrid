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

import sys
import time
import unittest
import warnings
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
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
