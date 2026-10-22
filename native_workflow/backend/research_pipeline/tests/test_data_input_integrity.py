"""Offline regression for complete Context and pre-response bindings."""
import copy
import pytest
from research_pipeline import data_agents as d, project_rule_agent as rules
from research_pipeline.common import read_json, write_json, PipelineError
from test_data_agents import case


@pytest.mark.parametrize('field', ['missing_information', 'scientific_context', 'data', 'uncertainties', 'rules'])
def test_context_projection_rejects_changed_semantic_input(tmp_path, monkeypatch, field):
    main={'objective':'Study Z','study':{},'rules':[], 'checks':[], 'uncertainties':['Pending'],
          'scientific_context':{'items':[{'statement':'Observed'}]},
          'missing_information':{'items':[{'id':'MI001'}]},'data':{'files':[]}}
    published=write_json(tmp_path/'published.json',main)
    pack=write_json(tmp_path/'pack.json',{})
    main['project_rules_ref']=d.file_ref(pack)
    write_json(published,main)
    monkeypatch.setattr(rules,'verify_published',lambda ref:{'main_ref':d.file_ref(published),'rules':[]})
    altered=copy.deepcopy(main);altered.pop(field)
    with pytest.raises(PipelineError,match='context'):
        rules.context_with_rules(altered)
    assert rules.context_with_rules(main)['missing_information']==main['missing_information']


def test_define_rejects_input_changed_while_waiting(case):
    _,run,main,_,generate,_=case
    output=run/'definition.json'
    def change(request,**options):
        result=generate(request,**options)
        value=read_json(main);value['objective']='Changed while waiting'
        write_json(main,value)
        return result
    with pytest.raises(PipelineError):d.define(run,main,output,generator=change)
    assert not output.exists()
