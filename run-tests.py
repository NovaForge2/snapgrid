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
"""

import sys
import unittest
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    warnings.simplefilter("error", ResourceWarning)
    tests = unittest.defaultTestLoader.discover(str(ROOT / "tests"), top_level_dir=str(ROOT))
    result = unittest.TextTestRunner(verbosity=2 if "-v" in sys.argv else 1).run(tests)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
