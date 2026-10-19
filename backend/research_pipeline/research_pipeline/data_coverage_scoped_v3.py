"""Current Coverage contract; immutable v1 remains the historical replay reader."""
import copy
import json
import re
from pathlib import Path
from openpyxl.utils.cell import coordinate_to_tuple, get_column_letter
from ctxcomp.schemas import S, TEXT, arr, obj, enum, validate_schema
from . import data_coverage_direct as old, data_direct_runtime as rt
from .common import read_json, write_json

VERSION = 'DIRECT_DR_COVERAGE_3.0'
KINDS = ('MEASUREMENT_RECORDS', 'REPORTED_VALUE', 'CONTEXT_ONLY', 'RELATIONSHIP', 'UNRESOLVED')
OBSERVATION_ROLES = {'PK_OBSERVATIONS','PD_OBSERVATIONS','MIC','BINDING','IN_VITRO_TIME_KILL','DOSING'}
INSTRUCTIONS = '''
Each source_scopes entry is its own typed support record: status, support_kind,
measurement, column_header, recorded_value_presence, unresolved_dimensions and
relation_source_ids. Never share dimensions across heterogeneous source items.
MEASUREMENT_RECORDS requires the exact cited column's TABLE_BODY evidence and
quantity/unit/basis/record_level copied exactly from that source's profile. Cite
only that column's body cells (optional local header/context evidence is allowed).
Different quantities/units/bases/individual or aggregate levels remain separate
source records, even within one original DR field. An item can have several typed
records for different columns; (item_id, support_kind, column_header) must be unique.
TABLE_BODY establishes location,
not scientific truth, matching, assay validity or fitness. REPORTED_VALUE is
note/context-reported support, never an upgrade of a TABLE_BODY whose dimensions
remain unknown. CONTEXT_ONLY cannot prove observations or measurement qualification.
recorded_value_presence PRESENT means an original value/record is cited, not that
its dimensions or adequacy are established. Unknown measurement dimensions must
remain exactly as supplied, listed in unresolved_dimensions, with scope status
UNRESOLVED or PARTIAL and concrete field unresolved_information; PRESENT is allowed
alongside this unresolved qualification. Null or blank dimensions and explicit
UNKNOWN, NOT_FOUND, NOT_REPORTED, NOT_SPECIFIED, NOT_ESTABLISHED, UNRESOLVED,
UNVERIFIED or UNCERTAIN markers anywhere inside a qualifier count as unresolved;
preserve the complete original string, including any known part. Never change UNKNOWN/NOT_FOUND into
NOT_APPLICABLE. For other kinds measurement is null, column_header empty and
unresolved_dimensions empty; PRESENT is allowed only for REPORTED_VALUE with local
reported-value evidence. Do not relabel table-body records as reported/context
values merely to bypass unresolved dimensions. Headers alone establish no values.
SUPPORTED field requires every listed source scope SUPPORTED and no unresolved
dimensions; any scope CONFLICT requires field CONFLICT. Relevant mixed resolved
and unresolved scopes require field PARTIAL. Preserve contrary scopes/uncertainty;
do not expand a source/requirement Cartesian matrix. A relationship scope supplies
explicit relation_source_ids among its cited source IDs; two endpoint values do
not prove a link. Host checks source identity, not entailment of relationship prose.
All arrays contain unique values; duplicate selectors/dimensions are rejected.
An original requirement condition or an exact inherited_rule_constraints condition
may be used in condition_gaps.condition or not_applicable_condition. The latter's
authority stays bound to the supplied original Rule source selector, not to a new
model claim. Do not paraphrase, invent, or treat inherited exceptions as conditions.
Local permitted-source evidence is still required for NOT_APPLICABLE; the Rule
itself never establishes that its condition is satisfied.
'''


def response_schema(requirements):
    schema = old.response_schema(requirements)
    field = schema['$defs']['field']
    scope = field['properties']['source_scopes']['items']
    extra = dict(status=enum(*old.STATES), support_kind=enum(*KINDS),
        measurement={'anyOf':[obj(**{k:{'anyOf':[TEXT,{'type':'null'}]} for k in
            ('quantity','unit','basis','record_level')}),{'type':'null'}]},
        column_header=TEXT, recorded_value_presence=enum('PRESENT','NOT_ESTABLISHED','NOT_APPLICABLE'),
        unresolved_dimensions=arr(enum('quantity','unit','basis','record_level')), relation_source_ids=arr(S))
    scope['properties'].update(extra)
    scope['required'] += list(extra)
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
    wire.update(instructions=wire['instructions']+INSTRUCTIONS, coverage_contract_version=VERSION,
                source_regions={item_id:{'kind':items.get(item_id,{}).get('kind','UNKNOWN'),
                    'table_body_region':items.get(item_id,{}).get('region')}
                    for item_id in profiles})
    wire['requirements'] = [{**r, **{k:copy.deepcopy(original[k]) for k in
        ('task_scope','inherited_rule_constraints') if k in original}}
        for r,original in zip(wire['requirements'],requirements)]
    rt.verify_refs(bindings)
    return bindings, requirements, catalog, wire


def validate(raw, requirements, catalog):
    validate_schema(raw, response_schema(requirements))
    projected = copy.deepcopy(raw)
    for rid, check in raw['checks'].items():
        for name, field in check['fields'].items():
            scopes = field['source_scopes']
            keys = [(s['item_id'],s['support_kind'],s['column_header']) for s in scopes]
            if len(keys) != len(set(keys)):
                rt.fail('Duplicate typed source/column support record')
            statuses = [s['status'] for s in scopes]
            if 'NOT_APPLICABLE' in statuses and field['status'] != 'NOT_APPLICABLE':
                rt.fail('Source applicability requires the exact original field condition')
            if 'CONFLICT' in statuses and field['status'] != 'CONFLICT':
                rt.fail('Field hides a conflicting source scope')
            if field['status'] in {'SUPPORTED', 'NOT_APPLICABLE'}:
                if not statuses or any(s != field['status'] for s in statuses):
                    rt.fail('Field support disagrees with its source scopes')
            if field['status'] not in {'CONFLICT','NOT_APPLICABLE'} and 'SUPPORTED' in statuses and any(s != 'SUPPORTED' for s in statuses) and field['status'] != 'PARTIAL':
                rt.fail('Mixed supported and unresolved source scopes require a partial field')
            for scope in scopes:
                validate_scope(scope, catalog)
            target = projected['checks'][rid]['fields'][name]
            for scope in target['source_scopes']:
                for key in ('status','support_kind','measurement','relation_source_ids',
                            'column_header','recorded_value_presence','unresolved_dimensions'):
                    scope.pop(key)
            # Historical validation checks item ownership/evidence/applicability.
            # Its one-row-per-item projection is not the new scientific record:
            # retain the original typed rows unchanged above and in publication.
            grouped = {}
            for scope in target['source_scopes']:
                item = scope['item_id']
                if item not in grouped:
                    grouped[item] = copy.deepcopy(scope)
                else:
                    grouped[item]['source_ids'] = list(dict.fromkeys(grouped[item]['source_ids'] + scope['source_ids']))
                    grouped[item]['scope_note'] += '\n'+scope['scope_note']
            target['source_scopes'] = list(grouped.values())
    validation_requirements = copy.deepcopy(requirements)
    for requirement in validation_requirements:
        inherited = inherited_condition_authorities(requirement)
        requirement['conditions'] = list(dict.fromkeys(requirement.get('conditions', []) + list(inherited)))
    old.validate(projected, validation_requirements, catalog)


def inherited_condition_authorities(requirement):
    result = {}
    for binding in requirement.get('inherited_rule_constraints', []):
        if not re.fullmatch(r'main:/rules/\d+/text', binding['source']):
            if binding['conditions'] or binding['exceptions']:
                rt.fail('Inherited Rule condition requires an exact original Rule selector')
            continue
        if binding['source'] not in requirement.get('project_source_ids', []):
            rt.fail('Inherited Rule condition is not bound to this requirement project authority')
        for condition in binding['conditions']:
            result.setdefault(condition, []).append(binding['source'])
    return result


UNKNOWN_DIMENSIONS = {'','UNKNOWN','NOT_FOUND','NOT_REPORTED','NOT_SPECIFIED','UNRESOLVED'}
UNKNOWN_MARKERS = re.compile(r'\b(?:UNKNOWN|NOT[ _-](?:FOUND|REPORTED|SPECIFIED|ESTABLISHED)|UNRESOLVED|UNVERIFIED|UNCERTAIN)\b', re.I)


def unknown_dimensions(measurement):
    """Keep full qualifiers; explicit uncertainty markers never become known dimensions."""
    return {k for k,v in measurement.items() if v is None or v.strip().upper() in UNKNOWN_DIMENSIONS or UNKNOWN_MARKERS.search(v)}


def validate_scope(scope, catalog):
    sources = scope['source_ids']
    if len(sources) != len(set(sources)):
        rt.fail('Duplicate source reference inside typed support record')
    if any(s not in catalog or catalog[s]['item_id'] != scope['item_id'] for s in sources):
        rt.fail('Unknown, excluded or cross-item source reference')
    body = [catalog[s] for s in sources if catalog[s].get('evidence_role') == 'TABLE_BODY']
    kind, measurement = scope['support_kind'], scope['measurement']
    dimensions = scope['unresolved_dimensions']
    if len(dimensions) != len(set(dimensions)):
        rt.fail('Duplicate unresolved dimension')
    if scope['status'] in {'SUPPORTED','NOT_APPLICABLE'} and kind == 'UNRESOLVED':
        rt.fail('Supported source has unresolved evidence type')
    if kind == 'MEASUREMENT_RECORDS':
        if measurement is None:
            rt.fail('Measurement claim needs explicit source dimensions')
        if not body or any(e.get('column_header') != scope['column_header'] or e.get('measurement') != measurement for e in body):
            rt.fail('Measurement support requires matching table body evidence and source dimensions')
        unknown = unknown_dimensions(measurement)
        if set(dimensions) != unknown:
            rt.fail('Unresolved dimensions must exactly preserve source qualification unknowns')
        if unknown and scope['status'] not in {'UNRESOLVED','PARTIAL','CONFLICT'}:
            rt.fail('Unknown measurement dimensions cannot establish support or applicability')
        if scope['status'] == 'SUPPORTED' and scope['recorded_value_presence'] != 'PRESENT':
            rt.fail('Supported measurements require recorded value presence')
    else:
        if measurement is not None or scope['column_header'] or dimensions:
            rt.fail('Non-measurement support cannot carry measurement dimensions')
        if kind in {'REPORTED_VALUE','CONTEXT_ONLY'} and body:
            rt.fail('Table body measurement records cannot be downgraded to bypass dimensions')
        if scope['recorded_value_presence'] == 'PRESENT' and kind != 'REPORTED_VALUE':
            rt.fail('Value presence requires measurement or reported-value support')
        if kind == 'CONTEXT_ONLY' and scope['status'] == 'SUPPORTED':
            rt.fail('Context-only evidence cannot establish field support')
    if scope['recorded_value_presence'] == 'NOT_APPLICABLE' and scope['status'] != 'NOT_APPLICABLE':
        rt.fail('Value applicability requires exact original field condition')
    relation = scope['relation_source_ids']
    if kind == 'RELATIONSHIP':
        if scope['status'] == 'SUPPORTED' and not relation:
            rt.fail('Relationship support needs explicit relation evidence')
        if len(relation) != len(set(relation)) or not set(relation).issubset(sources):
            rt.fail('Relation evidence must be an explicit cited source, not an invented join')
    elif relation:
        rt.fail('Relation evidence belongs only to a relationship claim')


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
    for requirement in build['requirements']:
        authorities = inherited_condition_authorities(requirement)
        check = checks[requirement['id']]
        for gap in check['condition_gaps']:
            gap['inherited_rule_source_ids'] = authorities.get(gap['condition'], [])
        for field in check['fields'].values():
            if field['status'] == 'NOT_APPLICABLE':
                field['inherited_rule_source_ids'] = authorities.get(field['not_applicable_condition'], [])
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
        rt.fail('Current Necessity requires completed scoped Coverage v3; legacy results remain replay-only')
    rt.verify_refs({'build': result['provenance']['build'], **{str(i): r for i, r in enumerate(result['provenance']['accepted_receipts'])}})
    out = Path(result['provenance']['build']['path']).parent
    build, catalog = verify_prepared(out)
    if result != _result(out, build, catalog):
        rt.fail('Coverage differs from accepted scoped evidence')
    return result
