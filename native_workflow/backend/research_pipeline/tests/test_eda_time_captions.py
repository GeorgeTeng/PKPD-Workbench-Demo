import copy
from research_pipeline import eda_plot_policy as policy

def fixture(notes):
    table={'dataset_id':'D','title':'Mouse IV plasma mean','notes':notes,'columns':[
        {'id':'t','header':'Time','meaning':'TIME','unit':'h'},
        {'id':'pixel','header':'Digitized time','meaning':'TIME','unit':'h'},
        {'id':'y','header':'Mean concentration','meaning':'CONCENTRATION','unit':'mg/L'}],
        'records':[{'record_id':'R','source_raw_values':{'t':1,'pixel':1.01,'y':2},
                    'value_status':{'t':'QUANTIFIED','pixel':'QUANTIFIED','y':'QUANTIFIED'}}]}
    spec={'id':'V','kind':'summary_profile','title':'Mouse IV','caption':'Source means.',
          'y_scale':'log10','x_label':'Time (h)','y_label':'Concentration (mg/L)',
          'panels':[{'label':'Plasma','series':[{'dataset_id':'D','x':'pixel','y':'y','label':'IV'}]}]}
    return table,spec

def test_nominal_caption_is_not_actual_time_and_keeps_selection():
    table,spec=fixture('Nominal times from PK methods.');before=copy.deepcopy(table)
    result=policy.normalize({'V':spec},{'D':table});assert len(result)==1
    out=next(iter(result.values()))
    assert out['panels'][0]['series'][0]['x']=='t'
    assert out['x_label']=='Nominal sampling time (h)'
    assert 'Nominal sampling times from the study methods are shown.' in out['caption']
    assert 'does not finalize the modeling time basis' in out['caption']
    assert 'PAPER_SAMPLING_TIMES' not in out['caption'] and table==before

def test_unconfirmed_schedule_keeps_digitized_axis():
    table,spec=fixture('Time columns are unresolved.');before=copy.deepcopy(table)
    out=next(iter(policy.normalize({'V':spec},{'D':table}).values()))
    assert out['panels'][0]['series'][0]['x']=='pixel'
    assert 'Digitized figure times are shown' in out['caption']
    assert 'Nominal sampling times from the study methods' not in out['caption']
    assert table==before

def test_diagnostic_caption_describes_alternate_column_not_main():
    table,spec=fixture('Nominal times from PK methods.')
    table['time_axis']={'source_conflict':True}
    views=policy.normalize({'V':spec},{'D':table})
    diagnostic=next(s for s in views.values() if s['display_policy']['role']=='TIME_CHECK')
    assert diagnostic['panels'][0]['series'][0]['x']=='pixel'
    assert 'Digitized figure times are shown' in diagnostic['caption']
    assert 'Nominal sampling times from the study methods are shown' not in diagnostic['caption']

def test_reported_schedule_does_not_claim_actual_collection():
    table,spec=fixture('Sampling times specified in the publication.')
    out=next(iter(policy.normalize({'V':spec},{'D':table}).values()))
    assert 'reported sampling schedule is shown' in out['caption']
    assert 'actual per-animal collection times are not established' in out['caption']
