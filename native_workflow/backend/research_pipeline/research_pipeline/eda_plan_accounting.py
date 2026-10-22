"""Resolve fixed source references and retain required parent views on unchanged EC.

Raw model outputs are immutable. This resolver is not permission to repair an
inadequate scientific plan: only already validated parent selections can survive
an accidental post-EC omission, and every retained selection is disclosed.
"""
import copy
from . import eda_pk_scales


def resolve(plan, final, candidates, tables, *, ec_reexecuted):
    from .eda_questions_v6 import validate_questions, candidate_datasets
    validate_questions(plan['analyses'], candidates, tables, plan['dataset_dispositions'])
    result = copy.deepcopy(final)
    changes = []
    decisions = result['task_decisions']
    by_question = {a['analysis_id']: a for a in decisions}
    dispositions = {d['dataset_id']: d for d in result['dataset_dispositions']}
    selected = {v['view_id'] for a in decisions for v in a['views']}
    if not selected <= set(candidates):
        raise ValueError('Unknown final view; cannot resolve plan references')
    optional = {d['dataset_id'] for d in result['dataset_dispositions']
                if d.get('handoff', {}).get('role') == 'SUPPLEMENTARY'
                and d.get('handoff', {}).get('purpose', '').strip()}
    for requirement in eda_pk_scales.requirements(candidates, tables):
        did = requirement['dataset_id']
        if did in optional:
            continue
        for scale in ('linear', 'log10'):
            offered = set(requirement[scale + '_views'])
            if not offered or selected & offered:
                continue
            if ec_reexecuted or dispositions.get(did, {}).get('status') != 'DISPLAYED':
                raise ValueError('Mandatory display omission needs explicit scientific resolution: ' + did)
            parents = [(a, v) for a in plan['analyses'] for v in a['views'] if v['view_id'] in offered]
            ids = {v['view_id'] for _, v in parents}
            if len(ids) != 1:
                raise ValueError('No unique validated parent view for mandatory scope: ' + did)
            parent, view = parents[0]
            target = by_question.get(parent['analysis_id'])
            if target is None or target['status'] not in {'PLANNED', 'PARTIAL'}:
                raise ValueError('Parent question cannot accept retained display: ' + did)
            # Any deliberate data-role change needs review rather than automatic retention.
            old = next(d for d in plan['dataset_dispositions'] if d['dataset_id'] == did)
            if old['handoff']['role'] != dispositions[did]['handoff']['role']:
                raise ValueError('Changed data role prevents automatic parent retention: ' + did)
            target['views'].append(copy.deepcopy(view))
            selected.add(view['view_id'])
            changes.append({'kind': 'RETAIN_REQUIRED_PARENT_VIEW', 'analysis_id': target['analysis_id'],
                            'view_id': view['view_id'], 'dataset_id': did, 'scale': scale,
                            'reason': 'Existing mandatory PK coverage; unchanged EC; exact validated EP selection retained. Independent review pending.'})
    # A DISPLAYED declaration with no selected figure is a missing link, not a
    # license to invent a display or to downgrade the declaration silently.
    covered = {did for vid in selected for did in candidate_datasets(candidates[vid])}
    for did, disposition in dispositions.items():
        if disposition['status'] != 'DISPLAYED' or did in covered:
            continue
        parents = [(a, v) for a in plan['analyses'] for v in a['views']
                   if did in candidate_datasets(candidates[v['view_id']])]
        if ec_reexecuted or len({v['view_id'] for _, v in parents}) != 1:
            raise ValueError('Displayed dataset lacks unique validated parent selection: ' + did)
        parent, view = parents[0]
        target = by_question.get(parent['analysis_id'])
        old = next(d for d in plan['dataset_dispositions'] if d['dataset_id'] == did)
        if (target is None or target['status'] not in {'PLANNED', 'PARTIAL'}
                or old['handoff']['role'] != disposition['handoff']['role']):
            raise ValueError('Changed scope prevents parent display reference resolution: ' + did)
        target['views'].append(copy.deepcopy(view))
        selected.add(view['view_id'])
        covered.update(candidate_datasets(candidates[view['view_id']]))
        changes.append({'kind': 'RETAIN_DECLARED_PARENT_VIEW', 'dataset_id': did,
                        'analysis_id': target['analysis_id'], 'view_id': view['view_id'],
                        'reason': 'Final output explicitly declares this dataset displayed; retain its unique unchanged-EC parent selection. Independent review pending.'})
    for a in decisions:
        if not set(a['dataset_ids']) <= set(tables):
            raise ValueError('Unknown declared dataset; cannot resolve question scope')
        required = {did for v in a['views'] for did in candidate_datasets(candidates[v['view_id']])}
        for did in sorted(required - set(a['dataset_ids'])):
            a['dataset_ids'].append(did)
            changes.append({'kind': 'SOURCE_SCOPE_REFERENCE', 'analysis_id': a['analysis_id'], 'dataset_id': did})
    validate_questions(decisions, candidates, tables, result['dataset_dispositions'])
    audit = {'version': 'EDA_PLAN_ACCOUNTING_1', 'changes': changes,
             'raw_model_output_modified': False, 'new_model_calls': 0,
             'data_modified': False, 'new_plot_candidates': False,
             'review_status': 'PENDING_INDEPENDENT_AND_HUMAN_REVIEW'}
    return result, audit
