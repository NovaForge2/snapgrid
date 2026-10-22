// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 NovaForge2
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const context = {};
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(__dirname, '../web/export.js'), 'utf8'), context);
function table(headers, rows, empty = false) {
  return {querySelectorAll: selector => selector === 'thead .th-label'
    ? headers.map(textContent => ({textContent}))
    : rows.map(values => ({querySelector: () => empty ? {} : null,
        querySelectorAll: () => values.map(value => ({innerText:value,
          querySelectorAll: () => Array.isArray(value) ? value.map(innerText => ({innerText})) : []}))}))};
}
const capture = value => JSON.parse(JSON.stringify(context.tableForExport(value)));
test('exports only displayed columns and rows, preserving sorted order', () => {
  assert.deepEqual(capture(table(['service','version'], [['z','2.0'],['a','1.10']])),
    {columns:['service','version'],rows:[['z','2.0'],['a','1.10']]});
});
test('empty filter result exports headers without the placeholder message', () => {
  assert.deepEqual(capture(table(['service'], [['No rows match']], true)), {columns:['service'],rows:[]});
});
test('compacted counts and comparison lines stay as displayed', () => {
  assert.deepEqual(capture(table(['service','version'], [['a ×2',['2.0','·','1.10']],['b gone',['gone','1.0']]])),
    {columns:['service','version'],rows:[['a ×2','2.0\n·\n1.10'],['b gone','gone\n1.0']]});
});
test('missing table and all hidden columns cannot silently export full data', () => {
  assert.throws(() => capture(null), /no table/);
  assert.throws(() => capture(table([], [])), /at least one column/);
});

// A chip is held off its value by a margin, and a margin is not text: without
// a space put back, a compacted row exports as `nginx×4`, which reads as a
// program with that name. The fake cells above have no children at all, which
// is why this builds one that has.
const cellWith = children => ({childNodes: children, innerText: ""});
const chip = textContent => ({nodeType: 1, textContent,
  classList: {contains: name => name === "chip"}});
const words = textContent => ({nodeType: 3, textContent});

test('a count chip keeps a space between it and the value', () => {
  assert.equal(context.cellText(cellWith([words('nginx'), chip('\u00d74')])), 'nginx \u00d74');
  assert.equal(context.cellText(cellWith([words('payments-api'), chip('NEW')])),
               'payments-api NEW');
});

test('a cell the renderer built by hand still reads', () => {
  // No childNodes at all, which is every cell in the fakes above.
  assert.equal(context.cellText({innerText: 'plain'}), 'plain');
  assert.equal(context.cellText({childNodes: [], innerText: 'empty children'}),
               'empty children');
});
