"""Global route coverage and rule-policy consistency, with no provider calls."""
import copy
import json

import pytest
from ctxcomp.governance import load_governance
from research_pipeline import context_minimal_policy as policy
from research_pipeline.common import read_json


def test_every_current_route_has_explicit_task_purpose_and_evidence_boundary():
    value, binding = policy.load_policy()
    routes = read_json(policy.ROUTES)['routes']
    assert len(routes) == 34
    assert 'context.sufficiency' in routes
    assert set(value['routes']) == set(routes)
    for route in routes:
        contract = policy.route_contract(route)
        assert contract['purpose'] and contract['model_needs'] and contract['evidence_boundary']
        assert contract['policy_ref'] == binding
    assert policy.route_contract('data.requirements')['profile'] == 'requirements_planning'
    assert policy.route_contract('data.coverage')['profile'] == 'source_assessment'
    assert policy.route_contract('compression.review')['profile'] == 'source_review'
    assert policy.route_contract('data.human_summary')['profile'] == 'accepted_summary'


def test_shared_g005_governs_all_stages_and_mirror_matches():
    value = load_governance()
    assert value['version'] == policy.load_policy()[0]['governance_version'] == '1.6.1'
    assert value['scope'] == 'ALL_WORKFLOW_STEPS'
    g005 = next(r for r in value['rules'] if r['id'] == 'G005')
    assert 'minimum self-contained semantic context' in g005['instruction']
    assert any('identifiers required' in action for action in g005['actions'])
    assert any('hard truncation' in action for action in g005['actions'])
    mirror = policy.HERE.parents[2] / 'docs/interfaces/workflow_governance.json'
    assert read_json(mirror) == value


def test_unknown_route_rejected():
    with pytest.raises(ValueError, match='No minimal-context contract'):
        policy.route_contract('data.unregistered_future_stage')


@pytest.mark.parametrize('stage', ['DIRECT_DR_COVERAGE', 'DC-review', 'context',
    'NECESSITY_SCOPED_ASSESSMENT', 'HUMAN_REVIEW_SUMMARY_ONLY', 'DR-access', 'DP', 'DH-handoff'])
def test_actual_projection_gate_keeps_complete_assigned_evidence_across_stages(stage):
    from ctxcomp.io import digest
    from research_pipeline import context_model_view
    from research_pipeline.minimal_context_reducer import expand_payload
    units=[{'id':'U'+str(i), 'source_id':'S'+str(i),
            'text':'Independent assigned evidence '+str(i), 'unit':'mg/L',
            'qualifier':'Conflicting evidence; do not average or infer a join.'} for i in range(4)]
    field = ('recorded_shortages' if stage == 'NECESSITY_SCOPED_ASSESSMENT' else
             'assessment' if stage == 'HUMAN_REVIEW_SUMMARY_ONLY' else 'source_units')
    assigned = {'accepted_findings':units} if field == 'assessment' else units
    payload={'stage':stage, 'instructions':'Preserve the complete assigned task basis.',
             'schema':{'type':'object'}, field:assigned}
    request={'payload':payload,'request_sha256':digest(payload)}
    visible,audit=context_model_view.project(request)
    assert expand_payload(visible['payload'])[field]==assigned
    assert audit['minimal_context']['task_profile']
    assert 'minimal_context_policy' in audit['bindings']
    assert visible['request_sha256']==request['request_sha256']


@pytest.mark.parametrize('change', ['missing_route', 'unknown_profile', 'fallback'])
def test_policy_cannot_silently_skip_route_or_use_full_payload_fallback(tmp_path, monkeypatch, change):
    value = copy.deepcopy(policy.load_policy()[0])
    if change == 'missing_route': value['routes'].pop('data.requirements')
    if change == 'unknown_profile': value['routes']['data.requirements']['profile'] = 'missing'
    if change == 'fallback': value['implicit_full_payload_fallback'] = True
    path = tmp_path / 'policy.json'
    path.write_text(json.dumps(value), encoding='utf-8')
    monkeypatch.setattr(policy, 'POLICY', path)
    with pytest.raises(ValueError): policy.load_policy()
