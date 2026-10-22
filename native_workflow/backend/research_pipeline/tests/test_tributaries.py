"""Synthetic supplemental branches exercise real QC/EDA and persistent review."""
import copy
import io
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from research_pipeline.attachments import store_upload
from research_pipeline.common import read_json, write_json, sha256, utcnow
from research_pipeline.workbench import create_workbench
from research_pipeline.workflow_runtime import make_plan, execute_contract


@pytest.fixture
def setup(tmp_path):
    app = create_workbench(tmp_path / 'outputs', tmp_path / 'state')
    client = TestClient(app); canvas = app.state.canvas
    sid = client.post('/ui-api/workflow/sessions').json()['session_id']
    jobs = {}
    def launch(path):
        jid = 'job_' + str(len(jobs)); folder = canvas.state / 'workbench_jobs' / jid
        spec = {'id': jid, 'created_at': utcnow(), 'mode': 'supplemental', 'stop_after': 'supplemental',
                'supplemental_request': str(path), 'job_dir': str(folder), 'out': str(canvas.outputs / jid)}
        write_json(folder / 'request.json', spec)
        plan = make_plan(spec)
        for stage in ['supplemental_prepare', 'supplemental_eda']: execute_contract(plan['steps'][stage]['contract'])
        jobs[jid] = {'id': jid, 'status': 'WAITING_FOR_HUMAN_REVIEW', 'target': 'supplemental',
                     'control': {'disposition': 'HUMAN_SCIENTIFIC_REVIEW'}}
        return jobs[jid]
    canvas.tributaries.launch = launch; canvas.job_status = lambda jid: jobs[jid]
    rows = 'subject_id,time_h,concentration_mg_L\n' + ''.join(f'R1,{t},{10/(1+t)}\n' for t in range(6))
    upload = store_upload(canvas.state, io.BytesIO(rows.encode()), 'arbitrary_name.csv')
    request = {'label': 'Synthetic extra PK', 'targets': ['pk'], 'datasets': [{
        'id': 'extra_pk', 'upload_id': upload['upload_id'],
        'metadata': {'role': 'pk_observations', 'drug': 'PMB', 'analyte': 'PMB', 'species': 'rat', 'route': 'IV',
            'matrix': 'plasma', 'concentration_basis': 'total', 'record_level': 'individual',
            'sampling_design': 'serial', 'time_unit': 'h', 'concentration_unit': 'mg/L', 'dose_unit': 'mg',
            'formulation': 'solution', 'parameter_definition': 'Observed plasma concentration'},
        'analysis_options': {'mode': 'individual', 'doses': [{'time_h': 0, 'duration_h': 0, 'dose_mg': 1}]}}]}
    return client, canvas, sid, request


def base(sid): return '/ui-api/workflow/sessions/' + sid


def process(setup, request=None):
    client, canvas, sid, default = setup
    created = client.post(base(sid) + '/supplements', json=request or default)
    assert created.status_code == 201, created.text
    bid = created.json()['id']
    started = client.post(base(sid) + '/supplements/' + bid + '/start')
    assert started.status_code == 202, started.text
    return client.get(base(sid) + '/supplements/' + bid).json()


def review(setup, branch, **extra):
    client, _, sid, _ = setup
    return client.post(base(sid) + '/supplements/' + branch['id'] + '/review', json={
        'decision': 'APPROVE', 'reviewer': 'Synthetic reviewer', 'confirmed': True,
        'output_signature': branch['output_signature'], **extra})


@pytest.mark.skip(reason='Requires retired EDA execution; EDA is explicitly disabled.')
def test_qc_eda_metadata_single_review_and_scoped_handoff(setup):
    client, canvas, sid, _ = setup; branch = process(setup)
    assert branch['status'] == 'WAITING_FOR_REVIEW'
    assert branch['langgraph_review']['status'] == 'INTERRUPTED'
    assert len([a for a in branch['artifacts'] if a['name'].endswith('.metadata.json')]) == 1
    assert len([a for a in branch['artifacts'] if a['kind'] == 'figure']) == 3
    assert client.get(base(sid) + '/nodes/pk/supplements').status_code == 409
    accepted = review(setup, branch); assert accepted.status_code == 200, accepted.text
    assert accepted.json()['review']['rationale'] == ''
    incoming = client.get(base(sid) + '/nodes/pk/supplements').json()
    assert len(incoming['inputs']) == 1 and incoming['replaces_main_prerequisites'] is False
    handoff = read_json(incoming['inputs'][0]['handoffs'][0]['path'])
    assert handoff['target'] == 'pk' and not handoff['scientific_acceptance']
    assert client.get(base(sid) + '/nodes/index/supplements').json()['inputs'] == []
    node = next(n for n in client.get(base(sid)).json()['nodes'] if n['id'] == 'pk')
    assert node['state']['can_run'] is False  # Main prerequisites remain in force.
    assert 'handoff_pk.json' in node['state']['supplemental_inputs'][0]['files']
    assert review(setup, branch).status_code == 409


@pytest.mark.parametrize('field', ['dose_unit', 'concentration_unit', 'species'])
@pytest.mark.skip(reason='Requires retired EDA execution; EDA is explicitly disabled.')
def test_missing_metadata_has_actionable_blocker_and_cannot_be_approved(setup, field):
    request = copy.deepcopy(setup[3]); del request['datasets'][0]['metadata'][field]
    branch = process(setup, request)
    assert branch['status'] == 'BLOCKED'
    assert branch['feedback']['why_cannot_pass'] and branch['feedback']['missing_materials']
    assert all(x['required'] for x in branch['feedback']['missing_materials'])
    if field == 'concentration_unit': assert not [a for a in branch['artifacts'] if a['kind'] == 'figure']
    if field == 'dose_unit': assert not [a for a in branch['artifacts'] if 'dose_normalized.png' in a['name']]
    assert review(setup, branch).status_code == 409
    assert review(setup, branch, decision='REQUEST_CHANGES', rationale='Provide missing source definitions').status_code == 200
    assert setup[0].get(base(setup[2]) + '/nodes/pk/supplements').status_code == 409


@pytest.mark.skip(reason='Requires retired EDA execution; EDA is explicitly disabled.')
def test_renaming_does_not_change_routing_and_incompatible_target_blocks(setup):
    client, canvas, sid, request = setup
    original = process(setup)
    path = canvas.state / 'uploads' / request['datasets'][0]['upload_id'] / 'file.csv'
    upload = store_upload(canvas.state, io.BytesIO(path.read_bytes()), 'index_clinical_mouse.csv')
    renamed = copy.deepcopy(request); renamed['datasets'][0]['upload_id'] = upload['upload_id']
    branch = process(setup, renamed)
    assert branch['status'] == original['status'] and branch['targets'] == ['pk']
    renamed['targets'] = ['index']
    mismatch = process(setup, renamed)
    assert mismatch['status'] == 'BLOCKED'
    assert any(f['code'] == 'ROUTE_INCOMPATIBLE' for f in mismatch['feedback']['why_cannot_pass'])


@pytest.mark.skip(reason='Requires retired EDA execution; EDA is explicitly disabled.')
def test_split_metadata_and_quarantine_preserve_source_rows(setup):
    _, canvas, _, request = setup
    text = 'subject_id,time_h,concentration_mg_L,matrix,status\n'
    for matrix in ['plasma', 'lung']:
        text += ''.join(f'R1,{i},{8/(i+1)},{matrix},QUANTIFIED\n' for i in range(6))
    text += 'R1,7,,plasma,BLQ\n'
    upload = store_upload(canvas.state, io.BytesIO(text.encode()), 'mixed.csv')
    request['datasets'][0]['upload_id'] = upload['upload_id']
    branch = process(setup, request)
    assert len(branch['datasets']) == 2
    full = canvas.tributaries.load(setup[2], branch['id'])
    metadata = [read_json(d['metadata_file']['path']) for d in full['datasets']]
    assert {m['metadata']['matrix'] for m in metadata} == {'lung', 'plasma'}
    assert sum(d['summary']['input_rows'] for d in full['datasets']) == 13
    assert sum(d['summary']['quarantined_rows'] for d in full['datasets']) == 1
    assert all(sha256(m['data_file']['path']) == m['data_file']['sha256'] for m in metadata)


@pytest.mark.skip(reason='Requires retired EDA execution; EDA is explicitly disabled.')
def test_modified_artifact_revokes_handoff_and_review_signature_is_checked(setup):
    branch = process(setup)
    assert review(setup, branch, output_signature='stale').status_code == 409
    assert review(setup, branch, confirmed=False).status_code == 422
    assert review(setup, branch).status_code == 200
    client, canvas, sid, _ = setup
    full = canvas.tributaries.load(sid, branch['id'])
    Path(full['datasets'][0]['metadata_file']['path']).write_text('{}', encoding='utf-8')
    assert client.get(base(sid) + '/supplements/' + branch['id']).json()['status'] == 'STALE'
    assert client.get(base(sid) + '/nodes/pk/supplements').status_code == 409


@pytest.mark.skip(reason='Requires retired EDA execution; EDA is explicitly disabled.')
def test_correction_replaces_only_unaccepted_branch(setup):
    client, _, sid, request = setup
    invalid = copy.deepcopy(request); invalid['datasets'][0]['analysis_options'] = {}
    blocked = process(setup, invalid); assert blocked['status'] == 'BLOCKED'
    correction = copy.deepcopy(request); correction['supersedes'] = blocked['id']
    branch = process(setup, correction)
    assert client.get(base(sid) + '/supplements/' + blocked['id']).json()['status'] == 'SUPERSEDED'
    assert review(setup, branch).status_code == 200
    assert client.get(base(sid) + '/nodes/pk/supplements').status_code == 200
    correction['supersedes'] = branch['id']
    assert client.post(base(sid) + '/supplements', json=correction).status_code == 409


@pytest.mark.skip(reason='Requires retired EDA execution; EDA is explicitly disabled.')
def test_bad_mapping_reports_failure_no_silent_omission(setup):
    request = copy.deepcopy(setup[3]); request['datasets'][0]['table'] = {'column_map': {'subject_id': 'time_h'}}
    branch = process(setup, request)
    assert branch['status'] == 'BLOCKED'
    assert any(f['code'] == 'DATASET_READ_FAILED' for f in branch['feedback']['why_cannot_pass'])


def test_scope_and_path_boundaries_and_existing_result_guard(setup):
    client, canvas, sid, request = setup
    bad = copy.deepcopy(request); bad['datasets'][0]['id'] = '../escape'
    assert client.post(base(sid) + '/supplements', json=bad).status_code == 422
    assert client.post(base(sid) + '/supplements', json=request, headers={'origin': 'http://other.example'}).status_code == 403
    invalid = copy.deepcopy(request); invalid['datasets'][0]['metadata']['role'] = ['pk_observations']
    assert client.post(base(sid) + '/supplements', json=invalid).status_code == 422
    invalid = copy.deepcopy(request); invalid['datasets'][0]['table'] = {'column_map': []}
    assert client.post(base(sid) + '/supplements', json=invalid).status_code == 422
    branch = client.post(base(sid) + '/supplements', json=request).json()
    other = client.post('/ui-api/workflow/sessions').json()['session_id']
    assert client.get(base(other) + '/supplements/' + branch['id']).status_code == 404
    s = canvas.load(sid); s['nodes']['pk']['execution'] = 'FAILED'; write_json(canvas.path(sid), s)
    assert client.post(base(sid) + '/supplements', json=request).status_code == 409


@pytest.mark.skip(reason='Requires retired EDA execution; EDA is explicitly disabled.')
def test_pause_and_legacy_resume_cannot_bypass_branch_review(setup):
    client, canvas, sid, request = setup
    branch = client.post(base(sid) + '/supplements', json=request).json()
    canvas.tributaries.launch = lambda _: {'id': 'owned_job'}
    state = {'status': 'RUNNING'}; canvas.job_status = lambda _: state
    pauses = []; canvas.pause_job = lambda jid: pauses.append(jid)
    client.post(base(sid) + '/supplements/' + branch['id'] + '/start')
    assert canvas.owns_job('owned_job')
    assert client.post('/ui-api/jobs/owned_job/resume', json={'target': 'supplemental'}).status_code == 409
    assert client.post(base(sid) + '/pause').json()['control_status'] == 'PAUSING'
    assert pauses == ['owned_job']
    state['status'] = 'PAUSED'
    assert client.get(base(sid)).json()['control_status'] == 'PAUSED'
    assert client.get(base(sid) + '/supplements/' + branch['id']).json()['status'] == 'PAUSED'
    assert client.get(base(sid) + '/nodes/pk/supplements').status_code == 409


@pytest.mark.skip(reason='Requires retired EDA execution; EDA is explicitly disabled.')
def test_wait_for_langgraph_diagnostics_after_prefect_finishes(setup):
    client, canvas, sid, request = setup
    branch = client.post(base(sid) + '/supplements', json=request).json()
    canvas.tributaries.launch = lambda _: {'id': 'diagnostic_race'}
    runtime = {'status': 'WAITING_FOR_HUMAN_REVIEW', 'target': 'supplemental'}
    canvas.job_status = lambda _: runtime
    client.post(base(sid) + '/supplements/' + branch['id'] + '/start')
    current = client.get(base(sid) + '/supplements/' + branch['id']).json()
    assert current['status'] == 'RUNNING' and not current.get('output_signature')
    runtime['control'] = {'disposition': 'ENGINEERING_FAILURE'}
    assert client.get(base(sid) + '/supplements/' + branch['id']).json()['status'] == 'FAILED'


def test_intake_is_technical_and_conditional_assessment_still_fails_closed(setup):
    client, canvas, sid, _ = setup; s = canvas.load(sid)
    p = write_json(canvas.outputs / 'intake.json', {'synthetic': True})
    canvas.record_completion(s, 'intake', [{'name': 'manifest.json', 'path': str(p), 'sha256': sha256(p)}])
    assert canvas.approved(s['nodes']['intake']) and s['nodes']['intake']['review'] is None
    assert 'langgraph_review' not in s['nodes']['intake']
    a = write_json(canvas.outputs / 'adequacy.json', {'assessment_status': 'SUFFICIENT_FOR_DEFINED_SCOPE', 'findings': [], 'requires_human_review': False})
    canvas.record_completion(s, 'adequacy', [{'name': 'adequacy.json', 'path': str(a), 'sha256': sha256(a)}])
    assert canvas.approved(s['nodes']['adequacy'])
    write_json(a, {'assessment_status': 'NOT_CALCULABLE', 'findings': [{'missing': 'precision'}]})
    canvas.record_completion(s, 'adequacy', [{'name': 'adequacy.json', 'path': str(a), 'sha256': sha256(a)}])
    assert not canvas.approved(s['nodes']['adequacy'])
    assert s['nodes']['adequacy']['requires_human_review']

