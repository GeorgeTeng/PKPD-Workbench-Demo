"""CC012 completeness: all sources/requirements/components and honest omissions."""
import pytest
from ctxcomp import split_review as split
from review_test_support import reference_run, split_run, branch_case, validate


def test_completeness_valid_review_covers_original_sources(split_run):
    case = branch_case(split_run, split.COMPLETE)
    validate(case, split.COMPLETE)
    p = case[1]['payload']
    assert p['agent_contract']['task'].startswith('Check source-to-output')
    assert p['source_units'] == case[0]['payload']['source_units']
    assert 'branch_reviews' not in p
    assert set(case[2]['review']).isdisjoint({'claims', 'atomic_claims', 'checks'})


@pytest.mark.parametrize('fault', [
    'missing_requirement', 'duplicate_requirement', 'missing_component', 'unknown_component',
    'missing_source_unit', 'duplicate_source_unit', 'missing_target',
    'invented_target', 'invalid_target_path', 'invented_retention_quote'
])
def test_completeness_rejects_incomplete_or_untraceable_coverage(split_run, fault):
    case = branch_case(split_run, split.COMPLETE)
    r = case[2]['review']; component = r['coverage'][0]['components'][0]
    if fault == 'missing_requirement': r['coverage'].pop()
    elif fault == 'duplicate_requirement': r['coverage'].append(dict(r['coverage'][0]))
    elif fault == 'missing_component': r['coverage'][0]['components'].pop()
    elif fault == 'unknown_component': component['component_id'] = 'UNKNOWN_COMPONENT'
    elif fault == 'missing_source_unit': r['source_units'].pop()
    elif fault == 'duplicate_source_unit': r['source_units'].append(dict(r['source_units'][0]))
    elif fault == 'missing_target': component['targets'] = []
    elif fault == 'invented_target': component['targets'][0]['quote'] = 'Not in this context.'
    elif fault == 'invalid_target_path': component['targets'][0]['path'] = '/study/unknown_field'
    else: r['retention'][0]['quote'] = 'Fabricated retention evidence.'
    with pytest.raises(ValueError): validate(case, split.COMPLETE)


def test_missing_source_requirement_outside_inventory_still_blocks_pass(split_run):
    case = branch_case(split_run, split.COMPLETE)
    r = case[2]['review']; r['source_units'][0]['verdict'] = 'MISSING'
    r['source_units'][0]['reason'] = 'Authored finding: a consequential source restriction was omitted from the inventory.'
    with pytest.raises(ValueError, match='PASS contradicts'): validate(case, split.COMPLETE)
    r['decision'] = 'REVISE'
    validate(case, split.COMPLETE)


def test_preserved_requirement_cannot_hide_an_omitted_component(split_run):
    case = branch_case(split_run, split.COMPLETE)
    r = case[2]['review']; r['decision'] = 'REVISE'
    r['coverage'][0]['components'][0]['verdict'] = 'MISSING'
    with pytest.raises(ValueError, match='contradicts component'): validate(case, split.COMPLETE)


def test_explicit_obligation_cannot_be_reclassified_as_optional_advice(split_run):
    case = branch_case(split_run, split.COMPLETE)
    target = case[2]['review']['coverage'][0]['components'][0]['targets'][0]
    entry = next(e for e in case[0]['payload']['evidence'] if e['path'] == target['path'])
    entry['status'] = 'PROPOSED'
    with pytest.raises(ValueError, match='Explicit obligation'): validate(case, split.COMPLETE)
