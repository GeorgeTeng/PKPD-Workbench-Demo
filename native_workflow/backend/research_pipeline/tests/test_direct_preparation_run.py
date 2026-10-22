"""Isolated end-to-end runner contracts with synthetic generators only."""
import pytest
from research_pipeline import direct_preparation as preparation
from research_pipeline.common import PipelineError, read_json, write_json
from research_pipeline.adequacy import file_ref
from test_direct_preparation import direct_checkpoint, approve
from test_data_agents import case as table_case
from pathlib import Path
from research_pipeline import data_agents as d


def test_approved_direct_runner_completes_fake_pipeline_and_preserves_boundaries(direct_checkpoint,table_case):
    c=direct_checkpoint;approve(c)
    output=c['root']/'complete_cleaning'
    calls=[]
    original=table_case[4]
    def generate(request,**options):
        calls.append((request['payload']['stage'],options['model']))
        return original(request,**options)
    result=preparation.run(file_ref(c['review_path']),output,model='gpt-6-astra',generator=generate)
    status=read_json(output/'cleaning_status.json')
    assert status['status']=='COMPLETE' and status['stage']=='COMPLETE'
    assert status['requested_model']=='gpt-6-astra'
    assert status['report']==file_ref(output/'data_preparation/data_report.json')
    assert status['scientific_release'] is False and status['downstream_executed'] is False
    assert result['technical_processing_complete'] is True
    assert result['handoff_review_complete'] is True
    assert result['scientific_release'] is False and result['fit_ready'] is False
    assert [stage for stage,_ in calls]==['DH-handoff']
    assert read_json(output/'preparation_plan.json')['executor']=='HOST_PROGRAM'
    assert all(model=='gpt-6-astra' for _,model in calls)
    assert read_json(output/'inputs/context.json')['assessment']==file_ref(c['nec_path'])


def test_pending_direct_runner_stops_before_provider_calls(direct_checkpoint):
    c=direct_checkpoint;calls=[];output=c['root']/'pending_cleaning'
    def forbidden(*args,**kwargs):
        calls.append(True)
        raise AssertionError('Pending checkpoint reached provider')
    with pytest.raises(PipelineError):
        preparation.run(file_ref(c['review_path']),output,model='gpt-6-astra',generator=forbidden)
    status=read_json(output/'cleaning_status.json')
    assert calls==[]
    assert status['status']=='FAILED_RETAINED' and status['stage']=='DP_IMPORT'
    assert not (output/'inputs/context.json').exists()
    assert not (output/'data_preparation/data_report.json').exists()


def test_existing_output_rejects_different_checkpoint_without_calls(direct_checkpoint):
    c=direct_checkpoint;approve(c);output=c['root']/'mismatched_cleaning'
    other=write_json(c['root']/'other_review.json',read_json(c['review_path']))
    original=preparation.import_inputs(file_ref(c['review_path']),output/'inputs/context.json')
    calls=[]
    def forbidden(*args,**kwargs):
        calls.append(True)
        raise AssertionError('Mismatched checkpoint reached provider')
    with pytest.raises(PipelineError,match='different reviewed checkpoint'):
        preparation.run(file_ref(other),output,model='gpt-6-astra',generator=forbidden)
    assert calls==[]
    assert read_json(output/'inputs/context.json')==original
    status=read_json(output/'cleaning_status.json')
    assert status['status']=='FAILED_RETAINED' and status['stage']=='DP_IMPORT'


def test_rerun_repairs_derived_csv_without_dp_or_dh_calls(direct_checkpoint,monkeypatch):
    c=direct_checkpoint;approve(c);output=c['root']/'repair_cleaning';calls=[]
    def forbidden(*args,**kwargs):
        calls.append(True)
        raise AssertionError('Host repair reached a model.')
    monkeypatch.setattr(d,'codex_generate',forbidden)
    options={'model':'gpt-6-astra','generator':forbidden,'review':False}
    preparation.run(file_ref(c['review_path']),output,**options)
    manifest=read_json(output/'data_preparation/normalization_manifest.json')
    csv=Path(manifest['datasets'][0]['csv']['path']);original=csv.read_bytes()
    source_before=Path(c['main']).read_bytes()
    csv.write_text('corrupted derived output\n',encoding='utf-8')
    result=preparation.run(file_ref(c['review_path']),output,**options)
    assert csv.read_bytes()==original and Path(c['main']).read_bytes()==source_before
    checked=read_json(output/'self_check.json')
    assert checked['decision']=='PASS' and checked['reused_execution'] is False
    assert len(checked['repairs'])==1 and checked['repairs'][0]['action']=='REBUILD_DERIVED_FROM_APPROVED_SOURCE'
    assert checked['source_modified'] is False and calls==[]
    assert result['status']=='HOST_COMPLETE_REVIEW_PENDING' and result['handoff_review_complete'] is False
    preparation.run(file_ref(c['review_path']),output,**options)
    assert read_json(output/'self_check.json')['reused_execution'] is True
    assert read_json(output/'self_check.json')['repairs']==[] and calls==[]


def test_rerun_rejects_changed_approved_source_without_repair(direct_checkpoint,monkeypatch):
    c=direct_checkpoint;approve(c);output=c['root']/'changed_source';calls=[]
    def forbidden(*args,**kwargs):
        calls.append(True)
        raise AssertionError('Changed approved source reached a model.')
    monkeypatch.setattr(d,'codex_generate',forbidden)
    options={'model':'gpt-6-astra','generator':forbidden,'review':False}
    preparation.run(file_ref(c['review_path']),output,**options)
    manifest=read_json(output/'data_preparation/normalization_manifest.json')
    csv=Path(manifest['datasets'][0]['csv']['path'])
    csv.write_text('leave corrupted derivative untouched\n',encoding='utf-8')
    source=Path(read_json(c['inventory'])['items'][0]['source']['path'])
    changed=source.read_bytes()+b'\nchanged approved source\n';source.write_bytes(changed)
    with pytest.raises(PipelineError):
        preparation.run(file_ref(c['review_path']),output,**options)
    assert source.read_bytes()==changed and calls==[]
    assert csv.read_text(encoding='utf-8')=='leave corrupted derivative untouched\n'
    assert read_json(output/'cleaning_status.json')['status']=='FAILED_RETAINED'
