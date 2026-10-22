import copy
import pytest
from research_pipeline.eda_study_annotations import annotate

@pytest.mark.parametrize('species',['Mouse','Rat'])
@pytest.mark.parametrize('assay,method',[('ED','Equilibrium dialysis'),('UF','Ultrafiltration')])
def test_binding_heading_preserves_selectors_and_source(species,assay,method):
    t={'title':f'{species} serum protein binding of polymyxin B1','notes':'Commercial pooled serum; triplicate; equilibrium dialysis (ED) and ultrafiltration (UF).','columns':[{'id':'y','header':f'{species} {assay} % bound','unit':'%'}]}
    r={'series':[{'dataset_id':'T','y':'y','projection':'reported_mean_sd'}],'question':'Scientific purpose retained','caption':'Source mean ± SD from triplicate pooled-serum experiments. SD intervals are not clipped at 100%.'}
    s={'kind':'source_projection','source_recipe':r,'caption':r['caption'],'title':'Long title'}
    before=copy.deepcopy((s,t));out=annotate(s,{'T':t})
    assert (s,t)==before
    assert out['title']==f'{species} serum protein binding — {assay}'
    assert out['subtitle']==f'Polymyxin B1 · {method}'
    assert out['source_recipe']['series']==r['series']
    assert out['source_recipe']['question']==r['question']
    assert 'Points = mean; error bars = SD.' in out['caption']
    assert 'SD intervals are not clipped at 100%.' in out['caption']
    assert annotate(out,{'T':t})==out
    t['notes']='unknown method'
    assert annotate(s,{'T':t})==s

def test_multi_assay_view_is_not_silently_collapsed():
    s={'kind':'source_projection','source_recipe':{'series':[{},{}]}}
    assert annotate(s,{})==s
