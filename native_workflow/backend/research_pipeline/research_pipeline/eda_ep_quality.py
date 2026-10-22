"""Deterministic review flags for scoped EDA omissions, not scientific approval.

These flags surface possible conflicts with existing EDA001/EDA006. They never
decide that an omitted dataset must be analyzed or generate a replacement plan.
"""
import re
from . import eda_ep_full as full
from .common import read_json


def check(plan, catalog):
    dispositions={d['dataset_id']:d for d in plan.get('dataset_disposition',[])}
    flags=[]
    relevant=[d for d in catalog if d['role'] in {'PK_OBSERVATIONS','PD_OBSERVATIONS'} and
              d['descriptive_readiness']['status']=='READY']
    for d in relevant:
        entry=dispositions.get(d['dataset_id'],{})
        if entry.get('use')!='OMITTED':continue
        reason=entry.get('reason','')
        scoped_limits=bool(d.get('operation_restrictions'))
        dependent_reason=bool(re.search(r'matched|common.record|correspondence|time[ -]+ax(?:is|es)|timing conflict|matrix interpretation|model.component',reason,re.I))
        if scoped_limits or dependent_reason:
            flags.append({'code':'OMISSION_USES_DEPENDENT_ANALYSIS_LIMIT',
                'dataset_ids':[d['dataset_id']],'rule_ids':['EDA001','EDA006'],
                'reason':reason,'status':'REVIEW_REQUIRED',
                'available_fallback':'Separate source table is admitted. A native point display depends on supported columns/status handling; otherwise retain a deferred figure design.',
                'question':'Provide a scoped figure/table plan and link it to this dataset, or establish an independent objective/scope exclusion. Do not use a dependent matching, modeling or conversion limit as the only reason to drop descriptive evidence.'})
    for group in sorted({d['group'] for d in relevant if d['role']=='PK_OBSERVATIONS'}):
        ids=[d['dataset_id'] for d in relevant if d['group']==group and d['role']=='PK_OBSERVATIONS']
        if ids and all(dispositions.get(d,{}).get('use')=='OMITTED' for d in ids):
            flags.append({'code':'ALL_ADMITTED_PK_IN_GROUP_OMITTED','dataset_ids':ids,
                'rule_ids':['EDA001','EDA003','EDA006'],'status':'REVIEW_REQUIRED',
                'reason':'All admitted descriptive PK evidence in group '+group+' is omitted.',
                'question':'Confirm a project-grounded exclusion or retain a bounded source display. This flag does not require one figure per table or authorize modeling.'})
    return {'status':'REVIEW_REQUIRED' if flags else 'NO_DETERMINISTIC_SCOPE_FLAGS',
        'flags':flags,'scientific_approval':False,
        'limitations':'Text triggers are triage flags, not a scientific completeness proof. A human content review remains necessary.'}


def require_execution_review(frozen):
    """Public EC/EV dispatch cannot silently execute a flagged EP plan."""
    full.verify_request(frozen)
    if 'plan' not in frozen['bindings']:
        return  # Internal synthetic transport tests have no model plan.
    plan=full.verified(frozen['bindings']['plan'])
    inputs=frozen['bindings']['ep:existing_inputs']
    full.verified(inputs)
    _,catalog,_,_=full.load_inputs(inputs['path'])
    result=check(plan,catalog)
    full.require(not result['flags'], 'EP scoped omissions require review before EC/EV execution')
