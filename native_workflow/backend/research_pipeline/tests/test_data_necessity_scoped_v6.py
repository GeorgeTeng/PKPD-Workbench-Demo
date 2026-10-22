import copy
import pytest
from research_pipeline import data_necessity_scoped_v6 as nec,data_requirement_plan_v6 as dr
from research_pipeline import data_assessment_workflow as workflow,data_coverage_scoped_v3 as cov
from research_pipeline import data_human_summary_scoped_v5 as summary
from research_pipeline.common import read_json,write_json
from test_data_coverage_scoped_v3 import scoped,legacy_case,no_provider,answer as prior_answer


def answer(request,**kw):
    raw=prior_answer(request,**kw)
    if request['payload']['stage']=='NECESSITY_SCOPED_ASSESSMENT':raw['action_decisions'].pop('PTA')
    return raw


@pytest.fixture
def assessed(scoped):
    plan,source,main,out=scoped
    m=read_json(main)
    m['rules'][0]['scope']={'stages':['prepare']}
    m['rules'].append({'id':'PTA-FUTURE','text':'After PK validation and PD qualification perform human PTA.',
        'scope':{'stages':['clinical'],'species':['human'],'endpoint':'PTA'},'conditions':['Inputs permit PTA estimation.'],
        'exceptions':[],'usage':{'used_in':['clinical']},'requirement':{'target':'human PTA'}})
    write_json(main,m)
    s=read_json(source);s['main_ref']=cov.rt.file_ref(main);write_json(source,s)
    p=read_json(plan);p['version']=dr.VERSION;p['bindings']['main']=cov.rt.file_ref(main)
    inv=read_json(p['bindings']['inventory']['path']);inv['main']=cov.rt.file_ref(main)
    write_json(p['bindings']['inventory']['path'],inv);p['bindings']['inventory']=cov.rt.file_ref(p['bindings']['inventory']['path'])
    p['deferred_stage_handoff']=dr.deferred_handoff(m);write_json(plan,p)
    methods=write_json(out.parent/'methods.json',{'profiles':[{'id':'MP004'},{'id':'MP010'}]})
    run=out.parent/'dr6-assessment';calls=[]
    def generate(request,**kw):calls.append(request['payload']['stage']);return answer(request)
    workflow.run(plan,source,main,methods,run,generator=generate)
    return run,calls


def test_current_opinion_and_exact_future_pta_are_separate(assessed):
    run,calls=assessed
    result=nec.verify_result(run/'necessity/necessity.json')
    assert result['version']=='DIRECT_NECESSITY_6.0' and len(calls)==3
    assert result['action_decisions']['PTA']['readiness']=='LATER'
    assert result['action_decisions']['PTA']['gap_ids']==[]
    assert result['deferred_stage_handoff']['obligations'][-1]['rule']['conditions']==['Inputs permit PTA estimation.']
    prepared=read_json(run/'necessity/prepared.json')
    assert 'PTA' not in prepared['request']['payload']['schema']['properties']['action_decisions']['properties']
    assert 'MP010' not in [m['id'] for m in prepared['request']['payload']['local_method_knowledge']['profiles']]
    assert summary.verify_result(run/'human_summary/summary.json')['action_decisions']['PTA']['readiness']=='LATER'
    assert not result['scientific_approval'] and not result['downstream_executed']


def test_model_cannot_override_deferred_pta_or_assign_current_gaps(assessed):
    run,calls=assessed;p=read_json(run/'necessity/prepared.json');raw=answer(p['request'])
    raw['action_decisions']['PTA']=nec.deferred_pta_decision(p['deferred_stage_handoff'])
    with pytest.raises(Exception):nec.validate_response(raw,p)
    raw=answer(p['request']);raw['analyses'][0]['action_scopes'][0]['action_id']='PTA'
    with pytest.raises(Exception):nec.validate_response(raw,p)


def test_deferred_handoff_tampering_fails_replay(assessed):
    run,calls=assessed;p=read_json(run/'necessity/prepared.json')
    p['deferred_stage_handoff']['obligations'][-1]['rule']['conditions']=[]
    write_json(run/'necessity/prepared.json',p)
    with pytest.raises(Exception):nec.verify_result(run/'necessity/necessity.json')


def test_method_menu_without_actual_human_pta_scope_cannot_create_obligation():
    with pytest.raises(Exception,match='exact published human/clinical PTA scope'):
        nec.deferred_pta_decision({'obligations':[]})


@pytest.mark.parametrize('damage',['false_ready','missing_gap_link','missing_scope','duplicate_scope','false_aggregate'])
def test_current_action_shortage_guards_remain_strict_with_host_deferred_pta(assessed,damage):
    run,calls=assessed;p=read_json(run/'necessity/prepared.json');raw=answer(p['request'])
    analysis=raw['analyses'][0];decision=raw['action_decisions']['MODEL_BASED_ANIMAL_PK']
    analysis['impact']='BLOCKS_ACTION'
    decision['readiness']='NOT_READY';decision['scope_readiness'][0]['readiness']='NOT_READY'
    nec.validate_response(raw,p)
    if damage=='false_ready':
        decision['readiness']='READY';decision['scope_readiness'][0]['readiness']='READY'
    elif damage=='missing_gap_link':decision['gap_ids']=[]
    elif damage=='missing_scope':decision['scope_readiness'][0]['scope_id']='F1:mouse'
    elif damage=='duplicate_scope':decision['scope_readiness']*=2
    else:decision['readiness']='CONDITIONAL'
    with pytest.raises(Exception):nec.validate_response(raw,p)
