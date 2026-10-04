// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 NovaForge2
//
// Which colour a cell gets, from the rules in a plugin's [colour] section.
//
// The rules arrive already parsed - {op: ">", n: 90} or {is: "ok"} - because
// the manifest is read in Python and the syntax should be understood in one
// place, not two. All that is left here is the test itself, which the
// spreadsheet also runs, in snapgrid/manifest.py shade_for. The two have to
// agree: a workbook that colours different cells from the page it came from
// would be worse than one with no colour at all.
//
// Tested in tests/colour.test.js.

"use strict";

function shadeFor(rules, value) {
  if (!rules || !rules.length) return "";
  const text = String(value === undefined || value === null ? "" : value).trim();

  // Number() says 0 for an empty string, which would make "< 10" match every
  // blank cell in the column.
  const number = text === "" ? NaN : Number(text);
  const isNumber = Number.isFinite(number);

  for (const rule of rules) {
    if (rule.is !== undefined) {
      if (text.toLowerCase() === rule.is) return rule.colour;
      continue;
    }
    // A comparison needs a number. A blank or a word is not one, and is left
    // for a later rule or for no colour at all.
    if (!isNumber) continue;
    const n = rule.n;
    const hit = rule.op === ">"  ? number > n
              : rule.op === ">=" ? number >= n
              : rule.op === "<"  ? number < n
              : rule.op === "<=" ? number <= n
              : rule.op === "="  ? number === n
              :                    number !== n;
    if (hit) return rule.colour;
  }
  return "";
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = { shadeFor };
}
