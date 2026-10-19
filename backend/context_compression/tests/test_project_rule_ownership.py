"""The new compression contract retains meaning without extracting formal rules."""
import copy
import pytest
from ctxcomp.engine import make_request, accept, init_run, load_run
from ctxcomp.schemas import validate_schema, MAIN
from test_retention import reference_run, replay_until
from ctxcomp.io import read_json


def test_context_rejects_nonempty_formal_rules(tmp_path,reference_run):
    run=tmp_path/'run'; replay_until(run,reference_run,'requirements_review')
    req=make_request(run,'context')
    response=read_json(reference_run/'saved_responses/context.json')
    response['request_sha256']=req['request_sha256']
    response['context']['rules']=['Use the new drug model.']
    with pytest.raises(ValueError,match='rules'):
        accept(run,'context',response)
    assert not (run/'handoff/main.json').exists()


def test_retention_inventory_is_not_a_rule_classifier(reference_run):
    req=make_request(reference_run,'requirements')
    assert req['payload']['schema']['properties']['requirements']['properties']['items']['items']['properties']['kind']['enum']==['FACT','UNKNOWN']
    response=read_json(reference_run/'saved_responses/requirements.json')
    response['requirements']['items'][0]['kind']='RULE'
    with pytest.raises(ValueError,match='kind'):
        validate_schema(response,req['payload']['schema'])


def test_preserved_requirements_remain_evidenced_and_publication_pending(reference_run):
    main=read_json(reference_run/'handoff/main.json')
    assert main['rules']==[] and main['rule_publication']=='PROJECT_RULES_AGENT'
    assert 'project_rules_ref' not in main
    assert any('prediction freeze' in s for s in main['checks'])
    assert '/checks/1' in {e['path'] for e in read_json(reference_run/'saved_responses/context.json')['evidence']}
    validate_schema(main,MAIN)
    main['rules']=['R001: Do not publish here.']
    with pytest.raises(ValueError,match='rules'): validate_schema(main,MAIN)
