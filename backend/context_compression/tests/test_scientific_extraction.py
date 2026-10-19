"""A/B/C contract tests with authored examples, not measured LLM accuracy."""
import copy
import json
import pytest

from ctxcomp import scientific, split_review as split
from ctxcomp.engine import init_run, prepare, accept, verify_context
from ctxcomp.io import read_json, write_json, digest
from ctxcomp.retention import source_units, requirements_check, requirements_review_check
from ctxcomp.schemas import MAIN, SCHEMAS, validate_schema
from ctxcomp.rules import load_rules
from ctxcomp.providers import run_model
from attachment_fixture import accept_empty_search
from test_retention import reference_run, replay_until, demo
from test_split_review import split_run, authored_response


def scientific_fixture():
    sources = [{'id': 'S1', 'file_id': 'F1', 'name': 'proposal.txt', 'role': 'PROPOSAL',
                'locator': 'Full text', 'original_sha256': 'a'*64,
                'text': 'Predict human PK.\n\nUse allometric scaling.\n\nHuman CL was predicted to be 4 L/h using allometric scaling.\n\nAssume constant human fu for this simulation.'}]
    units = source_units(sources)
    quotes = {f'/checks/{i}': u['text'].strip() for i, u in enumerate(units)}
    inventory = demo.fixture_requirements(quotes, units)
    for item, role, status in zip(inventory['items'], ['OBJECTIVE','METHOD','RESULT','ASSUMPTION'],
                                  ['NOT_APPLICABLE','NOT_APPLICABLE','PREDICTED','ASSUMED']):
        item['science'].update(role=role, evidence_status=status)
    result = inventory['items'][2]['science']
    result['method_refs'] = ['R002']
    result['bindings'] = [{'field': field, 'value': value, 'component_ids': ['C1']}
                          for field, value in [('species','Human'),('parameter','CL'),('value','4'),('units','L/h')]]
    inventory['items'][3]['science']['adoption_relations'] = [
        {'target_id':'R003','used_for':'this simulation','conditions':[], 'component_ids':['C1']}]
    inventory['potential_questions'] = [{'id':'Q001','statement':'Does constant fu apply to the intended exposure range?',
        'reason':'The stated assumption does not specify an exposure range.', 'origin':'MODEL_INFERENCE',
        'status':'PENDING_CONFIRMATION','needed_at':'human_pk','impact':'Unbound predictions need a qualified binding assumption.',
        'source_refs':inventory['items'][3]['components'][0]['evidence']}]
    return sources, units, inventory


def test_profile_is_frozen_scoped_and_keeps_13_categories(tmp_path):
    proposal=tmp_path/'proposal.txt'; proposal.write_text('Predict human PK.')
    run=tmp_path/'run'; init_run(run,proposal); accept_empty_search(run)
    p=prepare(run,'requirements')['payload']; pack=load_rules()
    assert p['processing_rules']['scientific_extraction']==pack['scientific_extraction']
    assert p['processing_rules']['pk_binding_knowledge']==pack['pk_binding_knowledge']
    assert pack['pk_binding_knowledge']['version']=='2.0.0'
    assert len(pack['pk_binding_knowledge']['groups'])==8
    assert len({g['id'] for g in pack['pk_binding_knowledge']['groups']})==8
    assert len(next(r for r in pack['rules'] if r['id']=='CC005')['details']['preserve'])==13
    assert 'scientific_extraction' not in prepare(run,'attachment_plan')['payload']['processing_rules']
    assert read_json(run/'audit/processing_rules.json')['scientific_extraction']==pack['scientific_extraction']


def test_new_request_requires_typed_inventory_but_legacy_schema_remains_usable():
    sources,units,inv=scientific_fixture()
    requirements_check(inv,units)
    new=scientific.response_schema('requirements',SCHEMAS['requirements'],True)
    old=scientific.response_schema('requirements',SCHEMAS['requirements'],False)
    response={'request_sha256':'fixture','requirements':inv}; validate_schema(response,new)
    legacy=copy.deepcopy(response); legacy['requirements']['version']='1.0'
    legacy['requirements'].pop('potential_questions')
    for item in legacy['requirements']['items']: item.pop('science')
    validate_schema(legacy,old)
    with pytest.raises(ValueError): validate_schema(legacy,new)
    # Building requests must not mutate reusable schema objects.
    assert scientific.response_schema('requirements',SCHEMAS['requirements'],True)==new


@pytest.mark.parametrize('fault', ['missing_component','invented_value','wrong_method','inferred_as_assumption','question_as_fact','unknown_relation'])
def test_invalid_extraction_cannot_enter_review(fault):
    _,units,inv=scientific_fixture(); s=inv['items'][2]['science']
    if fault=='missing_component': s['bindings'][0]['component_ids']=['C99']
    elif fault=='invented_value': s['bindings'][0]['value']='rat'
    elif fault=='wrong_method': s['method_refs']=['R001']
    elif fault=='inferred_as_assumption': inv['items'][3]['science']['evidence_status']='PREDICTED'
    elif fault=='question_as_fact': inv['potential_questions'][0]['status']='CONFIRMED'
    else: s['relations']=[{'type':'USES','target_id':'Q001','component_ids':['C1']}]
    with pytest.raises(ValueError): requirements_check(inv,units)


def test_pending_question_must_be_reviewed_and_cannot_disappear():
    _,units,inv=scientific_fixture(); r=demo.fixture_requirements_review(inv,units)
    with pytest.raises(ValueError,match='exactly once'): requirements_review_check(r,inv,units)
    r['items'].append({'requirement_id':'Q001','verdict':'PRESERVED','reason':'A justified question, not a fact.'})
    for unit in r['source_units']:
        if any(s['unit_id']==unit['unit_id'] for s in inv['potential_questions'][0]['source_refs']): unit['requirement_ids'].append('Q001')
    requirements_review_check(r,inv,units)


def test_projection_keeps_status_links_pending_question_and_exact_locations():
    sources,units,inv=scientific_fixture(); value=scientific.project(inv,units,sources)
    assert value['items'][2]['science']['evidence_status']=='PREDICTED'
    assert value['items'][2]['science']['method_refs']==['R002']
    assert value['potential_questions'][0]['status']=='PENDING_CONFIRMATION'
    ref=value['items'][2]['source_refs'][0]
    assert sources[0]['text'][ref['start_char']:ref['end_char']]==inv['items'][2]['statement']
    assert 'quote' not in ref
    partial=scientific.scoped_projection(value,['R003'])
    assert {i['id'] for i in partial['items']}=={'R002','R003'}
    assert not partial['potential_questions']


def test_compact_projection_removes_audit_only_and_keeps_semantic_dependencies():
    sources, units, inv = scientific_fixture()
    audit = scientific.project(inv, units, sources)
    compact = scientific.compact_projection(audit)
    scientific.validate_handoff(compact)
    assert compact['version'] == '2.0'
    assert compact['items'][2]['statement'] == audit['items'][2]['statement']
    assert compact['items'][2]['science']['evidence_status'] == 'PREDICTED'
    assert compact['items'][3]['science']['adoption_relations'] == [
        {'target_id':'R003', 'used_for':'this simulation', 'conditions':[]}]
    assert compact['potential_questions'][0]['needed_at'] == 'human_pk'
    serialized = json.dumps(compact)
    for key in ('bindings', 'source_refs', 'sources', 'component_ids', 'start_char', 'quote'):
        assert f'"{key}":' not in serialized
    routed = scientific.from_context_citations({'scientific_context':compact}, [
        {'path':'/scientific_context/items/2', 'quote':'4 L/h'}])
    assert {i['id'] for i in routed['items']} == {'R002', 'R003'}
    assert 'sources' in audit and 'bindings' in audit['items'][2]['science']


def test_citation_routing_includes_dependencies_and_never_guesses_from_names():
    sources,units,inv=scientific_fixture(); main={'scientific_context':scientific.project(inv,units,sources)}
    projected=scientific.from_context_citations(main,[{'path':'/scientific_context/items/2','quote':'4 L/h'}])
    assert {i['id'] for i in projected['items']}=={'R002','R003'}
    assert scientific.from_context_citations(main,[{'path':'/study/drug','quote':'Human CL'}])['items']==[]
    with pytest.raises(ValueError): scientific.from_context_citations(main,[{'path':'/scientific_context/items/2','quote':'rat'}])


@pytest.mark.parametrize('branch',[split.FAITH,split.COMPLETE])
@pytest.mark.parametrize('fault',['missing','failed','false_pass'])
def test_scientific_review_gate_cannot_be_bypassed(split_run,branch,fault):
    run,original=split_run
    def generator(req,model=None):
        result=authored_response(req,original)
        if req['payload']['stage']==branch:
            if fault=='missing': result['review']['scientific_checks'].pop()
            else:
                result['review']['scientific_checks'][0].update(verdict='ALTERED',reason='Predicted human CL was mislabeled as observed.')
                if fault=='failed': result['review']['decision']='REVISE'
        return result
    if fault=='failed':
        assert run_model(run,generator=generator)['status']=='REVISE'
        assert any('mislabeled as observed' in e for e in read_json(run/'feedback/context.json')['critical_errors'])
    else:
        with pytest.raises(ValueError): run_model(run,generator=generator)
    assert not (run/'handoff/main.json').exists()


def test_final_review_sees_exact_published_extension_and_tampering_fails(split_run):
    run,original=split_run; seen=[]
    def generate(req,model=None):
        seen.append(req['payload']['scientific_context'])
        return authored_response(req,original)
    assert run_model(run,generator=generate)['status']=='CONTEXT_READY'
    main=read_json(run/'handoff/main.json')
    assert len(seen)==3 and all(s==main['scientific_context'] for s in seen)
    assert main['version']=='3.2' and main['rule_publication']=='PROJECT_RULES_AGENT'
    assert main['scientific_context']['version']=='2.0'
    assert 'bindings' not in json.dumps(main['scientific_context'])
    audit = read_json(run/'audit/scientific_context.json')
    assert audit['main_sha256'] == digest(main)
    assert audit['projection']['version'] == '1.0'
    verify_context(run)
    original_audit = copy.deepcopy(audit)
    audit['projection']['items'][0]['statement']='Unreviewed change'
    write_json(run/'audit/scientific_context.json',audit)
    with pytest.raises(ValueError,match='Scientific audit'): verify_context(run)
    write_json(run/'audit/scientific_context.json',original_audit)
    main['scientific_context']['items'][0]['science']['evidence_status']='OBSERVED'
    write_json(run/'handoff/main.json',main)
    with pytest.raises(ValueError): verify_context(run)


def test_historical_main_remains_valid_but_extension_cannot_use_old_version(reference_run):
    main=read_json(reference_run/'handoff/main.json'); validate_schema(main,MAIN)
    main['version']='3.0'
    with pytest.raises(ValueError): validate_schema(main,MAIN)
    main.pop('scientific_context'); validate_schema(main,MAIN)
