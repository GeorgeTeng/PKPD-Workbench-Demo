"""Typed EP -> EC TEST bridge. No prose compilation or generated analysis code."""
from __future__ import annotations

import copy
from pathlib import Path

from jsonschema import Draft202012Validator
from ctxcomp.io import digest
from . import context_builder as cb, context_task, eda_context, eda_ep
from .common import PROJECT, read_json, write_json

CONTRACT = 'EP_EC_TASK_1.0'
REGISTRY = Path(__file__).parent / 'resources/eda_ep_ec_registry.test.v1.json'
HANDLER = PROJECT / 'pkpd_r/eda/test_source_rows.R'
EV_HANDLER = PROJECT / 'pkpd_r/eda/test_render.R'
CATALOG = Path(__file__).parent / 'resources/context_builder/reference_catalogs/eda.20261013.json'
MANUAL_ORIGIN = 'HAND_AUTHORED_TEST_EXECUTION_PLAN'


def _require(ok, message):
    if not ok:
        raise ValueError('EP->EC: ' + message)


def _object(properties):
    return {'type': 'object', 'required': list(properties), 'additionalProperties': False,
            'properties': properties}


def execution_schema():
    """Refine existing artifact fields; legacy prose is replayable, not executable."""
    schema = eda_ep.response_schema()
    schema['title'] = 'EP plan with optional typed TEST execution contract'
    analysis = schema['properties']['analyses']['items']['properties']
    text = {'type': 'string', 'minLength': 1}
    texts = {'type': 'array', 'items': text, 'uniqueItems': True, 'minItems': 1}
    string_map = {'type': 'object', 'additionalProperties': text, 'minProperties': 1}
    typed = {
        'formula_definition': _object({
            'contract': {'const': CONTRACT}, 'operation_id': text,
            'parameters': _object({'column_roles': string_map,
                                   'value_handling': {'const': 'SOURCE_UNCHANGED'}}),
            'expected_output': {'const': 'SOURCE_ROW_SELECTION_1.0'}}),
        'record_selection': {'oneOf': [
            _object({'dataset_id': text, 'row_numbers': {'type': 'array', 'items': {
                'type': 'integer', 'minimum': 1}, 'uniqueItems': True, 'minItems': 1}, 'columns': texts}),
            _object({'dataset_id': text, 'cell_ids': texts})]},
        'grouping': _object({'columns': texts}),
        'transform_aggregation_order': _object({'transform': {'const': 'NONE'},
                                                'aggregation': {'const': 'NONE'}, 'units': string_map}),
        'censoring_policy': _object({'mode': {'const': 'PRESERVE_RAW_NO_IMPUTATION'}}),
        'input_relationships': _object({'mode': {'const': 'WITHIN_SOURCE_ROW_ONLY'},
                                         'cross_dataset_join': {'const': False},
                                         'baseline_scope': {'enum': ['NOT_APPLICABLE', 'SAME_TABLE_FOOTNOTES']}}),
    }
    for field, spec in typed.items():
        analysis[field] = {'anyOf': [analysis[field], spec]}
    analysis['status']['description'] = 'Only PLANNED tasks can execute; other statuses remain scoped omissions.'
    analysis['experimental_unit']['description'] = 'For typed execution, copy the exact permitted experimental_unit from the operation signature.'
    schema['properties']['version']['description'] = 'A concise plan-format identifier, for example EP_PLAN_1.0; not the task objective or explanatory prose.'
    schema['properties']['input_refs']['description'] = (
        'Prefer dataset_ids only. Per-analysis source_refs, requirement_ids and reference_sections '
        'carry the scientific citations; do not duplicate them globally. Legacy optional source_ids '
        'must identify supplied source cells, not dataset IDs or method-reference IDs.')
    schema['properties']['objective']['description'] = 'Copy task_context.objective exactly; it identifies the assigned task.'
    display = analysis['display_spec']['properties']
    axis = _object({'column': text, 'unit': text,
                    'scale': {'enum': ['linear', 'log10', 'categorical']}})
    for field in ['x_variable_unit_scale', 'y_variable_unit_scale']:
        display[field] = {'anyOf': [display[field], axis]}
    display['facets'] = {'anyOf': [display['facets'], _object({'column': text})]}
    display['kind']['description'] = 'Use an exact registered display kind and signature for rendering; prose/unknown displays remain unavailable.'
    display['uncertainty_definition']['description'] = (
        'Registered machine CODE ONLY, copied exactly from display_signature.uncertainty_definition. '
        'Put explanations in annotations or caption_limits; do not append prose to the code.')
    # Accept the old scaffold exactly as a replay document. An executable task
    # is validated against every typed field together, below.
    return schema


def typed_fields_schema():
    properties = execution_schema()['properties']['analyses']['items']['properties']
    names = ['formula_definition', 'record_selection', 'grouping',
             'transform_aggregation_order', 'censoring_policy', 'input_relationships']
    return _object({name: properties[name]['anyOf'][1] for name in names})


def prepare(inputs_path, *, rule_context_path=None, reference_selection=None,
            context_request=None, context_resolver=None):
    """A future EP call can emit typed fields directly; this function makes no call."""
    inputs, refs, audit = eda_ep.intake(inputs_path, rule_context_path=rule_context_path)
    registry = read_json(REGISTRY)
    profiles = {i['item_id']: i['profile'] for i in inputs['data_handoff']['source_items']}
    for value in registry['operations'].values():
        _require(value['experimental_unit'] == profiles[value['dataset_id']]['record_level'],
                 'registered experimental unit differs from admitted source profile')
    refs.update({'ep:execution_contract': cb.file_ref(__file__), 'ep:operation_registry': cb.file_ref(REGISTRY),
                 'ep:r_test_handler': cb.file_ref(HANDLER), 'ep:reference_catalog': cb.file_ref(CATALOG),
                 'ep:ec_dispatch': cb.file_ref(Path(__file__).with_name('eda_ec.py')),
                 'ep:ev_dispatch': cb.file_ref(Path(__file__).with_name('eda_ev.py')),
                 'ep:ev_test_renderer': cb.file_ref(EV_HANDLER),
                 'ep:transport_schema_adapter': cb.file_ref(Path(__file__).with_name('eda_ep_transport.py'))})
    # Only scientific signatures/parameter names enter the model body.
    inputs['task_context']['implemented_r_operations'] = [
        {'id': op, 'column_roles': value['column_roles'],
         'grouping_columns': value['grouping_columns'], 'units': value['units'],
         'dataset_id': value['dataset_id'], 'baseline_scope': value['baseline_scope'],
         'experimental_unit': value['experimental_unit'], 'executable_status': registry['executable_status'],
         'display_signature': value['display']}
        for op, value in registry['operations'].items()]
    inputs['task_context']['planning_boundary']['typed_execution'] = (
        'Translate executable selections directly into the typed existing output fields. '
        'formula_definition identifies the operation and named column roles; record_selection '
        'uses exact source rows/columns or cell IDs. Keep source grouping, units, missing markers '
        'and same-table baseline scope. Prose-only plans are readable but not executable. '
        'EC TEST handlers return source values unchanged. EV renders only the explicitly selected '
        'registered typed display signature; no new statistics, fits or inferred relationships. '
        'Copy experimental_unit and uncertainty_definition codes exactly from the operation signature. '
        'Describe observation windows from the selected observed time cells; a dosing event, axis origin '
        'or calibration boundary at zero is not an observed time-zero point.')
    original = eda_context.prepare('EP-plan', inputs, execution_schema(), input_bindings=refs)
    bundle = context_task.assemble(original, reference_selection=reference_selection,
                                  context_request=context_request, context_resolver=context_resolver)
    cb.verify_bundle(bundle)
    return bundle, audit


def _selected_rows(selector, item):
    """Resolve explicit identities only; never parse natural-language selectors."""
    source = [r for r in item['source_rows'] if r['row_type'] == 'SOURCE_ROW']
    by_number = {r['source_row']: r for r in source}
    profile_columns = [c['column'] for c in item['profile']['columns']]
    if 'row_numbers' in selector:
        numbers, columns = selector['row_numbers'], selector['columns']
        _require(all(n in by_number for n in numbers), 'unauthorized row selector')
        _require(all(c in profile_columns for c in columns), 'unauthorized column selector')
        _require(numbers == [r['source_row'] for r in source if r['source_row'] in numbers],
                 'row order must preserve the source order')
        _require(columns == [c for c in profile_columns if c in columns], 'column order must preserve source order')
    else:
        supplied = selector['cell_ids']
        cells = {c['source_id']: (r['source_row'], c['column']) for r in source for c in r['cells']}
        _require(all(c in cells for c in supplied), 'unauthorized cell selector')
        numbers = [r['source_row'] for r in source if any(cells[c][0] == r['source_row'] for c in supplied)]
        columns = [col for col in profile_columns if any(cells[c][1] == col for c in supplied)]
        expected = [c['source_id'] for n in numbers for c in by_number[n]['cells'] if c['column'] in columns]
        _require(supplied == expected, 'cell selector must preserve complete rows/groups and source order')
    rows = []
    for n in numbers:
        row = copy.deepcopy(by_number[n])
        row['cells'] = [c for c in row['cells'] if c['column'] in columns]
        _require([c['column'] for c in row['cells']] == columns, 'incomplete row selector')
        row['row_source_ids'] = [c['source_id'] for c in row['cells']]
        rows.append(row)
    return rows, columns


def record_test_plan(plan_path, prepared_request_path, receipt_path):
    """Explicit host receipt for a manual TEST plan and its original EP request.

    This does not authenticate model output or approve any scientific plan.
    """
    from .context_linear import assemble
    request_ref = cb.file_ref(prepared_request_path)
    plan_ref = cb.file_ref(plan_path)
    bundle = assemble(read_json(prepared_request_path))
    cb.verify_bundle(bundle)
    _require(bundle['context_manifest']['route'] == 'eda.plan', 'receipt requires original EP request')
    _require(read_json(plan_path)['version'] == MANUAL_ORIGIN, 'only explicitly hand-authored TEST plans are supported')
    _require(bundle['request']['payload']['schema'] == execution_schema(), 'prepared EP request lacks this typed contract')
    receipt = {'version': 'EP_PLAN_RECEIPT_TEST_1.0', 'origin': MANUAL_ORIGIN,
               'plan_ref': plan_ref, 'prepared_request_ref': request_ref,
               'request_sha256': bundle['request']['request_sha256'],
               'original_bindings': bundle['context_manifest']['input_bindings'],
               'scientific_approval': False, 'model_generated': False}
    _require(not Path(receipt_path).exists(), 'receipt already exists; old decisions are immutable')
    cb.check_refs({'plan': plan_ref, 'request': request_ref, **receipt['original_bindings']})
    write_json(receipt_path, receipt)
    return receipt


def _response_evidence(prepared, evidence_refs, evidence_kind):
    """Verify existing gateway artifacts, never infer provider/model identity."""
    from . import context_model_view, context_gateway
    cb.check_refs(evidence_refs)
    required = {'gateway_request', 'gateway_status', 'gateway_response',
                'gateway_model_input', 'gateway_schema', 'provider_call'}
    _require(set(evidence_refs) == required, 'complete gateway response evidence is mandatory')
    values = {key: read_json(ref['path']) for key, ref in evidence_refs.items()}
    request = prepared['request']
    _require(values['gateway_request'] == request, 'gateway request differs from original prepared EP request')
    status, call = values['gateway_status'], values['provider_call']
    _require(status.get('status') == 'RETURNED_PENDING_STAGE_VALIDATION' and
             status.get('provider_started') is True and status.get('request_sha256') == request['request_sha256'] and
             status.get('task_identity') == context_gateway.task_identity(request['payload']),
             'gateway status/task/request does not establish a returned response')
    _require(call.get('status') == 'RETURNED' and call.get('exit_code') == 0 and
             call.get('request_sha256') == request['request_sha256'] and bool(call.get('provider')),
             'provider call diagnostics do not match successful gateway request')
    slot = Path(evidence_refs['gateway_status']['path']).resolve().parent
    _require(all(Path(evidence_refs[key]['path']).resolve().parent == slot for key in required - {'provider_call'}) and
             Path(evidence_refs['provider_call']['path']).resolve().parent.parent == slot,
             'gateway evidence must belong to one saved dispatch slot')
    mock = evidence_kind == 'MOCK_TRANSPORT_RESPONSE'
    _require(evidence_kind in {'MODEL_RESPONSE', 'MOCK_TRANSPORT_RESPONSE'}, 'unsupported response evidence kind')
    if mock:
        _require(status.get('mock_transport') in (None, True) and call.get('mock_transport') is True and
                 call.get('provider') == 'MOCK_TRANSPORT', 'mock evidence must be explicitly labeled MOCK_TRANSPORT')
    else:
        _require(not status.get('mock_transport') and not call.get('mock_transport') and
                 call.get('provider') != 'MOCK_TRANSPORT', 'mock transport cannot be labeled a model response')
    wire, _ = context_model_view.project(request)
    from . import eda_ep_transport
    registry = read_json(prepared['context_manifest']['input_bindings']['ep:operation_registry']['path'])
    permitted_schemas = [request['payload']['schema'], eda_ep_transport.schema(
        request['payload']['schema'], registry, scope=_semantic_scope(prepared)[1])]
    _require(values['gateway_model_input'] == wire and values['gateway_schema'] in permitted_schemas,
             'saved transport differs from original prepared EP projection/schema')
    Draft202012Validator(values['gateway_schema']).validate(values['gateway_response'])
    Draft202012Validator(request['payload']['schema']).validate(values['gateway_response'])
    cb.verify_bundle(prepared)
    cb.check_refs(evidence_refs)


def record_model_plan(prepared_request_path, gateway_directory, receipt_path, *,
                      evidence_kind='MODEL_RESPONSE'):
    """Associate the exact saved EP response with mandatory gateway evidence.

    No generation, provider request, approval, or served-model inference occurs.
    MOCK_TRANSPORT_RESPONSE is an explicit offline-test origin, never live proof.
    """
    from .context_linear import assemble
    request_ref = cb.file_ref(prepared_request_path)
    prepared = assemble(read_json(prepared_request_path))
    cb.verify_bundle(prepared)
    _require(prepared['context_manifest']['route'] == 'eda.plan' and
             prepared['request']['payload']['schema'] == execution_schema(), 'typed original EP request required')
    slot = Path(gateway_directory)
    evidence = {key: cb.file_ref(slot / name) for key, name in {
        'gateway_request': 'request.json', 'gateway_status': 'status.json', 'gateway_response': 'response.json',
        'gateway_model_input': 'model_input.json', 'gateway_schema': 'transport_schema.json',
        'provider_call': 'provider/call.json'}.items()}
    _response_evidence(prepared, evidence, evidence_kind)
    receipt = {'version': 'EP_PLAN_RECEIPT_TEST_1.0', 'origin': evidence_kind,
               'plan_ref': evidence['gateway_response'], 'prepared_request_ref': request_ref,
               'request_sha256': prepared['request']['request_sha256'],
               'original_bindings': prepared['context_manifest']['input_bindings'],
               'response_evidence': evidence, 'scientific_approval': False,
               'model_generated': evidence_kind == 'MODEL_RESPONSE',
               'served_model_identity_verified': False}
    _require(not Path(receipt_path).exists(), 'receipt already exists; old decisions are immutable')
    cb.check_refs({'prepared_request': request_ref, **receipt['original_bindings'], **evidence})
    write_json(receipt_path, receipt)
    return receipt


def _receipt(receipt_path):
    from .context_linear import assemble
    receipt_ref = cb.file_ref(receipt_path)
    receipt = read_json(receipt_path)
    _require(receipt['version'] == 'EP_PLAN_RECEIPT_TEST_1.0' and
             receipt['origin'] in {MANUAL_ORIGIN, 'MODEL_RESPONSE', 'MOCK_TRANSPORT_RESPONSE'} and
             receipt['scientific_approval'] is False and
             receipt['model_generated'] == (receipt['origin'] == 'MODEL_RESPONSE'),
             'unsupported receipt origin/version')
    refs = {'receipt': receipt_ref, 'plan': receipt['plan_ref'],
            'prepared_request': receipt['prepared_request_ref'], **receipt['original_bindings'],
            **receipt.get('response_evidence', {})}
    cb.check_refs(refs)
    prepared = assemble(read_json(refs['prepared_request']['path']))
    cb.verify_bundle(prepared)
    _require(receipt['request_sha256'] == prepared['request']['request_sha256'] and
             receipt['original_bindings'] == prepared['context_manifest']['input_bindings'],
             'receipt does not match original prepared EP bindings')
    if receipt['origin'] == MANUAL_ORIGIN:
        _require(read_json(refs['plan']['path'])['version'] == MANUAL_ORIGIN, 'receipt plan origin mismatch')
    else:
        _require(receipt['plan_ref'] == receipt['response_evidence']['gateway_response'], 'plan is not exact saved raw response')
        _response_evidence(prepared, receipt['response_evidence'], receipt['origin'])
    return prepared, refs


def _semantic_scope(prepared):
    from . import context_model_view
    from .minimal_context_reducer import expand_payload
    wire, audit = context_model_view.project(prepared['request'])
    payload = expand_payload(wire['payload'])
    items = payload['data_handoff']['source_items']
    sources = {c['source_id'] for i in items for r in eda_ep.unpack_rows(i['source_rows']) for c in r['cells']}
    rules = {r['id'] for r in payload['processing_rules'] + payload['governance']['rules'] + payload['task_context']['project_rules']}
    selection = audit.get('reference_selection', {})
    if selection:
        sections = {s['id'] for field in selection['fields'] for s in field['included']}
    else:
        sections = {s['id'] for s in read_json(CATALOG)['sections']}
    return payload, {'dataset_ids': {i['item_id'] for i in items}, 'source_ids': sources,
                     'rule_ids': rules, 'reference_sections': sections}


def freeze(receipt_path):
    """Bind, validate, and materialize a compact EC request; never execute it."""
    prepared, refs = _receipt(receipt_path)
    payload, scope = _semantic_scope(prepared)
    plan = read_json(refs['plan']['path'])
    registry = read_json(refs['ep:operation_registry']['path'])
    _require(refs['ep:operation_registry'] == cb.file_ref(REGISTRY), 'unrecognized/stale registry binding')
    _require(registry['task_contract'] == CONTRACT and registry['status'] == eda_ep.TEST_STATUS,
             'stale registry/task version or non-TEST registry')
    Draft202012Validator(execution_schema()).validate(plan)
    _require(plan['objective'] == payload['task_context']['objective'], 'plan objective identity mismatch')
    for key, ids in plan['input_refs'].items():
        _require(set(ids) <= scope[key], 'input_refs cite IDs outside original prepared EP scope: ' + key)
    analyses = plan['analyses']
    _require(len({a['analysis_id'] for a in analyses}) == len(analyses), 'duplicate analysis identity')
    original = read_json(refs['ep:full_assigned_inputs']['path'])
    items = {i['item_id']: i for i in original['data_handoff']['source_items']}
    all_ids = scope['source_ids']
    available = {op['id'] for op in original['task_context']['implemented_r_operations']}
    tasks, omissions = [], []
    for analysis in analyses:
        aid = analysis['analysis_id']
        _require(set(analysis['dataset_ids']) <= set(items), 'unauthorized dataset identity')
        _require(set(analysis['source_refs']) <= all_ids, 'unauthorized source reference')
        _require(set(analysis['requirement_ids']) <= scope['rule_ids'], 'requirement IDs absent from original EP context')
        _require(set(analysis['reference_sections']) <= scope['reference_sections'], 'reference sections absent from original EP context')
        # Explicit identities remain hard boundaries, including on omitted work.
        if isinstance(analysis['record_selection'], dict):
            Draft202012Validator(typed_fields_schema()['properties']['record_selection']).validate(analysis['record_selection'])
            selection = analysis['record_selection']
            _require(selection['dataset_id'] in items and analysis['dataset_ids'] == [selection['dataset_id']],
                     'one authorized dataset per operation; no inferred join')
            _selected_rows(selection, items[selection['dataset_id']])
        if analysis['status'] != registry['executable_status']:
            omissions.append({'analysis_id': aid, 'status': 'NOT_CALCULABLE',
                              'reason': analysis['reason'] + ' [Plan status: ' + analysis['status'] + '] '})
            continue
        support = payload.get('context_support')
        if support is not None:
            rows = {row['output_id']: row for row in support['outputs']}
            affected = [aid] if aid in rows else analysis['dataset_ids']
            if not affected or any(key not in rows or rows[key]['status'] != 'READY_WITHIN_DECLARED_SCOPE'
                                   for key in affected):
                omissions.append({'analysis_id': aid, 'status': 'NOT_CALCULABLE',
                                  'reason': 'CONTEXT_DEPENDENCY_UNRESOLVED: automatic local restriction.'})
                continue
        if not isinstance(analysis['formula_definition'], dict):
            omissions.append({'analysis_id': aid, 'status': 'NOT_CALCULABLE',
                              'reason': 'LEGACY_PROSE_PLAN_NOT_EXECUTABLE; EP must supply typed fields.'})
            continue
        op = analysis['formula_definition']['operation_id']
        if op not in registry['operations'] or op not in available:
            omissions.append({'analysis_id': aid, 'status': 'NOT_CALCULABLE',
                              'reason': 'Operation is not registered/available; no code is generated.'})
            continue
        fields = {name: analysis[name] for name in typed_fields_schema()['properties']}
        Draft202012Validator(typed_fields_schema()).validate(fields)
        selector = analysis['record_selection']
        _require(selector['dataset_id'] in items and analysis['dataset_ids'] == [selector['dataset_id']],
                 'one authorized dataset per operation; no inferred join')
        item = items[selector['dataset_id']]
        rows, columns = _selected_rows(selector, item)
        selected_ids = {c['source_id'] for r in rows for c in r['cells']}
        context_ids = {c['source_id'] for r in item['source_rows'] if r['row_type'] != 'SOURCE_ROW' for c in r['cells']}
        _require(set(analysis['source_refs']) <= selected_ids | context_ids and
                 bool(set(analysis['source_refs']) & selected_ids),
                 'analysis citations must identify selected cells and their own source context')
        spec = analysis['formula_definition']
        op = spec['operation_id']
        error = None
        registered = registry['operations'][op]
        units = {c['column']: c['unit'] for c in item['profile']['columns'] if c['column'] in columns}
        if registered['dataset_id'] != item['item_id'] or registered['role'] != item['profile']['role']:
            error = 'Registered operation does not match source identity/role.'
        elif spec['parameters']['column_roles'] != registered['column_roles']:
            error = 'Column roles differ from the vetted operation signature.'
        elif not set(registered['column_roles'].values()) <= set(columns):
            error = 'Required source/group/summary columns are omitted.'
        elif analysis['grouping']['columns'] != registered['grouping_columns']:
            error = 'Source grouping columns must remain intact; no aggregation.'
        elif analysis['transform_aggregation_order']['units'] != units or any(
                units.get(c) != u for c, u in registered['units'].items()):
            error = 'Units differ from source metadata; no conversion or double-log operation is implemented.'
        elif analysis['experimental_unit'] != registered['experimental_unit'] or registered['experimental_unit'] != item['profile']['record_level']:
            error = 'Experimental unit differs from source record level; animal identities cannot be inferred.'
        elif analysis['input_relationships']['baseline_scope'] != registered['baseline_scope']:
            error = 'Baseline scope differs from the registered source-table relationship.'
        if error:
            omissions.append({'analysis_id': aid, 'status': 'NOT_CALCULABLE', 'reason': error})
            continue
        # R receives data and typed scientific conditions only, never the EP prompt.
        tasks.append({'analysis_id': aid, 'operation_id': op, 'contract': CONTRACT,
                      'parameters': spec['parameters'], 'expected_output': spec['expected_output'],
                      'record_selection': {'dataset_id': item['item_id'],
                                           'row_numbers': [r['source_row'] for r in rows], 'columns': columns},
                      'experimental_unit': analysis['experimental_unit'],
                      'grouping': analysis['grouping'],
                      'transform_aggregation_order': analysis['transform_aggregation_order'],
                      'censoring_policy': analysis['censoring_policy'],
                      'input_relationships': analysis['input_relationships'],
                      'source_rows': copy.deepcopy(rows),
                      'source_context': {'profile': copy.deepcopy(item['profile']),
                                         'notes': [copy.deepcopy(r) for r in item['source_rows'] if r['row_type'] != 'SOURCE_ROW'],
                                         'limitations': original['data_handoff']['unresolved_and_limitations']}})
    request = {'version': 'EP_EC_DISPATCH_TEST_1.0', 'status': eda_ep.TEST_STATUS,
               'handler_version': registry['handler_version'], 'tasks': tasks,
               'not_calculable': omissions}
    cb.check_refs(refs)
    return {'request': request, 'request_sha256': digest(request), 'bindings': refs,
            'expected_rows': {t['analysis_id']: _selected_rows(t['record_selection'], items[t['record_selection']['dataset_id']])[0]
                              for t in tasks}, 'execution_authorized': 'EXPLICIT_TEST_ONLY'}


def verify(frozen):
    cb.check_refs(frozen['bindings'])
    _require(digest(frozen['request']) == frozen['request_sha256'], 'changed frozen EC request')
    # Expected data are independently reconstructed from the frozen source and
    # selectors, so a caller cannot replace expected_rows to bless altered R output.
    replay = freeze(frozen['bindings']['receipt']['path'])
    _require(frozen == replay, 'frozen task differs from bound plan/inputs/registry; rebuild required')
    return frozen
