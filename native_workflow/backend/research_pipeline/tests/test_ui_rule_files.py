import hashlib

from fastapi.testclient import TestClient

from research_pipeline.ui_rule_files import rule_sources
from research_pipeline.workbench import create_workbench


def test_catalog_downloads_original_allowlisted_files_without_rule_editor(tmp_path):
    client = TestClient(create_workbench(tmp_path / 'outputs', tmp_path / 'state'))
    before = {s[0]: s[4].read_bytes() for s in rule_sources()}
    result = client.get('/ui-api/workflow/rule-catalog')
    assert result.status_code == 200
    catalog = result.json()
    assert catalog['read_only'] is True
    assert {f['id'] for f in catalog['files']} == set(before)
    for file in catalog['files']:
        assert 'rules' not in file and 'path' not in file
        response = client.get(file['url'])
        assert response.status_code == 200
        assert response.content == before[file['id']]
        assert hashlib.sha256(response.content).hexdigest() == file['sha256']
        assert 'attachment' in response.headers['content-disposition']
    assert client.get('/ui-api/workflow/rule-files/unknown').status_code == 404
    assert client.post('/ui-api/workflow/rule-files/general', json={}).status_code == 405
    assert before == {s[0]: s[4].read_bytes() for s in rule_sources()}
    assert not list((tmp_path / 'state/canvas_sessions').glob('*/session.json'))


def test_rule_files_use_existing_api_auth(tmp_path, monkeypatch):
    monkeypatch.setenv('RESEARCH_PIPELINE_API_TOKEN', 'synthetic-test-token')
    client = TestClient(create_workbench(tmp_path / 'outputs', tmp_path / 'state'))
    for path in ['/ui-api/workflow/rule-catalog', '/ui-api/workflow/rule-files/general']:
        assert client.get(path).status_code == 401
        assert client.get(path, headers={'Authorization':'Bearer synthetic-test-token'}).status_code == 200
