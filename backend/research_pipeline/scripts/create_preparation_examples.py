"""Create pending examples. This never creates or submits a human approval."""
import copy
import shutil
from research_pipeline.common import BACKEND, PROJECT, read_json, write_json, sha256
from research_pipeline.data_rules import RULESET_VERSION

examples=BACKEND/'research_pipeline/examples'
source=PROJECT.parent/'file-c-users-georg-downloads-s11095/cms_translational/species_selection_evidence.md'
copy_path=examples/'species_selection_evidence.snapshot.md'
shutil.copyfile(source,copy_path)
evidence_hash=sha256(copy_path)
old=read_json(examples/'parallel.request.json')
specs=[]
for oldstep,identifier,kind in zip(old['steps'],['pk','index'],['pk','index']):
    meta=copy.deepcopy(oldstep['metadata'])
    meta.update(analyte='SyntheticDrug',species='synthetic_animal',route='IV',matrix='plasma',
                formulation='synthetic solution',sampling_design='serial',parameter_definition='CL')
    if kind=='index': meta['concentration_basis']='free'
    specs.append({'id':identifier,'kind':kind,'data_attachment':oldstep['input']['data_attachment'],
                  'metadata':meta,'analysis_options':oldstep['options']})
config={'schema_version':'1.0','ruleset_version':RULESET_VERSION,'evidence_attachment':'evidence','evidence_sha256':evidence_hash,
        'study_plan':{'purpose':'within_species_fit','human_pk_available':False},'datasets':specs,'precision_plans':[]}
write_json(examples/'preparation_synthetic.plan.json',config)
request={'schema_version':'1.0','request_id':'preparation_synthetic_pending_001',
         'attachments':old['attachments']+[
             {'id':'plan','path':'preparation_synthetic.plan.json','role':'data_preparation_plan'},
             {'id':'evidence','path':'species_selection_evidence.snapshot.md','sha256':evidence_hash,'role':'decision_method_source'}],
         'steps':[{'id':'data','module':'data_preparation','input':{'preparation_attachment':'plan'},'options':{}},
                  {'id':'pk','module':'pk_longitudinal','input':{'prepared_step':'data','prepared_dataset':'pk__001'},'options':{}},
                  {'id':'index','module':'pkpd_index','input':{'prepared_step':'data','prepared_dataset':'index__001'},'options':{}}]}
write_json(examples/'preparation_parallel.request.json',request)

real=read_json(examples/'roberts_pmb.request.json')
meta=copy.deepcopy(real['steps'][0]['metadata'])
meta.update(analyte='polymyxin_b',formulation='NOT_FOUND',parameter_definition='CL_per_kg',sampling_design='serial')
config['datasets']=[{'id':'pk','kind':'pk','data_attachment':'source','table':{'adapter':'roberts_fig4b','drug':'PMB'},
                     'metadata':meta,'analysis_options':real['steps'][0]['options']}]
config['study_plan']={'purpose':'human_translation','human_pk_available':False,
 'target':{'drug':'polymyxin_b','analyte':'polymyxin_b','route':'IV','matrix':'plasma','concentration_basis':'total',
           'parameter_definition':'CL_per_kg','human_population':'NOT_FOUND','decision_quantity':'NOT_FOUND'},
 'scaling':{'mode':'unknown_exponent'}}
write_json(examples/'preparation_roberts.plan.json',config)
real['request_id']='preparation_roberts_pending_001'
real['attachments'] += [{'id':'plan','path':'preparation_roberts.plan.json'},
                       {'id':'evidence','path':'species_selection_evidence.snapshot.md','sha256':evidence_hash}]
real['steps']=[{'id':'data','module':'data_preparation','input':{'preparation_attachment':'plan'},'options':{}},
               {'id':'pk','module':'pk_longitudinal','input':{'prepared_step':'data','prepared_dataset':'pk__001'},'options':{}}]
write_json(examples/'preparation_roberts.request.json',real)
write_json(examples/'evidence_snapshot.provenance.json',{'source_path':str(source),'sha256':evidence_hash,
          'snapshot':copy_path.name,'read_status':'FULL_LOCAL_DOCUMENT_READ','interpretation':'Project method proposal, not a regulatory minimum.'})
print('Wrote pending synthetic parallel and observed PMB requests.')
