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
  keyIndexIn, keyIndexesIn, keyNamesOf, keyTextOf,
  missingKeyColumn, missingKeyColumns, cellValue, sameRow, rowText, rowTextIgnoring,
  ignoredIndexes, compareRuns, compactRows, duplicateCount,
  groupByKey, valuesIn, mergeGroup, linesOf, sameGroup, changedValues, cellLines,
  LINES,
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
  // One entry per run, and each entry is the lines that run printed under the
  // name - one line here, which is the ordinary table.
  assert.deepEqual(entry(diff, "a").overRuns.map((g) => g[0][1]), ["5", "4", "3", "2", "1"]);
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
  assert.match(diff.impossible, /\[table\] key names "repoo"/);
  assert.match(diff.impossible, /repo, ENV1, ENV2/);
});

test("a key of several columns names a row no single column names", () => {
  // environment repeats on every repo, repo repeats in every environment:
  // one column alone cannot line two runs up, and the pair can.
  const columns = ["environment", "repo", "version"];
  const before = [["ENV1", "payments", "1.0.0"], ["ENV1", "orders", "2.0.0"],
                  ["ENV2", "payments", "1.0.0"]];
  const after = [["ENV1", "payments", "1.1.0"], ["ENV1", "orders", "2.0.0"],
                 ["ENV2", "payments", "1.0.0"]];
  const diff = compareRuns([run(columns, after), run(columns, before)],
                           ["environment", "repo"]);
  assert.equal(diff.changedCells, 1);
  assert.equal(diff.added, 0);
  assert.equal(diff.removed, 0);
  assert.equal(diff.rows.size, 3);
  const moved = [...diff.rows.values()].filter((entry) => entry.moved);
  assert.equal(moved.length, 1);
});

test("one of several key columns is enough to tell two rows apart", () => {
  const columns = ["environment", "repo", "version"];
  const rows = [["ENV1", "payments", "1.0.0"], ["ENV2", "payments", "1.0.0"]];
  // On "repo" alone both lines are called the same thing, so they are one
  // row holding two environments. Name the pair and they are two rows.
  const onRepo = compareRuns([run(columns, rows), run(columns, rows)], "repo");
  assert.equal(onRepo.rows.size, 1);
  const onBoth = compareRuns([run(columns, rows), run(columns, rows)],
                             ["environment", "repo"]);
  assert.equal(onBoth.rows.size, 2);
});

test("a value holding the separator does not merge two rows", () => {
  // Any separator can also be a value. "a" + "b,c" and "a,b" + "c" are two
  // different rows, and joining the parts on a comma would make them one.
  const columns = ["left", "right", "version"];
  const rows = [["a", "b,c", "1.0.0"], ["a,b", "c", "2.0.0"]];
  const diff = compareRuns([run(columns, rows), run(columns, rows)],
                           ["left", "right"]);
  assert.equal(diff.rows.size, 2);
});

test("a repeating key is one row holding several values, not a refusal", () => {
  const columns = ["environment", "repo", "version"];
  const rows = [["ENV1", "payments", "1.0.0"], ["ENV1", "orders", "2.0.0"]];
  const diff = compareRuns([run(columns, rows), run(columns, rows)], "environment");
  assert.equal(diff.rows.size, 1, "one environment is one row");
  assert.equal(entry(diff, "ENV1").overRuns[0].length, 2, "holding both lines");
  assert.equal(diff.changedCells, 0, "and nothing changed between the runs");
});

test("a key column is never left out of a comparison by [compare] ignore", () => {
  const columns = ["environment", "repo", "version"];
  const kept = ignoredIndexes(columns, ["environment", "repo", "version"],
                              ["environment", "repo"]);
  assert.deepEqual([...kept], [2]);
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

/* ----------------------------------------- several lines under one name ----
 *
 * A plugin printing two lines with the same name has printed one row holding
 * two values - blue and green of one service, two pods of one deployment. The
 * lines are merged into one row, and a value that arrived or went is marked
 * in the cell it is in. Before this the whole table fell back to comparing
 * rows as whole lines, where a changed version read as one row leaving and
 * another arriving, and nothing could be seen inside a cell.
 */

test("lines sharing a name are one row, not a row each", () => {
  const diff = compareRuns([
    run(VERSIONS, [["a", "1", "9"], ["a", "2", "9"]]),
    run(VERSIONS, [["a", "1", "9"]]),
  ], "repo");
  assert.equal(diff.rows.size, 1);
  assert.equal(diff.added, 0, "the row was there before; one of its values is new");
  assert.equal(diff.removed, 0);
  assert.equal(diff.changedCells, 1, "one version arrived in the version column");
  assert.equal(entry(diff, "a").moved, true);
});

test("one value replacing another counts once, not twice", () => {
  const diff = compareRuns([
    run(VERSIONS, [["a", "1", "9"], ["a", "3", "9"]]),
    run(VERSIONS, [["a", "1", "9"], ["a", "2", "9"]]),
  ], "repo");
  assert.equal(diff.changedCells, 1, "2 became 3; 1 stayed");
});

test("the order the lines arrive in is not a change", () => {
  const diff = compareRuns([
    run(VERSIONS, [["a", "2", "9"], ["a", "1", "9"]]),
    run(VERSIONS, [["a", "1", "9"], ["a", "2", "9"]]),
  ], "repo");
  assert.equal(diff.changedCells, 0);
  assert.equal(entry(diff, "a").moved, false);
});

test("a line that goes is a changed value, not a row that left", () => {
  const diff = compareRuns([
    run(VERSIONS, [["a", "1", "9"]]),
    run(VERSIONS, [["a", "1", "9"], ["a", "2", "9"]]),
  ], "repo");
  assert.equal(diff.removed, 0, "the row is still here");
  assert.equal(diff.changedCells, 1);
});

test("a name that goes entirely is still a row that left", () => {
  const diff = compareRuns([
    run(VERSIONS, [["a", "1", "9"]]),
    run(VERSIONS, [["a", "1", "9"], ["b", "2", "9"], ["b", "3", "9"]]),
  ], "repo");
  assert.equal(diff.removed, 1, "both of b's lines went, which is one row gone");
  assert.equal(entry(diff, "b").here, false);
});

test("identical lines under one name are one value, written once", () => {
  const group = [["a", "1", "9"], ["a", "1", "9"], ["a", "1", "9"]];
  assert.deepEqual(valuesIn(group, 1), ["1"]);
  assert.deepEqual(mergeGroup(VERSIONS, group), ["a", "1", "9"]);
});

test("a line that knows nothing does not put an empty line in the cell", () => {
  // One pod knows its branch and the other does not. Written out, the one
  // that does not is an empty line in the middle of the table, which reads as
  // a fault in the table rather than as a fact about that pod.
  const group = [["a", "release/sprint11", ""], ["a", "", ""]];
  assert.deepEqual(valuesIn(group, 1), ["release/sprint11"]);
  assert.deepEqual(mergeGroup(VERSIONS, group)[1], "release/sprint11");
});

test("a cell where nothing is known is still one empty cell", () => {
  const group = [["a", "", ""], ["a", "", ""]];
  assert.deepEqual(valuesIn(group, 1), [""]);
});

test("a merged cell holds its values as lines, in the order they were printed", () => {
  const group = [["a", "2", "9"], ["a", "1", "8"]];
  const merged = mergeGroup(VERSIONS, group);
  assert.deepEqual(linesOf(merged[1]), ["2", "1"]);
  assert.deepEqual(linesOf(merged[2]), ["9", "8"]);
  assert.equal(merged[0], "a", "the name itself is written once");
});

test("a value holding a newline is one value, not two lines", () => {
  // The separator is a zero byte for exactly this reason: a plugin can print
  // a value with a line break in it, and splitting on that would say a value
  // changed when the table is the same.
  const merged = mergeGroup(VERSIONS, [["a", "one\ntwo", "9"]]);
  assert.deepEqual(linesOf(merged[1]), ["one\ntwo"]);
  assert.equal(LINES, "\u0000");
});

test("groupByKey keeps every line, in the order it came", () => {
  const groups = groupByKey(VERSIONS, [["a", "1", ""], ["b", "9", ""], ["a", "2", ""]],
                            "repo");
  assert.equal(groups.size, 2);
  assert.deepEqual(groups.get("a").map((row) => row[1]), ["1", "2"]);
});

/* --- what one cell says ------------------------------------------------- */

test("a value that arrived is marked, and one that went is kept", () => {
  const now = [["a", "1", ""], ["a", "3", ""]];
  const before = [["a", "1", ""], ["a", "2", ""]];
  assert.deepEqual(cellLines([now, before], 1, now[0], new Set()), [
    { value: "1", mark: "" },
    { value: "3", mark: "fresh" },
    { value: "2", mark: "went" },
  ]);
});

test("nothing is marked where nothing moved", () => {
  const group = [["a", "1", ""], ["a", "2", ""]];
  assert.deepEqual(cellLines([group, group], 1, group[0], new Set()),
                   [{ value: "1", mark: "" }, { value: "2", mark: "" }]);
});

test("a column that is not compared is never marked", () => {
  const now = [["a", "9h", ""]];
  const before = [["a", "8h", ""]];
  assert.deepEqual(cellLines([now, before], 1, now[0], new Set([1])),
                   [{ value: "9h", mark: "" }]);
});

test("a row only this run has is not marked as new in every cell", () => {
  // The arrival is a fact about the row, said once by the chip on its name.
  const now = [["a", "1", ""]];
  assert.deepEqual(cellLines([now, null], 1, now[0], new Set()),
                   [{ value: "1", mark: "" }]);
});

test("a cell holding several values looks one run back, however deep the stack", () => {
  // Five runs of a service whose pod is replaced every time: taking all of
  // them into the cell put eight pod names in it. The lines of this cell are
  // its values, not the runs, so there is no line to spare for a fifth run.
  const runs = ["e", "d", "c", "b", "a"].map((name) => [["svc", `pod-${name}`, ""]]);
  const lines = cellLines(runs, 1, runs[0][0], new Set());
  assert.deepEqual(lines, [{ value: "pod-e", mark: "fresh" },
                           { value: "pod-d", mark: "went" }]);
});

test("a row missing from the run before is compared with the one before that", () => {
  const now = [["svc", "2", ""]];
  const earlier = [["svc", "1", ""]];
  assert.deepEqual(cellLines([now, null, earlier], 1, now[0], new Set()),
                   [{ value: "2", mark: "fresh" }, { value: "1", mark: "went" }]);
});

test("a row that has gone is drawn from the run that last had it", () => {
  // The bug this replaced: with no run to read "now" from, a column that is
  // not compared had nothing to fall back on, and the cell was drawn as one
  // empty line - an empty line in the middle of a table, saying nothing.
  const before = [["a", "9h", ""], ["a", "8h", ""]];
  const lastSeen = ["a", "9h\u00008h", ""];
  assert.deepEqual(cellLines([null, before], 1, lastSeen, new Set([1])),
                   [{ value: "9h", mark: "" }, { value: "8h", mark: "" }]);
  const compared = cellLines([null, before], 1, lastSeen, new Set());
  assert.ok(compared.every((line) => line.value), "no line is empty");
});

test("changedValues counts what arrived and what went, whichever is larger", () => {
  const was = [["a", "1", ""], ["a", "2", ""]];
  assert.equal(changedValues(was, [["a", "1", ""], ["a", "2", ""]], 1), 0);
  assert.equal(changedValues(was, [["a", "1", ""], ["a", "3", ""]], 1), 1);
  assert.equal(changedValues(was, [["a", "1", ""]], 1), 1);
  assert.equal(changedValues(was, [["a", "3", ""], ["a", "4", ""]], 1), 2);
});

/* ------------------------------------------- columns left out of it ----
 *
 * [compare] ignore in plugin.toml, and the columns hidden on screen. The
 * reason for both is the same: a column holding the time of the run moves
 * every time the plugin runs, so without this every run differs from the one
 * before and the answer to "what changed" is the clock.
 */

const WITH_TIME = ["repo", "version", "checked_at"];

test("a column that is not compared does not count as a change", () => {
  const diff = compareRuns([
    run(WITH_TIME, [["a", "1", "10:05"]]),
    run(WITH_TIME, [["a", "1", "10:00"]]),
  ], "repo", ["checked_at"]);
  assert.equal(diff.changedCells, 0);
  assert.equal(entry(diff, "a").moved, false,
               "a row whose only difference is not compared did not move");
});

test("a real change beside an ignored one is still a change", () => {
  const diff = compareRuns([
    run(WITH_TIME, [["a", "2", "10:05"]]),
    run(WITH_TIME, [["a", "1", "10:00"]]),
  ], "repo", ["checked_at"]);
  assert.equal(diff.changedCells, 1, "the version, and not the clock beside it");
  assert.equal(entry(diff, "a").moved, true);
});

test("ignoring nothing is the same as not asking", () => {
  const runs = [run(WITH_TIME, [["a", "1", "10:05"]]),
                run(WITH_TIME, [["a", "1", "10:00"]])];
  assert.equal(compareRuns(runs, "repo", []).changedCells, 1);
  assert.equal(compareRuns(runs, "repo").changedCells, 1);
  assert.equal(compareRuns(runs, "repo", null).changedCells, 1);
});

test("a row that arrives is a row that arrived, whatever is ignored", () => {
  const diff = compareRuns([
    run(WITH_TIME, [["a", "1", "10:05"], ["b", "1", "10:05"]]),
    run(WITH_TIME, [["a", "1", "10:00"]]),
  ], "repo", ["checked_at", "version"]);
  assert.equal(diff.added, 1);
  assert.equal(diff.changedCells, 0);
});

test("the column that names a row is never taken out of the comparison", () => {
  // It is identity, not a value. Taken out of the row text in whole row mode,
  // two different things would read as the same thing - so compareRuns drops
  // it from the list rather than trusting what it was given. The manifest
  // refuses it too; this is the second line of defence.
  const ignored = ignoredIndexes(WITH_TIME, ["repo", "checked_at"], "repo");
  assert.deepEqual([...ignored], [2]);
  const first = ignoredIndexes(WITH_TIME, ["repo"], "");
  assert.equal(first.size, 0, "with no [table] key the first column is the name");
});

test("a column that is not in the table is ignored harmlessly", () => {
  // [compare] ignore can only be checked against [table] columns, which most
  // plugins do not declare. A name that matches nothing matches nothing.
  const diff = compareRuns([
    run(WITH_TIME, [["a", "2", "10:05"]]),
    run(WITH_TIME, [["a", "1", "10:00"]]),
  ], "repo", ["nothing_called_this"]);
  assert.equal(diff.changedCells, 2);
});

test("sameGroup leaves the ignored columns out of the lines it compares", () => {
  // Two lines under one name, and the clock is the only thing that moved.
  // With the clock in the line, that reads as both lines leaving and two
  // others arriving.
  const ignored = ignoredIndexes(WITH_TIME, ["checked_at"], "repo");
  const now = [["a", "1", "10:05"], ["a", "2", "10:05"]];
  const before = [["a", "1", "10:00"], ["a", "2", "10:00"]];
  assert.equal(sameGroup(now, before, WITH_TIME, ignored), true);
  assert.equal(sameGroup(now, before, WITH_TIME, new Set()), false);
  assert.equal(sameGroup(now, null, WITH_TIME, ignored), false);
  assert.equal(sameGroup(null, null, WITH_TIME, ignored), true);
});

test("several lines and an ignored clock still report what went", () => {
  const diff = compareRuns([
    run(WITH_TIME, [["a", "1", "10:05"], ["a", "2", "10:05"]]),
    run(WITH_TIME, [["a", "1", "10:00"], ["a", "2", "10:00"], ["a", "3", "10:00"]]),
  ], "repo", ["checked_at"]);
  assert.equal(diff.rows.size, 1);
  assert.equal(diff.removed, 0, "the row is still here with two of its three values");
  assert.equal(diff.changedCells, 1, "the third version went; the clock did not count");
  assert.equal(entry(diff, "a").moved, true);
});

test("rowTextIgnoring reads a short row the same as a blank one", () => {
  const ignored = ignoredIndexes(WITH_TIME, ["checked_at"], "repo");
  assert.equal(rowTextIgnoring(["a", "1"], WITH_TIME, ignored),
               rowTextIgnoring(["a", "1", ""], WITH_TIME, ignored));
  assert.equal(rowTextIgnoring(["a", "1"], WITH_TIME, new Set()),
               rowText(["a", "1"]), "nothing ignored is the plain row text");
});

test("sameRow skips the columns it is told to skip", () => {
  assert.equal(sameRow(["a", "1", "x"], ["a", "1", "y"], WITH_TIME), false);
  assert.equal(sameRow(["a", "1", "x"], ["a", "1", "y"], WITH_TIME, new Set([2])), true);
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
