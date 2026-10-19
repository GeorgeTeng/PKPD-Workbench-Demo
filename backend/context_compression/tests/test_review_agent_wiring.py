"""Real provider construction with a stubbed CLI transport; no live LLM accuracy claim."""
import json
import subprocess
import sys
import threading
from pathlib import Path
import pytest
from ctxcomp.engine import init_run, load_run, prepare, accept, verify_context
from ctxcomp.io import read_json, write_json, digest
from ctxcomp import providers, model_view, split_review as split
from test_retention import reference_run, EXAMPLES
from test_split_review import authored_response, part_response, context_run, complete_branches


def test_new_python_runs_default_to_three_required_agents(tmp_path,monkeypatch):
    monkeypatch.delenv('CTXCOMP_CONTEXT_REVIEW_MODE',raising=False)
    run=tmp_path/'run'; init_run(run,EXAMPLES/'current_research/proposal.md')
    assert load_run(run)[0]['context_review_mode']=='parallel_v3'


def test_new_cli_runs_default_to_three_required_agents(tmp_path,monkeypatch):
    monkeypatch.delenv('CTXCOMP_CONTEXT_REVIEW_MODE',raising=False)
    run=tmp_path/'cli'
    result=subprocess.run([sys.executable,'-I','-X','utf8','-m','ctxcomp','init',
        '--proposal',str(EXAMPLES/'current_research/proposal.md'),'--out',str(run)],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    assert load_run(run)[0]['context_review_mode']=='parallel_v3'


def test_environment_switches_new_runs_back_to_one_faithfulness_review(tmp_path,monkeypatch):
    monkeypatch.setenv('CTXCOMP_CONTEXT_REVIEW_MODE','parallel_v1')
    run=tmp_path/'run'; init_run(run,EXAMPLES/'current_research/proposal.md')
    assert load_run(run)[0]['context_review_mode']=='parallel_v1'
    monkeypatch.setenv('CTXCOMP_CONTEXT_REVIEW_MODE','parallel_v2')
    init_run(tmp_path/'after_both',EXAMPLES/'current_research/proposal.md')
    assert load_run(tmp_path/'after_both')[0]['context_review_mode']=='parallel_v2'
    monkeypatch.setenv('CTXCOMP_CONTEXT_REVIEW_MODE','parallel_v9')
    with pytest.raises(ValueError,match='Unknown context review mode'):
        init_run(tmp_path/'unknown',EXAMPLES/'current_research/proposal.md')


def test_three_agents_reach_separate_ephemeral_provider_calls(tmp_path,reference_run,monkeypatch):
    run,original=context_run(tmp_path/'connected',reference_run,'parallel_v1')
    lock=threading.Lock(); barrier=threading.Barrier(2); calls={}; finished=set()
    monkeypatch.setattr(providers.shutil,'which',lambda _: 'mock-codex')
    def transport(command,prompt,cwd,diagnostics_dir=None,**kwargs):
        request=json.loads(prompt[prompt.index('{'):]); p=request['payload']; stage=p['stage']
        assert model_view.enabled(p) or request['request_sha256']==digest(p)
        assert stage in split.BRANCHES
        assert '--ephemeral' in command and '--ignore-user-config' in command
        assert read_json(Path(command[command.index('--output-schema')+1]))==p['schema']
        if stage in (split.FAITH, split.COMPLETE):
            assert 'scientific_checks' in p['schema']['properties']['review']['required']
        assert p['agent_contract'] and any(r['id']=='CC012' for r in p['processing_rules']['rules'])
        assert [r['id'] for r in p['governance']['rules']] == [f'G{i:03}' for i in range(1, 9)]
        assert any(r['id']=='CC005' and len(r['details']['preserve'])==13 for r in p['processing_rules']['rules'])
        if stage in [split.FAITH,split.COMPLETE]:
            assert 'branch_reviews' not in p
            barrier.wait(timeout=10)
        else:
            assert finished=={split.FAITH,split.COMPLETE}
            assert set(p['branch_reviews'])==finished
        with lock:
            assert stage not in calls
            calls[stage]={'cwd':str(cwd),'request_hash':request['request_sha256'],
                          'diagnostics':str(diagnostics_dir),'request':request}
        response=authored_response(request,original)
        write_json(Path(command[command.index('--output-last-message')+1]),response)
        with lock: finished.add(stage)
        return subprocess.CompletedProcess(command,0,'','')
    monkeypatch.setattr(providers,'monitored_run',transport)
    assert providers.run_model(run)['status']=='CONTEXT_READY'
    assert set(calls)==set(split.BRANCHES)
    for field in ['cwd','request_hash','diagnostics']:
        assert len({c[field] for c in calls.values()})==3
    proof=read_json(run/'parallel_review_proof.json')
    for branch,record in proof['branches'].items():
        stored=read_json(run/record['request'])
        assert stored['request_sha256']==digest(stored['payload']) and model_view.view(stored)==calls[branch]['request']
        assert (run/record['response']).is_file()
    assert verify_context(run)['status']=='VALID'


def test_split_faithfulness_parts_reach_separate_provider_calls(tmp_path,reference_run,monkeypatch):
    run,original=context_run(tmp_path/'connected_v2',reference_run,'parallel_v2'); completes=complete_branches(run)
    first=split.FAITH_PARTS+len(completes); lock=threading.Lock(); barrier=threading.Barrier(first); calls={}
    monkeypatch.setattr(providers.shutil,'which',lambda _: 'mock-codex')
    def transport(command,prompt,cwd,diagnostics_dir=None,**kwargs):
        request=json.loads(prompt[prompt.index('{'):]); p=request['payload']
        label=Path(diagnostics_dir).name
        assert (model_view.enabled(p) or request['request_sha256']==digest(p)) and kwargs.get('cancel_event') is not None
        if label!=split.GLOBAL:
            barrier.wait(timeout=10)  # Parts and completeness run together.
        else:
            assert len(calls)==first and p['branch_reviews'][split.FAITH]['review']['reviewer'].startswith('Faithfulness review in')
        with lock: calls[label]=request
        write_json(Path(command[command.index('--output-last-message')+1]),part_response(request,original))
        return subprocess.CompletedProcess(command,0,'','')
    monkeypatch.setattr(providers,'monitored_run',transport)
    assert providers.run_model(run)['status']=='CONTEXT_READY'
    parts=[f'{split.FAITH}--part_{n}' for n in range(1,split.FAITH_PARTS+1)]
    assert set(calls)=={*parts,*completes,split.GLOBAL}
    assert all(calls[label]['payload']['review_part']['part']==n for n,label in enumerate(parts,1))
    proof=read_json(run/'parallel_review_proof.json')
    for label,record in proof['branches'].items():
        stored=read_json(run/record['request'])
        assert stored['request_sha256']==digest(stored['payload']) and model_view.view(stored)==calls[label]
    assert verify_context(run)['status']=='VALID'


def test_concurrent_conflict_review_reaches_its_own_provider_call(tmp_path,reference_run,monkeypatch):
    run,original=context_run(tmp_path/'connected_v3',reference_run,'parallel_v3'); completes=complete_branches(run)
    lock=threading.Lock(); barrier=threading.Barrier(split.FAITH_PARTS+len(completes)+1); calls={}
    monkeypatch.setattr(providers.shutil,'which',lambda _: 'mock-codex')
    def transport(command,prompt,cwd,diagnostics_dir=None,**kwargs):
        request=json.loads(prompt[prompt.index('{'):]); label=Path(diagnostics_dir).name
        p=request['payload']
        assert (model_view.enabled(p) or request['request_sha256']==digest(p)) and kwargs.get('cancel_event') is not None
        barrier.wait(timeout=10)  # Parts, completeness and the conflict review run together.
        with lock: calls[label]=request
        write_json(Path(command[command.index('--output-last-message')+1]),part_response(request,original))
        return subprocess.CompletedProcess(command,0,'','')
    monkeypatch.setattr(providers,'monitored_run',transport)
    assert providers.run_model(run)['status']=='CONTEXT_READY'
    assert set(calls)=={*[f'{split.FAITH}--part_{n}' for n in range(1,split.FAITH_PARTS+1)],*completes,split.GLOBAL}
    assert 'branch_reviews' not in calls[split.GLOBAL]['payload']
    assert read_json(run/'parallel_review_proof.json')['mode']=='parallel_v3'
    assert verify_context(run)['status']=='VALID'
