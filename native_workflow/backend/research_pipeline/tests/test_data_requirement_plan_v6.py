"""Current nonhuman needs and source-bound future obligations stay separate."""
import copy
import pytest
from research_pipeline import data_requirement_plan_v6 as p
from test_data_requirement_plan_v4 import case,checkpoint


def current(case):
    main,view=copy.deepcopy(case[5]),copy.deepcopy(case[6])
    main['rules'][1].update(scope={'species':['human'],'stages':['clinical']},
        text='After PK validation and PD qualification simulate the specified human population for PTA.',
        conditions=['Required inputs permit PTA estimation.'],exceptions=[],
        usage={'used_in':['clinical']},requirement={'target':'human PTA'})
    main['rules'][0]['scope']['stages']=['prepare','clinical']
    payload,schema,sources,knowledge=p.build_payload(main,view)
    raw=copy.deepcopy(case[4]);raw['requirements']=raw['requirements'][:2]
    for row in raw['requirements']:
        row['task_scope']={'population':'NONHUMAN','input_role':'INPUT_DEFINITION','producer_method_use':None}
    return main,view,payload,schema,sources,knowledge,raw


def test_no_invented_current_pta_and_exact_future_handoff(case):
    main,view,payload,schema,sources,knowledge,raw=current(case)
    result=p.materialize(raw,payload,sources,knowledge)
    assert result['version']=='REQUIREMENT_PLAN_6.0'
    assert result['deferred_stage_handoff']==p.deferred_handoff(main)
    assert payload['current_stage_contract']['required_method_uses']==['MODEL_BASED','PD_INDEX','PD_TARGET']
    assert 'MP010' not in [m['id'] for m in payload['method_knowledge']['profiles']]
    assert [m['id'] for m in payload['deferred_method_knowledge']['profiles']]==['MP010']
    assert len(payload['project_rules'])==len(main['rules'])
    # A mixed prepare/clinical Rule remains current authority and is projected
    # only to its later recipient, without deferring its current preparation.
    assert payload['source_authority_contract']['main:/rules/0/text']['role']=='CURRENT_AUTHORITY'
    mixed=result['deferred_stage_handoff']['obligations'][0]
    assert mixed['recipient_stages']==['clinical'] and mixed['rule']['scope']['stages']==['prepare','clinical']
    future=result['deferred_stage_handoff']['obligations'][1]
    assert future['rule']['conditions']==main['rules'][1]['conditions']


@pytest.mark.parametrize('damage',['pta','mp010','human_population','human_observations','self_producer',
                                  'missing_producer','definition_producer','missing_pd_target'])
def test_current_scope_and_planned_producer_guards(case,damage):
    main,view,payload,schema,sources,knowledge,raw=current(case);row=raw['requirements'][0]
    if damage=='pta':row['method_uses']=['PTA']
    elif damage=='mp010':row['method_profile_ids']=['MP010']
    elif damage=='human_population':row['task_scope']['population']='HUMAN'
    elif damage=='human_observations':row['input_fields']=['observed human plasma concentration']
    elif damage=='self_producer':row['task_scope'].update(input_role='PLANNED_NONHUMAN_OUTPUT',producer_method_use='MODEL_BASED')
    elif damage=='missing_producer':row['task_scope']['input_role']='PLANNED_NONHUMAN_OUTPUT'
    elif damage=='definition_producer':row['task_scope']['producer_method_use']='PD_TARGET'
    else:raw['requirements'][1]['method_uses']=['PD_INDEX']
    with pytest.raises(Exception):p.materialize(raw,payload,sources,knowledge)


def test_planned_pk_product_can_feed_different_current_pd_consumer(case):
    main,view,payload,schema,sources,knowledge,raw=current(case)
    raw['requirements'][1]['task_scope'].update(input_role='PLANNED_NONHUMAN_OUTPUT',producer_method_use='MODEL_BASED')
    result=p.materialize(raw,payload,sources,knowledge)
    assert result['requirements'][1]['task_scope']['application_stages']==['NONHUMAN_PD']


def test_dr6_mock_replay_preserves_deferred_obligations(case,tmp_path,monkeypatch):
    main,view,payload,schema,sources,knowledge,raw=current(case)
    changed=list(case);changed[5]=main;changed[6]=view
    source,baseline=checkpoint(changed,tmp_path,monkeypatch)
    def generate(request,**kw):
        value=copy.deepcopy(raw);value['request_sha256']=request['request_sha256'];return value
    out=tmp_path/'dr6'
    result=p.run(source,out,input_bindings=baseline,generator=generate)
    assert p.verify_plan(out/'plan.json')==result
    result['deferred_stage_handoff']['obligations'][1]['rule']['conditions']=[]
    p.write_json(out/'plan.json',result)
    with pytest.raises(Exception,match='raw derivation'):p.verify_plan(out/'plan.json')
