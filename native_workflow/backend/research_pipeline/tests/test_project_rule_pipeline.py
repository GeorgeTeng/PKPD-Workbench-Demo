"""Mutation tests for ledger mechanics, not a substitute for real semantic review."""
import copy
import pytest
from ctxcomp.io import digest
from research_pipeline import project_rule_agent as a, project_rule_pipeline as p
from research_pipeline.common import read_json,write_json
from test_project_rule_agent import bundle


@pytest.fixture
def ledger_bundle(bundle):
    root,_,old=bundle
    v=a._input_value(old['base_main_ref'],old['sources'],old['source_refs'],compact=True)
    policy=a.compact_rules.SUPPORTED_POLICIES['1.4.1']
    reference=a.compact_rules.SUPPORTED_WORKFLOW_REFERENCES['1.2.0']
    v.update(extraction_policy=copy.deepcopy(policy),policy_sha256=digest(policy),processing_rules=copy.deepcopy(policy['rules']),
        workflow_reference=copy.deepcopy(reference),workflow_reference_sha256=digest(reference))
    return root,a.file_ref(write_json(root/'ledger_input.json',v)),v


def generate(req,**_):
    q=req['payload'];stage=q['stage']
    if stage=='project_rules_inventory':
        return {'request_sha256':req['request_sha256'],'segments':[
            {'segment_id':s['id'],'disposition':'OBLIGATIONS','reason':'Explicit synthetic requirement',
             'obligations':[{'id':'O1','text':s['text'],'evidence':[{'source_id':s['source_id'],'unit_id':s['unit_id'],'quote':s['text']}]}]}
            for s in q['source_segments']]}
    if stage=='project_rules_consolidate':
        return {'request_sha256':req['request_sha256'],'rules':[
            {'id':f'R{i+1:03d}','text':o['text'],'obligation_ids':[o['id']],
             'operations':['prediction_release'] if i==0 else ['data_preparation']}
            for i,o in enumerate(q['obligation_inventory'])], 'excluded':[],
            'original_rule_mapping':[{'path':path,'item_ids':['R001'],'reason':'Retained'} for path in q['required_original_rule_paths']]}
    if stage=='project_rules_review':
        response={'request_sha256':req['request_sha256'],'candidate_sha256':q['candidate_sha256'],
            'final_rules_sha256':q['publication_candidate']['final_rules_sha256'],'decision':'PASS','findings':[],'repair_targets':[]}
        for field,schema in q['schema']['properties'].items():
            if not field.endswith('_checks'):continue
            props=schema['items']['properties'];key=next(k for k in props if k not in ('verdict','reason'))
            response[field]=[{key:id,'verdict':'PASS','reason':'Synthetic reviewed case'} for id in props[key].get('enum',[])]
        return response
    raise AssertionError(stage)


def candidate(v):
    inv=generate(p.inventory_request(v));draft=generate(p.consolidation_request(v,inv))
    return p.materialize(v,inv,draft)


def test_three_stage_publication_and_evidence(ledger_bundle):
    root,ref,v=ledger_bundle;calls=[]
    def record(req,**kw):calls.append(req['payload']['stage']);return generate(req,**kw)
    c=a.extract(ref,root/'extract',generator=record)
    sel=p.review_with_repair(ref,a.file_ref(root/'extract/candidate.json'),root/'review',generator=record)
    report=a.publish(ref,sel['candidate_ref'],sel['review_ref'],root/'published')
    pack=a.verify_published(report['project_rules_ref'])
    assert calls==['project_rules_inventory','project_rules_consolidate','project_rules_review']
    assert all(set(r)=={'id','text','used_in','evidence'} for r in pack['rules'])
    assert pack['rules']==c['items']
    assert len(read_json(report['audit_ref']['path'])['module_views'])==12
    assert [r['id'] for r in a.project(report['project_rules_ref'],'pk_translation')['rules']]==['R001']


@pytest.mark.parametrize('fault',['drop_obligation','wrong_used_in','alter_evidence','duplicate_text','orphan_segment','forged_quote','omit_mapping'])
def test_corruption_cannot_be_hidden_in_coverage(ledger_bundle,fault):
    _,_,v=ledger_bundle;c=candidate(v)
    if fault=='drop_obligation':c['consolidation']['rules'].pop()
    elif fault=='wrong_used_in':c['items'][0]['used_in']=['prepare']
    elif fault=='alter_evidence':c['items'][0]['evidence'][0]['quote']='Invented'
    elif fault=='duplicate_text':c['consolidation']['rules'][1]['text']=c['consolidation']['rules'][0]['text']
    elif fault=='orphan_segment':c['inventory']['segments'].pop()
    elif fault=='forged_quote':c['inventory']['segments'][0]['obligations'][0]['evidence'][0]['quote']='Invented'
    else:c['consolidation']['original_rule_mapping']=[]
    with pytest.raises((ValueError,KeyError)):p.validate_candidate(c,v)


def test_routing_is_order_independent_and_review_sees_delivery(ledger_bundle):
    _,_,v=ledger_bundle;c=candidate(v);changed=copy.deepcopy(c)
    changed['consolidation']['rules'].reverse();changed['inventory']['segments'].reverse()
    assert p.materialize(v,changed['inventory'],changed['consolidation'])['items']==c['items']
    req=p.review_request(v,c)
    translation=next(m for m in req['payload']['module_views'] if m['module_id']=='translation')
    assert translation['rule_ids']==['R001']
    assert 'used_in' not in p.draft_schema(v,c['inventory'])['properties']['rules']['items']['properties']


@pytest.mark.parametrize('field',['module_checks','obligation_checks','segment_checks'])
def test_review_cannot_skip_new_checks(ledger_bundle,field):
    _,_,v=ledger_bundle;c=candidate(v);req=p.review_request(v,c);r=generate(req)
    r[field].pop()
    with pytest.raises(ValueError):p.validate_review(r,req,c,v)


def rejection(v,c):
    req=p.review_request(v,c);r=generate(req);r['decision']='REVISE'
    r['final_rule_checks'][1].update(verdict='REVISE',reason='Synthetic local correction')
    r['repair_targets']=[{'rule_ids':['R002'],'segment_ids':[],'reason':'Clarify original units for rats'}]
    return r


def patch_response(req,c):
    row=copy.deepcopy(c['consolidation']['rules'][1]);row['text']='Preserve original units for rats.'
    return {'request_sha256':req['request_sha256'],'segments':[],'rules':[row],'removed_rule_ids':[],'excluded':[]}


def test_patch_preserves_unaffected_rules_and_requires_fresh_review(ledger_bundle):
    root,ref,v=ledger_bundle;c=candidate(v);r=rejection(v,c)
    cr=a.file_ref(write_json(root/'before.json',c));rr=a.file_ref(write_json(root/'before_review.json',r))
    patched=p.repair(ref,cr,rr,root/'repair',generator=lambda req,**_:patch_response(req,c))
    assert patched['items'][0]==c['items'][0]
    assert patched['items'][1]['text']!=c['items'][1]['text']
    with pytest.raises(ValueError):a.publish(ref,a.file_ref(root/'repair/candidate.json'),rr,root/'bad_publish')
    a.review(ref,a.file_ref(root/'repair/candidate.json'),root/'new_review',generator=generate)
    result=a.publish(ref,a.file_ref(root/'repair/candidate.json'),a.file_ref(root/'new_review/review.json'),root/'good_publish')
    a.verify_published(result['project_rules_ref'])
    with pytest.raises(ValueError):p.repair_request(v,patched,rejection(v,patched))


@pytest.mark.parametrize('fault',['unrelated_rule','unrelated_obligation','wrong_request'])
def test_patch_cannot_regenerate_unrelated_records(ledger_bundle,fault):
    _,_,v=ledger_bundle;c=candidate(v);req=p.repair_request(v,c,rejection(v,c));patch=patch_response(req,c)
    if fault=='unrelated_rule':patch['rules'].append(copy.deepcopy(c['consolidation']['rules'][0]))
    elif fault=='unrelated_obligation':patch['rules'][0]['obligation_ids']=c['consolidation']['rules'][0]['obligation_ids']
    elif fault=='wrong_request':patch['request_sha256']='bad'
    with pytest.raises(ValueError):p.apply_patch_response(patch,req,v,c)


def test_omitted_patch_row_is_preserved_not_deleted(ledger_bundle):
    _,_,v=ledger_bundle;c=candidate(v);req=p.repair_request(v,c,rejection(v,c));patch=patch_response(req,c)
    patch['rules']=[]
    inv,draft=p.apply_patch_response(patch,req,v,c)
    assert p.materialize(v,inv,draft)['items']==c['items']


def test_unchanged_neighbour_echo_does_not_mutate_original_audit_reason(source_route_bundle):
    _,_,v=source_route_bundle;c=source_candidate(v);req=p.repair_request(v,c,rejection(v,c))
    echo=copy.deepcopy(c['inventory']['segments'][0]);echo['reason']='An unnecessary paraphrase'
    patch=patch_response(req,c);patch.update(segments=[echo],route_updates=[])
    inv,draft=p.apply_patch_response(patch,req,v,c)
    assert inv['segments'][0]==c['inventory']['segments'][0]
    patch['segments'][0]['obligations'][0]['operations']=['pta_design']
    with pytest.raises(ValueError):p.apply_patch_response(patch,req,v,c)


def test_identical_rule_echo_is_ignored_but_unrelated_edits_are_rejected(source_route_bundle):
    _,_,v=source_route_bundle;c=source_candidate(v);req=p.repair_request(v,c,rejection(v,c))
    patch=patch_response(req,c);patch['route_updates']=[]
    patch['rules'].append(copy.deepcopy(c['consolidation']['rules'][0]))
    inv,draft=p.apply_patch_response(patch,req,v,c)
    assert p.materialize(v,inv,draft)['items'][0]==c['items'][0]
    patch['rules'][-1]['text']='Unrelated edit'
    with pytest.raises(ValueError,match='unrelated rules'):p.apply_patch_response(patch,req,v,c)


def test_semantic_exclusion_is_visible_and_review_can_block_it(ledger_bundle):
    _,_,v=ledger_bundle;c=candidate(v);draft=c['consolidation'];removed=draft['rules'].pop()
    draft['excluded']=[{'obligation_id':removed['obligation_ids'][0],'reason':'Incorrect model judgment: unnecessary'}]
    c=p.materialize(v,c['inventory'],draft);p.validate_candidate(c,v)
    req=p.review_request(v,c);r=generate(req)
    r['obligation_checks'][-1].update(verdict='REVISE',reason='Source duty improperly excluded')
    with pytest.raises(ValueError):p.validate_review(r,req,c,v)


def test_source_omission_patch_adds_obligation_without_rewriting_others(ledger_bundle):
    _,_,v=ledger_bundle;c=candidate(v)
    second=c['inventory']['segments'][1];second['disposition']='CONTEXT';second['obligations']=[]
    c['consolidation']['rules'].pop()
    c['consolidation']['request_sha256']=p.consolidation_request(v,c['inventory'])['request_sha256']
    c=p.materialize(v,c['inventory'],c['consolidation']);p.validate_candidate(c,v)
    review=generate(p.review_request(v,c));review['decision']='REVISE'
    review['repair_targets']=[{'rule_ids':[],'segment_ids':[second['segment_id']],'reason':'Original units obligation omitted'}]
    req=p.repair_request(v,c,review)
    full=candidate(v)
    patch={'request_sha256':req['request_sha256'],'segments':[full['inventory']['segments'][1]],
        'rules':[full['consolidation']['rules'][1]],'removed_rule_ids':[],'excluded':[]}
    inv,draft=p.apply_patch_response(patch,req,v,c)
    result=p.materialize(v,inv,draft)
    assert result['items']==full['items']


def test_duplicate_shortlist_is_route_independent_and_does_not_merge_species():
    rules=[{'id':'mic_short','text':'Freeze MIC input before dose simulation.','used_in':['pta']},
        {'id':'mic_full','text':'Preserve MIC bins and units, derive probabilities and freeze MIC input before dose simulation.','used_in':['prepare']},
        {'id':'dog','text':'In dog evidence, separate total radioactivity from unchanged meropenem.','used_in':['animal_pk']},
        {'id':'analytes','text':'Separate routes and analytes, including unchanged meropenem and total radioactivity. Keep plasma and serum distinct.','used_in':['prepare']},
        {'id':'rabbit','text':'Use rabbit evidence only when model parameters identify a supported component.','used_in':['animal_pk']},
        {'id':'monkey','text':'Use monkey evidence only when conflicting animal counts and doses are preserved.','used_in':['animal_pk']}]
    original=copy.deepcopy(rules);pairs=p.duplicate_candidates(rules)
    ids={frozenset(row['rule_ids']) for row in pairs}
    assert frozenset(('mic_short','mic_full')) in ids
    assert frozenset(('dog','analytes')) in ids
    assert rules==original
    assert p.duplicate_candidates(list(reversed(rules)))==pairs


def test_duplicate_and_operation_review_are_mandatory(ledger_bundle):
    _,_,v=ledger_bundle;c=candidate(v);req=p.review_request(v,c)
    for field in ('duplicate_checks','operation_checks'):
        r=generate(req);r.pop(field)
        with pytest.raises(ValueError):p.validate_review(r,req,c,v)
    r=generate(req);r['operation_checks'][0]['verdict']='REVISE'
    with pytest.raises(ValueError):p.validate_review(r,req,c,v)


def test_every_module_receives_exactly_its_reviewed_view(ledger_bundle):
    root,ref,v=ledger_bundle
    a.extract(ref,root/'extract',generator=generate)
    cr=a.file_ref(root/'extract/candidate.json');a.review(ref,cr,root/'review',generator=generate)
    report=a.publish(ref,cr,a.file_ref(root/'review/review.json'),root/'published')
    audit=read_json(report['audit_ref']['path'])
    for view in audit['module_views']:
        assert [r['id'] for r in a.project(report['project_rules_ref'],view['module_id'])['rules']]==view['rule_ids']


def test_workflow_selects_repaired_candidate_explicitly(ledger_bundle,monkeypatch):
    from research_pipeline.workflow_runtime import execute_builtin
    root,ref,v=ledger_bundle
    calls=[]
    def model(req,**kw):
        calls.append(req['payload']['stage'])
        if calls.count('project_rules_review')==1 and req['payload']['stage']=='project_rules_review':
            return rejection(v,read_json(root/'extract/candidate.json'))
        if req['payload']['stage']=='project_rules_repair':
            return patch_response(req,read_json(root/'extract/candidate.json'))
        return generate(req,**kw)
    monkeypatch.setattr(a,'codex_generate',model)
    a.extract(ref,root/'extract')
    execute_builtin({'kind':'project_rules_review','options':{'input_ref':ref},
        'inputs':[ref['path'],str(root/'extract/candidate.json')],'outputs':[str(root/'review')]})
    execute_builtin({'kind':'project_rules_publish','options':{'input_ref':ref},
        'inputs':[ref['path'],str(root/'extract/candidate.json'),str(root/'review/review.json')],'outputs':[str(root/'published')]})
    report=read_json(root/'published/report.json');pack=a.verify_published(report['project_rules_ref'])
    assert pack['candidate_ref']['path']==str((root/'review/repair/candidate.json').resolve())
    assert calls==['project_rules_inventory','project_rules_consolidate','project_rules_review','project_rules_repair','project_rules_review']


def test_ui_policy_is_the_runtime_policy():
    from research_pipeline.ui_rule_files import rule_sources
    sources={r[0]:r[4] for r in rule_sources()}
    assert read_json(sources['prc-policy'])==a.compact_rules.POLICY
    assert read_json(sources['prc-workflow'])==a.compact_rules.WORKFLOW_REFERENCE


@pytest.fixture
def source_route_bundle(ledger_bundle):
    root,_,v=ledger_bundle;v=copy.deepcopy(v)
    policy=a.compact_rules.SUPPORTED_POLICIES['1.5.0']
    v.update(extraction_policy=copy.deepcopy(policy),policy_sha256=digest(policy),processing_rules=copy.deepcopy(policy['rules']))
    return root,a.file_ref(write_json(root/'source_route_input.json',v)),v


def generate_source_route(req,**kw):
    result=generate(req,**kw)
    if req['payload']['stage']=='project_rules_inventory':
        for i,row in enumerate(result['segments']):
            for o in row['obligations']:o['operations']=['prediction_release'] if i==0 else ['data_preparation']
    if req['payload']['stage']=='project_rules_consolidate':
        for r in result['rules']:r.pop('operations')
    return result


def source_candidate(v):
    inv=generate_source_route(p.inventory_request(v));draft=generate_source_route(p.consolidation_request(v,inv))
    return p.materialize(v,inv,draft)


def test_source_routing_publication_and_direct_tag_tamper(source_route_bundle):
    root,ref,v=source_route_bundle
    c=a.extract(ref,root/'extract',generator=generate_source_route)
    cr=a.file_ref(root/'extract/candidate.json');a.review(ref,cr,root/'review',generator=generate_source_route)
    report=a.publish(ref,cr,a.file_ref(root/'review/review.json'),root/'published');a.verify_published(report['project_rules_ref'])
    assert 'operations' not in c['consolidation']['rules'][0]
    assert 'operations' in c['inventory']['segments'][0]['obligations'][0]
    c['items'][0]['used_in']=['pta']
    with pytest.raises(ValueError):p.validate_candidate(c,v)


def test_different_grouping_cannot_contaminate_source_routes(source_route_bundle):
    _,_,v=source_route_bundle;c=source_candidate(v)
    draft=copy.deepcopy(c['consolidation'])
    draft['rules'][0]['obligation_ids']+=draft['rules'][1]['obligation_ids'];draft['rules'].pop()
    with pytest.raises(ValueError,match='different frozen routes'):p.validate_draft(draft,v,c['inventory'])
    # Two obligations with the same footprint can be represented together or
    # separately; their delivery cannot change when the grouping changes.
    inv=copy.deepcopy(c['inventory'])
    inv['segments'][1]['obligations'][0]['operations']=inv['segments'][0]['obligations'][0]['operations']
    draft['request_sha256']=p.consolidation_request(v,inv)['request_sha256']
    p.validate_draft(draft,v,inv)
    grouped=p.materialize(v,inv,draft)
    separate=copy.deepcopy(c['consolidation']);separate['request_sha256']=draft['request_sha256']
    p.validate_draft(separate,v,inv);ungrouped=p.materialize(v,inv,separate)
    assert all(r['used_in']==grouped['items'][0]['used_in'] for r in ungrouped['items'])


def test_source_route_patch_is_local_and_re_reviewed(source_route_bundle):
    root,ref,v=source_route_bundle;c=source_candidate(v);review=rejection(v,c)
    cr=a.file_ref(write_json(root/'before.json',c));rr=a.file_ref(write_json(root/'review.json',review))
    def patch(req,**_):
        result=patch_response(req,c)
        result['route_updates']=[{'obligation_id':c['consolidation']['rules'][1]['obligation_ids'][0],'operations':['preparation_source_use']}]
        return result
    fixed=p.repair(ref,cr,rr,root/'repair',generator=patch)
    assert fixed['items'][0]==c['items'][0]
    assert fixed['items'][1]['used_in']==['prepare']
    a.review(ref,a.file_ref(root/'repair/candidate.json'),root/'fresh_review',generator=generate_source_route)
    report=a.publish(ref,a.file_ref(root/'repair/candidate.json'),a.file_ref(root/'fresh_review/review.json'),root/'published')
    a.verify_published(report['project_rules_ref'])


def test_unresolved_source_classification_cannot_hide_in_exclusion(source_route_bundle):
    _,_,v=source_route_bundle;c=source_candidate(v)
    c['inventory']['segments'][1]['obligations'][0]['operations']=['UNRESOLVED']
    removed=c['consolidation']['rules'].pop()
    c['consolidation']['excluded']=[{'obligation_id':removed['obligation_ids'][0],'reason':'No mapped consumer'}]
    c['consolidation']['request_sha256']=p.consolidation_request(v,c['inventory'])['request_sha256']
    c=p.materialize(v,c['inventory'],c['consolidation']);p.validate_candidate(c,v)
    req=p.review_request(v,c)
    with pytest.raises(ValueError):p.validate_review(generate(req),req,c,v)


def test_diagnostic_branch_requires_real_bound_feedback_and_cannot_recurse(ledger_bundle):
    root,ref,v=ledger_bundle;c=candidate(v);r=rejection(v,c)
    cr=a.file_ref(write_json(root/'before.json',c));rr=a.file_ref(write_json(root/'before_review.json',r))
    first=p.repair(ref,cr,rr,root/'first',generator=lambda req,**_:patch_response(req,c))
    first_ref=a.file_ref(root/'first/candidate.json')
    final_review=a.file_ref(write_json(root/'first_review.json',rejection(v,first)))
    diagnostics=[{'candidate_ref':first_ref,'review_ref':final_review}]
    revised=p.repair(ref,cr,rr,root/'branch',generator=lambda req,**_:patch_response(req,c),diagnostic_reviews=diagnostics)
    assert revised['lineage']['diagnostic_reviews']==diagnostics
    p.validate_candidate(revised,v)
    branch_ref=a.file_ref(root/'branch/candidate.json')
    branch_review=a.file_ref(write_json(root/'branch_review.json',rejection(v,revised)))
    with pytest.raises(ValueError,match='recursive branch'):
        p.repair_request(v,c,r,[{'candidate_ref':branch_ref,'review_ref':branch_review}])
    other=copy.deepcopy(c);other['consolidation']['rules'][0]['text']+=' Different scope.'
    other=p.materialize(v,other['inventory'],other['consolidation'])
    with pytest.raises(ValueError,match='another original candidate'):p.repair_request(v,other,rejection(v,other),diagnostics)


@pytest.mark.parametrize('fix_retry',[True,False])
def test_cross_route_patch_has_one_bounded_contract_retry(source_route_bundle,fix_retry):
    root,ref,v=source_route_bundle;c=source_candidate(v);r=rejection(v,c)
    r['repair_targets'][0]['rule_ids']=['R001','R002']
    cr=a.file_ref(write_json(root/'before.json',c));rr=a.file_ref(write_json(root/'before_review.json',r));calls=[]
    def model(req,**_):
        calls.append(req)
        rules=copy.deepcopy(c['consolidation']['rules']);removed=[]
        if len(calls)==1 or not fix_retry:
            rules[0]['obligation_ids']+=rules[1]['obligation_ids'];rules.pop();removed=['R002']
        return {'request_sha256':req['request_sha256'],'segments':[],'rules':rules,'removed_rule_ids':removed,'excluded':[],'route_updates':[]}
    if fix_retry:
        revised=p.repair(ref,cr,rr,root/'repair',generator=model)
        p.validate_candidate(revised,v)
        assert revised['items']==c['items']
        assert 'contract_correction' in revised['lineage']
        assert (root/'repair/stopped.json').exists()
        assert (root/'repair/contract_correction/patch.json').exists()
    else:
        with pytest.raises(ValueError,match='different frozen routes'):p.repair(ref,cr,rr,root/'repair',generator=model)
        assert not (root/'repair/candidate.json').exists()
    assert len(calls)==2
    assert calls[0]['payload']['allowed_rule_ids']==calls[1]['payload']['allowed_rule_ids']
    assert 'contract_correction' in calls[1]['payload']
