"""Read-only inspection of model handoffs belonging to one workflow session."""
import hashlib
import json
from pathlib import Path
from urllib.parse import quote

from fastapi import HTTPException

FILES = ('request.json', 'response.json', 'call.json', 'replay.json', 'model_input.json',
         'model_prompt.txt', 'context_manifest.json', 'projection_manifest.json',
         'budget.json', 'transport_schema.json', 'status.json')
PURPOSES = {
    'DR': ('Reviewed Context + Rules', 'Data requirement agent', 'Define task-specific input requirements.'),
    'DR-access': ('Requirements + inventory', 'Source access agent', 'Assign permitted, deferred and reference-only sources.'),
    'DC-label': ('Permitted source + requirements', 'Data label agent', 'Extract source-backed labels and unresolved definitions.'),
    'DC-review': ('Requirements + labels + evidence', 'Coverage reviewer', 'Check input coverage and retain gaps by downstream task.'),
    'DP': ('Approved Data scope + source table', 'Preparation agent', 'Propose permitted, source-preserving preparation.'),
    'DH-handoff': ('Prepared data + program QC', 'Handoff reviewer', 'Review the declared downstream handoff and remaining issues.'),
}


def read_json(path):
    try:
        return json.loads(path.read_text(encoding='utf-8-sig'))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def handoff_index(state, session):
    """Index allowlisted artifacts only in this session's registered job outputs."""
    state = Path(state).resolve()
    outputs = (state / 'workbench_outputs').resolve()
    jobs = list(dict.fromkeys([*session.get('job_history', []), session.get('job_id')]))
    entries = []
    for job in reversed([j for j in jobs if j]):
        if Path(job).name != job or '/' in job or '\\' in job:
            raise HTTPException(409, 'Invalid workflow job binding.')
        spec = read_json(state / 'workbench_state/workbench_jobs' / job / 'request.json')
        if not spec.get('out'):
            continue
        run = Path(spec['out']).resolve()
        if not run.is_relative_to(outputs) or run == outputs:
            raise HTTPException(409, 'Workflow output is outside this demo.')
        requests = [*run.glob('data_agents/audit/*/*/request.json'),
                    *run.glob('context_work/contextbuilder_linear/*/request.json'),
                    *run.glob('project_rules/extraction/request.json')]
        for request_path in sorted(requests):
            if not request_path.resolve().is_relative_to(run):
                raise HTTPException(409, 'Handoff request escaped its registered output folder.')
            request = read_json(request_path)
            payload = request.get('payload', request)
            stage = payload.get('stage') or request_path.parent.name
            if 'project_rules/extraction' in request_path.as_posix():
                stage = 'Project Rules'
            sender, receiver, purpose = PURPOSES.get(stage, ('Registered upstream inputs', stage, 'Inspect the exact retained request and response.'))
            identity = hashlib.sha256((job + '/' + request_path.relative_to(run).as_posix()).encode()).hexdigest()[:24]
            base = f'/workspace-api/workflow/{quote(session.get("session_id") or session["id"], safe="")}/handoffs/{identity}/files/'
            files = []

            def collect(directory, prefix=''):
                for name in FILES:
                    path = (directory / name).resolve()
                    if path.is_file() and path.is_relative_to(run):
                        key = prefix + name
                        files.append({'name': key, 'bytes': path.stat().st_size,
                                      'url': base + quote(key, safe=''), '_path': str(path)})

            collect(request_path.parent)
            digest = request.get('request_sha256', '')
            if len(digest) == 64 and all(c in '0123456789abcdef' for c in digest):
                for folder in (run / 'calls' / digest[:20] / 'contextbuilder').glob('*'):
                    collect(folder, 'assembled-')
                    collect(folder / 'provider', 'provider-')
            call = read_json(request_path.parent / 'call.json')
            replay = read_json(request_path.parent / 'replay.json')
            result = read_json(request_path.parent / 'status.json')
            status = ('REUSED_RESPONSE' if replay else call.get('status') or result.get('status')
                      or ('RESPONSE_RECORDED' if (request_path.parent / 'response.json').is_file() else 'REQUEST_RECORDED'))
            entries.append({'id': identity, 'job_id': job, 'current_job': job == session.get('job_id'),
                            'stage': stage, 'sender': sender, 'receiver': receiver, 'purpose': purpose,
                            'status': status, 'request_sha256': digest, 'elapsed_seconds': call.get('elapsed_seconds'),
                            'requested_model': call.get('requested_model'),
                            'reasoning_effort': call.get('requested_reasoning_effort'),
                            'timeout_seconds': call.get('timeout_seconds'), 'files': files})
    return entries


def connect_handoffs(app, state):
    def entries(identifier):
        with app.state.canvas.lock:
            session = app.state.canvas.load(identifier)
            return handoff_index(state, session)

    @app.get('/workspace-api/workflow/{identifier}/handoffs')
    def index(identifier: str):
        values = entries(identifier)
        return {'session_id': identifier, 'read_only': True, 'scientific_release': False,
                'calls': [{**v, 'files': [{k: x for k, x in f.items() if k != '_path'} for f in v['files']]} for v in values]}

    @app.get('/workspace-api/workflow/{identifier}/handoffs/{call_id}/files/{name}')
    def artifact(identifier: str, call_id: str, name: str):
        from fastapi.responses import FileResponse
        item = next((c for c in entries(identifier) if c['id'] == call_id), None)
        file = next((f for f in item['files'] if f['name'] == name), None) if item else None
        if not file:
            raise HTTPException(404, 'Handoff artifact not found in this workflow.')
        path = Path(file['_path'])
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        return FileResponse(path, media_type='application/json' if name.endswith('.json') else 'text/plain',
                            headers={'X-Artifact-SHA256': digest})
