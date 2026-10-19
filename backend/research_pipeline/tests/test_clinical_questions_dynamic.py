"""Different reviewed proposals must not inherit the PMB example's answers."""
import copy
from research_pipeline.clinical_questions import derive_questions,index_scope
from research_pipeline.clinical_dispatch import task_branch,build,route_dataset
from research_pipeline.common import read_json,write_json
from research_pipeline.adequacy import file_ref
from test_clinical_dispatch import snapshot,approval,node


def proposal(drug,organism,window,basis,indices,binding,safety):
    return {'objective':f'Evaluate {drug} exposure-response against {organism}.',
        'study':{'drug':drug,'population':f'{drug} protocol adult population','regimen':'Protocol-specific IV infusion',
            'system':f'{organism} thigh infection', 'measurements':f'{basis} plasma exposure; {window} bacterial response.',
            'methods':f'Compare {indices}. {binding} Safety endpoint: {safety}. Translation uses the prespecified animal PK model.'},
        'rules':[f'Endpoint window: {window}. Do not pool infection sites.',f'Model acceptance: {drug} protocol criteria.']}


def assessment(window,basis):
    return {'tasks':[{'id':'p','question':'Fit animal PK components.','estimand':'clearance','endpoint':'plasma PK',
        'endpoint_window':'0-72 h','units':'mg/L','exposure_basis':basis},
        {'id':'i','question':'Compare exposure-response indices.','estimand':'response slope','endpoint':'Change in log10 CFU',
        'endpoint_window':window,'units':'log10 CFU','exposure_basis':basis}], 'requirements':[]}


def assert_exact_evidence(result,main,assess):
    for item in result['evidence_catalog'].values():
        value=main if item['source']=='effective_main.json' else assess
        for key in item['path'].strip('/').split('/'):
            value=value[int(key)] if isinstance(value,list) else value[key]
        assert item['quote'] in value


def test_two_proposals_change_answers_windows_basis_policy_and_indices():
    a=proposal('PMB','K. pneumoniae','0-24 h','free','fAUC/MIC, fCmax/MIC and fT>MIC',
        'Human protein-binding data are reserved for final validation after the model freeze.', 'renal injury')
    b=proposal('Cefepime','P. aeruginosa','0-48 h','total','AUC/MIC and Cmax/MIC',
        'Human protein-binding data may inform the prespecified translation before fitting.', 'neurological adverse events')
    aa=assessment('0-24 h','free');bb=assessment('0-48 h','total')
    x=derive_questions(a,aa,task_branch);y=derive_questions(b,bb,task_branch)
    for key in ['decision_question','endpoint_window','target_population','exposure_definition',
                'mic_and_binding_source','safety_endpoints','pathogen_infection_site','decision_criteria']:
        assert x['values'][key]!=y['values'][key],key
    assert '0-48 h' in y['values']['endpoint_window'] and '0-24 h' not in y['values']['endpoint_window']
    assert 'before fitting' in y['values']['mic_and_binding_source']
    assert 'reserved for final validation' not in y['values']['mic_and_binding_source']
    assert 'neurological adverse events' in y['values']['safety_endpoints']
    assert 'K. pneumoniae' not in str(y) and 'PMB' not in str(y)
    assert index_scope(a)['candidates']==['fAUC/MIC','fCmax/MIC','fT>MIC']
    assert index_scope(b)['candidates']==['AUC/MIC','Cmax/MIC']
    assert_exact_evidence(x,a,aa);assert_exact_evidence(y,b,bb)


def test_absence_is_unknown_not_a_default_binding_policy_or_endpoint():
    result=derive_questions({'objective':'A new research question','study':{},'rules':[]},{'tasks':[]},task_branch)
    for field in ['endpoint_window','mic_and_binding_source','safety_endpoints','target_population']:
        assert result['values'][field].startswith('UNKNOWN:')
        assert result['field_evidence'][field]['definition_evidence']==[]
    assert 'final validation' not in str(result) and 'K. pneumoniae' not in str(result)
    assert index_scope({'study':{},'rules':[]})['candidates']==[]


def test_branch_projection_keeps_task_windows_scoped_and_original_pointers():
    main={'objective':'Scoped task comparison','study':{}}
    assess=assessment('0-48 h','total')
    result=derive_questions(main,assess,task_branch,task_ids={'i'})
    assert '0-48 h' in result['values']['endpoint_window']
    assert '0-72 h' not in result['values']['endpoint_window']
    assert all('/tasks/0/' not in e['path'] for e in result['evidence_catalog'].values())
    assert_exact_evidence(result,main,assess)


def test_index_negation_is_retained_and_not_turned_into_a_candidate():
    main={'study':{'methods':'Compare AUC/MIC and Cmax/MIC. Do not use fAUC/MIC or fCmax/MIC.'}}
    scope=index_scope(main)
    assert scope['candidates']==['AUC/MIC','Cmax/MIC']
    assert scope['excluded_or_ambiguous']==['fAUC/MIC','fCmax/MIC']
    result=derive_questions(main,{'tasks':[]},task_branch)
    assert 'Do not use fAUC/MIC or fCmax/MIC.' in result['values']['exposure_definition']


def test_other_pathogen_routing_does_not_retain_klebsiella_filter():
    main={'study':{'methods':'Study P. aeruginosa thigh infection.'}}
    d={'id':'x','role':'PD_OBSERVATIONS','metadata':{'permission':'DEVELOPMENT_CANDIDATE',
        'source_table':{'title':'Pseudomonas aeruginosa thigh'}}}
    assert route_dataset(d,main)[0]==['index']
    d['metadata']['source_table']['title']='Klebsiella pneumoniae thigh'
    assert route_dataset(d,main)[0]==[]


def test_branch_contracts_get_new_project_answers_without_unused_tasks(snapshot,tmp_path):
    value=read_json(snapshot['path'])
    main={'objective':'Animal pharmacokinetics of compound Z','study':{'drug':'Compound Z','methods':'Fit animal PK only.'},'rules':[]}
    assess={'tasks':[{'id':'only_pk','question':'Fit animal PK components.','endpoint':'concentration','estimand':'CL'}], 'requirements':[]}
    refs=[{'name':name,**file_ref(write_json(tmp_path/name,data))} for name,data in [('new_main.json',main),('new_assessment.json',assess)]]
    refs[0]['name']='effective_main.json';refs[1]['name']='assessment.json'
    value['nodes']['context']=node(refs[:1]);value['nodes']['adequacy']=node(refs)
    ref=file_ref(write_json(tmp_path/'new_snapshot.json',value));build(ref,tmp_path/'new_dispatch')
    pk=read_json(tmp_path/'new_dispatch/pk_context.json');index=read_json(tmp_path/'new_dispatch/index_context.json')
    assert pk['drug']=='Compound Z' and pk['work_items']==['only_pk: Fit animal PK components. Estimand: CL']
    assert index['tasks']==[] and index['data_files']==[] and index['candidate_indices']==[]
    assert index['expected_outputs']==[]
    assert 'Emax' not in str(pk) and 'PTA' not in str(pk)
