"""Offline ContextBuilder benchmark against immutable real request snapshots.

No provider calls, response reuse, scientific acceptance or source mutation.
Timings exclude interpreter/import startup and include explicitly named phases.
"""
import argparse
import copy
import html
import json
import statistics
import time
from pathlib import Path

from ctxcomp import providers
from ctxcomp.io import canonical, digest
from . import context_builder as cb, context_model_view as mv, context_budget, context_routes, context_optimization
from .common import read_json, write_json


def evidence_view(value):
    value = copy.deepcopy(value)
    if isinstance(value, list):
        for row in value:
            if isinstance(row, dict):
                row.pop('text_sha256', None)
                row.pop('original_sha256', None)
    return value


def probe(path, out, repetitions=5):
    path, out = Path(path).resolve(), Path(out).resolve()
    ref = cb.file_ref(path)
    wrapper = read_json(path)
    request = wrapper.get('request', wrapper)
    route = context_routes.select(request['payload'])
    times = []
    for _ in range(repetitions):
        start = time.perf_counter()
        bundle = cb.rebuild_snapshot(*route, path)
        assembled = time.perf_counter()
        wire, projection = mv.project(request)
        projected = time.perf_counter()
        prompt = providers.PROMPT + canonical(wire)
        size = context_budget.check(prompt, request['payload']['schema'])
        budgeted = time.perf_counter()
        cb.verify_bundle(bundle)
        cb.check_refs(projection['bindings'])
        verified = time.perf_counter()
        times.append({'assembly': assembled-start, 'projection': projected-assembled,
                      'serialization_and_budget': budgeted-projected,
                      'verification': verified-budgeted, 'total': verified-start})
    config = read_json(cb.CONFIG)['routes']['.'.join(route)]
    preserved = {}
    restored_payload = context_optimization.expand(wire['payload'])
    for key in set(config['evidence']) | {'governance', 'schema'}:
        if key in request['payload']:
            preserved[key] = evidence_view(request['payload'][key]) == evidence_view(restored_payload.get(key))
    for key in config['rules']:
        if key in request['payload'] and not (key == 'processing_rules' and projection['compiled_rules_audit']):
            preserved[key] = request['payload'][key] == restored_payload.get(key)
    if not all(preserved.values()):
        raise ValueError('Unexpected evidence/rule/schema projection change: ' + str(preserved))
    start = time.perf_counter()
    cb.save_bundle(out, bundle)
    write_json(out/'model_input.json', wire)
    write_json(out/'projection_manifest.json', projection)
    write_json(out/'budget.json', size)
    (out/'model_prompt.txt').write_text(prompt, encoding='utf-8')
    save_seconds = time.perf_counter()-start
    cb.check_refs({'snapshot':ref})
    result = {'status':'PASS', 'route':'.'.join(route), 'source':ref,
              'replay_only':True, 'provider_calls':0, 'scientific_approval':False,
              'request_unchanged':bundle['request']==request,
              'preserved_sections':preserved,
              'compiled_override_groups':len(projection['compiled_rules_audit']),
              'baseline_characters':projection['baseline_model_characters'],
              'model_characters':projection['model_characters'],
              'reduction_percent':100*projection['character_reduction']/projection['baseline_model_characters'],
              'combined_transport_characters':size['combined_input_characters'],
              'budget_status':size['status'], 'timing_samples_seconds':times,
              'median_seconds':{key:statistics.median(t[key] for t in times) for key in times[0]},
              'artifact_write_and_reverify_seconds':save_seconds,
              'timing_scope':'Warm imports; actual filesystem/hash/schema work. No model or network latency.'}
    write_json(out/'probe.json', result)
    return result


def run(paths, out, repetitions=5):
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=False)
    results = []
    for index, path in enumerate(paths, 1):
        try:
            result = probe(path, out/f'{index:02}', repetitions)
        except Exception as exc:
            result = {'status':'REJECTED','source':cb.file_ref(path),'error':str(exc),'provider_calls':0}
        results.append(result)
    report = {'provider_calls':0, 'historical_responses_rebound':False, 'results':results,
              'all_passed':all(r['status']=='PASS' for r in results),
              'quality_scope':'Structural preservation and routing only; not new model-output quality.'}
    write_json(out/'report.json', report)
    rows = []
    for i,r in enumerate(results,1):
        rows.append('<tr><td>'+html.escape(r.get('route',Path(r['source']['path']).name))+'</td><td>'+r['status']+
                    '</td><td>'+str(round(r.get('median_seconds',{}).get('total',0)*1000,2))+
                    '</td><td>'+str(r.get('model_characters',''))+'</td><td>'+str(round(r.get('reduction_percent',0),2))+
                    '</td><td>'+('<a href="'+f'{i:02}/model_input.json">Input</a>' if r['status']=='PASS' else html.escape(r['error']))+'</td></tr>')
    (out/'report.html').write_text('<!doctype html><html lang="en"><meta charset="utf-8"><title>ContextBuilder audit</title>'
        '<style>body{font:16px/1.5 system-ui;max-width:1150px;margin:40px auto}td,th{padding:10px;border-bottom:1px solid #ccc;text-align:left}</style>'
        '<h1>ContextBuilder: routing, preservation and local timing</h1><p>Immutable request replay. Zero model calls. '
        'Historical responses are not outputs from these new prompts. All sizes are characters, not tokens.</p>'
        '<table><tr><th>Stage</th><th>Result</th><th>Local median ms</th><th>Model input</th><th>Reduction %</th><th>Details</th></tr>'+
        ''.join(rows)+'</table><p>Local timing includes assembly, projection, serialization, budget and binding verification; '
        'artifact writes are separately recorded. Warm imports; five samples by default.</p><a href="report.json">Full measurements</a></html>',encoding='utf-8')
    return report


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request', action='append', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--repetitions', type=int, default=5)
    args=parser.parse_args()
    if args.repetitions < 1: parser.error('repetitions must be positive')
    result=run(args.request,args.out,args.repetitions)
    print(json.dumps(result,ensure_ascii=False))
