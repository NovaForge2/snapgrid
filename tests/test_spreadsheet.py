# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 NovaForge2
"""Reading .xlsx files.

The workbooks here are built by hand, so these tests check the reader against
the file format rather than against a file Excel actually wrote. They catch
mistakes in the reader; they cannot catch a wrong assumption about what Excel
puts in a file. A real workbook is still worth trying.
"""

import tempfile
import unittest
import zipfile
from pathlib import Path

from snapgrid.spreadsheet import (
    SpreadsheetError,
    column_number,
    read_xlsx,
    serial_to_text,
    tidy_number,
)

CONTENT_TYPES = """<?xml version="1.0"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="xml" ContentType="application/xml"/>
</Types>"""

ROOT_RELS = """<?xml version="1.0"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Target="xl/workbook.xml"
    Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"/>
</Relationships>"""


def workbook_xml(names):
    sheets = "".join(
        f'<sheet name="{name}" sheetId="{index + 1}" '
        f'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
        f'r:id="rId{index + 1}"/>'
        for index, name in enumerate(names)
    )
    return ('<?xml version="1.0"?><workbook '
            'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f"<sheets>{sheets}</sheets></workbook>")


def workbook_rels(count):
    entries = "".join(
        f'<Relationship Id="rId{index + 1}" Target="worksheets/sheet{index + 1}.xml" '
        f'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"/>'
        for index in range(count)
    )
    return ('<?xml version="1.0"?><Relationships '
            'xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f"{entries}</Relationships>")


def sheet_xml(rows):
    """rows: list of lists of raw <c> element strings."""
    body = ""
    for number, cells in enumerate(rows, start=1):
        body += f'<row r="{number}">' + "".join(cells) + "</row>"
    return ('<?xml version="1.0"?><worksheet '
            'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f"<sheetData>{body}</sheetData></worksheet>")


def shared_strings_xml(values):
    items = "".join(f"<si><t>{value}</t></si>" for value in values)
    return ('<?xml version="1.0"?><sst '
            'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f"{items}</sst>")


def styles_xml(format_ids):
    """One cellXf per entry, so style index 0, 1, 2 ... map to these formats."""
    entries = "".join(f'<xf numFmtId="{value}" applyNumberFormat="1"/>' for value in format_ids)
    return ('<?xml version="1.0"?><styleSheet '
            'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<numFmts><numFmt numFmtId="200" formatCode="dd/mm/yyyy"/>'
            '<numFmt numFmtId="201" formatCode="0.00&quot;kg&quot;"/></numFmts>'
            f"<cellXfs>{entries}</cellXfs></styleSheet>")


class XlsxTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def build(self, sheets, strings=None, styles=None, name="book.xlsx"):
        path = self.root / name
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("[Content_Types].xml", CONTENT_TYPES)
            archive.writestr("_rels/.rels", ROOT_RELS)
            archive.writestr("xl/workbook.xml", workbook_xml([n for n, _ in sheets]))
            archive.writestr("xl/_rels/workbook.xml.rels", workbook_rels(len(sheets)))
            for index, (_, rows) in enumerate(sheets, start=1):
                archive.writestr(f"xl/worksheets/sheet{index}.xml", sheet_xml(rows))
            if strings is not None:
                archive.writestr("xl/sharedStrings.xml", shared_strings_xml(strings))
            if styles is not None:
                archive.writestr("xl/styles.xml", styles_xml(styles))
        return path


class Reading(XlsxTest):
    def test_shared_strings_and_numbers(self):
        path = self.build(
            [("Sheet1", [
                ['<c r="A1" t="s"><v>0</v></c>', '<c r="B1" t="s"><v>1</v></c>'],
                ['<c r="A2" t="s"><v>2</v></c>', '<c r="B2"><v>42</v></c>'],
            ])],
            strings=["service", "count", "payments-api"],
        )
        self.assertEqual(read_xlsx(path), [["service", "count"], ["payments-api", "42"]])

    def test_inline_strings(self):
        path = self.build([("Sheet1", [
            ['<c r="A1" t="inlineStr"><is><t>name</t></is></c>'],
            ['<c r="A2" t="inlineStr"><is><t>value</t></is></c>'],
        ])])
        self.assertEqual(read_xlsx(path), [["name"], ["value"]])

    def test_formatted_runs_are_joined(self):
        # Text with mixed formatting is stored as several runs.
        path = self.build(
            [("Sheet1", [['<c r="A1" t="s"><v>0</v></c>']])],
            strings=[],
        )
        with zipfile.ZipFile(path, "a") as archive:
            archive.writestr("xl/sharedStrings.xml",
                             '<?xml version="1.0"?><sst xmlns="http://schemas.openxmlformats.org'
                             '/spreadsheetml/2006/main"><si><r><t>pay</t></r><r><t>ments</t></r>'
                             "</si></sst>")
        self.assertEqual(read_xlsx(path), [["payments"]])

    def test_booleans_and_formula_results(self):
        path = self.build([("Sheet1", [
            ['<c r="A1" t="b"><v>1</v></c>', '<c r="B1" t="b"><v>0</v></c>',
             '<c r="C1"><f>SUM(1,2)</f><v>3</v></c>'],
        ])])
        self.assertEqual(read_xlsx(path), [["TRUE", "FALSE", "3"]])

    def test_a_formula_never_calculated_is_empty_not_a_crash(self):
        # No stored value, so nothing to show - but the row around it survives.
        path = self.build([("Sheet1", [
            ['<c r="A1"><f>SUM(1,2)</f></c>', '<c r="B1"><v>5</v></c>'],
        ])])
        self.assertEqual(read_xlsx(path), [["", "5"]])

    def test_gaps_are_filled_by_position(self):
        # B is missing, so its column must still exist and be empty.
        path = self.build([("Sheet1", [
            ['<c r="A1"><v>1</v></c>', '<c r="C1"><v>3</v></c>'],
        ])])
        self.assertEqual(read_xlsx(path), [["1", "", "3"]])

    def test_trailing_empty_rows_are_dropped(self):
        path = self.build([("Sheet1", [
            ['<c r="A1" t="inlineStr"><is><t>a</t></is></c>'],
            ['<c r="A2"/>'],
            ['<c r="A3"/>'],
        ])])
        self.assertEqual(read_xlsx(path), [["a"]])

    def test_columns_beyond_z(self):
        path = self.build([("Sheet1", [['<c r="AA1"><v>27</v></c>']])])
        self.assertEqual(len(read_xlsx(path)[0]), 27)


class Dates(XlsxTest):
    def test_a_date_formatted_cell_becomes_a_readable_date(self):
        # Style 0 uses format 14, one of Excel's built-in date formats.
        path = self.build(
            [("Sheet1", [['<c r="A1" s="0"><v>45914</v></c>']])],
            styles=[14],
        )
        self.assertEqual(read_xlsx(path), [["2025-09-14"]])

    def test_the_same_number_without_a_date_format_stays_a_number(self):
        path = self.build(
            [("Sheet1", [['<c r="A1" s="0"><v>45914</v></c>']])],
            styles=[0],
        )
        self.assertEqual(read_xlsx(path), [["45914"]])

    def test_a_custom_date_format_is_recognised(self):
        path = self.build(
            [("Sheet1", [['<c r="A1" s="0"><v>45914</v></c>']])],
            styles=[200],           # dd/mm/yyyy, declared in styles_xml
        )
        self.assertEqual(read_xlsx(path), [["2025-09-14"]])

    def test_a_custom_format_that_merely_quotes_letters_is_not_a_date(self):
        # 0.00"kg" contains no date markers outside the quotes.
        path = self.build(
            [("Sheet1", [['<c r="A1" s="0"><v>12.5</v></c>']])],
            styles=[201],
        )
        self.assertEqual(read_xlsx(path), [["12.5"]])

    def test_a_time_with_no_date(self):
        path = self.build(
            [("Sheet1", [['<c r="A1" s="0"><v>0.5</v></c>']])],
            styles=[18],
        )
        self.assertEqual(read_xlsx(path), [["12:00:00"]])

    def test_a_date_with_a_time_keeps_both(self):
        path = self.build(
            [("Sheet1", [['<c r="A1" s="0"><v>45914.5</v></c>']])],
            styles=[22],
        )
        self.assertEqual(read_xlsx(path), [["2025-09-14 12:00"]])

    def test_the_serial_conversion_directly(self):
        self.assertEqual(serial_to_text(45914), "2025-09-14")
        # Before Excel's imaginary 29 February 1900, dates need the day back.
        self.assertEqual(serial_to_text(1), "1900-01-01")
        self.assertEqual(serial_to_text(59), "1900-02-28")


class Sheets(XlsxTest):
    def test_the_first_sheet_is_used_by_default(self):
        path = self.build([
            ("First", [['<c r="A1" t="inlineStr"><is><t>one</t></is></c>']]),
            ("Second", [['<c r="A1" t="inlineStr"><is><t>two</t></is></c>']]),
        ])
        self.assertEqual(read_xlsx(path), [["one"]])

    def test_a_named_sheet_can_be_chosen(self):
        path = self.build([
            ("First", [['<c r="A1" t="inlineStr"><is><t>one</t></is></c>']]),
            ("Second", [['<c r="A1" t="inlineStr"><is><t>two</t></is></c>']]),
        ])
        self.assertEqual(read_xlsx(path, "Second"), [["two"]])

    def test_an_unknown_sheet_lists_the_ones_that_exist(self):
        path = self.build([
            ("First", [['<c r="A1"><v>1</v></c>']]),
            ("Second", [['<c r="A1"><v>2</v></c>']]),
        ])
        with self.assertRaises(SpreadsheetError) as caught:
            read_xlsx(path, "Third")
        message = str(caught.exception)
        self.assertIn("First", message)
        self.assertIn("Second", message)


class Refusals(XlsxTest):
    def test_the_old_binary_format_is_refused_clearly(self):
        path = self.root / "ancient.xls"
        path.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 100)
        with self.assertRaises(SpreadsheetError) as caught:
            read_xlsx(path)
        self.assertIn(".xls", str(caught.exception))

    def test_a_zip_that_is_not_a_workbook(self):
        path = self.root / "notes.xlsx"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("hello.txt", "not a workbook")
        with self.assertRaises(SpreadsheetError):
            read_xlsx(path)


class Helpers(unittest.TestCase):
    def test_column_letters_to_numbers(self):
        for reference, expected in [("A1", 0), ("B2", 1), ("Z1", 25), ("AA1", 26), ("AB3", 27)]:
            self.assertEqual(column_number(reference), expected, reference)

    def test_numbers_are_tidied(self):
        self.assertEqual(tidy_number("3"), "3")
        self.assertEqual(tidy_number("3.0"), "3")
        self.assertEqual(tidy_number("3.10"), "3.1")
        self.assertEqual(tidy_number("0.30000000000000004"), "0.3")
        self.assertEqual(tidy_number("not a number"), "not a number")


if __name__ == "__main__":
    unittest.main()
