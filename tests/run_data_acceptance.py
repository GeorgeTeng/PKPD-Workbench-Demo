"""Exercise the real HTTP workflow through Data; no EDA or PK calls.

Automatic gate approval requires the explicit --approve-test-gates flag.
Every decision stays bound to the original canvas output signature.
"""
import argparse
import json
from pathlib import Path
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError

parser = argparse.ArgumentParser()
parser.add_argument('--base', default='http://127.0.0.1:8772')
parser.add_argument('--example', default='pmb')
parser.add_argument('--session', help='Continue a stopped, source-bound run instead of importing another package.')
parser.add_argument('--max-context-repairs', type=int, default=2)
parser.add_argument('--approve-test-gates', action='store_true')
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
if not args.approve_test_gates:
    parser.error('This acceptance run needs explicit --approve-test-gates authorization.')
args.output.parent.mkdir(parents=True, exist_ok=True)
report = {'status': 'RUNNING', 'scope': 'INTAKE_CONTEXT_DATA_ONLY', 'model_outputs': 'LIVE',
          'gate_reviewer': 'USER_AUTHORIZED_DEMO_ACCEPTANCE', 'independent_human_review': False,
          'scientific_release': False, 'eda_executed': False, 'pk_executed': False, 'events': []}


def record(event, **values):
    report['events'].append({'at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'event': event, **values})
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    print(json.dumps(report['events'][-1], ensure_ascii=False), flush=True)


def call(path, body=None):
    request = Request(args.base + path, data=json.dumps(body).encode() if body is not None else None,
                      headers={'Content-Type': 'application/json'})
    try:
        with urlopen(request, timeout=120) as response:
            return json.load(response)
    except HTTPError as exc:
        raise RuntimeError(f'HTTP {exc.code}: {exc.read().decode()}') from exc


try:
    receipt = ({'id': args.session, 'upload': {}} if args.session else call('/workspace-api/examples/' + args.example + '/import', {}))
    report['session_id'] = receipt['id']
    path = '/ui-api/workflow/sessions/' + receipt['id']
    record('CONTINUED' if args.session else 'REGISTERED', session_id=receipt['id'], package_sha256=receipt['upload'].get('sha256'))
    repairs = 0
    for node in ['intake', 'context', 'adequacy', 'prepare']:
        state = call(path)
        n = next(n for n in state['nodes'] if n['id'] == node)['state']
        if n['execution'] != 'COMPLETED' and (n['can_run'] or (node in {'adequacy','prepare'} and n.get('can_retry_adequacy' if node=='adequacy' else 'can_retry_preparation'))):
            call(path + '/nodes/' + node + '/start', {})
            record('STARTED', node=node)
        prior = None
        while True:
            state = call(path)
            n = next(n for n in state['nodes'] if n['id'] == node)['state']
            raw = n.get('model_progress') or {}
            compact = {key: raw.get(key) for key in ('stage', 'phase', 'status', 'call_id', 'last_transport_or_model_error')}
            progress = (n['execution'], compact)
            if progress != prior:
                record('PROGRESS', node=node, execution=n['execution'], model_progress=compact)
                prior = progress
            if node == 'context' and n['execution'] == 'REVISION_REQUIRED' and repairs < args.max_context_repairs:
                feedback = call(path + '/context-feedback')
                revision = call(path + '/context-revisions', {
                    'feedback_signature': feedback['signature'], 'mode': 'REPAIR_EXTRACTION',
                    'guidance': 'Resolve the independent review findings with a targeted correction. Preserve the original proposal meaning, source quotations, conditions and unresolved issues. Keep one canonical owner for each proposition and use short references instead of duplicate claims. Do not change source facts or grant scientific approval.',
                    'submitted_by': report['gate_reviewer'], 'confirmed': True})
                if revision['session_id'] != receipt['id']:
                    record('SOURCE_PRESERVING_REVISION', parent_session=receipt['id'], child_session=revision['session_id'])
                    receipt['id'] = revision['session_id']
                    report['session_id'] = receipt['id']
                    path = '/ui-api/workflow/sessions/' + receipt['id']
                repairs += 1
                record('CONTEXT_REPAIR', attempt=repairs, feedback_signature=feedback['signature'])
                continue
            if n['execution'] not in {'NOT_STARTED', 'RUNNING', 'PAUSING'}:
                break
            time.sleep(5)
        if n['execution'] != 'COMPLETED':
            report['blocking_node'] = node
            report['blocking_state'] = n
            raise RuntimeError(f'{node} stopped with {n["execution"]}: {n.get("error") or n.get("reason")}')
        if n['can_review']:
            decision = {'decision': 'APPROVE', 'reviewer': report['gate_reviewer'],
                        'rationale': 'User explicitly authorized automatic gates for this demo acceptance through Data only. This records technical test progression, not independent human scientific acceptance or downstream model release.',
                        'output_signature': n['output_signature'], 'confirmed': True}
            if node == 'context':
                decision['objective_decision'] = 'CONFIRMED'
            call(path + '/nodes/' + node + '/review', decision)
            record('AUTOMATIC_GATE', node=node, output_signature=n['output_signature'], scientific_release=False)
        record('COMPLETED', node=node, artifacts=[{'name': a['name'], 'sha256': a['sha256']} for a in n['artifacts']])
    report['status'] = 'PASSED_THROUGH_DATA'
    report['final_session'] = call(path)
    record('ACCEPTANCE_PASSED')
except Exception as exc:
    report['status'] = 'FAILED'
    report['error'] = str(exc)
    record('ACCEPTANCE_FAILED', error=str(exc))
    raise SystemExit(1)
