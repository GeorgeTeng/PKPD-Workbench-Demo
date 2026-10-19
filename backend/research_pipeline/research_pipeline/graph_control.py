"""LangGraph human interrupts and decision state; no scientific cutoffs are embedded."""
from pathlib import Path
from typing import TypedDict
from uuid import uuid4
from langgraph.graph import StateGraph, START, END
from langgraph.types import Command, interrupt
from langgraph.checkpoint.sqlite import SqliteSaver


class ReviewState(TypedDict, total=False):
    session_id: str
    node_id: str
    output_signature: str
    artifact_refs: list[dict]
    rule_snapshot: list[dict]
    decision: dict
    disposition: str


def validate_decision(state, decision):
    if decision.get('output_signature') != state['output_signature']:
        raise ValueError('LangGraph review signature mismatch')
    if not decision.get('confirmed') or not decision.get('reviewer', '').strip():
        raise ValueError('Human confirmation is required')
    if decision.get('decision') not in {'APPROVE', 'REQUEST_CHANGES', 'REJECT'}:
        raise ValueError('Unsupported human decision')


def review_graph(checkpointer):
    def human_review(state):
        decision = interrupt({'type': 'HUMAN_REVIEW', 'node_id': state['node_id'],
            'output_signature': state['output_signature'], 'artifact_refs': state['artifact_refs'],
            'rule_snapshot': state.get('rule_snapshot', []), 'allowed': ['APPROVE', 'REQUEST_CHANGES', 'REJECT']})
        validate_decision(state, decision)
        return {'decision': decision}

    graph = StateGraph(ReviewState)
    graph.add_node('human_review', human_review)
    graph.add_node('accepted', lambda _: {'disposition': 'APPROVED'})
    graph.add_node('return_for_revision', lambda _: {'disposition': 'REVISION_REQUIRED'})
    graph.add_edge(START, 'human_review')
    graph.add_conditional_edges('human_review', lambda s: 'accepted' if s['decision']['decision'] == 'APPROVE' else 'return_for_revision')
    graph.add_edge('accepted', END); graph.add_edge('return_for_revision', END)
    return graph.compile(checkpointer=checkpointer)


class ReviewController:
    def __init__(self, state_root):
        self.path = Path(state_root) / 'langgraph' / 'human_reviews.sqlite'

    def begin(self, session_id, node_id, signature, refs, rules=None):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        thread_id = f'{session_id}:{node_id}:{uuid4().hex}'
        config = {'configurable': {'thread_id': thread_id}}
        with SqliteSaver.from_conn_string(str(self.path)) as saver:
            graph = review_graph(saver)
            result = graph.invoke({'session_id': session_id, 'node_id': node_id, 'output_signature': signature,
                'artifact_refs': refs, 'rule_snapshot': rules or []}, config)
            snapshot = graph.get_state(config)
            return {'thread_id': thread_id, 'checkpoint_id': snapshot.config['configurable']['checkpoint_id'],
                    'interrupt_id': result['__interrupt__'][0].id, 'status': 'INTERRUPTED'}

    def resume(self, receipt, decision):
        config = {'configurable': {'thread_id': receipt['thread_id']}}
        with SqliteSaver.from_conn_string(str(self.path)) as saver:
            graph = review_graph(saver)
            snapshot = graph.get_state(config)
            if not snapshot.next: raise ValueError('This LangGraph review has already been resolved')
            # Reject before Command(resume=...) can consume/persist the interrupt value.
            validate_decision(snapshot.values, decision)
            result = graph.invoke(Command(resume=decision), config)
            snapshot = graph.get_state(config)
            return {**receipt, 'checkpoint_id': snapshot.config['configurable']['checkpoint_id'],
                    'status': result['disposition']}

    def export_history(self, receipt):
        """Read scoped snapshots through LangGraph, never copy a live SQLite file."""
        config = {'configurable': {'thread_id': receipt['thread_id']}}
        with SqliteSaver.from_conn_string(str(self.path)) as saver:
            graph = review_graph(saver)
            return [{'checkpoint_id': s.config['configurable']['checkpoint_id'],
                     'created_at': s.created_at, 'next': list(s.next), 'values': s.values,
                     'interrupts': [{'id': i.id, 'value': i.value} for i in s.interrupts]}
                    for s in graph.get_state_history(config)]
