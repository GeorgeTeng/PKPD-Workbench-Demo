import copy
import json
from pathlib import Path
import pytest
from research_pipeline import data_test_workflow as t,data_agents as d,method_profiles as methods
from research_pipeline.common import read_json,write_json,PipelineError
from test_project_rule_agent import bundle,run as publish


@pytest.fixture
def rejected(bundle):
    publication=publish(bundle);main=Path(publication['main_ref']['path']);run=bundle[0]/'data'
    def generate(req,**kwargs):
        p=req['payload'];profile=next(x for x in methods.check_context(p['method_knowledge'])['profiles'] if x['id']=='MP002')
        good={'id':'N1','task_id':'T1','description':'Project need','kind':'DEFINITION','required_by':'BEFORE_QC',
            'fields':[],'rule_ids':[],'evidence':[{'source':'main:/objective','quote':p['objective']}],
            'origin':'PROJECT_EXPLICIT','method_profile_ids':[],'conditions':[]}
        bad={**copy.deepcopy(good),'id':'N2','origin':'METHOD_CANDIDATE','method_profile_ids':['MP002'],
            'conditions':['Only if the source makes this applicable'],
            'evidence':[{'source':'method:MP002','quote':json.dumps(profile,ensure_ascii=False)}]}
        return {'request_sha256':req['request_sha256'],'tasks':[{'id':'T1','objective':p['objective'],
            'destination':'pk','evidence':good['evidence']}],'requirements':[good,bad],'findings':[]}
    with pytest.raises(PipelineError,match='objective context'):t.run_stage(main,run,'define',generator=generate)
    audit=next((run/'data_agents/audit/DR').iterdir());before={n:(audit/n).read_bytes() for n in ['request.json','response.json']}
    manifest={'source_main_ref':d.file_ref(main),'failed_request_ref':d.file_ref(audit/'request.json'),
        'failed_response_ref':d.file_ref(audit/'response.json'),'affected_requirement_ids':['N2'],
        'instruction':'N2 must establish project relevance or be omitted with an explicit finding. Keep other records unchanged.'}
    write_json(run/'definition_correction.json',manifest)
    return main,run,audit,before


def test_bound_corrective_call_removes_unsupported_candidate_without_touching_valid_records(rejected):
    main,run,audit,before=rejected
    def correct(req,**kwargs):
        c=req['payload']['definition_correction'];assert c['authority']=='NON_EVIDENCE_TEST_CONTRACT_CORRECTION'
        out=copy.deepcopy(c['prior_rejected_response']);assert out['request_sha256']!=req['request_sha256']
        out['request_sha256']=req['request_sha256'];out['requirements']=out['requirements'][:1]
        out['findings']=[{'code':'METHOD_NOT_ESTABLISHED','affected_id':'N2','reason':'Project applicability not established',
            'needed_material':'Project endpoint clarification','required_by':'BEFORE_MODELING','severity':'FOLLOW_UP'}]
        return out
    result=t.run_stage(main,run,'define',generator=correct)
    assert result['status']=='COMPLETED_TEST_STAGE'
    assert read_json(run/'definition.json')['requirements']==read_json(audit/'response.json')['requirements'][:1]
    assert all((audit/n).read_bytes()==b for n,b in before.items())


@pytest.mark.parametrize('mutation',['main','request','response','schema','source','rules','target'])
def test_correction_binding_rejects_changes(rejected,mutation):
    main,run,audit,_=rejected;request=read_json(audit/'request.json');p=request['payload'];scope=p['test_scope']
    payload={k:v for k,v in p.items() if k not in ['stage','agent','policy_version','processing_rules','schema']}
    # The original base instruction is a prefix of the governed request; using the full text also remains exact here.
    schema=copy.deepcopy(p['schema'])
    if mutation in {'main','request','response'}:
        path=main if mutation=='main' else audit/(mutation+'.json');path.write_bytes(path.read_bytes()+b' ')
    elif mutation=='schema':schema['description']='Different'
    elif mutation=='source':payload['context_sources']['main:/objective']='Different'
    elif mutation=='rules':payload['project_rules'][0]['conditions']=['Changed']
    else:
        path=run/'definition_correction.json';v=read_json(path);v['affected_requirement_ids']=['UNKNOWN'];write_json(path,v)
    with pytest.raises(Exception):t.definition_correction(run,payload,schema,scope)


@pytest.mark.parametrize('mutation',['task','other_requirement','authority','omission_without_finding'])
def test_corrective_response_cannot_change_unrelated_content_or_authority(rejected,mutation):
    _,_,audit,_=rejected;prior=read_json(audit/'response.json');out=copy.deepcopy(prior)
    if mutation=='task':out['tasks'][0]['objective']='Different'
    elif mutation=='other_requirement':out['requirements'][0]['description']='Different'
    elif mutation=='authority':out['requirements'][1]['origin']='PROJECT_EXPLICIT'
    else:out['requirements']=out['requirements'][:1]
    with pytest.raises(PipelineError):t.check_definition_correction(out,{'definition_correction':{
        'prior_rejected_response':prior,'affected_requirement_ids':['N2']}})
