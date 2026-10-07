# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 NovaForge2
"""Rules in the stylesheet that quietly undo other rules.

The headings stopped being sticky for ten days and nobody noticed, because
nothing broke: `thead th { position: relative; }` was added lower down so a
resize grip had something to anchor to, and the later rule simply replaced the
`position: sticky` set above it. Both looked right on their own.

There is no DOM in these tests, so this cannot check that the headings stay
put. What it can check is that nothing later in the file takes the property
away again - which is the shape of the mistake, and the part a person reading
a diff is least likely to see.
"""

import re
import unittest
from pathlib import Path

STYLESHEET = Path(__file__).resolve().parent.parent / "web" / "style.css"

# selector { body } - enough for a stylesheet written by hand, with no nesting.
RULE_RE = re.compile(r"([^{}]+)\{([^{}]*)\}", re.DOTALL)


def declarations_for(target: str, property_name: str) -> list[tuple[str, str]]:
    """Every declaration of a property on rules aimed at exactly this
    selector, in the order the browser would apply them.

    Whole selectors, not substrings: `#table-wrap table.fixed td` is a rule
    about the cells, not about the box that scrolls, and treating it as the
    latter made this file fail on its own first run.
    """
    css = re.sub(r"/\*.*?\*/", "", STYLESHEET.read_text(encoding="utf-8"), flags=re.DOTALL)
    found = []
    for selectors, body in RULE_RE.findall(css):
        parts = [" ".join(one.split()) for one in selectors.split(",")]
        if target not in parts:
            continue
        for declaration in body.split(";"):
            name, _, value = declaration.partition(":")
            if name.strip() == property_name:
                found.append((" ".join(selectors.split()), value.strip()))
    return found


class TheHeadingsStayPut(unittest.TestCase):
    def test_nothing_takes_the_sticky_position_away(self):
        positions = declarations_for("thead th", "position")
        self.assertTrue(positions, "the headings have to be positioned at all")
        selector, value = positions[-1]
        self.assertEqual(value, "sticky",
                         f"the last word on where a heading sits is {selector!r}, "
                         f"saying {value!r}. A heading that scrolls away with the "
                         f"rows is the one thing it must not do")

    def test_the_scrolling_box_does_not_hide_its_overflow(self):
        # `overflow: hidden` on the ancestor that scrolls kills sticky as
        # surely as changing the position does, and just as quietly.
        for selector, value in declarations_for("#table-wrap", "overflow"):
            self.assertIn(value, ("auto", "scroll"), selector)


class TheGridScalesFromOnePlace(unittest.TestCase):
    """A px left inside the table does not grow with the text around it.

    The size buttons set one custom property; everything in the table is in
    em so that padding and the smaller type move with it. A stray px would
    leave a bigger font in a box built for a smaller one, and nobody would
    notice until they used the buttons.
    """

    def test_the_table_takes_its_size_from_the_property(self):
        sizes = declarations_for("table", "font-size")
        self.assertTrue(any("--grid-text" in value for _, value in sizes),
                        f"the table's font-size is {sizes}")

    def test_the_cells_are_padded_in_em(self):
        for selector in ("tbody td", ".th-inner"):
            for _, value in declarations_for(selector, "padding"):
                self.assertNotIn("px", value,
                                 f"{selector} padding is {value}, which will not scale")


class ThePillsAndTheGrid(unittest.TestCase):
    def test_a_coloured_value_keeps_its_place_in_a_column_of_numbers(self):
        # The pill's padding pushed digits out of line, so numeric columns
        # drop it. If that rule is lost the column stops lining up, which is
        # subtle enough to survive a review.
        padding = declarations_for("td.num .shade", "padding")
        self.assertEqual([value for _, value in padding][-1:], ["0"])


class TheStackedLinesStayLevel(unittest.TestCase):
    """The guides across a compared row are the bottom edge of each line, so
    they only line up while every line is the same height. An older line is
    set slightly smaller than the current one, which is exactly how they stop
    being the same height - and a guide half a pixel out across six columns
    reads as a table that has come apart."""

    def test_a_stacked_line_is_given_an_explicit_height(self):
        heights = declarations_for("td.stack .v", "height")
        self.assertTrue(heights, "without a height, a smaller line is a shorter line")
        selector, value = heights[-1]
        self.assertIn("--stack-line", value,
                      f"{selector!r} sets the height to {value!r}; it has to come "
                      f"from the one variable every cell in the row reads")

    def test_the_height_does_not_come_from_the_line_s_own_font(self):
        # `em` resolves against the element's own font-size, and an older line
        # has a smaller one. The variable is in px for that reason.
        for _, value in declarations_for("table", "--stack-line"):
            self.assertNotIn("em", value,
                             "an em here is a shorter em on the smaller lines")


class EveryElementTheScriptAsksForExists(unittest.TestCase):
    """app.js reaches for elements by id and gets null when one is not there,
    which fails at the first use - a long way from the renamed id, and only if
    that part of the page is ever opened. Moving the theme, the text size and
    the Log and Config buttons into a menu was a move of exactly this kind."""

    def test_no_id_is_asked_for_that_the_page_does_not_have(self):
        script = (STYLESHEET.parent / "app.js").read_text(encoding="utf-8")
        page = (STYLESHEET.parent / "index.html").read_text(encoding="utf-8")
        wanted = sorted(set(re.findall(r'\bel\("([^"]+)"\)', script)))
        self.assertTrue(wanted, "the pattern this reads for has changed")
        have = set(re.findall(r'id="([^"]+)"', page))
        self.assertEqual([one for one in wanted if one not in have], [])
