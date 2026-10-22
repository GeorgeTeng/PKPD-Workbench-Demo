"""Branch-specific projection used by ContextBuilder; no routing or model calls.

The router supplies task/data assignments. This adapter preserves source pointers,
scientific limitations, question edits and the established downstream contract.
"""
import re
from pathlib import Path

from .common import PipelineError, read_json, write_json
from .adequacy import file_ref
from .clinical_questions import derive_questions, index_scope

CLINICAL_KEYS = {
    'pk': ['decision_question', 'experimental_unit', 'target_population', 'exposure_definition',
           'regimen_constraints', 'translation_assumptions', 'decision_criteria'],
    'index': ['decision_question', 'pd_endpoint', 'endpoint_window', 'experimental_unit',
              'pathogen_infection_site', 'exposure_definition', 'mic_and_binding_source', 'decision_criteria'],
    'clinical': ['decision_question', 'target_population', 'regimen_constraints', 'safety_endpoints',
                 'translation_assumptions', 'decision_criteria'],
}

def index_candidates(main):
    return index_scope(main)['candidates']


def rules_for(main, branch):
    from .task_rules import project_rules
    return project_rules(main, branch)['rules']


def project_reference_advice(advice, branch=None):
    """Advice suggests questions; it cannot overwrite answers or activate rules."""
    if not advice: return None
    stages = {'pk':{'pk','human_pk'}, 'index':{'index'}, 'clinical':{'validation'}}
    selected = [s for s in advice['suggestions'] if branch is None or s['relevant_step'] in stages[branch]]
    ids = {s['card_id'] for s in selected}
    cards = [c for c in advice['cards'] if c['id'] in ids]
    sources = {s for c in cards for s in c['source_ids']}
    return {'authority':advice['authority'], 'scope':advice['scope'], 'rule_activation':False,
        'provenance':advice.get('provenance'), 'suggestions':selected, 'cards':cards,
        'sources':[s for s in advice['sources'] if s['id'] in sources],
        'use':'QUESTION_AND_DEPENDENCY_REVIEW_ONLY', 'answers_overwritten':False,
        'clinical_design_added':False, 'parameter_transfer_authorized':False}


def prepare_branch(branch, source, assignment, output):
    main = source['main']; snapshot = source['snapshot']; assessment = source['assessment']
    values = source['values']; derived = source['derived']; defaults = derived['values']
    advice = source['advice']; exposure_source = source['exposure_source']
    require_eda = source['require_eda']; output = Path(output)
    reports = {d['dataset_id']: d for d in source['eda']['datasets']}
    task_branch = lambda task: source['task_branches'].get(task['id'])
    selected_tasks = assignment['tasks']
    selected_ids = {t['id'] for t in selected_tasks}
    requirements = [r for r in assessment.get('requirements', []) if r.get('task_id') in selected_ids]
    dataset_items = []
    findings = []
    for dataset in assignment['datasets']:
        metadata = dataset['metadata']; report = reports[dataset['id']]
        dataset_items.append({'dataset_id':dataset['id'], 'role':dataset['role'],
            'species':metadata.get('species'), 'matrix':metadata.get('matrix'),
            'record_level':metadata.get('record_level'), 'exposure_basis':metadata.get('exposure_basis'),
            'source_title':metadata.get('source_table', {}).get('title'),
            'data':dataset['data'], 'csv':dataset['csv'], 'metadata':dataset['metadata_file'],
            'excluded_records':dataset['quarantine'], 'use':'CANDIDATE_INPUT_ONLY_NOT_FIT_RELEASE'})
        findings += report.get('findings', [])
    missing = [{'code':'SOURCE_QUALIFICATION_REQUIRED', 'reason':'Confirm units, dosing, identities, source permissions and missingness treatment for each selected dataset.',
                'needed_material':'Reviewed branch-specific model inputs and model eligibility; draft routing is not fit approval.'}]
    if branch == 'pk':
        missing += [{'code':'MODEL_LIBRARY_QUALIFICATION', 'reason':'Model structures, code and parameter-source permissions require qualification under the current project rules; a mixed catalog is not passed wholesale.',
            'needed_material':'Qualified model inputs consistent with the project permissions, comparisons and uncertainty plan.'}]
        outputs = ['pk_model_comparison.json','pk_parameters.csv','parameter_uncertainty.json','exposure_predictions.csv','pk_diagnostics/']
    elif branch == 'index':
        missing += [{'code':'EXPOSURE_MATCHING_UNCONFIRMED','reason':'Project-defined exposure basis, matched references, dosing and windows need qualification as calculation-ready inputs.',
            'needed_material':'Verified project-defined exposure series or reviewed PK predictions with matching identifiers and units.'},
            {'code':'PD_MATCHING_UNCONFIRMED','reason':'Preparing indices does not establish matched PD responses or identify the best index.',
             'needed_material':'Approved experimental-unit/regimen/strain/endpoint join and common response set before the project-specified response-model comparison.'}]
        outputs = ['index_input_readiness.json','calculated_indices.csv','index_comparison.json','index_diagnostics/']
    else:
        missing += [{'code':'HUMAN_SCENARIO_UNDEFINED','reason':values['target_population']+' '+values['regimen_constraints'],
            'needed_material':'Prespecified target population, dosing scenarios, validation/attainment criteria and safety evidence.'}]
        outputs = ['clinical_interpretation.json','validation_plan.json','pta_readiness.json','next_cycle_request.json']
        if not any(re.search(r'\bPTA\b|attainment',str(t),re.I) for t in selected_tasks): outputs.remove('pta_readiness.json')
    # Scientific work comes from this project's reviewed tasks, not a PMB
    # example. Common technical safeguards are separately labeled below.
    jobs = [f"{t['id']}: {t['question']}" + (" Estimand: "+t['estimand'] if t.get('estimand') else '') for t in selected_tasks]
    for req in requirements:
        if req.get('status') in {'MISSING','UNRESOLVED','DEFERRED'}:
            missing.append({'code':req['id'],'status':req['status'],'required_by':req.get('required_by'),
                'reason':req.get('reason'),'needed_material':req.get('needed_material'),
                'condition':req.get('condition'),'source':'assessment.json'})
    if branch=='clinical' and 'UNKNOWN' not in (values['target_population']+' '+values['regimen_constraints']).upper():
        missing=[m for m in missing if m['code']!='HUMAN_SCENARIO_UNDEFINED']
    if not selected_tasks:
        outputs=[]
        missing=[{'code':'NO_REVIEWED_BRANCH_TASK','reason':'This branch has no assigned reviewed task.',
            'needed_material':'No calculation is scheduled. Clarify the proposal/assessment if this branch is intended.'}]
    branch_derived=derive_questions(main,assessment,task_branch,task_ids=selected_ids)
    edited={key for key in CLINICAL_KEYS[branch] if values[key]!=defaults[key]}
    branch_values={key:values[key] if key in edited else branch_derived['values'][key] for key in CLINICAL_KEYS[branch]}
    field_info={key:(derived if key in edited else branch_derived)['field_evidence'][key] for key in CLINICAL_KEYS[branch]}
    catalog={**derived['evidence_catalog'],**branch_derived['evidence_catalog']}
    evidence_ids={x for f in field_info.values() for k in ['definition_evidence','related_evidence'] for x in f[k]}
    context = {'schema_version':'1.0','module':branch,'status':'PENDING_DISPATCH_REVIEW' if require_eda else 'DRAFT_NOT_RELEASED',
        'objective':main.get('objective'), 'drug':main.get('study',{}).get('drug'),
        'clinical_questions':branch_values,
        'question_projection':'Unedited defaults are projected to assigned task IDs; human-edited definitions are retained.',
        'question_evidence':field_info,'question_evidence_catalog':{key:catalog[key] for key in sorted(evidence_ids)},
        'question_generator':derived['generator_version'],
        'human_edited_question_fields':[key for key in CLINICAL_KEYS[branch] if values[key]!=defaults[key]],
        'generic_execution_safeguards':['Confirm source permissions, units, identities and analysis eligibility before fitting.',
            'This adapter does not grant access to human/holdout bodies; project-specific use must be qualified separately.'],
        'tasks':selected_tasks,'work_items':jobs,'task_requirements':requirements,
        'data_files':dataset_items,'rules':[], 'findings':findings,'missing_materials':missing,
        'expected_outputs':outputs,'data_access':{'human_pk':False,'human_binding':False,'benchmark_results':False},
        'model_release':False,'human_prediction_validated':False,
        'upstream_signatures':{k:n['output_signature'] for k,n in snapshot['nodes'].items()},
        'handoff_gate':'Exact dispatch output signature plus LangGraph human APPROVE is required; downstream validates it at consumption.'}
    scoped_advice = project_reference_advice(advice, branch) if selected_tasks else None
    if 'scientific_context' in main:
        from ctxcomp.scientific import from_context_citations
        citations = [s for task in selected_tasks + requirements for s in task.get('context_evidence', [])]
        context['scientific_context'] = from_context_citations(main, citations)
        main_ref = next(a for a in snapshot['nodes']['adequacy']['artifacts'] if a['name']=='effective_main.json')
        context['scientific_context_source'] = {
            'path': main_ref['path'], 'sha256': main_ref['sha256'], 'pointer': '/scientific_context',
            'selection': 'Reviewed task/requirement record citations plus referenced methods and premises; no filename or keyword routing.',
            'uncited_items': 'Not assigned automatically. Inspect the source during routing review if task evidence is incomplete.'}
    if scoped_advice and scoped_advice['suggestions']: context['external_reference_advice'] = scoped_advice
    if branch == 'index': context.update(candidate_indices=index_candidates(main), index_scope_evidence=index_scope(main), index_exposure_source=exposure_source,
        phases={'prepare':'CAN_PLAN_IN_PARALLEL_WITH_PK_AFTER_DISPATCH_REVIEW',
                'calculate':'REQUIRES_QUALIFIED_PROJECT_DEFINED_EXPOSURE_AND_REFERENCE',
                'fit':'REQUIRES_CALCULATED_INDICES_AND_MATCHED_PD'})
    if branch == 'clinical': context['expected_upstream_results']=['pk_context outputs','index_context outputs']
    from .task_rules import project_rules
    rule_source = main
    provenance_ref = next((a for a in snapshot['nodes']['adequacy']['artifacts'] if a['name']=='context_provenance.json'), None)
    if provenance_ref:
        provenance = read_json(provenance_ref['path'])
        if provenance.get('project_rules_ref'):
            from .project_rule_agent import verify_published
            pack = verify_published(provenance['project_rules_ref'])
            if read_json(pack['main_ref']['path']) != main:
                raise PipelineError('PROJECT_RULES_CONTEXT_MISMATCH', 'Routing context differs from the reviewed project-rule publication.')
            rule_source = {**main, 'project_rules_ref':provenance['project_rules_ref'], 'tasks':selected_tasks}
    projection = project_rules(rule_source, branch, [d['metadata'] for d in assignment['datasets']])
    context['rules'] = projection['rules']
    context['rule_projection'] = {k:v for k,v in projection.items() if k not in {'audit','rules'}}
    context['rule_audit_ref'] = file_ref(write_json(output/(branch+'_rule_audit.json'), projection))
    return context
