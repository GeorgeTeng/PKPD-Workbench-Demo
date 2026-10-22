"""Numerical evidence precedes the comparison agent and signature-bound human review."""
import math
from .animal_pk import digest
from .adequacy import check_ref
from .common import PipelineError, read_json, write_json, utcnow
from .graph_control import ReviewController

COMPARABILITY = ['species','analysis_id','observation_signature','response_scale','response_unit',
    'likelihood_definition','likelihood_constants','estimation_method','n_observations','bic_n_definition']


def compare_results(results):
    rows=[]
    for result in results:
        row={'candidate_id':result['candidate_id'],'species':result.get('species'),'analysis_id':result.get('analysis_id'),
             'status':result.get('status'),'AIC':None,'BIC':None,'delta_AIC':None,'delta_BIC':None,'reasons':[],
             'parameters':result.get('parameters',[]),'converged':result.get('converged'),
             'diagnostic_status':result.get('diagnostic_status'),'engine_metrics':result.get('engine_metrics'),
             'likelihood_kind':'APPROXIMATE' if result.get('estimation_method')=='APPROXIMATE_FOCEI' else 'EXACT_ML'}
        row['evidence_refs']={k:result[k] for k in ['execution_ref','model_code_ref','diagnostics_ref','fit_result_ref'] if k in result}
        row['diagnostic_rule_signature']=result.get('diagnostic_rule_signature')
        row['comparability']={key:result.get(key) for key in COMPARABILITY}
        if result.get('status')!='FITTED': row['reasons'].append('No completed numerical fit.')
        if result.get('converged') is not True: row['reasons'].append('Convergence has not been established.')
        if any(result.get(k) in (None,'','UNKNOWN','NOT_FOUND') for k in COMPARABILITY):
            row['reasons'].append('Incomplete observation/likelihood comparability contract.')
        if result.get('estimation_method') not in {'MAXIMUM_LIKELIHOOD','APPROXIMATE_FOCEI'}:
            row['reasons'].append('This adapter supports matched ML or matched nlmixr2 FOCEI approximations; other objectives need qualification.')
        if result.get('diagnostic_status')!='PASSED_PRESET_CHECKS': row['reasons'].append('Required numerical diagnostics are unresolved.')
        if not result.get('diagnostic_rule_signature'): row['reasons'].append('The applied diagnostic rule snapshot is missing.')
        for name in ['execution_ref','model_code_ref','diagnostics_ref']:
            try: check_ref(result[name])
            except (KeyError,ValueError,OSError): row['reasons'].append('Missing or changed '+name+'.')
        if result.get('fit_result_ref'):
            try:check_ref(result['fit_result_ref'])
            except (ValueError,OSError):row['reasons'].append('Missing or changed fitted-parameter result.')
        ll=result.get('log_likelihood'); k=result.get('n_parameters'); n=result.get('n_observations')
        valid_number=lambda x: type(x) in (int,float) and math.isfinite(x)
        if not valid_number(ll) or type(k)!=int or k<1 or type(n)!=int or n<1:
            row['reasons'].append('Finite logLik and positive integer parameter/observation counts are required.')
        row.update(logLik=ll,n_parameters=k,n_observations=n)
        if not row['reasons']:
            row.update(AIC=-2*ll+2*k,BIC=-2*ll+math.log(n)*k,
                comparison_group=digest({**{key:result[key] for key in COMPARABILITY},
                    'matrix':result.get('matrix'),'exposure_basis':result.get('exposure_basis')}),status='ELIGIBLE_FOR_WITHIN_GROUP_RANKING')
        else: row['status']='NOT_COMPARABLE'
        rows.append(row)
    if len({r['candidate_id'] for r in rows})!=len(rows):
        raise PipelineError('PK_DUPLICATE_CANDIDATE','Candidate IDs must be unique.')
    groups={}
    for row in rows:
        if row.get('comparison_group'): groups.setdefault(row['comparison_group'],[]).append(row)
    recommendations=[]
    for key,items in groups.items():
        if len(items)<2:
            items[0]['reasons'].append('Only one eligible candidate in this comparison group; no comparative winner.')
            continue
        for metric in ['AIC','BIC']:
            best=min(r[metric] for r in items)
            for r in items:r['delta_'+metric]=r[metric]-best
        recommendations.append({'comparison_group':key,'species':items[0]['species'],'analysis_id':items[0]['analysis_id'],
            'likelihood_kind':items[0]['likelihood_kind'],
            'lowest_AIC':[r['candidate_id'] for r in items if r['delta_AIC']==0],
            'lowest_BIC':[r['candidate_id'] for r in items if r['delta_BIC']==0]})
    report={'schema_version':'1.0','at':utcnow(),'rows':rows,'recommendations':recommendations,
        'status':'PENDING_HUMAN_REVIEW','scientific_accepted':False,
        'limitations':['Different observation sets, response scales, likelihood definitions and BIC sample-size conventions are not ranked together.',
            'Best AIC/BIC is a statistical candidate recommendation, not an automatic scientific acceptance.',
            'FOCEI rankings use an approximate likelihood, require matched engine/objective definitions, and remain separate from exact ML. Numerical eligibility does not establish scientific adequacy.',
            'REML, Bayesian and other estimation objectives require a separate comparison contract.']}
    report['output_signature']=digest(report)
    return report


def validate_report(report):
    if report.get('output_signature')!=digest({k:v for k,v in report.items() if k!='output_signature'}):
        raise PipelineError('PK_CHANGED_COMPARISON','The comparison report changed; generate and review a new report.')


def begin_review(report, folder, session_id, species):
    validate_report(report)
    if not any(r['species']==species for r in report['rows']): raise PipelineError('PK_UNKNOWN_SPECIES','No comparison exists for this species.')
    from pathlib import Path
    from .adequacy import file_ref
    folder=Path(folder); report_path=write_json(folder/'comparison.json',report)
    receipt=ReviewController(folder).begin(session_id,'animal_pk_'+species,report['output_signature'],[file_ref(report_path)])
    write_json(folder/'review_interrupt.json',{'species':species,'receipt':receipt,'report_ref':file_ref(report_path)})
    return receipt


def finish_review(folder, decision):
    from pathlib import Path
    folder=Path(folder); gate=read_json(folder/'review_interrupt.json');check_ref(gate['report_ref'])
    report=read_json(gate['report_ref']['path']);validate_report(report)
    if decision.get('decision')=='APPROVE':
        selected=decision.get('selected_candidates',[])
        eligible={r['candidate_id']:r for r in report['rows'] if r['species']==gate['species'] and r['status']=='ELIGIBLE_FOR_WITHIN_GROUP_RANKING'}
        selected_groups=[eligible[c]['comparison_group'] for c in selected if c in eligible]
        expected_groups={r['comparison_group'] for r in eligible.values()}
        if not selected or any(c not in eligible for c in selected) or len(set(selected_groups))!=len(selected) or set(selected_groups)!=expected_groups:
            raise PipelineError('PK_INVALID_SELECTION','Select one eligible candidate per comparison group for this species; unresolved groups require revision.')
        for candidate in selected:
            for ref in eligible[candidate]['evidence_refs'].values():check_ref(ref)
        if any(r['species']==gate['species'] and r['status']=='NOT_COMPARABLE' and not any(x['analysis_id']==r['analysis_id'] for x in eligible.values()) for r in report['rows']):
            raise PipelineError('PK_UNRESOLVED_ANALYSIS','An analysis has no eligible fit; resolve it or revise the approved scope.')
    elif decision.get('decision')=='REQUEST_CHANGES':
        if decision.get('return_to') not in {'input_qualification','model_review','candidate_model','diagnostics','fit_self_check','comparison'} or not decision.get('requested_changes','').strip():
            raise PipelineError('PK_REVISION_TARGET_REQUIRED','Specify the target agent step and requested changes.')
    receipt=ReviewController(folder).resume(gate['receipt'],decision)
    release={'at':utcnow(),'species':gate['species'],'decision':decision,'langgraph':receipt,
        'comparison_signature':report['output_signature'],'model_release':receipt['status']=='APPROVED',
        'human_prediction_validated':False}
    write_json(folder/'review_decision.json',release)
    if receipt['status']=='APPROVED':
        write_json(folder/'accepted_models.json',{'species':gate['species'],'comparison_signature':report['output_signature'],
            'selected_models':[eligible[c] for c in decision['selected_candidates']],
            'review_decision':release,'human_prediction_validated':False})
    elif decision.get('decision')=='REQUEST_CHANGES':
        write_json(folder/'revision_request.json',{'species':gate['species'],'comparison_signature':report['output_signature'],
            'target_agent_role':decision['return_to'],'requested_changes':decision['requested_changes'],
            'candidate_ids':decision.get('candidate_ids',[]),'execution_status':'PENDING_NEW_ATTEMPT','model_release':False})
    return release
