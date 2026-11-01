// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 NovaForge2
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function setup() {
  const pending = [], errors = [], renders = [];
  const state = {selected: 'a', snapshotId: null, depth: 1, detail: {id:'a', live:null}};
  const context = {
    state, AbortController, setTimeout, clearTimeout, encodeURIComponent,
    fetch: (url) => new Promise((resolve, reject) => pending.push({url, reject,
      resolve: (data) => resolve({ok:true,json:async()=>data})})),
    renderDetail: () => renders.push(state.detail.id),
    showMessage: (message) => errors.push(message),
    renderSidebar(){}, renderServerInfo(){}, renderEmptyState(){}, renderPauseAll(){},
    el: () => ({}),
  };
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../web/data.js'),'utf8'), context);
  return {context, state, pending, errors, renders};
}
const flush = () => new Promise(resolve => setImmediate(resolve));

test('an idle selected table refreshes after a scheduled run', async () => {
  const x = setup(); const done = x.context.loadPlugins();
  x.pending.shift().resolve({plugins:[{id:'a',last_finished:123}],server:{}});
  await flush();
  assert.equal(x.pending[0].url, '/api/plugins/a');
  x.pending.shift().resolve({id:'a',snapshot:{id:2}}); await done;
  assert.equal(x.state.detail.snapshot.id,2);
});

test('switching plugins discards an older response', async () => {
  const x=setup(); const a=x.context.loadDetail();
  x.state.selected='b'; const b=x.context.loadDetail();
  x.pending[1].resolve({id:'b'}); await b;
  x.pending[0].resolve({id:'a'}); await a;
  assert.equal(x.state.detail.id,'b'); assert.deepEqual(x.renders,['b']);
});

test('switching snapshots discards an older response', async () => {
  const x=setup(); const a=x.context.loadDetail();
  x.state.snapshotId=7; const b=x.context.loadDetail();
  x.pending[1].resolve({id:'a',snapshot:{id:7}}); await b;
  x.pending[0].resolve({id:'a',snapshot:{id:8}}); await a;
  assert.equal(x.state.detail.snapshot.id,7);
});

test('overlapping polls share the request and historical selection is preserved', async () => {
  const x=setup(); x.state.snapshotId=7;
  const a=x.context.loadDetail(), b=x.context.loadDetail();
  assert.equal(x.pending.length,1); assert.match(x.pending[0].url,/snapshot=7/);
  x.pending[0].resolve({id:'a'}); await Promise.all([a,b]);
});

test('a failed request can be retried and stale errors are ignored', async () => {
  const x=setup(); const a=x.context.loadDetail();
  x.state.selected='b'; const b=x.context.loadDetail();
  x.pending[0].reject(new Error('old failure')); await a;
  assert.deepEqual(x.errors,[]);
  x.pending[1].reject(new Error('offline')); await b;
  assert.deepEqual(x.errors,['offline']);
  const retry=x.context.loadDetail(); x.pending[2].resolve({id:'b'}); await retry;
  assert.equal(x.state.detail.id,'b');
});

test('unchanged snapshots update status without rebuilding the table', async () => {
  const x = setup(); const redraws = [];
  x.context.renderDetail = (redraw) => redraws.push(redraw);
  x.state.detail = {id:'a',snapshot:{id:1},key:'name',colours:{}};
  const first = x.context.loadDetail();
  x.pending[0].resolve({id:'a',snapshot:{id:1},key:'name',colours:{},live:null});
  await first;
  const second = x.context.loadDetail();
  x.pending[1].resolve({id:'a',snapshot:{id:2},key:'name',colours:{}});
  await second;
  assert.deepEqual(redraws,[false,true]);
});

/* ------------------------------------------------------------------------
   Reading the ticked runs.

   Changing a tick starts a fetch and the fetches overlap, so the answer to
   an older set of ticks can arrive after a newer set is on screen. It must
   not land: the strip would name one run over another run's values, which
   is a wrong answer told confidently.
   ------------------------------------------------------------------------ */

function comparing(chosen, snapshots) {
  const x = setup();
  x.state.chosen = chosen.slice();
  x.state.depth = chosen.length;
  x.state.past = [];
  x.state.snapshotId = null;
  x.state.detail = { id: 'a', snapshots: snapshots.map((id) => ({ id })) };
  // The signature is app.js's; here it only has to move when the ticks do.
  x.context.comparisonSignature = () =>
    `${x.state.selected}|${x.state.chosen[0]}|${x.state.chosen.join(',')}`;
  return x;
}

test('the runs that are ticked are the runs that are read', async () => {
  const x = comparing([3, 1], [3, 2, 1]);
  const done = x.context.loadComparison();
  assert.equal(x.pending[0].url, '/api/snapshots/1');
  x.pending.shift().resolve({ snapshot: { id: 1 } });
  await done;
  assert.equal(x.state.past.map((one) => one.id).join(','), '1');
});

test('an answer for ticks that have since changed does not land', async () => {
  const x = comparing([3, 1], [3, 2, 1]);
  const done = x.context.loadComparison();
  // The tick moved from run 1 to run 2 while run 1 was being read.
  x.state.chosen = [3, 2];
  x.pending.shift().resolve({ snapshot: { id: 1 } });
  await done;
  assert.equal(x.state.past.length, 0);
});

test('a slow answer cannot overwrite the ticks asked for after it', async () => {
  const x = comparing([3, 1], [3, 2, 1]);
  const first = x.context.loadComparison();
  x.state.chosen = [3, 2];
  const second = x.context.loadComparison();
  x.pending.find((one) => one.url.endsWith('/2')).resolve({ snapshot: { id: 2 } });
  await second;
  x.pending.find((one) => one.url.endsWith('/1')).resolve({ snapshot: { id: 1 } });
  await first;
  assert.equal(x.state.past.map((one) => one.id).join(','), '2');
});
