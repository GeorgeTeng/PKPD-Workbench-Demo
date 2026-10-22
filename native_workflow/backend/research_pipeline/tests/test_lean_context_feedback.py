"""Synthetic lean semantic stops remain actionable and bound to their candidate."""
import pytest
from ctxcomp.io import digest
from research_pipeline.common import write_json, read_json, utcnow
from research_pipeline.context_feedback import context_feedback


@pytest.fixture
def lean_stop(tmp_path):
    work = tmp_path / 'context_work'
    span = {'source_id': 'proposal', 'unit_id': 'U1', 'quote': 'Freeze before validation.'}
    candidate = {'context': {}, 'scientific_context': {}, 'missing_information': {},
                 'evidence': [{'id': 'SC02', 'citations': [span]}]}
    response = {'request_sha256': 'synthetic', **candidate}
    write_json(work / 'accepted/context.json', response)
    write_json(work / 'state.json', {'accepted': {'context': {'file': 'accepted/context.json', 'sha256': digest(response)}}})
    write_json(work / 'inputs.json', {'compression_profile': {'id': 'LEAN_1.0'},
                                    'source_units': [{'id': 'U1', 'text': span['quote']}]})
    review = {'decision': 'REVISE', 'critical_errors': ['One summary must not hide other findings.'],
              'records': [{'id': 'SC02', 'faithfulness': 'ALTERED', 'completeness': 'PRESERVED', 'reason': 'Freeze condition lost.'},
                          {'id': 'MI001', 'faithfulness': 'PRESERVED', 'completeness': 'MISSING', 'reason': 'Gap scope missing.'}],
              'source_units': [{'unit_id': 'U1', 'verdict': 'MISSING', 'record_ids': ['SC02'], 'reason': 'Retain timing.'}],
              'checks': [{'id': 'conditions_negation_units', 'verdict': 'ALTERED', 'reason': 'Temporal qualification changed.'}],
              'fixes': [{'id': 'F1', 'target': 'SC02', 'reason': 'Restore freeze timing.', 'citations': [span]}]}
    write_json(work / 'reviews/stop.json', {'candidate_sha256': digest(candidate), 'review': review})
    write_json(work / 'stopped.json', {'status': 'REVISE', 'stage': 'context_review', 'at': utcnow(), 'response': 'reviews/stop.json'})
    return work


def test_lean_feedback_reports_all_findings_with_canonical_ids(lean_stop):
    feedback = context_feedback(lean_stop.parent)
    issue = next(x for x in feedback['issues'] if x['requirement_ids'] == ['SC02'])
    assert issue['source_evidence'][0]['quote'] == 'Freeze before validation.'
    assert any(x['requirement_ids'] == ['MI001'] for x in feedback['issues'])
    assert any('Temporal qualification changed.' in x['reason'] for x in feedback['issues'])
    assert feedback['source_units'][0]['id'] == 'U1'
    assert not feedback['can_approve'] and not feedback['scientific_release']
    assert any(x['path'].endswith('context.json') for x in feedback['evidence_refs'])


def test_lean_feedback_rejects_candidate_drift(lean_stop):
    path = lean_stop / 'accepted/context.json'
    value = read_json(path)
    value['context'] = {'objective': 'changed'}
    write_json(path, value)
    with pytest.raises(ValueError, match='candidate|Candidate'):
        context_feedback(lean_stop.parent)
