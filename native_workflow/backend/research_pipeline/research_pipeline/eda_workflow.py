"""Explicit descriptive EDA runner: EP -> R EC -> EP display review -> R EV -> EI -> ER -> human.

Reuse prepared Data. Each model stage runs once through ContextBuilder. No
automatic repairs, retries, fitting, downstream launch or synthetic approval.
This explicit runner does not enable the legacy workbench EDA dispatcher.
"""
from __future__ import annotations

import argparse
import copy
import html
import json
import shutil
import time
from pathlib import Path

from jsonschema import Draft202012Validator
from ctxcomp import providers
from ctxcomp.io import digest
from . import context_builder as cb, eda_context, eda_ep_full as ep, eda_ec, eda_ev
from . import eda_ep_quality, eda_post_ec
from . import minimal_context_reducer as reducer
from .common import read_json, write_json, utcnow
from .context_linear import LinearSession

STAGES = ('EP', 'EC', 'EP_FINALIZE', 'EV', 'EI', 'ER')
RENDER_PREFIX = STAGES[:4]


def require(ok, message):
    if not ok:
        raise ValueError('EDA workflow: ' + message)


def strict_schema(node):
    """Wire-only normalization; the complete host schema still validates output."""
    if isinstance(node, list):
        return [strict_schema(v) for v in node]
    if not isinstance(node, dict):
        return node
    out = {k: strict_schema(v) for k, v in node.items() if k not in {
        '$schema', 'uniqueItems', 'minLength', 'maxLength', 'minProperties', 'maxProperties'}}
    if 'const' in out:
        out['enum'] = [out.pop('const')]
    if 'oneOf' in out:
        out['anyOf'] = out.pop('oneOf')
    if out.get('type') == 'object':
        out['required'] = list(out.get('properties', {}))
        out['additionalProperties'] = False
    return out


def reconcile_ep(raw):
    """Separate an explicitly requested table fallback; never infer new science.

    The raw response remains immutable. Do not repair unsupported operations,
    selectors, omissions, values or references. The full validator still runs.
    """
    plan = copy.deepcopy(raw); changes = []
    original = {a['analysis_id']: a for a in plan.get('analyses', [])}
    for a in list(plan.get('analyses', [])):
        execution = a.get('execution', {})
        if a.get('status') == 'DEFERRED' and execution.get('operation_id') == 'SOURCE_TABLE' and execution.get('series'):
            fallback = copy.deepcopy(a)
            fallback['analysis_id'] = a['analysis_id']+'_TABLE_FALLBACK'
            require(fallback['analysis_id'] not in original, 'fallback ID collision')
            fallback['status'] = 'PLANNED'
            fallback['question'] = 'Source-table fallback for: '+a['question']
            fallback['display_spec']['kind'] = 'SOURCE_TABLE'
            for key in ['x_variable_unit_scale', 'y_variable_unit_scale', 'facets']:
                fallback['display_spec'][key] = 'Not applicable: unchanged source table.'
            fallback['display_spec']['marks'] = 'Original values, statuses and source cells.'
            fallback['reason'] = 'Host-separated execution of the source-table fallback explicitly selected in '+a['analysis_id']+'. The original figure remains DEFERRED. '+a['reason']
            a['execution'] = {'operation_id': 'NONE', 'series': [], 'limitation': execution['limitation']}
            plan['analyses'].append(fallback)
            for d in plan.get('dataset_disposition', []):
                if d['dataset_id'] in a['dataset_ids'] and a['analysis_id'] in d['analysis_ids']:
                    d['analysis_ids'].append(fallback['analysis_id'])
            changes.append({'kind': 'SEPARATE_DECLARED_TABLE_FALLBACK', 'analysis_id': a['analysis_id'], 'fallback_id': fallback['analysis_id']})
    for d in plan.get('dataset_disposition', []):
        selected = [a for a in plan.get('analyses', []) if d['dataset_id'] in a['dataset_ids']]
        if (d.get('use') == 'SUPPORTING' and selected and
                set(d.get('analysis_ids', [])) == {a['analysis_id'] for a in selected} and
                all(a['execution']['operation_id'] == 'SOURCE_TABLE' for a in selected)):
            d['use'] = 'PLANNED'
            changes.append({'kind': 'DERIVE_SELECTED_TABLE_USE', 'dataset_id': d['dataset_id'],
                            'note': 'Scientific source role and original reason remain unchanged.'})
    return plan, changes


def response_schema(stage, inputs=None):
    text = {'type': 'string', 'minLength': 1}
    texts = {'type': 'array', 'items': text, 'uniqueItems': True}
    def obj(properties):
        return {'type': 'object', 'properties': properties, 'required': list(properties), 'additionalProperties': False}
    refs = obj({'analysis_ids': texts, 'artifact_ids': texts})
    if stage == 'EI':
        finding = obj({k: texts if k in {'analysis_ids', 'artifact_refs', 'record_scope'} else text for k in [
            'finding_id', 'analysis_ids', 'artifact_refs', 'record_scope', 'observation',
            'interpretation_if_useful', 'alternative_if_interpretation', 'downstream_implication']})
        for key in ['interpretation_if_useful', 'alternative_if_interpretation']:
            finding['properties'][key] = {'type': 'string'}
        schema = obj({'version': text, 'input_refs': refs, 'findings': {'type': 'array', 'items': finding},
                      'limitations': texts, 'open_items': texts})
    else:
        require(stage == 'ER', 'unknown review schema')
        issue = obj({k: text for k in ['issue_id', 'affected_artifact', 'evidence', 'consequence',
                                  'correction_owner', 'smallest_correction']})
        issue['properties']['correction_owner'] = {'enum': ['Data', 'EP', 'EC', 'EV', 'EI', 'ER', 'HUMAN']}
        schema = obj({'version': text, 'reviewed_refs': refs, 'decision': {'enum': ['PASS', 'REVISE', 'NEEDS_REVIEW']},
                      'review_scope': text, 'issues': {'type': 'array', 'items': issue}, 'unreviewed_items': texts})
    if inputs is None:
        return schema
    def selectors(values, description, complete=False):
        out = {'type': 'array', 'items': {'type': 'string', 'enum': values} if values else {'type':'string'},
               'uniqueItems': True, 'description': description}
        if complete or not values:
            out.update(minItems=len(values), maxItems=len(values))
        return out
    analyses = [a['analysis_id'] for a in inputs['eda_plan']['analyses']]
    artifacts = [a['artifact_id'] for a in inputs['figure_bundle']['artifacts']]
    refs['properties'] = {
        'analysis_ids': selectors(analyses, 'Copy every supplied analysis ID exactly once, including DEFERRED originals and separate table fallbacks.', True),
        'artifact_ids': selectors(artifacts, 'Copy every supplied artifact ID exactly once.', True)}
    if stage == 'EI':
        records = list(dict.fromkeys(r['record_id'] for t in inputs['calculation_bundle']['source_tables'].values()
                                     for r in expand_grid(t['records'])))
        finding['properties']['analysis_ids'] = selectors(analyses, 'Analyses actually supported by this finding.')
        finding['properties']['artifact_refs'] = selectors(artifacts, 'Actual source-table/plot artifacts supporting this finding.')
        finding['properties']['record_scope'] = selectors(records,
            'Source ROW IDs only, never dataset IDs. For a metadata/plan/notes-only finding use an empty array and cite its actual analysis/artifact. Do not expand a dataset ID into every row automatically.')
    else:
        issue['properties']['affected_artifact'] = {'type':'string', 'enum': artifacts+analyses+
            ['data_handoff','eda_plan','calculation_bundle','figure_bundle','eda_findings'],
            'description':'Select one supplied target. Put any nested field path in evidence, never append it to this ID.'}
    return schema


def validate_output(stage, raw, inputs):
    Draft202012Validator(response_schema(stage)).validate(raw)
    plan = inputs['eda_plan']
    analyses = {a['analysis_id']: a for a in plan['analyses']}
    artifacts = {a['artifact_id']: a for a in inputs['figure_bundle']['artifacts']}
    refs = raw['input_refs' if stage == 'EI' else 'reviewed_refs']
    require(set(refs['analysis_ids']) == set(analyses), 'response must account for the supplied analysis scope')
    require(set(refs['artifact_ids']) == set(artifacts), 'response must account for supplied artifact scope')
    if stage == 'EI':
        require(len({f['finding_id'] for f in raw['findings']}) == len(raw['findings']), 'duplicate finding IDs')
        rows = inputs['calculation_bundle']['source_tables']
        for finding in raw['findings']:
            require(not finding['interpretation_if_useful'].strip() or bool(finding['alternative_if_interpretation'].strip()),
                    'an interpretation requires an alternative explanation')
            require(bool(finding['analysis_ids']) and set(finding['analysis_ids']) <= set(analyses), 'unknown finding analysis')
            require(set(finding['artifact_refs']) <= set(artifacts), 'unknown finding artifact')
            allowed_data = {d for aid in finding['analysis_ids'] for d in analyses[aid]['dataset_ids']}
            allowed_rows = {r['record_id'] for d in allowed_data if d in rows for r in expand_grid(rows[d]['records'])}
            require(set(finding['record_scope']) <= allowed_rows, 'finding rows outside its analysis')
            require(all(artifacts[aid]['analysis_id'] in finding['analysis_ids'] for aid in finding['artifact_refs']),
                    'finding artifact belongs to a different analysis')
    else:
        require(len({i['issue_id'] for i in raw['issues']}) == len(raw['issues']), 'duplicate issue IDs')
        allowed = set(artifacts) | set(analyses) | {'data_handoff', 'eda_plan', 'calculation_bundle', 'figure_bundle', 'eda_findings'}
        require(all(i['affected_artifact'] in allowed for i in raw['issues']), 'unknown issue target')
        require(raw['decision'] != 'PASS' or not raw['issues'], 'PASS cannot contain unresolved issues')
        require(bool(raw['unreviewed_items']), 'JSON-only review must disclose uninspected rendered images')


def compact_grid(records):
    """Lossless columnar JSON, using the existing exact-defaults implementation.

    Only JSON representation changes. Explicit null and absent stay distinct;
    all original numbers, source IDs, status and scientific fields round-trip.
    """
    if not records or not all(isinstance(r, dict) for r in records):
        return copy.deepcopy(records)
    rows = json.loads(json.dumps(records, allow_nan=False))
    aliases = [k for k in rows[0] if k not in reducer.IDENTITY and all(
        k in r and k in r.get('source_raw_values', {}) and
        reducer.canonical(r[k]) == reducer.canonical(r['source_raw_values'][k]) for r in rows)]
    for r in rows:
        for key in aliases:
            del r[key]
    defaults = reducer._common_defaults(rows)
    fields = list(dict.fromkeys(k for r in rows for k in r))
    nested = {}
    for key in fields:
        if all(key in r and isinstance(r[key], dict) for r in rows):
            column = [r[key] for r in rows]
            packed = compact_grid(column)
            if len(reducer.canonical(packed)) + len(rows)*5 + len(key) + 20 < len(reducer.canonical(column)):
                nested[key] = packed
    grid = {'encoding': 'EDA_COLUMNAR_1', 'defaults': defaults,
            'copy_from_source_raw_values': aliases, 'fields': fields,
            'rows': [[None if k in nested else r.get(k) for k in fields] for r in rows],
            'nested_columns': nested,
            'absent_fields': [[k for k in fields if k not in r] for r in rows]}
    require(reducer.canonical(expand_grid(grid)) == reducer.canonical(records), 'columnar round-trip mismatch')
    return grid if len(reducer.canonical(grid)) < len(reducer.canonical(records)) else records


def expand_grid(grid):
    if isinstance(grid, list):
        return copy.deepcopy(grid)
    require(grid.get('encoding') == 'EDA_COLUMNAR_1', 'unknown source encoding')
    fields = grid['fields']
    require(len(fields) == len(set(fields)), 'duplicate source fields')
    require(len(grid['rows']) == len(grid['absent_fields']), 'invalid absent-field inventory')
    nested = {k: expand_grid(v) for k, v in grid['nested_columns'].items()}
    require(set(nested) <= set(fields) and all(len(v) == len(grid['rows']) for v in nested.values()), 'invalid nested source columns')
    out = []
    for index, (cells, absent) in enumerate(zip(grid['rows'], grid['absent_fields'])):
        require(len(cells) == len(fields) and set(absent) <= set(fields), 'invalid source row')
        row = {k: copy.deepcopy(v) for k, v in zip(fields, cells) if k not in absent}
        for key, values in nested.items():
            require(key not in absent and row[key] is None, 'nested source collision')
            row[key] = values[index]
        reducer._merge(row, grid['defaults'])
        for key in grid['copy_from_source_raw_values']:
            require(key not in row, 'source alias collision')
            row[key] = copy.deepcopy(row['source_raw_values'][key])
        out.append(row)
    return out


def review_inputs(root, stage):
    """Supply result contents once; locators never masquerade as visible images."""
    root = Path(root)
    frozen = read_json(root/'EP/accepted/ec_request.json')
    ep.verify_request(frozen)
    initial = read_json(root/'EP/prepared/request.json')['payload']
    result = ep.verified(read_json(root/'EC/calculation_bundle.json')['result'])
    manifest = read_json(root/'EV/visualization_bundle.json')
    result = read_json(root/'EV/render_input.json')
    plan = read_json(root/'EP/accepted/resolved_plan.json')
    plan['post_ec_display_review'] = read_json(root/'EP_FINALIZE/output.json')
    plan['execution_note'] = 'Original analyses are the proposal. post_ec_display_review and the final task selections in calculation_bundle define executed displays; EC source records and calculations are unchanged.'
    handoff = copy.deepcopy(initial['data_handoff'])
    handoff.pop('reading_views', None)
    # Exact source locators stay in the bound original handoff and stage receipts.
    # Retain file IDs, roles, readiness, and every other substantive field.
    for f in handoff.get('files', []):
        for key in ['data', 'csv', 'metadata_file', 'quarantine', 'observation_view']:
            if key in f:
                require(isinstance(f[key], dict) and set(f[key]) == {'path', 'sha256'}, 'unexpected source locator content')
                cb.check_refs({key: f.pop(key)})
    for key, value in list(handoff.items()):
        if isinstance(value, list):
            handoff[key] = compact_grid(value)
    handoff['materialization_note'] = 'Original source rows, columns and notes for executed displays occur once in calculation_bundle.source_tables. Full admitted scope and unresolved items remain here and in eda_plan. No new extraction or Data assessment.'
    source_tables, results, artifacts, contexts = {}, [], [], {}
    for task in result['tasks']:
        table = {key: task[key] for key in ['dataset_id', 'title', 'columns', 'experimental_unit', 'records', 'notes']}
        if task['dataset_id'] in source_tables:
            require(source_tables[task['dataset_id']] == table, 'inconsistent repeated source table')
        source_tables[task['dataset_id']] = table
        results.append({key: value for key, value in task.items() if key not in table or key == 'dataset_id'})
        context = results[-1].pop('context')
        contexts[task['task_id']] = context
    for table in source_tables.values():
        table['records'] = compact_grid(table['records'])
    for item in manifest['artifacts']:
        task = next(t for t in result['tasks'] if t['task_id'] == item['task_id'])
        artifacts.append({'artifact_id': item['task_id'], 'analysis_id': task['analysis_id'],
            'dataset_id': task['dataset_id'], 'context_location': 'calculation_bundle.analysis_contexts.'+task['task_id'],
            'image_supplied_to_model': False,
            'image_exists': bool(item['image']),
            'plot_data_location': 'calculation_bundle.results task_id=' + item['task_id']})
    task_context = copy.deepcopy(initial['task_context'])
    task_context.pop('dataset_catalog', None)
    task_context.pop('ep_plan_contract', None)
    task_context['eda_output_contract'] = {
        'instruction': 'Use the supplied source_tables and results; do not inspect file paths. Results contain source-native observations, not fitted values or new statistics. Mention limitations once per relevant analysis. Return concise English JSON. Use analysis IDs and TASK IDs in input_refs/reviewed_refs; cover all supplied IDs. Record scope uses exact source record IDs. Unavailable interpretation may be stated as not applicable.',
        'review_scope': 'Rendered images are not supplied by this JSON transport. ER must disclose visual inspection as unreviewed; a human must inspect the exact images before handoff. PASS is limited to the disclosed evidence and cannot approve the human checkpoint.',
        'issue_targets': 'Use a supplied analysis ID, TASK ID, data_handoff, eda_plan, calculation_bundle, figure_bundle or eda_findings.'}
    task_context['ep_execution_mapping'] = read_json(root/'EP/reconciliation.json')
    task_context['review_reference_contract'] = {
        'scope': 'Account for every supplied analysis, including deferred analyses with no rendered artifact. A deferred original and its executed source-table fallback are distinct plan entries; the exact parent/fallback mapping is in ep_execution_mapping.changes.',
        'findings': 'record_scope identifies original source ROW IDs from the response enum. Dataset IDs such as T0001 are not row IDs. A statement based only on metadata, notes, scope or unresolved status may use an empty record_scope; cite its actual analyses and artifacts. Do not fabricate row attribution.',
        'review': 'affected_artifact must be one permitted ID or top-level section. Describe nested field paths in evidence. Read explicit analysis_id on each task and all plan entries before alleging a missing association. No field should be judged missing merely from a compact encoding placeholder.',
        'content': 'Describe supported observed patterns where the supplied evidence permits them. Do not substitute only a restriction list for interpretation. If plots have been deferred, distinguish source-table availability from completion of graphical EDA.'}
    task_context['input_encoding'] = (
        'EDA_COLUMNAR_1 is a lossless table representation, not missing data. Map each rows cell to fields in order; '
        'remove fields named in the matching absent_fields entry; recursively inherit absent fields from defaults. '
        'Before inheriting defaults, replace any nested_columns field placeholder by the corresponding row decoded from its nested grid. '
        'Explicit null, empty strings and lists override defaults. Then copy each copy_from_source_raw_values key '
        'from that row\'s source_raw_values. Original record IDs, source cells, raw values and statuses are preserved. '
        'Final display context appears once per task in calculation_bundle.analysis_contexts, selected by task_id for every task '
        'and artifact. File paths and hashes remain in host receipts, not model evidence. No content is truncated.')
    inputs = {'data_handoff': handoff, 'task_context': task_context, 'eda_plan': plan,
        'calculation_bundle': {'source_tables': source_tables, 'results': results, 'analysis_contexts': contexts, 'computed_statistics': False},
        'figure_bundle': {'artifacts': artifacts, 'visual_review': 'NOT_SUPPLIED_TO_MODEL',
            'deferred_analyses': [a['analysis_id'] for a in plan['analyses'] if a['status'] != 'PLANNED']}}
    if stage == 'ER':
        inputs['eda_findings'] = read_json(root/'EI/output.json')
    return inputs


def pack_review_inputs(inputs):
    """Lossless exact-subtree sharing for large EI/ER evidence, never Rules."""
    from collections import Counter
    from ctxcomp.io import canonical
    counts = Counter()
    def scan(value):
        key = canonical(value)
        if isinstance(value, (dict, list, str)) and len(key) > 80:
            counts[key] += 1
        if isinstance(value, dict):
            require(set(value) != {'EDA_SHARED_REF'}, 'reserved evidence codec key in input')
            for child in value.values(): scan(child)
        elif isinstance(value, list):
            for child in value: scan(child)
    scan(inputs)
    pool = {}; ids = {}
    def pack(value, skip=False):
        key = canonical(value)
        if not skip and counts[key] > 1 and len(key) > 80:
            if key not in ids:
                label = 'E'+str(len(ids)+1); ids[key] = label
                pool[label] = pack(value, True)
            return {'EDA_SHARED_REF': ids[key]}
        if isinstance(value, dict): return {k:pack(v) for k,v in value.items()}
        if isinstance(value, list): return [pack(v) for v in value]
        return value
    packed = pack(inputs)
    def expand(value):
        if isinstance(value, dict):
            if set(value) == {'EDA_SHARED_REF'}: return expand(pool[value['EDA_SHARED_REF']])
            return {k:expand(v) for k,v in value.items()}
        if isinstance(value, list): return [expand(v) for v in value]
        return value
    require(canonical(expand(packed)) == canonical(inputs), 'evidence sharing failed exact round trip')
    if len(canonical(inputs))-len(canonical([packed,pool])) < 10000:
        return copy.deepcopy(inputs)
    packed['task_context']['project_rules'] = copy.deepcopy(inputs['task_context'].get('project_rules', []))
    packed['task_context']['shared_evidence'] = pool
    packed['task_context']['shared_evidence_encoding'] = (
        'EDA_SHARED_REF is lossless shared JSON, NOT missing evidence or a file link. '
        'Replace each object whose sole key is EDA_SHARED_REF with the matching value in task_context.shared_evidence; '
        'recursively resolve nested references before reading the evidence or EDA_COLUMNAR_1 grids. '
        'All referenced values are supplied here. Expanded logical paths in artifact locators are unchanged. '
        'All numbers, rows, flags, source identities and limitations round-trip exactly. No Rules are encoded or changed.')
    return packed


def evidence_refs(root):
    root = Path(root)
    refs = {}
    for stage in STAGES:
        receipt = read_json(root/(stage+'.receipt.json'))
        cb.check_refs(receipt['outputs'])
        refs.update({stage+':'+k: v for k, v in receipt['outputs'].items()})
        refs[stage+':receipt'] = cb.file_ref(root/(stage+'.receipt.json'))
    ep.verify_request(read_json(root/'EP/accepted/ec_request.json'))
    return refs


def human_packet(root):
    root = Path(root)
    refs = evidence_refs(root)
    review = read_json(root/'ER/output.json')
    findings = read_json(root/'EI/output.json')
    plan = read_json(root/'EP/accepted/resolved_plan.json')
    upstream = read_json(root/'EP/prepared/request.json')['payload']['data_handoff']
    display_review = read_json(root/'EP_FINALIZE/output.json')
    open_items = list(dict.fromkeys(findings['open_items'] + display_review['open_items'] +
        [d['task_id'] + ': graphical display deferred; ' + d['reason']
         for d in display_review['task_decisions'] if d['decision'] == 'DEFER']))
    packet = {'version': 'EDA_HUMAN_PACKET_1.0', 'status': 'WAITING_FOR_HUMAN_REVIEW',
        'bindings': refs, 'review_decision': review['decision'],
        'summary': {'findings': findings['findings'], 'limitations': findings['limitations'],
                    'open_items': open_items, 'issues': review['issues'],
                    'unreviewed_items': review['unreviewed_items'],
                    'deferred_analyses': [a for a in plan['analyses'] if a['status'] != 'PLANNED'],
                    'post_ec_display_review': read_json(root/'EP_FINALIZE/output.json'),
                    'upstream_open_items': {key: upstream[key] for key in ['unknowns', 'unresolved_items', 'unresolved_ledger', 'accepted_limitations'] if key in upstream}},
        'human_confirmation': None, 'scientific_release': False, 'fit_ready': False,
        'handoff_eligible_after_human_confirmation': review['decision'] == 'PASS'}
    packet['content_sha256'] = digest(packet)
    write_json(root/'human_review.json', packet)
    esc = html.escape
    lines = ['<!doctype html><html lang="en"><meta charset="utf-8"><title>EDA human review</title>',
        '<style>body{max-width:1100px;margin:30px auto;font:16px/1.6 system-ui;padding:24px}section{padding:18px;border:1px solid #ccd4df;margin:14px 0}pre{white-space:pre-wrap}img{max-width:100%}</style>',
        '<h1>EDA — human review</h1><p>No human approval or downstream launch has occurred.</p>',
        '<p>Independent review: <b>'+esc(review['decision'])+'</b>. The model reviewed supplied text and rows; rendered images still require human inspection.</p>']
    for f in findings['findings']:
        lines.append('<section><h2>'+esc(', '.join(f['analysis_ids']))+'</h2><p>'+esc(f['observation'])+'</p><p>'+esc(f['downstream_implication'])+'</p></section>')
    for key, values in [('Limitations', findings['limitations']), ('Open items', packet['summary']['open_items']), ('Unreviewed evidence', review['unreviewed_items'])]:
        lines.append('<h2>'+key+'</h2><ul>'+''.join('<li>'+esc(v)+'</li>' for v in values)+'</ul>')
    for issue in review['issues']:
        lines.append('<section><b>'+esc(issue['affected_artifact'])+'</b><p>'+esc(issue['consequence'])+'</p><p>'+esc(issue['smallest_correction'])+'</p></section>')
    display_review = packet['summary']['post_ec_display_review']
    lines.append('<h2>Post-calculation display review</h2><p>'+esc(display_review['summary'])+'</p>')
    for item in display_review['task_decisions']:
        if item['decision'] == 'KEEP':
            continue
        lines.append('<p><b>'+esc(item['task_id']+' — '+item['decision'])+'</b>: '+esc(item['reason'])+'</p>')
    for a in packet['summary']['deferred_analyses']:
        lines.append('<section><h2>Deferred: '+esc(a['analysis_id'])+'</h2><p>'+esc(a['question'])+'</p><p>'+esc(a['reason'])+'</p></section>')
    ev = read_json(root/'EV/visualization_bundle.json')
    for item in ev['artifacts']:
        lines.append('<p><a href="EV/'+esc(item['table'], quote=True)+'">'+esc(item['task_id'])+' — source table, plot and notes</a></p>')
    lines.append('<p><a href="human_review.json">Bound review packet</a> · <a href="EP/accepted/resolved_plan.json">EP plan</a> · <a href="EI/output.json">Findings JSON</a> · <a href="ER/output.json">Independent review JSON</a></p>')
    (root/'report.html').write_text('\n'.join(lines), encoding='utf-8')
    return packet


def confirm(root, decision_path):
    """Consume an explicit external human decision, never synthesize one."""
    root = Path(root)
    require(not (root/'eda_handoff.json').exists(), 'handoff already exists')
    packet = read_json(root/'human_review.json')
    if packet.get('version')=='EDA_QUESTION_HUMAN_PACKET_1':
        from .eda_review_handoff import confirm as confirm_question_packet
        return confirm_question_packet(root,decision_path)
    expected = packet.pop('content_sha256')
    require(digest(packet) == expected, 'changed human packet')
    require(evidence_refs(root) == packet['bindings'], 'reviewed evidence changed')
    decision_ref = cb.file_ref(decision_path)
    decision = read_json(decision_path)
    require(decision.get('actor_type') == 'HUMAN' and bool(decision.get('reviewer')) and bool(decision.get('reviewed_at')),
            'explicit identified human decision required')
    require(decision.get('packet_sha256') == expected and decision.get('decision') == 'APPROVE_DESCRIPTIVE_EDA', 'decision is not for this packet')
    require(packet['review_decision'] == 'PASS', 'unresolved ER review cannot be approved by this handoff path')
    require(decision.get('images_inspected') is True and decision.get('limitations_acknowledged') is True,
            'human visual inspection and limitation acknowledgement required')
    require(decision.get('accepted_unreviewed_items') == packet['summary']['unreviewed_items'], 'unreviewed scope not explicitly acknowledged')
    require(decision.get('accepted_open_items') == packet['summary']['open_items'], 'open scope not explicitly acknowledged')
    require(decision.get('accepted_deferred_analysis_ids') == [a['analysis_id'] for a in packet['summary']['deferred_analyses']], 'deferred scope not explicitly acknowledged')
    cb.check_refs(packet['bindings']); cb.check_refs({'human': decision_ref})
    handoff = {'version': 'EDA_DESCRIPTIVE_HANDOFF_1.0', 'review_ref': cb.file_ref(root/'ER/output.json'),
        'human_confirmation_ref': decision_ref, 'input_refs': packet['bindings'],
        'scoped_contexts': {'scope': 'REVIEWED_DESCRIPTIVE_EDA_ONLY', 'findings_ref': cb.file_ref(root/'EI/output.json')},
        'not_calculable': packet['summary']['deferred_analyses'], 'accepted_limitations': packet['summary']['limitations'],
        'open_items': {'eda': packet['summary']['open_items'], 'data': packet['summary']['upstream_open_items']},
        'scientific_release': False, 'fit_ready': False, 'downstream_started': False}
    write_json(root/'eda_handoff.json', handoff)
    return handoff


def verify_rendered(source, existing_inputs):
    """Verify the completed prefix; never migrate or rebind model responses."""
    source = Path(source)
    status = read_json(source/'status.json')
    require(status['bindings']['existing_inputs'] == cb.file_ref(existing_inputs), 'completed stages belong to different inputs')
    pre_dispatch_failure = status['status'] == 'FAILED' and status['stage'] == 'EI'
    require(status['status'] == 'STOPPED_AFTER_EV' or pre_dispatch_failure, 'only a completed render boundary may be imported')
    if pre_dispatch_failure:
        ledger = read_json(source/'model_calls/session.json')
        require(not any(c['route'] in {'eda.findings','eda.review'} for c in ledger['calls']), 'cannot replay prior or uncertain EI/ER dispatch')
        require(not (source/'EI/output.json').exists(), 'EI output already exists')
    for stage in RENDER_PREFIX:
        receipt = read_json(source/(stage+'.receipt.json'))
        require(receipt['stage'] == stage and receipt['status'] == 'COMPLETE', 'incomplete reused stage')
        cb.check_refs(receipt['outputs'])
        actual = {str(p.relative_to(source/stage)).replace('\\', '/'): cb.file_ref(p)
                  for p in (source/stage).rglob('*') if p.is_file()}
        require(actual == receipt['outputs'], 'reused stage file inventory changed')
    frozen = read_json(source/'EP/accepted/ec_request.json')
    ep.verify_request(frozen)
    require(frozen['tasks'] == ep.verified(read_json(source/'EC/calculation_bundle.json')['result'])['tasks'],
            'reused EC changed source records')


def import_rendered(source, root, existing_inputs):
    verify_rendered(source, existing_inputs)
    for stage in RENDER_PREFIX:
        target = root/stage
        require(not target.exists(), 'completed stage import would overwrite files')
        old = read_json(source/(stage+'.receipt.json'))
        shutil.copytree(source/stage, target)
        outputs = {str(p.relative_to(target)).replace('\\', '/'): cb.file_ref(p)
                   for p in sorted(target.rglob('*')) if p.is_file()}
        require({k:v['sha256'] for k,v in outputs.items()} ==
                {k:v['sha256'] for k,v in old['outputs'].items()}, 'completed stage copy differs')
        write_json(root/(stage+'.receipt.json'), {**old, 'outputs': outputs,
            'reused_from_receipt': cb.file_ref(source/(stage+'.receipt.json')),
            'execution_repeated': False, 'elapsed_seconds': 0,
            'original_elapsed_seconds': old['elapsed_seconds']})
    verify_rendered(source, existing_inputs)


def verify_calculated(source, existing_inputs):
    """Only resume a pre-dispatch finalizer failure, never a failed model call."""
    source = Path(source)
    state = read_json(source/'status.json')
    require(state['bindings']['existing_inputs'] == cb.file_ref(existing_inputs), 'EC reuse belongs to different Data')
    require(state['status'] == 'FAILED' and state['stage'] == 'EP_FINALIZE', 'not a pre-finalizer EC boundary')
    ledger = read_json(source/'model_calls/session.json')
    require(not ledger['calls'], 'EC boundary reuse cannot repeat prior or uncertain model dispatches')
    require(not (source/'EP_FINALIZE/output.json').exists(), 'finalizer response already exists')
    for stage in ('EP', 'EC'):
        receipt = read_json(source/(stage+'.receipt.json'))
        require(receipt['stage'] == stage and receipt['status'] == 'COMPLETE', 'incomplete calculated stage')
        cb.check_refs(receipt['outputs'])
        actual = {str(p.relative_to(source/stage)).replace('\\','/'): cb.file_ref(p)
                  for p in (source/stage).rglob('*') if p.is_file()}
        require(actual == receipt['outputs'], 'calculated stage inventory changed')
    frozen = read_json(source/'EP/accepted/ec_request.json')
    ep.verify_request(frozen)
    require(ep.verified(read_json(source/'EC/calculation_bundle.json')['request']) == frozen, 'EC request mismatch')
    require(ep.verified(read_json(source/'EC/calculation_bundle.json')['result'])['tasks'] == frozen['tasks'], 'EC source task mismatch')


def import_calculated(source, root, existing_inputs):
    verify_calculated(source, existing_inputs)
    for stage in ('EP', 'EC'):
        target = root/stage
        require(not target.exists(), 'calculated import would overwrite output')
        old = read_json(source/(stage+'.receipt.json'))
        shutil.copytree(source/stage, target)
        outputs = {str(p.relative_to(target)).replace('\\','/'): cb.file_ref(p)
                   for p in sorted(target.rglob('*')) if p.is_file()}
        require({k:v['sha256'] for k,v in outputs.items()} == {k:v['sha256'] for k,v in old['outputs'].items()}, 'calculated copy differs')
        write_json(root/(stage+'.receipt.json'), {**old, 'outputs': outputs,
            'reused_from_receipt': cb.file_ref(source/(stage+'.receipt.json')),
            'execution_repeated': False, 'elapsed_seconds': 0, 'original_elapsed_seconds': old['elapsed_seconds']})
    verify_calculated(source, existing_inputs)


def run(existing_inputs, out, *, model=None, until='ER', saved_ep=None, previous_handler=None, completed_run=None, saved_ei=None, calculated_run=None):
    require(until in STAGES, 'unknown stopping stage')
    root = Path(out).resolve(); root.mkdir(parents=True, exist_ok=True)
    bindings = {'runner': cb.file_ref(__file__), 'existing_inputs': cb.file_ref(existing_inputs)}
    if calculated_run is not None:
        require(completed_run is None and saved_ep is None and saved_ei is None and previous_handler is None, 'EC reuse cannot rebuild prior stages')
        calculated_run = Path(calculated_run).resolve()
        require(calculated_run != root, 'EC continuation needs a new directory')
        verify_calculated(calculated_run, existing_inputs)
        for name in ('status.json', 'model_calls/session.json', 'EP.receipt.json', 'EC.receipt.json'):
            bindings['calculated:'+name] = cb.file_ref(calculated_run/name)
    if saved_ei is not None:
        require(completed_run is not None, 'saved EI requires a verified completed EP/EC/EV prefix')
        saved_ei = Path(saved_ei).resolve()
        bindings.update(saved_ei_output=cb.file_ref(saved_ei/'output.json'),
                        saved_ei_request=cb.file_ref(saved_ei/'prepared/request.json'),
                        saved_ei_manifest=cb.file_ref(saved_ei/'prepared/context_manifest.json'))
    if completed_run is not None:
        require(saved_ep is None and previous_handler is None, 'completed reuse must not also rebuild EP')
        completed_run = Path(completed_run).resolve()
        require(completed_run != root, 'completed reuse requires a separate continuation directory')
        verify_rendered(completed_run, existing_inputs)
        bindings['completed_status'] = cb.file_ref(completed_run/'status.json')
        for stage in RENDER_PREFIX:
            bindings['completed_'+stage] = cb.file_ref(completed_run/(stage+'.receipt.json'))
    if saved_ep is not None:
        saved_ep = Path(saved_ep)
        bindings.update(saved_ep_response=cb.file_ref(saved_ep/'output.json'),
                        saved_ep_request=cb.file_ref(saved_ep/'prepared/request.json'),
                        saved_ep_manifest=cb.file_ref(saved_ep/'prepared/context_manifest.json'))
    if previous_handler is not None:
        require(saved_ep is not None, 'handler migration requires an explicit saved EP')
        bindings['previous_handler'] = cb.file_ref(previous_handler)
    lock = root/'workflow.lock'
    with lock.open('x', encoding='utf-8') as stream:
        stream.write(utcnow())
    try:
        state_path = root/'status.json'
        if state_path.exists():
            prior = read_json(state_path)
            require(prior['bindings'] == bindings, 'run belongs to different inputs or code')
            require(prior['status'] not in {'RUNNING', 'FAILED', 'REVIEW_REQUIRED'}, 'previous failed/uncertain/flagged run retained; no automatic retry')
        state = {'status': 'RUNNING', 'bindings': bindings, 'stage': None, 'automatic_retries': 0,
                 'automatic_patches': 0, 'requested_model': model, 'scientific_release': False}
        if completed_run is not None and not state_path.exists():
            import_rendered(completed_run, root, existing_inputs)
        if calculated_run is not None and not state_path.exists():
            import_calculated(calculated_run, root, existing_inputs)
        with LinearSession(root/'model_calls', bindings).activate():
            for stage in STAGES:
                cb.check_refs(bindings)
                state['stage'] = stage
                receipt_path = root/(stage+'.receipt.json')
                if receipt_path.exists():
                    cb.check_refs(read_json(receipt_path)['outputs'])
                    if stage == until: break
                    continue
                state['status'] = 'RUNNING'; write_json(state_path, state)
                started = time.perf_counter()
                folder = root/stage
                if stage == 'EP':
                    migration = None
                    if saved_ep is None:
                        bundle = ep.prepare(existing_inputs)
                    else:
                        bundle = {'request': read_json(saved_ep/'prepared/request.json'),
                                  'context_manifest': read_json(saved_ep/'prepared/context_manifest.json')}
                        if previous_handler is None:
                            cb.verify_bundle(bundle)
                        else:
                            old = bundle
                            require(digest(old['request']['payload']) == old['request']['request_sha256'], 'changed original request')
                            old_bindings = old['context_manifest']['input_bindings']
                            old_handler = old['request']['payload']['eda_context_bindings']['ep:source_handler']
                            require(bindings['previous_handler']['sha256'] == old_handler['sha256'], 'previous handler snapshot does not match original EP')
                            cb.check_refs({k: v for k, v in old_bindings.items() if k != 'ep:source_handler'})
                            bundle = ep.prepare(existing_inputs)
                            old_payload = copy.deepcopy(old['request']['payload'])
                            new_payload = copy.deepcopy(bundle['request']['payload'])
                            old_refs = old_payload.pop('eda_context_bindings')
                            new_refs = new_payload.pop('eda_context_bindings')
                            require(old_payload == new_payload, 'saved EP scientific context changed; cannot migrate')
                            require({k:v for k,v in old_refs.items() if k != 'ep:source_handler'} ==
                                    {k:v for k,v in new_refs.items() if k != 'ep:source_handler'}, 'migration changes more than the R handler')
                            migration = {'kind': 'EXPLICIT_R_HANDLER_MIGRATION_WITH_IDENTICAL_SCIENTIFIC_INPUT',
                                'original_request_sha256': old['request']['request_sha256'],
                                'execution_request_sha256': bundle['request']['request_sha256'],
                                'original_handler': old_handler, 'snapshot': bindings['previous_handler'],
                                'execution_handler': new_refs['ep:source_handler'],
                                'old_request_modified': False, 'model_resampled': False}
                        require(bundle['request']['payload']['eda_context_bindings']['ep:existing_inputs'] == bindings['existing_inputs'],
                                'saved EP belongs to different Data input')
                    cb.save_bundle(folder/'prepared', bundle)
                    raw = (providers.codex_generate(bundle['request'], model=model, timeout=None,
                        cli_schema=strict_schema(bundle['request']['payload']['schema'])) if saved_ep is None else read_json(saved_ep/'output.json'))
                    write_json(folder/'output.raw.json', raw)
                    mapped, changes = reconcile_ep(raw)
                    write_json(folder/'output.json', mapped)
                    write_json(folder/'reconciliation.json', {'origin': 'SAVED_RESPONSE' if saved_ep else 'CURRENT_MODEL_RESPONSE',
                        'original_request_sha256': migration['original_request_sha256'] if migration else bundle['request']['request_sha256'],
                        'handler_migration': migration,
                        'raw_ref': cb.file_ref(folder/'output.raw.json'), 'changes': changes,
                        'new_model_call_for_reconciliation': False, 'scientific_approval': False})
                    accepted = ep.accept(folder/'output.json', bundle, folder/'accepted')
                    require(accepted['status'] == 'CONTRACT_VALID', 'EP contract errors: '+str(accepted.get('errors')))
                    _, catalog, _, _ = ep.load_inputs(existing_inputs)
                    flags = eda_ep_quality.check(mapped, catalog)
                    write_json(folder/'scope_check.json', flags)
                    if flags['flags']:
                        state.update(status='REVIEW_REQUIRED', issues=flags['flags'])
                        write_json(state_path, state)
                        return state
                elif stage == 'EC':
                    eda_ec.execute(read_json(root/'EP/accepted/ec_request.json'), folder)
                elif stage == 'EP_FINALIZE':
                    eda_post_ec.run(root, folder, model=model)
                elif stage == 'EV':
                    eda_post_ec.render(root, folder)
                else:
                    inputs = review_inputs(root, stage)
                    prior_refs = {}
                    for previous in STAGES[:STAGES.index(stage)]:
                        receipt = read_json(root/(previous+'.receipt.json'))
                        cb.check_refs(receipt['outputs'])
                        prior_refs[previous+':receipt'] = cb.file_ref(root/(previous+'.receipt.json'))
                    bundle = eda_context.prepare(stage+('-findings' if stage == 'EI' else '-review'),
                        pack_review_inputs(inputs), response_schema(stage, inputs), input_bindings=prior_refs)
                    cb.save_bundle(folder/'prepared', bundle)
                    if stage == 'EI' and saved_ei is not None:
                        old = {'request': read_json(saved_ei/'prepared/request.json'),
                               'context_manifest': read_json(saved_ei/'prepared/context_manifest.json')}
                        cb.verify_bundle(old)
                        before = copy.deepcopy(old['request']['payload'])
                        after = copy.deepcopy(bundle['request']['payload'])
                        before.pop('eda_context_bindings'); after.pop('eda_context_bindings')
                        # Only relax the two conditionally applicable text fields.
                        # No source, Rule, reference enum or substantive contract changes.
                        for key in ['interpretation_if_useful', 'alternative_if_interpretation']:
                            before['schema']['properties']['findings']['items']['properties'][key].pop('minLength', None)
                        require(before == after, 'saved EI scientific inputs or contract changed')
                        raw = read_json(saved_ei/'output.json')
                        write_json(folder/'reused_response.json', {
                            'original_request': bindings['saved_ei_request'], 'original_response': bindings['saved_ei_output'],
                            'scientific_context_identical': True, 'response_modified': False, 'new_model_call': False,
                            'schema_transition': 'Optional interpretation/alternative strings may be empty; a stated interpretation still requires a nonempty alternative.'})
                    else:
                        raw = providers.codex_generate(bundle['request'], model=model, timeout=None,
                            cli_schema=strict_schema(bundle['request']['payload']['schema']))
                    write_json(folder/'output.json', raw)
                    cb.verify_bundle(bundle)
                    for previous in STAGES[:STAGES.index(stage)]:
                        cb.check_refs(read_json(root/(previous+'.receipt.json'))['outputs'])
                    validate_output(stage, raw, inputs)
                cb.check_refs(bindings)
                outputs = {str(p.relative_to(folder)).replace('\\', '/'): cb.file_ref(p)
                           for p in sorted(folder.rglob('*')) if p.is_file()}
                write_json(receipt_path, {'stage': stage, 'status': 'COMPLETE', 'outputs': outputs,
                    'elapsed_seconds': round(time.perf_counter()-started, 3), 'scientific_approval': False})
                if stage == until: break
        if until == 'ER':
            packet = human_packet(root)
            state['status'] = 'WAITING_FOR_HUMAN_REVIEW' if packet['review_decision'] == 'PASS' else 'REVIEW_REQUIRED'
        else:
            state['status'] = 'STOPPED_AFTER_'+until
        write_json(root/'status.json', state)
        return state
    except BaseException as exc:
        if 'state' in locals():
            state.update(status='FAILED', error=str(exc)); write_json(root/'status.json', state)
        raise
    finally:
        lock.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('run'); p.add_argument('--inputs', required=True); p.add_argument('--out', required=True)
    p.add_argument('--model'); p.add_argument('--until', choices=STAGES, default='ER')
    p.add_argument('--saved-ep', help='Explicitly reuse an unchanged bound EP response; never resample it.')
    p.add_argument('--previous-handler', help='Exact prior R handler snapshot for an explicit handler-only migration; scientific inputs must match.')
    p.add_argument('--completed-run', help='Reuse verified EP/EC/EV artifacts without repeating extraction, model or R execution.')
    p.add_argument('--saved-ei', help='Reuse an unchanged EI response with identical scientific inputs; only the optional-text contract transition is supported.')
    p = sub.add_parser('run-questions'); p.add_argument('--inputs', required=True); p.add_argument('--completed-run', required=True); p.add_argument('--catalog', required=True); p.add_argument('--out', required=True); p.add_argument('--model'); p.add_argument('--until', choices=['EV','ER'], default='EV'); p.add_argument('--inheritance-scope', help='Optional hash-bound metadata and DC lineage manifest for selected-table issue scoping.')
    p = sub.add_parser('resume-question-review'); p.add_argument('--inputs', required=True); p.add_argument('--completed-run', required=True); p.add_argument('--catalog', required=True); p.add_argument('--out', required=True); p.add_argument('--previous-adapter', required=True)
    p = sub.add_parser('confirm'); p.add_argument('--run', required=True); p.add_argument('--decision', required=True)
    p = sub.add_parser('assign'); p.add_argument('--run', required=True); p.add_argument('--out'); p.add_argument('--preview', action='store_true')
    args = parser.parse_args()
    if args.command == 'assign':
        from .eda_task_assignment import build as assign_tasks
        print(assign_tasks(args.run, args.out, preview=args.preview)); return
    if args.command == 'resume-question-review':
        from .eda_questions import resume_question_review
        print(resume_question_review(args.inputs,args.completed_run,args.catalog,args.out,args.previous_adapter)); return
    if args.command == 'run-questions':
        from .eda_questions_v6 import run_questions
        print(run_questions(args.inputs,args.completed_run,args.catalog,args.out,model=args.model,until=args.until,inheritance_scope=args.inheritance_scope)); return
    result = run(args.inputs, args.out, model=args.model, until=args.until, saved_ep=args.saved_ep, previous_handler=args.previous_handler, completed_run=args.completed_run, saved_ei=args.saved_ei) if args.command == 'run' else confirm(args.run, args.decision)
    print(result)


if __name__ == '__main__':
    main()
