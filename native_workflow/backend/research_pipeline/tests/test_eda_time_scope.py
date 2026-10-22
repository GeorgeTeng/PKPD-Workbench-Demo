import copy
from research_pipeline import eda_plot_policy as p

def table(matrix='whole lung',route='IT'):
 return {'dataset_id':'D','title':f'Rabbit {route}: {matrix}',
  'notes':f'Matrix: {matrix}; group mean.\nFigure plasma times/count differ from blood protocol, especially SC.\nTissue/ELF nominal times 0.5,2,6 h.\nSC whole-lung Fig.2 peak differs from Table S5 Cmax.',
  'columns':[{'id':'t','meaning':'TIME','header':'Time','unit':'h'},{'id':'pixel','meaning':'TIME','header':'Pixel time','unit':'h'}],
  'records':[{'record_id':str(i),'source_raw_values':{'t':x,'pixel':z},'value_status':{'t':'QUANTIFIED','pixel':'QUANTIFIED'}} for i,(x,z) in enumerate([(0.5,.495),(2,2.004),(6,5.998)])]}

def test_matrix_schedule_and_conflict_scope():
 for matrix in ['whole lung','ELF']:
  t=table(matrix);before=copy.deepcopy(t);d=p.time_decision(t)
  assert d['primary']=='t' and not d['trigger'] and d['out_of_scope_conflicts']
  assert t==before
 for route in ['IT','SC']:
  d=p.time_decision(table('plasma',route))
  assert d['primary']=='pixel' and d['trigger']

def test_mismatch_does_not_snap_time():
 t=table();t['records'][0]['source_raw_values']['t']=.75
 assert p.time_decision(t)['primary']=='pixel'

def test_route_specific_peak_warning_is_preserved_only_where_applicable():
 text='Plasma timing/protocol discrepancy and SC whole-lung peak conflict remain open. No SD recovered.'
 assert p.scoped_caption(text,[table()])=='No SD recovered.'
 assert 'SC whole-lung peak conflict' in p.scoped_caption(text,[table(route='SC')])

def test_explicit_diagnostic_request_is_retained():
 t=table();t['time_axis']={'diagnostic_requested':True}
 assert p.time_decision(t)['trigger']
