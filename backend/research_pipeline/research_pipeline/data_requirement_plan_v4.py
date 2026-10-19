"""Overview-only DR: reusable requirements, without a dataset-to-method graph.

This entry plans inputs and their applicability. It never decides coverage,
necessity resolution, fitness, source permissions, or a fitted model winner.
"""
import argparse
import copy
import difflib
import json
import re
import time
from pathlib import Path

from ctxcomp.io import digest
from ctxcomp.schemas import S, arr, enum, obj
from . import data_agents as d, data_requirement_planning as legacy
from . import data_source_first_workflow as sf, method_profiles_next as mp
from .adequacy import check_ref, file_ref
from .common import read_json, write_json

VERSION = 'REQUIREMENT_PLAN_4.0'
MODEL = 'gpt-6-luna'
USES = ('MODEL_BASED', 'NCA', 'PD_INDEX', 'PD_TARGET', 'PTA')
CURRENT_USES = {'MODEL_BASED', 'PD_INDEX', 'PD_TARGET', 'PTA'}
PROFILE_IDS = ('MP001', 'MP002', 'MP003', 'MP004', 'MP007', 'MP009', 'MP010', 'MP012')
RULE_FIELDS = ('id', 'kind', 'text', 'conditions', 'exceptions', 'scope', 'requirement', 'usage')
CONTEXT_FIELDS = ('objective', 'study', 'scientific_context', 'missing_information', 'potential_questions', 'uncertainties')
DEFAULT_BINDINGS = Path(__file__).resolve().parents[3]/'outputs/Codex_Agent_Run_20261009/data_test_12_dr_only/input_bindings.json'
HISTORICAL_CHECKER_SHA = '40ef17eaea5fe9aeae34d9206dbdbedbb2dabdc174fd6951a30cdd8d6e2b96a2'
HISTORICAL_CHECKER = DEFAULT_BINDINGS.parents[1]/'fixes/data-stated-value-literals/after_data_agents.py'
POLICY = {'scope': 'NONHUMAN_PLANNING', 'animal_pk_preference': 'MODEL_BASED', 'NCA': 'OPTIONAL_ALTERNATIVE',
          'animal_pk_satisfaction': 'EITHER_APPLICABLE_ROUTE_NOT_MUTUAL_PREREQUISITES',
          'current_method_uses': list(USES), 'human_translation': 'LATER_SOURCE_OBJECTIVE_NOT_CURRENT_DATA',
          'data_assignment_and_adequacy': 'LATER_INDEPENDENT_COVERAGE',
          'necessity_resolution': 'LATER_INDEPENDENT_STAGE', 'project_rules': 'UNCHANGED'}
INSTRUCTIONS = '''Produce concise reusable input requirements, not a methods graph or a data review.
Use the original project context, exact operative Rule fields and method knowledge. Data overviews
only orient the plan: do not infer completeness, missingness, pairability or numerical sufficiency.
Describe what input is needed, for which method uses, under which conditions, and by which phase.
A requirement can serve multiple methods. Knowledge profile references are separate from method uses:
MP009 plus MP012 may jointly inform a definition used for index and target work. Avoid duplicate needs.
Current uses are animal MODEL_BASED PK (preferred), optional NCA, PD_INDEX, PD_TARGET and nonhuman PTA.
Do not make NCA a prerequisite for model-based PK or vice versa. Terminal NCA inputs are conditional
on terminal endpoints; mean-curve methods do not automatically require individual IDs or IIV.
The current PD objective is K. pneumoniae; other organisms remain source/support context. Detailed
dataset assignment and independent-panel matching are for coverage, not this stage. Do not generate
task_id, analysis, group_id, dataset assignments, methods objects or availability/status conclusions.
PROJECT_EXPLICIT requires a direct permitted Rule text or an explicit scientific statement. A broad
objective alone does not explicitly request a library-derived endpoint. Such a candidate must instead
be METHOD_CANDIDATE, cite relevant method profiles plus project context, and state its conditions.
Explicit requirements have no method-library authority references; method_uses still describes use.
Rules explicitly scoped only to human cannot authorize current nonhuman requirements. They remain
unchanged later-project context. Do not access Horse, human data or benchmark sources, invent joins,
values or thresholds, or claim a method was fitted, adequate, validated or approved.
Keep original upstream missing_information as attributed context; neither close nor re-diagnose it.
Planned PK/target outputs are future task inputs, not missing raw measurements. PTA population/scenario
choices must be stated as definitions, not invented observations. State relevant conditional inputs
without converting every method-library caution into a mandatory blocker.
Only use provided project_source_ids and method_profile_ids. Never cite paper IDs from an upstream
Rule audit or bare dataset IDs as project authority. Notes are overview facts, not adopted obligations.
The host preserves all overview items independently; there is no obligation to invent one need per
table or to enumerate every dataset. Return requirements only, without an overall PASS or gap verdict.
'''


def fail(message):
    d.fail('REQUIREMENT_PLAN_V4_INVALID', message)


def unique(values, label):
    if len(values) != len(set(values)): fail('Duplicate '+label)
    return set(values)


def check_refs(value):
    if isinstance(value, dict):
        if 'path' in value and 'sha256' in value: check_ref(value)
        else:
            for v in value.values(): check_refs(v)
    elif isinstance(value, list):
        for v in value: check_refs(v)


def response_schema(payload):
    common = dict(description=S, method_uses=arr(enum(*USES), 1), input_fields=arr(S, 1),
                  conditions=arr(S), required_by=copy.deepcopy(d.PHASE))
    explicit = obj(**common, origin=enum('PROJECT_EXPLICIT'),
        project_source_ids=arr(enum(*payload['direct_project_source_ids']), 1),
        method_profile_ids={'type': 'array', 'items': enum(*PROFILE_IDS), 'maxItems': 0})
    candidate = obj(**common, origin=enum('METHOD_CANDIDATE'),
        project_source_ids=arr(enum(*payload['project_context_source_ids']), 1),
        method_profile_ids=arr(enum(*PROFILE_IDS), 1))
    candidate['properties']['conditions'] = arr(S, 1)
    return obj(request_sha256=S, requirements=arr({'anyOf': [explicit, candidate]}, 1))


def build_payload(main, source_view, knowledge=None):
    knowledge = copy.deepcopy(knowledge or mp.planning_context())
    library = mp.check_context(knowledge)
    profiles, note_sources = legacy.overview(source_view)
    grouped = {}
    for source, text in note_sources.items(): grouped.setdefault(text, []).append(source)
    for row in profiles: row['notes'] = [n['source'] for n in row['notes']]
    rules = []
    for index, original in enumerate(main.get('rules', [])):
        rule = {k: copy.deepcopy(original[k]) for k in RULE_FIELDS if k in original}
        rule['provenance'] = {'main_pointer': f'/rules/{index}', 'original_sha256': digest(original),
            'source_ids': sorted({e['source'] for field in ('evidence', 'authority_evidence')
                                  for e in original.get(field, []) if 'source' in e})}
        rules.append(rule)
    selected = mp.scoped_context(knowledge, PROFILE_IDS)
    sources = d.source_map(main, main.get('rules', []))
    direct = [f'main:/rules/{i}/text' for i, r in enumerate(main.get('rules', []))
              if {str(s).lower().strip() for s in r.get('scope', {}).get('species', [])} != {'human'}]
    direct += [k for k in sources if re.fullmatch(r'main:/scientific_context/items/\d+/statement', k)]
    context = list(dict.fromkeys(['main:/objective']+direct))
    if not direct: fail('No direct project authority supplied')
    method_sources = mp.evidence_sources(knowledge)
    catalog = {k: sources[k] for k in context}
    catalog.update({f'method:{i}': method_sources[f'method:{i}'] for i in PROFILE_IDS})
    payload = {'operation': VERSION, 'policy': copy.deepcopy(POLICY), 'instructions': INSTRUCTIONS,
        'project_context': {k: copy.deepcopy(main[k]) for k in CONTEXT_FIELDS if k in main},
        'project_rules': rules, 'method_knowledge': selected, 'data_overviews': profiles,
        'overview_notes': [{'text': text, 'source_ids': ids} for text, ids in grouped.items()],
        'direct_project_source_ids': direct, 'project_context_source_ids': context,
        'source_scope': 'CHECKED_METADATA_AND_REFERENCED_NOTES_ONLY; ORIGINAL NUMERIC ROWS NOT TRANSMITTED',
        'scientific_approval': False}
    return payload, response_schema(payload), catalog, knowledge


def materialize(raw, payload, sources, knowledge):
    d.validate_schema(raw, response_schema(payload))
    result = copy.deepcopy(raw)
    uses = set()
    validation_needs = []
    for index, n in enumerate(result['requirements'], 1):
        n['id'] = f'RQ{index:03d}'
        uses |= unique(n['method_uses'], 'method uses')
        unique(n['input_fields'], 'input fields')
        ids = list(n['project_source_ids']) + ['method:'+i for i in n['method_profile_ids']]
        if not unique(ids, 'source selectors') <= sources.keys(): fail('Unknown source')
        if not n['description'].strip() or any(not f.strip() for f in n['input_fields']): fail('Empty requirement content')
        text = n['description']+' '+' '.join(n['input_fields'])
        if re.search(r'\b(?:define|provide|require|collect|use|estimate|simulate)\s+(?:the\s+|a\s+)?human\b', text, re.I):
            fail('Human input belongs to a later project scope')
        n['evidence'] = [{'source': s, 'quote': sources[s]} for s in ids]
        d.evidence_check(n['evidence'], sources)
        validation_needs.append({'id': n['id'], 'origin': n['origin'], 'kind': 'DATA',
            'method_profile_ids': n['method_profile_ids'], 'conditions': n['conditions'], 'evidence': n['evidence']})
    mp.validate_requirements(validation_needs, knowledge)
    if not CURRENT_USES <= uses: fail('Current planning omitted a required method-use family')
    result.update(version=VERSION, policy=copy.deepcopy(POLICY),
        overview_manifest={'item_ids': [p['item_id'] for p in payload['data_overviews']],
            'overview_sha256': digest(payload['data_overviews']), 'notes_sha256': digest(payload['overview_notes']),
            'scope': payload['source_scope']}, scientific_approval=False, can_enter_qc=False, fit_ready=False)
    return result


def verify_source_checkpoint(source_run):
    """Resolve only the explicitly audited historical checker; every other ref is exact."""
    manifest = read_json(Path(source_run)/'manifest.json')
    if manifest['version'] != sf.VERSION: fail('Unknown source checkpoint contract')
    resolution = None
    for name, reference in manifest['bindings'].items():
        if name == 'original_data_checker' and file_ref(reference['path']) != reference:
            if reference['sha256'] != HISTORICAL_CHECKER_SHA or Path(reference['path']).resolve() != Path(d.__file__).resolve():
                fail('Historical checker is not the authorized snapshot')
            snapshot = file_ref(HISTORICAL_CHECKER)
            if snapshot['sha256'] != reference['sha256']: fail('Historical checker snapshot changed')
            resolution = {'original_path': reference['path'], 'original_sha256': reference['sha256'],
                'snapshot_ref': snapshot, 'current_checker_ref': file_ref(d.__file__),
                'diff': list(difflib.unified_diff(HISTORICAL_CHECKER.read_text(encoding='utf-8').splitlines(),
                    Path(d.__file__).read_text(encoding='utf-8').splitlines(), fromfile='historical', tofile='current')),
                'scope': 'HISTORICAL_EXTRACTION_VALIDATOR_ONLY; NO SOURCE REEXTRACTION OR APPROVAL'}
        else: check_ref(reference)
    verified = sf.verify_final_main(manifest['bindings']['main']['path'])
    if verified['main_ref'] != manifest['bindings']['main']: fail('Final main changed')
    return manifest, verified, resolution


def prepare(source_run, out, *, input_bindings=None, model=MODEL):
    source_run, out = Path(source_run).resolve(), Path(out).resolve()
    if source_run == out or source_run in out.parents or out in source_run.parents: fail('Use isolated output')
    if out.exists() and any(out.iterdir()): fail('Output already contains an attempt')
    baseline_path = Path(input_bindings or DEFAULT_BINDINGS).resolve()
    baseline = read_json(baseline_path); check_refs(baseline)
    manifest, verified, historical = verify_source_checkpoint(source_run)
    if manifest['bindings']['main'] != baseline['main'] or file_ref(source_run/'source_view.json') != baseline['source_view']:
        fail('Source checkpoint differs from approved input bindings')
    view = read_json(source_run/'source_view.json')
    if view.get('pending_item_ids'): fail('Source repairs remain pending')
    access = {x['item_id']: x for x in read_json(source_run/'permissions.json')['access']}
    if any(access.get(p['item_id'], {}).get('disposition') != 'REVIEW_DATA' for p in view['profiles']): fail('Unpermitted overview item')
    for item in read_json(source_run/'inventory.json')['items']:
        for key in ('source', 'snapshot'):
            if item.get(key): check_ref(item[key])
    payload, schema, sources, knowledge = build_payload(verified['main'], view)
    request = legacy.governed_request(payload, schema, model)
    size = len(json.dumps(request, ensure_ascii=False))
    if size > d.REQUEST_BUDGET: fail('Transport budget exceeded; no content truncated')
    bindings = {name: file_ref(source_run/(name+'.json')) for name in ('manifest', 'source_view', 'inventory', 'permissions')}
    bindings.update(main=baseline['main'], input_baseline=file_ref(baseline_path), code=file_ref(__file__),
                    overview_code=file_ref(legacy.__file__), method_loader=file_ref(mp.__file__), library=file_ref(mp.LIBRARY_PATH),
                    invocation_code=file_ref(d.__file__), source_workflow_code=file_ref(sf.__file__))
    if historical:
        bindings['historical_checker_snapshot'] = historical['snapshot_ref']
        write_json(out/'historical_checker_resolution.json', historical)
        bindings['historical_checker_resolution'] = file_ref(out/'historical_checker_resolution.json')
    for name, value in [('payload', payload), ('schema', schema), ('source_catalog', sources),
                        ('method_context', knowledge), ('request', request), ('bindings', bindings)]: write_json(out/(name+'.json'), value)
    write_json(out/'build.json', {'version': VERSION, 'request_chars': size, 'model': model, 'new_model_calls': 0,
        'payload_key_chars': {k: len(json.dumps(v, ensure_ascii=False)) for k, v in payload.items()}})
    return request


def run(source_run, out, *, input_bindings=None, generator=None, model=MODEL):
    started = time.monotonic(); out = Path(out)
    request = prepare(source_run, out, input_bindings=input_bindings, model=model)
    values = {n: read_json(out/(n+'.json')) for n in ('payload', 'schema', 'source_catalog', 'method_context', 'bindings')}
    def check(raw):
        check_refs(values['bindings']); check_refs(read_json(values['bindings']['input_baseline']['path']))
        materialize(raw, values['payload'], values['source_catalog'], values['method_context'])
        return True
    sf.emit(out, 'STAGE_START', stage=VERSION, model=model, request_chars=len(json.dumps(request, ensure_ascii=False)))
    try:
        raw = d.invoke(out, 'DR', values['payload'], values['schema'], model=model, generator=generator, check=check)
        check(raw); write_json(out/'raw.json', raw)
        result = materialize(raw, values['payload'], values['source_catalog'], values['method_context'])
        result['bindings'] = values['bindings']
        result['provenance'] = {n+'_ref': file_ref(out/(n+'.json')) for n in
                               ('raw', 'request', 'payload', 'schema', 'source_catalog', 'method_context', 'bindings')}
        result['provenance'].update(model=model, derivation='MODEL_PLAN_WITH_HOST_EXACT_SOURCE_MATERIALIZATION')
        staged = write_json(out/'staged/plan.json', result); staged.replace(out/'plan.json')
        verify_plan(out/'plan.json')
        sf.emit(out, 'STAGE_END', stage=VERSION, elapsed_seconds=time.monotonic()-started)
        return result
    except Exception as exc:
        sf.emit(out, 'STAGE_ERROR', stage=VERSION, elapsed_seconds=time.monotonic()-started, reason=str(exc)); raise


def verify_plan(path):
    plan = read_json(path)
    if plan.get('version') != VERSION: fail('Unknown plan version')
    check_refs(plan['bindings']); refs = plan['provenance']
    check_refs({k: v for k, v in refs.items() if k.endswith('_ref')})
    baseline = read_json(plan['bindings']['input_baseline']['path']); check_refs(baseline)
    _, _, historical = verify_source_checkpoint(Path(plan['bindings']['manifest']['path']).parent)
    if historical is not None and historical != read_json(plan['bindings']['historical_checker_resolution']['path']):
        fail('Historical checker resolution does not replay')
    if baseline['main'] != plan['bindings']['main'] or baseline['source_view'] != plan['bindings']['source_view']:
        fail('Plan input bindings changed')
    loaded = {n: read_json(refs[n+'_ref']['path']) for n in ('raw', 'request', 'payload', 'schema', 'source_catalog', 'method_context', 'bindings')}
    if loaded['bindings'] != plan['bindings']: fail('Bindings mismatch')
    rebuilt = build_payload(read_json(plan['bindings']['main']['path']), read_json(plan['bindings']['source_view']['path']), loaded['method_context'])
    for n, v in zip(('payload', 'schema', 'source_catalog', 'method_context'), rebuilt):
        if v != loaded[n]: fail('Input projection does not replay: '+n)
    if legacy.governed_request(loaded['payload'], loaded['schema'], refs['model']) != loaded['request']: fail('Request does not replay')
    if loaded['raw']['request_sha256'] != loaded['request']['request_sha256']: fail('Wrong response request')
    derived = materialize(loaded['raw'], loaded['payload'], loaded['source_catalog'], loaded['method_context'])
    if derived != {k: v for k, v in plan.items() if k not in ('bindings', 'provenance')}: fail('Plan differs from raw derivation')
    return plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-run', required=True); parser.add_argument('--out', required=True)
    parser.add_argument('--input-bindings'); parser.add_argument('--build-only', action='store_true')
    args = parser.parse_args()
    fn = prepare if args.build_only else run
    fn(args.source_run, args.out, input_bindings=args.input_bindings)
    print(json.dumps({'status': 'BUILT' if args.build_only else 'PLANNED_NOT_ASSESSED', 'out': str(Path(args.out).resolve())}))


if __name__ == '__main__': main()
