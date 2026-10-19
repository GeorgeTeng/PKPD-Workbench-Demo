"""Scoped animal-PK control API. Scientific execution uses the workflow scheduler."""
from pathlib import Path
from urllib.parse import quote
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, ConfigDict
from .animal_pk import build_plan, blueprint, digest, VERSION
from .adequacy import file_ref, check_ref
from .common import read_json, write_json, require_id, PipelineError, utcnow


class PlanOptions(BaseModel):
    model_config=ConfigDict(extra='forbid')
    three_compartment:dict[str,str]=Field(default_factory=dict)


class WorkflowReviewRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    plan_signature:str
    decision:str
    reviewer:str
    confirmed:bool=False
    rationale:str=''


class AgentRunRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    agent_id:str
    plan_signature:str
    instruction:str=''


class QualificationRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    plan_signature:str
    qualification:dict


class CandidateRunsRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    analysis_id:str
    plan_signature:str
    instruction:str=''


class ModelReviewRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    decision:str
    reviewer:str
    confirmed:bool=False
    selected_candidate_ids:list[str]=Field(default_factory=list)
    selected_candidates:list[str]=Field(default_factory=list)
    comment:str=''
    rationale:str=''
    review_signature:str=''
    report_signature:str=''
    output_signature:str=''
    plan_signature:str=''
    return_to:str='candidate_model'
    requested_changes:str=''
    candidate_ids:list[str]=Field(default_factory=list)


def animal_pk_router(canvas, launch_mode, job_status, pause_worker):
    router=APIRouter(prefix='/workflow',tags=['Animal PK architecture'])
    def source(identifier):
        with canvas.lock:
            s=canvas.load(identifier);dispatch=s['nodes']['dispatch']
            artifact=next((a for a in dispatch.get('artifacts',[]) if a['name']=='pk_context.json'),None)
            if not artifact or not canvas.artifacts_valid([artifact]):
                raise HTTPException(409,'Generate Clinical questions & routing outputs first. The architecture uses its PK context.')
            return artifact,canvas.approved(dispatch)
    def registration(identifier,job_id):
        require_id(identifier);require_id(job_id)
        p=canvas.outputs/'animal_pk_architecture_runs'/identifier/(job_id+'.json')
        if not p.is_file():raise HTTPException(404,'Architecture run not found for this study.')
        return read_json(p)

    def scientific_error(exc, status=409):
        return HTTPException(status, {'code':getattr(exc,'code','PK_CONTROL_INVALID'),
            'message':str(exc),'action':'Review the affected agent inputs or qualification, correct them, then start a new attempt.'})

    def control_plan(identifier, options=None, create=False):
        """A source/options/version key prevents a GET from regenerating plan signatures."""
        require_id(identifier)
        ref,approved=source(identifier)
        base=canvas.outputs/'animal_pk_controls'/identifier
        pointer=base/'active.json'
        if options is None:
            saved=read_json(pointer) if pointer.is_file() else {}
            options=saved.get('options',{}) if saved.get('context_sha256')==ref['sha256'] else {}
        options=PlanOptions(**options).model_dump()
        key=digest({'context':ref['sha256'],'options':options,'version':VERSION})
        folder=base/key[:16]
        plan_path=folder/'plan.json'
        if plan_path.is_file():
            plan=read_json(plan_path)
            if plan.get('plan_signature')!=digest({k:v for k,v in plan.items() if k!='plan_signature'}):
                raise PipelineError('PK_PLAN_CHANGED','The saved PK plan changed. Restore the original plan before running an agent.')
            for artifact in plan['source_refs']:check_ref(artifact)
        elif create:
            plan=build_plan(ref,options)
            write_json(plan_path,plan)
        else:
            raise PipelineError('PK_PLAN_NOT_GENERATED','Enter Animal PK modeling to generate its workflow from the approved routing context.')
        if create:write_json(pointer,{'context_sha256':ref['sha256'],'options':options,'plan_ref':file_ref(plan_path)})
        return plan,folder,approved

    def assert_signature(plan, signature):
        if signature!=plan['plan_signature']:
            raise PipelineError('PK_STALE_PLAN','The PK plan or source data changed. Reload the control panel and review the current inputs before running.')

    def approved_handoff(identifier, plan, folder):
        handoff=canvas.assigned_context(identifier,'pk')
        from .animal_pk_planning import require_workflow_approval
        require_workflow_approval(folder,plan)
        ref,_=source(identifier)
        if ref['sha256']!=plan['context_ref']['sha256']:
            raise PipelineError('PK_STALE_HANDOFF','The approved branch context changed. Reload the current PK plan.')
        # This is dispatch authorization only; model-data qualification requires its own explicit confirmation.
        record={'kind':'APPROVED_DISPATCH_AUTHORIZATION','session_id':identifier,
            'plan_signature':plan['plan_signature'],'context_ref':ref,'handoff':handoff,
            'workflow_review_ref':file_ref(folder/'workflow_planning.json'),
            'fit_qualification':False}
        path=folder/'dispatch_auth'/(digest(record)[:16]+'.json')
        if not path.is_file():write_json(path,record)
        return file_ref(path)

    def run_registration(identifier, job_id):
        require_id(identifier);require_id(job_id)
        path=canvas.outputs/'animal_pk_agent_runs'/identifier/(job_id+'.json')
        if not path.is_file():raise HTTPException(404,'This animal PK agent run does not belong to the selected study.')
        return read_json(path)

    def load_run(record,agent_id=None):
        job=job_status(record['job_id'])
        selected=agent_id or record.get('agent_id')
        value={**record,**job,'id':record['job_id'],'agent_id':selected,'job':job}
        report_path=canvas.outputs/record['job_id']/'animal_pk/report.json'
        if record.get('agent_ids') and selected:
            if selected not in record['agent_ids']:raise PipelineError('PK_UNKNOWN_AGENT','The selected agent is not part of this batch.')
            report_path=canvas.outputs/record['job_id']/'animal_pk/agents'/selected/'report.json'
        if not report_path.is_file() and report_path.with_name('failure.json').is_file():
            report_path=report_path.with_name('failure.json')
        if report_path.is_file():
            value['result']=read_json(report_path);value['result_ref']=file_ref(report_path)
        execution_path=report_path.with_name('execution.json')
        if execution_path.is_file():value['execution']=read_json(execution_path)
        return value

    def current_runs(identifier, plan):
        base=canvas.outputs/'animal_pk_agent_runs'/identifier
        result=[]
        if base.is_dir():
            for path in base.glob('*.json'):
                record=read_json(path)
                if record.get('plan_signature')==plan['plan_signature']:
                    if record.get('agent_ids'):result.extend(load_run(record,agent_id) for agent_id in record['agent_ids'])
                    else:result.append(load_run(record))
        return sorted(result,key=lambda row:(row.get('created_at',''),row['id'],row.get('agent_id','')))

    def selected_request(record, agent_id):
        refs=record.get('request_refs') or {record.get('agent_id'):record['request_ref']}
        for parent_id,reference in refs.items():
            check_ref(reference);request=read_json(reference['path'])
            if not agent_id and len(refs)==1 or agent_id==parent_id:
                return parent_id,reference,None
            for child in request.get('step_contracts',{}).values():
                if child.get('id')==agent_id:return parent_id,reference,child
        if agent_id:raise PipelineError('PK_UNKNOWN_AGENT','This agent is not part of the selected execution attempt.')
        return None,None,None

    def child_invocations(record, parent_id, child):
        """Read only the named child in the hash-bound parent contract, including live attempts."""
        root=canvas.outputs/record['job_id']/'animal_pk'
        if record.get('agent_ids'):root=root/'agents'/parent_id
        role=child['role'];require_id(role)
        folder=root/'agents'/role
        invocations=[]
        if folder.is_dir():
            for invocation in folder.iterdir():
                if not invocation.is_dir():continue
                if not invocation.resolve().is_relative_to(root.resolve()):
                    raise PipelineError('PK_INVALID_AGENT_AUDIT','The child audit folder points outside its execution.')
                files={name:invocation/(name+'.json') for name in ['request','response','execution']}
                if not files['request'].is_file():continue
                request=read_json(files['request'])
                if request.get('payload',{}).get('task',{}).get('id')!=child['id']:
                    raise PipelineError('PK_INVALID_AGENT_AUDIT','The saved invocation belongs to a different child agent.')
                item={'invocation_id':invocation.name,'agent_id':child['id'],'role':role}
                for name,path in files.items():
                    if path.is_file():item[name]=read_json(path);item[name+'_ref']=file_ref(path)
                invocations.append(item)
        return sorted(invocations,key=lambda item:(item.get('execution',{}).get('started_at',''),item['invocation_id']))

    def run_files(identifier, job_id):
        run_registration(identifier,job_id)
        root=(canvas.outputs/job_id).resolve()
        manifest=root/'animal_pk/artifact_manifest.json'
        items=[]
        if manifest.is_file():items=read_json(manifest).get('files',[])
        names=set();safe=[]
        for item in items:
            name=item.get('name','')
            if not name or name in names or '\\' in name or name.startswith('/') or any(part in {'.','..',''} for part in name.split('/')):
                raise PipelineError('PK_INVALID_ARTIFACT_MANIFEST','The agent artifact list contains an invalid or duplicate download name.')
            target=Path(item['path']).resolve()
            if not target.is_relative_to(root):
                raise PipelineError('PK_INVALID_ARTIFACT_PATH','An agent artifact points outside its execution folder.')
            check_ref(item);names.add(name)
            encoded='/'.join(quote(part,safe='') for part in name.split('/'))
            safe.append({**item,'url':f'/ui-api/workflow/sessions/{identifier}/animal-pk/agent-runs/{job_id}/files/{encoded}'})
        return safe

    def latest_review(identifier, plan, folder, runs, species):
        from .animal_pk_control import review_bundle
        from .animal_pk_comparison import begin_review
        known={item['species'] for item in plan['species']}
        if species not in known:raise PipelineError('PK_UNKNOWN_SPECIES','Choose a species in the current PK plan.')
        report=review_bundle(plan,folder,runs,species)
        if not report:
            return {'report':None,'review':None,'eligible_candidates':[], 'can_review':False,
                'blocked_reason':'Complete the candidate fits and comparison agents for this species before human model selection.'},None
        # Current comparison signature is the review boundary: a rerun can never inherit an old approval.
        review_folder=folder/'reviews'/digest(species)[:16]/report['output_signature'][:16]
        if not (review_folder/'review_interrupt.json').is_file():begin_review(report,review_folder,identifier,species)
        review=read_json(review_folder/'review_decision.json') if (review_folder/'review_decision.json').is_file() else None
        eligible=[{'id':row['candidate_id'],'analysis_id':row.get('analysis_id'),'label':row['candidate_id'],
            'comparison_group':row.get('comparison_group'),'AIC':row.get('AIC'),'BIC':row.get('BIC')}
            for row in report['rows'] if row.get('species')==species and row.get('status')=='ELIGIBLE_FOR_WITHIN_GROUP_RANKING']
        return {'report':report,'review':review,'eligible_candidates':eligible,'review_signature':report['output_signature'],
            'report_signature':report['output_signature'],'plan_signature':plan['plan_signature'],
            'can_review':review is None,'blocked_reason':'This review has already been resolved.' if review else ''},review_folder
    @router.get('/animal-pk/blueprint')
    def template():return blueprint()
    @router.get('/sessions/{identifier}/animal-pk/plan')
    def preview(identifier:str):
        try:plan,_,approved=control_plan(identifier)
        except (ValueError,OSError) as exc:raise HTTPException(409,str(exc)) from exc
        return {'plan':plan,'dispatch_approved':approved,'inspection_only':True,'model_release':False}
    @router.post('/sessions/{identifier}/animal-pk/architecture-runs',status_code=202)
    def start(identifier:str,options:PlanOptions):
        ref,approved=source(identifier)
        try:build_plan(ref,options.model_dump())
        except (ValueError,OSError) as exc:raise HTTPException(422,str(exc)) from exc
        job=launch_mode({'mode':'animal_pk_architecture','pk_context':ref,'pk_options':options.model_dump(),
            'session_id':identifier,'inspection_only':True,'dispatch_approved_at_planning':approved},'animal_pk_architecture')
        write_json(canvas.outputs/'animal_pk_architecture_runs'/identifier/(job['id']+'.json'),{'job_id':job['id'],'session_id':identifier})
        return job
    @router.get('/sessions/{identifier}/animal-pk/architecture-runs/{job_id}')
    def status(identifier:str,job_id:str):
        registration(identifier,job_id);current=job_status(job_id)
        manifest=canvas.outputs/job_id/'animal_pk/artifact_manifest.json'
        files=read_json(manifest)['files'] if manifest.is_file() else []
        return {'job':current,'files':[{'name':a['name'],'sha256':a['sha256']} for a in files],
                'scientific_fits':0,'model_release':False}
    @router.post('/sessions/{identifier}/animal-pk/architecture-runs/{job_id}/pause')
    def pause(identifier:str,job_id:str):
        registration(identifier,job_id);return pause_worker(job_id)
    @router.get('/sessions/{identifier}/animal-pk/architecture-runs/{job_id}/files/{name}')
    def artifact(identifier:str,job_id:str,name:str):
        registration(identifier,job_id)
        path=canvas.outputs/job_id/'animal_pk/artifact_manifest.json'
        if not path.is_file():raise HTTPException(409,'Architecture artifacts are not ready yet.')
        item=next((a for a in read_json(path)['files'] if a['name']==name),None)
        if not item or not canvas.artifacts_valid([item]):raise HTTPException(409,'Artifact is missing or changed; inspect the execution log.')
        return FileResponse(item['path'],filename=name)

    def control_value(identifier,options=None):
        from .animal_pk_control import control_snapshot
        from .animal_pk_planning import planning_state,initialize_draft
        with canvas.lock:
            plan,folder,approved=control_plan(identifier,options,create=options is not None)
            if options is not None:initialize_draft(folder,plan,identifier,canvas.graph_reviews)
            planning=planning_state(folder,plan)
            runs=current_runs(identifier,plan)
            snapshot=control_snapshot(plan,folder,runs)
            blocked_reason=None
            if not approved:blocked_reason='Approve the Clinical questions & routing handoff before scientific execution.'
            elif not planning['approved']:blocked_reason='Review and approve the generated PK workflow before running its agents.'
            else:
                try:canvas.assigned_context(identifier,'pk')
                except HTTPException as exc:
                    blocked_reason=exc.detail.get('message',str(exc.detail)) if isinstance(exc.detail,dict) else str(exc.detail)
            if blocked_reason:
                for state in snapshot.get('agent_states',{}).values():
                    state.update(can_run=False,blocked_reason=blocked_reason)
            snapshot.setdefault('capabilities',{})['scientific_run_authorized']=blocked_reason is None
            return {'plan':plan,'planning':planning,'dispatch_approved':approved,'runs':runs,**snapshot}

    @router.post('/sessions/{identifier}/animal-pk/planning/enter')
    def enter_planning(identifier:str):
        from .animal_pk_planning import initialize_draft
        try:
            with canvas.lock:
                ref,approved=source(identifier)
                if not approved:raise PipelineError('PK_ROUTING_REVIEW_REQUIRED','Approve Clinical questions & routing before generating the Animal PK workflow.')
                canvas.assigned_context(identifier,'pk')
                plan,folder,_=control_plan(identifier,create=True)
                initialize_draft(folder,plan,identifier,canvas.graph_reviews)
                return control_value(identifier)
        except (ValueError,OSError,KeyError) as exc:raise scientific_error(exc) from exc

    @router.post('/sessions/{identifier}/animal-pk/planning/review')
    def workflow_review(identifier:str,request:WorkflowReviewRequest):
        from .animal_pk_planning import review_draft
        try:
            with canvas.lock:
                plan,folder,approved=control_plan(identifier)
                if not approved:raise PipelineError('PK_ROUTING_REVIEW_REQUIRED','Routing approval is required.')
                canvas.assigned_context(identifier,'pk');assert_signature(plan,request.plan_signature)
                if any(r.get('status') in {'QUEUED','RUNNING'} for r in current_runs(identifier,plan)):
                    raise PipelineError('PK_ACTIVE_AGENT','Pause or finish the active agent before revising workflow approval.')
                decision=request.model_dump();decision['output_signature']=decision.pop('plan_signature')
                review_draft(folder,plan,decision,canvas.graph_reviews)
                return control_value(identifier)
        except (ValueError,OSError,KeyError) as exc:raise scientific_error(exc) from exc

    @router.get('/sessions/{identifier}/animal-pk/planning/files/{name}')
    def planning_file(identifier:str,name:str):
        if name not in {'plan.json','planning_agent_contract.json','planning_report.json','workflow_planning.json','animal_pk_context.json','rule_audit.json'}:
            raise HTTPException(404,'Planning artifact not found.')
        try:
            plan,folder,_=control_plan(identifier)
            from .animal_pk_planning import planning_state
            planning_state(folder,plan)
            if not (folder/name).is_file():raise HTTPException(404,'Planning artifact has not been generated.')
            return FileResponse(folder/name,filename=name)
        except (ValueError,OSError,KeyError) as exc:raise scientific_error(exc) from exc

    @router.get('/sessions/{identifier}/animal-pk/control')
    def control(identifier:str):
        try:return control_value(identifier)
        except (ValueError,OSError,KeyError) as exc:raise scientific_error(exc) from exc

    @router.post('/sessions/{identifier}/animal-pk/control/plan')
    def change_plan(identifier:str,options:PlanOptions):
        try:
            with canvas.lock:
                current,_,_=control_plan(identifier)
                if any(run.get('status') in {'QUEUED','RUNNING'} for run in current_runs(identifier,current)):
                    raise PipelineError('PK_ACTIVE_AGENT','Pause or finish the active agent before changing model candidates.')
                return control_value(identifier,options.model_dump())
        except (ValueError,OSError,KeyError) as exc:raise scientific_error(exc) from exc

    @router.post('/sessions/{identifier}/animal-pk/agent-runs',status_code=202)
    def start_agent(identifier:str,request:AgentRunRequest):
        from .animal_pk_control import make_agent_request
        try:
            with canvas.lock:
                plan,folder,_=control_plan(identifier)
                assert_signature(plan,request.plan_signature)
                approval=approved_handoff(identifier,plan,folder)
                runs=current_runs(identifier,plan)
                if any(run.get('status') in {'QUEUED','RUNNING'} for run in runs):
                    raise PipelineError('PK_ACTIVE_AGENT','An animal PK agent is still active. Wait for it to finish or pause it before starting another attempt.')
                agent_request=make_agent_request(plan,request.agent_id,folder,request.instruction,runs,approval)
                check_ref(agent_request)
                job=launch_mode({'mode':'animal_pk_execution','pk_plan':file_ref(folder/'plan.json'),
                    'agent_request':agent_request,'session_id':identifier},'animal_pk_execution')
                record={'job_id':job['id'],'agent_id':request.agent_id,'session_id':identifier,
                    'plan_signature':plan['plan_signature'],'created_at':job.get('created_at',utcnow()),
                    'request_ref':agent_request,'approval_ref':approval}
                write_json(canvas.outputs/'animal_pk_agent_runs'/identifier/(job['id']+'.json'),record)
                return {**job,'agent_id':request.agent_id,'plan_signature':plan['plan_signature']}
        except (ValueError,OSError,KeyError) as exc:raise scientific_error(exc) from exc

    @router.post('/sessions/{identifier}/animal-pk/candidate-runs',status_code=202)
    def start_candidates(identifier:str,request:CandidateRunsRequest):
        from .animal_pk_control import make_agent_request
        try:
            with canvas.lock:
                plan,folder,_=control_plan(identifier)
                assert_signature(plan,request.plan_signature)
                approval=approved_handoff(identifier,plan,folder)
                runs=current_runs(identifier,plan)
                if any(run.get('status') in {'QUEUED','RUNNING'} for run in runs):
                    raise PipelineError('PK_ACTIVE_AGENT','An animal PK agent is still active. Wait or pause it before starting the parallel candidates.')
                unit=next((item for item in plan['analysis_units'] if item['analysis_id']==request.analysis_id),None)
                if unit is None:raise PipelineError('PK_UNKNOWN_ANALYSIS','Choose an analysis unit in the current PK plan.')
                agent_ids=[candidate['model_agent'] for candidate in unit['candidates']]
                requests=[make_agent_request(plan,agent_id,folder,request.instruction,runs,approval) for agent_id in agent_ids]
                for ref in requests:check_ref(ref)
                job=launch_mode({'mode':'animal_pk_execution','pk_plan':file_ref(folder/'plan.json'),
                    'agent_requests':requests,'session_id':identifier},'animal_pk_execution')
                record={'job_id':job['id'],'agent_ids':agent_ids,'analysis_id':request.analysis_id,'session_id':identifier,
                    'plan_signature':plan['plan_signature'],'created_at':job.get('created_at',utcnow()),
                    'request_refs':dict(zip(agent_ids,requests)),'approval_ref':approval}
                write_json(canvas.outputs/'animal_pk_agent_runs'/identifier/(job['id']+'.json'),record)
                return {**job,'agent_ids':agent_ids,'plan_signature':plan['plan_signature']}
        except (ValueError,OSError,KeyError) as exc:raise scientific_error(exc) from exc

    @router.get('/sessions/{identifier}/animal-pk/agent-runs/{job_id}')
    def agent_status(identifier:str,job_id:str,agent_id:str|None=None):
        try:
            record=run_registration(identifier,job_id)
            selected,selected_ref,child=selected_request(record,agent_id)
            value=load_run(record,selected)
            refs=record.get('request_refs',{})
            ref=selected_ref
            if ref:check_ref(ref)
            else:
                for item in refs.values():check_ref(item)
            result=value.get('result') or {}
            response=result.get('response');execution=result.get('execution') or value.get('execution')
            for key in ['response','execution']:
                output_ref=result.get(key+'_ref')
                if output_ref:
                    check_ref(output_ref)
                    if key=='response':response=read_json(output_ref['path'])
                    else:execution=read_json(output_ref['path'])
            files=run_files(identifier,job_id)
            details={'job':value['job'],'request':read_json(ref['path']) if ref else {key:read_json(item['path']) for key,item in refs.items()},
                'response':response,'execution':execution,'result':value.get('result'),
                'files':[{'name':item['name'],'url':item['url'],'sha256':item['sha256']} for item in files]}
            if child:
                invocations=child_invocations(record,selected,child)
                details.update(agent_id=child['id'],managed_by=selected,agent_invocations=invocations,
                    request=invocations[-1]['request'] if invocations else {'agent':child,'status':'NOT_INVOKED'},
                    response=invocations[-1].get('response') if invocations else None,
                    execution=invocations[-1].get('execution') if invocations else {'status':'NOT_INVOKED'})
            return details
        except (ValueError,OSError,KeyError) as exc:raise scientific_error(exc) from exc

    @router.post('/sessions/{identifier}/animal-pk/agent-runs/{job_id}/pause')
    def pause_agent(identifier:str,job_id:str):
        run_registration(identifier,job_id)
        return pause_worker(job_id)

    @router.get('/sessions/{identifier}/animal-pk/agent-runs/{job_id}/files/{name:path}')
    def agent_artifact(identifier:str,job_id:str,name:str):
        try:
            item=next((item for item in run_files(identifier,job_id) if item['name']==name),None)
            if not item:raise HTTPException(404,'The requested file is not in this agent run artifact manifest.')
            return FileResponse(item['path'],filename=name)
        except (ValueError,OSError,KeyError) as exc:raise scientific_error(exc) from exc

    @router.get('/sessions/{identifier}/animal-pk/qualifications/{candidate_id}')
    def qualification(identifier:str,candidate_id:str):
        from .animal_pk_control import qualification_template
        try:
            with canvas.lock:
                plan,folder,_=control_plan(identifier)
                template=qualification_template(plan,candidate_id)
                require_id(candidate_id)
                pointer=folder/'qualifications'/candidate_id/'current.json'
                saved=read_json(pointer) if pointer.is_file() else {}
                ref=saved.get('qualification_ref',saved if 'path' in saved else None)
                envelope=saved.get('qualification')
                if ref:check_ref(ref);envelope=read_json(ref['path'])
                return {'plan_signature':plan['plan_signature'],'template':template,
                    'qualification':envelope,'qualification_ref':ref,'validation':saved.get('validation')}
        except (ValueError,OSError,KeyError) as exc:raise scientific_error(exc) from exc

    @router.put('/sessions/{identifier}/animal-pk/qualifications/{candidate_id}')
    def put_qualification(identifier:str,candidate_id:str,request:QualificationRequest):
        from .animal_pk_control import save_qualification
        try:
            with canvas.lock:
                plan,folder,_=control_plan(identifier)
                assert_signature(plan,request.plan_signature)
                approval=approved_handoff(identifier,plan,folder)
                runs=current_runs(identifier,plan)
                if any(run.get('status') in {'QUEUED','RUNNING'} for run in runs):
                    raise PipelineError('PK_ACTIVE_AGENT','Pause or finish the active agent before changing its fit qualification.')
                return save_qualification(plan,candidate_id,request.qualification,folder,approval)
        except (ValueError,OSError,KeyError) as exc:raise scientific_error(exc,422) from exc

    @router.get('/sessions/{identifier}/animal-pk/reviews')
    def model_reviews(identifier:str,species:str):
        try:
            with canvas.lock:
                plan,folder,_=control_plan(identifier)
                value,_=latest_review(identifier,plan,folder,current_runs(identifier,plan),species)
                return value
        except (ValueError,OSError,KeyError) as exc:raise scientific_error(exc) from exc

    @router.post('/sessions/{identifier}/animal-pk/reviews/{species}')
    def submit_model_review(identifier:str,species:str,request:ModelReviewRequest):
        from .animal_pk_comparison import finish_review
        try:
            with canvas.lock:
                plan,folder,_=control_plan(identifier)
                if request.plan_signature:assert_signature(plan,request.plan_signature)
                approved_handoff(identifier,plan,folder)
                runs=current_runs(identifier,plan)
                if any(run.get('status') in {'QUEUED','RUNNING'} for run in runs):
                    raise PipelineError('PK_ACTIVE_AGENT','Complete or pause active PK execution before reviewing the current results.')
                value,review_folder=latest_review(identifier,plan,folder,runs,species)
                if not value['can_review']:raise PipelineError('PK_REVIEW_UNAVAILABLE',value['blocked_reason'])
                signatures=[signature for signature in [request.review_signature,request.report_signature,request.output_signature] if signature]
                if not signatures or any(signature!=value['review_signature'] for signature in signatures):
                    raise PipelineError('PK_STALE_REVIEW','The comparison changed. Reload and review the current results before confirming a selection.')
                decision={'decision':request.decision,'reviewer':request.reviewer,'confirmed':request.confirmed,
                    'selected_candidates':request.selected_candidate_ids or request.selected_candidates,
                    'rationale':request.comment or request.rationale,'output_signature':value['review_signature'],
                    'return_to':request.return_to,'requested_changes':request.requested_changes or request.comment,
                    'candidate_ids':request.candidate_ids}
                return finish_review(review_folder,decision)
        except (ValueError,OSError,KeyError) as exc:raise scientific_error(exc,422) from exc
    from .animal_pk_analysis_api import analysis_router
    router.include_router(analysis_router(canvas,source,run_files,launch_mode,job_status,pause_worker))
    return router
