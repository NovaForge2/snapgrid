// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 NovaForge2
//
// Working out what changed between runs. Pure functions: they are given the
// runs and the name of the key column, and they return what differs. Nothing
// here touches the page, the network or any shared state.
//
// It lives in its own file for one reason. Everything in here decides what a
// person is told about their data, and "nothing changed" is an answer that
// has to be right. Four bugs in this logic were found by people reading the
// screen rather than by anything automatic, which is a bad way to find them.
// Separated from the page, it can be tested directly - see tests/compare.test.js,
// which node runs and ./run-tests.py includes.
//
// The guiding rule throughout: when the comparison cannot be worked out
// reliably, say so. Never guess and never quietly show less than was asked
// for.

"use strict";

// What separates the values inside one cell. A plugin printing several lines
// under one name has them merged into one row, and the cell holds them as
// lines. A zero byte, because any character a person can type is a character
// some table already holds: a separator that can also be a value would split
// one value into two and say it changed.
const LINES = "\u0000";

// [table] key, as a list of names whatever it was written as. A plugin may
// name one column or several, and an older server sends a bare string.
function keyNamesOf(keyName) {
  if (Array.isArray(keyName)) return keyName.filter(Boolean);
  return keyName ? [keyName] : [];
}

// The columns that name each row: [table] key, or the first column. Without
// one, a changed value looks like a row leaving and another arriving, which
// is true and useless.
//
// More than one when no single column is unique. In "environment,repo,version"
// the environment repeats on every repo and the repo repeats in every
// environment; the pair names the row, and nothing else does.
function keyIndexesIn(columns, keyName) {
  const names = keyNamesOf(keyName);
  if (!names.length) return [0];
  const out = names.map((name) => columns.indexOf(name)).filter((index) => index >= 0);
  return out.length ? out : [0];
}

// Kept for the one caller that wants somewhere to hang the name chip: the
// leftmost of the key columns.
function keyIndexIn(columns, keyName) {
  return keyIndexesIn(columns, keyName)[0];
}

// What names this row, across however many columns name it. Stringified
// rather than joined, because any separator can also be a value and two
// different rows would then read as one.
function keyTextOf(row, keyIndexes) {
  if (keyIndexes.length === 1) return cellValue(row, keyIndexes[0]);
  return JSON.stringify(keyIndexes.map((index) => cellValue(row, index)));
}

// [table] key naming columns the result does not have. The manifest can only
// catch that when [table] columns is declared as well, so most of the time
// the first this can be known is here, with a result in hand. Falling back to
// the leftmost column would compare by whatever happens to be there and say
// nothing about it.
function missingKeyColumns(columns, keyName) {
  return keyNamesOf(keyName).filter((name) => !columns.includes(name));
}

function missingKeyColumn(columns, keyName) {
  return missingKeyColumns(columns, keyName)[0] || "";
}

function cellValue(row, index) {
  return row[index] === undefined ? "" : row[index];
}

function sameRow(a, b, columns, ignored) {
  if (a === null || b === null) return a === b;
  return columns.every((_, index) => (ignored && ignored.has(index))
                                     || cellValue(a, index) === cellValue(b, index));
}

// The columns the comparison is told to leave alone, as indexes: [compare]
// ignore from plugin.toml, and whatever is hidden on screen. A column holding
// the time the plugin last looked moves on every run, so a table with one in
// it is never equal to itself and "what changed" answers with the clock.
//
// Never the column that names the row. That one is identity rather than a
// value: taken out of the row text below, two different things would read as
// the same thing.
function ignoredIndexes(columns, ignore, keyName) {
  const names = new Set(ignore || []);
  for (const index of keyIndexesIn(columns, keyName)) names.delete(columns[index]);
  const out = new Set();
  columns.forEach((column, index) => { if (names.has(column)) out.add(index); });
  return out;
}

// A row as one piece of text, for asking whether two of them say the same
// thing without walking their columns twice.
function rowText(row) {
  return JSON.stringify(row);
}

// The same, with the ignored columns blanked out, so that two rows differing
// only in one of them are one row that stayed rather than one that went and
// another that arrived. Written as a function of the columns so that a row
// which stops early and one spelling the blank out still read alike.
function rowTextIgnoring(row, columns, ignored) {
  if (!ignored || !ignored.size) return rowText(row);
  return JSON.stringify(columns.map((_, index) =>
    (ignored.has(index) ? "" : cellValue(row, index))));
}

// Two rows that are identical once a column is taken off the screen are not
// two facts any more; they are one fact written twice. This keeps the first
// and counts the rest.
//
// Counted rather than quietly dropped. `1|2|4` and `1|5|4` become one row the
// moment B is hidden, and a table saying there is one of a thing when there
// are two is wrong in the direction that matters - the same direction as
// saying a port is free when it is taken.
//
// Only the columns on screen decide. That is the whole point: the duplicates
// exist *because* something was hidden.
function compactRows(rows, shownIndexes) {
  const seen = new Map();
  const kept = [];
  const counts = new Map();
  for (const row of rows) {
    // Stringified rather than joined on a separator, because any separator
    // can also be a value, and two different rows would then compact into
    // one on a comma.
    const key = JSON.stringify(shownIndexes.map((index) => cellValue(row, index)));
    const first = seen.get(key);
    if (first === undefined) {
      seen.set(key, row);
      kept.push(row);
      counts.set(row, 1);
    } else {
      counts.set(first, counts.get(first) + 1);
    }
  }
  return { rows: kept, counts };
}

// How many rows would go if it were turned on. Said in the row count while it
// is off, which is how the button gets noticed without a popup announcing it.
function duplicateCount(rows, shownIndexes) {
  return rows.length - compactRows(rows, shownIndexes).rows.length;
}

// Every row the key names, in the order the plugin printed them. One row is
// the ordinary case. Several mean the plugin printed more than one line under
// the same name, and those lines are that row's values rather than rows of
// their own: blue and green of one service, two pods of one deployment.
function groupByKey(columns, rows, keyName) {
  const indexes = keyIndexesIn(columns, keyName);
  const groups = new Map();
  for (const row of rows) {
    const name = keyTextOf(row, indexes);
    const group = groups.get(name);
    if (group) group.push(row);
    else groups.set(name, [row]);
  }
  return groups;
}

// What one column holds across a group, each value written once, in the order
// the plugin printed it. Printed order rather than sorted: a cell is read
// beside the cells next to it, and sorting each column on its own would put
// one line's status next to another line's branch.
function valuesIn(group, index) {
  const out = [];
  const seen = new Set();
  for (const row of group) {
    const value = cellValue(row, index);
    if (seen.has(value)) continue;
    seen.add(value);
    out.push(value);
  }
  return out;
}

// One row for the key, whatever the plugin printed under it. A cell holding
// several values holds them as lines, and the table draws a line each.
function mergeGroup(columns, group) {
  if (group.length === 1) return group[0];
  return columns.map((_, index) => valuesIn(group, index).join(LINES));
}

// A cell as the lines it holds. Every cell has at least one.
function linesOf(value) {
  return String(value === undefined || value === null ? "" : value).split(LINES);
}

// Whether two groups of the same name say the same thing. The order the rows
// arrived in is not part of it: a plugin that lists two pods the other way
// round has not changed anything.
function sameGroup(a, b, columns, ignored) {
  if (a === null || b === null) return a === b;
  if (a.length !== b.length) return false;
  const textOf = (group) => group.map((row) => rowTextIgnoring(row, columns, ignored)).sort();
  const left = textOf(a);
  const right = textOf(b);
  return left.every((text, at) => text === right[at]);
}

// How many of one column's values changed between two groups. One value each
// side and a different value is one change, which is the ordinary row. Where
// a group holds several, it is the larger of what arrived and what went, so
// that one image replacing another counts once rather than twice.
function changedValues(before, after, index) {
  const was = new Set(valuesIn(before, index));
  const now = new Set(valuesIn(after, index));
  let gone = 0;
  let fresh = 0;
  for (const value of was) if (!now.has(value)) gone += 1;
  for (const value of now) if (!was.has(value)) fresh += 1;
  return Math.max(gone, fresh);
}

// What each row looks like across the runs given, newest first, or a reason it
// cannot be worked out. A row is included if it was there in any of them, so
// one that has gone is still visible - that is the thing worth noticing.
//
// A row here is a name and the lines the plugin printed under it. A repeating
// key is not an error and never was worth refusing to compare: the lines under
// one name are that row's values, and a value that moved is drawn inside the
// cell it moved in.
function compareRuns(runs, keyName, ignore) {
  if (!runs || runs.length < 2) return null;

  const current = runs[0];
  const columns = current.columns;

  const shape = columns.join("\u0000");
  if (runs.some((run) => run.columns.join("\u0000") !== shape)) {
    return { impossible: "the columns are not the same in every run" };
  }

  const missing = missingKeyColumns(columns, keyName);
  if (missing.length) {
    return { impossible: `[table] key names ${missing.map((name) => `"${name}"`).join(", ")}, `
                         + `and this result has no column of that name - it has `
                         + columns.join(", ") };
  }

  const keys = keyIndexesIn(columns, keyName);
  const keySet = new Set(keys);
  const ignored = ignoredIndexes(columns, ignore, keyName);
  const grouped = runs.map((run) => groupByKey(run.columns, run.rows, keyName));

  const names = [];
  const seen = new Set();
  for (const one of grouped) {
    for (const name of one.keys()) {
      if (!seen.has(name)) { seen.add(name); names.push(name); }
    }
  }

  const rows = new Map();
  let changedCells = 0;
  let added = 0;
  let removed = 0;

  for (const name of names) {
    // One entry per run: the lines printed under this name then, or null if
    // the name was not there at all.
    const overRuns = grouped.map((one) => one.get(name) || null);
    const here = overRuns[0] !== null;
    const everBefore = overRuns.slice(1).some((group) => group !== null);
    const moved = overRuns.some((group, at) =>
      at > 0 && !sameGroup(group, overRuns[at - 1], columns, ignored));

    if (here && !everBefore) added += 1;
    else if (!here && everBefore) removed += 1;

    if (here && everBefore && moved) {
      // The runs the row was in, in order. A row that went away and came back
      // is compared across the gap rather than through it: the arrival is a
      // fact about the row, said once by the chip, not by each of its cells.
      const present = overRuns.filter((group) => group !== null);
      columns.forEach((_, index) => {
        if (keySet.has(index) || ignored.has(index)) return;   // not a compared value
        for (let at = 1; at < present.length; at += 1) {
          changedCells += changedValues(present[at], present[at - 1], index);
        }
      });
    }
    rows.set(name, { overRuns, here, everBefore, moved });
  }
  return { rows, names, runs, changedCells, added, removed, ignored, keys };
}

// In the browser these are already global, because this is an ordinary script
// and the page loads it before app.js. Under node the same file is required by
// the tests, and this is the one line that makes that work.
if (typeof module !== "undefined" && module.exports) {
  module.exports = {
    keyIndexIn, keyIndexesIn, keyNamesOf, keyTextOf,
    missingKeyColumn, missingKeyColumns, cellValue, sameRow, rowText, rowTextIgnoring,
    ignoredIndexes, compareRuns, compactRows, duplicateCount,
    groupByKey, valuesIn, mergeGroup, linesOf, sameGroup, changedValues, LINES,
  };
}
