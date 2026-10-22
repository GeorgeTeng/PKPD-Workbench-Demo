"""Independent LLM steps, numerical-tool hooks, and checkpointed candidate revision loops."""
from pathlib import Path
from ctxcomp.governance import governed_request
from typing import TypedDict
from uuid import uuid4
from jsonschema import validate
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.sqlite import SqliteSaver
from .animal_pk import digest, RESPONSE_SCHEMA
from .adequacy import check_ref, file_ref
from .common import PipelineError, read_json, write_json, utcnow


def invoke_agent(contract, inputs, folder, generator=None):
    """inputs contains only the caller-validated output of this agent's dependencies."""
    if contract.get('rule_scope',{}).get('unresolved'):
        raise PipelineError('PK_RULE_SCOPE_UNRESOLVED', 'Assign the unclassified project rules to their scientific tasks before invoking this agent. Inspect the rule audit; no rule was silently discarded.')
    if generator is None:
        from ctxcomp.providers import codex_generate
        generator=codex_generate
    folder=Path(folder)/uuid4().hex;folder.mkdir(parents=True)
    payload={'stage':'animal_pk_'+contract['role'],'instructions':contract['instructions'],
        'task':contract,'upstream':inputs,'schema':RESPONSE_SCHEMA}
    request=governed_request(payload)
    write_json(folder/'request.json',request)
    record={'started_at':utcnow(),'status':'RUNNING','role':contract['role'],'agent_id':contract['id'],
        'request_sha256':request['request_sha256'],'fresh_session':True}
    write_json(folder/'execution.json',record)
    try:
        result=generator(request,diagnostics_dir=folder/'provider')
        write_json(folder/'response.json',result);validate(result,RESPONSE_SCHEMA)
        if result['decision']=='REVISE' and not result['requested_changes']:
            raise PipelineError('PK_EMPTY_REVISION','Agent requested a revision without specifying changes.')
        record.update(status='COMPLETED',finished_at=utcnow())
        write_json(folder/'execution.json',record)
        return {'agent_id':contract['id'],'role':contract['role'],'invocation_id':folder.name,
            'response':result,'response_ref':file_ref(folder/'response.json'),'request_ref':file_ref(folder/'request.json'),
            'execution_ref':file_ref(folder/'execution.json')}
    except Exception as exc:
        record.update(status='FAILED',finished_at=utcnow(),reason=str(exc));raise
    finally: write_json(folder/'execution.json',record)


class CandidateState(TypedDict,total=False):
    attempt: int
    proposal_ref: dict
    fit_ref: dict
    diagnostic_ref: dict
    revision: list[str]
    status: str


def run_comparison_agent(contract, fit_refs, folder, generator=None):
    """Compute the table first; a fresh comparison agent explains but cannot alter it."""
    from .animal_pk_comparison import compare_results
    if contract['role']!='comparison':raise PipelineError('PK_WRONG_AGENT_ROLE','A comparison agent contract is required.')
    results=[]
    for ref in fit_refs:check_ref(ref);results.append(read_json(ref['path']))
    expected=set(contract['context']['candidate_ids'])
    if {r['candidate_id'] for r in results}!=expected or len(results)!=len(expected):
        raise PipelineError('PK_COMPARISON_COVERAGE','Supply exactly one result or explicit failed-result record for every expected candidate.')
    if any(r.get('species')!=contract['scope']['species'] or r.get('analysis_id')!=contract['scope']['analysis_id'] for r in results):
        raise PipelineError('PK_COMPARISON_SCOPE','Candidate results belong to another species or analysis.')
    folder=Path(folder);report=compare_results(results)
    report_ref=file_ref(write_json(folder/'comparison.json',report))
    call=invoke_agent(contract,{'validated_comparison':report,'fit_result_refs':fit_refs},folder/'comparison_agent',generator)
    output={'status':'PENDING_HUMAN_REVIEW','comparison_ref':report_ref,'agent_response_ref':call['response_ref'],
        'scientific_accepted':False,'model_release':False}
    write_json(folder/'comparison_handoff.json',output)
    return output


def run_candidate(model_contract, diagnostic_contract, qualification_ref, folder, *, fit_adapter=None,
                  generator=None, max_attempts=2):
    """Trusted host code supplies the adapter; LLM output is never an executable command.

    max_attempts bounds scientific revisions, not model latency or token output.
    Every new numerical attempt sees the same qualified data and model class.
    """
    if type(max_attempts)!=int or max_attempts<1: raise ValueError('max_attempts must be positive')
    check_ref(qualification_ref); qualification=read_json(qualification_ref['path'])
    if qualification.get('fit_ready') is not True or qualification.get('candidate_id')!=model_contract['candidate']['id']:
        raise PipelineError('PK_INPUTS_NOT_QUALIFIED','A candidate-specific fit-ready input contract is required.')
    if qualification.get('compartments')!=model_contract['candidate']['compartments']:
        raise PipelineError('PK_MODEL_SCOPE_CHANGED','Qualified compartment count differs from the candidate.')
    for ref in qualification.get('input_refs',[]):check_ref(ref)
    if not qualification.get('input_refs') or not qualification.get('approval_ref'):
        raise PipelineError('PK_QUALIFICATION_EVIDENCE_REQUIRED','Qualified inputs and their source approval reference are required.')
    check_ref(qualification['approval_ref'])
    if fit_adapter is None:
        raise PipelineError('PK_FIT_ADAPTER_PENDING','No numerical PK adapter is connected. Architecture files can be inspected; no fit has run.')
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    def propose(state):
        for ref in qualification['input_refs']:check_ref(ref)
        check_ref(qualification_ref)
        call=invoke_agent(model_contract,{'qualification':qualification,'requested_changes':state.get('revision',[])},folder/'model_agent',generator)
        return {'attempt':state.get('attempt',0)+1,'proposal_ref':call['response_ref'],
            'status':'SPECIFIED' if call['response']['decision']=='CONTINUE' else 'NEEDS_REVIEW'}
    def fit(state):
        # Adapter must validate parameter constraints and error-model specifications itself.
        path=folder/'attempts'/str(state['attempt']);path.mkdir(parents=True)
        result=fit_adapter(qualification,state['proposal_ref'],path)
        if result.get('candidate_id')!=model_contract['candidate']['id']:
            raise PipelineError('PK_RESULT_SCOPE_CHANGED','Numerical adapter returned another candidate.')
        return {'fit_ref':file_ref(write_json(path/'fit_result.json',result))}
    def diagnose(state):
        check_ref(state['fit_ref'])
        call=invoke_agent(diagnostic_contract,{'fit_result':read_json(state['fit_ref']['path']),
            'qualification_ref':qualification_ref},folder/'diagnostic_agent',generator)
        action=call['response']['decision']
        return {'diagnostic_ref':call['response_ref'],'revision':call['response']['requested_changes'],
            'status':'READY_FOR_COMPARISON' if action=='CONTINUE' else 'REVISE' if action=='REVISE' and state['attempt']<max_attempts else 'NEEDS_REVIEW'}
    graph=StateGraph(CandidateState)
    graph.add_node('candidate_model_agent',propose);graph.add_node('numerical_fit_tool',fit);graph.add_node('diagnostic_agent',diagnose)
    graph.add_edge(START,'candidate_model_agent')
    graph.add_conditional_edges('candidate_model_agent',lambda s:'numerical_fit_tool' if s['status']=='SPECIFIED' else END)
    graph.add_edge('numerical_fit_tool','diagnostic_agent')
    graph.add_conditional_edges('diagnostic_agent',lambda s:'candidate_model_agent' if s['status']=='REVISE' else END)
    thread='candidate_'+uuid4().hex
    with SqliteSaver.from_conn_string(str(folder/'candidate.sqlite')) as saver:
        compiled=graph.compile(checkpointer=saver)
        result=compiled.invoke({'attempt':0},{'configurable':{'thread_id':thread},'recursion_limit':max_attempts*4+5})
    write_json(folder/'result.json',{**result,'thread_id':thread,'scientific_accepted':False})
    return result
