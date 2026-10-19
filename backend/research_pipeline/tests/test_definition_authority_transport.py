import copy
import pytest
from research_pipeline import data_agents as d


def test_mixed_authority_rejected_before_generation_and_source_claim_preserved():
    # Reproduces the live rejected shape: a project claim citing a method profile.
    need={'id':'REQ13','task_id':'T03','description':'Define prediction scenario',
          'kind':'DEFINITION','required_by':'BEFORE_TRANSLATION','fields':['route'],
          'rule_ids':[],'evidence':[{'source':'main:/objective','quote':'objective'},
                                    {'source':'method:MP006','quote':'method'}],
          'origin':'PROJECT_EXPLICIT','method_profile_ids':['MP006'],'conditions':['if applicable']}
    raw={'request_sha256':'hash','tasks':[{'id':'T03','objective':'objective',
         'destination':'clinical','evidence':[{'source':'main:/objective','quote':'objective'}]}],
         'requirements':[need],'findings':[]}
    before=copy.deepcopy(d.DEFINITION)
    schema=d.definition_transport_schema(d.DEFINITION)
    with pytest.raises(Exception):d.validate_schema(raw,schema)
    method=copy.deepcopy(raw);method['requirements'][0]['origin']='METHOD_CANDIDATE'
    d.validate_schema(method,schema)
    explicit=copy.deepcopy(raw);explicit['requirements'][0]['evidence'].pop()
    d.validate_schema(explicit,schema)
    assert d.DEFINITION == before
