"""Species-scoped access to explicitly authorized PK batches and review publications."""
from pathlib import Path
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict
from .common import read_json, write_json, require_id, utcnow, PipelineError
from .adequacy import check_ref
from .animal_pk import digest

class RerunAnalysis(BaseModel):
    model_config=ConfigDict(extra='forbid')
    request_signature:str

def analysis_router(canvas, source, run_files, launch_mode, job_status, pause_worker):
    router=APIRouter()
    prefix='/sessions/{identifier}/animal-pk/analysis-runs'
    active={'QUEUED','RUNNING','STARTING','PAUSING','PAUSE_REQUESTED'}

    def registration(identifier,run_id):
        require_id(identifier);require_id(run_id)
        p=canvas.outputs/'animal_pk_agent_runs'/identifier/(run_id+'.json')
        if not p.is_file():raise HTTPException(404,'This analysis does not belong to the selected study.')
        value=read_json(p)
        if value.get('interface')!='species_analysis' or value.get('session_id')!=identifier or value.get('job_id')!=run_id:
            raise HTTPException(404,'This run is not registered as a species analysis.')
        return value

    def records(identifier):
        require_id(identifier);canvas.load(identifier)
        folder=canvas.outputs/'animal_pk_agent_runs'/identifier
        return [registration(identifier,p.stem) for p in folder.glob('*.json') if read_json(p).get('interface')=='species_analysis']

    def template(identifier,record):
        spec=record['rerun'];mode=spec['mode']
        if mode=='animal_pk_summary':
            from .animal_pk_summary import validate_summary_request as validate
            key='summary_request';children='groups';expected='mouse'
        elif mode=='animal_pk_individual':
            from .animal_pk_individual import validate_request as validate
            key='individual_request';children='candidates';expected='rat'
        else:raise PipelineError('PK_ANALYSIS_MODE','This registered analysis has no supported execution adapter.')
        if record['species']!=expected:raise PipelineError('PK_ANALYSIS_SPECIES','Registered species and execution adapter disagree.')
        context,approved=source(identifier)
        check_ref(record['context_ref'])
        if not approved or context['sha256']!=record['context_ref']['sha256']:
            raise PipelineError('PK_ANALYSIS_STALE_CONTEXT','The routed PK context changed or is not approved. Requalify this analysis before rerunning.')
        master=validate(spec['request_ref'])
        if not any(ref['sha256']==context['sha256'] for ref in master['source_refs']):
            raise PipelineError('PK_ANALYSIS_CONTEXT','The reviewed request is not bound to this routed PK context.')
        for ref in master[children]:validate(ref)
        return {key:spec['request_ref'],'mode':mode},digest({'rerun':spec,'context':record['context_ref']})

    def view(identifier,record,detail=False):
        run_id=record['job_id'];is_publication=record.get('mode')=='PK_REVIEW_PUBLICATION'
        job=None if is_publication else job_status(run_id)
        files=run_files(identifier,run_id)
        by_name={f['name']:f for f in files}
        def artifact(name):return read_json(by_name[name]['path']) if name in by_name else None
        comparison=artifact('comparison.json');report=artifact('report.json') or {}
        rows=(comparison or {}).get('rows',[])
        if any(r.get('species',record['species'])!=record['species'] for r in rows):
            raise PipelineError('PK_ANALYSIS_SPECIES','Result rows contain another species; inspect the registration.')
        blocked=None;signature=None
        try:_,signature=template(identifier,record)
        except (ValueError,OSError,KeyError,HTTPException) as exc:blocked=str(getattr(exc,'detail',exc))
        status=job['status'] if job else 'NEEDS_HUMAN_SCIENTIFIC_REVIEW'
        value={'id':run_id,'species':record['species'],'title':record['title'],'description':record.get('description',''),
            'created_at':record.get('created_at'),'status':status,'job':{k:v for k,v in (job or {}).items() if k in
                {'status','stage','started_at','finished_at','error','failure','blocks','fit_calls','llm_calls','model_progress'}},
            'publication_only':is_publication,'source_job_ids':record.get('source_job_ids',[run_id]),
            'candidate_count':len(rows) or report.get('candidate_count'),
            'fit_calls':report.get('fit_calls',report.get('verification',{}).get('completed_R_fits')),
            'model_release':False,'can_run':not blocked and status not in active,'blocked_reason':blocked,
            'can_pause':not is_publication and status in active,'request_signature':signature,
            'report_url':f'/ui-api/workflow/sessions/{identifier}/animal-pk/analysis-runs/{run_id}/report' if 'review.html' in by_name else None}
        if detail:value.update(comparison=comparison,report=report,review_summary=artifact('human_review_summary.json'),
            files=[{k:f[k] for k in ('name','url','sha256')} for f in files],
            execution_request=read_json(record['rerun']['request_ref']['path']) if signature else None)
        return value

    def error(exc):return HTTPException(409,{'code':getattr(exc,'code','PK_ANALYSIS_UNAVAILABLE'),'message':str(exc),
        'action':'Inspect the registered request and source files. Existing results are preserved; do not bypass scientific review.'})

    @router.get(prefix)
    def analyses(identifier:str):
        values=[]
        for record in records(identifier):
            try:values.append(view(identifier,record))
            except (ValueError,OSError,KeyError) as exc:
                values.append({'id':record['job_id'],'species':record['species'],'title':record['title'],
                    'status':'ARTIFACT_CHECK_FAILED','can_run':False,'can_pause':False,'blocked_reason':str(exc),'model_release':False})
        return {'analyses':sorted(values,key=lambda v:v.get('created_at') or '',reverse=True)}

    @router.get(prefix+'/{run_id}')
    def analysis(identifier:str,run_id:str):
        try:return view(identifier,registration(identifier,run_id),True)
        except (ValueError,OSError,KeyError) as exc:raise error(exc) from exc

    @router.get(prefix+'/{run_id}/report')
    def report_page(identifier:str,run_id:str):
        registration(identifier,run_id)
        try:
            item=next((f for f in run_files(identifier,run_id) if f['name']=='review.html'),None)
            if not item:raise HTTPException(404,'This run has no compiled report yet. Inspect its results and figures instead.')
            return FileResponse(item['path'],media_type='text/html')
        except (ValueError,OSError,KeyError) as exc:raise error(exc) from exc

    @router.post(prefix+'/{run_id}/rerun',status_code=202)
    def rerun(identifier:str,run_id:str,request:RerunAnalysis):
        try:
            with canvas.lock:
                record=registration(identifier,run_id);mode,signature=template(identifier,record)
                if signature!=request.request_signature:raise PipelineError('PK_ANALYSIS_CHANGED','The registered request changed. Refresh and inspect it before running.')
                canvas.assigned_context(identifier,'pk')
                for other in records(identifier):
                    if other.get('mode')!='PK_REVIEW_PUBLICATION' and job_status(other['job_id'])['status'] in active:
                        raise PipelineError('PK_ANALYSIS_ACTIVE','An animal PK analysis is already running. Pause it or wait for completion.')
                job=launch_mode({**mode,'session_id':identifier,'retry_of':run_id},mode['mode'])
                new={**record,'job_id':job['id'],'mode':mode['mode'],'request_ref':record['rerun']['request_ref'],
                    'created_at':job['created_at'],'parent_analysis_id':run_id,'source_job_ids':[job['id']]}
                write_json(canvas.outputs/'animal_pk_agent_runs'/identifier/(job['id']+'.json'),new)
                return {'id':job['id'],'status':job['status'],'model_release':False}
        except (ValueError,OSError,KeyError) as exc:raise error(exc) from exc

    @router.post(prefix+'/{run_id}/pause')
    def pause(identifier:str,run_id:str):
        record=registration(identifier,run_id)
        if record.get('mode')=='PK_REVIEW_PUBLICATION':raise HTTPException(409,'This is a completed review publication, not a running job.')
        return pause_worker(run_id)
    return router
