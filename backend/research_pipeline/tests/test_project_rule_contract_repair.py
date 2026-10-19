import copy
import pytest
from ctxcomp.io import digest
from research_pipeline import project_rule_agent as a
from research_pipeline.common import write_json, read_json
from test_project_rule_agent import bundle, extraction, reviewer


def broken(bundle):
    req = a.request(bundle[2], 'project_rules_extract'); raw = extraction(req)
    for item in raw['items']:
        if item['kind'] == 'PROJECT_REQUIREMENT':
            item['authority_evidence'] = []
            item['field_evidence'] = [b for b in item['field_evidence'] if not b['path'].startswith('/requirement/forms/')]
    return req, raw


def repairer(req, **kwargs):
    p = req['payload']; items = {i['id']:i for i in p['candidate']['items']}
    return {'request_sha256':req['request_sha256'], 'candidate_sha256':p['candidate_sha256'],
            'decision':'REPAIRED', 'reason':'Synthetic citation repair, not scientific approval.',
            'items':[{'item_id':t['item_id'],
                      'authority_evidence':copy.deepcopy(items[t['item_id']]['evidence']) if t['authority_missing'] else [],
                      'field_evidence':[{'path':path,'spans':copy.deepcopy(items[t['item_id']]['evidence'])}
                                        for path in t['missing_form_paths']]}
                     for t in p['repair_targets']]}


def test_targeted_model_repair_preserves_all_scientific_fields_and_replays(bundle):
    root, ref, value = bundle; req, raw = broken(bundle); original = copy.deepcopy(raw)
    candidate_ref = a.repair_saved_contract(ref, a.file_ref(write_json(root/'request.json',req)),
                                          a.file_ref(write_json(root/'raw.json',raw)),root/'repair',generator=repairer)
    candidate = read_json(candidate_ref['path'])
    for old, new in zip(original['items'], candidate['items']):
        for key in old:
            if key not in {'evidence','authority_evidence','field_evidence'}:assert old[key] == new[key]
    assert candidate['source_coverage'] == original['source_coverage']
    assert read_json(root/'raw.json') == original
    a.review(ref,candidate_ref,root/'review',generator=reviewer)
    result=a.publish(ref,candidate_ref,a.file_ref(root/'review/review.json'),root/'published')
    assert a.verify_published(result['project_rules_ref'])['status']=='PROJECT_RULES_PUBLISHED'
    write_json(root/'raw.json',{})
    with pytest.raises(ValueError):a.verify_published(result['project_rules_ref'])


@pytest.mark.parametrize('mode',['wrong_hash','omit_item','text_edit','invalid_quote','supporting_authority','unresolved','extra_field'])
def test_repair_is_strictly_bounded(bundle,mode):
    req,raw=broken(bundle); r=a.contract_repair_request(bundle[2],raw); response=repairer(r)
    if mode=='wrong_hash':response['candidate_sha256']='wrong'
    elif mode=='omit_item':response['items'].pop()
    elif mode=='text_edit':response['items'][0]['text']='Invented requirement'
    elif mode=='invalid_quote':response['items'][0]['authority_evidence'][0]['quote']='Invented'
    elif mode=='supporting_authority':response['items'][0]['authority_evidence']=copy.deepcopy(raw['items'][2]['evidence'])
    elif mode=='unresolved':response['decision']='UNRESOLVED'
    else:response['items'][0]['field_evidence'][0]['path']='/requirement/action'
    with pytest.raises(ValueError):a._apply_contract_repair(raw,response,r,bundle[2])


def test_explicit_existing_field_unit_recovery_requires_raw_span_and_coverage(bundle):
    root,ref,value=bundle;req,raw=broken(bundle)
    extra=copy.deepcopy(raw['items'][1]['evidence'][0])
    raw['items'][0]['field_evidence'][0]['spans'].append(extra)
    raw['source_coverage'][1]['item_ids'].append('P1')
    r=a.contract_repair_request(value,raw);response=repairer(r)
    with pytest.raises(ValueError,match='source-unit'):
        a._apply_contract_repair(raw,response,r,value)
    links=[{'item_id':'P1','source_id':extra['source_id'],'unit_id':extra['unit_id']}]
    c=a.resume_saved_contract(ref,a.file_ref(write_json(root/'extreq.json',req)),
        a.file_ref(write_json(root/'raw.json',raw)),a.file_ref(write_json(root/'repairreq.json',r)),
        a.file_ref(write_json(root/'response.json',response)),root/'resume',links)
    a.verify_candidate_recovery(ref,c)
    proof=read_json(c['contract_repair_ref']['path']);proof['existing_field_links_sha256']='tampered'
    write_json(c['contract_repair_ref']['path'],proof);c['contract_repair_ref']=a.file_ref(c['contract_repair_ref']['path'])
    with pytest.raises(ValueError,match='whitelist'):a.verify_candidate_recovery(ref,c)
    wrong=[{'item_id':'P2','source_id':extra['source_id'],'unit_id':raw['items'][0]['evidence'][0]['unit_id']}]
    with pytest.raises(ValueError,match='original field'):
        a._apply_contract_repair(raw,response,r,value,wrong)
