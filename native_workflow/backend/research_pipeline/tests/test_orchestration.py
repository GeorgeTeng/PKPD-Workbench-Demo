import sys
from pathlib import Path
import pytest
from research_pipeline.common import write_json, read_json, sha256, utcnow
from research_pipeline.workflow_runtime import make_plan, execute_contract, ref
from research_pipeline.context_router import route_context
from ctxcomp.intake import intake_files


def fresh_spec(tmp_path):
    proposal = tmp_path / 'new_proposal.txt'; proposal.write_text('Study polymyxin B animal PK and free PK/PD indices.', encoding='utf-8')
    data = tmp_path / 'new_data.csv'; data.write_text('time_h,concentration_mg_L\n0,0\n1,2\n', encoding='utf-8')
    job = tmp_path / 'job'; job.mkdir()
    return {'id': 'fresh_test', 'created_at': utcnow(), 'mode': 'fresh', 'job_dir': str(job),
            'out': str(tmp_path / 'run'), 'uploads': [{'path': str(p), 'name': p.name} for p in [proposal, data]]}


def test_new_uploads_have_minimal_contracts_and_review_boundary(tmp_path):
    spec = fresh_spec(tmp_path); plan = make_plan(spec)
    assert plan['targets'] == {'intake':'intake','compression':'compress',
                               'project_rules':'project_rules_publish','context':'project_rules_publish'}
    assert plan['steps']['project_rules_prepare']['depends']==['compress']
    assert 'exploratory_results' not in plan['targets']
    contract = read_json(plan['steps']['compress']['contract'])
    assert len(contract['inputs']) == 1
    assert 'baseline' not in str(contract)
    assert 'sources' not in plan['steps']  # QC requires the reviewed-context adequacy gate
    assert plan['automatic_retries'] == 0


def test_changed_source_and_completed_artifacts_cannot_be_reused(tmp_path):
    spec = fresh_spec(tmp_path); plan = make_plan(spec)
    execute_contract(plan['steps']['intake']['contract'])
    receipt = read_json(Path(spec['job_dir']) / 'receipts/intake.json')
    assert receipt['status'] == 'SUCCEEDED'
    Path(receipt['outputs'][0]['path']).write_text('{}', encoding='utf-8')
    with pytest.raises(ValueError, match='Changed or missing'): make_plan(spec)


def test_reference_bytes_never_parsed_in_fresh_upload_mode(tmp_path):
    source = tmp_path / 'benchmark_reference.json'; source.write_bytes(b'not json and must not be parsed')
    result = intake_files(tmp_path / 'intake', paths=[source], opaque_references=True)
    item = result['manifest']['files'][0]
    assert item['role'] == 'REFERENCE_ONLY' and item['parsed_content_chunks'] == 0
    assert not item['content_sent_to_context']
    assert 'not json' not in str(result)


def test_failed_process_writes_no_success_receipt_and_blocks_next_step(tmp_path):
    root = tmp_path / 'run'; root.mkdir()
    path = tmp_path / 'step.json'
    contract = {'stage': 'fail', 'kind': 'commands', 'options': {}, 'inputs': [], 'outputs': [],
        'commands': [[sys.executable, '-c', 'raise SystemExit(7)']], 'cpu_slots': 1,
        'dependency_receipts': [], 'receipt': str(tmp_path / 'done.json'), 'run_root': str(root),
        'attempts_dir': str(tmp_path / 'attempts'), 'cancel_file': str(tmp_path / 'cancel.flag'), 'partial_paths': []}
    write_json(path, contract)
    with pytest.raises(RuntimeError, match='exit 7'): execute_contract(path)
    assert not (tmp_path / 'done.json').exists()
    with pytest.raises(RuntimeError, match='Another block failed'): execute_contract(path)


def test_router_separates_species_and_keeps_endpoints(tmp_path):
    run = tmp_path
    write_json(run / 'B1/main.json', {'data': {'files': []}})
    write_json(run / 'data_preparation/main.json', {'fit_ready': False})
    for species in ['rat', 'mouse']:
        write_json(run / 'model_inputs' / (species + '.json'), {'records': [{'species': species}], 'metadata': {'species': species}})
    datasets = []
    for identifier in ['rat_plasma_IV', 'terminal_FADDI_PA038', 'S02_T3_FADDI_KP032', 'S01_plasma_binding']:
        p = write_json(run / (identifier + '.json'), {'records': []})
        datasets.append({'id': identifier, 'json': ref(p), 'metadata': {}})
    write_json(run / 'data_preparation/normalization_manifest.json', {'datasets': datasets})
    route_context(run)
    rat = read_json(run / 'handoffs/rat_population.json')
    assert rat['records'] == [{'species': 'rat'}] and not rat['task']['data_gate_signed']
    index = read_json(run / 'handoffs/index.json')
    assert {d['id'] for d in index['datasets']} == {'terminal_FADDI_PA038', 'S02_T3_FADDI_KP032', 'S01_plasma_binding'}
    assert 'objective' not in index and 'rules' not in index
    assert not read_json(run / 'handoffs/routing_plan.json')['full_proposal_forwarded']
