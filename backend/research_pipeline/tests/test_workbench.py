from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from research_pipeline.common import read_json, write_json, sha256
from research_pipeline.workbench import create_workbench


@pytest.fixture
def space(tmp_path):
    outputs = tmp_path / 'outputs'; run = outputs / 'PMB_test'; state = tmp_path / 'state'
    data = run / 'data_preparation/normalized/example.json'
    write_json(data, {'metadata': {'species': 'rabbit', 'record_level': 'group_summary'},
                     'records': [{'record_id': 'R1', 'response': None, 'status': 'NOT_DETERMINED'},
                                 {'record_id': 'R2', 'response': 0, 'status': 'QUANTIFIED'}]})
    ref = lambda p: {'path': str(p), 'sha256': sha256(p)}
    manifest = run / 'data_preparation/normalization_manifest.json'
    write_json(manifest, {'datasets': [{'id': 'example', 'json': ref(data), 'record_count': 2,
                                      'metadata': {'species': 'rabbit'}}], 'source_records': 2})
    prep = run / 'data_preparation/main.json'; write_json(prep, {'normalization_manifest': ref(manifest)})
    branch = run / 'rat_population/results/output.json'; write_json(branch, {'comparison': []})
    main = run / 'main.json'
    write_json(main, {'created_at': '2026-09-19T00:00:00Z', 'status': 'PARTIAL_PENDING_HUMAN_REVIEW',
                     'branches': {'rat_population': ref(branch)}, 'upstream': {'data_preparation': ref(prep)}})
    app = create_workbench(outputs, state)
    return TestClient(app), run, state


def test_real_artifact_routes_and_static_ui(space):
    client, run, _ = space
    assert client.get('/').status_code == 200
    assert 'Translational Research Workbench' in client.get('/').text
    assert 'lang="en"' in client.get('/').text
    assert client.get('/assets/canvas.js').status_code == 200
    assert client.get('/assets/app.js').status_code == 404
    runs = client.get('/ui-api/runs').json()['runs']
    assert [r['id'] for r in runs] == ['PMB_test']
    detail = client.get('/ui-api/runs/PMB_test').json()
    assert detail['data']['summary']['source_records'] == 2
    assert detail['main_sha256'] == sha256(run / 'main.json')


def test_only_current_frontend_is_served_without_stale_asset_cache(space):
    import re
    client, _, _ = space
    response = client.get('/')
    assert response.headers['cache-control'] == 'no-store'
    assert 'name="workbench-build"' in response.text
    for asset in re.findall(r'(?:src|href)="(/assets/[^"?]+\.(?:js|css)\?v=[a-f0-9]+)"', response.text):
        resource = client.get(asset)
        assert resource.status_code == 200
        assert resource.headers['cache-control'] == 'no-store'
        assert asset.split('v=')[-1] == __import__('hashlib').sha256(resource.content).hexdigest()[:16]
    assert 'workbench.css?v=' in response.text
    for path in ['/assets/app.js','/assets/style.css']:
        assert client.get(path).status_code == 404
    for path in ['/assets/results-index.html','/assets/index.html']:
        redirect = client.get(path+'?flow=synthetic',follow_redirects=False)
        assert redirect.status_code == 307
        assert redirect.headers['location'] == '/?flow=synthetic'


def test_dataset_pagination_preserves_zero_and_missing(space):
    client, _, _ = space
    missing = client.get('/ui-api/runs/PMB_test/datasets/example?offset=0&limit=1').json()
    zero = client.get('/ui-api/runs/PMB_test/datasets/example?offset=1&limit=1').json()
    assert missing['total'] == 2 and missing['records'][0]['response'] is None
    assert zero['records'][0]['response'] == 0


def test_download_cannot_escape_run_or_open_reference_content(space):
    client, run, _ = space
    write_json(run / 'attachments/F0002.json', {'reference': 'not for display'})
    write_json(run / 'benchmark_reference.json', {'reference': 'not for display'})
    assert client.get('/ui-api/runs/PMB_test/files/attachments/F0002.json').status_code == 403
    assert client.get('/ui-api/runs/PMB_test/files/benchmark_reference.json').status_code == 403
    assert client.get('/ui-api/runs/PMB_test/files/%2e%2e/outside.json').status_code == 404
    assert client.get('/ui-api/runs/PMB_test/files/main.json?download=true').status_code == 200


def review_payload(run):
    return {'main_sha256': sha256(run / 'main.json'), 'reviewer': 'Test reviewer',
            'decision': 'REQUEST_CHANGES', 'rationale': 'Need independent validation', 'confirmed_scope': True}


def test_review_is_append_only_and_does_not_release_science(space):
    client, run, state = space
    before = sha256(run / 'main.json')
    response = client.post('/ui-api/runs/PMB_test/reviews', json=review_payload(run))
    assert response.status_code == 200
    assert response.json()['downstream_scientific_use_allowed'] is False
    assert response.json()['data_gate_modified'] is False
    assert sha256(run / 'main.json') == before
    assert len(list((state / 'workbench_reviews/PMB_test').glob('*.json'))) == 1
    assert client.get('/ui-api/runs/PMB_test').json()['reviews'][0]['current']


def test_stale_review_and_modified_branch_are_rejected(space):
    client, run, _ = space
    body = review_payload(run); body['main_sha256'] = '0' * 64
    assert client.post('/ui-api/runs/PMB_test/reviews', json=body).status_code == 409
    body = review_payload(run)
    write_json(run / 'rat_population/results/output.json', {'changed': True})
    assert client.post('/ui-api/runs/PMB_test/reviews', json=body).status_code == 409


def test_cross_origin_mutation_rejected_for_ui_and_existing_api(space):
    client, run, _ = space
    headers = {'origin': 'https://unrelated.example'}
    assert client.post('/ui-api/runs/PMB_test/reviews', json=review_payload(run), headers=headers).status_code == 403
    assert client.post('/pipeline/v1/attachments', files={'file': ('x.txt', b'x')}, headers=headers).status_code == 403


def test_api_token_protects_data_but_ui_can_load(space, monkeypatch):
    client, _, _ = space; monkeypatch.setenv('RESEARCH_PIPELINE_API_TOKEN', 'test-secret')
    assert client.get('/').status_code == 200
    assert client.get('/ui-api/runs').status_code == 401
    assert client.get('/ui-api/runs', headers={'Authorization': 'Bearer test-secret'}).status_code == 200


def test_jobs_require_a_portable_baseline_before_launch(space):
    client, _, _ = space
    response = client.post('/ui-api/jobs', json={'baseline_run': 'PMB_test', 'package_upload_id': 'unknown'})
    assert response.status_code == 422
    assert client.get('/ui-api/jobs').json()['jobs'] == []


def test_fresh_upload_job_needs_no_historical_baseline(space, monkeypatch):
    client, run, state = space
    class Process:
        def poll(self): return None
    monkeypatch.setattr('research_pipeline.workbench.subprocess.Popen', lambda *a, **k: Process())
    proposal = client.post('/pipeline/v1/attachments', files={'file': ('new_proposal.txt', b'Polymyxin B proposal')}).json()
    dataset = client.post('/pipeline/v1/attachments', files={'file': ('new_data.csv', b'time,c\n1,2\n')}).json()
    response = client.post('/ui-api/jobs', json={'upload_ids': [proposal['upload_id'], dataset['upload_id']], 'stop_after': 'intake'})
    assert response.status_code == 202
    spec = read_json(state / 'workbench_jobs' / response.json()['id'] / 'request.json')
    assert spec['mode'] == 'fresh' and 'baseline' not in spec
    assert [x['name'] for x in spec['uploads']] == ['new_proposal.txt', 'new_data.csv']
    assert client.get('/ui-api/jobs/' + response.json()['id']).status_code == 200


def test_new_data_cannot_jump_to_fitting(space):
    client, _, _ = space
    assert client.post('/ui-api/jobs', json={'upload_ids': ['unused'], 'stop_after': 'exploratory_results'}).status_code == 422


def test_model_status_returns_no_credentials(space, monkeypatch):
    client, _, _ = space
    monkeypatch.setattr('research_pipeline.model_connection.connection_status', lambda: {'logged_in': True, 'method': 'ChatGPT'})
    assert client.get('/ui-api/model/status').json() == {'logged_in': True, 'method': 'ChatGPT'}
