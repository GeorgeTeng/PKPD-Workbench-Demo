"""G008 unresolved-item ledger for the Data agents.

Items arrive from context compression (main.json missing_information) or are raised by a
Data step for a later phase. Each handoff before an item's phase forwards it unchanged; the
step whose gate is that phase records one outcome. No outcome is inferred by host code.
"""
import copy

from ctxcomp.schemas import S, arr, enum, obj

VERSION = '1.1'
PHASES = ('BEFORE_QC', 'BEFORE_EDA', 'BEFORE_MODELING', 'BEFORE_INDEX_ANALYSIS',
          'BEFORE_TRANSLATION', 'BEFORE_PTA', 'FINAL_VALIDATION')
# CC019 needed_at (compression vocabulary) -> first Data phase whose decision depends on it.
CONTEXT_PHASE = {'context': 'BEFORE_QC', 'adequacy': 'BEFORE_QC', 'prepare': 'BEFORE_QC', 'eda': 'BEFORE_EDA',
                 'pk': 'BEFORE_MODELING', 'index': 'BEFORE_INDEX_ANALYSIS', 'human_pk': 'BEFORE_TRANSLATION', 'pk_translation': 'BEFORE_TRANSLATION',
                 'clinical': 'BEFORE_PTA', 'validation': 'FINAL_VALIDATION'}
OPEN_STATES = {'OPEN', 'CARRIED', 'ESCALATED'}
OUTCOME = obj(item_id=S, outcome=enum('RESOLVED', 'LIMITATION_ACCEPTED', 'ESCALATED', 'CARRIED'),
              reason=S, evidence=arr(obj(source=S, quote=S)), limitation=S,
              carried_to=enum(*PHASES, 'NOT_APPLICABLE'))
INSTRUCTIONS = (
    ' unresolved_ledger holds the G008 items; due_item_ids are the items whose needed_at is this step. '
    'Return exactly one ledger_outcomes record per due item and none for other items. '
    'RESOLVED: cite the exact evidence that settles it. LIMITATION_ACCEPTED: only when proceeding is acceptable; state the limitation the affected output must carry. '
    'ESCALATED: the item needs its owner or human review, and the dependent decision stays pending. '
    'CARRIED: name the later phase in carried_to and explain why the decision belongs there. '
    'Use limitation NONE and carried_to NOT_APPLICABLE when they do not apply. A PASS, elapsed time or absent evidence closes nothing; NOT_FOUND is not proof of absence.')
# Coverage words at the start of an UNMATCHED_REQUIREMENT reason -> G008 status.
COVERAGE_STATUS = {'MISSING': 'NOT_FOUND', 'DEFERRED': 'DEFERRED', 'CONFLICT': 'CONFLICT'}


def fail(message):
    from .common import PipelineError
    raise PipelineError('UNRESOLVED_LEDGER_INVALID', message)


def later(phase, than):
    return PHASES.index(phase) > PHASES.index(than)


def from_context(main, main_ref):
    """Open CC019 warnings, with their original record kept verbatim."""
    block = main.get('missing_information') or {}
    return [{'id': w['id'], 'field': w['field'], 'status': w['status'], 'needed_at': w['needed_at'],
             'phase': CONTEXT_PHASE[w['needed_at']], 'impact': w['impact'],
             'origin': {'step': 'context_compression', 'artifact': main_ref}, 'record': copy.deepcopy(w),
             'resolution_status': 'OPEN', 'history': []}
            for w in block.get('items', []) if w.get('resolution_status', 'OPEN') == 'OPEN']


def from_findings(findings, step, artifact_ref, after, existing, origin_step=None, follow_up_to=None):
    """A step's findings that a later phase depends on become new items; ledger echoes are skipped.

    origin_step names the step that raised the findings when it differs from the recording step.
    follow_up_to: a non-blocking FOLLOW_UP due at `after` goes to this phase, so it is not dropped once the gate opens."""
    known = {i['id'] for i in existing}
    numbered = sum(1 for i in existing if i['id'].startswith(step + '-U'))
    items = []
    for f in findings:
        if f['affected_id'] in known:
            continue
        if later(f['required_by'], after):
            phase = f['required_by']
        elif follow_up_to and f['required_by'] == after and f['severity'] == 'FOLLOW_UP':
            phase = follow_up_to
        else:
            continue
        head = f['reason'].split(':', 1)[0] if f['code'] == 'UNMATCHED_REQUIREMENT' else ''
        items.append({'id': f'{step}-U{numbered + len(items) + 1:03d}', 'field': f['affected_id'],
                      'status': COVERAGE_STATUS.get(head, 'OPEN_FINDING'), 'needed_at': phase,
                      'phase': phase, 'impact': f['reason'], 'origin': {'step': origin_step or step, 'artifact': artifact_ref},
                      'record': copy.deepcopy(f), 'resolution_status': 'OPEN', 'history': []})
    return items


def due(items, phase, include_overdue=False):
    return [i for i in items if i['resolution_status'] in {'OPEN', 'CARRIED'}
            and (i['phase'] == phase or (include_overdue and later(phase, i['phase'])))]


def apply_outcomes(items, phase, outcomes, step, evidence_ok, bound_to, include_overdue=False):
    """Record the due step's outcomes (G006-bound) and return the findings they imply."""
    expected = [i['id'] for i in due(items, phase, include_overdue)]
    got = [o['item_id'] for o in outcomes]
    if len(got) != len(set(got)) or set(got) != set(expected):
        fail(f'{step} must record one outcome per due item: missing={sorted(set(expected) - set(got))}, '
             f'unexpected={sorted(set(got) - set(expected))}.')
    by_id = {i['id']: i for i in items}
    findings = []
    for o in outcomes:
        item = by_id[o['item_id']]
        if o['outcome'] == 'RESOLVED' and not o['evidence']:
            fail('A resolved item needs evidence: ' + item['id'])
        for span in o['evidence']:
            if not evidence_ok(span):
                fail('Outcome evidence is not an exact permitted quote: ' + item['id'])
        if (o['outcome'] == 'LIMITATION_ACCEPTED') == (o['limitation'].strip().upper() in {'NONE', 'N/A'}):
            fail('A stated limitation belongs to, and only to, LIMITATION_ACCEPTED: ' + item['id'])
        if o['outcome'] == 'CARRIED':
            if o['carried_to'] == 'NOT_APPLICABLE' or not later(o['carried_to'], phase):
                fail('A carried item needs a later phase: ' + item['id'])
        elif o['carried_to'] != 'NOT_APPLICABLE':
            fail('Only a carried item names a later phase: ' + item['id'])
        item['history'].append({'step': step, 'phase': phase, **{k: o[k] for k in ['outcome', 'reason', 'evidence', 'limitation', 'carried_to']},
                                'bound_to': bound_to})
        item['resolution_status'] = o['outcome']
        base = {'affected_id': item['id'], 'needed_material': o['reason']}
        if o['outcome'] == 'CARRIED':
            item['phase'] = o['carried_to']
            findings.append({**base, 'code': 'UNRESOLVED_ITEM_CARRIED', 'severity': 'FOLLOW_UP', 'required_by': o['carried_to'],
                             'reason': f"{item['status']} ({item['field']}) carried to {o['carried_to']}: {o['reason']}"})
        elif o['outcome'] == 'ESCALATED':
            findings.append({**base, 'code': 'UNRESOLVED_ITEM_ESCALATED', 'severity': 'HUMAN_REVIEW', 'required_by': phase,
                             'reason': f"{item['status']} ({item['field']}) escalated: {o['reason']}"})
        elif o['outcome'] == 'LIMITATION_ACCEPTED':
            findings.append({**base, 'code': 'UNRESOLVED_ITEM_LIMITATION', 'severity': 'FOLLOW_UP', 'required_by': phase,
                             'reason': f"{item['status']} ({item['field']}) accepted as a limitation: {o['limitation']}"})
    return findings


def ledger(items, step, inputs):
    return {'schema_version': VERSION, 'rule': 'G008', 'step': step, 'input_refs': inputs, 'items': items,
            'open_item_ids': [i['id'] for i in items if i['resolution_status'] in OPEN_STATES]}


def forwarded(items):
    """What a handoff carries: every still-open item unchanged, plus accepted limitations of its outputs."""
    return ([copy.deepcopy(i) for i in items if i['resolution_status'] in OPEN_STATES],
            [{'id': i['id'], 'field': i['field'], 'limitation': i['history'][-1]['limitation']}
             for i in items if i['resolution_status'] == 'LIMITATION_ACCEPTED'])
