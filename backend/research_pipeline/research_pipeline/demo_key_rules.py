"""Explicitly provisional key Rules for the user-authorized demo through Data.

One extraction call, source/shape checks, and a recorded automatic acceptance.
This path never manufactures an independent review PASS.
"""
import copy
import os
from pathlib import Path
from ctxcomp.io import digest
from ctxcomp.schemas import S, arr, enum, obj, validate_schema
from ctxcomp.retention import span_check
from .common import read_json, write_json, utcnow

VERSION = 'DEMO_KEY_RULES_1.0'


def enabled():
    if os.environ.get('PKPD_DEMO_PROVISIONAL_RULES') != '1':
        raise ValueError('Provisional Rules are enabled only in the explicitly configured demo.')


def request(value):
    from .project_rule_agent import SPAN
    steps = list(value['extraction_policy']['steps'])
    payload = {'stage': 'project_rules_extract', 'operation': 'DEMO_KEY_RULES',
        'instructions': 'Extract the key adopted project requirements for a provisional workflow demonstration. '
        'Keep complete conditions, prohibitions, timing and exceptions in text. Use exact project-source evidence. '
        'Assign only applicable used_in stages. Do not invent data, authority or approval. '
        'Do not duplicate the objective or descriptive facts. Return English JSON only. '
        'This is one extraction, with completeness and scientific refinement deferred to later review.',
        'objective': value['objective'], 'source_units': value['source_units'],
        'source_permissions': value['source_permissions'], 'steps': value['extraction_policy']['steps'],
        'schema': obj(request_sha256=S, rules=arr(obj(id=S, text=S,
            used_in=arr(enum(*steps), 1), evidence=arr(SPAN, 1)), 1))}
    return {'request_sha256': digest(payload), 'payload': payload}


def validate(response, value):
    req = request(value)
    validate_schema(response, req['payload']['schema'])
    if response['request_sha256'] != req['request_sha256']:
        raise ValueError('Provisional Rules response belongs to different inputs.')
    authorized = {x['source_id'] for x in value['source_permissions'] if x['may_supply_project_authority']}
    ids = [r['id'] for r in response['rules']]
    if len(ids) != len(set(ids)) or not all(i.strip() for i in ids):
        raise ValueError('Provisional Rule IDs must be unique and nonempty.')
    for rule in response['rules']:
        if not rule['text'].strip() or not any(s['source_id'] in authorized for s in rule['evidence']):
            raise ValueError('Each provisional Rule needs text and admitted project authority.')
        for span in rule['evidence']:
            span_check(span, value['source_units'])


def extract(input_ref, output, model=None):
    enabled()
    from . import project_rule_agent as a
    value = a.validate_input(input_ref)
    output = Path(output)
    response = a._call(request(value), output/'extraction', model, None,
                       lambda x: validate(x, value), 'candidate.json')
    # Recheck all original bindings before accepting this exact response.
    a.validate_input(input_ref)
    candidate_ref = a.file_ref(output/'extraction/candidate.json')
    published = output/'published'
    acceptance = {'status': 'USER_AUTHORIZED_DEMO_ACCEPTANCE', 'at': utcnow(),
        'reviewer': 'USER_AUTHORIZED_DEMO_ACCEPTANCE', 'candidate_ref': candidate_ref,
        'scope': 'THROUGH_DATA_ONLY', 'independent_model_review': False,
        'independent_human_review': False, 'scientific_results_accepted': False,
        'rationale': 'User requested key Rules extraction and automatic continuation for the demo; content refinement is deferred.'}
    review_ref = a.file_ref(write_json(published/'acceptance.json', acceptance))
    audit_ref = a.file_ref(write_json(published/'rule_audit.json', {
        'input_ref': input_ref, 'candidate_ref': candidate_ref,
        'checks': ['SCHEMA', 'REQUEST_IDENTITY', 'SOURCE_QUOTES', 'PROJECT_AUTHORITY', 'INPUT_HASHES'],
        'semantic_completeness': 'DEFERRED', 'scientific_results_accepted': False}))
    pack = {'schema_version': VERSION, 'status': 'DEMO_PROVISIONAL_RULES',
        'rules': response['rules'], 'main_file': 'main.json', 'base_main_ref': value['base_main_ref'],
        'input_ref': input_ref, 'candidate_ref': candidate_ref, 'review_ref': review_ref,
        'audit_ref': audit_ref, 'scientific_results_accepted': False}
    pack_ref = a.file_ref(write_json(published/'project_rules.json', pack))
    main = copy.deepcopy(read_json(value['base_main_ref']['path']))
    main['project_rules_ref'] = pack_ref
    main_ref = a.file_ref(write_json(published/'main.json', main))
    write_json(published/'report.json', {'status': 'DEMO_PROVISIONAL_RULES',
        'handoff_published': True, 'rule_count': len(response['rules']),
        'project_rules_ref': pack_ref, 'main_ref': main_ref, 'review_ref': review_ref,
        'independent_model_review': False, 'scientific_results_accepted': False})
    verify(pack_ref)
    return pack_ref


def verify(pack_ref):
    enabled()
    from . import project_rule_agent as a
    a.check_ref(pack_ref)
    pack = read_json(pack_ref['path'])
    if pack.get('schema_version') != VERSION or pack.get('status') != 'DEMO_PROVISIONAL_RULES':
        raise ValueError('Not a provisional demo Rules pack.')
    value = a.validate_input(pack['input_ref'])
    for key in ('candidate_ref', 'review_ref', 'audit_ref', 'base_main_ref'):
        a.check_ref(pack[key])
    response = read_json(pack['candidate_ref']['path'])
    validate(response, value)
    accepted = read_json(pack['review_ref']['path'])
    if (accepted.get('status') != 'USER_AUTHORIZED_DEMO_ACCEPTANCE'
            or accepted.get('scope') != 'THROUGH_DATA_ONLY'
            or accepted.get('candidate_ref') != pack['candidate_ref']
            or accepted.get('independent_model_review') is not False
            or accepted.get('independent_human_review') is not False
            or accepted.get('scientific_results_accepted') is not False
            or pack.get('scientific_results_accepted') is not False
            or pack['rules'] != response['rules'] or pack['base_main_ref'] != value['base_main_ref']):
        raise ValueError('Provisional Rules acceptance or contents changed.')
    main_ref = a.file_ref(Path(pack_ref['path']).parent/'main.json')
    expected = copy.deepcopy(read_json(value['base_main_ref']['path']))
    expected['project_rules_ref'] = pack_ref
    if read_json(main_ref['path']) != expected:
        raise ValueError('Provisional Rules belong to a different Context.')
    return {**pack, 'main_ref': main_ref}


def project(pack_ref, target):
    pack = verify(pack_ref)
    # Data requirements inspect future-stage obligations without executing
    # those stages. Execution limits are enforced by the demo API/runner.
    steps = read_json(pack['input_ref']['path'])['extraction_policy']['steps']
    if target not in steps:
        raise ValueError('Unknown Rules projection target.')
    selected = [{**copy.deepcopy(r), 'text': r['id']+': '+r['text'],
        'context_path': f'/rules/{i}', 'project_rules_ref': pack_ref,
        'projection_version': VERSION} for i, r in enumerate(pack['rules']) if target in r['used_in']]
    return {'version': VERSION, 'target': target, 'rules': selected, 'unresolved': [],
        'audit': [], 'project_rules_ref': pack_ref, 'method': 'USER_AUTHORIZED_PROVISIONAL_DEMO',
        'execution_scope': 'THROUGH_DATA_ONLY', 'scientific_approval': False,
        'source_rule_count': len(pack['rules']), 'selected_rule_count': len(selected)}
