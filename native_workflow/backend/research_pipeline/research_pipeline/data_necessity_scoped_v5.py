"""Action/source consistency for new assessments; historical v3 is unchanged."""
import copy
from pathlib import Path
from ctxcomp.schemas import validate_schema
from ctxcomp.io import digest
from . import data_necessity_decisions as old, data_necessity_direct as base
from . import data_necessity_prompt as prompt, data_coverage_scoped_v3 as coverage, data_direct_runtime as rt
from .common import read_json, write_json

ACTIONS, READINESS = old.ACTIONS, old.READINESS
UNKNOWN = 'UNESTABLISHED_SOURCE'
VERSION = 'DIRECT_NECESSITY_5.0'
INSTRUCTIONS = prompt.INSTRUCTIONS + '''
Use action_scopes to bind each analysis to the exact action_id and source_ids
affected by its impact. These IDs must match the supplied available_scope_ids.
Use UNESTABLISHED_SOURCE when a shortage has no established source. Account for
every unresolved source scope of a grouped shortage. Do not assign the same gap
to multiple analyses; use multiple action_scopes when one fact affects several actions.
Each action_decision has scope_readiness rows only for actually assessed scopes.
An action's gap_ids is exactly the union of shortages linked to that action.
BLOCKS_ACTION requires NOT_READY for that action/source; PENDING_CONFIRMATION
requires NOT_ESTABLISHED or NOT_READY; LIMITS_ANALYSIS cannot be READY;
FUTURE_DEPENDENCY requires LATER for the consuming action/source only.
Aggregate scope readiness: all READY -> READY; identical states retain that state;
mixed states with READY or CONDITIONAL -> CONDITIONAL; otherwise any NOT_READY
-> NOT_READY; otherwise NOT_ESTABLISHED. No scope/action Cartesian expansion.
Reported/context support is not measurement support. Consult the supplied typed
coverage fields and source profiles; retain quantities, units, basis and record level.
Coverage v3 dimensions and support kinds belong to each source_scopes record.
recorded_value_presence PRESENT preserves cited values; it does not resolve unknown
measurement dimensions or establish analysis adequacy. Account for these explicit
qualification shortages only in the affected action/source. Never turn unknown basis
into NOT_APPLICABLE or qualified support, or a present value into confirmed absence.
Task scopes are current nonhuman applications; later human/held-out context does not
authorize current human observations or downstream execution. Exact cited-rule
conditions/exceptions remain inherited constraints, not observations of satisfaction.
'''


def schema_for(gaps, profiles, scopes):
    schema = old.schema_for(gaps, profiles)
    link = base.obj({'action_id': {'type':'string','enum':ACTIONS},
                     'scope_ids': {**base.strings(scopes), 'minItems':1}})
    analysis = schema['properties']['analyses']['items']
    analysis['properties']['action_scopes'] = {'type':'array','items':link,'minItems':1}
    analysis['required'].append('action_scopes')
    row = base.obj({'scope_id': {'type':'string','enum':scopes}, 'readiness': {'type':'string','enum':READINESS}})
    for action in schema['properties']['action_decisions']['properties'].values():
        action['properties']['scope_readiness'] = {'type':'array','items':row,'minItems':1}
        action['required'].append('scope_readiness')
    return schema


def aggregate(states):
    states = set(states)
    if len(states) == 1:
        return next(iter(states))
    if states & {'READY','CONDITIONAL'}:
        return 'CONDITIONAL'
    return 'NOT_READY' if 'NOT_READY' in states else 'NOT_ESTABLISHED'


def gap_scopes(gap):
    groups = gap.get('source_scopes', [])
    if groups:
        return {g['item_id'] for g in groups if g['status'] not in {'SUPPORTED','NOT_APPLICABLE'}} or {UNKNOWN}
    return {e['item_id'] for e in gap.get('evidence', []) if 'item_id' in e} or {UNKNOWN}


def validate_response(raw, p):
    validate_schema(raw, p['request']['payload']['schema'])
    old.validate_response(raw, p)
    expected = {action:set() for action in ACTIONS}
    decisions = raw['action_decisions']
    scopes_by_action = {}
    for action, decision in decisions.items():
        rows = decision['scope_readiness']
        scopes = {r['scope_id']:r['readiness'] for r in rows}
        if len(scopes) != len(rows) or len(set(decision['gap_ids'])) != len(decision['gap_ids']):
            rt.fail('Duplicate action scope or shortage')
        if decision['readiness'] != aggregate(scopes.values()):
            rt.fail('Action readiness disagrees with its source scopes')
        scopes_by_action[action] = scopes
    allowed = {'BLOCKS_ACTION': {'NOT_READY'}, 'PENDING_CONFIRMATION': {'NOT_ESTABLISHED','NOT_READY'},
               'LIMITS_ANALYSIS': {'CONDITIONAL','NOT_READY','NOT_ESTABLISHED'}, 'FUTURE_DEPENDENCY': {'LATER'}}
    for analysis in raw['analyses']:
        links = analysis['action_scopes']
        if len({x['action_id'] for x in links}) != len(links):
            rt.fail('Duplicate analysis action link')
        required = set().union(*(gap_scopes(p['gaps'][g]) for g in analysis['gap_ids']))
        assigned = set()
        for link in links:
            action, scopes = link['action_id'], link['scope_ids']
            if len(scopes) != len(set(scopes)) or not set(scopes).issubset(required):
                rt.fail('Analysis cites duplicated or unrelated shortage scopes')
            assigned.update(scopes)
            expected[action].update(analysis['gap_ids'])
            for scope in scopes:
                status = scopes_by_action[action].get(scope)
                if status is None:
                    rt.fail('Action omits an affected source scope')
                if analysis['impact'] in allowed and status not in allowed[analysis['impact']]:
                    rt.fail('Action/source readiness contradicts the detailed impact')
        if assigned != required:
            rt.fail('Analysis omitted an unresolved shortage source scope')
    for action, decision in decisions.items():
        if set(decision['gap_ids']) != expected[action]:
            rt.fail('Action shortage links differ from its detailed analyses')


def prepare(coverage_path, main_path, mp_path, out):
    bindings = {**rt.runtime_bindings(), 'necessity_code':rt.file_ref(__file__),
        'legacy_contract':rt.file_ref(base.__file__), 'opinion_contract':rt.file_ref(old.__file__),
        'prompt_code':rt.file_ref(prompt.__file__), 'coverage_contract':rt.file_ref(coverage.__file__),
        'coverage':rt.file_ref(coverage_path), 'main':rt.file_ref(main_path), 'local_method_profiles':rt.file_ref(mp_path)}
    cov = coverage.verify_result(coverage_path)
    main, mp = read_json(main_path), read_json(mp_path)
    if cov['bindings']['main'] != bindings['main']:
        rt.fail('Necessity main differs from Coverage')
    gaps = base.collect_gaps(cov)
    scopes = sorted({v['item_id'] for v in cov['source_catalog'].values()} | {UNKNOWN})
    payload = {'stage':'NECESSITY_SCOPED_ASSESSMENT', 'instructions':INSTRUCTIONS,
        'objective':main['objective'], 'rules':[{k:r[k] for k in coverage.old.RULE_KEYS if k in r} for r in main['rules']],
        'requirements':[{k:r[k] for k in (*coverage.old.REQUIREMENT_KEYS,'task_scope','inherited_rule_constraints') if k in r} for r in cov['requirements']],
        'coverage_summary':{rid:{'status':c['status'], 'summary':c['summary'],
            'supported_fields':{k:v for k,v in c['fields'].items() if v['status'] in {'SUPPORTED','NOT_APPLICABLE'}}}
            for rid,c in cov['checks'].items()},
        'source_profiles':cov['source_profiles'], 'available_scope_ids':scopes, 'recorded_shortages':gaps,
        'local_method_knowledge':{k:mp[k] for k in ('version','status','use','interpretation','sources','profiles') if k in mp}}
    p = {'version':'DIRECT_NECESSITY_PREPARED_5.0', 'bindings':bindings, 'gaps':gaps,
         'request':rt.make_request(payload, schema_for(gaps,[x['id'] for x in mp['profiles']],scopes))}
    path = Path(out)/'prepared.json'
    if path.exists() and read_json(path) != p:
        rt.fail('Prepared Necessity differs; use a new directory')
    rt.verify_refs(bindings)
    if not path.exists():
        write_json(path,p)
    return p


def materialize(raw, p, bindings, receipt):
    result = old.materialize(raw,p,bindings,receipt)
    result['version'] = VERSION
    return result


def prepared(out):
    path = Path(out)/'prepared.json'
    p = read_json(path)
    if p.get('version') != 'DIRECT_NECESSITY_PREPARED_5.0':
        rt.fail('Legacy Necessity cannot resume under the scoped contract')
    rt.verify_refs(p['bindings'])
    if p['request']['request_sha256'] != digest(p['request']['payload']):
        rt.fail('Necessity prepared request hash changed')
    # Reconstruct the request and its schema before every call/replay.
    prepare(*(p['bindings'][k]['path'] for k in ('coverage','main','local_method_profiles')), out)
    return p, {**p['bindings'], 'prepared':rt.file_ref(path)}


def run_prepared(out, generator=None):
    out = Path(out)
    p, bindings = prepared(out)
    if generator is None and read_json(bindings['coverage']['path'])['execution']['test_generator']:
        rt.fail('Real Necessity cannot consume synthetic Coverage')
    raw = rt.invoke(out/'call',p['request'],bindings,lambda r:validate_response(r,p),generator=generator)
    result = materialize(raw,p,bindings,read_json(out/'call/accepted.json'))
    rt.verify_refs(bindings)
    write_json(out/'necessity.json',result)
    return result


def verify_result(path):
    path = Path(path)
    p, bindings = prepared(path.parent)
    receipt = read_json(path.parent/'call/accepted.json')
    rt.verify_refs({'raw':receipt['raw']})
    raw = read_json(receipt['raw']['path'])
    validate_response(raw,p)
    if (receipt.get('requested_model') != rt.MODEL or not isinstance(receipt.get('test_generator'),bool)
            or any(m != rt.MODEL for m in receipt.get('served_models',[]))
            or raw['request_sha256'] != p['request']['request_sha256'] or receipt['request_sha256'] != raw['request_sha256']):
        rt.fail('Necessity receipt identity changed')
    result = read_json(path)
    if result != materialize(raw,p,bindings,receipt):
        rt.fail('Necessity differs from accepted scoped opinion')
    return result
