"""Explicit, read-only loader for authored coverage/necessity policy resources.

Loading validates the authored bundle and its examples. It does not activate a
policy, inspect project data, invoke a model, or grant a scientific gate.
"""
import argparse
import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator

from .common import PipelineError, read_json, utcnow, write_json
from .adequacy import file_ref

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MANIFEST = REPOSITORY_ROOT / 'backend/rules/data/staged_assessment/manifest.1.0.0.json'
ROLES = {'coverage_policy', 'necessity_policy', 'references', 'schema'}


def fail(message):
    raise PipelineError('STAGED_ASSESSMENT_POLICY_INVALID', message)


def contained(base, relative):
    path = (base / relative).resolve()
    if not path.is_relative_to(base.resolve()):
        fail('A bundle reference leaves its declared root: ' + str(relative))
    return path


def checked_file(path, expected):
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        fail('File missing or hash changed: ' + str(path))


def _schema_check(value, schema, label):
    errors = sorted(Draft202012Validator(schema).iter_errors(value), key=lambda e: str(list(e.path)))
    if errors:
        error = errors[0]
        fail(label + ' schema error at ' + '/'.join(map(str, error.path)) + ': ' + error.message)


def _object_ids(value):
    result = set()
    if isinstance(value, dict):
        if isinstance(value.get('id'), str):
            result.add(value['id'])
        for child in value.values():
            result.update(_object_ids(child))
    elif isinstance(value, list):
        for child in value:
            result.update(_object_ids(child))
    return result


def load_bundle(manifest_path=DEFAULT_MANIFEST, *, repository_root=REPOSITORY_ROOT):
    manifest_path, repository_root = Path(manifest_path).resolve(), Path(repository_root).resolve()
    manifest = read_json(manifest_path)
    if (manifest.get('kind') != 'STAGED_ASSESSMENT_MANIFEST'
            or manifest.get('status') != 'AUTHORED_NOT_ACTIVATED'
            or manifest.get('runtime_integration') != 'NOT_CONNECTED'
            or manifest.get('source_path_base') != 'REPOSITORY_ROOT'
            or manifest.get('supersedes') != []):
        fail('This loader requires an authored, unactivated bundle that supersedes no original rules.')
    rows = manifest.get('files', [])
    if len(rows) != len(ROLES) or {r.get('role') for r in rows} != ROLES:
        fail('Manifest must contain every distinct bundle role exactly once.')
    bundle = {'manifest': manifest}
    for row in rows:
        path = contained(manifest_path.parent, row['path'])
        checked_file(path, row['file_sha256'])
        bundle[row['role']] = read_json(path)
    schema = bundle['schema']
    Draft202012Validator.check_schema(schema)
    for name in ('manifest', 'coverage_policy', 'necessity_policy', 'references'):
        _schema_check(bundle[name], schema, name)
    sources = bundle['references']['sources']
    source_ids = [s['id'] for s in sources]
    if len(source_ids) != len(set(source_ids)):
        fail('Duplicate reference source IDs.')
    for source in sources:
        path = contained(repository_root, source['path'])
        checked_file(path, source['file_sha256'])
        if path.suffix.lower() == '.json':
            if not set(source.get('ids', [])) <= _object_ids(read_json(path)):
                fail('A cited rule or method ID is absent from its bound source: ' + source['id'])
    allowed = set(source_ids)
    for name in ('coverage_policy', 'necessity_policy'):
        policy = bundle[name]
        if policy['authority'] != 'PROCESSING_POLICY_NOT_PROJECT_SCIENTIFIC_RULES':
            fail('A processing policy cannot replace scientific project rules.')
        if not set(policy['inherits'] + policy['source_refs']) <= allowed:
            fail('Unknown inherited/source reference in ' + name)
        ids = [r['id'] for r in policy['rules']]
        if len(ids) != len(set(ids)):
            fail('Duplicate policy rule IDs in ' + name)
        for rule in policy['rules']:
            if not rule['source_ids'] or not set(rule['source_ids']) <= allowed:
                fail('Unknown or absent rule provenance: ' + rule['id'])
    if bundle['references']['authority'] != 'REFERENCE_KNOWLEDGE_NOT_SOURCE_DATA':
        fail('Reference knowledge cannot be presented as observed source data.')
    for action in bundle['references']['action_templates']:
        for item in [action] + action['inputs']:
            if not item['source_ids'] or not set(item['source_ids']) <= allowed:
                fail('Unknown action/input reference: ' + action['action_id'])
    for example in bundle['references']['examples']:
        if example['hypothetical'] is not True or example['case_schema'] not in schema.get('$defs', {}):
            fail('Examples must be marked hypothetical and use an existing case schema.')
        case_schema = {'$schema': schema.get('$schema'), '$defs': schema['$defs'],
                       '$ref': '#/$defs/' + example['case_schema']}
        _schema_check(example['case'], case_schema, 'example: ' + example['title'])
    return bundle


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', default=str(DEFAULT_MANIFEST))
    parser.add_argument('--out', help='Optional new JSON verification record; existing files are preserved')
    args = parser.parse_args(argv)
    bundle = load_bundle(args.manifest)
    result = {'status': 'AUTHORING_AND_REFERENCE_CHECKS_PASSED_NOT_ACTIVATED', 'at': utcnow(),
              'manifest': file_ref(args.manifest),
              'coverage_rules': len(bundle['coverage_policy']['rules']),
              'necessity_rules': len(bundle['necessity_policy']['rules']),
              'action_templates': len(bundle['references']['action_templates']),
              'hypothetical_examples': len(bundle['references']['examples']),
              'runtime_connected': False, 'data_assessed': False, 'scientific_approval': False}
    if args.out:
        if Path(args.out).exists():
            fail('Verification output already exists; use a new path.')
        write_json(args.out, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
