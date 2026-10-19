"""Check newly supplied index ingredients within study/experiment; no fitting."""
import argparse
from pathlib import Path
from research_pipeline.common import read_json, write_json, sha256


def ref(p): return {'path': str(p.resolve()), 'sha256': sha256(p)}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run', type=Path, required=True)
    a = p.parse_args(); run = a.run.resolve(); prepared = run / 'data_preparation/normalized'
    sources = {f.stem: (f, read_json(f)) for f in prepared.glob('S*.json')}
    mic, binding, joined, missing, summaries = {}, {}, [], [], []
    for name, (path, d) in sources.items():
        if name.endswith('_strain_MIC'):
            for r in d['records']:
                key = (r['study_id'], r['strain'])
                if key in mic: raise ValueError('Ambiguous study-strain MIC')
                mic[key] = {'value': r['mic_mg_L'], 'source': ref(path), 'record_id': r['record_id']}
        if name.endswith('_plasma_binding'):
            r = d['records'][0]
            if r['study_id'] in binding: raise ValueError('Ambiguous study binding')
            binding[r['study_id']] = {'fu_mean': r['fu_mean'], 'fu_SD': r['fu_SD'], 'source': ref(path),
                                      'record_id': r['record_id'], 'matrix': 'plasma'}
    for name, (path, d) in sources.items():
        if not name.startswith('S02_T3_'): continue
        quant = [r for r in d['records'] if r['status'] == 'QUANTIFIED_GROUP_SUMMARY']
        summaries.append({'strain': d['metadata']['strain'], 'numeric_group_endpoints': len(quant),
                          'dose_schedules': sorted({r['interval_h'] for r in quant}),
                          'individual_animals': 'NOT_FOUND', 'records_are': 'GROUP_MEANS',
                          'Hill_mean_parameter_count': 4,
                          'Hill_residual_df_if_group_means_independent': len(quant)-4,
                          'Emax_mean_parameter_count': 3,
                          'Emax_residual_df_if_group_means_independent': len(quant)-3,
                          'E0': 'Untreated 24 h endpoint not supplied; baseline is not E0'})
        for r in d['records']:
            if r['status'] != 'QUANTIFIED_GROUP_SUMMARY':
                missing.append({'source': ref(path), 'record_id': r['record_id'], 'status': r['status']}); continue
            joined.append({'source': ref(path), 'record_id': r['record_id'],
                'study_id': r['study_id'], 'experiment_id': r['experiment_id'], 'strain': r['strain'],
                'regimen_id': r['regimen_id'], 'dose_mg_kg': r['dose_mg_kg'], 'dose_times_h': r['dose_times_h'],
                'response': r['response'], 'response_SD': r['response_SD'], 'reported_n': r['reported_n'],
                'response_unit': r['response_unit'], 'response_time_h': r['response_time_h'],
                'MIC': mic.get((r['study_id'], r['strain'])), 'binding': binding.get(r['study_id']),
                'binding_transfer_scope': 'Same study plasma; experiment/preparation transfer remains a review item',
                'matched_free_exposure': None, 'individual_animal_links': 'NOT_FOUND',
                'primary_regression_eligible': False})
    design = sources['S02_dose_fractionation_regimens'][1]
    output = {'status': 'BLOCKED_FOR_PRIMARY_INDEX_RANKING', 'benchmark_content_accessed': False,
        'same_study_MIC_records': len(mic), 'binding_studies': binding,
        'dose_fractionation_regimens': len(design['records']),
        'regimens_with_supplied_response': sum(r['response'] is not None for r in design['records']),
        'matched_Table3_group_summaries': joined, 'nonquantitative_endpoints': missing,
        'strain_design_assessment': summaries,
        'primary_complete_free_index_response_rows': 0, 'best_index': None,
        'AIC_BIC_R2': 'NOT_RUN',
        'remaining_gaps': ['No primary measured or independently fitted same-study plasma exposure profiles for these regimens',
            'Full fractionation schedule-to-endpoint mapping absent',
            'Table 3 is a separate q8h experiment with 4/3 group means, no individual animal links',
            'Study S01 printed dose ranges have unresolved source conflicts'],
        'execution_scope': 'Source matching and eligibility only; no reference-only modeled exposures joined'}
    write_json(run / 'index/supplemental_input_audit.json', output)
    print('Index supplement audit:', len(mic), 'MIC records;', len(joined), 'numeric Table 3 means; no eligible complete free-index rows')


if __name__ == '__main__': main()
