"""New DR applicability contracts survive minimal model projection exactly."""
import copy

import pytest

from research_pipeline import context_builder as cb, context_routes
from research_pipeline import context_model_view as cmv
from research_pipeline.minimal_context_reducer import expand_payload


@pytest.mark.parametrize('version', ['REQUIREMENT_PLAN_4.0', 'REQUIREMENT_PLAN_5.0', 'REQUIREMENT_PLAN_5.1', 'REQUIREMENT_PLAN_6.0'])
def test_explicit_dr_version_uses_requirements_route(version):
    assert context_routes.select({'stage': 'DR', 'operation': version}) == ('data', 'requirements')


def test_dr5_authority_and_scope_are_not_moved_to_host_audit():
    rules = [
        {'id': 'R1', 'kind': 'PROJECT_REQUIREMENT', 'text': 'Use animal PK records.',
         'conditions': ['Only actual source record identity'], 'exceptions': ['Held-out horse'],
         'scope': {'stages': ['animal_pk']}, 'requirement': {'action': 'Define input'},
         'usage': {'used_in': ['animal_pk']}, 'provenance': {'main_pointer': '/rules/0'}},
        {'id': 'R2', 'kind': 'PROJECT_REQUIREMENT', 'text': 'Later human prediction.',
         'conditions': ['After translation approval'], 'exceptions': [],
         'scope': {'stages': ['human_pk']}, 'requirement': {'action': 'Predict'},
         'usage': {'used_in': ['human_pk']}, 'provenance': {'main_pointer': '/rules/1'}},
    ]
    authority = {
        'main:/rules/0/text': {'role': 'CURRENT_AUTHORITY', 'permitted_method_uses': ['MODEL_BASED'],
                              'scope': rules[0]['scope'], 'inherited_conditions': rules[0]['conditions']},
        'main:/rules/1/text': {'role': 'LATER_OR_HOLDOUT_CONTEXT', 'permitted_method_uses': [],
                              'scope': rules[1]['scope'], 'inherited_conditions': rules[1]['conditions']},
    }
    scope = {'population': 'NONHUMAN', 'later_context_source_ids': ['main:/rules/1/text'],
             'reference_validation': 'IDENTITY_AND_DECLARED_APPLICABILITY_ONLY_NOT_SEMANTIC_ENTAILMENT'}
    payload = {'stage': 'DR', 'operation': 'REQUIREMENT_PLAN_5.0',
               'instructions': 'Plan current nonhuman inputs only.',
               'project_context': {'objective': 'Animal PK'}, 'project_rules': rules,
               'method_knowledge': {}, 'data_overviews': [], 'overview_notes': [],
               'direct_project_source_ids': ['main:/rules/0/text'],
               'project_context_source_ids': ['main:/objective', 'main:/rules/0/text'],
               'source_authority_contract': authority, 'stage_output_contract': scope}
    schema = {'type': 'object', 'properties': {'source': {'enum': ['main:/rules/0/text']}}}
    before = copy.deepcopy(payload)
    bundle = cb.build_context('data', 'requirements', payload, schema)
    projected = cmv.view(bundle['request'])
    semantic = expand_payload(projected['payload'])
    assert payload == before
    assert semantic['source_authority_contract'] == authority
    assert semantic['stage_output_contract'] == scope
    assert semantic['schema'] == schema
    for original, actual in zip(rules, semantic['project_rules']):
        assert {k: actual[k] for k in original if k != 'provenance'} == {
            k: v for k, v in original.items() if k != 'provenance'}
    assert len(semantic['project_rules']) == 2
    assert bundle['context_manifest']['sections']['source_authority_contract']['kind'] == 'rules'
    assert bundle['context_manifest']['sections']['stage_output_contract']['kind'] == 'rules'


def test_coverage3_contract_and_necessity_typed_shortage_survive_projection():
    payload = {'stage': 'DIRECT_DR_COVERAGE', 'instructions': 'Compare by source and column.',
               'coverage_contract_version': 'DIRECT_DR_COVERAGE_3.0',
               'objective': 'Animal PK', 'requirements': [], 'rules': [], 'profiles': [], 'source_units': {}}
    bundle = cb.build_context('data', 'coverage', payload, {'type': 'object'})
    assert cmv.view(bundle['request'])['payload']['coverage_contract_version'] == 'DIRECT_DR_COVERAGE_3.0'
    scope = {'item_id': 'S1:plasma', 'column_header': 'Concentration', 'status': 'UNRESOLVED',
             'support_kind': 'MEASUREMENT_RECORDS', 'recorded_value_presence': 'PRESENT',
             'measurement': {'quantity': 'CONCENTRATION', 'unit': 'mg/L', 'basis': 'NOT_FOUND',
                             'record_level': 'Mean of terminal groups'},
             'unresolved_dimensions': ['basis'], 'source_ids': ['S1:plasma:A2'],
             'relation_source_ids': []}
    shortages = {'RQ1:F1': {'status': 'UNRESOLVED', 'source_scopes': [scope],
                            'unresolved_information': 'Value recorded, basis unresolved.'}}
    payload = {'stage': 'NECESSITY_SCOPED_ASSESSMENT', 'instructions': 'Assess accepted qualification shortages.',
               'objective': 'Animal PK', 'requirements': [], 'rules': [], 'coverage_summary': {},
               'recorded_shortages': shortages, 'local_method_knowledge': {}}
    bundle = cb.build_context('data', 'necessity', payload, {'type': 'object'})
    semantic = expand_payload(cmv.view(bundle['request'])['payload'])
    assert semantic['recorded_shortages'] == shortages


def test_dr51_existing_exact_rule_selector_is_not_echoed_as_second_id():
    from research_pipeline import context_minimal_policy
    from research_pipeline.minimal_context_reducer import reduce_payload
    rule = {'id': 'R1', 'text': 'Original rule', 'conditions': ['Current animal task'],
            'project_source_id': 'main:/rules/0/text', 'provenance': {'main_pointer': '/rules/0'}}
    payload = {'stage': 'DR', 'operation': 'REQUIREMENT_PLAN_5.1', 'project_rules': [rule],
               'project_context': {}, 'data_overviews': [],
               'direct_project_source_ids': ['main:/rules/0/text'],
               'project_context_source_ids': ['main:/rules/0/text']}
    reduced, _ = reduce_payload(payload, 'data.requirements', context_minimal_policy.load_policy()[0])
    semantic = expand_payload(reduced)
    assert semantic['project_rules'][0]['project_source_id'] == 'main:/rules/0/text'
    assert semantic['project_rules'][0]['conditions'] == ['Current animal task']
    assert 'output_source_ids' not in semantic['project_rules'][0]
    assert 'unmapped_authorized_source_refs' not in semantic


@pytest.mark.parametrize('stage,operation', [('DR','REQUIREMENT_PLAN_6.0'),('NECESSITY_SCOPED_ASSESSMENT',None)])
def test_deferred_stage_manifest_is_preserved_with_current_rules(stage,operation):
    rule={'id':'R1','kind':'PROJECT_REQUIREMENT','text':'Only after PK validation.',
          'conditions':['After PD qualification'],'exceptions':['No clinical efficacy claim'],
          'scope':{'stages':['prepare','clinical']},'requirement':{'action':'Define future population'},
          'usage':{'used_in':['prepare','clinical']}}
    manifest={'version':'DEFERRED_PROJECT_STAGE_HANDOFF_1.0','main_content_sha256':'a'*64,
              'later_rule_ids':['R1'],'accounting':'EXACT_HOST_INHERITANCE_NOT_CURRENT_DATA_REQUIREMENTS'}
    payload={'stage':stage,'instructions':'Keep current conditions and later recipient obligations.',
             'deferred_stage_handoff_manifest':manifest}
    if operation:
        payload.update(operation=operation,project_context={},project_rules=[rule],method_knowledge={},
            data_overviews=[],overview_notes=[],
            current_stage_contract={'required_method_uses':['MODEL_BASED','PD_INDEX','PD_TARGET'],
                'optional_method_uses':['NCA'],'source_scope':'NONHUMAN_CURRENT_EVIDENCE',
                'later_recipient_stages':['human_pk','clinical']},
            deferred_method_knowledge={'profiles':[{'id':'MP010','conditions':['Defined human population']}]})
        route='requirements'
    else:
        payload.update(objective='Animal evidence for later human prediction',requirements=[],rules=[rule],
            coverage_summary={},recorded_shortages={},local_method_knowledge={})
        route='necessity'
    bundle=cb.build_context('data',route,payload,{'type':'object'})
    semantic=expand_payload(cmv.view(bundle['request'])['payload'])
    assert semantic['deferred_stage_handoff_manifest']==manifest
    key='project_rules' if operation else 'rules'
    assert semantic[key][0]==rule
    if operation:
        assert semantic['current_stage_contract']==payload['current_stage_contract']
        assert semantic['deferred_method_knowledge']==payload['deferred_method_knowledge']
    assert bundle['context_manifest']['sections']['deferred_stage_handoff_manifest']['kind']=='rules'
