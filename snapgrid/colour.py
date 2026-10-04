# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 NovaForge2
"""Which colour a cell gets, from a plugin's [colour] rules.

The same test runs twice: here, for the spreadsheet, and in web/colour.js, for
the page. A workbook that coloured different cells from the screen it came
from would be worse than one with no colour at all, so the two are kept to the
same handful of lines and tested against the same cases.

The rules are parsed once, when the manifest is read, into {"op": ">", "n": 90}
or {"is": "ok"}. Nothing here has to understand the syntax.
"""

from __future__ import annotations

import re

# The whole set. Fixed deliberately: a plugin naming its own shades would be a
# plugin deciding what the page looks like, and the two themes would have to
# cope with whatever it picked.
COLOURS = ("red", "amber", "green", "blue", "grey")

# "> 90", ">=90", "< 7", "= 0", "!= 0" on the left of a [colour] line.
THRESHOLD_RE = re.compile(r"^(>=|<=|!=|>|<|=)\s*(-?\d+(?:\.\d+)?)$")


def shade_for(rules: list[dict] | None, value: str) -> str:
    """The colour for one cell, or "". The first rule that matches wins.

    The same test the page runs, kept here as well because the spreadsheet is
    written in Python and has to colour the identical cells.
    """
    if not rules:
        return ""
    text = (value or "").strip()
    number = None
    try:
        number = float(text)
    except ValueError:
        pass

    for rule in rules:
        if "is" in rule:
            if text.lower() == rule["is"]:
                return rule["colour"]
            continue
        # A comparison needs a number. A blank or a word is not one, and is
        # left for a later rule or for no colour at all.
        if number is None:
            continue
        op, n = rule["op"], rule["n"]
        hit = (number > n if op == ">" else
               number >= n if op == ">=" else
               number < n if op == "<" else
               number <= n if op == "<=" else
               number == n if op == "=" else
               number != n)
        if hit:
            return rule["colour"]
    return ""
