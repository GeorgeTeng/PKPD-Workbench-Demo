"""Read existing EDA records into one small status/next-action view. No calls."""
import argparse
import html
from pathlib import Path
from . import context_builder as cb
from .common import read_json, write_json


def review_state(root):
    root = Path(root)
    outer = read_json(root / 'status.json') if (root / 'status.json').exists() else {}
    state = dict(status='NOT_REVIEWED', independent_review='NOT_RUN', human_approval=False,
                 fit_ready=False, scientific_release=False,
                 next_step='Complete the descriptive EDA stages and independent review before exact-packet human review.')
    if not (root / 'human_review.json').exists():
        if outer.get('status') == 'FAILED':
            state.update(status='FAILED', next_step='Inspect the recorded failure; this entry point does not retry or resume.')
        return state
    from .eda_review_handoff import packet
    p = packet(root)
    review = read_json(p['bindings']['review']['path'])
    if review['decision'] != p['review_decision'] or review['issues'] != p['summary']['issues']:
        raise ValueError('EDA summary: packet and bound independent review differ')
    blocked = review['decision'] != 'PASS' or bool(review['issues']) or outer.get('new_ER_run') is False
    state.update(packet_sha256=p['content_sha256'], independent_review=review['decision'],
        historical_ER=outer.get('historical_ER'), new_ER_run=outer.get('new_ER_run', 'unknown'),
        blocking_issue_count=len(review['issues']), unreviewed_items=p['summary']['unreviewed_items'],
        presentation_closeout_is_independent_review=False)
    if blocked:
        state.update(status='BLOCKED_INDEPENDENT_REVIEW',
            next_step='Address and account for outstanding review issues, then obtain independent ER PASS on this exact packet version before human approval. Presentation closeout does not replace ER.')
    else:
        state.update(status='WAITING_FOR_EXACT_PACKET_HUMAN_REVIEW',
            next_step='An identified human must inspect every required figure and approve this packet SHA, acknowledging the exact limitations, open items and unreviewed scope.')
    if (root / 'approved_release.json').exists():
        r = read_json(root / 'approved_release.json')
        cb.check_refs({'packet': r['packet_ref'], 'decision': r['decision_ref'], **r['branches']})
        if blocked or r['packet_sha256'] != p['content_sha256']:
            raise ValueError('EDA summary: release differs from eligible packet')
        state.update(status='READY_FOR_INPUT_QUALIFICATION', human_approval=True,
            next_step='Consume the scoped PK/PD handoffs for branch input qualification; model readiness remains unestablished.')
    return state


def summarize(root):
    root = Path(root); refs = {}
    def load(path):
        refs[str(path.relative_to(root))] = cb.file_ref(path)
        return read_json(path)
    status = load(root / 'status.json') if (root / 'status.json').exists() else {}
    session = load(root / 'model_calls/session.json') if (root / 'model_calls/session.json').exists() else {}
    recorded_calls = session.get('calls', [])
    stages = []
    for stage in ['EP', 'EP_FINALIZE', 'EV', 'EI', 'ER']:
        folder = root / stage
        timing = load(folder / 'timing.json') if (folder / 'timing.json').exists() else {}
        related = [c for c in recorded_calls if c.get('route') == {'EP':'eda.plan','EP_FINALIZE':'eda.finalize','EI':'eda.findings','ER':'eda.review'}.get(stage)]
        elapsed = timing.get('seconds', sum(c.get('elapsed_seconds', 0) for c in related) if related else 'unknown')
        if stage == 'EV' and (root / 'verification.json').exists():
            elapsed = load(root / 'verification.json').get('R_seconds', elapsed)
        stages.append({'stage': stage, 'status': 'RECORDED' if folder.exists() else 'NOT_RECORDED_LOCALLY', 'seconds': elapsed})
    calls = []
    for path in sorted((root / 'model_calls').glob('*/provider/call.json')):
        record = load(path); budget_path = path.parent.parent / 'budget.json'
        budget = load(budget_path) if budget_path.exists() else {}
        calls.append({'record_ref': refs[str(path.relative_to(root))],
            'provider': record.get('provider', status.get('provider', 'unknown')),
            'requested_model': record.get('requested_model', status.get('model') or 'unknown'),
            'served_models': record.get('served_models') or record.get('served_model') or 'unknown',
            'status': record.get('status', 'unknown'), 'seconds': record.get('elapsed_seconds', 'unknown'),
            'budget_status': budget.get('status', 'unknown'),
            'combined_input_characters': budget.get('combined_input_characters', 'unknown')})
    manifest_path = root / 'EV/manifest.json'
    manifest = load(manifest_path) if manifest_path.exists() else {}
    tables_path = root / 'source_tables.json'
    tables = load(tables_path) if tables_path.exists() else []
    verification_path = root / 'verification.json'
    verification = load(verification_path) if verification_path.exists() else {}
    cb.check_refs(refs)
    packet = load(root / 'human_review.json') if (root / 'human_review.json').exists() else {}
    figures = len(manifest['artifacts']) if 'artifacts' in manifest else len(packet.get('required_figure_review_ids', []))
    return {'version': 'EDA_RUN_SUMMARY_1', 'run_ref': str(root.resolve()), 'execution_status': status.get('status', 'UNKNOWN'),
        'provider': status.get('provider', 'unknown'), 'requested_model': status.get('model') or 'unknown',
        'served_models': sorted({m for c in calls for m in (c['served_models'] if isinstance(c['served_models'], list) else [])}) or 'unknown',
        'elapsed_seconds': status.get('elapsed_seconds', 'unknown'), 'stages': stages, 'calls': calls,
        'figures': figures, 'datasets': len(tables),
        'technical_verification': verification.get('status', 'NOT_RUN'),
        'review': review_state(root), 'source_records': refs,
        'boundary': 'Technical verification and transport records do not establish scientific adequacy, served identity without evidence, human approval or fit readiness.'}


def export(root, out=None):
    value = summarize(root); out = Path(out) if out else Path(root)
    out.mkdir(parents=True, exist_ok=True)
    write_json(out / 'run_summary.json', value)
    e = lambda x: html.escape(str(x))
    rows = ''.join('<tr><td>' + e(s['stage']) + '</td><td>' + e(s['status']) + '</td><td>' + e(s['seconds']) + '</td></tr>' for s in value['stages'])
    (out / 'run_summary.html').write_text('<!doctype html><html lang="en"><meta charset="utf-8"><title>EDA run summary</title><h1>EDA run summary</h1><p>'
        + e(value['execution_status']) + ' · ' + e(value['datasets']) + ' datasets · ' + e(value['figures']) + ' figures</p><p>Requested model: '
        + e(value['requested_model']) + '; served: ' + e(value['served_models']) + '</p><p>Review: ' + e(value['review']['status'])
        + '</p><p>' + e(value['review']['next_step']) + '</p><table><tr><th>Stage</th><th>Record</th><th>Seconds</th></tr>' + rows
        + '</table><p>' + e(value['boundary']) + '</p><a href="run_summary.json">Bound records, budgets and details</a></html>', encoding='utf-8')
    return value


def main():
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('root'); p.add_argument('--out', required=True)
    a = p.parse_args(); print(export(a.root, a.out)['review'])


if __name__ == '__main__': main()
