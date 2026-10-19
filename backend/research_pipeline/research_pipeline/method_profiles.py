"""Versioned PK/PD planning knowledge, separate from G policy and project rules.

This module validates and scopes knowledge packets. It performs no PK calculation
and never treats a draft profile as a release gate or permission grant.
"""
import copy
import json

from ctxcomp.governance import load_governance
from ctxcomp.io import digest
from ctxcomp.schemas import S, arr, enum, obj, validate_schema
from .common import RULES, PipelineError, read_json

LIBRARY_PATH = RULES / 'data/pkpd_method_profiles.json'
DATA_SCOPE_INSTRUCTIONS = (
    'This step assesses data requirements only: requirement, matched source evidence, input availability, '
    'coverage or definition gaps, affected task/endpoint, required phase and next action. '
    'For profiles marked DATA_REQUIREMENTS_ONLY, target_endpoints describe the later scientific objective; '
    'outputs describe this input assessment. Do not select or test integration, terminal-regression, '
    'compartmental or residual-error methods, and do not require their numerical results or diagnostics here. '
    'Legacy profile analysis/evaluation checks are later-stage reference, not current input acceptance criteria. '
    'If deciding adequacy requires calculation or fitting, keep that question unresolved for the downstream module. '
    'AVAILABLE_CANDIDATE means source-backed input availability only. For partially met requirements use '
    'UNRESOLVED and state both available evidence and missing material; MISSING means the required input '
    'was not located in the permitted reviewed sources; DEFERRED retains a documented later-stage need. '
    'None of these statuses qualifies a result, model or species for human extrapolation.'
)
LEGACY_PROFILE = obj(
    id=S, name=S, family=enum('NCA', 'COMPARTMENTAL_PK', 'TRANSLATION', 'IN_VITRO_PK', 'PKPD'),
    outputs=arr(S, 1), applies_when=S, required_inputs=arr(S, 1),
    conditional_inputs=arr(), acceptable_alternatives=arr(), preflight_checks=arr(S, 1),
    post_analysis_checks=arr(S, 1), missing_effect=S, not_established=arr(S, 1),
    needed_at=S, source_ids=arr(S, 1))
DATA_PROFILE = obj(
    id=S, name=S, family=enum('NCA', 'COMPARTMENTAL_PK', 'TRANSLATION', 'IN_VITRO_PK', 'PKPD'),
    assessment_scope={'const': 'DATA_REQUIREMENTS_ONLY'}, target_endpoints=arr(S, 1),
    outputs=arr(S, 1), applies_when=S, required_inputs=arr(S, 1),
    conditional_inputs=arr(), acceptable_alternatives=arr(), data_checks=arr(S, 1),
    missing_effect=S, not_established=arr(S, 1),
    needed_at={'const': 'DATA_REQUIREMENTS_ASSESSMENT'}, source_ids=arr(S, 1))
# Categorical DC labels that condition triggers may test. NOT_FOUND and MIXED
# never decide applicability; they leave the condition for independent review.
LABEL_CATEGORIES = {
    'role': ('PK_OBSERVATIONS', 'PD_OBSERVATIONS', 'DOSING', 'MIC', 'BINDING', 'IN_VITRO_TIME_KILL',
             'URINE_EXCRETION', 'IN_VITRO_CLEARANCE', 'REPORTED_PARAMETERS', 'ANIMAL_CHARACTERISTICS',
             'MODEL_CATALOG', 'SUPPORTING_EVIDENCE', 'SOURCE_TABLE'),
    'route_category': ('IV_BOLUS', 'IV_INFUSION', 'EXTRAVASCULAR', 'NOT_APPLICABLE', 'MIXED', 'NOT_FOUND'),
    'matrix_category': ('PLASMA_SERUM_BLOOD', 'URINE', 'INFECTION_SITE', 'OTHER_TISSUE', 'IN_VITRO_SYSTEM',
                        'NOT_APPLICABLE', 'MIXED', 'NOT_FOUND'),
    'record_category': ('INDIVIDUAL', 'GROUP_SUMMARY', 'POOLED', 'REPORTED_PARAMETER',
                        'NOT_APPLICABLE', 'MIXED', 'NOT_FOUND'),
    'observation_source': ('SOURCE_VALUES', 'DIGITIZED_FROM_FIGURE', 'NOT_APPLICABLE', 'MIXED', 'NOT_FOUND'),
}
UNDECIDED_LABELS = {'NOT_FOUND', 'MIXED'}
# labels: every listed field must hold one of its values (empty = every linked dataset).
# review: NONE applies on the label match alone; OBJECTIVE or DATA leaves applicability to DC-review.
TRIGGER = obj(labels={'type': 'object', 'additionalProperties': arr(S, 1)},
              review=enum('NONE', 'OBJECTIVE', 'DATA'))
TRIGGERED_PROFILE = copy.deepcopy(DATA_PROFILE)
TRIGGERED_PROFILE['properties'].update(
    data_roles=arr(enum(*LABEL_CATEGORIES['role']), 1),
    condition_triggers=obj(conditional_inputs=arr(TRIGGER), data_checks=arr(TRIGGER)))
TRIGGERED_PROFILE['required'] += ['data_roles', 'condition_triggers']
# Keep frozen legacy snapshots readable without reinjecting their contents into
# the current data-only menu. Later-stage profiles remain readable in snapshots.
PROFILE = {'anyOf': [TRIGGERED_PROFILE, DATA_PROFILE, LEGACY_PROFILE]}
SOURCE = obj(id=S, title=S, url=S, locator=S, type=S, checked_on=S, supports=S)
LIBRARY_SCHEMA = obj(
    version=S, status=enum('DRAFT_PENDING_SCIENTIFIC_REVIEW'),
    use=enum('CANDIDATE_REQUIREMENT_PLANNING_ONLY'),
    general_rules=obj(provider=enum('ctxcomp.governance.load_governance'),
                      namespace=enum('G'), duplicate_rule_text={'const': False}),
    interpretation=S, sources=arr(SOURCE, 1), profiles=arr(PROFILE, 1))


def reject(message):
    raise PipelineError('METHOD_PROFILE_INVALID', message)


def validate_library(value):
    validate_schema(value, LIBRARY_SCHEMA)
    for field in ('profiles', 'sources'):
        ids = [x['id'] for x in value[field]]
        if len(ids) != len(set(ids)):
            reject('Duplicate IDs in method library ' + field)
    source_ids = {s['id'] for s in value['sources']}
    for profile in value['profiles']:
        if not set(profile['source_ids']) <= source_ids:
            reject('Unknown source for ' + profile['id'])
        for kind, triggers in profile.get('condition_triggers', {}).items():
            if len(triggers) != len(profile[kind]):
                reject(f'Every {kind} entry of {profile["id"]} needs exactly one trigger.')
            for trigger in triggers:
                for field, values in trigger['labels'].items():
                    allowed = set(LABEL_CATEGORIES.get(field, ())) - UNDECIDED_LABELS
                    if not values or not set(values) <= allowed:
                        reject(f'Invalid trigger label {field} for {profile["id"]}')
    return value


def load_library():
    library = validate_library(read_json(LIBRARY_PATH))
    if any('condition_triggers' not in p for p in library['profiles']):
        reject('The current method menu needs condition triggers for every profile.')
    return library


def planning_context():
    """The global requirements planner needs the candidate menu, not measurements."""
    library = load_library()
    return {
        'library_sha256': digest(library),
        'general_rules_sha256': digest(load_governance()),
        'library': library,
        'authority': 'CANDIDATE_METHOD_KNOWLEDGE_NOT_PROJECT_RULES',
        'scientific_release': False,
    }


def check_context(context):
    library = validate_library(context['library'])
    if context['library_sha256'] != digest(library):
        reject('Method library content does not match its frozen digest.')
    if context['general_rules_sha256'] != digest(load_governance()):
        reject('General rules changed after requirements planning; obtain a new reviewed requirements artifact.')
    if context['authority'] != 'CANDIDATE_METHOD_KNOWLEDGE_NOT_PROJECT_RULES' or context['scientific_release'] is not False:
        reject('Method knowledge cannot grant project authority or scientific release.')
    return library


def evidence_sources(context):
    return {'method:' + p['id']: json.dumps(p, ensure_ascii=False)
            for p in check_context(context)['profiles']}


def scoped_context(context, profile_ids):
    library = check_context(context)
    requested = set(profile_ids)
    profiles = [p for p in library['profiles'] if p['id'] in requested]
    if requested != {p['id'] for p in profiles}:
        reject('Unknown method profile requested; no silent omission is allowed.')
    source_ids = {s for p in profiles for s in p['source_ids']}
    return copy.deepcopy({
        'library_version': library['version'], 'library_sha256': context['library_sha256'],
        'general_rules_sha256': context['general_rules_sha256'],
        'status': library['status'], 'use': library['use'],
        'interpretation': library['interpretation'], 'profiles': profiles,
        'sources': [s for s in library['sources'] if s['id'] in source_ids],
        'authority': context['authority'], 'scientific_release': False,
    })


def validate_requirements(requirements, context):
    known = {p['id'] for p in check_context(context)['profiles']}
    for need in requirements:
        ids = need['method_profile_ids']
        if len(ids) != len(set(ids)) or not set(ids) <= known:
            reject('Invalid method references for ' + need['id'])
        method_citations = {e['source'].removeprefix('method:') for e in need['evidence']
                            if e['source'].startswith('method:')}
        project_evidence = any(e['source'].startswith(('main:', 'rule:')) for e in need['evidence'])
        if not method_citations <= set(ids):
            reject('Unlinked method evidence for ' + need['id'])
        if need['origin'] == 'METHOD_CANDIDATE':
            if not ids or method_citations != set(ids) or not project_evidence or not need['conditions']:
                reject('Method-derived needs require method evidence, objective context and applicability conditions: ' + need['id'])
            if need['kind'] == 'SOURCE_PERMISSION':
                reject('A method profile cannot authorize source access.')
        elif need['origin'] == 'PROJECT_EXPLICIT':
            if method_citations or not project_evidence:
                reject('An explicit project requirement needs project evidence, not method-library authority: ' + need['id'])
        else:
            reject('Unknown requirement origin for ' + need['id'])


def requirement_profile_ids(requirements):
    return sorted({p for n in requirements for p in n.get('method_profile_ids', [])})


def label_roles(label):
    return {label['role'], *label.get('additional_roles', [])} - UNDECIDED_LABELS


def applicability(trigger, label):
    basis = {field: label.get(field, 'NOT_FOUND') for field in trigger['labels']}
    state = {}
    for field, value in basis.items():
        if field == 'role':  # Any of the item's roles may carry the condition; MIXED leaves it open.
            hit = bool(label_roles(label) & set(trigger['labels']['role']))
            state[field] = 'MATCH' if hit else 'UNDECIDED' if value in UNDECIDED_LABELS else 'MISS'
        else:
            state[field] = 'UNDECIDED' if value in UNDECIDED_LABELS else 'MATCH' if value in trigger['labels'][field] else 'MISS'
    if 'MISS' in state.values():
        return 'NOT_APPLICABLE', basis
    if 'UNDECIDED' in state.values():
        return 'UNDETERMINED', basis
    return ('APPLIES' if trigger['review'] == 'NONE' else 'REVIEW_' + trigger['review']), basis


def condition_checklist(context, requirements, labels):
    """Map each labelled dataset onto the conditions of the profiles its requirements selected.

    Data choose which conditions of a selected profile apply; they never select a profile."""
    if context is None:
        return []
    profiles = {p['id']: p for p in check_context(context)['profiles']}
    rows = []
    for label in labels:
        linked = [n for n in requirements if n['id'] in label['requirement_ids']]
        for pid in requirement_profile_ids(linked):
            profile = profiles[pid]
            if 'condition_triggers' not in profile:
                continue  # Frozen snapshots before condition triggers stay readable.
            need_ids = sorted(n['id'] for n in linked if pid in n['method_profile_ids'])
            for kind, short in (('conditional_inputs', 'CI'), ('data_checks', 'DC')):
                for i, (text, trigger) in enumerate(zip(profile[kind], profile['condition_triggers'][kind]), 1):
                    status, basis = applicability(trigger, label)
                    rows.append({'id': f"{label['item_id']}:{pid}:{short}{i:02d}", 'item_id': label['item_id'],
                                 'profile_id': pid, 'requirement_ids': need_ids, 'condition': f'{kind}[{i - 1}]',
                                 'text': text, 'applicability': status, 'label_basis': basis})
    return rows


def unrequested_profiles(context, labels):
    """Datasets no requirement uses, with the profiles whose data roles they fit (for human review only)."""
    if context is None:
        return []
    profiles = check_context(context)['profiles']
    result = []
    for label in labels:
        fitting = [p['id'] for p in profiles if label_roles(label) & set(p.get('data_roles', []))]
        if fitting and not label['requirement_ids']:
            result.append({'item_id': label['item_id'], 'role': label['role'], 'profile_ids': fitting})
    return result
