# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 NovaForge2
"""Writing an .xlsx, and not mangling anything on the way.

The point of exporting a workbook rather than a CSV is that Excel interprets a
CSV: 1.10 becomes 1.1, 0042 becomes 42, a long number becomes 1E+20. Most of
what is below is about proving that does not happen here, because a formatted
file that quietly changed a version number would be worse than no file at all.
"""

import io
import re
import tempfile
import unittest
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from snapgrid.spreadsheet import read_xlsx
from snapgrid.workbook import (
    column_letter,
    looks_numeric,
    safe_sheet_name,
    survives_as_a_number,
    write_xlsx,
)


def written(columns, rows, sheet="Sheet1"):
    folder = tempfile.mkdtemp()
    path = Path(folder) / "out.xlsx"
    path.write_bytes(write_xlsx(columns, rows, sheet))
    return path


class Values(unittest.TestCase):
    """What may be stored as a number, and what may not."""

    def test_plain_numbers_are_numbers(self):
        for value in ("1", "42", "-4", "3.2", "0", "0.5"):
            self.assertTrue(survives_as_a_number(value), value)

    def test_a_version_that_looks_like_a_decimal_is_not(self):
        # The whole reason this exists: 1.10 is a later version than 1.9, and
        # as a number it is 1.1, which is earlier.
        self.assertFalse(survives_as_a_number("1.10"))
        self.assertFalse(looks_numeric(["1.9", "1.10"]))

    def test_a_trailing_zero_is_kept(self):
        self.assertFalse(survives_as_a_number("2.50"))

    def test_a_leading_zero_is_kept(self):
        self.assertFalse(survives_as_a_number("0042"))

    def test_a_number_longer_than_excel_keeps_is_text(self):
        # Excel holds fifteen significant digits and silently drops the rest.
        self.assertFalse(survives_as_a_number("100000000000000000000"))
        self.assertTrue(survives_as_a_number("999999999999999"))

    def test_one_odd_value_makes_the_whole_column_text(self):
        self.assertFalse(looks_numeric(["1", "2", "n/a"]))

    def test_blanks_do_not_decide_anything(self):
        self.assertTrue(looks_numeric(["1.5", "", "2.5"]))
        self.assertFalse(looks_numeric(["", ""]), "nothing to go on is not a number")


class RoundTrip(unittest.TestCase):
    """What goes in comes back out, read by this project's own reader."""

    def test_a_table_survives(self):
        columns = ["repo", "ENV1", "count"]
        rows = [["payments-api", "2.14.1", "42"], ["orders-api", "1.9.3", "7"]]
        self.assertEqual(read_xlsx(written(columns, rows)), [columns] + rows)

    def test_the_values_excel_would_mangle_survive(self):
        columns = ["version", "account", "amount"]
        rows = [["1.10", "0042", "2.50"], ["1.9", "100000000000000000000", "3.00"]]
        self.assertEqual(read_xlsx(written(columns, rows))[1:], rows)

    def test_commas_quotes_and_angle_brackets_survive(self):
        rows = [['a,b "quoted"', "<script>", "ampersand & co"]]
        self.assertEqual(read_xlsx(written(["a", "b", "c"], rows))[1:], rows)

    def test_a_short_row_becomes_blanks_rather_than_an_error(self):
        got = read_xlsx(written(["a", "b", "c"], [["one"]]))
        self.assertEqual(got[1][0], "one")

    def test_no_rows_still_gives_a_header(self):
        self.assertEqual(read_xlsx(written(["a", "b"], [])), [["a", "b"]])

    def test_many_columns_get_the_right_letters(self):
        columns = [f"c{n}" for n in range(30)]
        self.assertEqual(read_xlsx(written(columns, [[str(n) for n in range(30)]]))[0],
                         columns)


class WhatExcelIsGiven(unittest.TestCase):
    """The shape of the file, which Excel is strict about."""

    def parts(self, path):
        with zipfile.ZipFile(path) as archive:
            return archive.namelist()

    def sheet(self, path):
        with zipfile.ZipFile(path) as archive:
            return archive.read("xl/worksheets/sheet1.xml").decode("utf-8")

    def test_every_part_excel_requires_is_there(self):
        path = written(["a"], [["1"]])
        for name in ("[Content_Types].xml", "_rels/.rels", "xl/workbook.xml",
                     "xl/_rels/workbook.xml.rels", "xl/styles.xml",
                     "xl/worksheets/sheet1.xml"):
            self.assertIn(name, self.parts(path))

    def test_the_header_row_is_frozen(self):
        self.assertIn('state="frozen"', self.sheet(written(["a"], [["1"]])))

    def test_the_header_row_has_filters(self):
        self.assertIn("<autoFilter", self.sheet(written(["a", "b"], [["1", "2"]])))

    def test_columns_are_given_a_width(self):
        self.assertIn("customWidth", self.sheet(written(["a"], [["1"]])))

    def test_the_sheet_is_named_after_the_plugin(self):
        with zipfile.ZipFile(written(["a"], [], "Image versions")) as archive:
            self.assertIn('name="Image versions"',
                          archive.read("xl/workbook.xml").decode("utf-8"))

    def test_a_name_excel_would_refuse_is_cleaned(self):
        self.assertEqual(safe_sheet_name("a/b:c*d"), "a b c d")
        self.assertLessEqual(len(safe_sheet_name("x" * 60)), 31)
        self.assertEqual(safe_sheet_name("   "), "Sheet1")

    def test_the_same_table_gives_the_same_bytes(self):
        # A fixed timestamp inside the zip, so nothing looks changed when it
        # is not - which matters if anyone ever diffs or caches these.
        first = write_xlsx(["a"], [["1"]])
        second = write_xlsx(["a"], [["1"]])
        self.assertEqual(first, second)


class FormulaInjection(unittest.TestCase):
    """A value must never become something Excel executes.

    A plugin prints what it reads, and what it reads may come from somewhere
    else entirely. `=cmd|' /C calc'!A0` in a cell is the classic spreadsheet
    attack, and a CSV hands it straight to Excel as a formula.

    Nothing here escapes or prefixes anything, because nothing needs to: every
    text cell is written as an inline string, which Excel displays and never
    evaluates. These tests exist so that stays true - a later change to shared
    strings or to a formula element would reintroduce it silently.
    """

    DANGEROUS = [
        "=cmd|' /C calc'!A0",
        "@SUM(1+1)*cmd|' /C calc'!A0",
        '=HYPERLINK("http://example.invalid","click")',
        "+1+1",
        "-1+1",
        "=1+1",
    ]

    def sheet(self, rows):
        path = written(["a"], [[value] for value in rows])
        with zipfile.ZipFile(path) as archive:
            return archive.read("xl/worksheets/sheet1.xml").decode("utf-8")

    def test_no_cell_is_ever_written_as_a_formula(self):
        self.assertNotIn("<f>", self.sheet(self.DANGEROUS))

    def test_every_dangerous_value_is_an_inline_string(self):
        xml = self.sheet(self.DANGEROUS)
        # One per value, plus the header cell, which is a string too.
        self.assertEqual(xml.count("inlineStr"), len(self.DANGEROUS) + 1)

    def test_the_text_comes_back_exactly_as_written(self):
        rows = [[value] for value in self.DANGEROUS]
        self.assertEqual(read_xlsx(written(["a"], rows))[1:], rows)

    def test_a_leading_minus_is_not_mistaken_for_a_number(self):
        # -1+1 is not a number, so it must not reach a <v> element where Excel
        # would try to make sense of it.
        self.assertFalse(survives_as_a_number("-1+1"))


class OddCharacters(unittest.TestCase):
    def test_unicode_tabs_and_newlines_survive(self):
        rows = [["emoji \u2713 \u00e9\u4e2d", "tab\there", "new\nline"]]
        self.assertEqual(read_xlsx(written(["a", "b", "c"], rows))[1:], rows)

    def test_xml_special_characters_survive(self):
        rows = [["<script>", "a & b", '"quoted"', "it's"]]
        self.assertEqual(read_xlsx(written(["a", "b", "c", "d"], rows))[1:], rows)


class Letters(unittest.TestCase):
    def test_column_letters(self):
        for index, expected in ((0, "A"), (25, "Z"), (26, "AA"), (27, "AB"), (51, "AZ"),
                                (52, "BA"), (701, "ZZ"), (702, "AAA")):
            self.assertEqual(column_letter(index), expected, index)


if __name__ == "__main__":
    unittest.main()


class Colours(unittest.TestCase):
    """A value the plugin gave a colour to keeps it in the spreadsheet."""

    def parts(self, colours):
        body = write_xlsx(["id", "status"],
                          [["1", "red"], ["2", "amber"], ["3", "green"],
                           ["4", "blue"], ["5", "grey"], ["6", "something else"]],
                          colours=colours)
        archive = zipfile.ZipFile(io.BytesIO(body))
        return (archive.read("xl/worksheets/sheet1.xml").decode(),
                archive.read("xl/styles.xml").decode())

    MAP = {"status": {"red": "red", "amber": "amber", "green": "green",
                      "blue": "blue", "grey": "grey"}}

    def test_each_shade_gets_its_own_style(self):
        sheet, _ = self.parts(self.MAP)
        used = re.findall(r'<c r="B(\d+)" s="(\d+)"', sheet)
        # Row 1 is the header. Then one style per shade, all different.
        shades = [style for row, style in used if row != "1"][:5]
        self.assertEqual(len(set(shades)), 5, "five shades, five styles")

    def test_a_value_with_no_colour_keeps_the_ordinary_style(self):
        sheet, _ = self.parts(self.MAP)
        used = dict(re.findall(r'<c r="B(\d+)" s="(\d+)"', sheet))
        self.assertIn(used["7"], ("2", "3"), "the plain text styles")

    def test_the_style_sheet_counts_what_it_contains(self):
        # Excel refuses a file whose counts do not match the elements.
        _, styles = self.parts(self.MAP)
        for part, pattern in (("fonts", r"<font"), ("fills", r"<fill>"),
                              ("cellXfs", r"<xf ")):
            declared = int(re.search(rf'<{part} count="(\d+)"', styles).group(1))
            section = styles.split(f"<{part}")[1].split(f"</{part}>")[0]
            self.assertEqual(declared, len(re.findall(pattern, section)),
                             f"{part} says {declared}")

    def test_no_colours_means_the_file_is_as_it_was(self):
        plain, _ = self.parts(None)
        self.assertNotIn('s="6"', plain)

    def test_every_part_is_well_formed(self):
        body = write_xlsx(["id", "status"], [["1", "red"]], colours=self.MAP)
        archive = zipfile.ZipFile(io.BytesIO(body))
        for name in archive.namelist():
            ElementTree.fromstring(archive.read(name))
