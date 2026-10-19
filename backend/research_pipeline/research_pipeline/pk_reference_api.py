"""A small inspection/rerun surface for the optional PK reference pilot."""
from pathlib import Path
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict
from .common import read_json, write_json, require_id, utcnow
from .adequacy import file_ref, check_ref
from .pk_reference_pilot import LIBRARY, load_library


class PilotOptions(BaseModel):
    model_config=ConfigDict(extra='forbid')
    enabled:bool


class PilotRunOptions(BaseModel):
    model_config=ConfigDict(extra='forbid')
    revise_main:bool=False
    allow_unreviewed_context:bool=False


def reference_router(canvas, launch_mode, job_status, pause_worker):
    router=APIRouter(prefix='/workflow/sessions/{identifier}/pk-reference-pilot',tags=['PK reference pilot'])

    def preview_ready(session):
        node=session['nodes']['context']
        return node['execution']=='COMPLETED' and canvas.artifacts_valid(node['artifacts']) and any(a['name']=='main.json' for a in node['artifacts'])

    def source(session,allow_unreviewed=False):
        approved=canvas.dependency_ready(session,'context')
        if not approved and not (allow_unreviewed and preview_ready(session)):
            raise HTTPException(409,'Complete and review Context compression first.')
        # Use reviewed effective scope, including explicit user clarifications.
        node=session['nodes']['adequacy']
        artifact=next((a for a in node['artifacts'] if a['name']=='effective_main.json'),None) if approved and canvas.approved(node) else None
        artifact=artifact or next(a for a in session['nodes']['context']['artifacts'] if a['name']=='main.json')
        if not canvas.artifacts_valid([artifact]): raise HTTPException(409,'The reviewed context changed. Refresh its review before the pilot.')
        return artifact

    def registered(identifier,job_id):
        require_id(identifier);require_id(job_id)
        path=canvas.outputs/'pk_reference_runs'/identifier/(job_id+'.json')
        if not path.is_file(): raise HTTPException(404,'Pilot run not found for this project.')
        return read_json(path)

    def files(record):
        spec=read_json(canvas.state/'workbench_jobs'/record['job_id']/'request.json')
        root=Path(spec['out']).resolve()/'pk_references'
        if not root.is_relative_to(canvas.outputs): raise HTTPException(409,'Invalid pilot output directory.')
        entries={}
        for path in sorted(root.rglob('*')):
            if path.is_file(): entries[path.relative_to(root).as_posix().replace('/','__')]=path
        library=canvas.state/'workbench_jobs'/record['job_id']/'pk_reference_library.json'
        if library.is_file(): entries['library.json']=library
        return entries

    @router.get('')
    def view(identifier:str):
        with canvas.lock:
            session=canvas.load(identifier); setting=session.get('pk_reference_pilot',{})
            approved=canvas.dependency_ready(session,'context')
            can_preview=preview_ready(session) and session.get('control_status')=='READY'
            can_run=(approved or can_preview) and session.get('control_status')=='READY'
            result={'enabled':setting.get('enabled',False),'scope':'Animal-to-human PK only',
                'can_run':can_run,'library':load_library(),'job':None,'files':[],
                'context_review_pending':not approved,'can_preview':can_preview,
                'integration':'When enabled, the next data adequacy run receives independently assessed reference advice. Existing accepted outputs are preserved.'}
            if not setting.get('last_job_id'): return result
            record=registered(identifier,setting['last_job_id']); status=job_status(record['job_id'])
            result['job']=status
            result['source_matches_current']=source(session,record.get('preview_only',False))['sha256']==record['main']['sha256'] if (approved or (can_preview and record.get('preview_only'))) else None
            result['preview_only']=record.get('preview_only',False)
            result['files']=[{'name':name,'bytes':path.stat().st_size,
                'url':f'/ui-api/workflow/sessions/{identifier}/pk-reference-pilot/jobs/{record["job_id"]}/files/{name}'} for name,path in files(record).items()]
            report=files(record).get('review__reference_report.json')
            if report: result['report']=read_json(report)
            revision=files(record).get('revised__main_review.json')
            if revision: result['revision_review']=read_json(revision)
            changes=files(record).get('revised__main_changes.json')
            if changes: result['revision_changes']=read_json(changes)
            result['can_pause']=status['status'] in {'QUEUED','RUNNING'}
            return result

    @router.post('/configuration')
    def configure(identifier:str,options:PilotOptions):
        with canvas.lock:
            s=canvas.load(identifier)
            s.setdefault('pk_reference_pilot',{})['enabled']=options.enabled
            write_json(canvas.path(identifier),s)
        return {'enabled':options.enabled,'rules_activated':False,'existing_results_changed':False}

    @router.get('/model-library')
    def models(identifier:str,drug:str|None=None,species:str|None=None,route:str|None=None,include_related:bool=False,query:str=''):
        from .animal_model_library import search_models
        canvas.load(identifier)
        return search_models(drug,species,route,include_related,query)

    @router.get('/model-library/files/{name}')
    def model_file(identifier:str,name:str):
        from .animal_model_library import DIRECTORY
        canvas.load(identifier)
        if name not in {'animal_models.json','model_library_catalog_expanded.csv','library.json'}:
            raise HTTPException(404,'Library file not found.')
        return FileResponse(DIRECTORY/name,filename=name)

    @router.post('/start',status_code=202)
    def start(identifier:str,options:PilotRunOptions=PilotRunOptions()):
        with canvas.lock:
            s=canvas.load(identifier)
            if s.get('control_status')!='READY': raise HTTPException(409,'Wait for or pause the current workflow before starting the pilot.')
            main=source(s,options.allow_unreviewed_context)
            preview_only=not canvas.dependency_ready(s,'context')
            previous=s.get('pk_reference_pilot',{}).get('last_job_id')
            if previous and job_status(previous)['status'] in {'QUEUED','RUNNING'}:
                raise HTTPException(409,'The reference pilot is already running. Wait for completion or pause it.')
            job=launch_mode({'mode':'pk_reference_pilot','main_ref':main,'reference_library':file_ref(LIBRARY),
                'session_id':identifier,'revise_main':options.revise_main,'preview_only':preview_only,
                'input_review_status':'PENDING_HUMAN_REVIEW' if preview_only else 'REVIEWED'},'pk_reference_pilot')
            write_json(canvas.outputs/'pk_reference_runs'/identifier/(job['id']+'.json'),
                {'job_id':job['id'],'main':main,'created_at':utcnow(),'preview_only':preview_only})
            s.setdefault('pk_reference_pilot',{}).update(last_job_id=job['id'])
            write_json(canvas.path(identifier),s)
            return job

    @router.post('/jobs/{job_id}/pause',status_code=202)
    def pause(identifier:str,job_id:str):
        registered(identifier,job_id)
        return pause_worker(job_id)

    @router.get('/jobs/{job_id}/files/{name}')
    def download(identifier:str,job_id:str,name:str):
        record=registered(identifier,job_id); path=files(record).get(name)
        if path is None: raise HTTPException(404,'Pilot artifact is not available.')
        return FileResponse(path,filename=name)

    return router
