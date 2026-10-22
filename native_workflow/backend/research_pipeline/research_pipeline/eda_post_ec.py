"""One bounded EP display review after EC; no extraction, calculation or retry."""
import copy
from collections import Counter
from pathlib import Path
from jsonschema import Draft202012Validator
from ctxcomp import providers
from . import context_builder as cb, eda_context, eda_ep_full as ep
from .common import read_json, write_json


def schema(tasks):
    text = {'type': 'string', 'minLength': 1}
    def obj(properties):
        return {'type': 'object', 'properties': properties, 'required': list(properties), 'additionalProperties': False}
    decision = obj({'task_id': {'enum': [t['task_id'] for t in tasks] or ['NO_TASKS']},
        'decision': {'enum': ['KEEP', 'ADJUST', 'DEFER']},
        'operation_id': {'enum': ep.OPERATIONS},
        'selection': obj({'dataset_id': text, 'x': {'type': 'string'}, 'y': {'type': 'string'},
            'group_by': {'type': 'string'}, 'x_scale': {'enum': ['linear', 'log10']},
            'y_scale': {'enum': ['linear', 'log10']}}),
        'reason': text, 'additional_note': {'type': 'string'}})
    return obj({'version': {'enum': ['EP_FINAL_DISPLAYS_1.0']}, 'summary': text,
        'task_decisions': {'type': 'array', 'items': decision, 'minItems': len(tasks), 'maxItems': len(tasks)},
        'open_items': {'type': 'array', 'items': text}})


def task_summary(task):
    """Deterministic metadata from completed EC rows; no statistical inference."""
    statuses = {c['id']: dict(Counter(r['value_status'].get(c['id'], 'ABSENT_STATUS')
                for r in task['records'])) for c in task['columns']}
    summary = {k: copy.deepcopy(v) for k,v in task.items() if k not in {'records'}}
    summary['record_count'] = len(task['records'])
    summary['status_counts'] = statuses
    summary['source_rows_supplied'] = False
    return summary


def share_contexts(tasks):
    """Factor only byte-equivalent repeated analysis context; verify round trip."""
    from ctxcomp.io import canonical
    original = copy.deepcopy(tasks)
    keys = [canonical(t['context']) for t in tasks]
    if len(set(keys)) == len(keys):
        return {'tasks': tasks}
    contexts = {}; identities = {}
    for task, key in zip(tasks, keys):
        if key not in identities:
            identities[key] = 'CONTEXT'+str(len(identities)+1)
            contexts[identities[key]] = task['context']
        task['context_ref'] = identities[key]
        del task['context']
    restored = copy.deepcopy(tasks)
    for task in restored:
        task['context'] = copy.deepcopy(contexts[task.pop('context_ref')])
    ep.require(canonical(restored) == canonical(original), 'shared display context changed evidence')
    return {'tasks': tasks, 'shared_contexts': contexts,
        'context_encoding': 'Each task.context_ref selects its complete context from shared_contexts. Apply that context to that task. No field or rule was dropped; exact round-trip verified.'}


def sources(root):
    root = Path(root)
    paths = {'post_ec:plan': root/'EP/accepted/resolved_plan.json',
             'post_ec:frozen': root/'EP/accepted/ec_request.json',
             'post_ec:initial': root/'EP/prepared/request.json',
             'post_ec:calculation': root/'EC/calculation_bundle.json',
             'post_ec:adapter': Path(__file__)}
    refs = {k: cb.file_ref(p) for k,p in paths.items()}
    frozen = read_json(paths['post_ec:frozen']); ep.verify_request(frozen)
    calculation = read_json(paths['post_ec:calculation'])
    ep.require(ep.verified(calculation['request']) == frozen, 'EC request mismatch')
    actual = ep.verified(calculation['result'])
    ep.require(actual['tasks'] == frozen['tasks'] and actual['computed_statistics'] is False,
               'post-EC review cannot repair changed source results')
    refs['post_ec:result'] = calculation['result']
    return frozen, actual, read_json(paths['post_ec:initial'])['payload'], read_json(paths['post_ec:plan']), refs


def prepare(root):
    frozen, actual, initial, plan, refs = sources(root)
    task_context = copy.deepcopy(initial['task_context'])
    task_context.pop('dataset_catalog', None)
    task_context.pop('ep_plan_contract', None)
    handoff = copy.deepcopy(initial['data_handoff'])
    handoff.pop('reading_views', None)
    from .eda_workflow import compact_grid
    for key, value in list(handoff.items()):
        if isinstance(value, list):
            handoff[key] = compact_grid(value)
    task_context['input_encoding'] = (
        'EDA_COLUMNAR_1 is lossless JSON, not missing data: map rows cells to fields; remove absent_fields for each row; '
        'recursively inherit missing keys from defaults. Decode nested_columns and replace the corresponding placeholders first. '
        'Explicit null/empty values override defaults. Copy copy_from_source_raw_values keys from source_raw_values. '
        'Every original field, value, source binding and restriction is retained; the host verified exact round-trip equivalence.')
    inputs = {'task_context': task_context, 'data_handoff': handoff, 'eda_plan': plan,
        'calculation_bundle': {**share_contexts([task_summary(t) for t in actual['tasks']]),
            'computed_statistics': False, 'source_preservation_checked_by_host': True,
            'evidence_scope': 'All EC task identities, source column descriptions, notes, status counts and exact current plot points. Full source rows are host-bound, not model-visible. No claim of independent full-row review.'}}
    return eda_context.prepare('EP-finalize', inputs, schema(frozen['tasks']), input_bindings=refs)


def apply(response, frozen):
    """Derive presentation tasks, preserving source rows and existing limits."""
    Draft202012Validator(schema(frozen['tasks'])).validate(response)
    decisions = response['task_decisions']
    ep.require([d['task_id'] for d in decisions] == [t['task_id'] for t in frozen['tasks']],
               'display review requires every task exactly once in order')
    result = copy.deepcopy(frozen['tasks'])
    for task, decision in zip(result, decisions):
        selection = decision['selection']; operation = decision['operation_id']
        ep.require(selection['dataset_id'] == task['dataset_id'], 'display review changed dataset')
        keys = {c['id'] for c in task['columns']}
        ep.require(not selection['group_by'] or selection['group_by'] in keys, 'unknown display group')
        if decision['decision'] == 'KEEP':
            ep.require(operation == task['operation_id'] and selection == task['selection'], 'KEEP changed a display')
        if decision['decision'] == 'DEFER':
            ep.require(operation == 'SOURCE_TABLE', 'deferred display requires source-table fallback')
        if operation == 'SOURCE_TABLE':
            ep.require(not any(selection[k] for k in ['x','y','group_by']) and
                       selection['x_scale'] == selection['y_scale'] == 'linear', 'invalid source-table selection')
            plot = {'points': [], 'excluded': []}
        else:
            ep.require(selection['x'] in keys and selection['y'] in keys, 'unknown display axis')
            plot = ep.point_rows(task['records'], selection)
            ep.require(bool(plot['points']), 'numeric display has no supported points')
        task['operation_id'] = operation
        task['selection'] = copy.deepcopy(selection)
        task['plot'] = plot
        note = decision['additional_note']
        # Do not replace earlier restrictions or notes with a model's summary.
        addition = 'Post-EC display review: '+decision['reason']+(('\n'+note) if note else '')
        annotations = task['context']['annotations']
        if isinstance(annotations, str):
            task['context']['annotations'] = annotations+'\n'+addition
        elif isinstance(annotations, list) and all(isinstance(value, str) for value in annotations):
            annotations.append(addition)
        else:
            ep.require(False, 'unsupported source annotation type')
    return result


def run(root, out, *, model=None):
    from .eda_workflow import strict_schema
    out = Path(out)
    bundle = prepare(root)
    cb.save_bundle(out/'prepared', bundle)
    response = providers.codex_generate(bundle['request'], model=model, timeout=None,
        cli_schema=strict_schema(bundle['request']['payload']['schema']))
    write_json(out/'output.json', response)
    cb.verify_bundle(bundle)
    frozen, _, _, _, refs = sources(root)
    cb.check_refs(refs)
    apply(response, frozen)
    write_json(out/'validation.json', {'status': 'CONTRACT_VALID', 'model_calls': 1,
        'automatic_retries': 0, 'calculations_changed': False, 'scientific_approval': False})


def final_tasks(review_path, frozen, actual):
    """Revalidate bindings and decision schema immediately before/after EV."""
    path = Path(review_path)
    bundle = {'request': read_json(path/'prepared/request.json'),
              'context_manifest': read_json(path/'prepared/context_manifest.json')}
    cb.verify_bundle(bundle)
    refs = bundle['request']['payload']['eda_context_bindings']
    ep.require(ep.verified(refs['post_ec:frozen']) == frozen and ep.verified(refs['post_ec:result']) == actual,
               'display review belongs to different EC results')
    response = read_json(path/'output.json')
    tasks = apply(response, frozen)
    return tasks, {'ep_final_output': cb.file_ref(path/'output.json'),
                   'ep_final_request': cb.file_ref(path/'prepared/request.json'),
                   'ep_final_manifest': cb.file_ref(path/'prepared/context_manifest.json')}


def render(root, out):
    root = Path(root)
    calculation = read_json(root/'EC/calculation_bundle.json')
    frozen = read_json(root/'EP/accepted/ec_request.json')
    from .eda_ep_quality import require_execution_review
    require_execution_review(frozen)
    return ep.execute_ev(calculation, out, display_review=root/'EP_FINALIZE')
