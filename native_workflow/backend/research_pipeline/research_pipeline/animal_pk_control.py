"""Scoped PK agent execution and bounded model searches.

The UI schedules these contracts through LangGraph -> Prefect -> Snakemake.
Each logical task makes a fresh provider call. Only trusted R code fits models.
"""
import copy
from pathlib import Path
from typing import TypedDict
from uuid import uuid4

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.sqlite import SqliteSaver

from .animal_pk import digest
from .animal_pk_agents import invoke_agent
from .adequacy import check_ref, file_ref
from .common import PipelineError, read_json, write_json, utcnow

READY = {'AGENT_COMPLETED', 'CANDIDATE_SEARCH_COMPLETED', 'PENDING_HUMAN_REVIEW'}


def validate_plan(plan):
    if plan.get('plan_signature') != digest({k: v for k, v in plan.items() if k != 'plan_signature'}):
        raise PipelineError('PK_PLAN_CHANGED', 'The PK plan changed. Refresh the controller before continuing.')
    for reference in plan['source_refs']:
        check_ref(reference)


def candidate_for(plan, candidate_id):
    for unit in plan['analysis_units']:
        for candidate in unit['candidates']:
            if candidate['id'] == candidate_id:
                return unit, candidate
    raise PipelineError('PK_UNKNOWN_CANDIDATE', 'Select a model candidate in the current PK plan.')


def qualification_template(plan, candidate_id):
    unit, candidate = candidate_for(plan, candidate_id)
    parameters = ['CL', 'VC'] + (['Q', 'VP'] if candidate['compartments'] >= 2 else []) + (['Q2', 'VP2'] if candidate['compartments'] == 3 else [])
    return {'reviewer': '', 'confirmed': False, 'max_attempts': 1,
        'confirmation_scope': 'Confirm source identity, dosing, units, data transformation and permitted configurations; this does not accept a fitted model.',
        'configurations': [{'configuration_id': 'config_1', 'candidate_id': candidate_id,
            'species': unit['species'], 'analysis_id': unit['analysis_id'], 'compartments': candidate['compartments'],
            'fit_ready': True, 'input_refs': [unit['data']['data'], unit['data']['metadata']],
            'normalized_data_ref': {'path': '', 'sha256': ''},
            'source_provenance': {'assigned_dataset_ref': unit['data']['data'],
                'transformation_description': '', 'dose_evidence': '', 'identity_evidence': ''},
            'fit_config': {'engine': 'nlmixr2', 'estimator': 'focei', 'error_model': 'combined',
                'initial': {k: None for k in parameters}, 'bounds': {k: [None, None] for k in parameters},
                'random_effects': [], 'omega_initial': {},
                'residual_initial': {'additive': None, 'proportional': None},
                'seed': 123, 'cores': 1, 'max_outer_iterations': 200}}]}


def qualification_record(folder, candidate_id):
    pointer = Path(folder) / 'qualifications' / candidate_id / 'current.json'
    if not pointer.is_file():
        return None
    reference = read_json(pointer)['qualification_ref']
    check_ref(reference)
    return reference


def save_qualification(plan, candidate_id, envelope, folder, approval_ref):
    """An explicit human confirmation binds data qualification, never fit acceptance."""
    from .animal_pk_nlmixr2 import validate_qualification
    validate_plan(plan); check_ref(approval_ref)
    unit, candidate = candidate_for(plan, candidate_id)
    if envelope.get('confirmed') is not True or not str(envelope.get('reviewer', '')).strip():
        raise PipelineError('PK_QUALIFICATION_CONFIRMATION_REQUIRED',
            'Confirm the data identity, dosing, transformation and fitting configurations, and enter a reviewer. Fitted model selection remains a later review.')
    configurations = copy.deepcopy(envelope.get('configurations', []))
    limit = envelope.get('max_attempts')
    if not configurations or type(limit) is not int or not 1 <= len(configurations) <= limit <= 30:
        raise PipelineError('PK_INVALID_SEARCH_BUDGET', 'Provide 1–30 explicit configurations and a finite attempt budget covering every configuration.')
    ids = [q.get('configuration_id') for q in configurations]
    if any(not isinstance(x, str) or not x or not x.replace('_', '').replace('-', '').isalnum() for x in ids) or len(set(ids)) != len(ids):
        raise PipelineError('PK_CONFIG_ID_REQUIRED', 'Each configuration needs a unique ID using letters, numbers, hyphens or underscores.')
    destination = Path(folder) / 'qualifications' / candidate_id / uuid4().hex[:16]
    for q in configurations:
        for key, expected in [('candidate_id', candidate_id), ('species', unit['species']),
                              ('analysis_id', unit['analysis_id']), ('compartments', candidate['compartments'])]:
            if q.get(key) != expected:
                raise PipelineError('PK_QUALIFICATION_SCOPE', 'Fitting contract has a different ' + key + '.')
        provenance = q.get('source_provenance', {})
        if provenance.get('assigned_dataset_ref') != unit['data']['data'] or any(not str(provenance.get(k, '')).strip()
                for k in ['transformation_description', 'dose_evidence', 'identity_evidence']):
            raise PipelineError('PK_SOURCE_MAPPING_REQUIRED', 'Describe the data transformation, dose evidence and verified animal identities, and bind them to the assigned dataset.')
        check_ref(q['normalized_data_ref'])
        q['input_refs'] = list({r['path']: r for r in [*q.get('input_refs', []), unit['data']['data'],
            unit['data']['metadata'], q['normalized_data_ref']]}.values())
        for reference in q['input_refs']:
            check_ref(reference)
        # Preserve source permission and species even when a normalization file is supplied.
        normalized = read_json(q['normalized_data_ref']['path'])
        meta = normalized.get('metadata', {})
        if meta.get('species') != unit['species'] or meta.get('permission') != 'DEVELOPMENT_CANDIDATE':
            raise PipelineError('PK_DATA_PERMISSION', 'Normalized data must remain animal development data for this species.')
        for key in ['matrix', 'exposure_basis']:
            original = unit['metadata'].get(key)
            if original not in {None, '', 'UNKNOWN', 'NOT_FOUND', 'UNVERIFIED'} and meta.get(key) != original:
                raise PipelineError('PK_DATA_DEFINITION_CHANGED', 'Normalized ' + key + ' contradicts the assigned source metadata. Return the data transformation to QC.')
        level = str(unit['metadata'].get('record_level', '')).upper()
        if any(word in level for word in ['SUMMARY', 'MEAN', 'COMPOSITE', 'POOLED']):
            raise PipelineError('PK_UNSUPPORTED_SAMPLING_DESIGN', 'Summary or composite records cannot be relabeled as individual longitudinal observations. Use a suitable reviewed fitting adapter.')
        approval = {'status': 'APPROVED', 'at': utcnow(), 'reviewer': envelope['reviewer'],
            'confirmed': True, 'scope': 'DATA_AND_CONFIGURATION_ONLY_NOT_MODEL_ACCEPTANCE',
            'plan_signature': plan['plan_signature'], 'candidate_id': candidate_id,
            'configuration_id': q['configuration_id'], 'input_refs': q['input_refs'],
            'normalized_data_ref': q['normalized_data_ref'], 'dispatch_approval_ref': approval_ref,
            'source_provenance': provenance}
        q['approval_ref'] = file_ref(write_json(destination / (digest(q['configuration_id'])[:12] + '_approval.json'), approval))
        validate_qualification(q)
    value = {**envelope, 'configurations': configurations, 'plan_signature': plan['plan_signature'],
             'candidate_id': candidate_id, 'at': utcnow(), 'model_release': False}
    reference = file_ref(write_json(destination / 'qualification.json', value))
    write_json(Path(folder) / 'qualifications' / candidate_id / 'current.json', {'qualification_ref': reference})
    return {'qualification_ref': reference, 'qualification': value,
            'validation': {'valid': True, 'configuration_count': len(configurations), 'model_release': False}}


def latest_runs(runs):
    latest = {}
    for run in sorted(runs, key=lambda r: (r.get('created_at') or '', r['id'])):
        latest[run['agent_id']] = run
    return latest


def usable(run):
    if not run or run.get('status') in {'QUEUED', 'RUNNING', 'PAUSED', 'STOPPED_ON_ERROR'}:
        return False
    result = run.get('result') or {}
    if result.get('status') not in READY:
        return False
    if run.get('result_ref'):
        check_ref(run['result_ref'])
    return True


def run_current(plan, folder, latest, agent_id, visiting=None):
    """Review evidence must still match the full upstream chain, not just its last edge."""
    visiting=set(visiting or ())
    if agent_id in visiting:
        return False
    visiting.add(agent_id)
    run=latest.get(agent_id)
    if not usable(run):return False
    contract=next((a for a in plan['agents'] if a['id']==agent_id),None)
    if not contract:return False
    if contract['role']=='candidate_model' and run['result'].get('qualification_ref') != qualification_record(folder,contract['candidate']['id']):
        return False
    for dependency in contract['depends_on']:
        if dependency.startswith('human_'):continue  # The signed human boundary is checked separately below.
        if run['result'].get('upstream_run_ids',{}).get(dependency)!=latest.get(dependency,{}).get('id'):
            return False
        if not run_current(plan,folder,latest,dependency,visiting):return False
    return True


def review_bundle(plan, folder, runs, species):
    from .animal_pk_comparison import compare_results
    spec = next((s for s in plan['species'] if s['species'] == species), None)
    if not spec:
        raise PipelineError('PK_UNKNOWN_SPECIES', 'This species is not in the current PK plan.')
    latest = latest_runs(runs); results = []; run_ids = []
    for agent_id in spec['comparison_agents']:
        run = latest.get(agent_id)
        if not run_current(plan,folder,latest,agent_id):
            return None
        for dep, used_id in run['result'].get('upstream_run_ids', {}).items():
            if latest.get(dep, {}).get('id') != used_id:
                return None
        for reference in run['result'].get('fit_refs', []):
            check_ref(reference); results.append({**read_json(reference['path']),'fit_result_ref':reference})
        run_ids.append(run['id'])
    if not results:
        return None
    report = compare_results(results)
    report['at'] = max((latest[a].get('finished_at') or latest[a].get('created_at', '') for a in spec['comparison_agents']))
    report['source_run_ids'] = run_ids
    report['plan_signature'] = plan['plan_signature']
    report['output_signature'] = digest({k: v for k, v in report.items() if k != 'output_signature'})
    return report


def review_release(plan, folder, runs, species):
    report = review_bundle(plan, folder, runs, species)
    if not report:
        return None
    path = Path(folder) / 'reviews' / digest(species)[:16] / report['output_signature'][:16] / 'review_decision.json'
    if not path.is_file():
        return None
    release = read_json(path)
    if release.get('model_release') is not True or release.get('comparison_signature') != report['output_signature']:
        return None
    # Revalidate numerical evidence at the handoff boundary.
    for row in report['rows']:
        for reference in row.get('evidence_refs', {}).values():
            check_ref(reference)
    accepted = path.parent / 'accepted_models.json'
    return file_ref(accepted) if accepted.is_file() else None


def control_snapshot(plan, folder, runs):
    validate_plan(plan); latest = latest_runs(runs); states = {}; reviews = {}
    busy = any(r.get('status') in {'QUEUED', 'RUNNING'} for r in runs)
    for species in plan['species']:
        report = review_bundle(plan, folder, runs, species['species'])
        reviews[species['species']] = {'ready': bool(report), 'approved': bool(review_release(plan, folder, runs, species['species']))}
    # Evaluate the DAG in declaration order; managed children do not authorize a bypass.
    for agent in plan['agents']:
        last = latest.get(agent['id']); reason = None
        if agent.get('managed_by'):
            reason = 'Run the containing model block; this agent is invoked fresh within its bounded LangGraph loop.'
        for dependency in agent['depends_on']:
            if dependency.startswith('human_'):
                species = next(s['species'] for s in plan['species'] if s['human_gate'] == dependency)
                if not reviews[species]['approved']:
                    reason = 'Select the species models in Human model selection before releasing the species report.'
            elif not usable(latest.get(dependency)) or states.get(dependency, {}).get('status') == 'STALE':
                reason = 'Complete upstream agent ' + dependency + ' and resolve its requested changes.'
        stale = bool(last and (any(latest.get(a, {}).get('id') != r for a, r in (last.get('result') or {}).get('upstream_run_ids', {}).items())
            or any(states.get(dep,{}).get('status')=='STALE' for dep in agent['depends_on'])))
        if last and any(dep.startswith('human_') for dep in agent['depends_on']) and reason:
            stale=True
        if agent['role'] == 'candidate_model':
            reference = qualification_record(folder, agent['candidate']['id'])
            if not reference:
                reason = 'Provide a reviewed fitting contract with verified individual IV data, dosing, units and permitted nlmixr2 configurations.'
            elif last and (last.get('result') or {}).get('qualification_ref') != reference:
                stale = True
        if busy and not reason:
            reason = 'Another PK run is active. Pause it or wait for its result.'
        states[agent['id']] = {'can_run': reason is None, 'blocked_reason': reason,
            'status': 'STALE' if stale else (last.get('result') or {}).get('status', last.get('status')) if last else 'NOT_STARTED',
            'last_run_id': last['id'] if last else None, 'managed_by': agent.get('managed_by')}
        if agent.get('managed_by'):
            parent=latest.get(agent['managed_by'])
            calls=[c for c in (parent or {}).get('result',{}).get('agent_calls',[]) if c.get('agent_id')==agent['id']]
            if calls:
                states[agent['id']].update(status='AGENT_COMPLETED',last_run_id=parent['id'],invocations=len(calls))
    return {'agent_states': states, 'review': reviews,
        'capabilities': {'fresh_agents': True, 'bounded_candidate_loop': True, 'numerical_engine': 'nlmixr2',
            'controller': 'LangGraph', 'scheduler': 'Prefect', 'file_executor': 'Snakemake',
            'supported_fitting_scope': 'Qualified individual longitudinal IV bolus/infusion; unsupported designs stop with a specific explanation.',
            'automatic_scientific_acceptance': False}}


def make_agent_request(plan, agent_id, folder, instruction, upstream_runs, approval_ref):
    check_ref(approval_ref); snapshot = control_snapshot(plan, folder, upstream_runs)
    if agent_id not in snapshot['agent_states']:
        raise PipelineError('PK_UNKNOWN_AGENT', 'Select an agent from the current PK plan.')
    state = snapshot['agent_states'][agent_id]
    if not state['can_run']:
        raise PipelineError('PK_AGENT_BLOCKED', state['blocked_reason'])
    contract = next(a for a in plan['agents'] if a['id'] == agent_id)
    latest = latest_runs(upstream_runs); upstream = {}; upstream_ids = {}; refs = [approval_ref]
    for dependency in contract['depends_on']:
        if dependency.startswith('human_'):
            species = next(s['species'] for s in plan['species'] if s['human_gate'] == dependency)
            reference = review_release(plan, folder, upstream_runs, species)
        else:
            run = latest[dependency]; reference = run.get('result_ref')
            upstream_ids[dependency] = run['id']
        if not reference:
            raise PipelineError('PK_MISSING_UPSTREAM_REF', 'Upstream output has no verifiable file reference.')
        check_ref(reference); refs.append(reference); upstream[dependency] = reference
    request = {'agent': contract, 'plan_signature': plan['plan_signature'], 'upstream_refs': upstream,
        'upstream_run_ids': upstream_ids, 'instruction': instruction or '', 'approval_ref': approval_ref,
        'created_at': utcnow(), 'source_refs': refs, 'model_release': False}
    if contract['role'] in {'input_qualification', 'model_review'}:
        unit = next(u for u in plan['analysis_units'] if u['analysis_id'] == contract['scope']['analysis_id'])
        request['qualification_refs'] = [r for c in unit['candidates'] if (r := qualification_record(folder, c['id']))]
        request['source_refs'].extend(request['qualification_refs'])
    if contract['role'] == 'candidate_model':
        _, candidate = candidate_for(plan, contract['candidate']['id'])
        request['qualification_ref'] = qualification_record(folder, candidate['id'])
        request['source_refs'].append(request['qualification_ref'])
        request['step_contracts'] = {s['role']: next(a for a in plan['agents'] if a['id'] == s['agent_id']) for s in candidate['steps']}
    destination = Path(folder) / 'requests' / uuid4().hex[:16] / 'request.json'
    return file_ref(write_json(destination, request))


class SearchState(TypedDict, total=False):
    position: int
    selection: dict
    configuration: dict
    fit_ref: dict
    fits: list[dict]
    calls: list[dict]
    attempt_ok: bool
    issues: list[str]
    status: str


def candidate_search(request, folder, generator=None, fit_adapter=None):
    from .animal_pk_nlmixr2 import fit_adapter as default_adapter, validate_qualification
    fit_adapter = fit_adapter or default_adapter
    reference = request['qualification_ref']; check_ref(reference)
    envelope = read_json(reference['path']); configurations = envelope['configurations']
    if not 1 <= len(configurations) <= envelope['max_attempts'] <= 30:
        raise PipelineError('PK_INVALID_SEARCH_BUDGET', 'The search needs a finite, validated configuration list.')
    if envelope.get('plan_signature') != request['plan_signature']:
        raise PipelineError('PK_QUALIFICATION_STALE', 'The reviewed fitting contract belongs to another plan.')
    for q in configurations:
        validate_qualification(q)
    contracts = request['step_contracts']; folder = Path(folder)
    def call(role, inputs):
        return invoke_agent(contracts[role], inputs, folder / 'agents' / role, generator)
    def current(state):
        return configurations[state['position']]
    def select(state):
        q = current(state)
        c = call('configuration_selection', {'qualification': q, 'requested_changes': request['instruction'],
            'previous_attempt_refs': state.get('fits', []),
            'previous_attempts': [read_json(r['path']) for r in state.get('fits', [])],
            'configuration_number': state['position'] + 1,
            'total_configurations': len(configurations)})
        return {'selection': c, 'attempt_ok': c['response']['decision'] == 'CONTINUE',
            'calls': state.get('calls', []) + [c]}
    def configure(state):
        q = current(state)
        c = call('estimation_configuration', {'qualification': q, 'selection': state['selection']['response'],
            'normalized_data': read_json(q['normalized_data_ref']['path'])})
        return {'configuration': c, 'attempt_ok': c['response']['decision'] == 'CONTINUE', 'calls': state['calls'] + [c]}
    def fit_and_check(state):
        q = current(state); attempt = folder / 'attempts' / digest(q['configuration_id'])[:12]
        attempt.mkdir(parents=True, exist_ok=True)
        # All executable model syntax and numbers come from the validated contract.
        result = fit_adapter(q, state['configuration']['response_ref'], attempt)
        if result.get('candidate_id') != q['candidate_id']:
            raise PipelineError('PK_RESULT_SCOPE_CHANGED', 'The numerical tool returned another candidate.')
        result['base_candidate_id'] = q['candidate_id']; result['configuration_id'] = q['configuration_id']
        result['candidate_id'] = q['candidate_id'] + '__' + q['configuration_id']
        raw_ref = file_ref(write_json(attempt / 'numerical_result.json', result))
        c = call('fit_self_check', {'fit_result': result, 'qualification': q, 'numerical_result_ref': raw_ref})
        # A language model may block, but can never promote failed numerical checks.
        if c['response']['decision'] != 'CONTINUE':
            result['diagnostic_status'] = 'AGENT_REVIEW_REQUIRED'
        result['agent_self_check_ref'] = c['response_ref']
        result['issues'] = list(result.get('issues', [])) + c['response']['issues'] + c['response']['requested_changes']
        fitted_ref = file_ref(write_json(attempt / 'fit_result.json', result))
        return {'fit_ref': fitted_ref, 'fits': state['fits'] + [fitted_ref], 'calls': state['calls'] + [c]}
    def skipped(state):
        q = current(state); c = state.get('configuration') if state.get('configuration', {}).get('response', {}).get('decision') != 'CONTINUE' else state['selection']
        c = c or state['selection']
        record = {'candidate_id': q['candidate_id'] + '__' + q['configuration_id'], 'base_candidate_id': q['candidate_id'],
            'configuration_id': q['configuration_id'], 'species': q['species'], 'analysis_id': q['analysis_id'],
            'status': 'NOT_FITTED_AGENT_REQUESTED_CHANGES', 'issues': c['response']['issues'] + c['response']['requested_changes'],
            'agent_response_ref': c['response_ref']}
        r = file_ref(write_json(folder / 'attempts' / digest(q['configuration_id'])[:12] / 'fit_result.json', record))
        return {'fits': state['fits'] + [r]}
    def advance(state):
        return {'position': state['position'] + 1, 'configuration': {}}
    def summarize(state):
        c = call('attempt_summary', {'attempts': [read_json(r['path']) for r in state['fits']],
            'fit_refs': state['fits'], 'selection_policy': 'Retain all eligible configurations for comparison and human selection.'})
        return {'calls': state['calls'] + [c],
            'status': 'CANDIDATE_SEARCH_COMPLETED' if c['response']['decision']=='CONTINUE' else 'NEEDS_REVIEW'}
    graph = StateGraph(SearchState)
    for name, node in [('select_configuration', select), ('configure_estimation', configure),
                       ('fit_and_internal_self_checks', fit_and_check), ('record_unfitted_attempt', skipped),
                       ('next_permitted_configuration', advance), ('return_all_attempts', summarize)]:
        graph.add_node(name, node)
    graph.add_edge(START, 'select_configuration')
    graph.add_conditional_edges('select_configuration', lambda s: 'configure_estimation' if s['attempt_ok'] else 'record_unfitted_attempt')
    graph.add_conditional_edges('configure_estimation', lambda s: 'fit_and_internal_self_checks' if s['attempt_ok'] else 'record_unfitted_attempt')
    graph.add_edge('fit_and_internal_self_checks', 'next_permitted_configuration')
    graph.add_edge('record_unfitted_attempt', 'next_permitted_configuration')
    graph.add_conditional_edges('next_permitted_configuration', lambda s: 'select_configuration' if s['position'] < len(configurations) else 'return_all_attempts')
    graph.add_edge('return_all_attempts', END)
    thread = 'pk_search_' + uuid4().hex
    with SqliteSaver.from_conn_string(str(folder / 'candidate.sqlite')) as saver:
        compiled = graph.compile(checkpointer=saver)
        result = compiled.invoke({'position': 0, 'fits': [], 'calls': []},
            {'configurable': {'thread_id': thread}, 'recursion_limit': len(configurations) * 6 + 5})
        checkpoint = compiled.get_state({'configurable': {'thread_id': thread}}).config['configurable']['checkpoint_id']
    return {'status': result['status'], 'fit_refs': result['fits'], 'agent_calls': result['calls'],
        'llm_calls': len(result['calls']), 'fit_calls': len(list(folder.glob('attempts/*/numerical_result.json'))),
        'qualification_ref': reference, 'search_thread_id': thread, 'search_checkpoint_id': checkpoint,
        'human_review': 'REQUIRED_AFTER_COMPARISON', 'model_release': False}


def execute_agent(request_ref, output, generator=None, fit_adapter=None):
    """Only called as a Snakemake builtin, or with explicit test doubles in tests."""
    from .animal_pk_comparison import compare_results
    check_ref(request_ref); request = read_json(request_ref['path']); folder = Path(output)
    folder.mkdir(parents=True, exist_ok=True)
    for reference in request['source_refs']:
        check_ref(reference)
    contract = request['agent']; upstream = {k: read_json(r['path']) for k, r in request['upstream_refs'].items()}
    started = utcnow()
    write_json(folder / 'execution.json', {'agent_id': contract['id'], 'status': 'RUNNING', 'started_at': started})
    try:
        if contract['role'] == 'candidate_model':
            result = candidate_search(request, folder, generator, fit_adapter)
        elif contract['role'] == 'comparison':
            fit_refs = [r for value in upstream.values() for r in value.get('fit_refs', [])]
            fits = []
            for reference in fit_refs:
                check_ref(reference); fits.append({**read_json(reference['path']),'fit_result_ref':reference})
            expected = set(contract['context']['candidate_ids'])
            if {f.get('base_candidate_id', f['candidate_id']) for f in fits} != expected:
                raise PipelineError('PK_COMPARISON_COVERAGE', 'Every model branch must return its attempts, including explicit unsuccessful attempts.')
            if any(f.get('species') != contract['scope']['species'] or f.get('analysis_id') != contract['scope']['analysis_id'] for f in fits):
                raise PipelineError('PK_COMPARISON_SCOPE', 'Comparison inputs include another species or analysis.')
            report = compare_results(fits)
            reference = file_ref(write_json(folder / 'comparison.json', report))
            call = invoke_agent(contract, {'validated_comparison': report, 'instruction': request['instruction']}, folder / 'agents', generator)
            result = {'status': 'PENDING_HUMAN_REVIEW' if call['response']['decision'] == 'CONTINUE' else 'NEEDS_REVIEW',
                'comparison_ref': reference, 'fit_refs': fit_refs, 'agent_calls': [call], 'llm_calls': 1, 'fit_calls': 0}
        else:
            inputs = {'upstream': upstream, 'instruction': request['instruction']}
            if request.get('qualification_refs'):
                inputs['reviewed_fitting_contracts'] = [read_json(r['path']) for r in request['qualification_refs']]
            dataset = contract.get('context', {}).get('dataset')
            if dataset:
                # Assigned tables only. No whole proposal, other species, PD or human holdout data.
                for key in ['data', 'metadata', 'excluded_records']:
                    check_ref(dataset[key]); inputs['assigned_' + key] = read_json(dataset[key]['path'])
            call = invoke_agent(contract, inputs, folder / 'agents', generator)
            result = {'status': 'AGENT_COMPLETED' if call['response']['decision'] == 'CONTINUE' else 'NEEDS_REVIEW',
                'response': call['response'], 'agent_calls': [call], 'llm_calls': 1, 'fit_calls': 0}
            if contract['role']=='species_report' and result['status']=='AGENT_COMPLETED':
                if not upstream or any(v.get('review_decision',{}).get('model_release') is not True for v in upstream.values()):
                    raise PipelineError('PK_HUMAN_SELECTION_REQUIRED','Species reports require signed human model selections.')
                handoff={'module':'animal_pk_species','species':contract['scope']['species'],
                    'selected_models':[m for v in upstream.values() for m in v['selected_models']],
                    'human_review_refs':list(request['upstream_refs'].values()),
                    'model_release':True,'human_prediction_validated':False,
                    'scope':'HUMAN_SELECTED_WITHIN_SPECIES_MODELS_ONLY'}
                result['handoff_ref']=file_ref(write_json(folder/'species_handoff.json',handoff))
            elif contract['role']=='animal_pk_report' and result['status']=='AGENT_COMPLETED':
                handoffs=[]
                for value in upstream.values():
                    reference=value.get('handoff_ref')
                    if not reference:raise PipelineError('PK_SPECIES_HANDOFF_MISSING','A species report lacks its reviewed parameter handoff.')
                    check_ref(reference); handoff=read_json(reference['path'])
                    if handoff.get('model_release') is not True:raise PipelineError('PK_HUMAN_SELECTION_REQUIRED','An upstream species model is not released.')
                    handoffs.append(reference)
                result['handoff_ref']=file_ref(write_json(folder/'animal_pk_handoff.json',{
                    'module':'animal_pk','species_handoffs':handoffs,'model_release':True,
                    'human_prediction_validated':False,'scope':'ANIMAL_MODELS_ONLY_HUMAN_TRANSLATION_REQUIRES_ITS_OWN_REVIEW'}))
        result.update(agent_id=contract['id'], role=contract['role'], started_at=started, finished_at=utcnow(),
            plan_signature=request['plan_signature'], upstream_run_ids=request['upstream_run_ids'],
            request_ref=request_ref, scientific_accepted=False, model_release=False)
        write_json(folder / 'report.json', result)
        write_json(folder / 'execution.json', {k: result[k] for k in ['agent_id', 'status', 'started_at', 'finished_at', 'llm_calls', 'fit_calls']})
    except Exception as exc:
        failure = {'status': 'STOPPED_ON_ERROR', 'agent_id': contract['id'], 'started_at': started, 'finished_at': utcnow(),
            'code': getattr(exc, 'code', 'PK_AGENT_EXECUTION_FAILED'), 'summary': str(exc),
            'next_action': 'Inspect the failed request and logs. Correct the fitting contract or requested input, then start a fresh attempt.',
            'model_release': False}
        write_json(folder / 'failure.json', failure); write_json(folder / 'execution.json', failure)
        raise
    finally:
        files = [{'name': p.relative_to(folder).as_posix(), **file_ref(p)} for p in sorted(folder.rglob('*'))
            if p.is_file() and p.suffix in {'.json', '.jsonl', '.log', '.csv', '.R', '.txt', '.png'} and p.name != 'artifact_manifest.json']
        write_json(folder / 'artifact_manifest.json', {'files': files, 'model_release': False})
    return result


def assemble_batch(folders, output):
    """Merge independent model branches after Snakemake has joined their receipts."""
    output=Path(output)
    reports=[read_json(Path(folder)/'report.json') for folder in folders]
    result={'status':'PARALLEL_CANDIDATE_SEARCHES_COMPLETED','finished_at':utcnow(),
        'agents':reports,'llm_calls':sum(r['llm_calls'] for r in reports),
        'fit_calls':sum(r['fit_calls'] for r in reports),'model_release':False}
    write_json(output/'report.json',result)
    files=[{'name':p.relative_to(output).as_posix(),**file_ref(p)} for p in sorted(output.rglob('*'))
        if p.is_file() and p.suffix in {'.json','.jsonl','.csv','.log','.R','.png','.txt'} and p.name!='artifact_manifest.json']
    write_json(output/'artifact_manifest.json',{'files':files,'model_release':False})
    return result
