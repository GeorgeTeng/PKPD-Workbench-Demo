"""Explicit recovery of grouped ID links with byte-bound provenance, never scientific repair."""
import copy
import pytest
from ctxcomp import lean_compression as lean,lean_reference_normalization as normal
from ctxcomp.engine import load_run,prepare,accept,accepted_response,verify_context
from ctxcomp.io import read_json,write_json
from ctxcomp.providers import run_model
from ctxcomp.schemas import validate_schema
from test_lean_compression import setup,review,patch
from test_lean_gap_lineage import gap_candidate


def historical_setup(tmp_path,monkeypatch):
    original=lean.profile
    def frozen(identifier):
        p=original(identifier);p['version']='1.13';p.pop('reference_array_format')
        p['candidate_schema']=copy.deepcopy(lean.RESPONSE);p['patch_schema']=copy.deepcopy(lean.PATCH)
        for key in ('generation_instructions','review_instructions'):
            p[key]=p[key].removesuffix(lean.REFERENCE_ARRAY_FORMAT)
        return p
    with monkeypatch.context() as m:
        m.setattr(lean,'profile',frozen);run=setup(tmp_path)
    return run


def failed_case(tmp_path,monkeypatch):
    run=historical_setup(tmp_path,monkeypatch)
    def generator(req,**kwargs):
        v=gap_candidate(req);gap=copy.deepcopy(v['missing_information']['items'][0]);gap['id']='MI002'
        v['missing_information']['items'].append(gap)
        ev=copy.deepcopy(next(e for e in v['evidence'] if e['id']=='MI001'));ev['id']='MI002';v['evidence'].append(ev)
        v['context']['uncertainties']=['[MI001] [MI002]']
        return v
    with pytest.raises(ValueError,match='Uncertainty references'):run_model(run,generator=generator)
    raw=next((run/'responses').glob('context.*.json'))
    return run,raw


def resume(run,raw):
    return normal.resume_grouped_references(run,raw,minimum_elapsed_seconds=221.61,
        submitted_by='ROOT_REVIEW',reason='Exact known ID links only; preserve scientific records and original raw.')


@pytest.mark.parametrize('needs_patch',[False,True])
def test_recovery_no_extraction_and_proof_survives_full_review_and_patch(tmp_path,monkeypatch,needs_patch):
    run,raw=failed_case(tmp_path,monkeypatch);bundle,state=load_run(run);original=read_json(raw)
    preserved={p:p.read_bytes() for p in (raw,run/'inputs.json',run/'requests/context.json')}
    with pytest.raises(ValueError):lean.validate_candidate(lean.content(original),bundle)
    assert resume(run,raw)['status']=='ACCEPTED'
    normalized=accepted_response(run,load_run(run)[1],'context')
    assert normalized['scientific_context']==original['scientific_context']
    assert normalized['missing_information']==original['missing_information']
    assert normalized['context']['uncertainties']==['[MI001]','[MI002]']
    assert [e for e in normalized['evidence'] if not e['id'].startswith('/uncertainties/')]==[e for e in original['evidence'] if not e['id'].startswith('/uncertainties/')]
    assert resume(run,raw)['status']=='ALREADY_NORMALIZED'
    assert read_json(run/'lean/execution_budget.json')['elapsed_seconds']==221.61
    calls=[]
    def generator(req,**kwargs):
        p=req['payload'];op=p.get('operation',p['stage']);calls.append(op)
        assert op!='context'
        if op=='TARGETED_PATCH':return patch(req)
        return review(req,'REVISE' if needs_patch and len(calls)==1 else 'PASS')
    assert run_model(run,generator=generator)['status']=='CONTEXT_READY'
    assert calls==(['context_review','TARGETED_PATCH','context_review'] if needs_patch else ['context_review'])
    assert verify_context(run)['status']=='VALID'
    assert read_json(run/'lean/execution_budget.json')['elapsed_seconds']>=221.61
    assert all(p.read_bytes()==b for p,b in preserved.items())
    with pytest.raises(ValueError):lean.validate_candidate(lean.content(read_json(raw)),bundle)


@pytest.mark.parametrize('fault',['duplicate','unknown','prose','missing','citations','status','extra_evidence','quote'])
def test_group_projection_rejects_ambiguous_refs_and_other_candidate_errors(tmp_path,monkeypatch,fault):
    run,path=failed_case(tmp_path,monkeypatch);bundle,_=load_run(run);raw=read_json(path)
    if fault=='duplicate':raw['context']['uncertainties']=['[MI001] [MI001] [MI002]']
    elif fault=='unknown':raw['context']['uncertainties']=['[MI001] [MI999]']
    elif fault=='prose':raw['context']['uncertainties']=['Known: [MI001] [MI002]']
    elif fault=='missing':raw['context']['uncertainties']=['[MI001]']
    elif fault=='citations':next(e for e in raw['evidence'] if e['id']=='/uncertainties/0')['citations']=raw['evidence'][-1]['citations']
    elif fault=='status':next(e for e in raw['evidence'] if e['id']=='/uncertainties/0')['status']='EXPLICIT'
    elif fault=='extra_evidence':raw['evidence'].append(copy.deepcopy(next(e for e in raw['evidence'] if e['id']=='/uncertainties/0')))
    else:raw['evidence'][-1]['citations'][0]['quote']='UNSUPPORTED SCIENTIFIC CLAIM'
    with pytest.raises(ValueError):normal.project(bundle,read_json(run/'requests/context.json'),raw)
    assert not load_run(run)[1]['accepted']


@pytest.mark.parametrize('fault',['raw','proof','proof_missing','budget','candidate'])
def test_review_construction_replays_proof_and_rejects_tampering(tmp_path,monkeypatch,fault):
    run,path=failed_case(tmp_path,monkeypatch);resume(run,path)
    if fault=='raw':path.write_bytes(path.read_bytes()+b' ')
    elif fault=='proof':
        p=run/normal.PROOF;v=read_json(p);v['operations']['mapping'][0]['reference']='[MI999]';write_json(p,v)
    elif fault=='proof_missing':(run/normal.PROOF).unlink()
    elif fault=='budget':
        p=run/'lean/execution_budget.json';v=read_json(p);v['elapsed_seconds']=0;write_json(p,v)
    else:
        record=load_run(run)[1]['accepted']['context'];p=run/record['file'];v=read_json(p);v['context']['objective']='Tampered';write_json(p,v)
    with pytest.raises(ValueError):prepare(run,'context_review')


def test_future_schema_rejects_grouping_and_duplicates_but_accepts_separate_known_format(tmp_path):
    run=setup(tmp_path);bundle,_=load_run(run);req=prepare(run,'context');p=bundle['compression_profile']
    assert p['version']=='1.14'
    assert lean.REFERENCE_ARRAY_FORMAT in req['payload']['instructions']
    for schema in (p['candidate_schema']['properties']['context']['properties']['uncertainties'],p['patch_schema']['properties']['uncertainty_refs']):
        validate_schema(['[MI001]','[PQ001]'],schema)
        assert 'uniqueItems' not in schema  # Host exact IDs enforce uniqueness; provider dialect stays minimal.
        for bad in (['[MI001] [MI002]'],['MI001'],['[MI001] prose']):
            with pytest.raises(ValueError):validate_schema(bad,schema)

    value=gap_candidate(req);value['context']['uncertainties']=['[MI001]','[MI001]']
    value['evidence'].append(dict(id='/uncertainties/1',status='REFERENCE',citations=[],reason='Duplicate MI001'))
    validate_schema(value,req['payload']['schema'])
    with pytest.raises(ValueError,match='Uncertainty references'):
        lean.validate_candidate(lean.content(value),bundle)
