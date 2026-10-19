"""Route/stop tests use synthetic models; no external calls or Data execution."""
import json
import pytest
from research_pipeline import first_part_cli as cli
from research_pipeline.common import read_json
from test_first_part_handoff import prepared, passing
from test_project_rule_agent import bundle


def test_run_routes_only_prepare_review_publish(prepared, monkeypatch):
    root, proof = prepared
    calls=[]
    def generator(req, **kwargs):
        calls.append(req['payload']['stage'])
        assert kwargs['model']=='gpt-6-luna' and 0 < kwargs['timeout'] < 1500
        return passing(req)
    result=cli.run(proof['pack_ref']['path'],root/'workflow',generator=generator)
    assert result['status']=='FIRST_PART_REVIEWED'
    assert calls==['first_part_review']
    assert not result['data_started'] and not result['scientific_approval']
    assert cli.handoff.verify_final_main(result['handoff_main_ref']['path'])['status']=='VALID'
    assert not (root/'workflow/plan.json').exists()


@pytest.mark.parametrize('failure', ['REVISE','UNRESOLVED','engine_error','invalid_response'])
def test_failure_never_publishes_or_retries(prepared, failure):
    root, proof=prepared; calls=[]
    def generator(req, **kwargs):
        calls.append(1)
        if failure=='engine_error': raise RuntimeError('synthetic provider failure')
        result=passing(req)
        if failure=='invalid_response':result['main_sha256']='0'*64
        else:result['decision']=failure;result['checks'][0]['verdict']=failure
        return result
    result=cli.run(proof['pack_ref']['path'],root/'workflow',generator=generator)
    assert len(calls)==1 and result['handoff_main_ref'] is None
    assert result['status']==('FIRST_PART_REVISION_REQUIRED' if failure in {'REVISE','UNRESOLVED'} else 'ERROR')
    assert not (root/'workflow/published').exists()
    assert read_json(root/'workflow/workflow_status.json')==result
    with pytest.raises(Exception):cli.handoff.verify_final_main(root/'workflow/candidate/main.json')
    with pytest.raises(ValueError):cli.run(proof['pack_ref']['path'],root/'workflow',generator=generator)


def test_cli_saved_pass_publish_verify_without_model(prepared, monkeypatch, capsys):
    root,proof=prepared
    cli.handoff.review(root/'combined',generator=passing)
    def forbidden(*args,**kwargs):raise AssertionError('No model should run')
    monkeypatch.setattr(cli.handoff,'codex_generate',forbidden)
    assert cli.main(['publish','--prepared',str(root/'combined'),'--out',str(root/'final')])==0
    capsys.readouterr()
    assert cli.main(['verify','--main',str(root/'final/main.json')])==0
    assert json.loads(capsys.readouterr().out)['status']=='VALID'


def test_cli_prepare_is_not_a_data_handoff(prepared, capsys):
    root,proof=prepared
    assert cli.main(['prepare','--rules-pack',proof['pack_ref']['path'],'--out',str(root/'fresh')])==0
    result=json.loads(capsys.readouterr().out)
    assert result['status']=='PREPARED_NOT_REVIEWED' and result['handoff_main_ref'] is None
    assert cli.main(['verify','--main',str(root/'fresh/main.json')])==2


@pytest.mark.parametrize('status,exitcode',[('FIRST_PART_REVIEWED',0),('FIRST_PART_REVISION_REQUIRED',3),('ERROR',2)])
def test_cli_exit_statuses(monkeypatch,status,exitcode,capsys):
    monkeypatch.setattr(cli,'run',lambda *args:{'status':status})
    assert cli.main(['run','--rules-pack','pack.json','--out','new'])==exitcode
    assert json.loads(capsys.readouterr().out)['status']==status


@pytest.mark.parametrize('budget',['0','-1','1801','nan','inf'])
def test_cli_rejects_invalid_budget(budget):
    with pytest.raises(SystemExit):cli.main(['run','--rules-pack','unused','--out','unused','--budget-seconds',budget])
