"""Versioned requirement planning from source overviews, never adequacy assessment."""
import argparse
import copy
import json
import re
import time
from pathlib import Path

from ctxcomp.io import digest
from ctxcomp.schemas import S, arr, enum, obj
from . import data_agents as d, data_source_first_workflow as sf
from . import method_profiles_next as mp
from .adequacy import check_ref, file_ref
from .common import read_json, write_json

VERSION = 'REQUIREMENT_PLANNING_3.3'
MODEL = 'gpt-6-luna'
FAMILIES = ('NCA', 'MODEL_BASED', 'PD_INDEX', 'PD_TARGET', 'PTA')
TASKS = ('ANIMAL_PK', 'PD_INDEX', 'PD_TARGET', 'PTA')
ROUTES = {'NCA': {'MP001', 'MP002', 'MP003'}, 'MODEL_BASED': {'MP004'},
          'PD_INDEX': {'MP009'}, 'PD_TARGET': {'MP012'}, 'PTA': {'MP010'}, 'SHARED': {'MP007'}}
ACTIVE_PROFILES = set().union(*ROUTES.values())
ROUTES['SHARED'] = ACTIVE_PROFILES
POLICY = {'animal_pk': {'preferred_family': 'MODEL_BASED', 'optional_family': 'NCA',
                      'satisfaction': 'ANY_ONE', 'scope_keys': ['study', 'species', 'matrix', 'record_level']},
          'stage': 'REQUIREMENT_PLANNING_ONLY', 'rules_authority': 'UNCHANGED_PROJECT_RULES',
          'coverage_and_necessity': 'DEFERRED_TO_INDEPENDENT_STAGES',
          'current_population': 'NONHUMAN', 'current_pd_organism': 'K_PNEUMONIAE',
          'human_translation': 'LATER_OBJECTIVE_RETAINED_IN_SOURCE_NOT_CURRENT_REQUIREMENT'}
INSTRUCTIONS = '''Plan requirements; do not review data adequacy, assign availability, missingness,
feasibility status or blockers. Input profiles are lightweight source overviews, not a full data review.
Upstream missing_information remains attributed source context, not this DR's coverage verdict;
planning neither closes those items nor resolves conflicting source claims.
Derive obligations from objectives and unchanged project Rules. Method profiles propose conditional
candidate requirements, never replace project authority. Keywords only locate clues, not decisions.
Tasks are ANIMAL_PK, PD_INDEX, PD_TARGET and PTA. For each animal study/species/matrix/record-level
scope prefer MODEL_BASED. NCA is an optional alternative: either adequate route may satisfy that
animal PK scope, neither is a prerequisite for the other. Reuse common needs through references.
Use one group_id for those alternative routes only when their scope is exactly the same. Separate
different studies, species, matrices and record levels. Do not infer individual trajectories or IIV
from group means, pair independent panels, invent dose events from sampling times, or read holdouts.
Describe candidate requirements with necessity REQUIRED or CONDITIONAL and explicit applicability
conditions. Conditions are triggers, not findings that data failed. METHOD_CANDIDATE needs cite both
the actual project objective/rule and each chosen method profile. PROJECT_EXPLICIT needs cite actual
project authority; dataset notes alone cannot authorize an obligation. Optional terminal NCA endpoints
MP002/003 must remain conditional; absence of terminal inputs does not block finite-window NCA.
Route MP001/002/003 to NCA, MP004 to MODEL_BASED, MP009 to PD_INDEX, MP012 to PD_TARGET, MP010 to PTA.
MP007 is a shared free-exposure dependency only when that basis is used, not a universal total-PK gate.
Do not add all method-library conditions as mandatory requirements. Planned fitted outputs are
requirements on a future producing task, not absent raw observations. No fitting or winner selection.
Use methods.dataset_ids for the analysis datasets and supporting_item_ids for permitted documents or
auxiliary inputs. Keep requirements reusable; do not add duplicate dataset mappings to requirements.
Keep method and requirement IDs concise, descriptions specific, and conditions short. Do not repeat
source tables, historical findings, old requirement IDs or old availability conclusions. Select only
supplied evidence_source_ids; host will materialize exact original text with an audit trail.
Use ONLY allowed_evidence_source_ids: main:/objective, supplied main scientific/MI statements,
main:/rules/<index>/text, method:MPxxx or actual supplied note source IDs. Upstream paper IDs such as
F0003_P0001 and bare dataset IDs are NOT evidence selectors. Method-derived requirements need BOTH
method:MPxxx and the actual relevant main/rule source, not a paper citation copied from a rule audit.
Current planning is nonhuman only, including nonhuman PTA. Preserve later human translation in main
context without creating current human-population/dose/data requirements. Current PD index/target
goal is K. pneumoniae; E. coli and other organisms may be supporting_item_ids, not primary PD datasets.
Use SHARED for common time/dose/identity inputs or PD definitions used across families; SHARED can
cite all relevant active method profiles. Keep its applicability conditions and authority evidence.
Do not attach PD_INDEX-only needs to PD_TARGET: shared definitions must explicitly be SHARED.
Every primary PK item listed in primary_pk_item_ids must occur in a MODEL_BASED candidate, or in
pk_exclusions with a brief source-bound scope reason. Never exclude it merely by presuming inadequacy;
coverage is later. Exclusions are only original metadata proving outside the current objective scope
or supporting-only purpose, never flags, missing fields, uncertainty or SOURCE_REVIEW judgments.
Retain MODEL_BASED in every animal group; NCA is optional. Shared needs do not
remove the actual MP004/MP009/MP012/MP010 profile link required by each method family.
Authority is exclusive: PROJECT_EXPLICIT evidence must not contain method: citations. If both
project and method authority are needed for a candidate, use METHOD_CANDIDATE with actual project
evidence, all cited method IDs and explicit applicability conditions. Do not relabel a candidate as
explicit simply because the broader project objective is explicit. A shared definition used by two
families has analysis SHARED; keep its real task owner and all relevant method authority. Every need
must be used by a retained method. Do not generate unselected optional NCA/terminal needs as orphan
obligations or attach them to MODEL_BASED merely to satisfy a reference check.
'''


def fail(message):
    d.fail('REQUIREMENT_PLANNING_INVALID', message)


def unique(values, what):
    if len(values) != len(set(values)):
        fail('Duplicate ' + what)
    return set(values)


def overview(view):
    """Whitelist descriptive metadata; no measurements, historical judgments or body quotes."""
    units = view.get('source_units', {})
    profiles, visible = [], {}
    fields = ('role', 'additional_roles', 'species', 'matrix', 'record_level', 'record_category',
              'route', 'dose_basis', 'analyte', 'dosing_regimen', 'endpoint_window', 'observation_source')
    for original in view['profiles']:
        item = original['item_id']
        descriptor = json.loads(units.get(item, '{}'))
        profile = {'item_id': item, **{k: copy.deepcopy(original[k]) for k in fields if k in original}}
        profile.update({k: copy.deepcopy(descriptor[k]) for k in ('title', 'kind', 'sheet', 'study', 'sampling_design') if k in descriptor})
        profile['columns'] = [{k: copy.deepcopy(c[k]) for k in ('header', 'meaning', 'unit', 'qualifiers') if k in c}
                              for c in original.get('columns', [])]
        notes = []
        for key in ('source_notes', 'linked_notes'):
            if isinstance(descriptor.get(key), str):
                notes.extend(descriptor[key].splitlines())
        # Documents can themselves reproduce numeric tables. Only the checked overview's
        # original descriptive references are included here; coverage reads the full document.
        if descriptor.get('kind') == 'document':
            notes.extend(units[key] for key in original.get('evidence_source_ids', [])
                         if key in units and key.startswith(item + ':'))
        notes = list(dict.fromkeys(n for n in notes if n.strip()))
        profile['notes'] = []
        for index, note in enumerate(notes):
            matches = [k for k, text in units.items() if k.startswith(item + ':') and text == note]
            source = matches[0] if matches else f'overview:{item}:note:{index}'
            visible[source] = note
            profile['notes'].append({'source': source, 'text': note})
        profiles.append(profile)
    unique([p['item_id'] for p in profiles], 'profile IDs')
    return profiles, visible


def response_schema(payload):
    need = copy.deepcopy(d.NEED)
    need['properties'].pop('evidence'); need['required'].remove('evidence')
    need['properties'].update(analysis=enum(*FAMILIES, 'SHARED'), necessity=enum('REQUIRED', 'CONDITIONAL'),
                              task_id=enum(*TASKS), evidence_source_ids=arr(enum(*payload['allowed_evidence_source_ids']), 1))
    need['required'] += ['analysis', 'necessity', 'evidence_source_ids']
    need['properties']['method_profile_ids'] = arr(enum(*sorted(set().union(*ROUTES.values()))))
    explicit = copy.deepcopy(need)
    explicit['properties']['origin'] = enum('PROJECT_EXPLICIT')
    explicit['properties']['evidence_source_ids'] = arr(enum(*[s for s in payload['allowed_evidence_source_ids']
                                                             if not s.startswith('method:')]), 1)
    candidate = copy.deepcopy(need)
    candidate['properties']['origin'] = enum('METHOD_CANDIDATE')
    candidate['properties']['method_profile_ids']['minItems'] = 1
    candidate['properties']['conditions']['minItems'] = 1
    ids = [p['item_id'] for p in payload['data_profiles']]
    method = obj(id=S, group_id=S, family=enum(*FAMILIES),
                 scope=obj(study=S, species=S, matrix=S, record_level=S),
                 dataset_ids=arr(enum(*ids), 1), supporting_item_ids=arr(enum(*ids)),
                 requirement_ids=arr(S, 1))
    exclusion = obj(item_id=enum(*ids), reason=S,
                    evidence_source_ids=arr(enum(*payload['allowed_evidence_source_ids']), 1))
    return obj(request_sha256=S, requirements=arr({'anyOf': [explicit, candidate]}, 1), methods=arr(method, 1), pk_exclusions=arr(exclusion))


def build_payload(main, source_view, knowledge=None):
    knowledge = copy.deepcopy(knowledge or mp.planning_context())
    mp.check_context(knowledge)
    profiles, notes = overview(source_view)
    # One exact text body; every original source ID remains visible and resolves identically.
    grouped = {}
    for source, text in notes.items(): grouped.setdefault(text, []).append(source)
    overview_notes = [{'text': text, 'sources': ids} for text, ids in grouped.items()]
    for profile in profiles: profile['notes'] = [n['source'] for n in profile['notes']]
    rules = copy.deepcopy(main.get('rules', []))
    # Full Rules occur once; source IDs resolve to their unchanged canonical JSON.
    sources = d.source_map(main, rules)
    context = {k: v for k, v in sources.items() if k.startswith('main:') and not k.startswith('main:/rules/')}
    sources.update(notes)
    sources.update(mp.evidence_sources(knowledge))
    payload = {'operation': VERSION, 'objective': main['objective'], 'policy': copy.deepcopy(POLICY),
               'instructions': INSTRUCTIONS, 'context_sources': context, 'project_rules': rules,
               'method_knowledge': knowledge, 'data_profiles': profiles, 'overview_notes': overview_notes,
               'source_overview_contract': 'DESCRIPTIVE_METADATA_AND_NOTES_ONLY_NOT_ADEQUACY',
               'scientific_approval': False}
    # Hide main.data registry body and non-present sources; only metadata notes are source inputs.
    allowed = {'main:/objective'} | set(notes) | {'method:'+i for i in ACTIVE_PROFILES}
    allowed.update(k for k in context if re.fullmatch(r'main:/scientific_context/items/\d+/statement', k)
                   or re.fullmatch(r'main:/missing_information/items/\d+/(field|clarification|impact|why_it_matters)', k))
    allowed.update(k for k in sources if re.fullmatch(r'main:/rules/\d+/text', k))
    sources = {k: v for k, v in sources.items() if k in allowed}
    payload['allowed_evidence_source_ids'] = sorted(sources)
    payload['primary_pk_item_ids'] = [p['item_id'] for p in profiles if p.get('role') == 'PK_OBSERVATIONS']
    return payload, response_schema(payload), sources, knowledge


def validate_plan(plan, payload, sources, knowledge):
    needs = {n['id']: n for n in plan['requirements']}
    unique([n['id'] for n in plan['requirements']], 'requirement IDs')
    unique([m['id'] for m in plan['methods']], 'method IDs')
    mp.validate_requirements(plan['requirements'], knowledge)
    rules = {r['id'] for r in payload['project_rules']}
    profiles = {p['item_id']: p for p in payload['data_profiles']}
    for n in needs.values():
        d.evidence_check(n['evidence'], sources)
        if not set(n['rule_ids']) <= rules: fail('Unknown project rule')
        if not set(n['method_profile_ids']) <= ROUTES[n['analysis']]: fail('Method knowledge routed to unrelated analysis')
        task = 'ANIMAL_PK' if n['analysis'] in ('NCA', 'MODEL_BASED') else n['analysis']
        if n['analysis'] != 'SHARED' and n['task_id'] != task: fail('Requirement task/analysis mismatch')
        if n['necessity'] == 'CONDITIONAL' and not n['conditions']: fail('Conditional requirement lacks applicability conditions')
        if set(n['method_profile_ids']) & {'MP002', 'MP003'} and n['necessity'] != 'CONDITIONAL':
            fail('Optional terminal/disposition endpoints must stay conditional')
        # Narrow contradiction check for explicitly requested human inputs; no adequacy inference.
        explicit = n['description'] + ' ' + ' '.join(n['fields'])
        if re.search(r'\b(?:define|provide|require|collect|use|estimate|simulate)\s+(?:the\s+|a\s+)?human\b', explicit, re.I):
            fail('Current planning cannot request human inputs; human translation remains later')
    groups, linked = {}, set()
    for m in plan['methods']:
        dataset = unique(m['dataset_ids'], 'method dataset IDs')
        support = unique(m['supporting_item_ids'], 'support IDs')
        if not (dataset | support) <= profiles.keys(): fail('Unknown or protected item')
        refs = unique(m['requirement_ids'], 'method requirement IDs')
        if not refs <= needs.keys(): fail('Unknown method requirement')
        linked |= refs
        if any(needs[q]['analysis'] not in (m['family'], 'SHARED') for q in refs): fail('Unrelated requirement route')
        if not any(set(needs[q]['method_profile_ids']) & ROUTES[m['family']] for q in refs): fail('Method needs its actual profile-linked requirement')
        scope = m['scope']
        if any(not str(v).strip() for v in scope.values()): fail('Empty method scope')
        old = groups.setdefault(m['group_id'], {'scope': scope, 'families': set()})
        if old['scope'] != scope: fail('Different study/species/matrix/record level in same group')
        old['families'].add(m['family'])
        if len(old['families']) > 1 and not old['families'] <= {'NCA', 'MODEL_BASED'}: fail('Unrelated task routes cannot satisfy one another')
        # Explicit species descriptors protect grouping, not scientific inference from keywords.
        def known_species(text):
            import re
            return {name for name, pattern in [('Mouse', r'\b(mouse|mice|murine)\b'), ('Rat', r'\brats?\b'), ('Rabbit', r'\brabbits?\b')]
                    if re.search(pattern, str(text), re.I)}
        observed = set().union(*(known_species(profiles[i].get('species', '')) for i in dataset))
        if len(observed) > 1: fail('One method mixes known species')
        declared = known_species(scope['species'])
        if observed and declared != observed: fail('Method scope contradicts source species')
        if re.search(r'\b(?:human|patients?|volunteers?)\b', scope['species'], re.I):
            fail('Current method population must be nonhuman')
        if m['family'] in ('PD_INDEX', 'PD_TARGET'):
            for item in dataset:
                p = profiles[item]
                clue = p.get('title', '') + ' ' + p.get('species', '')
                if re.search(r'\b(?:E\.?\s*coli|Escherichia\s+coli)\b', clue, re.I):
                    fail('Explicit E. coli data are supporting material, not current K. pneumoniae PD datasets')
    for group in groups.values():
        if group['families'] & {'NCA', 'MODEL_BASED'} and 'MODEL_BASED' not in group['families']:
            fail('Animal PK planning must retain MODEL_BASED in every group; NCA is optional')
    if set(needs) != linked: fail('Requirements must belong to a planned method')
    primary = {i for i, p in profiles.items() if p.get('role') == 'PK_OBSERVATIONS'}
    covered = {i for m in plan['methods'] if m['family'] == 'MODEL_BASED' for i in m['dataset_ids']}
    exclusions = plan['pk_exclusions']
    excluded = unique([x['item_id'] for x in exclusions], 'PK exclusions')
    if not excluded <= primary or excluded & covered: fail('Invalid or already covered PK exclusion')
    for x in exclusions:
        d.evidence_check(x['evidence'], sources)
        if not x['reason'].strip(): fail('PK exclusion needs a scope reason')
        item = x['item_id']
        if not any(e['source'] in profiles[item]['notes'] for e in x['evidence']):
            fail('PK exclusion must cite that item original overview notes')
    if not primary <= covered | excluded: fail('Primary PK item omitted from MODEL_BASED planning and exclusions')
    return True


def materialize(raw, payload, sources, knowledge):
    d.validate_schema(raw, response_schema(payload))
    result = copy.deepcopy(raw)
    for need in result['requirements'] + result['pk_exclusions']:
        ids = need.pop('evidence_source_ids')
        if not unique(ids, 'evidence selectors') <= sources.keys(): fail('Unknown source selector')
        need['evidence'] = [{'source': key, 'quote': sources[key]} for key in ids]
    result.update(version=VERSION, policy=copy.deepcopy(POLICY), scientific_approval=False, can_enter_qc=False, fit_ready=False)
    validate_plan(result, payload, sources, knowledge)
    return result


def governed_request(payload, schema, model=MODEL):
    class Captured(Exception): pass
    private = sf.private_module()
    def capture(p):
        error = Captured(); error.request = d.governed_request(p); raise error
    private.governed_request = capture
    try: private.invoke(Path('.'), 'DR', payload, schema, model=model)
    except Captured as result: return result.request
    fail('Request capture reached provider')


def prepare(source_run, out, *, model=MODEL):
    source_run, out = Path(source_run).resolve(), Path(out).resolve()
    if source_run == out or source_run in out.parents or out in source_run.parents: fail('Use isolated output directory')
    if out.exists() and any(out.iterdir()): fail('Output already contains an attempt')
    manifest, verified = sf.verify_run(source_run)
    view = read_json(source_run/'source_view.json')
    if view.get('pending_item_ids'): fail('Source repairs pending')
    access = {a['item_id']: a for a in read_json(source_run/'permissions.json')['access']}
    if any(access.get(p['item_id'], {}).get('disposition') != 'REVIEW_DATA' for p in view['profiles']): fail('Unpermitted profile')
    for item in read_json(source_run/'inventory.json')['items']:
        for key in ('source', 'snapshot'):
            if item.get(key): check_ref(item[key])
    payload, schema, sources, knowledge = build_payload(verified['main'], view)
    request = governed_request(payload, schema, model)
    chars = len(json.dumps(request, ensure_ascii=False))
    if chars > d.REQUEST_BUDGET: fail(f'Request exceeds 700000 characters: {chars}; no content truncated')
    bindings = {name.removesuffix('.json'): file_ref(source_run/name) for name in ('manifest.json', 'inventory.json', 'permissions.json', 'source_view.json')}
    bindings.update(main=manifest['bindings']['main'], code=file_ref(__file__), library=file_ref(mp.LIBRARY_PATH), policy=file_ref(d.AGENT_FILES['DR']))
    for name, value in [('payload', payload), ('schema', schema), ('source_catalog', sources), ('method_context', knowledge),
                        ('request', request), ('bindings', bindings)]: write_json(out/(name+'.json'), value)
    write_json(out/'build.json', {'version': VERSION, 'request_chars': chars, 'model': model,
                                'new_model_calls': 0, 'source_body_transmitted': False})
    return request


def run(source_run, out, *, generator=None, model=MODEL):
    started = time.monotonic(); out = Path(out)
    request = prepare(source_run, out, model=model)
    payload, schema, sources, knowledge, bindings = [read_json(out/(n+'.json')) for n in
        ('payload', 'schema', 'source_catalog', 'method_context', 'bindings')]
    def check(raw):
        for ref in bindings.values(): check_ref(ref)
        materialize(raw, payload, sources, knowledge)
        return True
    sf.emit(out, 'STAGE_START', stage=VERSION, model=model, request_chars=len(json.dumps(request, ensure_ascii=False)))
    try:
        raw = d.invoke(out, 'DR', payload, schema, model=model, generator=generator, check=check)
        check(raw)
        write_json(out/'raw.json', raw)
        result = materialize(raw, payload, sources, knowledge)
        result['bindings'] = bindings
        result['provenance'] = {name+'_ref': file_ref(out/(name+'.json')) for name in
                               ('raw', 'request', 'payload', 'schema', 'source_catalog', 'method_context', 'bindings')}
        result['provenance'].update(model=model, evidence_derivation='HOST_EXACT_SOURCE_SELECTOR_MATERIALIZATION')
        staged = write_json(out/'staged/plan.json', result); staged.replace(out/'plan.json')
        verify_plan(out/'plan.json')
        sf.emit(out, 'STAGE_END', stage=VERSION, elapsed_seconds=time.monotonic()-started)
        return result
    except Exception as exc:
        sf.emit(out, 'STAGE_ERROR', stage=VERSION, elapsed_seconds=time.monotonic()-started, reason=str(exc)); raise


def verify_plan(plan_path):
    plan = read_json(plan_path)
    if plan.get('version') != VERSION: fail('Unknown planning version')
    for ref in plan['bindings'].values(): check_ref(ref)
    refs = plan['provenance']
    for key, ref in refs.items():
        if key.endswith('_ref'): check_ref(ref)
    loaded = {n: read_json(refs[n+'_ref']['path']) for n in ('raw', 'request', 'payload', 'schema', 'source_catalog', 'method_context', 'bindings')}
    if loaded['bindings'] != plan['bindings']: fail('Plan bindings changed')
    rebuilt = build_payload(read_json(plan['bindings']['main']['path']),
                            read_json(plan['bindings']['source_view']['path']), loaded['method_context'])
    for name, value in zip(('payload', 'schema', 'source_catalog', 'method_context'), rebuilt):
        if loaded[name] != value: fail('Planning input does not reconstruct from bound sources: '+name)
    if 'correction_ref' in refs:
        proof = read_json(refs['correction_ref']['path'])
        for reference in proof['parents'].values(): check_ref(reference)
        original = read_json(proof['parents']['raw']['path'])
        parent_request = read_json(proof['parents']['request']['path'])
        if original['request_sha256'] != parent_request['request_sha256'] or parent_request['request_sha256'] != digest(parent_request['payload']):
            fail('Correction parent raw/request binding changed')
        old_bindings = read_json(proof['parents']['bindings']['path'])
        if {k: v for k, v in old_bindings.items() if k != 'code'} != {k: v for k, v in plan['bindings'].items() if k != 'code'}:
            fail('Correction changed an original scientific input binding')
        cp, cs = correction_payload(original, loaded['payload'], loaded['source_catalog'], loaded['method_context'])
        if loaded['request'] != governed_request(cp, cs, refs['model']): fail('Correction request changed')
        candidate = apply_correction(original, loaded['raw'], loaded['payload'], loaded['source_catalog'], loaded['method_context'])
        if proof['candidate_sha256'] != digest(candidate): fail('Correction derivation changed')
    else:
        if loaded['request'] != governed_request(loaded['payload'], loaded['schema'], refs['model']): fail('Frozen request changed')
        candidate = loaded['raw']
    if loaded['raw']['request_sha256'] != loaded['request']['request_sha256']: fail('Raw response belongs to another request')
    replay = materialize(candidate, loaded['payload'], loaded['source_catalog'], loaded['method_context'])
    if replay != {k: v for k, v in plan.items() if k not in ('bindings', 'provenance')}: fail('Plan does not replay from raw response')
    return plan


CORRECTION_FIELDS = ('id', 'task_id', 'origin', 'analysis', 'method_profile_ids', 'conditions', 'rule_ids', 'evidence_source_ids')


def human_only_rules(payload):
    """Use explicit original species scope, never infer it from clinical-stage keywords."""
    return {r['id'] for r in payload['project_rules']
            if {str(s).strip().lower() for s in r.get('scope', {}).get('species', [])} == {'human'}}


def correction_payload(original, payload, sources, knowledge):
    """Authority/routing-only continuation; scientific requirement text remains immutable."""
    needs = {n['id']: n for n in original['requirements']}
    linked = {q for m in original['methods'] for q in m['requirement_ids']}
    orphans = sorted(set(needs) - linked)
    variants = []
    for variant in response_schema(payload)['properties']['requirements']['items']['anyOf']:
        update = obj(**{k: copy.deepcopy(variant['properties'][k]) for k in CORRECTION_FIELDS})
        explicit = variant['properties']['origin']['enum'] == ['PROJECT_EXPLICIT']
        ids = [n['id'] for n in needs.values() if not explicit or n['origin'] == 'PROJECT_EXPLICIT']
        if not ids: continue
        update['properties']['id'] = enum(*ids)
        variants.append(update)
    method_schema = copy.deepcopy(response_schema(payload)['properties']['methods']['items'])
    method_schema['properties']['family'] = enum('NCA', 'PD_INDEX', 'PD_TARGET')
    schema = obj(request_sha256=S, need_updates=arr({'anyOf': variants}, len(needs)),
        retired_requirement_ids=arr(enum(*orphans)) if orphans else {'type': 'array', 'items': S, 'maxItems': 0},
        method_links=arr(obj(id=enum(*[m['id'] for m in original['methods']]), requirement_ids=arr(enum(*needs), 1)), len(original['methods'])),
        additional_methods=arr(method_schema))
    rule_ids = {i for n in needs.values() for i in n['rule_ids']}
    rule_ids.update({'R003', 'R004', 'R013', 'R025', 'R026', 'R034', 'R035'})
    forbidden_rules = human_only_rules(payload)
    rule_ids -= forbidden_rules  # The original Rules remain unchanged in the bound main.
    rules = [copy.deepcopy(r) for r in payload['project_rules'] if r['id'] in rule_ids]
    indices = {i for i, r in enumerate(payload['project_rules']) if r['id'] in rule_ids}
    project_keys = {f'main:/rules/{i}/text' for i in indices}
    additions = [p for p in payload['data_profiles'] if p['item_id'] in {'F0004:S1:T24', 'F0004:S1:T25', 'F0004:S1:T26'}]
    note_ids = {x for p in additions for x in p['notes']}
    visible = {s: text for s, text in sources.items() if s.startswith(('method:', 'main:/objective',
               'main:/scientific_context/', 'main:/missing_information/')) or s in note_ids}
    allowed = set(visible) | project_keys
    for variant in schema['properties']['need_updates']['items']['anyOf']:
        e = variant['properties']['evidence_source_ids']['items']['enum']
        variant['properties']['evidence_source_ids']['items']['enum'] = [s for s in e if s in allowed]
        variant['properties']['rule_ids'] = arr(enum(*[r['id'] for r in rules]))
    usages = {q: [{'method_id': m['id'], 'family': m['family']} for m in original['methods']
                  if q in m['requirement_ids']] for q in needs}
    diagnostics = []
    for n in needs.values():
        if not set(n['method_profile_ids']) <= ROUTES[n['analysis']]:
            diagnostics.append({'need_id': n['id'], 'issue': 'METHOD_ANALYSIS_ROUTE',
                                'analysis': n['analysis'], 'profiles': n['method_profile_ids']})
        if n['analysis'] != 'SHARED' and n['task_id'] != ('ANIMAL_PK' if n['analysis'] in ('NCA', 'MODEL_BASED') else n['analysis']):
            diagnostics.append({'need_id': n['id'], 'issue': 'TASK_ANALYSIS_ROUTE'})
        wrong = [u for u in usages[n['id']] if n['analysis'] not in (u['family'], 'SHARED')]
        if wrong: diagnostics.append({'need_id': n['id'], 'issue': 'CROSS_FAMILY_USAGE', 'uses': wrong})
        if n['id'] in orphans: diagnostics.append({'need_id': n['id'], 'issue': 'ORPHAN_RETIRE_OR_LINK_REQUIRED'})
    return {'operation': VERSION+'_TARGETED_CORRECTION', 'policy': payload['policy'],
        'instructions': '''Correct only the provided authority/routing metadata. The original candidate is NON-EVIDENCE.
Its description, fields, phase, necessity and original method scopes/dataset assignments are locked.
Return one need_update per original need, including retired ones; return links for every original method.
analysis_routes and task_routes below are exact host constraints, not informal examples. Every retained
need must be linked by a method. Each orphan must be explicitly retired or legitimately linked; no
unreferenced need can remain. Use need_to_method_usages and contract_diagnostics to correct every row.
An original METHOD_CANDIDATE must remain METHOD_CANDIDATE (including a retired update); never promote
it to PROJECT_EXPLICIT or drop its method authority merely to satisfy the schema. Each candidate
needs all selected method citations, actual project context and applicability conditions.
Across every family, methods sharing group_id must have IDENTICAL study/species/matrix/record_level.
Different independent Kp104 panels should use distinct group IDs when their scopes differ; do not
erase source differences to make scopes equal. Truly shared needs use SHARED; otherwise remove the
inapplicable link while retaining its condition and linking/retiring the need legitimately.
PROJECT_EXPLICIT has actual project authority and NO method: evidence. METHOD_CANDIDATE requires all
linked method sources plus actual project authority and applicability conditions. Never turn a library
condition into a project obligation. Rules explicitly scoped only to human are not direct authority
for current nonhuman planning; the forbidden_current_authority_rule_ids list comes from original scope.species.
Use SHARED for genuine cross-family inputs/definitions; do not attach NCA-only needs to MODEL_BASED.
The listed orphan IDs may be retired (original evidence remains in history), or properly linked to a
retained conditional method. Do not drop any other need or scientific content. Static Kp time-kill may
remain a conditional candidate under R013: conditions must state index/target interpretation still
requires checking; no adequacy verdict or best-index selection occurs here.
Add Kp104 T24/T25/T26 PD_INDEX candidates using their supplied original notes. These are independent
panels: no inferred shared IDs, rank pairing or common matched records. A group may describe them
together only without assuming joins. Optional new PD_TARGET candidates may share definitions.
Optional NCA methods must use EXACT scope and dataset_ids of an existing MODEL_BASED group.
No measurements, requirement descriptions or fields may be rewritten; no new formal requirements.
Existing project rule objects are unchanged, with original indices in project_rule_indices. Select only
the provided evidence IDs. Return metadata corrections, not a complete re-extracted plan.''',
        'original_candidate_NON_EVIDENCE': original, 'retirable_orphan_ids': orphans,
        'analysis_routes': {k: sorted(v) for k, v in ROUTES.items()},
        'task_routes': {k: (list(TASKS) if k == 'SHARED' else ['ANIMAL_PK' if k in ('NCA', 'MODEL_BASED') else k]) for k in ROUTES},
        'group_constraints': {'same_group_scope': 'EXACT_OBJECT_EQUALITY', 'scope_keys': ['study', 'species', 'matrix', 'record_level'],
                              'animal_group_required_family': 'MODEL_BASED', 'NCA': 'OPTIONAL'},
        'need_to_method_usages': usages, 'contract_diagnostics': diagnostics,
        'original_method_candidate_ids_locked': [n['id'] for n in needs.values() if n['origin'] == 'METHOD_CANDIDATE'],
        'forbidden_current_authority_rule_ids': sorted(forbidden_rules),
        'project_rules': rules, 'project_rule_indices': {r['id']: i for i, r in enumerate(payload['project_rules']) if i in indices},
        'authoritative_sources': visible, 'additional_candidate_overviews': additions,
        'allowed_evidence_source_ids': sorted(allowed), 'method_knowledge_authority': knowledge['authority'],
        'scientific_approval': False}, schema


def apply_correction(original, correction, payload, sources, knowledge):
    _, schema = correction_payload(original, payload, sources, knowledge)
    d.validate_schema(correction, schema)
    d.exact([n['id'] for n in correction['need_updates']], [n['id'] for n in original['requirements']], 'Correction need metadata')
    d.exact([m['id'] for m in correction['method_links']], [m['id'] for m in original['methods']], 'Correction method links')
    retired = unique(correction['retired_requirement_ids'], 'retired requirements')
    result = copy.deepcopy(original); result['request_sha256'] = correction['request_sha256']
    updates = {n['id']: n for n in correction['need_updates']}
    forbidden_rules = human_only_rules(payload)
    forbidden_sources = {f'main:/rules/{i}/text' for i, r in enumerate(payload['project_rules']) if r['id'] in forbidden_rules}
    for old in original['requirements']:
        new = updates[old['id']]
        if old['origin'] == 'METHOD_CANDIDATE' and new['origin'] != old['origin']:
            fail('Original METHOD_CANDIDATE authority cannot be promoted')
        if forbidden_rules & set(new['rule_ids']) or forbidden_sources & set(new['evidence_source_ids']):
            fail('Human-only scoped Rules are not direct current nonhuman authority')
    result['requirements'] = [{**n, **updates[n['id']]} for n in result['requirements'] if n['id'] not in retired]
    links = {m['id']: m['requirement_ids'] for m in correction['method_links']}
    for m in result['methods']: m['requirement_ids'] = links[m['id']]
    expected_new = {'F0004:S1:T24', 'F0004:S1:T25', 'F0004:S1:T26'} & {p['item_id'] for p in payload['data_profiles']}
    for m in correction['additional_methods']:
        if m['family'] == 'NCA':
            if not any(old['family'] == 'MODEL_BASED' and m['group_id'] == old['group_id']
                       and m['scope'] == old['scope'] and m['dataset_ids'] == old['dataset_ids']
                       and m['supporting_item_ids'] == old['supporting_item_ids'] for old in original['methods']):
                fail('New NCA must preserve an existing MODEL_BASED scope and sources')
        elif not set(m['dataset_ids']) <= expected_new:
            fail('New PD candidates are limited to the explicitly omitted Kp104 panels')
        result['methods'].append(copy.deepcopy(m))
    actual = {i for m in result['methods'] if m['family'] == 'PD_INDEX' for i in m['dataset_ids']}
    if not expected_new <= actual: fail('Correction omitted an authorized Kp104 index panel')
    materialize(result, payload, sources, knowledge)
    return result


def prepare_correction(prior_run, out, *, model=MODEL):
    prior_run, out = Path(prior_run).resolve(), Path(out).resolve()
    if prior_run == out or prior_run in out.parents or out in prior_run.parents: fail('Use isolated correction output')
    if out.exists() and any(out.iterdir()): fail('Correction output already contains an attempt')
    old_bindings = read_json(prior_run/'bindings.json')
    for key, reference in old_bindings.items():
        if key != 'code': check_ref(reference)
    raw_paths = list(prior_run.glob('data_agents/audit/DR/*/response.json'))
    if len(raw_paths) != 1: fail('Select a prior attempt with exactly one original DR response')
    raw_path = raw_paths[0]; original = read_json(raw_path)
    old_request = read_json(raw_path.parent/'request.json')
    if original['request_sha256'] != old_request['request_sha256']: fail('Parent response request mismatch')
    if old_request['request_sha256'] != digest(old_request['payload']):
        fail('Parent request digest mismatch')
    if old_request != read_json(prior_run/'request.json'): fail('Parent audit/request mismatch')
    payload, schema, sources, knowledge = build_payload(read_json(old_bindings['main']['path']),
                                                       read_json(old_bindings['source_view']['path']))
    cp, cs = correction_payload(original, payload, sources, knowledge)
    request = governed_request(cp, cs, model); chars = len(json.dumps(request, ensure_ascii=False))
    if chars > d.REQUEST_BUDGET: fail('Correction exceeds transport budget; no truncation')
    bindings = {**old_bindings, 'code': file_ref(__file__)}
    parents = {'raw': file_ref(raw_path), 'request': file_ref(raw_path.parent/'request.json'),
               'bindings': file_ref(prior_run/'bindings.json')}
    for name, value in [('payload', payload), ('schema', schema), ('source_catalog', sources), ('method_context', knowledge),
        ('request', request), ('bindings', bindings), ('correction_payload', cp), ('correction_schema', cs), ('parents', parents)]:
        write_json(out/(name+'.json'), value)
    write_json(out/'build.json', {'version': VERSION, 'operation': 'TARGETED_CORRECTION', 'request_chars': chars,
                                'model': model, 'new_model_calls': 0})
    return request


def run_correction(prior_run, out, *, generator=None, model=MODEL):
    started = time.monotonic(); out = Path(out)
    request = prepare_correction(prior_run, out, model=model)
    names = ('payload', 'schema', 'source_catalog', 'method_context', 'bindings', 'parents', 'correction_payload', 'correction_schema')
    loaded = {n: read_json(out/(n+'.json')) for n in names}
    original = read_json(loaded['parents']['raw']['path'])
    def check(raw):
        for ref in list(loaded['bindings'].values()) + list(loaded['parents'].values()): check_ref(ref)
        apply_correction(original, raw, loaded['payload'], loaded['source_catalog'], loaded['method_context'])
        return True
    sf.emit(out, 'STAGE_START', stage=VERSION+'_TARGETED_CORRECTION', model=model,
            request_chars=len(json.dumps(request, ensure_ascii=False)))
    try:
        raw = d.invoke(out, 'DR', loaded['correction_payload'], loaded['correction_schema'], model=model, generator=generator, check=check)
        check(raw); write_json(out/'raw.json', raw)
        candidate = apply_correction(original, raw, loaded['payload'], loaded['source_catalog'], loaded['method_context'])
        write_json(out/'derived_candidate.json', candidate)
        write_json(out/'correction.json', {'parents': loaded['parents'], 'candidate_sha256': digest(candidate),
             'derivation': 'MODEL_METADATA_CORRECTION_FIXED_ORIGINAL_SCIENTIFIC_FIELDS',
             'retired_requirement_ids': raw['retired_requirement_ids']})
        result = materialize(candidate, loaded['payload'], loaded['source_catalog'], loaded['method_context'])
        result['bindings'] = loaded['bindings']
        result['provenance'] = {n+'_ref': file_ref(out/(n+'.json')) for n in
                               ('raw', 'request', 'payload', 'schema', 'source_catalog', 'method_context', 'bindings', 'correction')}
        result['provenance'].update(model=model, evidence_derivation='HOST_REPLAYED_MODEL_TARGETED_CORRECTION')
        staged = write_json(out/'staged/plan.json', result); staged.replace(out/'plan.json')
        verify_plan(out/'plan.json')
        sf.emit(out, 'STAGE_END', stage=VERSION+'_TARGETED_CORRECTION', elapsed_seconds=time.monotonic()-started)
        return result
    except Exception as exc:
        sf.emit(out, 'STAGE_ERROR', stage=VERSION+'_TARGETED_CORRECTION', elapsed_seconds=time.monotonic()-started, reason=str(exc)); raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-run', required=True); parser.add_argument('--out', required=True)
    parser.add_argument('--build-only', action='store_true'); args = parser.parse_args()
    result = prepare(args.source_run, args.out) if args.build_only else run(args.source_run, args.out)
    print(json.dumps({'status': 'BUILT' if args.build_only else 'PLANNED_NOT_ASSESSED', 'out': str(Path(args.out).resolve())}))


if __name__ == '__main__': main()
