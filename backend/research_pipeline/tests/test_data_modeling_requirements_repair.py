"""Regressions from the first live DR: absent branches and empty mapping arrays."""
import copy
import pytest

from research_pipeline import data_modeling_requirements_repair as repair
from test_data_modeling_requirements import case


def response(case):
    payload, _, _, _, original, _ = case
    schema = repair.response_schema(payload)
    result = {'request_sha256': 'test', 'requirements': [
        {k: copy.deepcopy(v) for k, v in n.items() if k != 'dataset_ids'} for n in original['requirements']],
        'branches': {name: [] for name in repair.BRANCHES}, 'findings': []}
    for task in original['method_feasibility']:
        for a in task['approaches']:
            result['branches'][a['analysis']].append({k: copy.deepcopy(v) for k, v in a.items() if k != 'analysis'})
    links = copy.deepcopy(original['data_links'])
    assignments = [{k: copy.deepcopy(v) for k, v in row.items() if k in ('source', 'scope', 'requirement_ids')}
                   for row in original['objective_coverage']]
    for key, rows, id_field in [('data_links', links, 'item_id'), ('objective_assignments', assignments, 'source')]:
        if schema['properties'][key]['type'] == 'object':
            result[key] = {row[id_field]: {k: v for k, v in row.items() if k != id_field} for row in rows}
        else:
            result[key] = rows
    if 'findings' not in schema['properties']:
        del result['findings']
    return result


def materialize(case, value):
    payload, _, sources, knowledge, original, _ = case
    return repair.materialize(value, payload, sources, knowledge, original)[0]


def test_three_branches_and_single_dataset_need_mapping(case):
    value = response(case)
    result = materialize(case, value)
    assert all('dataset_ids' not in n for n in result['requirements'])
    assert len(result['data_links']) == 3
    assert {a['analysis'] for t in result['method_feasibility'] for a in t['approaches']} == set(repair.BRANCHES)
    assert any('MP004' in n['method_profile_ids'] for n in result['requirements'])
    assert any('MP009' in n['method_profile_ids'] for n in result['requirements'])
    assert result['data_links'][0]['evidence'][0]['quote'] == case[2]['M:1']
    # An approach follows the item evidence through data_links; it need not copy the same quote.
    for t in value['branches'].values():
        for a in t:
            a['evidence_source_ids'] = [k for k in a['evidence_source_ids'] if not k.endswith(':1')]
    assert materialize(case, value)


@pytest.mark.parametrize('fault', ['missing_branch', 'empty_branch', 'missing_dataset', 'missing_objective',
    'redundant_mapping', 'unknown_evidence', 'wrong_method', 'disconnected_model', 'unknown_requirement'])
def test_live_failure_shapes_cannot_publish(case, fault):
    value = response(case)
    if fault == 'missing_branch':
        del value['branches']['MODEL_BASED']
    elif fault == 'empty_branch':
        value['branches']['MODEL_BASED'] = []
    elif fault == 'missing_dataset':
        rows = value['data_links']
        rows.pop(next(iter(rows))) if isinstance(rows, dict) else rows.pop()
    elif fault == 'missing_objective':
        rows = value['objective_assignments']
        rows.pop(next(iter(rows))) if isinstance(rows, dict) else rows.pop()
    elif fault == 'redundant_mapping':
        value['requirements'][0]['dataset_ids'] = ['M']
    elif fault == 'unknown_evidence':
        value['requirements'][0]['evidence_source_ids'].append('not-provided:1')
    elif fault == 'wrong_method':
        value['branches']['NCA'][0]['method_profile_ids'] = ['MP004']
    elif fault == 'disconnected_model':
        value['branches']['MODEL_BASED'][0]['requirement_ids'] = ['Q0']
    elif fault == 'unknown_requirement':
        value['branches']['PD_INDEX'][0]['requirement_ids'] = ['INVENTED']
    with pytest.raises(Exception):
        materialize(case, value)


def test_later_scope_does_not_create_a_current_requirement(case):
    result = materialize(case, response(case))
    assert any(r['scope'] == 'DEFERRED' and not r['requirement_ids'] for r in result['objective_coverage'])
    assert all(n['id'] != 'DOWNSTREAM-HUMAN' for n in result['requirements'])
