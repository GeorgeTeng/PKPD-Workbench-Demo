"""Scoped English Necessity opinion; v1 remains available for historical replay."""
import copy
from pathlib import Path
from ctxcomp.schemas import validate_schema
from . import data_necessity_direct as legacy, data_direct_runtime as rt
from .common import read_json, write_json

INSTRUCTIONS = legacy.INSTRUCTIONS.replace(
    'Use concise Chinese explanations with original\nscientific terms.',
    'Write all generated explanations in clear English. Preserve source names and quotations.') + '''

Give your own scoped opinion on whether the available data can proceed to the
next project work. This is a recommendation for a human, never human approval.
assessment.decision is PASS, CONDITIONAL_PASS, or NOT_PASS for assessment.scope:
PASS means the stated work can proceed without an outstanding necessary condition;
CONDITIONAL_PASS means useful stated work can proceed within explicit limits or
holds; NOT_PASS means the requested next analysis cannot proceed yet. An unrelated
task that can continue does not make the blocked task pass. Do not equate preparing
input files with readiness to fit a model or estimate a scientific target.

Provide reasons_to_proceed, reasons_not_to_proceed, conditions, and next_steps.
Explain which animal PK work can actually begin, which remains unestablished,
and the separate implications for PD index, target estimation and PTA where
relevant. Keep model-based PK the priority and NCA an independent option.
For each grouped analysis assign importance:
REQUIRED_NOW (necessary for its named next_action), ANALYSIS_SPECIFIC (limits that
analysis only), FUTURE_DEPENDENCY (needed later), OPTIONAL_IMPROVEMENT (helpful,
not a required condition), or NEEDS_CONFIRMATION (necessity/support not settled).
Do not weaken a Rule or relabel a mandatory input as optional. A partly supported
field is not universally missing. Assess the stated DR condition, not every
possible scientific ideal. Missing original measurement details do not alone
invalidate an otherwise permitted reported value. Describe actual shortcomings
in analyses, then synthesize the opinion without repeating all evidence.
'''


def schema_for(gaps, profiles):
    schema = legacy.schema_for(gaps, profiles)
    item = schema['properties']['analyses']['items']
    item['properties']['importance'] = {'type': 'string', 'enum': [
        'REQUIRED_NOW', 'ANALYSIS_SPECIFIC', 'FUTURE_DEPENDENCY',
        'OPTIONAL_IMPROVEMENT', 'NEEDS_CONFIRMATION']}
    item['required'].append('importance')
    schema['properties']['assessment'] = legacy.obj({
        'decision': {'type': 'string', 'enum': ['PASS', 'CONDITIONAL_PASS', 'NOT_PASS']},
        'scope': {'type': 'string', 'minLength': 1},
        'opinion': {'type': 'string', 'minLength': 1},
        'reasons_to_proceed': legacy.strings(),
        'reasons_not_to_proceed': legacy.strings(),
        'conditions': legacy.strings(), 'next_steps': {**legacy.strings(), 'minItems': 1}})
    schema['required'].append('assessment')
    return schema


def validate_response(raw, prepared):
    legacy.validate_response(raw, prepared)
    opinion = raw['assessment']
    if opinion['decision'] in {'PASS', 'CONDITIONAL_PASS'} and not opinion['reasons_to_proceed']:
        rt.fail('A positive recommendation needs reasons to proceed')
    if opinion['decision'] == 'NOT_PASS' and not opinion['reasons_not_to_proceed']:
        rt.fail('NOT_PASS needs reasons not to proceed')
    if opinion['decision'] == 'CONDITIONAL_PASS' and not opinion['conditions']:
        rt.fail('CONDITIONAL_PASS needs explicit conditions')
    if opinion['decision'] == 'PASS' and opinion['conditions']:
        rt.fail('Unconditional PASS cannot retain necessary conditions')
    for analysis in raw['analyses']:
        if analysis['importance'] == 'OPTIONAL_IMPROVEMENT' and analysis['impact'] != 'NO_CURRENT_BLOCK':
            rt.fail('An optional improvement cannot block or limit required work')
        if analysis['importance'] == 'FUTURE_DEPENDENCY' and analysis['impact'] != 'FUTURE_DEPENDENCY':
            rt.fail('Future importance must match future impact')


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
    prepared = {'version': 'DIRECT_NECESSITY_PREPARED_2.0', 'gaps': gaps,
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
    return {'version': 'DIRECT_NECESSITY_2.0', 'complete': True,
        'scope': 'SCOPED_DATA_RECOMMENDATION', 'assessment': raw['assessment'], 'analyses': analyses,
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
