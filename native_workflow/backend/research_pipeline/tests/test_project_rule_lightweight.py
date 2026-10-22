"""Active lightweight contract; synthetic reviews do not establish semantic quality."""
import pytest
from research_pipeline import project_rule_agent as a, project_rule_pipeline as ledger
from research_pipeline.common import read_json, write_json
from test_project_rule_agent import bundle
from test_project_rule_compact import extract, review


@pytest.mark.parametrize('decision', ['PASS', 'REVISE'])
def test_fresh_default_uses_two_calls_and_preserves_review_gate(bundle, decision):
    root, _, old = bundle
    value = a._input_value(old['base_main_ref'], old['sources'], old['source_refs'], compact=True)
    assert not ledger.enabled(value)
    assert value['extraction_policy']['version'] == '1.6.0'
    assert value['workflow_reference']['version'] == '1.1.0'
    ref = a.file_ref(write_json(root/'light_input.json', value))
    calls = []
    def generate(req, **kw):
        calls.append(req['payload']['stage'])
        if calls[-1] == 'project_rules_extract':
            return extract(req)
        result = review(req)
        if decision == 'REVISE':
            result['decision'] = 'REVISE'
            result['global_checks'][0].update(verdict='REVISE', reason='Synthetic unnecessary generic instruction')
        return result
    candidate = a.extract(ref, root/'light_extract', generator=generate)
    cr = a.file_ref(root/'light_extract/candidate.json')
    a.review(ref, cr, root/'light_review', generator=generate)
    result = a.publish(ref, cr, a.file_ref(root/'light_review/review.json'), root/'light_published')
    assert calls == ['project_rules_extract', 'project_rules_review']
    assert result['handoff_published'] == (decision == 'PASS')
    assert not (root/'light_review/selection.json').exists()
    if decision == 'PASS':
        pack = a.verify_published(result['project_rules_ref'])
        assert all(set(r) == {'id','text','used_in','evidence'} for r in pack['rules'])
        assert pack['rules'][0]['evidence'] == candidate['items'][0]['evidence']
    else:
        assert not (root/'light_published/project_rules.json').exists()
        assert read_json(root/'light_review/review.json')['decision'] == 'REVISE'


def test_active_prompts_share_project_specific_selection():
    policy = a.compact_rules.POLICY
    assert 'pipeline' not in policy
    for prompt in policy['prompts'].values():
        assert 'drug/project-specific' in prompt
        assert 'generic workflow' in prompt
    assert 'pk_translation' in policy['steps'] and 'human_pk' not in policy['steps']
