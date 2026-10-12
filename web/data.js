// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 NovaForge2
// Requests and view loading. Plain scripts keep deployment build-free.

async function api(path, options = {}) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 15000);
  try {
    const response = await fetch(path, {
      ...options, signal: controller.signal,
      headers: { "X-Snapgrid": "1", ...options.headers },
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.error || "request failed (" + response.status + ")");
    return payload;
  } finally {
    clearTimeout(timeout);
  }
}

let pluginsPending = false;
let detailRequest = 0;
let detailPending = null;


async function loadPlugins() {
  if (pluginsPending) return;
  pluginsPending = true;
  try {
    const data = await api("/api/plugins");
    state.plugins = data.plugins;
    renderServerInfo(data.server);
    renderEmptyState(data.server, data.plugins.length);
    renderSidebar();
    renderPauseAll();      // sets the plugin count, with the paused one in it
    // Landing on "pick something" when there is a table ready to look at
    // wastes the first few seconds. Open the first one.
    if (!state.selected && state.plugins.length) {
      // A link can name the plugin, and how far back to compare, so that what
      // is on your screen is something you can send to somebody.
      const asked = new URLSearchParams(location.search);
      const wanted = asked.get("plugin");
      const known = state.plugins.some((plugin) => plugin.id === wanted);
      await select(known ? wanted : state.plugins[0].id);
      state.depth = Math.min(MAX_DEPTH, Math.max(1, Number(asked.get("compare")) || 1));
      state.onlyChanged = asked.get("changed") === "1";
      el("diff-only-box").checked = state.onlyChanged;
      if (state.depth > 1) {
        renderComparePicker();
        await loadComparison();
        renderTable();
      }
    } else if (state.selected) {
      // Runs can start and finish entirely between polls. Refresh even when
      // the last detail response said the plugin was idle.
      await loadDetail();
    }
  } catch (error) {
    el("server-note").textContent = error.message;
  } finally {
    pluginsPending = false;
  }
}


async function loadDetail() {
  const id = state.selected;
  const snapshot = state.snapshotId;
  if (!id) return;
  const key = JSON.stringify([id, snapshot]);
  if (detailPending && detailPending.key === key) return detailPending.promise;
  const mine = ++detailRequest;
  const current = () => mine === detailRequest && state.selected === id && state.snapshotId === snapshot;
  const query = snapshot ? "?snapshot=" + snapshot : "";
  const request = { key };
  detailPending = request;
  request.promise = (async () => {
    try {
      const detail = await api("/api/plugins/" + encodeURIComponent(id) + query);
      if (!current()) return;
      const signature = (value) => value && JSON.stringify([
        value.id, value.snapshot && value.snapshot.id, value.key, value.colours,
      ]);
      const redraw = signature(state.detail) !== signature(detail);
      state.detail = detail;
      renderDetail(redraw);
      if (state.depth > 1 && state.pastFor !== comparisonSignature()) {
        await loadComparison();
        if (current()) renderTable();
      }
    } catch (error) {
      if (current()) showMessage(error.message, false);
    } finally {
      if (detailPending === request) detailPending = null;
    }
  })();
  return request.promise;
}

let comparisonRequest = 0;

async function loadComparison() {
  const mine = ++comparisonRequest;
  const wanted = comparisonSignature();
  state.past = [];
  state.pastFor = "";
  state.unreadable = 0;
  if (state.depth < 2 || !state.detail) return;

  const snapshots = state.detail.snapshots || [];
  const showing = state.snapshotId ? Number(state.snapshotId) : (snapshots[0] || {}).id;
  const at = snapshots.findIndex((snapshot) => snapshot.id === showing);
  const older = snapshots.slice(at + 1, at + state.depth);

  const loaded = [];
  let unreadable = 0;
  for (const snapshot of older) {
    try {
      const payload = await api("/api/snapshots/" + snapshot.id);
      if (mine !== comparisonRequest || wanted !== comparisonSignature()) return;       // something newer was asked for
      loaded.push(payload.snapshot || payload);     // the endpoint wraps it
    } catch (error) {
      // One stored result that cannot be read should not lose the others, but
      // quietly comparing fewer runs than were asked for would be a smaller
      // answer wearing the label of the one requested.
      unreadable = older.length - loaded.length;
      break;
    }
  }
  if (mine !== comparisonRequest || wanted !== comparisonSignature()) return;
  state.past = loaded;
  state.pastFor = wanted;
  state.unreadable = unreadable;
}


async function loadConfig() {
  const id = state.selected;
  if (!id) return;
  try {
    const config = await api("/api/plugins/" + encodeURIComponent(id) + "/config");
    if (state.selected !== id) return;   // they moved on while it was loading
    state.configFor = id;
    renderConfig(config);
  } catch (error) {
    if (state.selected === id) el("config-body").textContent = error.message;
  }
}
