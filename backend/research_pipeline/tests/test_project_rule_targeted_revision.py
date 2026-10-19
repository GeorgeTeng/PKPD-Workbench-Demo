import copy
import pytest
from research_pipeline import project_rule_agent as a
from research_pipeline.common import write_json,read_json
from test_project_rule_agent import bundle,extraction,reviewer


def patcher(req,**kwargs):
    p=req['payload'];parent=next(x for x in p['candidate']['items'] if x['id']=='P1')
    return {'request_sha256':req['request_sha256'],'candidate_sha256':p['candidate_sha256'],
            'replacements':[{'parent_id':'P1','items':[copy.deepcopy(parent)]}]}


def test_targeted_revision_full_review_exact_hash_schema_and_replay(bundle):
    root,ref,value=bundle;a.extract(ref,root/'extract',generator=extraction)
    old=a.file_ref(root/'extract/candidate.json');feedback=a.file_ref(write_json(root/'finding.json',{'diagnosis':'synthetic'}))
    new=a.revise_candidate(ref,old,['P1'],[feedback],root/'revision',generator=patcher)
    candidate=read_json(new['path']);before=read_json(old['path'])
    assert candidate==before
    historical=a.request(value,'project_rules_review',candidate)
    bound=a.request(value,'project_rules_review',candidate,review_hash_binding=True)
    assert historical!=bound and 'review_contract' not in historical['payload']
    assert bound['payload']['schema']['properties']['candidate_sha256']['enum']==[bound['payload']['candidate_sha256']]
    a.review(ref,new,root/'review',generator=reviewer,bind_known_hashes=True)
    reviewref=read_json(root/'review/review_ref.json')
    result=a.publish(ref,new,reviewref,root/'published')
    assert a.verify_published(result['project_rules_ref'])['status']=='PROJECT_RULES_PUBLISHED'
    write_json(root/'finding.json',{'diagnosis':'changed'})
    with pytest.raises(ValueError):a.verify_published(result['project_rules_ref'])


@pytest.mark.parametrize('mode',['non_target','wrong_child_id','source_unit','classification','wrong_hash'])
def test_targeted_revision_rejects_scope_escape(bundle,mode):
    value=bundle[2];candidate=extraction(a.request(value,'project_rules_extract'))
    req=a.targeted_revision_request(value,candidate,['P1'],[]);response=patcher(req)
    item=response['replacements'][0]['items'][0]
    if mode=='non_target':response['replacements'][0]['parent_id']='P2'
    elif mode=='wrong_child_id':item['id']='UNRELATED'
    elif mode=='source_unit':item['evidence']=copy.deepcopy(candidate['items'][1]['evidence'])
    elif mode=='classification':item['kind']='LITERATURE_FACT'
    else:response['candidate_sha256']='wrong'
    with pytest.raises(ValueError):a._apply_targeted_revision(candidate,response,req,value)


def test_repeated_split_reserves_existing_sibling_ids_without_changing_v1(bundle):
    value=bundle[2];candidate=extraction(a.request(value,'project_rules_extract'))
    sibling=copy.deepcopy(candidate['items'][0]);sibling['id']='P1__2';candidate['items'].append(sibling)
    candidate['source_coverage'][0]['item_ids'].append('P1__2')
    old=a.targeted_revision_request(value,candidate,['P1'],[])
    req=a.targeted_revision_request(value,candidate,['P1'],[],reserve_existing_ids=True)
    assert 'child_id_order' not in old['payload']
    assert req['payload']['child_id_order']['P1'][:2]==['P1','P1__3']
    response=patcher(req);child=copy.deepcopy(response['replacements'][0]['items'][0]);child['id']='P1__3'
    response['replacements'][0]['items'].append(child)
    result=a._apply_targeted_revision(candidate,response,req,value)
    assert next(x for x in result['items'] if x['id']=='P1__2')==sibling
    child['id']='P1__2'
    with pytest.raises(ValueError):a._apply_targeted_revision(candidate,response,req,value)


def test_only_extra_nonbinding_outside_parent_evidence_can_be_discarded(bundle):
    root,ref,value=bundle;candidate=extraction(a.request(value,'project_rules_extract'))
    parentref=a.file_ref(write_json(root/'parent.json',candidate))
    req=a.targeted_revision_request(value,candidate,['P1'],[],reserve_existing_ids=True);response=patcher(req)
    extra=copy.deepcopy(candidate['items'][1]['evidence'][0]);item=response['replacements'][0]['items'][0]
    item['evidence'].append(extra);drops=[{'parent_id':'P1','item_id':'P1','span':extra}]
    new=a.resume_saved_targeted_revision(ref,parentref,a.file_ref(write_json(root/'req.json',req)),
        a.file_ref(write_json(root/'raw.json',response)),[],root/'resume',drops)
    assert read_json(new['path'])==candidate
    a.verify_candidate_recovery(ref,new)
    for location in ['authority','binding']:
        bad=copy.deepcopy(response);item=bad['replacements'][0]['items'][0]
        if location=='authority':item['authority_evidence'].append(extra)
        else:item['field_evidence'][0]['spans'].append(extra)
        with pytest.raises(ValueError):a._discard_nonbinding_evidence(candidate,bad,drops)
    proof=read_json(new['targeted_revision_ref']['path']);proof['discarded_nonbinding_evidence_sha256']='bad'
    write_json(new['targeted_revision_ref']['path'],proof);new['targeted_revision_ref']=a.file_ref(new['targeted_revision_ref']['path'])
    with pytest.raises(ValueError,match='Discard audit'):a.verify_candidate_recovery(ref,new)


def test_v2_review_findings_cannot_mix_published_rule_ids(bundle):
    value=bundle[2];candidate=extraction(a.request(value,'project_rules_extract'))
    v1=a.request(value,'project_rules_review',candidate,review_hash_binding=True)
    v2=a.request(value,'project_rules_review',candidate,review_hash_binding='EXACT_DIGEST_V2')
    assert v1['payload']['review_contract']=='EXACT_DIGEST_V1'
    assert v2['payload']['schema']['properties']['findings']['items']['properties']['item_ids']['items']['enum']==['P1','P2','P3']
    response=reviewer(v2)
    response['findings']=[{'code':'x','severity':'INFO','item_ids':['R001'],'reason':'wrong namespace','needed_material':'none'}]
    with pytest.raises(ValueError):a.validate_review(response,v2,candidate,value)
