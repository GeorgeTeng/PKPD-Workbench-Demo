"""Compression rules 1.29.0: a single item the host cannot confirm is removed and listed instead of stopping the run.
Authored responses exercise the host contract, not model accuracy."""
import copy

import pytest

from ctxcomp import binding_repair as repair
from ctxcomp import supporting
from ctxcomp.bindings import STRICT, binding_diagnostics, options, value_location
from ctxcomp.citation_repair import verify_proof
from ctxcomp.engine import accept, init_run, prepare
from ctxcomp.io import digest, read_json
from ctxcomp.matching import contains
from ctxcomp.providers import run_model
from ctxcomp.rules import load_rules
from ctxcomp.schemas import SCHEMAS
from ctxcomp.supporting_agents import execute
from attachment_fixture import accept_empty_search
from rule_versions import before_1_29, cc002, freeze
from test_binding_repair import runner
from test_retention import EXAMPLES, reference_run
from test_scientific_extraction import scientific_fixture
from test_supporting_agents import request
from test_table_context import row, table_run

MARKED = dict(quote_matching='NORMALIZED', unconfirmed_citations='REMOVE_AND_MARK')
POLICY = {'max_attempts_per_response': 1, 'alternative_sources': True, 'approved_excerpts': True}


@pytest.mark.parametrize('source,quote', [
    ('Mouse thigh model', 'mouse  thigh model'), ('24 ± 17', '24 +/- 17'), ('24 ± 17', '24+-17'),
    ('0.5–2 h', '0.5 - 2 h'), ('“free” drug', '"free" drug'), ('AUC / MIC', 'AUC/MIC'), ('Mouse thigh model', 'Mouse thigh model.')])
def test_a_normalized_quote_matches_across_case_spacing_and_spelling(source, quote):
    assert not contains(source, quote) and contains(source, quote, loose=True)


@pytest.mark.parametrize('source,quote', [
    ('24 ± 17', '24 ± 71'), ('1.5 mg', '15 mg'), ('1.5 mg', '1,5 mg'), ('<5 h', '≤5 h'), ('free drug', 'total drug'), ('x', ' . ')])
def test_normalization_keeps_digits_decimal_points_signs_and_words(source, quote):
    assert not contains(source, quote, loose=True)


def evidence(switches=MARKED):
    req = request(); p = req['payload']
    p['processing_rules'] = {'rules': p['processing_rules']['rules'] + cc002(**switches)['rules']}
    p['citation_repair_policy'] = POLICY
    return {'request_sha256': digest(p), 'payload': p}


def answered(req, citations, status='FOUND'):
    return {'request_sha256': req['request_sha256'], 'answers': [{'question_id': 'MI001', 'status': status,
            'statement': 'Binding evidence.', 'reason': 'Authored test.', 'citations': citations}]}


@pytest.mark.parametrize('switches', [MARKED, {}])
def test_a_quote_differing_only_in_spelling_validates_from_1_29(switches):
    req = evidence(switches); text = req['payload']['passages'][0]['text']
    response = answered(req, [{'passage_id': 'F1_0', 'quote': text.upper().replace(' ', '  ')}])
    if switches:
        supporting.validate(req, response)
    else:
        with pytest.raises(supporting.EvidenceCitationError): supporting.validate(req, response)


def generator(file_citations, review_decision=None, calls=None):
    """File calls cite file_citations(p); a synthesis cites its first supplied quote; reviews answer review_decision."""
    def generate(req, label):
        p = req['payload']
        if calls is not None: calls.append(label)
        if p['stage'] == 'attachment_citation_repair':
            return {'request_sha256': req['request_sha256'], 'decisions': [{'issue_id': x['issue_id'],
                    'decision': review_decision, 'source_id': x['citation']['passage_id'], 'quote': x['citation']['quote'],
                    'reason': 'Authored reviewer cannot confirm the quotation.'} for x in p['issues']]}
        if p['evidence_task']['mode'] == 'FILE_SEARCH':
            return answered(req, file_citations(p))
        cited = [{'passage_id': x['id'], 'quote': x['text']} for x in p['passages'][:1]]
        return answered(req, cited, 'FOUND' if cited else 'SEARCH_INCOMPLETE')
    return generate


def test_an_unknown_source_is_removed_without_a_review_call(tmp_path):
    req = evidence(); calls = []
    first = lambda p: [{'passage_id': p['passages'][0]['id'], 'quote': p['passages'][0]['text']},
                       {'passage_id': 'NOT_SUPPLIED', 'quote': 'Invented.'}]
    result = execute(req, tmp_path, generator(first, calls=calls))
    assert not any('citation_repair' in c for c in calls)
    corrected = read_json(tmp_path/'file_0001/citation_repair/corrected_response.json')['answers'][0]
    assert [c['passage_id'] for c in corrected['citations']] == ['F1_0'] and corrected['status'] == 'SEARCH_INCOMPLETE'
    assert corrected['reason'].startswith('Unconfirmed by the host: citation NOT_SUPPLIED removed: unknown source.')
    listed = read_json(tmp_path/'unconfirmed_evidence.json')['citations']
    assert {(x['call'], x['citation_id'], x['stage']) for x in listed} == {
        ('file_0001', 'NOT_SUPPLIED', 'host_check'), ('file_0002', 'NOT_SUPPLIED', 'host_check')}
    assert all(x['request_sha256'] == req['request_sha256'] for x in listed)
    assert verify_proof(tmp_path/'proof.json', req, result) == []


def test_an_unresolved_review_removes_the_citation_and_marks_the_answer(tmp_path):
    req = evidence()
    wrong = lambda p: [{'passage_id': p['passages'][0]['id'], 'quote': 'Deliberately incorrect quotation.'}]
    result = execute(req, tmp_path, generator(wrong, 'UNRESOLVED'))
    assert result['answers'][0]['status'] == 'SEARCH_INCOMPLETE' and result['answers'][0]['citations'] == []
    review = read_json(tmp_path/'file_0001/citation_repair/result.json')
    assert [x['stage'] for x in review['unconfirmed']] == ['citation_review']
    assert 'cannot confirm' in review['unconfirmed'][0]['reason']
    verify_proof(tmp_path/'proof.json', req, result)


def test_runs_frozen_before_1_29_still_stop_on_an_unconfirmed_citation(tmp_path):
    req = evidence({})
    wrong = lambda p: [{'passage_id': p['passages'][0]['id'], 'quote': 'Deliberately incorrect quotation.'}]
    with pytest.raises(ValueError): execute(req, tmp_path, generator(wrong, 'UNRESOLVED'))
    assert not (tmp_path/'unconfirmed_evidence.json').exists()


def test_a_live_run_continues_and_keeps_the_material_question_as_a_warning(tmp_path):
    from test_runtime_rules import evidence_run
    run, q, _ = evidence_run(tmp_path)
    wrong = lambda p: [{'passage_id': p['passages'][0]['id'], 'quote': 'Deliberately incorrect quotation.'}]
    def model(req, model=None):
        return generator(wrong, 'UNRESOLVED')(req, 'live')
    assert run_model(run, generator=model, until='attachment_evidence')['status'] == 'STAGE_READY'
    listed = read_json(run/'audit/unconfirmed_evidence.json')['citations']
    assert [(x['question_id'], x['stage']) for x in listed] == [('MI001', 'citation_review')]
    warnings = prepare(run, 'requirements')['payload']['missing_information_warnings']
    assert [(w['id'], w['status']) for w in warnings] == [('MI001', 'SEARCH_INCOMPLETE')]


def table_payload(tmp_path):
    run, fid, last, req = table_run(tmp_path)
    accept(run, 'attachment_evidence', {'request_sha256': req['request_sha256'], 'answers': [{
        'question_id': 'MI001', 'status': 'FOUND', 'statement': 'The free-drug 24-h AUC/MIC ratio is 24 ± 17.',
        'reason': 'Authored test.', 'citations': [{'passage_id': row(fid, last), 'quote': '24 ± 17'}]}]})
    p = prepare(run, 'requirements')['payload']
    units = p['source_units']; lookup = {u['id']: u for u in units}
    unit = next(u for u in units if u['source_id'] == row(fid, last))
    return p, units, lookup, [{'unit_id': unit['id'], 'source_id': unit['source_id'], 'quote': '24 ± 17'}]


@pytest.mark.parametrize('value,where', [('Neutropenic mice', 'TABLE_CONTEXT'), ('mouse', 'SHEET_NAME'),
                                         ('24 +/- 17', 'QUOTE'), ('Free drug', 'COLUMN_HEADER')])
def test_a_binding_value_may_sit_in_its_table_title_from_1_29(tmp_path, value, where):
    p, units, lookup, cited = table_payload(tmp_path)
    assert value_location(value, cited, lookup, units, options(p)) == where
    assert value_location(value, cited, lookup, units, STRICT) == (where if where == 'COLUMN_HEADER' else None)


def test_runs_frozen_before_1_29_match_binding_values_exactly(tmp_path, monkeypatch):
    freeze(monkeypatch, before_1_29())
    p = table_payload(tmp_path)[0]
    assert options(p) == STRICT


def binding_case(**switches):
    _, units, inv = scientific_fixture()
    inv['items'][2]['science']['bindings'][2]['value'] = '4.0 L/hour'
    p = {'stage': 'requirements', 'schema': SCHEMAS['requirements'], 'source_units': units,
         'processing_rules': cc002(**({'unconfirmed_bindings': 'DROP'} | switches))}
    parent = {'request_sha256': digest(p), 'payload': p}
    candidate = {'request_sha256': parent['request_sha256'], 'requirements': inv}
    return parent, candidate, units


def repair_reply(req, **entry):
    return {'request_sha256': req['request_sha256'], 'method_ref_repairs': [], 'repairs': [{
        'item_id': 'R003', 'binding_index': 2, 'status': 'CORRECTED', 'reason': 'Authored.',
        'replacements': [{'field': 'value', 'value': '4', 'component_ids': ['C1']}], **entry}]}


@pytest.mark.parametrize('fault,stage', [('unresolved', 'binding_repair'), ('drop', 'binding_repair'),
                                         ('component', 'binding_repair'), ('fabricate', 'after_repair')])
def test_a_binding_the_repair_cannot_confirm_is_dropped(fault, stage):
    parent, candidate, units = binding_case()
    details = binding_diagnostics(candidate['requirements'], units)
    req = repair.make_request(parent, candidate, details, load_rules())
    entry = {'unresolved': {'status': 'UNRESOLVED', 'replacements': []}, 'drop': {'replacements': []},
             'component': {'replacements': [{'field': 'value', 'value': '4', 'component_ids': ['C999']}]},
             'fabricate': {'replacements': [{'field': 'value', 'value': '400', 'component_ids': ['C1']}]}}[fault]
    fixed, removed = repair.apply_response(parent, candidate, req, repair_reply(req, **entry), with_drops=True)
    want = copy.deepcopy(candidate['requirements']); want['items'][2]['science']['bindings'].pop(2)
    assert fixed['requirements'] == want
    assert [(x['item_id'], x['binding_index'], x['stage']) for x in removed] == [('R003', 2, stage)]


def test_an_invalid_component_selection_is_dropped_without_a_call(tmp_path):
    parent, candidate, units = binding_case()
    candidate['requirements']['items'][2]['science']['bindings'][2].update(value='4', component_ids=['C999'])
    details = binding_diagnostics(candidate['requirements'], units)
    assert [i['reason'] for i in details['issues']] == ['INVALID_COMPONENT_SELECTION']
    assert 'INVALID_COMPONENT_SELECTION' in repair.handled(load_rules(), parent['payload'])
    assert 'INVALID_COMPONENT_SELECTION' not in repair.handled(load_rules(), {})
    directory = tmp_path/'audit/binding_repairs/one'
    fixed = repair.execute(parent, candidate, details, load_rules(), directory, lambda request: pytest.fail('no call'))
    want = copy.deepcopy(candidate['requirements']); want['items'][2]['science']['bindings'].pop(2)
    assert fixed['requirements'] == want
    assert read_json(directory/'result.json')['attempts'] == 0
    assert [x['stage'] for x in read_json(tmp_path/'audit/unconfirmed_evidence.json')['bindings']] == ['host']


def test_a_reply_that_cannot_be_applied_drops_every_flagged_binding(tmp_path):
    parent, candidate, units = binding_case()
    details = binding_diagnostics(candidate['requirements'], units)
    def duplicate(request):
        reply = repair_reply(request); reply['repairs'] *= 2; return reply
    fixed = repair.execute(parent, candidate, details, load_rules(), tmp_path/'a/b', duplicate)
    result = read_json(tmp_path/'a/b/result.json')
    assert result['corrected_sha256'] == digest(fixed) and result['original_sha256'] == digest(candidate)
    assert [x['binding_index'] for x in result['dropped_bindings']] == [2]


def test_a_component_quote_missing_from_its_source_still_stops():
    parent, candidate, units = binding_case()
    candidate['requirements']['items'][2]['components'][0]['evidence'][0]['quote'] = 'Not in the source.'
    reasons = {i['reason'] for i in binding_diagnostics(candidate['requirements'], units)['issues']}
    assert 'CITED_EVIDENCE_INVALID' in reasons
    assert not reasons <= repair.handled(load_rules(), parent['payload'])


def test_a_live_run_drops_the_unconfirmed_binding_and_reaches_review(tmp_path, reference_run):
    run = tmp_path/'run'; init_run(run, EXAMPLES/'current_research/proposal.md', context_review_mode='parallel_v1')
    accept_empty_search(run); calls = []
    assert run_model(run, generator=runner(reference_run, calls, False, True))['status'] == 'CONTEXT_READY'
    assert calls.count('binding_repair') == 1 and 'requirements_review' in calls
    dropped = read_json(run/'audit/unconfirmed_evidence.json')['bindings']
    assert [(x['value'], x['stage']) for x in dropped] == [('still rewritten', 'after_repair')]
