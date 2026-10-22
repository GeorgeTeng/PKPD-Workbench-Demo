import copy
from research_pipeline import eda_plot_policy as policy

def test_terminal_heading_is_short_and_idempotent_without_data_edits():
    for drug,dose in [('Polymyxin B','45'),('Other compound','12.5')]:
        s={'kind':'categorical_raw','title':f'Terminal lung bacterial burden | Example strain | {drug} ({dose}mg/kg/d)',
           'subtitle':'Independent observations.','record_scope':{'D':['R1','R2']},'panels':[{'x':'same'}]}
        before=copy.deepcopy(s);policy.readable_heading(s)
        assert s['title']=='Example strain | Lung bacterial burden'
        assert s['subtitle']==f'{drug} {dose} mg/kg/day\nIndependent observations.'
        assert {k for k in s if s[k]!=before[k]}=={'title','subtitle'}
        once=copy.deepcopy(s);policy.readable_heading(s);assert s==once

def test_unknown_treatment_and_other_figures_remain_literal():
    for kind,title in [('categorical_raw','Terminal lung bacterial burden | Strain | Unknown treatment'),('summary_profile','Other study | SC 4 mg/kg')]:
        s={'kind':kind,'title':title,'subtitle':'Original context'};before=copy.deepcopy(s)
        policy.readable_heading(s);assert s==before
