"""Explicit TEST-only EV rendering from a bound typed EP plan and exact EC rows.

No ContextBuilder assembly, retrieval, model interpretation, fitting or release.
"""
from __future__ import annotations

import copy
import math
import struct
import subprocess
from pathlib import Path

from jsonschema import Draft202012Validator
from ctxcomp.io import digest
from . import context_builder as cb, eda_ep_execution as bridge
from .common import read_json, write_json
from .engine import rscript_path


def _require(ok, message):
    if not ok:
        raise ValueError('EV TEST: ' + message)


def _number(raw, nd=False):
    if nd and raw == 'ND':
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise ValueError('unsupported numeric/missing marker: ' + str(raw)) from None
    if not math.isfinite(value):
        raise ValueError('nonfinite source value')
    return value


def _display_issue(analysis, result, registered):
    display = analysis['display_spec']
    signature = registered['display']
    columns = {c['column'] for row in result['rows'] for c in row['cells']}
    for field in ['x_variable_unit_scale', 'y_variable_unit_scale']:
        axis = display[field]
        if isinstance(axis, dict):
            _require(axis['column'] in columns, 'display selects unauthorized/unavailable column')
    if display['kind'] != signature['kind']:
        return 'Display kind is not registered for this source operation; no fallback.'
    for field, key in [('x_variable_unit_scale', 'x'), ('y_variable_unit_scale', 'y')]:
        axis, allowed = display[field], signature[key]
        if (not isinstance(axis, dict) or axis.get('column') != allowed['column'] or
                axis.get('unit') != allowed['unit'] or axis.get('scale') not in allowed['scales']):
            return 'Typed axis column/unit/scale does not match the registered display signature.'
    for field in ['marks', 'facets', 'legend', 'uncertainty_definition']:
        if display[field] != signature[field]:
            return 'Typed display field does not match the registered signature: ' + field
    roles = registered['column_roles']
    baselines = {}
    try:
        for row in result['rows']:
            cells = {c['column']: c['raw_value'] for c in row['cells']}
            x_axis, y_axis = display['x_variable_unit_scale'], display['y_variable_unit_scale']
            if x_axis['scale'] != 'categorical':
                x = _number(cells[x_axis['column']])
                if x_axis['scale'] == 'log10' and x <= 0:
                    return 'Log axis requires positive observed values; no artificial offset.'
            y = _number(cells[y_axis['column']], nd=analysis['formula_definition']['operation_id'] == 'REPORTED_MEAN_SD_DISPLAY')
            if y is not None and y_axis['scale'] == 'log10' and y <= 0:
                return 'Log axis requires positive observed values; no artificial offset.'
            if analysis['formula_definition']['operation_id'] == 'REPORTED_MEAN_SD_DISPLAY':
                sd = _number(cells[roles['endpoint_sd']], nd=True)
                bm, bs = _number(cells[roles['baseline_mean']]), _number(cells[roles['baseline_sd']], nd=True)
                if (sd is not None and sd < 0) or (bs is not None and bs < 0):
                    return 'Reported SD is negative; dependent display unavailable.'
                group = cells[roles['strain']]
                baseline = (cells[roles['baseline_mean']], cells[roles['baseline_sd']])
                if group in baselines and baselines[group] != baseline:
                    return 'Conflicting same-table baseline values; no averaging or cohort substitution.'
                baselines[group] = baseline
    except ValueError as error:
        return str(error)
    return None


def _inputs(receipt_path, calculation_path):
    """Recheck immutable host evidence directly; never rebuild a model prompt."""
    refs = {'ev:receipt': cb.file_ref(receipt_path), 'ev:calculation_bundle': cb.file_ref(calculation_path),
            'ev:dispatch': cb.file_ref(__file__), 'ev:renderer': cb.file_ref(bridge.EV_HANDLER)}
    receipt = read_json(receipt_path)
    _require(receipt['version'] == 'EP_PLAN_RECEIPT_TEST_1.0' and receipt['scientific_approval'] is False,
             'unsupported plan receipt')
    refs.update(receipt['original_bindings'])
    refs.update(receipt.get('response_evidence', {}))
    refs.update({'ev:plan': receipt['plan_ref'], 'ev:original_request': receipt['prepared_request_ref']})
    cb.check_refs(refs)
    _require(refs.get('ep:ev_dispatch') == cb.file_ref(__file__) and
             refs.get('ep:ev_test_renderer') == cb.file_ref(bridge.EV_HANDLER),
             'renderer was not bound before the EP decision; prepare a fresh request')
    request = read_json(receipt['prepared_request_ref']['path'])
    _require(request['request_sha256'] == receipt['request_sha256'] == digest(request['payload']), 'original EP identity changed')
    plan = read_json(receipt['plan_ref']['path'])
    Draft202012Validator(request['payload']['schema']).validate(plan)
    calculation = read_json(calculation_path)
    _require(calculation['plan_ref'] == receipt['plan_ref'] and
             calculation['input_refs']['receipt'] == refs['ev:receipt'], 'EC belongs to another plan/receipt')
    _require(all(calculation['input_refs'].get(k) == v for k, v in receipt['original_bindings'].items()),
             'EC changed the original EP bindings')
    cb.check_refs(calculation['input_refs'])
    refs.update({'ev:result': calculation['results_ref']['json'], 'ev:ec_provenance': calculation['provenance_ref']})
    if calculation['results_ref'].get('rds'):
        refs['ev:rds'] = calculation['results_ref']['rds']
    cb.check_refs(refs)
    ec = read_json(calculation['results_ref']['json']['path'])
    ec_request = read_json(calculation['input_refs']['ec_request']['path'])
    provenance = read_json(calculation['provenance_ref']['path'])
    _require(provenance['request_sha256'] == digest(ec_request) and provenance['source_values_exact'] is True,
             'EC request/result provenance mismatch')
    _require(ec['computed_statistics'] is False and ec['version'] == 'EP_EC_RESULT_TEST_1.0', 'unsupported EC result')
    registry = read_json(refs['ep:operation_registry']['path'])
    source = read_json(refs['ep:full_assigned_inputs']['path'])
    items = {i['item_id']: i for i in source['data_handoff']['source_items']}
    analyses = {a['analysis_id']: a for a in plan['analyses']}
    _require([r['analysis_id'] for r in ec['results']] == [t['analysis_id'] for t in ec_request['tasks']], 'EC result identity/order changed')
    tasks, omissions = [], copy.deepcopy(calculation['not_calculable'])
    for result in ec['results']:
        _require(result['analysis_id'] in analyses, 'EC cites an unknown analysis')
        analysis = analyses[result['analysis_id']]
        op = analysis['formula_definition']['operation_id']
        _require(op in registry['operations'] and result['operation_id'] == op, 'unknown/different source operation')
        registered = registry['operations'][op]
        item = items[registered['dataset_id']]
        _require(analysis['record_selection']['dataset_id'] == item['item_id'],
                 'display source identity mismatch')
        expected, _ = bridge._selected_rows(analysis['record_selection'], item)
        _require(result['rows'] == expected, 'EC rows differ from exact authorized source values')
        for field in ['experimental_unit', 'grouping', 'transform_aggregation_order', 'censoring_policy', 'input_relationships']:
            _require(result[field] == analysis[field], 'EC scientific condition changed: ' + field)
        _require(result['parameters'] == analysis['formula_definition']['parameters'], 'EC column roles changed')
        context = {'profile': item['profile'], 'notes': [r for r in item['source_rows'] if r['row_type'] != 'SOURCE_ROW'],
                   'limitations': source['data_handoff']['unresolved_and_limitations']}
        _require(result['source_context'] == context, 'EC source design/notes/limits changed')
        issue = _display_issue(analysis, result, registered)
        if issue:
            omissions.append({'analysis_id': analysis['analysis_id'], 'status': 'NOT_RENDERABLE', 'reason': issue})
            continue
        tasks.append({'figure_id': 'F' + str(len(tasks) + 1).zfill(3), 'analysis_id': analysis['analysis_id'],
                      'operation_id': op, 'display_spec': analysis['display_spec'],
                      'signature': registered['display'], 'column_roles': registered['column_roles'],
                      'rows': result['rows'], 'source_context': result['source_context']})
    cb.check_refs(refs)
    cb.check_refs(calculation['input_refs'])
    return {'version': 'EV_TEST_RENDER_1.0', 'tasks': tasks}, refs, omissions


def render(receipt_path, calculation_path, out):
    """Render only registered typed TEST displays, with pre/post binding checks."""
    calculation = read_json(calculation_path)
    if calculation.get("version") == "EP_FULL_SOURCE_1.0":
        from . import eda_ep_full as full
        frozen = read_json(receipt_path)
        full.verify_request(frozen)
        from .eda_ep_quality import require_execution_review
        require_execution_review(frozen)
        _require(frozen == full.verified(calculation["request"]), "full Data receipt differs from EC request")
        return full.execute_ev(calculation, out)
    request, refs, omissions = _inputs(receipt_path, calculation_path)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    request_path = write_json(out / 'ev_request.json', request)
    refs['ev:request'] = cb.file_ref(request_path)
    write_json(out / 'host_bindings.json', refs)
    if request['tasks']:
        cb.check_refs(refs)
        process = subprocess.run([rscript_path(), '--vanilla', str(bridge.EV_HANDLER), str(request_path.resolve()), str(out.resolve())],
                                 capture_output=True, text=True, encoding='utf-8', timeout=60)
        (out / 'r_stdout.txt').write_text(process.stdout, encoding='utf-8')
        (out / 'r_stderr.txt').write_text(process.stderr, encoding='utf-8')
        if process.returncode:
            raise ValueError('EV TEST renderer failed: ' + process.stderr.strip())
        metadata = read_json(out / 'rendered.json')
    else:
        metadata = {'figures': []}
    repeated, repeated_refs, repeated_omissions = _inputs(receipt_path, calculation_path)
    _require(repeated == request and all(refs[k] == v for k,v in repeated_refs.items()) and repeated_omissions == omissions,
             'bound rendering inputs changed')
    _require([m['figure_id'] for m in metadata['figures']] == [t['figure_id'] for t in request['tasks']], 'rendered figure identity/order mismatch')
    figures, tables, outputs = [], [], {}
    for meta, task in zip(metadata['figures'], request['tasks']):
        fid = task['figure_id']
        image = out / (fid + '.png')
        svg = out / (fid + '.svg')
        plotted = out / (fid + '.plotted_rows.json')
        outputs.update({fid + ':png': cb.file_ref(image), fid + ':svg': cb.file_ref(svg), fid + ':rows': cb.file_ref(plotted)})
        data = read_json(plotted)
        _require(data['raw_rows'] == task['rows'] and data['display_spec'] == task['display_spec'], 'rendered row/definition provenance changed')
        header = image.read_bytes()[:24]
        _require(header[:8] == b'\x89PNG\r\n\x1a\n', 'output is not PNG')
        width, height = struct.unpack('>II', header[16:24])
        _require(width >= 1400 and height >= 900, 'PNG resolution is below the readable TEST target')
        caption = task['display_spec']['caption_limits']
        source_refs = [c['source_id'] for row in task['rows'] for c in row['cells']]
        figures.append({'figure_id': fid, 'analysis_ids': [task['analysis_id']], 'image_ref': outputs[fid + ':png'],
                        'plotted_rows_ref': outputs[fid + ':rows'], 'caption': caption,
                        'source_refs': source_refs,
                        'limitations': task['signature']['required_notes'] + task['source_context']['limitations']})
        tables.append({'analysis_ids': [task['analysis_id']], 'source_rows_ref': outputs[fid + ':rows']})
    cb.check_refs(refs)
    cb.check_refs(outputs)
    write_json(out / 'render_provenance.json', {'input_bindings': refs, 'outputs': outputs, 'provider_calls': 0,
                                             'rendered_images_inspected': False, 'scientific_approval': False})
    bundle = {'version': 'EV_TEST_FIGURE_BUNDLE_1.0', 'plan_ref': refs['ev:plan'],
              'calculation_ref': refs['ev:calculation_bundle'], 'figures': figures, 'tables': tables,
              'technical_checks': {'source_values_exact': True, 'production_enabled': False,
                                   'rendered_images_inspected': False, 'new_statistics_computed': False,
                                   'provider_calls': 0}, 'omissions': omissions}
    write_json(out / 'figure_bundle.json', bundle)
    return bundle
