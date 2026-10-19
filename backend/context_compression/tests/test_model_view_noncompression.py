"""Only explicitly opted-in compression payloads may use compression compaction."""
import copy
import pytest
from ctxcomp import model_view
from ctxcomp.io import canonical,digest


@pytest.mark.parametrize('rules',[[{'id':'PRC001','text':'Only adopted project obligations.'}],[],None,'not a compression pack'])
def test_noncompression_rule_shapes_pass_through_byte_equivalent(rules):
    payload={'stage':'project_rules_extract','processing_rules':rules,
             'sources':[{'id':'P','role':'PROPOSAL','text':'Use reported units.'}],
             'source_permissions':[{'source_id':'P','may_read':True,'may_supply_project_authority':True}],
             'source_units':[{'id':'P_U1','source_id':'P','start_char':0,'end_char':19,'text':'Use reported units.'}],
             'schema':{'type':'object'},'governance':{'rules':[{'id':'G001'}]}}
    request={'request_sha256':digest(payload),'payload':payload}
    before=canonical(copy.deepcopy(request)).encode('utf-8')
    assert model_view.enabled(payload) is False
    assert model_view.view(request) is request
    assert canonical(model_view.view(request)).encode('utf-8')==before


def test_compression_compact_opt_in_still_removes_only_redundant_text():
    payload={'processing_rules':{'rules':[{'id':'CC002','host_requirement':{'model_payload':'COMPACT'}}]},
             'sources':[{'id':'S1','role':'PROPOSAL','text':'abc'}],
             'source_units':[{'id':'U1','source_id':'S1','text':'abc','start_char':0,'end_char':3,'text_sha256':'kept in host'}],
             'source_registry':[{'id':'S1'}],'requirements_evidence_audit':{'host':'only'}}
    request={'request_sha256':digest(payload),'payload':payload};before=copy.deepcopy(request)
    assert model_view.enabled(payload)
    sent=model_view.view(request)
    assert sent['request_sha256']==request['request_sha256'] and request==before
    assert sent['payload']['sources']==[{'id':'S1','role':'PROPOSAL'}]
    assert sent['payload']['source_units'][0]['text']=='abc'
    assert 'source_registry' not in sent['payload'] and 'requirements_evidence_audit' not in sent['payload']
