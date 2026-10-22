"""Source-scoped clinical routing and independent review gates; synthetic approvals only."""
import copy
import pytest
from fastapi.testclient import TestClient
from research_pipeline.common import read_json,write_json,PipelineError
from research_pipeline.adequacy import file_ref
from research_pipeline.clinical_dispatch import build,inputs,route_dataset,task_branch,execute
from research_pipeline.clinical_dispatch import reference_advice,project_reference_advice
from research_pipeline.workflow_runtime import make_plan,execute_contract
from research_pipeline.workflow_canvas import fingerprint,ClinicalSpec
from research_pipeline.workbench import create_workbench
from retired_eda_support import approval


def node(artifacts):
    signature=fingerprint(artifacts)
    return {'execution':'COMPLETED','artifacts':artifacts,'output_signature':signature,'segments':[],
        'review':{'decision':'APPROVE','output_signature':signature},'langgraph_review':{'status':'APPROVED'}}


@pytest.fixture
def snapshot(approval,tmp_path):
    main={'objective':'Synthetic translation feasibility','study':{'drug':'Synthetic drug','methods':'Animal PK; K. pneumoniae; fAUC/MIC, fCmax/MIC, fT>MIC.'},
          'rules':['Keep source identities.','Human validation must follow the model freeze.']}
    tasks=[{'id':'animal','question':'Which animal PK components are identifiable?','endpoint':'plasma concentrations'},
           {'id':'index','question':'Which free-drug indices can be calculated?','endpoint':'matched PD'},
           {'id':'final','question':'Compare independent observed human exposures.','endpoint':'agreement'}]
    refs=[{'name':name,**file_ref(write_json(tmp_path/name,value))} for name,value in [
        ('effective_main.json',main),('assessment.json',{'tasks':tasks,'requirements':[{'task_id':'index','id':'needs-mic','needed_material':'matched MIC'}]})]]
    prepare=read_json(approval['path'])['prepare']
    eda_ref={'name':'eda_report.json',**file_ref(write_json(tmp_path/'eda_report.json',
        {'input_approval':approval,'datasets':[{'dataset_id':'D1','findings':[{'reason':'Group mean; no independent identities.'}]}]}))}
    return file_ref(write_json(tmp_path/'snapshot.json',{'nodes':{'context':node(refs[:1]),'adequacy':node(refs),
        'prepare':prepare,'eda':node([eda_ref])}}))


def test_scoped_contract_execution_and_receipt(snapshot,tmp_path):
    draft=tmp_path/'draft';build(snapshot,draft)
    questions=read_json(draft/'clinical_questions.json')
    spec=file_ref(write_json(tmp_path/'confirmed.json',{'confirmed':True,'reviewer':'Synthetic test only',
        'values':questions['values'],'index_exposure_source':'REQUIRES_PK_PREDICTIONS',
        'upstream_signatures':{k:n['output_signature'] for k,n in read_json(snapshot['path'])['nodes'].items()}}))
    plan=make_plan({'mode':'reviewed_eda','reviewed_eda':snapshot,'clinical_spec':spec,
        'job_dir':str(tmp_path/'job'),'out':str(tmp_path/'run')})
    execute_contract(plan['steps']['clinical_dispatch']['contract'])
    pk=read_json(tmp_path/'run/dispatch/pk_context.json');index=read_json(tmp_path/'run/dispatch/index_context.json')
    assert [t['id'] for t in pk['tasks']]==['animal'] and 'pd_endpoint' not in pk['clinical_questions']
    assert len(pk['data_files'])==1 and not index['data_files']
    assert index['candidate_indices']==['fAUC/MIC','fCmax/MIC','fT>MIC']
    assert index['task_requirements'][0]['id']=='needs-mic'
    assert not pk['model_release'] and not any(pk['data_access'].values())
    assert index['phases']['fit']=='REQUIRES_CALCULATED_INDICES_AND_MATCHED_PD'
    assert read_json(tmp_path/'job/receipts/clinical_dispatch.json')['status']=='SUCCEEDED'
    for artifact in read_json(snapshot['path'])['nodes']['prepare']['artifacts']:
        assert file_ref(artifact['path'])['sha256']==artifact['sha256']


def test_reviewed_advice_is_version_bound_and_projected_without_changing_answers(snapshot,tmp_path,monkeypatch):
    from research_pipeline import pk_reference_pilot
    original=build(snapshot,tmp_path/'original')
    original_values=read_json(tmp_path/'original/clinical_questions.json')['values']
    advisory={'authority':'ADVISORY_ONLY_NO_PROJECT_RULE_ACTIVATION','scope':'IN_SCOPE','rule_activation':False,
        'suggestions':[{'card_id':'PK','relevant_step':'pk','proposed_action':'Review structure.'},
                       {'card_id':'VALIDATION','relevant_step':'validation','proposed_action':'Keep clinical comparison held out.'}],
        'cards':[{'id':'PK','source_ids':['S1']},{'id':'VALIDATION','source_ids':['S2']}],
        'sources':[{'id':'S1'},{'id':'S2'}]}
    advice_ref=file_ref(write_json(tmp_path/'advice.json',advisory))
    report_ref={'name':'adequacy.json',**file_ref(write_json(tmp_path/'adequacy.json',{'external_reference_context':advice_ref}))}
    s=read_json(snapshot['path']);s['nodes']['adequacy']=node(s['nodes']['adequacy']['artifacts']+[report_ref])
    new_snapshot=file_ref(write_json(tmp_path/'with_advice.json',s))
    calls=[]
    def verified(path,main):
        calls.append((path,main));return advisory
    monkeypatch.setattr(pk_reference_pilot,'downstream_context',verified)
    build(new_snapshot,tmp_path/'with_advice')
    questions=read_json(tmp_path/'with_advice/clinical_questions.json')
    assert questions['values']==original_values and questions['external_reference_advice']['answers_overwritten'] is False
    pk=read_json(tmp_path/'with_advice/pk_context.json')['external_reference_advice']
    clinical=read_json(tmp_path/'with_advice/clinical_context.json')['external_reference_advice']
    assert [s['id'] for s in pk['sources']]==['S1']
    assert [s['id'] for s in clinical['sources']]==['S2']
    assert 'external_reference_advice' not in read_json(tmp_path/'with_advice/index_context.json')
    assert len(calls)==1 and not pk['rule_activation'] and not pk['parameter_transfer_authorized']
    write_json(tmp_path/'advice.json',{'tampered':True})
    with pytest.raises((PipelineError,ValueError)):
        reference_advice(s,calls[0][1])


def test_draft_does_not_need_eda_approval_but_execution_does(snapshot,tmp_path):
    s=read_json(snapshot['path']);s['nodes']['eda']['review']=None;s['nodes']['eda']['langgraph_review']={'status':'PENDING'}
    ref=file_ref(write_json(tmp_path/'pending.json',s));build(ref,tmp_path/'draft')
    with pytest.raises(PipelineError,match='Approve'):inputs(ref,require_eda=True)


def test_metadata_routes_not_filenames_and_holdout_is_rejected():
    d={'id':'arbitrary','role':'MIC','data':{'path':'human_pk.csv'},'metadata':{
        'species':'not_applicable','permission':'DEVELOPMENT_CANDIDATE','source_table':{'title':'Surveillance MIC distribution'}}}
    assert route_dataset(d,{})[0]==['clinical']
    d['data']['path']='renamed.csv';assert route_dataset(d,{})[0]==['clinical']
    d['metadata']['permission']='WITHHELD_VALIDATION'
    with pytest.raises(PipelineError,match='held-out'):route_dataset(d,{})
    d['metadata']['permission']='DEVELOPMENT_CANDIDATE';d['metadata']['species']='human'
    with pytest.raises(PipelineError,match='held-out'):route_dataset(d,{})


def test_nonmatching_pathogen_is_not_routed_and_unknown_roles_retained():
    main={'study':{'scope':'K. pneumoniae'}}
    d={'id':'x','role':'PD_OBSERVATIONS','metadata':{'permission':'DEVELOPMENT_CANDIDATE','source_table':{'title':'P. aeruginosa thigh'}}}
    assert route_dataset(d,main)[0]==[]
    d['metadata']['source_table']['title']='K. pneumoniae thigh';assert route_dataset(d,main)[0]==['index']
    d['role']='SOURCE_TABLE';assert route_dataset(d,main)[0]==[]


def test_changed_qc_file_cannot_enter(snapshot,tmp_path):
    path=tmp_path/'qc/normalized/D1.csv';path.write_text('changed',encoding='utf-8')
    with pytest.raises(PipelineError):build(snapshot,tmp_path/'draft')


def test_frontend_draft_binding_and_api_release_gate(snapshot,tmp_path):
    app=create_workbench(tmp_path,tmp_path/'state');store=app.state.canvas;client=TestClient(app)
    sid=client.post('/ui-api/workflow/sessions').json()['session_id'];base='/ui-api/workflow/sessions/'+sid
    s=store.load(sid);s['nodes'].update(read_json(snapshot['path'])['nodes']);s['nodes']['adequacy']['adequacy_status']='SUFFICIENT_FOR_DEFINED_SCOPE'
    # Intake is synthetic; no upload or research approval is fabricated.
    s['nodes']['intake']=node(s['nodes']['context']['artifacts']);write_json(store.path(sid),s)
    response=client.post(base+'/clinical-questions/draft',json={});assert response.status_code==200,response.text
    state=next(n['state'] for n in response.json()['nodes'] if n['id']=='dispatch')
    draft=state['clinical_draft']
    assert client.get(base+'/clinical-questions/draft/files/pk_context.json').status_code==200
    assert client.get(base+'/clinical-questions/draft/files/nope.json').status_code==404
    assert client.get(base+'/nodes/pk/assigned-context').status_code==409
    payload={'values':draft['values'],'reviewer':'Synthetic only','confirmed':True,'index_exposure_source':'REQUIRES_PK_PREDICTIONS','draft_signature':'stale'}
    assert client.post(base+'/clinical-questions',json=payload).status_code==409
    payload['draft_signature']=draft['signature'];response=client.post(base+'/clinical-questions',json=payload)
    assert response.status_code==200,response.text
    s=store.load(sid);folder=tmp_path/'executed';execute(store.clinical_snapshot(s),s['nodes']['dispatch']['clinical_spec_ref'],folder)
    artifacts=read_json(folder/'artifact_manifest.json')['files'];store.record_completion(s,'dispatch',artifacts);write_json(store.path(sid),s)
    assert client.get(base+'/nodes/pk/assigned-context').status_code==409
    sig=s['nodes']['dispatch']['output_signature']
    r=client.post(base+'/nodes/dispatch/review',json={'decision':'APPROVE','reviewer':'Synthetic only','rationale':'','confirmed':True,'output_signature':sig})
    assert r.status_code==200,r.text
    r=client.get(base+'/nodes/pk/assigned-context');assert r.status_code==200,r.text
    assert not r.json()['model_release']
    (tmp_path/'qc/normalized/D1.csv').write_text('changed',encoding='utf-8')
    assert client.get(base+'/nodes/pk/assigned-context').status_code==409
