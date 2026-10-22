"""Recover a rejected saved patch through audited omission, never relaxed edit permissions."""
import copy
import pytest
from ctxcomp import lean_compression as lean,lean_saved_patch as saved
from ctxcomp.engine import load_run,accepted_response,verify_context
from ctxcomp.io import read_json,write_json
from ctxcomp.providers import run_model
from test_lean_compression import setup,review
from test_lean_gap_lineage import gap_candidate,gap_patch,gap_review


def failed_case(tmp_path):
    run=setup(tmp_path)
    def model(req,**kwargs):
        p=req['payload']
        if p.get('operation')=='TARGETED_PATCH':
            response=gap_patch(req)
            unrelated=copy.deepcopy(p['candidate']['missing_information']['items'][1]);unrelated['clarification']='A rephrased instruction'
            response['replace_gaps'].append({'record':unrelated,'fix_ids':['OTHER']})
            response['uncertainty_refs']=['[MI001]','[MI003]','[MI002]']
            response['evidence']=[e for e in response['evidence'] if not e['id'].startswith('/uncertainties/')]
            ev=copy.deepcopy(next(e for e in p['candidate']['evidence'] if e['id']=='MI003'));ev['reason']='Rephrased evidence'
            response['evidence']+=[ev,{'id':'/uncertainties/2','status':'REFERENCE','citations':[],'reason':'MI002'}]
            return response
        if p['stage']=='context':
            value=gap_candidate(req);other=copy.deepcopy(value['missing_information']['items'][0]);other['id']='MI003'
            value['missing_information']['items'].append(other);value['context']['uncertainties'].append('[MI003]')
            ev=copy.deepcopy(next(e for e in value['evidence'] if e['id']=='MI001'));ev['id']='MI003'
            value['evidence']+=[ev,{'id':'/uncertainties/1','status':'REFERENCE','citations':[],'reason':'MI003'}]
            return value
        result=gap_review(req);result['review']['fixes'].append({'id':'OTHER','target':'F001','reason':'Keep the gap owned by MI003','citations':[]})
        return result
    with pytest.raises(ValueError,match='unrelated.*MI003'):run_model(run,generator=model)
    raw=next((run/'responses').glob('context_patch.*.json'))
    return run,raw


def basis(run,raw):
    bundle,state=load_run(run);candidate=lean.content(accepted_response(run,state,'context'))
    return bundle,candidate,read_json(run/'lean/last_review.json')['review'],read_json(run/'requests/context_patch.json'),read_json(raw)


def resume(run,raw):
    return saved.resume_saved_patch(run,raw,omit_gap_ids=['MI003'],submitted_by='ROOT_SUPPLEMENTAL_REVIEW',
        reason='Drop this unrequested rephrasing; preserve the original complete gap.',minimum_elapsed_seconds=603.343)


@pytest.mark.parametrize('decision',['PASS','REVISE'])
def test_saved_patch_resume_only_calls_final_review_preserves_raw_and_budget(tmp_path,decision):
    run,raw=failed_case(tmp_path);bundle,candidate,r,req,response=basis(run,raw)
    original={p:p.read_bytes() for p in (raw,run/'inputs.json',run/'requests/context_patch.json',run/'lean/patch_attempt.json')}
    assert resume(run,raw)['status']=='SAVED_PATCH_APPLIED_PENDING_FULL_REVIEW'
    assert read_json(run/'lean/execution_budget.json')['elapsed_seconds']==603.343
    after=lean.content(accepted_response(run,load_run(run)[1],'context'))
    assert next(g for g in after['missing_information']['items'] if g['id']=='MI003')==next(g for g in candidate['missing_information']['items'] if g['id']=='MI003')
    assert next(e for e in after['evidence'] if e['id']=='MI003')==next(e for e in candidate['evidence'] if e['id']=='MI003')
    audit=read_json(run/'audit/saved_patch_projection.json')
    assert len(audit['operations']['reused_unchanged_reference_evidence'])==2
    assert resume(run,raw)['status']=='ALREADY_APPLIED'
    calls=[]
    def model(req,**kwargs):
        calls.append(req['payload'].get('operation',req['payload']['stage']))
        assert calls==['context_review']
        return review(req,decision)
    result=run_model(run,generator=model)
    assert result['status']==('CONTEXT_READY' if decision=='PASS' else 'REVISE')
    assert calls==['context_review'] and all(p.read_bytes()==value for p,value in original.items())
    assert read_json(run/'lean/execution_budget.json')['elapsed_seconds']>=603.343
    with pytest.raises(ValueError,match='unrelated.*MI003'):lean.apply_patch_response(bundle,candidate,r,req,response)
    if decision=='PASS':assert verify_context(run)['status']=='VALID'
    else:
        assert run_model(run,generator=model)['status']=='REVISE'
        assert calls==['context_review'] and not (run/'handoff/main.json').exists()


@pytest.mark.parametrize('fault',['changed_ref','missing_new_ref','direct_target','extra_unrelated','unknown_fix'])
def test_projection_never_fabricates_evidence_or_permits_unrelated_changes(tmp_path,fault):
    run,raw=failed_case(tmp_path);bundle,candidate,r,req,response=basis(run,raw)
    if fault=='changed_ref':response['uncertainty_refs'][0]='[MI003]'
    elif fault=='missing_new_ref':response['evidence']=[e for e in response['evidence'] if e['id']!='/uncertainties/2']
    elif fault=='direct_target':next(f for f in r['fixes'] if f['id']=='OTHER')['target']='MI003'
    elif fault=='extra_unrelated':
        response['overview']=[{'path':'/study/drug','value':'Unrelated change','fix_ids':['OTHER']}]
    else:response['replace_gaps'][-1]['fix_ids']=['UNKNOWN']
    with pytest.raises(ValueError):saved.project(bundle,candidate,r,req,response,['MI003'])


@pytest.mark.parametrize('fault',['raw','projection','proof_missing','budget_reset'])
def test_projection_proof_replay_rejects_tampering(tmp_path,fault):
    run,raw=failed_case(tmp_path);resume(run,raw)
    if fault=='raw':raw.write_text(raw.read_text(encoding='utf-8')+' ',encoding='utf-8')
    elif fault=='projection':
        p=run/'audit/saved_patch_projection.json';v=read_json(p);v['operations']['omitted_evidence']=[];write_json(p,v)
    elif fault=='proof_missing':
        p=run/'lean/patch_proof.json';v=read_json(p);v.pop('saved_patch_projection');write_json(p,v)
    else:
        p=run/'lean/execution_budget.json';v=read_json(p);v['elapsed_seconds']=0;write_json(p,v)
    bundle,state=load_run(run);candidate=lean.content(accepted_response(run,state,'context'))
    with pytest.raises(ValueError):lean.verify_patch_proof(run,bundle,candidate)
