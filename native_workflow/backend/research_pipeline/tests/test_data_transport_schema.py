"""Transport restrictions preserve governed requests and host rejection."""
import copy
import json
import subprocess
from pathlib import Path
import pytest
from ctxcomp import providers
from research_pipeline import data_agents as d
from research_pipeline.common import PipelineError, read_json, write_json
from test_data_agents import case, assess, approve_dp


@pytest.mark.parametrize('wrong_hash',[False,True])
def test_dp_transport_enums_exact_ids_without_changing_governed_contract(tmp_path,monkeypatch,wrong_hash):
    monkeypatch.setenv('CTXCOMP_MODEL_PROVIDER','codex')
    schema_before=copy.deepcopy(d.PLAN)
    payload={'source_units':{'T1':'headers'},'table':{'label':{
        'columns':[{'evidence':[{'source':'T1:A1','quote':'Time (h)'}]}],
        'stated_values':[{'evidence':[{'source':'T1:B1','quote':'original'}]}]}}}
    before=copy.deepcopy(payload);seen=[]
    def generate(request,**options):
        seen.append(copy.deepcopy(request))
        assert request['payload']['schema']==schema_before
        transport=options['cli_schema']
        assert transport['properties']['request_sha256']['enum']==[request['request_sha256']]
        citation=transport['properties']['tables']['items']['properties']['evidence']['items']['properties']['source']
        assert citation['enum']==['T1','T1:A1','T1:B1']
        assert options['model']=='gpt-6-astra'
        return {'request_sha256':'wrong' if wrong_hash else request['request_sha256'],
                'tables':[{'item_id':'T1','action':'PREPARE','reason':'Preserve source',
                           'columns':[],'evidence':[{'source':'T1','quote':'headers'}]}],
                'findings':[]}
    monkeypatch.setattr(d,'codex_generate',generate)
    if wrong_hash:
        with pytest.raises(PipelineError,match='exact inputs'):
            d.invoke(tmp_path,'DP',payload,d.PLAN,model='gpt-6-astra',check=lambda response:True)
        audit=next((tmp_path/'data_agents/audit/DP').iterdir())
        assert read_json(audit/'response.json')['request_sha256']=='wrong'
        assert not list((tmp_path/'data_agents/kept').glob('*.json'))
    else:
        result=d.invoke(tmp_path,'DP',payload,d.PLAN,model='gpt-6-astra',check=lambda response:True)
        assert result['request_sha256']==seen[0]['request_sha256']
        # The same governed request still finds the existing cache.
        d.invoke(tmp_path,'DP',payload,d.PLAN,model='gpt-6-astra',check=lambda response:True)
        assert len(seen)==1
    assert payload==before and d.PLAN==schema_before


@pytest.mark.parametrize('override',[False,True])
def test_codex_cli_enforces_transport_schema_while_prompt_retains_governed_schema(tmp_path,monkeypatch,override):
    monkeypatch.setenv('CTXCOMP_MODEL_PROVIDER','codex')
    monkeypatch.setattr(providers.shutil,'which',lambda name:'synthetic-codex')
    base={'type':'object','properties':{'request_sha256':{'type':'string'}}}
    transport=copy.deepcopy(base)
    transport['properties']['request_sha256']['enum']=['bound-hash']
    request={'request_sha256':'bound-hash','payload':{'stage':'DP','schema':base}}
    before=copy.deepcopy(request)
    def run(command,prompt,cwd,*args,**kwargs):
        supplied=read_json(Path(command[command.index('--output-schema')+1]))
        assert supplied==(transport if override else base)
        assert prompt.endswith(providers.canonical(request))
        write_json(Path(command[command.index('--output-last-message')+1]),{'request_sha256':'bound-hash'})
        return subprocess.CompletedProcess(command,0,'','')
    monkeypatch.setattr(providers,'monitored_run',run)
    result=providers.codex_generate(request,model='gpt-6-astra',diagnostics_dir=tmp_path,
                                    **({'cli_schema':transport} if override else {}))
    assert result=={'request_sha256':'bound-hash'} and request==before


@pytest.mark.parametrize('headers,expected',[
    (['Time (h)','Concentration (mg/L)','duplicate','duplicate'],
     {('Time (h)','time_h'),('Concentration (mg/L)','concentration_mg_L')}),
    (['TIME','Y'],set()),
])
def test_transport_only_allows_executable_unique_header_target_pairs(tmp_path,monkeypatch,headers,expected):
    monkeypatch.setenv('CTXCOMP_MODEL_PROVIDER','codex')
    payload={'source_units':{'T1':'source'},'table':{'label':{},'descriptor':{'headers':headers}}}
    def generate(request,**options):
        columns=options['cli_schema']['properties']['tables']['items']['properties']['columns']
        if expected:
            actual={(pair['properties']['source_header']['enum'][0],pair['properties']['target']['enum'][0])
                    for pair in columns['items']['anyOf']}
            assert actual==expected
        else:
            assert columns['maxItems']==0
        return {'request_sha256':request['request_sha256'],'tables':[
            {'item_id':'T1','action':'PREPARE','reason':'Preserve source','columns':[],
             'evidence':[{'source':'T1','quote':'source'}]}],'findings':[]}
    monkeypatch.setattr(d,'codex_generate',generate)
    d.invoke(tmp_path,'DP',payload,d.PLAN,model='gpt-6-astra',check=lambda response:True)


def test_unsupported_mapping_rejected_before_cache_or_execution(case):
    _,run,_,_,original,_=case
    context=approve_dp(assess(case));plan=run/'unsupported_plan.json'
    def generate(request,**options):
        response=original(request,**options)
        response['tables'][0]['columns']=[{'target':'concentration_mg_L','source_header':'Time (h)'}]
        return response
    generate.executor_id='unsupported-mapping-fixture'
    with pytest.raises(PipelineError,match='adapter cannot execute'):
        d.plan_preparation(run,context,plan,model='gpt-6-astra',generator=generate)
    assert not plan.exists()
    assert not list((run/'data_agents/kept').glob('*.json'))
    assert not (run/'data_preparation').exists()


def test_executor_still_rejects_unsupported_mapping_if_plan_is_altered(case):
    _,run,_,_,original,_=case
    context=approve_dp(assess(case));plan_path=run/'altered_plan.json'
    d.plan_preparation(run,context,plan_path,generator=original)
    plan=read_json(plan_path)
    plan['tables'][0]['columns']=[{'target':'concentration_mg_L','source_header':'Time (h)'}]
    write_json(plan_path,plan)
    with pytest.raises(PipelineError,match='Explicit compatible header units'):
        d.execute_preparation(context,plan_path,run/'data_preparation')
    assert not (run/'data_preparation/preparation_execution.json').exists()
    assert not (run/'data_preparation/data_report.json').exists()
