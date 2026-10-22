"""Explicit evidence-only patch of an immutable rejected document label; no scientific record rewriting."""
import copy
import json
from pathlib import Path
from ctxcomp.io import digest
from ctxcomp.schemas import S,enum,obj,validate_schema
from . import data_agents as d
from .common import read_json,write_json,PipelineError

VERSION='EVIDENCE_APPEND_ONLY_PATCH_1.0'


def fail(message):
    raise PipelineError('DATA_CITATION_PATCH_INVALID',message)


def schema(payload):
    c=payload['contract_correction']['response_constraint']
    if c['version']!=VERSION:fail('Unknown citation patch contract')
    return obj(request_sha256=S,evidence=obj(source=enum(*c['allowed_added_sources']),quote=S))


def derive(patch,payload):
    """The model supplies one citation only; every other candidate field is locked, including findings."""
    validate_schema(patch,schema(payload))
    c=payload['contract_correction'];constraint=c['response_constraint']
    for key in ('failed_request_ref','failed_response_ref','manifest_ref'):d.check_ref(c[key])
    fixed=read_json(c['failed_response_ref']['path'])
    if fixed!=c['prior_rejected_response']:fail('Locked response differs from its original source artifact')
    old_request=read_json(c['failed_request_ref']['path'])
    manifest=read_json(c['manifest_ref']['path'])
    matches=[x for x in manifest['corrections'] if (x['item_id'],x['page'])==(payload['item_id'],payload['page'])]
    if (len(matches)!=1 or matches[0]['response_constraint']!=constraint
            or matches[0]['failed_request_ref']!=c['failed_request_ref']
            or matches[0]['failed_response_ref']!=c['failed_response_ref']
            or matches[0]['source_units_sha256']!=digest(payload['source_units'])
            or manifest['source_main_ref']!=payload['test_scope']['source_main_ref']):
        fail('Patch constraint or source binding differs from the authorized manifest')
    for key in ('source_main_ref','project_rules_ref','first_part_receipt_ref','first_part_review_ref'):
        if key in payload['test_scope']:d.check_ref(payload['test_scope'][key])
    if (fixed['request_sha256']!=old_request['request_sha256']
            or digest(old_request['payload'])!=old_request['request_sha256']
            or any(payload.get(k)!=old_request['payload'].get(k) for k in ('test_scope','requirements',
                'project_rules','context_sources','method_knowledge','item_id','page','pages','source_units'))):
        fail('Original request, response or source units changed')
    li=constraint['label_index'];vi=constraint['stated_value_index']
    if li<0 or vi<0:fail('Patch target must be an exact nonnegative index')
    try:label=fixed['labels'][li];value=label['stated_values'][vi]
    except (IndexError,KeyError,TypeError):fail('Unknown fixed stated-value target')
    descriptor=json.loads(payload['source_units'].get(payload['item_id'],'{}'))
    if label['item_id']!=payload['item_id'] or descriptor.get('kind')!='document':
        fail('This narrow patch supports a fixed document label only')
    evidence=patch['evidence'];source=payload['source_units'].get(evidence['source'])
    if not source or not evidence['quote'].strip() or evidence['quote'] not in source:
        fail('Added citation is not an exact quote in the unchanged source page')
    if evidence in value['evidence']:fail('Patch must add one new citation, not duplicate an existing one')
    result=copy.deepcopy(fixed);result['request_sha256']=patch['request_sha256']
    result['labels'][li]['stated_values'][vi]['evidence'].append(copy.deepcopy(evidence))
    validate_schema(result,d.LABEL_RESPONSE)
    return result


def invoke(original_invoke,run,stage,payload,**options):
    """Cache raw patches only after derivation and every original label host check succeeds."""
    if stage!='DC-label' or not options.get('check'):fail('Citation patch requires the complete original label checker')
    old_check=options['check'];checked={}
    def verify(patch):
        result=derive(patch,payload)
        verdict=old_check(result)
        checked[patch['request_sha256']]=result
        return verdict
    options={**options,'check':verify}
    patch=original_invoke(run,stage,payload,schema(payload),**options)
    result=checked[patch['request_sha256']]
    directory=Path(run)/'data_agents/citation_patches'/patch['request_sha256']
    matching=[p for p in (Path(run)/'data_agents/audit'/stage).glob('*/request.json')
              if read_json(p)['request_sha256']==patch['request_sha256']]
    if not matching:fail('Missing actual patch request audit')
    request_ref=d.file_ref(sorted(matching)[0]);raw_ref=d.file_ref(write_json(directory/'raw_patch.json',patch))
    derived_ref=d.file_ref(write_json(directory/'derived_response.json',result))
    c=payload['contract_correction']
    proof={'version':VERSION,'attribution':'HOST_APPLIED_MODEL_CITATION_PATCH','request_ref':request_ref,
        'raw_patch_ref':raw_ref,'derived_response_ref':derived_ref,'original_request_ref':c['failed_request_ref'],
        'original_response_ref':c['failed_response_ref'],'correction_manifest_ref':c['manifest_ref'],
        'operation':c['response_constraint'],'original_host_checks_passed':True,
        'scientific_approval':False,'all_other_records_locked':True}
    write_json(directory/'proof.json',proof);verify_proof(directory/'proof.json')
    return result


def verify_proof(path):
    proof=read_json(path)
    if proof['version']!=VERSION or proof['attribution']!='HOST_APPLIED_MODEL_CITATION_PATCH':fail('Invalid derivation attribution')
    for key in ('request_ref','raw_patch_ref','derived_response_ref','original_request_ref','original_response_ref','correction_manifest_ref'):
        d.check_ref(proof[key])
    request=read_json(proof['request_ref']['path']);payload=request['payload'];patch=read_json(proof['raw_patch_ref']['path'])
    if request['request_sha256']!=digest(payload) or patch['request_sha256']!=request['request_sha256']:
        fail('Patch does not belong to its exact real request')
    c=payload['contract_correction']
    if (c['failed_request_ref']!=proof['original_request_ref'] or c['failed_response_ref']!=proof['original_response_ref']
            or c['manifest_ref']!=proof['correction_manifest_ref'] or c['response_constraint']!=proof['operation']):
        fail('Patch lineage changed')
    if derive(patch,payload)!=read_json(proof['derived_response_ref']['path']):fail('Derived response cannot be replayed')
    return {'status':'VALID_DERIVATION','scientific_approval':False}
