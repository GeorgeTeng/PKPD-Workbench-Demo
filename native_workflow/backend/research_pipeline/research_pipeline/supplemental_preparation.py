"""Source-bound normalization for the supplemental MIC, binding and PD tables.

No published PK parameter file is read. Group summaries remain summaries, and
reported dose schedules do not imply observed or model-derived exposures.
"""
import copy
import math
import re


def normalize_supplemental(table):
    headers = list(table['column_map'].values())
    rows = table['records']
    def base(r):
        return copy.deepcopy(r)
    def values(r):
        return {label: r[key] for key, label in table['column_map'].items()}
    def numeric(v, name, positive=False):
        if not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v) or (positive and v <= 0):
            raise ValueError('Invalid ' + name + ': ' + repr(v))
        return v
    def ds(name, records, **metadata):
        return {'name': name, 'records': records, 'metadata': metadata}
    study = re.findall(r'\bS\d+\b', table['source_notes'])[0]
    if headers[:3] == ['Species', 'Strain', 'PMB MIC (mg/L)']:
        result = []
        for r in rows:
            v = values(r)
            result.append({**base(r), 'study_id': study, 'pathogen': v['Species'],
                           'strain': str(v['Strain']), 'mic_mg_L': numeric(v['PMB MIC (mg/L)'], 'MIC', True)})
        return [ds(study + '_strain_MIC', result, species='mouse', study_id=study,
                   record_level='strain_susceptibility', concentration_basis='not_applicable')]
    if headers == ['Study', 'Reported measure', 'Mean (%)', 'SD (percentage points)', 'Method', 'Plasma material']:
        result = []
        for r in rows:
            v = values(r); mean = numeric(v['Mean (%)'], 'binding mean'); sd = numeric(v['SD (percentage points)'], 'binding SD')
            if not (0 <= mean <= 100 and sd >= 0) or v['Reported measure'] not in ('Bound', 'Unbound'):
                raise ValueError('Invalid binding definition')
            fu = mean / 100 if v['Reported measure'] == 'Unbound' else 1 - mean / 100
            record = {**base(r), 'study_id': v['Study'], 'reported_measure': v['Reported measure'],
                      'reported_mean_percent': mean, 'reported_SD_percentage_points': sd,
                      'fu_mean': fu, 'fu_SD': sd / 100, 'method': v['Method'], 'plasma_material': v['Plasma material'],
                      'derivation': 'percent/100' if v['Reported measure'] == 'Unbound' else '1-bound_percent/100',
                      'individual_animal_count': 'NOT_FOUND'}
            result.append(ds(v['Study'] + '_plasma_binding', [record], species='mouse', study_id=v['Study'],
                             matrix='plasma', record_level='group_summary', uncertainty_type='SD',
                             transfer_to_other_study_or_ELF_allowed=False))
        return result
    if headers == ['Regimen label', 'Dose (mg/kg)', 'Interval (h)', 'Strain', 'Route', 'Window start (h)', 'Window end (h)']:
        result = []
        for r in rows:
            v = values(r); dose = numeric(v['Dose (mg/kg)'], 'dose', True); tau = numeric(v['Interval (h)'], 'interval', True)
            start = numeric(v['Window start (h)'], 'window start'); end = numeric(v['Window end (h)'], 'window end')
            if start != 0 or end != 24 or v['Route'] != 'SC':
                raise ValueError('New regimen definition requires review')
            times = [start + n * tau for n in range(math.ceil((end - start) / tau))]
            result.append({**base(r), 'study_id': study, 'experiment_id': study + '_DOSE_FRACTIONATION',
                           'regimen_id': v['Regimen label'], 'strain': v['Strain'], 'route': v['Route'],
                           'dose_mg_kg': dose, 'dose_basis': 'PMB_sulphate_as_reported', 'interval_h': tau,
                           'dose_times_h': times, 'window_h': [start, end],
                           'response': None, 'response_status': 'NOT_SUPPLIED_FOR_REGIMEN', 'exposure_status': 'NOT_SUPPLIED'})
        return [ds(study + '_dose_fractionation_regimens', result, species='mouse', study_id=study,
                   record_level='regimen_design', matrix='plasma_exposure_not_supplied')]
    if headers == ['Strain', 'Dose level', 'Daily dose (mg/kg/24 h)', '24 h mean', '24 h SD', 'Reported n', '0 h mean', '0 h SD']:
        groups = {}
        for r in rows:
            v = values(r); missing = v['24 h mean'] == 'ND'
            if missing:
                if v['24 h SD'] != 'ND' or v['Reported n'] != 'ND':
                    raise ValueError('Inconsistent ND summary')
                mean = sd = n = None
            else:
                mean = numeric(v['24 h mean'], 'endpoint'); sd = numeric(v['24 h SD'], 'endpoint SD')
                n = numeric(v['Reported n'], 'reported n', True)
                if sd < 0 or int(n) != n: raise ValueError('Invalid summary SD/n')
            baseline = numeric(v['0 h mean'], 'baseline')
            daily = numeric(v['Daily dose (mg/kg/24 h)'], 'daily dose', True)
            record = {**base(r), 'study_id': study, 'experiment_id': study + '_T3', 'strain': v['Strain'],
                      'regimen_id': study + '_T3_' + v['Strain'] + '_' + str(v['Dose level']),
                      'route': 'SC', 'daily_dose_mg_kg': daily, 'dose_mg_kg': daily / 3,
                      'dose_basis': 'PMB_sulphate_as_reported', 'dose_times_h': [0, 8, 16], 'interval_h': 8,
                      'response_time_h': 24, 'response': mean, 'response_SD': sd, 'reported_n': n,
                      'baseline_mean': baseline, 'baseline_SD': numeric(v['0 h SD'], 'baseline SD'),
                      'change_from_baseline': None if missing else mean - baseline,
                      'status': 'NOT_DETERMINED' if missing else 'QUANTIFIED_GROUP_SUMMARY',
                      'independent_animals': 'NOT_FOUND', 'animal_cluster_ids': 'NOT_FOUND',
                      'response_unit': 'log10 CFU/thigh', 'exposure_status': 'NOT_SUPPLIED'}
            groups.setdefault(v['Strain'], []).append(record)
        return [ds(study + '_T3_' + re.sub(r'[^A-Za-z0-9]+', '_', strain), records,
                   species='mouse', study_id=study, experiment_id=study + '_T3', strain=strain,
                   pathogen='K. pneumoniae', route='SC', matrix='thigh', record_level='group_summary',
                   response_definition='Absolute 24 h log10 CFU/thigh group mean; baseline change stored separately',
                   untreated_endpoint_E0='NOT_SUPPLIED', concentration_basis='free_exposure_not_supplied')
                for strain, records in groups.items()]
    if headers == ['Interval (h)', 'Dose range (mg/kg)', 'Daily dose range (mg/kg)', 'Interpretation']:
        result = [{**base(r), 'study_id': study, 'interval_h': values(r)['Interval (h)'],
                   'dose_range_as_reported': values(r)['Dose range (mg/kg)'],
                   'daily_range_as_reported': values(r)['Daily dose range (mg/kg)'],
                   'status': values(r)['Interpretation']} for r in rows]
        return [ds(study + '_dose_range_conflict', result, species='mouse', study_id=study,
                   record_level='context_only', dose_grid_generated=False)]
    raise ValueError('Unsupported supplemental table schema: ' + table['title'])
