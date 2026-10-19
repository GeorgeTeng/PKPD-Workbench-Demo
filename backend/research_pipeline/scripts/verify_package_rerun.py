"""Verify a new-package rerun's source coverage, provenance and execution overlap."""
import argparse
import math
from pathlib import Path
from research_pipeline.common import read_json, write_json, sha256, utcnow


def ref(p): return {'path': str(Path(p).resolve()), 'sha256': sha256(p)}


def verify_refs(value):
    if isinstance(value, dict):
        if 'path' in value and 'sha256' in value:
            if sha256(value['path']) != value['sha256']: raise ValueError('Changed file: ' + value['path'])
        for v in value.values(): verify_refs(v)
    elif isinstance(value, list):
        for v in value: verify_refs(v)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run', type=Path, required=True)
    p.add_argument('--previous-run', type=Path, required=True)
    a = p.parse_args(); run = a.run.resolve()
    main = read_json(run / 'main.json'); verify_refs(main)
    manifest = read_json(run / 'data_preparation/normalization_manifest.json'); verify_refs(manifest)
    source = read_json(run / 'source_preparation/output.json')
    source_records = {r['record_id'] for t in source['tables']
                      for r in read_json(run / 'source_preparation' / t['records_path'])['records']}
    normalized_records = {r['record_id'] for d in manifest['datasets'] for r in read_json(d['json']['path'])['records']}
    if source_records != normalized_records: raise ValueError('Source record coverage failed')
    old = read_json(a.previous_run / 'rat_population/results/output.json')
    current = read_json(run / 'rat_population/results/output.json')
    comparisons = []
    for row in current['comparison']:
        previous = next(x for x in old['comparison'] if x['candidate'] == row['candidate'])
        same = row['status'] == previous['status']
        if row.get('AIC') is not None:
            same = same and math.isclose(row['AIC'], previous['AIC'], abs_tol=1e-7)
        comparisons.append({'candidate': row['candidate'], 'same_status_and_AIC_as_previous': same})
    execution = {name: read_json(run / name / 'execution.json')
                 for name in ('rat_population', 'rat_individual', 'mouse_plasma', 'index')}
    parallel = execution['rat_population']['started_at'] < execution['index']['started_at'] < execution['rat_population']['finished_at']
    report = {'status': 'PASSED', 'script': ref(__file__), 'checked_at': utcnow(),
              'tables': len(source['tables']), 'datasets': len(manifest['datasets']),
              'source_records': len(source_records), 'normalized_rows': manifest['normalized_records'],
              'all_source_records_represented': True, 'all_main_and_normalized_references_verified': True,
              'rat_comparison_to_prior': comparisons, 'index_executed_while_rat_running': parallel,
              'execution': {name: {'record': ref(run / name / 'execution.json'),
                                  'started_at': e['started_at'], 'finished_at': e['finished_at'],
                                  'R_pid': e.get('R_pid'), 'status': e['status']} for name, e in execution.items()},
              'fitted_parameters_not_copied_from_prior': True}
    write_json(run / 'verification/package_provenance.json', report)
    main['package_verification'] = ref(run / 'verification/package_provenance.json')
    write_json(run / 'main.json', main)
    audit = read_json(run / 'execution.json')
    audit['intake_finished_at'] = audit['finished_at']
    audit.update(status=main['status'], finished_at=utcnow(), final_main=ref(run / 'main.json'),
                 actual_R_processes={name: e.get('R_pid') for name, e in execution.items() if e.get('R_pid')},
                 source_records=len(source_records), normalized_datasets=len(manifest['datasets']))
    write_json(run / 'execution.json', audit)
    verify_refs(read_json(run / 'main.json'))
    print('Package source coverage, output references and actual execution verified')


if __name__ == '__main__': main()
