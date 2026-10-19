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
from research_pipeline import demo_data, data_agents
from research_pipeline.common import write_json
from research_pipeline.adequacy import file_ref
from demo.handoffs import handoff_index
from fastapi import HTTPException


class LightweightTests(unittest.TestCase):
    def fixture(self, folder):
        main = {'objective': 'Preserve source data.', 'data': {'files': []}}
        inv = {'items': [{'id': 'A', 'kind': 'TABLE'}], 'findings': []}
        mp, ip = folder/'main.json', folder/'inventory.json'
        write_json(mp, main); inv['main']=file_ref(mp); write_json(ip, inv)
        finding = {'code':'MISSING_DOSE', 'affected_id':'A', 'reason':'Dose not specified.',
                   'needed_material':'Source dose.', 'required_by':'BEFORE_QC', 'severity':'HUMAN_REVIEW'}
        req = {'main':file_ref(mp), 'inventory':file_ref(ip), 'tasks':[],
               'requirements':[{'id':'R1','task_id':'T1'}], 'findings':[],
               'access':[{'item_id':'A','disposition':'REVIEW_DATA'}]}
        rp = folder/'requirements.json'; write_json(rp, req)
        labels = {'requirements':file_ref(rp), 'labels':[{'item_id':'A'}],
                  'coverage':[{'item_id':'A','status':'BODY_REVIEWED'}], 'findings':[finding], 'model':'original-model'}
        lp=folder/'labels.json'; write_json(lp, labels)
        return (mp, ip, rp, lp), (main, inv, req, labels)

    def test_demo_defers_scientific_coverage_without_resolving_findings(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp); paths, values=self.fixture(folder)
            with patch.object(data_agents,'context_input',return_value=(*values[:2], {}, {})), patch.object(data_agents,'invoke',side_effect=AssertionError('Unexpected model call')):
                demo_data.assess(folder,*paths,folder/'out')
            report=json.loads((folder/'out/adequacy.json').read_text())
            self.assertTrue(demo_data.validated(report))
            self.assertEqual(report['llm_review'],{'validated':False,'decision':'NOT_RUN_IN_DEMO'})
            self.assertIn(values[3]['findings'][0],report['findings'])
            self.assertEqual(report['requirements'][0]['coverage_status'],'NOT_ASSESSED_IN_DEMO')
            self.assertTrue(report['requires_human_review'])
            self.assertFalse(demo_data.validated({**report,'scientific_release':True}))
            self.assertFalse(demo_data.validated({**report,'demo_profile':'FULL'}))

    def test_demo_rejects_changed_binding_and_missing_labels(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp); paths, values=self.fixture(folder)
            with patch.object(data_agents,'context_input',return_value=(*values[:2],{},{})):
                write_json(paths[3],{**values[3],'labels':[]})
                with self.assertRaisesRegex(ValueError,'Every admitted source'):
                    demo_data.assess(folder,*paths,folder/'out')
                write_json(paths[3],values[3]);write_json(paths[1],{**values[1],'changed':True})
                with self.assertRaises(ValueError):demo_data.assess(folder,*paths,folder/'out')

    def test_restore_preserves_original_model_and_checks_context_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);paths,values=self.fixture(folder)
            refs={key:file_ref(p) for key,p in zip(('main','inventory','requirements','labels'),paths)}
            new_main=write_json(folder/'new_main.json',values[0])
            demo_data.restore(new_main,refs,folder/'next')
            restored=json.loads((folder/'next/data_labels.json').read_text())
            inventory=json.loads((folder/'next/inventory.json').read_text())
            requirements=json.loads((folder/'next/requirements.json').read_text())
            self.assertEqual(inventory['main'],file_ref(new_main))
            self.assertEqual(requirements['main'],inventory['main'])
            self.assertEqual(requirements['inventory'],file_ref(folder/'next/inventory.json'))
            self.assertEqual(restored['requirements'],file_ref(folder/'next/requirements.json'))
            self.assertEqual(restored['model'],'original-model')
            self.assertEqual(restored['findings'],values[3]['findings'])
            changed=write_json(folder/'changed.json',{'objective':'Different'})
            with self.assertRaisesRegex(ValueError,'different Context'):
                demo_data.restore(changed,refs,folder/'bad')

    def test_provider_configuration_is_explicit_and_does_not_export_key(self):
        with patch.dict(os.environ,{},clear=True):
            app.configure_model('openai','my-model','high','http://127.0.0.1:11434/v1/')
            self.assertEqual(os.environ['CTXCOMP_MODEL_PROVIDER'],'openai')
            self.assertEqual(os.environ['CTXCOMP_OPENAI_MODEL'],'my-model')
            self.assertEqual(os.environ['CTXCOMP_OPENAI_BASE_URL'],'http://127.0.0.1:11434/v1')
            self.assertNotIn('CTXCOMP_OPENAI_API_KEY',os.environ)
            app.configure_model()
            self.assertEqual(os.environ['CTXCOMP_CODEX_MODEL'],'gpt-6.1-sol')
            with self.assertRaises(ValueError):app.configure_model('openai')
            with self.assertRaises(ValueError):app.configure_model('openai','x',api_base='https://user:secret@example.test/v1')

    def test_preparation_import_preserves_approved_demo_scope(self):
        from research_pipeline import preparation_workflow as pw
        report={'demo_profile':demo_data.PROFILE,'execution_scope':demo_data.SCOPE,
                'technical_review':{'executor':'HOST_PROGRAM','decision':'PASS'},
                'scientific_release':False,'fit_ready':False,'can_enter_qc':True,
                'assessment_status':'SUFFICIENT_FOR_DEFINED_SCOPE'}
        qc={'execution_scope':demo_data.SCOPE,'demo_profile':demo_data.PROFILE}
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp); approval=file_ref(write_json(folder/'approval.json',{'scope':'TECHNICAL_PREPARATION_ONLY_NOT_MODEL_RELEASE'}))
            with patch.object(pw,'approved_inputs',return_value=({},qc,report)):
                result=pw.import_inputs(approval,folder/'qc_context.json')
            self.assertTrue(all(result[k]==v for k,v in qc.items()))

    def test_handoff_inspection_is_scoped_to_registered_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            state=Path(tmp);run=state/'workbench_outputs/job1'
            write_json(state/'workbench_state/workbench_jobs/job1/request.json',{'out':str(run)})
            call=run/'data_agents/audit/DC-label/call1'
            write_json(call/'request.json',{'request_sha256':'a'*64,'payload':{'stage':'DC-label'}})
            write_json(call/'response.json',{'source':'retained'})
            write_json(call/'auth.json',{'never':'exposed'})
            session={'id':'flow_test','job_id':'job1'}
            entries=handoff_index(state,session)
            self.assertEqual(len(entries),1)
            self.assertNotIn('auth.json',[f['name'] for f in entries[0]['files']])
            write_json(state/'workbench_state/workbench_jobs/job1/request.json',{'out':str(state.parent)})
            with self.assertRaises(HTTPException):handoff_index(state,session)
