"""Noncontiguous cell quotes remain invalid; no automatic evidence repair."""
import copy
import pytest
from ctxcomp import lean_compression as lean
from ctxcomp.retention import source_units,span_check
from ctxcomp.engine import load_run,prepare,accept
from test_lean_compression import setup,candidate


def test_skipping_internal_source_line_is_rejected_but_separate_spans_are_valid():
    text='Mouse!A1 | "Study title"\nMouse!A2 | "DOI source"\nMouse!A3 | "8 mg/kg/day IP"\nMouse!A4 | "no sampling is a missing-value marker"'
    units=source_units([dict(id='S1',text=text)])
    def span(quote):return dict(source_id='S1',unit_id=units[0]['id'],quote=quote)
    lines=text.splitlines()
    with pytest.raises(ValueError,match='verbatim'):span_check(span(lines[0]+'\n'+lines[2]),units)
    for quote in (text,lines[0],lines[2],lines[3]):
        result=span_check(span(quote),units)
        assert result['matches']
    assert units[0]['text']==text  # No unit rewrite or skipped source metadata.


def test_quote_crossing_units_requires_two_exact_spans():
    units=source_units([dict(id='S1',text='First source paragraph.\n\nSecond source paragraph.')])
    with pytest.raises(ValueError,match='verbatim'):
        span_check(dict(source_id='S1',unit_id=units[0]['id'],quote=units[0]['text']+units[1]['text']),units)
    for u in units:
        assert span_check(dict(source_id='S1',unit_id=u['id'],quote=u['text']),units)['matches']


def test_exact_quote_and_marker_contract_reaches_generation_patch_and_independent_review(tmp_path):
    run=setup(tmp_path);bundle,state=load_run(run);generation=prepare(run,'context')
    value=candidate(generation);accept(run,'context',value)
    independent=prepare(run,'context_review');targeted=lean.patch_request(bundle,lean.content(value),{'fixes':[]},run)
    assert bundle['compression_profile']['version']=='1.14'
    for req in (generation,independent,targeted):
        text=req['payload']['instructions']
        assert lean.EXACT_CITATION_PLACEMENT in text
        assert 'Never join nonadjacent lines or cells' in text
        assert 'cite A1 and A3 separately' in text
        assert 'never invent an ID range' in text
        assert 'never turn it into a claim that no samples are missing' in text


def test_citation_contract_freezes_without_changing_historical_request(tmp_path,monkeypatch):
    run=setup(tmp_path);bundle,state=load_run(run);current=lean.request(run,bundle,state,'context')
    old=copy.deepcopy(bundle);old['compression_profile']['version']='1.10';old['compression_profile'].pop('citation_placement')
    for key in ('generation_instructions','review_instructions'):
        old['compression_profile'][key]=old['compression_profile'][key].removesuffix(lean.REFERENCE_ARRAY_FORMAT).removesuffix(lean.SOURCE_OWNER_COMPLETENESS).removesuffix(lean.EXACT_CITATION_PLACEMENT)
    historical=lean.request(run,old,state,'context')
    monkeypatch.setattr(lean,'EXACT_CITATION_PLACEMENT','UNFROZEN REPLACEMENT')
    assert lean.request(run,bundle,state,'context')==current
    assert lean.request(run,old,state,'context')==historical
    for key in ('candidate_schema','review_schema','patch_schema','stages','max_patches'):
        assert old['compression_profile'][key]==bundle['compression_profile'][key]
