"""Demo deferral never converts a scientific review failure into PASS."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app
from ctxcomp import demo_review
from ctxcomp.io import write_json, read_json, leaves, digest


def review(request):
    p=request['payload']
    return {'request_sha256':request['request_sha256'],'candidate_sha256':p['candidate_sha256'],
        'review':{'decision':'REVISE','reviewer':'Synthetic reviewer',
        'records':[{'id':i,'faithfulness':'PRESERVED','completeness':'PRESERVED','reason':'Fixture'} for i in p['expected_record_ids']],
        'source_units':[{'unit_id':u['id'],'verdict':'PRESERVED','record_ids':['SC001'],'reason':'Fixture'} for u in p['source_units']],
        'checks':[{'id':i,'verdict':'ALTERED' if i==demo_review.CHECK else 'PRESERVED','reason':'Repeated proposition' if i==demo_review.CHECK else 'Fixture'} for i in p['required_check_ids']],
        'critical_errors':[],'fixes':[{'id':'FIX1','target':'SC001','reason':'Use a short reference for repeated text.','citations':[]}],
        'limitations':['Synthetic contract test; no scientific acceptance.']}}


class DemoContextTests(unittest.TestCase):
    def test_continuation_cannot_run_an_unstarted_context(self):
        from fastapi.testclient import TestClient
        with tempfile.TemporaryDirectory() as temp, TestClient(app.create_app(Path(temp))) as client:
            session=client.post('/ui-api/workflow/sessions',json={}).json()['session_id']
            endpoint=f'/workspace-api/workflow/{session}/continue-context-demo'
            self.assertEqual(client.post(endpoint,json={'confirmed':False}).status_code,422)
            result=client.post(endpoint,json={'confirmed':True})
            self.assertEqual(result.status_code,409,result.text)
            current=client.get(f'/ui-api/workflow/sessions/{session}').json()
            self.assertTrue(all(n['state']['execution']=='NOT_STARTED' for n in current['nodes']))

    def test_only_placement_issue_can_be_deferred(self):
        request={'request_sha256':'a','payload':{'candidate_sha256':'b','expected_record_ids':['SC001'],
            'source_units':[{'id':'U1'}],'required_check_ids':['source_faithfulness',demo_review.CHECK]}}
        value=review(request)['review']
        with patch.dict('os.environ',{'PKPD_DEMO_LIGHTWEIGHT_DATA':'0'}):
            self.assertFalse(demo_review.eligible(value))
        with patch.dict('os.environ',{'PKPD_DEMO_LIGHTWEIGHT_DATA':'1'}):
            self.assertTrue(demo_review.eligible(value))
            for location,field,changed in [('records','faithfulness','ALTERED'),('records','completeness','MISSING'),
                                         ('source_units','verdict','MISSING'),('checks','verdict','UNRESOLVED')]:
                bad=copy.deepcopy(value);bad[location][0][field]=changed
                self.assertFalse(demo_review.eligible(bad))
            self.assertFalse(demo_review.eligible({**value,'critical_errors':['Wrong units']}))
            self.assertFalse(demo_review.eligible({**value,'decision':'NEEDS_REVIEW'}))
            bad=copy.deepcopy(value);bad['fixes'][0]['target']='NEW'
            self.assertFalse(demo_review.eligible(bad))

    def test_handoff_keeps_exact_revise_and_rejects_tampering_or_full_mode(self):
        from ctxcomp.engine import init_run, prepare, accept, verify_context
        from ctxcomp.lean_compression import content
        with tempfile.TemporaryDirectory() as temp, patch.dict('os.environ',{'PKPD_DEMO_LIGHTWEIGHT_DATA':'1'}):
            folder=Path(temp);source=folder/'proposal.txt'
            fact='Give Compound Z 2 mg/kg IV to rats; reserve human PK until predictions are frozen.'
            source.write_text(fact,encoding='utf-8');run=folder/'run'
            init_run(run,source,compression_profile='LEAN_1.0')
            request=prepare(run,'context');unit=request['payload']['source_units'][0]
            span={'source_id':unit['source_id'],'unit_id':unit['id'],'quote':fact}
            core={'version':'3.0','objective':'Compound Z research',
                'study':{k:'NOT_FOUND' for k in ['drug','regimen','population','system','measurements','methods']},
                'data':{'available':[],'required':[]},'rules':[],'checks':[],'uncertainties':[]}
            candidate={'request_sha256':request['request_sha256'],'context':core,
                'scientific_context':{'version':'2.0','items':[{'id':'SC001','statement':fact,'science':{
                    'role':'OTHER','evidence_status':'SOURCE_REPORTED','method_refs':[],'adoption_relations':[],'relations':[]}}], 'potential_questions':[]},
                'missing_information':{'schema_version':'1.0','items':[]},
                'evidence':[{'id':p,'status':'NOT_FOUND' if v=='NOT_FOUND' else 'EXPLICIT',
                    'citations':[] if v=='NOT_FOUND' else [span],'reason':'Fixture'} for p,v in leaves(core) if p!='/version']}
            candidate['evidence'].append({'id':'SC001','status':'EXPLICIT','citations':[span],'reason':'Fixture'})
            accept(run,'context',candidate);response=review(prepare(run,'context_review'))
            with patch.dict('os.environ',{'PKPD_DEMO_LIGHTWEIGHT_DATA':'0'}):
                self.assertEqual(accept(run,'context_review',response)['status'],'REVISE')
                self.assertFalse((run/'handoff/main.json').exists())
            self.assertEqual(accept(run,'context_review',response)['status'],'ACCEPTED')
            self.assertEqual(verify_context(run)['status'],'VALID')
            main=read_json(run/'handoff/main.json');ref=main['demo_context_review_ref']
            receipt=demo_review.verify(ref)
            self.assertEqual(receipt['candidate_sha256'],digest(content(candidate)))
            self.assertEqual(main['scientific_context'],candidate['scientific_context'])
            self.assertEqual(read_json(receipt['review_ref']['path']),response)
            self.assertEqual(receipt['original_review_decision'],'REVISE')
            self.assertEqual(len(receipt['findings']),2)
            self.assertFalse(receipt['independent_review_passed'])
            from research_pipeline.workflow_runtime import execute_builtin
            from ctxcomp import providers
            output=folder/'B1/main.json'
            with patch.dict('os.environ',{'CTXCOMP_DISABLE_RESPONSE_REUSE':'0'}), \
                 patch.object(providers,'run_model',side_effect=AssertionError('Unexpected repeated dispatch')):
                execute_builtin({'kind':'compress','options':{'work':str(run)},'outputs':[str(output)]})
            self.assertEqual(read_json(output),main)
            self.assertFalse(read_json(run/'audit/verified_context_reuse.json')['new_model_calls'])
            with patch.dict('os.environ',{'PKPD_DEMO_LIGHTWEIGHT_DATA':'0'}):
                with self.assertRaises(ValueError):verify_context(run)
            write_json(ref['path'],{**receipt,'scientific_release':True})
            with self.assertRaisesRegex(ValueError,'changed'):verify_context(run)
