"""Build scoped, source-bound clinical task contracts; never approve their science.

Drafts may be inspected after completed EDA. Execution requires approved EDA and
confirmed questions, and the resulting dispatch still has its own review gate.
No concentration fitting, human holdout access or response join occurs here.
"""
import json
import re
from pathlib import Path

from .common import PipelineError, read_json, write_json, utcnow
from .adequacy import check_ref, file_ref
from .workflow_definition import CLINICAL_FIELDS
from .clinical_questions import derive_questions, index_scope, pathogen_scope, matches_pathogen

BRANCHES = ('pk', 'index', 'clinical')
CLINICAL_KEYS = {
    'pk': ['decision_question', 'experimental_unit', 'target_population', 'exposure_definition',
           'regimen_constraints', 'translation_assumptions', 'decision_criteria'],
    'index': ['decision_question', 'pd_endpoint', 'endpoint_window', 'experimental_unit',
              'pathogen_infection_site', 'exposure_definition', 'mic_and_binding_source', 'decision_criteria'],
    'clinical': ['decision_question', 'target_population', 'regimen_constraints', 'safety_endpoints',
                 'translation_assumptions', 'decision_criteria'],
}


def task_branch(task):
    if task.get('destination') in BRANCHES:
        return task['destination']
    text = ' '.join(str(task.get(k, '')) for k in ['question', 'estimand', 'endpoint']).lower()
    if re.search(r'pta|attainment|mic distribution|population weighting|feasibility conclusion|final benchmark|independent observed|observed versus predicted|human.*agreement', text):
        return 'clinical'
    if re.search(r'indices|index|exposure.response|antibacterial targets|kill targets', text): return 'index'
    if re.search(r'pk components|animal.*pk|human.*exposure|concentration.time|\bpharmacokinetics?\b|\bpk\s+(?:model|parameters|fit)', text): return 'pk'
    return None


def inputs(snapshot_ref, require_eda=False):
    from .workflow_canvas import CanvasStore, fingerprint
    raise PipelineError('EDA_DISABLED', 'EDA is disabled. Its backend has been removed and will not be called.')
    check_ref(snapshot_ref); snapshot = read_json(snapshot_ref['path']); nodes = snapshot['nodes']
    for key in ['context', 'adequacy', 'prepare', 'eda']:
        node = nodes[key]
        if node.get('execution') != 'COMPLETED' or node.get('output_signature') != fingerprint(node.get('artifacts', [])):
            raise PipelineError('DISPATCH_UPSTREAM_INVALID', 'Complete and verify '+key+' before preparing clinical questions.')
        if (key != 'eda' or require_eda) and not CanvasStore.approved(node):
            raise PipelineError('DISPATCH_APPROVAL_REQUIRED', 'Approve the exact '+key+' outputs before releasing clinical dispatch.')
        for artifact in node['artifacts']: check_ref(artifact)
    refs = {a['name']: a for a in nodes['adequacy']['artifacts']}
    if not {'effective_main.json', 'assessment.json'} <= refs.keys():
        raise PipelineError('DISPATCH_CONTEXT_MISSING', 'The reviewed assessment must provide effective main.json and its task definitions.')
    main = read_json(refs['effective_main.json']['path']); assessment = read_json(refs['assessment.json']['path'])
    eda_refs = {a['name']: a for a in nodes['eda']['artifacts']}
    eda = read_json(eda_refs['eda_report.json']['path'])
    approval, _, _, datasets = approved_preparation(eda['input_approval'])
    if approval['prepare']['output_signature'] != nodes['prepare']['output_signature']:
        raise PipelineError('DISPATCH_QC_VERSION_MISMATCH', 'EDA describes another QC version. Rerun EDA against the current approved files.')
    eda_ids = {d['dataset_id'] for d in eda['datasets']}
    if eda_ids != {d['id'] for d in datasets}:
        raise PipelineError('DISPATCH_DATASET_MISMATCH', 'The EDA report and approved dataset scope differ.')
    return snapshot, main, assessment, eda, datasets


def question_values(main, tasks):
    return derive_questions(main, {'tasks':tasks}, task_branch)['values']


def index_candidates(main):
    return index_scope(main)['candidates']


def route_dataset(dataset, main):
    metadata = dataset['metadata']; role = dataset['role']
    if metadata.get('permission') != 'DEVELOPMENT_CANDIDATE' or re.search(r'human|homo sapiens', str(metadata.get('species', '')), re.I):
        raise PipelineError('DISPATCH_RESTRICTED_DATA', 'Human/held-out data cannot enter development task contracts: '+dataset['id'])
    source = metadata.get('source_table', {}); text = str(source.get('title', '')) + ' ' + str(source.get('notes', ''))
    if role == 'PK_OBSERVATIONS': return ['pk'], 'Animal PK observation role; index receives reviewed exposure outputs through a separate dependency.'
    if role in {'BINDING', 'DOSING'}: return ['pk', 'index'], 'Development binding/dosing evidence; applicability and source matching remain required.'
    if role == 'MIC':
        if re.search(r'distribution|surveillance|population.weight', text, re.I): return ['clinical'], 'Population MIC weighting evidence, not a matched strain MIC.'
        return ['index'], 'Strain MIC candidate; no regimen or PD link inferred.'
    if role in {'PD_OBSERVATIONS', 'IN_VITRO_TIME_KILL'}:
        scope=pathogen_scope(main)
        if scope['names'] and not matches_pathogen(scope,text):
            return [], 'Current project mentions '+', '.join(scope['names'])+'; this source has no matching pathogen declaration. Scope interpretation remains subject to review.'
        return ['index'], 'PD/time-kill candidate; endpoint, independent units and exposure-response joins remain unconfirmed.'
    return [], 'Metadata role is not sufficiently specific for automatic branch allocation. Review its source and assign a qualified role in QC.'


def rules_for(main, branch):
    from .task_rules import project_rules
    return project_rules(main, branch)['rules']


def reference_advice(snapshot, main):
    """Consume the exact advice used by reviewed adequacy, never today's library."""
    from .pk_reference_pilot import downstream_context
    report_ref = next((a for a in snapshot['nodes']['adequacy']['artifacts'] if a['name']=='adequacy.json'), None)
    if not report_ref: return None
    check_ref(report_ref)
    ref = read_json(report_ref['path']).get('external_reference_context')
    if not ref: return None
    check_ref(ref)
    return {**downstream_context(ref['path'], main), 'provenance':ref}


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


def build(snapshot_ref, output, values=None, exposure_source='UNKNOWN', require_eda=False):
    snapshot, main, assessment, eda, datasets = inputs(snapshot_ref, require_eda)
    advice = reference_advice(snapshot, main)
    tasks = assessment.get('tasks', []); output = Path(output)
    derived = derive_questions(main, assessment, task_branch)
    defaults = derived['values']; values = values or defaults
    if set(values) != {key for key, _, _ in CLINICAL_FIELDS} or any(not isinstance(v, str) or not v.strip() for v in values.values()):
        raise PipelineError('DISPATCH_QUESTIONS_INCOMPLETE', 'Every clinical question needs a definition or an explicit UNKNOWN reason.')
    if exposure_source not in {'UNKNOWN', 'AVAILABLE_MATCHED_DATA', 'REQUIRES_PK_PREDICTIONS'}:
        raise PipelineError('DISPATCH_DEPENDENCY_INVALID', 'Choose a supported exposure-source dependency.')
    routes = []; assigned = {b: [] for b in BRANCHES}; unassigned = []
    active_branches={task_branch(t) for t in tasks if task_branch(t)}
    for dataset in datasets:
        targets, reason = route_dataset(dataset, main)
        if targets and not any(b in active_branches for b in targets):
            reason='No reviewed task is assigned to a compatible branch. Confirm the requested analysis before allocating this dataset.'
        targets=[b for b in targets if b in active_branches]
        routes.append({'dataset_id':dataset['id'], 'role':dataset['role'], 'targets':targets, 'reason':reason,
                       'metadata_ref':dataset['metadata_file']})
        for branch in targets: assigned[branch].append(dataset)
        if not targets:
            scope_excluded=dataset['role'] in {'PD_OBSERVATIONS','IN_VITRO_TIME_KILL'}
            unassigned.append({'dataset_id':dataset['id'], 'reason':reason,
                'status':'PATHOGEN_SCOPE_NOT_MATCHED' if scope_excluded else 'NEEDS_ROLE_QUALIFICATION',
                'needed_material':'Confirm the project and source pathogen scope before allocation; a mention alone cannot resolve exclusions or eligibility.' if scope_excluded
                    else 'Reviewed source role and permitted downstream task before allocation.'})
    questions = {'schema_version':'1.0', 'module':'clinical_questions', 'created_at':utcnow(),
        'status':'CONFIRMED_INPUTS' if require_eda else 'DRAFT_FOR_REVIEW', 'values':values,
        'index_exposure_source':exposure_source, 'source_snapshot':snapshot_ref,
        'source_task_ids':[t['id'] for t in tasks], 'scientific_release':False,
        'generator_version':derived['generator_version'],
        'field_evidence':derived['field_evidence'],'evidence_catalog':derived['evidence_catalog'],
        'provenance':{'values_origin':derived['method'],'limitation':derived['limitation'],
            'question_defaults':defaults,'human_edited_fields':[k for k in values if values[k]!=defaults[k]]}, 'unknowns':[{'field':k,'reason':v} for k,v in values.items() if 'UNKNOWN' in v.upper()]}
    if advice: questions['external_reference_advice'] = project_reference_advice(advice)
    write_json(output/'clinical_questions.json', questions)
    branches = {}; files = []
    reports = {d['dataset_id']:d for d in eda['datasets']}
    for branch in BRANCHES:
        selected_tasks = [t for t in tasks if task_branch(t) == branch]
        selected_ids = {t['id'] for t in selected_tasks}
        requirements = [r for r in assessment.get('requirements', []) if r.get('task_id') in selected_ids]
        dataset_items = []
        findings = []
        for dataset in assigned[branch]:
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
            'data_files':dataset_items,'rules':rules_for(main,branch), 'findings':findings,'missing_materials':missing,
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
        projection = project_rules(rule_source, branch, [d['metadata'] for d in assigned[branch]])
        context['rules'] = projection['rules']
        context['rule_projection'] = {k:v for k,v in projection.items() if k not in {'audit','rules'}}
        context['rule_audit_ref'] = file_ref(write_json(output/(branch+'_rule_audit.json'), projection))
        write_json(output/(branch+'_context.json'), context)
        branches[branch]={'context':file_ref(output/(branch+'_context.json')), 'dataset_ids':[d['id'] for d in assigned[branch]],
            'task_ids':sorted(selected_ids),'status':context['status'],'model_release':False}
    routing = {'schema_version':'1.0','module':'clinical_dispatch','created_at':utcnow(),
        'status':'WAITING_FOR_HUMAN_REVIEW' if require_eda else 'DRAFT_NOT_RELEASED',
        'branches':branches,'file_routes':routes,'unassigned_datasets':unassigned,
        'unassigned_tasks':[t for t in tasks if not task_branch(t)],
        'parallel_groups':[[b+':task_input_preparation' for b in BRANCHES if b in active_branches]],
        'dependencies':[{'from':'pk:reviewed_exposure_predictions','to':'index:calculation',
            'condition':'Applies only when confirmed exposure source is REQUIRES_PK_PREDICTIONS'},
            {'from':'index:qualified_matched_PD','to':'index:response_model_comparison','condition':'If a reviewed task requests a response-model comparison'}],
        'why_cannot_fit':['Routing is not scientific model-input release. Inspect the branch-specific missing materials.',
                         'Unclassified source tables remain unassigned; human/benchmark data remain reserved.'],
        'source_snapshot':snapshot_ref,'scientific_release':False}
    write_json(output/'routing_plan.json',routing)
    report = {'schema_version':'1.0','module':'clinical_dispatch','status':routing['status'],
        'summary':{b:{'datasets':len(assigned[b]),'tasks':len(branches[b]['task_ids'])} for b in BRANCHES},
        'unknowns':questions['unknowns'],'unassigned_datasets':unassigned,
        'why_cannot_pass':routing['why_cannot_fit'],'branches':branches,
        'index_exposure_source':exposure_source,'scientific_release':False,'fit_ready':False,
        'question_generator':derived['generator_version'],'question_generation_method':derived['method']}
    write_json(output/'dispatch_report.json',report)
    for path in output.glob('*.json'): files.append({'name':path.name,**file_ref(path),'kind':'context'})
    write_json(output/'artifact_manifest.json',{'files':files})
    return report


def execute(snapshot_ref, spec_ref, output):
    check_ref(spec_ref); spec=read_json(spec_ref['path'])
    if not spec.get('confirmed') or not spec.get('reviewer','').strip():
        raise PipelineError('DISPATCH_QUESTIONS_UNCONFIRMED','Confirm the clinical questions and exposure dependency before running dispatch.')
    if spec.get('index_exposure_source') == 'UNKNOWN':
        raise PipelineError('DISPATCH_DEPENDENCY_UNCONFIRMED','Confirm whether index calculations use matched exposure or require PK predictions.')
    snapshot, *_=inputs(snapshot_ref,require_eda=True)
    signatures={k:n['output_signature'] for k,n in snapshot['nodes'].items()}
    if spec.get('upstream_signatures') != signatures:
        raise PipelineError('DISPATCH_CONFIRMATION_STALE','Clinical questions were confirmed against different upstream outputs. Refresh and confirm the current draft.')
    result=build(snapshot_ref,output,spec['values'],spec['index_exposure_source'],require_eda=True)
    inputs(snapshot_ref,require_eda=True)
    return result
