"""Explicit carry-forward of an unchanged model candidate; no model calls or forged reviews."""
import copy
import hashlib
import math
from pathlib import Path

from .io import read_json,write_json,digest

PROVIDER='HOST_CARRIED_FROM_PRIOR_MODEL'
CONTRACT='SAME_SOURCE_CANDIDATE_1.0'


def ref(path):
    path=Path(path).resolve()
    return {'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}


def checked(reference):
    if ref(reference['path'])!=reference:raise ValueError('Carry-forward referenced artifact changed')
    return read_json(reference['path'])


def source_identity(run,bundle,state):
    from .handoff import file_handoff
    files=file_handoff(run,bundle,state)['files']
    keys=('id','original_name','sha256','purpose','kind','receivers','read_status','compression_input')
    return {'source_units':bundle['source_units'],
        'sources':[{k:s[k] for k in ('id','name','role','text','original_sha256')} for s in bundle['sources']],
        'compression_scope':bundle['compression_scope'],'policy':bundle['policy'],
        'files':[{k:f[k] for k in keys} for f in files],
        'processing_rules_sha256':digest(bundle['processing_rules'])}


def revision(parent_run,model_review_path,supplemental_review_path,*,minimum_prior_elapsed=0,guidance=''):
    """Create revision data to pass to init_run; complete challenges are frozen as non-evidence."""
    from .engine import load_run,accepted_response,make_request
    from . import lean_compression as lean
    parent=Path(parent_run).resolve();bundle,state=load_run(parent)
    if not lean.enabled(bundle) or (parent/'lean/patch_attempt.json').exists():
        raise ValueError('Carry-forward requires a lean parent with its single patch unused')
    if 'context_review' in state['accepted']:raise ValueError('Carry-forward requires an unresolved parent review')
    original=accepted_response(parent,state,'context');candidate=lean.content(original)
    lean.validate_candidate(candidate,bundle)
    review_ref=ref(model_review_path);review=checked(review_ref)
    if (review.get('candidate_sha256')!=digest(candidate) or
        review.get('request_sha256')!=make_request(parent,'context_review')['request_sha256'] or
        review.get('review',{}).get('decision')!='REVISE'):
        raise ValueError('Prior model review does not bind this exact unresolved candidate')
    extra_ref=ref(supplemental_review_path);extra=checked(extra_ref)
    candidate_ref=ref(parent/state['accepted']['context']['file'])
    supplied=extra.get('candidate_ref',{})
    if supplied.get('path')!=candidate_ref['path'] or supplied.get('sha256')!=candidate_ref['sha256']:
        raise ValueError('Supplemental review must bind the exact original candidate bytes')
    budget_ref=ref(parent/'lean/execution_budget.json');elapsed=checked(budget_ref)['elapsed_seconds']
    if (isinstance(minimum_prior_elapsed,bool) or not math.isfinite(minimum_prior_elapsed) or minimum_prior_elapsed<0
        or not math.isfinite(elapsed) or elapsed<0):raise ValueError('Invalid prior execution budget')
    lineage={'contract':CONTRACT,'parent_run':str(parent),'parent_inputs_ref':ref(parent/'inputs.json'),
        'parent_state_ref':ref(parent/'state.json'),'candidate_ref':candidate_ref,'model_review_ref':review_ref,
        'supplemental_review_ref':extra_ref,'budget_ref':budget_ref,'prior_elapsed_seconds':max(elapsed,minimum_prior_elapsed),
        'candidate_sha256':digest(candidate),'source_identity_sha256':digest(source_identity(parent,bundle,state)),
        'parent_patch_attempts':0}
    return {'carry_forward':lineage,'guidance':guidance,
        'prior_review':{'authority':'NON_EVIDENCE_REVIEW_CHALLENGES',
            'original_model_review':{'ref':review_ref,'contract_status':'UNACCEPTED_REVISE','content':review},
            'root_supplemental_review':{'ref':extra_ref,'authority':'ROOT_SUPPLEMENTAL_REVIEW_NOT_HUMAN_APPROVAL','content':extra}}}


def _lineage(run,bundle,state):
    from .engine import load_run
    frozen=bundle.get('revision',{}).get('carry_forward')
    if not frozen or frozen.get('contract')!=CONTRACT:raise ValueError('No frozen carry-forward contract')
    for key in ('parent_inputs_ref','parent_state_ref','candidate_ref','model_review_ref','supplemental_review_ref','budget_ref'):
        checked(frozen[key])
    parent=Path(frozen['parent_run']);parent_bundle,parent_state=load_run(parent)
    if (parent/'lean/patch_attempt.json').exists():raise ValueError('Parent patch already used')
    if (bundle['compression_profile']['max_patches']!=1 or parent_bundle['compression_profile']['max_patches']!=1
        or bundle['compression_profile']['wall_budget_seconds']!=parent_bundle['compression_profile']['wall_budget_seconds']):
        raise ValueError('Carry-forward cannot enlarge the parent patch or time allowance')
    if frozen['prior_elapsed_seconds']<checked(frozen['budget_ref'])['elapsed_seconds']:
        raise ValueError('Carry-forward cannot discard prior execution time')
    identity=source_identity(parent,parent_bundle,parent_state)
    if digest(identity)!=frozen['source_identity_sha256'] or source_identity(run,bundle,state)!=identity:
        raise ValueError('Carry-forward requires identical scientific sources, file bytes, roles and policy')
    prior=bundle['revision']['prior_review']
    if (prior['original_model_review']['content']!=checked(frozen['model_review_ref']) or
        prior['root_supplemental_review']['content']!=checked(frozen['supplemental_review_ref'])):
        raise ValueError('Frozen review challenges differ from their attributed originals')
    from .lean_compression import content,validate_candidate
    candidate=content(checked(frozen['candidate_ref']));validate_candidate(candidate,bundle)
    if digest(candidate)!=frozen['candidate_sha256']:raise ValueError('Carry-forward candidate changed')
    return frozen,candidate


def carry_forward(run):
    """Accept unchanged content with host provenance, carrying the parent execution budget once."""
    from .engine import load_run,prepare,accept
    from .lean_compression import record_prior_elapsed
    run=Path(run);bundle,state=load_run(run)
    if bundle['compression_profile'].get('carry_forward')!=CONTRACT:raise ValueError('Frozen profile does not permit carry-forward')
    lineage,candidate=_lineage(run,bundle,state)
    if state['accepted']:
        verify(run,bundle,state)
        return {'status':'ALREADY_CARRIED','candidate_sha256':lineage['candidate_sha256']}
    proof=run/'audit/carry_forward.json'
    if proof.exists() and read_json(proof)!=lineage:raise ValueError('Carry-forward proof changed')
    ledger=run/'lean/execution_budget.json'
    if not ledger.exists():record_prior_elapsed(run,lineage['prior_elapsed_seconds'],lineage)
    else:
        saved=read_json(ledger)
        if (saved.get('imported_prior_execution',{}).get('evidence')!=lineage or
            saved['elapsed_seconds']<lineage['prior_elapsed_seconds']):raise ValueError('Carry-forward budget changed or reset')
    write_json(proof,lineage)
    req=prepare(run,'context');outcome=accept(run,'context',{'request_sha256':req['request_sha256'],**candidate},PROVIDER)
    return {**outcome,'candidate_sha256':lineage['candidate_sha256'],'provider':PROVIDER}


def verify(run,bundle,state):
    """Recheck provenance at independent-review construction and publication, including after patch."""
    from .lean_compression import content
    if not bundle.get('revision',{}).get('carry_forward'):return
    run=Path(run);lineage,candidate=_lineage(run,bundle,state)
    if read_json(run/'audit/carry_forward.json')!=lineage:raise ValueError('Carry-forward proof changed')
    ledger=read_json(run/'lean/execution_budget.json')
    if (ledger.get('imported_prior_execution',{}).get('evidence')!=lineage or
        ledger['elapsed_seconds']<lineage['prior_elapsed_seconds']):raise ValueError('Carry-forward budget reset')
    patch=run/'lean/patch_proof.json'
    record=read_json(patch)['original_context'] if patch.exists() else state['accepted']['context']
    if record['provider']!=PROVIDER or content(read_json(run/record['file']))!=candidate:
        raise ValueError('Carried candidate differs from original model content or attribution')
