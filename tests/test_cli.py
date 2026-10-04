# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 NovaForge2
"""Finding the running server from the command line.

The state file lives inside the plugins folder, so `./server.py stop` typed
without the `--dir` that `start` was given used to look in the wrong place and
report nothing running while the server carried on serving. A stop that says
"not running" and does not stop anything is worse than an error, because it is
believed. The port is the one thing both commands agree on, so it is the
fallback - and these are the tests for it.
"""

import unittest
from unittest import mock

from snapgrid import __main__ as cli
from snapgrid.config import Config


def config_for(tmp) -> Config:
    return Config(plugins_dir=tmp, host="127.0.0.1", port=8765)


class FoundByPort(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path
        self.tmp = tempfile.TemporaryDirectory()
        self.config = config_for(Path(self.tmp.name))
        self.addCleanup(self.tmp.cleanup)

    def test_nothing_on_the_port_is_nothing_running(self):
        with mock.patch.object(cli, "snapgrid_on_port", return_value=None):
            self.assertIsNone(cli.found_by_port(self.config))

    def test_something_that_is_not_snapgrid_is_not_ours_to_stop(self):
        # snapgrid_on_port returns None for anything that does not answer the
        # way snapgrid does, so a stray web server on 8765 is never killed.
        with mock.patch.object(cli, "snapgrid_on_port", return_value=None), \
             mock.patch.object(cli, "pid_listening_on", return_value=4242):
            self.assertIsNone(cli.found_by_port(self.config))

    def test_a_snapgrid_with_no_findable_pid_is_not_reported(self):
        # Nothing could be stopped, so claiming it is running would only lead
        # to a stop that silently does nothing.
        with mock.patch.object(cli, "snapgrid_on_port", return_value={}), \
             mock.patch.object(cli, "pid_listening_on", return_value=None):
            self.assertIsNone(cli.found_by_port(self.config))

    def test_a_snapgrid_from_another_folder_is_found_and_says_so(self):
        with mock.patch.object(cli, "snapgrid_on_port",
                               return_value={"plugins_dir": "examples"}), \
             mock.patch.object(cli, "pid_listening_on", return_value=4242):
            found = cli.found_by_port(self.config)
        self.assertEqual(found["pid"], 4242)
        self.assertEqual(found["port"], 8765)
        self.assertEqual(found["url"], "http://127.0.0.1:8765")
        self.assertEqual(found["plugins_dir"], "examples")
        self.assertTrue(found["elsewhere"], "the caller has to know it is not this config's")

    def test_it_is_shaped_like_the_state_file(self):
        # command_stop reads pid and port off whichever of the two it got.
        with mock.patch.object(cli, "snapgrid_on_port", return_value={}), \
             mock.patch.object(cli, "pid_listening_on", return_value=1):
            found = cli.found_by_port(self.config)
        for key in ("pid", "port", "url", "started"):
            self.assertIn(key, found)


class LooksLikeSnapgrid(unittest.TestCase):
    def test_it_agrees_with_what_answered(self):
        with mock.patch.object(cli, "snapgrid_on_port", return_value={}):
            self.assertTrue(cli.looks_like_snapgrid("127.0.0.1", 8765))
        with mock.patch.object(cli, "snapgrid_on_port", return_value=None):
            self.assertFalse(cli.looks_like_snapgrid("127.0.0.1", 8765))


class WhichProcessHoldsThePort(unittest.TestCase):
    """Two processes can listen on one port, on different addresses.

    Answering on 127.0.0.1 says nothing about which of them the operating
    system lists first, so picking the first would sometimes stop a stranger
    and leave snapgrid running - while reporting success.
    """

    def test_the_one_on_our_address_is_chosen(self):
        with mock.patch.object(cli, "listeners_on",
                               return_value=[(10, "192.168.1.5:8765"),
                                             (11, "127.0.0.1:8765")]):
            self.assertEqual(cli.pid_listening_on(8765, "127.0.0.1"), 11)

    def test_nothing_on_our_address_is_nothing(self):
        with mock.patch.object(cli, "listeners_on",
                               return_value=[(10, "192.168.1.5:8765")]):
            self.assertIsNone(cli.pid_listening_on(8765, "127.0.0.1"))

    def test_two_that_cannot_be_told_apart_are_left_alone(self):
        with mock.patch.object(cli, "listeners_on",
                               return_value=[(10, "127.0.0.1:8765"),
                                             (11, "*:8765")]):
            self.assertIsNone(cli.pid_listening_on(8765, "127.0.0.1"),
                              "doing nothing beats stopping the wrong one")

    def test_a_wildcard_listener_is_the_one_answering(self):
        with mock.patch.object(cli, "listeners_on", return_value=[(10, "0.0.0.0:8765")]):
            self.assertEqual(cli.pid_listening_on(8765, "127.0.0.1"), 10)

    def test_addresses(self):
        for address, host, expected in (
            ("127.0.0.1:8765", "127.0.0.1", True),
            ("192.168.1.5:8765", "127.0.0.1", False),
            ("*:8765", "127.0.0.1", True),
            ("[::1]:8765", "::1", True),
            ("[::]:8765", "::1", True),
        ):
            self.assertIs(cli.address_matches(address, host), expected, address)
