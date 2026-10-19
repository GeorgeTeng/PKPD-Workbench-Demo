"""Register existing reviewed-scope executions; never alter fit outputs or acceptance."""
from research_pipeline.common import PROJECT,read_json,write_json
from research_pipeline.adequacy import check_ref
from research_pipeline.animal_pk_summary import validate_summary_request
from research_pipeline.animal_pk_individual import validate_request

session='flow_f75c012fdd294693847d00f393ff3271'
base=PROJECT/'outputs/Workbench_Preview_v22'
context=read_json(base/'runs/animal_pk_controls'/session/'active.json')
plan=read_json(context['plan_ref']['path']);ref=plan['context_ref'];check_ref(ref)
items=[('MOUSE_PK_20260923_MEANS_03','MOUSE_PK_20260923_MEANS_03','mouse','animal_pk_summary','summary_request',
    'Mouse PK · Exploratory mean curves','Three separate study groups · 1C / 2C · additive / lognormal errors · no animal random effects'),
    ('RAT_PK_REVIEW_20260923','RAT_PK_20260923_INDIVIDUAL_02','rat','animal_pk_individual','individual_request',
    'Rat PK · Individual NLME','11 rats · 102 quantified observations · 1C / 2C · three residual models · rerun uses the reviewed nlminb configurations')]
for publication,source,species,mode,key,title,description in items:
    spec=read_json(base/'state/workbench_jobs'/source/'request.json')
    request=spec[key];validate=validate_summary_request if species=='mouse' else validate_request
    master=validate(request)
    for child in master['groups' if species=='mouse' else 'candidates']:validate(child)
    assert any(r['sha256']==ref['sha256'] for r in master['source_refs'])
    path=base/'runs/animal_pk_agent_runs'/session/(publication+'.json')
    record=read_json(path)
    record.update(interface='species_analysis',species=species,title=title,description=description,
        context_ref=ref,rerun={'mode':mode,'request_ref':request},
        source_job_ids=[source] if species=='mouse' else ['RAT_PK_20260923_INDIVIDUAL_01','RAT_PK_20260923_INDIVIDUAL_02'])
    write_json(path,record)
    print(publication,species,'connected; scientific acceptance unchanged')
