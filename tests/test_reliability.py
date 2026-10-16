# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 NovaForge2
import csv
from unittest.mock import patch

from tests.test_running import RunningPlugins


class Reliability(RunningPlugins):
    def test_long_csv_field_fails_without_losing_a_worker(self):
        plugin = self.make_plugin('long', f'print("name")\nprint("x" * {csv.field_size_limit() + 1})')
        run = self.run_now(plugin)
        self.assertEqual(run['status'], 'failed')
        self.assertIn('CSV', run['error'])
        self.assertTrue(all(worker.is_alive() for worker in self.runner._workers))
        good = self.make_plugin('good', 'print("name\\nvalue")')
        self.assertEqual(self.run_now(good)['status'], 'ok')

    def test_unexpected_parser_error_does_not_kill_worker(self):
        plugin = self.make_plugin('unexpected', 'print("name\\nvalue")')
        with patch('snapgrid_core.runner.parse_table', side_effect=RuntimeError('parser broke')):
            run = self.run_now(plugin)
        self.assertEqual(run['status'], 'failed')
        self.assertIn('parser broke', run['error'])
        self.assertTrue(all(worker.is_alive() for worker in self.runner._workers))
        self.assertEqual(self.run_now(plugin)['status'], 'ok')

    def test_cached_and_file_only_results_do_not_need_an_encryption_key(self):
        value = 'enc:opaque-test-value'
        for name, file_only in [('cached', False), ('fileonly', True)]:
            plugin = self.make_plugin(name, 'raise RuntimeError("must not execute")',
                manifest_extra='[output]\nfile="table.csv"\nfresh_for="1h"\n',
                env='TOKEN=' + value)
            (plugin.dir / 'table.csv').write_text('name,value\na,' + value + '\n')
            if file_only:
                manifest = plugin.dir / 'plugin.toml'
                manifest.write_text('[output]\nfile="table.csv"\n')
            rid = self.runner.submit(plugin, 'schedule')
            run = self.wait_for(rid)
            self.assertEqual(run['status'], 'ok', run['error'])
            snapshot = self.store.get_snapshot(run['snapshot_id'])
            self.assertEqual(snapshot['rows'][0][1], value)

    def test_header_validation_is_independent_of_opaque_env_values(self):
        plugin = self.make_plugin('header', 'print("unexpected")',
            manifest_extra='[table]\ncolumns=["expected"]\n',
            env='TOKEN=enc:not-base64')
        run = self.run_now(plugin)
        self.assertEqual(run['status'], 'failed')
        self.assertIn('header line does not match', run['error'])

    def test_cached_and_failed_runs_are_pruned(self):
        cached = self.make_plugin('cached', 'pass', manifest_extra='[output]\nfile="table.csv"\nfresh_for="1h"\n')
        (cached.dir / 'table.csv').write_text('name\na\n')
        failed = self.make_plugin('failed', 'raise SystemExit(1)')
        with patch('snapgrid_core.store.RUNS_KEPT_PER_PLUGIN', 3):
            for plugin in (cached, failed):
                for _ in range(5):
                    self.wait_for(self.runner.submit(plugin, 'schedule'))
                self.assertEqual(len(self.store.list_runs(plugin.id)), 3)
            queued = self.store.create_run('failed', 'manual')
            self.run_now(failed)
            self.assertEqual(self.store.get_run(queued)['status'], 'queued')

    def test_output_overflow_fails_without_waiting_for_timeout(self):
        plugin = self.make_plugin('overflow', 'import sys, time\nsys.stdout.write("x" * 100000)\nsys.stdout.flush()\ntime.sleep(10)', timeout=5)
        with patch('snapgrid_core.runner.MAX_OUTPUT_BYTES', 1024):
            run = self.run_now(plugin, seconds=3)
        self.assertEqual(run['status'], 'failed')
        self.assertIn('32 MB', run['error'])

    def test_file_only_and_cached_files_obey_byte_limit(self):
        for name, cached in [('fileonly', False), ('cached', True)]:
            plugin = self.make_plugin(name, 'pass', manifest_extra='[output]\nfile="table.csv"\nfresh_for="1h"\n')
            if not cached:
                (plugin.dir / 'plugin.toml').write_text('[output]\nfile="table.csv"\n')
            (plugin.dir / 'table.csv').write_text('name\n' + 'x' * 2000)
            with patch('snapgrid_core.runner.MAX_OUTPUT_BYTES', 1024):
                run = self.wait_for(self.runner.submit(plugin, 'schedule'))
            self.assertEqual(run['status'], 'failed')
            self.assertIn('32 MB', run['error'])

    def test_long_stderr_line_is_still_bounded(self):
        plugin = self.make_plugin('noisy',
            'import sys\nprint("name\\nvalue")\nprint("x"*100000, file=sys.stderr)',
            env='TOKEN=enc:opaque')
        run = self.run_now(plugin)
        self.assertEqual(run['status'], 'ok', run['error'])
        self.assertEqual(run['log'], '[log truncated]')
