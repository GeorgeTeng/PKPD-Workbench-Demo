"""Architecture and boundary regression tests. All fits and approvals below are synthetic."""
import copy
import math
import pytest
from research_pipeline.animal_pk import build_plan, digest
from research_pipeline.animal_pk_agents import run_candidate, invoke_agent, run_comparison_agent
from research_pipeline.animal_pk_comparison import compare_results, begin_review, finish_review
from research_pipeline.common import read_json,write_json,PipelineError
from research_pipeline.adequacy import file_ref
from research_pipeline.workflow_runtime import make_plan,execute_contract


@pytest.fixture
def pk_context(tmp_path):
    items=[]
    for identifier,species in [('M1','mouse'),('M2','mouse'),('R1','rat')]:
        folder=tmp_path/identifier
        data=file_ref(write_json(folder/'data.json',{'records':[{'id':'a','time':0,'concentration':1}]}))
        metadata={'role':'PK_OBSERVATIONS','permission':'DEVELOPMENT_CANDIDATE','species':species,
            'matrix':'plasma','record_level':'INDIVIDUAL','exposure_basis':'total','route':'IV',
            'source_table':{'title':'Synthetic '+identifier}}
        meta=file_ref(write_json(folder/'metadata.json',{'dataset_id':identifier,'data_file':data,'metadata':metadata}))
        csv=folder/'data.csv';csv.write_text('id,time,concentration\na,0,1\n')
        items.append({'dataset_id':identifier,'role':'PK_OBSERVATIONS','data':data,'csv':file_ref(csv),
            'metadata':meta,'excluded_records':file_ref(write_json(folder/'quarantine.json',{'records':[]}))})
    return file_ref(write_json(tmp_path/'pk_context.json',{'module':'pk','drug':'Synthetic drug','data_files':items,
        'rules':[{'id':'SOURCE_BOUNDARY','text':'Keep original units and source boundaries.'}],
        'tasks':[{'id':'PK','question':'Fit animal concentrations.'}], 'clinical_questions':{'exposure_definition':'total plasma'},
        'data_access':{'human_pk':False},'findings':[{'dataset_id':'M1','reason':'Synthetic finding.'}]}))


def test_scope_species_sources_and_conditional_candidate(pk_context):
    plan=build_plan(pk_context,{'three_compartment':{'M1':'Investigate unresolved early-phase shape.'}})
    assert [s['species'] for s in plan['species']]==['mouse','rat']
    assert len(plan['analysis_units'])==3
    assert [u['compartments'] for u in plan['analysis_units']]==[[1,2,3],[1,2],[1,2]]
    for a in plan['agents']:
        assert a['session_policy']=='FRESH_CALL_NO_CONVERSATION_REUSE'
        if a['role']=='candidate_model':
            assert a['context']['dataset']['dataset_id']==a['scope']['analysis_id']
            assert a['context']['metadata']['species']==a['scope']['species']
        if a['role']=='species_coordinator':
            assert all(d['metadata']['species']==a['scope']['species'] for d in a['context']['datasets'])
    assert not plan['model_release']
    with pytest.raises(PipelineError,match='reason'):build_plan(pk_context,{'three_compartment':{'M1':''}})
    with pytest.raises(PipelineError,match='unknown'):build_plan(pk_context,{'three_compartment':{'no':'reason'}})


def test_changed_or_heldout_sources_block(pk_context,tmp_path):
    value=read_json(pk_context['path']);item=value['data_files'][0]
    sidecar=read_json(item['metadata']['path']);sidecar['metadata']['permission']='WITHHELD_VALIDATION'
    write_json(item['metadata']['path'],sidecar)
    with pytest.raises(ValueError):build_plan(pk_context)
    item['metadata']=file_ref(item['metadata']['path'])
    ref=file_ref(write_json(tmp_path/'restricted.json',value))
    with pytest.raises(PipelineError,match='development'):build_plan(ref)


def test_materialized_dag_records_no_fake_fits(pk_context,tmp_path):
    spec={'mode':'animal_pk_architecture','pk_context':pk_context,'job_dir':str(tmp_path/'job'),'out':str(tmp_path/'run')}
    plan=make_plan(spec)
    for step in plan['steps'].values():execute_contract(step['contract'])
    report=read_json(tmp_path/'run/animal_pk/report.json')
    assert report['candidate_count']==6 and report['llm_calls']==report['fit_calls']==0
    assert all(r['AIC'] is None for r in report['comparisons'])
    assert report['status']=='ARCHITECTURE_READY_NOT_FITTED' and not report['model_release']
    assert read_json(tmp_path/'job/receipts/animal_pk_architecture.json')['status']=='SUCCEEDED'


def fit_result(tmp_path,identifier='M1_1C',ll=-20,k=2):
    proof=file_ref(write_json(tmp_path/(identifier+'_evidence.json'),{'synthetic':True}))
    return {'candidate_id':identifier,'species':'mouse','analysis_id':'M1','status':'FITTED','converged':True,
        'observation_signature':'same-observations','response_scale':'concentration','response_unit':'mg/L',
        'likelihood_definition':'Gaussian independent','likelihood_constants':'included',
        'estimation_method':'MAXIMUM_LIKELIHOOD','n_observations':20,'bic_n_definition':'Independent observations',
        'log_likelihood':ll,'n_parameters':k,'diagnostic_status':'PASSED_PRESET_CHECKS','diagnostic_rule_signature':'synthetic-rules',
        'execution_ref':proof,'model_code_ref':proof,'diagnostics_ref':proof}


def test_comparison_uses_metrics_only_in_comparable_groups(tmp_path):
    a=fit_result(tmp_path);b=fit_result(tmp_path,'M1_2C',-15,4)
    other=fit_result(tmp_path,'M2_1C',-100,2);other['observation_signature']='other-observations'
    bad=fit_result(tmp_path,'M1_3C',-10,6);bad['converged']=False
    report=compare_results([a,b,other,bad]);rows=report['rows']
    assert rows[0]['AIC']==44 and rows[1]['AIC']==38
    assert rows[1]['BIC']==pytest.approx(30+math.log(20)*4)
    assert rows[0]['delta_AIC']==6 and rows[2]['delta_AIC'] is None and rows[3]['AIC'] is None
    assert len(report['recommendations'])==1
    b['response_scale']='log_concentration'
    assert not compare_results([a,b])['recommendations']
    b['estimation_method']='REML'
    assert compare_results([b])['rows'][0]['status']=='NOT_COMPARABLE'


def test_human_gate_signature_selection_and_revision(tmp_path):
    report=compare_results([fit_result(tmp_path),fit_result(tmp_path,'M1_2C',-15,4)])
    folder=tmp_path/'gate';begin_review(report,folder,'synthetic','mouse')
    decision={'decision':'APPROVE','confirmed':True,'reviewer':'Synthetic reviewer','rationale':'',
        'output_signature':'wrong','selected_candidates':['M1_2C']}
    with pytest.raises(ValueError,match='signature'):finish_review(folder,decision)
    decision['output_signature']=report['output_signature'];decision['selected_candidates']=['missing']
    with pytest.raises(PipelineError):finish_review(folder,decision)
    decision['selected_candidates']=['M1_2C'];result=finish_review(folder,decision)
    assert result['model_release'] and not result['human_prediction_validated']
    with pytest.raises(ValueError,match='already'):finish_review(folder,decision)
    folder2=tmp_path/'revision';begin_review(report,folder2,'synthetic','mouse')
    decision.update(decision='REQUEST_CHANGES',return_to='diagnostics',requested_changes='Investigate residual pattern.')
    result=finish_review(folder2,decision)
    assert not result['model_release'] and result['langgraph']['status']=='REVISION_REQUIRED'


def test_fresh_agent_calls_candidate_revision_and_no_adapter(pk_context,tmp_path):
    plan=build_plan(pk_context);unit=plan['analysis_units'][0];c=unit['candidates'][0]
    model=next(a for a in plan['agents'] if a['id']==c['model_agent'])
    diag=next(a for a in plan['agents'] if a['id']==c['diagnostic_agent'])
    approval=file_ref(write_json(tmp_path/'synthetic_approval.json',{'synthetic':True}))
    qualification=file_ref(write_json(tmp_path/'qualified.json',{'fit_ready':True,'candidate_id':c['id'],'compartments':1,
        'input_refs':[unit['data']['data']],'approval_ref':approval}))
    with pytest.raises(PipelineError,match='No numerical'):run_candidate(model,diag,qualification,tmp_path/'no_adapter')
    calls=[]
    def generator(request,diagnostics_dir):
        calls.append(request);revision=len(calls)==2
        return {'decision':'REVISE' if revision else 'CONTINUE','summary':'Synthetic response',
            'issues':[],'requested_changes':['Try a qualified alternative starting point.'] if revision else []}
    def fit(qualification,proposal_ref,folder):return fit_result(folder,c['id'])
    result=run_candidate(model,diag,qualification,tmp_path/'loop',fit_adapter=fit,generator=generator)
    assert result['attempt']==2 and result['status']=='READY_FOR_COMPARISON' and len(calls)==4
    assert len(list((tmp_path/'loop').glob('*_agent/*/request.json')))==4
    assert all('messages' not in r['payload'] for r in calls)
    assert read_json(tmp_path/'loop/result.json')['scientific_accepted'] is False


def test_comparison_agent_cannot_replace_numeric_evidence_or_accept(pk_context,tmp_path):
    plan=build_plan(pk_context);contract=next(a for a in plan['agents'] if a['role']=='comparison')
    refs=[file_ref(write_json(tmp_path/(c+'.json'),fit_result(tmp_path,c))) for c in contract['context']['candidate_ids']]
    def generator(request,diagnostics_dir):
        assert request['payload']['upstream']['validated_comparison']['rows'][0]['AIC']==44
        return {'decision':'CONTINUE','summary':'Ready for human review.','issues':[],'requested_changes':[]}
    value=run_comparison_agent(contract,refs,tmp_path/'comparison',generator)
    assert not value['model_release'] and read_json(value['comparison_ref']['path'])['rows'][0]['AIC']==44
    with pytest.raises(PipelineError,match='every expected'):run_comparison_agent(contract,refs[:1],tmp_path/'missing',generator)


def test_api_empty_options_and_preview_never_approve(pk_context,tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from research_pipeline.animal_pk_api import animal_pk_router
    from types import SimpleNamespace
    from threading import RLock
    calls=[]
    source={**pk_context,'name':'pk_context.json'}
    canvas=SimpleNamespace(lock=RLock(),outputs=tmp_path,
        load=lambda _: {'nodes':{'dispatch':{'artifacts':[source]}}},
        artifacts_valid=lambda refs: all(file_ref(r['path'])['sha256']==r['sha256'] for r in refs),approved=lambda _:False)
    def launch(mode,target):calls.append((mode,target));return {'id':'synthetic_job','status':'QUEUED'}
    app=FastAPI();app.include_router(animal_pk_router(canvas,launch,lambda _: {'status':'QUEUED'},lambda _: {'status':'PAUSED'}))
    client=TestClient(app)
    preview=client.get('/workflow/sessions/synthetic/animal-pk/plan')
    assert preview.status_code==409 and not calls
    assert not (tmp_path/'animal_pk_controls/synthetic').exists()
    r=client.post('/workflow/sessions/synthetic/animal-pk/architecture-runs',json={'three_compartment':{}})
    assert r.status_code==202 and calls[0][0]['inspection_only'] is True
    assert client.post('/workflow/sessions/synthetic/animal-pk/architecture-runs',json={'approve':True}).status_code==422
