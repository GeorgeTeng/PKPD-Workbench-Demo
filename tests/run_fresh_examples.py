"""Fresh four-example acceptance: no response reuse, resume, repair or retries.

Start app.py with a new --state directory and without --allow-response-reuse.
Each failed round remains immutable. Fix code, restart with a NEW state directory,
then run this command again with a NEW output directory. No model time limit.
"""
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_three_examples import ROOT, UPSTREAM, fetch, read_json, digest, stamp, require, validate, model_calls

EXAMPLES = ('imidocarb', 'pmb', 'meropenem', 'voriconazole')


def code_snapshot():
    paths = [ROOT / 'app.py']
    for folder in ('backend', 'demo', 'tests'):
        paths.extend(p for p in (ROOT / folder).rglob('*') if p.is_file()
                     and p.suffix in {'.py', '.json', '.yaml', '.yml', '.toml'} and '__pycache__' not in p.parts)
    paths.extend((ROOT / 'examples/inputs').glob('*'))
    return {p.relative_to(ROOT).as_posix(): digest(p.read_bytes()) for p in sorted(paths) if p.is_file()}


def assert_fresh(driver, verified, outputs, model='gpt-6.1-sol', effort='high'):
    events = driver['events']
    require(Counter(e['node'] for e in events if e['event'] == 'STARTED') == Counter(UPSTREAM),
            'Every stage must be started exactly once')
    require(not any(e['event'] in {'CONTINUED', 'CONTEXT_REPAIR', 'SOURCE_PRESERVING_REVISION'} for e in events),
            'A resumed or repaired driver cannot pass fresh acceptance')
    require(all(c['new_or_changed'] and c['status'] == 'RETURNED' for c in verified['model_calls']),
            'Every model call must be new and returned successfully')
    banned = ('replay.json', 'cache_reuse.jsonl', 'verified_context_reuse.json', 'saved_patch_projection.json')
    for name in banned:
        require(not list(outputs.rglob(name)), 'Forbidden reuse/recovery receipt: ' + name)
    require(not any(p.is_file() for p in outputs.glob('**/audit/reused/**')), 'Shared stage response reused')
    require(not list(outputs.rglob('patch_attempt.json')), 'Context patch attempt is not a fresh one-pass run')
    for path in outputs.rglob('call.json'):
        call = read_json(path)
        require(call.get('requested_model') == model and call.get('requested_reasoning_effort') == effort,
                'Unexpected model identity: ' + str(path))
        require(call.get('timeout_seconds') is None, 'Model timeout unexpectedly enabled')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', default='http://127.0.0.1:8774')
    parser.add_argument('--state-root', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--approve-test-gates', action='store_true')
    parser.add_argument('--expected-model', default='gpt-6.1-sol')
    parser.add_argument('--expected-effort', default='high',
                        type=lambda value: None if value.lower() == 'none' else value)
    args = parser.parse_args()
    args.state_root = args.state_root.resolve()
    args.output_dir = args.output_dir.resolve()
    if not args.approve_test_gates:
        parser.error('Explicit --approve-test-gates authorization is required')
    require(not args.output_dir.exists(), 'Use a new output directory; fresh rounds cannot be resumed')
    require(not list((args.state_root / 'workbench_state/canvas_sessions').glob('*/session.json')),
            'Use a new server state directory with no previous sessions')
    require(not model_calls(args.state_root), 'Previous model receipts found; use a fresh server state directory')
    caps = json.loads(fetch(args.base, '/workspace-api/capabilities'))
    require(caps.get('response_reuse_disabled') is True, 'Server must disable response reuse')
    identity = caps['model_executor']
    require(identity.get('requested_model') == args.expected_model and identity.get('requested_reasoning_effort') == args.expected_effort,
            'Server model identity does not match the requested acceptance configuration')
    available = json.loads(fetch(args.base, '/workspace-api/examples'))
    require({e['id'] for e in available} == set(EXAMPLES), 'Expected exactly four packaged examples')
    args.output_dir.mkdir(parents=True)
    report_path = args.output_dir / 'fresh_examples_acceptance.json'
    frozen = code_snapshot()
    report = {'status': 'RUNNING', 'started_at': stamp(), 'scope': 'INTAKE_CONTEXT_DATA_ONLY',
              'execution': 'FRESH_SEQUENTIAL_LIVE_HTTP', 'response_reuse_disabled': True,
              'state_root': str(args.state_root.resolve()), 'base_url': args.base,
              'expected_requested_model': args.expected_model, 'expected_reasoning_effort': args.expected_effort,
              'gate_reviewer': 'USER_AUTHORIZED_DEMO_ACCEPTANCE', 'independent_human_review': False,
              'scientific_release': False, 'eda_executed': False, 'pk_executed': False,
              'automatic_retries': 0, 'manual_repairs': 0, 'model_deadline': None,
              'packaged_examples': available, 'code_and_inputs': frozen, 'examples': []}
    def save():
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    save()
    try:
        for example in EXAMPLES:
            require(code_snapshot() == frozen, 'Code or input changed during this round; restart all examples')
            baseline = model_calls(args.state_root)
            output = args.output_dir / (example + '_driver.json')
            command = [sys.executable, '-I', '-B', '-X', 'utf8', str(ROOT / 'tests/run_data_acceptance.py'),
                       '--base', args.base, '--example', example, '--max-context-repairs', '0',
                       '--approve-test-gates', '--output', str(output)]
            item = {'example': example, 'status': 'RUNNING', 'started_at': stamp(),
                    'driver_report': str(output.resolve()), 'attempts': [{'attempt': 1, 'continued_session_id': None}],
                    'command': command}
            report['examples'].append(item)
            save()
            print(json.dumps({'event': 'FRESH_EXAMPLE_STARTED', 'example': example, 'at': stamp()}), flush=True)
            with output.with_suffix('.log').open('w', encoding='utf-8') as log:
                result = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                                        env=dict(os.environ, PYTHONUTF8='1'), check=False)
            driver = read_json(output)
            item.update(session_id=driver.get('session_id'), driver_exit_code=result.returncode)
            require(result.returncode == 0 and driver['status'] == 'PASSED_THROUGH_DATA',
                    example + ': ' + driver.get('error', driver['status']))
            verified = validate(args.base, driver['session_id'], args.state_root, baseline, args.expected_model, args.expected_effort)
            assert_fresh(driver, verified, args.state_root / 'workbench_outputs', args.expected_model, args.expected_effort)
            require(code_snapshot() == frozen, 'Code or input changed during the run; restart all examples')
            item.update(verified, finished_at=stamp())
            save()
            print(json.dumps({'event': 'FRESH_EXAMPLE_VERIFIED', 'example': example,
                              'model_calls': len(verified['model_calls']), 'at': stamp()}), flush=True)
        report.update(status='ALL_FOUR_PASSED_FRESH_THROUGH_DATA', finished_at=stamp(),
                      code_unchanged=True, no_reuse_verified=True)
        save()
        print(json.dumps({'status': report['status'], 'report': str(report_path)}), flush=True)
        return 0
    except Exception as exc:
        report.update(status='FAILED', error=str(exc), finished_at=stamp())
        if report['examples']:
            report['examples'][-1].update(status='FAILED', error=str(exc), finished_at=report['finished_at'])
        save()
        print(json.dumps({'status': 'FAILED', 'error': str(exc), 'report': str(report_path)}), flush=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
