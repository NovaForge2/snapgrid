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
        for name in ("requirements.txt", "pyproject.toml", "setup.py", "Pipfile"):
            self.assertFalse((ROOT / name).exists(),
                             f"{name} exists, so something has to be installed")

    def test_a_third_party_import_would_be_noticed(self):
        # Otherwise the check could be silently passing on everything.
        with tempfile.TemporaryDirectory() as folder:
            bad = Path(folder) / "bad.py"
            bad.write_text("import requests\n", encoding="utf-8")
            found = check_imports.imported_names(bad)
        self.assertIn("requests", found)
        self.assertNotIn("requests", check_imports.STANDARD)

    def test_our_own_modules_are_not_mistaken_for_dependencies(self):
        for name in ("snapgrid", "tests", "tools"):
            self.assertIn(name, check_imports.OURS)


if __name__ == "__main__":
    unittest.main()
