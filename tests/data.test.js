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
