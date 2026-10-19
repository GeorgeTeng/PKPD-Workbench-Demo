import copy
from pathlib import Path
from research_pipeline.common import BACKEND, PROJECT,read_json,write_json

root=BACKEND/'research_pipeline/research_pipeline/schemas'
schema=read_json(root/'request.schema.json')
step=schema['properties']['steps']['items']['properties']
if 'data_preparation' not in step['module']['enum']: step['module']['enum'].append('data_preparation')
for key in ['preparation_attachment','review_attachment','prepared_step','prepared_dataset']:
    step['input']['properties'][key]={'$ref':'#/$defs/id'}
write_json(root/'request.schema.json',schema)
output=read_json(root/'module-output.schema.json')
output['properties']['module']['enum']=step['module']['enum']
output['properties']['status']['enum']=['SUCCEEDED','FAILED','SKIPPED','WAITING_FOR_REVIEW','BLOCKED']
write_json(root/'module-output.schema.json',output)
identifier={'type':'string','pattern':'^[A-Za-z0-9][A-Za-z0-9_-]{0,59}$'}
prep={
 '$schema':'https://json-schema.org/draft/2020-12/schema','title':'Data preparation plan 1.0','type':'object','additionalProperties':False,
 'required':['schema_version','ruleset_version','evidence_attachment','evidence_sha256','study_plan','datasets'],
 'properties':{
  'schema_version':{'const':'1.0'},'ruleset_version':{'type':'string'},'evidence_attachment':identifier,
  'evidence_sha256':{'type':'string','pattern':'^[a-f0-9]{64}$'},
  'study_plan':{'type':'object','required':['purpose'],'properties':{'purpose':{'enum':['within_species_fit','human_translation','NOT_FOUND']},
    'target':{'type':'object'},'scaling':{'type':'object'},'human_pk_available':{'type':['boolean','string']}},'additionalProperties':False},
  'precision_plans':{'type':'array','maxItems':50,'items':{'type':'object'}},
  'datasets':{'type':'array','minItems':1,'maxItems':30,'items':{'type':'object','additionalProperties':False,
   'required':['id','kind','data_attachment','metadata','analysis_options'],
   'properties':{'id':identifier,'kind':{'enum':['pk','index']},'data_attachment':identifier,
      'metadata':{'type':'object'},'analysis_options':copy.deepcopy(step['options']),
      'table':copy.deepcopy(step['input']['properties']['table'])}}}
 }}
write_json(root/'data-preparation.schema.json',prep)
review={
 '$schema':'https://json-schema.org/draft/2020-12/schema','title':'Human data review decision 1.0','type':'object','additionalProperties':False,
 'required':['schema_version','assessment_sha256','decision','reviewer','confirm_rules','scope','selected_datasets','acknowledged_issues','rationale'],
 'properties':{'schema_version':{'const':'1.0'},'assessment_sha256':{'type':'string','pattern':'^[a-f0-9]{64}$'},
    'decision':{'enum':['APPROVE','REQUEST_CHANGES','REJECT']},'reviewer':{'type':'string','minLength':1},'confirm_rules':{'type':'boolean'},
    'scope':{'const':'exploratory_fit_only'},'selected_datasets':{'type':'array','uniqueItems':True,'items':{'type':'string'}},
    'acknowledged_issues':{'type':'array','uniqueItems':True,'items':{'type':'string'}},'rationale':{'type':'string','minLength':1},
    'review_id':{'type':'string'},'reviewed_at':{'type':'string'},'source_run':{'type':'string'},'source_step':{'type':'string'},
    'identity_verification':{'type':'string'}}}
write_json(root/'data-review.schema.json',review)
print('Updated four schemas.')
