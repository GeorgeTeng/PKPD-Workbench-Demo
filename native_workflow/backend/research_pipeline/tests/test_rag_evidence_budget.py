"""Lossless packing and joint allocation, without scientific/model assertions."""
import copy
from pathlib import Path
import pytest
from research_pipeline import context_library
from research_pipeline.common import read_json

CONFIG = Path(__file__).resolve().parents[3] / 'outputs/RAG_Budget_20261016/candidate_config.json'

@pytest.fixture(scope='module')
def budgeter():
    return context_library.load_runtime(read_json(CONFIG)).evidence_budget


def knowledge(name, text, *, source='s'):
    return {'methods': [{'id': name, 'conditions': [text], 'limitations': [text],
                         'evidence_chunk_ids': [name + ':1'], 'source_ids': [source]}],
            'evidence': [{'id': name + ':1', 'source_id': source, 'text': text,
                          'locator': 'original:1', 'sha256': 'bound-hash'}],
            'sources': {source: {'id': source, 'limitations': 'keep', 'sha256': 'source-hash'}}}


def test_exact_text_sharing_keeps_every_occurrence_and_provenance(budgeter):
    k = knowledge('a', 'Repeated verbatim condition and source evidence. ' * 35)
    k['methods'][0]['unknown'] = None
    before = copy.deepcopy(k)
    packed = budgeter.compact(k)
    assert len(budgeter.canonical(packed)) < len(budgeter.canonical(k))
    assert budgeter.expand(packed) == before == k
    assert packed['evidence'][0]['locator'] == 'original:1'
    assert packed['evidence'][0]['sha256'] == 'bound-hash'
    assert packed['methods'][0]['evidence_chunk_ids'] == ['a:1']
    broken = copy.deepcopy(packed); broken['rag_text_encoding']['verbatim'].clear()
    with pytest.raises(ValueError, match='Missing verbatim'): budgeter.expand(broken)


def test_similar_conditions_are_not_merged(budgeter):
    text = 'Baseline wording repeated to provide a long condition. ' * 10
    k = knowledge('a', text)
    k['methods'][0]['limitations'] = [text + ' NOT APPLICABLE TO CHILDREN.']
    assert budgeter.expand(budgeter.compact(k)) == k


def test_conflicting_evidence_identity_rejected_even_if_not_selected(budgeter):
    a = knowledge('a', 'x' * 400); b = copy.deepcopy(a); b['evidence'][0]['text'] = 'changed'
    with pytest.raises(ValueError, match='Conflicting evidence'):
        budgeter.allocate([{'need_id':'one','knowledge':a},{'need_id':'two','knowledge':b}],
            lambda ids,k: {'knowledge':k}, budget=1000)


def background(ids, packed):
    return {'knowledge': packed, 'selected': sorted(ids), 'budget_gaps': sorted({'large','small1','small2'} - ids)}


def test_global_budget_avoids_first_need_consuming_everything(budgeter):
    candidates = [{'need_id': name, 'knowledge': knowledge(name, text)} for name,text in
        [('large','x'*1800),('small1','y'*450),('small2','z'*450)]]
    both = budgeter.compact(budgeter.union([c['knowledge'] for c in candidates[1:]]))
    limit = len(budgeter.canonical(background({'small1','small2'},both)))
    result, selected, audit = budgeter.allocate(candidates, background, budget=limit)
    assert selected == {'small1','small2'}
    assert audit['omitted_need_ids'] == ['large']
    assert len(budgeter.canonical(result)) <= limit
    reverse, ids, _ = budgeter.allocate(list(reversed(candidates)), background, budget=limit)
    assert ids == selected and reverse == result


def test_one_shared_packet_can_serve_two_needs_without_duplicate_cost(budgeter):
    k = knowledge('same', 'same original evidence ' * 40)
    packed = budgeter.compact(k)
    build = lambda ids, value: {'knowledge': value, 'selected': sorted(ids)}
    limit = len(budgeter.canonical(build({'a','b'}, packed)))
    result, ids, audit = budgeter.allocate([{'need_id':'a','knowledge':k},{'need_id':'b','knowledge':k}],build,budget=limit)
    assert ids == {'a','b'}
    assert budgeter.expand(result['knowledge']) == k
    assert audit['lossless_roundtrip_verified'] is True


def test_does_not_slice_an_over_budget_method_or_its_evidence(budgeter):
    k=knowledge('large','x'*3000)
    result, ids, audit=budgeter.allocate([{'need_id':'large','knowledge':k}], background, budget=500)
    assert not ids and audit['omitted_need_ids']==['large']
    assert result['knowledge']['methods']==[] and result['knowledge']['evidence']==[]
