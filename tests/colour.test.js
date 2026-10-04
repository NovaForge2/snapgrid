// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 NovaForge2
//
// Which cell gets which colour.
//
//     node --test tests/
//
// This decides what a person is told about their numbers - a disk at 91% in
// red, a certificate with four days left in red - so the tests below are
// mostly about the ways it could say something untrue: a blank cell reading
// as zero, a word reading as a number, the wrong rule winning.
//
// snapgrid/manifest.py shade_for runs the identical test for the spreadsheet,
// and tests/test_manifest.py checks the two agree on the same cases.

"use strict";

const test = require("node:test");
const assert = require("node:assert");
const path = require("node:path");

const { shadeFor } = require(path.join(__dirname, "..", "web", "colour.js"));

const DISK = [
  { op: ">", n: 90, colour: "red" },
  { op: ">", n: 80, colour: "amber" },
];

test("nothing to go on means no colour", () => {
  assert.equal(shadeFor(null, "95"), "");
  assert.equal(shadeFor([], "95"), "");
});

test("the first rule that matches wins", () => {
  assert.equal(shadeFor(DISK, "95"), "red");
  assert.equal(shadeFor(DISK, "85"), "amber");
});

test("a value no rule matches is left plain", () => {
  assert.equal(shadeFor(DISK, "70"), "");
});

test("the boundary belongs to neither side of a strict comparison", () => {
  assert.equal(shadeFor(DISK, "90"), "amber", "90 is not > 90");
  assert.equal(shadeFor(DISK, "80"), "", "80 is not > 80");
});

test("a blank cell is not zero", () => {
  // Number("") is 0, so "< 10" would paint every empty cell in the column.
  const rules = [{ op: "<", n: 10, colour: "red" }];
  assert.equal(shadeFor(rules, ""), "");
  assert.equal(shadeFor(rules, "   "), "");
  assert.equal(shadeFor(rules, undefined), "");
  assert.equal(shadeFor(rules, null), "");
});

test("a word is not a number", () => {
  assert.equal(shadeFor(DISK, "n/a"), "");
  assert.equal(shadeFor(DISK, "unknown"), "");
});

test("decimals and negatives compare as numbers, not as text", () => {
  assert.equal(shadeFor(DISK, "90.5"), "red");
  assert.equal(shadeFor([{ op: "<", n: 0, colour: "red" }], "-3"), "red");
  // As text "9" sorts after "10"; as a number it does not.
  assert.equal(shadeFor([{ op: ">", n: 10, colour: "red" }], "9"), "");
});

test("every operator", () => {
  const at = (op, n, value) => shadeFor([{ op, n, colour: "red" }], value);
  assert.equal(at(">", 5, "6"), "red");
  assert.equal(at(">=", 5, "5"), "red");
  assert.equal(at("<", 5, "4"), "red");
  assert.equal(at("<=", 5, "5"), "red");
  assert.equal(at("=", 5, "5"), "red");
  assert.equal(at("!=", 5, "6"), "red");
  assert.equal(at("!=", 5, "5"), "");
});

test("a value matched whole ignores case and surrounding space", () => {
  const rules = [{ is: "expired", colour: "red" }];
  assert.equal(shadeFor(rules, "EXPIRED"), "red");
  assert.equal(shadeFor(rules, " expired "), "red");
  assert.equal(shadeFor(rules, "expired soon"), "", "whole value, not part of it");
});

test("words and numbers live in the same column", () => {
  // A column that is mostly numbers but says "unknown" when it cannot tell.
  const rules = [
    { is: "unknown", colour: "grey" },
    { op: ">", n: 90, colour: "red" },
  ];
  assert.equal(shadeFor(rules, "unknown"), "grey");
  assert.equal(shadeFor(rules, "95"), "red");
  assert.equal(shadeFor(rules, "20"), "");
});

test("a number written as a value is matched as text, not as a number", () => {
  // "0" = "green" is a value, and 0.0 printed as "0.0" is not that value.
  const rules = [{ is: "0", colour: "green" }];
  assert.equal(shadeFor(rules, "0"), "green");
  assert.equal(shadeFor(rules, "0.0"), "");
});

test("a value that is not a real number is not compared", () => {
  // float("NaN") succeeds in Python, Number("NaN") is NaN here. Left alone,
  // a cell saying NaN came out red in the spreadsheet and plain on the page.
  // snapgrid/colour.py has the same cases.
  const rules = [{ op: "!=", n: 200, colour: "red" }];
  for (const odd of ["NaN", "nan", "inf", "-inf", "Infinity"]) {
    assert.equal(shadeFor(rules, odd), "", odd);
  }
  assert.equal(shadeFor(rules, "503"), "red", "a real number still counts");
});
