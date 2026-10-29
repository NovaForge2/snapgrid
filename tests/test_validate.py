# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 NovaForge2
import contextlib
import io
import os
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from snapgrid_core.__main__ import main
from snapgrid_core.runner import OutputError
from snapgrid_core.validate import validate_plugin
from tests.test_spreadsheet import XlsxTest
from snapgrid_core.spreadsheet import read_xlsx, SpreadsheetError


class Validation(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        (self.folder / 'plugin.toml').write_text('[output]\nfile="data.csv"\n')

    def table(self, text):
        (self.folder / 'data.csv').write_text(text)

    def test_good_file_and_cli_exit_status(self):
        self.table('name,value\na,1\nb,2\n')
        with contextlib.redirect_stdout(io.StringIO()) as out:
            code = main(['validate', str(self.folder)])
        self.assertEqual(code, 0)
        self.assertIn('2 rows', out.getvalue())

    def test_duplicate_or_empty_keys_are_rejected(self):
        for text in ['name,value\na,1\na,2\n', 'name,value\n,1\n']:
            self.table(text)
            with self.assertRaisesRegex(OutputError, 'unique'):
                validate_plugin(self.folder)

    def test_duplicate_or_empty_headers_are_rejected(self):
        for text in ['name,name\na,b\n', 'name,\na,b\n']:
            self.table(text)
            with self.assertRaisesRegex(OutputError, 'column names'):
                validate_plugin(self.folder)

    def test_missing_key_is_rejected(self):
        (self.folder / 'plugin.toml').write_text('[output]\nfile="data.csv"\n[table]\nkey="id"\n')
        self.table('name\na\n')
        with self.assertRaisesRegex(OutputError, 'missing'):
            validate_plugin(self.folder)

    def test_several_key_columns_that_are_unique_together_are_accepted(self):
        # Neither column is unique on its own. The pair is, which is the shape
        # [table] key takes a list for.
        (self.folder / 'plugin.toml').write_text(
            '[output]\nfile="data.csv"\n[table]\nkey=["environment","repo"]\n')
        self.table('environment,repo,version\nENV1,api,1\nENV2,api,2\nENV1,web,3\n')
        self.assertIn('3 rows', validate_plugin(self.folder))

    def test_several_key_columns_that_repeat_together_are_rejected(self):
        (self.folder / 'plugin.toml').write_text(
            '[output]\nfile="data.csv"\n[table]\nkey=["environment","repo"]\n')
        self.table('environment,repo,version\nENV1,api,1\nENV1,api,2\n')
        with self.assertRaisesRegex(OutputError, 'name each row once'):
            validate_plugin(self.folder)

    def test_an_empty_value_in_one_key_column_is_rejected(self):
        (self.folder / 'plugin.toml').write_text(
            '[output]\nfile="data.csv"\n[table]\nkey=["environment","repo"]\n')
        self.table('environment,repo,version\nENV1,,1\n')
        with self.assertRaisesRegex(OutputError, 'empty values'):
            validate_plugin(self.folder)

    def test_one_missing_key_column_of_several_is_rejected(self):
        (self.folder / 'plugin.toml').write_text(
            '[output]\nfile="data.csv"\n[table]\nkey=["environment","repo"]\n')
        self.table('environment,version\nENV1,1\n')
        with self.assertRaisesRegex(OutputError, 'missing'):
            validate_plugin(self.folder)

    def test_an_ignored_column_that_is_not_in_the_table_is_rejected(self):
        # [compare] ignore names a column that is never compared. Misspelt, it
        # quietly does nothing - and the table looks as though the setting was
        # not read. Here the columns are known, so it can be said.
        (self.folder / 'plugin.toml').write_text(
            '[output]\nfile="data.csv"\n[compare]\nignore=["when"]\n')
        self.table('name,value\na,1\n')
        with self.assertRaisesRegex(OutputError, "the table does not have"):
            validate_plugin(self.folder)

    def test_an_ignored_column_that_is_in_the_table_is_accepted(self):
        (self.folder / 'plugin.toml').write_text(
            '[output]\nfile="data.csv"\n[compare]\nignore=["value"]\n')
        self.table('name,value\na,1\n')
        self.assertIn('1 rows', validate_plugin(self.folder))

    def test_manifest_only_does_not_execute_plugin(self):
        marker = self.folder / 'executed'
        (self.folder / 'plugin.toml').write_text('[run]\ncommand=["python", "main.py"]\n')
        (self.folder / 'main.py').write_text('from pathlib import Path\nPath("executed").touch()')
        self.assertIn('table not checked', validate_plugin(self.folder))
        self.assertFalse(marker.exists())
        self.table('name\na\n')
        self.assertIn('1 rows', validate_plugin(self.folder, self.folder / 'data.csv'))
        self.assertFalse(marker.exists())

    def test_invalid_manifest_fails_cli(self):
        (self.folder / 'plugin.toml').write_text('not toml')
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(['validate', str(self.folder)]), 1)

    def test_table_validation_does_not_need_an_encryption_key(self):
        (self.folder / '.env').write_text('TOKEN=enc:not-base64\n', encoding='utf-8')
        self.table('name,value\na,enc:literal\n')
        key_file = self.folder / 'missing-key'
        with mock.patch.dict(os.environ, SNAPGRID_KEY_FILE=str(key_file)):
            self.assertIn('1 rows', validate_plugin(self.folder))
            self.assertIn('1 rows', validate_plugin(self.folder, self.folder / 'data.csv'))
        self.assertFalse(key_file.exists())

    def test_table_validation_does_not_read_the_plugin_environment(self):
        self.table('name,value\na,1\n')
        (self.folder / '.env').mkdir()  # Not even a readable file.
        self.assertIn('1 rows', validate_plugin(self.folder))


class SpreadsheetLimits(XlsxTest):
    def test_column_beyond_excel_limit_is_rejected(self):
        path = self.build([('Sheet', [['<c r="ZZZZZZ1"><v>1</v></c>']])])
        with self.assertRaisesRegex(SpreadsheetError, 'column limit'):
            read_xlsx(path)

    def test_sparse_rows_cannot_expand_without_limit(self):
        path = self.build([('Sheet', [['<c r="XFD1"><v>1</v></c>']] * 123)])
        with self.assertRaisesRegex(SpreadsheetError, '2 million'):
            read_xlsx(path)
