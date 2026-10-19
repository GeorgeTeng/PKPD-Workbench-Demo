import copy,json
from pathlib import Path
import pytest
from research_pipeline import data_source_first_review_repair as r

BASE=Path(__file__).resolve().parents[3]/'outputs/Codex_Agent_Run_20261009'


@pytest.fixture
def case():
    c=r.read_json(BASE/'fixes/source-first-data/review_repair_contracts/REVIEW_002.json')
    full,_,_=r._load(c)
    return c,full,r.payload(c),r.read_json(c['main_ref']['path'])


@pytest.mark.parametrize('index',[46,12,44,45])
def test_unique_rule_leaf_maps_to_verbatim_canonical_rule_field(case,index):
    _,full,p,main=case;audit=[];selector={'source':f'main:/rules/{index}/text','field':'text'}
    e=r._span(selector,p,full,main=main,audit=audit)
    assert e['source']=='rule:'+main['rules'][index]['id']
    assert e['quote'] in full['evidence_catalog'][e['source']]['content']
    assert audit[0]['original_selector']==selector
    assert audit[0]['operation']=='CANONICAL_RULE_LEAF_SELECTOR_ALIAS'


@pytest.mark.parametrize('fault',['changed_main','duplicate_projection','wrong_context','changed_canonical','non_text_leaf'])
def test_alias_rejects_nonidentical_or_ambiguous_records(case,fault):
    _,full,p,main=case;selector={'source':'main:/rules/46/text','field':'text'}
    rule=next(x for x in p['project_rules'] if x['id']=='R047')
    if fault=='changed_main':main['rules'][46]['text']+=' modified'
    elif fault=='duplicate_projection':p['project_rules'].append(copy.deepcopy(rule))
    elif fault=='wrong_context':rule['context_path']='/rules/45'
    elif fault=='changed_canonical':
        value=json.loads(full['evidence_catalog']['rule:R047']['content']);value['text']+=' modified'
        full['evidence_catalog']['rule:R047']['content']=json.dumps(value)
    else:selector['source']='main:/rules/46'
    with pytest.raises(Exception):r._span(selector,p,full,main=main)


def test_alias_does_not_extend_requirement_allowed_scope(case):
    _,full,p,main=case;e=r._span({'source':'main:/rules/12/text','field':'text'},p,full,main=main)
    plan=next(x for x in full['criterion_plans'] if x['requirement_id']=='SFQ16')
    assert e['source']=='rule:R013' and e['source'] not in plan['allowed_source_ids']


def test_real_saved_raw_is_still_rejected_for_missing_required_operation(case):
    c,_,_,_=case
    a=r.read_json(BASE/'data_test_05_source_first/run/data_agents/audit/DC-review/14d785c1e5d14161a0605cabbab797f3/response.json')
    with pytest.raises(Exception,match='Only failed deferred citations'):r.derive(a,c)
