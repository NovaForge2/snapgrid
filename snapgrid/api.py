# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 NovaForge2
"""The HTTP server: a small JSON API plus the static web page.

Two deliberate security choices, both cheap and both easy to get wrong later:

* the server listens on 127.0.0.1, so nothing else on the network can reach it;
* anything that starts or stops a run must be a POST carrying a header that a
  web page from another site cannot add, and its Origin must match. Without
  that, any site you happened to visit could quietly tell your browser to run
  your plugins, with your credentials;
* every request must be addressed to this machine by name. A site can point
  its own hostname at 127.0.0.1 and the browser will then treat it as the same
  origin and let it read the answers - but it still sends that site's name in
  the Host header, which it cannot forge. Checking the name closes the only
  way in that listening on loopback does not already close.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import ssl
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import store as store_module
from .config import Config, display_path
from .manifest import MANIFEST_NAME
from .scheduler import interval_for

EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"
from .runner import resolve_command
from .secrets_store import PREFIX as ENCRYPTED_PREFIX, parse_env_file
from .settings import load_settings

GUARD_HEADER = "X-Snapgrid"
# The names this machine answers to. Anything else means the request was
# addressed somewhere that was made to resolve here, which is the whole trick.
LOOPBACK_NAMES = frozenset({"localhost", "127.0.0.1", "::1", "[::1]"})

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".json": "application/json; charset=utf-8",
}

PLUGIN_RUN_RE = re.compile(r"^/api/plugins/([^/]+)/run$")
PLUGIN_RUNS_RE = re.compile(r"^/api/plugins/([^/]+)/runs$")
PLUGIN_SNAPS_RE = re.compile(r"^/api/plugins/([^/]+)/snapshots$")
PLUGIN_EXPORT_RE = re.compile(r"^/api/plugins/([^/]+)/export\.csv$")
PLUGIN_CONFIG_RE = re.compile(r"^/api/plugins/([^/]+)/config$")
PLUGIN_RE = re.compile(r"^/api/plugins/([^/]+)$")
RUN_CANCEL_RE = re.compile(r"^/api/runs/(\d+)/cancel$")
RUN_RE = re.compile(r"^/api/runs/(\d+)$")
SNAPSHOT_RE = re.compile(r"^/api/snapshots/(\d+)$")


class HttpError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


class Application:
    """Turns requests into data. Kept separate from the HTTP plumbing."""

    def __init__(self, config: Config, store, registry, runner) -> None:
        self.config = config
        self.store = store
        self.registry = registry
        self.runner = runner
        self.started = time.time()

    # ----- helpers ------------------------------------------------------

    def _plugin(self, plugin_id: str):
        plugin = self.registry.get(plugin_id)
        if plugin is None:
            self.registry.scan()
            plugin = self.registry.get(plugin_id)
        if plugin is None:
            raise HttpError(404, f"no plugin called {plugin_id!r}")
        return plugin

    def _summary(self, plugin) -> dict:
        live = self.runner.live(plugin.id)
        last = self.store.last_finished_run(plugin.id)
        last_finished, failures = self.store.get_state(plugin.id)
        next_run = None
        if plugin.runnable and plugin.every is not None and last_finished:
            next_run = last_finished + interval_for(plugin.every, failures)
        status = "never"
        if plugin.error:
            status = "broken"
        elif not plugin.enabled:
            status = "disabled"
        elif live:
            status = live["status"]
        elif last:
            status = last["status"]
        return {
            "id": plugin.id,
            "name": plugin.name,
            "description": plugin.description,
            "group": plugin.group,
            "enabled": plugin.enabled,
            "error": plugin.error,
            "every": plugin.every,
            "timeout": plugin.timeout,
            "history_keep": plugin.history_keep,
            "columns": plugin.columns,
            "command": plugin.command,
            "status": status,
            "busy": bool(live),
            "last_finished": last["finished_at"] if last else None,
            "last_status": last["status"] if last else None,
            "failures": failures,
            "next_run": next_run,
            "row_count": last["row_count"] if last else None,
        }

    # ----- endpoints ----------------------------------------------------

    def _banner_id(self, text: str) -> str:
        seed = f"{int(self.started)}|{text}".encode("utf-8")
        return hashlib.sha256(seed).hexdigest()[:16]

    def list_plugins(self) -> dict:
        # Read again each time, so editing snapgrid.toml shows up without a
        # restart. It is a small file and this is not a hot path.
        settings = load_settings()
        return {
            "plugins": [self._summary(p) for p in self.registry.all()],
            "server": {
                "max_concurrent": self.config.max_concurrent,
                "plugins_dir": display_path(self.config.plugins_dir),
                "examples_dir": display_path(EXAMPLES_DIR) if EXAMPLES_DIR.is_dir() else "",
                "title": settings["title"],
                "banner": {
                    "text": settings["banner_text"],
                    "level": settings["banner_level"],
                    # Dismissing the banner hides this exact message from this
                    # server run. A new message, or a restart, brings it back.
                    "id": self._banner_id(settings["banner_text"]),
                },
            },
        }

    def plugin_detail(self, plugin_id: str, query: dict) -> dict:
        plugin = self._plugin(plugin_id)
        payload = self._summary(plugin)
        payload["live"] = self.runner.live(plugin.id)

        snapshot_id = query.get("snapshot", [None])[0]
        if snapshot_id:
            snapshot = self.store.get_snapshot(int(snapshot_id))
            if snapshot is None or snapshot["plugin_id"] != plugin.id:
                raise HttpError(404, "no such snapshot")
        else:
            snapshot = self.store.latest_snapshot(plugin.id)

        payload["snapshot"] = snapshot
        payload["snapshots"] = self.store.list_snapshots(plugin.id, limit=50)
        last = self.store.last_finished_run(plugin.id)
        if last:
            payload["last_run"] = {
                "id": last["id"],
                "status": last["status"],
                "trigger": last["trigger"],
                "started_at": last["started_at"],
                "finished_at": last["finished_at"],
                "error": last["error"],
                "log": last["log"],
                "changed": bool(last["changed"]),
            }
        else:
            payload["last_run"] = None
        return payload

    def plugin_config(self, plugin_id: str) -> dict:
        """What this plugin is configured to do, read fresh from disk.

        Values from .env are never included, only the names, so that a panel
        showing this cannot become a way to read a password. Which variables
        exist, and which of them are encrypted, is what you need when working
        out why a plugin cannot log in.
        """
        plugin = self._plugin(plugin_id)
        manifest = plugin.dir / MANIFEST_NAME
        try:
            text = manifest.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            text = f"(cannot read {MANIFEST_NAME}: {exc})"

        entries = []
        env_file = plugin.env_file
        if env_file.is_file():
            try:
                for name, value in parse_env_file(env_file.read_text(encoding="utf-8")):
                    entries.append({
                        "name": name,
                        "encrypted": value.startswith(ENCRYPTED_PREFIX),
                    })
            except OSError:
                pass

        return {
            # Relative where possible: shorter to read, and a full path carries
            # the account name of whoever is running it, which has a habit of
            # ending up in screenshots.
            "dir": display_path(plugin.dir),
            "manifest": text,
            "command": resolve_command(plugin.command) if plugin.command else [],
            "error": plugin.error,
            "env": {"present": env_file.is_file(), "entries": entries},
        }

    def plugin_runs(self, plugin_id: str) -> dict:
        plugin = self._plugin(plugin_id)
        return {"runs": self.store.list_runs(plugin.id, limit=50)}

    def plugin_snapshots(self, plugin_id: str) -> dict:
        plugin = self._plugin(plugin_id)
        return {"snapshots": self.store.list_snapshots(plugin.id, limit=50)}

    def start_run(self, plugin_id: str) -> dict:
        plugin = self._plugin(plugin_id)
        if plugin.error:
            raise HttpError(400, plugin.error)
        if not plugin.enabled:
            raise HttpError(400, "this plugin is disabled in plugin.toml")
        run_id = self.runner.submit(plugin, "manual")
        return {"run_id": run_id}

    def cancel_run(self, run_id: int) -> dict:
        return {"cancelled": self.runner.cancel(run_id)}

    def run_detail(self, run_id: int) -> dict:
        run = self.store.get_run(run_id)
        if run is None:
            raise HttpError(404, "no such run")
        live = self.runner.live(run["plugin_id"])
        if live and live["run_id"] == run_id:
            run["log"] = live.get("log") or run.get("log") or ""
            run["elapsed"] = live.get("elapsed", 0)
        return {"run": run}

    def snapshot_detail(self, snapshot_id: int) -> dict:
        snapshot = self.store.get_snapshot(snapshot_id)
        if snapshot is None:
            raise HttpError(404, "no such snapshot")
        return {"snapshot": snapshot}

    def export_csv(self, plugin_id: str, query: dict) -> tuple[bytes, str]:
        plugin = self._plugin(plugin_id)
        snapshot_id = query.get("snapshot", [None])[0]
        snapshot = (
            self.store.get_snapshot(int(snapshot_id))
            if snapshot_id
            else self.store.latest_snapshot(plugin.id)
        )
        if snapshot is None or snapshot["plugin_id"] != plugin.id:
            raise HttpError(404, "there is no result to export yet")

        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator="\n")
        writer.writerow(snapshot["columns"])
        writer.writerows(snapshot["rows"])
        stamp = time.strftime("%Y%m%d-%H%M", time.localtime(snapshot["last_seen"]))
        return buffer.getvalue().encode("utf-8"), f"{plugin.id}-{stamp}.csv"


class Handler(BaseHTTPRequestHandler):
    server_version = "snapgrid"
    # HTTP/1.1 keeps the connection open between requests. The page polls every
    # few seconds, and on 1.0 each poll opened and closed a socket, leaving a
    # trail of TIME_WAIT entries that look like something is wrong. Every
    # response here sends a Content-Length, which is what 1.1 requires.
    protocol_version = "HTTP/1.1"
    app: Application

    def log_message(self, fmt: str, *args) -> None:  # quieter than the default
        return

    # ----- plumbing -----------------------------------------------------

    def _send(self, status: int, body: bytes, content_type: str, extra: dict | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8")

    def _error(self, status: int, message: str) -> None:
        self._json({"error": message}, status=status)

    def _check_host(self) -> None:
        """Refuse a request addressed to a name that is not this machine.

        Browsers set Host from the address bar and a page cannot change it, so
        this is what tells an ordinary visit apart from a site that has pointed
        its own name here to read what it finds.
        """
        header = self.headers.get("Host")
        if header is None:
            raise HttpError(403, "the request did not say which host it was for")
        name = header.rsplit(":", 1)[0] if not header.endswith("]") else header
        if name.lower() in LOOPBACK_NAMES:
            return
        # Whatever it was told to listen on is also a name it answers to, for
        # anyone who has deliberately bound something other than loopback.
        if name == self.app.config.host:
            return
        raise HttpError(403, f"this server does not answer to {name!r}")

    def _check_guard(self) -> None:
        if self.headers.get(GUARD_HEADER) is None:
            raise HttpError(403, "missing request header")
        origin = self.headers.get("Origin")
        if origin:
            host = self.headers.get("Host", "")
            scheme = "https" if isinstance(getattr(self, "connection", None), ssl.SSLSocket) \
                     else "http"
            if origin != f"{scheme}://{host}":
                raise HttpError(403, "request came from another site")

    def _static(self, path: str) -> None:
        web_dir = self.app.config.web_dir.resolve()
        name = "index.html" if path in ("/", "") else path.lstrip("/")
        target = (web_dir / name).resolve()
        if not str(target).startswith(str(web_dir)) or not target.is_file():
            raise HttpError(404, "not found")
        suffix = target.suffix.lower()
        self._send(200, target.read_bytes(), CONTENT_TYPES.get(suffix, "application/octet-stream"))

    # ----- routing ------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path, query = parsed.path, parse_qs(parsed.query)
        try:
            self._check_host()
            if path == "/api/plugins":
                return self._json(self.app.list_plugins())

            match = PLUGIN_EXPORT_RE.match(path)
            if match:
                body, filename = self.app.export_csv(match.group(1), query)
                return self._send(
                    200, body, "text/csv; charset=utf-8",
                    {"Content-Disposition": f'attachment; filename="{filename}"'},
                )

            for pattern, method in (
                (PLUGIN_RUNS_RE, self.app.plugin_runs),
                (PLUGIN_SNAPS_RE, self.app.plugin_snapshots),
                (PLUGIN_CONFIG_RE, self.app.plugin_config),
            ):
                match = pattern.match(path)
                if match:
                    return self._json(method(match.group(1)))

            match = PLUGIN_RE.match(path)
            if match:
                return self._json(self.app.plugin_detail(match.group(1), query))

            match = RUN_RE.match(path)
            if match:
                return self._json(self.app.run_detail(int(match.group(1))))

            match = SNAPSHOT_RE.match(path)
            if match:
                return self._json(self.app.snapshot_detail(int(match.group(1))))

            if path.startswith("/api/"):
                raise HttpError(404, "no such endpoint")
            return self._static(path)
        except HttpError as exc:
            return self._error(exc.status, exc.message)
        except Exception as exc:  # never leak a stack trace to the browser
            return self._error(500, f"internal error: {exc}")

    def do_HEAD(self) -> None:  # noqa: N802
        self.do_GET()

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try:
            self._check_host()
            self._check_guard()

            match = PLUGIN_RUN_RE.match(path)
            if match:
                return self._json(self.app.start_run(match.group(1)), status=202)

            match = RUN_CANCEL_RE.match(path)
            if match:
                return self._json(self.app.cancel_run(int(match.group(1))))

            raise HttpError(404, "no such endpoint")
        except HttpError as exc:
            return self._error(exc.status, exc.message)
        except Exception as exc:
            return self._error(500, f"internal error: {exc}")


def make_server(config: Config, store, registry, runner) -> ThreadingHTTPServer:
    handler = type("BoundHandler", (Handler,), {"app": Application(config, store, registry, runner)})
    httpd = ThreadingHTTPServer((config.host, config.port), handler)
    httpd.daemon_threads = True
    return httpd
