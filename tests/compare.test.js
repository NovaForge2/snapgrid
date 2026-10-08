// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 NovaForge2
//
// What changed between runs, tested directly.
//
// Run by node's own test runner, which is part of node and needs nothing
// installed:
//
//     node --test tests/
//
// ./run-tests.py runs this too, and says so when node is not there rather than
// pretending the suite passed.
//
// Everything in here is about one question: does the comparison ever say
// something that is not true? "Nothing changed" is an answer, and a wrong one
// is worse than an error message.

"use strict";

const test = require("node:test");
const assert = require("node:assert");
const path = require("node:path");

const {
  keyIndexIn, missingKeyColumn, cellValue, sameRow, rowText, byKey,
  compareRuns, wholeRows, compactRows, duplicateCount,
} = require(path.join(__dirname, "..", "web", "compare.js"));

// A run, newest first when passed to compareRuns.
const run = (columns, rows) => ({ columns, rows, last_seen: 0 });
const VERSIONS = ["repo", "ENV1", "ENV2"];

function entry(diff, name) {
  return diff.rows.get(name);
}

/* ---------------------------------------------------------- the basics */

test("nothing to compare against gives nothing", () => {
  assert.equal(compareRuns([run(VERSIONS, [])], "repo"), null);
  assert.equal(compareRuns([], "repo"), null);
  assert.equal(compareRuns(null, "repo"), null);
});

test("a value that changed is counted once per change", () => {
  const diff = compareRuns([
    run(VERSIONS, [["a", "1", "9"]]),
    run(VERSIONS, [["a", "2", "9"]]),
  ], "repo");
  assert.equal(diff.changedCells, 1);
  assert.equal(diff.added, 0);
  assert.equal(diff.removed, 0);
  assert.equal(entry(diff, "a").moved, true);
});

test("a row that did not move is not marked as moved", () => {
  const diff = compareRuns([
    run(VERSIONS, [["a", "1", "9"]]),
    run(VERSIONS, [["a", "1", "9"]]),
  ], "repo");
  assert.equal(diff.changedCells, 0);
  assert.equal(entry(diff, "a").moved, false);
});

test("the key column is never compared", () => {
  // Two runs identical apart from the name: that is a different row, not a
  // changed one, so nothing is "changed" and both sides are added/removed.
  const diff = compareRuns([
    run(VERSIONS, [["a", "1", "9"]]),
    run(VERSIONS, [["b", "1", "9"]]),
  ], "repo");
  assert.equal(diff.changedCells, 0);
  assert.equal(diff.added, 1);
  assert.equal(diff.removed, 1);
});

/* -------------------------------------------------- appearing and going */

test("a row only in the newest run has appeared", () => {
  const diff = compareRuns([
    run(VERSIONS, [["a", "1", "9"], ["b", "1", "9"]]),
    run(VERSIONS, [["a", "1", "9"]]),
  ], "repo");
  assert.equal(diff.added, 1);
  assert.equal(entry(diff, "b").here, true);
  assert.equal(entry(diff, "b").everBefore, false);
});

test("a row missing from the newest run has gone, and is still listed", () => {
  const diff = compareRuns([
    run(VERSIONS, [["a", "1", "9"]]),
    run(VERSIONS, [["a", "1", "9"], ["gone", "1", "9"]]),
  ], "repo");
  assert.equal(diff.removed, 1);
  assert.equal(entry(diff, "gone").here, false);
  assert.ok(diff.names.includes("gone"), "it has to stay visible to be noticed");
});

test("an empty newest run means everything went", () => {
  const diff = compareRuns([
    run(VERSIONS, []),
    run(VERSIONS, [["a", "1", "9"], ["b", "1", "9"]]),
  ], "repo");
  assert.equal(diff.removed, 2);
  assert.equal(diff.added, 0);
  assert.equal(diff.names.length, 2);
});

test("an empty earlier run means everything is new", () => {
  const diff = compareRuns([
    run(VERSIONS, [["a", "1", "9"]]),
    run(VERSIONS, []),
  ], "repo");
  assert.equal(diff.added, 1);
  assert.equal(diff.removed, 0);
});

/* ------------------------------------------------------- two to five runs */

test("up to five runs line up, newest first", () => {
  const runs = ["5", "4", "3", "2", "1"].map((v) => run(VERSIONS, [["a", v, "9"]]));
  const diff = compareRuns(runs, "repo");
  assert.equal(diff.runs.length, 5);
  assert.deepEqual(entry(diff, "a").overRuns.map((r) => r[1]), ["5", "4", "3", "2", "1"]);
  assert.equal(diff.changedCells, 4, "four steps between five values");
});

test("a row that comes and goes across five runs is marked moved", () => {
  const runs = [
    run(VERSIONS, [["a", "1", "9"]]),
    run(VERSIONS, []),
    run(VERSIONS, [["a", "1", "9"]]),
  ];
  const diff = compareRuns(runs, "repo");
  assert.equal(entry(diff, "a").moved, true,
    "it disappeared and came back inside the window");
});

test("a row present and unchanged in every run is not moved", () => {
  const runs = [1, 2, 3, 4].map(() => run(VERSIONS, [["a", "1", "9"]]));
  assert.equal(entry(compareRuns(runs, "repo"), "a").moved, false);
});

/* ------------------------------------------------- refusing to guess */

test("columns that differ between runs are refused, with a reason", () => {
  const diff = compareRuns([
    run(["repo", "ENV1"], [["a", "1"]]),
    run(["repo", "ENV1", "ENV2"], [["a", "1", "9"]]),
  ], "repo");
  assert.match(diff.impossible, /columns are not the same/);
  assert.equal(diff.rows, undefined, "nothing is shown when it cannot be worked out");
});

test("a key column the result does not have is refused, and the message says what it has", () => {
  const diff = compareRuns([
    run(VERSIONS, [["a", "1", "9"]]),
    run(VERSIONS, [["a", "2", "9"]]),
  ], "repoo");
  assert.match(diff.impossible, /\[table\] key is "repoo"/);
  assert.match(diff.impossible, /repo, ENV1, ENV2/);
});

test("the column order does not have to match the key's position", () => {
  const columns = ["environment", "repo", "version"];
  const diff = compareRuns([
    run(columns, [["ENV1", "a", "2"]]),
    run(columns, [["ENV1", "a", "1"]]),
  ], "repo");
  assert.equal(diff.changedCells, 1);
  assert.equal(entry(diff, "a").moved, true);
});

test("no key named means the first column", () => {
  const diff = compareRuns([
    run(VERSIONS, [["a", "2", "9"]]),
    run(VERSIONS, [["a", "1", "9"]]),
  ], "");
  assert.equal(diff.changedCells, 1);
  assert.ok(diff.rows.has("a"));
});

/* ------------------------------------------- rows that cannot be told apart */

test("duplicate names fall back to whole rows, and say why", () => {
  const diff = compareRuns([
    run(VERSIONS, [["a", "1", "9"], ["a", "2", "9"]]),
    run(VERSIONS, [["a", "1", "9"]]),
  ], "repo");
  assert.equal(diff.whole, true);
  assert.match(diff.degraded, /more than one row is called the same thing in "repo"/);
  assert.equal(diff.added, 1, 'the second "a" is a row that was not there before');
});

test("identical rows are counted, not collapsed", () => {
  // Three yesterday, none today, is three rows gone.
  const diff = wholeRows([
    run(VERSIONS, []),
    run(VERSIONS, [["a", "1", "9"], ["a", "1", "9"], ["a", "1", "9"]]),
  ], "test");
  assert.equal(diff.removed, 3);
  assert.equal(diff.names.length, 3);
});

test("one copy becoming two is an addition", () => {
  const diff = wholeRows([
    run(VERSIONS, [["a", "1", "9"], ["a", "1", "9"]]),
    run(VERSIONS, [["a", "1", "9"]]),
  ], "test");
  assert.equal(diff.added, 1);
  assert.equal(diff.removed, 0);
});

test("a copy that disappears and returns counts as moved", () => {
  const diff = wholeRows([
    run(VERSIONS, [["a", "1", "9"]]),
    run(VERSIONS, []),
    run(VERSIONS, [["a", "1", "9"]]),
  ], "test");
  assert.equal([...diff.rows.values()][0].moved, true);
});

/* -------------------------------------------------------------- values */

test("unicode, commas, quotes and newlines are compared exactly", () => {
  const odd = ["é中 ✓", 'x,y "q"', "a\nb\tc"];
  const same = compareRuns([
    run(VERSIONS, [[odd[0], odd[1], odd[2]]]),
    run(VERSIONS, [[odd[0], odd[1], odd[2]]]),
  ], "repo");
  assert.equal(same.changedCells, 0, "identical odd values must not read as changed");

  const changed = compareRuns([
    run(VERSIONS, [[odd[0], odd[1], "a\nb\tc"]]),
    run(VERSIONS, [[odd[0], odd[1], "a\nb\tX"]]),
  ], "repo");
  assert.equal(changed.changedCells, 1);
});

test("a short row is compared as blanks rather than as undefined", () => {
  const diff = compareRuns([
    run(VERSIONS, [["a", "1"]]),
    run(VERSIONS, [["a", "1", ""]]),
  ], "repo");
  assert.equal(diff.changedCells, 0, "a missing cell and an empty cell are the same thing");
});

test("an empty key value is a row like any other", () => {
  const diff = compareRuns([
    run(VERSIONS, [["", "2", "9"]]),
    run(VERSIONS, [["", "1", "9"]]),
  ], "repo");
  assert.equal(diff.changedCells, 1);
});

/* ------------------------------------------------------- the small parts */

test("cellValue turns a missing cell into an empty string", () => {
  assert.equal(cellValue(["a"], 5), "");
  assert.equal(cellValue(["a"], 0), "a");
});

test("sameRow handles a row that was not there", () => {
  assert.equal(sameRow(null, null, VERSIONS), true);
  assert.equal(sameRow(["a"], null, VERSIONS), false);
});

test("rowText distinguishes rows that differ only in where a comma is", () => {
  assert.notEqual(rowText(["a,b", "c"]), rowText(["a", "b,c"]));
});

test("keyIndexIn falls back to the first column when the name is unknown", () => {
  // The fallback still exists for the drawing code; refusing is compareRuns's
  // job, and missingKeyColumn is what it asks.
  assert.equal(keyIndexIn(VERSIONS, "nope"), 0);
  assert.equal(keyIndexIn(VERSIONS, "ENV2"), 2);
  assert.equal(missingKeyColumn(VERSIONS, "nope"), "nope");
  assert.equal(missingKeyColumn(VERSIONS, "ENV2"), "");
});

test("byKey reports duplicates without throwing any row away", () => {
  const { map, duplicates } = byKey(VERSIONS, [["a", "1", ""], ["a", "2", ""]], "repo");
  assert.equal(duplicates, true);
  assert.equal(map.size, 1, "the first one wins, and the caller is told why that is wrong");
});

// ---- compacting ------------------------------------------------------
//
// Hiding a column can leave two rows that are identical on screen. They are
// one fact written twice, and folding them together is a view decision - but
// a table claiming one of something when there are two is wrong in the
// direction that matters, so what is folded is always counted.

test("rows that differ only in a hidden column fold together", () => {
  //  A B C          hide B      A C
  //  1 2 3                      1 3
  //  1 2 4                      1 4   <- these two
  //  1 5 4                      1 4   <- are now the same
  const rows = [["1", "2", "3"], ["1", "2", "4"], ["1", "5", "4"]];
  const { rows: kept, counts } = compactRows(rows, [0, 2]);
  assert.deepEqual(kept, [["1", "2", "3"], ["1", "2", "4"]]);
  assert.equal(counts.get(kept[0]), 1);
  assert.equal(counts.get(kept[1]), 2, "the third row folded into the second");
});

test("nothing folds while every column is on screen", () => {
  const rows = [["1", "2", "3"], ["1", "2", "4"], ["1", "5", "4"]];
  const { rows: kept } = compactRows(rows, [0, 1, 2]);
  assert.equal(kept.length, 3);
  assert.equal(duplicateCount(rows, [0, 1, 2]), 0);
});

test("the first of a group is the one that stays, in the order it arrived", () => {
  const rows = [["b", "x"], ["a", "y"], ["b", "z"], ["a", "w"]];
  const { rows: kept } = compactRows(rows, [0]);
  assert.deepEqual(kept.map((row) => row[0]), ["b", "a"]);
});

test("a separator inside a value does not fold two different rows into one", () => {
  // Joined on a comma, ["a,b", "c"] and ["a", "b,c"] are the same string.
  const rows = [["a,b", "c"], ["a", "b,c"]];
  assert.equal(compactRows(rows, [0, 1]).rows.length, 2);
  // And the same again for the one used to join: a null byte.
  const nulls = [["a\u0000b", "c"], ["a", "b\u0000c"]];
  assert.equal(compactRows(nulls, [0, 1]).rows.length, 2);
});

test("a short row and a blank cell are the same thing", () => {
  // cellValue() reads a missing cell as empty, so a row that stops early
  // must fold into one that spells the blank out.
  const rows = [["a", ""], ["a"]];
  assert.equal(compactRows(rows, [0, 1]).rows.length, 1);
});

test("duplicateCount says how many rows would go", () => {
  const rows = [["1", "2", "3"], ["1", "2", "4"], ["1", "5", "4"], ["1", "9", "4"]];
  assert.equal(duplicateCount(rows, [0, 2]), 2);
});

test("an empty table compacts to an empty table", () => {
  assert.deepEqual(compactRows([], [0]).rows, []);
  assert.equal(duplicateCount([], [0]), 0);
});
