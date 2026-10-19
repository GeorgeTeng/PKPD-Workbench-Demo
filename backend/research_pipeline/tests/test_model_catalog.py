import copy
import csv
import os
from pathlib import Path

import pytest

from research_pipeline.common import BACKEND, PROJECT, PipelineError, read_json, sha256
from research_pipeline.engine import run_pipeline
from research_pipeline.model_catalog import COLUMNS, load_catalog, search_catalog, require_catalog_models


@pytest.fixture
def catalog_path(tmp_path):
    supplied = os.environ.get('MODEL_CATALOG_TEST_PATH')
    path = tmp_path / 'catalog.csv'
    if supplied:
        path.write_bytes(Path(supplied).read_bytes())
    else:
        with path.open('w', encoding='utf-8', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=COLUMNS)
            writer.writeheader()
            for model_id, layer in [('PK_SYS_1C_LIN','systemic_pk'), ('PK_SYS_2C_LIN','systemic_pk'),
                                    ('INPUT_IV_BOLUS','input'), ('INPUT_IV_INF','input'),
                                    ('PD_EMAX','pd'), ('PD_SIGMOID','pd'), ('SCALE_EST_EXP','scaling')]:
                writer.writerow(dict(zip(COLUMNS, [model_id, layer, model_id, 'Required data', 'Declared scope', 'Requires review', 1])))
    return path


def options():
    return {'mode':'individual', 'compartments':1}


def worker(duration=0):
    return {'doses':[{'time_h':0, 'dose_mg':100, 'duration_h':duration}]}


def test_supplied_catalog_is_bound_and_rules_are_not_executed(catalog_path):
    catalog = load_catalog(catalog_path)
    assert catalog['source']['sha256'] == sha256(catalog_path)
    assert catalog['scientific_review'] == 'NOT_GRANTED_BY_CATALOG'
    if os.environ.get('MODEL_CATALOG_TEST_PATH'):
        assert len(catalog['models']) == 34
    scaling = search_catalog(catalog, layer='scaling')
    assert scaling and all(m['implementation']=='NOT_IMPLEMENTED' for m in scaling)
    assert all(m['scientific_acceptance']=='NOT_ESTABLISHED' for m in catalog['models'])
    assert search_catalog(catalog, query='unfindable_nonexistent_model') == []


@pytest.mark.parametrize('fault,code', [('duplicate','CATALOG_DUPLICATE_ID'), ('priority','CATALOG_PRIORITY'),
                                     ('layer','CATALOG_LAYER_MISMATCH'), ('missing','CATALOG_ROW')])
def test_malformed_catalog_fails_without_silent_defaults(catalog_path, fault, code):
    with catalog_path.open(encoding='utf-8-sig',newline='') as stream:
        rows=list(csv.DictReader(stream))
    if fault=='duplicate': rows.append(copy.deepcopy(rows[0]))
    if fault=='priority': rows[0]['selection_priority']='not a number'
    if fault=='layer': rows[0]['layer']='pd'
    if fault=='missing': rows[0]['required_data']=''
    with catalog_path.open('w',encoding='utf-8',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=COLUMNS); writer.writeheader(); writer.writerows(rows)
    with pytest.raises(PipelineError) as error: load_catalog(catalog_path)
    assert error.value.code==code


@pytest.mark.parametrize('ids,change,duration,code', [
    (['SCALE_EST_EXP'],{},0,'CATALOG_MODEL_NOT_IMPLEMENTED'),
    (['ABSENT'],{},0,'CATALOG_MODEL_NOT_FOUND'),
    (['PD_EMAX'],{},0,'CATALOG_MODULE_MISMATCH'),
    (['PK_SYS_2C_LIN','INPUT_IV_BOLUS'],{},0,'CATALOG_MODEL_CONFIG_MISMATCH'),
    (['PK_SYS_1C_LIN','INPUT_IV_BOLUS'],{},1,'CATALOG_INPUT_MISMATCH'),
    (['PK_SYS_1C_LIN','INPUT_IV_INF'],{},0,'CATALOG_INPUT_MISMATCH'),
    (['PK_SYS_1C_LIN','INPUT_IV_INF'],{},None,'CATALOG_INPUT_TIMING_MISSING'),
    (['PK_SYS_1C_LIN'],{},0,'CATALOG_INPUT_REQUIRED'),
    (['PK_SYS_2C_LIN','INPUT_IV_BOLUS'],{'compartments':2,'mode':'population_bolus'},0,'CATALOG_MODEL_CONFIG_MISMATCH'),
])
def test_unsupported_or_mismatched_selection_is_rejected(catalog_path, ids, change, duration, code):
    with pytest.raises(PipelineError) as error:
        require_catalog_models(load_catalog(catalog_path),ids,'pk_longitudinal',options()|change,{'route':'IV'},worker(duration))
    assert error.value.code==code


def test_sigmoid_setting_must_match_and_does_not_imply_validation(catalog_path):
    cat=load_catalog(catalog_path)
    with pytest.raises(PipelineError, match='Hill'):
        require_catalog_models(cat,['PD_SIGMOID'],'pkpd_index',{'estimate_hill':False},{},{})
    result=require_catalog_models(cat,['PD_SIGMOID'],'pkpd_index',{'estimate_hill':True},{},{})
    assert not result['rejection_rules_evaluated']
    assert result['scientific_acceptance']=='PENDING_HUMAN_REVIEW'


def add_catalog(request,catalog_path):
    request['attachments'].append({'id':'models','path':str(catalog_path),'sha256':sha256(catalog_path)})
    for step in request['steps']:
        if step['module']=='data_preparation': continue
        step['input']['model_catalog_attachment']='models'
        if not step['input'].get('prepared_step'):
            step['options']['model_catalog_ids']=['PK_SYS_1C_LIN','INPUT_IV_BOLUS'] if step['module']=='pk_longitudinal' else ['PD_EMAX']


def test_catalog_selected_parallel_R_execution(catalog_path,tmp_path):
    request=read_json(BACKEND/'research_pipeline/examples/parallel.request.json')
    request['request_id']='catalog_parallel'
    add_catalog(request,catalog_path)
    state=tmp_path/'state'
    result=run_pipeline(request,state,BACKEND/'research_pipeline/examples')
    assert result['status']=='SUCCEEDED', result
    for step in result['steps']:
        directory=state/'runs/catalog_parallel/steps'/step['id']
        assessment=read_json(directory/'catalog_assessment.json')
        output=read_json(directory/'output.json')
        assert assessment['source']['sha256']==sha256(catalog_path)
        assert assessment['status']=='IMPLEMENTATION_CONFIG_MATCHED'
        assert output['provenance']['attachment_sha256']['models']==sha256(catalog_path)
        assert output['result']['human_review']['decision']=='PENDING'
        assert (directory/'model_review.template.json').exists()
    ranking=read_json(state/'runs/catalog_parallel/steps/index/output.json')['result']['ranking']
    assert len(ranking)==3
    assert all({'R2','AIC','AICc','BIC','Akaike_weight','grouped_CV_RMSE'}<=row.keys() for row in ranking)


def test_catalog_never_overrides_data_review(catalog_path,tmp_path):
    request=read_json(BACKEND/'research_pipeline/examples/preparation_parallel.request.json')
    request['request_id']='catalog_pending_data'
    add_catalog(request,catalog_path)
    result=run_pipeline(request,tmp_path/'state',BACKEND/'research_pipeline/examples')
    assert [s['status'] for s in result['steps']]==['WAITING_FOR_REVIEW','SKIPPED','SKIPPED']
    assert not list((tmp_path/'state/runs/catalog_pending_data').rglob('r_result.json'))


def test_unimplemented_scaling_stops_before_R(catalog_path,tmp_path):
    request=read_json(BACKEND/'research_pipeline/examples/parallel.request.json')
    request['request_id']='unsupported_scaling'
    request['steps']=request['steps'][:1]
    add_catalog(request,catalog_path)
    request['steps'][0]['options']['model_catalog_ids']=['SCALE_EST_EXP']
    result=run_pipeline(request,tmp_path/'state',BACKEND/'research_pipeline/examples')
    assert result['status']=='FAILED'
    directory=tmp_path/'state/runs/unsupported_scaling/steps/pk'
    assert read_json(directory/'output.json')['errors'][0]['code']=='CATALOG_MODEL_NOT_IMPLEMENTED'
    assert not (directory/'input.json').exists() and not (directory/'r_result.json').exists()
