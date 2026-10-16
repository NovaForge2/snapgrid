# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 NovaForge2
"""Writing an .xlsx, with the standard library and nothing else.

Why bother, when Excel opens a CSV: because Excel *interprets* a CSV. It turns
1.10 into 1.1, strips the leading zero off 0042, reads 3-4 as a date and puts
long numbers into scientific notation. For a table of version numbers and
identifiers that is not a formatting preference, it is data loss. A cell
written as text in an .xlsx arrives as exactly what was written.

An .xlsx is a zip of XML, which the standard library can write as easily as it
reads. Excel is strict about that XML: anything it does not like produces a
"we found a problem with some content" dialog rather than a useful error, so
everything here sticks to the smallest valid shape and nothing clever.

What the sheet gets, following what a reader expects of a generated report:

* one unmerged header row, bold, on a filled background, frozen so it stays
  while scrolling;
* an autofilter on that row, so the dropdowns line up with the right columns;
* thin borders and banded rows, so a wide table can be read across;
* column widths from the content;
* numbers stored as numbers only when the whole column is numeric, so a column
  of versions keeps its text and a column of counts can still be summed.
"""

from __future__ import annotations

import re
import zipfile
from xml.sax.saxutils import escape

from .colour import shade_for

HEADER_FILL = "FF2F6F4E"       # the same green as the page
HEADER_TEXT = "FFFFFFFF"
BAND_FILL = "FFF3F6F4"         # a very light tint for every other row
# Dark enough to be seen as a border rather than mistaken for Excel's own
# gridlines, which this file switches off so these are the only lines drawn.
LINE = "FF9AA4AF"

# [colour] in plugin.toml, as Excel sees it: the same five, in the lighter of
# the two themes, because a spreadsheet is printed and read on white.
SHADES = {
    "red":   ("FF9B2C2C", "FFFDECEC"),
    "amber": ("FF8A5A00", "FFFDF3E0"),
    "green": ("FF1F6340", "FFE7F5ED"),
    "blue":  ("FF1F4E79", "FFE8F1FA"),
    "grey":  ("FF4A5260", "FFEEF0F3"),
}
# Where each shade's style sits in cellXfs, after the six that were there.
SHADE_STYLE = {name: 6 + index for index, name in enumerate(SHADES)}

MAX_WIDTH = 60
MIN_WIDTH = 8

# A value Excel would mangle if it were left to guess: anything that is not
# plainly a number is written as text.
NUMBER_RE = re.compile(r"^-?(\d+\.?\d*|\.\d+)$")


def column_letter(index: int) -> str:
    """0 -> A, 25 -> Z, 26 -> AA."""
    letters = ""
    index += 1
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def survives_as_a_number(value: str) -> bool:
    """True only when Excel would hand this exact text back again.

    The test is a round trip rather than a pattern. "1.10" is a perfectly good
    number and Excel stores it as 1.1, which is the same number and the wrong
    version. "0042" is 42. Twenty digits is 1E+20. Each of those is a number
    that does not survive being one, so it has to stay text.
    """
    if not NUMBER_RE.match(value):
        return False
    if "." in value:
        try:
            return repr(float(value)) == value
        except ValueError:
            return False
    try:
        # str(int()) drops a leading zero and a leading +, so a mismatch means
        # the text carried something the number does not.
        return str(int(value)) == value and len(value.lstrip("-")) <= 15
    except ValueError:
        return False


def looks_numeric(values: list[str]) -> bool:
    """True when every value in the column is safely a number.

    Whole columns, not single cells. One numeric-looking value in a column of
    versions proves nothing, and a column is only stored as numbers when every
    value in it comes back unchanged - otherwise the lot stays text, which is
    always correct and merely loses the ability to sum it.
    """
    seen = False
    for value in values:
        if value == "":
            continue
        if not survives_as_a_number(value):
            return False
        seen = True
    return seen


def _sheet_xml(columns: list[str], rows: list[list[str]], numeric: list[bool],
               colours: dict[str, list[dict]] | None = None) -> str:
    out = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">',
    ]
    last = column_letter(len(columns) - 1)
    span = f"A1:{last}{len(rows) + 1}"

    widths = []
    for index, name in enumerate(columns):
        longest = len(name)
        for row in rows:
            if index < len(row):
                longest = max(longest, len(row[index]))
        # Room for the filter arrow on the header, and a little air.
        widths.append(min(MAX_WIDTH, max(MIN_WIDTH, longest + 4)))
    out.append("<cols>")
    for index, width in enumerate(widths, start=1):
        out.append(f'<col min="{index}" max="{index}" width="{width}" customWidth="1"/>')
    out.append("</cols>")

    # Freeze below the header, so it stays while the rows scroll under it.
    out.insert(2, '<sheetViews><sheetView workbookViewId="0" tabSelected="1" showGridLines="0">'
                  '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
                  '<selection pane="bottomLeft" activeCell="A2" sqref="A2"/>'
                  '</sheetView></sheetViews>'
                  '<sheetFormatPr defaultRowHeight="15"/>')
    shades = colours or {}

    def shade_of(column: str, value: str) -> str:
        return shade_for(shades.get(column), value)

    out.append(f'<sheetData>')

    out.append('<row r="1" spans="1:%d" ht="20" customHeight="1">' % len(columns))
    for index, name in enumerate(columns):
        reference = f"{column_letter(index)}1"
        out.append(f'<c r="{reference}" s="1" t="inlineStr">'
                   f"<is><t>{escape(name)}</t></is></c>")
    out.append("</row>")

    for number, row in enumerate(rows, start=2):
        banded = number % 2 == 0
        out.append(f'<row r="{number}" spans="1:{len(columns)}">')
        for index in range(len(columns)):
            value = row[index] if index < len(row) else ""
            reference = f"{column_letter(index)}{number}"
            # A value the plugin gave a colour to keeps it here, so the
            # spreadsheet says the same thing as the page. It overrides the
            # banding, which is decoration, where this is meaning.
            shade = shade_of(columns[index], value)
            if shade:
                style = str(SHADE_STYLE[shade])
            # A number carrying the text format makes Excel flag every cell
            # with a green corner, so the two kinds get their own styles.
            elif numeric[index]:
                style = "5" if banded else "4"
            else:
                style = "3" if banded else "2"
            if value == "":
                out.append(f'<c r="{reference}" s="{style}"/>')
            elif numeric[index]:
                out.append(f'<c r="{reference}" s="{style}"><v>{escape(value)}</v></c>')
            else:
                out.append(f'<c r="{reference}" s="{style}" t="inlineStr">'
                           f"<is><t>{escape(value)}</t></is></c>")
        out.append("</row>")

    out.append("</sheetData>")
    out.append(f'<autoFilter ref="{span}"/>')
    out.append("</worksheet>")
    return "".join(out)


_SHADE_FONTS = "".join(
    f'<font><b/><sz val="11"/><color rgb="{text}"/><name val="Calibri"/></font>'
    for text, _ in SHADES.values()
)
_SHADE_FILLS = "".join(
    f'<fill><patternFill patternType="solid"><fgColor rgb="{fill}"/>'
    f'<bgColor indexed="64"/></patternFill></fill>'
    for _, fill in SHADES.values()
)
_SHADE_XFS = "".join(
    f'<xf numFmtId="49" fontId="{2 + index}" fillId="{4 + index}" borderId="1" xfId="0" '
    f'applyFont="1" applyFill="1" applyBorder="1"/>'
    for index in range(len(SHADES))
)

STYLES = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <fonts count="{2 + len(SHADES)}">
    <font><sz val="11"/><name val="Calibri"/></font>
    <font><b/><sz val="11"/><color rgb="{HEADER_TEXT}"/><name val="Calibri"/></font>
    {_SHADE_FONTS}
  </fonts>
  <fills count="{4 + len(SHADES)}">
    <fill><patternFill patternType="none"/></fill>
    <fill><patternFill patternType="gray125"/></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="{HEADER_FILL}"/><bgColor indexed="64"/></patternFill></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="{BAND_FILL}"/><bgColor indexed="64"/></patternFill></fill>
    {_SHADE_FILLS}
  </fills>
  <borders count="3">
    <border><left/><right/><top/><bottom/><diagonal/></border>
    <border>
      <left style="thin"><color rgb="{LINE}"/></left>
      <right style="thin"><color rgb="{LINE}"/></right>
      <top style="thin"><color rgb="{LINE}"/></top>
      <bottom style="thin"><color rgb="{LINE}"/></bottom>
      <diagonal/>
    </border>
    <border>
      <left style="thin"><color rgb="{HEADER_FILL}"/></left>
      <right style="thin"><color rgb="{HEADER_FILL}"/></right>
      <top style="thin"><color rgb="{HEADER_FILL}"/></top>
      <bottom style="medium"><color rgb="{HEADER_FILL}"/></bottom>
      <diagonal/>
    </border>
  </borders>
  <cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
  <cellXfs count="{6 + len(SHADES)}">
    <xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
    <xf numFmtId="0" fontId="1" fillId="2" borderId="2" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1">
      <alignment vertical="center"/>
    </xf>
    <xf numFmtId="49" fontId="0" fillId="0" borderId="1" xfId="0" applyBorder="1"/>
    <xf numFmtId="49" fontId="0" fillId="3" borderId="1" xfId="0" applyFill="1" applyBorder="1"/>
    <xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyBorder="1"/>
    <xf numFmtId="0" fontId="0" fillId="3" borderId="1" xfId="0" applyFill="1" applyBorder="1"/>
    {_SHADE_XFS}
  </cellXfs>
  <cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>'''

CONTENT_TYPES = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
</Types>'''

ROOT_RELS = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>'''

WORKBOOK_RELS = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>'''


def _workbook_xml(sheet_name: str, columns: int, rows: int) -> str:
    # A defined name makes the header row repeat on every printed page, which
    # is what anyone who prints one of these will want.
    last = column_letter(max(columns - 1, 0))
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<sheets><sheet name="{escape(sheet_name)}" sheetId="1" r:id="rId1"/></sheets>'
        '<definedNames>'
        f'<definedName name="_xlnm._FilterDatabase" localSheetId="0" hidden="1">'
        f"'{escape(sheet_name)}'!$A$1:${last}${rows + 1}</definedName>"
        f'<definedName name="_xlnm.Print_Titles" localSheetId="0">'
        f"'{escape(sheet_name)}'!$1:$1</definedName>"
        '</definedNames>'
        "</workbook>"
    )


def safe_sheet_name(name: str) -> str:
    """Excel refuses : \\ / ? * [ ] and anything over 31 characters."""
    cleaned = re.sub(r"[:\\/?*\[\]]", " ", name).strip() or "Sheet1"
    return cleaned[:31]


def write_xlsx(columns: list[str], rows: list[list[str]], sheet_name: str = "Sheet1",
               colours: dict[str, list[dict]] | None = None) -> bytes:
    """The table as an .xlsx file, ready to be sent."""
    import io

    if not columns:
        columns = ["(no columns)"]
    name = safe_sheet_name(sheet_name)
    numeric = [
        looks_numeric([row[index] if index < len(row) else "" for row in rows])
        for index in range(len(columns))
    ]

    buffer = io.BytesIO()
    # Deflate, and a fixed date so the same table gives the same bytes.
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, text in (
            ("[Content_Types].xml", CONTENT_TYPES),
            ("_rels/.rels", ROOT_RELS),
            ("xl/workbook.xml", _workbook_xml(name, len(columns), len(rows))),
            ("xl/_rels/workbook.xml.rels", WORKBOOK_RELS),
            ("xl/styles.xml", STYLES),
            ("xl/worksheets/sheet1.xml", _sheet_xml(columns, rows, numeric, colours)),
        ):
            item = zipfile.ZipInfo(path, date_time=(1980, 1, 1, 0, 0, 0))
            item.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(item, text)
    return buffer.getvalue()
