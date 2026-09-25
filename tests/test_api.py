# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 NovaForge2
"""The HTTP layer, against a real server on a real socket."""

import json
import socket
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from snapgrid.api import make_server
from snapgrid.config import Config
from snapgrid.manifest import Registry
from snapgrid.runner import Runner
from snapgrid.store import Store


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class ApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config = Config(plugins_dir=Path(self.tmp.name) / "plugins", port=free_port())
        self.config.prepare()

        folder = self.config.plugins_dir / "demo"
        folder.mkdir(parents=True)
        (folder / "plugin.toml").write_text(
            '[plugin]\nname = "Demo"\ngroup = "Tests"\n'
            '[run]\ncommand = ["python", "main.py"]\nevery = "off"\n',
            encoding="utf-8",
        )
        (folder / "main.py").write_text('print("a,b")\nprint("1,2")\n', encoding="utf-8")
        (folder / ".env").write_text("TOKEN=super-secret-value\n", encoding="utf-8")

        self.store = Store(self.config.db_path)
        self.addCleanup(self.store.close)
        self.registry = Registry(self.config.plugins_dir)
        self.registry.scan()
        self.runner = Runner(self.store, self.registry, self.config)
        self.addCleanup(self.runner.stop)
        self.httpd = make_server(self.config, self.store, self.registry, self.runner)
        self.addCleanup(self.httpd.server_close)
        # A short poll interval: the default makes every shutdown wait half a
        # second, which turns this file into an eight second test run.
        threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.02},
                         daemon=True).start()
        self.addCleanup(self.httpd.shutdown)
        self.base = f"http://127.0.0.1:{self.config.port}"

    def request(self, path, method="GET", headers=None):
        request = urllib.request.Request(self.base + path, method=method,
                                         headers=headers or {})
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, response.read(), dict(response.headers)
        except urllib.error.HTTPError as error:
            return error.code, error.read(), dict(error.headers)

    def get_json(self, path, headers=None):
        status, body, _ = self.request(path, headers={"X-Snapgrid": "1", **(headers or {})})
        return status, json.loads(body or b"{}")


class AddressedToThisMachine(ApiTest):
    """DNS rebinding, which is the only way in that loopback does not close.

    A site can point its own name at 127.0.0.1, and the browser will then
    treat it as the same origin and hand it whatever it reads. What the site
    cannot do is change the Host header, so that is what is checked.
    """

    def test_an_ordinary_request_is_allowed(self):
        status, _ = self.get_json("/api/plugins")
        self.assertEqual(status, 200)

    def test_a_request_addressed_elsewhere_is_refused(self):
        status, payload = self.get_json("/api/plugins", headers={"Host": "evil.example"})
        self.assertEqual(status, 403)
        self.assertIn("does not answer to", payload["error"])

    def test_the_page_itself_is_refused_too(self):
        # Not just the API: the page is what would be loaded and read.
        status, _, _ = self.request("/", headers={"Host": "evil.example"})
        self.assertEqual(status, 403)

    def test_localhost_by_name_is_allowed(self):
        status, _ = self.get_json("/api/plugins",
                                  headers={"Host": f"localhost:{self.config.port}"})
        self.assertEqual(status, 200)

    def test_starting_a_run_from_elsewhere_is_refused(self):
        status, _, _ = self.request("/api/plugins/demo/run", method="POST",
                                    headers={"X-Snapgrid": "1", "Host": "evil.example"})
        self.assertEqual(status, 403)


class Throttling(ApiTest):
    """What the page needs in order to say why nothing is happening."""

    def test_a_healthy_plugin_reports_no_failures(self):
        _, payload = self.get_json("/api/plugins/demo")
        self.assertEqual(payload["failures"], 0)

    def test_failures_and_the_next_attempt_are_reported(self):
        # every = "off" in this plugin, so give it a schedule to be held off.
        folder = self.config.plugins_dir / "demo"
        (folder / "plugin.toml").write_text(
            '[plugin]\nname = "Demo"\n[run]\ncommand = ["python", "main.py"]\nevery = "15m"\n',
            encoding="utf-8",
        )
        self.registry.scan()
        for _ in range(4):
            run_id = self.store.create_run("demo", "schedule")
            self.store.finish_run(run_id, "demo", "failed", error="no")

        _, payload = self.get_json("/api/plugins/demo")
        self.assertEqual(payload["failures"], 4)
        # Four failures means an hour, not the fifteen minutes it asked for.
        last_finished, _ = self.store.get_state("demo")
        self.assertAlmostEqual(payload["next_run"] - last_finished, 3600, delta=1)


class Reading(ApiTest):
    def test_the_plugin_list(self):
        status, payload = self.get_json("/api/plugins")
        self.assertEqual(status, 200)
        self.assertEqual([p["id"] for p in payload["plugins"]], ["demo"])
        self.assertEqual(payload["plugins"][0]["group"], "Tests")
        self.assertIn("title", payload["server"])

    def test_a_plugin_that_does_not_exist(self):
        status, payload = self.get_json("/api/plugins/nope")
        self.assertEqual(status, 404)
        self.assertIn("no plugin", payload["error"])

    def test_an_endpoint_that_does_not_exist(self):
        self.assertEqual(self.get_json("/api/nothing")[0], 404)

    def test_the_page_itself_is_served(self):
        status, body, headers = self.request("/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers["Content-Type"])
        self.assertIn(b"snapgrid", body)

    def test_the_script_and_stylesheet_are_served_with_their_types(self):
        for path, expected in [("/app.js", "javascript"), ("/style.css", "css")]:
            status, _, headers = self.request(path)
            self.assertEqual(status, 200, path)
            self.assertIn(expected, headers["Content-Type"], path)

    def test_export_before_anything_has_run(self):
        status, payload = self.get_json("/api/plugins/demo/export.csv")
        self.assertEqual(status, 404)
        self.assertIn("no result", payload["error"])

    def test_export_returns_the_table_as_a_download(self):
        self.store.save_snapshot("demo", ["a", "b"], [["1", "2"], ["x,y", "3"]], 5)
        status, body, headers = self.request("/api/plugins/demo/export.csv",
                                             headers={"X-Snapgrid": "1"})
        self.assertEqual(status, 200)
        self.assertIn("text/csv", headers["Content-Type"])
        self.assertIn("attachment", headers["Content-Disposition"])
        self.assertEqual(body.decode(), 'a,b\n1,2\n"x,y",3\n')


class Config_(ApiTest):
    def test_the_config_panel_shows_the_manifest_and_the_real_command(self):
        status, payload = self.get_json("/api/plugins/demo/config")
        self.assertEqual(status, 200)
        self.assertIn("[plugin]", payload["manifest"])
        self.assertTrue(payload["command"][0].endswith(("python", "python.exe", "python3",
                                                        "python3.exe")))

    def test_it_lists_env_names_but_never_their_values(self):
        _, payload = self.get_json("/api/plugins/demo/config")
        self.assertEqual([e["name"] for e in payload["env"]["entries"]], ["TOKEN"])
        self.assertNotIn("super-secret-value", json.dumps(payload))


class Guarding(ApiTest):
    """Anything that starts work has to prove it did not come from another site."""

    def test_starting_a_run_without_the_header_is_refused(self):
        status, body, _ = self.request("/api/plugins/demo/run", method="POST")
        self.assertEqual(status, 403)
        self.assertIn(b"header", body)

    def test_a_request_from_another_site_is_refused(self):
        status, _, _ = self.request(
            "/api/plugins/demo/run", method="POST",
            headers={"X-Snapgrid": "1", "Origin": "http://evil.example"},
        )
        self.assertEqual(status, 403)

    def test_a_request_from_the_page_itself_is_allowed(self):
        status, _, _ = self.request(
            "/api/plugins/demo/run", method="POST",
            headers={"X-Snapgrid": "1", "Origin": f"http://127.0.0.1:{self.config.port}"},
        )
        self.assertEqual(status, 202)

    def test_starting_a_run_with_the_header_is_allowed(self):
        status, payload = self.get_json("/api/plugins/demo/run")   # GET, wrong method
        self.assertEqual(status, 404)
        status, body, _ = self.request("/api/plugins/demo/run", method="POST",
                                       headers={"X-Snapgrid": "1"})
        self.assertEqual(status, 202)
        self.assertIn(b"run_id", body)


class NotEscapingTheWebFolder(ApiTest):
    def test_paths_that_climb_out_are_refused(self):
        for path in ["/../snapgrid/store.py", "/..%2fsnapgrid/store.py",
                     "/../../etc/passwd", "/%2e%2e/%2e%2e/etc/passwd"]:
            status, _, _ = self.request(path)
            self.assertIn(status, (400, 404), path)

    def test_a_file_that_is_not_there(self):
        self.assertEqual(self.request("/nothing.js")[0], 404)


if __name__ == "__main__":
    unittest.main()
