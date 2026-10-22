// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 NovaForge2
// Capture the rendered table at click time: filtering, sorting, hidden columns,
// compacting and comparisons have already been applied by the renderer.
function tableForExport(table) {
  if (!table) throw new Error("There is no table to export yet.");
  const columns = Array.from(table.querySelectorAll("thead .th-label"), cell => cell.textContent);
  if (!columns.length) throw new Error("Show at least one column before exporting.");
  const rows = Array.from(table.querySelectorAll("tbody tr"))
    .filter(row => !row.querySelector(".empty-row"))
    .map(row => Array.from(row.querySelectorAll("td"), cell => {
      const lines = cell.querySelectorAll(".v:not(.rule)");
      return lines.length
        ? Array.from(lines, cellText).join("\n")
        : cellText(cell);
    }));
  return { columns, rows };
}

// A chip - the x4 of a compacted row, the NEW or GONE of a compared one - is
// held off the value by a margin on screen, and a margin is not text. Without
// a space put back it exports as `nginx\u00d74`, which reads as a program
// called that and sorts next to nothing.
function cellText(node) {
  const children = node.childNodes;
  if (!children || typeof children.length !== "number") return node.innerText;
  let out = "";
  for (let at = 0; at < children.length; at += 1) {
    const child = children[at];
    const chip = child.nodeType === 1 && child.classList
              && child.classList.contains("chip");
    if (chip && out && !out.endsWith(" ")) out += " ";
    out += child.textContent === undefined ? "" : child.textContent;
  }
  return out.trim() || node.innerText || "";
}


async function downloadTableView(button, table, pluginId) {
  // Capture before awaiting the network, so a scheduled refresh cannot change
  // which rows this particular download contains.
  const view = tableForExport(table);
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 30000);
  button.disabled = true;
  try {
    const response = await fetch("/api/plugins/" + encodeURIComponent(pluginId) + "/export.xlsx", {
      method: "POST", signal: controller.signal,
      headers: { "X-Snapgrid": "1", "Content-Type": "application/json" },
      body: JSON.stringify(view),
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.error || "Excel export failed (" + response.status + ")");
    }
    const url = URL.createObjectURL(await response.blob());
    const link = document.createElement("a");
    link.href = url;
    link.download = pluginId + "-view.xlsx";
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 60000);
  } finally {
    clearTimeout(timeout);
    button.disabled = false;
  }
}
