"""Production entry point: existing extraction + DR -> Coverage -> Necessity.

No earlier stage is rerun. Old matrix runners remain historical replay tools.
"""
import argparse
import html
import json
import os
import time
from collections import Counter
from pathlib import Path

from . import data_coverage_direct as coverage, data_necessity_direct as necessity
from . import data_direct_runtime as rt
from .common import read_json, write_json, utcnow, PROJECT


def report(out, cov, nec, necessity_path=None):
    out = Path(out)
    attempts = [read_json(path) for path in out.glob('**/attempts/*/status.json')]
    summary = {'version': 'DIRECT_DATA_REPORT_1.0', 'coverage': nec['bindings']['coverage'],
        'necessity': rt.file_ref(necessity_path or out/'necessity/necessity.json'),
        'requirements': len(cov['checks']),
        'field_checks': sum(len(row['fields']) for row in cov['checks'].values()),
        'requirement_statuses': dict(Counter(row['status'] for row in cov['checks'].values())),
        'field_statuses': dict(Counter(field['status'] for row in cov['checks'].values() for field in row['fields'].values())),
        'recorded_shortage_entries': len(nec['recorded_shortages']), 'impact_advice_groups': len(nec['analyses']),
        'count_note': 'Field/condition entries are not independent missing datasets; UNRESOLVED is not confirmed absent.',
        'provider_calls': sum(not attempt['test_generator'] for attempt in attempts),
        'test_calls': sum(attempt['test_generator'] for attempt in attempts),
        'model_seconds': sum(attempt.get('elapsed_seconds', 0) for attempt in attempts),
        'requested_model': rt.MODEL,
        'served_models': sorted({model for attempt in attempts for model in attempt.get('served_models', [])}),
        'usage': {key: sum(attempt.get('usage', {}).get(key, 0) for attempt in attempts)
                  for key in ('input_tokens', 'cached_input_tokens', 'output_tokens')},
        'scientific_approval': False, 'downstream_executed': False}
    write_json(out/'report.json', summary)
    esc = lambda value: html.escape(str(value))
    rows = []
    requirements = {row['id']: row for row in cov['requirements']}
    for rid, check in cov['checks'].items():
        fields = ''.join('<li><b>'+esc(name)+'</b> — '+esc(field['status'])+'<br>'+esc(field['summary'])+
            ('<br>Support type: '+esc(field['support_kind']) if field.get('support_kind') else '')+
            ('<br>Measurement: '+esc(json.dumps(field['measurement'],ensure_ascii=False)) if field.get('measurement') else '')+
            ('<br>Unconfirmed: '+esc(field['unresolved_information']) if field.get('unresolved_information') else '')+
            ''.join('<details><summary>'+esc(group['item_id'])+' · '+esc(group.get('status',''))+' · '+esc(group['scope_note'])+'</summary>'+
                ('<p>Support type: '+esc(group['support_kind'])+'</p>' if group.get('support_kind') else '')+
                ('<p>Column: '+esc(group['column_header'])+'<br>Measurement dimensions: '+esc(json.dumps(group['measurement'],ensure_ascii=False))+'</p>' if group.get('measurement') else '')+
                ('<p>Recorded value presence: '+esc(group['recorded_value_presence'])+'</p>' if group.get('recorded_value_presence') else '')+
                ('<p>Unresolved measurement qualification: '+esc(', '.join(group['unresolved_dimensions']))+'</p>' if group.get('unresolved_dimensions') else '')+
                ''.join('<p><code>'+esc(e['source'])+'</code><br>'+esc(e['quote'])+'</p>' for e in group.get('evidence', []))+
                '</details>' for group in field['source_scopes'])+'</li>' for name, field in check['fields'].items())
        conditions = ''.join('<li>'+esc(gap['condition'])+'<br>'+esc(gap['summary'])+'</li>' for gap in check['condition_gaps'])
        rows.append('<tr><td>'+esc(rid)+'</td><td>'+esc(requirements[rid]['description'])+'</td><td>'+esc(check['status'])+
            '</td><td>'+esc(check['summary'])+'<details><summary>Fields and source evidence</summary><ul>'+fields+conditions+'</ul></details></td></tr>')
    advice = ''.join('<article><h3>'+esc(a['id'])+' · '+esc(', '.join(a['requirement_ids']))+' · '+esc(a['impact'])+'</h3>'+
        '<p><b>Scope: </b>'+esc(a['affected_scope'])+'<br><b>Next action: </b>'+esc(a['next_action'])+'</p>'+
        '<p>'+esc(a['impact_summary'])+'</p><p><b>Advice: </b>'+esc(a['recommendation'])+'</p>'+
        '<p><b>Can continue: </b>'+esc('; '.join(a['can_continue']))+'</p><p><b>Conditions to verify: </b>'+esc('; '.join(a['conditions_to_verify']))+'</p>'+
        '<small>Recorded gaps: '+esc(', '.join(a['gap_ids']))+' · Local MP: '+esc(', '.join(a['local_method_profile_ids']))+'</small></article>'
        for a in nec['analyses'])
    page = ('<!doctype html><html lang="en"><meta charset="utf-8"><title>DR → Coverage → Necessity</title>'+'''
<style>body{font:16px/1.65 system-ui,sans-serif;max-width:1400px;margin:36px auto;padding:0 24px;color:#172b38;background:#f5f7fa}
h1{font-size:28px}table{border-collapse:collapse;width:100%;background:white}th,td{border:1px solid #ccd6df;padding:12px;text-align:left;vertical-align:top}
article{background:white;padding:16px 24px;margin:16px 0;border-left:4px solid #237888}summary{cursor:pointer;color:#17627b}li{margin:12px 0}code{overflow-wrap:anywhere}</style>'''+
        '<h1>DR → Coverage → Necessity</h1><p>Completed extraction and DR are reused. Coverage checks support for DR; Necessity explains impact and next steps.</p>'+
        '<p>'+esc(summary['requirements'])+' requirements | '+esc(summary['field_checks'])+' original fields | '+esc(summary['provider_calls'])+' real model calls | '+
        esc(round(summary['model_seconds'], 1))+' model seconds</p><p>Partial or unresolved support is not confirmed absence. This assessment does not establish model validity or scientific approval. Served model: '+
        esc(', '.join(summary['served_models']) or 'not reported by provider; unverified')+'</p><h2>Coverage results</h2><table><thead><tr><th>DR</th><th>Requirement</th><th>Status</th><th>Result</th></tr></thead><tbody>'+
        ''.join(rows)+'</tbody></table><h2>Necessity: impact and advice</h2>'+advice+'</html>')
    (out/'report.html').write_text(page, encoding='utf-8')
    return summary


def run_legacy(plan, source_view, main, local_mp, out, *, build_only=False, generator=None, review_state=None):
    if generator is None:
        rt.fail('Legacy workflow is replay/test-only; use the current assessment entry for new work')
    out = Path(out).resolve()
    refs = {key: rt.file_ref(path) for key, path in
            [('plan', plan), ('source_view', source_view), ('main', main), ('local_mp', local_mp)]}
    manifest = out/'inputs.json'
    if manifest.exists() and read_json(manifest) != refs:
        rt.fail('Direct workflow output belongs to different inputs')
    write_json(manifest, refs)
    started = time.monotonic()
    state = {'pid': os.getpid(), 'started_at': utcnow(), 'scope': 'COVERAGE_THEN_NECESSITY',
             'aggregate_time_limit': None, 'scientific_approval': False, 'downstream_executed': False}
    def emit(stage, status, **extra):
        state.update(stage=stage, status=status, at=utcnow(), elapsed_seconds=time.monotonic()-started, **extra)
        write_json(out/'runner_status.json', state)
        print(json.dumps(state, ensure_ascii=False), flush=True)
    try:
        emit('COVERAGE', 'PREPARING')
        if not (out/'coverage/build.json').exists():
            coverage.prepare(plan, source_view, main, out/'coverage')
        coverage.verify_prepared(out/'coverage')
        if build_only:
            emit('COVERAGE', 'PREPARED_NO_PROVIDER_CALLS')
            return read_json(out/'coverage/preflight.json')
        emit('COVERAGE', 'RUNNING')
        coverage.run_prepared(out/'coverage', generator=generator)
        cov = coverage.verify_result(out/'coverage/coverage.json')
        emit('NECESSITY', 'PREPARING')
        rt.verify_refs(refs)
        necessity.prepare(out/'coverage/coverage.json', main, local_mp, out/'necessity')
        emit('NECESSITY', 'RUNNING')
        necessity.run_prepared(out/'necessity', generator=generator)
        nec = necessity.verify_result(out/'necessity/necessity.json')
        rt.verify_refs(refs)
        summary = report(out, cov, nec)
        if generator is None:
            from .data_direct_review import DirectDataReview
            gate = DirectDataReview(review_state or PROJECT/'outputs/workbench_state', PROJECT/'outputs').publish(out)
            write_json(out/'human_gate.json', gate)
            emit('HUMAN_GATE', 'AWAITING_HUMAN_REVIEW', report=rt.file_ref(out/'report.json'), review_url=gate['url'])
        else:
            emit('REPORT', 'COMPLETE', report=rt.file_ref(out/'report.json'))
        return summary
    except BaseException as exc:
        emit(state.get('stage', 'UNKNOWN'), 'FAILED_RETAINED', error=str(exc))
        raise


def run(*args, **kwargs):
    from .data_assessment_workflow import run as assessed_run
    kwargs.setdefault('contract', 'original')
    return assessed_run(*args, **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ('plan', 'source-view', 'main', 'local-mp', 'out'):
        parser.add_argument('--'+flag, required=True)
    parser.add_argument('--build-only', action='store_true')
    parser.add_argument('--reuse-coverage', help='Reuse an accepted Coverage result without another model check')
    parser.add_argument('--reuse-necessity', help='Reuse accepted Necessity when regenerating only the human summary')
    parser.add_argument('--review-state', help='Workbench state directory for the existing human review gate')
    options = vars(parser.parse_args())
    run(**options)


if __name__ == '__main__':
    main()
