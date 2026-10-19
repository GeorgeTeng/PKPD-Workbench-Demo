"""Current Coverage contract; immutable v1 remains the historical replay reader."""
import copy
import json
import re
from pathlib import Path
from openpyxl.utils.cell import coordinate_to_tuple, get_column_letter
from ctxcomp.schemas import S, TEXT, arr, obj, enum, validate_schema
from . import data_coverage_direct as old, data_direct_runtime as rt
from .common import read_json, write_json

VERSION = 'DIRECT_DR_COVERAGE_2.0'
KINDS = ('MEASUREMENT_RECORDS', 'REPORTED_VALUE', 'CONTEXT_ONLY', 'RELATIONSHIP', 'UNRESOLVED')
OBSERVATION_ROLES = {'PK_OBSERVATIONS','PD_OBSERVATIONS','MIC','BINDING','IN_VITRO_TIME_KILL','DOSING'}
INSTRUCTIONS = '''
For every field state support_kind: MEASUREMENT_RECORDS, REPORTED_VALUE,
CONTEXT_ONLY or UNRESOLVED. This describes the type of support actually established,
not an upgraded interpretation of it. For every relevant source_scopes entry give
its own status. A note-reported MIC is REPORTED_VALUE, never MEASUREMENT_RECORDS.
Measurement support requires a cited TABLE_BODY source fragment; headers, linked
notes and context documents cannot establish measurement records. TABLE_BODY is
only a location qualification, not proof of analyte, units or experimental identity.
Retain quantity, total/free basis and individual/aggregate distinctions from profiles.
For a SUPPORTED field every listed source scope must be SUPPORTED; a conflict in
any scope makes the field CONFLICT. Do not remove a contrary source to obtain PASS.
Use only relevant source scopes; do not expand a Cartesian source/requirement matrix.
For MEASUREMENT_RECORDS, measurement contains quantity, unit, basis and record_level
copied exactly from profiles (no synonyms or free/total conversion).
Each supported source scope gives its exact column_header and cites that column's
body. Unknown dimensions cannot establish measurement support. For other support
types measurement is null and column_header is empty. For RELATIONSHIP provide
relation_source_ids that explicitly document the link, not just its two endpoints.
The host verifies citation identity, not the scientific truth of relationship prose.
For all other types relation_source_ids is empty.
'''


def response_schema(requirements):
    schema = old.response_schema(requirements)
    field = schema['$defs']['field']
    field['properties']['support_kind'] = enum(*KINDS)
    field['required'].append('support_kind')
    field['properties']['measurement'] = {'anyOf':[obj(quantity=S, unit=S, basis=S, record_level=S), {'type':'null'}]}
    field['properties']['relation_source_ids'] = arr(S)
    field['required'] += ['measurement','relation_source_ids']
    scope = field['properties']['source_scopes']['items']
    scope['properties']['status'] = enum(*old.STATES)
    scope['required'].append('status')
    scope['properties']['column_header'] = TEXT
    scope['required'].append('column_header')
    return schema


def _inputs(plan_path, source_path, main_path):
    bindings, requirements, catalog, wire = old._inputs(plan_path, source_path, main_path)
    bindings['coverage_contract'] = rt.file_ref(__file__)
    inventory_ref = read_json(plan_path).get('bindings', {}).get('inventory')
    if not inventory_ref:
        rt.fail('Scoped Coverage requires the frozen source inventory')
    bindings['inventory'] = inventory_ref
    rt.verify_refs(bindings)
    inventory = read_json(inventory_ref['path'])
    if inventory.get('main') != bindings['main']:
        rt.fail('Coverage inventory belongs to a different main')
    items = {i['id']: i for i in inventory['items']}
    profiles = {p['item_id']: p for p in wire['profiles']}
    for item_id in profiles:
        for key in ('source','snapshot'):
            if key in items.get(item_id, {}):
                bindings[item_id+':'+key] = items[item_id][key]
    rt.verify_refs(bindings)
    for sid, entry in catalog.items():
        item = items.get(entry['item_id'], {})
        role = 'CONTEXT_ONLY'
        if item.get('kind') == 'TABLE' and profiles[entry['item_id']].get('role') in OBSERVATION_ROLES:
            region = item.get('region', {})
            try:
                coordinate = sid[len(entry['item_id'])+1:]
                if not re.fullmatch(r'[A-Z]+[1-9][0-9]*', coordinate):
                    raise ValueError('Not an A1 cell reference')
                row, column = coordinate_to_tuple(coordinate)
                if (region['header_row'] < row <= region['end_row']
                        and region['left'] <= column <= region['right']):
                    role = 'TABLE_BODY'
            except (ValueError, KeyError):
                pass
        entry['evidence_role'] = role
        if role == 'TABLE_BODY':
            header_id = entry['item_id']+':'+get_column_letter(column)+str(region['header_row'])
            header = catalog.get(header_id, {}).get('quote')
            profile = profiles[entry['item_id']]
            columns = [c for c in profile.get('columns', []) if c.get('header') == header]
            if len(columns) == 1:
                col = columns[0]
                entry['column_header'] = header
                entry['measurement'] = {'quantity':col.get('meaning'), 'unit':col.get('unit'),
                    'basis':profile.get('exposure_basis'), 'record_level':profile.get('record_level')}
    wire.update(instructions=wire['instructions']+INSTRUCTIONS,
                source_regions={item_id:{'kind':items.get(item_id,{}).get('kind','UNKNOWN'),
                    'table_body_region':items.get(item_id,{}).get('region')}
                    for item_id in profiles})
    rt.verify_refs(bindings)
    return bindings, requirements, catalog, wire


def validate(raw, requirements, catalog):
    validate_schema(raw, response_schema(requirements))
    projected = copy.deepcopy(raw)
    for rid, check in raw['checks'].items():
        for name, field in check['fields'].items():
            scopes = field['source_scopes']
            statuses = [s['status'] for s in scopes]
            if 'NOT_APPLICABLE' in statuses and field['status'] != 'NOT_APPLICABLE':
                rt.fail('Source applicability requires the exact original field condition')
            if 'CONFLICT' in statuses and field['status'] != 'CONFLICT':
                rt.fail('Field hides a conflicting source scope')
            if field['status'] in {'SUPPORTED', 'NOT_APPLICABLE'}:
                if not statuses or any(s != field['status'] for s in statuses):
                    rt.fail('Field support disagrees with its source scopes')
                if field['support_kind'] == 'UNRESOLVED':
                    rt.fail('Supported field has unresolved evidence type')
            if field['support_kind'] == 'MEASUREMENT_RECORDS':
                if field['measurement'] is None:
                    rt.fail('Measurement claim needs explicit dimensions')
                if field['status'] == 'SUPPORTED' and any(v.strip().upper() in
                        {'UNKNOWN','NOT_FOUND','NOT_REPORTED','NOT_SPECIFIED','UNRESOLVED'}
                        for v in field['measurement'].values()):
                    rt.fail('Unknown measurement dimensions cannot establish support')
                for scope in scopes:
                    if scope['status'] == 'SUPPORTED' and not any(
                            catalog.get(sid, {}).get('evidence_role') == 'TABLE_BODY'
                            and catalog[sid].get('column_header') == scope['column_header']
                            and catalog[sid].get('measurement') == field['measurement']
                            for sid in scope['source_ids']):
                        rt.fail('Measurement support requires matching table body evidence and dimensions, not context or notes')
            elif field['measurement'] is not None or any(s['column_header'] for s in scopes):
                rt.fail('Non-measurement support cannot carry measurement dimensions')
            relation = field['relation_source_ids']
            if field['support_kind'] == 'RELATIONSHIP':
                if field['status'] == 'SUPPORTED' and not relation:
                    rt.fail('Relationship support needs explicit relation evidence')
                cited = {sid for scope in scopes for sid in scope['source_ids']}
                if len(relation) != len(set(relation)) or not set(relation).issubset(cited):
                    rt.fail('Relation evidence must be an explicit cited source, not an invented join')
            elif relation:
                rt.fail('Relation evidence belongs only to a relationship claim')
            target = projected['checks'][rid]['fields'][name]
            target.pop('support_kind')
            target.pop('measurement'); target.pop('relation_source_ids')
            for scope in target['source_scopes']:
                scope.pop('status')
                scope.pop('column_header')
    old.validate(projected, requirements, catalog)


def _requests(wire):
    parts = []
    def pack(selected):
        try:
            request = rt.make_request({**wire, 'requirements': selected}, response_schema(selected))
        except ValueError as exc:
            if 'transport capacity' not in str(exc) or len(selected) < 2:
                raise
            mid = len(selected)//2
            pack(selected[:mid]); pack(selected[mid:])
            return
        parts.append((selected, request))
    pack(wire['requirements'])
    return parts


def prepare(plan, source, main, out):
    out = Path(out).resolve()
    if out.exists() and any(out.iterdir()):
        rt.fail('Prepare into a new empty directory')
    bindings, requirements, catalog, wire = _inputs(plan, source, main)
    parts = []
    for i, (selected, request) in enumerate(_requests(wire), 1):
        part_id = f'DR_CHECK_{i:02}'
        path = write_json(out/'prepared'/part_id/'request.json', request)
        parts.append({'part_id': part_id, 'requirement_ids': [r['id'] for r in selected],
                      'request_ref': rt.file_ref(path), 'request_chars': len(json.dumps(request, ensure_ascii=False))})
    build = {'version': VERSION, 'bindings': bindings, 'requirements': requirements, 'parts': parts,
             'source_catalog_ref': rt.file_ref(write_json(out/'source_catalog.json', catalog)),
             'profiles': wire['profiles'], 'excluded_items': wire['excluded_items']}
    rt.verify_refs(bindings)
    write_json(out/'build.json', build)
    write_json(out/'preflight.json', {'provider_calls': 0, 'parts': len(parts),
        'requirements': len(requirements), 'source_fragments': len(catalog), 'version': VERSION})
    return build


def verify_prepared(out):
    out = Path(out)
    build = read_json(out/'build.json')
    if build.get('version') != VERSION:
        rt.fail('Legacy Coverage cannot be resumed under the scoped contract; prepare a new run')
    rt.verify_refs(build['bindings'])
    rt.verify_refs({'catalog': build['source_catalog_ref']})
    bindings, requirements, catalog, wire = _inputs(*(build['bindings'][k]['path'] for k in ('plan','source_view','main')))
    if (bindings != build['bindings'] or requirements != build['requirements']
            or catalog != read_json(build['source_catalog_ref']['path'])
            or wire['profiles'] != build['profiles'] or wire['excluded_items'] != build['excluded_items']):
        rt.fail('Prepared scoped Coverage does not replay')
    expected = _requests(wire)
    if len(expected) != len(build['parts']):
        rt.fail('Coverage partition changed')
    for part, (selected, request) in zip(build['parts'], expected):
        rt.verify_refs({'request': part['request_ref']})
        if part['requirement_ids'] != [r['id'] for r in selected] or read_json(part['request_ref']['path']) != request:
            rt.fail('Prepared scoped Coverage request changed')
    return build, catalog


def _result(out, build, catalog):
    checks, receipts, identities = {}, [], []
    for part in build['parts']:
        path = out/part['part_id']/'accepted.json'
        receipt = read_json(path)
        request = read_json(part['request_ref']['path'])
        rt.verify_refs({'raw': receipt['raw']})
        raw = read_json(receipt['raw']['path'])
        if (receipt.get('requested_model') != rt.MODEL or not isinstance(receipt.get('test_generator'), bool)
                or any(m != rt.MODEL for m in receipt.get('served_models', []))
                or receipt['request_sha256'] != request['request_sha256'] or raw['request_sha256'] != request['request_sha256']):
            rt.fail('Coverage receipt identity changed')
        validate(raw, [r for r in build['requirements'] if r['id'] in part['requirement_ids']], catalog)
        if set(checks) & set(raw['checks']):
            rt.fail('Duplicate accepted requirement')
        checks.update(copy.deepcopy(raw['checks'])); receipts.append(rt.file_ref(path)); identities.append(receipt)
    if set(checks) != {r['id'] for r in build['requirements']} or len({r['test_generator'] for r in identities}) != 1:
        rt.fail('Incomplete or mixed-execution Coverage')
    for check in checks.values():
        groups = [s for f in check['fields'].values() for s in f['source_scopes']] + check['condition_gaps']
        for group in groups:
            group['evidence'] = [{'source': sid, **catalog[sid]} for sid in group['source_ids']]
    return {'version': VERSION, 'complete': True, 'scope': 'DR_COMPARISON_ONLY', 'direct_next_stage': 'NECESSITY',
        'requirements': build['requirements'], 'checks': checks, 'source_catalog': catalog,
        'source_profiles': build['profiles'], 'excluded_items': build['excluded_items'], 'bindings': build['bindings'],
        'provenance': {'build': rt.file_ref(out/'build.json'), 'accepted_receipts': receipts, 'source_catalog': build['source_catalog_ref']},
        'execution': {'test_generator': identities[0]['test_generator'], 'requested_model': rt.MODEL,
                      'served_models': sorted({m for r in identities for m in r.get('served_models', [])})},
        'scientific_approval': False, 'can_enter_qc': False, 'fit_ready': False}


def run_prepared(out, *, generator=None):
    out = Path(out).resolve()
    build, catalog = verify_prepared(out)
    for part in build['parts']:
        selected = [r for r in build['requirements'] if r['id'] in part['requirement_ids']]
        rt.invoke(out/part['part_id'], read_json(part['request_ref']['path']), build['bindings'],
                  lambda raw: validate(raw, selected, catalog), generator=generator)
    result = _result(out, build, catalog)
    rt.verify_refs(build['bindings'])
    write_json(out/'coverage.json', result)
    return result


def verify_result(path):
    result = read_json(path)
    if result.get('version') != VERSION or result.get('complete') is not True:
        rt.fail('Current Necessity requires completed scoped Coverage v2; legacy results remain replay-only')
    rt.verify_refs({'build': result['provenance']['build'], **{str(i): r for i, r in enumerate(result['provenance']['accepted_receipts'])}})
    out = Path(result['provenance']['build']['path']).parent
    build, catalog = verify_prepared(out)
    if result != _result(out, build, catalog):
        rt.fail('Coverage differs from accepted scoped evidence')
    return result
