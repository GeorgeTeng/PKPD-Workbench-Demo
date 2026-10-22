"""Source assertions independent of the execution/QC implementations."""
import copy
from pathlib import Path
import pytest
from research_pipeline.common import PROJECT, read_json
from research_pipeline.preparation_semantics import row_value_statuses, dose_metadata


NOTE = ('A dot is missing/not applicable. CENS=1 flags censored Y. '
        'The 1e-8 control exposure is retained exactly; independent replicate IDs NOT_FOUND.')
FIELDS = {'y': 'Y', 'flag': 'CENS', 'time': 'TIME'}


@pytest.mark.parametrize('raw,status,expected',[(0,'QUANTIFIED','CENSORED'),
    (2.3,'QUANTIFIED','CENSORED'),('.','MISSING_OR_NOT_APPLICABLE','MISSING_CENSORED_OBSERVATION'),
    (None,'EMPTY_SLOT','MISSING_CENSORED_OBSERVATION'),('=A1','FORMULA_REQUIRES_REVIEW','FORMULA_REQUIRES_REVIEW')])
def test_explicit_censor_flag_preserves_values_and_has_no_limit_inference(raw,status,expected):
    values={'y':raw,'flag':1,'time':24};base={'y':status,'flag':'QUANTIFIED','time':'QUANTIFIED'}
    original=copy.deepcopy((values,base))
    result=row_value_statuses(values,FIELDS,NOTE,base)
    assert result['y']==expected and (values,base)==original
    assert row_value_statuses(values,FIELDS,NOTE,result)==result
    assert set(result)==set(base)


@pytest.mark.parametrize('flag,note',[(0,NOTE),(True,NOTE),(1,''),
    (1,'CENS=1 does not flag censored Y.'),(1,'Do not assume CENS=1 flags censored Y.')])
def test_no_censor_inference_without_source_definition_or_exact_positive_flag(flag,note):
    base={'y':'QUANTIFIED','flag':'QUANTIFIED'}
    assert row_value_statuses({'y':0,'flag':flag},FIELDS,note,base)==base


def dose_fixture(value='2',subject='PMB sulphate'):
    label={'item_id':'F0004:S1:T28','route':'SC','drug':'PMB sulphate',
           'dose_basis':'as-reported PMB sulphate','dosing_regimen':'Single SC dose'}
    statement={'item_id':label['item_id'],'quantity':'NOT_FOUND','value':value,'unit':'mg/kg',
               'subject':subject,'qualifiers':['Single SC dose','as-reported PMB sulphate'],
               'evidence':[{'source':label['item_id']+':A566',
                            'quote':f'S02 Figure 1: SC {value} mg/kg plasma mean concentrations (digitized)'}]}
    return label,statement


def test_source_dose_is_copied_with_qualifiers_and_without_row_assignment():
    label,statement=dose_fixture();before=copy.deepcopy((label,statement))
    result=dose_metadata(label,[statement])
    assert result['status']=='SOURCE_STATED' and result['value']=='2' and result['unit']=='mg/kg'
    assert result['dose_basis']=='as-reported PMB sulphate'
    assert result['evidence']==statement['evidence'] and result['per_record_assignment'] is False
    assert dose_metadata(label,[statement])==result and (label,statement)==before


def test_conflicting_or_other_agent_doses_remain_candidates():
    label,first=dose_fixture();_,second=dose_fixture('4')
    result=dose_metadata(label,[first,second])
    assert result['status']=='SOURCE_REPORTED_APPLICABILITY_UNRESOLVED'
    assert [c['value'] for c in result['candidates']]==['2','4']
    assert result['per_record_assignment'] is False and 'value' not in result
    _,other=dose_fixture('200','surfactant')
    assert dose_metadata(label,[other])['status']=='SOURCE_REPORTED_APPLICABILITY_UNRESOLVED'


@pytest.mark.parametrize('fault',['wrong_quote','foreign_item','foreign_evidence','missing_evidence'])
def test_dose_requires_same_source_literal_evidence(fault):
    label,statement=dose_fixture()
    if fault=='wrong_quote':statement['evidence'][0]['quote']='SC 8 mg/kg'
    elif fault=='foreign_item':statement['item_id']='another'
    elif fault=='foreign_evidence':statement['evidence'][0]['source']='another:A1'
    else:statement['evidence']=[]
    assert dose_metadata(label,[statement])=='NOT_FOUND'


def test_real_reviewed_source_fixture_semantics():
    run=PROJECT/'outputs/Codex_Agent_Run_20261009/data_test_20_cleaning_sol61/live02'
    if not (run/'inputs/context.json').exists():pytest.skip('Reviewed local source fixture is unavailable.')
    context=read_json(run/'inputs/context.json');labeled=read_json(context['labels']['path'])
    labels={l['item_id']:l for l in labeled['labels']}
    for number,value in [(28,'2'),(29,'4'),(30,'8'),(31,'16')]:
        result=dose_metadata(labels[f'F0004:S1:T{number}'],labeled['stated_values'])
        assert result['status']=='SOURCE_STATED' and result['value']==value
        assert result['unit']=='mg/kg' and result['dose_basis']=='as-reported PMB sulphate'
    inventory=read_json(context['inventory']['path'])
    item=next(i for i in inventory['items'] if i['id']=='F0004:S4:T1')
    snapshot=read_json(item['snapshot']['path']);sheet=snapshot['sheets'][item['sheet_index']]
    cells={(c['row'],c['column']):c['value'] for c in sheet['cells']}
    # Actual source facts, asserted without reading derived output statuses.
    for row in (26,33,34):
        assert cells[row,5]==0 and cells[row,6]==1
        statuses=row_value_statuses({'y':cells[row,5],'flag':cells[row,6]},FIELDS,
                                   item['descriptor']['source_notes'],{'y':'QUANTIFIED','flag':'QUANTIFIED'})
        assert statuses['y']=='CENSORED'
