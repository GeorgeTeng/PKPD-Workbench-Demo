"""Synthetic adequacy contracts; fake model outputs are labeled fixtures, never research results."""
import copy
import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from research_pipeline import adequacy as a
from research_pipeline.common import read_json, write_json, PipelineError
from research_pipeline.workflow_canvas import fingerprint
from research_pipeline.workflow_runtime import make_plan, execute_contract
from research_pipeline.workbench import create_workbench
from research_pipeline.graph_execution import run_controlled


@pytest.fixture
def inputs(tmp_path):
    data=tmp_path/'renamable.csv'; data.write_text('animal_id,time_h,total_mg_L\nSENTINEL_BODY,1,999999.123\n',encoding='utf-8')
    reference=tmp_path/'heldout.json'; reference.write_text('NEVER_SEND_BENCHMARK',encoding='utf-8')
    def attachment(path,id,role,kind):
        return {'id':id,'name':path.name,**a.file_ref(path),'kind':kind,'role':role,
            'receivers':['validation' if role=='REFERENCE_ONLY' else 'data_preparation'],
            'read_status':'READ_COMPLETE','qc_status':'NOT_RUN','fit_ready':False}
    main={'version':'3.0','objective':'Estimate animal clearance; compare free exposure indices.',
        'study':dict(drug='Synthetic drug',regimen='IV',population='rat',system='plasma',
            measurements='time and concentration',methods='compartment modeling'),
        'data':{'available':['Candidate PK table'],'required':['Individual PK; free fraction before index fitting'],
            'files':[attachment(data,'F1','DATA_CANDIDATE','csv'),attachment(reference,'F2','REFERENCE_ONLY','json')]},
        'rules':['R001: Freeze MIC before index fitting.'],'checks':['Preserve units'], 'uncertainties':['Free fraction unavailable']}
    path=write_json(tmp_path/'main.json',main)
    inventory_path=tmp_path/'run/adequacy/inventory.json'; inventory=a.inspect_inputs(path,inventory_path)
    return tmp_path/'run',path,inventory_path,main,inventory


def assessment(request, **kwargs):
    p=request['payload']; item=p['inventory']['items'][0]
    span=[{'path':'/objective','quote':p['main']['objective']}]
    need={'id':'N1','task_id':'T1','description':'Candidate PK observations','kind':'DATA','required_by':'BEFORE_QC',
        'origin':'EXPLICIT_CONTEXT','applicability':'REQUIRED','condition':'Always','context_evidence':span,
        'status':'AVAILABLE_CANDIDATE','inventory_evidence':[{'item_id':item['id'],'quote':'time_h'}],
        'reason':'A nonempty candidate table contains a time header; values remain unverified.','needed_material':'QC and mapping'}
    future={**need,'id':'N2','description':'Unbound fraction','kind':'METADATA','required_by':'BEFORE_MODELING',
        'status':'MISSING','inventory_evidence':[],'reason':'Not established from inspected metadata.',
        'needed_material':'Provide a species-specific free fraction measurement and source.'}
    return {'request_sha256':request['request_sha256'],'tasks':[{'id':'T1','question':p['main']['objective'],
        'estimand':'CL','species':p['main']['study']['population'],'endpoint':'concentration','endpoint_window':'NOT_FOUND',
        'units':'NOT_FOUND','exposure_basis':'total','context_evidence':span}],
        'requirements':[need,future],'limitations':['Synthetic fixture. Metadata do not establish reliable estimates.']}


def review(request, **kwargs):
    p=request['payload']; draft=p['assessment']
    return {'request_sha256':request['request_sha256'],'decision':'PASS',
        'task_checks':[{'id':x['id'],'verdict':'SUPPORTED','reason':'Synthetic check'} for x in draft['tasks']],
        'requirement_checks':[{'id':x['id'],'verdict':'SUPPORTED','reason':'Synthetic check'} for x in draft['requirements']],
        'context_coverage':[{'path':x,'verdict':'COVERED','reason':'Synthetic check'} for x in p['required_context_paths']],
        'findings':[],'limitations':['Synthetic independent review; not evidence of LLM accuracy.']}


def complete(inputs, reviewer=review):
    run,path,ip,main,inventory=inputs
    draft=a.call_stage(run,'adequacy_assessment',path,ip,generator=assessment)
    dp=write_json(run/'adequacy/assessment.json',draft)
    checked=a.call_stage(run,'adequacy_review',path,ip,dp,generator=reviewer)
    return a.finalize(run,path,ip,dp,checked)


def test_model_input_scoped_to_metadata_and_every_context_leaf(inputs):
    run,path,ip,main,inventory=inputs
    request=a.model_request('adequacy_assessment',main,inventory)
    text=json.dumps(request)
    assert 'SENTINEL_BODY' not in text and '999999.123' not in text and 'NEVER_SEND_BENCHMARK' not in text
    assert str(path) not in text and 'renamable.csv' not in text
    assert '/rules/0' in request['payload']['required_context_paths']
    other=copy.deepcopy(main); other['study'].update(drug='Different drug',population='rabbit')
    assert a.model_request('adequacy_assessment',other,inventory)['request_sha256']!=request['request_sha256']
    assert assessment(a.model_request('adequacy_assessment',other,inventory))['tasks'][0]['species']=='rabbit'
    assert inventory['items'][0]['animal_count']=='NOT_ESTABLISHED'


def test_later_gap_does_not_claim_model_adequacy(inputs):
    report=complete(inputs)
    assert report['can_enter_qc'] and not report['requires_human_review']
    assert not report['fit_ready'] and not report['human_prediction_validated']
    assert report['missing_materials'][0]['required_by']=='BEFORE_MODELING'
    qc=read_json(inputs[0]/'adequacy/qc_context.json')
    assert len(qc['files'])==1 and 'REFERENCE_ONLY' not in str(qc['files'])
    assert 'objective' not in qc and not qc['fit_ready']


@pytest.mark.parametrize('mutation', ['bad_quote','missing_rule','false_pass','duplicate_task'])
def test_invalid_independent_review_never_releases(inputs,mutation):
    def invalid(req,**kw):
        r=review(req)
        if mutation=='missing_rule': r['context_coverage']=[x for x in r['context_coverage'] if x['path']!='/rules/0']
        if mutation=='duplicate_task': r['task_checks']*=2
        if mutation=='false_pass': r['requirement_checks'][0]['verdict']='UNRESOLVED'
        if mutation=='bad_quote': r['findings']=[{'code':'X','required_by':'BEFORE_QC','severity':'FOLLOW_UP',
            'reason':'Bad evidence','needed_material':'Data','context_evidence':[{'path':'/objective','quote':'invented'}],'inventory_evidence':[]}]
        return r
    with pytest.raises(ValueError): complete(inputs,invalid)
    assert not (inputs[0]/'adequacy/adequacy.json').exists()
    assert read_json(inputs[0]/'adequacy/stopped.json')['error_code']==(
        'MODEL_CHECKLIST_MISMATCH' if mutation in {'missing_rule','duplicate_task'} else 'MODEL_REVIEW_INVALID')


def test_missing_current_data_and_review_details_are_explicit(inputs):
    def human(req,**kw):
        r=review(req);r['decision']='NEEDS_REVIEW';r['requirement_checks'][0].update(verdict='UNRESOLVED',reason='Confirm dosing route')
        return r
    report=complete(inputs,human)
    assert report['assessment_status']=='NOT_CALCULABLE' and not report['can_enter_qc']
    assert 'Confirm dosing route' in str(report['why_cannot_pass'])


def test_nonempty_catalog_is_not_observation_evidence(inputs):
    _,_,_,main,inventory=inputs
    inventory['items'][0]['file_role']='MODEL_CATALOG'
    request=a.model_request('adequacy_assessment',main,inventory)
    with pytest.raises(ValueError,match='catalog'): a.validate_assessment(assessment(request),request,main,inventory)


def test_empty_table_cannot_be_available_data(inputs):
    _,_,_,main,inventory=inputs; inventory['items'][0]['candidate_body_rows']=0
    request=a.model_request('adequacy_assessment',main,inventory)
    with pytest.raises(ValueError,match='nonempty'): a.validate_assessment(assessment(request),request,main,inventory)


def test_changed_input_and_unavailable_model_stop(inputs):
    run,path,ip,main,_=inputs
    def unavailable(*args,**kwargs): raise RuntimeError('Synthetic model unavailable')
    with pytest.raises(RuntimeError): a.call_stage(run,'adequacy_assessment',path,ip,generator=unavailable)
    assert not (run/'adequacy/adequacy.json').exists()
    Path(main['data']['files'][0]['path']).write_text('changed')
    with pytest.raises(PipelineError,match='changed'): a.call_stage(run,'adequacy_assessment',path,ip,generator=assessment)


def test_real_file_contract_chain_and_qc_gate(inputs,tmp_path,monkeypatch):
    run,path,ip,main,_=inputs
    # Synthetic human decision with a real LangGraph interrupt/checkpoint.
    app=create_workbench(tmp_path,tmp_path/'state'); store=app.state.canvas; client=TestClient(app)
    sid=client.post('/ui-api/workflow/sessions').json()['session_id']; s=store.load(sid)
    p=write_json(tmp_path/'intake.json',{'test_fixture':True})
    store.record_completion(s,'intake',[{'name':'manifest.json',**a.file_ref(p)}])
    store.record_completion(s,'context',[{'name':'main.json',**a.file_ref(path)}]); write_json(store.path(sid),s)
    resp=client.post(f'/ui-api/workflow/sessions/{sid}/nodes/context/review',json={
        'decision':'APPROVE','reviewer':'Synthetic test only','output_signature':s['nodes']['context']['output_signature'],'confirmed':True,'objective_decision':'CONFIRMED'})
    assert resp.status_code==200
    node=store.load(sid)['nodes']['context']; assert node['langgraph_review']['status']=='APPROVED'
    approval=write_json(tmp_path/'approval.json',{'context':node})
    spec={'id':'fixture','mode':'reviewed_context','out':str(run),'job_dir':str(tmp_path/'job'),
        'approved_context':a.file_ref(approval),'stop_after':'adequacy'}
    plan=make_plan(spec); assert plan['steps']['adequacy_review']['depends']==['adequacy_assessment']
    monkeypatch.setattr(a,'codex_generate',lambda req,**kw: assessment(req) if req['payload']['stage']=='adequacy_assessment' else review(req))
    original=a.file_ref(path)
    for stage in ['reviewed_context','adequacy_inventory','adequacy_assessment','adequacy_review']:
        execute_contract(plan['steps'][stage]['contract'])
    assert a.file_ref(path)==original
    assert read_json(tmp_path/'job/receipts/adequacy_review.json')['status']=='SUCCEEDED'
    report=run/'adequacy/adequacy.json'
    with pytest.raises(PipelineError,match='workflow'): a.verify_qc_gate(tmp_path/'job/qc_release.json',report)
    s=store.load(sid);store.record_completion(s,'adequacy',[{'name':'adequacy.json',**a.file_ref(report)}])
    assert store.dependency_ready(s,'adequacy') and not s['nodes']['adequacy']['requires_human_review']
    gate=write_json(tmp_path/'job/qc_release.json',{'adequacy':s['nodes']['adequacy']}); a.verify_qc_gate(gate,report)
    execute_contract(plan['steps']['sources']['contract'])
    source=read_json(run/'source_preparation/output.json')
    assert source['status']!='FAILED' and 'objective' not in source['context']
    assert source['context']['task_requirements'] and len(source['tables'])==1
    request=write_json(tmp_path/'job/request.json',spec)
    result=run_controlled(request,'adequacy',prefect_runner=lambda *x,**kw:{'status':'WAITING_FOR_HUMAN_REVIEW'})
    assert result['control']['disposition']=='READY_FOR_QC'
    assert result['control']['scheduler']=='Prefect' and not result['control']['diagnostics']['scientific_accepted']
    write_json(report,{**read_json(report),'can_enter_qc':False})
    with pytest.raises(PipelineError): a.verify_qc_gate(gate,report)


def test_canvas_starts_new_scoped_job_and_preserves_context_approval(inputs,tmp_path):
    app=create_workbench(tmp_path,tmp_path/'state'); store=app.state.canvas; client=TestClient(app)
    sid=client.post('/ui-api/workflow/sessions').json()['session_id']; s=store.load(sid)
    p=write_json(tmp_path/'intake.json',{'fixture':True})
    store.record_completion(s,'intake',[{'name':'manifest.json',**a.file_ref(p)}])
    store.record_completion(s,'context',[{'name':'main.json',**a.file_ref(inputs[1])}]);s['job_id']='prior_job'
    write_json(store.path(sid),s)
    client.post(f'/ui-api/workflow/sessions/{sid}/nodes/context/review',json={
        'decision':'APPROVE','reviewer':'Synthetic test only','output_signature':s['nodes']['context']['output_signature'],'confirmed':True,'objective_decision':'CONFIRMED'})
    original=copy.deepcopy(store.load(sid)['nodes']['context']); calls=[]
    store.launch_adequacy=lambda session: calls.append(session['nodes']['context']['output_signature']) or {'id':'scoped_job'}
    store.job_status=lambda _: {'status':'RUNNING'}
    response=client.post(f'/ui-api/workflow/sessions/{sid}/nodes/adequacy/start',json={})
    assert response.status_code==202 and calls==[original['output_signature']]
    s=store.load(sid)
    assert s['job_id']=='scoped_job' and s['job_history']==['prior_job'] and store.owns_job('prior_job')
    assert s['nodes']['context']==original and s['nodes']['adequacy']['requires_control_trace']
    assert client.post(f'/ui-api/workflow/sessions/{sid}/nodes/prepare/start',json={}).status_code==409


def test_xlsx_body_and_reference_content_are_not_sent(inputs,tmp_path):
    from openpyxl import Workbook
    from openpyxl.worksheet.table import Table
    main=inputs[3]; p=tmp_path/'renamed.xlsx';w=Workbook();s=w.active;s.title='Human_PK'
    s.append(['time_h','concentration_mg_L']);s.append(['SECRET_HELDOUT_BODY','876543.21'])
    s.add_table(Table(displayName='HumanValidationPK',ref='A1:B2'));w.save(p)
    main['data']['files'][0].update(**a.file_ref(p),kind='xlsx',name=p.name)
    write_json(inputs[1],main); inventory=a.inspect_inputs(inputs[1],inputs[2])
    text=json.dumps(a.model_request('adequacy_assessment',main,inventory))
    assert 'SECRET_HELDOUT_BODY' not in text and '876543.21' not in text and 'NEVER_SEND_BENCHMARK' not in text
    assert 'HumanValidationPK' in text and 'time_h' in text


def test_scientific_prompt_schema_and_validator_share_exact_path_list(inputs):
    from ctxcomp.io import leaves
    from ctxcomp.schemas import validate_schema
    main,inventory=inputs[3:]; request=a.model_request('adequacy_assessment',main,inventory)
    assert 'version' not in request['payload']['main']
    assert set(request['payload']['required_context_paths'])=={p for p,_ in leaves(request['payload']['main'])}
    draft=assessment(request); rr=a.model_request('adequacy_review',main,inventory,draft)
    coverage=rr['payload']['schema']['properties']['context_coverage']
    assert coverage['items']['properties']['path']['enum']==rr['payload']['required_context_paths']
    assert coverage['minItems']==coverage['maxItems']==len(a.context_values(main))
    good=review(rr); validate_schema(good,rr['payload']['schema']); a.validate_review(good,rr,draft,main,inventory)
    bad=copy.deepcopy(good);bad['context_coverage'].append({'path':'/version','verdict':'NOT_A_DATA_REQUIREMENT','reason':'Format marker'})
    with pytest.raises(ValueError): validate_schema(bad,rr['payload']['schema'])
    with pytest.raises(a.ModelProviderError) as exc: a.validate_review(bad,rr,draft,main,inventory)
    assert exc.value.code=='MODEL_CHECKLIST_MISMATCH'
    assert exc.value.validation_details=={'field':'path','missing':[],'unexpected':['/version'],'duplicates':[]}
    # The shared template must not acquire the first project's path/ID enums.
    assert 'enum' not in a.REVIEW_SCHEMA['properties']['context_coverage']['items']['properties']['path']


def test_scope_amendment_preserves_original_and_reaches_both_model_requests(inputs,tmp_path):
    from research_pipeline.scope_amendments import apply_amendment
    app=create_workbench(tmp_path,tmp_path/'state');store=app.state.canvas;client=TestClient(app)
    sid=client.post('/ui-api/workflow/sessions').json()['session_id'];s=store.load(sid)
    p=write_json(tmp_path/'intake.json',{'fixture':True})
    store.record_completion(s,'intake',[{'name':'manifest.json',**a.file_ref(p)}])
    store.record_completion(s,'context',[{'name':'main.json',**a.file_ref(inputs[1])}]);write_json(store.path(sid),s)
    client.post(f'/ui-api/workflow/sessions/{sid}/nodes/context/review',json={
        'decision':'APPROVE','reviewer':'Synthetic test only','output_signature':s['nodes']['context']['output_signature'],'confirmed':True,'objective_decision':'CONFIRMED'})
    s=store.load(sid);original=a.file_ref(inputs[1]);before=s['nodes']['context']
    body={'context_signature':before['output_signature'],'instruction':'Human binding for final validation only.',
        'submitted_by':'Synthetic test only','confirmed':True,'changes':[{'path':'/rules/0',
        'before':inputs[3]['rules'][0],'after':'R001: Reserve human protein binding for final validation; freeze MIC before animal index fitting.'}]}
    endpoint=f'/ui-api/workflow/sessions/{sid}/scope-amendments'
    denied={**body,'changes':[{'path':'/version','before':'3.0','after':'4.0'}]}
    assert client.post(endpoint,json=denied).status_code==422
    assert client.post(endpoint,json={**body,'confirmed':False}).status_code==422
    assert client.post(endpoint,json=body).status_code==200
    s=store.load(sid);assert s['nodes']['context']==before and a.file_ref(inputs[1])==original
    approval=write_json(tmp_path/'approval.json',{'context':before,'scope_amendment':s['scope_amendment']})
    output=tmp_path/'new/B1/main.json'; effective=a.import_reviewed_context(a.file_ref(approval),output)
    assert effective['rules'][0]==body['changes'][0]['after']
    assert store.project_rules(s)==effective['rules']
    assert (output.parent/'context_provenance.json').is_file()
    ip=tmp_path/'new/adequacy/inventory.json'; inventory=a.inspect_inputs(output,ip)
    req=a.model_request('adequacy_assessment',effective,inventory);draft=assessment(req)
    rr=a.model_request('adequacy_review',effective,inventory,draft)
    assert req['payload']['main']['rules']==rr['payload']['main']['rules']==effective['rules']
    amendment=read_json(s['scope_amendment']['path'])
    changed=copy.deepcopy(inputs[3]);changed['rules'][0]='R001: Changed'
    with pytest.raises(ValueError,match='stale'): apply_amendment(changed,amendment)
    s['nodes']['adequacy']['execution']='RUNNING';write_json(store.path(sid),s)
    store.job_status=lambda _: {'status':'RUNNING'}
    assert client.post(endpoint,json=body).status_code==409


def test_checklist_diagnosis_is_not_a_missing_data_request(inputs):
    from research_pipeline.execution_feedback import execution_feedback
    def extra(req,**kw):
        r=review(req);r['context_coverage'].append({'path':'/version','verdict':'NOT_A_DATA_REQUIREMENT','reason':'Format version'})
        return r
    with pytest.raises(ValueError): complete(inputs,extra)
    f=execution_feedback(inputs[0],'failure',stage='adequacy')
    assert f['code']=='MODEL_CHECKLIST_MISMATCH' and f['proposal_change_required'] is False
    assert f['missing_materials']==[] and f['validation_details']['unexpected']==['/version']
    assert 'Missing checklist fields: None' in f['known_facts'] and f['retry_supported']


def test_cc004_objective_decision_gates_context_and_correction_reaches_adequacy(inputs,tmp_path):
    app=create_workbench(tmp_path,tmp_path/'state');store=app.state.canvas;client=TestClient(app)
    sid=client.post('/ui-api/workflow/sessions').json()['session_id'];s=store.load(sid)
    p=write_json(tmp_path/'intake.json',{'fixture':True})
    store.record_completion(s,'intake',[{'name':'manifest.json',**a.file_ref(p)}])
    store.record_completion(s,'context',[{'name':'main.json',**a.file_ref(inputs[1])}]);write_json(store.path(sid),s)
    endpoint=f'/ui-api/workflow/sessions/{sid}/nodes/context/review'
    base={'reviewer':'Synthetic test only','output_signature':s['nodes']['context']['output_signature'],'confirmed':True}
    corrected='Estimate animal clearance and volume; compare free exposure indices.'
    for body in [{'decision':'APPROVE'},  # No objective judgement.
                 {'decision':'APPROVE','objective_decision':'OFF_SCOPE'},
                 {'decision':'REQUEST_CHANGES','rationale':'Objective drifts','objective_decision':'CORRECTED','objective_correction':corrected},
                 {'decision':'APPROVE','objective_decision':'CONFIRMED','objective_correction':corrected},
                 {'decision':'APPROVE','objective_decision':'CORRECTED','objective_correction':corrected},  # No rationale.
                 {'decision':'APPROVE','objective_decision':'CORRECTED','rationale':'Same text',
                  'objective_correction':inputs[3]['objective']}]:
        assert client.post(endpoint,json={**base,**body}).status_code==422, body
    s=store.load(sid);s['project_rules_ref']={'path':'not-loaded','sha256':'not-loaded'};write_json(store.path(sid),s)
    published={**base,'decision':'APPROVE','objective_decision':'CORRECTED','rationale':'Volume was requested too',
               'objective_correction':corrected}
    assert client.post(endpoint,json=published).status_code==409  # Rules were reviewed against the original objective.
    s=store.load(sid);s.pop('project_rules_ref');write_json(store.path(sid),s)
    assert store.load(sid)['nodes']['context']['execution']=='COMPLETED' and not store.load(sid).get('scope_amendment')
    response=client.post(endpoint,json=published)
    assert response.status_code==200
    s=store.load(sid);review=s['nodes']['context']['review']
    assert review['objective_decision']=='CORRECTED' and review['objective_correction']==corrected
    amendment=read_json(s['scope_amendment']['path'])
    assert amendment['origin']=='CC004_CONTEXT_REVIEW' and amendment['changes']==[
        {'path':'/objective','before':inputs[3]['objective'],'after':corrected}]
    assert read_json(inputs[1])['objective']==inputs[3]['objective']  # Original handoff is never edited.
    approval=write_json(tmp_path/'approval.json',{'context':s['nodes']['context'],'scope_amendment':s['scope_amendment']})
    effective=a.import_reviewed_context(a.file_ref(approval),tmp_path/'new/B1/main.json')
    assert effective['objective']==corrected
    assert any(e['action']=='USER_OBJECTIVE_CORRECTED' for e in s['events'])
