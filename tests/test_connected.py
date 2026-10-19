"""Integration contracts for imported inputs, direct intake and native review gates."""
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import app
from fastapi.testclient import TestClient


class ConnectedTests(unittest.TestCase):
    def test_method_candidate_cannot_be_generated_as_source_permission(self):
        from research_pipeline import data_agents as agents
        from jsonschema import validate, ValidationError
        schema=agents.definition_transport_schema(agents.DEFINITION,
            sources={'main:/objective':'Inspect permitted source data.'},
            method_sources={'method:MP007':'Confirm project permission before use.'})
        need={'id':'N1','task_id':'T1','description':'Confirm permission before using an input.',
              'kind':'SOURCE_PERMISSION','required_by':'BEFORE_QC','fields':['permission'],
              'rule_ids':[],'origin':'METHOD_CANDIDATE','method_profile_ids':['MP007'],
              'conditions':['Use only when independently authorized by the project.'],
              'evidence':[{'source':'main:/objective','quote':'Inspect permitted source data.'},
                          {'source':'method:MP007','quote':'Confirm project permission before use.'}]}
        scoped={'$defs':schema['$defs'],**schema['properties']['requirements']['items']}
        with self.assertRaises(ValidationError): validate(need,scoped)
        validate({**need,'kind':'METHOD_REQUIREMENT'},scoped)
        validate({**need,'origin':'PROJECT_EXPLICIT','method_profile_ids':[],
                  'evidence':[need['evidence'][0]]},scoped)

    def test_inferred_stated_fields_remain_unresolved_with_review_finding(self):
        from research_pipeline import data_agents as agents
        value={'quantity':'age','value':'7','unit':'weeks','subject':'Female Swiss mice','qualifiers':[],
            'evidence':[{'source':'cell:A5','quote':'Female Swiss mice, 7 weeks.'}]}
        findings=[]
        agents.retain_literal_stated_fields(value,findings,'table1')
        self.assertEqual(value['quantity'],'NOT_FOUND')
        self.assertEqual((value['value'],value['unit']),('7','weeks'))
        self.assertEqual(findings[0]['severity'],'HUMAN_REVIEW')
        self.assertEqual(findings[0]['required_by'],'BEFORE_EDA')
        self.assertIn('age',findings[0]['reason'])
        value['value']='70'
        agents.retain_literal_stated_fields(value,findings,'table1')
        self.assertEqual(value['value'],'NOT_FOUND')
        self.assertEqual(value['evidence'][0]['quote'],'Female Swiss mice, 7 weeks.')

    def test_footnote_measurement_can_cite_body_for_applicability(self):
        from research_pipeline import data_agents as agents
        region={'start_row':45,'end_row':57,'header_row':51,'left':1,'right':4}
        cells={'T:A49':{'row':49,'column':1},'T:A56':{'row':56,'column':1},
               'T:B56':{'row':56,'column':2}}
        value={'quantity':'urine','value':'0-8','unit':'h','subject':'Beagle dog',
               'qualifiers':['b) 0-8 h urine.'],
               'evidence':[{'source':'T:A49','quote':'Footnotes: b) 0-8 h urine.'},
                           {'source':'T:A56','quote':'Beagle dog'},
                           {'source':'T:B56','quote':'49.1 ± 8.4 b)'}]}
        self.assertTrue(agents.stated_measurement_has_text_support(value,'T',cells,region))
        self.assertFalse(agents.stated_measurement_has_text_support(
            {**value,'value':'49.1'},'T',cells,region))
        self.assertFalse(agents.stated_measurement_has_text_support(
            {**value,'evidence':value['evidence'][1:]},'T',cells,region))

    def test_demo_keeps_mixed_note_table_annotation_unresolved(self):
        import copy
        from research_pipeline import data_agents as agents
        region={'start_row':1,'end_row':20,'header_row':7,'left':1,'right':5}
        cells={'T:A6':{'row':6,'column':1},'T:A20':{'row':20,'column':1},
               'T:D7':{'row':7,'column':4},'T:D20':{'row':20,'column':4}}
        value={'quantity':'F','value':'106','unit':'%','subject':'Oral Without TFC',
               'qualifiers':['printed values'],
               'evidence':[{'source':'T:A6','quote':'F is AUC oral / AUC IV; printed values 106 and 122.'},
                           {'source':'T:A20','quote':'F (%)'},
                           {'source':'T:D7','quote':'Oral Without TFC (n = 6)'},
                           {'source':'T:D20','quote':'106'}]}
        original=copy.deepcopy(value)
        with self.assertRaisesRegex(ValueError,'table body'):
            agents.validate_stated_text_location(value,'T',cells,region,[])
        self.assertEqual(value,original)
        findings=[]
        agents.validate_stated_text_location(value,'T',cells,region,findings,allow_unresolved=True)
        self.assertEqual((value['quantity'],value['value'],value['unit']),('F','106','NOT_FOUND'))
        self.assertEqual(value['evidence'],original['evidence'])
        self.assertTrue(agents.stated_measurement_has_text_support(value,'T',cells,region))
        self.assertEqual(findings[0]['code'],'STATED_LOCATION_UNRESOLVED')
        self.assertEqual(findings[0]['severity'],'HUMAN_REVIEW')
        self.assertEqual(findings[0]['required_by'],'BEFORE_EDA')
        self.assertIn('"unit": "%"',findings[0]['reason'])
        body=copy.deepcopy(original);body['evidence']=[original['evidence'][-1]]
        agents.validate_stated_text_location(body,'T',cells,region,findings,allow_unresolved=True)
        self.assertEqual(body['value'],'NOT_FOUND')
        self.assertEqual(body['evidence'],[original['evidence'][-1]])

    def test_exact_header_resolves_position_with_supplemental_unit_evidence(self):
        from research_pipeline import data_agents as agents
        region={'start_row':100,'end_row':110,'header_row':103,'left':1,'right':4}
        cells={'T:B103':{'row':103,'column':2,'value':'Residual % at 1 min'},
               'T:C103':{'row':103,'column':3,'value':'60 min'},
               'T:C104':{'row':104,'column':3,'value':70.2}}
        column={'header':'60 min','evidence':[{'source':key,'quote':str(cell['value'])}
                                             for key,cell in cells.items()]}
        self.assertEqual(agents.cited_column_position(column,'T',cells,region),3)
        with self.assertRaisesRegex(ValueError,'one header cell'):
            agents.cited_column_position({**column,'header':'60 minutes'},'T',cells,region)
        cells['T:B103']['value']='60 min'
        with self.assertRaisesRegex(ValueError,'one header cell'):
            agents.cited_column_position(column,'T',cells,region)

    def test_demo_retains_mixed_units_as_unresolved_without_weakening_full_route(self):
        import copy
        from research_pipeline import data_agents as agents
        column={'header':'Mean','unit':'MIXED','qualifiers':['Mean','Converted to mg/L'],
                'evidence':[{'source':'T:B1','quote':'Mean'},
                            {'source':'T:A2','quote':'Vc/F (liters)'},
                            {'source':'T:A3','quote':'CL/F (liters/h)'}]}
        original=copy.deepcopy(column)
        with self.assertRaisesRegex(ValueError,'not written'):
            agents.validate_column_literals(column,[],'T')
        self.assertEqual(column,original)
        findings=[]
        agents.validate_column_literals(column,findings,'T',allow_unresolved=True)
        self.assertEqual(column['unit'],'NOT_FOUND')
        self.assertEqual(column['qualifiers'],['Mean'])
        self.assertEqual(column['evidence'],original['evidence'])
        self.assertEqual(findings[0]['severity'],'HUMAN_REVIEW')
        self.assertIn('MIXED',findings[0]['reason'])
        self.assertIn('Converted to mg/L',findings[0]['reason'])
        self.assertEqual(findings[0]['required_by'],'BEFORE_EDA')

    def test_demo_does_not_map_linked_note_or_nested_header_to_current_table(self):
        from research_pipeline import data_agents as agents
        region={'start_row':11,'end_row':30,'header_row':14,'left':1,'right':5}
        cells={'T:A5':{'row':5,'column':1,'value':'Organism'},
               'T:A14':{'row':14,'column':1,'value':'Strain'},
               'T:A26':{'row':26,'column':1,'value':'Source'}}
        columns=[{'header':cell['value'],'unit':'NOT_FOUND','qualifiers':[],
                  'evidence':[{'source':key,'quote':cell['value']}]} for key,cell in cells.items()]
        with self.assertRaisesRegex(ValueError,'one header cell'):
            agents.bind_column_positions(columns,'T',cells,region,[])
        findings=[]
        bound=agents.bind_column_positions(columns,'T',cells,region,findings,allow_unresolved=True)
        self.assertEqual([(c['header'],c['column']) for c in bound],[('Strain','A')])
        self.assertEqual(len(findings),2)
        self.assertTrue(all(f['code']=='COLUMN_POSITION_UNRESOLVED' for f in findings))
        self.assertTrue(all(f['severity']=='HUMAN_REVIEW' for f in findings))
        self.assertIn('T:A5',findings[0]['reason'])
        self.assertIn('T:A26',findings[1]['reason'])
        self.assertNotIn('column',columns[0])
        self.assertNotIn('column',columns[2])

    def test_context_path_alias_keeps_exact_source_binding(self):
        from research_pipeline import data_agents as agents
        sources={'main:/objective':'Use source evidence.'}
        self.assertEqual(agents.canonical_context_paths(['main:/objective','/objective'],sources),['/objective'])
        with self.assertRaisesRegex(ValueError,'Unknown context path'):
            agents.canonical_context_paths(['main:/invented'],sources)

    def test_context_container_resolves_only_existing_descendants(self):
        from research_pipeline import data_agents as agents
        sources={'main:/scientific_context/items/1/id':'SC002',
                 'main:/scientific_context/items/1/statement':'Preserve source units.',
                 'main:/scientific_context/items/10/id':'SC011',
                 'rule:R001':'Permission is separate.'}
        expected=['/scientific_context/items/1/id','/scientific_context/items/1/statement']
        self.assertEqual(agents.canonical_context_paths(
            ['main:/scientific_context/items/1',expected[0]],sources),expected)
        for path in ['/scientific_context/items/100','/scientific_context/items/1/',
                     'rule:R001','/scientific_context/items/1/invented']:
            with self.assertRaisesRegex(ValueError,'Unknown context path'):
                agents.canonical_context_paths([path],sources)

    def test_explicit_data_replay_requires_identical_request_and_executor(self):
        from research_pipeline import data_agents as agents
        from ctxcomp.schemas import obj, S
        with tempfile.TemporaryDirectory(prefix='pkpd-data-replay-') as folder:
            root=Path(folder)
            def generate(request,**kwargs): return {'request_sha256':request['request_sha256']}
            with patch.object(agents,'codex_generate',side_effect=generate):
                original=agents.invoke(root/'prior','DR-access',{},obj(request_sha256=S),model='gpt-6-sol')
            with patch.dict('os.environ',{'PKPD_DEMO_REUSE_DATA_RUN':str(root/'prior')}), \
                 patch.object(agents,'codex_generate',side_effect=AssertionError('Repeated model call')):
                self.assertEqual(agents.invoke(root/'next','DR-access',{},obj(request_sha256=S),model='gpt-6-sol'),original)
                with self.assertRaisesRegex(AssertionError,'Repeated model call'):
                    agents.invoke(root/'changed','DR-access',{'objective':'Changed'},obj(request_sha256=S),model='gpt-6-sol')
            self.assertEqual(len(list((root/'next').rglob('replay.json'))),1)

    def test_requirements_quotes_are_literal_bound_spans(self):
        from research_pipeline import data_agents as agents
        from jsonschema import validate, ValidationError
        sources={'main:/objective':'Analyze animal PK.',
                 'rule:R14':json.dumps({'text':'Keep evidence levels: a successful fit is not predictive validation.'})}
        methods={'method:MP1':json.dumps({'claim':'Preserve sampling time and units.'})}
        schema=agents.definition_transport_schema(agents.DEFINITION,sources=sources,method_sources=methods)
        quote_schema={'$defs':schema['$defs'],'$ref':'#/$defs/projectEvidence'}
        validate({'source':'rule:R14','quote':'Keep evidence levels: a successful fit is not predictive validation.'},quote_schema)
        with self.assertRaises(ValidationError):
            validate({'source':'rule:R14','quote':'A successful fit is not predictive validation.'},quote_schema)
        with self.assertRaises(ValidationError):
            validate({'source':'main:/objective','quote':'Preserve sampling time and units.'},quote_schema)
        with self.assertRaises(ValidationError):
            validate({'source':'method:MP1','quote':'Preserve sampling time and units.'},quote_schema)

    def test_requirements_transport_uses_actual_source_ids(self):
        from research_pipeline import data_agents as agents
        sources=['main:/scientific_context/items/12/statement','rule:R001','method:MP001']
        schema=agents.definition_transport_schema(agents.DEFINITION,source_ids=sources)
        task=schema['properties']['tasks']['items']['properties']['evidence']['items']['properties']['source']
        variants=schema['properties']['requirements']['items']['anyOf']
        explicit=variants[0]['properties']['evidence']['items']['properties']['source']
        method=variants[1]['properties']['evidence']['items']['properties']['source']
        self.assertEqual(task['enum'],sources[:2])
        self.assertEqual(explicit['enum'],sources[:2])
        self.assertEqual(method['enum'],sources)
        self.assertNotIn('main:/scientific_context/items/12/science/statement',task['enum'])

    def test_live_model_calls_have_no_default_timeout(self):
        from research_pipeline import data_agents as agents
        from ctxcomp.lean_compression import profile
        from ctxcomp.schemas import obj, S
        with tempfile.TemporaryDirectory(prefix='pkpd-data-timeout-') as folder:
            seen=[]
            def generate(request, **kwargs):
                seen.append(kwargs['timeout'])
                scope=Path(kwargs['context_scope'])
                self.assertTrue(scope.is_relative_to(Path(folder)))
                self.assertEqual(scope,Path(folder)/'calls'/request['request_sha256'][:20])
                return {'request_sha256':request['request_sha256']}
            with patch.object(agents,'codex_generate',side_effect=generate):
                agents.invoke(folder,'DR-access',{},obj(request_sha256=S))
                agents.invoke(folder,'DR-access',{},obj(request_sha256=S),timeout=25)
            self.assertEqual(seen,[None,25])
            self.assertIsNone(profile('LEAN_1.0')['wall_budget_seconds'])

    def test_provisional_rules_preserve_truth_scope_and_hashes(self):
        import os
        from research_pipeline import demo_key_rules as rules, project_rule_agent as agent
        from research_pipeline.common import write_json
        with tempfile.TemporaryDirectory(prefix='pkpd-demo-rules-') as folder:
            root = Path(folder)
            base = agent.file_ref(write_json(root/'base.json', {'objective':'Preserve data','rules':[]}))
            input_ref = agent.file_ref(write_json(root/'input.json', {'extraction_policy':{'steps':{'adequacy':{},'prepare':{},'eda':{}}}}))
            value = {'objective':'Preserve data','base_main_ref':base,
                'extraction_policy':{'steps':{'adequacy':{},'prepare':{},'eda':{}}},
                'source_units':[{'id':'U1','source_id':'P1','start_char':0,'text':'Keep original measurements.'}],
                'source_permissions':[{'source_id':'P1','may_supply_project_authority':True}]}
            def generate(req, **kwargs):
                return {'request_sha256':req['request_sha256'],'rules':[{'id':'R001',
                    'text':'Keep original measurements.','used_in':['prepare'],
                    'evidence':[{'source_id':'P1','unit_id':'U1','quote':'Keep original measurements.'}]}]}
            with patch.dict(os.environ, {'PKPD_DEMO_PROVISIONAL_RULES':'1','PREFECT_HOME':str(root/'prefect')}), \
                 patch.object(agent,'validate_input',return_value=value), \
                 patch.object(agent,'codex_generate',side_effect=generate) as model:
                reference = rules.extract(input_ref,root/'project_rules')
                self.assertEqual(model.call_count,1)
                pack=agent.verify_published(reference)
                self.assertEqual(pack['status'],'DEMO_PROVISIONAL_RULES')
                acceptance=json.loads(Path(pack['review_ref']['path']).read_text())
                self.assertFalse(acceptance['independent_model_review'])
                self.assertFalse(acceptance['scientific_results_accepted'])
                self.assertEqual(len(agent.project(reference,'prepare')['rules']),1)
                self.assertEqual(agent.project(reference,'eda')['execution_scope'],'THROUGH_DATA_ONLY')
                report=json.loads((root/'project_rules/published/report.json').read_text())
                self.assertTrue(agent.publication_ready(report,allow_provisional=True))
                with self.assertRaisesRegex(ValueError,'unauthorized'):
                    agent.publication_ready(report)
                with self.assertRaisesRegex(ValueError,'differs'):
                    agent.publication_ready({**report,'scientific_results_accepted':True},allow_provisional=True)
                # Exercise both scheduler completion and graph diagnosis after
                # the real provisional publisher, with no second model call.
                from research_pipeline import orchestration, workflow_runtime
                from research_pipeline.graph_execution import run_controlled
                job=root/'job';job.mkdir()
                request_path=write_json(job/'request.json',{'id':'demo-test','created_at':'test',
                    'job_dir':str(job),'out':str(root),'demo_key_rules':True})
                with patch.object(orchestration,'run_dag',return_value='test.log'), \
                     patch.object(workflow_runtime,'context_requires_project_rules',return_value=True):
                    result=run_controlled(request_path,'context',prefect_runner=orchestration.research_flow.fn)
                self.assertEqual(result['status'],'WAITING_FOR_HUMAN_REVIEW')
                self.assertEqual(result['control']['disposition'],'HUMAN_SCIENTIFIC_REVIEW')
                self.assertFalse(result['scientific_release'])
                self.assertEqual(model.call_count,1)
                with self.assertRaisesRegex(ValueError,'Unknown Rules'):
                    agent.project(reference,'invented_stage')
                with patch.dict(os.environ, {'PKPD_DEMO_PROVISIONAL_RULES':'0'}):
                    with self.assertRaisesRegex(ValueError,'explicitly configured demo'):
                        agent.verify_published(reference)
                write_json(pack['candidate_ref']['path'], {'changed':True})
                with self.assertRaises(ValueError):
                    agent.verify_published(reference)

    def test_context_handoff_formatting_does_not_change_approved_content(self):
        from research_pipeline.adequacy import import_reviewed_context, file_ref
        from research_pipeline.workflow_canvas import fingerprint
        from research_pipeline.common import write_json
        with tempfile.TemporaryDirectory(prefix='pkpd-context-format-') as folder:
            root=Path(folder)
            main={'version':'3.2','objective':'Original objective','rule_publication':'PROJECT_RULES_AGENT'}
            write_json(root/'B1.json',main)
            (root/'handoff.json').write_text(json.dumps(main,separators=(',',':')),encoding='utf-8')
            published={**main,'project_rules_ref':{'path':'stub','sha256':'stub'}}
            write_json(root/'published.json',published)
            artifact={**file_ref(root/'B1.json'),'name':'main.json'}
            approval=file_ref(write_json(root/'approval.json',{'context':{'artifacts':[artifact],
                'output_signature':fingerprint([artifact])},'project_rules_ref':published['project_rules_ref']}))
            pack={'base_main_ref':file_ref(root/'handoff.json'),'main_ref':file_ref(root/'published.json')}
            with patch('research_pipeline.workflow_canvas.CanvasStore.approved',return_value=True), \
                 patch('ctxcomp.handoff.verify_main'), \
                 patch('research_pipeline.project_rule_agent.verify_published',return_value=pack):
                self.assertEqual(import_reviewed_context(approval,root/'imported.json'),published)
                write_json(root/'handoff.json',{**main,'objective':'Different objective'})
                with self.assertRaisesRegex(ValueError,'exact approved context'):
                    import_reviewed_context(approval,root/'rejected.json')

    def test_revision_draft_is_bound_to_the_exact_reviewed_candidate(self):
        from ctxcomp.io import digest
        from research_pipeline.common import write_json, utcnow
        from research_pipeline.context_feedback import context_feedback
        from ctxcomp import lean_compression as lean
        candidate = {'context':{}, 'scientific_context':{'items':[], 'potential_questions':[]},
                     'missing_information':{'items':[]}, 'evidence':[]}
        accepted = {'request_sha256':'synthetic', **candidate}
        with tempfile.TemporaryDirectory(prefix='pkpd-revision-draft-') as folder:
            root = Path(folder); work = root/'context_work'
            write_json(work/'accepted/context.json', accepted)
            write_json(work/'state.json', {'accepted':{'context':{'file':'accepted/context.json','sha256':digest(accepted)}}})
            write_json(work/'inputs.json', {'compression_profile':{'id':'LEAN_1.0'}, 'source_units':[]})
            write_json(work/'review.json', {'candidate_sha256':digest(candidate),'review':{'decision':'REVISE'}})
            write_json(work/'stopped.json', {'status':'REVISE','stage':'context_review','at':utcnow(),'response':'review.json'})
            feedback = context_feedback(root)
            self.assertEqual(feedback['prior_candidate'], candidate)
            bundle = {'compression_profile':{'version':'1.0','max_patches':0,'generation_instructions':'Revise against sources.',
                      'review_instructions':'Review against sources.', 'candidate_schema':{},'review_schema':{},
                      'revision_policy':lean.REVISION_POLICY,'revision_max_chars':140000},
                      'source_units':[], 'sources':[], 'revision':{'prior_candidate':feedback['prior_candidate']}}
            with patch('ctxcomp.lean_rules.attach'), patch('ctxcomp.lean_reference_normalization.verify'), \
                 patch('ctxcomp.engine.accepted_response',return_value=accepted), patch.object(lean,'validate_candidate'):
                generation = lean.request(work,bundle,{},'context')['payload']
                review = lean.request(work,bundle,{},'context_review')['payload']
            self.assertEqual(generation['revision_feedback']['prior_candidate'], candidate)
            self.assertNotIn('revision_feedback', review)
            write_json(work/'accepted/context.json', {**accepted,'context':{'objective':'changed'}})
            with self.assertRaisesRegex(ValueError, 'candidate changed'):
                context_feedback(root)

    def test_fresh_context_dispatch_has_completed_direct_intake(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory(prefix='pkpd-context-launch-') as folder:
            state = Path(folder)
            client = TestClient(app.create_app(state))
            imported = client.post('/workspace-api/examples/pmb/import').json()
            def spawn(command, **kwargs):
                job = Path(command[-1]).parent
                receipt = json.loads((job/'direct_intake.json').read_text())
                self.assertEqual(receipt['scheduler'], 'NONE')
                self.assertEqual(receipt['model_calls'], 0)
                self.assertEqual(receipt['context_builder_calls'], 0)
                self.assertTrue((job/'receipts/intake.json').is_file())
                plan = json.loads((job/'plan.json').read_text())
                self.assertEqual(plan['targets']['context'], 'project_rules_publish')
                self.assertEqual(plan['steps']['project_rules_prepare']['depends'], ['compress'])
                self.assertEqual(plan['steps']['project_rules_publish']['depends'], ['project_rules_prepare'])
                self.assertEqual(plan['steps']['project_rules_publish']['contract'].endswith('project_rules_publish.json'), True)
                self.assertEqual(plan['steps']['compress']['depends'], ['intake'])
                return SimpleNamespace(pid=None, poll=lambda: 0)
            with patch('research_pipeline.workbench.subprocess.Popen', side_effect=spawn) as worker, \
                 patch('research_pipeline.context_builder.build_context', side_effect=AssertionError('Intake called ContextBuilder')):
                result = client.post('/ui-api/jobs', json={
                    'upload_ids':[imported['upload']['upload_id']], 'stop_after':'context'})
                self.assertEqual(result.status_code, 202, result.text)
                self.assertEqual(worker.call_count, 1)
            client.close()

    def test_legacy_linear_failure_recovers_typed_error_only_for_current_attempt(self):
        from research_pipeline.execution_feedback import execution_feedback
        from research_pipeline.common import write_json
        with tempfile.TemporaryDirectory(prefix='pkpd-linear-stop-') as folder:
            root = Path(folder)
            stop = {'status':'ERROR', 'stage':'context', 'reason':'Provider returned no response',
                    'error_code':'MODEL_RESPONSE_UNAVAILABLE', 'model_call':None}
            write_json(root/'context_work/stopped.json', stop)
            write_json(root/'context_work/contextbuilder_linear/execution_stop.json', stop)
            write_json(root/'context_work/audit/model_calls/test/context/call.json',
                       {'at':'2026-01-02T00:00:00+00:00','stage':'context','status':'RETURNED'})
            current = execution_feedback(root, 'Provider failed', '2026-01-01T00:00:00+00:00')
            self.assertEqual(current['code'], 'MODEL_RESPONSE_UNAVAILABLE')
            self.assertTrue(current['retry_supported'])
            stale = execution_feedback(root, 'Provider failed', '2099-01-01T00:00:00+00:00')
            self.assertEqual(stale['code'], 'EXECUTION_FAILED')
            self.assertFalse(stale['retry_supported'])

    def test_explicit_revision_feedback_is_preserved_as_metadata(self):
        from research_pipeline import context_builder as cb
        from research_pipeline.common import PipelineError
        config = json.loads(cb.CONFIG.read_text(encoding='utf-8'))
        payload = {key: [] for key in config['routes']['compression.extract']['required']}
        payload.update(stage='context', instructions='Extract source-bound context.',
                       revision_feedback={'guidance': 'Retain one owner for each source proposition.'},
                       revision_policy='Administrative feedback is not scientific evidence.')
        bundle = cb.build_context('compression', 'extract', payload, {'type': 'object'})
        cb.verify_bundle(bundle)
        self.assertEqual(bundle['request']['payload']['revision_feedback'], payload['revision_feedback'])
        self.assertEqual(bundle['context_manifest']['sections']['revision_feedback']['kind'], 'task_metadata')
        with self.assertRaises(PipelineError):
            cb.build_context('compression', 'extract', {**payload, 'unregistered_instruction': True}, {'type': 'object'})

    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='pkpd-connected-')
        cls.state = Path(cls.temp.name)
        cls.client = TestClient(app.create_app(cls.state))

    @classmethod
    def tearDownClass(cls):
        cls.client.close()
        cls.temp.cleanup()

    def test_examples_are_byte_bound_and_parseable(self):
        import hashlib
        examples = self.client.get('/workspace-api/examples').json()
        self.assertEqual({e['id'] for e in examples}, {'pmb', 'meropenem', 'voriconazole'})
        for example in examples:
            with self.subTest(example=example['id']):
                data = self.client.get(example['url']).content
                self.assertEqual(hashlib.sha256(data).hexdigest(), example['sha256'])
                with ZipFile(io.BytesIO(data)) as archive:
                    self.assertEqual(len(archive.namelist()), 3)
                    for member in example['members']:
                        self.assertEqual(hashlib.sha256(archive.read(member['name'])).hexdigest(), member['sha256'])
                imported = self.client.post('/workspace-api/examples/' + example['id'] + '/import').json()
                response = self.client.post('/workspace-api/imports/' + imported['id'] + '/inspect')
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(len(response.json()['manifest']['files']), 3)
                self.assertEqual(response.json()['scientific_qc'], 'NOT_RUN')
                self.assertFalse(response.json()['scientific_approval'])

    def test_direct_intake_does_not_call_builder_model_or_scheduler(self):
        imported = self.client.post('/workspace-api/examples/pmb/import').json()
        path = '/ui-api/workflow/sessions/' + imported['id']
        with patch('research_pipeline.workbench.subprocess.Popen', side_effect=AssertionError('Scheduler launched')), \
             patch('research_pipeline.context_builder.build_context', side_effect=AssertionError('ContextBuilder called')), \
             patch('ctxcomp.providers.codex_generate', side_effect=AssertionError('Model called')):
            response = self.client.post(path + '/nodes/intake/start', json={})
            self.assertEqual(response.status_code, 202, response.text)
            value = self.client.get(path).json()
        intake = next(n['state'] for n in value['nodes'] if n['id'] == 'intake')
        context = next(n['state'] for n in value['nodes'] if n['id'] == 'context')
        self.assertEqual(intake['execution'], 'COMPLETED')
        self.assertTrue(intake['approved'])
        self.assertFalse(intake['automatic_validation']['scientific_acceptance'])
        self.assertTrue(context['can_run'])
        job_id = json.loads((self.state/'workbench_state/canvas_sessions'/imported['id']/'session.json').read_text())['job_id']
        status = json.loads((self.state/'workbench_state/workbench_jobs'/job_id/'status.json').read_text())
        self.assertEqual((status['scheduler'], status['context_builder_calls'], status['model_calls']), ('NONE', 0, 0))

    def test_data_cannot_skip_context_or_approve_missing_outputs(self):
        imported = self.client.post('/workspace-api/examples/pmb/import').json()
        base = '/ui-api/workflow/sessions/' + imported['id']
        self.assertEqual(self.client.post(base+'/nodes/adequacy/start', json={}).status_code, 409)
        self.assertEqual(self.client.post(base+'/nodes/context/review', json={
            'decision':'APPROVE', 'reviewer':'Test', 'output_signature':'0'*64, 'confirmed':True,
            'objective_decision':'CONFIRMED'}).status_code, 409)

    def test_zip_upload_is_persisted_across_restart(self):
        data=(ROOT/'examples/inputs/PMB_example_inputs.zip').read_bytes()
        result=self.client.post('/workspace-api/imports', files={'file':('input.zip', data, 'application/zip')})
        self.assertEqual(result.status_code, 201, result.text)
        with TestClient(app.create_app(self.state)) as reopened:
            self.assertEqual(reopened.get('/workspace-api/imports/'+result.json()['id']).json()['upload']['sha256'], result.json()['upload']['sha256'])

    def test_unsafe_zip_is_rejected_without_escaping(self):
        stream=io.BytesIO()
        with ZipFile(stream, 'w') as archive:
            archive.writestr('../escaped.txt','not allowed')
        imported=self.client.post('/workspace-api/imports',files={'file':('bad.zip',stream.getvalue(),'application/zip')}).json()
        response=self.client.post('/workspace-api/imports/'+imported['id']+'/inspect')
        self.assertEqual(response.status_code,422,response.text)
        self.assertFalse((self.state/'escaped.txt').exists())

    def test_real_source_preparation_preserves_review_gate(self):
        imported=self.client.post('/workspace-api/examples/pmb/import').json()
        base='/workspace-api/imports/'+imported['id']
        self.assertEqual(self.client.post(base+'/organize',json={}).status_code,409)
        self.client.post(base+'/inspect')
        response=self.client.post(base+'/organize',json={})
        self.assertEqual(response.status_code,200,response.text)
        result=response.json()['source_preparation']
        self.assertEqual(result['status'],'WAITING_FOR_REVIEW',json.dumps(result.get('errors')))
        # Raw workbook extraction includes 63 regions; the recorded reviewed
        # Data run contains a scoped subset of 58 datasets.
        self.assertEqual(len(result['tables']),63)
        self.assertTrue(all(t['fit_ready'] is False for t in result['tables']))
        table=result['tables'][0]
        self.assertEqual(self.client.get('/pipeline/v1/source-preparations/'+result['id']+'/files/'+table['records_path']).status_code,200)

    def test_sol6_high_is_passed_to_cli_and_bound_to_identity(self):
        from ctxcomp import providers
        captured = {}
        def transport(request, provider, command_for, response_from, model, *args, **kwargs):
            captured['command'] = command_for(self.state/'cli-test')
            return {'ok': True}
        with patch.dict('os.environ', {'CTXCOMP_MODEL_PROVIDER':'codex', 'CTXCOMP_CODEX_MODEL':'gpt-6-sol', 'CTXCOMP_CODEX_REASONING_EFFORT':'high'}), \
             patch.object(providers.shutil, 'which', return_value='codex.exe'), \
             patch.object(providers, 'cli_call', side_effect=transport):
            providers.codex_generate({'request_sha256':'unused-test', 'payload':{'schema':{'type':'object'}}})
            self.assertEqual(providers.executor_identity()['requested_reasoning_effort'], 'high')
        command = captured['command']
        self.assertEqual(command[command.index('--model')+1], 'gpt-6-sol')
        self.assertIn('model_reasoning_effort="high"', command)


if __name__=='__main__':
    unittest.main(verbosity=2)
