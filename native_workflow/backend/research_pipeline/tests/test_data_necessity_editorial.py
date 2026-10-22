import copy
import pytest
from research_pipeline import data_necessity_editorial as ed
from research_pipeline.common import write_json,read_json,PipelineError


def fixture(tmp_path,monkeypatch):
    original={'analyses':[{'id':'NA001','next_action':'Find a key.','conditions_to_verify':[]}],
        'assessment':{'decision':'CONDITIONAL_PASS'},'action_decisions':{'PD_INDEX':'NOT_READY'},
        'scientific_approval':False,'downstream_executed':False}
    path=write_json(tmp_path/'original.json',original)
    monkeypatch.setattr(ed.necessity,'verify_result',lambda p:read_json(p))
    patches=[{'analysis_id':'NA001','field':'next_action','before':'Find a key.',
        'after':'Compare matched records.','reason':'Finding the key is advice, not the blocked analysis.',
        'basis':'Original requirement for matched-record comparison.'}]
    return path,original,patches


def test_editorial_preserves_original_and_all_data_opinions(tmp_path,monkeypatch):
    path,original,patches=fixture(tmp_path,monkeypatch)
    result=ed.create(path,patches,tmp_path/'reviewed')
    assert read_json(path)==original
    assert result['action_decisions']==original['action_decisions']
    assert result['assessment']==original['assessment']
    assert not result['editorial_review']['human_approval']
    assert ed.verify_result(tmp_path/'reviewed/necessity.reviewed.json')==result
    result['assessment']['decision']='PASS'
    write_json(tmp_path/'reviewed/necessity.reviewed.json',result)
    with pytest.raises(PipelineError):ed.verify_result(tmp_path/'reviewed/necessity.reviewed.json')


@pytest.mark.parametrize('damage',['changed_before','changed_field','missing_basis'])
def test_editorial_cannot_change_verdict_or_unmatched_text(tmp_path,monkeypatch,damage):
    _,original,patches=fixture(tmp_path,monkeypatch)
    if damage=='changed_before':patches[0]['before']='another value'
    elif damage=='changed_field':patches[0]['field']='impact'
    else:patches[0]['basis']=''
    with pytest.raises(PipelineError):ed.apply(original,patches)
