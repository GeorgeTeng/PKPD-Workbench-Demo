"""Source-first Data test: verified reuse -> local repair -> post-source DR -> gap review.

Historical extraction retains its real model identity; new calls use gpt-6-luna.
"""
import argparse
import copy
import importlib.util
import json
import os
import time
import threading
from pathlib import Path
from uuid import uuid4
from ctxcomp.io import digest
from ctxcomp.providers import executor_identity
from . import data_agents as d
from .adequacy import file_ref,check_ref
from .common import read_json,write_json,PipelineError,utcnow
from .first_part_handoff import verify_final_main

VERSION='SOURCE_FIRST_1.0'
MODEL='gpt-6-luna'
STAGES=('import','repair','organize','review')
_EVENT_LOCK=threading.Lock()


def fail(message):raise PipelineError('SOURCE_FIRST_CONTRACT',message)


def private_module():
    spec=importlib.util.spec_from_file_location('research_pipeline._source_first_'+uuid4().hex,d.__file__)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def verify_run(run):
    manifest=read_json(Path(run)/'manifest.json')
    if manifest['version']!=VERSION:fail('Unknown source-first contract')
    for reference in manifest['bindings'].values():check_ref(reference)
    verified=verify_final_main(manifest['bindings']['main']['path'])
    if verified['main_ref']!=manifest['bindings']['main']:fail('Final main changed')
    return manifest,verified


def emit(run,event,**details):
    value={'at':utcnow(),'event':event,**details}
    with _EVENT_LOCK:
        Path(run).mkdir(parents=True,exist_ok=True)
        with (Path(run)/'events.jsonl').open('a',encoding='utf-8') as stream:stream.write(json.dumps(value,ensure_ascii=False)+'\n')
        write_json(Path(run)/'telemetry.json',value)


def invoke(run,stage,payload,schema,*,generator=None,check=None):
    """One model call; original policy/schema/evidence checks and 700k guard remain active."""
    payload={**payload,'source_first_contract':VERSION,'scientific_approval':False}
    def generate(request,**options):
        call_id=uuid4().hex;status='ERROR'
        emit(run,'MODEL_START',call_id=call_id,stage=stage,item=payload.get('item_id'),part=payload.get('part_id'),
             model=MODEL,request_chars=len(json.dumps(request,ensure_ascii=False)),request_sha256=request['request_sha256'])
        started=time.monotonic()
        try:
            result=(generator or d.codex_generate)(request,**options);status='RETURNED';return result
        finally:
            usage=None;diagnostics=options.get('diagnostics_dir')
            if diagnostics and Path(diagnostics).exists():
                for path in Path(diagnostics).rglob('*.jsonl'):
                    for line in path.read_text(encoding='utf-8',errors='replace').splitlines():
                        try:value=json.loads(line)
                        except ValueError:continue
                        if isinstance(value,dict) and isinstance(value.get('usage'),dict):usage=value['usage']
            emit(run,'MODEL_END',call_id=call_id,status=status,stage=stage,item=payload.get('item_id'),part=payload.get('part_id'),
                 model=MODEL,elapsed_seconds=round(time.monotonic()-started,3),
                 usage=usage,provider_diagnostics=str(options.get('diagnostics_dir','')))
    identity=getattr(generator,'executor_id',None) if generator else 'provider:'+digest(executor_identity(MODEL))
    generate.executor_id='SOURCE_FIRST_1.0:'+identity if identity else None
    return d.invoke(run,stage,payload,schema,model=MODEL,generator=generate,check=check)


def import_checked(main_path,run,reuse_manifest,repair_spec):
    """Replay the original label host checks locally; never pretend this was a fresh model extraction."""
    run=Path(run);verified=verify_final_main(main_path);reuse=read_json(reuse_manifest)
    if reuse['original_main_ref']!=verified['main_ref']:fail('Reuse belongs to another main')
    if not reuse['all_host_page_checks_passed'] or not reuse['all_source_units_exact']:fail('Reuse audit is incomplete')
    for key in ('local_validator_ref','original_main_ref','original_inventory_ref','original_requirements_ref'):check_ref(reuse[key])
    if reuse['local_validator_ref']!=file_ref(d.__file__):fail('Revalidate reuse with the current original host checker')
    inv=read_json(reuse['original_inventory_ref']['path']);legacy=read_json(reuse['original_requirements_ref']['path'])
    if inv['main']!=verified['main_ref'] or legacy['main']!=verified['main_ref']:fail('Legacy source bindings differ')
    if legacy['inventory']!=reuse['original_inventory_ref']:fail('Legacy permissions belong to another inventory')
    for item in inv['items']:
        for key in ('source','snapshot'):
            if item.get(key):check_ref(item[key])
    access={a['item_id']:a for a in legacy['access']};records={}
    for entry in reuse['items']:
        key=(entry['item_id'],entry['page'])
        if key in records:fail('Duplicate reusable page')
        for name in ('raw_response_ref','request_ref','kept_ref','source_main_ref','source_ref','snapshot_ref'):check_ref(entry[name])
        request=read_json(entry['request_ref']['path']);response=read_json(entry['raw_response_ref']['path'])
        if (request['request_sha256']!=digest(request['payload']) or response['request_sha256']!=request['request_sha256']
                or response!=read_json(entry['kept_ref']['path']) or entry['source_main_ref']!=verified['main_ref']
                or request['payload']['test_scope']['source_main_ref']!=verified['main_ref']
                or digest(request['payload']['source_units'])!=entry['source_units_sha256']
                or access[entry['item_id']]['disposition']!='REVIEW_DATA'):
            fail('Invalid legacy extraction/source/permission binding')
        records[key]=(entry,request,response)
    permitted=[i for i in inv['items'] if access[i['id']]['disposition']=='REVIEW_DATA']
    repair=read_json(repair_spec)
    for key in ('failed_request_ref','failed_response_ref'):check_ref(repair[key])
    pending_request=read_json(repair['failed_request_ref']['path']);pending_response=read_json(repair['failed_response_ref']['path'])
    pending_id=pending_request['payload']['item_id']
    if (pending_request['payload']['test_scope']['source_main_ref']!=verified['main_ref']
            or pending_request['request_sha256']!=digest(pending_request['payload'])
            or pending_response['request_sha256']!=pending_request['request_sha256']
            or pending_id not in {i['id'] for i in permitted}):fail('Pending local repair is not a permitted bound source')
    expected={i['id'] for i in permitted}
    if {key[0] for key in records}|{pending_id}!=expected:fail('Every permitted item must be reused or explicitly pending repair')
    # Original checker runs with its original historical requirements solely for validation.
    # Those associations are not copied into the source-first interpretation.
    validation=run/'audit/local_revalidation';selected={key[0] for key in records}
    filtered={**copy.deepcopy(inv),'items':[i for i in inv['items'] if i['id'] in selected]}
    invpath=write_json(validation/'inventory.json',filtered)
    historical={**copy.deepcopy(legacy),'inventory':file_ref(invpath),
                'access':[a for a in legacy['access'] if a['item_id'] in selected]}
    reqpath=write_json(validation/'historical_requirements.json',historical)
    module=private_module();visited=[]
    def reuse_call(_,stage,payload,schema,check=None,**options):
        if stage!='DC-label' or check is None:fail('Only local label verification is permitted during import')
        key=(payload['item_id'],payload['page'])
        if key not in records:fail('No reverified legacy response for this exact page')
        entry,request,response=records[key]
        if payload['source_units']!=request['payload']['source_units']:fail('Current source page/notes differ from extraction')
        answer=copy.deepcopy(response);d.validate_schema(answer,schema);check(answer);visited.append(key)
        return answer
    module.invoke=reuse_call
    module.label(validation,main_path,invpath,reqpath,validation/'checked_labels.json',model='LEGACY_REUSE_NO_MODEL_CALL')
    if set(visited)!=set(records) or len(visited)!=len(records):fail('Incomplete local validation coverage')
    checked=read_json(validation/'checked_labels.json')
    bindings={'main':verified['main_ref'],'first_part_receipt':verified['receipt_ref'],'first_part_review':verified['review_ref'],
        'reuse_manifest':file_ref(reuse_manifest),'repair_spec':file_ref(repair_spec),
        'DR_policy':file_ref(d.AGENT_FILES['DR']),'DC_policy':file_ref(d.AGENT_FILES['DC']),
        'source_first_code':file_ref(__file__),'original_data_checker':file_ref(d.__file__),
        'repair_code':file_ref(Path(__file__).with_name('data_source_first_repair.py')),
        'citation_patch_code':file_ref(Path(__file__).with_name('data_label_citation_patch.py'))}
    write_json(run/'manifest.json',{'version':VERSION,'bindings':bindings,'model_for_new_calls':MODEL,
        'scientific_approval':False,'can_enter_qc':False,'created_at':utcnow()})
    write_json(run/'inventory.json',inv)
    permissions=[{k:copy.deepcopy(v) for k,v in a.items() if k!='requirement_ids'} for a in legacy['access']]
    for item in inv['items']:
        a=next(a for a in permissions if a['item_id']==item['id'])
        if item['kind']=='PROTECTED' and a['disposition']!='REFERENCE_ONLY':fail('Protected resource cannot become readable')
    write_json(run/'permissions.json',{'main':verified['main_ref'],'access':permissions,
        'legacy_permission_ref':reuse['original_requirements_ref'],'requirement_associations_not_used':True})
    write_json(run/'pending_repairs.json',{'items':[{'item_id':pending_id,'spec_ref':file_ref(repair_spec)}]})
    write_json(run/'legacy_import.json',{'version':VERSION,'labels':checked['labels'],'findings':checked['findings'],
        'coverage':checked['coverage'],'page_provenance':[{'item_id':e['item_id'],'page':e['page'],
        'original_model':e['original_model'],'request_ref':e['request_ref'],'response_ref':e['raw_response_ref'],
        'source_units_sha256':e['source_units_sha256']} for e,_,_ in records.values()],
        'limitations':reuse['limitations'],'historical_requirements_ref':reuse['original_requirements_ref']})
    build_source_view(run)
    bind_outputs(run,('inventory.json','permissions.json','pending_repairs.json','legacy_import.json','source_view.json'))
    return {'status':'IMPORTED_CHECKED_LEGACY_SOURCES','reused_pages':len(records),'model_calls':0,'pending':[pending_id]}


def bind_outputs(run,names):
    run=Path(run);manifest=read_json(run/'manifest.json')
    for name in names:manifest['bindings']['output:'+name]=file_ref(run/name)
    write_json(run/'manifest.json',manifest)


def build_source_view(run):
    run=Path(run);manifest,verified=verify_run(run);inv=read_json(run/'inventory.json');permissions=read_json(run/'permissions.json')
    imported=read_json(run/'legacy_import.json');labels=copy.deepcopy(imported['labels']);findings=copy.deepcopy(imported['findings'])
    repair=run/'repaired_document.json'
    if repair.exists():
        fixed=read_json(repair);labels+=fixed['labels'];findings+=fixed['findings']
    original={x['item_id']:x for x in labels};profiles=[];history=[];units={}
    allowed={a['item_id'] for a in permissions['access'] if a['disposition']=='REVIEW_DATA'}
    for item in inv['items']:
        if item['id'] not in allowed:continue
        source=dict(d.content_units(item));source[item['id']]=json.dumps(item['descriptor'],ensure_ascii=False)
        units.update(source)
        if item['id'] not in original:continue
        label=original[item['id']]
        history.append({'item_id':item['id'],'requirement_ids':label['requirement_ids'],'reason':label['reason']})
        profile={k:copy.deepcopy(v) for k,v in label.items() if k not in ('requirement_ids','reason')}
        # Exact quotes remain in one original source map; evidence identities remain on each interpreted field.
        def evidence_ids(value):
            if isinstance(value,dict):
                for k,v in list(value.items()):
                    if k=='evidence':
                        for e in v:d.evidence_check([e],source)
                        value['evidence_source_ids']=list(dict.fromkeys(e['source'] for e in v));del value[k]
                    else:evidence_ids(v)
            elif isinstance(value,list):
                for x in value:evidence_ids(x)
        evidence_ids(profile);profiles.append(profile)
    pending=sorted(allowed-set(original))
    write_json(run/'source_view.json',{'version':VERSION,'main_ref':manifest['bindings']['main'],'profiles':profiles,
        'source_units':units,'legacy_findings':findings,'legacy_association_history':history,
        'permissions':permissions['access'],'pending_item_ids':pending,'scientific_approval':False,
        'interpretation':'Reused legacy Sol extraction was requirement-conditioned; old IDs/reasons/findings targets are historical, not constraints on post-source DR. Every permitted original source unit and note is supplied. Do not drop scientific limits embedded in historical text.'})
    return {'profiles':len(profiles),'pending':pending}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--stage',choices=STAGES,required=True)
    parser.add_argument('--main');parser.add_argument('--out',required=True);parser.add_argument('--reuse-manifest');parser.add_argument('--repair-spec')
    args=parser.parse_args();run=Path(args.out).resolve();run.mkdir(parents=True,exist_ok=True)
    lock=run/'.stage.lock'
    try:fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
    except FileExistsError:fail('A source-first stage is already active')
    os.close(fd)
    try:
        emit(run,'STAGE_START',stage=args.stage,model_for_new_calls=MODEL)
        if args.stage=='import':
            if (run/'manifest.json').exists():fail('Import is immutable; verify existing artifacts instead of repeating it')
            result=import_checked(args.main,run,args.reuse_manifest,args.repair_spec)
        elif args.stage=='repair':
            from .data_source_first_repair import repair
            result=repair(run)
        elif args.stage=='organize':
            from .data_source_first_organize import organize
            result=organize(run)
        else:
            from .data_source_first_review import review
            result=review(run)
        write_json(run/'receipts'/f'{args.stage}.json',result);emit(run,'STAGE_END',stage=args.stage,result=result)
        print(json.dumps(result,ensure_ascii=False))
    except Exception as exc:
        emit(run,'STAGE_ERROR',stage=args.stage,error_type=type(exc).__name__,error=str(exc))
        raise
    finally:lock.unlink()


if __name__=='__main__':main()
