"""Injected contract failures test the host, not real-LLM detection sensitivity."""
import copy

import pytest

from research_pipeline import data_agents as d
from research_pipeline import data_requirement_check as c
from research_pipeline.common import PipelineError, read_json, write_json
from test_data_agents import case, assess


def change_review(case, edit, *, phase='BEFORE_MODELING'):
    model = case[4]

    def generate(request, **options):
        result = model(request, **options)
        if request['payload'].get('operation') == 'DEFINE_REQUIREMENTS':
            result['requirements'][0]['required_by'] = phase
        if request['payload']['stage'] == 'DC-review':
            edit(result, request['payload'])
        return result
    return generate


def test_missing_field_retains_partial_coverage_and_later_gap(case):
    def edit(result, payload):
        match = result['matches'][0]
        criterion = next(x for x in match['criteria'] if x['id'] == 'FIELD_002')
        criterion.update(status='MISSING', evidence=[], reason='Injected missing concentration field',
                         needed_material='Provide concentration observations with their units')
        match.update(status='UNRESOLVED', reason='Only time is supported in this injected review',
                     needed_material=criterion['needed_material'])
    assess(case, change_review(case, edit))
    report = read_json(case[1] / 'adequacy/adequacy.json')
    matrix = read_json(report['requirement_matrix']['path'])
    assert matrix['requirements'][0]['coverage_status'] == 'PARTIAL'
    assert report['can_enter_qc']
    assert report['task_assessments'][0]['input_coverage']['PARTIAL'] == ['N001']
    assert report['findings'][0]['required_by'] == 'BEFORE_MODELING'
    assert report['findings'][0]['severity'] == 'FOLLOW_UP'
    assert 'PARTIAL' in (case[1] / 'adequacy/report.md').read_text(encoding='utf-8')
    assert report['fit_ready'] is False


def test_scope_conflict_cannot_be_hidden_by_supported_fields(case):
    def edit(result, payload):
        match = result['matches'][0]
        criterion = next(x for x in match['criteria'] if x['id'] == 'SCOPE_ALIGNMENT')
        criterion.update(status='CONFLICT', reason='Injected free/total conflict',
                         needed_material='Clarify the concentration basis before using this dataset')
        match.update(status='UNRESOLVED', reason=criterion['reason'], needed_material=criterion['needed_material'])
    assess(case, change_review(case, edit, phase='BEFORE_QC'))
    report = read_json(case[1] / 'adequacy/adequacy.json')
    assert not report['can_enter_qc']
    assert report['requirements'][0]['coverage_status'] == 'CONFLICT'
    assert report['task_assessments'][0]['current_prerequisite_gaps'] == ['N001']


@pytest.mark.parametrize('fault', ['missing_check', 'duplicate_check', 'invented_quote', 'descriptor_only', 'false_pass'])
def test_false_evidence_or_inconsistent_result_is_rejected(case, fault):
    def edit(result, payload):
        match = result['matches'][0]
        if fault == 'missing_check':
            match['criteria'].pop()
        elif fault == 'duplicate_check':
            match['criteria'].append(copy.deepcopy(match['criteria'][0]))
        elif fault == 'invented_quote':
            match['criteria'][0]['evidence'][0]['quote'] = 'INVENTED_NONEXISTENT_VALUE'
        elif fault == 'descriptor_only':
            key = next(k for k,v in payload['evidence_catalog'].items() if v['kind'] == 'DESCRIPTOR')
            for criterion in match['criteria']:
                criterion['evidence'] = [{'source':key, 'quote':payload['evidence_catalog'][key]['content']}]
            match['source_ids'] = [key]
        else:
            match['criteria'][0].update(status='PARTIAL', needed_material='Resolve the injected missing field')
    with pytest.raises(PipelineError):
        assess(case, change_review(case, edit))
    assert not (case[1] / 'adequacy/qc_context.json').exists()


def deferred_target(case):
    _, run, main, inv, model, _ = case
    value = read_json(main)
    value['objective'] = 'Estimate the PD target later in the index analysis from matched exposure-response data.'
    write_json(main, value)
    d.inventory(main, inv)

    def edit(result, payload):
        match = result['matches'][0]
        key = 'main:/objective'
        evidence = [{'source':key,'quote':payload['evidence_catalog'][key]['content']}]
        for criterion in match['criteria']:
            criterion.update(status='DEFERRED', evidence=evidence, reason='Documented downstream estimation',
                             needed_material='Index analysis must publish the estimated PD target')
        match.update(status='DEFERRED', source_ids=[key], reason='Target awaiting the documented upstream analysis',
                     needed_material='Index analysis output: PD target',
                     deferred_outputs=[{'producer_task':'Index analysis', 'output':'Estimated PD target', 'evidence':evidence}])
    return edit


def test_documented_pending_target_is_deferred_and_does_not_block_qc(case):
    assess(case, change_review(case, deferred_target(case), phase='BEFORE_PTA'))
    report = read_json(case[1] / 'adequacy/adequacy.json')
    assert report['can_enter_qc']
    assert report['requirements'][0]['coverage_status'] == 'DEFERRED'
    assert report['requirements'][0]['deferred_outputs'][0]['producer_task'] == 'Index analysis'
    assert report['task_assessments'][0]['input_coverage']['MISSING'] == []
    assert report['missing_materials'] == []
    assert report['deferred_requirement_ids'] == ['N001']
    assert report['findings'][0]['reason'].startswith('DEFERRED:')
    assert 'No reviewed source matches' not in report['findings'][0]['reason']


def test_deferral_cannot_hide_a_current_prerequisite(case):
    with pytest.raises(PipelineError, match='current prerequisite'):
        assess(case, change_review(case, deferred_target(case), phase='BEFORE_QC'))


def test_deferral_without_producer_evidence_is_rejected(case):
    edit_target = deferred_target(case)
    def edit(result, payload):
        edit_target(result, payload)
        result['matches'][0]['deferred_outputs'] = []
    with pytest.raises(PipelineError, match='documented producer'):
        assess(case, change_review(case, edit))


def test_source_change_during_review_prevents_publication(case):
    def edit(result, payload):
        (case[0] / 'data.csv').write_text('Time (h),Concentration (mg/L)\n0,999\n', encoding='utf-8')
    with pytest.raises(PipelineError):
        assess(case, change_review(case, edit))
    assert not (case[1] / 'adequacy/requirement_matrix.json').exists()
    assert not (case[1] / 'adequacy/qc_context.json').exists()


def test_reports_in_documents_can_support_input_availability_without_raw_tables():
    need={'id':'N001','task_id':'T001','kind':'DATA','description':'Reported same-drug clearance',
          'fields':['reported clearance'],'conditions':[],'rule_ids':[],'origin':'METHOD_CANDIDATE',
          'required_by':'BEFORE_TRANSLATION','evidence':[{'source':'main:/objective','quote':'Use reported clearance'}]}
    original='The reported clearance was 2 L/h; no individual curves are supplied.'
    item={'id':'F1:document','kind':'DOCUMENT'}
    req={'tasks':[{'id':'T001','evidence':need['evidence']}], 'requirements':[need],
         'access':[{'item_id':item['id'],'disposition':'REVIEW_DATA','requirement_ids':['N001'],'context_paths':[]}]}
    labeled={'labels':[{'item_id':item['id'],'evidence':[{'source':'F1:document:line1','quote':original}]}],
             'coverage':[{'item_id':item['id'],'status':'BODY_REVIEWED'}]}
    plans,catalog=c.build_inputs(req,{'items':[item]},labeled,
                                {'main:/objective':'Use reported clearance',item['id']:'Document descriptor'},
                                lambda item:[('F1:document:line1',original)])
    evidence=[{'source':'F1:document:line1','quote':original}]
    match={'status':'AVAILABLE_CANDIDATE','source_ids':['F1:document:line1'],'reason':'Reported input only',
           'needed_material':'NONE','deferred_outputs':[],
           'criteria':[{'id':check['id'],'status':'SUPPORTED','reason':'Synthetic reported-input match',
                        'needed_material':'NONE','evidence':evidence} for check in plans[0]['criteria']]}
    result=c.validate_match(need,match,plans[0],catalog)
    assert result['coverage_status']=='AVAILABLE_CANDIDATE'
    assert c.task_summaries([{'id':'T001'}],[result])[0]['fit_ready'] is False



def test_linked_footnote_cells_are_notes_not_body_evidence():
    need={'id':'N001','task_id':'T001','kind':'DATA','description':'Plasma concentrations','fields':['concentration'],'conditions':[],'rule_ids':[],
          'origin':'PROJECT_EXPLICIT','required_by':'BEFORE_QC','evidence':[{'source':'main:/objective','quote':'Model plasma PK'}]}
    region={'start_row':1,'end_row':3,'left':1,'right':2,'header_row':1,'note_regions':[{'start_row':5,'end_row':5,'left':1,'right':1,'kind':'FOOTNOTE'}]}
    item={'id':'F1:S1:T1','kind':'TABLE','region':region}
    cells={'F1:S1:T1:A1':{'cell':'A1','row':1,'column':1,'value':'Conc (ng/mL)*'},'F1:S1:T1:A2':{'cell':'A2','row':2,'column':1,'value':4.2},
           'F1:S1:T1:A5':{'cell':'A5','row':5,'column':1,'value':'* Plasma concentration 12 ng/mL at 1 h'}}
    req={'tasks':[{'id':'T001','evidence':need['evidence']}],'requirements':[need],
         'access':[{'item_id':item['id'],'disposition':'REVIEW_DATA','requirement_ids':['N001'],'context_paths':[]}]}
    labeled={'labels':[{'item_id':item['id'],'columns':[],'evidence':[{'source':k,'quote':str(v['value'])} for k,v in cells.items()]}],
             'coverage':[{'item_id':item['id'],'status':'BODY_REVIEWED'}]}
    _,catalog=c.build_inputs(req,{'items':[item]},labeled,{'main:/objective':'Model plasma PK',item['id']:'Table descriptor'},
                             lambda item:[(k,d.render_cell(v)) for k,v in cells.items()],lambda item:list(cells.items()))
    assert [catalog[k]['kind'] for k in cells]==['SOURCE_HEADER','SOURCE_CONTENT','SOURCE_NOTE']
    assert catalog['F1:S1:T1:A2']['content']=='4.2'  # Cells reach review in the cell format, not as JSON records.

def test_matrix_is_registered_in_the_existing_snakemake_contract(case,tmp_path):
    from research_pipeline.workflow_runtime import make_plan
    approval=write_json(tmp_path/'approval.json',{'context':{'artifacts':[{'name':'main.json',**d.file_ref(case[2])}]}})
    plan=make_plan({'mode':'reviewed_context','data_agents_version':'2.0','approved_context':d.file_ref(approval),
                    'job_dir':str(tmp_path/'job'),'out':str(tmp_path/'new_run')})
    contract=read_json(plan['steps']['data_adequacy_agent']['contract'])
    assert any(str(path).endswith('requirement_matrix.json') for path in contract['outputs'])
    assert plan['scheduler']=='Prefect' and plan['file_executor']=='Snakemake'
