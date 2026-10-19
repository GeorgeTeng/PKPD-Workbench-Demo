"""CC012 faithfulness: field/claim coverage, provenance and false PASS rejection."""
import pytest
from ctxcomp import split_review as split
from review_test_support import reference_run, split_run, branch_case, validate


def test_faithfulness_valid_review_has_its_own_contract(split_run):
    case = branch_case(split_run, split.FAITH)
    validate(case, split.FAITH)
    payload = case[1]['payload']
    assert payload['agent_contract']['task'].startswith('Check output-to-source')
    assert 'branch_reviews' not in payload
    assert set(case[2]['review']).isdisjoint({'coverage', 'source_units', 'checks'})


@pytest.mark.parametrize('fault', [
    'missing_field', 'duplicate_field', 'missing_decomposition', 'duplicate_atom',
    'wrong_candidate_quote', 'fabricated_source_quote', 'wrong_source_unit',
    'missing_source_evidence', 'changed_evidence_status', 'unmapped_atom', 'stale_request'
])
def test_faithfulness_rejects_invalid_claim_contract(split_run, fault):
    case = branch_case(split_run, split.FAITH)
    response = case[2]; r = response['review']
    atom = next(a for a in r['atomic_claims'] if a['status'] == 'EXPLICIT')
    if fault == 'missing_field': r['claims'].pop()
    elif fault == 'duplicate_field': r['claims'].append(dict(r['claims'][0]))
    elif fault == 'missing_decomposition': r['decomposition'].pop()
    elif fault == 'duplicate_atom': r['atomic_claims'].append(dict(atom))
    elif fault == 'wrong_candidate_quote': atom['quote'] = 'A sentence absent from this candidate.'
    elif fault == 'fabricated_source_quote': atom['evidence'][0]['quote'] = 'Fabricated source evidence.'
    elif fault == 'wrong_source_unit': atom['evidence'][0]['unit_id'] = 'UNKNOWN_UNIT'
    elif fault == 'missing_source_evidence': atom['evidence'] = []
    elif fault == 'changed_evidence_status': atom['status'] = 'PROPOSED'
    elif fault == 'unmapped_atom': r['decomposition'][0]['claim_ids'].append('UNKNOWN_ATOM')
    else: response['request_sha256'] = 'another_candidate_version'
    with pytest.raises(ValueError): validate(case, split.FAITH)


@pytest.mark.parametrize('collection', ['claims', 'atomic_claims', 'decomposition'])
@pytest.mark.parametrize('verdict', ['MISSING', 'ALTERED', 'UNRESOLVED'])
def test_faithfulness_cannot_pass_its_own_negative_finding(split_run, collection, verdict):
    case = branch_case(split_run, split.FAITH)
    case[2]['review'][collection][0]['verdict'] = verdict
    with pytest.raises(ValueError, match='PASS contradicts'): validate(case, split.FAITH)
    case[2]['review']['decision'] = 'NEEDS_REVIEW' if verdict == 'UNRESOLVED' else 'REVISE'
    validate(case, split.FAITH)  # Valid negative review; it must remain a failed release gate.
