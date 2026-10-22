# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 NovaForge2
import json
import urllib.request
import urllib.error
from pathlib import Path
from tests.test_api import ApiTest
from snapgrid_core.spreadsheet import read_xlsx


class ExportView(ApiTest):
    def post(self, payload, guard=True):
        headers = {'Content-Type': 'application/json'}
        if guard:
            headers['X-Snapgrid'] = '1'
        request = urllib.request.Request(self.base + '/api/plugins/demo/export.xlsx',
            data=json.dumps(payload).encode(), headers=headers, method='POST')
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.read()

    def test_visible_subset_and_order_are_preserved_when_latest_changes(self):
        self.store.save_snapshot('demo', ['a','hidden','b'], [['1','secret','2'],['x','secret','3']], 5)
        visible = {'columns':['b','a'], 'rows':[['3','x']]}
        self.store.save_snapshot('demo', ['new'], [['unrelated']], 5)
        status, body = self.post(visible)
        self.assertEqual(status, 200)
        output = Path(self.tmp.name) / 'view.xlsx'
        output.write_bytes(body)
        self.assertEqual(read_xlsx(output), [['b','a'],['3','x']])

    def test_empty_filtered_result_retains_only_headers(self):
        status, body = self.post({'columns':['a'], 'rows':[]})
        self.assertEqual(status, 200)
        output = Path(self.tmp.name) / 'view.xlsx'
        output.write_bytes(body)
        self.assertEqual(read_xlsx(output), [['a']])

    def test_comparison_lines_counts_and_formula_text_survive(self):
        rows = [['a ×2', '2.0\n·\n1.10'], ['b gone', '=1+1']]
        status, body = self.post({'columns':['name','value'], 'rows':rows})
        self.assertEqual(status, 200)
        output = Path(self.tmp.name) / 'view.xlsx'
        output.write_bytes(body)
        self.assertEqual(read_xlsx(output), [['name','value']] + rows)

    def test_invalid_shapes_are_rejected(self):
        for payload in [None, {}, {'columns':[], 'rows':[]},
                        {'columns':['a'], 'rows':[['x','y']]},
                        {'columns':['a'], 'rows':[[None]]},
                        {'columns':['a'], 'rows':[['x'*32768]]}]:
            self.assertEqual(self.post(payload)[0], 400)

    def test_guard_is_required(self):
        self.assertEqual(self.post({'columns':['a'], 'rows':[]}, guard=False)[0], 403)
