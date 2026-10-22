"""Thin task/data router; ContextBuilder assembles source-bound branch handoffs.

Drafts may be inspected after completed EDA. Execution requires approved EDA and
confirmed questions, and the resulting dispatch still has its own review gate.
No concentration fitting, human holdout access or response join occurs here.
"""
import re
from pathlib import Path

from . import context_builder
from .dispatch_context import index_candidates, rules_for, project_reference_advice
from .common import PipelineError, read_json, write_json, utcnow
from .adequacy import check_ref, file_ref
from .workflow_definition import CLINICAL_FIELDS
from .clinical_questions import derive_questions, pathogen_scope, matches_pathogen

BRANCHES = ('pk', 'index', 'clinical')


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
    source = dict(snapshot=snapshot, main=main, assessment=assessment, eda=eda,
                  advice=advice, values=values, derived=derived, exposure_source=exposure_source,
                  require_eda=require_eda, task_branches={t['id']:task_branch(t) for t in tasks})
    bindings = {'snapshot': snapshot_ref, 'questions': file_ref(output/'clinical_questions.json')}
    for stage, node in snapshot['nodes'].items():
        for i, artifact in enumerate(node.get('artifacts', [])):
            bindings[f'{stage}:{i}'] = artifact
    for branch in BRANCHES:
        assignment = {'tasks':[t for t in tasks if task_branch(t) == branch],
                      'datasets':assigned[branch]}
        bundle = context_builder.build_branch_handoff(
            branch, source=source, assignment=assignment, output=output, input_bindings=bindings)
        context = bundle['context']
        context['context_manifest_ref'] = file_ref(write_json(
            output/(branch+'_context_manifest.json'), bundle['context_manifest']))
        context_builder.verify_branch_handoff(context)
        write_json(output/(branch+'_context.json'), context)
        branches[branch] = {'context':file_ref(output/(branch+'_context.json')),
            'context_manifest':context['context_manifest_ref'],
            'dataset_ids':[d['id'] for d in assigned[branch]],
            'task_ids':sorted(t['id'] for t in assignment['tasks']),
            'status':context['status'], 'model_release':False}
    # Recheck earlier branches before publishing the combined handoff.
    for branch in branches.values():
        check_ref(branch['context'])
        context_builder.verify_branch_handoff(read_json(branch['context']['path']))
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
    for path in sorted(output.glob('*.json')):
        # On regeneration the old manifest must not bind its own prior hash.
        if path.name != 'artifact_manifest.json':
            files.append({'name':path.name, **file_ref(path), 'kind':'context'})
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
