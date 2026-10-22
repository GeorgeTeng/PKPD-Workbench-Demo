"""Bounded EI/ER context assembly. No scientific editing, retrieval or model calls."""
import copy
import json
from collections import Counter


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def compact_schema(schema):
    """Factor identical JSON Schema nodes, preserving the full validation language."""
    if '$defs' in schema:
        return copy.deepcopy(schema)
    counts = Counter()
    def children(node):
        for key in ('properties', 'patternProperties'):
            for child in node.get(key, {}).values():
                yield child
        for key in ('items', 'contains', 'not', 'if', 'then', 'else', 'additionalProperties'):
            if isinstance(node.get(key), dict): yield node[key]
        for key in ('anyOf', 'oneOf', 'allOf', 'prefixItems'):
            yield from node.get(key, [])
    def count(node):
        if not isinstance(node, dict): return
        key = canonical(node)
        if len(key) >= 160: counts[key] += 1
        for child in children(node): count(child)
    count(schema)
    definitions, names = {}, {}
    def factor(node, root=False):
        if not isinstance(node, dict): return copy.deepcopy(node)
        key = canonical(node)
        if not root and counts[key] > 1:
            if key not in names:
                names[key] = 'S' + str(len(names) + 1)
                definitions[names[key]] = factor(node, True)
            return {'$ref': '#/$defs/' + names[key]}
        out = copy.deepcopy(node)
        for k in ('properties', 'patternProperties'):
            if k in out: out[k] = {a: factor(b) for a, b in out[k].items()}
        for k in ('items', 'contains', 'not', 'if', 'then', 'else', 'additionalProperties'):
            if isinstance(out.get(k), dict): out[k] = factor(out[k])
        for k in ('anyOf', 'oneOf', 'allOf', 'prefixItems'):
            if k in out: out[k] = [factor(v) for v in out[k]]
        return out
    result = factor(schema, True)
    if definitions: result['$defs'] = definitions
    def expand(node):
        if isinstance(node, dict) and set(node) == {'$ref'}:
            return expand(definitions[node['$ref'].split('/')[-1]])
        if isinstance(node, dict): return {k: expand(v) for k, v in node.items() if k != '$defs'}
        if isinstance(node, list): return [expand(v) for v in node]
        return node
    if expand(result) != schema: raise ValueError('Schema factoring changed validation constraints')
    return result


def prepare_inputs(call_id, inputs):
    """Remove only obsolete planning instructions; retain every scientific object."""
    out = copy.deepcopy(inputs)
    if call_id not in {'EI-findings', 'ER-review'}: return out
    task = out['task_context']
    if task.get('review_stage_scope', {}).get('operation') == call_id:
        return out
    contract = task['question_driven_contract']
    # Inventory is a candidate-selection catalog, superseded by the exact final
    # coverage ledger. Keep scale requirements/policies and all evidence intact.
    removed = {}
    for parent, key, loc in [(task, 'execution_registry_note', 'task_context'),
                             (task, 'implemented_r_operations', 'task_context'),
                             (contract, 'instruction', 'question_driven_contract'),
                             (contract, 'dataset_display_inventory', 'question_driven_contract')]:
        if key in parent:
            removed[loc + '.' + key] = parent.pop(key)
    task['implemented_r_operations'] = []  # Review has no execution operation.
    task['review_stage_scope'] = {
        'operation': call_id,
        'instruction': 'Interpret/review completed evidence only. Do not select new plots, execute R, re-extract data, rewrite EP or change data. The final plan and actual dataset_display_coverage replace the historical candidate-selection inventory. Scale policies, required scales, scientific Rules, source records and limitations remain supplied.',
        'omitted_operational_fields': sorted(removed),
    }
    return out


def summary_inputs(inputs):
    """EI packages existing dispositions and limits; it does not inspect new data.

    The original full evidence remains in the caller's immutable package for ER.
    Source identities, project Rules, existing assessments and unresolved items
    stay literal. Detailed source columns/notes, numerical records and rendering
    recipes belong to ER; EI may only summarize the already recorded limits.
    """
    out = prepare_inputs('EI-findings', inputs)
    task = out['task_context']
    task['question_driven_contract']['current_stage_evidence'] = {
        'stage': 'EI', 'generated_image_count': len(out['figure_bundle']['figures']),
        'images_supplied_to_this_call': 0, 'inspection': 'NONE_IN_EI',
        'boundary': 'Handoff summary only; all figure images remain for ER and human review.'}
    if task.get('ei_handoff_summary', {}).get('version') == 'EI_HANDOFF_SUMMARY_1':
        return out
    contract = task['question_driven_contract']
    for key in ('pk_scale_requirements', 'coverage_contract', 'imperfect_data',
                'axis_scale_contract', 'pk_scale_policy', 'presentation_policy',
                'three_quality_checks', 'dataset_handoff_contract'):
        contract.pop(key, None)  # Executed plan / ER scope, not a second planning task.
    contract['review_output'] = (
        'EI is a concise handoff editor. Use the existing dataset dispositions and figure purposes, '
        'host verification and recorded limitations. Group into PK, PD or shared context where useful. '
        'Do not choose or revise destinations, inspect curves, identify new anomalies, compare groups, '
        'choose models or repeat Coverage/Necessity. Describe the affected next action without inventing '
        'a new necessity verdict. Use at most 250 English prose words across findings, limitations and '
        'open_items; prefer 2-4 findings. Cite the supplied dataset or figure IDs. All six question IDs '
        'must be accounted for, but related questions may share one short finding. '
        'All observations are NON_GRAPHICAL summaries of supplied metadata and prior decisions. '
        'The host adds uninspected-figure accounting; ER performs independent picture/evidence review.')
    table_counts = {}
    for t in out['data_handoff']['admitted_evidence']:
        rows = t.pop('records', [])
        table_counts[t['dataset_id']] = len(rows)
        t['record_inventory'] = {'count': len(rows), 'evidence_scope': 'Metadata only in EI; exact source rows remain in the bound EDA package and ER input.'}
        t.pop('columns', None)
        t.pop('notes', None)  # Full notes are for ER; EI uses the recorded issue/readiness ledger.
    # DR definitions, file locators and extraction implementation are not the
    # existing assessment. Keep current readiness, all unresolved items and
    # inherited issues; do not ask EI to derive a second assessment from DR.
    for key in ('task_requirements', 'preparation_evidence', 'metadata_validation',
                'upstream_data', 'operation_catalog', 'inheritance_lineage_refs',
                'inheritance_projector_ref', 'files'):
        out['data_handoff'].pop(key, None)
    for f in out['figure_bundle']['figures']:
        rows = f.pop('plotted_rows', [])
        f['plotted_row_count'] = len(rows)
        f.pop('audit', None)
        f.pop('render_recipe', None)
        f.pop('render_facts', None)  # Reviewed by ER; not interpreted by the handoff editor.
        f.pop('semantic_audit', None)
        f.pop('image_ref', None)
        f['image_supplied_to_model'] = False
    for a in out['eda_plan']['analyses']:
        a['selected_view_ids'] = [v['view_id'] for v in a.pop('views', [])]
    audit = out['eda_plan'].pop('host_plan_accounting', None)
    if audit:
        out['eda_plan']['host_plan_accounting_summary'] = {
            'changes': len(audit.get('changes', [])),
            'review_status': audit['review_status'],
            'detail': 'Exact host restorations remain in the bound resolved plan and ER input.'}
    task['ei_handoff_summary'] = {
        'version': 'EI_HANDOFF_SUMMARY_1',
        'purpose': 'Package existing dataset/figure destinations, intended use and a few material limitations for human review.',
        'routing_authority': 'Existing eda_plan.dataset_dispositions only; the host copies these assignments without model reassignment.',
        'data_and_figure_source': 'figure_bundle.tables.host_file and the existing source-bound figure package; paths are locators, not model-inspected contents.',
        'image_inspection': 'NONE_IN_EI; independent ER and exact-version human review remain required.',
        'source_record_counts': table_counts,
        'forbidden': ['new numerical or visual findings', 'new outlier labels', 'new model advice', 'source changes', 'approval'],
    }
    return out


def summary_schema(schema):
    """Narrow the existing EI artifact to factual handoff summaries, not new analysis."""
    out = copy.deepcopy(schema)
    if 'anyOf' not in out['properties']['findings']['items']:
        return compact_schema(out)
    # Reuse the existing finding fields with explicit non-graphical constants.
    item = copy.deepcopy(out['properties']['findings']['items']['anyOf'][0])
    p = item['properties']
    p['record_scope'] = {'type': 'array', 'items': {'type': 'string'}, 'maxItems': 0}
    p['interpretation_if_useful'] = {'type': 'string', 'enum': ['']}
    p['alternative_if_interpretation'] = {'type': 'string', 'enum': ['']}
    p['observation'] = {'type': 'string', 'minLength': 1, 'maxLength': 420}
    p['downstream_implication'] = {'type': 'string', 'minLength': 1, 'maxLength': 300}
    visual = p['visual_support']['properties']
    visual['status'] = {'type': 'string', 'enum': ['NON_GRAPHICAL']}
    visual['figure_ids'] = {'type': 'array', 'items': {'type': 'string'}, 'maxItems': 0}
    visual['element_claims'] = {'type': 'array', 'items': {'type': 'object', 'properties': {}, 'required': [], 'additionalProperties': False}, 'maxItems': 0}
    visual['features'] = {'type': 'string', 'enum': ['Existing metadata and handoff decisions only; no EI visual inspection.']}
    visual['limitations'] = {'type': 'array', 'items': {'type': 'string'}, 'maxItems': 0}
    p['anomaly_assessment'] = {
        'type': 'object', 'properties': {
            'status': {'type': 'string', 'enum': ['NOT_ASSESSED']},
            'record_ids': {'type': 'array', 'items': {'type': 'string'}, 'maxItems': 0},
            'observation': {'type': 'string', 'enum': ['Not reassessed during handoff packaging.']},
            'possible_explanations': {'type': 'array', 'items': {'type': 'string'}, 'maxItems': 0},
            'recommended_action': {'type': 'string', 'enum': ['Retain existing flags for ER and human review.']},
            'affected_analysis': {'type': 'string', 'enum': ['No new anomaly assessment.']},
            'data_changed': {'const': False}},
        'required': ['status', 'record_ids', 'observation', 'possible_explanations', 'recommended_action', 'affected_analysis', 'data_changed'],
        'additionalProperties': False}
    out['properties']['findings'] = {'type': 'array', 'items': item, 'minItems': 1, 'maxItems': 6}
    for key in ('limitations', 'open_items'):
        out['properties'][key] = {'type': 'array', 'items': {'type': 'string', 'minLength': 1, 'maxLength': 240}, 'maxItems': 6}
    out['properties'].pop('figure_checks', None)
    out['required'] = [k for k in out['required'] if k != 'figure_checks']
    return compact_schema(out)


def complete_summary(raw, figure_ids):
    """Host records that EI did not inspect pictures. Never invent inspection."""
    result = copy.deepcopy(raw)
    if 'figure_checks' in raw: raise ValueError('EI summary must not supply visual inspection claims')
    result['figure_checks'] = [{'figure_id': fid, 'inspection': 'NOT_ASSESSED',
        'note': 'EI packages existing decisions only; image inspection belongs to ER and the human checkpoint.'} for fid in figure_ids]
    return result


def figure_datasets(figure):
    return {r['dataset_id'] for r in figure.get('plotted_rows', []) + figure.get('context_rows', [])}


def review_groups(inputs, max_images=32):
    """Keep figures from the same dataset together; no image repeated per ER stage."""
    figures = inputs['figure_bundle']['figures']
    groups = []
    for f in figures:
        ids = figure_datasets(f)
        touching = [g for g in groups if g['datasets'] & ids]
        group = {'figures': [f['figure_id']], 'datasets': set(ids)}
        for g in touching:
            group['figures'] += g['figures']; group['datasets'] |= g['datasets']; groups.remove(g)
        groups.append(group)
    position = {f['figure_id']: i for i, f in enumerate(figures)}
    for g in groups: g['figures'].sort(key=position.get)
    groups.sort(key=lambda g: min(position[i] for i in g['figures']))
    batches = []
    for g in groups:
        parts = [g['figures'][i:i+max_images] for i in range(0, len(g['figures']), max_images)]
        for part in parts:
            if batches and len(batches[-1]) + len(part) <= max_images:
                batches[-1] += part
            else: batches.append(part)
    return batches


def review_slice(inputs, figure_ids):
    """Materialize complete relevant tables; retain other tables' metadata/limits.

    Full source records of every dataset used by the selected figures are
    included, including unplotted values. This is not a snippet retriever.
    """
    out = prepare_inputs('ER-review', inputs)
    chosen = set(figure_ids)
    all_figures = out['figure_bundle']['figures']
    if not chosen or not chosen <= {f['figure_id'] for f in all_figures}:
        raise ValueError('Empty or unknown image scope')
    selected = [f for f in all_figures if f['figure_id'] in chosen]
    questions = {a for f in selected for a in f['analysis_ids']}
    datasets = set().union(*(figure_datasets(f) for f in selected))
    # Do not pull every study's numerical table just because it shares a broad
    # question such as PK shape. Keep full exact tables for these figures and
    # explicit context rows, plus all other sources' metadata/limitations.
    # Include all unplotted datasets for metadata/table-only review as well.
    plotted = set().union(*(figure_datasets(f) for f in all_figures))
    datasets.update(t['dataset_id'] for t in out['data_handoff']['admitted_evidence'] if t['dataset_id'] not in plotted)
    for t in out['data_handoff']['admitted_evidence']:
        if t['dataset_id'] not in datasets:
            rows = t.pop('records', [])
            t['outside_batch_records'] = {'count': len(rows), 'status': 'REVIEWED_IN_OTHER_BATCH; metadata retained here, no numerical claims from these omitted rows.'}
    out['figure_bundle']['figures'] = selected
    # All EI text remains visible to each reviewer; local rows/images constrain
    # what it may independently verify, not what the other batches concluded.
    out['task_context']['review_scope'] = {
        'figure_ids': list(figure_ids), 'dataset_ids': sorted(datasets),
        'analysis_ids': sorted(questions),
        'boundary': 'Check the supplied images and complete in-scope source/plot rows against the unchanged Rules and EI handoff summary. Other image groups are separate ER tasks, not missing data. Do not claim visual or numerical verification outside this scope. Flag cross-batch comparisons that need joint evidence as unreviewed. The host combines every batch without suppressing issues; no automatic retries.',
    }
    return out
