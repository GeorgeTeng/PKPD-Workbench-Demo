"""Rule delivery and release gates; authored cases are not live-model qualification."""
import copy
import pytest
from ctxcomp import lean_compression as lean,lean_rules
from ctxcomp.engine import load_run,prepare,accept,verify_context
from ctxcomp.io import digest,read_json,write_json
from test_lean_compression import setup,candidate,review


def test_every_model_phase_receives_one_frozen_rule_projection_and_all_categories(tmp_path):
    run=setup(tmp_path);bundle,state=load_run(run);context=prepare(run,'context')
    response=candidate(context);accept(run,'context',response)
    review_request=prepare(run,'context_review')
    patch_request=lean.patch_request(bundle,lean.content(response),{'fixes':[]},run)
    original=bundle['processing_rules'];cc005=next(r for r in original['rules'] if r['id']=='CC005')
    binding=bundle['lean_effective_rules']
    assert read_json(run/'audit/lean_effective_rules.json')==binding
    for req in (context,review_request,patch_request):
        p=req['payload'];projection=p['processing_rules']
        assert p['governance']==original['governance']
        assert p['governance_sha256']==digest(original['governance'])
        assert projection['scientific_extraction']==original['scientific_extraction']
        assert projection['pk_binding_knowledge']==original['pk_binding_knowledge']
        assert [r['id'] for r in projection['rules']]==[r['id'] for r in original['rules']]
        projected=next(r for r in projection['rules'] if r['id']=='CC005')
        assert projected['details']==cc005['details'] and len(projected['details']['preserve'])==13
        assert p['effective_rule_binding']['source_pack_sha256']==digest(original)
        assert p['effective_rule_binding_sha256']==digest(binding)
        assert p['processing_rules_sha256']==digest(projection)
        assert 'agent_contract' not in p and 'review_agent_contracts' not in p
        assert p['effective_rule_binding']['source_scope']['attachment_search']=='NOT_SEARCHED'
        assert p['host_input_checks']['selected_proposal_file_id']=='S1'
        assert p['host_input_checks']['coverage_status']=='NOT_ASSESSED'
        assert p['host_input_checks']['source_units_sha256']==digest(bundle['source_units'])
    assert set(lean_rules.REVIEW_CHECKS)<=set(review_request['payload']['required_check_ids'])
    assert next(r for r in context['payload']['processing_rules']['rules'] if r['id']=='CC012')['qualification_requirement']==next(r for r in original['rules'] if r['id']=='CC012')['qualification_requirement']


def test_intake_coverage_metadata_is_supplied_without_attachment_body_or_completeness_claim(tmp_path):
    run=setup(tmp_path,attachments=True);bundle,_=load_run(run);payload=prepare(run,'context')['payload']
    host=payload['host_input_checks']
    assert host['coverage_reference']['manifest_sha256']==bundle['intake']['manifest_sha256']
    assert host['coverage_state_sha256'] and host['coverage_status']=='NO_GAPS_DETECTED'
    assert 'not proof of semantic or extraction completeness' in host['limitations'][-1]
    from ctxcomp.io import canonical
    assert 'ATTACHMENT_BODY_MUST_NOT_REACH_MODEL' not in canonical(payload)


def test_unassessed_legacy_coverage_never_claims_detector_pass(tmp_path,monkeypatch):
    run=setup(tmp_path);bundle,_=load_run(run)
    monkeypatch.setattr('ctxcomp.engine.require_source_coverage',lambda *args:{'status':'NOT_ASSESSED','resolutions':[]})
    host=lean_rules.host_input_checks(run,bundle)
    assert host['coverage_status']=='NOT_ASSESSED' and host['coverage_gate']=='NOT_ASSESSED'


def test_each_override_resolves_to_unchanged_original_clause_with_explicit_authority(tmp_path):
    run=setup(tmp_path);bundle,_=load_run(run);pack=bundle['processing_rules']
    sources={r['id']:r for r in pack['rules']};sources['scientific_extraction']=pack['scientific_extraction']
    projection=bundle['lean_effective_rules']
    for override in projection['execution_overrides']:
        assert override['authorization'] and override['effective_instruction']
        assert set(override['source_clause_hashes'])==set(override['clause_paths'])
        for path in override['clause_paths']:
            assert override['source_clause_hashes'][path]==digest(lean_rules.pointer(sources[override['source_id']],path))
    science=pack['scientific_extraction']
    assert projection['processing_rules']['scientific_extraction']['proposition_contract']==science['proposition_contract']
    assert not any(o['source_id']=='CC005' for o in projection['execution_overrides'])


@pytest.mark.parametrize('fault',['no_pack','missing_governance','missing_category','changed_lineage','changed_clause'])
def test_invalid_rule_dependencies_or_bindings_stop_before_request(tmp_path,fault):
    run=setup(tmp_path);bundle,state=load_run(run)
    if fault=='no_pack':bundle.pop('processing_rules')
    elif fault=='missing_governance':bundle['processing_rules']['governance']['rules'].pop()
    elif fault=='missing_category':next(r for r in bundle['processing_rules']['rules'] if r['id']=='CC005')['details']['preserve'].popitem()
    elif fault=='changed_lineage':bundle['lean_effective_rules']['source_rule_sha256']['CC004']='bad'
    else:bundle['lean_effective_rules']['execution_overrides'][0]['source_clause_hashes']['/instruction']='bad'
    with pytest.raises(ValueError):lean.request(run,bundle,state,'context')


def test_changed_effective_rule_audit_is_rejected(tmp_path):
    run=setup(tmp_path);path=run/'audit/lean_effective_rules.json';binding=read_json(path)
    binding['qualification']='QUALIFIED';write_json(path,binding)
    with pytest.raises(ValueError,match='projection changed'):load_run(run)


@pytest.mark.parametrize('objective,status',[('NOT_FOUND','NOT_FOUND'),(' ','EXPLICIT'),('Inferred project','MODEL_INFERENCE')])
def test_unresolved_objective_can_remain_draft_but_cannot_publish_despite_pass(tmp_path,objective,status):
    run=setup(tmp_path);response=candidate(prepare(run,'context'));response['context']['objective']=objective
    evidence=next(e for e in response['evidence'] if e['id']=='/objective');evidence['status']=status
    if status=='NOT_FOUND':evidence['citations']=[]
    assert accept(run,'context',response)['status']=='ACCEPTED'
    with pytest.raises(ValueError,match='CC004'):accept(run,'context_review',review(prepare(run,'context_review')))
    assert not (run/'handoff/main.json').exists()
    assert 'context_review' not in load_run(run)[1]['accepted']


def test_missing_substantive_review_check_cannot_be_hidden_by_pass(tmp_path):
    run=setup(tmp_path);accept(run,'context',candidate(prepare(run,'context')))
    result=review(prepare(run,'context_review'));result['review']['checks']=[x for x in result['review']['checks'] if x['id']!='CC009_proposition_role_and_evidence_status']
    with pytest.raises(ValueError,match='exactly once'):accept(run,'context_review',result)
    assert not (run/'handoff/main.json').exists()


def test_profileless_rule_binding_preserves_old_lean_request_without_retroactive_governance(tmp_path):
    run=setup(tmp_path);bundle,state=load_run(run)
    bundle['compression_profile'].pop('effective_rule_binding');bundle['compression_profile'].pop('review_check_ids')
    bundle['compression_profile']['version']='1.5';bundle.pop('lean_effective_rules')
    before=lean.request(run,bundle,state,'context')
    bundle['processing_rules']={'historical':'not implicitly rebound'}
    after=lean.request(run,bundle,state,'context')
    assert before==after and 'processing_rules' not in after['payload'] and 'governance' not in after['payload']
    assert after['payload']['compression_profile']['version']=='1.5'
