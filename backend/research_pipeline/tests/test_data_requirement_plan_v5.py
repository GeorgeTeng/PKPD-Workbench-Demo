"""Current nonhuman DR contract; offline fixtures only."""
import copy
import pytest
from research_pipeline import data_requirement_plan_v5 as p
from test_data_requirement_plan_v4 import case,checkpoint


def current(case):
    main, view = copy.deepcopy(case[5]), copy.deepcopy(case[6])
    main['rules'] += [
        {'id':'Scaling', 'text':'Translate supported animal models to human predictions.',
         'scope':{'species':['mouse','rat','rabbit'],'stages':['human_pk']},'usage':{'used_in':['human_pk']}},
        {'id':'Index', 'text':'Compare nonhuman indices.', 'conditions':['Eligible paired records exist.'],
         'exceptions':['Do not invent matching.'], 'scope':{'stages':['index']},'usage':{'used_in':['index']}}]
    payload, schema, sources, knowledge = p.build_payload(main,view)
    raw = copy.deepcopy(case[4])
    for row,stage in zip(raw['requirements'],('ANIMAL_PK','NONHUMAN_PD','NONHUMAN_PTA')):
        row['task_scope']={'population':'NONHUMAN','application_stage':stage,'input_role':'INPUT_DEFINITION'}
    return payload,schema,sources,knowledge,raw


def test_nonhuman_contract_and_host_inherited_constraints(case):
    payload,schema,sources,knowledge,raw=current(case)
    row=raw['requirements'][1]
    row.update(origin='PROJECT_EXPLICIT',project_source_ids=['main:/rules/3/text'],method_profile_ids=[])
    result=p.materialize(raw,payload,sources,knowledge)
    assert result['version']=='REQUIREMENT_PLAN_5.0'
    assert result['requirements'][1]['inherited_rule_constraints']==[{'source':'main:/rules/3/text',
        'conditions':['Eligible paired records exist.'],'exceptions':['Do not invent matching.']}]
    assert payload['project_rules'][2]['scope']['stages']==['human_pk']
    assert 'main:/rules/2/text' in payload['stage_output_contract']['later_context_source_ids']
    assert 'main:/rules/2/text' in sources
    assert payload['stage_output_contract']['reference_validation'].endswith('NOT_SEMANTIC_ENTAILMENT')
    assert 'unique' in schema['properties']['requirements']['items']['anyOf'][0]['properties']['project_source_ids']['description']


@pytest.mark.parametrize('damage',['later_scaling','wrong_use','human_prediction','human_actual','population',
                                   'wrong_application','duplicate_source','duplicate_condition','final_validation'])
def test_prior_failures_and_current_contract_contradictions_rejected(case,damage):
    payload,schema,sources,knowledge,raw=current(case)
    row=raw['requirements'][0]
    if damage=='later_scaling': row.update(origin='PROJECT_EXPLICIT',project_source_ids=['main:/rules/2/text'],method_profile_ids=[])
    elif damage=='wrong_use': row.update(origin='PROJECT_EXPLICIT',project_source_ids=['main:/rules/3/text'],method_profile_ids=[])
    elif damage=='human_prediction': row.update(description='Before human prediction, retain justified animal scaling inputs.',input_fields=['specified human doses and routes'])
    elif damage=='human_actual': row.update(description='For independent human PK validation, later task needs dose histories.',input_fields=['actual human dose histories','observed human plasma concentrations'])
    elif damage=='population': row['task_scope']['population']='HUMAN'
    elif damage=='wrong_application': row['task_scope']['application_stage']='NONHUMAN_PD'
    elif damage=='duplicate_source': row['project_source_ids']*=2
    elif damage=='duplicate_condition': row['conditions']*=2
    else: row['required_by']='FINAL_VALIDATION'
    with pytest.raises(Exception):p.materialize(raw,payload,sources,knowledge)


def test_prohibition_against_human_transfer_is_not_a_human_input(case):
    payload,schema,sources,knowledge,raw=current(case)
    raw['requirements'][1]['conditions']=['Do not transfer animal fu to human.']
    p.materialize(raw,payload,sources,knowledge)


def test_missing_task_contract_is_not_silently_added(case):
    payload,schema,sources,knowledge,raw=current(case)
    raw['requirements'][0].pop('task_scope')
    with pytest.raises(Exception):p.materialize(raw,payload,sources,knowledge)


def test_new_plan_exact_mock_replay_preserves_scope_and_rule_constraints(case,tmp_path,monkeypatch):
    source,baseline=checkpoint(case,tmp_path,monkeypatch)
    raw=copy.deepcopy(case[4])
    for row,stage in zip(raw['requirements'],('ANIMAL_PK','NONHUMAN_PD','NONHUMAN_PTA')):
        row['task_scope']={'population':'NONHUMAN','application_stage':stage,'input_role':'INPUT_DEFINITION'}
    def generate(request,**kw):
        result=copy.deepcopy(raw);result['request_sha256']=request['request_sha256'];return result
    out=tmp_path/'current'
    result=p.run(source,out,input_bindings=baseline,generator=generate)
    assert p.verify_plan(out/'plan.json')==result
    result['requirements'][0]['task_scope']['population']='HUMAN'
    p.write_json(out/'plan.json',result)
    with pytest.raises(Exception,match='raw derivation'):p.verify_plan(out/'plan.json')
