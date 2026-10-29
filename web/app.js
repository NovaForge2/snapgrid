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
  depth: 1,           // how many runs are shown in each cell; 1 means off
  against: 0,         // compare with this one stored run instead of the last
                      // few: its snapshot id, or 0 for the stack above
  past: [],           // the older snapshots, newest first, once fetched
  unreadable: 0,      // how many of those could not be read
  pastFor: "",        // what those older snapshots were fetched for
  onlyChanged: false,
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

// A symbol as well as the word: the word alone reads as a label rather than
// as something to press.
const THEME_MARKS = { auto: "\u25D1", light: "\u2600", dark: "\u263E" };

function applyTheme(choice) {
  const root = document.documentElement;
  if (choice === "auto") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", choice);
  const button = document.getElementById("theme");
  if (button) button.textContent = `${THEME_MARKS[choice]} ${choice}`;
}

function storedTheme() {
  try {
    const saved = localStorage.getItem(THEME_KEY);
    return THEMES.includes(saved) ? saved : "auto";
  } catch (error) {
    return "auto";
  }
}

// A link can ask for a theme, which the button then overrides as usual. It is
// what makes a screenshot or a link for a presentation come out as intended
// rather than as whatever the viewer's machine happens to prefer.
function askedTheme() {
  const asked = new URLSearchParams(location.search).get("theme");
  return THEMES.includes(asked) ? asked : storedTheme();
}

applyTheme(askedTheme());

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


/* -------------------------------------------------------------- helpers */

// One vocabulary for every length of time on the page: s, m, h, d - the same
// letters plugin.toml uses. It used to say "every 15m" in one place, "5 min
// ago" in the next and "in 12 min" in a third, which reads like three
// different units rather than one written three ways.
function duration(seconds) {
  const n = Math.abs(Math.round(seconds));
  if (n < 60) return n + "s";
  if (n < 3600) return Math.round(n / 60) + "m";
  if (n < 86400) return Math.round(n / 3600) + "h";
  return Math.round(n / 86400) + "d";
}

function timeAgo(seconds) {
  if (!seconds) return "never";
  const delta = Date.now() / 1000 - seconds;
  if (delta < 45) return "just now";
  if (delta < 172800) return duration(delta) + " ago";
  return new Date(seconds * 1000).toLocaleString();
}

// A date and a clock time, for the two dropdowns that name a stored run.
// "2h ago" is the friendlier form in a sentence and the wrong one in a list
// of runs to choose between: several of them are "2h ago", and the minutes
// are the only thing that tells them apart.
//
// A 24 hour clock whatever the machine's locale says, for width: "19:47" is
// five characters where "07:47 PM" is eight, in a dropdown where the clock
// is the part that was being cut off. The date keeps the locale's own order.
function clockOf(seconds, withSeconds) {
  if (!seconds) return "never";
  const when = new Date(seconds * 1000);
  const day = when.toLocaleDateString([], { day: "numeric", month: "short" });
  const clock = when.toLocaleTimeString([], {
    hour: "2-digit", minute: "2-digit", hour12: false,
    ...(withSeconds ? { second: "2-digit" } : {}),
  });
  return `${day} ${clock}`;
}

// Two runs a few seconds apart read as the same entry to the minute, and a
// list of runs where two lines are identical cannot be chosen from. Seconds
// are added to all of them when that happens, rather than to the pair, so
// that every line in the list is still the same shape.
function clockNeedsSeconds(snapshots) {
  const seen = new Set();
  for (const snapshot of snapshots) {
    const label = clockOf(snapshot.last_seen, false);
    if (seen.has(label)) return true;
    seen.add(label);
  }
  return false;
}

function timeUntil(seconds) {
  const delta = seconds - Date.now() / 1000;
  if (delta <= 30) return "any moment";
  if (delta < 5400) return "in " + duration(delta);

  // A clock time is friendlier than "in 5h" for something happening today.
  // For anything later it is a lie that reads as today, so the date comes too.
  const when = new Date(seconds * 1000);
  const clock = when.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  if (when.toDateString() === new Date().toDateString()) return "at " + clock;
  return "in " + duration(delta) + ", " + when.toLocaleDateString([], { day: "numeric", month: "short" })
         + " " + clock;
}

// A wall clock schedule is shown as it was written. Translating "0 9 * * 1-5"
// into English reads well until the expression is one of the awkward ones,
// and a half-translated schedule is worse than the line the person typed.
function humanSchedule(detail) {
  if (detail.cron) return "at " + detail.cron;
  return humanInterval(detail.every);
}

function humanInterval(seconds) {
  if (!seconds) return "manual only";
  if (seconds % 604800 === 0) return "every " + seconds / 604800 + "w";
  if (seconds % 86400 === 0) return "every " + seconds / 86400 + "d";
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

    const row = document.createElement("div");
    row.className = "plugin" + (plugin.id === state.selected ? " selected" : "")
                             + (plugin.paused_since ? " paused" : "");

    // In front of the name, because that is where the eye goes when the
    // question is "why has this not changed?" - and because it has to be its
    // own button, not part of the one that opens the plugin.
    if (onASchedule(plugin)) {
      row.appendChild(pauseButton(plugin));
    } else {
      const gap = document.createElement("span");
      gap.className = "pause-gap";     // keeps the names in a line
      row.appendChild(gap);
    }

    const pick = document.createElement("button");
    pick.className = "pick";
    pick.type = "button";

    const dot = document.createElement("span");
    dot.className = "dot " + plugin.status;
    dot.title = plugin.error || plugin.status;

    const label = document.createElement("span");
    label.className = "label";
    label.textContent = plugin.name;

    pick.append(dot, label);
    pick.addEventListener("click", () => select(plugin.id));
    row.appendChild(pick);
    list.appendChild(row);
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
    el("brand-text").textContent = server.title;
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


async function select(id) {
  if (state.selected !== id) {
    state.selected = id;
    state.detail = null;
    el("panel").hidden = true;
    state.configFor = null;
    el("config-body").textContent = "";
    state.snapshotId = null;
    state.filters.clear();
    state.sort = { column: null, direction: 0 };
    state.search = "";
    el("search").value = "";
    // A comparison belongs to one table; carrying it to another would compare
    // things that have nothing to do with each other.
    state.depth = 1;
    state.past = [];
    state.onlyChanged = false;
    el("diff-only-box").checked = false;
    closeCellHistory();
  }
  renderSidebar();
  rememberInTheAddress();
  await loadDetail();
}

// Kept in the address rather than in storage: a bookmark, a link in a message
// and the back button then all mean the same thing.
//
// What goes in is what is about the data: which plugin, how far back it is
// compared, what it is sorted and filtered by, what was searched for. What
// stays in this browser is what is about this screen - the hidden columns,
// the dragged widths, Compact - because those are one person's view of the
// table on one monitor, and sending them to somebody else says nothing.
//
// It is also what lets the animation in the README be rebuilt rather than
// recorded by hand: every frame of it is a state the address can name. See
// tools/make-screenshots.py.
function rememberInTheAddress() {
  const asked = new URLSearchParams();
  if (state.selected) asked.set("plugin", state.selected);
  // Which result, not only which plugin: "this is what it said at nine" is a
  // thing to send somebody.
  if (state.snapshotId) asked.set("snapshot", String(state.snapshotId));
  if (state.against) asked.set("against", String(state.against));
  else if (state.depth > 1) asked.set("compare", String(state.depth));
  if (state.onlyChanged) asked.set("changed", "1");
  if (state.sort.column && state.sort.direction) {
    asked.set("sort", state.sort.column + (state.sort.direction > 0 ? ":asc" : ":desc"));
  }
  if (state.search.trim()) asked.set("q", state.search);
  // One parameter per column, named after the column, one value each. A value
  // can hold a comma, a colon or anything else that might have been used to
  // join them, so nothing is joined: the column name is in the name of the
  // parameter, where the browser encodes it for us.
  for (const [column, allowed] of state.filters) {
    for (const value of allowed) asked.append(FILTER_PREFIX + column, value);
  }

  const query = asked.toString();
  // renderTable calls this, and renderTable runs once a second while a plugin
  // is running. Writing the same address over and over is both pointless and
  // rate limited by some browsers, so nothing is written unless it changed.
  if (location.search === (query ? "?" + query : "")) return;
  history.replaceState(null, "", query ? "?" + query : location.pathname);
}

const FILTER_PREFIX = "filter.";

// The other half of it: the view a link asks for, applied once, when the first
// plugin is opened. After that the address is something this page writes
// rather than something it was given.
//
// A sort or a filter naming a column this table does not have is ignored
// rather than guessed at: the link was written for some other table, or for
// this one before a column was renamed, and inventing a column is worse than
// showing the table as it is. Returns whether it asked for anything, so the
// caller knows whether the table has to be drawn again.
function viewFromTheAddress(asked) {
  const columns = (state.detail && state.detail.snapshot && state.detail.snapshot.columns) || [];
  let anything = false;

  const sort = asked.get("sort");
  if (sort) {
    // Split on the last colon, and only when what follows it is a direction:
    // a column may be called anything at all, including "11:30".
    let column = sort;
    let direction = 1;
    const cut = sort.lastIndexOf(":");
    if (cut > 0) {
      const how = sort.slice(cut + 1).toLowerCase();
      if (how === "asc" || how === "desc") {
        column = sort.slice(0, cut);
        direction = how === "desc" ? -1 : 1;
      }
    }
    if (columns.includes(column)) {
      state.sort = { column, direction };
      anything = true;
    }
  }

  const needle = asked.get("q");
  if (needle) {
    state.search = needle;
    el("search").value = needle;
    anything = true;
  }

  for (const [name, value] of asked) {
    if (!name.startsWith(FILTER_PREFIX)) continue;
    const column = name.slice(FILTER_PREFIX.length);
    if (!columns.includes(column)) continue;
    if (!state.filters.has(column)) state.filters.set(column, new Set());
    state.filters.get(column).add(value);
    anything = true;
  }
  return anything;
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

function renderDetail(redraw = true) {
  const detail = state.detail;
  if (!detail) return;

  el("empty").hidden = true;
  el("panel").hidden = false;

  el("p-name").textContent = detail.name;
  el("p-desc").textContent = detail.description || "";

  const live = detail.live;
  const meta = [];
  meta.push(humanSchedule(detail));
  if (detail.history_keep) meta.push("history " + detail.history_keep);
  if (live && live.status === "running") {
    meta.push("running " + Math.round(live.elapsed) + "s");
  } else if (live) {
    meta.push("queued");
  } else if (detail.snapshot) {
    meta.push("result from " + timeAgo(detail.snapshot.last_seen));
  }
  // A plugin that keeps failing is slowed down, and used to be slowed down in
  // silence: nothing running, nothing said, and the same old error on screen.
  if (!live && detail.next_run) {
    meta.push(detail.failures >= 3
      ? `slowed after ${detail.failures} failures, next try ${timeUntil(detail.next_run)}`
      : "next run " + timeUntil(detail.next_run));
  }
  // One element per fact, so a row that wraps on a narrow window does not
  // leave a separator dangling at the end of a line - the rule between them
  // is drawn by the stylesheet.
  const metaBox = el("p-meta");
  metaBox.textContent = "";
  for (const fact of meta) {
    const span = document.createElement("span");
    span.className = "fact";
    span.textContent = fact;
    metaBox.appendChild(span);
  }

  // A paused plugin shows a table that looks exactly like a current one, so
  // the page has to be loud about it. This is the whole risk of the feature:
  // a fortnight-old number read as today's is worse than no number.
  const paused = detail.paused_since;
  const pausedBox = el("p-paused");
  pausedBox.hidden = !paused;
  if (paused) {
    pausedBox.textContent = "";
    const icon = document.createElement("span");
    icon.innerHTML = PAUSE_ICON;
    const words = document.createElement("span");
    // Two facts, and the second is the one people ask about: a paused plugin
    // is not a broken one, and the button still works.
    words.textContent = "Paused \u00b7 Manual runs available.";
    pausedBox.append(icon, words);
    pausedBox.title = `Paused ${timeAgo(paused)}. The schedule is leaving it `
                    + `alone until you resume it; Run now still works.`;
  }


  const busy = Boolean(live);
  el("btn-refresh").disabled = busy;
  el("btn-refresh").textContent = busy ? "Running..." : "Run now";
  el("btn-cancel").hidden = !busy;

  // A failed run is not announced above the table. The table under it is the
  // last good result, which is still true, and a red block sitting on top of a
  // correct table every time one run in fifty fails is noise: the dot beside
  // the plugin's name is already red, the line under the title already says
  // when the result is from and when the next try is, and the Log panel still
  // has the error in full.
  //
  // The exception is a plugin with nothing to show at all. Then the message is
  // the whole screen, and "no result yet" would read as "nothing has happened"
  // when what happened is that it ran and failed.
  const lastRun = detail.last_run;
  const failed = lastRun && lastRun.status !== "ok";
  if (detail.error) {
    showMessage("This plugin cannot be loaded:\n" + detail.error, false);
  } else if (!detail.snapshot && !busy) {
    showMessage(failed
      ? ("Last run " + lastRun.status + ": " + (lastRun.error || "")).trim()
      : "No result yet. Press Run now, or wait for the schedule.", !failed);
  } else {
    showMessage("", true);
  }

  renderSnapshotPicker();
  renderComparePicker();
  renderLog();

  // A plugin that cannot be loaded has nothing else to show, and its file is
  // exactly what you need to look at.
  if (detail.error && state.side === null) showSide("config");
  else if (state.side === "config" && state.configFor !== detail.id) loadConfig();


  // Filters only make sense for the columns they were built against.
  const snapshot = detail.snapshot;
  const key = snapshot ? snapshot.columns.join("\u0000") : "";
  if (key !== state.columnsKey) {
    state.columnsKey = key;
    state.filters.clear();
    state.sort = { column: null, direction: 0 };
  }
  if (redraw) renderTable();
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
  const seconds = clockNeedsSeconds(snapshots);
  snapshots.forEach((snapshot, index) => {
    const option = document.createElement("option");
    option.value = String(snapshot.id);
    // The time in full, with its minutes. Said as "2h ago", two runs an hour
    // apart read as the same entry, and the one thing anybody picks a stored
    // run by - when it was - is the part that was missing.
    //
    // "Showing", because without it the closed dropdown reads as a label
    // saying when the result is from rather than as the control that picks
    // which result is on screen - and then the only thing anybody finds is
    // the Compare dropdown beside it, which says what it does.
    const when = clockOf(snapshot.last_seen, seconds);
    option.textContent = index === 0
      ? "Showing " + when + " (latest)"
      : "Showing " + when + " - " + rowCount(snapshot.row_count);
    if (state.snapshotId ? Number(state.snapshotId) === snapshot.id : index === 0) {
      option.selected = true;
    }
    picker.appendChild(option);
  });
}

function renderComparePicker() {
  const picker = el("compare-picker");
  const snapshots = state.detail.snapshots || [];
  // Nothing to compare a single result with.
  if (snapshots.length < 2) {
    picker.hidden = true;
    return;
  }
  picker.hidden = false;
  picker.textContent = "";

  const chosen = pickerValue();
  const add = (into, value, label) => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    if (value === chosen) option.selected = true;
    into.appendChild(option);
  };
  const group = (label) => {
    const holder = document.createElement("optgroup");
    holder.label = label;
    picker.appendChild(holder);
    return holder;
  };

  add(picker, "1", "Compare: off");

  // Stacking every run in between answers "when did this move?". Five is the
  // most, and it is a limit of height rather than of arithmetic: five runs of
  // a forty row table is a very tall page.
  const stack = group("The last few runs, stacked");
  add(stack, "2", "Compare with: the one before");
  for (let depth = 3; depth <= Math.min(MAX_DEPTH, snapshots.length); depth += 1) {
    add(stack, String(depth), `Compare: last ${depth} runs`);
  }

  // A pair instead, which answers the other question: what is different now
  // from how it was then. Every stored run is reachable, not only the last
  // five, and the runs in between are not drawn - two lines in a cell, now
  // and then. Only differing results are stored, so the oldest entry here is
  // the last time the table said something else.
  const showing = state.snapshotId ? Number(state.snapshotId) : (snapshots[0] || {}).id;
  const at = snapshots.findIndex((snapshot) => snapshot.id === showing);
  const older = snapshots.slice(at + 1);
  if (older.length) {
    const seconds = clockNeedsSeconds(older);
    const pair = group("One earlier run, on its own");
    for (const snapshot of older) {
      add(pair, "at:" + snapshot.id,
          "Compare with " + clockOf(snapshot.last_seen, seconds)
          + " - " + rowCount(snapshot.row_count));
    }
  }
}

// What the compare dropdown should have selected: a stored run if one was
// named, otherwise the depth of the stack.
function pickerValue() {
  return state.against ? "at:" + state.against : String(state.depth);
}

const MAX_DEPTH = 5;

/* ---------------------------------------------------------- comparing */

// The work itself is in compare.js, which the page loads first: pure
// functions, given the runs and the key column, returning what differs.
// These three are the seam, and the only part that knows about state.

// The columns that name a row: [table] key, or the leftmost one. More than
// one when no single column is unique, which is the usual case in a table
// shaped "environment,repo,version".
function keyIndexes(columns) {
  return keyIndexesIn(columns, state.detail && state.detail.key);
}

function keyIndex(columns) {
  return keyIndexes(columns)[0];
}

// Every run being shown, newest first: what is on screen, then the older ones.
// Each becomes one line inside every cell.
function comparedRuns(current) {
  return [current, ...state.past].slice(0, state.depth);
}

// The columns a comparison leaves alone: the ones [compare] ignore names, and
// the ones taken off the screen. A hidden column is out of the comparison for
// the same reason it is out of the table - what is being compared is what is
// being looked at - and a change in one of them would otherwise open a second
// line in every cell of a row with nothing to show on it.
function notCompared() {
  const named = (state.detail && state.detail.compare_ignore) || [];
  return new Set([...named, ...hiddenColumns()]);
}

function comparisonFor(current) {
  return compareRuns(comparedRuns(current), state.detail && state.detail.key, notCompared());
}

// What a set of older snapshots belongs to: this plugin, showing this result,
// this many runs back. When any of those changes the baseline is wrong.
function comparisonSignature() {
  const snapshots = (state.detail && state.detail.snapshots) || [];
  const showing = state.snapshotId ? Number(state.snapshotId) : (snapshots[0] || {}).id;
  return `${state.selected}|${showing}|${state.depth}|${state.against}`;
}

// Bumped on every request, so a slow answer cannot land after a newer one and
// overwrite it. Switching plugins mid-flight used to leave one plugin's table
// being compared against another plugin's history.

function renderDiffBar(diff) {
  const bar = el("diff-bar");
  if (!diff) {
    bar.hidden = true;
    return;
  }
  bar.hidden = false;

  const what = el("diff-what");
  what.textContent = "";
  const tally = el("diff-tally");
  tally.textContent = "";

  if (diff.impossible) {
    what.textContent = "Cannot compare: " + diff.impossible;
    return;
  }

  const short = state.unreadable
    ? ` - ${state.unreadable} earlier result${state.unreadable > 1 ? "s" : ""} could not be read`
    : "";
  // The columns plugin.toml takes out of the comparison are said here, once.
  // Without it a table where the only thing that moved is the time of the run
  // reads as "nothing changed" and looks broken. Hidden columns are not named:
  // the row count beneath already says how many are off the screen.
  const named = ((state.detail && state.detail.compare_ignore) || [])
    .filter((column) => diff.runs[0].columns.includes(column));
  const left = named.length
    ? ` - ${named.join(", ")} ${named.length > 1 ? "are" : "is"} not compared`
    : "";
  const against = state.against && diff.runs.length === 2
    ? `Comparing with the run of ${clockOf(diff.runs[1].last_seen)}`
    : `Showing the last ${diff.runs.length} runs`;
  what.textContent = (diff.degraded
    ? `Whole rows only, because ${diff.degraded}`
    : against) + left + short;

  // The runs are the same for every cell, so they are named once, here.
  // There is no room for a date inside a cell.
  const legend = document.createElement("span");
  legend.className = "legend";
  // Whole row mode draws one line per row, so numbering five runs would point
  // at lines that are not there.
  const listed = diff.whole ? diff.runs.slice(0, 1) : diff.runs;
  listed.forEach((run, at) => {
    const item = document.createElement("span");
    const number = document.createElement("i");
    number.className = at === 0 ? "n now" : "n";
    number.textContent = String(at + 1);
    item.append(number, document.createTextNode(at === 0 ? "now" : whenExactly(run.last_seen)));
    legend.appendChild(item);
  });
  // A dot is read either as "the same" or as "nothing there", and those are
  // opposites, so it is not left to be guessed at. Only where there are dots
  // to explain: whole row mode draws no stacked lines.
  if (!diff.whole && diff.runs.length > 1) {
    const key = document.createElement("span");
    key.className = "key";
    const dot = document.createElement("i");
    dot.className = "dotmark";
    dot.textContent = "\u00b7";
    key.append(dot, document.createTextNode("same as the run above"));
    key.title = "A cell written once did not change in any of these runs.";
    legend.appendChild(key);
  }
  tally.appendChild(legend);

}

// The counts beside the legend: values changed, rows appeared, rows gone.
// Appended once the table has been drawn, and counted from the rows it drew.
// Counted from the runs instead, the strip said "50 values changed" over nine
// visible rows - a count of somebody else's table. A filter that takes ENV2
// off the screen takes its changes out of the count with it.
//
// compareRuns still counts the whole table in diff.changedCells, diff.added
// and diff.removed. That is the truth about the two runs, which is what its
// tests check; it is not what this page shows.
function renderDiffCounts(moved, added, gone) {
  const tally = el("diff-tally");
  for (const [css, number, noun, verb] of [["c-changed", moved, "value", "changed"],
                                           ["c-added", added, "row", "appeared"],
                                           ["c-removed", gone, "row", "gone"]]) {
    if (!number) continue;
    const span = document.createElement("span");
    span.className = css;
    const bold = document.createElement("b");
    bold.textContent = String(number);
    span.append(bold, document.createTextNode(` ${noun}${number === 1 ? "" : "s"} ${verb}`));
    tally.appendChild(span);
  }
}

/* --------------------------------------------- the history of one cell */

function closeCellHistory() {
  el("cell-history").hidden = true;
}

// rowValues holds one value per column [table] key names, in that order:
// that is what says which row this cell is in when no single column is unique.
async function openCellHistory(rowValues, column, anchor) {
  const names = Array.isArray(rowValues) ? rowValues : [rowValues];
  const popup = el("cell-history");
  popup.textContent = "";
  popup.hidden = false;

  const heading = document.createElement("h4");
  heading.textContent = `${names.join(" / ")} - ${column}`;
  popup.appendChild(heading);

  const loading = document.createElement("div");
  loading.className = "none";
  loading.textContent = "reading the history...";
  popup.appendChild(loading);
  placePopup(popup, anchor);

  let payload;
  try {
    const asked = names.map((value) => "row=" + encodeURIComponent(value)).join("&");
    payload = await api("/api/plugins/" + encodeURIComponent(state.selected) + "/cell"
                        + "?" + asked + "&column=" + encodeURIComponent(column));
  } catch (error) {
    loading.textContent = "the history could not be read";
    return;
  }
  if (popup.hidden) return;                   // closed while it was loading

  loading.remove();
  const history = payload.history || [];
  if (!history.length) {
    const none = document.createElement("div");
    none.className = "none";
    none.textContent = "Only one result is stored, so there is nothing to compare.";
    popup.appendChild(none);
    return;
  }

  const list = document.createElement("ol");
  history.forEach((entry, index) => {
    const item = document.createElement("li");
    if (index === 0) item.className = "now";
    const when = document.createElement("span");
    when.className = "when";
    when.textContent = index === 0 ? "now" : whenExactly(entry.since);
    const value = document.createElement("span");
    value.className = "val";
    value.textContent = entry.value === "" ? "(blank)" : entry.value;
    item.append(when, value);
    list.appendChild(item);
  });
  popup.appendChild(list);
  placePopup(popup, anchor);
}

// Built by hand rather than left to the locale, because "Sep 25, 08:40 PM"
// wraps onto two lines in a column this narrow and a 24 hour clock does not.
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function whenExactly(seconds) {
  const date = new Date(seconds * 1000);
  const pad = (number) => String(number).padStart(2, "0");
  const year = date.getFullYear() === new Date().getFullYear()
    ? "" : " " + date.getFullYear();
  return `${date.getDate()} ${MONTHS[date.getMonth()]}${year} `
       + `${pad(date.getHours())}:${pad(date.getMinutes())}`;
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
      .map((entry) => entry.name)
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


/* ----------------------------------------------------------- side panel */

// The panel floats over the table rather than sitting under it, so a closed
// panel costs the grid nothing at all.
function showSide(which) {
  state.side = which;
  const open = which !== null;
  el("side").hidden = !open;
  el("log-text").hidden = which !== "log";
  el("config-body").hidden = which !== "config";
  el("side-follow").hidden = which !== "log";
  if (which === "log") {
    setFollowing(following());
    requestAnimationFrame(() => { if (following()) scrollLogToEnd(); });
  }
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
  // One Escape, one thing closed. The menu is in front, so it goes first and
  // the panel behind it stays open.
  if (event.key !== "Escape" || viewMenuOpen()) return;
  if (state.side) showSide(null);
});

// Following means the newest line stays in view while a plugin is running.
// It is on by default because a log you have opened during a run is a log you
// are watching, and it turns itself off the moment you scroll up to read
// something - which is the only reason anyone ever scrolls up in a log.
const FOLLOW_KEY = "snapgrid-follow";
const AT_BOTTOM = 24;   // px of slack, so "nearly at the bottom" counts

function following() {
  try {
    return localStorage.getItem(FOLLOW_KEY) !== "off";
  } catch (error) {
    return true;
  }
}

function setFollowing(on) {
  try {
    localStorage.setItem(FOLLOW_KEY, on ? "on" : "off");
  } catch (error) {
    /* the choice lasts for this page only, which is better than failing */
  }
  const button = el("side-follow");
  button.classList.toggle("active", on);
  button.textContent = on ? "Following" : "Follow";
  if (on) scrollLogToEnd();
}

function scrollLogToEnd() {
  const pre = el("log-text");
  pre.scrollTop = pre.scrollHeight;
}

function renderLog() {
  const detail = state.detail;
  const live = detail.live;
  const text = (live && live.log) || (detail.last_run && detail.last_run.log) || "";
  const pre = el("log-text");

  const unchanged = pre.textContent === (text || "(no log output)");
  if (!unchanged) pre.textContent = text || "(no log output)";

  el("side-follow").hidden = state.side !== "log";
  if (!unchanged && following()) scrollLogToEnd();
}

el("side-follow").addEventListener("click", () => setFollowing(!following()));

// Scrolling up is how you say "stop moving"; scrolling back to the bottom is
// how you say "carry on". Neither needs a button to be pressed.
el("log-text").addEventListener("scroll", () => {
  const pre = el("log-text");
  const atBottom = pre.scrollHeight - pre.scrollTop - pre.clientHeight <= AT_BOTTOM;
  if (atBottom !== following()) setFollowing(atBottom);
});

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

// [colour.<column>] in plugin.toml, as a class name or nothing. The rules
// themselves are tested by shadeFor, in colour.js.
function colourFor(column, value) {
  const rules = state.detail && state.detail.colours && state.detail.colours[column];
  const shade = shadeFor(rules, value);
  return shade ? "shade " + shade : "";
}

// A value that has a colour is drawn as a pill rather than as coloured text,
// which stays legible in both themes and against the banded rows.
function putValue(td, column, value) {
  const shade = colourFor(column, value);
  if (!shade) {
    td.textContent = value;
    return;
  }
  const pill = document.createElement("span");
  pill.className = shade;
  pill.textContent = value;
  // The pill clips like any other cell, so the whole value has to stay
  // reachable. On the cell itself this is only set where the cell is one line;
  // on the pill it covers a stacked one too.
  pill.title = value;
  td.appendChild(pill);
}

// "1 rows" was on every screenshot of a one-row table.
function rowCount(n) {
  return n + (n === 1 ? " row" : " rows");
}

function renderTable() {
  // A run finishing redraws the table once a second. Doing that while a column
  // is being dragged threw away the heading under the pointer and laid the
  // table out from the stored widths again, so the column sprang back to where
  // it started and the rest of the drag went to a detached element. Hold the
  // redraw until the pointer is up; a drag lasts a moment.
  if (draggingColumn) { redrawWanted = true; return; }

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
  let diff = null;
  try {
    diff = comparisonFor(snapshot);
  } catch (error) {
    diff = { impossible: "these runs cannot be lined up" };
  }
  renderDiffBar(state.depth > 1 ? (diff || { impossible: "there are no earlier runs yet" })
                                : null);
  const usable = diff && diff.rows ? diff : null;
  const ignored = (usable && usable.ignored) || new Set();
  const keys = keyIndexes(columns);
  const key = keys[0];            // where the new/gone chip hangs
  const keySet = new Set(keys);   // every column that is identity, not a value
  // What to ask the server for when a cell's own history is opened: one value
  // per key column, in the order [table] key names them.
  const keyValuesOf = (row) => keys.map((index) => cellValue(row, index));
  // Hidden columns still filter and sort - they are out of sight, not out of
  // the table - so everything below works on indexes into the full row.
  const hidden = hiddenColumns();
  const shownIndexes = columns.map((column, index) => (hidden.has(column) ? -1 : index))
                              .filter((index) => index >= 0);
  const shownColumns = shownIndexes.map((index) => columns[index]);
  let rows = visibleRows(columns, snapshot.rows, null);

  // After the filters, because what is compacted is what is on screen; before
  // the sort, because the sort then orders the rows that are left rather than
  // ordering rows that are about to be merged.
  //
  // Not while runs are being compared. A compacted row is not a row the plugin
  // printed: it has no [table] key, so there is nothing to line it up with in
  // an earlier run, and the set of merged rows can differ from run to run.
  let counts = null;
  const duplicates = usable ? 0 : duplicateCount(rows, shownIndexes);
  if (!usable && compacting() && duplicates) {
    const compacted = compactRows(rows, shownIndexes);
    rows = compacted.rows;
    counts = compacted.counts;
  }

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

  shownIndexes.forEach((columnIndex) => {
    const column = columns[columnIndex];
    const th = document.createElement("th");
    const inner = document.createElement("div");
    inner.className = "th-inner";

    const label = document.createElement("span");
    label.className = "th-label";
    label.textContent = column;
    label.addEventListener("click", () => toggleSort(column));
    // Sorting was mouse only: a heading is a span, because a button inside a
    // cell whose width is being dragged brought its own box model with it.
    // The keyboard gets at it through the span instead.
    label.tabIndex = 0;
    label.setAttribute("role", "button");
    label.setAttribute("aria-label", "Sort by " + column);
    label.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();       // Space would scroll the table instead
        toggleSort(column);
      }
    });

    const sorted = state.sort.column === column && state.sort.direction !== 0;
    th.setAttribute("aria-sort", sorted
      ? (state.sort.direction > 0 ? "ascending" : "descending") : "none");
    const mark = document.createElement("span");
    mark.className = "sort-mark";
    if (sorted) {
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
    th.appendChild(columnGrip(table, shownColumns, column, th));
    headRow.appendChild(th);
  });

  thead.appendChild(headRow);
  table.appendChild(thead);

  const tbody = document.createElement("tbody");
  // Said in place of the rows, whether there were none to begin with or none
  // of them survived. A table that empties itself and says nothing reads as a
  // page that has broken rather than as an answer.
  const sayThereAreNone = () => {
    const tr = document.createElement("tr");
    tr.className = "no-rows";
    const td = document.createElement("td");
    td.colSpan = shownIndexes.length;
    td.className = "empty-row";
    td.textContent = state.onlyChanged && usable
      ? "Nothing changed between these two results."
      : snapshot.rows.length
        ? "No rows match the current filters."
        : "The plugin returned no rows.";
    tr.appendChild(td);
    tbody.appendChild(tr);
  };

  if (!rows.length && !(usable && usable.removed)) {
    sayThereAreNone();
  } else {
    // Without a comparison this is one line per row, as it always was. With
    // one, every cell in the row holds the same number of lines, so line two
    // means "the run before" the whole way across.
    const drawRow = (row, over, kind) => {
      const tr = document.createElement("tr");
      if (kind) tr.className = kind;
      const depth = over ? over.length : 1;

      shownIndexes.forEach((index) => {
        const td = document.createElement("td");
        if (kinds[index] === "number") td.className = "num";

        if (!over) {
          const value = cellValue(row, index);
          putValue(td, columns[index], value);
          td.title = value;   // cells are clipped, so keep the full value reachable
          // At the end of the row, not the start. On the first cell it reads
          // as a count of that one value - "nginx x4" - when what it counts
          // is the whole row.
          if (counts && index === shownIndexes[shownIndexes.length - 1]) {
            const many = counts.get(row) || 1;
            if (many > 1) {
              const chip = document.createElement("span");
              chip.className = "chip many";
              chip.textContent = "\u00d7" + many;
              chip.title = `${many} rows are identical in the columns on screen`;
              td.appendChild(chip);
            }
          }
          if (index === key && kind) {
            const chip = document.createElement("span");
            chip.className = "chip " + kind;
            chip.textContent = kind === "added" ? "new" : "gone";
            td.appendChild(chip);
          }
          // A row drawn as one line while the runs are being compared is
          // still a compared row, and the history of one cell goes further
          // back than the comparison does. Before this, stacking was what
          // made a cell clickable, so the rows that stopped stacking took
          // their history with them.
          if (usable && !keySet.has(index)) {
            td.classList.add("has-history");
            td.addEventListener("click", (event) => {
              event.stopPropagation();
              openCellHistory(keyValuesOf(row), columns[index], td);
            });
          }
          tr.appendChild(td);
          return;
        }

        td.classList.add("stack");

        // A column that names the row is not a value: it says the same
        // thing in every run by definition, so it is written once. With a
        // composite key that holds for each of them.
        if (keySet.has(index)) {
          const line = document.createElement("span");
          line.className = "v now";
          line.textContent = cellValue(row, index);
          if (kind && index === key) {
            const chip = document.createElement("span");
            chip.className = "chip " + kind;
            chip.textContent = kind === "added" ? "new" : "gone";
            line.appendChild(chip);
          }
          td.appendChild(line);
          td.classList.add("name");
          tr.appendChild(td);
          return;
        }

        const values = over.map((one) => (one ? cellValue(one, index) : null));
        // Whether this value ever changed, ignoring the runs the row was not
        // in: a row arriving or leaving is a fact about the row, said once by
        // the chip and the tint, not something each of its cells repeats.
        const present = values.filter((value) => value !== null);
        const moved = !ignored.has(index)
                   && present.some((value, at) => at > 0 && value !== present[at - 1]);
        if (moved) td.classList.add("moved");

        // A cell that never moved is written once. Stacking every cell meant
        // two thirds of the table was dots saying "same as above", and the
        // rows that had actually moved were buried in it.
        if (!moved) {
          const line = document.createElement("span");
          line.className = "v now";
          putValue(line, columns[index], cellValue(row, index));
          line.addEventListener("click", (event) => {
            event.stopPropagation();
            openCellHistory(keyValuesOf(row), columns[index], td);
          });
          td.appendChild(line);
          // The guides have to cross this cell even though it has nothing to
          // write on those lines, or they stop here and the eye loses the run
          // it was following across the row.
          addGuides(td, depth - 1);
          tr.appendChild(td);
          return;
        }

        for (let at = 0; at < depth; at += 1) {
          const line = document.createElement("span");
          const value = values[at];
          if (value === null) {
            // It was not in that run at all. Said once, not on every line.
            const firstMissing = at === 0 || values[at - 1] !== null;
            line.className = "v gap";
            line.textContent = firstMissing ? (at === 0 ? "gone" : "not there") : "\u00b7";
          } else if (at > 0 && value === values[at - 1]) {
            line.className = "v same";
            line.textContent = "\u00b7";     // the same as the line above
            line.title = value;
          } else {
            line.className = at === 0 ? "v now" : "v old";
            putValue(line, columns[index], value);
          }
          line.addEventListener("click", (event) => {
            // Without this the same click reaches the document handler below
            // and closes the popup in the same tick as it opens.
            event.stopPropagation();
            openCellHistory(keyValuesOf(row), columns[index], td);
          });
          td.appendChild(line);
        }
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    };

    // How many cells of one row moved, counting only the cells on screen:
    // not the name, not a column [compare] ignore took out, and not one that
    // is hidden. It answers two questions with one walk - whether the row is
    // worth stacking at all, and what the strip above the table should count.
    const movedCellsIn = (over) => {
      let moved = 0;
      shownIndexes.forEach((index) => {
        if (keySet.has(index) || ignored.has(index)) return;
        const present = over.map((one) => (one ? cellValue(one, index) : null))
                            .filter((value) => value !== null);
        for (let at = 1; at < present.length; at += 1) {
          if (present[at] !== present[at - 1]) moved += 1;
        }
      });
      return moved;
    };

    // A row gets a line per run only when a cell on screen has more than one
    // value to show. A row that never moved was given a line per run anyway,
    // and so was one that arrived or went - where every earlier line is blank,
    // because the arrival is said once by the chip and the edge rather than by
    // each of its cells. Either way the table came out two or three times
    // taller than it needed to be, with the real changes lost in blank lines.
    const worthStacking = (over) => movedCellsIn(over) > 0;

    // What the strip above the table says, counted from the rows this draw
    // actually puts on screen rather than from the runs as a whole.
    let movedHere = 0;
    let addedHere = 0;
    let goneHere = 0;

    if (!usable) {
      for (const row of rows) drawRow(row, null, "");
    } else {
      // Walk the rows in the order the table was sorted and filtered into,
      // rather than the order the snapshot happened to store them in, so that
      // clicking a heading still does something while comparing.
      // Identical rows are separate things in whole row mode, so the first
      // one on screen takes the first entry, the second takes the second.
      const taken = new Map();
      const nameOf = (row) => {
        if (!usable.whole) return keyTextOf(row, keys);
        const text = rowTextIgnoring(row, columns, usable.ignored);
        const n = taken.get(text) || 0;
        taken.set(text, n + 1);
        return `${text}#${n}`;
      };
      for (const row of rows) {
        const entry = usable.rows.get(nameOf(row));
        if (!entry) continue;
        if (state.onlyChanged && !entry.moved) continue;
        const over = usable.whole || !worthStacking(entry.overRuns)
          ? null : entry.overRuns;
        movedHere += movedCellsIn(entry.overRuns);
        if (!entry.everBefore) addedHere += 1;
        drawRow(row, over, entry.everBefore ? "" : "added");
      }
      // The rows that have gone, after the ones that are still here. There is
      // nothing to sort them by in this result, but the filter and the search
      // still apply, on the row as it last was: a row whose environment the
      // filter took off the screen is not put back on it by disappearing.
      // That was the one place where comparing showed something the view had
      // asked not to see.
      for (const name of usable.names) {
        const entry = usable.rows.get(name);
        if (entry.here) continue;
        const newest = entry.overRuns.find((one) => one !== null);
        if (!visibleRows(columns, [newest], null).length) continue;
        const over = usable.whole || !worthStacking(entry.overRuns)
          ? null : entry.overRuns;
        goneHere += 1;
        drawRow(newest, over, "removed");
      }
      renderDiffCounts(movedHere, addedHere, goneHere);
      // Only what changed can take every row away while there are rows to
      // take: nothing moved except in a column that is not compared.
      if (!tbody.children.length) sayThereAreNone();
    }
  }
  table.appendChild(tbody);
  wrap.appendChild(table);
  applyWidths(table, shownColumns);

  const total = snapshot.rows.length;
  // While comparing, what is on screen includes rows that have gone, so the
  // count is of lines drawn rather than of rows in this result.
  const drawn = tbody.querySelectorAll("tr:not(.no-rows)").length;
  const shown = usable ? drawn : rows.length;
  const said = [shown === total ? rowCount(total) : shown + " of " + rowCount(total)];
  const missing = columns.length - shownIndexes.length;
  if (missing) said.push(`${missing} column${missing > 1 ? "s" : ""} hidden`);
  // While it is off, the count is the only thing that says there is anything
  // to compact. That is deliberate: a button nobody notices is a button that
  // does not exist, and a popup announcing itself is worse.
  if (duplicates) said.push(counts ? `${duplicates} compacted` : `${duplicates} duplicates`);
  el("row-note").textContent = said.join(" - ");
  el("btn-columns").classList.toggle("active", missing > 0);

  const compact = el("btn-compact");
  compact.disabled = Boolean(usable);
  compact.classList.toggle("active", Boolean(counts));
  compact.title = usable
    ? "Not while runs are being compared: a compacted row is not one the plugin "
      + "printed, so there is nothing to line it up with in an earlier run"
    : "Show rows that are identical in the visible columns once, with a count";
  el("btn-clear").hidden = state.filters.size === 0 && !state.search;

  // Here rather than in each of the handlers - sorting, searching, filtering,
  // clearing - because the table being redrawn is exactly what all of them
  // have in common, and one of them forgetting to say so is how an address
  // stops meaning what is on screen.
  rememberInTheAddress();
}

// Empty lines, the same height as the written ones, so a guide runs the whole
// width of the row. Not dots: a dot means "the same as the line above", and
// what these say is that the one value above them covers every run.
function addGuides(td, count) {
  for (let at = 0; at < count; at += 1) {
    const line = document.createElement("span");
    line.className = "v rule";
    line.setAttribute("aria-hidden", "true");
    td.appendChild(line);
  }
}

function toggleSort(column) {
  if (state.sort.column !== column) {
    state.sort = { column: column, direction: 1 };
  } else if (state.sort.direction === 1) {
    state.sort.direction = -1;
  } else {
    state.sort = { column: null, direction: 0 };
  }
  // Sorting rebuilds the whole table, so the heading that was just pressed is
  // a different element afterwards. Without this the keyboard lands back on
  // the body and a second press sorts nothing.
  const hadFocus = document.activeElement
                && document.activeElement.classList.contains("th-label");
  renderTable();
  if (hadFocus) {
    for (const label of document.querySelectorAll(".th-label")) {
      if (label.textContent === column) { label.focus(); break; }
    }
  }
}

/* ------------------------------------------------------------- columns */

// Widths and hidden columns are per plugin and per browser: they are about
// this screen and this table, not about the data, so they do not belong in
// plugin.toml and are not shared with anyone else looking at the same page.

function columnKey(what) {
  return `snapgrid-${what}-${state.selected || ""}`;
}

function readStored(what, fallback) {
  try {
    const raw = localStorage.getItem(columnKey(what));
    return raw ? JSON.parse(raw) : fallback;
  } catch (error) {
    return fallback;
  }
}

function writeStored(what, value) {
  try {
    localStorage.setItem(columnKey(what), JSON.stringify(value));
  } catch (error) {
    /* the choice lasts for this page only */
  }
}

// Kept where the hidden columns are kept: per plugin, in this browser, out of
// plugin.toml. It is about this screen, not about the data.
function compacting() {
  return readStored("compact", false) === true;
}

function setCompacting(on) {
  writeStored("compact", on);
  renderTable();
}

function hiddenColumns() {
  const list = readStored("hidden", []);
  return new Set(Array.isArray(list) ? list : []);
}

function setHiddenColumns(set) {
  writeStored("hidden", Array.from(set));
  renderTable();
}

// Only the widths somebody dragged. A measured one is not kept: see below.
function storedWidths() {
  const map = readStored("widths", {});
  return map && typeof map === "object" ? map : {};
}

// What the browser gives each column when nobody has said otherwise - its
// widest value, since the table is sized to its contents rather than stretched
// to the pane. Read while the table is still on the browser's own layout,
// which is how every render starts: renderTable builds a new table element
// with no class and no inline widths on it.
function measuredWidths(table, shownColumns) {
  const headings = table.querySelectorAll("thead th");
  const widths = {};
  shownColumns.forEach((column, index) => {
    if (headings[index]) {
      // Rounded up, never down. A column the browser laid out at 206.4px,
      // written back as 206, is a column one third of a pixel too narrow for
      // its own widest value - which is all it takes for the ellipsis to
      // appear on a value that was fitting a moment ago.
      widths[column] = Math.ceil(headings[index].getBoundingClientRect().width);
    }
  });
  return widths;
}

// What every column should be: measured, then overruled where somebody has
// dragged that column.
//
// Measured on each render rather than stored, which is the whole of the fix
// for a table that clipped its values with the pane half empty beside it.
// Dragging one column used to write a width for *every* column, and those
// captured widths then outlived whatever made them right: a value that grew
// longer, a window that got wider, a column hidden next to them. The table
// stayed exactly as wide as that old sum, so the values were cut off at a
// line with nothing but space to the right of it.
//
// A width nobody chose is now a measurement, good for this render only. A
// width somebody dragged is a decision, and it is kept until they drag it
// again, double-click to fit it, or reset the widths from the Columns menu -
// a column they deliberately made narrow is meant to clip.
function layoutWidths(table, shownColumns) {
  const chosen = storedWidths();
  const widths = measuredWidths(table, shownColumns);
  for (const column of shownColumns) {
    if (chosen[column]) widths[column] = chosen[column];
  }
  return widths;
}

// A table laid out from fixed widths has to be told how wide it is. Left to
// itself it comes out wider than its columns add up to, and a fixed layout
// gives that difference to the last column - which is why the last column
// could never be made narrower, and why once any slack existed, dragging any
// other column appeared to do nothing: the slack absorbed the change.
function setWidths(table, shownColumns, widths) {
  const headings = table.querySelectorAll("thead th");
  table.classList.add("fixed");
  shownColumns.forEach((column, index) => {
    if (headings[index]) headings[index].style.width = widths[column] + "px";
  });
  table.style.width = totalWidth(widths, shownColumns) + "px";
}

function applyWidths(table, shownColumns) {
  const chosen = storedWidths();
  // Nothing on screen has been dragged, so there is nothing to hold the table
  // to: the browser's own layout already gives every column its widest value.
  // Fixed layout here would only freeze what it worked out, with nothing
  // gained and the next long value cut off.
  if (!shownColumns.some((column) => chosen[column])) {
    table.classList.remove("fixed");
    table.style.width = "";
    return;
  }
  setWidths(table, shownColumns, layoutWidths(table, shownColumns));
}

// The width the table should be: its columns, with one of them replaced while
// that one is being dragged.
function totalWidth(widths, shownColumns, replacing, replacement) {
  return shownColumns.reduce(
    (total, column) => total + (column === replacing ? replacement : widths[column] || 0), 0);
}

// shownColumns, not every column: a hidden column has no heading, so anything
// matching headings by position has to count only the ones on screen.
const MIN_COLUMN = 48;   // narrower than this and a heading cannot be read

// Set while a column is being dragged, so nothing rebuilds the table underneath
// the pointer. renderTable records that it wanted to run, and runs on pointerup.
let draggingColumn = false;
let redrawWanted = false;

function columnGrip(table, shownColumns, column, th) {
  const grip = document.createElement("span");
  grip.className = "col-grip";
  grip.title = "Drag to resize. Double-click to fit";

  grip.addEventListener("pointerdown", (event) => {
    if (event.button !== 0) return;
    event.preventDefault();
    event.stopPropagation();
    // Measuring is not enough: every column has to be given its width now,
    // or the ones nobody has dragged are laid out from nothing and share
    // the table equally between them the moment fixed layout starts. These
    // are not written down - only the column about to be dragged is, and only
    // when the pointer comes up.
    const widths = layoutWidths(table, shownColumns);
    setWidths(table, shownColumns, widths);
    const startX = event.clientX;
    const startWidth = widths[column];
    grip.setPointerCapture(event.pointerId);
    document.body.classList.add("resizing");
    draggingColumn = true;

    const onMove = (moved) => {
      const width = Math.max(MIN_COLUMN, Math.round(startWidth + moved.clientX - startX));
      th.style.width = width + "px";
      // The table has to narrow and widen with the column. Without this the
      // difference becomes slack, and the slack goes to the last column.
      table.style.width = totalWidth(widths, shownColumns, column, width) + "px";
    };
    const onUp = () => {
      grip.removeEventListener("pointermove", onMove);
      grip.removeEventListener("pointerup", onUp);
      grip.removeEventListener("pointercancel", onUp);
      document.body.classList.remove("resizing");
      // This column alone. The widths the other columns were given for the
      // drag were measurements, and writing them down is what left tables
      // clipping their values with the pane half empty beside them.
      const current = storedWidths();
      current[column] = parseInt(th.style.width, 10);
      writeStored("widths", current);
      draggingColumn = false;
      if (redrawWanted) { redrawWanted = false; renderTable(); }
    };
    grip.addEventListener("pointermove", onMove);
    grip.addEventListener("pointerup", onUp);
    grip.addEventListener("pointercancel", onUp);
  });

  // Back to whatever the content needs, for one column rather than all of them.
  grip.addEventListener("dblclick", (event) => {
    event.stopPropagation();
    const current = storedWidths();
    delete current[column];
    writeStored("widths", current);
    // One column, not the table: with no width of its own it is measured
    // again on the next render, while any other column somebody dragged keeps
    // the width they gave it.
    table.style.width = "";
    renderTable();
  });

  return grip;
}

function openColumns(anchor) {
  const popup = el("filter-popup");
  const columns = (state.detail && state.detail.snapshot && state.detail.snapshot.columns) || [];
  const hidden = hiddenColumns();

  popup.textContent = "";
  popup.hidden = false;

  const list = document.createElement("div");
  list.className = "values";
  for (const column of columns) {
    const row = document.createElement("label");
    row.className = "value-row";
    const box = document.createElement("input");
    box.type = "checkbox";
    box.checked = !hidden.has(column);
    box.addEventListener("change", () => {
      // The last visible column cannot be hidden: an empty table is not a
      // view of anything, and there would be no heading left to click.
      if (!box.checked && hidden.size >= columns.length - 1) {
        box.checked = true;
        return;
      }
      if (box.checked) hidden.delete(column);
      else hidden.add(column);
      setHiddenColumns(hidden);
    });
    const text = document.createElement("span");
    text.className = "v";
    text.textContent = column;
    row.append(box, text);
    list.appendChild(row);
  }
  popup.appendChild(list);

  const foot = document.createElement("div");
  foot.className = "popup-foot";
  const all = document.createElement("button");
  all.type = "button";
  all.textContent = "Show all";
  all.addEventListener("click", () => {
    setHiddenColumns(new Set());
    closeFilter();
  });
  foot.appendChild(all);

  // Dragged widths are remembered, and until now the only way back was to
  // double-click every heading in turn - which nothing tells you. A column
  // left wide weeks ago then looks like the table is broken.
  if (Object.keys(storedWidths()).length) {
    const reset = document.createElement("button");
    reset.type = "button";
    reset.textContent = "Reset widths";
    reset.title = "Forget the column widths you have dragged, and fit each column to its contents";
    reset.addEventListener("click", () => {
      writeStored("widths", {});
      closeFilter();
      renderTable();
    });
    foot.appendChild(reset);
  }
  popup.appendChild(foot);

  el("btn-columns").setAttribute("aria-expanded", "true");
  placePopup(popup, anchor);
}

el("btn-columns").addEventListener("click", (event) => {
  event.stopPropagation();
  if (!el("filter-popup").hidden) {
    closeFilter();
    return;
  }
  openColumns(el("btn-columns"));
});

/* -------------------------------------------------------- filter popup */

function closeFilter() {
  el("btn-columns").setAttribute("aria-expanded", "false");
  const popup = el("filter-popup");
  popup.hidden = true;
  popup.textContent = "";
}

function openFilter(column, anchor) {
  // The same popup serves the Columns button, which is no longer what is in
  // it the moment a heading opens a filter in it.
  el("btn-columns").setAttribute("aria-expanded", "false");
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

  placePopup(popup, anchor);
  search.focus();
}

function placePopup(popup, anchor) {
  const box = anchor.getBoundingClientRect();
  popup.style.top = window.scrollY + box.bottom + 4 + "px";
  const left = Math.min(window.scrollX + box.left, window.scrollX + window.innerWidth - 276);
  popup.style.left = Math.max(8, left) + "px";
}

document.addEventListener("click", (event) => {
  const popup = el("filter-popup");
  if (!popup.hidden && !popup.contains(event.target)) closeFilter();
  const history = el("cell-history");
  if (!history.hidden && !history.contains(event.target)
      && !event.target.closest("td.stack")) {
    closeCellHistory();
  }
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    closeFilter();
    closeCellHistory();
  }
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
  // A run named to compare with is named relative to what is on screen. Move
  // the screen to an older result and that run may now be the newer of the
  // two, which is not a comparison anybody asked for.
  state.against = 0;
  if (state.depth > 1) state.depth = 2;
  loadDetail();
});

el("search").addEventListener("input", (event) => {
  state.search = event.target.value;
  renderTable();
});

el("compare-picker").addEventListener("change", async (event) => {
  const chosen = String(event.target.value);
  if (chosen.startsWith("at:")) {
    // A pair: this result and that one run. Two runs deep, so everything
    // downstream that asks "is the comparison on?" keeps working unchanged.
    state.against = Number(chosen.slice(3));
    state.depth = 2;
  } else {
    state.against = 0;
    state.depth = Number(chosen) || 1;
  }
  state.onlyChanged = false;
  el("diff-only-box").checked = false;
  closeCellHistory();
  rememberInTheAddress();
  await loadComparison();
  renderTable();
});

el("diff-only-box").addEventListener("change", (event) => {
  state.onlyChanged = event.target.checked;
  rememberInTheAddress();
  renderTable();
});

el("btn-compact").addEventListener("click", () => setCompacting(!compacting()));

el("btn-clear").addEventListener("click", () => {
  state.filters.clear();
  state.search = "";
  el("search").value = "";
  renderTable();
});

/* ------------------------------------- how big the text in the grid is */

// The browser's own zoom takes the whole page with it, including the panels
// that were already the right size. This is the table only.
//
// Not per plugin: how big text should be is about the eyes and the screen,
// and nobody wants to set that again for every plugin they open.
const TEXT_SIZES = [10, 11, 12, 13, 15, 17, 20];
const TEXT_KEY = "snapgrid-text";
const DEFAULT_TEXT = 13;

// What is on screen now. Browser storage seeds it once and is written to
// afterwards if it will have it - but it is never asked again. Reading the
// size back from storage on every press meant that where storage refused the
// write, the next press stepped from the old value: A+ twice gave 15px twice,
// and A- after it went to 12px. Remembering is the optional part; knowing
// what the size currently is, is not.
let currentText = DEFAULT_TEXT;

function savedTextSize() {
  let saved = null;
  try {
    saved = parseInt(localStorage.getItem(TEXT_KEY), 10);
  } catch (error) {
    saved = null;                       // private window, or storage refused
  }
  return TEXT_SIZES.includes(saved) ? saved : DEFAULT_TEXT;
}

function applyTextSize(size) {
  currentText = size;
  document.documentElement.style.setProperty("--grid-text", size + "px");
  const at = TEXT_SIZES.indexOf(size);
  el("btn-smaller").disabled = at <= 0;
  el("btn-bigger").disabled = at >= TEXT_SIZES.length - 1;
  const label = `Text in the table: ${size}px`;
  el("btn-smaller").title = at <= 0 ? "Already the smallest" : label;
  el("btn-bigger").title = at >= TEXT_SIZES.length - 1 ? "Already the biggest" : label;
  // Behind a menu now, so the two steppers no longer have the table beside
  // them to show what they did. The number says it.
  el("text-size-now").textContent = size + "px";
}

function stepTextSize(by) {
  const at = TEXT_SIZES.indexOf(currentText);
  const next = TEXT_SIZES[Math.min(TEXT_SIZES.length - 1, Math.max(0, at + by))];
  applyTextSize(next);
  try {
    localStorage.setItem(TEXT_KEY, String(next));
  } catch (error) {
    /* it still applies for this page; it just will not be remembered */
  }
}

el("btn-smaller").addEventListener("click", () => stepTextSize(-1));
el("btn-bigger").addEventListener("click", () => stepTextSize(1));
applyTextSize(savedTextSize());

/* ---------------------------------------------- the secondary menu */

// Text size, theme, Log and Config: preferences and panels rather than things
// done to this table, so they are one button at the end of the toolbar
// instead of five competing with Run now.
//
// A disclosure button, not a role=menu. What is inside is a stepper, a
// three-way switch and two toggles; claiming the menu role would promise
// arrow-key navigation these do not have, and a promise an assistive
// technology keeps on your behalf is worse than none. Tab walks it, Escape
// closes it, and the focus goes back where it came from.

function viewMenuOpen() {
  return !el("view-popup").hidden;
}

// Both corners are wrong on their own. Hung from the button's right edge it
// runs off the left of a narrow window; hung from the left edge it runs off
// the right, because once the row wraps the button is in the middle of a line
// rather than at the start of one. So it is hung from the right and then moved
// if that put it off the screen - which is the only rule that holds at every
// width.
const MENU_EDGE = 8;   // px of daylight to leave at the side of the window

function placeViewMenu() {
  const popup = el("view-popup");
  popup.style.right = "0";
  popup.style.left = "auto";
  const box = popup.getBoundingClientRect();
  if (box.left >= MENU_EDGE) return;
  const wrap = el("view-wrap").getBoundingClientRect();
  popup.style.right = "auto";
  popup.style.left = (MENU_EDGE - wrap.left) + "px";
}

function showViewMenu(open) {
  el("view-popup").hidden = !open;
  el("btn-view").setAttribute("aria-expanded", open ? "true" : "false");
  if (open) placeViewMenu();
}

el("btn-view").addEventListener("click", (event) => {
  // Without this the document handler below sees the same click and closes
  // the menu in the tick it opened.
  event.stopPropagation();
  showViewMenu(!viewMenuOpen());
});

document.addEventListener("click", (event) => {
  if (viewMenuOpen() && !el("view-wrap").contains(event.target)) showViewMenu(false);
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && viewMenuOpen()) {
    showViewMenu(false);
    el("btn-view").focus();
  }
});

// Tabbing past the last item closes it too. relatedTarget is where the focus
// is going; null means it left the page altogether, which also counts.
el("view-wrap").addEventListener("focusout", (event) => {
  if (!el("view-wrap").contains(event.relatedTarget)) showViewMenu(false);
});

// A window being dragged narrower moves the button under an open menu, so the
// menu is placed again rather than left where it was.
window.addEventListener("resize", () => {
  if (viewMenuOpen()) placeViewMenu();
});

// Log and Config open a panel over the table, so the menu has no reason to
// stay in front of it.
for (const id of ["btn-log", "btn-config"]) {
  el(id).addEventListener("click", () => showViewMenu(false));
}

/* ------------------------------------------------------------- pausing */

// Drawn rather than typed. The pause and play characters render as colour
// emoji on some systems, which is both the wrong size and the wrong colour
// next to a plugin name.
const PAUSE_ICON = '<svg viewBox="0 0 10 10" aria-hidden="true">'
                 + '<rect x="2" y="1.5" width="2.2" height="7" rx="0.6"/>'
                 + '<rect x="5.8" y="1.5" width="2.2" height="7" rx="0.6"/></svg>';
const PLAY_ICON = '<svg viewBox="0 0 10 10" aria-hidden="true">'
                + '<path d="M2.6 1.6 L8.2 5 L2.6 8.4 Z"/></svg>';

function iconButton(className, paused, label) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = className + (paused ? " on" : "");
  button.innerHTML = paused ? PLAY_ICON : PAUSE_ICON;
  button.title = label;
  button.setAttribute("aria-label", label);
  return button;
}

// What the server means by a plugin the schedule would run, said once. The
// control in front of each name used this; the one for all of them used only
// half of it, so a disabled plugin with a schedule was counted but never
// paused - and "all paused" never became true, leaving no way to resume.
function onASchedule(plugin) {
  // Either kind of schedule. Reading only `every` left a plugin with a wall
  // clock schedule out of the pause controls altogether: no button in front
  // of its name, and not counted by the one that pauses the lot.
  const scheduled = plugin.every !== null || Boolean(plugin.cron);
  return scheduled && plugin.enabled && !plugin.error;
}

function pauseButton(plugin) {
  const paused = Boolean(plugin.paused_since);
  // State first, then what pressing it would do, then the plugin it belongs
  // to - a row of identical icons is unreadable to a screen reader otherwise,
  // and "Pause" alone does not say whether it is paused already.
  const button = iconButton("pause-btn", paused, paused
    ? `Paused ${timeAgo(plugin.paused_since)}. Resume ${plugin.name}: `
      + `put it back on its schedule`
    : `On its schedule. Pause ${plugin.name}: the schedule leaves it alone, `
      + `the last result stays, and Run now still works`);
  // A toggle, and said as one, so the state is announced rather than having
  // to be read out of the label.
  button.setAttribute("aria-pressed", paused ? "true" : "false");
  button.addEventListener("click", async (event) => {
    // The row behind it opens the plugin, which is not what was clicked.
    event.stopPropagation();
    button.disabled = true;
    try {
      await api(`/api/plugins/${encodeURIComponent(plugin.id)}/`
                + (paused ? "resume" : "pause"), { method: "POST" });
      await loadPlugins();
      if (state.selected === plugin.id) await loadDetail();
    } catch (error) {
      button.disabled = false;
      showMessage(error.message, false);
    }
  });
  return button;
}

// Ten plugins on a machine with little to spare, and two of them worth running
// this fortnight. Pausing is snapgrid's own state: plugin.toml is yours and is
// never written to, so a plugins folder under git stays clean.
// The same control for the whole list, at the head of it. No confirmation:
// pausing costs nothing and the same button puts it back.
el("btn-pause-all").addEventListener("click", async () => {
  const schedulable = state.plugins.filter(onASchedule);
  const resuming = schedulable.length > 0 && schedulable.every((p) => p.paused_since);
  try {
    await api("/api/server/" + (resuming ? "resume" : "pause"), { method: "POST" });
    await loadPlugins();
    if (state.selected) await loadDetail();
  } catch (error) {
    showMessage(error.message, false);
  }
});

function renderPauseAll() {
  const schedulable = state.plugins.filter(onASchedule);
  const paused = schedulable.filter((plugin) => plugin.paused_since);
  const all = schedulable.length > 0 && paused.length === schedulable.length;

  const button = el("btn-pause-all");
  button.hidden = schedulable.length === 0;
  button.innerHTML = all ? PLAY_ICON : PAUSE_ICON;
  button.classList.toggle("on", all);
  const label = all
    ? `All ${schedulable.length} paused. Resume them: put every plugin back `
      + `on its schedule`
    : paused.length
      ? `${paused.length} of ${schedulable.length} paused. Pause the rest: `
        + `the schedule leaves them alone, and Run now still works`
      : `${schedulable.length} on their schedule. Pause all of them: the `
        + `schedule leaves them alone, and Run now still works`;
  button.title = label;
  button.setAttribute("aria-label", label);
  button.setAttribute("aria-pressed", all ? "true" : "false");

  // Said next to the plugin count rather than as a chip of its own: the foot
  // of a 260px panel has no room for a third thing.
  const note = el("server-note");
  const plugins = state.plugins.length + " plugins";
  note.textContent = paused.length ? `${plugins}, ${paused.length} paused` : plugins;
  note.classList.toggle("some-paused", paused.length > 0 && !all);
}

/* --------------------------------------------------------- stopping it */

// The terminal snapgrid was started from is usually somewhere else by the time
// you want it closed, so the page can do it. Afterwards there is nothing to go
// back to, which is why this ends on a screen saying how to start it again
// rather than on a page that quietly stops answering.
el("btn-quit").addEventListener("click", async () => {
  if (!confirm("Stop snapgrid?\n\nAny plugin part way through a run is stopped "
               + "too. Nothing stored is lost, and the page will say how to "
               + "start it again.")) return;

  const button = el("btn-quit");
  button.disabled = true;
  button.textContent = "Stopping";
  try {
    const answer = await api("/api/server/stop", { method: "POST" });
    showStopped(answer.start_again);
  } catch (error) {
    // It may well have stopped anyway and taken the reply with it. Either way
    // the page is no longer talking to anything, so say so.
    showStopped("./server.py");
  }
});

function showStopped(command) {
  el("stopped-command").textContent = command || "./server.py";
  el("stopped").hidden = false;
  // Nothing underneath is alive any more; asking it questions would only fill
  // the console with failures.
  clearInterval(pluginPoll);
  clearInterval(detailPoll);
}

/* ------------------------------------------------------------- polling */

loadPlugins();
const pluginPoll = setInterval(loadPlugins, 5000);
const detailPoll = setInterval(() => {
  if (state.detail && state.detail.live) loadDetail();
}, 1000);

/* ------------------------------------------------------------- resizing */

// Both panels are dragged by a grip on the edge between them. The width is
// kept per browser, because it is a preference about this screen rather than
// about the data, and a shared one would fight between two people.
const PANES = {
  "sidebar-grip": {
    key: "snapgrid-sidebar-width",
    variable: "--sidebar-width",
    fallback: 260, min: 160, max: 560,
    measure: (event) => event.clientX,
  },
  "side-grip": {
    key: "snapgrid-side-width",
    variable: "--side-width",
    fallback: null,                         // the stylesheet decides
    min: 260, max: 1200,
    measure: (event) => window.innerWidth - event.clientX,
  },
};

function applyWidth(pane, pixels) {
  document.documentElement.style.setProperty(pane.variable, `${Math.round(pixels)}px`);
}

function restoreWidths() {
  for (const pane of Object.values(PANES)) {
    let saved = null;
    try {
      saved = parseInt(localStorage.getItem(pane.key), 10);
    } catch (error) {
      saved = null;
    }
    if (Number.isFinite(saved) && saved >= pane.min && saved <= pane.max) {
      applyWidth(pane, saved);
    }
  }
}

function dragPane(grip, pane) {
  grip.addEventListener("pointerdown", (event) => {
    if (event.button !== 0) return;
    event.preventDefault();
    grip.setPointerCapture(event.pointerId);
    grip.classList.add("dragging");
    document.body.classList.add("resizing");

    const onMove = (moved) => {
      const width = Math.min(pane.max, Math.max(pane.min, pane.measure(moved)));
      applyWidth(pane, width);
    };
    const onUp = () => {
      grip.removeEventListener("pointermove", onMove);
      grip.removeEventListener("pointerup", onUp);
      grip.removeEventListener("pointercancel", onUp);
      grip.classList.remove("dragging");
      document.body.classList.remove("resizing");
      const current = document.documentElement.style.getPropertyValue(pane.variable);
      try {
        if (current) localStorage.setItem(pane.key, parseInt(current, 10));
      } catch (error) {
        /* the width lasts for this page only */
      }
    };
    grip.addEventListener("pointermove", onMove);
    grip.addEventListener("pointerup", onUp);
    grip.addEventListener("pointercancel", onUp);
  });

  // Back to the width it came with, for anyone who has dragged it somewhere
  // unusable and would rather not drag it back by eye.
  grip.addEventListener("dblclick", () => {
    document.documentElement.style.removeProperty(pane.variable);
    if (pane.fallback) applyWidth(pane, pane.fallback);
    try {
      localStorage.removeItem(pane.key);
    } catch (error) {
      /* nothing to forget */
    }
  });

  // The keyboard reaches it too: a grip that only answers to a mouse is not
  // usable by everyone, and arrow keys are more precise anyway.
  grip.addEventListener("keydown", (event) => {
    const step = event.shiftKey ? 40 : 10;
    const towards = event.key === "ArrowLeft" ? -1 : event.key === "ArrowRight" ? 1 : 0;
    if (!towards) return;
    event.preventDefault();
    const element = grip.id === "sidebar-grip" ? el("sidebar") : el("side");
    const sign = grip.id === "sidebar-grip" ? 1 : -1;
    const width = Math.min(pane.max,
                  Math.max(pane.min, element.getBoundingClientRect().width + towards * step * sign));
    applyWidth(pane, width);
    try {
      localStorage.setItem(pane.key, Math.round(width));
    } catch (error) {
      /* the width lasts for this page only */
    }
  });
}

restoreWidths();
for (const [id, pane] of Object.entries(PANES)) {
  const grip = el(id);
  if (grip) dragPane(grip, pane);
}

/* ------------------------------------------------- hiding the left panel */

const SIDEBAR_KEY = "snapgrid-sidebar";

function sidebarHidden() {
  try {
    return localStorage.getItem(SIDEBAR_KEY) === "hidden";
  } catch (error) {
    return false;
  }
}

function showSidebar(visible) {
  document.body.classList.toggle("no-sidebar", !visible);
  try {
    localStorage.setItem(SIDEBAR_KEY, visible ? "shown" : "hidden");
  } catch (error) {
    /* the choice lasts for this page only */
  }
}

showSidebar(!sidebarHidden());
el("sidebar-toggle").addEventListener("click", () => showSidebar(false));
el("sidebar-show").addEventListener("click", () => showSidebar(true));

// The same key hides and shows it, the way an editor does, because reaching
// for the mouse to get more room defeats the point of getting more room.
document.addEventListener("keydown", (event) => {
  const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(event.target.tagName);
  if (typing || event.metaKey || event.ctrlKey || event.altKey) return;
  if (event.key === "[") {
    event.preventDefault();
    showSidebar(document.body.classList.contains("no-sidebar"));
  }
});


el("btn-xlsx").addEventListener("click", async () => {
  try {
    await downloadTableView(el("btn-xlsx"), el("table-wrap").querySelector("table"), state.detail.id);
  } catch (error) {
    showMessage(error.message, false);
  }
});
