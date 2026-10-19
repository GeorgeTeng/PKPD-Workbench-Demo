"""Control API boundary checks with synthetic data and an injected scheduler/core."""
from pathlib import Path
from threading import RLock
from types import SimpleNamespace, ModuleType
import sys
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from research_pipeline.adequacy import file_ref
from research_pipeline.common import read_json, write_json, PipelineError
from research_pipeline.animal_pk import digest
from research_pipeline.animal_pk_api import animal_pk_router
from research_pipeline.graph_control import ReviewController


def register_species_analysis(api,monkeypatch,run_id='rat_publication'):
    from research_pipeline import animal_pk_individual
    def validate(reference):
        from research_pipeline.adequacy import check_ref
        check_ref(reference);return read_json(reference['path'])
    monkeypatch.setattr(animal_pk_individual,'validate_request',validate)
    root=api.canvas.outputs/run_id/'animal_pk'
    master=file_ref(write_json(root/'request.json',{'species':'rat','source_refs':[api.source],'candidates':[]}))
    comparison=write_json(root/'comparison.json',{'rows':[{'species':'rat','candidate_id':'synthetic','AIC':12,'model_release':False}]})
    report=write_json(root/'report.json',{'model_release':False})
    page=root/'review.html';page.write_text('<h1>Synthetic review</h1>')
    write_json(root/'artifact_manifest.json',{'files':[{'name':p.name,**file_ref(p)} for p in [comparison,report,page]]})
    record={'job_id':run_id,'session_id':'synthetic','interface':'species_analysis','species':'rat','title':'Synthetic rat analysis',
        'context_ref':api.source,'mode':'PK_REVIEW_PUBLICATION','request_ref':master,
        'rerun':{'mode':'animal_pk_individual','request_ref':master}}
    write_json(api.canvas.outputs/'animal_pk_agent_runs/synthetic'/f'{run_id}.json',record)
    return record


def test_species_analysis_results_rerun_and_pause_keep_review_gates(api,monkeypatch):
    record=register_species_analysis(api,monkeypatch)
    path=api.base+'/analysis-runs/rat_publication'
    blocked=api.client.get(path).json();assert blocked['model_release'] is False and not blocked['can_run']
    assert api.client.post(path+'/rerun',json={'request_signature':'not-reviewed'}).status_code==409
    api.state['approved']=True
    viewed=api.client.get(path).json()
    assert viewed['can_run'] and viewed['publication_only'] and not viewed['can_pause']
    assert api.client.get(path+'/report').text=='<h1>Synthetic review</h1>'
    assert api.client.post(path+'/rerun',json={'request_signature':'stale'}).status_code==409
    launched=api.client.post(path+'/rerun',json={'request_signature':viewed['request_signature']})
    assert launched.status_code==202,launched.text
    new=launched.json();assert new['id']!='rat_publication' and new['model_release'] is False
    mode,target=api.state['calls'][-1][1:]
    assert target==mode['mode']=='animal_pk_individual'
    assert mode['individual_request']==record['rerun']['request_ref']
    assert api.client.post(path+'/rerun',json={'request_signature':viewed['request_signature']}).status_code==409
    assert api.client.post(api.base+'/analysis-runs/'+new['id']+'/pause').json()['status']=='PAUSED'
    assert api.client.get(api.base.replace('/synthetic/','/different/')+'/analysis-runs/'+new['id']).status_code==404
    # The original publication remains intact and no model-selection decision was written.
    assert read_json(api.canvas.outputs/'rat_publication/animal_pk/report.json')['model_release'] is False


def test_species_analysis_rejects_changed_context_and_foreign_artifacts(api,monkeypatch):
    record=register_species_analysis(api,monkeypatch);api.state['approved']=True
    path=api.base+'/analysis-runs/rat_publication'
    record['context_ref']={**api.source,'sha256':'changed'}
    write_json(api.canvas.outputs/'animal_pk_agent_runs/synthetic/rat_publication.json',record)
    assert not api.client.get(path).json()['can_run']
    manifest=api.canvas.outputs/'rat_publication/animal_pk/artifact_manifest.json'
    write_json(manifest,{'files':[{'name':'comparison.json',**api.source}]})
    assert api.client.get(path).status_code==409
    listing=api.client.get(api.base+'/analysis-runs').json()['analyses']
    assert listing[0]['status']=='ARTIFACT_CHECK_FAILED' and not listing[0]['can_run']


@pytest.fixture
def api(tmp_path,monkeypatch):
    data=file_ref(write_json(tmp_path/'data.json',{'records':[{'id':'synthetic','time':0,'concentration':1}]}))
    metadata={'role':'PK_OBSERVATIONS','permission':'DEVELOPMENT_CANDIDATE','species':'rat',
        'matrix':'plasma','record_level':'INDIVIDUAL','exposure_basis':'total','route':'IV','source_table':{'title':'Synthetic'}}
    sidecar=file_ref(write_json(tmp_path/'metadata.json',{'dataset_id':'R1','data_file':data,'metadata':metadata}))
    csv=tmp_path/'data.csv';csv.write_text('id,time,concentration\nsynthetic,0,1\n')
    source=file_ref(write_json(tmp_path/'pk_context.json',{'module':'pk','drug':'Synthetic',
        'data_files':[{'dataset_id':'R1','role':'PK_OBSERVATIONS','data':data,'csv':file_ref(csv),'metadata':sidecar,
            'excluded_records':file_ref(write_json(tmp_path/'excluded.json',{'records':[]}))}],
        'rules':[],'tasks':[],'clinical_questions':{},'data_access':{'human_pk':False}}))
    source['name']='pk_context.json'
    state={'approved':False,'handoff_checks':0,'jobs':{},'calls':[],'review_report':None}
    def assigned(identifier,branch):
        state['handoff_checks']+=1
        if not state['approved']:raise HTTPException(409,'The branch handoff is pending review.')
        return {'status':'ROUTING_APPROVED_NOT_MODEL_RELEASE','context':read_json(source['path']),
            'dispatch_output_signature':'synthetic','review':{'confirmed':True},'model_release':False}
    canvas=SimpleNamespace(lock=RLock(),outputs=tmp_path/'runs',graph_reviews=ReviewController(tmp_path/'state'),
        load=lambda _: {'nodes':{'dispatch':{'artifacts':[source]}}},
        artifacts_valid=lambda refs:all(file_ref(r['path'])['sha256']==r['sha256'] for r in refs),
        approved=lambda _:state['approved'],assigned_context=assigned)
    core=ModuleType('research_pipeline.animal_pk_control')
    core.control_snapshot=lambda plan,folder,runs:{'agent_states':{a['id']:{'can_run':True,'status':'NOT_STARTED'} for a in plan['agents']},'capabilities':{},'review':{}}
    def make_request(plan,agent_id,folder,instruction,runs,approval_ref):
        if not any(a['id']==agent_id for a in plan['agents']):raise PipelineError('PK_UNKNOWN_AGENT','Choose an agent from this plan.')
        state['calls'].append(('request',agent_id,approval_ref))
        agent=next(a for a in plan['agents'] if a['id']==agent_id)
        children={a['role']:a for a in plan['agents'] if a.get('managed_by')==agent_id}
        return file_ref(write_json(folder/'requests'/('request_'+str(len(state['calls']))+'.json'),
            {'agent_id':agent_id,'agent':agent,'instruction':instruction,'step_contracts':children}))
    core.make_agent_request=make_request
    core.qualification_template=lambda plan,candidate:{'candidate_id':candidate,'configurations':[],'max_attempts':2,'reviewer':'','confirmed':False}
    def save_qualification(plan,candidate,envelope,folder,approval_ref):
        if not envelope.get('confirmed') or not envelope.get('reviewer'):raise PipelineError('PK_QUALIFICATION_UNCONFIRMED','Confirm the fit configuration and provide a reviewer.')
        ref=file_ref(write_json(folder/'qualifications'/candidate/'immutable.json',envelope))
        saved={'qualification_ref':ref,'qualification':envelope,'validation':{'valid':True}}
        write_json(folder/'qualifications'/candidate/'current.json',saved)
        return saved
    core.save_qualification=save_qualification
    core.review_bundle=lambda *args:state['review_report']
    monkeypatch.setitem(sys.modules,'research_pipeline.animal_pk_control',core)
    def launch(mode,target):
        identifier='synthetic_'+str(len(state['jobs'])+1)
        job={'id':identifier,'status':'QUEUED','created_at':'2026-09-22T00:00:00Z'}
        state['jobs'][identifier]=job;state['calls'].append(('launch',mode,target));return job
    def pause(identifier):
        state['jobs'][identifier]['status']='PAUSED';return state['jobs'][identifier]
    app=FastAPI();app.include_router(animal_pk_router(canvas,launch,lambda identifier:state['jobs'][identifier],pause))
    result=SimpleNamespace(client=TestClient(app),state=state,canvas=canvas,source=source,
        base='/workflow/sessions/synthetic/animal-pk')
    # Existing execution tests start from an explicitly reviewed synthetic workflow.
    state['approved']=True
    draft=result.client.post(result.base+'/planning/enter').json()
    response=result.client.post(result.base+'/planning/review',json={
        'plan_signature':draft['plan']['plan_signature'],'reviewer':'Synthetic workflow reviewer',
        'decision':'APPROVE','confirmed':True})
    assert response.status_code==200,response.text
    state.update(approved=False,handoff_checks=0)
    return result


def test_plan_is_stable_and_dispatch_gate_precedes_agent_invocation(api):
    first=api.client.get(api.base+'/control').json()
    second=api.client.get(api.base+'/control').json()
    assert first['plan']['plan_signature']==second['plan']['plan_signature']
    assert all(not item['can_run'] for item in first['agent_states'].values())
    agent_id=first['plan']['agents'][0]['id']
    denied=api.client.post(api.base+'/agent-runs',json={'agent_id':agent_id,'plan_signature':first['plan']['plan_signature']})
    assert denied.status_code==409 and api.state['handoff_checks']==1 and not api.state['calls']
    api.state['approved']=True
    stale=api.client.post(api.base+'/agent-runs',json={'agent_id':agent_id,'plan_signature':'stale'})
    assert stale.status_code==409 and stale.json()['detail']['code']=='PK_STALE_PLAN'
    started=api.client.post(api.base+'/agent-runs',json={'agent_id':agent_id,'plan_signature':first['plan']['plan_signature'],'instruction':'Check the assigned dosing evidence.'})
    assert started.status_code==202,started.text
    mode,target=api.state['calls'][-1][1:]
    assert mode['mode']==target=='animal_pk_execution' and 'pk_plan' in mode and 'agent_request' in mode
    assert read_json(mode['agent_request']['path'])['instruction']=='Check the assigned dosing evidence.'
    assert read_json(api.state['calls'][0][2]['path'])['fit_qualification'] is False


def test_on_entry_generation_and_workflow_review_are_required(api):
    base=api.base.replace('/synthetic/','/new_project/')
    assert api.client.get(base+'/control').json()['detail']['code']=='PK_PLAN_NOT_GENERATED'
    assert not (api.canvas.outputs/'animal_pk_controls/new_project').exists()
    assert api.client.post(base+'/planning/enter').status_code==409
    api.state['approved']=True
    draft=api.client.post(base+'/planning/enter').json();plan=draft['plan']
    assert draft['planning']['status']=='DRAFT_PENDING_HUMAN_REVIEW'
    assert draft['planning']['langgraph_review']['status']=='INTERRUPTED'
    assert not draft['planning']['approved'] and not api.state['jobs']
    assert all(not a['can_run'] for a in draft['agent_states'].values())
    denied=api.client.post(base+'/agent-runs',json={'agent_id':plan['agents'][0]['id'],'plan_signature':plan['plan_signature']})
    assert denied.status_code==409 and denied.json()['detail']['code']=='PK_WORKFLOW_REVIEW_REQUIRED'
    second=api.client.post(base+'/planning/enter').json()
    assert second['planning']['langgraph_review']==draft['planning']['langgraph_review']
    review={'plan_signature':plan['plan_signature'],'reviewer':'Synthetic','decision':'APPROVE','confirmed':True}
    assert api.client.post(base+'/planning/review',json={**review,'plan_signature':'stale'}).status_code==409
    approved=api.client.post(base+'/planning/review',json=review).json()
    assert approved['planning']['approved']
    changed=api.client.post(base+'/control/plan',json={'three_compartment':{'R1':'Synthetic early distribution question'}}).json()
    assert not changed['planning']['approved']
    assert all(not a['can_run'] for a in changed['agent_states'].values())
    contract=api.client.get(base+'/planning/files/planning_agent_contract.json').json()
    assert contract['llm_calls']==contract['fit_calls']==0
    assert contract['llm_adapter_status']=='RESERVED_NOT_CONNECTED'


def test_control_qualification_requires_separate_confirmation(api):
    api.state['approved']=True
    view=api.client.get(api.base+'/control').json();plan=view['plan'];candidate=plan['analysis_units'][0]['candidates'][0]['id']
    path=api.base+'/qualifications/'+candidate
    template=api.client.get(path).json()['template']
    assert template['confirmed'] is False and template['reviewer']==''
    invalid=api.client.put(path,json={'plan_signature':plan['plan_signature'],'qualification':template})
    assert invalid.status_code==422 and invalid.json()['detail']['code']=='PK_QUALIFICATION_UNCONFIRMED',invalid.text
    template.update(confirmed=True,reviewer='Synthetic reviewer')
    assert api.client.put(path,json={'plan_signature':plan['plan_signature'],'qualification':template}).status_code==200
    loaded=api.client.get(path).json()
    assert loaded['qualification']==template and loaded['validation']['valid']


def test_run_pause_is_scoped_and_files_cannot_escape_run(api):
    api.state['approved']=True
    plan=api.client.get(api.base+'/control').json()['plan'];agent_id=plan['agents'][0]['id']
    started=api.client.post(api.base+'/agent-runs',json={'agent_id':agent_id,'plan_signature':plan['plan_signature']}).json()
    job_id=started['id'];path=api.base+'/agent-runs/'+job_id
    assert api.client.post(api.base+'/control/plan',json={'three_compartment':{'R1':'Explore shape.'}}).status_code==409
    assert api.client.post(path+'/pause').json()['status']=='PAUSED'
    assert api.client.get(path).json()['request']['agent_id']==agent_id
    assert api.client.post(path.replace('/synthetic/','/another/')+'/pause').status_code==404
    root=api.canvas.outputs/job_id
    report=write_json(root/'animal_pk/report.json',{'status':'SYNTHETIC_ONLY'})
    write_json(root/'animal_pk/artifact_manifest.json',{'files':[{'name':'report.json',**file_ref(report)}]})
    assert api.client.get(path+'/files/report.json').json()['status']=='SYNTHETIC_ONLY'
    # A valid hash is not sufficient authorization to expose a file outside this run.
    write_json(root/'animal_pk/artifact_manifest.json',{'files':[{'name':'foreign.json',**api.source}]})
    result=api.client.get(path)
    assert result.status_code==409 and result.json()['detail']['code']=='PK_INVALID_ARTIFACT_PATH'


def test_model_options_start_a_new_plan_and_do_not_inherit_qualification(api):
    first=api.client.get(api.base+'/control').json()['plan']
    response=api.client.post(api.base+'/control/plan',json={'three_compartment':{'R1':'Investigate the early distribution phase.'}})
    assert response.status_code==200
    current=response.json()['plan']
    assert current['plan_signature']!=first['plan_signature']
    assert current['analysis_units'][0]['compartments']==[1,2,3]
    assert api.client.get(api.base+'/control').json()['plan']['plan_signature']==current['plan_signature']


def test_parallel_candidates_have_separate_requests_results_and_nested_artifacts(api):
    api.state['approved']=True
    plan=api.client.get(api.base+'/control').json()['plan']
    candidates=plan['analysis_units'][0]['candidates']
    response=api.client.post(api.base+'/candidate-runs',json={'analysis_id':'R1','plan_signature':plan['plan_signature']})
    assert response.status_code==202,response.text
    job=response.json();mode,target=api.state['calls'][-1][1:]
    assert target=='animal_pk_execution' and len(mode['agent_requests'])==2
    assert mode['agent_requests'][0]!=mode['agent_requests'][1]
    api.state['jobs'][job['id']]['status']='COMPLETED'
    root=api.canvas.outputs/job['id']/'animal_pk'
    files=[]
    for candidate in candidates:
        agent_id=candidate['model_agent']
        path=write_json(root/'agents'/agent_id/'report.json',{'status':'SYNTHETIC_ONLY','agent_id':agent_id})
        files.append({'name':str(path.relative_to(root)).replace('\\','/'),**file_ref(path)})
    write_json(root/'artifact_manifest.json',{'files':files})
    runs=api.client.get(api.base+'/control').json()['runs']
    assert len(runs)==2 and all(run['id']==job['id'] for run in runs)
    agent_id=candidates[1]['model_agent']
    detail=api.client.get(api.base+'/agent-runs/'+job['id'],params={'agent_id':agent_id}).json()
    assert detail['result']['agent_id']==agent_id and detail['request']['agent_id']==agent_id
    nested=api.client.get(api.base+'/agent-runs/'+job['id']+'/files/'+files[1]['name'])
    assert nested.status_code==200 and nested.json()['agent_id']==agent_id


def test_managed_child_exposes_its_own_fresh_call_audit(api):
    api.state['approved']=True
    plan=api.client.get(api.base+'/control').json()['plan']
    candidate=plan['analysis_units'][0]['candidates'][0]
    child=next(a for a in plan['agents'] if a['id']==candidate['steps'][0]['agent_id'])
    started=api.client.post(api.base+'/agent-runs',json={'agent_id':candidate['model_agent'],'plan_signature':plan['plan_signature']}).json()
    endpoint=api.base+'/agent-runs/'+started['id']
    before=api.client.get(endpoint,params={'agent_id':child['id']}).json()
    assert before['execution']['status']=='NOT_INVOKED'
    folder=api.canvas.outputs/started['id']/'animal_pk/agents'/child['role']
    for i in range(2):
        invocation=folder/('synthetic_invocation_'+str(i))
        write_json(invocation/'request.json',{'payload':{'task':child,'upstream':{'configuration_number':i+1}}})
        write_json(invocation/'response.json',{'decision':'CONTINUE','summary':'Synthetic '+str(i)})
        write_json(invocation/'execution.json',{'started_at':str(i),'status':'COMPLETED','fresh_session':True})
    detail=api.client.get(endpoint,params={'agent_id':child['id']}).json()
    assert detail['managed_by']==candidate['model_agent'] and len(detail['agent_invocations'])==2
    assert detail['request']['payload']['task']['id']==child['id']
    assert detail['request']['payload']['upstream']['configuration_number']==2
    assert detail['execution']['fresh_session'] is True
    assert api.client.get(endpoint,params={'agent_id':'another_agent'}).status_code==409


def test_failed_agent_returns_semantic_diagnosis_and_execution_status(api):
    api.state['approved']=True
    plan=api.client.get(api.base+'/control').json()['plan'];agent_id=plan['agents'][0]['id']
    job=api.client.post(api.base+'/agent-runs',json={'agent_id':agent_id,'plan_signature':plan['plan_signature']}).json()
    api.state['jobs'][job['id']]['status']='STOPPED_ON_ERROR'
    root=api.canvas.outputs/job['id']/'animal_pk'
    failure={'status':'STOPPED_ON_ERROR','code':'SYNTHETIC_DATA_CONFLICT','summary':'Dose history conflicts with the source table.',
        'next_action':'Correct the dose mapping and confirm a new fitting contract.'}
    write_json(root/'failure.json',failure);write_json(root/'execution.json',failure)
    detail=api.client.get(api.base+'/agent-runs/'+job['id']).json()
    assert detail['result']['summary']==failure['summary'] and detail['result']['next_action']==failure['next_action']
    assert detail['execution']['status']=='STOPPED_ON_ERROR'


def test_review_requires_current_comparison_and_human_confirmation(api):
    api.state['approved']=True
    assert api.client.get(api.base+'/reviews?species=rat').json()['can_review'] is False
    report={'schema_version':'synthetic','rows':[{'candidate_id':'R1_1C','species':'rat','status':'NOT_COMPARABLE'}],
        'recommendations':[],'status':'PENDING_HUMAN_REVIEW','scientific_accepted':False}
    report['output_signature']=digest(report);api.state['review_report']=report
    review=api.client.get(api.base+'/reviews?species=rat').json()
    assert review.get('can_review') and not review['eligible_candidates'],review
    request={'decision':'REQUEST_CHANGES','reviewer':'Synthetic reviewer','confirmed':True,
        'comment':'Investigate residual error before another fit.','return_to':'candidate_model','review_signature':'stale'}
    assert api.client.post(api.base+'/reviews/rat',json=request).status_code==422
    request['review_signature']=review['review_signature'];request['confirmed']=False
    assert api.client.post(api.base+'/reviews/rat',json=request).status_code==422
    request['confirmed']=True
    result=api.client.post(api.base+'/reviews/rat',json=request)
    assert result.status_code==200 and result.json()['model_release'] is False
    assert api.client.get(api.base+'/reviews?species=rat').json()['can_review'] is False
    report={**report,'status':'PENDING_NEW_COMPARISON'};report['output_signature']=digest({k:v for k,v in report.items() if k!='output_signature'})
    api.state['review_report']=report
    assert api.client.get(api.base+'/reviews?species=rat').json()['can_review'] is True
