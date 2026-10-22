"""Local UI over immutable PMB run artifacts and the existing pipeline API."""
import argparse
import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
import threading
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse
from uuid import uuid4

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .api import create_app
from .attachments import uploaded_path
from .common import BACKEND, FRONTEND, PROJECT, PipelineError, read_json, require_id, sha256, utcnow, write_json
from .execution_feedback import WORKER_EXITED

STATIC = FRONTEND


def current_frontend_html():
    """Bind the entry page to the bytes of each current JS/CSS resource."""
    html = (STATIC / 'index.html').read_text(encoding='utf-8')
    def versioned(match):
        path = STATIC / match[2].removeprefix('/assets/')
        digest = sha256(path)[:16]
        return match[1] + match[2] + '?v=' + digest + match[3]
    html = re.sub(r'((?:src|href)=")(/assets/[^"?]+\.(?:js|css))(?:\?[^\"]*)?(\")', versioned, html)
    build = hashlib.sha256(html.encode('utf-8')).hexdigest()[:16]
    return html.replace('</head>', f'<meta name="workbench-build" content="{build}"></head>')


def pre_eda_artifact_paths(run, mode):
    """Resolve retained artifacts for both formal pre-EDA launch routes."""
    run = Path(run)
    base = run / 'data_chain' if mode == 'fresh_pre_eda_from_rules' else run
    cleaning = base / 'cleaning'
    return {'data_report': cleaning / 'data_preparation/data_report.json',
            'cleaning_status': cleaning / 'cleaning_status.json',
            'normalization_manifest': cleaning / 'data_preparation/normalization_manifest.json',
            'preparation_execution': cleaning / 'data_preparation/preparation_execution.json',
            'cleaning_log': cleaning / 'data_preparation/cleaning_log.json',
            'pre_eda_status': run / 'pre_eda_status.json'}


def worker_record(proc):
    """The worker's PID and start time; the start time stops a reused PID from passing for the worker.
    A launcher without a PID gives an empty record, which later reads as unknown, never as ended."""
    import psutil
    pid = getattr(proc, 'pid', None); created = None
    if pid:
        try: created = psutil.Process(pid).create_time()
        except psutil.Error: pass
    return {'pid': pid, 'create_time': created, 'recorded_at': utcnow()}


def worker_alive(record):
    """True or False when known; None for jobs started before workers were recorded, or when the OS refuses."""
    import psutil
    if not record or not record.get('pid'): return None
    try: created = psutil.Process(record['pid']).create_time()
    except psutil.NoSuchProcess: return False
    except psutil.Error: return None
    return record.get('create_time') is None or abs(created - record['create_time']) < 0.5


class Review(BaseModel):
    main_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    reviewer: str = Field(min_length=1, max_length=100)
    decision: Literal['ACKNOWLEDGE_EXPLORATORY', 'REQUEST_CHANGES', 'REJECT']
    rationale: str = Field(min_length=5, max_length=10000)
    confirmed_scope: Literal[True]


class Job(BaseModel):
    upload_ids: list[str] = Field(default_factory=list)
    proposal_entry: str | None = None
    reference_only: list[str] = Field(default_factory=list)
    project_materials: list[dict] = Field(default_factory=list)
    model: str | None = None
    stop_after: Literal['intake', 'context', 'data_preparation', 'exploratory_results'] = 'context'
    baseline_run: str | None = None
    package_upload_id: str | None = None


class ResumeJob(BaseModel):
    target: Literal['intake', 'context', 'adequacy', 'data_preparation', 'eda', 'clinical_dispatch', 'exploratory_results', 'supplemental']


class DirectPreparationRequest(BaseModel):
    confirmed_user_authorization: Literal[True]
    auto_approve_human_gates: Literal[True]
    model: str | None = None


class PreEdaRequest(BaseModel):
    main_id: str | None = Field(default=None, pattern=r'^main_[a-f0-9]{16}$')
    confirmed_user_authorization: Literal[True]
    auto_approve_human_gates: Literal[True]


def create_workbench(outputs=None, state=None):
    outputs = Path(outputs or PROJECT / 'outputs').resolve()
    state = Path(state or outputs / 'workbench_state').resolve()
    state.mkdir(parents=True, exist_ok=True)
    # Workers share accepted compression answers between runs here (ctxcomp.stage_cache); 'off' disables it.
    worker_env = {**os.environ, 'CTXCOMP_STAGE_CACHE': os.environ.get('CTXCOMP_STAGE_CACHE') or str(state / 'stage_cache')}
    app = FastAPI(title='PMB Research Workbench', version='0.1.0')
    children = {}; lock = threading.Lock()

    @app.middleware('http')
    async def same_origin(request: Request, call_next):
        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            origin = request.headers.get('origin')
            if origin and urlparse(origin).netloc != request.url.netloc:
                return JSONResponse({'detail': 'Cross-origin writes are not allowed'}, status_code=403)
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        if request.url.path == '/' or request.url.path.startswith('/assets/'):
            response.headers['Cache-Control'] = 'no-store'
        return response

    def authenticate(authorization: str | None = Header(default=None)):
        token = os.getenv('RESEARCH_PIPELINE_API_TOKEN')
        if token and not secrets.compare_digest(authorization or '', 'Bearer ' + token):
            raise HTTPException(401, 'API token required')

    api = APIRouter(prefix='/ui-api', dependencies=[Depends(authenticate)])

    @app.exception_handler(PipelineError)
    async def pipeline_error(request, exc):
        return JSONResponse({'detail': str(exc), 'code': exc.code}, status_code=422)

    @app.exception_handler(ValueError)
    async def invalid_operation(request, exc):
        return JSONResponse({'detail': str(exc)}, status_code=422)

    def run_dir(identifier):
        require_id(identifier)
        directory = (outputs / identifier).resolve()
        if not directory.is_relative_to(outputs) or not (directory / 'main.json').is_file():
            raise HTTPException(404, 'Run not found')
        return directory

    def optional(path, default=None):
        return read_json(path) if path.is_file() else default

    def linked(reference, default=None):
        if not reference: return default
        path = Path(reference['path']).resolve()
        if not path.is_relative_to(outputs): raise HTTPException(409, 'Artifact outside configured outputs')
        if sha256(path) != reference['sha256']: raise HTTPException(409, 'Artifact changed; reassessment required')
        return read_json(path)

    def review_list(identifier, main_hash):
        records = []
        for path in sorted((state / 'workbench_reviews' / identifier).glob('*.json'), reverse=True):
            r = read_json(path)
            r['current'] = r['main_sha256'] == main_hash
            records.append(r)
        return records

    @api.get('/runs')
    def runs():
        result = []
        for path in outputs.glob('*/main.json'):
            try:
                d = read_json(path)
                if 'rat_population' not in d.get('branches', {}): continue
                result.append({'id': path.parent.name, 'created_at': d.get('created_at'),
                               'status': d['status'], 'has_package_inputs': (path.parent / 'B1/main.json').is_file()})
            except (ValueError, OSError, KeyError): continue
        return {'runs': sorted(result, key=lambda d: d.get('created_at') or '', reverse=True)}

    @api.get('/runs/{identifier}')
    def run_details(identifier: str):
        folder = run_dir(identifier); main = read_json(folder / 'main.json'); main_hash = sha256(folder / 'main.json')
        branches = {key: linked(value) for key, value in main['branches'].items()}
        prep_ref = main.get('upstream', {}).get('data_preparation')
        prep = linked(prep_ref, {})
        manifest = linked(prep.get('normalization_manifest'), {'datasets': []})
        context = linked(main.get('upstream', {}).get('B1'), None)
        chosen = main.get('proposed_best_fit', {}).get('rat_population')
        parameters = optional(folder / 'rat_population/results/models' / (chosen or '_none') / 'result.json', {})
        logs = {}
        for name in ('rat_population', 'rat_individual', 'mouse_plasma', 'index'):
            logs[name] = optional(folder / name / 'execution.json', {})
        return {'id': identifier, 'main': main, 'main_sha256': main_hash, 'context': context,
                'package': optional(folder / 'package_changes.json', {}), 'branches': branches,
                'parameters': parameters, 'data': {'summary': {k: v for k, v in manifest.items() if k != 'datasets'},
                    'datasets': [{k: v for k, v in d.items() if k not in ('json', 'csv')} for d in manifest['datasets']],
                    'tables': linked(prep.get('table_assessments'), {}).get('tables', []),
                    'issues': linked(prep.get('scientific_issues'), {}).get('issues', []),
                    'quarantine': linked(prep.get('missingness'), {}).get('records', []),
                    'gate': linked(prep.get('human_review_gate'), {})},
                'catalog': linked(main.get('catalog_coverage'), {}),
                'index_supplement': linked(main.get('index_supplemental_assessment'), {}),
                'executions': logs, 'reviews': review_list(identifier, main_hash),
                'review_template': linked(main.get('human_review'), {}),
                'available_files': [str(p.relative_to(folder)).replace('\\', '/') for p in (
                    folder / 'verification/rat_population_diagnostics.png',
                    folder / 'mouse_plasma/results/mouse_composite_fits.png',
                    folder / 'REVIEW_REPORT.md') if p.is_file()]}

    @api.get('/runs/{identifier}/datasets/{dataset_id}')
    def dataset(identifier: str, dataset_id: str, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200)):
        main = read_json(run_dir(identifier) / 'main.json')
        prep = linked(main.get('upstream', {}).get('data_preparation'), {})
        manifest = linked(prep.get('normalization_manifest'), {'datasets': []})
        entry = next((d for d in manifest['datasets'] if d['id'] == dataset_id), None)
        if not entry: raise HTTPException(404, 'Dataset not found')
        data = linked(entry['json'])
        return {'id': dataset_id, 'metadata': data['metadata'], 'total': len(data['records']),
                'offset': offset, 'records': data['records'][offset:offset + limit], 'source_sha256': entry['json']['sha256']}

    @api.get('/runs/{identifier}/files/{artifact_path:path}')
    def artifact(identifier: str, artifact_path: str, download: bool = False):
        folder = run_dir(identifier); path = (folder / artifact_path).resolve()
        if not path.is_relative_to(folder) or not path.is_file(): raise HTTPException(404, 'File not found')
        parts = {s.casefold() for s in path.relative_to(folder).parts}
        if parts & {'attachments', 'snapshots'} or any('benchmark' in p for p in parts):
            raise HTTPException(403, 'Reference-only inputs are not exposed by the workbench')
        if path.suffix.lower() not in {'.json', '.csv', '.png', '.md', '.log', '.txt', '.xml'}:
            raise HTTPException(403, 'Artifact type not available')
        return FileResponse(path, filename=path.name if download else None)

    @api.post('/runs/{identifier}/reviews')
    def save_review(identifier: str, request: Review):
        folder = run_dir(identifier)
        if sha256(folder / 'main.json') != request.main_sha256:
            raise HTTPException(409, 'Results changed. Refresh before reviewing.')
        if not request.reviewer.strip() or len(request.rationale.strip()) < 5:
            raise HTTPException(422, 'Reviewer and rationale are required')
        main = read_json(folder / 'main.json')
        # Bind to artifact hashes too; a stable main file cannot hide changed results.
        for reference in main['branches'].values(): linked(reference)
        value = {**request.model_dump(), 'id': uuid4().hex, 'run_id': identifier, 'created_at': utcnow(),
                 'scope': 'EXPLORATORY_RESULT_REVIEW_ONLY', 'downstream_scientific_use_allowed': False,
                 'data_gate_modified': False, 'bound_results': main['branches']}
        write_json(state / 'workbench_reviews' / identifier / (value['created_at'].replace(':', '-') + '_' + value['id'] + '.json'), value)
        return value

    @api.get('/jobs')
    def jobs():
        result = []
        for path in (state / 'workbench_jobs').glob('*/status.json'):
            try: result.append(read_json(path))
            except (ValueError, OSError): continue
        return {'jobs': sorted(result, key=lambda d: d['created_at'], reverse=True)[:20]}

    @api.get('/direct-preparations')
    def direct_preparations():
        result = []
        seen = set()
        # Include runs started through the CLI/adapter as well as Workbench jobs.
        # The recorded approval reference is the join key; directory names are not trusted.
        for status_path in outputs.rglob('cleaning_status.json'):
            try:
                status = read_json(status_path)
                approval = status.get('approval') or {}
                review_path = Path(approval.get('path', '')).resolve()
                review_id = review_path.parent.name
                if (not review_path.is_relative_to(outputs) or not review_path.is_file()
                        or review_path.name != 'review.json' or review_path.parent.parent.name != 'direct_data_reviews'): continue
                if sha256(review_path) != approval.get('sha256'): continue
                from .direct_preparation import reviewed
                reviewed({'path': str(review_path), 'sha256': approval['sha256']})
                key = hashlib.sha256(str(status_path.resolve()).encode()).hexdigest()[:16]
                seen.add(str(status_path.resolve()))
                report = status.get('report') or {}
                report_path = Path(report.get('path', '')).resolve() if report.get('path') else None
                report_url = f'/ui-api/direct-preparations/{key}/report' if report_path and report_path.is_file() and report_path.is_relative_to(outputs) and sha256(report_path) == report.get('sha256') else None
                active_review_path = app.state.direct_data_reviews.path(review_id).resolve()
                result.append({'id': key, 'review_id': review_id, 'status': status.get('status'),
                    'stage': status.get('stage'), 'technical_processing_complete': status.get('technical_processing_complete'),
                    'report_available': bool(report_url), 'report_url': report_url,
                    'review_in_active_store': review_path == active_review_path,
                    'source': 'recorded_direct_preparation'})
            except (ValueError, OSError, KeyError, TypeError, PipelineError): continue
        for path in (state / 'workbench_jobs').glob('*/request.json'):
            try:
                spec = read_json(path)
                mode = spec.get('mode')
                if mode not in {'direct_preparation', 'fresh_pre_eda', 'fresh_pre_eda_from_rules'}: continue
                status = optional(path.parent / 'status.json', {})
                if mode == 'direct_preparation':
                    report = Path(spec['out']) / 'data_preparation/data_report.json'
                    cleaning_status = Path(spec['out']) / 'cleaning_status.json'
                else:
                    artifacts = pre_eda_artifact_paths(spec['out'], mode)
                    report, cleaning_status = artifacts['data_report'], artifacts['cleaning_status']
                if str(cleaning_status.resolve()) not in seen:
                    result.append({**status, 'report_available': report.is_file(),
                                   'report_url': f"/ui-api/jobs/{spec['id']}/artifacts/data_report" if report.is_file() else None})
            except (ValueError, OSError, KeyError): continue
        return {'jobs': sorted(result, key=lambda d: d.get('created_at') or '', reverse=True)}

    @api.get('/direct-preparations/{identifier}/report')
    def direct_preparation_report(identifier: str):
        require_id(identifier)
        for status_path in outputs.rglob('cleaning_status.json'):
            try:
                key = hashlib.sha256(str(status_path.resolve()).encode()).hexdigest()[:16]
                if key != identifier: continue
                status = read_json(status_path); ref = status.get('report') or {}
                path = Path(ref.get('path', '')).resolve()
                if not path.is_relative_to(outputs) or not path.is_file() or sha256(path) != ref.get('sha256'):
                    raise HTTPException(409, 'Preparation report changed or is unavailable.')
                return FileResponse(path, media_type='application/json', filename=path.name)
            except (ValueError, OSError, TypeError): continue
        raise HTTPException(404, 'Preparation report not found')

    def first_part_mains():
        from .first_part_handoff import verify_final_main
        result=[]
        for path in outputs.rglob('first_part/published/main.json'):
            try:
                verified=verify_final_main(path); reference=verified['main_ref']
                if not Path(reference['path']).resolve().is_relative_to(outputs): continue
                relative=path.parent.parent.parent.relative_to(outputs).as_posix()
                identifier='main_'+hashlib.sha256(str(path.resolve()).encode()).hexdigest()[:16]
                result.append({'id':identifier,'source':relative,'main_sha256':reference['sha256'],
                    'review_status':'VERIFIED_FIRST_PART_HANDOFF','scientific_approval':False})
            except (ValueError,OSError,KeyError): continue
        return sorted(result,key=lambda x:x['source'])

    @api.get('/first-part-mains')
    def list_first_part_mains():
        return {'mains':first_part_mains()}

    @api.post('/pre-eda', status_code=202)
    def start_pre_eda_from_first_part(request: PreEdaRequest):
        if not request.main_id: raise HTTPException(422,'Select a verified First Part handoff.')
        mains=first_part_mains(); selected=next((x for x in mains if x['id']==request.main_id),None)
        if not selected: raise HTTPException(409,'This First Part handoff is missing, stale or no longer verified.')
        main=outputs/selected['source']/'first_part/published/main.json'
        from .adequacy import file_ref
        main_ref=file_ref(main)
        from .first_part_handoff import verify_final_main
        if verify_final_main(main)['main_ref']!=main_ref: raise HTTPException(409,'First Part main changed after selection.')
        return launch_mode({'mode':'fresh_pre_eda','main_ref':main_ref,
            'auto_approve_human_gates':True,'user_authorized_automation':True,
            'authorization_at':utcnow(),'first_part_id':request.main_id},'data_preparation')

    @api.post('/workflow/sessions/{identifier}/pre-eda', status_code=202)
    def start_pre_eda_from_approved_context(identifier: str, request: PreEdaRequest):
        session=canvas.load(identifier)
        if not canvas.approved(session['nodes']['context']):
            raise HTTPException(409,'Approve the exact Context before starting pre-EDA.')
        rules_ref=session.get('project_rules_ref')
        if not rules_ref:
            raise HTTPException(409,'This approved Context has no published Project Rules pack. Publish Rules before the formal First Part handoff.')
        from .adequacy import check_ref
        from .project_rule_agent import verify_published
        check_ref(rules_ref)
        pack=verify_published(rules_ref)
        context_main=next((a for a in session['nodes']['context'].get('artifacts',[]) if a.get('name')=='main.json'),None)
        if not context_main or pack.get('main_ref')!={'path':context_main.get('path'),'sha256':context_main.get('sha256')}:
            raise HTTPException(409,'Published Rules pack does not bind to the reviewed Context.')
        rules_path=Path(rules_ref['path']).resolve()
        if not rules_path.is_relative_to(outputs):
            raise HTTPException(403,'Published Rules pack is outside configured outputs.')
        return launch_mode({'mode':'fresh_pre_eda_from_rules','rules_pack_ref':rules_ref,
            'auto_approve_human_gates':True,'user_authorized_automation':True,
            'authorization_at':utcnow(),'authorization_source_session':identifier},'data_preparation')

    @api.post('/jobs/{identifier}/pre-eda', status_code=202)
    def start_pre_eda(identifier: str, request: PreEdaRequest):
        require_id(identifier)
        folder = state / 'workbench_jobs' / identifier
        if not (folder / 'request.json').is_file(): raise HTTPException(404, 'Job not found')
        original = read_json(folder / 'request.json')
        if original.get('mode') == 'fresh_pre_eda': raise HTTPException(409, 'This job is already a pre-EDA run.')
        root = Path(original.get('out', '')).resolve()
        main = root / 'B1' / 'main.json'
        if not root.is_relative_to(outputs) or not main.is_file():
            raise HTTPException(409, 'The source job has no verified compressed Context main.json.')
        status = optional(folder / 'status.json', {})
        if status.get('status') != 'COMPLETED':
            raise HTTPException(409, 'Complete the compression/Context job before starting pre-EDA.')
        from .adequacy import file_ref
        main_ref = file_ref(main)
        from .first_part_handoff import verify_final_main
        try:
            if verify_final_main(main)['main_ref'] != main_ref:
                raise HTTPException(409, 'This B1 Context is not the required reviewed First Part v4 handoff. Select a verified first_part/published/main.json from the list instead.')
        except (ValueError, KeyError, OSError):
            raise HTTPException(409, 'This B1 Context is not the required reviewed First Part v4 handoff. Select a verified first_part/published/main.json from the list instead.')
        canvas_session = None
        for session_path in canvas.root.glob('*/session.json'):
            try:
                candidate = read_json(session_path)
                if candidate.get('job_id') == identifier:
                    canvas_session = candidate
                    break
            except (ValueError, OSError): continue
        if not canvas_session or not canvas.approved(canvas_session['nodes']['context']):
            raise HTTPException(409, 'Approve this exact Context in the workflow before starting the pre-EDA chain.')
        bound_main = next((a for a in canvas_session['nodes']['context'].get('artifacts', []) if a.get('name') == 'main.json'), None)
        if not bound_main or bound_main.get('sha256') != main_ref['sha256']:
            raise HTTPException(409, 'The approved Context does not bind to this compressed main.json.')
        return launch_mode({'mode': 'fresh_pre_eda', 'main_ref': main_ref,
            'auto_approve_human_gates': True,
            'user_authorized_automation': True, 'authorization_at': utcnow(),
            'authorization_source_job': identifier}, 'data_preparation')

    @api.get('/data-reviews')
    def data_reviews():
        store = app.state.direct_data_reviews
        values = []
        for path in sorted(store.root.glob('*/review.json'), key=lambda p: p.stat().st_mtime, reverse=True):
            try: values.append(store.view(path.parent.name))
            except (ValueError, OSError, KeyError): continue
        return {'reviews': values}

    @api.post('/data-reviews/{identifier}/preparation', status_code=202)
    def start_direct_preparation(identifier: str, request: DirectPreparationRequest):
        store = app.state.direct_data_reviews
        review = store.view(identifier)
        if review.get('status') == 'INTERRUPTED' and review.get('can_review'):
            from .workflow_canvas import Decision
            store.decide(identifier, Decision(decision='APPROVE', reviewer='USER_AUTHORIZED_AUTOMATION',
                rationale='User explicitly enabled auto_approve_human_gates for this run; scientific checks preserved.',
                output_signature=review['output_signature'], confirmed=True))
            review = store.view(identifier)
        if not review.get('approved'):
            raise HTTPException(409, 'Direct preparation requires a current DirectDataReview; stale/rejected/changed reviews cannot be approved automatically.')
        approval_path = store.path(identifier)
        from .adequacy import file_ref
        approval_ref = file_ref(approval_path)
        from ctxcomp.providers import provider_model
        # This per-request flag records the user's authorization to launch technical
        # preparation. It does not manufacture or replace the DirectDataReview decision.
        return launch_mode({'mode': 'direct_preparation', 'approval_ref': approval_ref,
            'model': request.model or provider_model(), 'launch_authorization': {
                'kind': 'USER_AUTHORIZED_TECHNICAL_PREPARATION', 'confirmed': True,
                'scope': 'DIRECT_PREPARATION_ONLY', 'user_authorized_automation': True,
                'auto_approve_human_gates': True, 'at': utcnow()}}, 'data_preparation')

    @api.post('/jobs', status_code=202)
    def start_job(request: Job):
        if request.upload_ids:
            if request.baseline_run or request.package_upload_id: raise HTTPException(422, 'Fresh uploads cannot be mixed with a replay baseline')
            if request.stop_after == 'exploratory_results': raise HTTPException(422, 'Fresh data require mapping, QC and human release before modeling')
            uploads = []
            for identifier in request.upload_ids:
                path = uploaded_path(state, identifier)
                meta = read_json(path.parent / 'metadata.json')
                uploads.append({'path': str(path), 'name': meta['filename'], 'sha256': meta['sha256']})
            mode = {'mode': 'fresh', 'uploads': uploads, 'proposal_entry': request.proposal_entry,
                    'reference_only': request.reference_only, 'model': request.model,
                    'project_materials': request.project_materials}
        else:
            if not request.baseline_run or not request.package_upload_id: raise HTTPException(422, 'Upload new files for this run')
            baseline = run_dir(request.baseline_run)
            if not (baseline / 'B1/main.json').is_file():
                raise HTTPException(422, 'This historical run has no portable proposal handoff. Choose a package run.')
            package = uploaded_path(state, request.package_upload_id)
            if package.suffix != '.zip': raise HTTPException(422, 'Upload a ZIP data package')
            mode = {'mode': 'verified_replay', 'package': str(package), 'baseline': str(baseline)}
        return launch_mode(mode, request.stop_after)

    def launch_mode(mode, stop_after):
        if mode.get('mode') == 'fresh' and stop_after not in {'intake', 'context'}:
            raise HTTPException(422, 'Review Context first, then start Data adequacy from the workflow. QC cannot bypass this gate.')
        if mode.get('mode') == 'fresh':
            mode = {'compression_profile': 'LEAN_1.0', **mode}
        with lock:
            if any(p.poll() is None for p in children.values()):
                raise HTTPException(409, 'Another run is active. Wait for it to finish.')
            identifier = 'PMB_UI_' + utcnow()[:19].replace('-', '').replace(':', '').replace('T', '_') + '_' + uuid4().hex[:6]
            job_dir = state / 'workbench_jobs' / identifier; job_dir.mkdir(parents=True)
            spec = {'id': identifier, 'created_at': utcnow(), **mode, 'stop_after': stop_after,
                    'out': str(outputs / identifier), 'job_dir': str(job_dir),
                    'state_dir': str(state), 'outputs_dir': str(outputs)}
            write_json(job_dir / 'request.json', spec)
            status = {'id': identifier, 'created_at': spec['created_at'], 'status': 'QUEUED', 'stage': '等待启动', 'events': []}
            write_json(job_dir / 'status.json', status)
            with (job_dir / 'worker.log').open('w', encoding='utf-8') as log:
                proc = subprocess.Popen([sys.executable, '-I', '-X', 'utf8', str(BACKEND / 'research_pipeline/scripts/run_workbench_job.py'),
                                         str(job_dir / 'request.json')], cwd=PROJECT, stdout=log, stderr=log, env=worker_env,
                                        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            children[identifier] = proc
            write_json(job_dir / 'worker.json', worker_record(proc))
        return status

    @api.post('/jobs/{identifier}/resume', status_code=202)
    def resume_job(identifier: str, request: ResumeJob):
        if canvas.owns_job(identifier):
            raise HTTPException(409, '该作业由流程画布管理，请通过对应步骤执行并完成上游审核')
        return resume_worker(identifier, request)

    def resume_worker(identifier: str, request: ResumeJob):
        from .workflow_runtime import make_plan
        require_id(identifier); folder = state / 'workbench_jobs' / identifier
        if not (folder / 'request.json').is_file(): raise HTTPException(404, 'Job not found')
        with lock:
            if any(p.poll() is None for p in children.values()): raise HTTPException(409, 'Another run is active')
            spec = read_json(folder / 'request.json'); plan = make_plan(spec)
            if request.target not in plan['targets']: raise HTTPException(422, 'Target is unavailable before scientific review')
            if (folder / 'pause.flag').exists():
                (folder / 'pause.flag').rename(folder / ('pause_' + uuid4().hex + '.flag'))
            if (folder / 'cancel.flag').exists():
                (folder / 'cancel.flag').rename(folder / ('cancel_' + uuid4().hex + '.flag'))
            current = read_json(folder / 'status.json')
            if current['status'] in {'QUEUED', 'RUNNING'}:
                # The worker never reported an end, e.g. the workbench closed while it ran. Continue only once it is
                # known to be gone; its executor lock may remain, so unlock this job folder first.
                if worker_alive(optional(folder / 'worker.json')) is not False: raise HTTPException(409, 'This run is still active')
                (folder / 'needs_unlock.flag').touch()
            # The previous attempt's outcome must not be read as this attempt's.
            for key in ('finished_at', 'error', 'failure', 'technical_error', 'context_feedback', 'control'): current.pop(key, None)
            current.update(status='QUEUED', stage='人工请求续跑 · ' + request.target, target=request.target)
            write_json(folder / 'status.json', current)
            write_json(folder / ('resume_' + uuid4().hex + '.json'), {'at': utcnow(), 'target': request.target,
                'scientific_approval': False, 'meaning': 'Technical continuation only; existing data gates remain enforced'})
            with (folder / 'worker.log').open('a', encoding='utf-8') as log:
                children[identifier] = subprocess.Popen([sys.executable, '-I', '-X', 'utf8',
                    str(BACKEND / 'research_pipeline/scripts/run_workbench_job.py'), str(folder / 'request.json'), '--target', request.target],
                    cwd=PROJECT, stdout=log, stderr=log, env=worker_env, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            write_json(folder / 'worker.json', worker_record(children[identifier]))
        return current

    def pause_worker(identifier: str):
        require_id(identifier); folder = state / 'workbench_jobs' / identifier
        with lock:
            if not (folder / 'request.json').is_file(): raise HTTPException(404, 'Job not found')
            current = read_json(folder / 'status.json')
            if current['status'] in {'QUEUED', 'RUNNING'}:
                write_json(folder / 'pause.flag', {'at': utcnow(), 'scope': 'THIS_JOB_ONLY',
                    'policy': 'STOP_ACTIVE_COMPUTATION_KEEP_COMPLETED_RECEIPTS'})
            return current

    @api.get('/model/status')
    def model_status():
        from .model_connection import connection_status
        return connection_status()

    @api.post('/model/test')
    def model_test():
        from .model_connection import test_connection
        return test_connection(state)

    @api.get('/jobs/{identifier}/artifacts/{name}')
    def job_artifact(identifier: str, name: str):
        require_id(identifier); folder = state / 'workbench_jobs' / identifier
        if not (folder / 'request.json').is_file(): raise HTTPException(404, 'Job not found')
        run = Path(read_json(folder / 'request.json')['out']).resolve()
        if not run.is_relative_to(outputs): raise HTTPException(403, 'Invalid run output')
        artifacts = {'plan': folder / 'plan.json', 'files': run / 'context_work/intake/manifest.json',
            'context': run / 'B1/main.json', 'sources': run / 'source_preparation/output.json',
            'data': run / 'data_preparation/main.json', 'data_report': run / 'data_preparation/data_report.json',
            'cleaning_status': run / 'cleaning_status.json',
            'normalization_manifest': run / 'data_preparation/normalization_manifest.json',
            'preparation_execution': run / 'data_preparation/preparation_execution.json',
            'cleaning_log': run / 'data_preparation/cleaning_log.json',
            'routing': run / 'handoffs/routing_plan.json'}
        mode = read_json(folder / 'request.json').get('mode')
        if mode in {'fresh_pre_eda', 'fresh_pre_eda_from_rules'}:
            artifacts.update(pre_eda_artifact_paths(run, mode))
        path = artifacts.get(name)
        if not path or not path.is_file(): raise HTTPException(404, 'Artifact is not ready')
        return FileResponse(path, filename=path.name)

    @api.get('/jobs/{identifier}')
    def job_status(identifier: str):
        require_id(identifier); folder = state / 'workbench_jobs' / identifier
        if not (folder / 'status.json').is_file(): raise HTTPException(404, 'Job not found')
        value = read_json(folder / 'status.json')
        if identifier in children and children[identifier].poll() not in (None, 0) and value['status'] in ('QUEUED', 'RUNNING'):
            value.update(status='STOPPED_ON_ERROR', error='Worker exited unexpectedly; inspect worker.log')
        if identifier in children and children[identifier].poll() is not None and value['status'] == 'WAITING_FOR_HUMAN_REVIEW' and not value.get('control'):
            value.update(status='STOPPED_ON_ERROR', error='Worker exited before LangGraph finalized diagnostics; inspect worker.log')
        if identifier not in children and value['status'] in ('QUEUED', 'RUNNING') and worker_alive(optional(folder / 'worker.json')) is False:
            value.update(status='STOPPED_ON_ERROR', error=WORKER_EXITED + ': the worker process for this run is no longer running. '
                         'The workbench may have closed or restarted while it ran.')
        log = folder / 'worker.log'
        value['log_tail'] = log.read_text(encoding='utf-8', errors='replace')[-18000:] if log.is_file() else ''
        plan = optional(folder / 'plan.json', {})
        value['available_targets'] = list(plan.get('targets', {}))
        value['cpu'] = plan.get('cpu')
        value['blocks'] = []
        for name, step in plan.get('steps', {}).items():
            done = optional(folder / 'receipts' / (name + '.json'))
            attempts = sorted((folder / 'attempts' / name).glob('*/execution.json'), key=lambda p: p.stat().st_mtime)
            last = read_json(attempts[-1]) if attempts else None
            value['blocks'].append({'stage': name, 'depends': step['depends'], 'cpu_slots': step['slots'],
                                    'status': (done or last or {}).get('status', 'NOT_RUN')})
        run = Path(read_json(folder / 'request.json')['out'])
        from .execution_feedback import execution_feedback, model_progress
        if value['status'] == 'STOPPED_ON_ERROR':
            technical = value.get('technical_error') or value.get('error', '')
            if value.get('target')=='animal_pk_execution':
                failures=sorted((run/'animal_pk').rglob('failure.json'),key=lambda p:p.stat().st_mtime)
                if failures:
                    value['failure']=read_json(failures[-1])
                elif not value.get('failure'):
                    value['failure']=execution_feedback(run,technical,value.get('started_at'),value.get('target'))
            else:
                value['failure'] = execution_feedback(run, technical, value.get('started_at'), value.get('target'))
            value.update(technical_error=technical, error=value['failure']['summary'])
        if value['status'] in {'QUEUED','RUNNING'}:
            value['model_progress'] = model_progress(run, value.get('started_at'))
        value['artifacts'] = [key for key, p in {'plan': folder / 'plan.json', 'files': run / 'context_work/intake/manifest.json',
            'context': run / 'B1/main.json', 'sources': run / 'source_preparation/output.json',
            'data': run / 'data_preparation/main.json', 'data_report': run / 'data_preparation/data_report.json',
            'cleaning_status': run / 'cleaning_status.json',
            'normalization_manifest': run / 'data_preparation/normalization_manifest.json',
            'preparation_execution': run / 'data_preparation/preparation_execution.json',
            'cleaning_log': run / 'data_preparation/cleaning_log.json',
            'routing': run / 'handoffs/routing_plan.json'}.items() if p.is_file()]
        mode = read_json(folder / 'request.json').get('mode')
        if mode in {'fresh_pre_eda', 'fresh_pre_eda_from_rules'}:
            fresh_artifacts = pre_eda_artifact_paths(run, mode)
            value['artifacts'] = list(dict.fromkeys([*value['artifacts'], *[k for k,p in fresh_artifacts.items() if p.is_file()]]))
        return value

    def launch_supplemental(request_path):
        with lock:
            if any(p.poll() is None for p in children.values()): raise HTTPException(409, 'Another run is active')
            identifier = 'SUPP_' + uuid4().hex
            folder = state / 'workbench_jobs' / identifier; folder.mkdir(parents=True)
            spec = {'id': identifier, 'created_at': utcnow(), 'mode': 'supplemental', 'stop_after': 'supplemental',
                    'supplemental_request': str(request_path), 'out': str(outputs / identifier), 'job_dir': str(folder)}
            write_json(folder / 'request.json', spec)
            status = {'id': identifier, 'created_at': spec['created_at'], 'status': 'QUEUED', 'events': []}
            write_json(folder / 'status.json', status)
            with (folder / 'worker.log').open('w', encoding='utf-8') as log:
                children[identifier] = subprocess.Popen([sys.executable, '-I', '-X', 'utf8',
                    str(BACKEND / 'research_pipeline/scripts/run_workbench_job.py'), str(folder / 'request.json')],
                    cwd=PROJECT, stdout=log, stderr=log, env=worker_env, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            write_json(folder / 'worker.json', worker_record(children[identifier]))
            return status

    from .workflow_canvas import CanvasStore, canvas_router
    from .tributaries import TributaryStore, tributary_router
    from .context_revisions import ContextRevisions, context_revision_router
    canvas = CanvasStore(state, outputs,
        lambda ids, target, project_materials=None: start_job(Job(upload_ids=ids, stop_after=target, project_materials=project_materials or [])),
        lambda identifier, target: resume_worker(identifier, ResumeJob(target=target)), job_status, pause_worker)
    def launch_adequacy(session):
        from .adequacy import file_ref
        # A new downstream plan preserves the approved context and its original code/receipts.
        approval = write_json(outputs / 'canvas_cycles' / session['id'] / ('context_approval_' + uuid4().hex + '.json'),
            {'at': utcnow(), 'session_id': session['id'], 'context': session['nodes']['context'],
             'parent_job_id': session.get('job_id'), 'scope': 'INITIAL_INPUTS_FOR_QC',
             **({'project_rules_ref':session['project_rules_ref']} if session.get('project_rules_ref') else {}),
             'scope_amendment': session.get('scope_amendment')})
        return launch_mode({'mode': 'reviewed_context', 'approved_context': file_ref(approval),
            'data_agents_version':'2.0',
            'pk_reference_pilot':session.get('pk_reference_pilot',{}).get('enabled',False),
            'parent_job_id': session.get('job_id')}, 'adequacy')
    canvas.launch_adequacy = launch_adequacy
    def launch_preparation(session):
        from .adequacy import file_ref
        approval = write_json(outputs / 'canvas_cycles' / session['id'] / ('data_approval_' + uuid4().hex + '.json'),
            {'at': utcnow(), 'session_id': session['id'], 'adequacy': session['nodes']['adequacy'],
             'parent_job_id': session.get('job_id'), 'preparation_plan': session.get('preparation_plan'),
             'scope': 'TECHNICAL_PREPARATION_ONLY_NOT_MODEL_RELEASE'})
        return launch_mode({'mode': 'reviewed_data', 'approved_data': file_ref(approval),
            'data_agents_version':'2.0',
            'parent_job_id': session.get('job_id')}, 'data_preparation')
    canvas.launch_preparation = launch_preparation
    def launch_dispatch(session):
        canvas.validate_clinical_draft(session)
        return launch_mode({'mode':'reviewed_eda','reviewed_eda':canvas.clinical_snapshot(session),
            'clinical_spec':session['nodes']['dispatch']['clinical_spec_ref'],
            'parent_job_id':session.get('job_id')},'clinical_dispatch')
    canvas.launch_dispatch=launch_dispatch
    canvas.tributaries = TributaryStore(canvas, launch_supplemental,
        lambda identifier: resume_worker(identifier, ResumeJob(target='supplemental')))
    def launch_context_revision(uploads, proposal_entry, reference_only, model, revision):
        files = [{'path': str(uploaded_path(state, u['upload_id'])), 'name': u['name'], 'sha256': u['sha256']} for u in uploads]
        return launch_mode({'mode': 'fresh', 'uploads': files, 'proposal_entry': proposal_entry,
            'reference_only': reference_only, 'model': model, 'context_revision': revision}, 'context')
    canvas.context_revisions = ContextRevisions(canvas, launch_context_revision)
    api.include_router(canvas_router(canvas))
    from .animal_pk_api import animal_pk_router
    api.include_router(animal_pk_router(canvas, launch_mode, job_status, pause_worker))
    from .pk_reference_api import reference_router
    api.include_router(reference_router(canvas, launch_mode, job_status, pause_worker))
    api.include_router(tributary_router(canvas.tributaries))
    api.include_router(context_revision_router(canvas.context_revisions))
    app.state.canvas = canvas
    app.include_router(api)
    from .data_direct_review import DirectDataReview, router as data_review_router
    app.state.direct_data_reviews = DirectDataReview(state, outputs)
    app.include_router(data_review_router(app.state.direct_data_reviews))
    app.mount('/pipeline', create_app(state))

    @app.get('/assets/results-index.html', include_in_schema=False)
    @app.get('/assets/index.html', include_in_schema=False)
    def retired_entry(request: Request):
        # Old bookmarks enter the only current UI without losing their flow ID.
        return RedirectResponse('/' + ('?' + request.url.query if request.url.query else ''), status_code=307)

    app.mount('/assets', StaticFiles(directory=STATIC), name='assets')

    @app.get('/')
    def index(): return HTMLResponse(current_frontend_html())

    return app


def main():
    p = argparse.ArgumentParser(); p.add_argument('--port', type=int, default=8767)
    p.add_argument('--outputs'); p.add_argument('--state'); args = p.parse_args()
    import uvicorn
    uvicorn.run(create_workbench(args.outputs, args.state), host='127.0.0.1', port=args.port)


if __name__ == '__main__': main()
