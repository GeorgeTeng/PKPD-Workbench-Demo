"""Explicit source-preserving Data demo; scientific adequacy remains unassessed.

This profile reuses native imports, labels, version-bound Human gates, preparation
and program QC. It does not impersonate an independent scientific review.
"""
from pathlib import Path
from .common import read_json, write_json, PipelineError
from .adequacy import file_ref, check_ref
from . import preparation_checks, unresolved_ledger

PROFILE = 'SOURCE_PRESERVING_DEMO_1.0'
SCOPE = 'SOURCE_ORGANIZATION_AND_TECHNICAL_QC_ONLY'


def restore(main_path, references, output):
    """Carry completed, bound inputs into a new plan without claiming a new call."""
    bindings = preparation_checks.freeze_refs(references)
    values = {key: read_json(ref['path']) for key, ref in references.items()}
    if values['main'] != read_json(main_path):
        raise PipelineError('DEMO_RETAINED_CONTEXT_CHANGED', 'Retained labels belong to a different Context/Rules version.')
    req, labels = values['requirements'], values['labels']
    if req['main'] != references['main'] or req['inventory'] != references['inventory'] or labels['requirements'] != references['requirements']:
        raise PipelineError('DEMO_RETAINED_INPUTS_CHANGED', 'Retained labels have inconsistent source bindings.')
    preparation_checks.freeze_refs(values)
    folder = Path(output)
    prior_inventory = values['inventory']
    if prior_inventory.get('main') and read_json(prior_inventory['main']['path']) != values['main']:
        raise PipelineError('DEMO_RETAINED_INPUTS_CHANGED', 'Inventory binds different Context content.')
    inventory = file_ref(write_json(folder/'inventory.json', {**prior_inventory, 'main': file_ref(main_path)}))
    requirements = file_ref(write_json(folder/'requirements.json', {**req, 'main': file_ref(main_path), 'inventory': inventory}))
    write_json(folder/'data_labels.json', {**labels, 'requirements': requirements})
    write_json(folder/'retained_inputs.json', {'demo_profile': PROFILE, 'input_refs': references,
        'new_model_calls': False, 'original_model': labels.get('model'), 'scientific_release': False})
    preparation_checks.verify_frozen(bindings)


def validated(report):
    checks = report.get('technical_review', {})
    return (report.get('demo_profile') == PROFILE and report.get('execution_scope') == SCOPE
            and checks.get('executor') == 'HOST_PROGRAM' and checks.get('decision') == 'PASS'
            and report.get('scientific_release') is False and report.get('fit_ready') is False)


def assess(run, main_path, inventory_path, requirements_path, labels_path, output, **_):
    from . import data_agents as da
    main, inv, _, _ = da.context_input(main_path, inventory_path)
    req, labels = read_json(requirements_path), read_json(labels_path)
    refs = [file_ref(p) for p in (main_path, inventory_path, requirements_path, labels_path)]
    bindings = preparation_checks.freeze_refs(*refs, main, inv, req, labels)
    if req['main'] != refs[0] or req['inventory'] != refs[1] or labels['requirements'] != refs[2]:
        raise PipelineError('DEMO_DATA_BINDING_CHANGED', 'Data labels and requirements do not bind these inputs.')
    da.exact([a['item_id'] for a in req['access']], [i['id'] for i in inv['items']], 'Access accounting')
    da.exact([c['item_id'] for c in labels['coverage']], [i['id'] for i in inv['items']], 'Read coverage accounting')
    allowed = {a['item_id'] for a in req['access'] if a['disposition'] == 'REVIEW_DATA'}
    labelled = {l['item_id'] for l in labels['labels']}
    if not labelled <= allowed or not allowed <= labelled:
        raise PipelineError('DEMO_LABEL_COVERAGE', 'Every admitted source must have its retained label; restricted bodies cannot enter preparation.')
    findings = [*inv['findings'], *req['findings'], *labels['findings']]
    if main.get('demo_context_review_ref'):
        from ctxcomp.demo_review import verify as verify_context_deferral
        findings += verify_context_deferral(main['demo_context_review_ref'])['findings']
    findings.append({'code': 'SCIENTIFIC_ADEQUACY_DEFERRED', 'affected_id': 'DATA',
        'reason': 'User selected technical demo scope. Scientific requirement coverage, model readiness and prediction validity were not assessed in this profile.',
        'needed_material': 'Review requirements and retained source issues before EDA and modeling.',
        'required_by': 'BEFORE_EDA', 'severity': 'HUMAN_REVIEW'})
    folder = Path(output)
    items = unresolved_ledger.from_context(main, refs[0])
    items += unresolved_ledger.from_findings(findings, 'DEMO_DATA', str(folder/'adequacy.json'), 'BEFORE_QC', items, 'DEMO_DATA', 'BEFORE_EDA')
    ledger = file_ref(write_json(folder/'unresolved_ledger.json', unresolved_ledger.ledger(items, 'DEMO_DATA', refs)))
    requirements = [{**n, 'status': 'UNRESOLVED', 'coverage_status': 'NOT_ASSESSED_IN_DEMO',
                     'source_ids': [], 'reason': 'Retained for later scientific review.',
                     'needed_material': 'Review source-backed coverage before the dependent analysis.', 'deferred_outputs': []} for n in req['requirements']]
    report = {'schema_version': da.VERSION, 'module': 'data_adequacy', 'agent_workflow_version': da.VERSION,
        'demo_profile': PROFILE, 'execution_scope': SCOPE,
        'assessment_status': 'SUFFICIENT_FOR_DEFINED_SCOPE', 'can_enter_qc': True, 'requires_human_review': True,
        'technical_review': {'executor': 'HOST_PROGRAM', 'decision': 'PASS',
            'checks': ['Source hashes verified', 'Access accounted for every item', 'Permitted labels accounted for', 'Upstream versions match']},
        'llm_review': {'validated': False, 'decision': 'NOT_RUN_IN_DEMO'},
        'tasks': req['tasks'], 'requirements': requirements, 'findings': findings, 'why_cannot_pass': [],
        'missing_materials': findings, 'input_refs': refs, 'unresolved_ledger': ledger,
        'models': {'label': labels.get('model'), 'review': 'NOT_RUN_IN_DEMO', 'same': False},
        'fit_ready': False, 'human_prediction_validated': False, 'scientific_release': False}
    report['requirement_matrix'] = file_ref(write_json(folder/'requirement_matrix.json', {
        'demo_profile': PROFILE, 'status': 'NOT_ASSESSED_IN_DEMO', 'requirements': requirements, 'scientific_release': False}))
    report['condition_checklist'] = file_ref(write_json(folder/'condition_checklist.json', {
        'demo_profile': PROFILE, 'status': 'NOT_ASSESSED_IN_DEMO', 'conditions': [], 'scientific_release': False}))
    preparation_checks.verify_frozen(bindings)
    write_json(folder/'adequacy.json', report)
    write_json(folder/'assessment.json', {'tasks': req['tasks'], 'requirements': requirements, 'demo_profile': PROFILE})
    write_json(folder/'review.json', {'executor': 'HOST_PROGRAM', 'technical_review': report['technical_review'],
        'scientific_review': 'NOT_RUN_IN_DEMO', 'findings': findings, 'demo_profile': PROFILE})
    write_json(folder/'qc_context.json', {'schema_version': da.VERSION, 'module': 'data_preparation',
        'demo_profile': PROFILE, 'execution_scope': SCOPE, 'assessment': file_ref(folder/'adequacy.json'),
        'upstream_main': refs[0], 'inventory': refs[1], 'requirements': refs[2], 'labels': refs[3],
        'can_enter_qc': True, 'fit_ready': False, 'task_requirements': requirements,
        'files': main['data']['files'], 'unresolved_ledger': ledger})
    da.write_findings(folder, findings)
    da.write_checkpoint(folder, report, findings, items)
    (folder/'report.md').write_text('# Data technical demo\n\nSource bindings, access and label accounting passed. '
        'This permits source-preserving preparation after the Human gate. Scientific input coverage remains unassessed. '
        'All inherited findings remain open; their original severity and required phase are retained.\n', encoding='utf-8')


def plan_preparation(run, context_path, output, **_):
    from . import data_agents as da
    context, main, inv, labels = da.prepared_input(context_path)
    report = read_json(context['assessment']['path'])
    if not validated(report):
        raise PipelineError('DEMO_PROFILE_REQUIRED', 'An approved technical-demo assessment is required.')
    da.dp_gate_evidence(context)
    req = read_json(context['requirements']['path'])
    allowed = {a['item_id'] for a in req['access'] if a['disposition'] == 'REVIEW_DATA'}
    tables = []
    for item in inv['items']:
        if item['kind'] != 'TABLE' or item['id'] not in allowed:
            continue
        headers = item['descriptor']['headers']
        usable = all(isinstance(h, str) and h.strip() for h in headers) and len(headers) == len(set(headers))
        tables.append({'item_id': item['id'], 'action': 'PREPARE' if usable else 'HOLD', 'columns': [], 'evidence': [],
            'reason': 'Preserve original columns and raw values; no unit conversion, inference, joining or imputation.' if usable else 'Ambiguous headers require source review; table held without changing its source.'})
    bindings = preparation_checks.freeze_refs(file_ref(context_path), context, main, inv, req, labels)
    write_json(output, {'schema_version': da.VERSION, 'demo_profile': PROFILE, 'executor': 'HOST_PROGRAM',
        'context': file_ref(context_path), 'human_approval': context['approval'], 'input_bindings': bindings,
        'tables': tables, 'findings': [], 'scientific_release': False})


def publish_data(run, execution_path, metadata_path, output, **_):
    from . import data_agents as da
    execution, metadata = read_json(execution_path), read_json(metadata_path)
    bindings = preparation_checks.freeze_refs(file_ref(execution_path), file_ref(metadata_path), execution, metadata)
    if metadata.get('executor') != 'HOST_PROGRAM' or metadata['execution'] != file_ref(execution_path):
        raise PipelineError('DEMO_QC_BINDING', 'Metadata validation does not bind this execution.')
    context, main, inv, labels = da.prepared_input(execution['context']['path'])
    assessment = read_json(context['assessment']['path'])
    if not validated(assessment):
        raise PipelineError('DEMO_PROFILE_REQUIRED', 'Technical-demo assessment is missing.')
    qc = read_json(execution['program_qc']['path'])
    if qc['decision'] != 'PASS' or execution.get('source_values_preserved') is not True:
        raise PipelineError('DEMO_PROGRAM_QC_FAILED', 'Source preservation failed mechanical QC; inspect the actual records.')
    manifest = read_json(execution['manifest']['path'])
    da.exact([r['dataset_id'] for r in metadata['reviews']], [d['id'] for d in manifest['datasets']], 'Metadata coverage')
    findings = [*assessment['findings'], *read_json(execution['qc_findings']['path'])['findings']]
    for r in metadata['reviews']:
        check_ref(r['metadata_ref'])
        findings += r['review']['findings']
    folder = Path(output)
    items = read_json(assessment['unresolved_ledger']['path'])['items']
    items += unresolved_ledger.from_findings(findings, 'DEMO_HANDOFF', str(folder/'data_report.json'), 'BEFORE_EDA', items)
    ledger = file_ref(write_json(folder/'unresolved_ledger.json', unresolved_ledger.ledger(items, 'DEMO_HANDOFF', bindings)))
    open_items, limitations = unresolved_ledger.forwarded(items)
    review = {'demo_profile': PROFILE, 'executor': 'HOST_PROGRAM', 'technical_decision': 'PASS',
        'scientific_decision': 'NOT_RUN_IN_DEMO', 'scope': SCOPE, 'findings': findings,
        'program_qc': execution['program_qc'], 'metadata_validation': file_ref(metadata_path)}
    for destination in ('eda', 'pk', 'index'):
        write_json(folder/'handoffs'/(destination+'_context.json'), {
            'schema_version': da.VERSION, 'module': destination, 'demo_profile': PROFILE,
            'status': 'PENDING_SCIENTIFIC_REVIEW', 'allowed_action': 'INSPECT_SOURCE_DATA_ONLY',
            'execution_authorized': False, 'scientific_release': False, 'fit_ready': False,
            'files': [], 'inspection_manifest': execution['manifest'],
            'task_requirements': read_json(context['requirements']['path'])['requirements'],
            'unknowns': findings, 'unresolved_items': open_items, 'accepted_limitations': limitations,
            'unresolved_ledger': ledger, 'rules_ref': main['project_rules_ref'],
            'preparation_evidence': {k: execution[k] for k in ('plan', 'cleaning_log', 'program_qc', 'data_dictionary', 'qc_findings')}})
    summary = {'datasets': len(manifest['datasets']),
               **{k: sum(d['summary'][k] for d in manifest['datasets']) for k in ('source_records','retained_records','quarantined_records')}}
    report = {'schema_version': da.VERSION, 'module': 'data_preparation', 'agent_workflow_version': da.VERSION,
        'demo_profile': PROFILE, 'execution_scope': SCOPE, 'status': 'DEMO_TECHNICAL_DATA_READY',
        'assessment_status': 'SUFFICIENT_FOR_DEFINED_SCOPE', 'requires_human_review': True,
        'cleaning_complete': True, 'technical_processing_complete': True, 'handoff_review_complete': False,
        'cleaning_complete_definition': 'Source-preserving export and program QC completed; scientific normalization and analysis readiness remain pending.',
        'fit_ready': False, 'scientific_release': False, 'human_prediction_validated': False,
        'released_datasets': [], 'sample_size_status': 'NOT_ESTABLISHED', 'findings': findings,
        'why_cannot_pass': [], 'missing_materials': findings, 'summary': summary,
        'normalization_manifest': execution['manifest'], 'partition_manifest': execution['partition_manifest'],
        'unresolved_ledger': ledger, 'program_qc': execution['program_qc'],
        'metadata_validation': file_ref(metadata_path), 'upstream': {'assessment': context['assessment'], 'main': context['upstream_main']},
        'agent_reviews': {'handoff': file_ref(write_json(folder/'handoff_review.json', review))}}
    preparation_checks.verify_frozen(bindings)
    write_json(folder/'data_report.json', report)
    write_json(folder/'main.json', report)
    da.write_findings(folder, findings)
    (folder/'report.md').write_text('# Data technical demo\n\nSource-preserving preparation and mechanical QC completed. '
        'Scientific adequacy and downstream analysis remain pending. Inspect all findings and the final Human gate.\n', encoding='utf-8')
