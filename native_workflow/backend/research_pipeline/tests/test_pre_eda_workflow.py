"""Adapter contract test: verifies orchestration wiring with explicit stage doubles, not E2E science."""
from pathlib import Path

from research_pipeline import data_assessment_workflow, data_requirement_plan_v6, data_test_workflow
from research_pipeline.common import read_json, write_json
from research_pipeline.data_direct_review import DirectDataReview
from research_pipeline.pre_eda_workflow import run


def test_driver_orders_existing_stages_and_serializes_path_results(tmp_path, monkeypatch):
    calls=[]
    monkeypatch.setattr(data_test_workflow,'run_stage',lambda main,out,stage,**kw: calls.append(('source',stage,kw)) or {'stage':stage})
    projection=tmp_path/'projection'; view=projection/'source_view.json';manifest=projection/'manifest.json';baseline=projection/'input_bindings.json';methods=projection/'local_method_profiles.json'
    monkeypatch.setattr('research_pipeline.pre_eda_workflow._project_source',lambda main,source,out:{
        'projection':projection,'source_view':view,'manifest':manifest,'baseline':baseline,'method_profiles':methods})
    monkeypatch.setattr(data_requirement_plan_v6,'verify_source_checkpoint',lambda source:calls.append(('checkpoint',str(source))) or {})
    monkeypatch.setattr(data_requirement_plan_v6,'run',lambda source,out,**kw:calls.append(('plan',kw)) or {'path':Path(out)})
    def assessment(plan,source,main,mp,out,**kw):
        calls.append(('assessment',kw));write_json(Path(out)/'human_gate.json',{'id':'data_contract_test','output_signature':'signature'})
        return {'status':'prepared'}
    monkeypatch.setattr(data_assessment_workflow,'run',assessment)
    def decide(self,identifier,decision):
        calls.append(('decision',decision.model_dump()))
        review={'id':identifier,'scope':'DATA_ASSESSMENT_REVIEW'}
        write_json(self.path(identifier),review)
        return {'id':identifier,'status':'APPROVED','approved':True}
    monkeypatch.setattr(DirectDataReview,'decide',decide)
    import research_pipeline.direct_preparation as preparation
    monkeypatch.setattr(preparation,'run',lambda approval,output,**kw:calls.append(('preparation',approval,output,kw)) or {
        'technical_processing_complete':True,'handoff_review_complete':True,'fit_ready':False,'scientific_release':False})

    out=tmp_path/'outputs'/'pre_eda'; result=run(tmp_path/'main.json',out,state=tmp_path/'state',outputs=tmp_path/'outputs',
        model='gpt-6-sol',auto_approve_human_gates=True)
    stages=[row[1] for row in calls if row[0]=='source']
    assert stages==['inventory','define','access','label']
    names=[row[0] for row in calls]
    assert names.index('checkpoint')<names.index('plan')<names.index('assessment')<names.index('decision')<names.index('preparation')
    approval=[row for row in calls if row[0]=='decision'][0][1]
    assert approval['reviewer']=='USER_AUTHORIZED_AUTOMATION' and approval['confirmed'] is True
    persisted=read_json(out/'pre_eda_status.json')
    assert persisted['status']=='COMPLETED_TO_CLEANING'
    assert persisted['user_authorized_automation'] is True and persisted['downstream_executed'] is False
    assert result['technical_processing_complete'] is True


def test_model_summary_names_distinct_runtime_models():
    from ctxcomp.providers import provider_model
    from research_pipeline.data_direct_runtime import MODEL as assessment_model
    assert provider_model() in {'gpt-6-sol','gpt-6-luna'}
    assert assessment_model=='gpt-6-sol'


def test_method_profile_projection_matches_necessity_consumer_contract(tmp_path):
    from research_pipeline import method_profiles_next as methods
    from research_pipeline.data_necessity_decisions import schema_for
    from research_pipeline.pre_eda_workflow import _flatten_method_profiles
    wrapped=methods.planning_context()
    flattened=_flatten_method_profiles(wrapped,methods.LIBRARY_PATH,methods.__file__)
    assert flattened['profiles']==wrapped['library']['profiles']
    assert flattened['sources']==wrapped['library']['sources']
    assert flattened['projection_provenance']['source']['sha256']
    assert flattened['projection_provenance']['adapter']['sha256']
    schema=schema_for({},[profile['id'] for profile in flattened['profiles']])
    assert schema['properties']['analyses']['items']['properties']['local_method_profile_ids']['items']['enum']==[
        profile['id'] for profile in flattened['profiles']]
