"""Supplemental input branches with artifact-bound human release."""
import copy
from pathlib import Path
from typing import Literal
from uuid import uuid4
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, JsonValue
from .attachments import uploaded_path
from .common import read_json, write_json, sha256, require_id, utcnow
from .dataset_metadata import reference
from .tributary_processing import ROLE_TARGETS
from .workflow_canvas import Decision, fingerprint, run_timing, stop_clock


class DatasetInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str = Field(pattern=r'^[A-Za-z][A-Za-z0-9_-]{0,39}$')
    upload_id: str
    metadata: dict[str, JsonValue]
    table: dict[str, JsonValue] = Field(default_factory=dict)
    analysis_options: dict[str, JsonValue] = Field(default_factory=dict)
    evidence_locators: list[dict[str, JsonValue]] = Field(default_factory=list)


class TributaryInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    label: str = Field(min_length=1, max_length=160)
    targets: list[Literal['pk', 'index', 'clinical']] = Field(min_length=1)
    datasets: list[DatasetInput] = Field(min_length=1)
    supersedes: str | None = None


class TributaryStore:
    def __init__(self, canvas, launch, resume):
        self.canvas, self.launch, self.resume = canvas, launch, resume
        self.root = canvas.state / 'tributaries'

    def path(self, sid, bid):
        require_id(sid); require_id(bid)
        path = self.root / sid / bid / 'branch.json'
        if not path.is_file(): raise HTTPException(404, 'Supplemental branch not found')
        return path

    def save(self, branch):
        write_json(self.root / branch['session_id'] / branch['id'] / 'branch.json', branch)

    def summaries(self, sid):
        if not sid: return []
        return [self.load(sid, p.parent.name) for p in sorted((self.root / sid).glob('*/branch.json'))]

    def owns_job(self, jid):
        return any(read_json(p).get('job_id') == jid for p in self.root.glob('*/*/branch.json'))

    def load(self, sid, bid):
        with self.canvas.lock:
            return self._load(sid, bid)

    def _load(self, sid, bid):
        branch = read_json(self.path(sid, bid)); changed = False
        if branch['status'] in {'RUNNING', 'PAUSING'}:
            job = self.canvas.job_status(branch['job_id']); branch['runtime'] = {
                k: job[k] for k in ['status', 'blocks', 'started_at', 'finished_at', 'control'] if k in job}
            if job['status'] == 'PAUSED': branch['status'] = 'PAUSED'; changed = True
            elif job['status'] == 'STOPPED_ON_ERROR':
                branch.update(status='FAILED', error=job.get('error', 'Execution failed'))
                branch['feedback'] = {'why_cannot_pass': [{'reason': branch['error'], 'category': 'ENGINEERING_FAILURE'}],
                    'missing_materials': [{'required': 'Inspect the worker log and correct the failed input or implementation.'}]}; changed = True
            elif job['status'] == 'WAITING_FOR_HUMAN_REVIEW':
                # Prefect writes its completion before LangGraph finishes inspecting
                # diagnostics. Do not expose a reviewable package in that window.
                if not job.get('control'): return branch
                if job['control'].get('disposition') != 'HUMAN_SCIENTIFIC_REVIEW':
                    branch.update(status='FAILED', error='LangGraph did not release the diagnostic report for review')
                    self.save(branch); return branch
                if job.get('target') != 'supplemental': raise HTTPException(409, 'Unexpected branch execution target')
                spec = read_json(self.canvas.state / 'workbench_jobs' / branch['job_id'] / 'request.json')
                run = Path(spec['out']).resolve()
                if not run.is_relative_to(self.canvas.outputs): raise HTTPException(409, 'Invalid branch output directory')
                try:
                    package = read_json(run / 'eda/package.json')
                    artifacts = [{'name': p.relative_to(run).as_posix(), 'path': str(p), 'sha256': sha256(p),
                                  'kind': 'figure' if p.suffix == '.png' else 'data' if p.suffix == '.csv' else 'context'}
                                 for p in sorted(run.rglob('*')) if p.is_file()]
                    if not self.canvas.artifacts_valid(artifacts): raise ValueError('Invalid branch artifacts')
                    branch.update(artifacts=artifacts, datasets=package['datasets'],
                        feedback=read_json(package['feedback']['path']), output_signature=fingerprint(artifacts),
                        status='BLOCKED' if package['status'] == 'BLOCKED' else 'WAITING_FOR_REVIEW')
                    branch['langgraph_review'] = self.canvas.graph_reviews.begin(sid, bid, branch['output_signature'],
                        [{k: a[k] for k in ['name', 'sha256', 'kind']} for a in artifacts], branch['rules'])
                except (ValueError, OSError, KeyError) as exc:
                    branch.update(status='FAILED', error='Incomplete supplemental output: ' + str(exc))
                changed = True
        if branch['status'] not in {'RUNNING', 'PAUSING'}: stop_clock(branch)
        if branch.get('artifacts') and branch['status'] not in {'STALE', 'FAILED', 'SUPERSEDED', 'REJECTED'}:
            refs = branch['artifacts'] + branch.get('handoffs', []) + branch.get('source_refs', [])
            # All references live in this application's output tree except registered uploads.
            if any(not Path(a['path']).is_file() or sha256(a['path']) != a['sha256'] for a in refs):
                branch.update(status='STALE', error='An input or output changed. Submit a new supplemental branch.', review=None)
                changed = True
        if changed: self.save(branch)
        return branch

    def public(self, branch):
        result = copy.deepcopy(branch)
        result.update(can_start=False, can_continue=False,
            unavailable_reason='Supplemental processing is disabled because it requires EDA.')
        result.pop('source_refs', None); result.pop('request_path', None); result.pop('rules', None)
        for a in result.get('artifacts', []): a.pop('path', None)
        for a in result.get('handoffs', []): a.pop('path', None)
        result['datasets'] = [{k: e[k] for k in ['id', 'role', 'summary', 'readiness']} for e in result.get('datasets', [])]
        result['timing'] = run_timing([branch], utcnow())
        return result

    def create(self, sid, request):
        with self.canvas.lock:
            session = self.canvas.load(sid)
            if session['control_status'] != 'READY': raise HTTPException(409, 'Resume the study before adding a branch')
            targets = sorted(set(request.targets))
            previous = None
            if request.supersedes:
                previous = self.load(sid, request.supersedes)
                if previous['status'] not in {'DRAFT', 'BLOCKED', 'REVISION_REQUIRED', 'STALE', 'FAILED'}:
                    raise HTTPException(409, 'Only an unaccepted branch may be replaced')
                if not set(previous['targets']).issubset(targets): raise HTTPException(422, 'The correction must retain all previous destinations')
            if any(session['nodes'][t]['execution'] != 'NOT_STARTED' for t in targets):
                raise HTTPException(409, 'A selected downstream step has already started. Add these data in a new study cycle; rerun planning is deferred.')
            if not request.label.strip(): raise HTTPException(422, 'Provide a branch label')
            ids = [d.id for d in request.datasets]
            if len(ids) != len(set(ids)): raise HTTPException(422, 'Dataset IDs must be unique within a branch')
            attachments = {}
            for dataset in request.datasets:
                role = dataset.metadata.get('role')
                if not isinstance(role, str) or role not in ROLE_TARGETS: raise HTTPException(422, 'Select a supported scientific dataset role')
                if set(dataset.table) - {'sheet', 'header_row', 'column_map'}: raise HTTPException(422, 'Unsupported table mapping option')
                mapping = dataset.table.get('column_map', {})
                if not isinstance(mapping, dict) or any(not isinstance(v, str) or not v.strip() for v in mapping.values()):
                    raise HTTPException(422, 'Column mapping must map source column names to nonempty canonical names')
                if 'header_row' in dataset.table and (type(dataset.table['header_row']) is not int or dataset.table['header_row'] < 1):
                    raise HTTPException(422, 'Header row must be a positive integer')
                if 'sheet' in dataset.table and not isinstance(dataset.table['sheet'], str): raise HTTPException(422, 'Worksheet name must be text')
                path = uploaded_path(self.canvas.state, dataset.upload_id)
                if path.suffix.lower() not in {'.csv', '.xlsx', '.json'}: raise HTTPException(422, 'The data branch accepts CSV, XLSX or JSON tables')
                info = read_json(path.parent / 'metadata.json')
                attachments[dataset.upload_id] = {'path': str(path), 'name': info['filename'], 'sha256': info['sha256']}
            bid = 'supp_' + uuid4().hex
            folder = self.canvas.outputs / 'supplemental_requests' / sid / bid
            rules = self.canvas.project_rules(session)
            payload = {**request.model_dump(), 'targets': targets, 'branch_id': bid, 'session_id': sid,
                       'attachments': attachments, 'rules': rules, 'scientific_acceptance': False}
            path = write_json(folder / 'request.json', payload)
            branch = {'id': bid, 'session_id': sid, 'label': request.label.strip(), 'targets': targets,
                'created_at': utcnow(), 'status': 'DRAFT', 'request_path': str(path), 'rules': rules,
                'source_refs': [reference(path), *attachments.values()], 'review': None, 'artifacts': [], 'handoffs': [],
                'datasets': [], 'events': [{'at': utcnow(), 'action': 'REGISTERED'}]}
            self.save(branch)
            if previous:
                previous.update(status='SUPERSEDED', superseded_by=bid); self.save(previous)
                branch['supersedes'] = previous['id']; self.save(branch)
            session['events'].append({'at': utcnow(), 'node': targets[0], 'action': 'SUPPLEMENTAL_REGISTERED', 'branch_id': bid})
            write_json(self.canvas.path(sid), session)
            return self.public(branch)

    def start(self, sid, bid):
        self.load(sid, bid)
        raise HTTPException(409, 'Supplemental processing is disabled because it requires EDA.')

    def control(self, sid, bid, action):
        with self.canvas.lock:
            branch = self.load(sid, bid)
            if action == 'pause' and branch['status'] == 'RUNNING':
                self.canvas.pause_job(branch['job_id']); branch['status'] = 'PAUSING'
            elif action == 'continue' and branch['status'] == 'PAUSED':
                raise HTTPException(409, 'Supplemental processing is disabled because it requires EDA.')
            else: raise HTTPException(409, 'Branch cannot perform this action in its current state')
            self.save(branch); return self.public(branch)

    def review(self, sid, bid, decision):
        with self.canvas.lock:
            branch = self.load(sid, bid)
            if branch['status'] not in {'WAITING_FOR_REVIEW', 'BLOCKED'}: raise HTTPException(409, 'The branch is not awaiting review')
            if decision.output_signature != branch['output_signature']: raise HTTPException(409, 'Stale review signature')
            if not decision.reviewer.strip(): raise HTTPException(422, 'A reviewer is required')
            if decision.decision != 'APPROVE' and len(decision.rationale.strip()) < 5: raise HTTPException(422, 'Explain the requested changes or rejection')
            if decision.decision == 'APPROVE' and branch['status'] == 'BLOCKED': raise HTTPException(409, 'Correct blocking findings before approval')
            session = self.canvas.load(sid)
            if any(session['nodes'][t]['execution'] != 'NOT_STARTED' for t in branch['targets']): raise HTTPException(409, 'A downstream step has started; use a new study cycle')
            value = {**decision.model_dump(), 'rationale': decision.rationale.strip(), 'at': utcnow(),
                     'scope': 'SUPPLEMENTAL_DATA_HANDOFF_ONLY', 'scientific_acceptance': False}
            branch['langgraph_review'] = self.canvas.graph_reviews.resume(branch['langgraph_review'], value)
            branch['review'] = value
            branch['status'] = {'APPROVE': 'APPROVED', 'REQUEST_CHANGES': 'REVISION_REQUIRED', 'REJECT': 'REJECTED'}[decision.decision]
            folder = Path(branch['request_path']).parent
            write_json(folder / 'review.json', value)
            branch['source_refs'].append(reference(folder / 'review.json'))
            if branch['status'] == 'APPROVED':
                for target in branch['targets']:
                    selected = [d for d in branch['datasets'] if target in ROLE_TARGETS[d['role']]]
                    path = write_json(folder / ('handoff_' + target + '.json'), {
                        'schema_version': '1.0', 'branch_id': bid, 'session_id': sid, 'target': target,
                        'datasets': selected, 'review': reference(folder / 'review.json'),
                        'reviewed_output_signature': branch['output_signature'],
                        'scope': 'SUPPLEMENTAL_INPUTS_ONLY', 'full_proposal_forwarded': False,
                        'scientific_acceptance': False, 'replaces_main_prerequisites': False})
                    branch['handoffs'].append({'name': path.name, 'target': target, **reference(path)})
            branch['events'].append({'at': utcnow(), 'action': decision.decision}); self.save(branch)
            return self.public(branch)

    def incoming(self, sid, target):
        return [{'branch_id': b['id'], 'label': b['label'], 'status': b['status'],
                 'handoffs': [h for h in b['handoffs'] if h['target'] == target] if b['status'] == 'APPROVED' else []}
                for b in self.summaries(sid) if target in b['targets'] and b['status'] not in {'REJECTED', 'SUPERSEDED'}]


def tributary_router(store):
    router = APIRouter(prefix='/workflow/sessions/{sid}')
    @router.post('/supplements', status_code=201)
    def create(sid: str, request: TributaryInput): return store.create(sid, request)
    @router.get('/supplements')
    def listing(sid: str):
        store.canvas.path(sid)
        return {'branches': [store.public(b) for b in store.summaries(sid)]}
    @router.get('/supplements/{bid}')
    def get(sid: str, bid: str): return store.public(store.load(sid, bid))
    @router.post('/supplements/{bid}/start', status_code=202)
    def start(sid: str, bid: str): return store.start(sid, bid)
    @router.post('/supplements/{bid}/pause', status_code=202)
    def pause(sid: str, bid: str): return store.control(sid, bid, 'pause')
    @router.post('/supplements/{bid}/continue', status_code=202)
    def resume(sid: str, bid: str): return store.control(sid, bid, 'continue')
    @router.post('/supplements/{bid}/review')
    def review(sid: str, bid: str, request: Decision): return store.review(sid, bid, request)
    @router.get('/supplements/{bid}/artifacts/{name:path}')
    def artifact(sid: str, bid: str, name: str):
        branch = store.load(sid, bid)
        item = next((a for a in branch['artifacts'] + branch['handoffs'] if a['name'] == name), None)
        if not item: raise HTTPException(404, 'Artifact not found')
        if not store.canvas.artifacts_valid([item]): raise HTTPException(409, 'Artifact changed')
        return FileResponse(item['path'], filename=Path(item['path']).name)
    @router.get('/nodes/{target}/supplements')
    def incoming(sid: str, target: str):
        store.canvas.path(sid)
        if target not in {'pk', 'index', 'clinical'}: raise HTTPException(404, 'Unsupported target')
        entries = store.incoming(sid, target)
        if any(b['status'] != 'APPROVED' for b in entries): raise HTTPException(409, 'Supplemental input review is pending or invalid')
        return {'target': target, 'inputs': entries, 'replaces_main_prerequisites': False}
    return router
