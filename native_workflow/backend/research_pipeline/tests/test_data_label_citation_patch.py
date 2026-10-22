import copy
import pytest
from research_pipeline import data_agents as d,data_test_workflow as t,data_label_citation_patch as patcher
from research_pipeline.common import write_json,read_json,PipelineError


@pytest.fixture
def fixed(tmp_path):
    main=write_json(tmp_path/'main.json',{'objective':'Test only'})
    scope={'source_main_ref':d.file_ref(main)}
    sources={'D':'{"kind":"document"}','D:line1':'Experiment S02-T3','D:line2':'n=4 as reported'}
    payload={'item_id':'D','page':1,'pages':1,'source_units':sources,'instructions':'Literal labels',
        'test_scope':scope,'requirements':[],'project_rules':[],'context_sources':{},'method_knowledge':None,'stage':'DC-label'}
    request=d.governed_request(copy.deepcopy(payload));qr=write_json(tmp_path/'original_request.json',request)
    label={k:'NOT_FOUND' for k,s in d.LABEL['properties'].items() if s.get('type')=='string'}
    for k,s in d.LABEL['properties'].items():
        if 'enum' in s:label[k]=s['enum'][0]
    label.update(item_id='D',additional_roles=[],requirement_ids=[],columns=[],
        evidence=[{'source':'D:line2','quote':'n=4 as reported'}],stated_values=[{'quantity':'n','value':'4',
        'unit':'NOT_FOUND','subject':'Experiment S02-T3','qualifiers':['as reported'],
        'evidence':[{'source':'D:line2','quote':'n=4 as reported'}]} for _ in range(54)])
    # Only the designated entry needs the new subject quote; all other fields stay fixed.
    for i,v in enumerate(label['stated_values']):
        if i!=18:v['evidence'].append({'source':'D:line1','quote':'Experiment S02-T3'})
    findings=[{'code':'F'+str(i),'affected_id':'D','reason':'Preserve conflict '+str(i),
        'needed_material':'Source clarification','required_by':'BEFORE_QC','severity':'FOLLOW_UP'} for i in range(8)]
    response={'request_sha256':request['request_sha256'],'labels':[label],'findings':findings}
    rr=write_json(tmp_path/'original_response.json',response)
    constraint={'version':patcher.VERSION,'label_index':0,'stated_value_index':18,'allowed_added_sources':['D:line1']}
    manifest={'source_main_ref':scope['source_main_ref'],'corrections':[{'item_id':'D','page':1,
        'failed_request_ref':d.file_ref(qr),'failed_response_ref':d.file_ref(rr),
        'source_units_sha256':d.digest(sources),'page_sha256':d.digest({k:payload[k] for k in ['item_id','page','pages','source_units']}),
        'instruction':'Return one citation only. Every other field and all findings are locked.',
        'response_constraint':constraint}]}
    write_json(tmp_path/'label_corrections.json',manifest)
    return tmp_path,t.label_correction(tmp_path,payload,scope),response


def test_patch_locks_54_facts_8_findings_runs_host_check_and_replays_proof(fixed):
    folder,payload,old=fixed;calls=[];checks=[]
    def generate(req,**kwargs):
        calls.append(req);assert set(req['payload']['schema']['properties'])=={'request_sha256','evidence'}
        return {'request_sha256':req['request_sha256'],'evidence':{'source':'D:line1','quote':'Experiment S02-T3'}}
    generate.executor_id='synthetic_citation_patch'
    def host_check(response):
        checks.append(True);assert response['findings']==old['findings']
        for v in response['labels'][0]['stated_values']:
            d.evidence_check(v['evidence'],payload['source_units'])
            for k in ('quantity','value','subject'):assert any(v[k] in e['quote'] for e in v['evidence'])
    result=patcher.invoke(d.invoke,folder,'DC-label',payload,model='gpt-6-sol',generator=generate,check=host_check)
    expected=copy.deepcopy(old);expected['request_sha256']=result['request_sha256']
    expected['labels'][0]['stated_values'][18]['evidence'].append({'source':'D:line1','quote':'Experiment S02-T3'})
    assert result==expected and len(checks)==1
    proof=folder/'data_agents/citation_patches'/result['request_sha256']/'proof.json'
    assert patcher.verify_proof(proof)['status']=='VALID_DERIVATION'
    assert patcher.invoke(d.invoke,folder,'DC-label',payload,model='gpt-6-sol',generator=generate,check=host_check)==result
    assert len(calls)==1 and len(checks)==2  # Cached raw patch is re-derived and rechecked.
    value=read_json(proof);path=value['derived_response_ref']['path'];tampered=read_json(path);tampered['findings']=[];write_json(path,tampered)
    with pytest.raises(Exception):patcher.verify_proof(proof)


@pytest.mark.parametrize('fault',['unknown_source','bad_quote','rewritten_findings','changed_fixed','changed_target','changed_sources'])
def test_patch_cannot_rewrite_or_cite_outside_bound_source(fixed,fault):
    _,payload,_=fixed;patch={'request_sha256':'x','evidence':{'source':'D:line1','quote':'Experiment S02-T3'}}
    if fault=='unknown_source':patch['evidence']['source']='OTHER'
    elif fault=='bad_quote':patch['evidence']['quote']='Invented'
    elif fault=='rewritten_findings':patch['findings']=[]
    elif fault=='changed_fixed':payload['contract_correction']['prior_rejected_response']['findings']=[]
    elif fault=='changed_target':payload['contract_correction']['response_constraint']['stated_value_index']=19
    else:payload['source_units']['D:line1']='Changed'
    with pytest.raises(Exception):patcher.derive(patch,payload)


def test_original_host_rejection_is_not_cached(fixed):
    folder,payload,_=fixed
    def generate(req,**kwargs):return {'request_sha256':req['request_sha256'],'evidence':{'source':'D:line1','quote':'Experiment S02-T3'}}
    generate.executor_id='synthetic_rejected_patch'
    def reject(_):raise PipelineError('ORIGINAL_CHECK','Still blocked')
    with pytest.raises(PipelineError,match='Still blocked'):patcher.invoke(d.invoke,folder,'DC-label',payload,generator=generate,check=reject)
    assert not list((folder/'data_agents/kept').glob('*.json'))
