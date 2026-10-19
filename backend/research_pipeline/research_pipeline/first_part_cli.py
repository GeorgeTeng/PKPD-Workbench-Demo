"""Standalone first-part workflow; no Canvas continuation, approval or Data run.

python -m research_pipeline.first_part_cli --help
"""
import argparse
import json
import time
from pathlib import Path

from . import first_part_handoff as handoff
from .common import PipelineError, write_json, utcnow


def _budget(value):
    seconds = float(value)
    if not 0 < seconds <= 1800:
        raise argparse.ArgumentTypeError('Budget must be greater than zero and at most 1800 seconds.')
    return seconds


def _summary(verified):
    return {key: value for key, value in verified.items() if key not in {'main', 'rules'}}


def run(pack_path, output, budget_seconds=1500, generator=None):
    """One fresh attempt. Only PASS exposes a verified handoff_main_ref.

    A failed attempt keeps all source, request and raw response evidence. It is
    never silently retried; a saved PASS can be published explicitly with the
    publish command. This workflow cannot extract new Rules or start Data.
    """
    if not 0 < budget_seconds <= 1800:
        raise PipelineError('FIRST_PART_BUDGET', 'Budget must be in (0, 1800] seconds.')
    out = handoff._new(output)
    start = time.monotonic()
    state = {'workflow':'STANDALONE_FIRST_PART', 'status':'PREPARING', 'started_at':utcnow(),
        'budget_seconds':budget_seconds, 'model':handoff.DEFAULT_MODEL, 'handoff_main_ref':None,
        'data_started':False, 'scientific_approval':False, 'automatic_retry':False}
    def save():
        state['elapsed_seconds'] = round(time.monotonic()-start, 3)
        write_json(out/'workflow_status.json', state)
    save()
    try:
        proof = handoff.prepare(handoff.prc.file_ref(pack_path), out/'candidate')
        state.update(status='REVIEW_RUNNING', preparation_ref=handoff.prc.file_ref(out/'candidate/preparation.json'))
        save()
        remaining = budget_seconds-(time.monotonic()-start)
        if remaining <= 0:
            raise TimeoutError('First-part budget exhausted before review; no model was invoked.')
        response = handoff.review(out/'candidate', model=handoff.DEFAULT_MODEL, timeout=remaining, generator=generator)
        state.update(decision=response['decision'], review_ref=handoff.prc.file_ref(out/'candidate/review.json'))
        if response['decision'] != 'PASS':
            state['status'] = 'FIRST_PART_REVISION_REQUIRED'
        else:
            # Publication replays all validation; never trust the decision alone.
            verified = handoff.publish(out/'candidate', out/'published')
            state.update(status='FIRST_PART_REVIEWED', handoff_main_ref=verified['main_ref'],
                verification=_summary(verified))
    except Exception as exc:
        state.update(status='ERROR', error={'code':getattr(exc,'code',type(exc).__name__), 'message':str(exc)})
    except KeyboardInterrupt:
        state.update(status='INTERRUPTED', error={'code':'INTERRUPTED', 'message':'Explicit interruption; no automatic retry.'})
    finally:
        state['finished_at'] = utcnow()
        save()
    return state


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    p = commands.add_parser('run', help='Published Rules → embedded main → one unified Luna review → PASS publication')
    p.add_argument('--rules-pack', required=True, help='Existing verified project_rules.json')
    p.add_argument('--out', required=True, help='New empty workflow directory')
    p.add_argument('--budget-seconds', type=_budget, default=1500)
    p = commands.add_parser('prepare', help='Create an unapproved candidate and frozen review request; no model')
    p.add_argument('--rules-pack', required=True); p.add_argument('--out', required=True)
    p = commands.add_parser('review', help='One real Luna review of an existing prepared candidate; no publication')
    p.add_argument('--prepared', required=True); p.add_argument('--budget-seconds', type=_budget, default=1500)
    p = commands.add_parser('publish', help='Replay an existing PASS and publish exact reviewed bytes; no model')
    p.add_argument('--prepared', required=True); p.add_argument('--out', required=True)
    p = commands.add_parser('verify', help='Verify a final main plus its fixed sibling receipt; no model or Data')
    p.add_argument('--main', required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'run':
            result = run(args.rules_pack, args.out, args.budget_seconds)
            code = 0 if result['status']=='FIRST_PART_REVIEWED' else 3 if result['status']=='FIRST_PART_REVISION_REQUIRED' else 2
        elif args.command == 'prepare':
            proof = handoff.prepare(handoff.prc.file_ref(args.rules_pack), args.out)
            result = {'status':'PREPARED_NOT_REVIEWED', 'preparation_ref':handoff.prc.file_ref(Path(args.out)/'preparation.json'),
                'candidate_main_ref':proof['main_ref'], 'handoff_main_ref':None, 'data_started':False}
            code = 0
        elif args.command == 'review':
            response = handoff.review(args.prepared, model=handoff.DEFAULT_MODEL, timeout=args.budget_seconds)
            result = {'status':'REVIEW_RETURNED', 'decision':response['decision'],
                'review_ref':handoff.prc.file_ref(Path(args.prepared)/'review.json'), 'handoff_main_ref':None}
            code = 0 if response['decision']=='PASS' else 3
        elif args.command == 'publish':
            result = _summary(handoff.publish(args.prepared, args.out)); code = 0
        else:
            result = _summary(handoff.verify_final_main(args.main)); code = 0
    except Exception as exc:
        result = {'status':'ERROR', 'handoff_main_ref':None,
            'error':{'code':getattr(exc,'code',type(exc).__name__), 'message':str(exc)}}
        code = 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
