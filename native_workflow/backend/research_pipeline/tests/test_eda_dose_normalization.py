import copy
import json
import pytest
from research_pipeline import eda_dose_normalization as dn


@pytest.fixture
def sample(tmp_path, monkeypatch):
    tables={}
    for i,dose in enumerate((2,4)):
        did='D'+str(i)
        tables[did]={'dataset_id':did,'title':did,'notes':'single SC dose; plasma; study A',
            'columns':[{'id':'t','header':'Time','unit':'h','meaning':'TIME'},
                       {'id':'c','header':'Concentration','unit':'mg/L','meaning':'CONCENTRATION'}],
            'records':[{'record_id':did+'r','source_sha256':'abc','source_cells':{'t':'A1','c':'B1'},
                'source_raw_values':{'t':1.,'c':dose*3.},'value_status':{'t':'QUANTIFIED','c':'QUANTIFIED'}}]}
    group={'id':'TEST','scope':'study A, mouse SC plasma','dose_unit':'mg/kg','dose_basis':'single source dose',
        'evidence':['source methods'],'sources':[{'key':d,'title':t['title'],'signature':dn.signature(t)} for d,t in tables.items()],
        'series':[{'key':d,'x':'t','y':'c','dose':dose,'label':str(dose),'evidence':'source methods'} for d,dose in zip(tables,(2,4))]}
    reg=tmp_path/'registry.json';reg.write_text(json.dumps({'groups':[group]}));monkeypatch.setattr(dn,'REGISTRY',reg)
    candidates={'P':{'id':'P','kind':'summary_profile','title':'Mouse SC','subtitle':'means','caption':'source means',
        'y_scale':'log10','panels':[{'label':'plasma','series':[{'dataset_id':d,'x':'t','y':'c'} for d in tables]}],
        'display_policy':{'role':'MAIN'},'x_label':'Time (h)'}}
    return tables,candidates,reg


def test_multidose_requires_selected_curve(sample):
    tables,views,_=sample
    augmented=dn.augment(views,tables)
    with pytest.raises(ValueError,match='Mandatory'):dn.coverage(['P'],augmented,tables)
    result=dn.coverage(list(augmented),augmented,tables)
    assert result['groups'][0]['status']=='READY'


def test_calculation_keeps_original_values_and_provenance(sample):
    tables,views,_=sample;before=copy.deepcopy(tables)
    spec=dn.augment(views,tables)['TEST__DOSE_NORMALIZED']
    rows=dn.input_rows(spec,tables)
    assert [r['y'] for r in rows]==[3,3]
    assert [r['raw_y'] for r in rows]==[6,12]
    assert rows[0]['dose_evidence']=='source methods' and rows[0]['y_cell']=='B1'
    assert tables==before


@pytest.mark.parametrize('mutation',['records','notes','role','permission'])
def test_changed_or_blocked_source_cannot_reuse_contract(sample,mutation):
    tables,views,_=sample;spec=dn.augment(views,tables)['TEST__DOSE_NORMALIZED']
    if mutation=='records':tables['D0']['records'][0]['source_raw_values']['c']=9
    elif mutation=='notes':tables['D0']['notes']+='changed'
    elif mutation=='role':tables['D0']['metadata']={'observation_role':False}
    else:tables['D0']['dose_normalization_allowed']=False
    with pytest.raises(ValueError,match='contract'):dn.input_rows(spec,tables)
    report=dn.assess(views,tables)
    assert report['groups'][0]['status']=='BLOCKED' and report['groups'][0]['reason']


def test_unregistered_doses_remain_explicit_gap(sample):
    tables,views,reg=sample;reg.write_text(json.dumps({'groups':[]}))
    assessment=dn.assess(views,tables)
    assert len(assessment['groups'])==2
    assert all(g['status']=='NEEDS_METADATA' and g['reason'] for g in assessment['groups'])


def test_zero_denominator_rejected(sample):
    tables,views,reg=sample;r=json.loads(reg.read_text());r['groups'][0]['series'][0]['dose']=0
    # With only one remaining positive dose this is not an eligible comparison.
    reg.write_text(json.dumps(r));assert dn.assess(views,tables)['groups'][0]['status']=='NOT_APPLICABLE'


def test_missing_and_zero_values_retained_without_substitution(sample):
    tables,views,reg=sample
    tables['D0']['records'][0]['source_raw_values']['c']='<LLOQ'
    tables['D0']['records'][0]['value_status']['c']='BLQ'
    tables['D1']['records'][0]['source_raw_values']['c']=0
    r=json.loads(reg.read_text())
    for s in r['groups'][0]['sources']:s['signature']=dn.signature(tables[s['key']])
    reg.write_text(json.dumps(r))
    spec=dn.augment(views,tables)['TEST__DOSE_NORMALIZED'];rows=dn.input_rows(spec,tables)
    assert rows[0]['y'] is None and rows[0]['raw_y']=='<LLOQ'
    assert rows[1]['y']==0 and not rows[1]['plot_eligible']


def test_signature_binds_units(sample):
    tables,views,_=sample;spec=dn.augment(views,tables)['TEST__DOSE_NORMALIZED']
    tables['D0']['columns'][1]['unit']='ug/g'
    with pytest.raises(ValueError):dn.input_rows(spec,tables)
