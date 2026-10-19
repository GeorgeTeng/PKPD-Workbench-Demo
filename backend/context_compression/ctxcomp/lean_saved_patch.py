"""Explicit conservative projection of an already-generated patch; never another model call."""
import copy
import math
from pathlib import Path

from .io import read_json,write_json,digest
from .lean_carry_forward import ref,checked

POLICY='OMIT_UNTARGETED_GAP_REPLACEMENTS_REUSE_UNCHANGED_REFS_1.0'
PROVIDER='HOST_APPLIED_SAVED_MODEL_PATCH'


def project(bundle,candidate,review,request,raw,omit_gap_ids):
    from . import lean_compression as lean
    from .schemas import validate_schema
    validate_schema(raw,bundle['compression_profile']['patch_schema'])
    if raw['request_sha256']!=request['request_sha256'] or raw['base_candidate_sha256']!=digest(candidate):
        raise ValueError('Saved patch is stale')
    if not omit_gap_ids or len(set(omit_gap_ids))!=len(omit_gap_ids):raise ValueError('Name distinct gap replacements to omit')
    ids=[e['id'] for e in raw['evidence']]
    if len(ids)!=len(set(ids)):raise ValueError('Duplicate raw patch evidence cannot be projected')
    fixes={f['id']:f for f in review['fixes']};gaps={g['id'] for g in candidate['missing_information']['items']}
    projected=copy.deepcopy(raw);omitted=[];omitted_evidence=[]
    for rid in omit_gap_ids:
        matching=[c for c in raw['replace_gaps'] if c['record']['id']==rid]
        if rid not in gaps or len(matching)!=1:raise ValueError('Omitted target must be one existing gap replacement')
        change=matching[0]
        if any(fid not in fixes for fid in change['fix_ids']):raise ValueError('Unknown fix cannot be projected')
        if any(fixes[fid]['target']==rid for fid in change['fix_ids']):
            raise ValueError('Cannot omit a directly reviewed gap repair')
        if any(c.get('id',c.get('record',{}).get('id'))==rid for key in ('add_gaps','remove_gaps') for c in raw[key]):
            raise ValueError('Cannot project conflicting operations on one gap')
        evidence=[e for e in raw['evidence'] if e['id']==rid]
        if len(evidence)!=1:raise ValueError('Omitted gap must have its exact replacement evidence')
        omitted.append(copy.deepcopy(change));omitted_evidence.extend(copy.deepcopy(evidence))
    projected['replace_gaps']=[c for c in projected['replace_gaps'] if c['record']['id'] not in omit_gap_ids]
    projected['evidence']=[e for e in projected['evidence'] if e['id'] not in omit_gap_ids]
    old_e={e['id']:e for e in candidate['evidence']};provided={e['id'] for e in projected['evidence']}
    old_refs=candidate['context']['uncertainties'];new_refs=projected['uncertainty_refs'];reused=[]
    if old_refs!=new_refs:
        for index,value in enumerate(new_refs):
            rid='/uncertainties/'+str(index)
            if rid in provided:continue
            if index>=len(old_refs) or old_refs[index]!=value:
                raise ValueError('Cannot supply missing evidence for a changed uncertainty reference')
            evidence=old_e.get(rid)
            if not evidence or evidence['status']!='REFERENCE' or evidence['citations']:
                raise ValueError('Only exact unchanged REFERENCE evidence may be reused')
            projected['evidence'].append(copy.deepcopy(evidence))
            reused.append({'id':rid,'unchanged_value':value,'evidence':copy.deepcopy(evidence)})
    # The original remains invalid. All retained changes must pass the original strict validator.
    try:lean.apply_patch_response(bundle,candidate,review,request,raw)
    except ValueError as exc:
        if str(exc) not in {'Patch change is unrelated to its cited review target: '+rid for rid in omit_gap_ids}:
            raise ValueError('Original patch failure is not the explicitly omitted scope violation') from exc
    else:raise ValueError('Projection is only for an explicitly rejected saved patch')
    fixed=lean.apply_patch_response(bundle,candidate,review,request,projected)
    for rid in omit_gap_ids:
        if (next(g for g in fixed['missing_information']['items'] if g['id']==rid)!=next(g for g in candidate['missing_information']['items'] if g['id']==rid)
            or next(e for e in fixed['evidence'] if e['id']==rid)!=old_e[rid]):
            raise ValueError('Omitted gap record and evidence must remain unchanged')
    return projected,{'omitted_operations':omitted,'omitted_evidence':omitted_evidence,
                      'reused_unchanged_reference_evidence':reused},fixed


def verify_projection(run,bundle,patch_proof,before,request):
    """Rebuild the derived patch from original bytes and the explicit conservative policy."""
    run=Path(run).resolve();audit=checked(patch_proof['saved_patch_projection'])
    if audit['policy']!=POLICY:raise ValueError('Unknown saved patch projection policy')
    ledger=read_json(run/'lean/execution_budget.json')
    if ledger['elapsed_seconds']<max(audit['prior_elapsed_seconds'],audit['minimum_elapsed_seconds']):
        raise ValueError('Saved patch execution budget was reset')
    for key in ('raw_patch_ref','request_ref','review_ref'):
        if not Path(audit[key]['path']).resolve().is_relative_to(run):raise ValueError('Saved patch artifact outside its run')
    raw=checked(audit['raw_patch_ref']);original_request=checked(audit['request_ref']);review=checked(audit['review_ref'])
    if original_request!=request or review!=patch_proof['review'] or audit['base_candidate_sha256']!=digest(before):
        raise ValueError('Saved patch projection basis changed')
    projected,operations,_=project(bundle,before,review['review'],request,raw,audit['omit_gap_ids'])
    if (operations!=audit['operations'] or projected!=patch_proof['patch'] or
        digest(projected)!=audit['projected_patch_sha256'] or not audit['submitted_by'] or not audit['reason']):
        raise ValueError('Saved patch projection no longer matches its audit')


def resume_saved_patch(run,raw_patch_path,*,omit_gap_ids,submitted_by,reason,minimum_elapsed_seconds=0):
    """Apply one explicitly projected saved patch. Caller then runs only the remaining review."""
    from .engine import load_run,accepted_response,prepare,accept
    from . import lean_compression as lean
    run=Path(run).resolve();bundle,state=load_run(run)
    if not lean.enabled(bundle) or not submitted_by.strip() or not reason.strip():
        raise ValueError('An explicit attributed lean saved-patch projection is required')
    ledger_path=run/'lean/execution_budget.json';ledger=read_json(ledger_path)
    if isinstance(minimum_elapsed_seconds,bool) or not math.isfinite(minimum_elapsed_seconds) or minimum_elapsed_seconds<0:
        raise ValueError('Invalid execution-time lower bound')
    if (run/'lean/patch_proof.json').exists():
        proof=read_json(run/'lean/patch_proof.json')
        if not proof.get('saved_patch_projection'):raise ValueError('A different patch was already applied')
        audit=checked(proof['saved_patch_projection'])
        if audit['raw_patch_ref']!=ref(raw_patch_path) or audit['omit_gap_ids']!=list(omit_gap_ids):
            raise ValueError('A different saved patch projection was already applied')
        if ledger['elapsed_seconds']<minimum_elapsed_seconds:raise ValueError('Applied projection budget cannot be reset')
        lean.verify_patch_proof(run,bundle,lean.content(accepted_response(run,state,'context')))
        return {'status':'ALREADY_APPLIED','next_stage':'context_review','model_calls':0}
    if 'context_review' in state['accepted']:raise ValueError('Do not overwrite an accepted independent review')
    marker=read_json(run/'lean/patch_attempt.json');request=read_json(run/'requests/context_patch.json')
    reviewed=read_json(run/'lean/last_review.json');candidate=lean.content(accepted_response(run,state,'context'))
    lean.validate_review(reviewed,candidate,bundle,lean.request(run,bundle,state,'context_review'))
    if (reviewed['review']['decision']!='REVISE' or marker['request_sha256']!=request['request_sha256'] or
        marker['review_sha256']!=digest(reviewed) or marker['candidate_sha256']!=digest(candidate)):
        raise ValueError('No matching pending one-patch attempt')
    raw_path=Path(raw_patch_path).resolve()
    if not raw_path.is_relative_to(run/'responses'):raise ValueError('Use the original saved model response from this run')
    raw=read_json(raw_path);projected,operations,fixed=project(bundle,candidate,reviewed['review'],request,raw,list(omit_gap_ids))
    review_path=run/'reviews'/('context_review.'+digest(reviewed)[:16]+'.json')
    if read_json(review_path)!=reviewed:raise ValueError('Original independent review is not preserved')
    audit={'policy':POLICY,'submitted_by':submitted_by,'reason':reason,'human_approval':False,
        'raw_patch_ref':ref(raw_path),'request_ref':ref(run/'requests/context_patch.json'),'review_ref':ref(review_path),
        'base_candidate_sha256':digest(candidate),'omit_gap_ids':list(omit_gap_ids),'operations':operations,
        'projected_patch_sha256':digest(projected),'prior_elapsed_seconds':ledger['elapsed_seconds'],
        'minimum_elapsed_seconds':minimum_elapsed_seconds,'new_model_patch_calls':0}
    audit_path=run/'audit/saved_patch_projection.json'
    if audit_path.exists():raise ValueError('Saved patch projection already exists; inspect before resuming')
    if minimum_elapsed_seconds>ledger['elapsed_seconds']:
        ledger.setdefault('conservative_elapsed_floors',[]).append({'previous':ledger['elapsed_seconds'],
            'floor':minimum_elapsed_seconds,'submitted_by':submitted_by,'reason':reason})
        ledger['elapsed_seconds']=minimum_elapsed_seconds;write_json(ledger_path,ledger)
    write_json(audit_path,audit)
    proof={'original_context':state['accepted']['context'],'review':reviewed,'patch':projected,
        'before_sha256':digest(candidate),'after_sha256':digest(fixed),'saved_patch_projection':ref(audit_path)}
    if lean.split_groups(bundle):proof['split_lineage']=lean.split_lineage(bundle,candidate,reviewed['review'],projected)
    write_json(run/'lean/patch_proof.json',proof)
    state['accepted'].pop('context');write_json(run/'state.json',state)
    req=prepare(run,'context');accept(run,'context',{'request_sha256':req['request_sha256'],**fixed},PROVIDER)
    return {'status':'SAVED_PATCH_APPLIED_PENDING_FULL_REVIEW','next_stage':'context_review',
            'candidate_sha256':digest(fixed),'model_calls':0}
