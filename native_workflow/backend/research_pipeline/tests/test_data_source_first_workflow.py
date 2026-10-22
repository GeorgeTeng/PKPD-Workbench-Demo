import copy
import json
import pytest
from research_pipeline import data_source_first_workflow as sf
from research_pipeline.common import read_json,write_json


def test_bound_generated_artifact_tamper_is_rejected(tmp_path,monkeypatch):
    main=write_json(tmp_path/'main.json',{'version':'4.0'})
    output=write_json(tmp_path/'source_view.json',{'profiles':[]})
    ref=sf.file_ref(main)
    write_json(tmp_path/'manifest.json',{'version':sf.VERSION,'bindings':{'main':ref}})
    monkeypatch.setattr(sf,'verify_final_main',lambda p:{'main_ref':ref})
    sf.bind_outputs(tmp_path,['source_view.json'])
    assert sf.verify_run(tmp_path)[0]['bindings']['output:source_view.json']==sf.file_ref(output)
    write_json(output,{'profiles':['changed']})
    with pytest.raises(Exception):sf.verify_run(tmp_path)


@pytest.mark.parametrize('identity',[None,'FIXTURE_A','FIXTURE_B'])
def test_generator_cache_identity_is_explicit(tmp_path,monkeypatch,identity):
    seen=[]
    def fake(req,**kw):return {}
    if identity:fake.executor_id=identity
    def invoke(run,stage,payload,schema,**kw):
        seen.append(kw['generator'].executor_id)
        assert kw['model']=='gpt-6-luna'
        assert payload['scientific_approval'] is False
        return {}
    monkeypatch.setattr(sf.d,'invoke',invoke)
    sf.invoke(tmp_path,'DC-label',{}, {},generator=fake)
    assert seen==[sf.VERSION+':'+identity if identity else None]


def test_telemetry_appends_calls_and_marks_error(tmp_path,monkeypatch):
    def call(run,stage,payload,schema,**kw):
        return kw['generator']({'request_sha256':'abc','payload':payload})
    def fake(req,**kw):raise ValueError('synthetic failure')
    monkeypatch.setattr(sf.d,'invoke',call)
    for _ in range(2):
        with pytest.raises(ValueError):sf.invoke(tmp_path,'DC-label',{'item_id':'A'}, {},generator=fake)
    events=[json.loads(x) for x in (tmp_path/'events.jsonl').read_text().splitlines()]
    assert [e['event'] for e in events]==['MODEL_START','MODEL_END']*2
    assert len({e['call_id'] for e in events})==2
    assert all(e['status']=='ERROR' for e in events if e['event']=='MODEL_END')


def test_source_view_preserves_notes_findings_and_isolates_legacy_associations(tmp_path,monkeypatch):
    item={'id':'I','descriptor':{'kind':'document','notes':'uncertain dose basis'}}
    label={'item_id':'I','requirement_ids':['OLD_Q'],'reason':'Only relevant to OLD_Q',
        'stated_values':[{'quantity':'dose','value':'2','evidence':[{'source':'I:line1','quote':'2 mg'}]}],
        'evidence':[{'source':'I:line1','quote':'2 mg'}]}
    findings=[{'reason':'Unresolved identity','affected_id':'OLD_Q'}]
    write_json(tmp_path/'inventory.json',{'items':[item]})
    write_json(tmp_path/'permissions.json',{'access':[{'item_id':'I','disposition':'REVIEW_DATA'}]})
    write_json(tmp_path/'legacy_import.json',{'labels':[label],'findings':findings})
    monkeypatch.setattr(sf,'verify_run',lambda p:({'bindings':{'main':{'path':'main','sha256':'x'}}},{}))
    monkeypatch.setattr(sf.d,'content_units',lambda i:[('I:line1','Dose 2 mg. Identity unresolved.')])
    sf.build_source_view(tmp_path);view=read_json(tmp_path/'source_view.json')
    assert view['legacy_findings']==findings
    assert view['legacy_association_history'][0]['requirement_ids']==['OLD_Q']
    assert 'requirement_ids' not in view['profiles'][0] and 'reason' not in view['profiles'][0]
    assert 'uncertain dose basis' in view['source_units']['I']
    assert view['source_units']['I:line1']=='Dose 2 mg. Identity unresolved.'
    assert view['profiles'][0]['stated_values'][0]['evidence_source_ids']==['I:line1']
