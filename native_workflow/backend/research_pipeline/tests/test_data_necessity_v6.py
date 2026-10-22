"""Scoped impact contract and resumable local execution, without a provider."""
import copy

import pytest
from research_pipeline import data_necessity_v6 as n
from research_pipeline.common import PipelineError, read_json, write_json
from test_data_necessity_v5 import inputs
from test_data_necessity_v4 import rules


def answer(payload):
    registry, _ = n.evidence_registry(payload)
    reviews = {}
    for gid, group in payload['review_groups'].items():
        allowed = {eid: span for eid, span in registry.items() if span['source'] in group['allowed_source_ids']}
        authority = next(eid for eid, span in allowed.items() if span['role'] == 'REFERENCE_OR_AUTHORITY')
        local = next((eid for eid, span in allowed.items() if span['role'] == 'LOCAL_SOURCE_EVIDENCE'), None)
        cited = [authority] + ([local] if local else [])
        reviews[gid] = {'impacts': [{'gap_keys': group['gap_keys'], 'level': 'UNCERTAIN',
            'explanation': 'Synthetic test: original qualification requires clarification.',
            'affected_actions': group['actions'], 'conditions': ['Subject to original input and scope conditions.'],
            'evidence_refs': cited}], 'can_continue': [], 'recommendations': [{
                'kind': 'REVIEW_EXISTING_SOURCE', 'suggestion': 'Clarify the recorded uncertainty from existing sources.',
                'conditions': ['Preserve original scope and unresolved conditions.'],
                'gap_keys': group['gap_keys'], 'evidence_refs': cited}],
            'follow_up': [{'gap_keys': group['gap_keys'], 'question': 'Can the existing source resolve the stated uncertainty?'}]}
    return {'request_sha256': 'synthetic', 'reviews': reviews}


def built():
    plan, coverage, catalog = inputs()
    return n.build_payload(plan, coverage, catalog, project_rules=rules())


def test_new_contract_is_task_impact_not_legacy_gap_action_matrix():
    payload = built()
    raw = answer(payload)
    result = n.resolve(raw, payload)
    assert 'decisions' not in raw and 'decisions' not in result
    assert len(raw['reviews']) == 1
    assert result['coverage_facts'] == payload['units']
    assert set(result['gap_evidence_map']) == {g['key'] for g in payload['gaps']}
    assert result['reports'][0]['impact_level'] == 'UNCERTAIN'
    assert result['formal_new_data_assessment'] == 'NOT_PERFORMED_CANDIDATE_ADVICE_ONLY'
    assert not any(result[k] for k in n.GATES)
    wire = n.transport_payload(payload)
    assert 'new_data' not in str(n.wire_schema(payload))
    assert 'impacts' in str(n.wire_schema(payload)) and 'criterion_groups' not in str(n.wire_schema(payload))
    assert wire['review_groups'] and 'coverage_facts' not in wire


@pytest.mark.parametrize('damage', ['omit', 'duplicate', 'foreign_gap', 'foreign_action', 'formal_new_data', 'empty_condition'])
def test_fail_closed_contract_without_rejudging_coverage(damage):
    payload = built()
    raw = answer(payload)
    review = next(iter(raw['reviews'].values()))
    impact = review['impacts'][0]
    if damage == 'omit': review['impacts'] = []
    elif damage == 'duplicate': impact['gap_keys'] *= 2
    elif damage == 'foreign_gap': impact['gap_keys'] = ['FOREIGN/GAP']
    elif damage == 'foreign_action': impact['affected_actions'] = ['SIMULATE_PER_MIC_PTA']
    elif damage == 'formal_new_data': review['recommendations'][0]['kind'] = 'NEW_DATA'
    else: impact['conditions'] = ['NONE']
    with pytest.raises(PipelineError):
        n.resolve(raw, payload)


def test_unresolved_can_receive_conditional_option_without_confirming_missing_data():
    payload = built()
    raw = answer(payload)
    advice = next(iter(raw['reviews'].values()))['recommendations'][0]
    advice.update(kind='CONDITIONAL_DATA_OPTION', suggestion='Consider an additional observation only if the original source cannot resolve the need.',
        conditions=['First complete source review, resolve design and planned outputs, and assess the original necessity criteria.'])
    result = n.resolve(raw, payload)
    reported = result['reports'][0]['recommendations'][0]
    assert reported['status'] == 'CONDITIONAL_CANDIDATE_ONLY'
    assert not reported['confirms_missing_data'] and not reported['experiment_authorized']
    assert result['coverage_facts'][0]['criteria'][1]['status'] == 'UNRESOLVED'


@pytest.mark.parametrize('field,text_key', [('impacts', 'explanation'), ('recommendations', 'suggestion'),
                                         ('follow_up', 'question'), ('can_continue', 'activity')])
def test_empty_report_prose_is_rejected(field, text_key):
    payload = built()
    raw = answer(payload)
    review = next(iter(raw['reviews'].values()))
    if field == 'can_continue':
        review[field] = [{'activity': ' ', 'conditions': ['Original scope must be retained.'],
                         'evidence_refs': review['impacts'][0]['evidence_refs']}]
    else:
        review[field][0][text_key] = ' '
    with pytest.raises(PipelineError, match='substantive'):
        n.resolve(raw, payload)


def test_local_mp_lookup_includes_unreferenced_family_profile_and_preserves_conditions():
    payload = built()
    assert 'method:local/MP011' in payload['evidence_catalog']  # NCA alternative knowledge, not a new requirement.
    row = payload['evidence_catalog']['method:local/MP011']
    profile = n.json.loads(row['content'])
    library = n.mp.load_library()
    assert profile == next(p for p in library['profiles'] if p['id'] == 'MP011')
    assert payload['local_mp_ref']['sha256'] == n.file_ref(n.mp.LIBRARY_PATH)['sha256']
    assert 'MP011' not in payload['requirements'][0]['method_profile_ids']
    assert payload['local_mp_context']['authority'] == 'CANDIDATE_KNOWLEDGE_ONLY_NOT_APPLICABILITY'


def test_no_current_impact_for_method_candidate_does_not_invent_project_rule_dependency():
    plan, coverage, catalog = inputs()
    need = plan['requirements'][0]
    need['project_source_ids'] = ['main:/objective']
    need['evidence'] = [{'source': 'main:/objective', 'quote': 'Assess animal PK using appropriate scoped inputs.'}]
    catalog.pop('main:/rules/0/text')
    catalog['main:/objective'] = need['evidence'][0]['quote']
    coverage['planning_sha256'] = n.digest(plan)
    payload = n.build_payload(plan, coverage, catalog, project_rules=[])
    raw = answer(payload)
    review = next(iter(raw['reviews'].values()))
    registry, _ = n.evidence_registry(payload)
    method = next(eid for eid, span in registry.items() if span['source'] == 'method:local/MP004')
    local = next(eid for eid, span in registry.items() if span['source'] == 'I1:note')
    review['impacts'][0].update(level='NO_CURRENT_IMPACT', affected_actions=[], evidence_refs=[method, local],
        explanation='Synthetic: the recorded individual-record limitation does not prevent a conditional group-level task.',
        conditions=['Only group-level quantities are contemplated; individual inference and original future input conditions remain unresolved.'])
    result = n.resolve(raw, payload)
    assert result['reports'][0]['impact_level'] == 'NO_CURRENT_IMPACT'
    assert result['coverage_facts'] == payload['units']
    assert result['fit_ready'] is False


def test_level_buckets_preserve_many_distinct_remedies_and_count_mapping_overhead():
    payload = built()
    group = next(iter(payload['review_groups'].values()))
    base = payload['gaps'][0]
    unit = payload['units'][0]
    for i in range(1, 10):
        criterion = {**copy.deepcopy(unit['criteria'][1]), 'id': 'FIELD_' + str(i + 1).zfill(3)}
        unit['criteria'].append(criterion)
        key = unit['unit_id'] + '/' + criterion['id']
        payload['gaps'].append({**base, 'key': key, 'criterion_id': criterion['id']})
        group['gap_keys'].append(key)
    raw = answer(payload)
    row = next(iter(raw['reviews'].values()))
    original = row['recommendations'][0]
    row['recommendations'] = [{**copy.deepcopy(original), 'gap_keys': [key], 'suggestion': 'Review specific gap ' + key}
                              for key in group['gap_keys']]
    assert len(n.resolve(raw, payload)['reports'][0]['recommendations']) == 10
    assert len(n.resolve(raw, payload)['reports'][0]['impacts'][0]['gap_keys']) == 10
    part = n._engine().partition(payload)[0]
    assert part['assessment_limit']['max_impact_judgments'] == 4
    assert part['assessment_limit']['gap_mapping_count'] == 10
    assert part['gap_criteria'] == part['assessment_limit']['admission_units'] > 4


def test_prepare_pause_fake_review_and_exact_replay(tmp_path, monkeypatch):
    plan, coverage, catalog = inputs()
    engine = n._engine()
    monkeypatch.setattr(engine, '_verified_inputs', lambda *args:
        (copy.deepcopy(plan), copy.deepcopy(coverage), copy.deepcopy(catalog), rules()))
    monkeypatch.setattr(n, '_engine', lambda: engine)
    pp = write_json(tmp_path/'inputs/plan.json', plan)
    cp = write_json(tmp_path/'inputs/coverage.json', coverage)
    out = tmp_path/'impact'
    prepared = n.prepare(pp, cp, out)
    assert prepared['version'] == n.VERSION
    assert read_json(out/'bindings.json')['impact_code'] == n.file_ref(n.__file__)
    assert prepared['assessment_limit']['admission_basis'].endswith('FULL_GAP_MAPPING_CHARACTERS')
    calls = []
    def generate(request, **kwargs):
        calls.append(kwargs['model'])
        payload = read_json(out/'parts/NEC01/payload.json')
        raw = answer(payload)
        raw['request_sha256'] = request['request_sha256']
        return raw
    generate.executor_id = 'offline-scoped-impact-v6'
    (out/'PAUSE').write_text('pause', encoding='utf-8')
    assert n.run_prepared(out, generator=generate)['stop_reason'] == 'PAUSED'
    assert not calls
    (out/'PAUSE').unlink()
    result = n.run_prepared(out, generator=generate)
    assert calls == ['gpt-6-sol']
    assert n.verify_result(out/'necessity.json') == result
    assert n.run_prepared(out, generator=generate) == result and len(calls) == 1
    build = read_json(out/'build.json')
    build['parts'][0]['assessment_limit']['max_impact_judgments'] = 0
    write_json(out/'build.json', build)
    with pytest.raises(PipelineError, match='capacity changed'):
        engine.verify_prepared(out)
