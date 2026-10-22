"""Boundary checks plus opt-in real nlmixr2 IV synthetic-data regression."""
import copy
import math
import os
import random

import pytest

from research_pipeline.adequacy import file_ref, check_ref
from research_pipeline.animal_pk_nlmixr2 import validate_qualification, validate_config, fit_adapter, engine_preflight
from research_pipeline.common import read_json, write_json, PipelineError


def synthetic_qualification(folder, compartments=1):
    rng = random.Random(801)
    records = []
    for index in range(1, 9):
        cl = 0.4 * math.exp(rng.gauss(0, 0.15))
        vc = 1.2 * math.exp(rng.gauss(0, 0.12))
        records.append(dict(ID=index, TIME=0, DV=None, AMT=2.0, EVID=1, RATE=0, CMT=1))
        for t in [0.08, 0.25, 0.5, 1, 2, 4, 6, 8]:
            concentration = 2.0 / vc * math.exp(-cl/vc*t) + rng.gauss(0, 0.015)
            records.append(dict(ID=index, TIME=t, DV=max(concentration, 0.003), AMT=0, EVID=0, RATE=0, CMT=1))
    metadata = dict(species='synthetic_rat', record_level='INDIVIDUAL_LONGITUDINAL',
                    permission='DEVELOPMENT_CANDIDATE', route='IV_BOLUS', time_unit='h', dose_unit='mg',
                    concentration_unit='mg/L', exposure_basis='total', matrix='plasma', blq_handling='NO_BLQ',
                    provenance='Synthetic data only; not animal observations or scientific evidence.')
    data = file_ref(write_json(folder/'synthetic.json', dict(metadata=metadata, records=records)))
    candidate = f'synthetic_{compartments}c'
    approval = file_ref(write_json(folder/'approval.json', dict(status='APPROVED', candidate_id=candidate,
                                                              input_refs=[data], synthetic=True)))
    initial = dict(CL=0.3, VC=1.0)
    if compartments >= 2:
        initial.update(Q=0.15, VP=0.6)
    if compartments == 3:
        initial.update(Q2=0.06, VP2=0.3)
    config = dict(engine='nlmixr2', estimator='focei', error_model='additive', initial=initial,
                  bounds={p: [0.001, 100] for p in initial}, random_effects=['CL', 'VC'],
                  omega_initial=dict(CL=0.02, VC=0.02), residual_initial=dict(additive=0.04),
                  seed=801, cores=1, max_outer_iterations=150)
    return dict(candidate_id=candidate, species='synthetic_rat', analysis_id='synthetic_iv',
                compartments=compartments, fit_ready=True, input_refs=[data], approval_ref=approval,
                normalized_data_ref=data, fit_config=config)


def changed_data(q, transform):
    data = read_json(q['normalized_data_ref']['path'])
    transform(data)
    ref = file_ref(write_json(q['normalized_data_ref']['path'], data))
    q['normalized_data_ref'] = ref; q['input_refs'] = [ref]
    approval = read_json(q['approval_ref']['path']); approval['input_refs'] = [ref]
    q['approval_ref'] = file_ref(write_json(q['approval_ref']['path'], approval))


def test_normalized_individual_contract_and_structures(tmp_path):
    for count in [1, 2, 3]:
        q = synthetic_qualification(tmp_path/str(count), count)
        value = validate_qualification(q)
        assert value['n_subjects'] == 8 and value['n_observations'] == 64
    q['fit_config']['initial']['CL'] = 'system("unexpected")'
    with pytest.raises(PipelineError, match='lower < initial'):
        validate_qualification(q)


@pytest.mark.parametrize('key,value', [('record_level','GROUP_MEAN'), ('dose_unit','mg/kg'),
                                     ('route','SC'), ('blq_handling','M3'), ('permission','WITHHELD_VALIDATION')])
def test_unsupported_metadata_is_not_guessed(tmp_path, key, value):
    q = synthetic_qualification(tmp_path)
    changed_data(q, lambda d: d['metadata'].update({key: value}))
    with pytest.raises(PipelineError):
        validate_qualification(q)


def test_hash_and_approval_bindings(tmp_path):
    q = synthetic_qualification(tmp_path)
    other = file_ref(write_json(tmp_path/'unrelated.json', {'metadata':{},'records':[]}))
    q['normalized_data_ref'] = other
    with pytest.raises(PipelineError, match='assigned'):
        validate_qualification(q)
    q = synthetic_qualification(tmp_path)
    approval = read_json(q['approval_ref']['path']); approval['input_refs'] = [other]
    q['approval_ref'] = file_ref(write_json(q['approval_ref']['path'],approval))
    with pytest.raises(PipelineError, match='exact normalized'):
        validate_qualification(q)
    q = synthetic_qualification(tmp_path)
    with open(q['normalized_data_ref']['path'], 'a') as stream:
        stream.write(' ')
    with pytest.raises(ValueError):
        validate_qualification(q)


def test_dose_duplicates_and_unsupported_code_rejected(tmp_path):
    q = synthetic_qualification(tmp_path)
    changed_data(q, lambda d: d['records'].append(copy.deepcopy(d['records'][1])))
    with pytest.raises(PipelineError, match='duplicate'):
        validate_qualification(q)
    q = synthetic_qualification(tmp_path)
    q['fit_config']['code'] = 'anything'
    with pytest.raises(PipelineError, match='executable code'):
        validate_qualification(q)
    q = synthetic_qualification(tmp_path)
    q['fit_config']['estimator'] = 'saem'
    with pytest.raises(PipelineError, match='separately qualified'):
        validate_qualification(q)


@pytest.mark.skipif(os.environ.get('RUN_NLMIXR2_SMOKE') != '1', reason='Set RUN_NLMIXR2_SMOKE=1 for a real local R fit.')
def test_real_nlmixr2_synthetic_iv_fit(tmp_path):
    assert engine_preflight()['available']
    q = synthetic_qualification(tmp_path)
    # This smoke checks the executable path using a declared no-IIV fit. It does
    # not certify mixed-effects scientific adequacy or the clinical project.
    q['fit_config'].update(random_effects=[], omega_initial={}, max_outer_iterations=1000)
    proposal = file_ref(write_json(tmp_path/'proposal.json', dict(decision='CONTINUE', summary='Synthetic smoke only',
                                                                issues=[], requested_changes=[])))
    result = fit_adapter(q, proposal, tmp_path/'attempt')
    assert result['status'] == 'FITTED'
    assert result['estimation_method'] == 'APPROXIMATE_FOCEI'
    # Some installed engine versions report covariance derivative warnings even
    # after an optimizer-success code. They must not be silently passed.
    raw=read_json(result['raw_result_ref']['path'])
    if raw['critical_numerical_messages']:
        assert result['diagnostic_status'] == 'REQUIRES_SCIENTIFIC_REVIEW'
        assert result['numerical_eligibility'] is False
    assert not result['model_release'] and not result['scientific_accepted']
    params = {p['parameter']: p['estimate'] for p in result['parameters']}
    assert 0.25 < params['CL'] < 0.6 and 0.8 < params['VC'] < 1.6
    for key in ['execution_ref','model_code_ref','diagnostics_ref','predictions_ref','fit_object_ref']:
        check_ref(result[key])
    assert result['engine_metrics']['AIC'] is not None
    assert read_json(result['execution_ref']['path'])['fit_calls'] == 1


@pytest.mark.skipif(os.environ.get('RUN_NLMIXR2_SMOKE') != '1', reason='Set RUN_NLMIXR2_SMOKE=1 for a real local R fit.')
def test_real_iv_infusion_events(tmp_path):
    q=synthetic_qualification(tmp_path)
    q['fit_config'].update(random_effects=[], omega_initial={}, max_outer_iterations=1000)
    records=[]; rng=random.Random(88)
    for subject in range(1,5):
        records.append(dict(ID=subject,TIME=0,DV=None,AMT=2.0,EVID=1,RATE=1.0,CMT=1))
        for t in [0.08,0.25,0.5,1,1.5,2,3,4,6,8]:
            dv=(1/0.4)*(1-math.exp(-0.4/1.2*min(t,2)))*math.exp(-0.4/1.2*max(0,t-2))+rng.gauss(0,0.003)
            records.append(dict(ID=subject,TIME=t,DV=dv,AMT=0,EVID=0,RATE=0,CMT=1))
    def infusion(data):
        data['records']=records;data['metadata']['route']='IV_INFUSION'
    changed_data(q,infusion)
    ref=file_ref(write_json(tmp_path/'proposal.json',dict(decision='CONTINUE')))
    result=fit_adapter(q,ref,tmp_path/'attempt')
    assert result['status']=='FITTED'
    if read_json(result['raw_result_ref']['path'])['critical_numerical_messages']:
        assert not result['numerical_eligibility']
    values={p['parameter']:p['estimate'] for p in result['parameters']}
    assert values['CL']==pytest.approx(.4,rel=.05)
    assert values['VC']==pytest.approx(1.2,rel=.05)


@pytest.mark.skipif(os.environ.get('RUN_NLMIXR2_SMOKE') != '1', reason='Set RUN_NLMIXR2_SMOKE=1 for real local R fits.')
@pytest.mark.parametrize('compartments',[2,3])
def test_real_multicompartment_templates(tmp_path, compartments):
    import numpy as np
    from scipy.linalg import expm
    q = synthetic_qualification(tmp_path, compartments)
    true = dict(CL=0.4, VC=1.2, Q=0.8, VP=2.0, Q2=0.18, VP2=4.0)
    config = q['fit_config']
    config.update(random_effects=[], omega_initial={}, max_outer_iterations=1000)
    config['initial'] = {p: true[p]*1.1 for p in config['initial']}
    config['residual_initial'] = dict(additive=0.001)
    k = np.zeros((compartments,compartments)); k[0,0] = -true['CL']/true['VC']
    for j,suffix in [(1,''),(2,'2')]:
        if j >= compartments:
            continue
        outward=true['Q'+suffix]/true['VC']; inward=true['Q'+suffix]/true['VP'+suffix]
        k[0,0]-=outward; k[j,0]=outward; k[0,j]=inward; k[j,j]=-inward
    records=[]; rng=random.Random(99)
    for subject in range(1,5):
        records.append(dict(ID=subject,TIME=0,DV=None,AMT=2.0,EVID=1,RATE=0,CMT=1))
        for t in [0.01,0.04,0.1,0.25,0.5,1,2,3,4,6,8,12,18,24,36,48]:
            dv=2.0*expm(k*t)[0,0]/true['VC']+rng.gauss(0,0.0001)
            records.append(dict(ID=subject,TIME=t,DV=max(float(dv),0.00001),AMT=0,EVID=0,RATE=0,CMT=1))
    changed_data(q,lambda d:d.update(records=records))
    proposal=file_ref(write_json(tmp_path/'proposal.json',dict(decision='CONTINUE')))
    result=fit_adapter(q,proposal,tmp_path/'attempt')
    assert result['status']=='FITTED' and result['compartments']==compartments
    assert len(result['parameters'])==compartments*2
    assert all(math.isfinite(p['estimate']) and p['estimate']>0 for p in result['parameters'])
    assert not result['model_release']
