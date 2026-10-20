"""Workspace adapters. Scientific execution and review use the original canvas."""
from pathlib import Path
from uuid import uuid4
from fastapi import HTTPException, UploadFile, File
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from .services import read, sha


class OrganizeRequest(BaseModel):
    table_plan: dict = Field(default_factory=dict)


class RecoverContextRequest(BaseModel):
    confirmed: bool


def connect_workspace(app, root, state):
    from .handoffs import connect_handoffs
    connect_handoffs(app, state)
    from research_pipeline.attachments import store_upload, uploaded_path
    from research_pipeline.common import write_json, require_id, utcnow
    from ctxcomp.intake import intake_files
    from research_pipeline.source_preparation import prepare_sources
    native = state / 'workbench_state'
    catalog = read(root / 'examples/inputs/manifest.json')

    @app.post('/workspace-api/workflow/{identifier}/continue-context-demo', status_code=202)
    def continue_context_demo(identifier: str, request: RecoverContextRequest):
        """Resume an unchanged, eligible prior review after a demo policy update."""
        if request.confirmed is not True:
            raise HTTPException(422, 'Confirm technical demo continuation with the original review retained.')
        import os
        if os.getenv('CTXCOMP_DISABLE_RESPONSE_REUSE') == '1':
            raise HTTPException(409, 'Response reuse is disabled. Import the inputs into a fresh workflow.')
        from ctxcomp.engine import load_run, accepted_response
        from ctxcomp.lean_compression import content, validate_candidate, validate_review, request as review_request
        from ctxcomp.demo_review import eligible
        canvas=app.state.canvas
        with canvas.lock:
            session=canvas.load(identifier);node=session['nodes']['context']
            if (node['execution'] not in {'FAILED','REVISION_REQUIRED'} or session['control_status']!='READY'
                    or any(n['execution'] in {'RUNNING','PAUSING'} for n in session['nodes'].values())):
                raise HTTPException(409, 'Continuation requires an inactive Context review stop.')
            if not canvas.approved(session['nodes']['intake']):
                raise HTTPException(409, 'Current intake must be complete before continuation.')
            spec=read(native/'workbench_jobs'/session['job_id']/'request.json')
            run=Path(spec['out']).resolve()
            if not run.is_relative_to((state/'workbench_outputs').resolve()):
                raise HTTPException(409, 'Context is outside this demo.')
            work=run/'context_work';bundle,current=load_run(work)
            candidate=content(accepted_response(work,current,'context'))
            review=read(work/'lean/last_review.json')
            validate_candidate(candidate,bundle)
            validate_review(review,candidate,bundle,review_request(work,bundle,current,'context_review'))
            if not eligible(review['review']):
                raise HTTPException(409, 'Only a sole canonical-placement issue can be deferred in the technical demo.')
            prior=node.copy()
            from ctxcomp.lean_compression import run_model as apply_saved_review
            def no_model_calls(*args,**kwargs):
                raise ValueError('Demo continuation may only verify the retained candidate and review.')
            apply_saved_review(work,no_model_calls,'saved_response')
            canvas.resume(session['job_id'],'context')
            node.update(execution='RUNNING',error=None,failure=None,model_progress=None,
                        job_id=session['job_id'],requires_control_trace=True)
            node.setdefault('segments',[]).append({'started_at':utcnow(),'stopped_at':None})
            session['events'].append({'at':utcnow(),'node':'context','action':'DEMO_CONTEXT_CONTINUATION',
                'prior_state':prior,'original_review_decision':'REVISE','candidate_changed':False,'scientific_release':False})
            write_json(canvas.path(identifier),session)
            return canvas.view(session)

    @app.post('/workspace-api/workflow/{identifier}/recover-context')
    def recover_context(identifier: str, request: RecoverContextRequest):
        """Recollect a completed compression after its missing Rules are supplied."""
        if request.confirmed is not True:
            raise HTTPException(422, 'Confirm recovery of the retained, verified Context.')
        import os
        if os.getenv('CTXCOMP_DISABLE_RESPONSE_REUSE') == '1':
            raise HTTPException(409, 'Response reuse is disabled. Import the inputs into a fresh workflow.')
        from ctxcomp.engine import verify_context
        from research_pipeline.project_rule_agent import verify_published, file_ref
        canvas = app.state.canvas
        with canvas.lock:
            session = canvas.load(identifier)
            node = session['nodes']['context']
            if node['execution'] != 'FAILED' or any(n['execution'] in {'RUNNING','PAUSING'} for n in session['nodes'].values()):
                raise HTTPException(409, 'Recovery is limited to an inactive failed Context collector.')
            spec = read(native/'workbench_jobs'/session['job_id']/'request.json')
            run = Path(spec['out']).resolve()
            if not run.is_relative_to((state/'workbench_outputs').resolve()):
                raise HTTPException(409, 'Context is outside this demo.')
            verify_context(run/'context_work')
            if read(run/'B1/main.json') != read(run/'context_work/handoff/main.json'):
                raise HTTPException(409, 'Compressed Context changed after review.')
            pack = verify_published(file_ref(run/'project_rules/published/project_rules.json'))
            if read(pack['base_main_ref']['path']) != read(run/'B1/main.json'):
                raise HTTPException(409, 'Rules do not bind the completed Context.')
            receipt = run/'context_recovery.json'
            if receipt.exists():
                raise HTTPException(409, 'This recovery has already been recorded.')
            write_json(receipt, {'at': utcnow(), 'reason': 'Completed compression retained; missing Rules supplied.',
                'previous_context_state': node.copy(), 'rules_status': pack['status'], 'scientific_release': False})
            canvas.collect_outputs(session, 'context')
            for key in ('failure', 'technical_error', 'context_feedback'):
                session['nodes']['context'].pop(key, None)
            session['events'].append({'at': utcnow(), 'node': 'context', 'action': 'VERIFIED_OUTPUTS_RECOVERED',
                'receipt': file_ref(receipt), 'model_context_rerun': False})
            write_json(canvas.path(identifier), session)
            return canvas.view(session)

    @app.get('/workspace-api/capabilities')
    def capabilities():
        import os
        from ctxcomp.providers import executor_identity
        return {'version': 'connected-20261019', 'response_reuse_disabled': os.getenv('CTXCOMP_DISABLE_RESPONSE_REUSE') == '1', 'live': ['intake', 'source_tables', 'context_compression', 'data_assessment', 'data_preparation', 'review_notes'],
                'knowledge_pages': {'rag': 'EXPLANATION_ONLY', 'context_builder': 'EXPLANATION_ONLY'},
                'execution_stop': 'data', 'handoff_inspection': 'READ_ONLY_CURRENT_AND_PRIOR_ATTEMPTS',
                'data_profile': 'SOURCE_PRESERVING_DEMO_1.0', 'scientific_adequacy': 'DEFERRED_TO_DOWNSTREAM_REVIEW',
                'api_documentation': '/docs', 'openapi_schema': '/openapi.json', 'model_executor': executor_identity(),
                'eda': 'NOT_ENABLED', 'pk': 'RECORDED_DIAGNOSTICS_ONLY',
                'knowledge_curation': 'SNAPSHOT_INSPECTION_ONLY', 'scientific_release': False}

    @app.get('/workspace-api/examples')
    def examples():
        return [{**item, 'url': '/examples/inputs/' + item['filename']} for item in catalog]

    def import_package(stream, name, example_id=None):
        upload = store_upload(native, stream, name)
        session = app.state.canvas.create()
        identifier = session['session_id']
        app.state.canvas.bind_files(identifier, [upload['upload_id']])
        receipt = {'id': identifier, 'created_at': utcnow(), 'filename': name, 'example_id': example_id,
                   'upload': upload, 'status': 'REGISTERED', 'scientific_approval': False,
                   'workflow_url': '/workbench?flow=' + identifier + '#node=intake&tab=input'}
        write_json(state / 'imports' / identifier / 'receipt.json', receipt)
        return receipt

    @app.post('/workspace-api/examples/{example_id}/import', status_code=201)
    def import_example(example_id: str):
        item = next((e for e in catalog if e['id'] == example_id), None)
        if not item:
            raise HTTPException(404, 'Unknown example package.')
        path = root / 'examples/inputs' / item['filename']
        if sha(path) != item['sha256']:
            raise HTTPException(409, 'Example package changed; restore the verified package.')
        with path.open('rb') as stream:
            return import_package(stream, path.name, example_id)

    @app.post('/workspace-api/imports', status_code=201)
    def upload(file: UploadFile = File(...)):
        if Path(file.filename or '').suffix.lower() != '.zip':
            raise HTTPException(422, 'Upload one ZIP containing the proposal and source files.')
        return import_package(file.file, file.filename)

    @app.get('/workspace-api/imports')
    def imports():
        return sorted((read(p) for p in (state / 'imports').glob('*/receipt.json')),
                      key=lambda value: value['created_at'], reverse=True)

    def receipt_for(identifier):
        require_id(identifier)
        path = state / 'imports' / identifier / 'receipt.json'
        if not path.is_file():
            raise HTTPException(404, 'Import not found.')
        return path, read(path)

    @app.post('/workspace-api/imports/{identifier}/inspect')
    def inspect(identifier: str):
        path, receipt = receipt_for(identifier)
        intake = path.parent / 'intake'
        if (intake / 'manifest.json').exists():
            from ctxcomp.intake import verify_intake
            manifest = verify_intake(intake / 'manifest.json')
        else:
            manifest = intake_files(intake, package=uploaded_path(native, receipt['upload']['upload_id']))['manifest']
        receipt.update(status=manifest['status'], manifest=manifest, context_generation='NOT_RUN', scientific_qc='NOT_RUN')
        write_json(path, receipt)
        return receipt

    @app.post('/workspace-api/imports/{identifier}/organize')
    def organize(identifier: str, body: OrganizeRequest):
        path, receipt = receipt_for(identifier)
        manifest = path.parent / 'intake/manifest.json'
        if not manifest.is_file():
            raise HTTPException(409, 'Inspect the package before organizing source tables.')
        preparation_id = 'sourceprep_' + uuid4().hex
        result = prepare_sources(manifest, native / 'source_preparations' / preparation_id, body.table_plan or None)
        receipt['source_preparation'] = {'id': preparation_id, **result}
        write_json(path, receipt)
        return receipt

    @app.get('/workspace-api/imports/{identifier}')
    def import_details(identifier: str):
        return receipt_for(identifier)[1]

    @app.get('/workspace-api/workflow-runs')
    def workflow_runs():
        values = []
        for path in app.state.canvas.root.glob('*/session.json'):
            s = app.state.canvas.view(app.state.canvas.load(path.parent.name))
            values.append({'id': s['session_id'], 'control_status': s['control_status'], 'stats': s['stats'],
                           'nodes': [{'id': n['id'], 'state': n['state']} for n in s['nodes']]})
        return values
