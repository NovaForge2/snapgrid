// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 NovaForge2
//
// Everything a plugin produces is untrusted text, so it only ever reaches the
// page through textContent. Nothing here builds HTML out of plugin output.

"use strict";

const state = {
  plugins: [],
  selected: null,
  detail: null,
  snapshotId: null,
  filters: new Map(), // column name -> Set of allowed values
  configFor: null,    // which plugin the config panel is currently showing
  side: null,         // null, "log" or "config"
  sort: { column: null, direction: 0 },
  search: "",
  columnsKey: "",
};

const el = (id) => document.getElementById(id);

/* ---------------------------------------------------------------- theme */

// Three states rather than two: someone whose system switches at sunset
// usually wants the page to follow it, but anyone who disagrees with their
// system should not have to change the system to disagree.
const THEMES = ["auto", "light", "dark"];
const THEME_KEY = "snapgrid-theme";

function applyTheme(choice) {
  const root = document.documentElement;
  if (choice === "auto") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", choice);
  const button = document.getElementById("theme");
  if (button) button.textContent = choice;
}

function storedTheme() {
  try {
    const saved = localStorage.getItem(THEME_KEY);
    return THEMES.includes(saved) ? saved : "auto";
  } catch (error) {
    return "auto";
  }
}

applyTheme(storedTheme());

document.getElementById("theme").addEventListener("click", () => {
  const next = THEMES[(THEMES.indexOf(storedTheme()) + 1) % THEMES.length];
  try {
    localStorage.setItem(THEME_KEY, next);
  } catch (error) {
    /* the choice lasts for this page only, which is better than failing */
  }
  applyTheme(next);
});

/* ------------------------------------------------------------------ api */

async function api(path, options = {}) {
  const init = { headers: { "X-Snapgrid": "1" }, ...options };
  const response = await fetch(path, init);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error || "request failed (" + response.status + ")");
  return payload;
}

/* -------------------------------------------------------------- helpers */

function timeAgo(seconds) {
  if (!seconds) return "never";
  const delta = Date.now() / 1000 - seconds;
  if (delta < 45) return "just now";
  if (delta < 5400) return Math.round(delta / 60) + " min ago";
  if (delta < 172800) return Math.round(delta / 3600) + " h ago";
  return new Date(seconds * 1000).toLocaleString();
}

function humanInterval(seconds) {
  if (!seconds) return "manual only";
  if (seconds % 3600 === 0) return "every " + seconds / 3600 + "h";
  if (seconds % 60 === 0) return "every " + seconds / 60 + "m";
  return "every " + seconds + "s";
}

const NUMBER_RE = /^-?\d+(\.\d+)?$/;
const VERSION_RE = /^\d+(\.\d+)+/;

// A column is treated as numbers or versions only when every value in it looks
// that way. Otherwise "10" would sort before "9", which is the classic
// spreadsheet annoyance.
function detectKind(rows, index) {
  let sawValue = false;
  let allNumbers = true;
  let allVersions = true;
  for (const row of rows) {
    const value = (row[index] || "").trim();
    if (!value) continue;
    sawValue = true;
    if (!NUMBER_RE.test(value)) allNumbers = false;
    if (!VERSION_RE.test(value)) allVersions = false;
    if (!allNumbers && !allVersions) return "text";
  }
  if (!sawValue) return "text";
  if (allNumbers) return "number";
  if (allVersions) return "version";
  return "text";
}

function compareVersions(a, b) {
  const left = a.split(/[^0-9]+/).filter(Boolean).map(Number);
  const right = b.split(/[^0-9]+/).filter(Boolean).map(Number);
  for (let i = 0; i < Math.max(left.length, right.length); i++) {
    const x = left[i] === undefined ? 0 : left[i];
    const y = right[i] === undefined ? 0 : right[i];
    if (x !== y) return x - y;
  }
  return a.localeCompare(b);
}

function compareValues(a, b, kind) {
  const left = (a || "").trim();
  const right = (b || "").trim();
  if (left === "" && right === "") return 0;
  if (left === "") return 1; // blanks always sink to the bottom
  if (right === "") return -1;
  if (kind === "number") return Number(left) - Number(right);
  if (kind === "version") return compareVersions(left, right);
  return left.localeCompare(right, undefined, { numeric: true, sensitivity: "base" });
}

/* ------------------------------------------------------------- sidebar */

function renderSidebar() {
  const list = el("plugin-list");
  list.textContent = "";

  if (!state.plugins.length) {
    const note = document.createElement("div");
    note.className = "group-label";
    note.textContent = "no plugins yet";
    list.appendChild(note);
    return;
  }

  let currentGroup = null;
  for (const plugin of state.plugins) {
    const group = plugin.group || "Plugins";
    if (group !== currentGroup) {
      currentGroup = group;
      const label = document.createElement("div");
      label.className = "group-label";
      label.textContent = group;
      list.appendChild(label);
    }

    const button = document.createElement("button");
    button.className = "plugin" + (plugin.id === state.selected ? " selected" : "");
    button.type = "button";

    const dot = document.createElement("span");
    dot.className = "dot " + plugin.status;
    dot.title = plugin.error || plugin.status;

    const label = document.createElement("span");
    label.className = "label";
    label.textContent = plugin.name;

    button.append(dot, label);
    button.addEventListener("click", () => select(plugin.id));
    list.appendChild(button);
  }
}

/* -------------------------------------------------------------- detail */

const DISMISSED_KEY = "snapgrid-banner-dismissed";

// Browser storage can be unavailable or refuse to be written to, and a banner
// is not worth breaking the page over.
function dismissedBanner() {
  try {
    return localStorage.getItem(DISMISSED_KEY);
  } catch (error) {
    return null;
  }
}

function rememberDismissed(id) {
  try {
    localStorage.setItem(DISMISSED_KEY, id);
  } catch (error) {
    /* nothing to do: the banner simply comes back on the next load */
  }
}

// With no plugins at all, the page should say what to run rather than leave
// someone staring at an empty list.
function renderEmptyState(server, pluginCount) {
  const command = el("empty-command");
  if (pluginCount > 0) {
    el("empty-title").textContent = "No plugin selected";
    el("empty-text").textContent = "Pick one on the left.";
    command.hidden = true;
    return;
  }
  const plugins = (server && server.plugins_dir) || "plugins";
  const examples = server && server.examples_dir;
  el("empty-title").textContent = "No plugins yet";
  el("empty-text").textContent = "Nothing in " + plugins + "/. Stop the server and run one of these:";
  command.hidden = false;
  command.textContent = examples
    ? "# see the examples\n./server.py --dir " + examples +
      "\n\n# start your own\ncp -r " + examples + "/hello-table " + plugins + "/my-plugin\n" +
      "then edit " + plugins + "/my-plugin/plugin.toml"
    : "# start your own\nmkdir " + plugins + "/my-plugin\n" +
      "then put a plugin.toml and a script in it";
}

function renderServerInfo(server) {
  if (!server) return;
  if (server.title) {
    el("brand").textContent = server.title;
    document.title = server.title;
  }

  const banner = el("banner");
  const message = server.banner && server.banner.text;
  const id = server.banner && server.banner.id;

  if (!message || dismissedBanner() === id) {
    banner.hidden = true;
    banner.textContent = "";
    return;
  }

  // Already showing this exact message: leave it alone, so a click on the
  // close button is not undone by the next poll.
  if (!banner.hidden && banner.dataset.id === id) return;

  banner.hidden = false;
  banner.className = server.banner.level || "info";
  banner.dataset.id = id;
  banner.textContent = "";

  const text = document.createElement("span");
  text.className = "banner-text";
  text.textContent = message;

  const close = document.createElement("button");
  close.type = "button";
  close.className = "banner-close";
  close.title = "Hide this message until the server restarts";
  close.setAttribute("aria-label", "Hide this message");
  close.textContent = "\u00d7";
  close.addEventListener("click", () => {
    rememberDismissed(id);
    banner.hidden = true;
  });

  banner.append(text, close);
}

async function loadPlugins() {
  try {
    const data = await api("/api/plugins");
    state.plugins = data.plugins;
    renderServerInfo(data.server);
    renderEmptyState(data.server, data.plugins.length);
    el("server-note").textContent = data.plugins.length + " plugins";
    renderSidebar();
    // Landing on "pick something" when there is a table ready to look at
    // wastes the first few seconds. Open the first one.
    if (!state.selected && state.plugins.length) select(state.plugins[0].id);
  } catch (error) {
    el("server-note").textContent = error.message;
  }
}

async function select(id) {
  if (state.selected !== id) {
    state.selected = id;
    state.configFor = null;
    el("config-body").textContent = "";
    state.snapshotId = null;
    state.filters.clear();
    state.sort = { column: null, direction: 0 };
    state.search = "";
    el("search").value = "";
  }
  renderSidebar();
  await loadDetail();
}

async function loadDetail() {
  if (!state.selected) return;
  const query = state.snapshotId ? "?snapshot=" + state.snapshotId : "";
  try {
    state.detail = await api("/api/plugins/" + encodeURIComponent(state.selected) + query);
    renderDetail();
  } catch (error) {
    showMessage(error.message, false);
  }
}

function showMessage(text, info) {
  const box = el("message");
  if (!text) {
    box.hidden = true;
    box.textContent = "";
    return;
  }
  box.hidden = false;
  box.className = info ? "info" : "";
  box.textContent = text;
}

function renderDetail() {
  const detail = state.detail;
  if (!detail) return;

  el("empty").hidden = true;
  el("panel").hidden = false;

  el("p-name").textContent = detail.name;
  el("p-desc").textContent = detail.description || "";

  const live = detail.live;
  const meta = [];
  meta.push(humanInterval(detail.every));
  if (detail.history_keep) meta.push("history " + detail.history_keep);
  if (live && live.status === "running") {
    meta.push("running " + Math.round(live.elapsed) + "s");
  } else if (live) {
    meta.push("queued");
  } else if (detail.snapshot) {
    meta.push("result from " + timeAgo(detail.snapshot.last_seen));
  }
  el("p-meta").textContent = meta.join(" - ");

  const busy = Boolean(live);
  el("btn-refresh").disabled = busy;
  el("btn-refresh").textContent = busy ? "Running..." : "Refresh";
  el("btn-cancel").hidden = !busy;

  const lastRun = detail.last_run;
  if (detail.error) {
    showMessage("This plugin cannot be loaded:\n" + detail.error, false);
  } else if (lastRun && lastRun.status !== "ok" && !busy) {
    showMessage(("Last run " + lastRun.status + ": " + (lastRun.error || "")).trim(), false);
  } else if (!detail.snapshot && !busy) {
    showMessage("No result yet. Press Refresh, or wait for the schedule.", true);
  } else {
    showMessage("", true);
  }

  renderSnapshotPicker();
  renderLog();

  // A plugin that cannot be loaded has nothing else to show, and its file is
  // exactly what you need to look at.
  if (detail.error && state.side === null) showSide("config");
  else if (state.side === "config" && state.configFor !== detail.id) loadConfig();

  const suffix = state.snapshotId ? "?snapshot=" + state.snapshotId : "";
  el("btn-export").href =
    "/api/plugins/" + encodeURIComponent(detail.id) + "/export.csv" + suffix;

  // Filters only make sense for the columns they were built against.
  const snapshot = detail.snapshot;
  const key = snapshot ? snapshot.columns.join(" ") : "";
  if (key !== state.columnsKey) {
    state.columnsKey = key;
    state.filters.clear();
    state.sort = { column: null, direction: 0 };
  }
  renderTable();
}

function renderSnapshotPicker() {
  const picker = el("snapshot-picker");
  const snapshots = state.detail.snapshots || [];
  if (snapshots.length < 2) {
    picker.hidden = true;
    return;
  }
  picker.hidden = false;
  picker.textContent = "";
  snapshots.forEach((snapshot, index) => {
    const option = document.createElement("option");
    option.value = String(snapshot.id);
    const when = timeAgo(snapshot.last_seen);
    option.textContent =
      index === 0 ? "latest (" + when + ")" : when + " - " + snapshot.row_count + " rows";
    if (state.snapshotId ? Number(state.snapshotId) === snapshot.id : index === 0) {
      option.selected = true;
    }
    picker.appendChild(option);
  });
}

/* ------------------------------------------------------- toml highlight */

// Enough of TOML to read a plugin.toml comfortably: comments, section
// headings, keys, strings, numbers and booleans. Built as text nodes and
// spans, never as HTML, so a manifest cannot inject anything into the page.
const TOML_VALUE = /("(?:[^"\\]|\\.)*"|'[^']*')|(\btrue\b|\bfalse\b)|(-?\b\d+(?:\.\d+)?\b)|(#.*)/g;

function span(className, text) {
  const node = document.createElement("span");
  node.className = className;
  node.textContent = text;
  return node;
}

function highlightValue(target, text) {
  let index = 0;
  for (const match of text.matchAll(TOML_VALUE)) {
    if (match.index > index) target.appendChild(document.createTextNode(text.slice(index, match.index)));
    if (match[1]) target.appendChild(span("tok-string", match[1]));
    else if (match[2]) target.appendChild(span("tok-bool", match[2]));
    else if (match[3]) target.appendChild(span("tok-number", match[3]));
    else if (match[4]) target.appendChild(span("tok-comment", match[4]));
    index = match.index + match[0].length;
  }
  if (index < text.length) target.appendChild(document.createTextNode(text.slice(index)));
}

function highlightToml(text) {
  const out = document.createDocumentFragment();
  for (const line of text.split("\n")) {
    const trimmed = line.trimStart();
    if (trimmed.startsWith("#")) {
      out.appendChild(span("tok-comment", line));
    } else if (trimmed.startsWith("[")) {
      out.appendChild(span("tok-section", line));
    } else {
      const equals = line.indexOf("=");
      if (equals === -1) {
        out.appendChild(document.createTextNode(line));
      } else {
        out.appendChild(span("tok-key", line.slice(0, equals)));
        out.appendChild(document.createTextNode("="));
        highlightValue(out, line.slice(equals + 1));
      }
    }
    out.appendChild(document.createTextNode("\n"));
  }
  return out;
}

/* --------------------------------------------------------------- config */

function addFact(list, label, value, tag) {
  const term = document.createElement("dt");
  term.textContent = label;
  const detail = document.createElement("dd");
  detail.textContent = value;
  if (tag) {
    const mark = document.createElement("span");
    mark.className = "tag";
    mark.textContent = " " + tag;
    detail.appendChild(mark);
  }
  list.append(term, detail);
}

function renderConfig(config) {
  const body = el("config-body");
  body.textContent = "";

  const facts = document.createElement("dl");
  facts.className = "config-facts";
  addFact(facts, "folder", config.dir);
  addFact(facts, "runs", config.command.length ? config.command.join(" ") : "(not set)");

  if (!config.env.present) {
    addFact(facts, ".env", "none");
  } else if (!config.env.entries.length) {
    addFact(facts, ".env", "present, but empty");
  } else {
    const names = config.env.entries
      .map((entry) => entry.name + (entry.encrypted ? " (encrypted)" : ""))
      .join(", ");
    addFact(facts, ".env", names);
  }
  body.appendChild(facts);

  const note = document.createElement("p");
  note.className = "config-note";
  note.textContent = "Values from .env are never shown here, only the names.";
  body.appendChild(note);

  const file = document.createElement("pre");
  file.className = "config-file";
  file.appendChild(highlightToml(config.manifest));
  body.appendChild(file);
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
    el("config-body").textContent = error.message;
  }
}

/* ----------------------------------------------------------- side panel */

// The panel floats over the table rather than sitting under it, so a closed
// panel costs the grid nothing at all.
function showSide(which) {
  state.side = which;
  const open = which !== null;
  el("side").hidden = !open;
  el("log-text").hidden = which !== "log";
  el("config-body").hidden = which !== "config";
  el("side-log").classList.toggle("active", which === "log");
  el("side-config").classList.toggle("active", which === "config");
  el("btn-log").classList.toggle("active", which === "log");
  el("btn-config").classList.toggle("active", which === "config");
  // Fetched when shown rather than on every poll: it reads files from disk
  // and is only wanted occasionally.
  if (which === "config" && state.configFor !== state.selected) loadConfig();
}

function toggleSide(which) {
  showSide(state.side === which ? null : which);
}

el("btn-log").addEventListener("click", () => toggleSide("log"));
el("btn-config").addEventListener("click", () => toggleSide("config"));
el("side-log").addEventListener("click", () => showSide("log"));
el("side-config").addEventListener("click", () => showSide("config"));
el("side-close").addEventListener("click", () => showSide(null));
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && state.side) showSide(null);
});

function renderLog() {
  const detail = state.detail;
  const live = detail.live;
  const text = (live && live.log) || (detail.last_run && detail.last_run.log) || "";
  el("log-text").textContent = text || "(no log output)";
}

/* --------------------------------------------------------------- table */

// Rows passing every filter except one. Used both for the table itself and for
// the value list inside a filter popup, which is what makes the popup show the
// values that are actually reachable, the way a spreadsheet does.
function visibleRows(columns, rows, skipColumn) {
  const needle = state.search.trim().toLowerCase();
  return rows.filter((row) => {
    for (const [name, allowed] of state.filters) {
      if (name === skipColumn) continue;
      const index = columns.indexOf(name);
      if (index < 0) continue;
      if (!allowed.has(row[index] === undefined ? "" : row[index])) return false;
    }
    if (needle && !row.some((cell) => String(cell).toLowerCase().includes(needle))) return false;
    return true;
  });
}

function renderTable() {
  const wrap = el("table-wrap");
  wrap.textContent = "";

  const snapshot = state.detail && state.detail.snapshot;
  if (!snapshot) {
    el("row-note").textContent = "";
    el("btn-clear").hidden = true;
    return;
  }

  const columns = snapshot.columns;
  const kinds = columns.map((_, index) => detectKind(snapshot.rows, index));
  let rows = visibleRows(columns, snapshot.rows, null);

  if (state.sort.direction !== 0 && state.sort.column) {
    const index = columns.indexOf(state.sort.column);
    if (index >= 0) {
      const kind = kinds[index];
      const direction = state.sort.direction;
      rows = rows.slice().sort((a, b) => direction * compareValues(a[index], b[index], kind));
    }
  }

  const table = document.createElement("table");
  const thead = document.createElement("thead");
  const headRow = document.createElement("tr");

  columns.forEach((column) => {
    const th = document.createElement("th");
    const inner = document.createElement("div");
    inner.className = "th-inner";

    const label = document.createElement("span");
    label.className = "th-label";
    label.textContent = column;
    label.addEventListener("click", () => toggleSort(column));

    const mark = document.createElement("span");
    mark.className = "sort-mark";
    if (state.sort.column === column && state.sort.direction !== 0) {
      mark.textContent = state.sort.direction > 0 ? "▲" : "▼";
    }

    const filterButton = document.createElement("button");
    filterButton.type = "button";
    filterButton.className = "filter-btn" + (state.filters.has(column) ? " active" : "");
    filterButton.textContent = "▾";
    filterButton.title = "Filter this column";
    filterButton.addEventListener("click", (event) => {
      event.stopPropagation();
      openFilter(column, filterButton);
    });

    inner.append(label, mark, filterButton);
    th.appendChild(inner);
    headRow.appendChild(th);
  });

  thead.appendChild(headRow);
  table.appendChild(thead);

  const tbody = document.createElement("tbody");
  if (!rows.length) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = columns.length;
    td.className = "empty-row";
    td.textContent = snapshot.rows.length
      ? "No rows match the current filters."
      : "The plugin returned no rows.";
    tr.appendChild(td);
    tbody.appendChild(tr);
  } else {
    for (const row of rows) {
      const tr = document.createElement("tr");
      columns.forEach((_, index) => {
        const td = document.createElement("td");
        if (kinds[index] === "number") td.className = "num";
        const value = row[index] === undefined ? "" : row[index];
        td.textContent = value;
        td.title = value; // cells are clipped, so keep the full value reachable
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    }
  }
  table.appendChild(tbody);
  wrap.appendChild(table);

  const total = snapshot.rows.length;
  el("row-note").textContent =
    rows.length === total ? total + " rows" : rows.length + " of " + total + " rows";
  el("btn-clear").hidden = state.filters.size === 0 && !state.search;
}

function toggleSort(column) {
  if (state.sort.column !== column) {
    state.sort = { column: column, direction: 1 };
  } else if (state.sort.direction === 1) {
    state.sort.direction = -1;
  } else {
    state.sort = { column: null, direction: 0 };
  }
  renderTable();
}

/* -------------------------------------------------------- filter popup */

function closeFilter() {
  const popup = el("filter-popup");
  popup.hidden = true;
  popup.textContent = "";
}

function openFilter(column, anchor) {
  const popup = el("filter-popup");
  const snapshot = state.detail.snapshot;
  const columns = snapshot.columns;
  const index = columns.indexOf(column);
  const kind = detectKind(snapshot.rows, index);

  const counts = new Map();
  for (const row of visibleRows(columns, snapshot.rows, column)) {
    const value = row[index] === undefined ? "" : row[index];
    counts.set(value, (counts.get(value) || 0) + 1);
  }
  const values = Array.from(counts.keys()).sort((a, b) => compareValues(a, b, kind));

  const selected = state.filters.has(column)
    ? new Set(state.filters.get(column))
    : new Set(values);

  popup.textContent = "";
  popup.hidden = false;

  const search = document.createElement("input");
  search.type = "search";
  search.placeholder = "Find a value";
  popup.appendChild(search);

  const list = document.createElement("div");
  list.className = "values";
  popup.appendChild(list);

  const apply = () => {
    if (selected.size === values.length) state.filters.delete(column);
    else state.filters.set(column, new Set(selected));
    renderTable();
  };

  const draw = (needle) => {
    list.textContent = "";
    const shown = values.filter(
      (value) => !needle || String(value).toLowerCase().includes(needle.toLowerCase())
    );
    for (const value of shown) {
      const row = document.createElement("label");
      row.className = "value-row";

      const box = document.createElement("input");
      box.type = "checkbox";
      box.checked = selected.has(value);
      box.addEventListener("change", () => {
        if (box.checked) selected.add(value);
        else selected.delete(value);
        apply();
      });

      const text = document.createElement("span");
      text.className = "v";
      text.textContent = value === "" ? "(blank)" : value;

      const count = document.createElement("span");
      count.className = "c";
      count.textContent = String(counts.get(value));

      row.append(box, text, count);
      list.appendChild(row);
    }
    if (!shown.length) {
      const none = document.createElement("div");
      none.className = "c";
      none.textContent = "nothing matches";
      list.appendChild(none);
    }
  };

  search.addEventListener("input", () => draw(search.value));

  const actions = document.createElement("div");
  actions.className = "popup-actions";

  const all = document.createElement("button");
  all.type = "button";
  all.textContent = "Select all";
  all.addEventListener("click", () => {
    values.forEach((value) => selected.add(value));
    draw(search.value);
    apply();
  });

  const none = document.createElement("button");
  none.type = "button";
  none.textContent = "Clear";
  none.addEventListener("click", () => {
    selected.clear();
    draw(search.value);
    apply();
  });

  actions.append(all, none);
  popup.appendChild(actions);
  draw("");

  const box = anchor.getBoundingClientRect();
  popup.style.top = window.scrollY + box.bottom + 4 + "px";
  const left = Math.min(window.scrollX + box.left, window.scrollX + window.innerWidth - 276);
  popup.style.left = Math.max(8, left) + "px";
  search.focus();
}

document.addEventListener("click", (event) => {
  const popup = el("filter-popup");
  if (!popup.hidden && !popup.contains(event.target)) closeFilter();
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") closeFilter();
});

/* ------------------------------------------------------------- actions */

el("btn-refresh").addEventListener("click", async () => {
  try {
    await api("/api/plugins/" + encodeURIComponent(state.selected) + "/run", { method: "POST" });
    state.snapshotId = null;
    await loadDetail();
  } catch (error) {
    showMessage(error.message, false);
  }
});

el("btn-cancel").addEventListener("click", async () => {
  const live = state.detail && state.detail.live;
  if (!live) return;
  try {
    await api("/api/runs/" + live.run_id + "/cancel", { method: "POST" });
    await loadDetail();
  } catch (error) {
    showMessage(error.message, false);
  }
});

el("snapshot-picker").addEventListener("change", (event) => {
  const picker = event.target;
  state.snapshotId = picker.selectedIndex === 0 ? null : picker.value;
  loadDetail();
});

el("search").addEventListener("input", (event) => {
  state.search = event.target.value;
  renderTable();
});

el("btn-clear").addEventListener("click", () => {
  state.filters.clear();
  state.search = "";
  el("search").value = "";
  renderTable();
});

/* ------------------------------------------------------------- polling */

loadPlugins();
setInterval(loadPlugins, 5000);
setInterval(() => {
  if (state.detail && state.detail.live) loadDetail();
}, 1000);
