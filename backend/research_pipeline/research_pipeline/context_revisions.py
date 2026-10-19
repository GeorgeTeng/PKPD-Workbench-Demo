"""Explicit source-preserving retries. A retry or extraction repair continues the same run when its code,
rules and inputs are unchanged; otherwise, and for a replaced proposal, it starts a new run. Accepted
artifacts stay immutable either way."""
from pathlib import Path
from uuid import uuid4
from typing import Literal
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from .attachments import store_upload, uploaded_path
from .common import read_json, write_json, sha256, utcnow
from .context_feedback import context_feedback
from .workflow_canvas import blank_session


class ContextRevision(BaseModel):
    feedback_signature: str
    mode: Literal['REPAIR_EXTRACTION', 'REPLACE_PROPOSAL', 'RETRY_EXECUTION']
    proposal_upload_id: str | None = None
    guidance: str = Field(default='', max_length=20000)
    submitted_by: str = Field(min_length=1, max_length=100)
    confirmed: Literal[True]


class ContextRetry(BaseModel):
    failure_signature: str
    confirmed: Literal[True]


CONTEXT_STAGES = ('attachment_plan', 'attachment_evidence', 'requirements', 'requirements_review', 'context', 'context_review')


class StageRerun(BaseModel):
    submitted_by: str = Field(default='Workbench user', max_length=100)
    confirmed: Literal[True]


class SameRunUnavailable(Exception):
    """The stopped run cannot be reopened; the submission starts a new run instead."""


class ContextRevisions:
    def __init__(self, canvas, launch):
        self.canvas, self.launch = canvas, launch

    def feedback(self, sid, execution=False):
        s = self.canvas.load(sid)
        if not s.get('job_id'): raise HTTPException(409, 'No context attempt is available')
        folder = self.canvas.state / 'workbench_jobs' / s['job_id']
        spec, status = read_json(folder / 'request.json'), self.canvas.job_status(s['job_id'])
        if status['status'] not in {'STOPPED_ON_ERROR', 'REVISION_REQUIRED'}:
            raise HTTPException(409, 'Context is not stopped for revision')
        if execution:
            from .execution_feedback import execution_feedback
            if status['status'] != 'STOPPED_ON_ERROR': raise HTTPException(409, 'This attempt is not stopped for an execution error')
            failure = status.get('failure') or execution_feedback(spec['out'], status.get('technical_error') or status.get('error',''), status.get('started_at'))
            if not failure['retry_supported']: raise HTTPException(409, 'Inspect and correct this failure before starting a new run')
            return s, spec, {**failure, 'raw_review':{}, 'source_units':[]}
        feedback = context_feedback(spec['out'], status.get('started_at'))
        if not feedback: raise HTTPException(409, 'This is an execution error; no semantic revision report is available')
        return s, spec, feedback

    def submit(self, sid, request):
        with self.canvas.lock:
            s, spec, feedback = self.feedback(sid, execution=request.mode == 'RETRY_EXECUTION')
            if s.get('context_revision_child'):
                raise HTTPException(409, 'A revision already exists. Open that revision to continue.')
            if s.get('control_status') != 'READY': raise HTTPException(409, 'Continue the paused workflow before submitting a revision')
            if feedback['signature'] != request.feedback_signature:
                raise HTTPException(409, 'Review evidence changed. Refresh and inspect the current findings.')
            if not request.submitted_by.strip(): raise HTTPException(422, 'Submitter is required')
            if (request.mode == 'REPLACE_PROPOSAL') != bool(request.proposal_upload_id):
                raise HTTPException(422, 'Replacement mode requires one revised proposal; extraction repair keeps the original proposal')
            blocker = 'A revised proposal needs a new run' if request.mode == 'REPLACE_PROPOSAL' else self.same_run_blocker(spec)
            if not blocker:
                try:
                    return self.continue_same_run(sid, s, spec, request)
                except SameRunUnavailable as exc:
                    blocker = str(exc)
            from ctxcomp.engine import load_run
            work = Path(spec['out']) / 'context_work'
            bundle, _ = load_run(work)  # Includes all attachment and input fingerprints.
            proposal_id = bundle['compression_scope']['proposal_file_id']
            manifest = read_json(work / 'intake/manifest.json')
            replacement = uploaded_path(self.canvas.state, request.proposal_upload_id) if request.proposal_upload_id else None
            if replacement and replacement.suffix.lower() not in {'.md', '.txt', '.docx', '.pdf'}:
                raise HTTPException(422, 'Revised proposal must be a DOCX, PDF, Markdown or text document')
            uploads, reference_only, proposal_entry = [], [], None
            for item in manifest['files']:
                source = (work / 'intake' / item['raw_path']).resolve()
                if not source.is_relative_to(work.resolve()) or sha256(source) != item['sha256']:
                    raise HTTPException(409, 'Original attachment changed; it cannot be reused')
                name = Path(item['original_name']).name
                if item['id'] == proposal_id:
                    if replacement: source, name = replacement, Path(name).stem + replacement.suffix.lower()
                    proposal_entry = name
                with source.open('rb') as f: saved = store_upload(self.canvas.state, f, name)
                uploads.append({'upload_id': saved['upload_id'], 'name': name, 'sha256': saved['sha256']})
                if item.get('role') == 'REFERENCE_ONLY': reference_only.append(name)
            if not proposal_entry: raise HTTPException(409, 'Original proposal is not identified in the intake manifest')
            child = blank_session('flow_' + uuid4().hex)
            revision = {'id': uuid4().hex, 'at': utcnow(), 'parent_session': sid, 'parent_job': s['job_id'],
                **request.model_dump(), 'prior_review': feedback['raw_review'], 'evidence_refs': feedback['evidence_refs'],
                'guidance_is_scientific_evidence': False, 'scientific_approval': False,
                'source_policy': 'CURRENT_PROPOSAL_ONLY', 'prior_source_units': feedback['source_units'],
                'same_run_unavailable': blocker}
            if request.mode == 'REPAIR_EXTRACTION' and feedback.get('prior_candidate') is not None:
                revision['prior_candidate'] = feedback['prior_candidate']
            child.update(uploads=uploads, context_revision=revision)
            child['parent_cycle'] = {'session_id': sid, 'source_node': 'context', 'target': 'context',
                'reason': feedback['summary'], 'requested_changes': request.guidance or request.mode}
            revision_path = self.canvas.root / child['id'] / 'context_revision.json'
            write_json(revision_path, revision)
            # Launch uses registered copies, a new plan, current code hashes and no inherited approvals.
            job = self.launch(uploads, proposal_entry, reference_only, spec.get('model'), revision)
            child['job_id'] = job['id']
            child['nodes']['context'].update(execution='RUNNING', segments=[{'started_at': utcnow(), 'stopped_at': None}])
            child['events'].append({'at': utcnow(), 'node': 'context', 'action': 'REVISION_SUBMITTED', 'revision_id': revision['id']})
            write_json(self.canvas.root / child['id'] / 'session.json', child)
            s['context_revision_child'] = child['id']
            s['events'].append({'at': utcnow(), 'node': 'context', 'action': 'REVISION_LINKED', 'child_session': child['id']})
            write_json(self.canvas.path(sid), s)
            return self.canvas.view(child)

    def same_run_blocker(self, spec):
        """Why this attempt cannot continue in its own run, or None. make_plan rejects changed inputs, code or rules."""
        from .workflow_runtime import make_plan
        if not (Path(spec['job_dir']) / 'plan.json').is_file(): return 'This attempt has no saved execution plan'
        try:
            if 'context' not in make_plan(spec)['targets']: return 'This attempt has no context target'
            from ctxcomp.engine import load_run
            load_run(Path(spec['out']) / 'context_work')
        except (OSError, ValueError, KeyError) as exc:
            return str(exc)
        return None

    def continue_same_run(self, sid, s, spec, request):
        """Rerun context in the same run. Accepted stages and validated review calls are reused; an extraction
        repair first returns the reviewed stage to the model with the review and the submitter's guidance."""
        attempt = {'id': uuid4().hex, 'at': utcnow(), 'mode': request.mode, 'job_id': s['job_id'],
            'feedback_signature': request.feedback_signature, 'submitted_by': request.submitted_by,
            'scientific_approval': False, 'reuse': 'ACCEPTED_STAGES_AND_VALIDATED_CALLS_OF_THIS_RUN'}
        if request.mode == 'REPAIR_EXTRACTION':
            from ctxcomp.engine import reopen_for_revision
            try:
                reopened = reopen_for_revision(Path(spec['out']) / 'context_work', guidance=request.guidance,
                                               submitted_by=request.submitted_by)
            except ValueError as exc:  # Checked before anything is written, so a new run can still start.
                raise SameRunUnavailable(str(exc)) from exc
            attempt.update(stage=reopened['stage'], guidance=request.guidance)
        return self.resume_context(sid, s, attempt)

    def resume_context(self, sid, s, attempt):
        n = s['nodes']['context']
        attempt['previous'] = {k: n[k] for k in ('error', 'technical_error', 'failure', 'context_feedback') if n.get(k)}
        write_json(self.canvas.state / 'workbench_jobs' / s['job_id'] / 'context_attempts' / (attempt['id'] + '.json'), attempt)
        self.canvas.resume(s['job_id'], 'context')
        for key in ('failure', 'context_feedback', 'technical_error', 'model_progress'): n.pop(key, None)
        n.update(execution='RUNNING', error=None, requires_control_trace=True)
        n.setdefault('segments', []).append({'started_at': utcnow(), 'stopped_at': None})
        s['events'].append({'at': utcnow(), 'node': 'context', 'action': 'CONTINUED_IN_SAME_RUN',
                            'mode': attempt['mode'], 'attempt_id': attempt['id']})
        write_json(self.canvas.path(sid), s)
        return self.canvas.view(s)

    def stages(self, sid):
        """The compression stages of this session's run, and whether one can be run again now."""
        from ctxcomp.engine import stage_status
        s = self.canvas.load(sid)
        if not s.get('job_id'): raise HTTPException(409, 'No context attempt is available')
        spec = read_json(self.canvas.state / 'workbench_jobs' / s['job_id'] / 'request.json')
        work = Path(spec['out']) / 'context_work'
        if not (work / 'state.json').is_file(): raise HTTPException(409, 'Context has not started yet')
        blocker = self.rerun_blocker(s, spec)
        # The context step ends at context_review; the pipeline stages belong to a later step.
        rows = [r for r in stage_status(work) if r['stage'] in CONTEXT_STAGES]
        return {'job_id': s['job_id'], 'stages': rows, 'can_rerun': not blocker, 'rerun_blocker': blocker}

    def rerun_blocker(self, s, spec):
        status = self.canvas.job_status(s['job_id'])['status']
        if status not in {'STOPPED_ON_ERROR', 'REVISION_REQUIRED'}:
            return 'A step can be run again only while context is stopped' if status != 'RUNNING' else 'Context is running'
        if s.get('context_revision_child'): return 'A revision already exists. Open that revision to continue.'
        if s.get('control_status') != 'READY': return 'Continue the paused workflow first'
        from ctxcomp.engine import load_run
        from ctxcomp.lean_compression import enabled
        work = Path(spec['out']) / 'context_work'
        if (work / 'inputs.json').is_file() and enabled(load_run(work)[0]):
            return 'Lean compression uses a targeted correction; submit an extraction repair with the findings instead of resampling a stage.'
        return self.same_run_blocker(spec)

    def rerun_stage(self, sid, stage, submitted_by):
        """Run one stage again with a fresh model call, then continue; earlier accepted stages are kept."""
        from ctxcomp.engine import rerun_from, load_run, active_stages
        if stage not in CONTEXT_STAGES: raise HTTPException(404, 'Unknown stage')
        with self.canvas.lock:
            s = self.canvas.load(sid)
            if not s.get('job_id'): raise HTTPException(409, 'No context attempt is available')
            spec = read_json(self.canvas.state / 'workbench_jobs' / s['job_id'] / 'request.json')
            blocker = self.rerun_blocker(s, spec)
            if blocker: raise HTTPException(409, blocker)
            work = Path(spec['out']) / 'context_work'
            bundle, _ = load_run(work)
            if stage not in active_stages(bundle): raise HTTPException(404, 'Stage is not active in this compression profile')
            record = rerun_from(work, stage, requested_by=submitted_by)
            write_json(work / 'stage_control.json', {'fresh': [stage], 'at': record['at'], 'requested_by': submitted_by})
            attempt = {'id': uuid4().hex, 'at': utcnow(), 'mode': 'RERUN_STAGE', 'stage': stage, 'job_id': s['job_id'],
                'submitted_by': submitted_by, 'removed_acceptances': record['removed_acceptances'],
                'scientific_approval': False, 'reuse': 'EARLIER_ACCEPTED_STAGES_OF_THIS_RUN'}
            return self.resume_context(sid, s, attempt)


def context_revision_router(store):
    api = APIRouter(prefix='/workflow/sessions')

    @api.get('/{sid}/context-feedback')
    def feedback(sid: str):
        return store.feedback(sid)[2]

    @api.post('/{sid}/context-revisions', status_code=202)
    def revise(sid: str, request: ContextRevision):
        return store.submit(sid, request)

    @api.get('/{sid}/context-stages')
    def stages(sid: str):
        return store.stages(sid)

    @api.post('/{sid}/context-stages/{stage}/rerun', status_code=202)
    def rerun(sid: str, stage: str, request: StageRerun):
        return store.rerun_stage(sid, stage, request.submitted_by.strip() or 'Workbench user')

    @api.post('/{sid}/context-retries', status_code=202)
    def retry(sid: str, request: ContextRetry):
        return store.submit(sid, ContextRevision(feedback_signature=request.failure_signature,
            mode='RETRY_EXECUTION', submitted_by='Workbench user', confirmed=request.confirmed))

    return api
