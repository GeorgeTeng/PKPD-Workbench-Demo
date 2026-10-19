"""Review gates use isolated synthetic artifacts; never fit or approve research data."""
import io
import pytest
from fastapi.testclient import TestClient
from research_pipeline.attachments import store_upload
from research_pipeline.common import read_json, write_json, sha256
from research_pipeline.workbench import create_workbench
from research_pipeline.workflow_definition import CLINICAL_FIELDS


@pytest.fixture
def canvas(tmp_path):
    app = create_workbench(tmp_path / 'outputs', tmp_path / 'state')
    store = app.state.canvas
    calls = []
    status = {'status': 'RUNNING'}
    store.launch = lambda ids, target: calls.append(('launch', ids, target)) or {'id': 'fixture_job'}
    store.resume = lambda identifier, target: calls.append(('resume', identifier, target)) or {}
    store.job_status = lambda _: status
    store.pause_job = lambda identifier: calls.append(('pause', identifier))
    client = TestClient(app)
    created = client.post('/ui-api/workflow/sessions').json()
    identifier = created['session_id']
    return client, store, identifier, calls, status


def url(identifier, suffix=''):
    return '/ui-api/workflow/sessions/' + identifier + suffix


def node(response, identifier):
    return next(n for n in response['nodes'] if n['id'] == identifier)['state']


def complete(store, identifier, node_id):
    s = store.load(identifier)
    p = write_json(store.outputs / 'synthetic_test' / (node_id + '.json'),
                   {'test_fixture': True, **({'assessment_status': 'SUFFICIENT_FOR_DEFINED_SCOPE'} if node_id == 'adequacy' else {})})
    store.record_completion(s, node_id, [{'name': node_id + '.json', 'path': str(p), 'sha256': sha256(p)}])
    write_json(store.path(identifier), s)
    return p


def decision(client, identifier, node_id, choice='APPROVE', **overrides):
    signature = node(client.get(url(identifier)).json(), node_id).get('output_signature', '')
    payload = {'decision': choice, 'reviewer': 'Isolated test', 'rationale': 'Synthetic gate test only',
               'confirmed': True, 'output_signature': signature,
               **({'objective_decision': 'CONFIRMED' if choice == 'APPROVE' else 'INCORRECT'} if node_id == 'context' else {}),
               **overrides}
    return client.post(url(identifier, '/nodes/' + node_id + '/review'), json=payload)


def test_template_never_loads_old_files_or_creates_a_session(canvas):
    client, store, identifier, calls, _ = canvas
    write_json(store.outputs / 'PMB_old/main.json', {'branches': {'rat_population': {}}})
    template = client.get('/ui-api/workflow/template').json()
    assert template['session_id'] is None
    assert template['stats'] == {'files': 0, 'completed': 0, 'approved': 0}
    assert len(template['nodes']) == 10
    assert all(not n['state']['can_run'] and not n['state']['can_review'] for n in template['nodes'])
    assert len(list(store.root.glob('*/session.json'))) == 1
    html = client.get('/').text
    script = client.get('/assets/canvas.js').text
    assert '/assets/canvas.js' in html and '/assets/app.js' not in html
    assert '/ui-api/runs' not in script and 'localStorage' not in script
    assert calls == []


def test_context_warnings_and_rules_are_reviewable_downloadable_artifacts(canvas):
    client, store, identifier, _, _ = canvas
    complete(store, identifier, 'intake')
    session=store.load(identifier); session['job_id']='context_rules_fixture'
    run=store.outputs/'context_rules_fixture'
    write_json(store.state/'workbench_jobs/context_rules_fixture/request.json',{'out':str(run)})
    write_json(run/'B1/main.json',{'data':{'files':[]}})
    report={'status':'REVIEW_WARNINGS','warnings':[{'id':'MI001','field':'sampling identity',
        'needed_at':'pk','importance_reason':'Random effects need experimental-unit identity.',
        'downstream_impact':'Individual analysis remains conditional.',
        'requested_information':'Confirm animal IDs.','status':'NOT_FOUND','reason':'No relevant statement.',
        'search':{'files':[]}}]}
    for name,value in [('processing_rules.json',{'rules':[]}),('supporting_evidence.json',{'sources':[]}),
                       ('missing_information_review.json',report)]:
        write_json(run/'context_work/audit'/name,value)
    store.collect_outputs(session,'context'); write_json(store.path(identifier),session)
    state=node(client.get(url(identifier)).json(),'context')
    assert state['missing_information_review']==report
    assert {a['name'] for a in state['artifacts']}=={'main.json','processing_rules.json','supporting_evidence.json','missing_information_review.json'}
    assert state['can_review'] and not state['approved']
    js=client.get('/assets/context-revisions.js').text
    assert 'function renderMissingInformation' in js and 'download-missing-information' in js
    assert 'renderMissingInformation(n)' in client.get('/assets/canvas.js').text
    # The warning and rules share the review signature, so edits invalidate approval.
    write_json(run/'context_work/audit/missing_information_review.json',{'warnings':[]})
    state=node(client.get(url(identifier)).json(),'context')
    assert state['execution']=='STALE' and not state['can_review']


def test_clean_v2_adequacy_requires_confirmation_and_binds_checkpoint(canvas):
    client, store, identifier, calls, _ = canvas
    for name in ['intake', 'context']:
        complete(store, identifier, name)
    assert decision(client, identifier, 'context').status_code == 200
    s = store.load(identifier); s['job_id'] = 'dc008_fixture'
    run = store.outputs / 'dc008_fixture'
    write_json(store.state/'workbench_jobs/dc008_fixture/request.json', {'out':str(run)})
    write_json(run/'adequacy/adequacy.json', {'agent_workflow_version':'2.0',
        'assessment_status':'SUFFICIENT_FOR_DEFINED_SCOPE', 'findings':[], 'can_enter_qc':True,
        'requires_human_review':False, 'llm_review':{'validated':True,'decision':'PASS'}})
    write_json(run/'adequacy/qc_context.json', {'test_fixture':True})
    write_json(run/'adequacy/inventory.json', {'test_fixture':True})
    for relative in ['adequacy/assessment.json','B1/main.json','B1/context_provenance.json']:
        write_json(run/relative, {'test_fixture':True})
    for relative in ['adequacy/evidence_gaps.csv','adequacy/report.md']:
        (run/relative).write_text('Synthetic fixture', encoding='utf-8')
    checkpoint = write_json(run/'adequacy/checkpoint.json', {'confirmation_required':True})
    (run/'adequacy/checkpoint.md').write_text('A person confirms this review.', encoding='utf-8')
    store.collect_outputs(s, 'adequacy'); write_json(store.path(identifier), s)
    current = client.get(url(identifier)).json(); state = node(current, 'adequacy')
    assert state['requires_human_review'] is True and not state['approved']
    assert 'before DP' in state['gate_reason']
    assert state['review'] is None and state['can_review']
    assert {'checkpoint.json','checkpoint.md'} <= {a['name'] for a in state['artifacts']}
    assert not node(current, 'prepare')['can_run']
    assert client.post(url(identifier, '/nodes/prepare/start'), json={}).status_code == 409
    assert decision(client, identifier, 'adequacy').status_code == 200
    assert node(client.get(url(identifier)).json(), 'prepare')['can_run']
    write_json(checkpoint, {'confirmation_required':True, 'changed':True})
    current = client.get(url(identifier)).json()
    assert node(current, 'adequacy')['execution'] == 'STALE'
    assert not node(current, 'prepare')['can_run'] and calls == []


def test_empty_or_unreviewed_step_cannot_start_or_approve(canvas):
    client, _, identifier, calls, _ = canvas
    for n in ['intake', 'context', 'adequacy', 'prepare', 'eda', 'dispatch', 'pk', 'index', 'results', 'clinical']:
        assert client.post(url(identifier, '/nodes/' + n + '/start'), json={}).status_code == 409
        assert decision(client, identifier, n).status_code == 409
    assert client.post(url(identifier, '/nodes/intake/complete'), json={'execution': 'COMPLETED'}).status_code in (404, 405)
    assert calls == []


def test_diagnostic_preparation_has_separate_gate_and_versioned_correction(canvas):
    client, store, identifier, calls, status = canvas
    for name in ['intake','context']:
        complete(store, identifier, name)
        if name == 'context': assert decision(client, identifier, name).status_code == 200
    s = store.load(identifier)
    report = write_json(store.outputs/'diagnostic/adequacy.json', {'assessment_status':'NOT_CALCULABLE',
        'llm_review':{'validated':True,'decision':'PASS'},'can_enter_qc':False})
    qc = write_json(store.outputs/'diagnostic/qc_context.json', {'test_fixture':True})
    artifacts = [{'name':p.name,'path':str(p),'sha256':sha256(p)} for p in [report,qc]]
    store.record_completion(s,'adequacy',artifacts); write_json(store.path(identifier),s)
    assert decision(client,identifier,'adequacy').status_code == 200
    s=store.load(identifier)
    assert not store.dependency_ready(s,'adequacy')
    assert node(client.get(url(identifier)).json(),'prepare')['can_run']
    store.launch_preparation=lambda session: calls.append(('diagnostic',session['nodes']['adequacy']['output_signature'])) or {'id':'qc_job'}
    response=client.post(url(identifier,'/nodes/prepare/start'),json={})
    assert response.status_code==202 and node(response.json(),'prepare')['job_id']=='qc_job'
    # Simulate completion only within this isolated fixture; no scientific approval.
    complete(store,identifier,'prepare')
    n=node(client.get(url(identifier)).json(),'prepare')
    request={'output_signature':n['output_signature'],'confirmed':True,'rationale':'Exact header correction',
             'plan':{'tables':{'T1':{'columns':{'concentration_mg_L':'Mean (mg/L)'}}}}}
    saved=client.post(url(identifier,'/preparation-plan'),json=request)
    assert saved.status_code==200
    assert client.get(url(identifier,'/preparation-plan')).json()['tables']['T1']['columns']['concentration_mg_L']=='Mean (mg/L)'
    assert not node(saved.json(),'prepare')['approved']
    request['plan']['tables']['T1']['columns']['fu']=.2
    assert client.post(url(identifier,'/preparation-plan'),json=request).status_code==422
    assert node(saved.json(),'eda')['locked_by']==['prepare']


def test_completion_alone_rejection_and_changes_all_keep_next_locked(canvas):
    client, store, identifier, calls, _ = canvas
    complete(store, identifier, 'intake')
    complete(store, identifier, 'context')
    current = client.get(url(identifier)).json()
    assert node(current, 'context')['can_review']
    assert node(current, 'adequacy')['locked_by'] == ['context']
    for choice in ['REQUEST_CHANGES', 'REJECT']:
        response = decision(client, identifier, 'context', choice)
        assert response.status_code == 200
        assert node(response.json(), 'adequacy')['locked_by'] == ['context']
        assert client.post(url(identifier, '/nodes/context/start'), json={}).status_code == 409
    approved = decision(client, identifier, 'context')
    assert approved.status_code == 200
    assert node(approved.json(), 'adequacy')['locked_by'] == []
    assert decision(client, identifier, 'context').status_code == 409  # Freeze reviewed version.
    assert len(list((store.root / identifier / 'reviews').glob('*.json'))) == 3
    assert calls == []


def test_signatures_confirmation_and_reviewer_required(canvas):
    client, store, identifier, _, _ = canvas
    complete(store, identifier, 'intake')
    complete(store, identifier, 'context')
    assert decision(client, identifier, 'context', output_signature='stale').status_code == 409
    assert decision(client, identifier, 'context', confirmed=False).status_code == 422
    assert decision(client, identifier, 'context', reviewer=' ').status_code == 422
    assert decision(client, identifier, 'context', choice='REQUEST_CHANGES', rationale='     ').status_code == 422
    assert node(client.get(url(identifier)).json(), 'adequacy')['locked_by'] == ['context']


@pytest.mark.parametrize('comment', ['', '     ', '好', None])
def test_approval_needs_no_comment_and_keeps_human_gate(canvas, comment):
    client, store, identifier, _, _ = canvas
    complete(store, identifier, 'intake')
    complete(store, identifier, 'context')
    signature = node(client.get(url(identifier)).json(), 'context')['output_signature']
    payload = {'decision': 'APPROVE', 'reviewer': 'Synthetic test', 'confirmed': True,
               'output_signature': signature, 'objective_decision': 'CONFIRMED'}
    if comment is not None: payload['rationale'] = comment
    response = client.post(url(identifier, '/nodes/context/review'), json=payload)
    assert response.status_code == 200
    state = node(response.json(), 'context')
    assert state['approved'] and state['langgraph_review']['status'] == 'APPROVED'
    assert state['review']['rationale'] == (comment or '').strip()
    assert node(response.json(), 'adequacy')['locked_by'] == []


@pytest.mark.parametrize('choice', ['REQUEST_CHANGES', 'REJECT'])
@pytest.mark.parametrize('comment', ['', '     ', '短'])
def test_revision_or_rejection_still_requires_reason(canvas, choice, comment):
    client, store, identifier, _, _ = canvas
    complete(store, identifier, 'intake')
    complete(store, identifier, 'context')
    assert decision(client, identifier, 'context', choice=choice, rationale=comment).status_code == 422
    assert node(client.get(url(identifier)).json(), 'adequacy')['locked_by'] == ['context']


def test_mutated_approved_artifact_revokes_descendant_approvals(canvas):
    client, store, identifier, _, _ = canvas
    p = complete(store, identifier, 'intake')
    assert decision(client, identifier, 'intake').status_code == 409
    complete(store, identifier, 'context')
    assert decision(client, identifier, 'context').status_code == 200
    write_json(p, {'changed': True})
    current = client.get(url(identifier)).json()
    for name in ['intake', 'context']:
        assert node(current, name)['execution'] == 'STALE'
        assert node(current, name)['review'] is None
    assert not node(current, 'prepare')['can_run']
    assert client.get(url(identifier, '/nodes/intake/artifacts/intake.json')).status_code == 409


def test_parallel_branches_and_final_join_require_both_reviews(canvas):
    client, store, identifier, _, _ = canvas
    assert save_clinical(client, identifier).status_code == 200
    for name in ['intake', 'context', 'adequacy', 'prepare', 'eda', 'dispatch']:
        complete(store, identifier, name)
        assert decision(client, identifier, name).status_code == (409 if name in {'intake', 'results'} else 200)
    current = client.get(url(identifier)).json()
    for name in ['pk', 'index']:
        assert node(current, name)['locked_by'] == []
        assert not node(current, name)['can_run']  # No pretend modeling adapter.
        assert '适配器' in node(current, name)['reason']
    complete(store, identifier, 'pk')
    assert decision(client, identifier, 'pk').status_code == 200
    complete(store, identifier, 'index')
    current = client.get(url(identifier)).json()
    assert node(current, 'results')['locked_by'] == ['index']
    assert client.post(url(identifier, '/nodes/results/start'), json={}).status_code == 409
    assert decision(client, identifier, 'index').status_code == 200
    assert node(client.get(url(identifier)).json(), 'results')['locked_by'] == []


def test_registered_upload_intake_verifies_without_human_signature(canvas):
    client, store, identifier, calls, status = canvas
    uploaded = store_upload(store.state, io.BytesIO(b'synthetic proposal'), 'proposal.txt')
    assert client.post(url(identifier, '/files'), json={'upload_ids': [uploaded['upload_id']]}).status_code == 200
    response = client.post(url(identifier, '/nodes/intake/start'), json={})
    assert response.status_code == 202
    assert calls == [('launch', [uploaded['upload_id']], 'intake')]
    assert node(response.json(), 'intake')['execution'] == 'RUNNING'
    assert client.post(url(identifier, '/files'), json={'upload_ids': [uploaded['upload_id']]}).status_code == 409
    out = store.outputs / 'fixture_job'
    write_json(store.state / 'workbench_jobs/fixture_job/request.json', {'out': str(out)})
    write_json(out / 'context_work/intake/manifest.json', {'test_fixture': True})
    status.update(status='WAITING_FOR_HUMAN_REVIEW', target='intake', control={'controller':'LangGraph'})
    response = client.get(url(identifier)).json()
    assert node(response, 'intake')['execution'] == 'COMPLETED'
    assert node(response, 'context')['can_run']
    assert decision(client, identifier, 'intake').status_code == 409
    assert client.post(url(identifier, '/nodes/context/start'), json={}).status_code == 202
    assert calls[-1] == ('resume', 'fixture_job', 'context')


def test_legacy_resume_cannot_bypass_canvas_gate(canvas):
    client, store, identifier, _, _ = canvas
    s = store.load(identifier); s['job_id'] = 'owned_job'; write_json(store.path(identifier), s)
    response = client.post('/ui-api/jobs/owned_job/resume', json={'target': 'data_preparation'})
    assert response.status_code == 409
    assert '流程画布' in response.json()['detail']


def test_incomplete_cleaning_is_visible_but_cannot_be_approved(canvas):
    client, store, identifier, _, status = canvas
    for name in ['intake', 'context', 'adequacy']:
        complete(store, identifier, name); decision(client, identifier, name)
    s = store.load(identifier); s['job_id'] = 'fixture_job'; s['nodes']['prepare']['execution'] = 'RUNNING'
    write_json(store.path(identifier), s)
    out = store.outputs / 'fixture_job'
    write_json(store.state / 'workbench_jobs/fixture_job/request.json', {'out': str(out)})
    write_json(out / 'source_preparation/output.json', {'test_fixture': True})
    write_json(out / 'data_preparation/main.json', {'cleaning_complete': False, 'released_datasets': []})
    status.update(status='WAITING_FOR_HUMAN_REVIEW', target='data_preparation')
    current = client.get(url(identifier)).json()
    assert node(current, 'prepare')['execution'] == 'NEEDS_ATTENTION'
    assert decision(client, identifier, 'prepare').status_code == 409
    assert not node(current, 'dispatch')['can_run']
    assert client.get(url(identifier, '/nodes/prepare/artifacts/data_report.json')).status_code == 200


@pytest.mark.parametrize('failure', ['worker_error', 'missing_output', 'wrong_target'])
def test_execution_failure_never_unlocks_next_step(canvas, failure):
    client, store, identifier, _, status = canvas
    s = store.load(identifier); s['job_id'] = 'fixture_job'; s['nodes']['intake']['execution'] = 'RUNNING'
    write_json(store.path(identifier), s)
    write_json(store.state / 'workbench_jobs/fixture_job/request.json', {'out': str(store.outputs / 'missing')})
    status.update(status='STOPPED_ON_ERROR' if failure == 'worker_error' else 'WAITING_FOR_HUMAN_REVIEW',
                  target='context' if failure == 'wrong_target' else 'intake', error='Test failure')
    current = client.get(url(identifier)).json()
    assert node(current, 'intake')['execution'] == 'FAILED'
    assert not node(current, 'context')['can_run']
    assert decision(client, identifier, 'intake').status_code == 409


def test_session_artifact_path_and_api_auth_boundaries(canvas, monkeypatch):
    client, store, identifier, _, _ = canvas
    complete(store, identifier, 'intake')
    response = client.get(url(identifier))
    assert 'path' not in node(response.json(), 'intake')['artifacts'][0]
    assert client.get(url(identifier, '/nodes/intake/artifacts/intake.json')).status_code == 200
    assert client.get(url(identifier, '/nodes/intake/artifacts/secret.json')).status_code == 404
    assert client.post('/ui-api/workflow/sessions', headers={'Origin': 'https://elsewhere.example'}).status_code == 403
    monkeypatch.setenv('RESEARCH_PIPELINE_API_TOKEN', 'test-secret')
    assert client.get('/ui-api/workflow/template').status_code == 401
    assert client.get('/ui-api/workflow/template', headers={'Authorization': 'Bearer test-secret'}).status_code == 200


def save_clinical(client, identifier, exposure='AVAILABLE_MATCHED_DATA'):
    return client.post(url(identifier, '/clinical-questions'), json={
        'values': {key: 'UNKNOWN: synthetic test evidence only' for key, _, _ in CLINICAL_FIELDS},
        'reviewer': 'Test reviewer', 'confirmed': True, 'index_exposure_source': exposure})


def test_pause_acknowledgment_and_resume_preserve_gates_and_time(canvas):
    client, store, identifier, calls, status = canvas
    s = store.load(identifier); s['job_id'] = 'fixture_job'
    s['nodes']['intake'].update(execution='RUNNING', segments=[{'started_at': '2026-09-20T00:00:00+00:00', 'stopped_at': None}])
    write_json(store.path(identifier), s)
    response = client.post(url(identifier, '/pause')).json()
    assert response['control_status'] == 'PAUSING'
    assert calls[-1] == ('pause', 'fixture_job')
    assert client.post(url(identifier, '/continue')).status_code == 409
    status.update(status='PAUSED', finished_at='2026-09-20T00:00:12+00:00')
    paused = client.get(url(identifier)).json()
    assert paused['control_status'] == 'PAUSED'
    assert paused['timing']['elapsed_seconds'] == 12
    assert not paused['timing']['running']
    assert client.post(url(identifier, '/nodes/context/start'), json={}).status_code == 409
    assert client.post(url(identifier, '/continue')).status_code == 202
    assert calls[-1] == ('resume', 'fixture_job', 'intake')
    s = read_json(store.path(identifier))
    assert len(s['nodes']['intake']['segments']) == 2
    assert s['nodes']['intake']['review'] is None


def test_pause_while_waiting_review_does_not_approve_or_reexecute(canvas):
    client, store, identifier, calls, _ = canvas
    complete(store, identifier, 'intake')
    assert decision(client, identifier, 'intake').status_code == 409
    assert client.post(url(identifier, '/pause')).json()['control_status'] == 'PAUSED'
    assert not node(client.get(url(identifier)).json(), 'context')['can_run']
    assert client.post(url(identifier, '/continue')).status_code == 202
    assert node(client.get(url(identifier)).json(), 'context')['can_run']
    assert calls == []


def test_clinical_confirmation_and_dynamic_pk_dependency(canvas):
    client, store, identifier, _, _ = canvas
    response = save_clinical(client, identifier, 'REQUIRES_PK_PREDICTIONS')
    assert response.status_code == 200
    for name in ['intake', 'context', 'adequacy', 'prepare', 'eda', 'dispatch']:
        complete(store, identifier, name); assert decision(client, identifier, name).status_code == (409 if name in {'intake', 'results'} else 200)
    current = client.get(url(identifier)).json()
    assert node(current, 'index')['locked_by'] == ['pk']
    assert save_clinical(client, identifier).status_code == 409
    complete(store, identifier, 'pk'); decision(client, identifier, 'pk')
    assert node(client.get(url(identifier)).json(), 'index')['locked_by'] == []
    spec = store.load(identifier)['nodes']['dispatch']['clinical_spec_ref']['path']
    write_json(spec, {'changed': True})
    current = client.get(url(identifier)).json()
    assert node(current, 'dispatch')['execution'] == 'STALE'
    assert node(current, 'pk')['execution'] == 'STALE'


def test_approved_insufficiency_does_not_allow_qc(canvas):
    client, store, identifier, _, _ = canvas
    for name in ['intake', 'context']:
        complete(store, identifier, name); decision(client, identifier, name)
    s = store.load(identifier)
    p = write_json(store.outputs / 'insufficient.json', {'assessment_status': 'NOT_CALCULABLE'})
    store.record_completion(s, 'adequacy', [{'name': 'adequacy.json', 'path': str(p), 'sha256': sha256(p)}])
    write_json(store.path(identifier), s)
    assert decision(client, identifier, 'adequacy').status_code == 200
    current = client.get(url(identifier)).json()
    assert not node(current, 'prepare')['can_run']
    assert '数据不足' in node(current, 'prepare')['reason']


def test_clinical_feedback_and_publication_require_actual_final_review(canvas):
    client, store, identifier, _, _ = canvas
    request = {'target': 'eda', 'reason': 'Synthetic feedback test', 'requested_changes': 'Review synthetic endpoint definition',
               'reviewer': 'Test reviewer', 'confirmed': True}
    assert client.post(url(identifier, '/cycles'), json=request).status_code == 409
    assert client.post(url(identifier, '/publish')).status_code == 409
    save_clinical(client, identifier)
    for name in ['intake', 'context', 'adequacy', 'prepare', 'eda', 'dispatch', 'pk', 'index', 'results', 'clinical']:
        complete(store, identifier, name); assert decision(client, identifier, name).status_code == (409 if name in {'intake', 'results'} else 200)
    before = sha256(store.outputs / 'synthetic_test/clinical.json')
    response = client.post(url(identifier, '/cycles'), json=request)
    assert response.status_code == 201
    child = response.json()['new_session']
    assert child['parent_cycle']['target'] == 'eda'
    assert child['stats']['approved'] == 0 and child['uploads'] == []
    assert sha256(store.outputs / 'synthetic_test/clinical.json') == before
    published = client.post(url(identifier, '/publish'))
    assert published.status_code == 200
    import zipfile
    with zipfile.ZipFile(io.BytesIO(published.content)) as archive:
        assert 'audit.json' in archive.namelist()
        assert any(x.startswith('clinical/') for x in archive.namelist())


def test_rules_draft_is_read_only_and_never_enabled(canvas):
    client, store, identifier, _, _ = canvas
    draft = client.get('/ui-api/workflow/rules-draft').json()
    assert len(draft['rules']) == 12
    assert not draft['enabled'] and all(not r['enabled'] for r in draft['rules'])
    assert all(r['numeric_threshold'] is None for r in draft['rules'])
    assert store.project_rules(store.load(identifier)) == []
    assert client.post('/ui-api/workflow/rules-draft').status_code == 405


@pytest.mark.parametrize('target,kind', [
    ('intake', 'REVISE_PROPOSAL'), ('intake', 'ADD_DATA'), ('context', 'RETRIEVE_EVIDENCE'),
    ('adequacy', 'REASSESS_ADEQUACY'), ('prepare', 'CORRECT_DATA'), ('eda', 'REVISE_EDA'),
    ('dispatch', 'REVISE_CLINICAL_QUESTION'), ('pk', 'REVISE_PK'), ('index', 'REVISE_INDEX'), ('results', 'REVIEW_RESULTS')])
def test_whole_study_revision_can_start_before_modeling_without_accepting_results(canvas, target, kind):
    client, store, identifier, calls, _ = canvas
    complete(store, identifier, 'intake')
    request = {'target': target, 'change_type': kind, 'source_node': 'intake',
        'reason': 'Synthetic proposal or evidence gap', 'requested_changes': 'Revise the defined study scope or add missing data',
        'reviewer': 'Synthetic test', 'confirmed': True}
    response = client.post(url(identifier, '/cycles'), json=request)
    assert response.status_code == 201
    child = response.json()['new_session']
    assert child['parent_cycle']['change_type'] == kind
    assert child['parent_cycle']['entry_stage'] == 'intake'
    assert child['parent_cycle']['target_is_revision_scope']
    assert not child['parent_cycle']['scientific_acceptance']
    assert child['parent_cycle']['evidence_refs'][0]['sha256']
    assert child['stats']['approved'] == 0 and child['uploads'] == []
    assert node(client.get(url(identifier)).json(), 'intake')['review'] is None
    assert client.post(url(identifier, '/publish')).status_code == 409
    assert calls == []


def test_qc_issue_can_request_missing_data_but_invalid_routes_and_stale_evidence_cannot(canvas):
    client, store, identifier, _, _ = canvas
    path = complete(store, identifier, 'prepare')
    s = store.load(identifier); s['nodes']['prepare']['execution'] = 'NEEDS_ATTENTION'
    write_json(store.path(identifier), s)
    payload = {'target': 'intake', 'change_type': 'ADD_DATA', 'source_node': 'prepare',
        'reason': 'Missing dose and sampling metadata', 'requested_changes': 'Collect the dosing records before modeling',
        'reviewer': 'Synthetic test', 'confirmed': True}
    assert client.post(url(identifier, '/cycles'), json={**payload, 'confirmed': False}).status_code == 422
    assert client.post(url(identifier, '/cycles'), json={**payload, 'target': 'pk'}).status_code == 422
    assert client.post(url(identifier, '/cycles'), json=payload).status_code == 201
    assert not node(client.get(url(identifier)).json(), 'prepare')['approved']
    write_json(path, {'changed': True})
    assert client.post(url(identifier, '/cycles'), json=payload).status_code == 409


def test_objective_fields_belong_only_to_context_review(canvas):
    client, store, identifier, _, _ = canvas
    complete(store, identifier, 'intake')
    complete(store, identifier, 'context')
    assert decision(client, identifier, 'context', choice='REQUEST_CHANGES', rationale='Objective is about another drug',
                    objective_decision='OFF_SCOPE').status_code == 200
    assert node(client.get(url(identifier)).json(), 'adequacy')['locked_by'] == ['context']
    complete(store, identifier, 'context')
    assert decision(client, identifier, 'context').status_code == 200
    complete(store, identifier, 'adequacy')
    s = store.load(identifier); s['nodes']['adequacy']['requires_human_review'] = True; write_json(store.path(identifier), s)
    assert decision(client, identifier, 'adequacy', objective_decision='CONFIRMED').status_code == 422


def test_in001_gaps_keep_context_locked_until_each_is_resolved(canvas, tmp_path):
    import zipfile
    from docx import Document
    from ctxcomp.engine import init_run
    client, store, identifier, calls, _ = canvas
    proposal = tmp_path / 'proposal.txt'; proposal.write_text('Objective: estimate rat clearance.', encoding='utf-8')
    study = tmp_path / 'study.docx'; Document().save(study)
    with zipfile.ZipFile(study) as source: parts = {n: source.read(n) for n in source.namelist()}
    parts['word/document.xml'] = parts['word/document.xml'].decode().replace('<w:sectPr',
        '<w:p><w:r><w:t>Clearance</w:t></w:r><m:oMath><m:r><m:t>CL=D/AUC</m:t></m:r></m:oMath></w:p><w:sectPr', 1).encode()
    with zipfile.ZipFile(study, 'w') as target:
        for n, content in parts.items(): target.writestr(n, content)
    run = store.outputs / 'coverage_fixture'
    init_run(run / 'context_work', attachments=[proposal, study], proposal_entry=proposal.name)
    write_json(store.state / 'workbench_jobs/coverage_fixture/request.json', {'out': str(run)})
    s = store.load(identifier); s['job_id'] = 'coverage_fixture'
    store.collect_outputs(s, 'intake'); write_json(store.path(identifier), s)
    intake = node(client.get(url(identifier)).json(), 'intake')
    assert intake['execution'] == 'NEEDS_ATTENTION' and 'IN001' in intake['error'] and not intake['approved']
    gap = intake['coverage']['gaps'][0]
    assert intake['coverage']['unresolved_gap_ids'] == [gap['id']] and gap['code'] == 'DOCX_EQUATIONS'
    assert gap['locations'] == ['paragraph 1 near "Clearance"'] and gap['required_action']
    assert {a['name'] for a in intake['artifacts']} >= {'manifest.json', 'coverage_report.json', 'readability_report.json'}
    assert 'intake' in node(client.get(url(identifier)).json(), 'context')['locked_by']
    endpoint = url(identifier, '/nodes/intake/coverage-resolutions')
    body = {'gap_ids': [gap['id']], 'decision': 'IRRELEVANT_TO_TASK', 'reviewer': 'Synthetic reviewer',
            'reason': 'The equation restates the text definition.', 'confirmed': True}
    assert client.post(endpoint, json={**body, 'reason': 'no'}).status_code == 422
    assert client.post(endpoint, json={**body, 'confirmed': False}).status_code == 422
    assert client.post(endpoint, json={**body, 'gap_ids': ['F0002-DOCX_CHARTS']}).status_code == 422
    response = client.post(endpoint, json=body)
    assert response.status_code == 200
    intake = node(response.json(), 'intake')
    assert intake['execution'] == 'COMPLETED' and intake['approved']
    assert intake['coverage']['status'] == 'GAPS_RESOLVED_BY_HUMAN' and intake['coverage']['resolutions'][0]['reviewer'] == 'Synthetic reviewer'
    assert 'coverage_resolutions.json' in {a['name'] for a in intake['artifacts']}
    assert 'intake' not in node(response.json(), 'context')['locked_by']
    assert client.post(endpoint, json=body).status_code == 409
    assert calls == []
