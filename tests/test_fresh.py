"""No-reuse mode must defeat both local kept responses and explicit replay."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import app
from research_pipeline import data_agents
from ctxcomp import providers
from ctxcomp.schemas import obj, S
sys.path.insert(0, str(ROOT / 'tests'))
import run_fresh_examples as fresh


class FreshExecutionTests(unittest.TestCase):
    def test_access_receives_registered_names_bound_to_file_ids_and_hashes(self):
        """An explicit filename permission must remain resolvable after intake renames files."""
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            main_path = root / 'main.json'
            files = [{'id': 'F0002', 'name': 'authorized_source.xlsx', 'kind': 'xlsx',
                      'role': 'DATA_CANDIDATE', 'sha256': 'a' * 64, 'path': '/private/F0002.xlsx'},
                     {'id': 'F0003', 'kind': 'csv', 'role': 'REFERENCE_ONLY', 'sha256': 'b' * 64}]
            main = {'objective': 'Inspect supplied data', 'data': {'files': files}}
            main_path.write_text(json.dumps(main))
            knowledge = root / 'knowledge.json'
            knowledge.write_text('{}')
            definition = root / 'definition.json'
            definition.write_text(json.dumps({'main': data_agents.file_ref(main_path),
                'method_knowledge_ref': data_agents.file_ref(knowledge),
                'tasks': [], 'requirements': [], 'findings': []}))
            inv_path = root / 'inventory.json'
            inv_path.write_text('{}')
            inv = {'items': []}
            def capture(run, stage, payload, schema, **options):
                self.assertEqual(payload['file_registry'], [
                    {k: v for k, v in item.items() if k != 'path'} for item in files])
                return {'access': [], 'findings': [], 'request_sha256': 'c' * 64}
            with patch.object(data_agents, 'context_input', return_value=(main, inv, [], {})), \
                 patch.object(data_agents, 'invoke', side_effect=capture):
                data_agents.assign_access(root, main_path, inv_path, definition, root / 'access.json')

    def test_recovery_endpoints_cannot_bypass_no_reuse_mode(self):
        from fastapi.testclient import TestClient
        with tempfile.TemporaryDirectory() as folder, \
             patch.dict('os.environ', {'CTXCOMP_DISABLE_RESPONSE_REUSE': '1'}), \
             TestClient(app.create_app(Path(folder))) as client:
            self.assertTrue(client.get('/workspace-api/capabilities').json()['response_reuse_disabled'])
            for route in ('continue-context-demo', 'recover-context'):
                result = client.post('/workspace-api/workflow/unused/' + route, json={'confirmed': True})
                self.assertEqual(result.status_code, 409)
                self.assertIn('reuse is disabled', result.json()['detail'])

    def test_no_reuse_calls_provider_even_with_identical_kept_and_replay_inputs(self):
        with tempfile.TemporaryDirectory() as folder:
            run = Path(folder) / 'run'
            def generate(request, **kwargs):
                return {'request_sha256': request['request_sha256']}
            with patch.dict('os.environ', {'CTXCOMP_DISABLE_RESPONSE_REUSE': '1',
                                          'PKPD_DEMO_REUSE_DATA_RUN': str(run)}), \
                 patch.object(data_agents, 'codex_generate', side_effect=generate) as provider:
                for target in (run, run, Path(folder) / 'next'):
                    data_agents.invoke(target, 'DR-access', {}, obj(request_sha256=S),
                                       model='gpt-6.1-sol', check=lambda response: True)
            self.assertEqual(provider.call_count, 3)
            self.assertFalse(list(Path(folder).rglob('replay.json')))
            self.assertFalse(list(Path(folder).rglob('cache_reuse.jsonl')))

    def test_no_reuse_rejects_preaccepted_compression(self):
        with patch.dict('os.environ', {'CTXCOMP_DISABLE_RESPONSE_REUSE': '1'}), \
             patch.object(providers, 'load_run', return_value=({}, {'accepted': {'context': {}}})):
            with self.assertRaisesRegex(ValueError, 'fresh run'):
                providers.run_model('unused', generator=lambda *a, **kw: None)

    def test_fresh_driver_report_stays_in_requested_directory_across_child_cwd(self):
        with tempfile.TemporaryDirectory() as folder:
            before = Path.cwd()
            try:
                os.chdir(folder)
                def fetch(base, path):
                    if path.endswith('capabilities'):
                        return json.dumps({'response_reuse_disabled': True, 'model_executor': {
                            'requested_model': 'gpt-6.1-sol', 'requested_reasoning_effort': 'high'}}).encode()
                    return json.dumps([{'id': name} for name in fresh.EXAMPLES]).encode()
                def child(command, **kwargs):
                    output = Path(command[command.index('--output') + 1])
                    self.assertTrue(output.is_absolute())
                    self.assertEqual(output.parent, Path(folder) / 'reports')
                    output.write_text(json.dumps({'status':'FAILED','error':'deliberate test stop'}))
                    from types import SimpleNamespace
                    return SimpleNamespace(returncode=1)
                with patch.object(sys, 'argv', ['run_fresh_examples.py', '--state-root', 'state',
                        '--output-dir', 'reports', '--approve-test-gates']), \
                     patch.object(fresh, 'fetch', side_effect=fetch), \
                     patch.object(fresh, 'code_snapshot', return_value={}), \
                     patch.object(fresh.subprocess, 'run', side_effect=child):
                    self.assertEqual(fresh.main(), 1)
                report = json.loads((Path(folder) / 'reports/fresh_examples_acceptance.json').read_text())
                self.assertIn('deliberate test stop', report['error'])
                self.assertTrue((Path(folder) / 'reports/imidocarb_driver.json').is_file())
            finally:
                os.chdir(before)


if __name__ == '__main__':
    unittest.main()
