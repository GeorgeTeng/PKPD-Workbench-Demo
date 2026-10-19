from ctxcomp.review_benchmark import fixture,MUTATIONS,benchmark,score
from ctxcomp.io import digest


def test_fixtures_are_source_identical_single_defects_without_exposing_labels():
    clean,_=fixture('CLEAN'); p=clean['payload']
    for case,(index,replacement) in MUTATIONS.items():
        request,affected=fixture(case); q=request['payload']
        assert request['request_sha256']==digest(q)
        assert q['sources']==p['sources'] and q['requirements']==p['requirements']
        assert affected==f'Q{index+1}' and case not in str(request)
        expected=list(p['context']['rules'])
        if replacement is None: expected.pop(index)
        else: expected[index]=replacement
        assert q['context']['rules']==expected


def test_prepare_only_benchmark_never_calls_provider_or_claims_accuracy(tmp_path,monkeypatch):
    monkeypatch.setattr('ctxcomp.review_benchmark.codex_generate',lambda *a,**k:(_ for _ in ()).throw(AssertionError('No model requested')))
    result=benchmark(tmp_path/'fixtures')
    assert result['live'] is False and result['cases']==[]
    assert len(list((tmp_path/'fixtures').glob('*/input.json')))==7


def test_semantic_detection_is_distinct_from_blocking_for_another_reason():
    result=score({'review':{'decision':'REVISE','coverage':[{'requirement_id':'Q1','verdict':'PRESERVED','components':[]}]}},'Q1')
    assert result['defect_detected_in_requirement_coverage'] is False
    assert result['false_release'] is False



def test_split_faithfulness_mode_is_benchmarked_on_the_same_fixture(tmp_path,monkeypatch):
    from pathlib import Path
    from ctxcomp import review_benchmark as bench, split_review as split
    request,_=fixture('UNITS_CHANGED'); v2=bench.with_mode(request,'parallel_v2')
    assert {k:v for k,v in v2['payload'].items() if k!='context_review_mode'}==request['payload']
    parts=split.faithfulness_parts(v2)
    assert sorted(path for part in parts for path in part['paths'])==sorted(x['path'] for x in request['payload']['evidence'])
    seen={}
    def fake_execute(run,base,invocation,generate,executor_id=None):
        seen[Path(run).name]=base['payload'].get('context_review_mode','parallel_v1')
        return {'review':{'decision':'PASS','coverage':[]}}
    monkeypatch.setattr(bench,'execute',fake_execute)
    report=bench.benchmark(tmp_path/'out',live=True,cases=['CLEAN'],modes=['parallel_v1','parallel_v2'])
    assert seen=={'parallel_v1':'parallel_v1','parallel_v2':'parallel_v2'}
    assert set(report['summary'])=={'parallel_v1','parallel_v2'}
