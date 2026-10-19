import copy
import pytest
from research_pipeline import direct_preparation as dp, data_necessity_editorial as ed
from research_pipeline.common import read_json, write_json, PipelineError
from research_pipeline.adequacy import file_ref
from test_direct_preparation import direct_checkpoint, approve
from test_data_agents import case as table_case


def revised(c, monkeypatch):
    original=read_json(c['nec_path']);updated=copy.deepcopy(original)
    updated['analyses'][0]['next_action']='Compare matched records.'
    folder=c['result_run']/'editorial'
    corrections=write_json(folder/'editorial_corrections.json',{'synthetic_fixture':True})
    updated['editorial_review']={'original':file_ref(c['nec_path']), 'corrections':file_ref(corrections), 'human_approval':False}
    path=write_json(folder/'necessity.reviewed.json',updated)
    # The independent editorial verifier has its own exact-replay tests.
    monkeypatch.setattr(ed,'verify_result',lambda p:read_json(p))
    return path


def test_revised_gate_and_dp_consume_same_effective_assessment(direct_checkpoint,monkeypatch):
    c=direct_checkpoint;path=revised(c,monkeypatch)
    c['gate']=c['store'].publish(c['result_run']);c['review_path']=c['store'].path(c['gate']['id'])
    assert c['gate']['effective_assessment_name']=='necessity.reviewed.json'
    approve(c)
    context=dp.import_inputs(file_ref(c['review_path']),c['root']/'new_dp/context.json')
    assert context['assessment']==file_ref(path)
    assert dp.reviewed(file_ref(c['review_path']))[-1]['analyses'][0]['next_action']=='Compare matched records.'
    assert context['upstream_data']['necessity']==file_ref(path)


def test_new_revision_does_not_upgrade_old_approval(direct_checkpoint,monkeypatch):
    c=direct_checkpoint;approve(c);old=c['review_path'].read_bytes()
    revised(c,monkeypatch)
    gate=c['store'].publish(c['result_run'])
    assert gate['id']!=c['gate']['id'] and not gate['approved']
    assert c['review_path'].read_bytes()==old
    context=dp.import_inputs(file_ref(c['review_path']),c['root']/'old_dp/context.json')
    assert context['assessment']==file_ref(c['nec_path'])


def test_effective_pointer_tampering_invalidates_review(direct_checkpoint):
    c=direct_checkpoint;approve(c)
    value=read_json(c['review_path'])
    value['inputs']['effective_assessment']=file_ref(c['cov_path'])
    write_json(c['review_path'],value)
    with pytest.raises(PipelineError): dp.reviewed(file_ref(c['review_path']))
