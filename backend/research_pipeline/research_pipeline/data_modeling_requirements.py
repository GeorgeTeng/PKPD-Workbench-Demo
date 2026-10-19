"""Objective-scoped modeling requirements, reusing verified source-first extraction.

Only planning: no access grants, fitting, adequacy approval or downstream calls.
Model selectors become literal host evidence with an explicit derivation record.
"""
import argparse
import copy
import json
import re
import time
from pathlib import Path
from ctxcomp.io import digest
from ctxcomp.schemas import obj, arr, S, enum
from . import data_agents as d, method_profiles as mp, data_source_first_workflow as sf
from . import data_source_first_organize as legacy
from .adequacy import file_ref, check_ref
from .common import read_json, write_json

VERSION = 'MODELING_REQUIREMENTS_2.0'
MODEL = 'gpt-6-luna'
TASKS = ('ANIMAL_PK', 'PD_INDEX')
ANALYSES = ('NCA', 'MODEL_BASED', 'PD_INDEX', 'SHARED')
METHODS = {'NCA': {'MP001', 'MP002', 'MP003'}, 'MODEL_BASED': {'MP004'},
           'PD_INDEX': {'MP009'}, 'SHARED': {'MP007'}}
ACTIVE_METHODS = set().union(*METHODS.values())
STATUSES = ('INPUT_CANDIDATE', 'PARTIAL', 'BLOCKED', 'NOT_APPLICABLE', 'DEFERRED')
SCOPE = ('CURRENT', 'DEFERRED', 'CONSTRAINT')
INSTRUCTIONS = '''Plan only the two user-authorized objectives ANIMAL_PK and PD_INDEX.
ANIMAL_PK must have separate NCA and MODEL_BASED approaches. PD_INDEX is independent.
Read all permitted original source_units and notes, not just extracted labels. Prior labels,
reasons and finding IDs were generated with historical requirements; they are provenance and
scientific cautions, never filters on the new planning. Preserve all gaps and conflicting facts.
Group approaches into defensible study/species/matrix/regimen/data-level analysis units;
one source table need not mean one mandatory model, and a dataset may support several candidates.
For each animal study/species, describe candidate structural model families and questions for later
comparison in approach name/reason/next_step. Do not select the final compartment count,
error model or estimator, fit parameters, declare identifiability, or infer IIV from group means.
NCA uses MP001, conditional terminal endpoints MP002, conditional disposition endpoints MP003.
User scope requests a NCA branch, not every NCA endpoint as mandatory. State endpoint use and conditions.
MP002/MP003 inherit relevant MP001 input needs through shared requirement references, not duplicated needs.
MP004 must be linked to actual MODEL_BASED requirements AND approaches. MP009 must be linked to actual
PD_INDEX requirements AND approaches. MP007 is only a shared free-exposure dependency; reuse its inputs.
MP005/006 are downstream, MP008/011 are not enabled by this objective/data scope: retain relevant
downstream objectives with explicit deferred coverage, without inventing active requirements.
METHOD_CANDIDATE needs cite both method:MPxxx and actual main/rule applicability, have conditions,
and retain conditional status. PROJECT_EXPLICIT needs cite actual project authority, not a method profile.
Source data may suggest candidates but cannot itself adopt a project requirement or grant access.
Every approach's method profiles must be covered by its linked requirements. Link dataset evidence
from every listed dataset. Use only the permitted item IDs. Do not combine known Mouse/Rat/Rabbit
datasets into one approach; cross-species translation is outside this run.
Keep individual, destructive, pooled and mean data distinct. Do not invent IDs, weights, doses,
variance, BLQ limits or exposure-response joins. Incompatible independent index panels cannot be
rank-matched into common records. K. pneumoniae index comparison keeps three requested indices and
ordinary Emax/sigmoid Emax candidates equally eligible, with common compatible records/windows,
MIC and binding basis; inability to compare remains a valid gap, never a forced winner.
Keep key results concise: each data group -> what NCA/model-based PK/PD index could do -> actual
blocking gaps -> one useful next_step. Do not copy entire requirements into approaches. missing_inputs
lists material blocking THIS approach, not every theoretical uncertainty; optional terminal or
variability inputs must not automatically block finite-window summaries. Keep conditional gaps conditional.
data_links covers every permitted profile using item_id, requirement_ids and a brief reason. For primary
PK observations cover both NCA and MODEL_BASED through approaches/needs, or explain in that reason why
a branch is not currently applicable or deferred. PD observations and time-kill records need PD_INDEX
coverage or an explicit non-relevance reason. No separate duplicate analysis-disposition graph.
objective_coverage covers every supplied objective source exactly once; CURRENT, DEFERRED or CONSTRAINT
may have no requirement IDs if justified. Cite that exact source (MI may cite same-record clarification).
Do not map a Rabbit-only objective to Mouse-only datasets. Retain all downstream objectives/constraints.
Select evidence_source_ids from context_sources, semantic project rule main:/rules/<index>/<field>
leaves, source_units or method:MPxxx. Host copies the original value verbatim and records materialization;
do not write quotes. Do not cite unavailable rule audit fields, model summaries or historical findings as
primary source evidence. Status describes input candidacy only, never a fitted/validated method.
'''


def fail(message):
    d.fail('MODELING_REQUIREMENTS_INVALID', message)


def selected_knowledge(knowledge):
    full = mp.check_context(knowledge)
    selected = copy.deepcopy(full)
    selected['profiles'] = [p for p in full['profiles'] if p['id'] in ACTIVE_METHODS]
    if {p['id'] for p in selected['profiles']} != ACTIVE_METHODS:
        fail('Required current method profiles absent')
    refs = {s for p in selected['profiles'] for s in p['source_ids']}
    selected['sources'] = [s for s in full['sources'] if s['id'] in refs]
    return {**copy.deepcopy(knowledge), 'library': selected, 'library_sha256': digest(selected)}


def selectors(schema):
    result = copy.deepcopy(schema)
    del result['properties']['evidence']
    result['required'].remove('evidence')
    result['properties']['evidence_source_ids'] = arr(S, 1)
    result['required'].append('evidence_source_ids')
    return result


def response_schema(payload):
    ids = [p['item_id'] for p in payload['data_profiles']]
    task = selectors(d.TASK)
    task['properties']['id'] = enum(*TASKS)
    need = selectors(d.NEED)
    need['properties'].update(task_id=enum(*TASKS), dataset_ids=arr(enum(*ids)), analysis=enum(*ANALYSES))
    need['required'] += ['dataset_ids', 'analysis']
    need['properties']['method_profile_ids'] = arr(enum(*sorted(ACTIVE_METHODS)))
    need['properties']['rule_ids'] = arr(enum(*[r['id'] for r in payload['project_rules']]))
    approach = obj(id=S, name=S, analysis=enum('NCA', 'MODEL_BASED', 'PD_INDEX'),
        dataset_ids=arr(enum(*ids)), requirement_ids=arr(S), method_profile_ids=arr(enum(*sorted(ACTIVE_METHODS)), 1),
        status=enum(*STATUSES), available_inputs=arr(S), missing_inputs=arr(S), applicability_conditions=arr(S, 1),
        reason=S, evidence_source_ids=arr(S, 1), next_step=S)
    return obj(request_sha256=S, tasks=arr(task, 2), requirements=arr(need),
        data_links=arr(obj(item_id=enum(*ids), requirement_ids=arr(S), reason=S, evidence_source_ids=arr(S, 1))),
        objective_coverage=arr(obj(source=enum(*payload['objective_source_ids']), scope=enum(*SCOPE),
            requirement_ids=arr(S), reason=S, evidence_source_ids=arr(S, 1))),
        method_feasibility=arr(obj(task_id=enum(*TASKS), approaches=arr(approach, 1)), 2),
        findings=arr(d.FINDING))


def build_payload(main, view, knowledge=None):
    full = knowledge or mp.planning_context()
    knowledge = selected_knowledge(full)
    payload, _, sources = legacy.build_payload(main, view, knowledge)
    payload.update(operation=VERSION, instructions=INSTRUCTIONS,
        task_scope={'ANIMAL_PK': ['NCA', 'MODEL_BASED'], 'PD_INDEX': ['PD_INDEX']},
        user_scope_authority='Explicit current user scope: animal PK (NCA and model-based separately) plus PD index; no fitting.',
        method_scope={'enabled': sorted(ACTIVE_METHODS), 'downstream': ['MP005', 'MP006'],
            'not_enabled': ['MP008', 'MP011'], 'full_library_sha256': full['library_sha256']},
        scientific_approval=False)
    # Full original notes remain; exact duplicated extracted quotes are selectors into host sources.
    def compact_profile(value):
        if isinstance(value, list): return [compact_profile(x) for x in value]
        if not isinstance(value, dict): return value
        out = {k: compact_profile(v) for k, v in value.items() if k != 'evidence'}
        if 'evidence' in value:
            d.evidence_check(value['evidence'], sources)
            out['evidence_source_ids'] = list(dict.fromkeys(e['source'] for e in value['evidence']))
        return out
    payload['data_profiles'] = [compact_profile(p) for p in payload['data_profiles']]
    return payload, response_schema(payload), sources, knowledge


def unique(values, label):
    if len(values) != len(set(values)): fail('Duplicate '+label)
    return set(values)


def own_evidence(row, dataset_ids):
    for item in dataset_ids:
        if not any(e['source'] == item or e['source'].startswith(item+':') for e in row['evidence']):
            fail('Missing actual dataset evidence: '+item)


def species(text):
    words = str(text).lower()
    return {name for name, pattern in [('Mouse', r'\b(mouse|mice|murine)\b'),
        ('Rat', r'\b(rat|rats)\b'), ('Rabbit', r'\b(rabbit|rabbits)\b')] if re.search(pattern, words)}


def validate_response(value, payload, sources, knowledge):
    tasks = {x['id']: x for x in value['tasks']}
    d.exact([x['id'] for x in value['tasks']], list(TASKS), 'Fixed objective tasks')
    if tasks['ANIMAL_PK']['destination'] != 'pk' or tasks['PD_INDEX']['destination'] != 'index': fail('Task destination differs')
    needs = {x['id']: x for x in value['requirements']}
    unique([x['id'] for x in value['requirements']], 'requirement IDs')
    datasets = {p['item_id']: p for p in payload['data_profiles']}
    rules = {r['id'] for r in payload['project_rules']}
    mp.validate_requirements(value['requirements'], knowledge)
    def evidence(row):
        if not row['evidence']: fail('Empty evidence')
        d.evidence_check(row['evidence'], sources)
    def refs(row):
        ids = unique(row['requirement_ids'], 'requirement references')
        if not ids <= needs.keys(): fail('Unknown requirement reference')
        return [needs[i] for i in row['requirement_ids']]
    for task in value['tasks']: evidence(task)
    for need in value['requirements']:
        evidence(need)
        if need['task_id'] not in TASKS or not set(need['rule_ids']) <= rules: fail('Unknown task/rule')
        if not set(need['method_profile_ids']) <= METHODS[need['analysis']]: fail('Method/analysis mismatch')
        if need['analysis'] in {'NCA', 'MODEL_BASED'} and need['task_id'] != 'ANIMAL_PK': fail('Animal need task mismatch')
        if need['analysis'] == 'PD_INDEX' and need['task_id'] != 'PD_INDEX': fail('PD need task mismatch')
        if not unique(need['dataset_ids'], 'need datasets') <= datasets.keys(): fail('Unpermitted need dataset')
        own_evidence(need, need['dataset_ids'])
    d.exact([x['task_id'] for x in value['method_feasibility']], list(TASKS), 'Feasibility tasks')
    approaches = {}
    for row in value['method_feasibility']:
        expected = {'NCA', 'MODEL_BASED'} if row['task_id'] == 'ANIMAL_PK' else {'PD_INDEX'}
        if {a['analysis'] for a in row['approaches']} != expected: fail('Missing or misrouted approach branch')
        for a in row['approaches']:
            if a['id'] in approaches: fail('Duplicate approach ID')
            approaches[a['id']] = a
            evidence(a)
            linked = refs(a)
            if not unique(a['dataset_ids'], 'approach datasets') <= datasets.keys(): fail('Unpermitted approach dataset')
            own_evidence(a, a['dataset_ids'])
            known_species = set().union(*(species(datasets[i].get('species', '')) for i in a['dataset_ids']))
            if len(known_species) > 1: fail('Cross-species approach must remain separate')
            methods = unique(a['method_profile_ids'], 'approach methods')
            if not methods <= METHODS[a['analysis']] | METHODS['SHARED'] or not methods & METHODS[a['analysis']]: fail('Approach method/analysis mismatch')
            if not methods <= {p for n in linked for p in n['method_profile_ids']}: fail('Approach methods lack linked requirements')
            if any(n['analysis'] not in {a['analysis'], 'SHARED'} for n in linked): fail('Approach links unrelated analysis')
            if any(n['dataset_ids'] and not set(n['dataset_ids']) & set(a['dataset_ids']) for n in linked if n['analysis'] != 'SHARED'): fail('Approach links unrelated dataset need')
            if not set(a['dataset_ids']) <= {i for n in linked for i in n['dataset_ids']}: fail('Approach datasets lack linked needs')
            cited = {e['source'][7:] for e in a['evidence'] if e['source'].startswith('method:')}
            if cited != methods or not any(e['source'].startswith(('main:', 'rule:')) for e in a['evidence']): fail('Approach lacks method/project evidence')
            if not a['applicability_conditions'] or not a['reason'].strip() or not a['next_step'].strip(): fail('Unexplained approach or next step')
    for pid in ('MP004', 'MP009'):
        if not any(n['origin'] == 'METHOD_CANDIDATE' and pid in n['method_profile_ids'] for n in needs.values()): fail('Missing actual method requirement '+pid)
        if not any(pid in a['method_profile_ids'] for a in approaches.values()): fail('Missing actual approach '+pid)
    d.exact([x['item_id'] for x in value['data_links']], list(datasets), 'Complete permitted datasets')
    for link in value['data_links']:
        evidence(link); own_evidence(link, [link['item_id']]); linked = refs(link)
        if any(link['item_id'] not in n['dataset_ids'] for n in linked): fail('Data link/need dataset mismatch')
        if not link['reason'].strip(): fail('Unexplained data link')
        expected = {n['id'] for n in needs.values() if link['item_id'] in n['dataset_ids']}
        if set(link['requirement_ids']) != expected: fail('Data links must reflect all formal dataset requirements')
    d.exact([x['source'] for x in value['objective_coverage']], payload['objective_source_ids'], 'Complete objective coverage')
    for row in value['objective_coverage']:
        evidence(row); linked = refs(row)
        allowed = {row['source']}
        match = re.fullmatch(r'main:/missing_information/items/(\d+)/field', row['source'])
        if match: allowed.update('main:/missing_information/items/'+match[1]+'/'+k for k in ('clarification', 'impact', 'why_it_matters'))
        if not any(e['source'] in allowed for e in row['evidence']): fail('Objective must cite own source')
        named = species(sources[row['source']])
        related = set().union(*(species(datasets[i].get('species', '')) for n in linked for i in n['dataset_ids']))
        if len(named) == 1 and related and named.isdisjoint(related): fail('Objective species conflicts with linked datasets')
        if not row['reason'].strip(): fail('Unexplained objective coverage')
    return True


def materialize(raw, payload, sources, knowledge):
    d.validate_schema(raw, response_schema(payload))
    def convert(value):
        if isinstance(value, list): return [convert(x) for x in value]
        if not isinstance(value, dict): return value
        out = {k: convert(v) for k, v in value.items() if k != 'evidence_source_ids'}
        if 'evidence_source_ids' in value:
            ids = value['evidence_source_ids']
            if not unique(ids, 'evidence selectors') <= sources.keys(): fail('Unknown evidence selector')
            out['evidence'] = [{'source': key, 'quote': sources[key]} for key in ids]
        return out
    derived = convert(raw)
    validate_response(derived, payload, sources, knowledge)
    return derived


def governed_request(payload, schema):
    class Captured(Exception): pass
    private = sf.private_module()
    def capture(p):
        error = Captured(); error.request = d.governed_request(p); raise error
    private.governed_request = capture
    try: private.invoke(Path('.'), 'DR', payload, schema, model=MODEL)
    except Captured as result: return result.request
    fail('Request capture reached execution')


def prepare(source_run, out):
    source_run, out = Path(source_run).resolve(), Path(out).resolve()
    if source_run == out or source_run in out.parents or out in source_run.parents: fail('Use an isolated output directory')
    if out.exists() and any(out.iterdir()): fail('Output already contains an attempt; no silent resampling')
    manifest, verified = sf.verify_run(source_run)
    view = read_json(source_run/'source_view.json'); inventory = read_json(source_run/'inventory.json')
    permissions = read_json(source_run/'permissions.json')
    if view['pending_item_ids']: fail('Source repairs still pending')
    access = {a['item_id']: a for a in permissions['access']}
    if any(access.get(p['item_id'], {}).get('disposition') != 'REVIEW_DATA' for p in view['profiles']): fail('Unpermitted profile')
    ids = [p['item_id'] for p in view['profiles']]; unique(ids, 'source profiles')
    if any(not any(k == i or k.startswith(i+':') for i in ids) for k in view['source_units']): fail('Unpermitted source unit')
    for item in inventory['items']:
        for key in ('source', 'snapshot'):
            if item.get(key): check_ref(item[key])
    full = mp.planning_context()
    payload, schema, sources, knowledge = build_payload(verified['main'], view, full)
    request = governed_request(payload, schema)
    chars = len(json.dumps(request, ensure_ascii=False))
    if chars > d.REQUEST_BUDGET: fail('Request exceeds 700000 characters; no content truncated: '+str(chars))
    bindings = {name: file_ref(source_run/name) for name in ('manifest.json', 'inventory.json', 'permissions.json', 'source_view.json')}
    bindings.update(main=manifest['bindings']['main'], code=file_ref(__file__), library=file_ref(mp.LIBRARY_PATH),
        DR_policy=file_ref(d.AGENT_FILES['DR']))
    write_json(out/'bindings.json', {'version': VERSION, 'inputs': bindings, 'scientific_approval': False})
    for name, value in [('full_method_context', full), ('method_context', knowledge), ('payload', payload), ('schema', schema),
                        ('source_catalog', sources), ('request', request)]: write_json(out/(name+'.json'), value)
    write_json(out/'build.json', {'version': VERSION, 'request_chars': chars, 'model': MODEL, 'new_model_calls': 0})
    return request


def run(source_run, out, *, generator=None):
    started = time.monotonic(); out = Path(out)
    request = prepare(source_run, out)
    payload, schema, sources, knowledge = [read_json(out/(n+'.json')) for n in ('payload', 'schema', 'source_catalog', 'method_context')]
    bindings = read_json(out/'bindings.json'); checked = {}
    def check(raw):
        for reference in bindings['inputs'].values(): check_ref(reference)
        checked['derived'] = materialize(raw, payload, sources, knowledge)
        return True
    sf.emit(out, 'STAGE_START', stage=VERSION, model=MODEL, request_chars=len(json.dumps(request, ensure_ascii=False)))
    try:
        raw = d.invoke(out, 'DR', payload, schema, model=MODEL, generator=generator, check=check)
        for reference in bindings['inputs'].values(): check_ref(reference)
        write_json(out/'raw.json', raw)
        derived = checked['derived']; write_json(out/'derived.json', derived)
        permissions = read_json(Path(source_run)/'permissions.json')['access']
        links = {x['item_id']: x for x in derived['data_links']}
        access = [{**copy.deepcopy(a), 'requirement_ids': links.get(a['item_id'], {}).get('requirement_ids', [])} for a in permissions]
        result = {'schema_version': VERSION, **derived, 'access': access,
            'provenance': {'bindings_ref': file_ref(out/'bindings.json'), 'raw_ref': file_ref(out/'raw.json'),
                'source_catalog_ref': file_ref(out/'source_catalog.json'), 'full_method_context_ref': file_ref(out/'full_method_context.json'),
                'request_ref': file_ref(out/'request.json'), 'evidence_derivation': 'HOST_LITERAL_MATERIALIZATION_OF_MODEL_SOURCE_SELECTORS',
                'model_for_this_planning': MODEL, 'extraction': 'REUSED_CHECKED_LEGACY_SOURCES_NOT_NEW_EXTRACTION'},
            'scientific_approval': False, 'can_enter_qc': False, 'fit_ready': False}
        staged = write_json(out/'staged/requirements.json', result)
        target = out/'requirements.json'; staged.replace(target)
        sf.emit(out, 'STAGE_END', stage=VERSION, elapsed_seconds=time.monotonic()-started, requirements_ref=file_ref(target))
        return result
    except Exception as exc:
        sf.emit(out, 'STAGE_ERROR', stage=VERSION, elapsed_seconds=time.monotonic()-started, reason=str(exc)); raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-run', required=True); parser.add_argument('--out', required=True)
    parser.add_argument('--build-only', action='store_true'); args = parser.parse_args()
    result = prepare(args.source_run, args.out) if args.build_only else run(args.source_run, args.out)
    print(json.dumps({'status': 'BUILT' if args.build_only else 'DR_PLANNED_UNAPPROVED',
        'request_sha256': result.get('request_sha256'), 'out': str(Path(args.out).resolve())}))


if __name__ == '__main__': main()
