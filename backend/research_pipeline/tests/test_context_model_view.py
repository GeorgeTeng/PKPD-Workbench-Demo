import copy
from types import SimpleNamespace
import pytest
from ctxcomp import providers, context_dispatch, model_view
from ctxcomp.io import digest, canonical
from research_pipeline import context_model_view as cmv, context_linear as linear
from research_pipeline.common import read_json
from test_context_linear import request, coverage


def test_mechanical_fields_move_but_semantic_override_and_scope_survive():
    req=coverage(['RQ1'])
    p=req['payload']
    clause={'source_id':'CC002','clause_paths':['/actions/0'],
            'source_clause_hashes':{'/actions/0':'hash'},'effective_instruction':'Do not inspect attachments.',
            'authorization':'Exact authority with its conditions.'}
    p.update(effective_rule_binding={'source_pack_sha256':'packhash','source_rule_sha256':{'CC002':'hash'},
        'execution_overrides':[clause,copy.deepcopy(clause)],'precedence':'Overrides apply only to named clauses.',
        'source_scope':'Proposal only.','qualification':'No scientific qualification.'},
        effective_rule_binding_sha256='bindinghash',processing_rules_sha256='rulehash',
        host_input_checks={'source_units_sha256':'sourcehash','coverage_reference':'C:/audit/check.json',
                           'coverage_status':'NOT_ASSESSED','limitations':['Not proof of completeness.']},
        source_units=[{'id':'S1_U1','source_id':'S1','text':'dose not stated','text_sha256':'texthash'}])
    req['request_sha256']=digest(p)
    before=copy.deepcopy(req)
    visible,audit=cmv.project(req)
    out=visible['payload']; b=out['effective_rule_binding']
    assert req==before and visible['request_sha256']==req['request_sha256']
    assert 'effective_rule_binding_sha256' not in out and 'source_pack_sha256' not in b
    assert b['execution_overrides'][0]['effective_instruction']==clause['effective_instruction']
    assert b['execution_overrides'][0]['clause_paths']==clause['clause_paths']
    assert b['authorizations']==[clause['authorization']]
    for key in ('precedence','source_scope','qualification'):
        assert b[key]==p['effective_rule_binding'][key]
    for key in ('rules','schema','requirements','governance','instructions'):
        assert out[key]==p[key]
    assert out['source_units'][0]['text']=='dose not stated'
    assert out['source_units'][0]['id']=='S1_U1'
    assert out['host_input_checks']['coverage_status']=='NOT_ASSESSED'
    assert audit['host_only_fields']['payload/effective_rule_binding_sha256']=='bindinghash'
    assert audit['model_input_sha256']==digest(visible)


def test_no_recursive_stripping_of_scientific_relations_or_source_paths():
    req=coverage(['RQ1']);p=req['payload']
    p['source_units']={'S1':{'text':'2 mg/L','path':'Table A, row 3','relationship':'Study A MIC'}}
    p['requirements'][0]['rule_ids']=['R001']
    p['requirements'][0]['conditions']=['Only matched strain observations.']
    visible=cmv.view(req)['payload']
    assert visible['source_units']==p['source_units']
    assert visible['requirements']==p['requirements']


def test_each_stage_has_a_distinct_premise_without_universal_anonymization():
    config=read_json(cmv.PREMISES)
    assert set(linear.ROUTES).issubset(config['stages'])
    assert 'complete basis' in config['stages']['HUMAN_REVIEW_SUMMARY_ONLY']
    assert 'anonymous' not in config['common'].lower()
    assert 'training' not in config['stages']['context'].lower()


def test_actual_cli_stdin_equals_saved_projected_prompt(tmp_path,monkeypatch):
    req=request(); captured=[]
    def process(command,prompt,*args,**kwargs):
        captured.append(prompt)
        return SimpleNamespace(stdout='',stderr='',returncode=0)
    monkeypatch.setattr(providers,'monitored_run',process)
    def transport(req,**kwargs):
        return providers.cli_call(req,'codex',lambda root:['OFFLINE_STUB'],
            lambda root,result:{'request_sha256':req['request_sha256']},
            'gpt-6-sol',None,kwargs.get('diagnostics_dir'),None)
    monkeypatch.setattr(providers,'_codex_generate_raw',transport)
    with linear.LinearSession(tmp_path).activate():
        providers.codex_generate(req)
    saved=(tmp_path/'001_data_human_summary/model_prompt.txt').read_text(encoding='utf-8')
    assert captured==[saved]
    assert saved==providers.PROMPT+canonical(cmv.view(req))
    assert 'premise' in saved
    with pytest.raises(ValueError,match='requires a prepared'):
        context_dispatch.model_input(req)
