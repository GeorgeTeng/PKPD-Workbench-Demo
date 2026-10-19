"""Dedicated English summary prompt for the human gate, without another audit."""
from pathlib import Path
from ctxcomp.schemas import validate_schema
from . import data_direct_runtime as rt, data_necessity_decisions as necessity
from .data_necessity_direct import obj, strings
from .common import read_json, write_json

PRIMARY = necessity.ACTIONS[:3]
INSTRUCTIONS = """Produce a short English decision table for human review, using
ONLY the supplied Necessity action_decisions and overall opinion. Do not review
raw data or add methods, conditions, evidence, approvals or model claims.

The reader needs three answers: animal model-based PK, PD index comparison and
PD target estimation. For each preserve the exact readiness and source scope;
state the specific problem and its consequence in finding, then ONE next_step.
Do not hide different source scopes behind an overall conditional pass. Preserve
source IDs/study names and numbers that change the decision. State what CAN run
when one source or analysis is limited. Do not use vague 'some studies', 'review
inputs' or 'assess sufficiency'. Never turn unverified support into confirmed
absence or readiness. Unknown fit quality is later modeling work, not data loss.

Use 170-220 words, with an absolute maximum of 250 words across ALL prose fields.
headline: one recommendation, at most 20 words. Each finding: at most 45 words;
each next_step: at most 20 words. later_and_optional: at most 35 words total for
optional NCA and later PTA, stating they do not gate unrelated current work.
Do not repeat findings in an overview, separate wait list or next-steps list.
Human approval is shown by the interface separately: never count it as a data
shortage. Complete gap-to-evidence mappings remain in Necessity details and do
not have to be restated in the table. Do not alter the original scientific Rules.
"""


def prepare(necessity_path,out):
    nec=necessity.verify_result(necessity_path)
    rows={key:obj({'readiness':{'type':'string','enum':[nec['action_decisions'][key]['readiness']]},
        'finding':{'type':'string','minLength':1},'next_step':{'type':'string','minLength':1}}) for key in PRIMARY}
    schema=obj({'request_sha256':{'type':'string'},
        'decision':{'type':'string','enum':[nec['assessment']['decision']]},
        'headline':{'type':'string','minLength':1},'rows':obj(rows),
        'later_and_optional':{'type':'string','minLength':1}})
    p={'version':'DATA_HUMAN_SUMMARY_PREPARED_3.0',
       'bindings':{**rt.runtime_bindings(),'summary_code':rt.file_ref(__file__),'necessity':rt.file_ref(necessity_path)},
       'request':rt.make_request({'stage':'HUMAN_REVIEW_SUMMARY_ONLY','instructions':INSTRUCTIONS,
           'assessment':nec['assessment'],'action_decisions':nec['action_decisions']},schema)}
    path=Path(out)/'prepared.json'
    if path.exists() and read_json(path)!=p:rt.fail('Summary directory belongs to different inputs')
    write_json(path,p)
    return p


def validate(raw,p):
    payload=p['request']['payload']
    if raw['decision']!=payload['assessment']['decision']:
        rt.fail('Summary changed Necessity recommendation')
    if set(raw['rows'])!=set(PRIMARY):rt.fail('Summary must retain each primary analysis')
    prose=[raw['headline'],raw['later_and_optional']]
    for key,row in raw['rows'].items():
        if row['readiness']!=payload['action_decisions'][key]['readiness']:
            rt.fail('Summary changed an action recommendation')
        if len(row['finding'].split())>45 or len(row['next_step'].split())>20:
            rt.fail('Summary table row is too long')
        prose += [row['finding'],row['next_step']]
    if len(raw['headline'].split())>20 or len(raw['later_and_optional'].split())>35 or sum(len(x.split()) for x in prose)>250:
        rt.fail('Human summary exceeds its short-form word boundary')


def materialize(raw,p,bindings,receipt):
    return {'version':'DATA_HUMAN_SUMMARY_3.0','summary':raw,
        'assessment':p['request']['payload']['assessment'],
        'action_decisions':p['request']['payload']['action_decisions'], 'bindings':bindings,
        'execution':{k:receipt[k] for k in ('requested_model','served_models','test_generator')},
        'scientific_approval':False,'downstream_executed':False}


def run_prepared(out,generator=None):
    out=Path(out)
    p=read_json(out/'prepared.json')
    bindings={**p['bindings'],'prepared':rt.file_ref(out/'prepared.json')}
    if generator is None and read_json(bindings['necessity']['path'])['execution']['test_generator']:
        rt.fail('Real summary cannot consume synthetic Necessity')
    raw=rt.invoke(out/'call',p['request'],bindings,lambda r:validate(r,p),generator=generator)
    result=materialize(raw,p,bindings,read_json(out/'call/accepted.json'))
    rt.verify_refs(bindings)
    write_json(out/'summary.json',result)
    return result


def verify_result(path):
    path=Path(path)
    result=read_json(path)
    p=read_json(path.parent/'prepared.json')
    bindings={**p['bindings'],'prepared':rt.file_ref(path.parent/'prepared.json')}
    rt.verify_refs(bindings)
    receipt=read_json(path.parent/'call/accepted.json')
    rt.verify_refs({'raw':receipt['raw']})
    raw=read_json(receipt['raw']['path'])
    validate_schema(raw,p['request']['payload']['schema'])
    validate(raw,p)
    if raw['request_sha256']!=p['request']['request_sha256'] or receipt['request_sha256']!=raw['request_sha256']:
        rt.fail('Summary request identity changed')
    if result!=materialize(raw,p,bindings,receipt):
        rt.fail('Summary differs from accepted response')
    return result
