"""ContextBuilder explains the task without changing the original stage contract."""
import copy
import pytest
from research_pipeline import context_linear as linear, context_model_view as cmv
from research_pipeline import data_coverage_direct as cov, data_necessity_prompt as nec
from research_pipeline import data_human_summary_v3 as summary, data_direct_runtime as rt
from research_pipeline.minimal_context_reducer import expand_payload


@pytest.mark.parametrize('stage,instructions', [
    ('DIRECT_DR_COVERAGE',cov.INSTRUCTIONS),
    ('NECESSITY_SCOPED_ASSESSMENT',nec.INSTRUCTIONS),
    ('HUMAN_REVIEW_SUMMARY_ONLY',summary.INSTRUCTIONS)], ids=['coverage','necessity','summary'])
def test_original_instructions_schema_and_scope_survive_contextbuilder(stage,instructions):
    rule={'id':'R1','text':'Retain source uncertainty.','conditions':['For the requested endpoint'],
          'exceptions':['No invented longitudinal identity'],'scope':{'stages':['animal_pk']}}
    evidence={'item_id':'S1','scope_note':'Reported route and unknown basis.',
              'source_ids':['S1:A1'],'status':'PARTIAL'}
    requirement={'id':'RQ1','description':'Required study inputs','input_fields':['route'],
                 'conditions':['For the requested endpoint'],'method_uses':['MODEL_BASED']}
    payload={'stage':stage,'instructions':instructions}
    if stage=='DIRECT_DR_COVERAGE':
        payload.update(objective='Animal PK',requirements=[requirement],rules=[rule],
            profiles=[{'item_id':'S1','exposure_basis':'NOT_FOUND'}],
            source_units={'S1:A1':'PMB by IV; concentration basis NOT_FOUND.'})
        schema=cov.response_schema([requirement])
    elif stage=='NECESSITY_SCOPED_ASSESSMENT':
        payload.update(objective='Animal PK',requirements=[requirement],rules=[rule],
            coverage_summary={'RQ1':{'status':'PARTIAL','summary':'Route recorded; basis unknown.',
                'supported_fields':{'route':{'status':'SUPPORTED','source_scopes':[evidence]}}}},
            recorded_shortages={'RQ1:F2':{'status':'UNRESOLVED','unresolved_information':'Basis NOT_FOUND',
                'source_scopes':[evidence]}},local_method_knowledge={})
        schema=nec.contract.schema_for(payload['recorded_shortages'],[])
    else:
        payload.update(assessment={'decision':'CONDITIONAL_PASS','opinion':'Source limits remain.'},
            action_decisions={'MODEL_BASED_ANIMAL_PK':{'readiness':'CONDITIONAL','source_scope':'S1',
                'finding':'Route recorded; basis unknown.','next_step':'Use the stated conditional scope.'}})
        schema={'type':'object','properties':{'decision':{'type':'string','enum':['CONDITIONAL_PASS']}},
                'required':['decision'],'additionalProperties':False}
    request=rt.make_request(payload,schema);original=copy.deepcopy(request)
    assert linear.assemble(request)['request']==request
    result=expand_payload(cmv.view(request)['payload'])
    assert request==original
    assert result['instructions']==original['payload']['instructions']
    assert result['instructions'].endswith(instructions)
    assert result['schema']==schema
    for key in ('rules','requirements','source_units','profiles','coverage_summary','recorded_shortages',
                'assessment','action_decisions'):
        if key in payload:assert result[key]==payload[key],key
    assert 'This brief organizes that existing contract; it adds no requirements or decision criteria.' in result['premise']
    assert 'coverage_contract_version' not in result
    assert 'SOURCE_METADATA' not in str(result['schema'])
    assert 'MEASUREMENT_QUALIFICATION' not in str(result['schema'])
