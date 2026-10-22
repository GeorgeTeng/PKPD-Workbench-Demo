"""Exploratory individual PK batch: trusted nlmixr2 fits and fresh scoped reviews."""
import csv
import copy
import math
from pathlib import Path
from .common import read_json,write_json,PipelineError
from .adequacy import check_ref,file_ref
from .animal_pk import RESPONSE_SCHEMA
from .animal_pk_agents import invoke_agent
from .animal_pk_nlmixr2 import validate_qualification,fit_adapter


def max_available_rse(parameters):
    """Missing uncertainty is unknown, never zero precision error."""
    values=[p.get('delta_method_RSE_percent') for p in parameters]
    values=[v for v in values if isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v)]
    return max(values) if values else None


def validate_request(reference):
    check_ref(reference);request=read_json(reference['path'])
    for ref in request['source_refs']:check_ref(ref)
    check_ref(request['approval_ref']);approval=read_json(request['approval_ref']['path'])
    if approval.get('status')!='APPROVED' or approval.get('scope')!='EXPLORATORY_RAT_INDIVIDUAL_PK':
        raise PipelineError('RAT_SCOPE','The exploratory rat PK request requires its own user authorization.')
    if request.get('species')!='rat' or request.get('rule_scope',{}).get('unresolved'):
        raise PipelineError('RAT_SCOPE','Resolve species and assigned rule scope before execution.')
    return request


def review_contract(request,role):
    return {'id':request['id']+'_'+role,'role':role,'scope':{'species':'rat','analysis_id':request['analysis_id']},
        'instructions':'Review the trusted nlmixr2 numerical results for exploratory rat IV PK. Never change computed estimates. '
          'The user requested rat fitting; this authorizes exploratory execution, not scientific acceptance. '
          'Data are 11 cannulated rats; quantified-only analysis retains 2 BLQ records with unknown LLOQ outside the likelihood. '
          'Assess numerical convergence, parameter identifiability, residuals and the catalog criterion. '
          'FOCEI AIC/BIC are approximate engine metrics. AICc based on observations is descriptive only for this nonlinear mixed-effects model. '
          'Do not claim predictive validation or release human scaling. Report limitations and concrete human-review actions.',
        'context':{'drug':request['drug'],'observation_unit':'Repeated observations within rat',
          'qualification':request['qualification_notes'],'authorization':read_json(request['approval_ref']['path']),
          'catalog':request['catalog_rows'],'parameter_basis':'PER_KG','human_prediction_validated':False},
        'rule_snapshot':request['rules'],'response_schema':RESPONSE_SCHEMA,'fit_release':False,
        'session_policy':'FRESH_CALL_NO_CONVERSATION_REUSE'}


def execute_candidate(reference,output):
    request=validate_request(reference);out=Path(output);out.mkdir(parents=True,exist_ok=True)
    attempts=[]
    proposal=file_ref(write_json(out/'numerical_authorization.json',{'decision':'CONTINUE',
        'source':'TRUSTED_HOST_CONFIGURATION_UNDER_USER_EXPLORATORY_AUTHORIZATION',
        'approval_ref':request['approval_ref'],'scientific_acceptance':False}))
    for i,config in enumerate(request['configurations'],1):
        qualification=copy.deepcopy(request['qualification']);qualification['fit_config']=config
        validate_qualification(qualification)
        # An engineering failure stops this workflow; numerical concerns in a returned fit remain reviewable.
        result=fit_adapter(qualification,proposal,out/'attempts'/str(i))
        attempts.append({'attempt':i,'fit_result_ref':file_ref(out/'attempts'/str(i)/'fit_result.json'),
                         'result':result})
    converged=[a for a in attempts if a['result'].get('converged') and isinstance(a['result'].get('log_likelihood'),(int,float))]
    usable=converged or [a for a in attempts if isinstance(a['result'].get('log_likelihood'),(int,float))]
    if not usable:raise PipelineError('RAT_NO_OBJECTIVE','No attempt returned a finite likelihood; inspect engine logs.')
    best=max(usable,key=lambda a:a['result']['log_likelihood'])
    fit=best['result'];raw=read_json(fit['raw_result_ref']['path'])
    eligible=fit['numerical_eligibility'] and raw.get('finite_structural_intervals') and not raw.get('parameter_at_bound')
    reasons=[]
    diagnostics=read_json(fit['diagnostics_ref']['path'])
    reasons+=diagnostics['failed_checks']
    if not raw.get('finite_structural_intervals'):reasons.append('Nonfinite structural uncertainty')
    if raw.get('parameter_at_bound'):reasons.append('Structural parameter at numerical bound')
    corr=raw.get('max_structural_parameter_correlation')
    if request['compartments']==2 and isinstance(corr,(float,int)) and corr>.95:
        eligible=False;reasons.append('Current model catalog: structural parameter correlation above 0.95 (project criterion, not universal).')
    n,k=fit['n_observations'],fit['n_parameters'];aic=fit['engine_metrics']['AIC']
    row={'candidate_id':request['id'],'analysis_id':request['analysis_id'],'species':'rat',
         'compartments':request['compartments'],'error_model':request['error_model'],
         'n_subjects':fit['n_subjects'],'n_observations':n,'n_parameters':k,
         'logLik':fit['log_likelihood'],'minus2logLik':-2*fit['log_likelihood'],
         'AIC':aic,'BIC':fit['engine_metrics']['BIC'],
         'AICc_observation_heuristic':aic+2*k*(k+1)/(n-k-1) if n>k+1 else None,
         'metrics_interpretation':'Approximate FOCEI likelihood; n-based AICc is descriptive, not a validated mixed-model correction.',
         'R2_population':raw.get('fit_metrics',{}).get('PRED',{}).get('R2'),
         'R2_conditional':raw.get('fit_metrics',{}).get('IPRED',{}).get('R2'),
         'RMSE_population':raw.get('fit_metrics',{}).get('PRED',{}).get('RMSE'),
         'RMSE_conditional':raw.get('fit_metrics',{}).get('IPRED',{}).get('RMSE'),
         'max_RSE_percent':max_available_rse(fit['parameters']),
         'max_parameter_correlation':corr,'converged_starts':len(converged),'attempted_starts':len(attempts),
         'selected_attempt':best['attempt'],'screen_eligible':bool(eligible),'reasons':reasons,
         'parameters':fit['parameters'],'derived':raw.get('derived'),
         'diagnostics':diagnostics,'result_folder':str(Path(fit['raw_result_ref']['path']).parent),
         'CV_status':'NOT_PERFORMED','model_release':False}
    write_json(out/'candidate_result.json',row)
    review=invoke_agent(review_contract(request,'candidate_diagnostics'),{'result':row,
        'optimization_attempts':[{'attempt':a['attempt'],'converged':a['result'].get('converged'),
          'logLik':a['result'].get('log_likelihood'),'AIC':a['result']['engine_metrics'].get('AIC'),
          'diagnostic_status':a['result']['diagnostic_status']} for a in attempts]},out/'agent')
    write_json(out/'report.json',{'status':'EXPLORATORY_RESULTS_PENDING_HUMAN_REVIEW','row':row,
        'attempts':attempts,'agent_review':review,'llm_calls':1,'fit_calls':len(attempts),'model_release':False})


def assemble(reference,folders,output):
    request=validate_request(reference);out=Path(output);out.mkdir(parents=True,exist_ok=True)
    reports=[read_json(Path(f)/'report.json') for f in folders];rows=[r['row'] for r in reports]
    for row in rows:row['delta_AIC_all']=row['AIC']-min(r['AIC'] for r in rows)
    comparison={'rows':rows,'ranking_basis':'Same 102 quantified records, 11 rats, FOCEI engine and diagonal CL/VC IIV. No exact-ML or predictive-validation claim.',
      'scientific_selection':'PENDING_HUMAN_REVIEW','model_release':False}
    write_json(out/'comparison.json',comparison)
    columns=[k for k in rows[0] if k not in {'parameters','derived','diagnostics','reasons'}]
    with (out/'comparison.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,columns,extrasaction='ignore');w.writeheader();w.writerows(rows)
    review=invoke_agent(review_contract(request,'comparison'),{'comparison':comparison},out/'comparison_agent')
    report={'status':'EXPLORATORY_RESULTS_PENDING_HUMAN_REVIEW','species':'rat','candidate_count':len(rows),
      'llm_calls':len(reports)+1,'fit_calls':sum(r['fit_calls'] for r in reports),'model_release':False,
      'comparison_ref':file_ref(out/'comparison.json'),'agent_review':review,
      'limitations':['2 BLQ observations have unknown numeric LLOQ and are retained outside the exploratory likelihood.',
        'Parameters are per kg on the reported dose scale; no individual weights were invented.',
        'FOCEI information criteria and conditional R2 are not independent predictive validation.']}
    write_json(out/'report.json',report)
    (out/'README.md').write_text('# Exploratory rat PK results\n\nPending human model review.\n\n'+review['response']['summary']+'\n',encoding='utf-8')
    write_json(out/'artifact_manifest.json',{'files':[{'name':p.relative_to(out).as_posix(),**file_ref(p),'kind':'result'}
        for p in out.rglob('*') if p.is_file() and p.name!='artifact_manifest.json']})
