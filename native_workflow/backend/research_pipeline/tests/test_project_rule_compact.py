"""Compact requirements retain evidence, review and stage-specific delivery."""
import copy
import pytest
from ctxcomp.io import digest
from research_pipeline import project_rule_agent as a
from research_pipeline.common import read_json, write_json
from test_project_rule_agent import bundle


@pytest.fixture
def compact_bundle(bundle):
    root, _, old = bundle
    value = a._input_value(old['base_main_ref'], old['sources'], old['source_refs'], compact=True)
    # This suite replays the frozen pre-ledger contract. New default behavior has
    # its own lightweight integration tests; ledger replay is tested separately.
    policy=a.compact_rules.SUPPORTED_POLICIES['1.3.4']
    reference=a.compact_rules.SUPPORTED_WORKFLOW_REFERENCES['1.1.0']
    value.update(extraction_policy=copy.deepcopy(policy),policy_sha256=digest(policy),processing_rules=copy.deepcopy(policy['rules']),
        workflow_reference=copy.deepcopy(reference),workflow_reference_sha256=digest(reference))
    ref = a.file_ref(write_json(root/'compact_input.json', value))
    return root, ref, value


def extract(req, **_):
    p = req['payload']; units = p['source_units']
    items = [{'id':f'C{i+1}', 'text':u['text'].strip(),
              'used_in':['pk_translation' if 'pk_translation' in p['step_catalog'] else 'human_pk','human_validation'] if i == 0 else ['prepare'],
              'evidence':[{'source_id':u['source_id'],'unit_id':u['id'],'quote':u['text'].strip()}]}
             for i,u in enumerate(units[:2])]
    return {'request_sha256':req['request_sha256'], 'items':items,
        'source_coverage':[{'unit_id':u['id'], 'item_ids':[items[i]['id']] if i<2 else [],
            'disposition':'CLASSIFIED' if i<2 else 'NO_REQUIREMENT',
            'reason':'Adopted requirement' if i<2 else 'Literature description, no adopted project requirement'} for i,u in enumerate(units)],
        'original_rule_mapping':[{'path':p,'item_ids':['C1'],'reason':'Preserved with its freeze condition'} for p in p['required_original_rule_paths']],
        'findings':[]}


def review(req, **_):
    p=req['payload']; schema=p['schema']['properties']
    checks=lambda field,key:[{key:x,'verdict':'PASS','reason':'Synthetic source-grounded check'}
        for x in schema[field]['items']['properties'][key].get('enum',[])]
    return {'request_sha256':req['request_sha256'], 'candidate_sha256':p['candidate_sha256'],
        'final_rules_sha256':p['publication_candidate']['final_rules_sha256'], 'decision':'PASS',
        'final_rule_checks':checks('final_rule_checks','rule_id'),
        'source_checks':checks('source_checks','unit_id'),
        'original_rule_checks':checks('original_rule_checks','path'),
        'global_checks':checks('global_checks','id'), 'findings':[]}


def publish(bundle):
    root,ref,_=bundle
    a.extract(ref,root/'extract_compact',generator=extract)
    cr=a.file_ref(root/'extract_compact/candidate.json')
    a.review(ref,cr,root/'review_compact',generator=review)
    return a.publish(ref,cr,a.file_ref(root/'review_compact/review.json'),root/'published_compact')


def test_compact_pipeline_keeps_one_evidence_copy_and_routes_specific_steps(compact_bundle):
    root,ref,value=compact_bundle
    assert a.validate_input(ref)['schema_version']=='1.3'
    req=a.request(value,'project_rules_extract')
    assert set(req['payload']['schema']['properties']['items']['items']['properties'])=={'id','text','used_in','evidence'}
    assert 'sources' not in req['payload']  # Source units already carry the full original text.
    result=publish(compact_bundle); pack=a.verify_published(result['project_rules_ref'])
    assert a.request(value,'project_rules_extract')==req
    assert all(set(r)=={'id','text','used_in','evidence'} for r in pack['rules'])
    assert pack['rules'][0]['evidence'][0]['quote']==value['source_units'][0]['text'].strip()
    assert 'after predictions are frozen' in pack['rules'][0]['text']
    assert [r['id'] for r in a.project(result['project_rules_ref'],'human_validation')['rules']]==['R001']
    assert a.project(result['project_rules_ref'],'pta')['rules']==[]
    assert [r['id'] for r in a.project(result['project_rules_ref'],'clinical')['rules']]==['R001']
    assert [r['id'] for r in a.project(result['project_rules_ref'],'prepare')['rules']]==['R002']
    assert read_json(result['main_ref']['path'])['rules']==[]


@pytest.mark.parametrize('fault',['invented_quote','paper_authority','no_stage','unknown_stage','duplicate_stage','coverage_omission','false_coverage'])
def test_bad_evidence_or_routing_stops_before_review(compact_bundle,fault):
    _,_,v=compact_bundle; req=a.request(v,'project_rules_extract'); c=extract(req)
    if fault=='invented_quote':c['items'][0]['evidence'][0]['quote']='Not in the original source'
    elif fault=='paper_authority':
        u=v['source_units'][2];c['items'][0]['evidence']=[{'source_id':u['source_id'],'unit_id':u['id'],'quote':u['text']}]
    elif fault=='no_stage':c['items'][0]['used_in']=[]
    elif fault=='unknown_stage':c['items'][0]['used_in']=['imaginary']
    elif fault=='duplicate_stage':c['items'][0]['used_in']=['prepare','prepare']
    elif fault=='coverage_omission':c['source_coverage'][0].update(item_ids=[],disposition='NO_REQUIREMENT')
    else:c['source_coverage'][2].update(item_ids=['C1'],disposition='CLASSIFIED')
    with pytest.raises(ValueError):a.validate_candidate(c,req,v)


def test_review_cannot_pass_missing_checks_or_unsupported_rule(compact_bundle):
    _,_,v=compact_bundle;c=extract(a.request(v,'project_rules_extract')); req=a.request(v,'project_rules_review',c)
    response=review(req);response['final_rule_checks'][0]['verdict']='REVISE'
    with pytest.raises(ValueError):a.validate_review(response,req,c,v)
    response=review(req);response['source_checks'].pop()
    with pytest.raises(ValueError):a.validate_review(response,req,c,v)
    response=review(req);response['final_rules_sha256']='changed'
    with pytest.raises(ValueError):a.validate_review(response,req,c,v)


@pytest.mark.parametrize('change',['evidence','audit','scientific_approval'])
def test_compact_evidence_cannot_change_after_review(compact_bundle,change):
    result=publish(compact_bundle);p=result['project_rules_ref']['path'];pack=read_json(p)
    if change=='evidence':pack['rules'][0]['evidence'][0]['quote']='Changed evidence'
    elif change=='audit':
        audit=read_json(pack['audit_ref']['path']);audit['original_rule_mapping']=[]
        write_json(pack['audit_ref']['path'],audit);pack['audit_ref']=a.file_ref(pack['audit_ref']['path'])
    else:pack['scientific_results_accepted']=True
    write_json(p,pack)
    main=read_json(result['main_ref']['path']);main['project_rules_ref']=a.file_ref(p)
    write_json(result['main_ref']['path'],main)
    with pytest.raises(ValueError):a.verify_published(a.file_ref(p))


def test_compact_data_and_clinical_consumers_keep_evidence(compact_bundle):
    from research_pipeline.data_agents import rules_for
    from research_pipeline.data_test_workflow import embedded_projection
    from research_pipeline.clinical_questions import context_statements
    result=publish(compact_bundle);main=read_json(result['main_ref']['path']);pack=a.verify_published(result['project_rules_ref'])
    projected=rules_for(main,['prepare'])
    assert len(projected)==1 and projected[0]['evidence']==pack['rules'][1]['evidence']
    embedded={**main,'rules':pack['rules']}
    assert embedded_projection(embedded,['prepare'])==projected
    rows=[r for r in context_statements(main,'human_validation') if r['source']=='project_rules.json']
    assert len(rows)==1 and rows[0]['quote']==pack['rules'][0]['text']


def test_no_rules_is_valid_but_unresolved_requirement_cannot_publish(compact_bundle):
    _,_,v=compact_bundle
    # A fresh input with no inherited obligation may legitimately have no rules.
    v=copy.deepcopy(v);v['existing_rules']=[]
    req=a.request(v,'project_rules_extract');c=extract(req);c['items']=[]
    for row in c['source_coverage']:row.update(item_ids=[],disposition='NO_REQUIREMENT')
    a.validate_candidate(c,req,v)
    c['source_coverage'][0]['disposition']='UNRESOLVED'
    rreq=a.request(v,'project_rules_review',c)
    with pytest.raises(ValueError):a.validate_review(review(rreq),rreq,c,v)


def test_exact_duplicates_merge_without_repeating_evidence(compact_bundle):
    from research_pipeline.project_rule_compact import assemble
    _,_,value=compact_bundle;req=a.request(value,'project_rules_extract');candidate=extract(req)
    duplicate=copy.deepcopy(candidate['items'][0]);duplicate['id']='C3';duplicate['used_in'].reverse()
    candidate['items'].append(duplicate);candidate['source_coverage'][0]['item_ids'].append('C3')
    a.validate_candidate(candidate,req,value)
    rules,mapping=assemble(candidate)
    assert len(rules)==2 and len(rules[0]['evidence'])==1
    assert rules[0]['text']==duplicate['text']
    assert mapping[0]['candidate_ids']==['C1','C3']


def test_revise_keeps_review_without_publishing(compact_bundle):
    root,ref,_=compact_bundle
    a.extract(ref,root/'extract_compact',generator=extract)
    cr=a.file_ref(root/'extract_compact/candidate.json')
    def revise(req,**_):
        result=review(req);result['decision']='REVISE'
        result['global_checks'][0].update(verdict='REVISE',reason='Unnecessary rule requires source-grounded correction')
        return result
    a.review(ref,cr,root/'review_compact',generator=revise)
    result=a.publish(ref,cr,a.file_ref(root/'review_compact/review.json'),root/'blocked')
    assert not result['handoff_published'] and result['failed_checks']['global_checks']
    assert not (root/'blocked/project_rules.json').exists()


def test_compact_first_part_roundtrip_preserves_full_rules(compact_bundle,monkeypatch):
    from ctxcomp import engine
    from research_pipeline import first_part_handoff as f
    from test_first_part_handoff import passing
    root,ref,value=compact_bundle
    value['compression_run']=str(root/'compression')
    write_json(ref['path'],value);ref.update(a.file_ref(ref['path']))
    report=publish(compact_bundle)
    monkeypatch.setattr(engine,'verify_context',lambda _: {'status':'VALID'})
    proof=f.prepare(report['project_rules_ref'],root/'combined')
    f.review(root/'combined',generator=passing)
    verified=f.publish(root/'combined',root/'published_combined')
    assert verified['status']=='VALID'
    assert read_json(verified['main_ref']['path'])['rules']==read_json(report['project_rules_ref']['path'])['rules']
    assert verified['main_ref']['sha256']==proof['main_ref']['sha256']


def test_workflow_reference_is_shared_context_not_source_or_output(compact_bundle):
    from research_pipeline import project_rule_compact as compact
    _,ref,value=compact_bundle
    a.validate_input(ref)
    req=a.request(value,'project_rules_extract');candidate=extract(req)
    review_req=a.request(value,'project_rules_review',candidate)
    reference=value['workflow_reference']
    assert len(reference['modules'])==12
    for request in (req,review_req):
        p=request['payload']
        assert p['workflow_reference']==reference
        assert p['workflow_reference_sha256']==digest(reference)
        assert p['source_units']==value['source_units']
        assert p['source_permissions']==value['source_permissions']
        assert p['step_catalog']==compact.POLICY['steps']
        assert 'not project authority or source evidence' in p['instructions']
    for module in reference['modules']:
        assert set(module['routing_hint']['tags'])<=compact.POLICY['steps'].keys()
    # Reference text cannot become citable source material even beside a valid citation.
    candidate['items'][0]['evidence'].append({
        'source_id':'workflow_reference','unit_id':'workflow_reference/modules/pk',
        'quote':reference['modules'][5]['purpose']})
    with pytest.raises(ValueError):a.validate_candidate(candidate,req,value)


@pytest.mark.parametrize('fault',['missing_reference','missing_hash','changed_hash','changed_text_rehashed'])
def test_workflow_snapshot_must_match_its_frozen_version(compact_bundle,fault):
    root,_,value=compact_bundle;value=copy.deepcopy(value)
    if fault=='missing_reference':value.pop('workflow_reference')
    elif fault=='missing_hash':value.pop('workflow_reference_sha256')
    elif fault=='changed_hash':value['workflow_reference_sha256']='changed'
    else:
        value['workflow_reference']['modules'][0]['purpose']='Invented mandatory project requirement'
        value['workflow_reference_sha256']=digest(value['workflow_reference'])
    ref=a.file_ref(write_json(root/'changed_reference.json',value))
    with pytest.raises(ValueError):a.validate_input(ref)
    with pytest.raises(ValueError):a.request(value,'project_rules_extract')


def test_historical_compact_input_does_not_gain_reference_context(compact_bundle):
    from research_pipeline import project_rule_compact as compact
    root,_,value=compact_bundle;value=copy.deepcopy(value)
    policy=copy.deepcopy(compact.SUPPORTED_POLICIES['1.3.0'])
    value.update(extraction_policy=policy,policy_sha256=digest(policy),processing_rules=policy['rules'])
    value.pop('workflow_reference');value.pop('workflow_reference_sha256')
    ref=a.file_ref(write_json(root/'historical_input.json',value))
    a.validate_input(ref)
    req=a.request(value,'project_rules_extract');candidate=extract(req)
    # Shared governance prepends its existing instructions in both contracts.
    assert req['payload']['instructions'].endswith(compact.INSTRUCTIONS)
    for request in (req,a.request(value,'project_rules_review',candidate)):
        assert 'workflow_reference' not in request['payload']
        assert 'workflow_reference_sha256' not in request['payload']
    report=publish((root,ref,value))
    assert a.verify_published(report['project_rules_ref'])['schema_version']=='1.3'
