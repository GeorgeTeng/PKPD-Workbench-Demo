"""Direct human approval -> DP integration; isolated synthetic data, no providers.

Uses the real DirectDataReview HTTP decision path. Provider execution metadata is
simulated only in isolated fixtures with exact receipt replay and renewed hashes.
No legacy DC scientific PASS or legacy human approval is fabricated.
"""
import copy
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from research_pipeline import data_agents as d
from research_pipeline import data_coverage_direct as coverage
from research_pipeline import data_necessity_direct as necessity
from research_pipeline import data_direct_workflow as workflow
from research_pipeline.common import PipelineError, read_json, write_json
from research_pipeline.preparation_workflow import require_dp_approval
from research_pipeline.workbench import create_workbench
from test_data_agents import case as table_case, requirements
from test_data_coverage_direct import answer as coverage_answer
from test_data_necessity_direct import answer as necessity_answer
from test_data_direct_review import decision


@pytest.fixture
def direct_checkpoint(table_case, tmp_path, monkeypatch):
    _, run, main, inventory, generator, calls = table_case
    req = run/'requirements.json'
    labels = run/'labels.json'
    requirements(run, main, inventory, req, generator)
    d.label(run, main, inventory, req, labels, generator=generator)
    inv = read_json(inventory)
    permissions = read_json(req)['access']
    allowed = {p['item_id'] for p in permissions if p['disposition']=='REVIEW_DATA'}
    profiles = []
    units = {}
    for label in read_json(labels)['labels']:
        if label['item_id'] not in allowed:
            continue
        profile = {k:copy.deepcopy(v) for k,v in label.items()
                   if k not in {'evidence','requirement_ids','reason'}}
        column_sources={e['source'] for column in label['columns'] for e in column['evidence']}
        # Overall label evidence need not repeat all original column evidence.
        profile['evidence_source_ids'] = [e['source'] for e in label['evidence']
                                          if e['source'] not in column_sources]
        for span in label['evidence']:
            if span['source']==label['item_id']:
                units[span['source']]=span['quote']
        profiles.append(profile)
    for item in inv['items']:
        if item['id'] in allowed:
            units.update(d.content_units(item))
    source = write_json(tmp_path/'source_view.json', {
        'main_ref':d.file_ref(main), 'profiles':profiles,
        'permissions':permissions, 'source_units':units})
    plan = write_json(tmp_path/'plan.json', {
        'bindings':{'main':d.file_ref(main), 'source_view':d.file_ref(source),
                    'inventory':d.file_ref(inventory)},
        'requirements':[{'id':'RQ1','description':'Keep measured concentration and time.',
                         'input_fields':['time','concentration'], 'conditions':[]}],
        'scientific_approval':False, 'can_enter_qc':False, 'fit_ready':False})
    mp = write_json(tmp_path/'mp.json', {'profiles':[{'id':'MP004'}]})
    result_run = tmp_path/'direct'
    def generate(request, **kwargs):
        return (coverage_answer if request['payload']['stage']=='DIRECT_DR_COVERAGE'
                else necessity_answer)(request)
    workflow.run_legacy(plan, source, main, mp, result_run, generator=generate)
    # Isolated simulation of real execution metadata, including exact receipt
    # replay and renewed downstream hashes. These remain synthetic test files.
    cov_path=result_run/'coverage/coverage.json'
    cov=coverage.verify_result(cov_path)
    for ref in cov['provenance']['accepted_receipts']:
        receipt=read_json(ref['path']);receipt['test_generator']=False
        write_json(ref['path'],receipt)
    build,catalog=coverage.verify_prepared(cov_path.parent)
    cov=coverage._result(cov_path.parent,build,catalog)
    write_json(cov_path,cov)
    assert coverage.verify_result(cov_path)==cov
    nec_folder=result_run/'necessity_real_fixture'
    necessity.prepare(cov_path,main,mp,nec_folder)
    nec=necessity.run_prepared(nec_folder,generator=necessity_answer)
    receipt=read_json(nec_folder/'call/accepted.json');receipt['test_generator']=False
    write_json(nec_folder/'call/accepted.json',receipt)
    nec['execution']['test_generator']=False
    nec_path=write_json(nec_folder/'necessity.json',nec)
    assert necessity.verify_result(nec_path)==nec
    write_json(result_run/'necessity_ref.json',d.file_ref(nec_path))
    workflow.report(result_run,cov,nec,nec_path)
    app = create_workbench(tmp_path, tmp_path/'state')
    store = app.state.direct_data_reviews
    gate = store.publish(result_run)
    return {'client':TestClient(app), 'store':store, 'gate':gate,
            'review_path':store.path(gate['id']), 'source':source, 'inventory':inventory,
            'labels':labels, 'main':main, 'calls':calls, 'root':tmp_path,
            'cov_path':cov_path, 'nec_path':nec_path,'result_run':result_run}


def import_checkpoint(checkpoint):
    from research_pipeline.direct_preparation import import_inputs
    output = checkpoint['root']/'dp_inputs/context.json'
    import_inputs(d.file_ref(checkpoint['review_path']), output)
    return output


def approve(checkpoint):
    response = checkpoint['client'].post(
        '/ui-api/data-reviews/'+checkpoint['gate']['id']+'/review',
        json=decision(checkpoint['gate']))
    assert response.status_code==200,response.text
    assert response.json()['approved'] is True


def test_direct_review_listing_and_explicit_automation_launch(direct_checkpoint, monkeypatch):
    import research_pipeline.workbench as workbench
    c=direct_checkpoint
    assert c['client'].get('/ui-api/data-reviews').json()['reviews'][0]['id']==c['gate']['id']
    # The API launches the real worker contract, while this regression test does
    # not execute a scientific or model pipeline.
    class Process:
        pid=123456
        def poll(self): return None
    monkeypatch.setattr(workbench.subprocess,'Popen',lambda *args,**kwargs:Process())
    endpoint='/ui-api/data-reviews/'+c['gate']['id']+'/preparation'
    denied=c['client'].post(endpoint,json={'confirmed_user_authorization':True})
    assert denied.status_code==422
    started=c['client'].post(endpoint,json={'confirmed_user_authorization':True,
        'auto_approve_human_gates':True,'model':'gpt-6-luna'})
    assert started.status_code==202,started.text
    review=read_json(c['review_path'])
    assert review['review']['reviewer']=='USER_AUTHORIZED_AUTOMATION'
    assert review['review']['confirmed'] is True and review['review']['at']
    assert 'explicitly enabled auto_approve_human_gates' in review['review']['rationale']
    spec=read_json(c['root']/'state'/'workbench_jobs'/started.json()['id']/'request.json')
    assert spec['launch_authorization']['user_authorized_automation'] is True
    assert spec['launch_authorization']['auto_approve_human_gates'] is True
    assert c['client'].get('/ui-api/direct-preparations').json()['jobs'][0]['id']==started.json()['id']


def test_compressed_context_requires_first_part_v4_contract(tmp_path):
    import json
    from research_pipeline.common import write_json
    app=create_workbench(tmp_path/'outputs',tmp_path/'state');client=TestClient(app)
    job='PMB_UI_CONTEXT_TEST';run=tmp_path/'outputs'/job;write_json(run/'B1/main.json',{'version':'3.0'})
    folder=tmp_path/'state'/'workbench_jobs'/job;folder.mkdir(parents=True)
    write_json(folder/'request.json',{'id':job,'mode':'fresh','out':str(run)})
    write_json(folder/'status.json',{'id':job,'status':'COMPLETED'})
    response=client.post('/ui-api/jobs/'+job+'/pre-eda',json={
        'confirmed_user_authorization':True,'auto_approve_human_gates':True})
    assert response.status_code==409
    assert 'First Part v4 handoff' in response.json()['detail']
    assert client.get('/ui-api/first-part-mains').json()=={'mains':[]}


def test_rules_pre_eda_report_and_status_artifacts_follow_data_chain_path(tmp_path):
    from research_pipeline.common import write_json
    outputs=tmp_path/'outputs';state=tmp_path/'state';app=create_workbench(outputs,state);client=TestClient(app)
    job='PMB_RULES_PRE_EDA_TEST';run=outputs/job
    report=write_json(run/'data_chain/cleaning/data_preparation/data_report.json',{
        'preparation_policy':'DATASET_ACTION_V1','status':'PARTIALLY_READY',
        'technical_processing_complete':True,'cleaning_complete':True,'fit_ready':False,
        'scientific_release':False,'dataset_action_readiness':[{'dataset_id':'d1','source_item_id':'s1',
            'actions':{'DESCRIPTIVE_EDA':{'status':'READY','reasons':[]}}}]})
    write_json(run/'pre_eda_status.json',{'status':'COMPLETED_TO_CLEANING','scientific_release':False})
    folder=state/'workbench_jobs'/job;folder.mkdir(parents=True)
    write_json(folder/'request.json',{'id':job,'mode':'fresh_pre_eda_from_rules','out':str(run)})
    write_json(folder/'status.json',{'id':job,'status':'COMPLETED','created_at':'2026-10-15T00:00:00Z'})
    status=client.get('/ui-api/jobs/'+job).json()
    assert 'data_report' in status['artifacts'] and 'pre_eda_status' in status['artifacts']
    response=client.get('/ui-api/jobs/'+job+'/artifacts/data_report')
    assert response.status_code==200 and response.json()['dataset_action_readiness'][0]['dataset_id']=='d1'
    listed=client.get('/ui-api/direct-preparations').json()['jobs']
    item=next(row for row in listed if row['id']==job)
    assert item['report_available'] is True
    assert client.get(item['report_url']).json()['status']=='PARTIALLY_READY'


def test_exact_direct_human_checkpoint_imports_without_legacy_scientific_pass(direct_checkpoint):
    c = direct_checkpoint
    approve(c)
    original = {str(p):p.read_bytes() for p in [c['review_path'],c['source'],c['main']]}
    context_path = import_checkpoint(c)
    context = read_json(context_path)
    assert context['approval']==d.file_ref(c['review_path'])
    assert context['scientific_release'] is False
    assert context['assessment']==d.file_ref(c['nec_path'])
    assert context['upstream_data']['coverage']==d.file_ref(c['cov_path'])
    assert read_json(c['cov_path'])['can_enter_qc'] is False
    assert read_json(c['nec_path'])['scientific_approval'] is False
    require_dp_approval(context)
    _,main,inventory,labels = d.prepared_input(context_path)
    assert main==read_json(c['main'])
    assert inventory==read_json(c['inventory'])
    permitted = {p['item_id'] for p in read_json(c['source'])['permissions']
                 if p['disposition']=='REVIEW_DATA'}
    assert {p['item_id'] for p in labels['labels']}<=permitted
    assert all(p.read_bytes()==original[str(p)] for p in [c['review_path'],c['source'],c['main']])
    assert not any(p['stage']=='DC-review' for p in c['calls'])
    assert 'adequacy' not in read_json(c['review_path'])


@pytest.mark.parametrize('choice',['pending','REQUEST_CHANGES','REJECT'])
def test_direct_gate_without_human_approve_cannot_import(direct_checkpoint, choice):
    c = direct_checkpoint
    if choice!='pending':
        response=c['client'].post('/ui-api/data-reviews/'+c['gate']['id']+'/review',
                                 json=decision(c['gate'],choice))
        assert response.status_code==200
    with pytest.raises(PipelineError):
        import_checkpoint(c)
    assert not (c['root']/'dp_inputs/context.json').exists()


@pytest.mark.parametrize('fault',['unconfirmed','no_reviewer','no_timestamp','wrong_signature',
                                  'gate_not_approved','superseded'])
def test_direct_import_rejects_invalid_human_decision(direct_checkpoint,fault):
    c=direct_checkpoint
    approve(c)
    value=read_json(c['review_path'])
    if fault=='unconfirmed': value['review']['confirmed']=False
    elif fault=='no_reviewer': value['review']['reviewer']=' '
    elif fault=='no_timestamp': value['review']['at']=''
    elif fault=='wrong_signature': value['review']['output_signature']='different'
    elif fault=='gate_not_approved': value['gate']['status']='INTERRUPTED'
    else: value['superseded_by']='data_new_revision'
    write_json(c['review_path'],value)
    with pytest.raises(PipelineError):
        import_checkpoint(c)


@pytest.mark.parametrize('changed',['source_view','main','inventory','context','approval','labels','requirements'])
def test_imported_dp_inputs_cannot_be_rehashed_after_human_approval(direct_checkpoint,changed):
    c=direct_checkpoint
    approve(c)
    path=import_checkpoint(c)
    context=read_json(path)
    if changed=='context':
        context['files']=[]
        write_json(path,context)
    elif changed=='approval':
        value=read_json(c['review_path']);value['review']['confirmed']=False
        write_json(c['review_path'],value)
        context['approval']=d.file_ref(c['review_path'])
        write_json(path,context)
    elif changed in {'labels','requirements'}:
        target=Path(context[changed]['path'])
        value=read_json(target);value['changed_after_approval']=True
        write_json(target,value)
        context[changed]=d.file_ref(target)
        write_json(path,context)
    else:
        target={'source_view':c['source'],'main':c['main'],'inventory':c['inventory']}[changed]
        value=read_json(target);value['changed_after_approval']=True
        write_json(target,value)
        if changed=='main': context['upstream_main']=d.file_ref(target)
        elif changed=='inventory': context['inventory']=d.file_ref(target)
        write_json(path,context)
    with pytest.raises(PipelineError):
        d.prepared_input(path)


def test_missing_direct_approval_reference_blocks_dp(direct_checkpoint):
    c=direct_checkpoint
    approve(c)
    context=read_json(import_checkpoint(c))
    context.pop('approval')
    with pytest.raises(PipelineError):
        require_dp_approval(context)


def test_synthetic_assessment_cannot_enter_real_direct_review(direct_checkpoint):
    c=direct_checkpoint
    receipt_path=c['nec_path'].parent/'call/accepted.json'
    receipt=read_json(receipt_path);receipt['test_generator']=True
    write_json(receipt_path,receipt)
    nec=read_json(c['nec_path']);nec['execution']['test_generator']=True
    write_json(c['nec_path'],nec)
    # Exact accepted response and bindings replay, then the synthetic boundary
    # itself rejects registration; no stale-hash error masks this assertion.
    assert necessity.verify_result(c['nec_path'])==nec
    write_json(c['result_run']/'necessity_ref.json',d.file_ref(c['nec_path']))
    with pytest.raises(ValueError,match='Synthetic results'):
        c['store'].publish(c['result_run'])


def test_direct_import_rejects_persisted_synthetic_assessment_even_if_gate_claims_approved(direct_checkpoint):
    c=direct_checkpoint
    approve(c)
    value=read_json(c['review_path'])
    nec=read_json(c['nec_path']);nec['execution']['test_generator']=True
    write_json(c['nec_path'],nec)
    from research_pipeline.workflow_canvas import fingerprint
    for artifact in value['artifacts']:
        if artifact['name']=='necessity.json': artifact.update(d.file_ref(c['nec_path']))
    value['inputs']['effective_assessment']=d.file_ref(c['nec_path'])
    value['output_signature']=fingerprint({'artifacts':value['artifacts'],'inputs':value['inputs']})
    value['review']['output_signature']=value['output_signature']
    # Malicious serialized claim, not a submission through the real human gate.
    write_json(c['review_path'],value)
    with pytest.raises(PipelineError,match='Synthetic assessment'):
        import_checkpoint(c)


@pytest.mark.parametrize('kind',['direct','legacy'])
def test_dp_payload_carries_exact_verified_human_review_evidence(direct_checkpoint,table_case,kind):
    if kind=='direct':
        approve(direct_checkpoint)
        context_path=import_checkpoint(direct_checkpoint)
    else:
        from test_data_agents import assess, approve_dp
        context_path=approve_dp(assess(table_case))
    context=read_json(context_path)
    approval=read_json(context['approval']['path'])
    node=approval.get('adequacy',approval)
    requests=[]
    def generate(request,**kwargs):
        p=request['payload'];requests.append(copy.deepcopy(p))
        source=next(iter(p['source_units']))
        return {'request_sha256':request['request_sha256'],
                'tables':[{'item_id':p['table']['id'],'action':'PREPARE',
                           'reason':'Original generic records are preserved.', 'columns':[],
                           'evidence':[{'source':source,'quote':p['source_units'][source]}]}],
                'findings':[]}
    d.plan_preparation(direct_checkpoint['root']/'plan_test',context_path,
                       direct_checkpoint['root']/'plan_test/plan.json',generator=generate)
    assert requests
    for p in requests:
        gate=p['human_approval_gate']
        assert gate['status']=='APPROVED' and gate['verified_by']=='HOST_PROGRAM'
        assert gate['approval_ref']==context['approval']
        assert gate['output_signature']==node['output_signature']
        assert gate['review']==node['review']
        assert gate['approved_artifacts']==node['artifacts']
        assert gate['review']['reviewer']==node['review']['reviewer']
        assert gate['review']['confirmed'] is True
        assert gate['scope'].startswith('TECHNICAL_PREPARATION_ONLY')


def test_dp_original_column_citations_are_supplied_and_admitted(direct_checkpoint):
    approve(direct_checkpoint)
    context=import_checkpoint(direct_checkpoint)
    calls=[]
    def generate(request,**kwargs):
        p=request['payload'];calls.append(p)
        header=p['table']['label']['columns'][0]['evidence'][0]
        # This source is present only in label.columns, never duplicated into
        # label.evidence/source_units, but is transmitted in column.evidence.
        assert header['source'] not in {e['source'] for e in p['table']['label']['evidence']}
        assert header['source'] not in p['source_units']
        return {'request_sha256':request['request_sha256'],'tables':[
            {'item_id':p['table']['id'],'action':'PREPARE','reason':'Source header confirmed.',
             'columns':[],'evidence':[header]}],'findings':[]}
    d.plan_preparation(direct_checkpoint['root']/'column_test',context,
                       direct_checkpoint['root']/'column_test/plan.json',generator=generate)
    assert calls


@pytest.mark.parametrize('fault',['unknown_source','mismatched_quote'])
def test_dp_nested_column_evidence_still_rejects_unprovided_citations(direct_checkpoint,fault):
    approve(direct_checkpoint)
    context=import_checkpoint(direct_checkpoint)
    def generate(request,**kwargs):
        p=request['payload'];header=copy.deepcopy(p['table']['label']['columns'][0]['evidence'][0])
        if fault=='unknown_source': header['source']+=':invented_header'
        else: header['quote']='Time (UNKNOWN_UNIT)'
        return {'request_sha256':request['request_sha256'],'tables':[
            {'item_id':p['table']['id'],'action':'PREPARE','reason':'Synthetic incorrect citation.',
             'columns':[],'evidence':[header]}],'findings':[]}
    with pytest.raises(PipelineError,match='Citation does not match'):
        d.plan_preparation(direct_checkpoint['root']/'bad_column_test',context,
                           direct_checkpoint['root']/'bad_column_test/plan.json',generator=generate)
