"""Explicit audited recovery of grouped ID references; never repair scientific evidence."""
import copy
import math
import re
from pathlib import Path

from .io import read_json, write_json, digest
from .lean_carry_forward import ref, checked
from .schemas import validate_schema

POLICY = 'SPLIT_EXACT_GROUPED_ID_REFERENCES_1.0'
PROVIDER = 'HOST_NORMALIZED_GROUPED_ID_REFERENCES'
PROOF = 'audit/grouped_reference_normalization.json'
TOKEN = r'\[(?:MI|PQ)[0-9]+\]'


def project(bundle, request, raw):
    """Only split known bracketed IDs and duplicate their existing reference-link evidence."""
    from .lean_compression import content, validate_candidate
    validate_schema(raw, request['payload']['schema'])
    if raw['request_sha256'] != request['request_sha256']:
        raise ValueError('Grouped reference response request changed')
    known = ['['+r['id']+']' for group in (raw['missing_information']['items'],
        raw['scientific_context']['potential_questions']) for r in group]
    old_refs = raw['context']['uncertainties']
    groups = []
    for value in old_refs:
        if re.fullmatch(TOKEN+r'(?:\s+'+TOKEN+r')*', value) is None:
            raise ValueError('Grouped references require strict bracketed ID grammar without prose')
        groups.append(re.findall(TOKEN, value))
    tokens = [token for group in groups for token in group]
    if (len(set(known)) != len(known) or len(set(tokens)) != len(tokens)
            or set(tokens) != set(known)):
        raise ValueError('Grouped references must cover exact unique known MI/PQ IDs')
    if not any(len(group)>1 for group in groups):
        raise ValueError('No grouped reference array requires normalization')
    old_evidence = [e for e in raw['evidence'] if e['id'].startswith('/uncertainties/')]
    if (len(old_evidence) != len(old_refs)
            or {e['id'] for e in old_evidence} != {'/uncertainties/'+str(i) for i in range(len(old_refs))}
            or any(e['status'] != 'REFERENCE' or e['citations'] != [] for e in old_evidence)):
        raise ValueError('Grouped references require exact REFERENCE evidence with no citations')
    by_id = {e['id']:e for e in old_evidence};expanded=[];mapping=[]
    for old_index,group in enumerate(groups):
        old_id='/uncertainties/'+str(old_index)
        for token_index,token in enumerate(group):
            new_id='/uncertainties/'+str(len(expanded))
            evidence=copy.deepcopy(by_id[old_id]);evidence['id']=new_id
            expanded.append(evidence)
            mapping.append(dict(from_id=old_id,to_id=new_id,token_index=token_index,reference=token))
    normalized=copy.deepcopy(raw)
    normalized['context']['uncertainties']=tokens
    # Replace the first reference evidence position, preserving all other evidence verbatim and in order.
    new_evidence=[];inserted=False
    for evidence in raw['evidence']:
        if evidence['id'].startswith('/uncertainties/'):
            if not inserted:new_evidence.extend(expanded);inserted=True
        else:new_evidence.append(copy.deepcopy(evidence))
    normalized['evidence']=new_evidence
    validate_candidate(content(normalized),bundle)
    return normalized,dict(policy=POLICY,original_references=old_refs,
        original_reference_evidence=old_evidence,mapping=mapping)


def verify(run,bundle,state):
    """Bind the accepted base (including after a patch) to the raw response and exact projection."""
    from .lean_compression import request
    run=Path(run);proof_path=run/PROOF;patch=run/'lean/patch_proof.json'
    record=read_json(patch)['original_context'] if patch.exists() else state.get('accepted',{}).get('context')
    if not proof_path.exists():
        if record and record.get('provider')==PROVIDER:raise ValueError('Grouped reference proof missing')
        return
    proof=read_json(proof_path)
    if proof.get('policy')!=POLICY:raise ValueError('Grouped reference policy changed')
    raw=checked(proof['raw_response_ref']);req=checked(proof['request_ref']);checked(proof['inputs_ref'])
    if (Path(proof['raw_response_ref']['path']).resolve().parent!=(run/'responses').resolve()
            or Path(proof['request_ref']['path']).resolve()!=(run/'requests/context.json').resolve()
            or Path(proof['inputs_ref']['path']).resolve()!=(run/'inputs.json').resolve()):
        raise ValueError('Grouped reference provenance is outside the frozen run')
    if req!=request(run,bundle,state,'context'):raise ValueError('Grouped reference request changed')
    normalized,operations=project(bundle,req,raw)
    if proof['operations']!=operations or proof['normalized_response_sha256']!=digest(normalized):
        raise ValueError('Grouped reference projection proof changed')
    ledger=read_json(run/'lean/execution_budget.json')
    if ledger['elapsed_seconds']<proof['elapsed_seconds_floor']:
        raise ValueError('Grouped reference execution budget reset')
    if record:
        if (record.get('normalization_proof_sha256')!=digest(proof)
                or record.get('provider')!=PROVIDER or read_json(run/record['file'])!=normalized
                or record['sha256']!=digest(normalized)):
            raise ValueError('Normalized accepted candidate differs from original projection')


def resume_grouped_references(run,raw_path,*,minimum_elapsed_seconds,submitted_by,reason):
    """Explicit host recovery only. No extraction, review, patch or approval is performed."""
    from .engine import load_run,make_request,accept
    from .lean_compression import enabled
    run=Path(run).resolve();raw_path=Path(raw_path).resolve();bundle,state=load_run(run)
    if not enabled(bundle):raise ValueError('Grouped reference recovery requires lean compression')
    if raw_path.parent!=(run/'responses').resolve() or not raw_path.name.startswith('context.'):
        raise ValueError('Recovery requires the original context response in this run')
    if (isinstance(minimum_elapsed_seconds,bool) or not math.isfinite(minimum_elapsed_seconds)
            or minimum_elapsed_seconds<0 or not submitted_by or not reason):
        raise ValueError('Recovery requires attribution and a finite measured elapsed floor')
    proof_path=run/PROOF
    if state['accepted']:
        verify(run,bundle,state)
        if not proof_path.exists() or read_json(proof_path)['raw_response_ref']!=ref(raw_path):
            raise ValueError('Accepted stage is immutable')
        if read_json(run/'lean/execution_budget.json')['elapsed_seconds']<minimum_elapsed_seconds:
            raise ValueError('Repeated recovery cannot reset or silently alter budget provenance')
        return {'status':'ALREADY_NORMALIZED','model_calls':0}
    if (run/'lean/patch_attempt.json').exists():raise ValueError('Cannot normalize a consumed patch run')
    req=read_json(run/'requests/context.json')
    if req!=make_request(run,'context'):raise ValueError('Saved extraction request changed')
    normalized,operations=project(bundle,req,read_json(raw_path))
    budget_path=run/'lean/execution_budget.json';ledger=read_json(budget_path)
    elapsed=max(ledger['elapsed_seconds'],minimum_elapsed_seconds)
    proof=dict(policy=POLICY,raw_response_ref=ref(raw_path),request_ref=ref(run/'requests/context.json'),
        inputs_ref=ref(run/'inputs.json'),normalized_response_sha256=digest(normalized),operations=operations,
        elapsed_seconds_floor=elapsed,submitted_by=submitted_by,reason=reason)
    if proof_path.exists() and read_json(proof_path)!=proof:raise ValueError('Existing normalization proof differs')
    # Existing invocation measurements remain intact; only a documented conservative floor may increase time.
    if elapsed>ledger['elapsed_seconds']:
        ledger.setdefault('host_budget_floor_adjustments',[]).append(dict(policy=POLICY,
            from_seconds=ledger['elapsed_seconds'],to_seconds=elapsed,submitted_by=submitted_by,reason=reason))
        ledger['elapsed_seconds']=elapsed;write_json(budget_path,ledger)
    write_json(proof_path,proof)
    result=accept(run,'context',normalized,PROVIDER)
    _,state=load_run(run)
    state['accepted']['context']['normalization_proof_sha256']=digest(proof)
    write_json(run/'state.json',state)
    verify(run,*load_run(run))
    return {**result,'next_stage':'context_review','model_calls':0,
        'normalized_response_sha256':digest(normalized),'elapsed_seconds_floor':elapsed}
