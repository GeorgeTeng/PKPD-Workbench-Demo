"""One bounded independent review, with truthful scope and no live providers."""
import copy
import json
import pytest
from research_pipeline import data_agents as d, handoff_review as h
from research_pipeline.common import PipelineError


def payload(large=False):
    records=[{'record_id':f'R{i}','value_status':{'Y':'QUANTIFIED'},
              'source_raw_values':{'Y':i}} for i in range(12)]
    records[2]['duplicate_value_pattern']=True
    records[3]['qc_reasons']=['Needs source review']
    for i,status in enumerate(['CENSORED','BLQ','MISSING_CENSORED_OBSERVATION',
                               'FORMULA_REQUIRES_REVIEW','SOURCE_CELL_ERROR'],4):
        records[i]['value_status']['Y']=status
    records[9]['source_raw_values']['note']='UNRESOLVED identity'
    records[10]['source_raw_values']['note']='REVIEW applicability'
    if large: records[1]['unselected_original']='x'*310_000
    return {'actual_data':[{'id':'T1','records':records,
                           'quarantine':[{'record_id':'Q1','original_value':'uninterpretable'}]}],
        'datasets':[{'id':'T1','metadata':{'dose':'NOT_FOUND','source_notes':'CENS=1 flags censored Y.',
                                        'columns':[]}}],
        'metadata_reviews':[{'dataset_id':'T1','review':{'decision':'PASS'}}],
        'supplied_record_scope':[{'dataset_id':'T1','retained_records':12,'quarantined_records':1}],
        'transformation_logs':{'changes':[{'record_id':r['record_id'],'original':i}
                                        for i,r in enumerate(records)]},
        'qc_results':{'decision':'PASS','input_bindings':[]},
        'artifact_manifest_and_bindings':{'datasets':[{'id':'T1',
            'data':{'path':'data.json','sha256':'original'},
            'metadata_file':{'path':'metadata.json','sha256':'original-metadata'}}]},
        'requirements':[{'id':'RQ1','conditions':['Identity remains unresolved']}],
        'project_rules':[{'id':'G1','text':'Preserve censoring','exceptions':['No guessed LLOQ']}],
        'stated_values':[{'quantity':'dose','value':2,'unit':'mg/kg'},
                         {'quantity':'sample count','value':12,'unit':'count'}],
        'upstream_data':{'coverage':{'path':'coverage.json','sha256':'reviewed'}},
        'expected_check_ids':['T1','HANDOFF_SCOPE'],
        'due_item_ids':['MI1'],'unresolved_ledger':[{'id':'MI1','status':'UNRESOLVED'}],
        'findings':[{'code':'UNKNOWN_ID','reason':'Do not assign subjects.'}],
        'instructions':'Review the supplied evidence.'}


def reply(request):
    return {'request_sha256':request['request_sha256'],'decision':'PASS',
        'checks':[{'id':i,'decision':'PASS','reason':'Synthetic check.'}
                  for i in request['payload']['expected_check_ids']],
        'findings':[],'ledger_outcomes':[{'item_id':i,'outcome':'LIMITATION_ACCEPTED',
            'reason':'Synthetic preservation-only scope.', 'evidence':[],
            'limitation':'Identity remains unresolved; no subject assignment.',
            'carried_to':'NOT_APPLICABLE'} for i in request['payload']['due_item_ids']]}


@pytest.mark.parametrize('timeout',[None,180])
def test_review_timeout_reaches_provider_without_fallback(tmp_path,monkeypatch,timeout):
    observed=[]
    def provider(request,**options):
        observed.append(options['timeout'])
        return reply(request)
    monkeypatch.setattr(d,'codex_generate',provider)
    h.review(tmp_path,payload(),d.HANDOFF_REVIEW,lambda:None,model='gpt-6-astra',timeout=timeout)
    assert observed==[timeout]


def test_handoff_citations_match_transport_without_rewriting_source_values():
    sources={'program_qc':json.dumps({'scientific_adequacy_assessed':False}),
             'dataset:T1':json.dumps({'note':'dose  2 mg/kg','value':2})}
    assert d.handoff_quote_matches({'source':'program_qc','quote':'"scientific_adequacy_assessed":false'},sources)
    assert d.handoff_quote_matches({'source':'dataset:T1 metadata','quote':'dose  2 mg/kg'},sources)
    for source,quote in [('dataset:T2 metadata','dose  2 mg/kg'),('dataset:T1 metadata','dose 2 mg/kg'),
                         ('dataset:T1','"value":3'),('program_qc','"scientific_adequacy_assessed":true')]:
        assert not d.handoff_quote_matches({'source':source,'quote':quote},sources)


@pytest.mark.parametrize('large',[False,True])
def test_one_call_preserves_exceptions_and_discloses_actual_scope(tmp_path,monkeypatch,large):
    monkeypatch.setenv('DATA_AGENT_WORKERS','4')
    p=payload(large);original=copy.deepcopy(p);calls=[];boundaries=[]
    def generate(request,**kwargs):
        calls.append(copy.deepcopy(request['payload']))
        return reply(request)
    result=h.review(tmp_path,p,d.HANDOFF_REVIEW,lambda:boundaries.append(True),generator=generate)
    assert len(calls)==1 and len(boundaries)==2
    sent=calls[0];table=sent['actual_data'][0]
    expected={f'R{i}' for i in range(12)}-({'R1'} if large else set())
    assert {r['record_id'] for r in table['records']}==expected
    assert table['quarantine']==p['actual_data'][0]['quarantine']
    for key in ('findings','unresolved_ledger','due_item_ids','project_rules','requirements'):
        assert sent[key]==p[key]
    assert sent['datasets'][0]['metadata']['source_notes']=='CENS=1 flags censored Y.'
    scope=result['model_record_scope'][0]
    assert scope=={'dataset_id':'T1','total_retained':12,'supplied_retained':len(expected),
                   'total_quarantined':1,'supplied_quarantined':1,'unchecked_by_model':int(large)}
    assert result['host_qc_scope']=='All permitted source rows; not a scientific adequacy assessment.'
    if large:
        assert sent['operation']=='REVIEW_HANDOFF_WITH_HOST_FULL_QC_AND_SELECTED_RECORDS'
        assert 'do not claim full model record review' in sent['instructions']
        assert sent['stated_values_scope']['total']==2 and sent['stated_values_scope']['supplied']==1
        assert {c['record_id'] for c in sent['transformation_logs']['changes']}==expected
        assert sent['artifact_manifest_and_bindings']['datasets']==[{'id':'T1'}]
        assert 'complete manifest' in sent['artifact_manifest_and_bindings']['binding_scope']
    assert p==original


def test_compact_rows_preserve_raw_values_derived_fields_and_source_bindings():
    p=payload(True)
    row=p['actual_data'][0]['records'][0]
    row.update(Y=0,time_h=2,source_file_id='F1',source_sha256='frozen',source_sheet='Sheet1',
               source_cells={'Y':'B2'})
    result=h.compact(p)['actual_data'][0]
    sent=result['records'][0]
    assert sent['source_raw_values']=={'Y':0} and sent['time_h']==2
    assert sent['source_cells']=={'Y':'B2'} and 'Y' not in sent
    assert {'source_file_id':'F1','source_sha256':'frozen','source_sheet':'Sheet1'} in result['source_bindings']


def test_overdue_context_items_require_handoff_outcomes():
    from research_pipeline import unresolved_ledger as ledger
    items=[{'id':'MI1','phase':'BEFORE_QC','resolution_status':'OPEN','history':[],
            'status':'NOT_FOUND','field':'identity'}]
    assert ledger.due(items,'BEFORE_EDA')==[]
    assert ledger.due(items,'BEFORE_EDA',include_overdue=True)==items
    with pytest.raises(PipelineError,match='missing'):
        ledger.apply_outcomes(items,'BEFORE_EDA',[],'DH',lambda _:True,[],include_overdue=True)
    outcome={'item_id':'MI1','outcome':'ESCALATED','reason':'Identity requires source review',
             'evidence':[],'limitation':'NONE','carried_to':'NOT_APPLICABLE'}
    findings=ledger.apply_outcomes(items,'BEFORE_EDA',[outcome],'DH',lambda _:True,[],include_overdue=True)
    assert items[0]['phase']=='BEFORE_QC' and items[0]['resolution_status']=='ESCALATED'
    assert findings[0]['required_by']=='BEFORE_EDA'


def test_routed_finding_is_sent_once_without_losing_its_record():
    p=payload(True);finding=copy.deepcopy(p['findings'][0])
    p['unresolved_ledger'].append({'id':'DP-U001','record':finding})
    result=h.compact(p)
    assert result['findings']==[]
    assert result['unresolved_ledger'][-1]['record']==finding


def test_identity_conversion_examples_are_bounded_and_scope_disclosed():
    p=payload(True)
    p['transformation_logs']['changes']=[
        {'record_id':'R0','field':'time_h','factor':1,'before':0,'after':0},
        {'record_id':'R11','field':'time_h','factor':1,'before':11,'after':11},
        {'record_id':'R4','field':'time_h','factor':2,'before':4,'after':8}]
    # Actual record IDs identify their dataset before _R.
    for row in p['actual_data'][0]['records']:row['record_id']='T1_'+row['record_id']
    for change in p['transformation_logs']['changes']:change['record_id']='T1_'+change['record_id']
    log=h.compact(p)['transformation_logs']
    assert log['total_changes']==3 and log['supplied_changes']==2
    assert [c['factor'] for c in log['changes']]==[1,2]
    assert 'one example per dataset/field' in log['scope']


@pytest.mark.parametrize('when',['before','after'])
def test_input_drift_blocks_review_before_or_after_call(tmp_path,when):
    calls=[];changed=when=='before'
    def verify():
        if changed: raise PipelineError('INPUT_CHANGED','Approved input changed.')
    def generate(request,**kwargs):
        nonlocal changed
        calls.append(True);changed=True
        return reply(request)
    with pytest.raises(PipelineError,match='Approved input changed'):
        h.review(tmp_path,payload(),d.HANDOFF_REVIEW,verify,generator=generate)
    assert len(calls)==(0 if when=='before' else 1)
    assert not list(tmp_path.rglob('data_report.json'))


def test_invalid_ledger_rejected_before_cache_and_valid_retry_rechecked(tmp_path):
    calls=[];valid=False;checks=[]
    def generate(request,**kwargs):
        calls.append(True)
        return reply(request)
    generate.executor_id='isolated-handoff'
    def validate(response):
        checks.append(True)
        if not valid: raise PipelineError('INVALID_LEDGER','Missing independent ledger outcome.')
    with pytest.raises(PipelineError,match='Missing independent ledger'):
        h.review(tmp_path,payload(),d.HANDOFF_REVIEW,lambda:None,
                 validate_package=validate,generator=generate)
    assert len(calls)==1 and not list((tmp_path/'data_agents/kept').glob('*.json'))
    valid=True
    for _ in range(2):
        h.review(tmp_path,payload(),d.HANDOFF_REVIEW,lambda:None,
                 validate_package=validate,generator=generate)
    assert len(calls)==2 and len(checks)==3
    assert len(list((tmp_path/'data_agents/kept').glob('*.json')))==1
    reuse=[json.loads(line) for line in (tmp_path/'data_agents/cache_reuse.jsonl').read_text().splitlines()]
    assert len(reuse)==1 and reuse[0]['stage']=='DH-handoff'
