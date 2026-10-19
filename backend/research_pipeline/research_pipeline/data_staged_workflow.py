"""Explicit Data stages: lightweight requirements, coverage facts, gap disposition.

Each command stops at its own stage. Existing extraction is reused; this entry
point never calls preparation, fitting, simulation, approval or service restart.
"""
import argparse
import json
import time
from pathlib import Path

from .adequacy import check_ref, file_ref
from .common import PipelineError, read_json, write_json

VERSION = 'DATA_STAGES_1.4'
STAGES = ('planning', 'coverage', 'disposition', 'necessity')


def fail(message):
    raise PipelineError('DATA_STAGES_INVALID', message)


def _closed(value):
    for key in ('scientific_approval', 'can_enter_qc', 'fit_ready'):
        if value.get(key, False) is not False:
            fail('A Data input assessment cannot grant ' + key)


def _carry_forward(out, source_run=None, plan=None, coverage=None):
    """Preserve upstream open records without interpreting or closing them."""
    if source_run:
        root = Path(source_run)
        main_ref = read_json(root / 'manifest.json')['bindings']['main']
        check_ref(main_ref)
        view_ref = file_ref(root / 'source_view.json')
        main, view = read_json(main_ref['path']), read_json(view_ref['path'])
        value = {
            'version': VERSION, 'main_ref': main_ref, 'source_view_ref': view_ref,
            'missing_information': main.get('missing_information', {}),
            'extraction_findings': view.get('legacy_findings', []),
            'disposition': 'UNCHANGED_UPSTREAM_RECORDS_NO_CLOSURES',
            'scope': 'Input coverage and method routing do not replace DC007/DC008 or authorize QC.',
        }
    else:
        # A stage forwards the exact predecessor record, rather than rewriting it.
        prior = next((Path(p).parent / 'inherited_unresolved.json'
                      for p in (coverage, plan) if p and
                      (Path(p).parent / 'inherited_unresolved.json').exists()), None)
        if prior is None:
            # Direct module callers still retain their source bindings. Recover
            # the original records through the verified planning input reference.
            planning = read_json(plan)
            binding = planning.get('bindings', {})
            main_ref = binding.get('main') or binding.get('main_ref')
            view_ref = binding.get('source_view') or binding.get('source_view_ref')
            if not main_ref or not view_ref:
                fail('Cannot forward original unresolved records from this plan')
            check_ref(main_ref); check_ref(view_ref)
            value = {'version': VERSION, 'main_ref': main_ref, 'source_view_ref': view_ref,
                     'missing_information': read_json(main_ref['path']).get('missing_information', {}),
                     'extraction_findings': read_json(view_ref['path']).get('legacy_findings', []),
                     'disposition': 'UNCHANGED_UPSTREAM_RECORDS_NO_CLOSURES'}
        else:
            value = read_json(prior)
            check_ref(value['main_ref']); check_ref(value['source_view_ref'])
    return file_ref(write_json(out / 'inherited_unresolved.json', value))


def _necessity_module(coverage, prepared_out=None):
    if prepared_out is not None:
        version = read_json(Path(prepared_out) / 'build.json').get('version')
        if version == 'DATA_NECESSITY_IMPACT_6.0':
            from . import data_necessity_v6
            return data_necessity_v6
        if version == 'DATA_NECESSITY_5.0':
            from . import data_necessity_v5
            return data_necessity_v5
        if version == 'DATA_NECESSITY_4.0':
            from . import data_necessity_v4
            return data_necessity_v4
        fail('Unknown saved necessity implementation; never migrate an existing attempt implicitly')
    if read_json(coverage).get('version') == 'COVERAGE_FACTS_5.0':
        from . import data_necessity_v6
        return data_necessity_v6
    from . import data_necessity_v4
    return data_necessity_v4


def _continued(stage, out, *, resume, pause, status, max_new_calls,
               retry_failed, generator, batch=None):
    """Operate only on the exact prepared stage; never prepare another one."""
    saved = read_json(out / 'workflow.json')
    if saved['stage'] != stage:
        fail('Requested stage differs from the saved stage')
    for ref in saved['inputs'].values():
        check_ref(ref)
    if stage == 'coverage':
        from . import data_coverage_v5 as engine
        if read_json(out / 'build.json').get('version') != engine.VERSION:
            fail('Historical coverage must use its original runtime')
    elif stage == 'disposition':
        engine = _necessity_module(saved['inputs']['coverage']['path'], prepared_out=out)
        if pause and not hasattr(engine, 'checkpoint'):
            fail('Historical necessity pause requires its original execution controls')
    else:
        fail('Continuation controls are available for coverage and necessity')
    if pause:
        if stage == 'coverage':
            result = engine.request_pause(out)
        else:
            (out / 'PAUSE').write_text('Pause at the next part boundary.\n', encoding='utf-8')
            result = {'status': 'PAUSE_REQUESTED'}
    elif status:
        if stage == 'coverage':
            result = engine.rebuild_checkpoint(out, write=False)
        elif (out / 'necessity.json').exists():
            result = engine.verify_result(out / 'necessity.json')
        elif hasattr(engine, 'checkpoint'):
            result = engine.checkpoint(out)
        else:
            engine.verify_prepared(out)
            result = {'status': 'PREPARED_OR_PARTIAL', 'complete': False}
    else:
        # --resume is explicit permission to clear a previous safe-boundary pause.
        (out / 'PAUSE').unlink(missing_ok=True)
        result = engine.run_prepared(out, generator=generator,
                                    max_new_calls=max_new_calls, retry_failed=retry_failed, **({'batch': batch} if batch is not None else {}))
    _closed(result)
    manifest = {**saved, 'status': result.get('status', 'STAGE_COMPLETE'),
                'next_stage_started': False}
    manifest.pop('stop_reason', None)
    artifact = out / ('coverage.json' if stage == 'coverage' else 'necessity.json')
    if artifact.exists() and not pause:
        engine.verify_result(artifact)
        manifest.update(status='STAGE_COMPLETE', output=file_ref(artifact))
    if result.get('stop_reason'):
        manifest['stop_reason'] = result['stop_reason']
    if not status:
        write_json(out / 'workflow.json', manifest)
    return manifest


def run_stage(stage, out, *, source_run=None, plan=None, coverage=None,
              decisions=None, build_only=False, generator=None, import_from=None,
              max_new_calls=1, resume=False, pause=False, status=False,
              retry_failed=False, targeted_search=False, batch=None):
    """Run exactly one requested stage, preserving immutable predecessor files."""
    if stage not in STAGES:
        fail('Unknown stage: ' + str(stage))
    if stage == 'necessity':
        stage = 'disposition'
    if isinstance(max_new_calls, bool) or not isinstance(max_new_calls, int) or max_new_calls < 0:
        fail('max_new_calls must be a nonnegative integer')
    out = Path(out).resolve()
    if sum(bool(x) for x in (resume, pause, status)) > 1:
        fail('Choose one continuation control')
    if resume or pause or status:
        if any((source_run, plan, coverage, decisions, build_only, import_from, targeted_search)):
            fail('Continuation uses saved inputs; do not replace its predecessors')
        return _continued(stage, out, resume=resume, pause=pause, status=status,
                          max_new_calls=max_new_calls, retry_failed=retry_failed, generator=generator, batch=batch)
    if retry_failed:
        fail('Retry is an explicit --resume operation')
    if import_from and (stage != 'coverage' or targeted_search):
        fail('Historical imports belong to initial coverage only')
    if targeted_search and (stage != 'coverage' or not coverage):
        fail('Targeted search requires coverage and its completed parent --coverage')
    if stage in ('planning', 'coverage') and not source_run:
        fail('This stage requires the existing --source-run checkpoint')
    if stage in ('coverage', 'disposition') and not plan:
        fail('This stage requires a verified --plan')
    if stage == 'disposition' and not coverage:
        fail('Disposition requires independent --coverage')
    if stage != 'disposition' and decisions:
        fail('Applicability decisions belong to disposition only')
    # A failed attempt remains inspectable; never overwrite or silently retry it.
    if out.exists() and any(out.iterdir()):
        fail('Use a new empty output directory for this stage')
    inputs = [Path(p).resolve() for p in (source_run, plan, coverage, decisions, import_from) if p]
    for path in inputs:
        if path == out or out in path.parents or (path.is_dir() and path in out.parents):
            fail('Output must be separate from predecessor artifacts')
    refs = {key: file_ref(path) for key, path in (
        ('plan', plan), ('coverage', coverage), ('decisions', decisions)) if path}
    v4 = stage != 'planning' and str(read_json(plan).get('version', '')).startswith('REQUIREMENT_PLAN_4.')
    if (import_from or targeted_search) and not v4:
        fail('Incremental coverage requires a DR v4 plan')
    if stage == 'disposition' and build_only and not v4:
        fail('Legacy disposition is local and has no request to prepare')
    if v4 and decisions:
        fail('DR v4 necessity derives evidence-backed action decisions from its verified coverage input; '
             'legacy applicability decision files are incompatible.')
    started = time.monotonic()
    def invoke(function, *args, **kwargs):
        try:
            return function(*args, **kwargs)
        except BaseException as exc:
            # The runtime owns immutable attempts. Record an entry-point handle
            # even when the first call fails so explicit resume can find them.
            if v4 and (out / 'build.json').exists():
                failure = {'version': VERSION, 'stage': stage, 'status': 'FAILED_RETAINED',
                    'inputs': refs, 'error': str(exc), 'next_stage_started': False,
                    'scientific_approval': False, 'can_enter_qc': False, 'fit_ready': False}
                failure['inherited_unresolved_ref'] = _carry_forward(out, source_run, plan, coverage)
                write_json(out / 'workflow.json', failure)
            raise
    if stage == 'planning':
        from . import data_requirement_plan_v4 as planning
        result = (planning.prepare(source_run, out) if build_only else
                  planning.run(source_run, out, generator=generator))
        artifact = out / 'plan.json'
    elif stage == 'coverage' and v4:
        from . import data_coverage_v5 as review
        if targeted_search:
            parent = review.verify_result(coverage)
            if parent['bindings']['plan'] != file_ref(plan):
                fail('Search parent belongs to a different plan')
            result = review.prepare_search(coverage, out)
            if not build_only:
                result = invoke(review.run_prepared, out, generator=generator, max_new_calls=max_new_calls, **({'batch': batch} if batch is not None else {}))
        else:
            result = (review.prepare(plan, source_run, out, import_from=import_from) if build_only else
                      invoke(review.run, plan, source_run, out, generator=generator,
                             max_new_calls=max_new_calls, import_from=import_from, **({'batch': batch} if batch is not None else {})))
        artifact = out / 'coverage.json'
    elif stage == 'disposition' and v4:
        necessity = _necessity_module(coverage)
        time_policy = getattr(batch, 'policy_ref', None)
        result = necessity.prepare(plan, coverage, out,
                                   **({'time_policy': time_policy} if time_policy else {}))
        if not build_only:
            result = invoke(necessity.run_prepared, out, generator=generator, max_new_calls=max_new_calls, **({'batch': batch} if batch is not None else {}))
        artifact = out / 'necessity.json'
    elif stage == 'coverage':
        from . import data_requirement_planning as planning
        from . import data_coverage_review as review
        planning.verify_plan(plan)
        result = (review.prepare(plan, source_run, out) if build_only else
                  review.run(plan, source_run, out, generator=generator))
        artifact = out / 'coverage.json'
    else:
        from . import data_requirement_planning as planning
        from . import data_coverage_review as review
        from . import data_gap_disposition as disposition
        verified_plan = planning.verify_plan(plan)
        verified_coverage = review.verify_result(coverage)
        # The resolver independently checks the plan digest in coverage.
        result = disposition.resolve(
            verified_plan, verified_coverage,
            applicability_decisions=read_json(decisions) if decisions else (),
            evidence_sources=review.result_sources(coverage))
        _closed(result)
        artifact = write_json(out / 'disposition.json', result)
    if isinstance(result, dict):
        _closed(result)
    for ref in refs.values():
        check_ref(ref)
    stage_status = 'BUILT_NO_MODEL_CALL' if build_only else 'STAGE_COMPLETE'
    if not build_only and v4:
        if artifact.exists():
            (review if stage == 'coverage' else necessity).verify_result(artifact)
        else:
            stage_status = result.get('status', 'PARTIAL_CHECKPOINT')
    manifest = {
        'version': VERSION, 'stage': stage,
        'status': stage_status,
        'inputs': refs, 'elapsed_seconds': round(time.monotonic() - started, 3),
        'next_stage_started': False,
        'scientific_approval': False, 'can_enter_qc': False, 'fit_ready': False,
    }
    if artifact.exists():
        manifest['output'] = file_ref(artifact)
    if isinstance(result, dict) and result.get('stop_reason'):
        manifest['stop_reason'] = result['stop_reason']
    manifest['inherited_unresolved_ref'] = _carry_forward(out, source_run, plan, coverage)
    write_json(out / 'workflow.json', manifest)
    return manifest


def add_arguments(parser):
    parser.add_argument('stage', choices=STAGES)
    parser.add_argument('--source-run', help='Reuse an already verified extraction checkpoint')
    parser.add_argument('--plan', help='Published plan.json; routes to the matching version of coverage/necessity')
    parser.add_argument('--coverage', help='Published independent coverage.json')
    parser.add_argument('--decisions', help='Optional evidence-backed applicability decisions JSON array')
    parser.add_argument('--out', required=True)
    parser.add_argument('--build-only', action='store_true', help='Prepare requests without a model call')
    parser.add_argument('--import-from', help='Replay accepted historical v4 coverage parts and preserve its budget')
    parser.add_argument('--max-new-calls', type=int, default=1, help='Calls allowed in this invocation (default: 1)')
    controls = parser.add_mutually_exclusive_group()
    controls.add_argument('--resume', action='store_true', help='Continue the exact prepared stage')
    controls.add_argument('--pause', action='store_true', help='Pause at the next part boundary')
    controls.add_argument('--status', action='store_true', help='Verify and report the saved checkpoint without calling a model')
    parser.add_argument('--retry-failed', action='store_true', help='Explicitly retry a failed part during resume')
    parser.add_argument('--targeted-search', action='store_true', help='Prepare targeted permitted-source searches from --coverage')


def execute_args(args):
    return run_stage(args.stage, args.out, source_run=args.source_run, plan=args.plan,
                     coverage=args.coverage, decisions=args.decisions, build_only=args.build_only,
                     import_from=args.import_from, max_new_calls=args.max_new_calls,
                     resume=args.resume, pause=args.pause, status=args.status,
                     retry_failed=args.retry_failed, targeted_search=args.targeted_search)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    add_arguments(parser)
    args = parser.parse_args(argv)
    try:
        result = execute_args(args)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({'status': 'FAILED', 'code': getattr(exc, 'code', 'ERROR'),
                          'message': str(exc)}, ensure_ascii=False))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
