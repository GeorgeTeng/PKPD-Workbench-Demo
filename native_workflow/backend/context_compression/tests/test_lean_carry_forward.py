"""Carried candidates are attributed host copies; all model calls here are synthetic fixtures."""
import copy
import pytest
from ctxcomp import lean_compression as lean,lean_carry_forward as carry
from ctxcomp.engine import init_run,load_run,prepare,accept,verify_context
from ctxcomp.io import read_json,write_json,digest
from ctxcomp.providers import run_model
from test_lean_compression import setup,candidate,review,patch


def parent_case(tmp_path):
    folder=tmp_path/'parent';folder.mkdir();parent=setup(folder)
    req=prepare(parent,'context');value=candidate(req);accept(parent,'context',value,provider='codex')
    r=review(prepare(parent,'context_review'),'REVISE');r['review']['fixes'][0]['target']='/objective,F001'
    raw_path=parent/'original_model_review.json';write_json(raw_path,r)
    state=load_run(parent)[1];source=parent/state['accepted']['context']['file']
    extra=parent/'root_findings.json';write_json(extra,{'reviewer':'ROOT_SUPPLEMENTAL_REVIEW',
        'candidate_ref':carry.ref(source),'findings':[{'target':'/objective','reason':'Synthetic precise overview correction'}]})
    lean.record_prior_elapsed(parent,323.0629999998491,'Synthetic measured prior execution')
    revision=carry.revision(parent,raw_path,extra,minimum_prior_elapsed=323.078,guidance='Address independently, preserving all source facts.')
    return parent,revision


def child_case(tmp_path):
    parent,revision=parent_case(tmp_path);child=tmp_path/'child'
    init_run(child,parent.parent/'proposal.txt',clarifications=[parent.parent/'clarification.txt'],
             compression_profile=lean.ID,revision=revision)
    return parent,child,revision


@pytest.mark.parametrize('bad_target',['F001,/objective','F001–F002','scientific_context.items'])
def test_review_targets_are_dynamic_single_id_enum_not_normalized(tmp_path,bad_target):
    run=setup(tmp_path);accept(run,'context',candidate(prepare(run,'context')))
    req=prepare(run,'context_review');p=req['payload']
    targets=p['schema']['properties']['review']['properties']['fixes']['items']['properties']['target']['enum']
    assert set(targets)==set(p['expected_record_ids'])|{'NEW'}
    raw=review(req,'REVISE');raw['review']['fixes'][0]['target']=bad_target;original=copy.deepcopy(raw)
    with pytest.raises(ValueError):accept(run,'context_review',raw)
    assert raw==original and not (run/'lean/last_review.json').exists()
    assert not (run/'audit/review_target_normalization').exists()


def test_carry_runs_only_review_patch_full_review_and_replays_proof(tmp_path):
    parent,child,revision=child_case(tmp_path)
    original_bytes={p:p.read_bytes() for p in (parent/'inputs.json',parent/'state.json',parent/'original_model_review.json',parent/'root_findings.json')}
    assert carry.carry_forward(child)['provider']==carry.PROVIDER
    assert load_run(child)[1]['accepted']['context']['provider']==carry.PROVIDER
    initial_budget=read_json(child/'lean/execution_budget.json')
    assert initial_budget['elapsed_seconds']==323.078
    assert carry.carry_forward(child)['status']=='ALREADY_CARRIED'
    assert read_json(child/'lean/execution_budget.json')==initial_budget
    calls=[]
    def model(req,**kwargs):
        p=req['payload'];calls.append(p.get('operation',p['stage']))
        if p.get('operation')=='TARGETED_PATCH':return patch(req)
        assert p['stage']=='context_review'  # No repeat extraction.
        assert p['review_challenges']['prior_review']==revision['prior_review']
        assert 'NON-EVIDENCE' in p['review_challenge_policy']
        assert p['review_challenges']['prior_review']['original_model_review']['content']['review']['fixes'][0]['target']=='/objective,F001'
        return review(req) if 'TARGETED_PATCH' in calls else review(req,'REVISE')
    assert run_model(child,generator=model)['status']=='CONTEXT_READY'
    assert calls==['context_review','TARGETED_PATCH','context_review']
    assert verify_context(child)['status']=='VALID'
    assert read_json(child/'lean/execution_budget.json')['elapsed_seconds']>=323.078
    assert all(p.read_bytes()==value for p,value in original_bytes.items())
    proof=read_json(child/'audit/carry_forward.json');proof['candidate_sha256']='tampered'
    write_json(child/'audit/carry_forward.json',proof)
    with pytest.raises(ValueError,match='proof changed'):verify_context(child)


@pytest.mark.parametrize('fault',['source_text','source_role','source_unit','policy'])
def test_carry_rejects_different_scientific_sources_roles_and_policy(tmp_path,fault):
    parent,child,revision=child_case(tmp_path);bundle,state=load_run(child)
    if fault=='source_text':bundle['sources'][0]['text']+=' extra'
    elif fault=='source_role':bundle['sources'][0]['role']='CLARIFICATION'
    elif fault=='source_unit':bundle['source_units'][0]['text']+=' extra'
    else:bundle['policy']['human_pk_validation_only']=False
    with pytest.raises(ValueError,match='identical scientific sources'):carry._lineage(child,bundle,state)
    assert not (child/'audit/carry_forward.json').exists()


@pytest.mark.parametrize('fault',['reset','missing','evidence'])
def test_carry_budget_cannot_be_reset_dropped_or_relabelled(tmp_path,fault):
    parent,child,revision=child_case(tmp_path);carry.carry_forward(child)
    path=child/'lean/execution_budget.json';budget=read_json(path)
    if fault=='missing':path.unlink()
    else:
        if fault=='reset':budget['elapsed_seconds']=0
        else:budget['imported_prior_execution']['evidence']={}
        write_json(path,budget)
    with pytest.raises((ValueError,FileNotFoundError)):carry.carry_forward(child)
    assert fault!='missing' or not path.exists()


def test_parent_used_patch_and_changed_review_bytes_rejected(tmp_path):
    parent,child,revision=child_case(tmp_path)
    write_json(parent/'lean/patch_attempt.json',{'already_used':True})
    with pytest.raises(ValueError,match='Parent patch'):carry.carry_forward(child)
    (parent/'lean/patch_attempt.json').unlink()
    raw=parent/'original_model_review.json';value=read_json(raw);value['review']['reviewer']='changed';write_json(raw,value)
    with pytest.raises(ValueError,match='artifact changed'):carry.carry_forward(child)


@pytest.mark.parametrize('field,value',[('max_patches',2),('wall_budget_seconds',1800)])
def test_carry_cannot_enlarge_frozen_budget_or_patch_count(tmp_path,field,value):
    parent,child,revision=child_case(tmp_path);bundle,state=load_run(child)
    bundle['compression_profile'][field]=value
    with pytest.raises(ValueError,match='cannot enlarge'):carry._lineage(child,bundle,state)


def test_second_revise_consumes_only_one_patch_in_derived_run(tmp_path):
    parent,child,revision=child_case(tmp_path);carry.carry_forward(child);calls=[]
    def model(req,**kwargs):
        p=req['payload'];calls.append(p.get('operation',p['stage']))
        return patch(req) if p.get('operation')=='TARGETED_PATCH' else review(req,'REVISE')
    assert run_model(child,generator=model)['status']=='REVISE'
    assert run_model(child,generator=model)['status']=='REVISE'
    assert calls==['context_review','TARGETED_PATCH','context_review']
    assert not (child/'handoff/main.json').exists()
