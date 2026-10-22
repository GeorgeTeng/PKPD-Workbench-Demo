"""Offline entry-contract tests. Synthetic approvals are fixtures, never user approvals."""
import copy
import pytest
from research_pipeline import main_data_handoff as h
from research_pipeline.adequacy import file_ref,check_ref
from research_pipeline.common import read_json,write_json,PipelineError
from research_pipeline.workflow_canvas import fingerprint


@pytest.fixture
def source(tmp_path):
    raw=tmp_path/'protected.txt';raw.write_text('HELD_OUT_CONTENT_MUST_NOT_BE_INTERPRETED',encoding='utf-8')
    snap=write_json(tmp_path/'snapshot.json',{'not_parsed_by_handoff':True})
    main={'version':'3.2','objective':'Synthetic source-bound handoff.',
        'study':dict(drug='Z',regimen='Partial rat IV regimen [SC001].',population='rat',system='plasma',measurements='PK',methods='not run'),
        'data':{'available':[],'required':[],'files':[dict(id='F001',name=raw.name,**file_ref(raw),kind='document',
            role='REFERENCE_ONLY',receivers=['validation'],read_status='BYTES_READ_ONLY',qc_status='NOT_RUN',fit_ready=False,
            snapshot_path=str(snap),snapshot_sha256=file_ref(snap)['sha256'])]},
        'rules':[],'rule_publication':'PROJECT_RULES_AGENT','checks':[],'uncertainties':[],
        'scientific_context':{'version':'2.0','items':[dict(id='SC001',statement='Rat study: IV; dose and interval not stated.',
            science=dict(role='FACT',evidence_status='SOURCE_REPORTED',method_refs=[],adoption_relations=[],relations=[]))],
            'potential_questions':[]}}
    path=write_json(tmp_path/'main.json',main)
    return path,main


def approval(tmp_path,main_ref,rules_ref=None,approved=True):
    artifacts=[{'name':'main.json',**main_ref}];signature=fingerprint(artifacts)
    node={'execution':'COMPLETED','artifacts':artifacts,'output_signature':signature,
          'review':{'decision':'APPROVE' if approved else 'REVISE','output_signature':signature},
          'langgraph_review':{'status':'APPROVED' if approved else 'INTERRUPTED'}}
    return write_json(tmp_path/'approval.json',{'context':node,**({'project_rules_ref':rules_ref} if rules_ref else {})})


def publication(tmp_path,source,monkeypatch):
    base,original=source;pack_path=write_json(tmp_path/'project_rules.json',{'status':'SYNTHETIC_TEST_PACK'})
    pack_ref=file_ref(pack_path);effective=copy.deepcopy(original);effective['project_rules_ref']=pack_ref
    main=write_json(tmp_path/'published/main.json',effective)
    pack={'base_main_ref':file_ref(base),'main_ref':file_ref(main)};calls=[]
    def verify(ref):
        check_ref(ref);assert ref==pack_ref;calls.append(ref);return copy.deepcopy(pack)
    # Isolate this adapter; full published-rule verification is an existing independently tested consumer.
    monkeypatch.setattr('research_pipeline.project_rule_agent.verify_published',verify)
    return main,pack_ref,pack,calls


def test_pending_main_reference_without_fake_approval_or_data_input(source,tmp_path):
    path,main=source;before=path.read_bytes();out=tmp_path/'handoff'
    result=h.prepare(path,out)
    assert result['status']=='PENDING'
    assert set(result['pending'])=={'PENDING_CONTEXT_APPROVAL','PENDING_PROJECT_RULES'}
    assert result['data_input_ref'] is None and result['approval_ref'] is None
    assert result['source_main_ref']==file_ref(path)
    assert not (out/'B1').exists() and not result['data_started']
    assert path.read_bytes()==before
    assert 'HELD_OUT_CONTENT' not in str(read_json(out/'handoff_receipt.json'))


def test_real_import_function_preserves_entire_effective_main_and_stops(source,tmp_path,monkeypatch):
    base,original=source;main,rule_ref,pack,calls=publication(tmp_path,source,monkeypatch)
    approved=approval(tmp_path,file_ref(base),rule_ref);before=base.read_bytes();effective_before=main.read_bytes()
    result=h.prepare(main,tmp_path/'handoff',approved)
    assert result['status']=='IMPORTED_AT_DATA_ENTRY' and result['pending']==[]
    assert len(calls)==2  # Adapter and the unchanged real import_reviewed_context both verify rules.
    assert read_json(result['data_input_ref']['path'])==read_json(main)
    assert read_json(result['data_input_ref']['path'])['scientific_context']==original['scientific_context']
    assert read_json(result['data_input_ref']['path'])['data']==original['data']
    assert result['consumer']=='research_pipeline.adequacy.import_reviewed_context'
    assert not result['data_started'] and not result['data_adequacy_assessed']
    assert base.read_bytes()==before and main.read_bytes()==effective_before
    provenance=read_json(result['provenance_ref']['path'])
    assert provenance['approval']==file_ref(approved) and provenance['project_rules_ref']==rule_ref
    assert not (tmp_path/'handoff/adequacy').exists()


def test_unapproved_context_stays_pending_even_with_published_rules(source,tmp_path,monkeypatch):
    base,_=source;main,rule_ref,pack,calls=publication(tmp_path,source,monkeypatch)
    approved=approval(tmp_path,file_ref(base),rule_ref,approved=False)
    result=h.prepare(main,tmp_path/'handoff',approved)
    assert result['pending']==['PENDING_CONTEXT_APPROVAL'] and result['data_input_ref'] is None
    assert len(calls)==1 and not (tmp_path/'handoff/B1').exists()


@pytest.mark.parametrize('target',['raw','snapshot','approval_signature','main_mismatch'])
def test_changed_or_mismatched_inputs_fail_closed(source,tmp_path,target):
    path,main=source;approved=None
    if target=='raw':__import__('pathlib').Path(main['data']['files'][0]['path']).write_text('changed')
    elif target=='snapshot':__import__('pathlib').Path(main['data']['files'][0]['snapshot_path']).write_text('{}')
    else:
        approved=approval(tmp_path,file_ref(path))
        if target=='approval_signature':
            value=read_json(approved);value['context']['output_signature']='wrong';write_json(approved,value)
        else:
            other=copy.deepcopy(main);other['study']['regimen']='Changed';path=write_json(tmp_path/'other.json',other)
    with pytest.raises(ValueError):h.prepare(path,tmp_path/'handoff',approved)
    assert not (tmp_path/'handoff/handoff_receipt.json').exists()


def test_supplied_unpublished_rules_are_rejected(source,tmp_path):
    path,main=source;rules=write_json(tmp_path/'unpublished.json',{'status':'DRAFT'})
    main['project_rules_ref']=file_ref(rules);write_json(path,main)
    with pytest.raises(PipelineError,match='clean independently reviewed'):h.prepare(path,tmp_path/'handoff')


def test_existing_receipt_is_not_overwritten(source,tmp_path):
    path,_=source;out=tmp_path/'handoff';h.prepare(path,out)
    before=(out/'handoff_receipt.json').read_bytes()
    with pytest.raises(PipelineError,match='new empty'):h.prepare(path,out)
    assert (out/'handoff_receipt.json').read_bytes()==before
