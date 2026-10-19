import copy
import pytest
from research_pipeline import data_source_first_organize_patch as p,data_source_first_organize as o,method_profiles as mp,data_agents as d
from research_pipeline.common import read_json,write_json


@pytest.fixture
def case(tmp_path):
    source={'main:/objective':'Assess source inputs','I:line1':'Source dose 2 mg','main:/rules/0/text':'Preserve source units'}
    knowledge=mp.planning_context();all_sources={**source,**mp.evidence_sources(knowledge)}
    payload={'context_sources':{'main:/objective':source['main:/objective']},'project_rules':[{'id':'R1'}],
        'source_units':{'I:line1':source['I:line1']},'data_profiles':[{'item_id':'I'}],
        'objective_source_ids':['main:/objective'],'method_knowledge':knowledge}
    payload['schema']=o.response_schema(['I'],['main:/objective'],['R1'])
    request={'payload':payload,'request_sha256':d.digest(payload)}
    old={'request_sha256':request['request_sha256'],
        'tasks':[{'id':'SFT1','objective':'Assess source inputs','destination':'pk','evidence':[{'source':'main:/objective','quote':'Assess source inputs'}]}],
        'requirements':[{'id':'SFQ1','task_id':'SFT1','description':'Preserve dose units','kind':'DATA','required_by':'BEFORE_QC',
            'fields':['dose'],'rule_ids':['R1'],'origin':'PROJECT_EXPLICIT','method_profile_ids':[],'conditions':[],
            'evidence':[{'source':'I:line1','quote':'Invented wording'}]}],
        'data_links':[{'item_id':'I','requirement_ids':['SFQ1'],'reason':'Potential source only','evidence':[{'source':'I:line1','quote':'Source dose 2 mg'}]}],
        'objective_coverage':[{'source':'main:/objective','requirement_ids':['SFQ1'],'reason':'Wrong adjacent task','evidence':[{'source':'main:/objective','quote':'Wrong text'}]}],
        'findings':[{'code':'COVERAGE','affected_id':'I','reason':'Bodies not supplied','needed_material':'Bodies','severity':'HUMAN_REVIEW','required_by':'BEFORE_QC'}]}
    refs={k:d.file_ref(write_json(tmp_path/(k+'.json'),v)) for k,v in
          [('original_request_ref',request),('original_response_ref',old),('main_ref',{}),('source_view_ref',{}),('source_catalog_ref',all_sources)]}
    contract={'version':p.VERSION,**refs,'fixed_candidate_sha256':d.digest(old),
        'span_replacements':[{'path':'/requirements/0/evidence/0','record':old['requirements'][0],'allowed_sources':['I:line1']}],
        'project_evidence_additions':[{'requirement_id':'SFQ1','record':old['requirements'][0],'allowed_sources':['main:/rules/0/text']}],
        'objective_replacements':[{'source':'main:/objective','record':old['objective_coverage'][0]}],
        'coverage_finding':{'index':0,'record':old['findings'][0]},'repair_sources':all_sources,
        'requirements_index':[{'id':'SFQ1','description':'Preserve dose units'}],'tasks':old['tasks'],
        'method_source_profiles':[],'method_knowledge':knowledge,'project_rules':[{'id':'R1','text':'Preserve source units'}],
        'actual_delivery':{'all_permitted_source_units_were_sent':True}}
    answer={'request_sha256':'new','span_replacements':[{'path':'/requirements/0/evidence/0','evidence':{'source':'I:line1','quote':'Source dose 2 mg'}}],
        'project_evidence_additions':[{'requirement_id':'SFQ1','evidence':{'source':'main:/rules/0/text','quote':'Preserve source units'}}],
        'objective_replacements':[{'source':'main:/objective','requirement_ids':['SFQ1'],'reason':'Source input objective retained','evidence':[{'source':'main:/objective','quote':'Assess source inputs'}]}],
        'coverage_finding':{'reason':'Sources delivered; semantic extraction completeness is not guaranteed','needed_material':'Independent source completeness review'},
        'method_feasibility':[{'task_id':'SFT1','status':'UNRESOLVED','approaches':[],'proposed_requirement_followups':[],
            'reason':'No method is approved by input delivery','evidence':[{'source':'main:/objective','quote':'Assess source inputs'}]}]}
    return tmp_path,contract,answer,old


def test_narrow_derivation_preserves_locked_science_links_findings_severity(case):
    _,c,a,old=case;new=p.derive(a,c)
    assert new['tasks']==old['tasks'] and new['data_links']==old['data_links']
    for before,after in zip(old['requirements'],new['requirements']):
        assert {k:v for k,v in before.items() if k!='evidence'}=={k:v for k,v in after.items() if k!='evidence'}
    assert new['findings'][0]['severity']==old['findings'][0]['severity']=='HUMAN_REVIEW'
    assert new['findings'][0]['required_by']==old['findings'][0]['required_by']
    assert new['method_feasibility']==a['method_feasibility']


@pytest.mark.parametrize('fault',['missing_span','duplicate_append','outside_source','bad_quote','changed_source_key',
    'unknown_need','rewrite_need','missing_method_task','method_no_project','library_only_approach','changed_parent'])
def test_off_scope_or_unsupported_patch_rejected(case,fault):
    _,c,a,_=case
    if fault=='missing_span':a['span_replacements']=[]
    elif fault=='duplicate_append':a['project_evidence_additions']*=2
    elif fault=='outside_source':a['span_replacements'][0]['evidence']={'source':'main:/objective','quote':'Assess source inputs'}
    elif fault=='bad_quote':a['span_replacements'][0]['evidence']['quote']='2 grams'
    elif fault=='changed_source_key':a['objective_replacements'][0]['source']='main:/unknown'
    elif fault=='unknown_need':a['objective_replacements'][0]['requirement_ids']=['SFQ2']
    elif fault=='rewrite_need':a['requirements']=[]
    elif fault=='missing_method_task':a['method_feasibility']=[]
    elif fault=='method_no_project':a['method_feasibility'][0]['evidence']=[{'source':'I:line1','quote':'Source dose 2 mg'}]
    elif fault=='library_only_approach':a['method_feasibility'][0]['approaches']=[{'description':'NCA','method_profile_ids':['MP002'],
        'applicability_conditions':['if supported'],'available_inputs':[],'missing_inputs':[],
        'evidence':[{'source':'method:MP002','quote':'MP002'}]}]
    else:
        path=c['original_response_ref']['path'];changed=read_json(path);changed['findings']=[];write_json(path,changed)
    with pytest.raises(Exception):p.derive(a,c)


def test_proof_replays_and_detects_derived_tamper(case):
    folder,c,a,_=case
    request=d.governed_request(p.payload(c));a['request_sha256']=request['request_sha256']
    derived=p.derive(a,c)
    refs={k:d.file_ref(write_json(folder/(k+'.json'),v)) for k,v in
          [('contract_ref',c),('patch_request_ref',request),('raw_patch_ref',a),('derived_response_ref',derived)]}
    proof=write_json(folder/'proof.json',{'version':p.VERSION,'attribution':'HOST_APPLIED_MODEL_TARGET_PATCH',**refs})
    assert p.verify_proof(proof)['status']=='VALID_TARGETED_DERIVATION'
    changed=copy.deepcopy(derived);changed['requirements'][0]['description']='Unsupported new obligation'
    write_json(refs['derived_response_ref']['path'],changed)
    with pytest.raises(Exception):p.verify_proof(proof)
