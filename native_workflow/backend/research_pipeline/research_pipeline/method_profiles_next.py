"""Opt-in PD target/PTA input knowledge; historical method_profiles stays frozen.

New callers explicitly import this module. No global routing, model invocation,
calculation, source access or migration of saved contexts occurs here.
"""
import argparse
import copy
import json
from pathlib import Path

from ctxcomp.governance import load_governance
from ctxcomp.io import digest
from ctxcomp.schemas import S, obj, validate_schema
from . import method_profiles as legacy
from .adequacy import file_ref
from .common import RULES, read_json, write_json

VERSION = '1.1.0-draft.1'
LIBRARY_PATH = RULES / f'data/pkpd_method_profiles.{VERSION}.json'
DATA_SCOPE_INSTRUCTIONS = legacy.DATA_SCOPE_INSTRUCTIONS
reject = legacy.reject
requirement_profile_ids = legacy.requirement_profile_ids

# Extend a copy: importing this module must not mutate the historical schema.
LIBRARY_SCHEMA = copy.deepcopy(legacy.LIBRARY_SCHEMA)
LIBRARY_SCHEMA['properties']['version'] = {'const': VERSION}
for variant in LIBRARY_SCHEMA['properties']['profiles']['items']['anyOf']:
    variant['properties']['family']['enum'].append('PTA')
LIBRARY_SCHEMA['properties'].update(
    lineage=obj(path={'const': 'data/pkpd_method_profiles.json'},
                version={'const': '1.0.0-draft.15'},
                file_sha256={'const': 'f89b56e86024a0c60cd7ae7279b0964cae5d6a056b11f2e08143c627dc6d25b4'}),
    planning_conventions=obj(scope=S, gap_kinds=obj(
        DESIGN_DEFINITION=S, EXISTING_SOURCE_REVIEW=S, PLANNED_MODEL_OUTPUT=S, NEW_DATA=S)))
LIBRARY_SCHEMA['required'] += ['lineage', 'planning_conventions']


def validate_library(value):
    validate_schema(value, LIBRARY_SCHEMA)
    for field in ('profiles', 'sources'):
        ids = [entry['id'] for entry in value[field]]
        if len(ids) != len(set(ids)):
            reject('Duplicate IDs in method library ' + field)
    source_ids = {source['id'] for source in value['sources']}
    for profile in value['profiles']:
        if not set(profile['source_ids']) <= source_ids:
            reject('Unknown source for ' + profile['id'])
        if profile.get('assessment_scope') != 'DATA_REQUIREMENTS_ONLY' or 'condition_triggers' not in profile:
            reject('The opt-in menu contains data requirements with condition triggers only.')
        for kind, triggers in profile['condition_triggers'].items():
            if len(triggers) != len(profile[kind]):
                reject(f'Every {kind} entry of {profile["id"]} needs exactly one trigger.')
            for trigger in triggers:
                for field, values in trigger['labels'].items():
                    allowed = set(legacy.LABEL_CATEGORIES.get(field, ())) - legacy.UNDECIDED_LABELS
                    if not values or not set(values) <= allowed:
                        reject(f'Invalid trigger label {field} for {profile["id"]}')
    return value


def load_library():
    return validate_library(read_json(LIBRARY_PATH))


def planning_context():
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


def scoped_context(context, profile_ids):
    library = check_context(context)
    requested = set(profile_ids)
    profiles = [profile for profile in library['profiles'] if profile['id'] in requested]
    if requested != {profile['id'] for profile in profiles}:
        reject('Unknown method profile requested; no silent omission is allowed.')
    source_ids = {source for profile in profiles for source in profile['source_ids']}
    return copy.deepcopy({
        'library_version': library['version'], 'library_sha256': context['library_sha256'],
        'general_rules_sha256': context['general_rules_sha256'],
        'status': library['status'], 'use': library['use'],
        'interpretation': library['interpretation'], 'lineage': library['lineage'],
        'planning_conventions': library['planning_conventions'], 'profiles': profiles,
        'sources': [source for source in library['sources'] if source['id'] in source_ids],
        'authority': context['authority'], 'scientific_release': False,
    })


def evidence_sources(context):
    """Build method:MPxxx citation sources from the verified full frozen context."""
    return {'method:' + profile['id']: json.dumps(profile, ensure_ascii=False)
            for profile in check_context(context)['profiles']}


def validate_requirements(requirements, context):
    """The same evidence/authority contract as legacy, against this version's IDs."""
    known = {profile['id'] for profile in check_context(context)['profiles']}
    for need in requirements:
        ids = need['method_profile_ids']
        if len(ids) != len(set(ids)) or not set(ids) <= known:
            reject('Invalid method references for ' + need['id'])
        citations = {span['source'].removeprefix('method:') for span in need['evidence']
                     if span['source'].startswith('method:')}
        project_evidence = any(span['source'].startswith(('main:', 'rule:')) for span in need['evidence'])
        if not citations <= set(ids):
            reject('Unlinked method evidence for ' + need['id'])
        if need['origin'] == 'METHOD_CANDIDATE':
            if not ids or citations != set(ids) or not project_evidence or not need['conditions']:
                reject('Method-derived needs require method evidence, objective context and applicability conditions: ' + need['id'])
            if need['kind'] == 'SOURCE_PERMISSION':
                reject('A method profile cannot authorize source access.')
        elif need['origin'] == 'PROJECT_EXPLICIT':
            if citations or not project_evidence:
                reject('An explicit project requirement needs project evidence, not method-library authority: ' + need['id'])
        else:
            reject('Unknown requirement origin for ' + need['id'])


def export_context(profile_ids, out):
    """Save one compact, loadable frozen context and return its file manifest.

    The selected library gets its own digest; full_library_sha256 preserves the
    originating menu identity without duplicating every unselected profile.
    """
    context = planning_context()
    packet = scoped_context(context, profile_ids)
    if not packet['profiles']:
        reject('Export requires at least one method profile.')
    library = copy.deepcopy(context['library'])
    library.update(profiles=packet['profiles'], sources=packet['sources'])
    selected = {**context, 'library': library, 'library_sha256': digest(library),
                'full_library_sha256': context['library_sha256']}
    check_context(selected)
    path = Path(out).resolve()
    # This entry creates a new planning artifact, never rewrites an old run.
    if path.exists():
        reject('Output already exists; choose a new context artifact path.')
    write_json(path, selected)
    check_context(read_json(path))
    return {**file_ref(path), 'library_version': VERSION,
            'library_sha256': selected['library_sha256'],
            'full_library_sha256': context['library_sha256'],
            'profile_ids': [profile['id'] for profile in packet['profiles']],
            'scientific_release': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profiles', nargs='+', required=True)
    parser.add_argument('--out', required=True, help='New frozen context JSON path')
    args = parser.parse_args()
    print(json.dumps(export_context(args.profiles, args.out), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
