from research_pipeline import data_direct_workflow as workflow
from research_pipeline.common import read_json, write_json
from test_data_coverage_direct import case, answer as coverage_answer
from test_data_necessity_direct import answer as necessity_answer


def test_full_direct_workflow_reuses_upstream_and_reports(case, tmp_path):
    plan, source, main, _ = case
    original = {str(path): path.read_bytes() for path in (plan, source, main)}
    mp = write_json(tmp_path/'mp.json', {'profiles': [{'id': 'MP004'}]})
    out = tmp_path/'direct'
    calls = []
    def generate(request, **kwargs):
        stage = request['payload']['stage']
        calls.append(stage)
        return (coverage_answer if stage == 'DIRECT_DR_COVERAGE' else necessity_answer)(request)
    result = workflow.run_legacy(plan, source, main, mp, out, generator=generate)
    assert calls == ['DIRECT_DR_COVERAGE', 'NECESSITY_IMPACT_AND_ADVICE_ONLY']
    assert result['provider_calls'] == 0 and result['test_calls'] == 2
    assert result['requirements'] == 2 and result['field_checks'] == 3
    assert (out/'report.html').exists()
    assert read_json(out/'runner_status.json')['status'] == 'COMPLETE'
    assert workflow.run_legacy(plan, source, main, mp, out, generator=generate) == result
    assert len(calls) == 2
    assert all(path.read_bytes() == original[str(path)] for path in (plan, source, main))
