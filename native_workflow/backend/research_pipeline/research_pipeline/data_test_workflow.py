"""Isolated main-to-Data test with optional verified Project Rules; no approval or fitting."""
import argparse
import copy
import importlib.util
import json
import os
import time
from pathlib import Path
from uuid import uuid4
from ctxcomp.io import digest

from . import data_agents
from .adequacy import file_ref, check_ref
from .common import PipelineError, read_json, write_json, utcnow

SCOPE = 'UNAPPROVED_TEST_ONLY'
RULES_STATUS = 'Rules_NOT_PROVIDED_FOR_TEST'
RULES_PROVIDED = 'PROJECT_RULES_PROVIDED'
STAGES = ('inventory', 'define', 'access', 'label', 'assess')
OUTPUTS = {'inventory':'inventory.json','define':'definition.json','access':'requirements.json',
           'label':'labels.json','assess':'assessment/adequacy.json'}
DEPENDENCIES = {'inventory':[], 'define':[], 'access':['inventory','define'],
                'label':['inventory','access'], 'assess':['inventory','access','label']}


def fail(message):
    raise PipelineError('DATA_TEST_CONTRACT_INVALID',message)


def verified_rules(main_path,main,rules_mode):
    if rules_mode not in {'auto','none','published'}:fail('Unknown rules mode')
    reference=main.get('project_rules_ref')
    if rules_mode=='published' and not reference:fail('Published-rules test requires the actual project_rules_ref')
    if rules_mode=='none' and reference:fail('No-rules test does not silently discard an existing project_rules_ref')
    if main.get('version')=='4.0':
        if rules_mode=='none':fail('A complete first-part main cannot discard its embedded rules')
        return verified_final(main_path,main)['project_rules_ref']
    if not reference:return None
    from .project_rule_agent import verify_published
    pack=verify_published(reference)
    if pack['main_ref']!=file_ref(main_path) or read_json(pack['main_ref']['path'])!=main:
        fail('Test main must be the exact effective main bound to the published rules')
    return copy.deepcopy(reference)


def verified_final(main_path,main):
    from .first_part_handoff import verify_final_main
    result=verify_final_main(main_path)
    if result['main']!=main or result['rules']!=main['rules']:fail('Final main verification returned different content')
    return result


def embedded_projection(main,stages):
    """Same explicit stage projection as project(); full bodies come from verified main.rules."""
    if not main['rules']:
        return []
    if 'used_in' in main['rules'][0]:
        from .project_rule_compact import projection
        return list({r['id']:r for stage in stages for r in
            projection(main['rules'],stage,main['project_rules_ref'])['rules']}.values())
    from .project_rule_agent import DESTINATIONS
    aliases={'pk':{'animal_pk','human_pk'},'pk_longitudinal':{'animal_pk'},'pkpd_index':{'index'},
             'pk_translation':{'human_pk'}}
    result={}
    for stage in stages:
        requested=aliases.get(stage,{stage})
        if not requested<=set(DESTINATIONS):fail('Unknown rule destination')
        for index,rule in enumerate(main['rules']):
            if requested & set(rule['scope']['stages']):
                result[rule['id']]={**copy.deepcopy(rule),'text':rule['id']+': '+rule['text'],
                    'stages':rule['scope']['stages'],'context_path':'/rules/'+str(index),
                    'project_rules_ref':main['project_rules_ref'],'projection_version':'REVIEWED_SCOPE_V1'}
    return list(result.values())


def deduplicate_rule_sources(payload,embedded=None):
    """Delete only byte-equivalent duplicate rule strings; original host evidence sources stay intact."""
    sources=payload.get('context_sources',{});duplicates=set()
    for rule in payload.get('project_rules',[]):
        key='rule:'+rule['id']
        if key in sources and sources[key]==json.dumps(rule,ensure_ascii=False):duplicates.add(key)
    if embedded is not None:
        projected={r['id']:r for r in payload.get('project_rules',[])}
        for index,raw in enumerate(embedded):
            rule=projected.get(raw['id'])
            if not rule:continue
            if any(rule.get(k)!=(raw['id']+': '+v if k=='text' else v) for k,v in raw.items()):continue
            for path,value in data_agents.leaves(raw):
                key='main:/rules/'+str(index)+path
                if key in sources and sources[key]==str(value):duplicates.add(key)
    if not duplicates:return payload
    result=copy.deepcopy(payload)
    result['context_sources']={k:v for k,v in sources.items() if k not in duplicates}
    result['instructions']+=('\nEach rule:Rxxx evidence source is the complete project_rules record whose id is Rxxx, '
        'serialized as JSON (ensure_ascii=False, default separators). Its identical duplicate is omitted from '
        'context_sources. Cite that unchanged rule:Rxxx ID and an exact quote from the complete rule JSON. '
        'All rule fields, conditions, exceptions and provenance remain in project_rules. Any rule source '
        'still explicitly present in context_sources retains that exact evidence text. For embedded main.rules, '
        'duplicate main:/rules/index leaves are omitted only for the supplied complete rule. Cite rule:Rxxx '
        'for that rule; other main context and nonprojected rule sources remain available.')
    return result


def definition_correction(run,payload,schema,scope):
    """An explicit corrective call retains the rejected DR output as non-evidence, with exact input binding."""
    path=Path(run)/'definition_correction.json'
    if not path.exists():return payload
    correction=read_json(path)
    if correction['source_main_ref']!=scope['source_main_ref']:fail('Definition correction belongs to another main')
    for key in ('source_main_ref','failed_request_ref','failed_response_ref'):check_ref(correction[key])
    request=read_json(correction['failed_request_ref']['path']);response=read_json(correction['failed_response_ref']['path'])
    previous=request['payload']
    governed_base=data_agents.governed_request(copy.deepcopy(payload))['payload']
    if (request['request_sha256']!=digest(previous) or response['request_sha256']!=request['request_sha256']
            or previous.get('stage')!='DR' or previous.get('test_scope')!=scope
            or previous.get('schema')!=schema or 'definition_correction' in previous
            or any(previous.get(k)!=v for k,v in governed_base.items() if k!='instructions')
            or not previous.get('instructions','').startswith(governed_base.get('instructions',''))):
        fail('Definition correction source, rules, method context or request contract changed')
    ids=correction['affected_requirement_ids'];known={n['id'] for n in response['requirements']}
    if not ids or len(ids)!=len(set(ids)) or not set(ids)<=known:fail('Definition correction has unknown or duplicate target IDs')
    result=copy.deepcopy(payload)
    result['definition_correction']={'authority':'NON_EVIDENCE_TEST_CONTRACT_CORRECTION',
        'manifest_ref':file_ref(path),'failed_request_ref':correction['failed_request_ref'],
        'failed_response_ref':correction['failed_response_ref'],'affected_requirement_ids':ids,
        'instruction':correction['instruction'],'prior_rejected_response':response}
    result['instructions']+=('\nUse definition_correction only as attributed NON-EVIDENCE feedback on a rejected '
        'candidate. Recheck its affected requirements against the unchanged source context, full Project Rules '
        'and method knowledge. Preserve the other valid tasks and requirements. A METHOD_CANDIDATE needs '
        'both exact method evidence and exact main:/rule: evidence establishing project relevance, with '
        'explicit applicability conditions. A hypothetical endpoint in a method profile is not a requested '
        'project endpoint. If the source does not support applicability, omit that unsupported candidate and '
        'record a source-bounded finding; do not fabricate a quote, force a method into PROJECT_EXPLICIT, '
        'or invent a project obligation. Return the entire corrected contract with this NEW request hash. '
        'The prior response is rejected, not evidence or approval. '+correction['instruction'])
    return result


def label_correction(run,payload,scope):
    """An explicit, byte-bound correction applies only to its failed item/page, never source text."""
    path=Path(run)/'label_corrections.json'
    if not path.exists():return payload
    manifest=read_json(path)
    if manifest.get('source_main_ref')!=scope['source_main_ref']:fail('Label correction belongs to another main')
    check_ref(manifest['source_main_ref'])
    matches=[c for c in manifest['corrections'] if (c['item_id'],c['page'])==(payload['item_id'],payload['page'])]
    if not matches:return payload
    if len(matches)!=1:fail('Duplicate targeted label corrections')
    correction=matches[0]
    for key in ('failed_request_ref','failed_response_ref'):check_ref(correction[key])
    request=read_json(correction['failed_request_ref']['path']);response=read_json(correction['failed_response_ref']['path'])
    previous=request['payload']
    if (request['request_sha256']!=digest(previous) or response['request_sha256']!=request['request_sha256']
            or previous.get('test_scope')!=scope or previous['stage']!='DC-label'
            or (previous['item_id'],previous['page'])!=(payload['item_id'],payload['page'])
            or previous['source_units']!=payload['source_units']
            or correction['source_units_sha256']!=digest(payload['source_units'])
            or correction['page_sha256']!=digest({'item_id':payload['item_id'],'page':payload['page'],
                'pages':payload['pages'],'source_units':payload['source_units']})):
        fail('Label correction source/page/request binding changed')
    result=copy.deepcopy(payload)
    result['contract_correction']={'authority':'NON_EVIDENCE_TEST_CONTRACT_CORRECTION',
        'manifest_ref':file_ref(path),'failed_request_ref':correction['failed_request_ref'],
        'failed_response_ref':correction['failed_response_ref'],'instruction':correction['instruction']}
    if 'response_constraint' in correction:
        from .data_label_citation_patch import VERSION
        if correction['response_constraint']['version']!=VERSION:fail('Unknown label response constraint')
        result['contract_correction'].update(response_constraint=copy.deepcopy(correction['response_constraint']),
            prior_rejected_response=response)
        result['operation']='APPEND_ONE_CITATION_TO_LOCKED_LABEL'
    result['instructions']+='\nA contract_correction supplies attributed NON-EVIDENCE feedback for this page only. '
    result['instructions']+='Check it against the unchanged source_units. Preserve all scientific information and exact evidence; '
    result['instructions']+='do not treat it as source facts, permission, approval or a relaxed host check. '+correction['instruction']
    return result


def check_definition_correction(response,payload):
    correction=payload.get('definition_correction')
    if not correction:return response
    prior=correction['prior_rejected_response'];targets=set(correction['affected_requirement_ids'])
    previous={n['id']:n for n in prior['requirements']}
    if (response['tasks']!=prior['tasks']
            or [n for n in response['requirements'] if n['id'] not in targets]
            !=[n for n in prior['requirements'] if n['id'] not in targets]
            or any(n['id'] not in previous or n['origin']!=previous[n['id']]['origin'] for n in response['requirements'])
            or any(f not in response['findings'] for f in prior['findings'])):
        fail('Definition correction changed an unrelated task/requirement, dropped a finding or changed its authority')
    removed=targets-{n['id'] for n in response['requirements']}
    if any(not any(f.get('affected_id')==i for f in response['findings']) for i in removed):
        fail('An omitted unsupported candidate requires an explicit finding')
    return response


def private_agents(main_path,scope,requested_model=None):
    """A private module has its own globals; production data_agents is never monkeypatched."""
    spec=importlib.util.spec_from_file_location('research_pipeline._data_test_'+uuid4().hex,data_agents.__file__)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    source_main=read_json(main_path);original_invoke=module.invoke
    reuse_model=scope.get('model','gpt-6-sol');requested_model=requested_model or reuse_model
    mixed=requested_model!=reuse_model
    original_generate=module.codex_generate
    def guarded_generate(request,**options):
        if mixed and options.get('model')==reuse_model:
            fail('An unchanged page has no valid original-model cache; no paid replay is authorized')
        return original_generate(request,**options)
    if mixed:module.codex_generate=guarded_generate
    provided=scope.get('project_rules_status')==RULES_PROVIDED
    final=verified_final(main_path,source_main) if source_main.get('version')=='4.0' else None
    if final and (not provided or scope.get('first_part_receipt_ref')!=final['receipt_ref']
                  or scope.get('first_part_review_ref')!=final['review_ref']):
        fail('Test scope must bind the verified final-main receipt and review')
    def inline_rules(main,stages):
        check_ref(scope['source_main_ref'])
        check_ref(scope['first_part_receipt_ref']);check_ref(scope['first_part_review_ref'])
        if main!=source_main:fail('Embedded rules belong to a different main')
        return embedded_projection(main,stages)
    if provided and scope.get('project_rules_ref')!=source_main.get('project_rules_ref'):
        fail('Published test scope differs from the main rule reference')
    def no_project_rules(main,stages):
        check_ref(scope['source_main_ref'])
        if main!=source_main:fail('Test rule scope is bound to the complete original main only')
        return []
    def invoke(run,stage,payload,schema,**options):
        if stage not in {'DR','DR-access','DC-split','DC-label','DC-review'}:
            fail('Test adapter stops before preparation and handoff')
        if mixed and stage!='DC-label':fail('Mixed-model continuation is limited to the explicit label citation patch')
        check_ref(scope['source_main_ref'])
        if provided:check_ref(scope['project_rules_ref'])
        schema=copy.deepcopy(schema)
        if stage=='DR-access':
            registry={f['id']:f for f in source_main['data']['files']}
            payload=copy.deepcopy(payload)
            context_paths=[k.removeprefix('main:') for k in payload['context_sources'] if k.startswith('main:')]
            if not context_paths:fail('Access requires source main leaf paths')
            schema['properties']['access']['items']['properties']['context_paths']['items']={
                'type':'string','enum':context_paths}
            access_schema=schema['properties']['access']
            item_ids=[item['id'] for item in payload['inventory']]
            if item_ids:access_schema['items']['properties']['item_id']={'type':'string','enum':item_ids}
            else:access_schema['maxItems']=0
            requirement_ids=[item['id'] for item in payload['requirements']]
            requirements_schema=access_schema['items']['properties']['requirement_ids']
            if requirement_ids:requirements_schema['items']={'type':'string','enum':requirement_ids}
            else:requirements_schema['maxItems']=0
            for item in payload['inventory']:
                if item['file_id'] not in registry:fail('Access inventory references an unregistered file')
                registered=registry[item['file_id']]
                item['descriptor']['registered_file']={k:registered[k] for k in ('id','name','role') if k in registered}
            payload['instructions']=(payload.get('instructions','')+'\nEach descriptor.registered_file is exact '
                'metadata from the source main data.files registry, not inspected body evidence. Use it to '
                'identify which registered resource the source context describes. A file name does not '
                'establish scientific content, relevance or permission. Determine access from source-bound '
                'context restrictions; preserve PROTECTED and uncertain dispositions. No file body is added. '
                'Each context_paths element must be one exact LEAF JSON path from its schema enum, without '
                'the main: source-key prefix. For example use /objective, not main:/objective. A parent '
                'object such as /missing_information/items/0 is not a leaf: select its relevant explicit '
                'field/status/impact/clarification/needed_at leaf paths as applicable, preserving all '
                'needed restrictions. Do not drop a relevant restriction merely to avoid a path error.')
        if stage in {'DR','DR-access'}:
            collection='requirements' if stage=='DR' else 'access'
            rule_schema=schema['properties'][collection]['items']['properties']['rule_ids']
            ids=[rule['id'] for rule in payload['project_rules']] if provided else []
            if ids:rule_schema['items']={'type':'string','enum':ids}
            else:rule_schema['maxItems']=0
        if stage=='DC-label':
            payload={**payload,'instructions':payload.get('instructions','')+
                '\nFor each stated_values entry, quantity, value, unit and subject are literal copied fields, '
                'not semantic labels. A field the source does not name is NOT_FOUND. For example, "Female '
                'Swiss mice, 7 weeks" permits quantity=NOT_FOUND, value="7", unit="weeks", subject="Female '
                'Swiss mice"; it does not literally name quantity="age". Retain known values and units '
                'even when quantity is unstated. Never replace a known value with NOT_FOUND to avoid '
                'a failed citation check. Do not invent "number of doses", "dosing interval" or similar '
                'quantity wording unless written in the cited source. Copy unit word forms exactly: '
                '"ten-bin" contains "bin", not "bins"; "40-patient" contains "patient", not "patients". '
                'Do not normalize spelling, singular/plural, numbers or units. Every non-NOT_FOUND field '
                'and each qualifier must occur verbatim in this entry\'s exact cited source quote. Keep '
                'all source-stated values; do not remove entries to pass the contract. Explicit missing '
                'quantity/value remains unresolved text information, not an identified measured quantity '
                'for duplicate/conflict matching or proof of measurement coverage.'}
            payload=label_correction(run,payload,scope)
            if provided:
                payload['instructions']+=('\nDC004 column position comes from exactly one own lowest header cell. '
                    'Do not cite a neighbouring column header as an additional lowest header for this column. '
                    'Where a neighbouring unit column supplies the unit in its body, retain that exact body '
                    'evidence and relevant title/notes; keep the neighbouring header with its own column label. '
                    'If source meaning requires another header and cannot be expressed under this contract, '
                    'retain the information and report the ambiguity; do not delete facts or invent evidence to pass.')
        if provided:
            payload={**payload,'test_scope':copy.deepcopy(scope),
                'instructions':payload.get('instructions','')+'\nThis is UNAPPROVED_TEST_ONLY with '
                'PROJECT_RULES_PROVIDED. The supplied project_rules are the original Data stage projections '
                'from a verified independently reviewed publication, including complete conditions, scope '
                'and provenance. Apply them together with main; do not replace them with DR/DC/G processing '
                'rules. Output rule_ids may contain only IDs in the supplied project_rules collection, '
                'never processing/governance IDs. Preserve unresolved applicability and all source-based '
                'access restrictions. Published Project Rules do not constitute Canvas input approval, '
                'Data adequacy approval, scientific qualification or permission to prepare/fit/release. '
                'All processing rules and evidence checks remain active. Stop at the test checkpoint.'}
            payload=deduplicate_rule_sources(payload,source_main['rules'] if final else None)
            if final and stage=='DR-access':
                # Rule references use rule_ids. Do not reintroduce removed duplicate rule leaves through the schema.
                paths=[k.removeprefix('main:') for k in payload['context_sources'] if k.startswith('main:')]
                if not paths:fail('Access requires transmitted source main leaf paths')
                schema['properties']['access']['items']['properties']['context_paths']['items']={'type':'string','enum':paths}
            if stage=='DR':payload=definition_correction(run,payload,schema,scope)
            if payload.get('contract_correction',{}).get('response_constraint'):
                from .data_label_citation_patch import invoke as patch_invoke
                if mixed:payload['model_routing']={'fixed_candidate_model':reuse_model,'citation_patch_model':requested_model,
                    'unchanged_pages':'ORIGINAL_MODEL_CACHE_ONLY','attribution':'HOST_APPLIED_MODEL_CITATION_PATCH'}
                return patch_invoke(original_invoke,run,stage,payload,**options)
            if mixed:options={**options,'model':reuse_model}
            return check_definition_correction(original_invoke(run,stage,payload,schema,**options),payload)
        payload={**payload,'test_scope':copy.deepcopy(scope),
            'instructions':payload.get('instructions','')+'\nThis is UNAPPROVED_TEST_ONLY. Project Rules were deliberately '
            'not supplied for this test. Derive source-bound candidate requirements from main, preserving its '
            'holdout restrictions and unresolved gaps. Do not claim published rules, human approval, adopted '
            'project requirements or production readiness. An empty project_rules list does not mean that '
            'requirements or permissions have been approved. All supplied DR/DC and shared processing rules '
            'and evidence checks still apply. Output rule_ids refer ONLY to IDs in the supplied project_rules '
            'collection, never DR/DC/G processing or governance IDs. Because this test supplies no Project '
            'Rules, every output rule_ids array must be []; retain source-based access restrictions in '
            'context_paths and reason. Do not discard source restrictions because rule_ids is empty. '
            'No preparation, fitting or scientific release is authorized.'}
        if stage=='DR':payload=definition_correction(run,payload,schema,scope)
        if payload.get('contract_correction',{}).get('response_constraint'):
            from .data_label_citation_patch import invoke as patch_invoke
            if mixed:payload['model_routing']={'fixed_candidate_model':reuse_model,'citation_patch_model':requested_model,
                'unchanged_pages':'ORIGINAL_MODEL_CACHE_ONLY','attribution':'HOST_APPLIED_MODEL_CITATION_PATCH'}
            return patch_invoke(original_invoke,run,stage,payload,**options)
        if mixed:options={**options,'model':reuse_model}
        return check_definition_correction(original_invoke(run,stage,payload,schema,**options),payload)
    if final:module.rules_for=inline_rules
    elif not provided:module.rules_for=no_project_rules
    module.invoke=invoke
    return module


def seal_assessment(run,scope):
    """Retain raw technical outputs, but close the test export's downstream preparation gate."""
    folder=run/'assessment';audit=run/'audit/unapproved_technical_assessment'
    originals={}
    for name in ('adequacy.json','qc_context.json','checkpoint.json','checkpoint.md','report.md'):
        path=folder/name
        if path.exists():
            target=audit/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(path.read_bytes())
            originals[name]=file_ref(target)
    report=read_json(folder/'adequacy.json');technical=report['can_enter_qc']
    report.update(test_scope=scope,technical_can_enter_qc=technical,can_enter_qc=False,
                  requires_human_review=True,test_original_ref=originals['adequacy.json'])
    write_json(folder/'adequacy.json',report)
    context=read_json(folder/'qc_context.json')
    context.update(test_scope=scope,technical_can_enter_qc=technical,can_enter_qc=False,
                   assessment=file_ref(folder/'adequacy.json'),test_original_ref=originals['qc_context.json'])
    write_json(folder/'qc_context.json',context)
    path=folder/'checkpoint.json'
    if path.exists():
        checkpoint=read_json(path);checkpoint.update(test_scope=scope,confirmation_required=True,
            production_release=False,can_enter_qc=False,technical_can_enter_qc=technical,
            assessment=file_ref(folder/'adequacy.json'),test_original_ref=originals['checkpoint.json'])
        write_json(path,checkpoint)
    for name in ('checkpoint.md','report.md'):
        path=folder/name
        if path.exists():path.write_text('UNAPPROVED_TEST_ONLY — '+scope['project_rules_status']+'; production QC is blocked.\n'
            'The technical result below is retained for test review only.\n\n'+path.read_text(encoding='utf-8'),encoding='utf-8')
    write_json(run/'assessment_test_receipt.json',dict(test_scope=scope,original_technical_outputs=originals,
        technical_can_enter_qc=technical,can_enter_qc=False,production_release=False,
        assessment=file_ref(folder/'adequacy.json'),qc_context=file_ref(folder/'qc_context.json')))


def run_stage(main_path,output,stage,*,model='gpt-6-sol',generator=None,rules_mode='auto'):
    if stage not in STAGES:fail('Unknown or downstream stage')
    if model not in {'gpt-6-sol','gpt-6-luna'}:fail('This authorized Data test uses gpt-6-sol or gpt-6-luna')
    main_path=Path(main_path).resolve();run=Path(output).resolve();main=read_json(main_path)
    rule_ref=verified_rules(main_path,main,rules_mode)
    source_ref=file_ref(main_path)
    for f in main['data']['files']:
        check_ref(f)
        if f.get('snapshot_path'):check_ref({'path':f['snapshot_path'],'sha256':f['snapshot_sha256']})
    previous_manifest=read_json(run/'test_manifest.json') if (run/'test_manifest.json').exists() else None
    scope_model=previous_manifest['test_scope']['model'] if previous_manifest else model
    if model!=scope_model and stage!='label':fail('A model switch on an existing run is limited to its explicit label patch')
    scope=dict(status=SCOPE,project_rules_status=RULES_STATUS,source_main_ref=source_ref,
        input_approval='NOT_PROVIDED',production_release=False,stop_before='PREPARATION',model=scope_model)
    if rule_ref:scope.update(project_rules_status=RULES_PROVIDED,project_rules_ref=rule_ref)
    if main.get('version')=='4.0':
        final=verified_final(main_path,main)
        scope.update(first_part_receipt_ref=final['receipt_ref'],first_part_review_ref=final['review_ref'],
            rule_body_source='SOURCE_MAIN_RULES')
    run.mkdir(parents=True,exist_ok=True);lock=run/'.stage.lock'
    try:
        handle=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
    except FileExistsError:fail('Another test stage owns this run; inspect its process before retry')
    os.close(handle);started=time.monotonic();attempt=run/'attempts'/stage/uuid4().hex
    try:
        manifest=run/'test_manifest.json'
        if manifest.exists():
            if read_json(manifest)['test_scope']!=scope:fail('Test source, scope or model changed')
        elif any(p.name!='.stage.lock' for p in run.iterdir()):fail('New test output must be empty')
        else:write_json(manifest,{'test_scope':scope,'created_at':utcnow(),'adapter':file_ref(__file__),
            'consumer_implementation':file_ref(data_agents.__file__),'source_main_modified':False})
        for dependency in DEPENDENCIES[stage]:
            receipt=run/'receipts'/f'{dependency}.json'
            if not receipt.exists():fail('Complete prerequisite stage: '+dependency)
            for reference in read_json(receipt)['artifacts']:check_ref(reference)
        receipt=run/'receipts'/f'{stage}.json'
        if receipt.exists():
            for reference in read_json(receipt)['artifacts']:check_ref(reference)
            return {'status':'ALREADY_COMPLETED_TEST_STAGE','stage':stage,'test_scope':scope}
        runtime_refs={'adapter':file_ref(__file__),'data_agents':file_ref(data_agents.__file__)}
        write_json(attempt/'status.json',dict(status='RUNNING',stage=stage,test_scope=scope,
            runtime_refs=runtime_refs,pid=os.getpid(),started_at=utcnow()))
        module=private_agents(main_path,scope,requested_model=model);options={'model':model,'generator':generator}
        destination=run/OUTPUTS[stage]
        if stage=='inventory':module.inventory(main_path,destination,run=run,**options)
        elif stage=='define':module.define(run,main_path,destination,**options)
        elif stage=='access':module.assign_access(run,main_path,run/OUTPUTS['inventory'],run/OUTPUTS['define'],destination,**options)
        elif stage=='label':module.label(run,main_path,run/OUTPUTS['inventory'],run/OUTPUTS['access'],destination,**options)
        else:
            module.assess(run,main_path,run/OUTPUTS['inventory'],run/OUTPUTS['access'],run/OUTPUTS['label'],run/'assessment',**options)
            seal_assessment(run,scope)
        check_ref(source_ref)
        if rule_ref:verified_rules(main_path,main,'published')
        if stage!='assess':
            artifact=read_json(destination);artifact['test_scope']=scope
            if model!=scope_model:
                artifact['model']='MIXED'
                artifact['model_routing']={'unchanged_pages_model':scope_model,'unchanged_pages':'CACHE_REUSE_ONLY',
                    'citation_patch_model':model,'fixed_candidate_model':scope_model,'attribution':'HOST_APPLIED_MODEL_CITATION_PATCH'}
            write_json(destination,artifact)
        artifacts=[file_ref(destination)]
        if stage=='assess':artifacts += [file_ref(run/'assessment/qc_context.json'),file_ref(run/'assessment_test_receipt.json')]
        result=dict(status='COMPLETED_TEST_STAGE',stage=stage,test_scope=scope,artifacts=artifacts,
            runtime_refs=runtime_refs,elapsed_seconds=round(time.monotonic()-started,3),finished_at=utcnow())
        if model!=scope_model:result['model_routing']=artifact['model_routing']
        write_json(receipt,result);write_json(attempt/'status.json',result)
        return result
    except Exception as exc:
        write_json(attempt/'status.json',dict(status='ERROR',stage=stage,test_scope=scope,
            runtime_refs={'adapter':file_ref(__file__),'data_agents':file_ref(data_agents.__file__)},
            code=getattr(exc,'code',type(exc).__name__),error=str(exc),elapsed_seconds=round(time.monotonic()-started,3),finished_at=utcnow()))
        raise
    finally:lock.unlink()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--main',required=True);parser.add_argument('--out',required=True)
    parser.add_argument('--stage',required=True,choices=STAGES);parser.add_argument('--model',default='gpt-6-sol')
    parser.add_argument('--rules-mode',choices=['auto','none','published'],default='auto')
    args=parser.parse_args()
    print(json.dumps(run_stage(args.main,args.out,args.stage,model=args.model,rules_mode=args.rules_mode),ensure_ascii=False))


if __name__=='__main__':main()
