"""Shared numbering contracts, without live model calls or scientific fits."""
import copy
import pytest
from ctxcomp.governance import load_governance, attach_governance
from ctxcomp.io import digest
from research_pipeline.common import read_json
from research_pipeline.adequacy import model_request, file_ref
from research_pipeline import pk_reference_pilot as pilot
from research_pipeline import main_reference_revision as revision
from research_pipeline.animal_pk_agents import invoke_agent
from research_pipeline.task_rules import project_rules
from research_pipeline.workflow_runtime import make_plan
from test_adequacy import inputs
from test_pk_reference_pilot import prepared, pilot_response


def check(request):
    p=request['payload']
    assert p['governance']==load_governance()
    assert [r['id'] for r in p['governance']['rules']] == [f'G{i:03}' for i in range(1, 9)]
    assert p['instructions'].startswith('Apply governance rule G001 first')
    assert 'G008' in p['instructions']
    assert p['governance_sha256']==digest(p['governance'])
    assert request['request_sha256']==digest(p)
    assert set(p['governance']['evidence_handling']['checks']) == {'access','retrieval','support'}
    assert 'processing_rules' not in p  # The CC pack remains compression-only.


def test_shared_evidence_policy_does_not_enable_unimplemented_repair():
    policy=load_governance()['evidence_handling']
    assert 'implemented' in policy['correction']['activation']
    assert 'finite' in policy['correction']['budget']
    assert set(policy['failure_classes'])=={'ACCESS_DENIED','SOURCE_UNAVAILABLE','RETRIEVAL_INCOMPLETE',
        'QUESTION_SCOPE_MISMATCH','QUOTE_MISMATCH','UNSUPPORTED_CLAIM','SOURCE_CONFLICT'}


def test_scientific_and_reference_model_requests_get_g001(inputs):
    run,path,ip,main,inventory=inputs
    check(model_request('adequacy_assessment',main,inventory))
    check(model_request('adequacy_review',main,inventory,{'tasks':[],'requirements':[]}))
    prepared(inputs)
    package=read_json(run/'reference_input.json')
    check(pilot.model_request(package))
    pilot.execute(run/'reference_input.json',run/'review',generator=pilot_response)
    advice=read_json(run/'review/reference_context.json')
    check(revision.request_for(main,advice))


def test_animal_agent_uses_shared_rule_without_compression_rules(tmp_path):
    def generator(request,**kwargs):
        check(request)
        return {'decision':'CONTINUE','summary':'Synthetic contract test.','issues':[],'requested_changes':[]}
    result=invoke_agent({'id':'test','role':'model_review','instructions':'Review only the supplied plan.'},
                        {},tmp_path/'agent',generator)
    check(read_json(result['request_ref']['path']))


def test_every_new_snakemake_contract_snapshots_shared_rule(inputs,tmp_path):
    spec={'mode':'pk_reference_pilot','job_dir':str(tmp_path/'job'),'out':str(tmp_path/'out'),
          'main_ref':file_ref(inputs[1]),'revise_main':True}
    plan=make_plan(spec)
    assert len(plan['steps'])>=4
    for step in plan['steps'].values():
        assert read_json(step['contract'])['governance']==load_governance()


def test_subset_retains_rule_ids_and_source_version():
    main={'study':{'drug':'Example'},'rules':[
        {'id':'R002','text':'Require converged animal PK fits.','stages':['animal_pk']},
        {'id':'R009','text':'Review the PD endpoint.','stages':['index']} ]}
    before=copy.deepcopy(main)
    selected=project_rules(main,'animal_pk')
    assert [r['id'] for r in selected['rules']]==['R002']
    assert selected['rules'][0]['text'].startswith('R002:')
    assert selected['source_context_sha256']==digest(main) and main==before
    main['rules'][0]['text']='Require human review of animal PK fits.'
    assert project_rules(main,'animal_pk')['source_context_sha256']!=selected['source_context_sha256']


@pytest.mark.parametrize('rules',[
    ['R002: Require converged animal PK fits.','R002: Review the PD endpoint.'],
    [{'id':'R009','text':'R002: Require converged animal PK fits.'}]
])
def test_ambiguous_rule_identity_is_rejected(rules):
    with pytest.raises(ValueError,match='G001'):
        project_rules({'rules':rules},'animal_pk')


def test_shared_rule_is_idempotent_and_versions_cannot_be_mixed():
    payload={'instructions':'Step-specific instructions.'}
    attach_governance(payload); first=copy.deepcopy(payload)
    attach_governance(payload); assert payload==first
    other=load_governance(); other['version']='other'
    with pytest.raises(ValueError,match='Conflicting'): attach_governance(payload,other)
