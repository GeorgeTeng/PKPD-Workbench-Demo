"""Shared DR inputs bind to host-derived stage families; no live model calls."""
import copy
import pytest
from research_pipeline import data_requirement_plan_v5_1 as p
from test_data_requirement_plan_v4 import case,checkpoint
from test_data_coverage_scoped_v3 import scoped,legacy_case,no_provider,answer as current_answer


def current(case):
    main,view=copy.deepcopy(case[5]),copy.deepcopy(case[6])
    main['rules'] += [
        {'id':'Scaling','text':'Translate supported animal models to human predictions.',
         'scope':{'species':['mouse','rat','rabbit'],'stages':['human_pk']},'usage':{'used_in':['human_pk']}},
        {'id':'Index','text':'Compare nonhuman indices.','conditions':['Eligible paired records exist.'],
         'exceptions':['Do not invent matching.'],'scope':{'stages':['index']},'usage':{'used_in':['index']}}]
    payload,schema,sources,knowledge=p.build_payload(main,view)
    raw=copy.deepcopy(case[4])
    for row in raw['requirements']:
        row['task_scope']={'population':'NONHUMAN','input_role':'INPUT_DEFINITION'}
    return payload,schema,sources,knowledge,raw


def test_compact_applicability_preserves_original_rule_fields_and_exact_inheritance(case):
    payload,schema,sources,knowledge,raw=current(case)
    assert all(set(c)=={'role','permitted_method_uses'} for c in payload['source_authority_contract'].values())
    rule=payload['project_rules'][3]
    assert rule['project_source_id']=='main:/rules/3/text'
    assert rule['conditions']==['Eligible paired records exist.'] and rule['exceptions']==['Do not invent matching.']
    row=raw['requirements'][1]
    row.update(origin='PROJECT_EXPLICIT',project_source_ids=['main:/rules/3/text'],method_profile_ids=[])
    result=p.materialize(raw,payload,sources,knowledge)
    assert result['version']=='REQUIREMENT_PLAN_5.1'
    assert result['requirements'][1]['inherited_rule_constraints']==[{
        'source':'main:/rules/3/text','conditions':rule['conditions'],'exceptions':rule['exceptions']}]
    assert 'main:/rules/2/text' not in payload['direct_project_source_ids']
    assert payload['project_rules'][2]['scope']['stages']==['human_pk'] and 'main:/rules/2/text' in sources
    assert payload['stage_output_contract']['application_stage_derivation'].endswith('NO_MODEL_STAGE_ECHO')
    assert set(schema['properties']['requirements']['items']['anyOf'][0]['properties']['task_scope']['properties'])=={'population','input_role'}


@pytest.mark.parametrize('uses,expected',[
    (['MODEL_BASED','NCA','PD_INDEX','PD_TARGET'],{'ANIMAL_PK','NONHUMAN_PD'}),
    (['MODEL_BASED','PD_INDEX','PTA'],{'ANIMAL_PK','NONHUMAN_PD','NONHUMAN_PTA'}),
    (['PTA'],{'NONHUMAN_PTA'})])
def test_reusable_binding_need_derives_exact_multi_stage_set(case,uses,expected):
    payload,schema,sources,knowledge,raw=current(case)
    index=2 if uses==['PTA'] else 0
    row=raw['requirements'][index]
    row.update(description='Binding-dependent nonhuman inputs.',input_fields=['fu or bound fraction and source'],
        method_uses=uses,method_profile_ids=['MP007'])
    result=p.materialize(raw,payload,sources,knowledge)
    assert set(result['requirements'][index]['task_scope']['application_stages'])==expected
    assert 'application_stages' not in row['task_scope']


@pytest.mark.parametrize('damage',['single_stage_echo','stages_echo','human_stage','human_population','human_use',
    'unknown_use','later_scaling','wrong_use_reference','duplicate_use','duplicate_source','duplicate_conditions',
    'human_actual_fields','missing_scope'])
def test_stages_are_not_model_decisions_and_reference_checks_stay_strict(case,damage):
    payload,schema,sources,knowledge,raw=current(case);row=raw['requirements'][0]
    if damage=='single_stage_echo':row['task_scope']['application_stage']='ANIMAL_PK'
    elif damage=='stages_echo':row['task_scope']['application_stages']=['ANIMAL_PK','NONHUMAN_PD']
    elif damage=='human_stage':row['task_scope']['application_stages']=['HUMAN_PK']
    elif damage=='human_population':row['task_scope']['population']='HUMAN'
    elif damage=='human_use':row['method_uses']=['HUMAN_PK']
    elif damage=='unknown_use':row['method_uses']=['UNKNOWN']
    elif damage=='later_scaling':row.update(origin='PROJECT_EXPLICIT',project_source_ids=['main:/rules/2/text'],method_profile_ids=[])
    elif damage=='wrong_use_reference':row.update(origin='PROJECT_EXPLICIT',project_source_ids=['main:/rules/3/text'],method_profile_ids=[])
    elif damage=='duplicate_use':row['method_uses']*=2
    elif damage=='duplicate_source':row['project_source_ids']*=2
    elif damage=='duplicate_conditions':row['conditions']*=2
    elif damage=='human_actual_fields':row['input_fields']=['actual human dose histories','observed human plasma concentrations']
    else:row.pop('task_scope')
    with pytest.raises(Exception):p.materialize(raw,payload,sources,knowledge)


def test_new_plan_exact_mock_replay_and_derived_stages_cannot_be_tampered(case,tmp_path,monkeypatch):
    source,baseline=checkpoint(case,tmp_path,monkeypatch)
    raw=copy.deepcopy(case[4])
    for row in raw['requirements']:row['task_scope']={'population':'NONHUMAN','input_role':'INPUT_DEFINITION'}
    def generate(request,**kw):
        result=copy.deepcopy(raw);result['request_sha256']=request['request_sha256'];return result
    out=tmp_path/'current'
    result=p.run(source,out,input_bindings=baseline,generator=generate)
    assert p.verify_plan(out/'plan.json')==result
    result['requirements'][0]['task_scope']['application_stages'].append('NONHUMAN_PD')
    p.write_json(out/'plan.json',result)
    with pytest.raises(Exception,match='raw derivation'):p.verify_plan(out/'plan.json')


def test_conditional_method_text_does_not_imply_a_human_input(case):
    payload,schema,sources,knowledge,raw=current(case)
    raw['requirements'][1]['conditions']=['Do not transfer animal fu to human.']
    p.materialize(raw,payload,sources,knowledge)
    assert 'Do not duplicate the same input need' in payload['instructions']
    assert 'Separate planned upstream PK/target products' in payload['instructions']
    assert 'required_by is the first actual consuming phase' in payload['instructions']


def test_dr5_1_routes_to_existing_strict_cov3_nec5_summary_consumers(scoped):
    from research_pipeline import data_assessment_workflow as workflow
    from research_pipeline import data_coverage_scoped_v3 as cov,data_necessity_scoped_v5 as nec
    from research_pipeline import data_human_summary_scoped_v4 as summary
    plan,source,main,out=scoped
    value=p.read_json(plan);value['version']=p.VERSION;p.write_json(plan,value)
    methods=p.write_json(out.parent/'methods.json',{'profiles':[{'id':'MP004'}]})
    run=out.parent/'current-5.1';calls=[]
    def generate(request,**kw):calls.append(request['payload']['stage']);return current_answer(request)
    workflow.run(plan,source,main,methods,run,generator=generate)
    assert cov.verify_result(run/'coverage/coverage.json')['version']=='DIRECT_DR_COVERAGE_3.0'
    assert nec.verify_result(run/'necessity/necessity.json')['version']=='DIRECT_NECESSITY_5.0'
    result=summary.verify_result(run/'human_summary/summary.json')
    assert len(calls)==3 and not result['scientific_approval'] and not result['downstream_executed']
