"""Release must not publish partial or mismatched acceptance evidence."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('package_release', Path(__file__).resolve().parents[1] / 'tools/package_release.py')
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class ReleaseBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.report = {'status': 'ALL_THREE_PASSED_THROUGH_DATA', 'examples': [],
                       'eda_executed': False, 'pk_executed': False, 'scientific_release': False}
        for example in sorted(release.EXAMPLES):
            artifact = {'name': 'report.json', 'sha256': 'a' * 64}
            session = {'session_id': example, 'nodes': [
                {'id': node, 'state': {'execution': 'COMPLETED', 'approved': True, 'artifacts': [artifact]}}
                for node in sorted(release.NODES)] + [
                {'id': 'eda', 'state': {'execution': 'NOT_STARTED'}}]}
            driver = Path(self.temporary.name) / (example + '.json')
            driver.write_text(json.dumps({'status': 'PASSED_THROUGH_DATA', 'final_session': session}))
            self.report['examples'].append({'example': example, 'session_id': example,
                'status': 'PASSED_THROUGH_DATA', 'driver_report': str(driver),
                'verified_artifacts': [{'node': node, **artifact} for node in sorted(release.NODES)]})

    def test_all_three_source_bound_reports_are_required(self):
        self.assertEqual(len(release.accepted_examples(self.report)), 3)
        for status in ('RUNNING', 'FAILED', 'PASSED_THROUGH_DATA'):
            bad = dict(self.report, status=status)
            with self.assertRaisesRegex(ValueError, 'complete example suite'):
                release.accepted_examples(bad)
        bad = dict(self.report, examples=self.report['examples'][:2])
        with self.assertRaisesRegex(ValueError, 'example set'):
            release.accepted_examples(bad)

    def test_runtime_package_directories_are_not_confused_with_app_state(self):
        root=Path(self.temporary.name)/'distribution'
        names=['state/secret.json','outputs/run.json','runtime/Lib/site-packages/langchain_core/outputs/__init__.py',
               'runtime/Lib/site-packages/example/state/__init__.py','runtime/Lib/site-packages/example/__pycache__/x.pyc']
        for name in names:
            path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('fixture')
        with patch.object(release,'ROOT',root):
            included={name for _,name in release.files()}
        self.assertEqual(included,set(names[2:4]))

    def test_fresh_release_requires_four_new_calls_and_unchanged_round(self):
        report=copy.deepcopy(self.report)
        fourth=copy.deepcopy(report['examples'][0]);fourth['example']='imidocarb'
        report['examples'].append(fourth)
        report.update(status='ALL_FOUR_PASSED_FRESH_THROUGH_DATA',code_unchanged=True,
                      no_reuse_verified=True,response_reuse_disabled=True,manual_repairs=0,automatic_retries=0)
        for item in report['examples']:
            item.update(attempts=[{'attempt':1}],model_calls=[{'new_or_changed':True,'status':'RETURNED',
                        'requested_model':'gpt-6.1-sol','requested_reasoning_effort':'high'}])
        self.assertEqual(len(release.accepted_examples(report)),4)
        report['examples'][0]['model_calls'][0]['new_or_changed']=False
        with self.assertRaisesRegex(ValueError,'non-fresh'):release.accepted_examples(report)
        report['examples'][0]['model_calls'][0]['new_or_changed']=True
        report['code_unchanged']=False
        with self.assertRaisesRegex(ValueError,'unchanged-code'):release.accepted_examples(report)

    def test_changed_artifact_or_session_is_rejected(self):
        for field in ('sha256', 'session_id'):
            bad = copy.deepcopy(self.report)
            if field == 'sha256':
                bad['examples'][0]['verified_artifacts'][0][field] = 'b' * 64
            else:
                bad['examples'][0][field] = 'different'
            with self.assertRaisesRegex(ValueError, 'differ'):
                release.accepted_examples(bad)

    def test_collected_cases_must_match_completed_source_records(self):
        source=copy.deepcopy(self.report)
        fourth=copy.deepcopy(source['examples'][0]);fourth['example']='imidocarb'
        source['examples'].append(fourth)
        source.update(status='FAILED',state_root=self.temporary.name)
        for item in source['examples']:
            item.update(attempts=[{'attempt':1}],model_calls=[{'new_or_changed':True,'status':'RETURNED',
                        'requested_model':'gpt-6.1-sol','requested_reasoning_effort':'high'}])
        path=Path(self.temporary.name)/'source.json'
        path.write_text(json.dumps(source))
        report=copy.deepcopy(source);report['status']='FOUR_VERIFIED_DATA_EXAMPLES'
        for item in report['examples']:
            item.update(source_report={'path':str(path),'sha256':release.sha(path.read_bytes())},
                        state_root=source['state_root'],source_round='fixture')
        self.assertEqual(len(release.accepted_examples(report)),4)
        bad=copy.deepcopy(report);bad['examples'][0]['attempts'][0]['attempt']=2
        with self.assertRaisesRegex(ValueError,'differs from'):release.accepted_examples(bad)
        path.write_text(json.dumps(dict(source,status='RUNNING')))
        with self.assertRaisesRegex(ValueError,'source report changed'):release.accepted_examples(report)

    def test_downstream_or_unapproved_stage_is_rejected(self):
        for target in ('eda', 'prepare'):
            path = Path(self.report['examples'][0]['driver_report'])
            original = path.read_text()
            data = json.loads(original)
            state = next(n['state'] for n in data['final_session']['nodes'] if n['id'] == target)
            if target == 'eda':
                state['execution'] = 'COMPLETED'
            else:
                state['approved'] = False
            path.write_text(json.dumps(data))
            with self.assertRaises(ValueError):
                release.accepted_examples(self.report)
            path.write_text(original)


if __name__ == '__main__':
    unittest.main()
