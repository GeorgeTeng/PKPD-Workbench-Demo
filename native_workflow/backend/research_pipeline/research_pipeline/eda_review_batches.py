"""Preplanned, disjoint ER image scopes; one call per batch, no retry or repair."""
import copy
from pathlib import Path
from . import context_builder as cb
from .common import read_json, write_json
from . import eda_review_context as rc


def image_manifest(inputs, path):
    images = [{'figure_id': f['figure_id'], 'file': f['image_ref']}
              for f in inputs['figure_bundle']['figures']]
    write_json(path, {'version': 'EDA_IMAGE_INPUTS_1', 'images': images})
    return cb.file_ref(path)


def scope_schema(schema, ids):
    out = copy.deepcopy(schema)
    out['properties']['figure_checks'] = {
        'type': 'array', 'minItems': len(ids), 'maxItems': len(ids), 'items': {
            'type': 'object', 'properties': {
                'figure_id': {'type': 'string', 'enum': list(ids)},
                'inspection': {'type': 'string', 'enum': ['INSPECTED', 'NOT_ASSESSED']},
                'note': {'type': 'string', 'minLength': 1}},
            'required': ['figure_id', 'inspection', 'note'], 'additionalProperties': False}}
    out['required'].append('figure_checks')
    return rc.compact_schema(out)


def plan(inputs, schema, root, bindings, *, max_images=32):
    """Preflight all exact scopes before the first model call. Full sources unchanged."""
    from . import eda_questions_v6 as q
    from . import context_model_view, context_budget
    from ctxcomp import providers
    from ctxcomp.io import canonical
    root = Path(root); root.mkdir(parents=True, exist_ok=False)
    original = {f['figure_id']: f for f in inputs['figure_bundle']['figures']}
    queue = rc.review_groups(inputs, max_images)
    prepared = []
    while queue:
        order = {fid: i for i, fid in enumerate(original)}
        ids = sorted(queue.pop(0), key=order.get)
        sub = rc.review_slice(inputs, ids)
        idx = len(prepared) + 1
        image_ref = image_manifest(sub, root / f'images_{idx:03d}.json')
        local = {**bindings, 'eda_image_manifest': image_ref}
        for f in sub['figure_bundle']['figures']: f['image_supplied_to_model'] = True
        sub['task_context']['question_driven_contract']['current_stage_evidence'] = q.quality.stage_evidence('ER', sub)
        sch = scope_schema(schema, ids)
        try:
            bundle = q.prepare_bundle('ER-review', sub, sch, local)
            visible, _ = context_model_view.project(bundle['request'])
            budget = context_budget.check(providers.PROMPT + canonical(visible), q.strict_schema(sch))
            if bundle['context_manifest']['request_characters'] > 650000:
                raise ValueError('Batch headroom exceeded')
        except Exception as exc:
            if not ('capacity' in str(exc).lower() or 'budget' in str(exc).lower() or 'headroom' in str(exc).lower()): raise
            if len(ids) == 1: raise ValueError('One-image ER scope still exceeds budget; no evidence was truncated') from exc
            mid = len(ids)//2; queue[0:0] = [ids[:mid], ids[mid:]]
            continue
        prepared.append({'batch_id': f'ER_{idx:03d}', 'figure_ids': ids,
                         'dataset_ids': sub['task_context']['review_scope']['dataset_ids'],
                         'inputs': sub, 'schema': sch, 'images_ref': image_ref,
                         'preview_chars': bundle['context_manifest']['request_characters'],
                         'transport_budget': budget})
    seen = [fid for b in prepared for fid in b['figure_ids']]
    if len(seen) != len(set(seen)) or set(seen) != set(original):
        raise ValueError('ER partition dropped or repeated an image')
    source_ids = {t['dataset_id'] for t in inputs['data_handoff']['admitted_evidence']}
    covered = set().union(*(set(b['dataset_ids']) for b in prepared))
    if covered != source_ids: raise ValueError('ER partition did not carry every source table in full at least once')
    manifest = {'version': 'ER_REVIEW_PARTITION_1', 'stage': 'ER-review',
        'all_figure_ids': list(original), 'all_dataset_ids': sorted(source_ids),
        'images': {fid: original[fid]['image_ref'] for fid in original},
        'source_bindings': bindings, 'automatic_retries': 0, 'max_images_per_call': max_images,
        'batches': [{k: b[k] for k in ('batch_id', 'figure_ids', 'dataset_ids')} for b in prepared]}
    write_json(root/'partition.json', manifest); manifest_ref = cb.file_ref(root/'partition.json')
    for b in prepared:
        scope = next(x for x in manifest['batches'] if x['batch_id'] == b['batch_id'])
        b['inputs']['task_context']['review_batch'] = scope
        local = {**bindings, 'eda_image_manifest': b['images_ref'], 'eda_review_batch_manifest': manifest_ref}
        bundle = q.prepare_bundle('ER-review', b['inputs'], b['schema'], local)
        cb.save_bundle(root/b['batch_id'], bundle)
        visible, _ = context_model_view.project(bundle['request'])
        budget = context_budget.check(providers.PROMPT + canonical(visible), q.strict_schema(b['schema']))
        write_json(root/b['batch_id']/'transport_budget.json', budget)
        b['request_characters'] = bundle['context_manifest']['request_characters']
    write_json(root/'summary.json', {'batches': len(prepared), 'figures': len(original), 'datasets': len(source_ids),
        'source_records_preserved': True, 'rules_unchanged': True, 'model_calls': 0,
        'batch_details': [{k:b[k] for k in ('batch_id','figure_ids','dataset_ids','request_characters')} for b in prepared]})
    return prepared, manifest_ref


def validate_scope(payload):
    scope = payload.get('task_context', {}).get('review_batch')
    if not scope: return None
    if payload.get('stage') != 'ER-review': raise ValueError('Only ER may use image review partitions')
    ref = payload.get('eda_context_bindings', {}).get('eda_review_batch_manifest')
    if not ref: raise ValueError('Review partition is not host-bound')
    cb.check_refs({'partition': ref}); manifest = read_json(ref['path'])
    all_ids = [i for b in manifest['batches'] for i in b['figure_ids']]
    if manifest['version'] != 'ER_REVIEW_PARTITION_1' or len(all_ids) != len(set(all_ids)) or set(all_ids) != set(manifest['all_figure_ids']):
        raise ValueError('Invalid disjoint image partition')
    expected = next((b for b in manifest['batches'] if b['batch_id'] == scope['batch_id']), None)
    if scope != expected: raise ValueError('Review scope differs from frozen partition')
    # The image transport verifies each immutable image independently.
    actual = payload.get('transport_scope', {}).get('images', [])
    if [i['figure_id'] for i in actual] != scope['figure_ids']:
        raise ValueError('Attached images differ from frozen batch')
    if any(i['file'] != manifest['images'].get(i['figure_id']) for i in actual):
        raise ValueError('Attached image binding differs from frozen partition')
    bindings = payload['eda_context_bindings']
    if any(bindings.get(k) != ref for k, ref in manifest['source_bindings'].items()):
        raise ValueError('Batch source bindings differ from frozen partition')
    return {'manifest': ref, 'figure_ids': scope['figure_ids'], 'batch_id': scope['batch_id']}


def merge(reviews, batches):
    from . import eda_quality_checks_v3 as quality
    if len(reviews) != len(batches): raise ValueError('Incomplete ER batch results')
    issues, unreviewed, reviewed, checks = [], [], [], []
    for raw, batch in zip(reviews, batches):
        quality.validate_review(raw)
        ids = [c['figure_id'] for c in raw['figure_checks']]
        if len(ids) != len(set(ids)) or set(ids) != set(batch['figure_ids']):
            raise ValueError('ER figure inspection accounting incomplete')
        for item in raw['issues']:
            issues.append({**item, 'issue_id': batch['batch_id'] + ':' + item['issue_id']})
        unreviewed.extend(batch['batch_id'] + ': ' + item for item in raw['unreviewed_items'])
        unreviewed.extend(c['figure_id'] + ': ' + c['note'] for c in raw['figure_checks'] if c['inspection'] != 'INSPECTED')
        reviewed.extend(raw['reviewed_refs']); checks.append(raw['quality_checks'])
    def worst(values):
        return 'REVISE' if 'REVISE' in values else 'NOT_ASSESSED' if 'NOT_ASSESSED' in values else 'PASS'
    qc = {k: worst([c[k] for c in checks]) for k in checks[0]}
    decisions = [r['decision'] for r in reviews]
    decision = 'REVISE' if issues or 'REVISE' in decisions or 'REVISE' in qc.values() else (
        'NEEDS_REVIEW' if unreviewed or 'NEEDS_REVIEW' in decisions or 'NOT_ASSESSED' in qc.values() else 'PASS')
    return {'version': 'QUESTION_REVIEW_1', 'reviewed_refs': list(dict.fromkeys(reviewed)),
        'decision': decision, 'review_scope': 'Independent ER review across disjoint, preplanned image scopes; all selected images and source tables accounted for. Batch results combined deterministically without a model rewrite. Human review still required.',
        'issues': issues, 'unreviewed_items': list(dict.fromkeys(unreviewed)), 'quality_checks': qc}


def execute(inputs, schema, root, bindings, call_once):
    root = Path(root)
    if (root/'ER').exists(): raise ValueError('ER artifacts already exist; no automatic repeat')
    batches, ref = plan(inputs, schema, root/'ER/preflight', bindings)
    results = []
    for b in batches:
        raw = call_once('ER/' + b['batch_id'], 'ER-review', b['inputs'], b['schema'], root,
                        {**bindings, 'eda_review_batch_manifest': ref})
        results.append(raw)
        # Stop before the next call if this result is structurally inconsistent.
        merge([raw], [b])
    result = merge(results, batches)
    write_json(root/'ER/output.json', result)
    write_json(root/'ER/aggregation.json', {'method': 'DETERMINISTIC_ALL_BATCHES', 'partition_ref': ref,
        'batch_outputs': [cb.file_ref(root/'ER'/b['batch_id']/'output.json') for b in batches],
        'model_calls': len(batches), 'automatic_retries': 0, 'human_approval': False})
    return result
