# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 NovaForge2
"""Reading an .xlsx file without anything installed.

An .xlsx is a zip archive of XML, and the standard library has both a zip
reader and an XML parser, so no third party library is needed. That matters
here: a spreadsheet somebody else maintains is a perfectly ordinary source of
a table, and needing pip to read one would defeat the point of the project.

What is supported: one sheet, text, numbers, booleans, dates and times, shared
and inline strings, formulas by way of the value Excel last calculated and
stored, and rows with gaps in them.

What is not: the old binary .xls format, charts, images, merged cell spanning,
and formulas that have never been calculated. Anything unsupported is reported
plainly rather than guessed at.

Dates are the awkward part. Excel stores them as a count of days since the end
of 1899, and whether a number is a date is decided by the format applied to the
cell, not by the value. So the styles have to be read to know that 45914 means
a day in 2025 and not the number forty-five thousand.
"""

from __future__ import annotations

import re
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from xml.etree import ElementTree

MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
RELS = "{http://schemas.openxmlformats.org/package/2006/relationships}"
DOC_RELS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"

# Formats Excel ships with that mean a date or a time.
BUILTIN_DATE_FORMATS = set(range(14, 23)) | set(range(45, 48))
CELL_REFERENCE = re.compile(r"([A-Z]+)(\d+)")

# Excel counts days from this date. The offset is two days rather than one
# because Excel also believes 1900 was a leap year, and files written since
# depend on that mistake.
EPOCH = datetime(1899, 12, 30)


class SpreadsheetError(Exception):
    """The file cannot be read, with a reason worth showing someone."""


def column_number(reference: str) -> int:
    """A1 -> 0, B1 -> 1, AA1 -> 26."""
    match = CELL_REFERENCE.match(reference)
    letters = match.group(1) if match else reference
    number = 0
    for character in letters:
        number = number * 26 + (ord(character) - ord("A") + 1)
    return number - 1


def serial_to_text(value: float) -> str:
    """Turn Excel's day count into something that sorts correctly as text."""
    # Excel believes 29 February 1900 existed. Every date after it is therefore
    # consistent with an epoch of 30 December 1899, and every date before it is
    # a day out, so the first sixty values need the day put back.
    moment = EPOCH + timedelta(days=value + 1 if value < 60 else value)
    if value < 1:                      # a time on its own, with no date
        return moment.strftime("%H:%M:%S")
    if abs(value - int(value)) < 1e-9:  # midnight, so a plain date
        return moment.strftime("%Y-%m-%d")
    return moment.strftime("%Y-%m-%d %H:%M")


def tidy_number(text: str) -> str:
    """Keep numbers looking like the user typed them.

    Excel stores 3 as "3" but 3.10 as "3.1", and floating point leaves values
    such as 0.30000000000000004 in files. Neither belongs in a table.
    """
    try:
        number = float(text)
    except ValueError:
        return text
    if number == int(number) and abs(number) < 1e15:
        return str(int(number))
    return f"{round(number, 10):g}"


def _text_of(element) -> str:
    """All the text inside an element, including runs of formatted text."""
    return "".join(node.text or "" for node in element.iter(f"{MAIN}t"))


def _shared_strings(archive: zipfile.ZipFile) -> list[str]:
    try:
        root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    return [_text_of(item) for item in root.findall(f"{MAIN}si")]


def _date_styles(archive: zipfile.ZipFile) -> set[int]:
    """Which style indexes mean the cell holds a date or a time."""
    try:
        root = ElementTree.fromstring(archive.read("xl/styles.xml"))
    except KeyError:
        return set()

    custom: dict[int, str] = {}
    for entry in root.iter(f"{MAIN}numFmt"):
        try:
            custom[int(entry.get("numFmtId", "-1"))] = entry.get("formatCode", "")
        except ValueError:
            continue

    dated = set()
    cell_formats = root.find(f"{MAIN}cellXfs")
    for index, entry in enumerate(cell_formats or []):
        try:
            format_id = int(entry.get("numFmtId", "0"))
        except ValueError:
            continue
        if format_id in BUILTIN_DATE_FORMATS:
            dated.add(index)
        elif format_id in custom:
            # A custom format is a date if it mentions days, months, years or
            # hours outside a quoted literal.
            code = re.sub(r'"[^"]*"', "", custom[format_id]).lower()
            if any(marker in code for marker in ("yy", "mm", "dd", "hh", "ss")):
                dated.add(index)
    return dated


def _sheet_path(archive: zipfile.ZipFile, wanted: str | None) -> str:
    """Find the worksheet to read, by name or the first one in the workbook."""
    try:
        workbook = ElementTree.fromstring(archive.read("xl/workbook.xml"))
        relationships = ElementTree.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    except KeyError as exc:
        raise SpreadsheetError("this does not look like an .xlsx workbook") from exc

    targets = {
        node.get("Id"): node.get("Target", "")
        for node in relationships.findall(f"{RELS}Relationship")
    }

    sheets = []
    for sheet in workbook.iter(f"{MAIN}sheet"):
        name = sheet.get("name", "")
        target = targets.get(sheet.get(f"{DOC_RELS}id", ""), "")
        if target:
            sheets.append((name, target))

    if not sheets:
        raise SpreadsheetError("the workbook contains no sheets")

    if wanted:
        for name, target in sheets:
            if name == wanted:
                return target if target.startswith("xl/") else f"xl/{target.lstrip('/')}"
        available = ", ".join(name for name, _ in sheets)
        raise SpreadsheetError(f"no sheet called {wanted!r}. This workbook has: {available}")

    target = sheets[0][1]
    return target if target.startswith("xl/") else f"xl/{target.lstrip('/')}"


def read_xlsx(path: Path, sheet: str | None = None) -> list[list[str]]:
    """Read one sheet as rows of text. The first row is the header."""
    if not zipfile.is_zipfile(path):
        raise SpreadsheetError(
            f"{path.name} is not an .xlsx file. The old binary .xls format is not "
            f"supported - open it in a spreadsheet program and save it as .xlsx or .csv."
        )

    try:
        with zipfile.ZipFile(path) as archive:
            strings = _shared_strings(archive)
            dated = _date_styles(archive)
            worksheet = ElementTree.fromstring(archive.read(_sheet_path(archive, sheet)))
    except SpreadsheetError:
        raise
    except (KeyError, zipfile.BadZipFile, ElementTree.ParseError) as exc:
        raise SpreadsheetError(f"cannot read {path.name}: {exc}") from exc

    rows: list[list[str]] = []
    for row in worksheet.iter(f"{MAIN}row"):
        values: dict[int, str] = {}
        for cell in row.findall(f"{MAIN}c"):
            index = column_number(cell.get("r", "")) if cell.get("r") else len(values)
            values[index] = _cell_value(cell, strings, dated)
        if not values:
            continue
        width = max(values) + 1
        rows.append([values.get(position, "") for position in range(width)])

    while rows and all(value.strip() == "" for value in rows[-1]):
        rows.pop()
    return rows


def _cell_value(cell, strings: list[str], dated: set[int]) -> str:
    kind = cell.get("t", "n")

    if kind == "inlineStr":
        return _text_of(cell)

    value = cell.find(f"{MAIN}v")
    if value is None or value.text is None:
        # A formula that has never been calculated has no stored value.
        return ""
    text = value.text

    if kind == "s":
        try:
            return strings[int(text)]
        except (ValueError, IndexError):
            return ""
    if kind in ("str", "e"):
        return text
    if kind == "b":
        return "TRUE" if text == "1" else "FALSE"

    try:
        style = int(cell.get("s", "-1"))
    except ValueError:
        style = -1
    if style in dated:
        try:
            return serial_to_text(float(text))
        except (ValueError, OverflowError):
            return text
    return tidy_number(text)
