"""Source ownership and exact patch protocol; synthetic tests do not prove LLM semantics."""
import copy
import pytest
from ctxcomp import lean_compression as lean
from ctxcomp.engine import load_run,prepare,accept
from test_lean_compression import setup,candidate
from test_lean_gap_lineage import fixture


def test_source_ownership_reaches_generation_review_and_patch(tmp_path):
    run=setup(tmp_path);bundle,state=load_run(run);generation=prepare(run,'context')
    value=candidate(generation);accept(run,'context',value)
    independent=prepare(run,'context_review');targeted=lean.patch_request(bundle,lean.content(value),{'fixes':[]},run)
    assert bundle['compression_profile']['version']=='1.14'
    for req in (generation,independent,targeted):
        assert lean.SOURCE_OWNER_COMPLETENESS in req['payload']['instructions']
        assert req['payload']['source_units']==bundle['source_units']
    assert lean.PATCH_SCOPE_EVIDENCE in targeted['payload']['instructions']
    assert independent['payload']['schema']['properties']['review']['properties']['fixes']['items']['properties']['target']['enum']==list(lean.records(lean.content(value)))+['NEW']
    assert bundle['compression_profile']['max_patches']==1
    assert bundle['compression_profile']['stages']==['context','context_review']


def test_new_instructions_frozen_and_old_patch_contract_unchanged(tmp_path,monkeypatch):
    run=setup(tmp_path);bundle,state=load_run(run);value=lean.content(candidate(prepare(run,'context')))
    old=copy.deepcopy(bundle);p=old['compression_profile'];p['version']='1.12'
    p.pop('source_owner_completeness');p.pop('patch_scope_instructions')
    for key in ('generation_instructions','review_instructions'):
        p[key]=p[key].removesuffix(lean.REFERENCE_ARRAY_FORMAT).removesuffix(lean.SOURCE_OWNER_COMPLETENESS)
    before=[lean.request(run,b,state,'context') for b in (old,bundle)]
    patches=[lean.patch_request(b,value,{'fixes':[]},run) for b in (old,bundle)]
    assert lean.PATCH_SCOPE_EVIDENCE not in patches[0]['payload']['instructions']
    for key in ('candidate_schema','review_schema','patch_schema','max_patches','wall_budget_seconds'):
        assert p[key]==bundle['compression_profile'][key]
    monkeypatch.setattr(lean,'SOURCE_OWNER_COMPLETENESS','UNFROZEN')
    monkeypatch.setattr(lean,'PATCH_SCOPE_EVIDENCE','UNFROZEN')
    assert [lean.request(run,b,state,'context') for b in (old,bundle)]==before
    assert [lean.patch_request(b,value,{'fixes':[]},run) for b in (old,bundle)]==patches


def test_changed_refs_require_unchanged_index_evidence_without_host_fabrication(tmp_path):
    run,bundle,base,review,request,response=fixture(tmp_path)
    original=copy.deepcopy(response)
    response['evidence']=[e for e in response['evidence'] if e['id']!='/uncertainties/0']
    with pytest.raises(ValueError):lean.apply_patch_response(bundle,base,review,request,response)
    assert all(e['id']!='/uncertainties/0' for e in response['evidence'])
    old=copy.deepcopy(next(e for e in base['evidence'] if e['id']=='/uncertainties/0'))
    response['evidence'].append(old)
    fixed=lean.apply_patch_response(bundle,base,review,request,response)
    assert fixed['context']['uncertainties']==['[MI001]','[MI002]']
    assert next(e for e in fixed['evidence'] if e['id']=='/uncertainties/0')==old


def test_reason_mention_does_not_authorize_unrelated_owner_rewrite(tmp_path):
    run,bundle,base,review,request,response=fixture(tmp_path)
    review['fixes'][0].update(target='F001',reason='Change scientific prose to refer to its existing MI001 owner.')
    response['add_gaps']=[];response['replace_gaps'][0]['record']['clarification']='Rephrased owner'
    response['uncertainty_refs']=base['context']['uncertainties']
    with pytest.raises(ValueError,match='unrelated.*MI001'):
        lean.apply_patch_response(bundle,base,review,request,response)
