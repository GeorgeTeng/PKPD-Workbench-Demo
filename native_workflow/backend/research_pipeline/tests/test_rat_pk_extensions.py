import pytest
from research_pipeline.common import read_json,write_json,PipelineError
from research_pipeline.adequacy import file_ref
from research_pipeline.animal_pk_nlmixr2 import validate_qualification
from test_animal_pk_nlmixr2 import synthetic_qualification,changed_data
from research_pipeline.animal_pk_individual import max_available_rse


def test_missing_uncertainty_never_becomes_zero():
    assert max_available_rse([{'delta_method_RSE_percent':None},{}]) is None
    assert max_available_rse([{'delta_method_RSE_percent':float('nan')}]) is None
    assert max_available_rse([{'delta_method_RSE_percent':None},{'delta_method_RSE_percent':21.6}])==21.6


def test_explicit_mass_normalized_units_required(tmp_path):
    q=synthetic_qualification(tmp_path)
    changed_data(q,lambda d:d['metadata'].update(dose_unit='mg/kg',parameter_basis='PER_KG',rate_unit='mg/kg/h'))
    assert validate_qualification(q)['n_observations']==64
    changed_data(q,lambda d:d['metadata'].pop('rate_unit'))
    with pytest.raises(PipelineError,match='Mass-normalized'):validate_qualification(q)


def test_quantified_only_requires_bound_exclusions_and_rat_scope(tmp_path):
    q=synthetic_qualification(tmp_path);q['species']='rat'
    excluded=file_ref(write_json(tmp_path/'excluded.json',{'records':[{'status':'BLQ'}]}))
    changed_data(q,lambda d:d['metadata'].update(species='rat',blq_handling='QUANTIFIED_ONLY_EXPLORATORY',
        excluded_records_ref=excluded,scientific_release=False))
    q['input_refs'].append(excluded)
    with pytest.raises(PipelineError,match='explicit exploratory rat scope'):validate_qualification(q)
    approval=read_json(q['approval_ref']['path']);approval['scope']='EXPLORATORY_RAT_INDIVIDUAL_PK'
    q['approval_ref']=file_ref(write_json(q['approval_ref']['path'],approval))
    assert validate_qualification(q)['n_subjects']==8
    write_json(excluded['path'],{'records':[]})
    with pytest.raises(ValueError):validate_qualification(q)
