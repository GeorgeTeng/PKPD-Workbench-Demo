"""Behavior checks for the integrated demo, using an isolated review state."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import app
from fastapi.testclient import TestClient


class DemoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='pkpd-demo-tests-')
        cls.state = Path(cls.temp.name)
        cls.client = TestClient(app.create_app(cls.state))
        cls.query = {'query': 'concentration time plot experimental unit censoring', 'allow_draft': True}

    @classmethod
    def tearDownClass(cls):
        cls.client.close()
        cls.temp.cleanup()

    def test_original_backend_is_mounted(self):
        self.assertEqual(self.client.get('/pipeline/v1/health').json()['status'], 'OK')
        self.assertIn('Research Workbench', self.client.get('/workbench').text)
        self.assertEqual(self.client.get('/demo-api/health').json()['demo_version'], 'connected-20261019')

    def test_recorded_counts_and_permissions(self):
        result = self.client.get('/demo-api/summary').json()
        self.assertEqual((result['library']['cards'], result['library']['sources'], result['library']['method_cards']), (255, 80, 31))
        self.assertEqual((result['data']['datasets'], result['data']['retained_rows'], result['data']['quarantined_rows']), (58, 499, 0))
        self.assertEqual((result['data']['findings'], result['data']['human_review']), (20, 12))
        self.assertFalse(result['data']['fit_ready'])
        self.assertFalse(result['data']['scientific_release'])

    def test_actual_retrieval_preserves_evidence_and_filters(self):
        result = self.client.post('/demo-api/retrieve', json=self.query)
        self.assertEqual(result.status_code, 200, result.text)
        packet = result.json()
        self.assertTrue(packet['general_methods'])
        ids = {e['id'] for e in packet['applicability_and_examples']['evidence']}
        for card in packet['general_methods']:
            self.assertIn(card['knowledge_layer'], {'general_method', 'conditional_method'})
            self.assertTrue(set(card['evidence_chunk_ids']) <= ids)
        self.assertFalse(packet['scientific_approval'])

    def test_draft_opt_in_and_budget(self):
        self.assertEqual(self.client.post('/demo-api/retrieve', json=dict(self.query, allow_draft=False)).status_code, 422)
        packet = self.client.post('/demo-api/retrieve', json=dict(self.query, budget=1000)).json()
        self.assertFalse(packet['general_methods'])
        self.assertTrue(packet['selection']['budget_omitted'])

    def test_original_context_builder_verifies_bundle(self):
        response = self.client.post('/demo-api/context', json=self.query)
        self.assertEqual(response.status_code, 200, response.text)
        from research_pipeline.context_builder import verify_bundle
        bundle = response.json()['bundle']
        self.assertEqual(verify_bundle(bundle), bundle)
        self.assertEqual(bundle['context_manifest']['route'], 'data.requirements')
        self.assertEqual(bundle['context_manifest']['dropped_fields'], [])
        self.assertFalse(bundle['context_manifest']['execution_authorized'])

    def test_review_notes_bound_persistent_not_approval(self):
        findings = self.client.get('/demo-api/findings').json()
        finding = findings['findings'][0]
        body = {'code': finding['code'], 'affected_id': finding['affected_id'],
                'report_sha256': findings['report_sha256'], 'reviewer': 'Automated test',
                'decision': 'NEEDS_SOURCE', 'rationale': 'Test-only request for source identity evidence.'}
        self.assertEqual(self.client.post('/demo-api/reviews', json=dict(body, report_sha256='0'*64)).status_code, 409)
        self.assertEqual(self.client.post('/demo-api/reviews', json=dict(body, code='UNKNOWN')).status_code, 422)
        response = self.client.post('/demo-api/reviews', json=body)
        self.assertEqual(response.status_code, 201)
        self.assertFalse(response.json()['changes_workflow_permissions'])
        with TestClient(app.create_app(self.state)) as restarted:
            notes = restarted.get('/demo-api/reviews/export').json()['notes']
            self.assertIn(response.json()['id'], [n['id'] for n in notes])

    def test_invalid_execution_and_cross_origin_are_rejected(self):
        self.assertEqual(self.client.post('/pipeline/v1/runs', json={}).status_code, 403)
        self.assertEqual(self.client.post('/ui-api/jobs', json={}).status_code, 422)
        self.assertEqual(self.client.post('/ui-api/workflow/sessions/unknown/nodes/eda/start', json={}).status_code, 409)
        self.assertEqual(self.client.post('/demo-api/reviews', json={}, headers={'Origin': 'https://other.example'}).status_code, 403)

    def test_all_table_and_figure_links_exist(self):
        rows = self.client.get('/demo-api/datasets').json()
        for row in rows:
            identifier = row['dataset_id']
            self.assertEqual(self.client.get(f'/examples/review/tables/{identifier}.html').status_code, 200)
            self.assertEqual(self.client.get(f'/examples/review/evidence/latest_run/data_preparation/normalized/{identifier}.csv').status_code, 200)
        figures = self.client.get('/demo-api/gallery').json()
        self.assertEqual(len(figures), 8)
        for figure in figures:
            self.assertEqual(self.client.get(figure['url']).status_code, 200)

    def test_unknown_and_escape_paths_are_not_served(self):
        self.assertEqual(self.client.get('/examples/%2e%2e/app.py').status_code, 404)
        self.assertEqual(self.client.get('/state/review_notes.sqlite').status_code, 404)


if __name__ == '__main__':
    unittest.main(verbosity=2)
