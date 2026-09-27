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
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# plugins/ is the user's own folder and is not ours to police. examples/ is
# ours, ships with the project, and is the most likely place for an import of
# something convenient to creep in - so it is checked like everything else.
SKIP = {".git", "__pycache__", ".snapgrid", "plugins"}

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


# require("something") where something is not node's own and not a file next
# to it. The browser code has the same promise to keep as the Python: nothing
# that has to be installed, and no package.json to install it with.
REQUIRE_RE = re.compile(r"""require\(\s*["']([^"']+)["']\s*\)""")


def javascript_offenders() -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for path in sorted(ROOT.rglob("*.js")):
        if any(part in SKIP for part in path.relative_to(ROOT).parts):
            continue
        for name in REQUIRE_RE.findall(path.read_text(encoding="utf-8")):
            if name.startswith((".", "/")) or name.startswith("node:"):
                continue
            found.setdefault(name, set()).add(str(path.relative_to(ROOT)))
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

    for name, where in javascript_offenders().items():
        offenders.setdefault(name, set()).update(where)

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

    print(f"{checked} python files and every .js file: nothing that has to be "
          f"installed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
