"""Proposition boundaries are semantic judgments; these tests check delivery and gates."""
import copy
import pytest

from ctxcomp.engine import init_run, prepare
from ctxcomp.rules import load_rules
from ctxcomp.schemas import SCHEMAS
from ctxcomp import scientific
from ctxcomp.retention import requirements_review_check
from attachment_fixture import accept_empty_search
from test_scientific_extraction import scientific_fixture
from test_retention import demo


def test_new_inventory_requests_receive_field_specific_boundary_instructions(tmp_path):
    proposal=tmp_path/'proposal.txt'; proposal.write_text('Predict human PK.')
    run=tmp_path/'run'; init_run(run,proposal); accept_empty_search(run)
    p=prepare(run,'requirements')['payload']
    contract=p['processing_rules']['scientific_extraction']['proposition_contract']
    item=p['schema']['properties']['requirements']['properties']['items']['items']
    assert item['properties']['statement']['description']==contract['schema_guidance']['statement']
    assert item['properties']['science']['properties']['role']['description']==contract['schema_guidance']['role']
    assert item['properties']['science']['properties']['evidence_status']['description']==contract['schema_guidance']['evidence_status']
    assert 'proposition_contract' not in prepare(run,'attachment_plan')['payload']['processing_rules']


def test_schema_guidance_keeps_historical_requests_and_output_fields_unchanged():
    profile=load_rules()['scientific_extraction']['proposition_contract']
    original=copy.deepcopy(SCHEMAS)
    old=scientific.response_schema('requirements',SCHEMAS['requirements'],True)
    new=scientific.response_schema('requirements',SCHEMAS['requirements'],True,profile)
    old_item=old['properties']['requirements']['properties']['items']['items']
    new_item=new['properties']['requirements']['properties']['items']['items']
    assert old_item['required']==new_item['required']
    assert old_item['properties'].keys()==new_item['properties'].keys()
    assert 'description' not in old_item['properties']['statement']
    review=scientific.response_schema('requirements_review',SCHEMAS['requirements_review'],True,profile)
    reason=review['properties']['review']['properties']['items']['items']['properties']['reason']
    assert reason['description']==profile['schema_guidance']['review_reason']
    assert SCHEMAS==original
    # Guidance describes only its own field, although the schemas share one string definition.
    for schema, text in [(new, profile['schema_guidance']['statement']), (review, profile['schema_guidance']['review_reason'])]:
        described = [v for v in walk(schema) if v.get('description') == text]
        assert len(described) == 1


def walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values(): yield from walk(child)
    elif isinstance(value, list):
        for child in value: yield from walk(child)


def test_mixed_proposition_finding_cannot_be_overridden_by_pass():
    _,units,inventory=scientific_fixture()
    inventory['potential_questions']=[]
    review=demo.fixture_requirements_review(inventory,units)
    review['items'][2].update(verdict='ALTERED',reason='Split the predicted result from an independent prohibition.')
    review['decision']='REVISE'
    assert requirements_review_check(review,inventory,units)['decision']=='REVISE'
    review['decision']='PASS'
    with pytest.raises(ValueError,match='PASS contradicts'):
        requirements_review_check(review,inventory,units)
