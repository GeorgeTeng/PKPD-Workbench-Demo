"""Human gate tests are isolated synthetic fixtures, never real user approval."""
import copy
import pytest
from fastapi.testclient import TestClient
from research_pipeline import data_direct_workflow as workflow
from research_pipeline import data_coverage_direct as coverage, data_necessity_direct as necessity
from research_pipeline.common import read_json, write_json
from research_pipeline.workbench import create_workbench
from test_data_coverage_direct import case, answer as coverage_answer
from test_data_necessity_direct import answer as necessity_answer


@pytest.fixture
def review(case, tmp_path, monkeypatch):
    plan, source, main, _ = case
    mp = write_json(tmp_path/'mp.json', {'profiles': [{'id': 'MP004'}]})
    run = tmp_path/'live'
    def generate(request, **kwargs):
        return (coverage_answer if request['payload']['stage'] == 'DIRECT_DR_COVERAGE' else necessity_answer)(request)
    workflow.run_legacy(plan, source, main, mp, run, generator=generate)
    app = create_workbench(tmp_path, tmp_path/'state')
    store = app.state.direct_data_reviews
    with pytest.raises(ValueError, match='Synthetic results'):
        store.publish(run)
    # Exercise the trusted-real registration boundary with isolated test artifacts.
    for module, path in [(coverage,run/'coverage/coverage.json'),(necessity,run/'necessity/necessity.json')]:
        value = copy.deepcopy(module.verify_result(path))
        value['execution']['test_generator'] = False
        monkeypatch.setattr(module, 'verify_result', lambda path, value=value: value)
    registered = store.publish(run)
    return TestClient(app), store, registered, run, source


def decision(value, choice='APPROVE'):
    return {'decision':choice,'reviewer':'Isolated fixture reviewer','rationale':'Synthetic gate contract test',
            'confirmed':True,'output_signature':value['output_signature']}


def test_original_bytes_and_pending_gate_no_automatic_approval(review):
    client, store, value, run, _ = review
    assert value['status']=='INTERRUPTED' and value['can_review'] and not value['approved']
    assert store.publish(run)['id']==value['id']
    root='/ui-api/data-reviews/'+value['id']
    response=client.get(root+'/artifacts/necessity.json')
    assert response.content==(run/'necessity/necessity.json').read_bytes()
    assert client.get(root+'/artifacts/coverage.json?download=true').headers['content-disposition'].startswith('attachment')
    assert client.get(root+'/artifacts/secret.json').status_code==404
    assert client.get(value['url']).status_code==200
    assert client.get('/assets/data-direct-review.js').status_code==200
    assert store.load(value['id'])['review'] is None


@pytest.mark.parametrize('choice,status',[('APPROVE','APPROVED'),('REQUEST_CHANGES','REVISION_REQUIRED'),('REJECT','REVISION_REQUIRED')])
def test_human_decision_is_recorded_on_original_gate_without_downstream_launch(review,choice,status):
    client, store, value, _, _=review
    url='/ui-api/data-reviews/'+value['id']+'/review'
    response=client.post(url,json=decision(value,choice))
    assert response.status_code==200,response.text
    result=response.json()
    assert result['status']==status and result['review']['decision']==choice
    assert result['downstream_started'] is False and result['scientific_approval'] is False
    history=store.graph.export_history(store.load(value['id'])['gate'])
    assert history[0]['values']['decision']['decision']==choice
    assert client.post(url,json=decision(value,choice)).status_code==409


@pytest.mark.parametrize('change',['result','input','signature'])
def test_stale_output_or_input_cannot_be_approved(review,change):
    client, store, value, run, source=review
    payload=decision(value)
    if change=='result': write_json(run/'coverage/coverage.json',{'changed':True})
    elif change=='input': write_json(source,{'changed':True})
    else: payload['output_signature']='old-version'
    assert client.post('/ui-api/data-reviews/'+value['id']+'/review',json=payload).status_code==409
    assert store.load(value['id'])['review'] is None


def test_changed_file_invalidates_previously_approved_gate(review):
    client,store,value,run,_=review
    root='/ui-api/data-reviews/'+value['id']
    assert client.post(root+'/review',json=decision(value)).status_code==200
    write_json(run/'necessity/necessity.json',{'changed':True})
    result=client.get(root).json()
    assert result['status']=='STALE' and not result['approved'] and not result['can_review']


def test_confirmation_and_same_origin_are_required(review):
    client,store,value,_,_=review
    url='/ui-api/data-reviews/'+value['id']+'/review'
    payload=decision(value)
    payload['confirmed']=False
    assert client.post(url,json=payload).status_code==422
    assert client.post(url,json=decision(value),headers={'Origin':'https://unrelated.test'}).status_code==403
    assert store.load(value['id'])['review'] is None


def test_superseded_gate_retains_evidence_but_cannot_accept_decision(review):
    client,store,value,run,_=review
    saved=store.load(value['id'])
    saved['superseded_by']='data_new_revision'
    write_json(store.path(value['id']),saved)
    root='/ui-api/data-reviews/'+value['id']
    status=client.get(root).json()
    assert status['status']=='SUPERSEDED' and not status['can_review']
    assert client.post(root+'/review',json=decision(value)).status_code==409
    assert client.get(root+'/artifacts/necessity.json').content==(run/'necessity/necessity.json').read_bytes()
    assert store.load(value['id'])['review'] is None
