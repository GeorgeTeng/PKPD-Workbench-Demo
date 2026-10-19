"""Exercise real LangGraph -> Prefect -> Snakemake with isolated synthetic intake.

No LLM request, PK/PD fit, or approval of research data is made.
"""
from importlib.metadata import version
from pathlib import Path
from uuid import uuid4
from research_pipeline.common import PROJECT, read_json, write_json, utcnow, sha256
from research_pipeline.graph_execution import run_controlled


def main():
    root = PROJECT / 'outputs/Workflow_Stack_Check' / uuid4().hex[:8]
    job = root / 'job'; job.mkdir(parents=True)
    proposal = root / 'synthetic_proposal.txt'
    proposal.write_text('Synthetic engineering test only. Register polymyxin B animal PK data; do not estimate any scientific result.', encoding='utf-8')
    data = root / 'synthetic_data.csv'
    data.write_text('subject_id,time_h,concentration_mg_L\ntest_1,0,0\ntest_1,1,2\n', encoding='utf-8')
    spec = {'id': 'synthetic_stack_' + root.name, 'created_at': utcnow(), 'mode': 'fresh',
            'job_dir': str(job), 'out': str(root / 'run'), 'stop_after': 'intake',
            'uploads': [{'path': str(p), 'name': p.name, 'sha256': sha256(p)} for p in [proposal, data]]}
    request = write_json(job / 'request.json', spec)
    statuses = []
    result = run_controlled(request, 'intake'); statuses.append(result['status'])
    assert result['status'] == 'WAITING_FOR_HUMAN_REVIEW', result
    assert result['control']['controller'] == 'LangGraph' and result['scheduler'] == 'Prefect' and result['executor'] == 'Snakemake'
    receipt = job / 'receipts/intake.json'; digest = sha256(receipt)
    assert read_json(receipt)['status'] == 'SUCCEEDED'
    (job / 'pause.flag').touch()
    result = run_controlled(request, 'intake'); statuses.append(result['status'])
    assert result['status'] == 'PAUSED' and sha256(receipt) == digest
    (job / 'pause.flag').unlink()
    result = run_controlled(request, 'intake'); statuses.append(result['status'])
    assert result['status'] == 'WAITING_FOR_HUMAN_REVIEW' and sha256(receipt) == digest
    assert len(list((job / 'attempts/intake').glob('*/execution.json'))) == 1
    assert not (job / 'receipts/compress.json').exists()
    report = {'at': utcnow(), 'test_only': True, 'passed': True, 'statuses': statuses,
              'receipt_preserved': True, 'intake_attempts': 1, 'llm_calls': 0, 'scientific_release': False,
              'versions': {p: version(p) for p in ['langgraph', 'prefect', 'snakemake']},
              'job_dir': str(job), 'request': str(request),
              'checks': ['real three-layer call chain', 'actual intake files and receipt',
                         'pause boundary acknowledged', 'resume unlocks own DAG and reuses receipt',
                         'no context/model execution after intake gate']}
    path = write_json(root / 'report.json', report)
    print(path)
    print(report)


if __name__ == '__main__': main()
