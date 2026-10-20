"""One PMB Label-only comparison against retained baseline; never runs other stages."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import statistics
import sys
import threading
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import app
from research_pipeline import data_agents as da
from research_pipeline.common import write_json, utcnow


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        raise SystemExit('Use a new comparison directory; existing evidence is never overwritten.')
    baseline = ROOT/'examples/acceptance/pmb/handoffs'
    calls = [c for c in read(baseline/'index.json')['calls'] if c['stage'] == 'DC-label']
    old = {}
    for call in calls:
        payload = read(baseline/call['id']/'request.json')['payload']
        old[(payload['item_id'],payload['page'])] = payload
    assert len(old) == len(calls) == 52
    req_ref = read(ROOT/'examples/acceptance/pmb/adequacy/data_labels.json')['requirements']
    da.check_ref(req_ref)
    req = read(req_ref['path'])
    for ref in (req['main'],req['inventory']):
        da.check_ref(ref)
    output.mkdir(parents=True)
    app.configure_model('codex', 'gpt-6.1-sol', 'high')
    os.environ.update(CTXCOMP_DISABLE_RESPONSE_REUSE='1', PKPD_DEMO_LIGHTWEIGHT_DATA='1',
                      PKPD_DEMO_PROVISIONAL_RULES='1', DATA_AGENT_WORKERS='4')
    code = [ROOT/'backend/research_pipeline/research_pipeline'/name for name in ('data_agents.py','demo_data.py')]
    code_hashes = {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in code}
    report = {'status':'LABEL_RUNNING', 'example':'pmb', 'started_at':utcnow(),
              'scope':'LABEL_ONLY_ON_FROZEN_UPSTREAM_INPUTS', 'baseline_is_historical':True,
              'new_context_rules_or_requirements_calls':0, 'other_examples_run':False,
              'requested_model':'gpt-6.1-sol', 'requested_reasoning_effort':'high',
              'served_model_verified':False, 'workers':4, 'response_reuse_disabled':True,
              'input_refs':{'main':req['main'],'inventory':req['inventory'],'requirements':req_ref},
              'code_sha256':code_hashes}
    write_json(output/'comparison.json',report)
    invoke = da.invoke
    lock = threading.Lock()
    completed = []
    def checked_invoke(run, stage, payload, schema, **options):
        assert stage == 'DC-label'
        prior = old[(payload['item_id'],payload['page'])]
        for key in ('source_units','project_rules','label_vocabulary','item_id','page','pages'):
            assert payload[key] == prior[key], (payload['item_id'],key)
        assert payload['requirements'] == [] and payload['method_knowledge'] is None
        response = invoke(run,stage,payload,schema,**options)
        with lock:
            completed.append(payload['item_id'])
            print(json.dumps({'event':'LABEL_COMPLETED','item':payload['item_id'],
                              'completed':len(completed),'total':52,'at':utcnow()}),flush=True)
        return response
    clock = time.perf_counter()
    try:
        with patch.object(da,'invoke',side_effect=checked_invoke):
            da.label(output,req['main']['path'],req['inventory']['path'],req_ref['path'],
                     output/'data_labels.json',model='gpt-6.1-sol')
        report['wall_seconds'] = round(time.perf_counter()-clock,3)
        after = read(output/'data_labels.json')
        before = read(ROOT/'examples/acceptance/pmb/adequacy/data_labels.json')
        assert after['coverage'] == before['coverage']
        assert all(not label['requirement_ids'] for label in after['labels'])
        assert len(after['labels']) == 52
        assert code_hashes == {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in code}
        assert not list(output.rglob('replay.json')) and not list(output.rglob('cache_reuse.jsonl'))
        new_calls = [read(p) for p in (output/'data_agents/audit/DC-label').glob('*/call.json')]
        assert len(new_calls) == 52 and all(c['status']=='RETURNED' for c in new_calls)
        budgets = [read(p) for p in (output/'calls').rglob('budget.json')]
        responses = list((output/'data_agents/audit/DC-label').glob('*/response.json'))
        old_labels = {l['item_id']:l for l in before['labels']}
        differences = []
        for label in after['labels']:
            previous = old_labels[label['item_id']]
            for field in ['role','additional_roles',*da.LABEL_FIELDS]:
                if previous[field] != label[field]:
                    differences.append({'item':label['item_id'],'field':field,
                                        'before':previous[field],'after':label[field]})
            prior_columns = {c['column']:c for c in previous['columns']}
            columns = {c['column']:c for c in label['columns']}
            assert prior_columns.keys() == columns.keys(), label['item_id']
            for position,column in columns.items():
                for field in ('header','meaning','unit','qualifiers'):
                    if prior_columns[position][field] != column[field]:
                        differences.append({'item':label['item_id'],'field':f'columns.{position}.{field}',
                                            'before':prior_columns[position][field],'after':column[field]})
        write_json(output/'label_differences.json',differences)
        report.update(status='LABEL_COMPLETED_REQUIRES_RESULT_COMPARISON', completed_labels=52,
            source_units_and_selected_rules_unchanged=True, coverage_unchanged=True,
            column_positions_unchanged=True, native_evidence_checks_passed=True,
            requirement_matching='DEFERRED', scientific_adequacy='NOT_ASSESSED',
            baseline_label_wall_seconds=1462.106,
            baseline_mean_call_seconds=statistics.mean(c['elapsed_seconds'] for c in calls),
            optimized_mean_call_seconds=statistics.mean(c['elapsed_seconds'] for c in new_calls),
            baseline_prompt_median_bytes=statistics.median(read(baseline/c['id']/'assembled-budget.json')['prompt_utf8_bytes'] for c in calls),
            optimized_prompt_median_bytes=statistics.median(b['prompt_utf8_bytes'] for b in budgets) if budgets else None,
            baseline_response_median_bytes=statistics.median((baseline/c['id']/'response.json').stat().st_size for c in calls),
            optimized_response_median_bytes=statistics.median(p.stat().st_size for p in responses),
            differences_for_review=len(differences), unchanged_code=True)
    except Exception as exc:
        report.update(status='FAILED',error=str(exc),wall_seconds=round(time.perf_counter()-clock,3))
        raise
    finally:
        report['finished_at'] = utcnow()
        report['completed_model_calls'] = len(completed)
        write_json(output/'comparison.json',report)
        print(json.dumps(report),flush=True)


if __name__ == '__main__':
    main()
