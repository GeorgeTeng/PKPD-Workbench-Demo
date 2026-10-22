"""Species-first animal PK architecture. Planning never releases a scientific model."""
import hashlib
import json
import copy
from pathlib import Path

from .adequacy import check_ref, file_ref
from .common import PipelineError, read_json, write_json, utcnow
from .task_rules import scoped_context, project_rules

VERSION = '2.2'
ROLES = {
    'species_coordinator': 'Define the species-specific analysis scope and unresolved pooling decisions.',
    'input_qualification': 'Check dosing, observations, units, sampling design and source permissions for this analysis.',
    'model_review': 'Review the proposed compartment candidates against the assigned data, EDA and project rules. Identify missing qualifications without inventing observations or parameters.',
    'configuration_selection': 'Review this permitted configuration within the assigned compartment class. Request a change if unsupported; do not invent a new configuration or numerical estimates.',
    'estimation_configuration': 'Check the explicit nlmixr2 estimator, parameter starts and bounds, random effects and residual error against the qualified data. Numerical code is a trusted tool, not generated text.',
    'fit_self_check': 'Interpret this numerical fit and its internal self-checks. A failed deterministic check cannot be overridden. Explain uncertainty, convergence problems and the next permitted revision.',
    'attempt_summary': 'Summarize all attempts for this compartment class, retain every eligible fit, and explain excluded or unresolved attempts. Do not select the final model.',
    'candidate_model': 'Specify one compartment candidate, call a qualified numerical adapter, and revise only within its approved scope.',
    'diagnostics': 'Review numerical diagnostics, uncertainty and biological questions for one candidate; request justified revisions.',
    'comparison': 'Interpret the validated comparison table; explain disagreements between criteria and unresolved diagnostics.',
    'species_report': 'Assemble candidate evidence within one species, retaining separate analysis populations and likelihoods.',
    'animal_pk_report': 'Assemble species reports and human selections; report unresolved species and no human prediction.',
}
RESPONSE_SCHEMA = {'type':'object', 'additionalProperties':False, 'required':['decision','summary','issues','requested_changes'],
    'properties':{'decision':{'type':'string','enum':['CONTINUE','REVISE','NEEDS_REVIEW']},
        'summary':{'type':'string'}, 'issues':{'type':'array','items':{'type':'string'}},
        'requested_changes':{'type':'array','items':{'type':'string'}}}}


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()


def species_name(value):
    name=str(value or '').strip().lower()
    return {'mice':'mouse','mus musculus':'mouse','rats':'rat','rattus norvegicus':'rat',
            'rabbits':'rabbit','dogs':'dog'}.get(name,name)


def blueprint():
    return {'schema_version':VERSION, 'strategy':'WITHIN_SPECIES_FIRST',
        'roles':ROLES, 'controller':'LangGraph', 'scheduler':'Prefect', 'file_executor':'Snakemake',
        'candidate_loop':['configuration_selection','estimation_configuration','nlmixr2_fit_with_internal_self_checks','retain_or_next_configuration','attempt_summary'],
        'species_loop':['species_coordinator','input_qualification','model_review','parallel_candidates','comparison','human_review','species_report'],
        'human_revision_targets':['input_qualification','candidate_model','diagnostics','comparison'],
        'models':[{'compartments':1,'status':'PLANNED'},{'compartments':2,'status':'PLANNED'},
                  {'compartments':3,'status':'CONDITIONAL_REQUIRES_JUSTIFICATION'}],
        'execution_status':'EXECUTABLE_WITH_QUALIFIED_INPUTS',
        'fitting_engine':'nlmixr2',
        'agent_provider':'Fresh codex_generate call per logical agent invocation; tools compute numeric results.',
        'multi_species_joint_fit':'DEFERRED', 'automatic_scientific_acceptance':False,
        'metrics':['logLik','n_parameters','n_observations','AIC','BIC','delta_AIC','delta_BIC'],
        'metrics_source':'https://stat.ethz.ch/R-manual/R-devel/library/stats/html/AIC.html'}


def build_plan(context_ref, options=None):
    check_ref(context_ref); context=read_json(context_ref['path']); options=options or {}
    from .context_builder import verify_branch_handoff
    verify_branch_handoff(context)
    if context.get('module')!='pk': raise PipelineError('PK_CONTEXT_REQUIRED','Select the routed PK context.')
    if any(context.get('data_access',{}).values()):
        raise PipelineError('PK_HOLDOUT_PERMISSION','This animal-only architecture does not accept human or holdout access.')
    context, rule_projection = scoped_context(context, 'animal_pk')
    three=options.get('three_compartment',{})
    if not isinstance(three,dict) or any(not isinstance(v,str) or not v.strip() for v in three.values()):
        raise PipelineError('PK_3C_REASON_REQUIRED','Provide a scientific reason for each requested three-compartment analysis.')
    species={}; unassigned=[]; agents=[]; edges=[]; units=[]
    def agent(role, scope, inputs, depends=(), candidate=None):
        identifier='agent_'+digest([role,scope,candidate])[:16]
        metadata = inputs.get('metadata') or inputs.get('dataset_metadata')
        applicable = project_rules(context, 'animal_pk', [metadata] if metadata else None)
        value={'id':identifier,'role':role,'scope':scope,'instructions':ROLES[role],
            'context':copy.deepcopy(inputs),'rule_snapshot':applicable['rules'],
            'rule_scope':{'target':'animal_pk','version':applicable['version'], 'unresolved':applicable['unresolved']},'candidate':candidate,
            'response_schema':RESPONSE_SCHEMA,'depends_on':list(depends),
            'session_policy':'FRESH_CALL_NO_CONVERSATION_REUSE','state_policy':'FILE_REFERENCES_AND_THIS_TASK_ONLY',
            'status':'PLANNED_NOT_INVOKED','fit_release':False,
            'output_contract':{'agent_response':'response.json','execution':'execution.json','tool_outputs':'verified file references'},
            'safeguards':['Do not infer missing identities, units, dosing or source eligibility.',
                'Do not edit observations, change model class, or accept a model without the appropriate review.',
                'Use numerical tool output for estimates and metrics; never generate numeric fit results in an LLM response.']}
        agents.append(value);edges.extend({'from':d,'to':identifier} for d in depends)
        return identifier
    shared={k:context.get(k) for k in ['drug','clinical_questions','tasks','task_requirements']}
    refs=[context_ref]
    seen=set()
    for item in context.get('data_files',[]):
        identifier=item['dataset_id']
        if identifier in seen: raise PipelineError('PK_DUPLICATE_DATASET','Duplicate dataset ID: '+identifier)
        seen.add(identifier)
        for key in ['data','csv','metadata','excluded_records']:
            check_ref(item[key]);refs.append(item[key])
        sidecar=read_json(item['metadata']['path']); meta=sidecar.get('metadata',sidecar)
        if sidecar.get('dataset_id',identifier)!=identifier or (sidecar.get('data_file') and sidecar['data_file']!=item['data']):
            raise PipelineError('PK_METADATA_MISMATCH','Metadata does not describe its assigned dataset: '+identifier)
        name=species_name(meta.get('species'))
        if meta.get('permission')!='DEVELOPMENT_CANDIDATE' or name in {'human','humans','homo sapiens'}:
            raise PipelineError('PK_RESTRICTED_DATA','Animal development data required: '+identifier)
        if item['role']!='PK_OBSERVATIONS' or meta.get('role')!='PK_OBSERVATIONS':
            unassigned.append({'dataset_id':identifier,'reason':'Support evidence requires an explicit analysis association; no filename-based join.'});continue
        if name in {'','unknown','not_found','not_applicable'}:
            unassigned.append({'dataset_id':identifier,'reason':'Species metadata must be qualified before creating a species task.'});continue
        scope={'species':name,'analysis_id':identifier}
        if name not in species:
            sid=agent('species_coordinator',{'species':name},shared)
            species[name]={'species':name,'coordinator':sid,'analysis_ids':[],'comparison_agents':[]}
        unit={**scope,'data':item,'metadata':meta,'compartments':[1,2],
            'pooling':'SOURCE_TABLE_PRESERVED_PENDING_REVIEWED_POOLING_PLAN',
            'fit_release':False,'required_qualification':['Dosing and route','Observation IDs and sampling design',
                'Residual/random-effects specification','Units and free/total definition','BLQ and missingness policy',
                'Approved model/parameter source permissions','Parameter uncertainty and diagnostic plan']}
        if identifier in three:
            unit['compartments'].append(3);unit['three_compartment_reason']=three[identifier]
        species[name]['analysis_ids'].append(identifier)
        # A source table is a planning unit, not a declaration that it is fit-ready.
        scoped={**shared,'dataset':item,'metadata':meta,
                'eda_findings':[f for f in context.get('findings',[]) if f.get('dataset_id')==identifier],
                'required_qualification':unit['required_qualification']}
        inp=agent('input_qualification',scope,scoped,[species[name]['coordinator']]); unit['input_agent']=inp
        review=agent('model_review',scope,{**scoped,'compartments':unit['compartments']},[inp])
        unit['model_review_agent']=review
        unit['candidates']=[]
        for compartments in unit['compartments']:
            candidate={'id':identifier+'_'+str(compartments)+'C','compartments':compartments,
                       'route_model':'REQUIRES_QUALIFICATION','estimator':'REQUIRES_QUALIFICATION',
                       'random_effects':'REQUIRES_SAMPLING_DESIGN','residual_error':'REQUIRES_QUALIFICATION'}
            cid=agent('candidate_model',scope,scoped,[review],candidate)
            steps=[]
            for role,label in [('configuration_selection','Select reviewed configuration'),
                    ('estimation_configuration','Configure nlmixr2 estimation'),
                    ('fit_self_check','Fit and internal self-checks'),('attempt_summary','Return all attempts')]:
                step=agent(role,scope,{'candidate_agent':cid,'dataset_metadata':meta},[],candidate)
                agents[-1]['managed_by']=cid
                steps.append({'agent_id':step,'role':role,'label':label})
            edges.append({'from':steps[2]['agent_id'],'to':steps[0]['agent_id'],
                          'condition':'NEXT_PERMITTED_CONFIGURATION_OR_JUSTIFIED_REVISION','loop':True})
            unit['candidates'].append({**candidate,'engine':'nlmixr2','model_agent':cid,
                'diagnostic_agent':steps[2]['agent_id'],'steps':steps})
        comparison=agent('comparison',scope,{'candidate_ids':[c['id'] for c in unit['candidates']],
            'required_tool':'validated_likelihood_comparison','required_qualification':unit['required_qualification']},
            [c['model_agent'] for c in unit['candidates']])
        unit['comparison_agent']=comparison;species[name]['comparison_agents'].append(comparison);units.append(unit)
    if set(three)-seen: raise PipelineError('PK_UNKNOWN_ANALYSIS','Three-compartment request names an unknown dataset.')
    if any(k not in {u['analysis_id'] for u in units} for k in three):
        raise PipelineError('PK_UNKNOWN_ANALYSIS','Three-compartment request requires an eligible PK analysis.')
    for name,s in species.items():
        coordinator=next(a for a in agents if a['id']==s['coordinator'])
        coordinator['context']['datasets']=[{'dataset_id':u['analysis_id'],'metadata':u['metadata']} for u in units if u['species']==name]
        s['human_gate']='human_'+digest(name)[:12]
        edges.extend({'from':c,'to':s['human_gate']} for c in s['comparison_agents'])
        s['report_agent']=agent('species_report',{'species':name},{'analysis_ids':s['analysis_ids'],
            'comparison_policy':'Report human-selected candidates, preserving separate observation sets and likelihoods.'},[s['human_gate']])
        edges.append({'from':s['human_gate'],'to':s['coordinator'],'condition':'REQUEST_CHANGES','loop':True})
    agent('animal_pk_report',{'species':list(species)}, {'species_review_ids':[s['human_gate'] for s in species.values()],
        'requires':'Explicit human selections or documented unresolved species; no human extrapolation.'},[s['report_agent'] for s in species.values()])
    plan={**blueprint(),'created_at':utcnow(),'context_ref':context_ref,'source_refs':refs,
        'species':list(species.values()),'analysis_units':units,'agents':agents,'edges':edges,'unassigned':unassigned,
        'options':options,'status':'PLANNED_NOT_FITTED','model_release':False,
        'rule_projection':rule_projection,
        'limitations':['Default planning units preserve source tables; pooling must be scientifically defined before fitting.',
            'Architecture jobs materialize agent requests and empty comparison tables. No LLM or numerical fit is claimed.',
            'The connected nlmixr2 adapter requires explicitly qualified individual IV data and estimation configurations; other data designs need a suitable adapter.',
            'Every logical agent uses a fresh request; model-loop control and numerical fitting are deterministic tools. Human model selection remains mandatory.']}
    plan['plan_signature']=digest(plan)
    return plan


def materialize_agent(contract, output):
    """Executable architecture adapter; explicitly reports zero model/fit calls."""
    output=Path(output)
    write_json(output/'request.json',contract)
    write_json(output/'execution.json',{'agent_id':contract['id'],'at':utcnow(),'status':'PLANNED_NOT_INVOKED',
        'llm_calls':0,'fit_calls':0,'reason':'Connect qualified model inputs and the numerical adapter before scientific execution.'})


def assemble_architecture(plan_path, run):
    plan=read_json(plan_path);run=Path(run);folder=run/'animal_pk';files=[]
    if plan['plan_signature']!=digest({k:v for k,v in plan.items() if k!='plan_signature'}):
        raise PipelineError('PK_PLAN_CHANGED','The animal PK architecture changed during execution.')
    for ref in plan['source_refs']:check_ref(ref)
    for a in plan['agents']:
        root=folder/'agents'/a['id']
        for name in ['request.json','execution.json']: files.append({'name':a['id']+'_'+name,**file_ref(root/name)})
    rows=[{'species':u['species'],'analysis_id':u['analysis_id'],'candidate_id':c['id'],
        'compartments':c['compartments'],'status':'NOT_FITTED','logLik':None,'n_parameters':None,
        'n_observations':None,'AIC':None,'BIC':None,'delta_AIC':None,'delta_BIC':None,
        'reason':'Qualified inputs and a numerical adapter are required.'} for u in plan['analysis_units'] for c in u['candidates']]
    import csv
    folder.mkdir(parents=True,exist_ok=True)
    with (folder/'comparison.csv').open('w',encoding='utf-8',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]) if rows else ['species','candidate_id','status','AIC','BIC'])
        writer.writeheader();writer.writerows(rows)
    report={'schema_version':VERSION,'status':'ARCHITECTURE_READY_NOT_FITTED','plan_signature':plan['plan_signature'],
        'species_count':len(plan['species']),'analysis_count':len(plan['analysis_units']),'agent_count':len(plan['agents']),
        'candidate_count':len(rows),'comparisons':rows,'model_release':False,'llm_calls':0,'fit_calls':0,
        'human_review_status':'WAITING_FOR_FITTED_RESULTS','limitations':plan['limitations']}
    write_json(folder/'architecture.json',plan);write_json(folder/'report.json',report)
    for name in ['architecture.json','report.json','comparison.csv']:files.append({'name':name,**file_ref(folder/name)})
    write_json(folder/'artifact_manifest.json',{'files':files,'model_release':False})
    return report
