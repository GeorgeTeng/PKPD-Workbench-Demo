import copy,json
import pytest
from research_pipeline import eda_study_annotations as a,eda_plot_policy as p

def fixture(index=0):
 c=json.loads(a.CONFIG.read_text(encoding='utf8'));b=c['timekill_bindings'][index];did=b['dataset_id']
 t={'dataset_id':did,'title':b['table_title'],'notes':b['mic_evidence']+' '+b['exposure_evidence'],'records':[{k:b[k] for k in ['source_file_id','source_sha256','source_sheet']}]}
 s={'id':'V','kind':'source_id_profile','title':t['title']+' | '+t['title'],'subtitle':'Old subtitle','caption':'Censoring remains unresolved.','panels':[{'series':[{'dataset_id':did,'x':'t','y':'y'}]}]}
 return c,t,s

@pytest.mark.parametrize('index,mic',[(0,0.5),(1,64)])
def test_annotation_and_heading_are_idempotent_and_preserve_data(index,mic):
 c,t,s=fixture(index);before=copy.deepcopy(t);out=a.annotate(s,{t['dataset_id']:t},c);p.readable_heading(out)
 assert out['title']==t['title'] and f'MIC {mic:g} mg/L' in out['subtitle']
 assert out['caption']==s['caption'] and out['panels']==s['panels'] and t==before
 again=a.annotate(out,{t['dataset_id']:t},c);p.readable_heading(again);assert again==out

@pytest.mark.parametrize('bad',['missing','conflict','source','exposure'])
def test_no_guessed_MIC_or_cross_source_annotation(bad):
 c,t,s=fixture()
 if bad=='missing':t['notes']=t['notes'].replace(c['timekill_bindings'][0]['mic_evidence'],'')
 elif bad=='conflict':t['notes']+=' PMB MIC 99 mg/L.'
 elif bad=='source':t['records'][0]['source_sha256']='wrong'
 else:t['notes']=t['notes'].replace('Static in-vitro exposure','Dynamic exposure')
 with pytest.raises(ValueError):a.annotate(s,{t['dataset_id']:t},c)
