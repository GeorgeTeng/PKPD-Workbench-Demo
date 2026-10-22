"""Scoped English Necessity opinion; v1 remains available for historical replay."""
import copy
from pathlib import Path
from ctxcomp.schemas import validate_schema
from . import data_necessity_direct as legacy, data_direct_runtime as rt
from .common import read_json, write_json

ACTIONS = ['MODEL_BASED_ANIMAL_PK', 'PD_INDEX_COMPARISON', 'PD_TARGET_ESTIMATION', 'NCA', 'PTA']
READINESS = ['READY', 'CONDITIONAL', 'NOT_READY', 'NOT_ESTABLISHED', 'LATER']

INSTRUCTIONS = legacy.INSTRUCTIONS.replace(
    'Use concise Chinese explanations with original\nscientific terms.',
    'Write all generated explanations in direct English.') + """

Your decision is about DATA SUPPORT FOR THE NEXT ANALYSIS specified by DR, not
about permission to operate and not about final model validity. Do not retreat
from the analysis to 'data preparation' and call that a pass. Evaluate source-
specific model fitting attempts, the common-record PD index comparison and
PD target estimation separately. NCA is optional; PTA is later. Human review is
an independent workflow gate, not a missing data item or reason data are unready.

Not having chosen/fitted/validated a model is NOT an input defect. Structure
selection, identifiability, fit quality and predictive checks are work performed
in the modeling stage. A qualified model/estimated target is a future dependency
only for the later action that consumes it. Rabbit component assessment belongs
in animal PK; its uncertainty must not block unrelated rat or mouse work.
Do not upgrade uncertain data to READY. When support is unknown, name the exact
necessary input whose support is unestablished for that source and action.

For each of the five action_decisions, give one opinion:
READY = necessary data support is established for the named source scope;
CONDITIONAL = specified work can start within explicit data limitations;
NOT_READY = a specific necessary input is absent/conflicting for that action;
NOT_ESTABLISHED = a specific necessary input has not been verified;
LATER = the action awaits its named upstream products, not new experiments now.
Specify the usable source subset and the excluded/held subset in source_scope
or finding. The overall assessment is only an aggregate; it never replaces
these separate opinions. PASS must not conceal a held primary analysis.

Use concrete source IDs/study names. Say exactly WHAT is missing or inconsistent
and WHICH calculation/comparison is affected. Include numbers when they explain
an actual conflict (e.g. two dose descriptions), but only when supplied evidence
supports them. Never write only 'some studies', 'source discrepancies', 'review
inputs' or 'assess sufficiency'. Give one practical next_step that resolves the
named issue. Do not request already completed extraction or another general audit.

In analyses, next_action must name ONE action. If exposure-response matching is
blocked, name that comparison, not a compound action that starts with preparation
which can continue. impact, importance and can_continue must agree on the action.
Each gap_id remains accounted for once in details. Group genuinely shared impacts,
without erasing source differences. No blanket missing-data verdict for partly
supported fields. Preserve original Rules, conditions, provenance and holdouts.

Keep all generated prose under 1100 words (excluding gap IDs and copied evidence).
Use 8-12 concise analysis groups when possible, without dropping distinct impacts.
Do not repeat standard provenance cautions per group. Empty can_continue or
conditions_to_verify is appropriate when there is nothing specific to add.
Each action finding <=45 words; next_step <=25 words; source_scope <=20 words.
The assessment opinion is one direct sentence, <=30 words. It must not repeat the
five decisions. Detailed evidence belongs in recorded_shortages, not this opinion.
"""


def schema_for(gaps, profiles):
    schema = legacy.schema_for(gaps, profiles)
    item = schema['properties']['analyses']['items']
    item['properties']['importance'] = {'type':'string','enum':[
        'REQUIRED_NOW','ANALYSIS_SPECIFIC','FUTURE_DEPENDENCY','OPTIONAL_IMPROVEMENT','NEEDS_CONFIRMATION']}
    item['required'].append('importance')
    schema['properties']['assessment'] = legacy.obj({
        'decision':{'type':'string','enum':['PASS','CONDITIONAL_PASS','NOT_PASS']},
        'scope':{'type':'string','minLength':1},'opinion':{'type':'string','minLength':1}})
    action = legacy.obj({'readiness':{'type':'string','enum':READINESS},
        'source_scope':{'type':'string','minLength':1},'finding':{'type':'string','minLength':1},
        'next_step':{'type':'string','minLength':1},'gap_ids':legacy.strings(list(gaps))})
    schema['properties']['action_decisions'] = legacy.obj({k:copy.deepcopy(action) for k in ACTIONS})
    schema['required'] += ['assessment','action_decisions']
    return schema


def validate_response(raw, prepared):
    legacy.validate_response(raw,prepared)
    decisions=raw['action_decisions']
    if set(decisions)!=set(ACTIONS):
        rt.fail('Each project analysis needs its own data recommendation')
    if raw['assessment']['decision']=='PASS' and any(decisions[k]['readiness'] not in {'READY'} for k in ACTIONS[:3]):
        rt.fail('Overall PASS cannot conceal a conditional or held primary analysis')
    for action in decisions.values():
        if not set(action['gap_ids']).issubset(prepared['gaps']):
            rt.fail('Action decision refers to an invented shortage')
        for key,limit in [('source_scope',20),('finding',45),('next_step',25)]:
            if len(action[key].split())>limit:
                rt.fail('Action decision is too long: '+key)
    for analysis in raw['analyses']:
        if analysis['importance']=='OPTIONAL_IMPROVEMENT' and analysis['impact']!='NO_CURRENT_BLOCK':
            rt.fail('An optional improvement cannot block or limit required work')
        if analysis['importance']=='FUTURE_DEPENDENCY' and analysis['impact']!='FUTURE_DEPENDENCY':
            rt.fail('Future importance must match future impact')
    prose=[raw['assessment']['scope'],raw['assessment']['opinion']]
    for a in raw['analyses']:
        prose += [a[k] for k in ('affected_scope','next_action','impact_summary','recommendation')]
        prose += a['can_continue']+a['conditions_to_verify']
    prose += [a[k] for a in decisions.values() for k in ('source_scope','finding','next_step')]
    if sum(len(x.split()) for x in prose)>1100:
        rt.fail('Necessity exceeds its 1100-word prose boundary')
    if len(raw['assessment']['opinion'].split())>30:
        rt.fail('Overall opinion must fit one short sentence')


def prepare(coverage_path, main_path, mp_path, out):
    # Use the established projection, without writing or rebinding historical outputs.
    from .data_coverage_direct import verify_result
    cov = verify_result(coverage_path)
    main, mp = read_json(main_path), read_json(mp_path)
    if cov['bindings']['main'] != rt.file_ref(main_path):
        rt.fail('Necessity main differs from Coverage')
    gaps = legacy.collect_gaps(cov)
    payload = {'stage': 'NECESSITY_SCOPED_ASSESSMENT', 'instructions': INSTRUCTIONS,
        'objective': main['objective'],
        'rules': [{k: r[k] for k in ('id','kind','text','conditions','exceptions','scope','requirement','usage') if k in r} for r in main['rules']],
        'requirements': [{k: v for k,v in r.items() if k in {'id','description','method_uses','input_fields','conditions','required_by','origin','method_profile_ids'}} for r in cov['requirements']],
        'coverage_summary': {rid: {'status': c['status'], 'summary': c['summary'],
            'supported_fields': {k: v for k,v in c['fields'].items() if v['status'] in {'SUPPORTED','NOT_APPLICABLE'}}} for rid,c in cov['checks'].items()},
        'recorded_shortages': gaps,
        'local_method_knowledge': {k: mp[k] for k in ('version','status','use','interpretation','sources','profiles') if k in mp}}
    prepared = {'version': 'DIRECT_NECESSITY_PREPARED_3.0', 'gaps': gaps,
        'bindings': {**rt.runtime_bindings(), 'necessity_code': rt.file_ref(__file__),
            'legacy_contract': rt.file_ref(legacy.__file__), 'coverage': rt.file_ref(coverage_path),
            'main': rt.file_ref(main_path), 'local_method_profiles': rt.file_ref(mp_path)},
        'request': rt.make_request(payload, schema_for(gaps, [p['id'] for p in mp['profiles']]))}
    path = Path(out)/'prepared.json'
    if path.exists() and read_json(path) != prepared:
        rt.fail('Prepared assessment belongs to different inputs')
    write_json(path, prepared)
    return prepared


def materialize(raw, prepared, bindings, receipt):
    analyses = copy.deepcopy(raw['analyses'])
    for index, a in enumerate(analyses, 1):
        a.update(id=f'NA{index:03}', requirement_ids=sorted({prepared['gaps'][g]['requirement_id'] for g in a['gap_ids']}))
    return {'version': 'DIRECT_NECESSITY_3.0', 'complete': True,
        'scope': 'SCOPED_DATA_RECOMMENDATION', 'assessment': raw['assessment'], 'action_decisions':raw['action_decisions'], 'analyses': analyses,
        'recorded_shortages': prepared['gaps'], 'bindings': bindings,
        'request_sha256': raw['request_sha256'],
        'execution': {k: receipt[k] for k in ('requested_model','served_models','test_generator')},
        'scientific_approval': False, 'downstream_executed': False}


def run_prepared(out, generator=None):
    out = Path(out)
    p = read_json(out/'prepared.json')
    bindings = {**p['bindings'], 'prepared': rt.file_ref(out/'prepared.json')}
    if generator is None and read_json(bindings['coverage']['path'])['execution']['test_generator']:
        rt.fail('Real Necessity cannot consume synthetic Coverage')
    raw = rt.invoke(out/'call', p['request'], bindings, lambda r: validate_response(r,p), generator=generator)
    result = materialize(raw,p,bindings,read_json(out/'call/accepted.json'))
    rt.verify_refs(bindings)
    write_json(out/'necessity.json',result)
    return result


def verify_result(path):
    path = Path(path)
    result = read_json(path)
    p = read_json(path.parent/'prepared.json')
    bindings = {**p['bindings'], 'prepared': rt.file_ref(path.parent/'prepared.json')}
    rt.verify_refs(bindings)
    receipt = read_json(path.parent/'call/accepted.json')
    rt.verify_refs({'raw':receipt['raw']})
    raw = read_json(receipt['raw']['path'])
    validate_schema(raw,p['request']['payload']['schema'])
    validate_response(raw,p)
    if raw['request_sha256'] != p['request']['request_sha256'] or receipt['request_sha256'] != raw['request_sha256']:
        rt.fail('Assessment request identity changed')
    if result != materialize(raw,p,bindings,receipt):
        rt.fail('Assessment differs from accepted response')
    return result
