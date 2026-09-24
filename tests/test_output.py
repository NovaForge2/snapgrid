# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 NovaForge2
"""Turning what a plugin printed into a table."""

import unittest

from snapgrid.runner import OutputError, parse_csv


class Reading(unittest.TestCase):
    def test_header_then_rows(self):
        columns, rows = parse_csv("a,b\n1,2\n3,4\n", None)
        self.assertEqual(columns, ["a", "b"])
        self.assertEqual(rows, [["1", "2"], ["3", "4"]])

    def test_header_only_is_an_empty_table_not_an_error(self):
        columns, rows = parse_csv("a,b\n", None)
        self.assertEqual(columns, ["a", "b"])
        self.assertEqual(rows, [])

    def test_a_comma_inside_a_quoted_value(self):
        _, rows = parse_csv('a,b\n"x,y",2\n', None)
        self.assertEqual(rows, [["x,y", "2"]])

    def test_quotes_inside_a_value(self):
        _, rows = parse_csv('a\n"say ""hi"""\n', None)
        self.assertEqual(rows, [['say "hi"']])

    def test_carriage_return_line_endings(self):
        # Plenty of scripts and platforms print CRLF.
        columns, rows = parse_csv("a,b\r\n1,2\r\n", None)
        self.assertEqual(columns, ["a", "b"])
        self.assertEqual(rows, [["1", "2"]])

    def test_byte_order_mark_is_ignored(self):
        # Some shells and editors put one at the start of the output.
        columns, _ = parse_csv("﻿a,b\n1,2\n", None)
        self.assertEqual(columns, ["a", "b"])

    def test_blank_lines_are_skipped(self):
        _, rows = parse_csv("a,b\n1,2\n\n3,4\n\n\n", None)
        self.assertEqual(rows, [["1", "2"], ["3", "4"]])

    def test_a_short_row_is_padded_rather_than_refused(self):
        _, rows = parse_csv("a,b,c\n1,2\n", None)
        self.assertEqual(rows, [["1", "2", ""]])

    def test_headers_are_trimmed(self):
        columns, _ = parse_csv("a , b \n1,2\n", None)
        self.assertEqual(columns, ["a", "b"])

    def test_values_keep_their_spacing(self):
        _, rows = parse_csv("a\n  padded  \n", None)
        self.assertEqual(rows, [["  padded  "]])

    def test_non_ascii_survives(self):
        _, rows = parse_csv("name\nJosé\n", None)
        self.assertEqual(rows, [["José"]])


class Refusals(unittest.TestCase):
    def test_no_output_at_all(self):
        with self.assertRaises(OutputError) as caught:
            parse_csv("", None)
        self.assertIn("printed nothing", str(caught.exception))

    def test_only_blank_lines(self):
        with self.assertRaises(OutputError):
            parse_csv("\n\n\n", None)

    def test_an_empty_header_line(self):
        with self.assertRaises(OutputError) as caught:
            parse_csv(",,\n1,2,3\n", None)
        self.assertIn("column names", str(caught.exception))

    def test_too_many_values_names_the_line(self):
        # The usual cause is a comma in a value that was not quoted, so the
        # message has to point at the line and say so.
        with self.assertRaises(OutputError) as caught:
            parse_csv("a,b\n1,2\n3,4,5\n", None)
        message = str(caught.exception)
        self.assertIn("line 3", message)
        self.assertIn("quoted", message)


class AgainstDeclaredColumns(unittest.TestCase):
    def test_matching_header_is_accepted(self):
        columns, rows = parse_csv("a,b\n1,2\n", ["a", "b"])
        self.assertEqual(columns, ["a", "b"])
        self.assertEqual(rows, [["1", "2"]])

    def test_different_names_are_refused_and_both_lists_shown(self):
        with self.assertRaises(OutputError) as caught:
            parse_csv("x,y\n1,2\n", ["a", "b"])
        message = str(caught.exception)
        self.assertIn("['a', 'b']", message)
        self.assertIn("['x', 'y']", message)

    def test_a_reordered_header_is_refused(self):
        # Silently accepting this would put values under the wrong heading.
        with self.assertRaises(OutputError):
            parse_csv("b,a\n1,2\n", ["a", "b"])

    def test_an_extra_column_is_refused(self):
        with self.assertRaises(OutputError):
            parse_csv("a,b,c\n1,2,3\n", ["a", "b"])


if __name__ == "__main__":
    unittest.main()
