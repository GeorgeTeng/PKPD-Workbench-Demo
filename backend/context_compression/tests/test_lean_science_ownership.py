"""Frozen prompt delivery; these tests do not claim model semantic accuracy."""
import copy
from ctxcomp import lean_compression as lean
from ctxcomp.engine import load_run,prepare,accept
from test_lean_compression import setup,candidate


def test_science_single_owner_instruction_reaches_generation_review_and_patch(tmp_path):
    run=setup(tmp_path);bundle,state=load_run(run);generation=prepare(run,'context')
    response=candidate(generation);accept(run,'context',response)
    independent=prepare(run,'context_review')
    targeted=lean.patch_request(bundle,lean.content(response),{'fixes':[]},run)
    assert bundle['compression_profile']['version']=='1.14'
    assert bundle['compression_profile']['science_ownership']=='SINGLE_PROPOSITION_OWNER_1.0'
    assert bundle['compression_profile']['max_patches']==1
    for req in (generation,independent,targeted):
        text=req['payload']['instructions']
        assert 'one full-text owner, even when the source repeats it' in text
        assert 'both METHOD and REQUIREMENT' in text
        assert 'unique prohibition on fitting, model selection or scaling' in text
        assert 'complete freeze, reported-dose prediction, held-out comparison and no-retuning procedure' in text
        assert 'rabbit component support' in text
        assert 'Do not combine incompatible roles' in text
        assert 'not permission to add facts or delete source conditions' in text
        assert 'do not approve duplication merely because both copies are individually faithful' in text
    assert lean.STAGES==('context','context_review')


def test_ownership_instruction_is_frozen_and_not_injected_into_older_profile(tmp_path,monkeypatch):
    run=setup(tmp_path);bundle,state=load_run(run)
    original=lean.request(run,bundle,state,'context')
    old=copy.deepcopy(bundle);old['compression_profile']['version']='1.8'
    old['compression_profile'].pop('science_ownership')
    old['compression_profile'].pop('regimen_preservation')
    old['compression_profile'].pop('citation_placement')
    for key in ('generation_instructions','review_instructions'):
        old['compression_profile'][key]=old['compression_profile'][key].removesuffix(lean.REFERENCE_ARRAY_FORMAT).removesuffix(lean.SOURCE_OWNER_COMPLETENESS).removesuffix(lean.EXACT_CITATION_PLACEMENT).removesuffix(lean.REGIMEN_PRESERVATION).removesuffix(lean.SCIENCE_CANONICAL_OWNERSHIP)
    historical=lean.request(run,old,state,'context')
    monkeypatch.setattr(lean,'SCIENCE_CANONICAL_OWNERSHIP','UNFROZEN CHANGE')
    assert lean.request(run,bundle,state,'context')==original
    assert lean.request(run,old,state,'context')==historical
    assert 'one full-text owner, even when' not in historical['payload']['instructions']
    assert old['compression_profile']['candidate_schema']==bundle['compression_profile']['candidate_schema']
    assert old['compression_profile']['review_schema']==bundle['compression_profile']['review_schema']
    assert old['compression_profile']['patch_schema']==bundle['compression_profile']['patch_schema']
