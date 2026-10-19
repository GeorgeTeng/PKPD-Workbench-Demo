import copy
import pytest
from research_pipeline.index_screening import screen_index_dataset, INDICES, EXPANDED_SPECS


def valid_payload():
    rows=[dict(unit_id=f'u{i}',regimen_id=f'r{i}',strain='S1',mic_mg_L=.5,response_time_h=24,
               response=6-i*.5,fAUC_MIC_h=a,fCmax_MIC=c,fT_MIC_percent=t)
          for i,(a,c,t) in enumerate(zip([2,5,7,12,19,30],[.5,.7,1.4,1.6,3.8,4],[4,15,22,45,65,90]))]
    return {'records':rows,'metadata':{'exposure_provenance':'Synthetic test only',
      'index_definitions':{name:{'concentration_basis':'free','unit':unit,'window_h':[0,24]}
        for name,unit in zip(INDICES,['h','dimensionless','%'])}}}


def test_eligible_input_still_requires_review():
    d=valid_payload()
    for row in d['records']: row['log10_CFU_mL']=row['response']
    r=screen_index_dataset(d)
    assert r['status']=='CANDIDATE_REQUIRES_HUMAN_REVIEW' and not r['fit_executed']


def test_no_static_concentration_substitution():
    d={'records':[{'nominal_concentration_mg_L':c,'log10_CFU_mL':6-c} for c in [0,.5,1,2,4]],'metadata':{}}
    original=copy.deepcopy(d);r=screen_index_dataset(d)
    assert r['status']=='BLOCKED' and r['n_complete_index_response_rows']==0 and d==original
    assert {'IDX01_MATCHED_INDICES_MISSING','IDX02_STATIC_SUPPORT_ONLY'}<={v['code'] for v in r['issues']}


def test_proportional_indices_cannot_create_winner():
    d=valid_payload()
    for row in d['records']: row['fAUC_MIC_h']=24*row['fCmax_MIC']
    r=screen_index_dataset(d)
    assert r['status']=='BLOCKED'
    assert any(v['code']=='IDX17_PROPORTIONAL_INDICES' for v in r['issues'])


@pytest.mark.parametrize('fault,expected',[('basis','IDX12_DEFINITION'),('window','IDX13_UNMATCHED_WINDOWS'),
  ('duplicate','IDX07_REPEATED_ENDPOINT'),('missing','IDX01_MATCHED_INDICES_MISSING'),('strain','IDX11_STRAIN_EFFECT')])
def test_invalid_matches_are_blocked(fault,expected):
    d=valid_payload()
    if fault=='basis':d['metadata']['index_definitions']['fCmax_MIC']['concentration_basis']='nominal'
    if fault=='window':d['metadata']['index_definitions']['fAUC_MIC_h']['window_h']=[0,12]
    if fault=='duplicate':d['records'][1]['unit_id']=d['records'][0]['unit_id']
    if fault=='missing':d['records'][0]['fAUC_MIC_h']=None
    if fault=='strain':d['records'][0]['strain']='S2'
    r=screen_index_dataset(d)
    assert r['status']=='BLOCKED' and any(v['code']==expected for v in r['issues'])


def test_optional_indices_do_not_change_primary_eligibility():
    d=valid_payload()
    assert screen_index_dataset(d)['status']=='CANDIDATE_REQUIRES_HUMAN_REVIEW'
    assert screen_index_dataset(d,EXPANDED_SPECS)['status']=='BLOCKED'


def test_trough_and_multiple_threshold_require_explicit_definitions():
    d=valid_payload()
    for i,row in enumerate(d['records']):
        row['fCtrough_MIC']=[.01,.03,.07,.06,.2,.25][i]
        row['fT_4MIC_percent']=[0,1,3,7,20,45][i]
    for name,unit in [('fCtrough_MIC','dimensionless'),('fT_4MIC_percent','%')]:
        d['metadata']['index_definitions'][name]={'unit':unit,'concentration_basis':'free','window_h':[0,24]}
    codes={r['code'] for r in screen_index_dataset(d,EXPANDED_SPECS)['issues']}
    assert {'IDX18_THRESHOLD','IDX19_TROUGH'}<=codes
    d['metadata']['index_definitions']['fCtrough_MIC'].update(trough_definition='pre_dose_left_limit',trough_time_h=24)
    d['metadata']['index_definitions']['fT_4MIC_percent']['threshold_mic_multiplier']=4
    assert screen_index_dataset(d,EXPANDED_SPECS)['status']=='CANDIDATE_REQUIRES_HUMAN_REVIEW'
