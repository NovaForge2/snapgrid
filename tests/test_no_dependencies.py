# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 NovaForge2
"""The promise that nothing has to be installed, enforced rather than stated.

This is the one claim the whole project rests on. It is also the easiest to
break by accident, and the person who would find out is someone on a locked
down machine watching an import fail.
"""

import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

spec = importlib.util.spec_from_file_location("check_imports", ROOT / "tools" / "check-imports.py")
check_imports = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_imports)


class NothingToInstall(unittest.TestCase):
    def test_every_import_in_the_project_is_part_of_python(self):
        self.assertEqual(check_imports.main(), 0)

    def test_there_is_no_dependency_file(self):
        # package.json and package-lock.json included: the browser code has
        # the same promise to keep, and the JavaScript tests run on node's own
        # runner precisely so there is nothing to install for them either.
        for name in ("requirements.txt", "pyproject.toml", "setup.py", "Pipfile",
                     "package.json", "package-lock.json"):
            self.assertFalse((ROOT / name).exists(),
                             f"{name} exists, so something has to be installed")

    def test_the_browser_code_imports_nothing_either(self):
        self.assertEqual(check_imports.javascript_offenders(), {})

    def test_a_third_party_require_would_be_noticed(self):
        found = check_imports.REQUIRE_RE.findall(
            'require("lodash"); require("node:fs"); require("./near")')
        self.assertIn("lodash", found)

    def test_a_third_party_import_would_be_noticed(self):
        # Otherwise the check could be silently passing on everything.
        with tempfile.TemporaryDirectory() as folder:
            bad = Path(folder) / "bad.py"
            bad.write_text("import requests\n", encoding="utf-8")
            found = check_imports.imported_names(bad)
        self.assertIn("requests", found)
        self.assertNotIn("requests", check_imports.STANDARD)

    def test_the_examples_are_checked_too(self):
        # They ship with the project and are the likeliest place for an import
        # of something convenient to creep in, so they are not exempt.
        self.assertNotIn("examples", check_imports.SKIP)
        self.assertIn("plugins", check_imports.SKIP,
                      "the user's own folder is not ours to police")

    def test_our_own_modules_are_not_mistaken_for_dependencies(self):
        for name in ("snapgrid", "tests", "tools"):
            self.assertIn(name, check_imports.OURS)


if __name__ == "__main__":
    unittest.main()
