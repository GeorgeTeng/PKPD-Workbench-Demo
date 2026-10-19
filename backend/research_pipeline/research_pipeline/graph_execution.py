"""LangGraph decision layer -> Prefect runtime -> Snakemake file DAG.

State carries references and diagnostics, never a full copy of research data.
Scientific acceptance remains an explicit, separately checkpointed human interrupt.
"""
from pathlib import Path
from typing import TypedDict
from uuid import uuid4
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.sqlite import SqliteSaver
from .common import read_json, write_json, utcnow


class ExecutionState(TypedDict, total=False):
    request_path: str
    target: str
    dry_run: bool
    goal_ref: str | None
    input_refs: list[dict]
    runtime: dict
    diagnostics: dict
    disposition: str


def build_execution_graph(checkpointer, prefect_runner):
    def resolve_goal(state):
        spec = read_json(state['request_path'])
        goal = Path(spec['out']) / 'B1/main.json'
        if spec.get('mode') == 'project_rules':
            from .project_rule_agent import validate_input
            prepared = validate_input(spec['project_rules_input'])
            return {'goal_ref': prepared['base_main_ref']['path'],
                    'input_refs': [spec['project_rules_input'], prepared['base_main_ref'], *prepared['source_refs']]}
        if spec.get('mode') == 'pk_reference_pilot':
            from .adequacy import check_ref, file_ref
            from .pk_reference_pilot import LIBRARY
            references=[spec['main_ref'],spec.get('reference_library') or file_ref(LIBRARY)]
            for reference in references: check_ref(reference)
            return {'goal_ref':spec['main_ref']['path'],'input_refs':references}
        if spec.get('mode') == 'animal_pk_individual':
            from .animal_pk_individual import validate_request
            request=validate_request(spec['individual_request'])
            return {'goal_ref':spec['individual_request']['path'],'input_refs':[spec['individual_request'],request['approval_ref']]}
        if spec.get('mode') == 'animal_pk_summary':
            from .animal_pk_summary import validate_summary_request
            request=validate_summary_request(spec['summary_request'])
            return {'goal_ref':spec['summary_request']['path'],'input_refs':[spec['summary_request'],request['approval_ref']]}
        if spec.get('mode') == 'animal_pk_execution':
            from .adequacy import check_ref
            references=[spec['pk_plan'],*(spec.get('agent_requests') or [spec['agent_request']])]
            for reference in references:check_ref(reference)
            return {'goal_ref':spec['pk_plan']['path'],'input_refs':references}
        if spec.get('mode') == 'animal_pk_architecture':
            from .adequacy import check_ref
            check_ref(spec['pk_context'])
            return {'goal_ref':spec['pk_context']['path'],'input_refs':[spec['pk_context']]}
        if spec.get('reviewed_eda'):
            from .clinical_dispatch import inputs
            snapshot, _, _, _, _ = inputs(spec['reviewed_eda'], require_eda=True)
            handoff=next(a for a in snapshot['nodes']['adequacy']['artifacts'] if a['name']=='effective_main.json')
            return {'goal_ref':handoff['path'],'input_refs':[spec['reviewed_eda'],spec['clinical_spec']]}
        if spec.get('approved_preparation'):
            from .common import PipelineError
            raise PipelineError('EDA_DISABLED', 'EDA is disabled. Its backend has been removed and will not be called.')
        if spec.get('approved_data'):
            from .preparation_workflow import approved_inputs
            _, qc, _ = approved_inputs(spec['approved_data'])
            return {'goal_ref': qc['upstream_main']['path'], 'input_refs': [spec['approved_data'], qc['assessment']]}
        if spec.get('approved_context'):
            approval = read_json(spec['approved_context']['path'])
            original = next(a for a in approval['context']['artifacts'] if a['name'] == 'main.json')
            amendment = approval.get('scope_amendment')
            references=[]
            if spec.get('pk_reference_pilot'):
                from .adequacy import file_ref
                from .pk_reference_pilot import LIBRARY
                references=[spec.get('reference_library') or file_ref(LIBRARY)]
            if approval.get('project_rules_ref'):
                from .project_rule_agent import verify_published
                pack_ref = approval['project_rules_ref']; pack = verify_published(pack_ref)
                return {'goal_ref': pack['main_ref']['path'],
                        'input_refs': [spec['approved_context'], original, pack_ref, pack['main_ref'],
                                       *([amendment] if amendment else []), *references]}
            return {'goal_ref': str(goal) if amendment else original['path'],
                    'input_refs': [spec['approved_context'], original, *([amendment] if amendment else []), *references]}
        return {'goal_ref': str(goal) if goal.is_file() else None,
                'input_refs': [{'name': f['name'], 'sha256': f.get('sha256')} for f in spec.get('uploads', [])]}

    def call_prefect(state):
        try:
            runtime = prefect_runner(state['request_path'], target=state['target'], dry_run=state.get('dry_run', False))
            return {'runtime': runtime}
        except Exception as exc:
            return {'runtime': {'status': 'STOPPED_ON_ERROR', 'error': str(exc)}}

    def inspect_diagnostics(state):
        status = state['runtime']['status']
        # No R2/AIC/RSE, species count, or biological acceptance threshold is invented here.
        kind = 'ENGINEERING_FAILURE' if status == 'STOPPED_ON_ERROR' else 'PAUSED' if status == 'PAUSED' else 'HUMAN_SCIENTIFIC_REVIEW'
        if status == 'REVISION_REQUIRED': kind = 'CONTEXT_REVISION_REQUIRED'
        if status == 'ARCHITECTURE_READY': kind = 'ARCHITECTURE_ONLY'
        if status == 'PK_AGENT_COMPLETED': kind = 'PK_TASK_COMPLETE'
        if status == 'REFERENCE_ADVICE_READY': kind = 'REFERENCE_ADVICE_ONLY'
        if status == 'MAIN_REVISION_READY': kind = 'HUMAN_SCIENTIFIC_REVIEW'
        spec = read_json(state['request_path']); run = Path(spec['out'])
        from .workflow_runtime import context_requires_project_rules
        rules_required = state['target'] == 'project_rules' or (state['target'] == 'context' and context_requires_project_rules(spec))
        refs, findings, diagnostic_error = [], [], None
        if state['runtime'].get('failure'):
            failure = state['runtime']['failure']
            findings.append({'code':failure['code'], 'stage':failure['stage'], 'summary':failure['summary']})
            refs.extend(x['path'] for x in failure.get('evidence_refs',[]))
        if status == 'REVISION_REQUIRED':
            feedback = state['runtime'].get('context_feedback', {})
            refs.extend(x['path'] for x in feedback.get('evidence_refs', []))
            findings.append({'stage': feedback.get('stage'), 'decision': feedback.get('decision'),
                             'summary': feedback.get('summary'), 'feedback_signature': feedback.get('signature')})
        for path in [run / 'data_preparation/main.json', run / 'verification/verification.json', run / 'main.json',
                     run / 'prepared/preparation.json', run / 'eda/feedback.json', run / 'eda/eda_report.json', run / 'adequacy/adequacy.json', run/'dispatch/dispatch_report.json', run/'animal_pk/report.json', run/'pk_references/review/reference_report.json', run/'pk_references/revised/main_review.json', run/'project_rules/published/report.json']:
            if not path.is_file(): continue
            refs.append(str(path))
            try:
                report = read_json(path)
                if not isinstance(report, dict): raise ValueError('Diagnostic report must be a JSON object')
                if path == run/'project_rules/published/report.json' and rules_required and not state.get('dry_run') and status not in {'STOPPED_ON_ERROR', 'PAUSED'}:
                    from .project_rule_agent import publication_ready
                    published = publication_ready(report, allow_provisional=spec.get('demo_key_rules') is True)
                    expected = report['status'] if state['target'] == 'project_rules' else ('WAITING_FOR_HUMAN_REVIEW' if published else 'REVISION_REQUIRED')
                    if expected != status:
                        raise ValueError('Project-rules runtime and publication status disagree')
                    kind = ('PROJECT_RULES_READY' if state['target'] == 'project_rules' else 'HUMAN_SCIENTIFIC_REVIEW') if published else 'CONTEXT_REVISION_REQUIRED'
                if path.name == 'adequacy.json' and state['target'] == 'adequacy' and status == 'WAITING_FOR_HUMAN_REVIEW':
                    kind = 'READY_FOR_QC' if report.get('can_enter_qc') is True and report.get('requires_human_review') is False else 'DATA_SUPPLEMENT_REQUIRED' if report.get('assessment_status') == 'INSUFFICIENT' else 'HUMAN_SCIENTIFIC_REVIEW'
                if path==run/'data_preparation/main.json' and state['target']=='data_preparation' and status=='WAITING_FOR_HUMAN_REVIEW':
                    if report.get('agent_workflow_version')=='2.0' and report.get('cleaning_complete') is True and report.get('requires_human_review') is False:
                        kind='READY_FOR_EDA'
                fields = {k: report[k] for k in ['status', 'fit_ready', 'cleaning_complete', 'assessment_status',
                    'scientific_release', 'human_review', 'issues', 'limitations', 'findings', 'why_cannot_pass', 'missing_materials'] if k in report}
                findings.append({'source': str(path), 'reported_fields': fields})
            except (OSError, ValueError) as exc:
                diagnostic_error = f'Invalid structured diagnostics: {path.name}: {exc}'
                kind = 'ENGINEERING_FAILURE'
                break
        if rules_required and not state.get('dry_run') and status not in {'STOPPED_ON_ERROR', 'PAUSED'} and not (run/'project_rules/published/report.json').is_file():
            diagnostic_error = 'Project-rules publication report is missing; no handoff can be released'
            kind = 'ENGINEERING_FAILURE'
        return {'diagnostics': {'kind': kind, 'artifact_refs': refs, 'reported_findings': findings,
                'error': diagnostic_error, 'scientific_accepted': False,
                'dry_run': state.get('dry_run', False), 'acceptance_criteria': 'PROJECT_APPROVED_RULES_ONLY'},
                'disposition': kind}

    graph = StateGraph(ExecutionState)
    graph.add_node('resolve_goal_and_scope', resolve_goal)
    graph.add_node('prefect_dispatch', call_prefect)
    graph.add_node('read_structured_diagnostics', inspect_diagnostics)
    graph.add_node('engineering_repair_required', lambda _: {'disposition': 'ENGINEERING_FAILURE'})
    graph.add_node('await_human_scientific_review', lambda _: {'disposition': 'HUMAN_SCIENTIFIC_REVIEW'})
    graph.add_node('paused_at_file_checkpoint', lambda _: {'disposition': 'PAUSED'})
    graph.add_node('await_context_revision', lambda _: {'disposition': 'CONTEXT_REVISION_REQUIRED'})
    graph.add_node('ready_for_qc', lambda _: {'disposition': 'READY_FOR_QC'})
    graph.add_node('ready_for_eda', lambda _: {'disposition': 'READY_FOR_EDA'})
    graph.add_node('project_rules_ready', lambda _: {'disposition': 'PROJECT_RULES_READY'})
    graph.add_node('await_data_supplement', lambda _: {'disposition': 'DATA_SUPPLEMENT_REQUIRED'})
    graph.add_node('architecture_inspection_ready', lambda _: {'disposition':'ARCHITECTURE_ONLY'})
    graph.add_node('pk_task_complete', lambda _: {'disposition':'PK_TASK_COMPLETE'})
    graph.add_node('reference_advice_ready', lambda _: {'disposition':'REFERENCE_ADVICE_ONLY'})
    graph.add_edge(START, 'resolve_goal_and_scope'); graph.add_edge('resolve_goal_and_scope', 'prefect_dispatch')
    graph.add_edge('prefect_dispatch', 'read_structured_diagnostics')
    graph.add_conditional_edges('read_structured_diagnostics', lambda s: {
        'ENGINEERING_FAILURE': 'engineering_repair_required', 'PAUSED': 'paused_at_file_checkpoint',
        'CONTEXT_REVISION_REQUIRED': 'await_context_revision',
        'READY_FOR_QC': 'ready_for_qc', 'DATA_SUPPLEMENT_REQUIRED': 'await_data_supplement',
        'READY_FOR_EDA':'ready_for_eda',
        'PROJECT_RULES_READY': 'project_rules_ready',
        'ARCHITECTURE_ONLY':'architecture_inspection_ready',
        'PK_TASK_COMPLETE':'pk_task_complete',
        'REFERENCE_ADVICE_ONLY':'reference_advice_ready',
        'HUMAN_SCIENTIFIC_REVIEW': 'await_human_scientific_review'}[s['disposition']])
    for key in ['engineering_repair_required', 'await_human_scientific_review', 'paused_at_file_checkpoint', 'await_context_revision', 'ready_for_qc', 'ready_for_eda', 'project_rules_ready', 'await_data_supplement','architecture_inspection_ready','pk_task_complete','reference_advice_ready']: graph.add_edge(key, END)
    return graph.compile(checkpointer=checkpointer)


def run_controlled(request_path, target=None, dry_run=False, prefect_runner=None):
    if prefect_runner is None:
        from .orchestration import research_flow
        prefect_runner = research_flow
    spec = read_json(request_path); folder = Path(spec['job_dir'])
    # A compute retry has its own trace; successful Snakemake receipts are reused.
    thread_id = spec['id'] + ':' + uuid4().hex
    config = {'configurable': {'thread_id': thread_id}}
    with SqliteSaver.from_conn_string(str(folder / 'langgraph.sqlite')) as saver:
        graph = build_execution_graph(saver, prefect_runner)
        result = graph.invoke({'request_path': str(request_path), 'target': target or spec.get('stop_after', 'data_preparation'), 'dry_run': dry_run}, config)
        snapshot = graph.get_state(config)
        trace = {'at': utcnow(), 'thread_id': thread_id, 'checkpoint_id': snapshot.config['configurable']['checkpoint_id'],
                 'controller': 'LangGraph', 'scheduler': 'Prefect', 'file_executor': 'Snakemake',
                 'disposition': result['disposition'], 'diagnostics': result['diagnostics']}
    write_json(folder / 'control_traces' / (thread_id.split(':')[-1] + '.json'), trace)
    current = read_json(folder / 'status.json') if (folder / 'status.json').is_file() else result['runtime']
    current['control'] = trace
    if result['disposition'] == 'ENGINEERING_FAILURE':
        current.update(status='STOPPED_ON_ERROR', error=result['runtime'].get('error') or result['diagnostics']['error'])
    elif result['disposition'] == 'CONTEXT_REVISION_REQUIRED':
        current.update(status='REVISION_REQUIRED', scientific_release=False)
    write_json(folder / 'status.json', current)
    return current
