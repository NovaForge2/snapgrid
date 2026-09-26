#!/bin/sh
''''true
for candidate in python3 python py; do
    command -v "$candidate" >/dev/null 2>&1 || continue
    "$candidate" -c "" >/dev/null 2>&1 || continue
    exec "$candidate" "$0" "$@"
done
echo "check-imports: no working python found." >&2
exit 1
# '''
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 NovaForge2
"""Check that nothing in the project imports anything that has to be installed.

The whole claim of this project is that it runs where nothing can be installed.
That claim is one careless `import requests` away from being false, and the
person who finds out would be someone on a locked down machine watching it
fail. A README promise that nothing enforces is a promise that will eventually
be broken, so this is run in CI.

It reads the source rather than importing it: importing would run module level
code, and a missing module would fail here for the right reason but in a
confusing way.
"""

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP = {".git", "__pycache__", ".snapgrid", "plugins", "examples"}

# Modules that are part of Python itself. sys.stdlib_module_names covers the
# interpreter running this, which is the one that matters.
STANDARD = set(sys.stdlib_module_names) | {"__future__"}

# The project's own packages, which are neither standard nor installed.
OURS = {"snapgrid", "tests", "tools", "make_gif", "server"}


def imported_names(path: Path) -> set[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError as exc:
        print(f"{path}: cannot be parsed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level:            # from . import x - our own
                continue
            if node.module:
                found.add(node.module.split(".")[0])
    return found


def main() -> int:
    offenders: dict[str, set[str]] = {}
    checked = 0

    for path in sorted(ROOT.rglob("*.py")):
        if any(part in SKIP for part in path.relative_to(ROOT).parts):
            continue
        checked += 1
        for name in imported_names(path):
            if name in STANDARD or name in OURS:
                continue
            offenders.setdefault(name, set()).add(str(path.relative_to(ROOT)))

    if offenders:
        print("These are not part of the standard library, so they would have to be "
              "installed:", file=sys.stderr)
        for name in sorted(offenders):
            where = ", ".join(sorted(offenders[name]))
            print(f"  {name}  ({where})", file=sys.stderr)
        print("\nsnapgrid exists to run where nothing can be installed. Use the "
              "standard library, or say plainly in the README that this is now "
              "required.", file=sys.stderr)
        return 1

    print(f"{checked} files, every import is part of Python itself.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
