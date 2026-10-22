import copy
import csv
import io
import math
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from research_pipeline.api import create_app
from research_pipeline.attachments import store_upload, uploaded_path
from research_pipeline.common import BACKEND, PROJECT, PipelineError, read_json, write_json, sha256, verify_context
from research_pipeline.engine import run_pipeline, validate_request, SCHEMAS
from research_pipeline.literature import LocalLibrary, candidate_screen
from research_pipeline.references import canonical_drug, evaluate_reference, require_reference, REQUIRED_EVIDENCE
from research_pipeline.tables import prepare_records, roberts_fig4b

EXAMPLES = BACKEND / 'research_pipeline/examples'


def request(name='parallel_test'):
    value = read_json(EXAMPLES/'parallel.request.json')
    value['request_id'] = name
    return value


@pytest.fixture(scope='module')
def completed(tmp_path_factory):
    state = tmp_path_factory.mktemp('parallel')
    value = run_pipeline(request(), state, EXAMPLES)
    assert value['status'] == 'SUCCEEDED', value
    return state, value


def test_parallel_contract_and_numeric_ranking(completed):
    state, value = completed
    folder = state/'runs/parallel_test'
    assert len(value['steps']) == 2
    step = read_json(folder/'steps/index/output.json')
    Draft202012Validator(read_json(SCHEMAS/'module-output.schema.json')).validate(step)
    result = step['result']
    assert result['selection']['best_by_R2'] == result['selection']['best_by_AIC'] == ['fAUC_MIC_h']
    assert len(result['models']) == 3
    assert set(result['models'][0]['theta']) == {'E0','Emax','EC50','hill'}
    with (folder/'steps/index/index_predictions.csv').open() as f:
        records = list(csv.DictReader(f))
    y = [float(r['response']) for r in records]
    sst = sum((v-sum(y)/len(y))**2 for v in y)
    for row in result['ranking']:
        sse = sum((float(r['response'])-float(r['predicted_'+row['index']]))**2 for r in records)
        assert row['R2'] == pytest.approx(1-sse/sst, abs=1e-12)
        # E0, Emax, EC50 plus fitted Gaussian variance: k = 4.
        aic = len(y)*(math.log(2*math.pi)+1+math.log(sse/len(y)))+2*4
        assert row['AIC'] == pytest.approx(aic, abs=1e-8)
        k, n = 4, len(y)
        assert row['n_parameters'] == k and row['n_observations'] == n
        assert row['BIC'] == pytest.approx(aic-2*k+k*math.log(n), abs=1e-8)
        assert row['AICc'] == pytest.approx(aic+2*k*(k+1)/(n-k-1), abs=1e-8)
        assert row['log_likelihood'] == pytest.approx(-(aic-2*k)/2, abs=1e-8)
        assert row['rank_R2'] == row['rank_AIC']
        assert row['folds_successful'] == row['folds_total'] == 6
    ranking = result['ranking']
    denominator = sum(math.exp(-r['delta_AIC']/2) for r in ranking)
    assert sum(r['Akaike_weight'] for r in ranking) == pytest.approx(1)
    assert sum(r['AICc_weight'] for r in ranking) == pytest.approx(1)
    for row in ranking:
        assert row['delta_AICc'] == pytest.approx(row['AICc']-min(r['AICc'] for r in ranking))
        assert row['delta_BIC'] == pytest.approx(row['BIC']-min(r['BIC'] for r in ranking))
        assert row['Akaike_weight'] == pytest.approx(math.exp(-row['delta_AIC']/2)/denominator)
    assert result['selection']['status'] == 'PROPOSED_PENDING_HUMAN_REVIEW'
    for step_summary in value['steps']:
        assert sha256(folder/step_summary['output']['path']) == step_summary['output']['sha256']
        directory = folder/'steps'/step_summary['id']
        model_review = read_json(directory/'model_review.template.json')
        assert model_review['result_sha256'] == sha256(directory/'r_result.json')
        assert model_review['decision'] == 'PENDING' and not model_review['approved_for_downstream_use']
        assert read_json(directory/'output.json')['result']['human_review']['status'] == 'PENDING'


def test_failed_pk_does_not_block_index(tmp_path):
    value = request('independence')
    value['steps'][0]['metadata']['time_unit'] = 'min'
    result = run_pipeline(value, tmp_path, EXAMPLES)
    assert result['status'] == 'PARTIAL'
    assert [s['status'] for s in result['steps']] == ['FAILED', 'SUCCEEDED']
    assert read_json(tmp_path/'runs/independence/steps/index/output.json')['result']['selection']['best_by_AIC'] == ['fAUC_MIC_h']


def test_individual_pk_does_not_drop_unidentified_records(tmp_path):
    value = request('missing_pk_id')
    value['steps'] = value['steps'][:1]
    data = read_json(EXAMPLES/'synthetic_pk.json')
    records = data['records'] if isinstance(data,dict) else data
    records[0]['subject_id'] = None
    path = write_json(tmp_path/'missing_id.json',data)
    value['attachments'] = [{'id':'data','path':str(path)}]
    result = run_pipeline(value,tmp_path/'state')
    assert result['status'] == 'FAILED'
    message = read_json(tmp_path/'state/runs/missing_pk_id/steps/pk/output.json')['errors'][0]['message']
    assert 'Missing subject_id' in message


def test_standalone_index_api_upload_run_download(tmp_path):
    value = request('http_index')
    value['steps'] = value['steps'][1:]
    with TestClient(create_app(tmp_path)) as client:
        blob = (EXAMPLES/'synthetic_endpoints.csv').read_bytes()
        uploaded = client.post('/v1/attachments', files={'file':('endpoints.csv', blob)}).json()
        value['attachments'] = [{'id':'endpoints','upload_id':uploaded['upload_id'],'sha256':uploaded['sha256']}]
        response = client.post('/v1/modules/pkpd_index/run', json=value)
        assert response.status_code == 200, response.text
        assert response.json()['status'] == 'SUCCEEDED'
        assert client.get('/v1/runs/http_index').json()['status'] == 'SUCCEEDED'
        result = client.get('/v1/runs/http_index/files/steps/index/output.json').json()
        assert result['result']['selection']['best_by_AIC'] == ['fAUC_MIC_h']
        assert client.post('/v1/runs',json=value).status_code == 409
        assert client.get('/openapi.json').json()['info']['title'] == 'PK/PD Research Pipeline'


@pytest.mark.parametrize('mutation,code', [
    (lambda r:r.update(request_id='../escape'), 'INVALID_REQUEST'),
    (lambda r:r.update(unknown=True), 'INVALID_REQUEST'),
    (lambda r:r['attachments'].append(copy.deepcopy(r['attachments'][0])), 'DUPLICATE_ATTACHMENT'),
    (lambda r:r['steps'][1]['input'].update(upstream_step='unknown'), 'DEPENDENCY_ORDER'),
    (lambda r:r['steps'][1]['input'].update(data_attachment='unknown'), 'MISSING_ATTACHMENT'),
    (lambda r:r.update(search={'provider':'online','query':'model'}), 'DRUG_REQUIRED'),
])
def test_invalid_handoff_rejected(mutation, code):
    value = request()
    mutation(value)
    with pytest.raises(PipelineError) as error:
        validate_request(value)
    assert error.value.code == code


def test_upload_mutation_detected(tmp_path):
    info = store_upload(tmp_path, io.BytesIO(b'abc'), '../../anything.txt')
    path = uploaded_path(tmp_path, info['upload_id'])
    assert path.is_relative_to(tmp_path)
    path.write_bytes(b'changed')
    with pytest.raises(PipelineError, match='hash'):
        uploaded_path(tmp_path, info['upload_id'])


def test_api_does_not_accept_server_paths(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        value = request('forbidden_paths')
        value['attachments'][0]['path'] = str(EXAMPLES/'synthetic_pk.json')
        answer = client.post('/v1/runs',json=value).json()
        assert answer['status'] == 'FAILED'
        assert answer['errors'][0]['code'] == 'LOCAL_PATH_FORBIDDEN'
        assert client.post('/v1/library/index',json={'upload_ids':['unknown']}).status_code == 422


def test_token_authentication(tmp_path, monkeypatch):
    monkeypatch.setenv('RESEARCH_PIPELINE_API_TOKEN','test-token')
    with TestClient(create_app(tmp_path)) as client:
        assert client.get('/v1/health').status_code == 401
        assert client.get('/v1/health',headers={'Authorization':'Bearer test-token'}).status_code == 200


def test_explicit_exclusion_without_imputation():
    rows = [{'time_h':0.5,'concentration_mg_L':1}, {'time_h':1,'concentration_mg_L':None,'status':'BLQ'}]
    with pytest.raises(PipelineError, match='Explicit handling'):
        prepare_records(rows)
    included, excluded = prepare_records(rows,['BLQ'])
    assert len(included) == len(excluded) == 1
    assert excluded[0]['concentration_mg_L'] is None
    with pytest.raises(PipelineError):
        prepare_records([{'response':'NaN'}])


@pytest.mark.parametrize('fault', ['duplicate_unit','missing_index','different_window','missing_basis','constant_response'])
def test_index_comparability_errors(tmp_path, fault):
    value = request('invalid_index')
    value['steps'] = value['steps'][1:]
    value['steps'][0]['options'].pop('group_column')
    with (EXAMPLES/'synthetic_endpoints.csv').open() as file:
        records = list(csv.DictReader(file))
    if fault == 'duplicate_unit':
        records[1]['unit_id'] = records[0]['unit_id']
    elif fault == 'missing_index':
        records[0]['fAUC_MIC_h'] = None
    elif fault == 'constant_response':
        for record in records:
            record['response'] = 1
    elif fault == 'different_window':
        value['steps'][0]['metadata']['index_definitions']['fAUC_MIC_h']['window_h'] = [0,12]
    else:
        del value['steps'][0]['metadata']['index_definitions']['fAUC_MIC_h']['concentration_basis']
    source = write_json(tmp_path/'endpoints.json',records)
    value['attachments'] = [{'id':'endpoints','path':str(source)}]
    result = run_pipeline(value,tmp_path/'state')
    assert result['status'] == 'FAILED'
    assert result['steps'][0]['status'] == 'FAILED'


def test_local_search_offline_drug_filter_staleness(tmp_path, monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError('Local search must not use network')
    monkeypatch.setattr('urllib.request.urlopen', no_network)
    pmb = write_json(tmp_path/'pmb.json',{'title':'PMB model','drug_id':'polymyxin_b','note':'clearance 药代参数模型'})
    cms = write_json(tmp_path/'cms.json',{'title':'CMS model','drug_id':'cms','note':'clearance 药代参数模型'})
    library = LocalLibrary(tmp_path/'library.sqlite3')
    library.index_file(pmb)
    library.index_file(cms)
    library.index_file(pmb)
    assert library.status() == {'documents':2,'chunks':2}
    result = library.search('clearance',drug='PMB')
    assert len(result['results']) == 1 and not result['network_used']
    assert not result['results'][0]['document_changed_since_index']
    assert len(library.search('药代参数',drug='PMB')['results']) == 1
    pmb.write_text('changed',encoding='utf-8')
    assert library.search('clearance',drug='PMB')['results'][0]['document_changed_since_index']


def test_drug_matching_preserves_identity():
    assert canonical_drug('PMB') == canonical_drug('polymyxin b')
    assert len({canonical_drug(x) for x in ['PMB','colistin','CMS','FADDI-365']}) == 4
    assert candidate_screen('SyntheticDrug model','','SyntheticDrug')['same_drug_status'] == 'MENTIONED_NOT_MODEL_VERIFIED'


def reviewed_fixture():
    # Synthetic contract fixture, never a scientific endorsement of a paper.
    card = read_json(EXAMPLES/'model_card.template.json')
    card['publication_type'] = 'primary_research'
    card['model_spec'] = {'family':'one_compartment','route':'IV','species':'rat','matrix':'plasma','concentration_basis':'total'}
    for name in REQUIRED_EVIDENCE:
        card['evidence'][name] = {'status':'SUPPORTED','locator':'synthetic fixture section','finding':'Synthetic test only'}
    card['evidence']['validation']['kind'] = 'external_prediction'
    card['review'] = {'status':'ACCEPTED_FOR_SCOPE','reviewer':'test fixture','reviewed_at':'2026-09-16T00:00:00Z','scope':'synthetic','document_sha256':'a'*64}
    return card


def test_reference_source_and_scope_required():
    card = reviewed_fixture()
    meta = card['model_spec'].copy()
    assert evaluate_reference(card,'PMB',meta,['a'*64])['status'] == 'ACCEPTED_FOR_DECLARED_SCOPE'
    assert 'same_drug' in evaluate_reference(card,'CMS',meta,['a'*64])['unmet']
    assert 'source_binding' in evaluate_reference(card,'PMB',meta,['b'*64])['unmet']
    meta['matrix'] = 'serum'
    assert 'compatible_matrix' in evaluate_reference(card,'PMB',meta,['a'*64])['unmet']
    card['model_spec']['family'] = 'noncompartmental'
    assert 'actual_model' in evaluate_reference(card,'PMB')['unmet']
    assert evaluate_reference(read_json(EXAMPLES/'model_card.template.json'),'PMB')['status'] == 'NEEDS_EVIDENCE_OR_REVIEW'


def test_reference_model_family_must_match():
    card = reviewed_fixture()
    with pytest.raises(PipelineError) as error:
        require_reference(card,'PMB',card['model_spec'],['a'*64],2)
    assert error.value.code == 'REFERENCE_MODEL_MISMATCH'


def test_paper_guided_missing_review_fails(tmp_path):
    value = request('no_review')
    value['steps'] = value['steps'][:1]
    value['steps'][0]['options']['reference_mode'] = 'paper_guided'
    result = run_pipeline(value,tmp_path,EXAMPLES)
    assert result['status'] == 'FAILED'
    assert read_json(tmp_path/'runs/no_review/steps/pk/output.json')['errors'][0]['code'] == 'REFERENCE_REQUIRED'


def test_original_context_preserved():
    path = PROJECT/'outputs/Context_Compression_Local_2026-09-16/demo_run/compressed_context.json'
    if not path.exists():
        pytest.skip('Local upstream example absent')
    value = read_json(path)
    assert verify_context(value) == value.get('context', value)


def test_roberts_observed_data_regression(tmp_path):
    value = read_json(EXAMPLES/'roberts_pmb.request.json')
    if not Path(value['attachments'][0]['path']).exists():
        pytest.skip('User source workbook not present')
    value['request_id'] = 'roberts_test'
    value.pop('context_attachment',None)
    value['attachments'] = value['attachments'][:1]
    rows = roberts_fig4b(value['attachments'][0]['path'],'PMB')
    assert len(rows) == 110
    assert sum(r['status']=='QUANTIFIED' for r in rows) == 102
    result = run_pipeline(value,tmp_path,EXAMPLES)
    assert result['status'] == 'SUCCEEDED'
    model = read_json(tmp_path/'runs/roberts_test/steps/pk/output.json')['result']
    assert model['observations_used'] == 102 and model['subjects'] == 11
    # Original analysis initialized from individual fits; this request uses CL=.2,V=.4.
    # Agreement within 10 ppm accommodates optimizer convergence from different starts.
    assert model['models'][0]['theta']['CL'] == pytest.approx(0.199575666978648, rel=1e-5)
    assert model['models'][0]['theta']['V'] == pytest.approx(0.374457606208701, rel=1e-5)


def test_json_only_pk_helper_handoff(completed, tmp_path):
    state, _ = completed
    value = read_json(EXAMPLES/'synthetic_chain.request.json')
    value['request_id'] = 'portable_pk_helper'
    value['steps'] = value['steps'][1:]
    value['steps'][0]['input'] = {'upstream_attachment':'pk_result'}
    value['attachments'] = [{'id':'pk_result','path':str(state/'runs/parallel_test/steps/pk/output.json')}]
    result = run_pipeline(value,tmp_path,EXAMPLES)
    assert result['status'] == 'SUCCEEDED', result
    assert result['steps'][0]['module'] == 'pkpd_index'
