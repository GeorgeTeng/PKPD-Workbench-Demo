"""EP-only, offline intake for the explicitly scoped S02 review fixture.

This is not a production Data admission path. Full assigned evidence is frozen
and bound before construction. No model, R worker, or downstream stage is run.
The original EDA adapter remains the owner of instructions, rules and duties.
"""
from __future__ import annotations

import copy
import json

from ctxcomp.io import digest
from . import context_builder as cb, context_task, eda_context
from .common import read_json

TEST_STATUS = 'TEST_ONLY_NOT_PRODUCTION_ASSESSMENT'
TASK_FIELDS = {'objective', 'study', 'project_rules', 'scientific_context',
               'fixture_scope', 'implemented_r_operations', 'not_implemented_operations'}
HANDOFF_FIELDS = {'status', 'admission', 'source_items', 'source_view_ref',
                  'inventory_ref', 'scope_note', 'unresolved_and_limitations'}
ROW_FIELDS = {'dataset_id', 'source_row', 'row_type', 'role', 'record_level',
              'record_kind', 'cells', 'row_source_ids'}
CELL_FIELDS = {'column', 'header', 'source_id', 'raw_value'}
CELL_COLUMNS = ['column', 'header', 'source_id', 'raw_value']
ROW_CONTEXT = ['dataset_id', 'role', 'record_level', 'record_kind']

FIELD_PURPOSES = {
    'data_handoff.status/admission/scope_note': 'Make the test boundary and unapproved Data status visible.',
    'data_handoff.source_items.profile': 'Preserve verified record level, design, units, dose basis, windows, definitions and their source IDs.',
    'data_handoff.source_items.source_rows': 'Supply all assigned raw values and notes in a lossless row matrix with explicit column names and exact cell IDs.',
    'data_handoff.unresolved_and_limitations': 'Limit dependent displays and prohibit unsupported cohort or regimen joins.',
    'task_context.objective': 'Select displays for the existing objective without performing downstream fitting or translation.',
    'task_context.project_rules': 'Use original published EDA routing only when explicitly bound and verified; otherwise preserve all supplied project Rules. Full Rules remain host evidence.',
    'task_context.fixture_scope': 'Identify the three authorized tables and prevent fixture absence becoming project-level missingness.',
    'task_context.project_evaluation_setting': 'Carry the exact assigned study population statement so a held-out evaluation setting is not confused with project-wide absence of human evidence.',
    'task_context.implemented_r_operations/not_implemented_operations': 'Distinguish descriptive scientific permission from the explicitly available TEST handlers.',
    'task_context.planning_boundary': 'State EP-only assignment, readable matrix decoding and TEST scope.',
    'scientific_reference': 'Use explicitly selected exact method sections with GLOBAL/dependencies, or the full reference when selection is absent. No automatic RAG background.',
    'schema': 'Encode only the original eda_plan, analysis and display fields; permit explained not-applicable values.',
}


def _require(condition, message):
    if not condition:
        raise ValueError('EP intake: ' + message)


def pack_rows(rows):
    """Remove repeated row metadata only; values/IDs/unknown markers stay exact."""
    _require(isinstance(rows, list) and bool(rows), 'source rows required')
    context = {key: copy.deepcopy(rows[0][key]) for key in ROW_CONTEXT}
    records = []
    ids = []
    for row in rows:
        _require(set(row) == ROW_FIELDS, 'unknown or missing row fields require intake review')
        _require(all(row[k] == context[k] for k in ROW_CONTEXT), 'mixed row context requires intake review')
        _require(isinstance(row['cells'], list) and bool(row['cells']), 'empty cells')
        for cell in row['cells']:
            _require(set(cell) == CELL_FIELDS, 'unknown cell fields require intake review')
            _require(isinstance(cell['source_id'], str) and bool(cell['source_id']), 'missing source cell identity')
        cell_ids = [c['source_id'] for c in row['cells']]
        _require(row['row_source_ids'] == cell_ids, 'row and cell source identities disagree')
        ids.extend(cell_ids)
        records.append({'source_row': row['source_row'], 'row_type': row['row_type'],
                        'cells': [[copy.deepcopy(c[k]) for k in CELL_COLUMNS] for c in row['cells']]})
    _require(len(ids) == len(set(ids)), 'duplicate source cell identity')
    result = {'record_context': context, 'cell_columns': CELL_COLUMNS, 'rows': records}
    _require(unpack_rows(result) == rows, 'lossless row round trip failed')
    return result


def unpack_rows(table):
    _require(table['cell_columns'] == CELL_COLUMNS, 'matrix column contract changed')
    result = []
    for row in table['rows']:
        cells = [dict(zip(CELL_COLUMNS, values, strict=True)) for values in row['cells']]
        result.append({**copy.deepcopy(table['record_context']),
                       'source_row': row['source_row'], 'row_type': row['row_type'],
                       'cells': cells, 'row_source_ids': [c['source_id'] for c in cells]})
    return result


def response_schema():
    """Tighten the scaffold schema using only original EP output obligations."""
    artifact = read_json(eda_context.PACK)['artifact_contracts']['eda_plan']
    text = {'type': 'string', 'minLength': 1}
    texts = {'type': 'array', 'items': text}
    # Original instructions allow not-applicable fields with an explanation.
    detail = {'anyOf': [text, {'type': 'array', 'items': text}]}
    display = {'type': 'object', 'additionalProperties': False,
               'required': artifact['display_spec_fields'],
               'properties': {key: detail for key in artifact['display_spec_fields']}}
    analysis = {key: detail for key in artifact['analysis_fields']}
    for key in ['analysis_id', 'question', 'objective_link', 'experimental_unit',
                'formula_definition', 'censoring_policy', 'status', 'reason']:
        analysis[key] = text
    for key in ['requirement_ids', 'source_refs', 'reference_sections', 'dataset_ids']:
        analysis[key] = texts
    analysis['display_spec'] = display
    schema = {'$schema': 'https://json-schema.org/draft/2020-12/schema',
            'title': 'EP plan - original EDA artifact contract', 'type': 'object',
            'additionalProperties': False, 'required': artifact['required_fields'],
            'properties': {'version': text, 'input_refs': {
                               'type': 'object', 'additionalProperties': False,
                               'description': 'Only supplied semantic IDs; immutable file bindings are host-owned.',
                               'properties': {key: texts for key in
                                              ['dataset_ids', 'source_ids', 'rule_ids', 'reference_sections']}},
                           'objective': text, 'analyses': {'type': 'array', 'items': {
                               'type': 'object', 'additionalProperties': False,
                               'required': artifact['analysis_fields'], 'properties': analysis}},
                           'not_planned': {'type': 'array', 'items': text},
                           'open_items': {'type': 'array', 'items': text}}}
    # Every field must own its schema nodes before stage-specific descriptions
    # are added. deepcopy preserves shared references and cannot remove aliases.
    return json.loads(json.dumps(schema, ensure_ascii=False))


def intake(inputs_path, *, rule_context_path=None):
    """Construct a TEST EP intake; never infer approval from a status string.

    The explicit source file is the immutable host evidence. Unknown structural
    fields stop this adapter instead of silently becoming excluded context.
    Profiles, Rules, notes, values and limitations are copied without selection.
    The whole-project study/scientific catalog is host-only because this fixture
    authorizes exactly three tables. It is not independently reassessed here.
    """
    source_ref = cb.file_ref(inputs_path)
    full = read_json(inputs_path)
    _require(set(full) == {'data_handoff', 'task_context'}, 'exact two original inputs required')
    handoff, task = full['data_handoff'], full['task_context']
    _require(set(handoff) == HANDOFF_FIELDS, 'unknown handoff fields require review')
    _require(set(task) == TASK_FIELDS, 'unknown task fields require review')
    _require(handoff['status'] == TEST_STATUS and
             handoff['admission'] == 'FIXTURE_ONLY_UNVERIFIED_FOR_PRODUCTION',
             'only the unapproved TEST fixture is supported; production admission is unavailable')
    scope = task['fixture_scope']
    _require(scope.get('status') == TEST_STATUS and
             scope.get('no_production_admission_or_release') is True, 'explicit TEST scope required')
    _require(isinstance(task['objective'], str) and bool(task['objective']), 'objective required')
    rules = task['project_rules']
    _require(isinstance(rules, list) and rules and
             len({r['id'] for r in rules}) == len(rules), 'unique supplied project Rules required')
    operations = task['implemented_r_operations']
    _require(isinstance(operations, list) and all(isinstance(o, dict) and o.get('id') for o in operations),
             'explicit implemented operation registry required')
    _require(len({o['id'] for o in operations}) == len(operations), 'duplicate operation ID')
    assigned = scope['authorized_item_ids']
    _require(isinstance(assigned, list) and len(set(assigned)) == len(assigned), 'unique authorized item IDs required')
    _require([s['item_id'] for s in handoff['source_items']] == assigned, 'assigned source scope/order changed')
    refs = {'ep:full_assigned_inputs': source_ref, 'ep:intake_adapter': cb.file_ref(__file__)}
    routing = {'method': 'NO_EXPLICIT_PUBLISHED_ROUTING', 'included_ids': [r['id'] for r in rules],
               'excluded_ids': []}
    selected_rules = copy.deepcopy(rules)
    if rule_context_path is not None:
        from . import project_rule_agent
        context_ref = cb.file_ref(rule_context_path)
        main = read_json(rule_context_path)
        pack = project_rule_agent.validate_effective_context(main)
        _require(main['objective'] == task['objective'], 'published context objective differs')
        _require(pack['rules'] == rules, 'supplied Rules differ from the published full rule pack')
        projection = project_rule_agent.project(main['project_rules_ref'], 'eda')
        selected_ids = {r['id'] for r in projection['rules']}
        # Route membership comes only from the original verified host function.
        # Keep original operative fields/text rather than projection bookkeeping.
        selected_rules = [copy.deepcopy(r) for r in rules if r['id'] in selected_ids]
        routing = {'method': 'ORIGINAL_PUBLISHED_EDA_ROUTING', 'target': 'eda',
                   'included_ids': [r['id'] for r in selected_rules],
                   'excluded_ids': [r['id'] for r in rules if r['id'] not in selected_ids],
                   'original_projection': projection}
        refs.update({'ep:rule_context': context_ref,
                     'ep:published_rules': main['project_rules_ref'],
                     'ep:rule_routing_implementation': cb.file_ref(project_rule_agent.__file__)})
    for key in ['source_view_ref', 'inventory_ref']:
        refs['ep:' + key] = handoff[key]
    cb.check_refs(refs)
    source_view = read_json(handoff['source_view_ref']['path'])
    profiles = {p['item_id']: p for p in source_view['profiles']}
    source_units = source_view['source_units']
    items = []
    all_ids = []
    for index, item in enumerate(handoff['source_items']):
        _require(set(item) == {'item_id', 'profile', 'source_rows', 'source_binding'},
                 'unknown source item fields require review')
        _require(item['profile']['item_id'] == item['item_id'], 'profile identity mismatch')
        _require(item['profile'] == profiles.get(item['item_id']), 'profile differs from bound source view')
        packed = pack_rows(item['source_rows'])
        _require(packed['record_context']['dataset_id'] == item['item_id'], 'row dataset mismatch')
        actual = {c['source_id']: c['raw_value'] for r in item['source_rows'] for c in r['cells']}
        expected = {key: value for key, value in source_units.items()
                    if key == item['item_id'] or key.startswith(item['item_id'] + ':')}
        _require(actual == expected, 'source cells differ from the full assigned bound evidence')
        all_ids.extend(c['source_id'] for r in item['source_rows'] for c in r['cells'])
        for label, ref in item['source_binding'].items():
            refs[f'ep:source:{index}:{label}'] = ref
        items.append({'item_id': item['item_id'], 'profile': copy.deepcopy(item['profile']),
                      'source_rows': packed})
    _require(len(all_ids) == len(set(all_ids)), 'duplicate source IDs across items')
    cb.check_refs(refs)
    boundary = {
        'assignment': 'EP only: select decision-relevant displays and permitted descriptive operations for the assigned source scope. Return eda_plan; do not calculate or execute.',
        'test_scope': 'The registry is TEST-only passthrough/display support. Data is unapproved; production EDA is disabled. Fixture absence is not project-level missingness. No new calculated results are supplied.',
        'matrix_decode': 'record_context applies to every row. Each row has source_row, row_type and cells. Each cell is [column, header, source_id, raw_value], as named in cell_columns. Preserve exact IDs, values, notes and ND/NOT_FOUND meanings.',
    }
    narrowed = {'data_handoff': {k: copy.deepcopy(handoff[k]) for k in
                               ['status', 'admission', 'scope_note', 'unresolved_and_limitations']},
                'task_context': {k: copy.deepcopy(task[k]) for k in
                                 ['objective', 'project_rules', 'fixture_scope',
                                  'implemented_r_operations', 'not_implemented_operations']}}
    narrowed['data_handoff']['source_items'] = items
    narrowed['task_context']['project_rules'] = selected_rules
    population = task.get('study', {}).get('population')
    if population is not None:
        _require(isinstance(population, str) and bool(population), 'study population statement must be text')
        narrowed['task_context']['project_evaluation_setting'] = population
    boundary['evidence_scope'] = (
        'Describe only the assigned source evidence. The supplied project evaluation setting '
        'is distinct from the generic reference setting without target-drug human data. '
        'Human observations are not supplied to this TEST; do not infer project-wide absence '
        'from their absence here or use withheld validation outcomes.')
    unresolved = routing.get('original_projection', {}).get('unresolved', [])
    if unresolved:
        narrowed['task_context']['rule_scope_limits'] = copy.deepcopy(unresolved)
    narrowed['task_context']['planning_boundary'] = boundary
    cb.check_refs(refs)
    audit = {'status': TEST_STATUS, 'source_input_ref': source_ref,
             'full_inputs_sha256': digest(full), 'ep_inputs_sha256': digest(narrowed),
             'source_cells': len(all_ids), 'source_ids': all_ids, 'full_project_rules': len(rules),
             'model_project_rules': len(selected_rules), 'rule_routing': routing,
             'lossless_source_rows': True, 'raw_values_summarized': False,
             'host_only_original_task_fields': ['study', 'scientific_context'],
             'project_evaluation_setting_from': 'task_context.study.population' if population is not None else None,
             'host_only_evidence_bindings': ['source_view_ref', 'inventory_ref', 'source_binding'],
             'field_purposes': FIELD_PURPOSES, 'production_admission': False,
             'scientific_approval': False, 'provider_calls': 0}
    return narrowed, refs, audit


def prepare(inputs_path, *, rule_context_path=None, reference_selection=None, input_bindings=None,
            context_request=None, context_resolver=None):
    """Delegate exact original EP duties and shared assembly/projection policy."""
    inputs, refs, audit = intake(inputs_path, rule_context_path=rule_context_path)
    for key, value in (input_bindings or {}).items():
        _require(key not in refs or refs[key] == value, 'conflicting explicit binding: ' + key)
        refs[key] = value
    cb.check_refs(refs)
    schema = response_schema()
    original = eda_context.prepare('EP-plan', inputs, schema, input_bindings=refs)
    result = context_task.assemble(original, reference_selection=reference_selection,
                                  context_request=context_request, context_resolver=context_resolver)
    cb.verify_bundle(result)
    return result, audit
