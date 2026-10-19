"""Explicitly approved exploratory mean-curve PK; no NLME subject fabrication."""
import csv
import math
import os
import shutil
from pathlib import Path

from .adequacy import check_ref, file_ref
from .common import PROJECT, PipelineError, read_json, write_json, utcnow
from .engine import rscript_path
from .animal_pk import RESPONSE_SCHEMA
from .animal_pk_agents import invoke_agent


def validate_summary_request(reference):
    check_ref(reference); request=read_json(reference['path'])
    check_ref(request['approval_ref']); approval=read_json(request['approval_ref']['path'])
    if approval.get('status')!='APPROVED' or approval.get('scope')!='EXPLORATORY_MOUSE_MEAN_CURVES':
        raise PipelineError('SUMMARY_PREFIT_REVIEW_REQUIRED','Explicit pre-fit review of exploratory mouse mean curves is required.')
    if approval.get('preflight_ref')!=request.get('preflight_ref'):
        raise PipelineError('SUMMARY_APPROVAL_SCOPE','Pre-fit approval belongs to another analysis plan.')
    check_ref(request['preflight_ref'])
    if request.get('species')!='mouse' or request.get('random_effects') is not False:
        raise PipelineError('SUMMARY_SCOPE','This adapter only supports the approved mouse mean-curve scope, without random effects.')
    for ref in request['source_refs']:check_ref(ref)
    return request


def contract(request, role):
    return {'id':request['analysis_id']+'_'+str(request.get('compartments','comparison'))+'_'+role,
        'role':role,'scope':{'species':'mouse','analysis_id':request['analysis_id']},
        'instructions':'Review the computed exploratory mean-curve PK results. Do not generate, modify or replace numeric estimates. '
            'Check convergence, finite uncertainty, boundary estimates, fit residuals and limitations. '
            'No animal random effects, independent animal validation or human translation is established. '
            'Return concerns for human review; never accept a final model. Source references are provenance, not permission to browse benchmark results.',
        'context':{'observation_unit':request.get('observation_unit'),'assumptions':request.get('assumptions',[]),
            'drug':request['drug'],'estimator':'R nonlinear least squares with explicit Gaussian/lognormal likelihood'},
        'rule_snapshot':request['rules'],'response_schema':RESPONSE_SCHEMA,
        'session_policy':'FRESH_CALL_NO_CONVERSATION_REUSE','fit_release':False}


def execute_candidate(reference, output, generator=None):
    from .job_control import run_interruptible
    request=validate_summary_request(reference);out=Path(output);out.mkdir(parents=True,exist_ok=True)
    write_json(out/'input.json',request)
    source_script=PROJECT/'pkpd_r/scripts/fit_summary_pk.R'
    script=out/'fit_summary_pk.R'
    shutil.copyfile(source_script,script)
    source_code_ref=file_ref(source_script)
    # These computations are independent, small R processes; avoid nested BLAS threads.
    for key in ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS']:os.environ[key]='1'
    os.environ['R_LIBS_USER']='C:/Users/georg/Documents/Codex/ScienceEnv/R-library'
    started=utcnow()
    command=[rscript_path(),'--vanilla',str(script),str(out/'input.json'),str(out/'numerical')]
    with (out/'R.log').open('w',encoding='utf-8') as log:
        code=run_interruptible(command,pause_file=request['pause_file'],stdout=log,cwd=PROJECT,
            process_record=out/'R_process.json')
    execution={'started_at':started,'finished_at':utcnow(),'command':command,'return_code':code,
        'code_ref':file_ref(script),'source_code_ref':source_code_ref,
        'input_ref':file_ref(out/'input.json'),'model_release':False}
    write_json(out/'numerical_execution.json',execution)
    if code:
        raise PipelineError('SUMMARY_R_FAILED','Exploratory R fit failed. Inspect '+str(out/'R.log'))
    numeric=read_json(out/'numerical/numerical_results.json')
    # Each compartment candidate has its own fresh reasoning call after trusted R computation.
    review=invoke_agent(contract(request,'candidate_diagnostics'),{'numerical_results':numeric},out/'agent',generator)
    report={'status':'EXPLORATORY_RESULTS_PENDING_HUMAN_REVIEW','analysis_id':request['analysis_id'],
        'compartments':request['compartments'],'numerical_ref':file_ref(out/'numerical/numerical_results.json'),
        'execution_ref':file_ref(out/'numerical_execution.json'),'agent_review':review,
        'llm_calls':1,'fit_calls':2,'model_release':False,'human_prediction_validated':False}
    write_json(out/'report.json',report)
    return report


def assemble(master_ref, folders, output, generator=None):
    master=validate_summary_request(master_ref);out=Path(output);out.mkdir(parents=True,exist_ok=True)
    rows=[];reports=[]
    for folder in folders:
        p=Path(folder);r=read_json(p/'report.json');check_ref(r['numerical_ref'])
        data=read_json(r['numerical_ref']['path']);reports.append(file_ref(p/'report.json'))
        for row in data['rows']:
            rows.append({**row,'result_folder':str((p/'numerical'/row.get('error_model','')).resolve())})
    groups={r['analysis_id'] for r in rows if r.get('analysis_id')}
    recommendations=[]
    for group in sorted(groups):
        fitted=[r for r in rows if r.get('analysis_id')==group and r.get('converged') and isinstance(r.get('AIC'),(float,int))]
        eligible=[r for r in fitted if r.get('numerically_eligible')]
        for row in fitted:
            row['delta_AIC_all_converged']=row['AIC']-min(r['AIC'] for r in fitted)
            row['delta_BIC_all_converged']=row['BIC']-min(r['BIC'] for r in fitted)
            row['delta_AIC_eligible']=row['AIC']-min(r['AIC'] for r in eligible) if row in eligible else None
            row['delta_BIC_eligible']=row['BIC']-min(r['BIC'] for r in eligible) if row in eligible else None
            row['Akaike_weight_eligible']=(math.exp(-.5*row['delta_AIC_eligible'])/sum(math.exp(-.5*(r['AIC']-min(e['AIC'] for e in eligible))) for r in eligible)) if row in eligible else None
        recommendations.append({'analysis_id':group,'lowest_AIC_numerically_eligible':min(eligible,key=lambda r:r['AIC'])['candidate_id'] if eligible else None,
            'lowest_BIC_numerically_eligible':min(eligible,key=lambda r:r['BIC'])['candidate_id'] if eligible else None,
            'AIC_within_2':[r['candidate_id'] for r in eligible if r['delta_AIC_eligible']<2],
            'scientific_selection':'PENDING_HUMAN_REVIEW','basis':'Numerical screening only; local uncertainty excludes biological/digitization uncertainty.'})
    write_json(out/'comparison.json',{'rows':rows,'recommendations':recommendations,'model_release':False})
    columns=['analysis_id','candidate_id','compartments','error_model','n_observations','n_parameters','logLik','minus2logLik',
        'AIC','AICc','BIC','delta_AIC_all_converged','delta_AIC_eligible','delta_BIC_eligible','Akaike_weight_eligible',
        'R2_raw','R2_log','RMSE_raw','RMSE_log','MAE_raw','converged','converged_starts','attempted_starts',
        'max_RSE_percent','max_parameter_correlation','covariance_condition','parameter_at_bound','numerically_eligible','status']
    with (out/'comparison.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,columns,extrasaction='ignore');writer.writeheader();writer.writerows(rows)
    agent_request={**master,'analysis_id':'MOUSE_STUDY_COMPARISON','observation_unit':'Separate study-level observation sets'}
    review=invoke_agent(contract(agent_request,'comparison'),{'comparison':{'rows':rows,'recommendations':recommendations}},out/'comparison_agent',generator)
    report={'status':'EXPLORATORY_RESULTS_PENDING_HUMAN_REVIEW','species':'mouse','candidate_count':len(rows),
        'llm_calls':len(folders)+1,'fit_calls':len(rows),'candidate_reports':reports,
        'comparison_ref':file_ref(out/'comparison.json'),'comparison_agent':review,
        'model_release':False,'human_prediction_validated':False,
        'limitations':['No animal random effects or verified individual-animal cross-validation.',
            'AIC/BIC compare only the identical observed mean set within each study, never between studies.',
            'Extravascular parameters are apparent and conditional on absorption and reported dose scale.',
            'Human pre-fit authorization is not acceptance of any resulting scientific model.']}
    write_json(out/'report.json',report)
    lines=['# Exploratory mouse PK results','','Status: pending human model review.','',
        '| Study | Candidate | AIC | AICc | BIC | R2 (raw) | Numerical screen |',
        '|---|---|---:|---:|---:|---:|---|']
    def num(x):return f'{x:.3f}' if isinstance(x,(float,int)) else 'NA'
    for row in rows:
        lines.append('| '+' | '.join([str(row.get('analysis_id','')),row['candidate_id'],*[num(row.get(k)) for k in ['AIC','AICc','BIC','R2_raw']],
            'Eligible for review' if row.get('numerically_eligible') else 'Concerns / failed'])+' |')
    lines+=['','## Interpretation','','Both likelihoods include constants and the lognormal Jacobian. One residual-variance parameter is counted. '
        'R2 is descriptive. Lower AIC alone does not qualify a translational model.','',review['response']['summary'],'',
        '## Limitations','']+['- '+x for x in report['limitations']]
    lines+=['','## Files','','- [Full comparison and parameters](comparison.json)','- [Comparison CSV](comparison.csv)',
        '- [Execution and review references](report.json)']
    (out/'README.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    files=[{'name':p.name,**file_ref(p),'kind':'result'} for p in out.iterdir() if p.is_file()]
    write_json(out/'artifact_manifest.json',{'files':files})
    return report
