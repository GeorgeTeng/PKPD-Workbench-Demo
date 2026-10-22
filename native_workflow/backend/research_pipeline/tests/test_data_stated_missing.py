"""DC003 explicitly permits NOT_FOUND in copied stated-value fields."""
import copy
import pytest
from research_pipeline import data_agents as d
from research_pipeline.common import read_json,write_json,PipelineError
from test_data_agents import case,stated_case,requirements


@pytest.mark.parametrize('field',['quantity','value'])
def test_explicit_missing_copied_field_is_retained_without_false_matching(case,field):
    _,run,main,inv,_,_=case;generate=stated_case(case)
    source=read_json(main);file=next(f for f in source['data']['files'] if f['id']=='F0004')
    from pathlib import Path
    text=Path(file['path']);body=text.read_text(encoding='utf-8')
    if field=='quantity':
        body=body.replace('Cmax was ','').replace('had a Cmax of ','had ').replace('Half-life was ','')
    else:body=body.replace('12.3','not stated').replace('40','not stated').replace('2 h','not stated h')
    text.write_text(body,encoding='utf-8');file.update(d.file_ref(text));write_json(main,source);d.inventory(main,inv)
    def missing(request,**kwargs):
        response=generate(request,**kwargs)
        if request['payload'].get('item_id')=='F0004:document':
            for value in response['labels'][0]['stated_values']:value[field]='NOT_FOUND'
        return response
    req=run/'adequacy/requirements.json';labels=run/'adequacy/data_labels.json'
    requirements(run,main,inv,req,missing);d.label(run,main,inv,req,labels,generator=missing)
    rows=read_json(labels)['stated_values']
    assert len(rows)==4 and all(v[field]=='NOT_FOUND' for v in rows)
    assert all(v['status']=='TEXT_ONLY' and v['matches']==[] for v in rows)
    assert rows[0]['evidence'][0]['quote']==body.splitlines(keepends=True)[0]
    if field=='quantity':assert rows[0]['value']=='12.3' and rows[0]['unit']=='mg/L'
    else:assert rows[0]['quantity']=='Cmax'


@pytest.mark.parametrize('field,value',[('quantity','Semantic age'),('value','12.30'),('unit','mg/Ls'),('subject','Another group')])
def test_nonmissing_copied_fields_remain_verbatim(case,field,value):
    _,run,main,inv,_,_=case;generate=stated_case(case)
    def bad(request,**kwargs):
        response=generate(request,**kwargs)
        if request['payload'].get('item_id')=='F0004:document':response['labels'][0]['stated_values'][0][field]=value
        return response
    req=run/'adequacy/requirements.json';requirements(run,main,inv,req,bad)
    with pytest.raises(PipelineError) as error:d.label(run,main,inv,req,run/'adequacy/data_labels.json',generator=bad)
    assert error.value.code=='DATA_EVIDENCE_INVALID'


def test_unknown_value_is_not_an_earlier_conflicting_observation():
    def value(v):return dict(quantity='Cmax',value=v,unit='mg/L',subject='group',qualifiers=[],evidence=[])
    labels=[dict(item_id='doc',requirement_ids=[],stated_values=[value('NOT_FOUND'),value('4')])]
    rows,findings=d.stated_values(labels,{'doc':{'kind':'DOCUMENT'}})
    assert len(rows)==2 and not findings and all(r['matches']==[] for r in rows)
