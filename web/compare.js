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

// The column that names each row: [table] key, or the first column. Without
// one, a changed value looks like a row leaving and another arriving, which
// is true and useless.
function keyIndexIn(columns, keyName) {
  const index = keyName ? columns.indexOf(keyName) : 0;
  return index >= 0 ? index : 0;
}

// [table] key naming a column the result does not have. The manifest can only
// catch that when [table] columns is declared as well, so most of the time
// the first this can be known is here, with a result in hand. Falling back to
// the leftmost column would compare by whatever happens to be there and say
// nothing about it.
function missingKeyColumn(columns, keyName) {
  return keyName && !columns.includes(keyName) ? keyName : "";
}

function cellValue(row, index) {
  return row[index] === undefined ? "" : row[index];
}

function sameRow(a, b, columns) {
  if (a === null || b === null) return a === b;
  return columns.every((_, index) => cellValue(a, index) === cellValue(b, index));
}

// A row compared as a whole, for when rows cannot be told apart by name.
function rowText(row) {
  return JSON.stringify(row);
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

function byKey(columns, rows, keyName) {
  const index = keyIndexIn(columns, keyName);
  const map = new Map();
  let duplicates = false;
  for (const row of rows) {
    const key = cellValue(row, index);
    if (map.has(key)) duplicates = true;
    else map.set(key, row);
  }
  return { map, duplicates };
}

// What each row looks like across the runs given, newest first, or a reason it
// cannot be worked out. A row is included if it was there in any of them, so
// one that has gone is still visible - that is the thing worth noticing.
function compareRuns(runs, keyName) {
  if (!runs || runs.length < 2) return null;

  const current = runs[0];
  const columns = current.columns;

  const shape = columns.join("\u0000");
  if (runs.some((run) => run.columns.join("\u0000") !== shape)) {
    return { impossible: "the columns are not the same in every run" };
  }

  const missing = missingKeyColumn(columns, keyName);
  if (missing) {
    return { impossible: `[table] key is "${missing}", and this result has no column `
                         + `of that name - it has ${columns.join(", ")}` };
  }

  const key = keyIndexIn(columns, keyName);
  const indexed = runs.map((run) => byKey(run.columns, run.rows, keyName));
  if (indexed.some((one) => one.duplicates)) {
    // Cell by cell comparison needs one row per name. Without that, whole
    // rows can still be compared - a row is the same row or it is not -
    // which is less, and is better than showing nothing.
    return wholeRows(runs, `more than one row is called the same thing in "${columns[key]}"`);
  }

  const names = [];
  const seen = new Set();
  for (const one of indexed) {
    for (const name of one.map.keys()) {
      if (!seen.has(name)) { seen.add(name); names.push(name); }
    }
  }

  const rows = new Map();
  let changedCells = 0;
  let added = 0;
  let removed = 0;

  for (const name of names) {
    // One entry per run: the row as it was then, or null if it was not there.
    const overRuns = indexed.map((one) => one.map.get(name) || null);
    const here = overRuns[0] !== null;
    const everBefore = overRuns.slice(1).some((row) => row !== null);
    const moved = overRuns.some((row, at) =>
      at > 0 && !sameRow(row, overRuns[at - 1], columns));

    if (here && !everBefore) added += 1;
    else if (!here && everBefore) removed += 1;

    if (here && everBefore && moved) {
      columns.forEach((_, index) => {
        if (index === key) return;            // the name is not a value
        const values = overRuns.map((row) => (row ? cellValue(row, index) : null));
        for (let at = 1; at < values.length; at += 1) {
          if (values[at] !== null && values[at] !== values[at - 1]) changedCells += 1;
        }
      });
    }
    rows.set(name, { overRuns, here, everBefore, moved });
  }
  return { rows, names, runs, changedCells, added, removed };
}

function wholeRows(runs, why) {
  // Rows are compared as whole lines here, so two identical lines are two
  // things, not one. Everything below counts copies: three of a row yesterday
  // and none today is three rows gone, and it is drawn as three.
  const counts = runs.map((run) => {
    const seen = new Map();
    for (const row of run.rows) {
      const text = rowText(row);
      seen.set(text, (seen.get(text) || 0) + 1);
    }
    return seen;
  });

  const distinct = [];
  const seen = new Set();
  for (const run of runs) {
    for (const row of run.rows) {
      const text = rowText(row);
      if (!seen.has(text)) { seen.add(text); distinct.push({ text, row }); }
    }
  }

  const rows = new Map();
  const names = [];
  let added = 0;
  let removed = 0;

  for (const { text, row } of distinct) {
    const perRun = counts.map((one) => one.get(text) || 0);
    const copies = Math.max(...perRun);

    // One entry per copy. Copy n exists in a run if that run held more than n
    // of it, which is what turns "three became one" into two rows gone rather
    // than one row that is somehow still here.
    for (let n = 0; n < copies; n += 1) {
      const presence = perRun.map((held) => held > n);
      const here = presence[0];
      const everBefore = presence.slice(1).some(Boolean);
      // Moved if this copy was not there in every run being compared, which
      // also catches one that went away and came back inside the window.
      const moved = presence.some((one) => one !== presence[0]);

      if (here && !everBefore) added += 1;
      else if (!here && everBefore) removed += 1;

      rows.set(`${text}#${n}`, {
        overRuns: here ? [row] : [null, row],
        here,
        everBefore,
        moved,
      });
      names.push(`${text}#${n}`);
    }
  }

  return { rows, names, runs, changedCells: 0, added, removed, whole: true, degraded: why };
}

// In the browser these are already global, because this is an ordinary script
// and the page loads it before app.js. Under node the same file is required by
// the tests, and this is the one line that makes that work.
if (typeof module !== "undefined" && module.exports) {
  module.exports = {
    keyIndexIn, missingKeyColumn, cellValue, sameRow, rowText,
    byKey, compareRuns, wholeRows, compactRows, duplicateCount,
  };
}
