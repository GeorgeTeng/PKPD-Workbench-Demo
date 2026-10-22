"""Host-only model-switch cache checks; no provider or scientific review."""
from research_pipeline import data_agents as d
from research_pipeline.common import read_json

SCHEMA={'type':'object','properties':{'request_sha256':{'type':'string'},'value':{'type':'integer'}},
        'required':['request_sha256','value'],'additionalProperties':False}

def test_explicit_dp_reuse_preserves_origin_and_rechecks(tmp_path):
    calls=[];checks=[]
    def generator(request,**options):
        calls.append(options['model'])
        return {'request_sha256':request['request_sha256'],'value':1}
    generator.executor_id='lineage-fixture'
    def check(response):
        checks.append(response['value'])
        assert response['value']==1
    d.invoke(tmp_path,'DP',{'table':'one'},SCHEMA,model='gpt-6.1-sol',generator=generator,check=check)
    d.invoke(tmp_path,'DP',{'table':'one'},SCHEMA,model='gpt-6-astra',reuse_model='gpt-6.1-sol',generator=generator,check=check)
    assert calls==['gpt-6.1-sol'] and checks==[1,1]
    import json
    reused=json.loads((tmp_path/'data_agents/cache_reuse.jsonl').read_text().splitlines()[-1])
    assert reused['executor']=='lineage-fixture:gpt-6.1-sol'
    assert reused['requested_executor']=='lineage-fixture:gpt-6-astra'
    assert reused['reused_from_model']=='gpt-6.1-sol'
    assert reused['requested_model']=='gpt-6-astra'
    assert len(list((tmp_path/'data_agents/kept').glob('*.json')))==1
    assert len(list((tmp_path/'data_agents/audit/DP').glob('*/request.json')))==1
    assert len(list((tmp_path/'data_agents/audit/DP').iterdir()))==1
    d.invoke(tmp_path,'DP',{'table':'changed'},SCHEMA,model='gpt-6-astra',reuse_model='gpt-6.1-sol',generator=generator,check=check)
    assert calls==['gpt-6.1-sol','gpt-6-astra']

def test_model_switch_without_explicit_reuse_calls_new_model(tmp_path):
    calls=[]
    def generator(request,**options):
        calls.append(options['model'])
        return {'request_sha256':request['request_sha256'],'value':1}
    generator.executor_id='lineage-fixture'
    for model in ('gpt-6.1-sol','gpt-6-astra'):
        d.invoke(tmp_path,'DP',{'table':'one'},SCHEMA,model=model,generator=generator,check=lambda response: True)
    assert calls==['gpt-6.1-sol','gpt-6-astra']
