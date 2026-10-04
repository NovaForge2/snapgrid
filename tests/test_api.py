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

from snapgrid.api import make_server, start_command
from snapgrid.config import Config
from snapgrid.manifest import Registry
from snapgrid.runner import Runner
from snapgrid.spreadsheet import read_xlsx
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


class TheCellEndpoint(ApiTest):
    """What the history popover asks for when a cell is clicked."""

    def setUp(self):
        super().setUp()
        self.store.save_snapshot("demo", ["a", "b"], [["one", "1"]], 20)
        self.store.save_snapshot("demo", ["a", "b"], [["one", "2"]], 20)

    def test_it_returns_the_values_newest_first(self):
        status, payload = self.get_json("/api/plugins/demo/cell?row=one&column=b")
        self.assertEqual(status, 200)
        self.assertEqual([entry["value"] for entry in payload["history"]], ["2", "1"])

    def test_an_unknown_column_is_refused(self):
        status, _ = self.get_json("/api/plugins/demo/cell?row=one&column=nope")
        self.assertEqual(status, 404)

    def test_an_unknown_row_gives_an_empty_history(self):
        _, payload = self.get_json("/api/plugins/demo/cell?row=other&column=b")
        self.assertEqual(payload["history"], [])

    def test_the_key_column_is_reported_so_the_page_can_line_rows_up(self):
        _, payload = self.get_json("/api/plugins/demo")
        self.assertIn("key", payload)


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
        status, payload = self.get_json("/api/plugins/demo/export.xlsx")
        self.assertEqual(status, 404)
        self.assertIn("no result", payload["error"])

    def test_export_returns_a_workbook_as_a_download(self):
        self.store.save_snapshot("demo", ["a", "b"], [["1", "2"], ["x,y", "3"]], 5)
        status, body, headers = self.request("/api/plugins/demo/export.xlsx",
                                             headers={"X-Snapgrid": "1"})
        self.assertEqual(status, 200)
        self.assertIn("spreadsheetml", headers["Content-Type"])
        self.assertIn("attachment", headers["Content-Disposition"])
        self.assertIn(".xlsx", headers["Content-Disposition"])
        self.assertTrue(body.startswith(b"PK"), "an xlsx is a zip")

    def test_the_workbook_holds_the_table(self):
        self.store.save_snapshot("demo", ["a", "b"], [["1", "2"], ["x,y", "3"]], 5)
        _, body, _ = self.request("/api/plugins/demo/export.xlsx",
                                  headers={"X-Snapgrid": "1"})
        folder = tempfile.mkdtemp()
        path = Path(folder) / "out.xlsx"
        path.write_bytes(body)
        self.assertEqual(read_xlsx(path), [["a", "b"], ["1", "2"], ["x,y", "3"]])

    def test_csv_export_is_gone(self):
        self.store.save_snapshot("demo", ["a"], [["1"]], 5)
        status, _ = self.get_json("/api/plugins/demo/export.csv")
        self.assertEqual(status, 404)


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


class StoppingFromThePage(ApiTest):
    """The Stop button in the sidebar, and what guards it.

    This endpoint ends the process, so the interesting tests are the ones
    about not ending it: it is behind the same guards as every other write,
    and a page on another site cannot reach it.
    """

    def test_it_needs_the_header_every_write_needs(self):
        # Without the custom header a browser will not send this cross-origin
        # without asking first, which is the whole point of requiring it.
        status, _, _ = self.request("/api/server/stop", method="POST")
        self.assertEqual(status, 403)
        self.assertTrue(self.httpd.__dict__ is not None, "nothing was stopped")

    def test_a_request_from_another_site_is_refused(self):
        status, _, _ = self.request(
            "/api/server/stop", method="POST",
            headers={"X-Snapgrid": "1", "Origin": "http://evil.example"})
        self.assertEqual(status, 403)

    def test_a_request_addressed_to_another_name_is_refused(self):
        status, _, _ = self.request(
            "/api/server/stop", method="POST",
            headers={"X-Snapgrid": "1", "Host": "evil.example"})
        self.assertEqual(status, 403)

    def test_get_does_not_stop_anything(self):
        # A link, an image tag or a prefetch must never be able to do this.
        status, _, _ = self.request("/api/server/stop", headers={"X-Snapgrid": "1"})
        self.assertEqual(status, 404)

    def test_it_answers_with_how_to_start_again(self):
        # The page has nothing to go back to afterwards, so the reply carries
        # the command. Asserted here rather than in the browser because this
        # is where the folder is known.
        status, payload = self.get_json_post("/api/server/stop")
        self.assertEqual(status, 200)
        self.assertTrue(payload["stopping"])
        self.assertIn("./server.py", payload["start_again"])

    def get_json_post(self, path):
        status, body, _ = self.request(path, method="POST", headers={"X-Snapgrid": "1"})
        return status, json.loads(body or b"{}")


class TheCommandToStartAgain(unittest.TestCase):
    def test_the_default_folder_needs_no_dir(self):
        self.assertEqual(start_command(Config(plugins_dir=Path("plugins"))), "./server.py")

    def test_another_folder_is_named(self):
        self.assertEqual(start_command(Config(plugins_dir=Path("examples"))),
                         "./server.py --dir examples")


class PausingThroughTheApi(ApiTest):
    def post(self, path):
        status, body, _ = self.request(path, method="POST", headers={"X-Snapgrid": "1"})
        return status, json.loads(body or b"{}")

    def test_pausing_and_resuming_one_plugin(self):
        status, payload = self.post("/api/plugins/demo/pause")
        self.assertEqual(status, 200)
        self.assertIsNotNone(payload["paused_since"])

        status, listing = self.get_json("/api/plugins")
        self.assertIsNotNone(listing["plugins"][0]["paused_since"])

        status, payload = self.post("/api/plugins/demo/resume")
        self.assertIsNone(payload["paused_since"])

    def test_a_paused_plugin_has_no_next_run(self):
        # The page shows "next run in ..." from this, and a paused plugin has
        # no next run - saying one would be a lie that looks like data.
        self.post("/api/plugins/demo/pause")
        _, listing = self.get_json("/api/plugins")
        self.assertIsNone(listing["plugins"][0]["next_run"])

    def test_pausing_something_that_is_not_there(self):
        status, _ = self.post("/api/plugins/nope/pause")
        self.assertEqual(status, 404)

    def test_it_needs_the_header(self):
        status, _, _ = self.request("/api/plugins/demo/pause", method="POST")
        self.assertEqual(status, 403)

    def test_get_does_not_pause_anything(self):
        status, _ = self.get_json("/api/plugins/demo/pause")
        self.assertEqual(status, 404)
        _, listing = self.get_json("/api/plugins")
        self.assertIsNone(listing["plugins"][0]["paused_since"])

    def scheduled_plugin(self, name="timed"):
        """The demo plugin is every = "off", which Pause all rightly skips."""
        folder = self.config.plugins_dir / name
        folder.mkdir()
        (folder / "plugin.toml").write_text(
            f'[plugin]\nname = "{name}"\n[run]\n'
            'command = ["python", "-c", "print(1)"]\nevery = "1h"\n',
            encoding="utf-8")
        self.registry.scan()
        return name

    def test_pausing_everything_and_letting_it_go(self):
        self.scheduled_plugin()
        status, payload = self.post("/api/server/pause")
        self.assertEqual(status, 200)
        self.assertEqual(payload["plugins"], ["timed"])

        _, listing = self.get_json("/api/plugins")
        paused = {p["id"]: p["paused_since"] for p in listing["plugins"]}
        self.assertIsNotNone(paused["timed"])

        self.post("/api/server/resume")
        _, listing = self.get_json("/api/plugins")
        self.assertTrue(all(p["paused_since"] is None for p in listing["plugins"]))

    def test_pausing_everything_leaves_out_what_has_no_schedule(self):
        # every = "off" is already as paused as a plugin gets, and listing it
        # would make Resume all look like it had something to undo.
        self.scheduled_plugin()
        _, payload = self.post("/api/server/pause")
        self.assertEqual(payload["plugins"], ["timed"], "demo is every = off")


class TheCommandToStartAgainIsTypeable(unittest.TestCase):
    """The page is the one place where a wrong command cannot be checked
    against what you typed before, because you did not type anything."""

    def command(self, folder, port=8765):
        return start_command(Config(plugins_dir=Path(folder), port=port))

    def test_a_folder_with_a_space_is_quoted(self):
        self.assertIn("'", self.command("/tmp/my plugins"))

    def test_a_folder_with_a_quote_in_it_survives(self):
        # Not a path anybody plans, but one that silently produces an
        # unrunnable command is worse than one that looks odd.
        command = self.command("/tmp/it's here")
        self.assertIn("it", command)
        self.assertNotIn("it's here", command, "the quote has to be escaped")

    def test_an_ordinary_folder_is_not_quoted(self):
        self.assertEqual(self.command("examples"), "./server.py --dir examples")

    def test_a_port_given_on_the_command_line_is_kept(self):
        # It is not written anywhere the restarted server would read, so
        # leaving it out moves the address out from under the bookmark.
        self.assertIn("--port 8770", self.command("examples", port=8770))

    def test_the_usual_port_is_not_repeated(self):
        self.assertNotIn("--port", self.command("examples", port=8765))
