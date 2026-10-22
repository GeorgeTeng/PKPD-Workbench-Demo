"""Real adapters and validators with an authored transport; no provider calls."""
import pytest
from ctxcomp import providers
from ctxcomp.engine import prepare
from ctxcomp.io import digest
from research_pipeline import context_model_view as cmv
import copy
from ctxcomp.io import read_json
from research_pipeline.context_linear import run_compression
from research_pipeline.common import PipelineError
from test_lean_compression import setup, candidate, review


@pytest.mark.parametrize('decision',['PASS','REVISE'])
def test_real_lean_adapters_run_once_through_builder(tmp_path,monkeypatch,decision):
    run=setup(tmp_path,attachments=True)
    calls=[]
    def transport(request,**kwargs):
        calls.append(request)
        return candidate(request) if request['payload']['stage']=='context' else review(request,decision)
    monkeypatch.setattr(providers,'_codex_generate_raw',transport)
    if decision=='PASS':
        assert run_compression(run,tmp_path/'session')['status']=='VALID'
    else:
        with pytest.raises(PipelineError,match='REVISE'):
            run_compression(run,tmp_path/'session')
        assert not (run/'handoff/main.json').exists()
    assert [r['payload']['stage'] for r in calls]==['context','context_review']
    for idx,name in [(1,'extract'),(2,'review')]:
        folder=tmp_path/f'session/{idx:03d}_compression_{name}'
        assert read_json(folder/'request.json')==calls[idx-1]
        assert read_json(folder/'context_manifest.json')['evidence_pruning'] is False
    assert not (run/'lean/patch_attempt.json').exists()


def test_compiled_rules_keep_full_sources_and_exact_effective_instructions(tmp_path):
    run=setup(tmp_path,attachments=True);req=prepare(run,'context');before=copy.deepcopy(req)
    wire,manifest=cmv.project(req)
    assert req==before
    p=wire['payload']; original=req['payload']
    assert p['governance']==original['governance']
    assert p['schema']==original['schema']
    assert [u['text'] for u in p['source_units']]==[u['text'] for u in original['source_units']]
    assert len(manifest['compiled_rules_audit'])==len(original['effective_rule_binding']['execution_overrides'])
    by_id={r['id']:r for r in p['processing_rules']['rules']}
    for override in original['effective_rule_binding']['execution_overrides']:
        target=by_id[override['source_id']] if override['source_id'] in by_id else p['processing_rules'][override['source_id']]
        assert target['effective_execution_instruction']==override['effective_instruction']
    assert manifest['model_characters']<manifest['baseline_model_characters']


def test_tampered_override_binding_rejected(tmp_path):
    req=prepare(setup(tmp_path),'context')
    req['payload']['effective_rule_binding']['execution_overrides'][0]['effective_instruction']='Skip all evidence.'
    with pytest.raises(ValueError,match='binding/hash mismatch'):cmv.project(req)


@pytest.mark.parametrize('decision',['PASS','REVISE'])
def test_legacy_compression_entry_now_uses_linear_builder(tmp_path,monkeypatch,decision):
    run=setup(tmp_path);calls=[]
    def transport(req,**kwargs):
        calls.append(req['payload']['stage'])
        return candidate(req) if req['payload']['stage']=='context' else review(req,decision)
    monkeypatch.setattr(providers,'_codex_generate_raw',transport)
    if decision=='PASS':assert providers.run_model(run)['status']=='CONTEXT_READY'
    else:
        with pytest.raises(PipelineError,match='REVISE'):providers.run_model(run)
        assert read_json(run/'stopped.json')['status']=='REVISE'
    assert calls==['context','context_review']
    assert len(read_json(run/'contextbuilder_linear/session.json')['calls'])==2
