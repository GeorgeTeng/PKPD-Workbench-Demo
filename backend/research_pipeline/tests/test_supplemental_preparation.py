import pytest
from research_pipeline.supplemental_preparation import normalize_supplemental


def table(headers, rows):
    mapping = {f'c{i}': h for i, h in enumerate(headers)}
    return {'title': 'Test supplied table', 'source_notes': 'S02 | https://doi.org/10.1093/example',
            'column_map': mapping,
            'records': [{**dict(zip(mapping, values)), 'record_id': f'T_R{n}',
                         'source_cells': {key: f'{i}_{n}' for i, key in enumerate(mapping)}}
                        for n, values in enumerate(rows)]}


def test_binding_percent_conversion_keeps_studies_and_uncertainty_separate():
    d = table(['Study', 'Reported measure', 'Mean (%)', 'SD (percentage points)', 'Method', 'Plasma material'],
              [['S01', 'Unbound', 20, 4, 'ultrafiltration', 'infected'],
               ['S02', 'Bound', 91.4, 1.65, 'ultracentrifugation', 'pooled']])
    a, b = normalize_supplemental(d)
    assert a['records'][0]['fu_mean'] == pytest.approx(.2)
    assert b['records'][0]['fu_mean'] == pytest.approx(.086)
    assert b['records'][0]['fu_SD'] == pytest.approx(.0165)
    assert a['metadata']['study_id'] != b['metadata']['study_id']
    assert not b['metadata']['transfer_to_other_study_or_ELF_allowed']


def test_table3_nd_is_not_zero_and_group_n_does_not_expand_observations():
    d = table(['Strain', 'Dose level', 'Daily dose (mg/kg/24 h)', '24 h mean', '24 h SD',
               'Reported n', '0 h mean', '0 h SD'],
              [['KP032', 1, 22.5, 5.3, .27, 4, 6.8, .08],
               ['KP032', 2, 120, 'ND', 'ND', 'ND', 6.8, .08]])
    result = normalize_supplemental(d)[0]
    assert len(result['records']) == 2
    a, b = result['records']
    assert a['response'] == 5.3 and a['change_from_baseline'] == pytest.approx(-1.5)
    assert a['dose_mg_kg'] == 7.5 and a['dose_times_h'] == [0, 8, 16]
    assert a['reported_n'] == 4 and a['independent_animals'] == 'NOT_FOUND'
    assert b['response'] is None and b['status'] == 'NOT_DETERMINED'
    assert result['metadata']['untreated_endpoint_E0'] == 'NOT_SUPPLIED'
    assert b['source_cells'] == d['records'][1]['source_cells']


def test_design_schedule_preserves_rounding_without_inventing_exposure_or_endpoint():
    d = table(['Regimen label', 'Dose (mg/kg)', 'Interval (h)', 'Strain', 'Route', 'Window start (h)', 'Window end (h)'],
              [['regimen', .83, 8, 'KP032', 'SC', 0, 24]])
    r = normalize_supplemental(d)[0]['records'][0]
    assert r['dose_mg_kg'] == .83 and r['dose_times_h'] == [0, 8, 16]
    assert r['response'] is None and r['exposure_status'] == 'NOT_SUPPLIED'
    assert 'fAUC_MIC_h' not in r


def test_unknown_supplemental_schema_stops():
    with pytest.raises(ValueError, match='Unsupported supplemental'):
        normalize_supplemental(table(['Unknown', 'Value'], [['x', 1]]))
