"""DP planning pending checks settle only against independent DH + host proof."""
import copy
import json
import pytest
from research_pipeline import data_agents as d
from research_pipeline.common import PipelineError, read_json
from test_data_agents import case as legacy_case, prepared


@pytest.mark.parametrize('scenario',['resolved','scientific_gap','missing_proof','held_source','carried',
                                    'alias','prefixed_alias','reverse_alias'])
def test_execution_pending_lifecycle_preserves_original_and_requires_actual_source_proof(legacy_case,scenario):
    root,run,main,inventory,original,calls=legacy_case
    planning=[]
    def generate(request,**kwargs):
        p=request['payload'];response=original(request,**kwargs)
        if p['stage']=='DP':
            code={'alias':'EXECUTION_NOT_CHECKED','prefixed_alias':'DP_T29_EXECUTION_NOT_CHECKED',
                  'reverse_alias':'NOT_CHECKED_EXECUTION'}.get(scenario,'DP009_EXECUTION_NOT_CHECKED')
            finding={'code':code,'affected_id':p['table']['id'],
                     'reason':'At planning time, actual execution is NOT_CHECKED.',
                     'needed_material':'DP009 source-specific actual host program QC.',
                     'required_by':'BEFORE_EDA','severity':'BLOCK'}
            planning.append(copy.deepcopy(finding));response['findings'].append(finding)
            if scenario=='scientific_gap':
                response['findings'].append({'code':'SCIENTIFIC_IDENTITY_GAP','affected_id':p['table']['id'],
                    'reason':'Experimental-unit identity remains unestablished.',
                    'needed_material':'Original experimental-unit definition.',
                    'required_by':'BEFORE_EDA','severity':'HUMAN_REVIEW'})
            if scenario=='held_source':
                response['tables'][0].update(action='HOLD',columns=[],reason='Source unavailable for preparation.')
        if p['stage']=='DH-handoff':
            outcomes=[]
            for item in p['unresolved_ledger']:
                if item['id'] not in p['due_item_ids']: continue
                if not item['id'].startswith('DP-P'):
                    outcomes.append(next(o for o in response['ledger_outcomes'] if o['item_id']==item['id']))
                    continue
                qc=next((q for q in p['qc_results']['datasets']
                         if q['checked_scope']['source_item_id']==item['field']),p['qc_results'])
                outcomes.append({'item_id':item['id'],
                    'outcome':'CARRIED' if scenario=='carried' else 'RESOLVED',
                    'reason':'Independent synthetic reviewer checked the supplied actual program QC.',
                    'evidence':[] if scenario=='missing_proof' else
                        [{'source':'program_qc','quote':json.dumps(qc,ensure_ascii=False)}],
                    'limitation':'NONE',
                    'carried_to':'BEFORE_MODELING' if scenario=='carried' else 'NOT_APPLICABLE'})
            response['ledger_outcomes']=outcomes
        return response
    fixture=(root,run,main,inventory,generate,calls)
    execution=prepared(fixture)
    metadata=run/'metadata.json'
    d.metadata_review(run,execution,metadata)
    if scenario in {'missing_proof','held_source'}:
        with pytest.raises(PipelineError,match='passed source-specific program QC evidence'):
            d.publish_data(run,execution,metadata,run/'data_preparation',generator=generate)
        assert not (run/'data_preparation/data_report.json').exists()
        return
    d.publish_data(run,execution,metadata,run/'data_preparation',generator=generate)
    report=read_json(run/'data_preparation/data_report.json')
    manifest=read_json(read_json(execution)['manifest']['path'])
    ledger=read_json(report['unresolved_ledger']['path'])
    assert report['handoff_review_complete'] is True
    assert report['technical_processing_complete'] is True
    assert report['scientific_release'] is False and report['fit_ready'] is False
    entry=next(i for i in ledger['items'] if i['id'].startswith('DP-P'))
    assert entry['record']==planning[0]
    assert entry['origin']['step']=='DP'
    if scenario=='carried':
        assert entry['resolution_status']=='CARRIED'
        assert any(f['code']=='DP009_EXECUTION_NOT_CHECKED' for f in report['why_cannot_pass'])
        assert report['resolved_preparation_checks']==[]
    else:
        assert entry['resolution_status']=='RESOLVED'
        assert entry['history'][-1]['evidence'][0]['source']=='program_qc'
        assert report['resolved_preparation_checks'][0]['finding']==planning[0]
        assert not any(f['code']=='DP009_EXECUTION_NOT_CHECKED' for f in report['findings'])
    if scenario=='scientific_gap':
        assert report['status']=='WAITING_FOR_HUMAN_REVIEW'
        assert any(f['code']=='SCIENTIFIC_IDENTITY_GAP' for f in report['why_cannot_pass'])
    assert manifest['scientific_release'] is False
