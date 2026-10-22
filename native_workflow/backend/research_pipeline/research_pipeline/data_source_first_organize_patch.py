"""Explicit narrow repair of a rejected DR candidate, never regeneration of the full source packet."""
import argparse
import copy
import json
import os
from pathlib import Path
from ctxcomp.io import digest
from ctxcomp.schemas import obj,arr,S,enum
from . import data_agents as d,data_source_first_workflow as sf,data_source_first_organize as organizer
from .adequacy import file_ref,check_ref
from .common import read_json,write_json

VERSION='SOURCE_FIRST_DR_TARGET_PATCH_1.0'


def get_at(value,path):
    for key in path.strip('/').split('/'):
        value=value[int(key)] if isinstance(value,list) else value[key]
    return value


def put_at(value,path,new):
    parent,key=path.rsplit('/',1);target=get_at(value,parent)
    target[int(key) if isinstance(target,list) else key]=copy.deepcopy(new)


def prepare(run,request_path,response_path,output,*,shifted_sources,append_ids,
            coverage_finding_code='SOURCE_BODY_REVIEW_LIMITED_TO_SUPPLIED_PROFILES'):
    run=Path(run);output=Path(output);manifest,verified=sf.verify_run(run)
    if (run/'requirements.json').exists():sf.fail('Cannot patch an already published DR candidate')
    request=read_json(request_path);old=read_json(response_path);p=request['payload']
    if digest(p)!=request['request_sha256'] or old['request_sha256']!=request['request_sha256']:sf.fail('Original DR request/response binding failed')
    d.validate_schema(old,p['schema'])
    current,_,sources=organizer.build_payload(verified['main'],read_json(run/'source_view.json'),p['method_knowledge'])
    if any(p.get(k)!=v for k,v in current.items() if k!='instructions'):sf.fail('Original DR request differs from current unchanged source view')
    if current['instructions'] not in p['instructions']:sf.fail('Original DR instructions are not the frozen governed contract')
    rows={x['source']:x for x in old['objective_coverage']};needs={x['id']:x for x in old['requirements']}
    if not set(shifted_sources)<=set(rows) or not set(append_ids)<=set(needs):sf.fail('Unknown authorized target')
    replacements=[];repair_sources={};targets=[]
    for group,key in [('tasks','id'),('requirements','id'),('data_links','item_id'),('objective_coverage','source')]:
        for i,row in enumerate(old[group]):
            if group=='objective_coverage' and row['source'] in shifted_sources:continue
            for j,e in enumerate(row['evidence']):
                if e['source'] in sources and e['quote'].strip() and e['quote'] in sources[e['source']]:continue
                path=f'/{group}/{i}/evidence/{j}'
                possible=[s for s,text in sources.items() if s.startswith('main:') and e['quote'].casefold() in text.casefold()]
                if e['source'] in sources:possible.append(e['source'])
                possible=list(dict.fromkeys(possible))
                if not possible:sf.fail('No original source supports a bounded citation correction: '+path)
                replacements.append({'path':path,'record':copy.deepcopy(row),'allowed_sources':possible})
                repair_sources.update({s:sources[s] for s in possible});targets.append(path)
    additions=[]
    for rid in append_ids:
        need=needs[rid];allowed=[]
        for index,rule in enumerate(verified['main']['rules']):
            if rule['id'] in need['rule_ids']:
                for suffix in ('text','usage'):
                    source=f'main:/rules/{index}/{suffix}'
                    if source in sources:allowed.append(source)
        if not allowed:sf.fail('Project evidence append has no already-linked project rule source')
        additions.append({'requirement_id':rid,'record':copy.deepcopy(need),'allowed_sources':allowed})
        repair_sources.update({s:sources[s] for s in allowed})
        for e in need['evidence']:repair_sources[e['source']]=sources[e['source']]
    objective=[]
    for source in shifted_sources:
        objective.append({'source':source,'record':copy.deepcopy(rows[source])});repair_sources[source]=sources[source]
    findings=[{'index':i,'record':copy.deepcopy(f)} for i,f in enumerate(old['findings']) if f['code']==coverage_finding_code]
    if len(findings)!=1:sf.fail('Coverage wording correction must identify one existing finding')
    view=read_json(run/'source_view.json');inventory=read_json(run/'inventory.json');profiles=[];notes={}
    for profile in view['profiles']:
        item=next(i for i in inventory['items'] if i['id']==profile['item_id']);item_id=item['id']
        compact={k:copy.deepcopy(v) for k,v in profile.items() if k not in ('columns','stated_values','evidence_source_ids')}
        compact['columns']=[{k:v for k,v in c.items() if k!='evidence_source_ids'} for c in profile['columns']]
        profiles.append(compact);notes[item_id]=p['source_units'][item_id]
        cells=dict(d.content_cells(item)) if item['kind']=='TABLE' else {}
        for source,text in p['source_units'].items():
            if not source.startswith(item_id+':'):continue
            if item['kind']!='TABLE' or cells[source]['row']<=item['region']['header_row'] or not d.in_regions(cells[source],[item['region']]) or cells[source].get('comment'):
                notes[source]=text
    context={k:v for k,v in p['context_sources'].items() if k.startswith('main:')}
    for record in old['tasks']+old['requirements']:
        for e in record['evidence']:
            if e['source'] in sources and e['quote'] in sources[e['source']]:context[e['source']]=sources[e['source']]
    method_sources=d.method_profiles.evidence_sources(p['method_knowledge'])
    # All source references remain real original IDs; no label/findings text becomes original evidence.
    repair_sources.update(context);repair_sources.update(notes);repair_sources.update(method_sources)
    contract={'version':VERSION,'original_request_ref':file_ref(request_path),'original_response_ref':file_ref(response_path),
        'main_ref':manifest['bindings']['main'],'source_view_ref':file_ref(run/'source_view.json'),
        'source_catalog_ref':file_ref(run/'data_agents/source_first_evidence.json'),
        'span_replacements':replacements,'project_evidence_additions':additions,'objective_replacements':objective,
        'repair_sources':repair_sources,'requirements_index':[{'id':x['id'],'task_id':x['task_id'],'description':x['description'],
            'origin':x['origin'],'conditions':x['conditions']} for x in old['requirements']],
        'coverage_finding':findings[0],'tasks':copy.deepcopy(old['tasks']),
        'method_source_profiles':profiles,'method_knowledge':p['method_knowledge'],
        'project_rules':p['project_rules'],
        'actual_delivery':{'original_source_unit_count':len(p['source_units']),'permitted_profiles':len(p['data_profiles']),
            'all_permitted_source_units_were_sent':True,'legacy_extraction_was_requirement_conditioned':True,
            'scope':'Registered permitted sources only; protected horse/human/benchmark bodies were not opened. Complete delivery does not itself prove semantic extraction completeness.'},
        'fixed_candidate_sha256':digest(old),'scientific_approval':False}
    write_json(output,contract)
    return {'status':'PATCH_PREPARED_NO_MODEL_CALL','contract_ref':file_ref(output),
        'span_targets':len(replacements),'append_targets':len(additions),'objective_targets':len(objective)}


def schema(contract):
    method=copy.deepcopy(organizer.METHOD_FEASIBILITY)
    method['properties']['task_id']=enum(*(t['id'] for t in contract['tasks']))
    return obj(request_sha256=S,
        span_replacements=arr(obj(path=enum(*(x['path'] for x in contract['span_replacements'])),evidence=d.EVIDENCE)),
        project_evidence_additions=arr(obj(requirement_id=enum(*(x['requirement_id'] for x in contract['project_evidence_additions'])),evidence=d.EVIDENCE)),
        objective_replacements=arr(obj(source=enum(*(x['source'] for x in contract['objective_replacements'])),
            requirement_ids=arr(enum(*(x['id'] for x in contract['requirements_index']))),reason=S,evidence=arr(d.EVIDENCE,1))),
        coverage_finding=obj(reason=S,needed_material=S),method_feasibility=arr(method))


def payload(contract):
    return {'operation':'REPAIR_ONLY_LOCKED_DR_TARGETS','patch_version':VERSION,
        'targets':{k:contract[k] for k in ('span_replacements','project_evidence_additions','objective_replacements')},
        'requirements_index':contract['requirements_index'],'repair_sources':{k:v for k,v in contract['repair_sources'].items() if not k.startswith('method:')},
        'coverage_finding':contract['coverage_finding'],'actual_delivery':contract['actual_delivery'],
        'tasks':contract['tasks'],'method_source_profiles':contract['method_source_profiles'],
        'method_knowledge':contract['method_knowledge'],'project_rules':contract['project_rules'],
        'fixed_candidate_sha256':contract['fixed_candidate_sha256'],
        'instructions':'Return only the narrow patch schema. Target records and requirements_index are NON-EVIDENCE previous model claims. '
        'repair_sources are exact unchanged original main/rule/source text. Correct each bad citation only at its listed path. '
        'The two project_evidence_additions must APPEND genuine already-linked project rule support for preservation/identity restrictions; '
        'their existing source citations, origin and scientific fields stay locked. Do not force methodological adoption. '
        'For each objective_replacements entry, its source key is FIXED: re-read that exact source and correct only this row reason, '
        'new requirement IDs and evidence. Previous rows were shifted to adjacent scientific records. Cite its own exact source. '
        'The 17 existing requirements are fixed; if none covers that source, use an empty requirement_ids array and explicitly explain '
        'the uncovered gap and next action. Never invent a new need or force a false association. '
        'Preserve all other tasks, requirements, 60 data links, findings and objective rows verbatim. '
        'Quotes must be contiguous literal text with exact capitalization; source IDs/array indices are not interchangeable. '
        'Correct only reason/needed_material of coverage_finding: the original DR DID receive every permitted original source unit, not just profiles. '
        'Preserve the different limitation that historical Sol extraction was requirement-conditioned and semantic completeness still needs independent review; '
        'do not claim protected bodies were read. Its code, affected_id, severity and phase are locked. '
        'Also return exactly one method_feasibility record per task: a source-informed rough menu of possible conditional approaches, actual inputs, '
        'missing inputs and limitations, or explain UNAVAILABLE/UNRESOLVED. Cite exact project context and actual notes; cite every named method profile '
        'as method:MPxxx. The full method library is candidate knowledge, not project authority or evidence of an observed measurement. '
        'method:MPxxx denotes that exact complete profile in method_knowledge.library.profiles; it is not duplicated in repair_sources. '
        'Do not claim any method is fitted, selected, qualified or all conditions met. proposed_requirement_followups are only proposals; '
        'the existing 17 formal needs remain unchanged. Do not invent a method merely to fill the list. '
        'Return every listed target once. This correction grants no scientific approval.'}


def derive(answer,contract):
    if contract['version']!=VERSION:sf.fail('Unknown targeted repair contract')
    for k in ('original_request_ref','original_response_ref','main_ref','source_view_ref','source_catalog_ref'):check_ref(contract[k])
    request=read_json(contract['original_request_ref']['path']);old=read_json(contract['original_response_ref']['path'])
    if digest(old)!=contract['fixed_candidate_sha256'] or digest(request['payload'])!=request['request_sha256'] or old['request_sha256']!=request['request_sha256']:
        sf.fail('Immutable parent candidate binding changed')
    d.validate_schema(answer,schema(contract));result=copy.deepcopy(old);result['request_sha256']=answer['request_sha256']
    for name,key in [('span_replacements','path'),('project_evidence_additions','requirement_id'),('objective_replacements','source')]:
        d.exact([x[key] for x in answer[name]],[x[key] for x in contract[name]],'Scoped DR patch '+name)
    for op in answer['span_replacements']:
        target=next(x for x in contract['span_replacements'] if x['path']==op['path'])
        if op['evidence']['source'] not in target['allowed_sources']:sf.fail('Citation replacement exceeded its source scope')
        d.evidence_check([op['evidence']],contract['repair_sources']);put_at(result,op['path'],op['evidence'])
    for op in answer['project_evidence_additions']:
        target=next(x for x in contract['project_evidence_additions'] if x['requirement_id']==op['requirement_id'])
        if op['evidence']['source'] not in target['allowed_sources']:sf.fail('Project evidence append exceeded linked-rule scope')
        d.evidence_check([op['evidence']],contract['repair_sources'])
        need=next(x for x in result['requirements'] if x['id']==op['requirement_id'])
        if op['evidence'] in need['evidence']:sf.fail('A project evidence append must be new')
        need['evidence'].append(copy.deepcopy(op['evidence']))
    for op in answer['objective_replacements']:
        if not any(e['source']==op['source'] for e in op['evidence']):sf.fail('Corrected coverage must cite its own fixed source')
        d.evidence_check(op['evidence'],contract['repair_sources'])
        index=next(i for i,x in enumerate(result['objective_coverage']) if x['source']==op['source'])
        result['objective_coverage'][index]=copy.deepcopy(op)
    f=contract['coverage_finding'];result['findings'][f['index']].update(copy.deepcopy(answer['coverage_finding']))
    d.validate_schema(result,request['payload']['schema'])
    organizer.validate_response(result,request['payload'],read_json(contract['source_catalog_ref']['path']),request['payload']['method_knowledge'])
    organizer.validate_method_feasibility(answer['method_feasibility'],old['tasks'],contract['repair_sources'],contract['method_knowledge'])
    # Check original and visible text, including compact descriptor JSON, for every newly supplied method citation.
    organizer.validate_method_feasibility(answer['method_feasibility'],old['tasks'],read_json(contract['source_catalog_ref']['path']),contract['method_knowledge'])
    result['method_feasibility']=copy.deepcopy(answer['method_feasibility'])
    return result


def verify_proof(path):
    proof=read_json(path)
    if proof['version']!=VERSION or proof['attribution']!='HOST_APPLIED_MODEL_TARGET_PATCH':sf.fail('Invalid patch attribution')
    for k in ('contract_ref','patch_request_ref','raw_patch_ref','derived_response_ref'):check_ref(proof[k])
    contract=read_json(proof['contract_ref']['path']);request=read_json(proof['patch_request_ref']['path']);answer=read_json(proof['raw_patch_ref']['path'])
    if digest(request['payload'])!=request['request_sha256'] or answer['request_sha256']!=request['request_sha256']:sf.fail('Patch request binding failed')
    expected=payload(contract)
    if (any(request['payload'].get(k)!=v for k,v in expected.items() if k!='instructions')
            or expected['instructions'] not in request['payload']['instructions']):sf.fail('Patch prompt/target scope differs from its proof')
    if derive(answer,contract)!=read_json(proof['derived_response_ref']['path']):sf.fail('Derived candidate replay failed')
    return {'status':'VALID_TARGETED_DERIVATION','scientific_approval':False}


def execute(run,contract_path,*,generator=None):
    run=Path(run);sf.verify_run(run);contract=read_json(contract_path)
    if (run/'requirements.json').exists():sf.fail('DR already published')
    bound=file_ref(contract_path);checked={}
    def check(answer):
        check_ref(bound);checked[answer['request_sha256']]=derive(answer,contract);return True
    answer=sf.invoke(run,'DR',payload(contract),schema(contract),generator=generator,check=check)
    result=checked[answer['request_sha256']];sf.verify_run(run)
    requests=[p for p in (run/'data_agents/audit/DR').glob('*/request.json') if read_json(p)['request_sha256']==answer['request_sha256']]
    if not requests:sf.fail('Patch actual request audit is absent')
    directory=run/'data_agents/organize_patches'/answer['request_sha256']
    proof={'version':VERSION,'attribution':'HOST_APPLIED_MODEL_TARGET_PATCH','contract_ref':bound,
        'patch_request_ref':file_ref(requests[0]),'raw_patch_ref':file_ref(write_json(directory/'raw_patch.json',answer)),
        'derived_response_ref':file_ref(write_json(directory/'derived_response.json',result)),
        'code_ref':file_ref(__file__),'original_host_checks_passed':True,'scientific_approval':False}
    proof_path=write_json(directory/'proof.json',proof);verify_proof(proof_path)
    status=organizer.publish_checked(run,result,file_ref(run/'data_agents/method_context.json'),contract['source_catalog_ref'],file_ref(proof_path))
    stopped=run/'data_agents/stopped.json'
    stop=read_json(stopped) if stopped.exists() else {}
    resolved_audits={str(Path(contract['original_request_ref']['path']).parent.resolve()),*(str(p.parent.resolve()) for p in requests)}
    if stop.get('stage')=='DR' and str(Path(stop.get('audit_path','')).resolve()) in resolved_audits:
        # Archive the resolved engineering failure byte-for-byte; no rejected response or review is overwritten.
        archived=directory/'prior_stopped.json';archived.write_bytes(stopped.read_bytes())
        write_json(directory/'stop_resolution.json',{'prior_stop_ref':file_ref(archived),
            'resolved_by':file_ref(proof_path),'scientific_approval':False})
        if stopped.resolve().is_relative_to(run.resolve()):stopped.unlink()
    return {**status,'derivation_proof_ref':file_ref(proof_path),'targeted_patch':True}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--out',required=True);parser.add_argument('--contract',required=True)
    args=parser.parse_args();run=Path(args.out).resolve();lock=run/'.stage.lock'
    try:fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
    except FileExistsError:sf.fail('A source-first stage is already active')
    os.close(fd)
    try:
        sf.emit(run,'STAGE_START',stage='organize_target_patch',model_for_new_calls=sf.MODEL)
        result=execute(run,args.contract);write_json(run/'receipts/organize.json',result)
        sf.emit(run,'STAGE_END',stage='organize_target_patch',result=result);print(json.dumps(result,ensure_ascii=False))
    except Exception as exc:
        sf.emit(run,'STAGE_ERROR',stage='organize_target_patch',error_type=type(exc).__name__,error=str(exc));raise
    finally:lock.unlink()


if __name__=='__main__':main()
