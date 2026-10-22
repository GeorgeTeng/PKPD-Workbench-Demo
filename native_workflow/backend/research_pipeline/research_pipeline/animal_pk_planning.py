"""On-entry workflow drafts and an explicit planning-agent integration contract.

The current adapter constructs a draft from routed metadata. It is not an LLM
invocation and never authorizes numerical execution or scientific pooling.
"""
from .common import read_json, write_json, utcnow, PipelineError
from .adequacy import file_ref, check_ref


def initialize_draft(folder,plan,identifier,controller):
    path=folder/'workflow_planning.json'
    if path.is_file():return read_json(path)
    from .task_rules import scoped_context
    context, projection = scoped_context(read_json(plan['context_ref']['path']), 'animal_pk')
    context_ref=file_ref(write_json(folder/'animal_pk_context.json',context))
    audit_ref=file_ref(write_json(folder/'rule_audit.json',projection))
    contract={
        'agent_role':'animal_pk_workflow_planner','session_policy':'FRESH_CALL_NO_CONVERSATION_REUSE',
        'input_context':context_ref,'assigned_files':[context_ref,*plan['source_refs'][1:]],
        'task':'Propose a species-specific animal PK workflow using only the assigned branch context and metadata. Explain candidate choices, data grouping, dependencies and unresolved qualifications for human review.',
        'output_contract':{'workflow_plan':'plan.json','rationale':'planning_report.json','unresolved_questions':'planning_report.json'},
        'adapter':'METADATA_DRAFT_BUILDER','llm_adapter_status':'RESERVED_NOT_CONNECTED',
        'controller':'LangGraph','scheduler':'Prefect','file_executor':'Snakemake',
        'boundaries':['No fitting during workflow generation.','No automatic pooling of source tables.',
                      'No scientific execution before workflow approval and existing input qualifications.'],
        'llm_calls':0,'fit_calls':0}
    contract_ref=file_ref(write_json(folder/'planning_agent_contract.json',contract))
    report_ref=file_ref(write_json(folder/'planning_report.json',{
        'status':'DRAFT_PENDING_HUMAN_REVIEW','origin':'METADATA_DRAFT_BUILDER',
        'species':[s['species'] for s in plan['species']],
        'datasets':len(plan['analysis_units']),'agent_contracts':len(plan['agents']),
        'unresolved_questions':['Confirm scientific analysis groups; source tables have not been pooled.',
            'Review compartment candidates, source permissions and data qualification requirements.'],
        'rule_audit_ref':audit_ref,'scoped_context_ref':context_ref,
        'rule_scope_unresolved':projection['unresolved'],
        'llm_calls':0,'fit_calls':0,'scientific_acceptance':False}))
    receipt=controller.begin(identifier,'animal_pk_workflow',plan['plan_signature'],
        [file_ref(folder/'plan.json'),contract_ref,report_ref,context_ref,audit_ref])
    record={'status':'DRAFT_PENDING_HUMAN_REVIEW','generated_at':utcnow(),
        'plan_signature':plan['plan_signature'],'context_ref':plan['context_ref'],
        'planning_agent':contract_ref,'planning_report':report_ref,'langgraph_review':receipt,
        'review':None,'llm_calls':0,'fit_calls':0}
    write_json(path,record);return record


def planning_state(folder,plan):
    path=folder/'workflow_planning.json'
    if not path.is_file():return {'status':'NOT_GENERATED','approved':False}
    record=read_json(path)
    if record['plan_signature']!=plan['plan_signature']:
        raise PipelineError('PK_STALE_WORKFLOW','The workflow draft changed. Generate and review its current version.')
    for ref in [record['planning_agent'],record['planning_report']]:check_ref(ref)
    decision=record.get('review') or {}
    approved=(record.get('langgraph_review',{}).get('status')=='APPROVED' and
        decision.get('output_signature')==plan['plan_signature'] and decision.get('decision')=='APPROVE')
    return {**record,'approved':approved}


def require_workflow_approval(folder,plan):
    if not planning_state(folder,plan)['approved']:
        raise PipelineError('PK_WORKFLOW_REVIEW_REQUIRED','Inspect and approve the generated Animal PK workflow before starting any execution agent.')


def review_draft(folder,plan,decision,controller):
    state=planning_state(folder,plan)
    if state['status']=='NOT_GENERATED':raise PipelineError('PK_PLAN_NOT_GENERATED','Enter Animal PK modeling to generate a workflow draft first.')
    if decision['decision']!='APPROVE' and not decision.get('rationale','').strip():
        raise PipelineError('PK_REVISION_REASON_REQUIRED','Describe the workflow changes required.')
    state['langgraph_review']=controller.resume(state['langgraph_review'],decision)
    state.update(review={**decision,'at':utcnow()},status='APPROVED' if decision['decision']=='APPROVE' else 'REVISION_REQUIRED')
    state.pop('approved',None);write_json(folder/'workflow_planning.json',state)
    return planning_state(folder,plan)
