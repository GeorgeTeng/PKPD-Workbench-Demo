"""Source-selector continuation of one immutable, rejected narrow DR patch."""
import argparse
import copy
import json
import os
from pathlib import Path
from ctxcomp.io import digest
from ctxcomp.schemas import obj,arr,S,enum
from . import data_agents as d,data_source_first_workflow as sf,data_source_first_organize_patch as prior
from .common import read_json,write_json
from .adequacy import file_ref,check_ref

VERSION='SOURCE_FIRST_DR_CONTINUATION_1.0'
EVIDENCE_PATHS=('/span_replacements/6/evidence','/method_feasibility/0/approaches/0/evidence/1','/method_feasibility/1/approaches/0/evidence/2')


def prepare(contract_path,failed_request,failed_response,out):
    parent=read_json(contract_path);q=read_json(failed_request);raw=read_json(failed_response)
    if digest(q['payload'])!=q['request_sha256'] or raw['request_sha256']!=q['request_sha256']:sf.fail('Rejected patch binding differs')
    expected=prior.payload(parent)
    if any(q['payload'].get(k)!=v for k,v in expected.items() if k!='instructions') or expected['instructions'] not in q['payload']['instructions']:sf.fail('Rejected patch is not this scoped parent')
    d.validate_schema(raw,prior.schema(parent));sources=parent['repair_sources'];edits=[]
    paths=EVIDENCE_PATHS
    for path in paths:
        e=prior.get_at(raw,path)
        if path.startswith('/span_replacements/'):
            if e['source']!='main:/missing_information/items/15/clarification':sf.fail('Unexpected MI correction target')
            choices=[{'source':e['source'],'quote':sources[e['source']]}]
        else:
            choices=[{'source':s,'quote':e['quote']} for s,t in sources.items()
                     if s.startswith('main:/scientific_context/') and s.endswith('/statement') and e['quote'] in t]
        if not choices:sf.fail('No exact original source supports continuation evidence')
        edits.append({'path':path,'choices':choices})
    rows=[{'source':t['source'],'authoritative_text':sources[t['source']]} for t in parent['objective_replacements']]
    need_ids={x['id'] for x in parent['requirements_index']}
    original=read_json(parent['original_response_ref']['path'])
    rule_ids={rid for n in original['requirements'] if n['id'] in need_ids for rid in n['rule_ids']}
    c={'version':VERSION,'parent_contract_ref':file_ref(contract_path),'failed_request_ref':file_ref(failed_request),
       'fixed_patch_ref':file_ref(failed_response),'fixed_patch_sha256':digest(raw),'evidence_targets':edits,'objective_targets':rows,
       'requirements_index':parent['requirements_index'],'project_rules':[r for r in parent['project_rules'] if r['id'] in rule_ids],
       'scientific_approval':False}
    write_json(out,c);return c


def schema(c):
    return obj(request_sha256=S,evidence_selections=arr(obj(path=enum(*(x['path'] for x in c['evidence_targets'])),source=S)),
        objective_replacements=arr(obj(source=enum(*(x['source'] for x in c['objective_targets'])),
            requirement_ids=arr(enum(*(x['id'] for x in c['requirements_index']))),reason=S)))


def payload(c):
    return {'operation':'CONTINUE_ONLY_EXACT_SOURCE_TARGETS','version':VERSION,'fixed_patch_sha256':c['fixed_patch_sha256'],
        'evidence_targets':c['evidence_targets'],'objective_targets':c['objective_targets'],
        'requirements_index':c['requirements_index'],'project_rules':c['project_rules'],
        'instructions':'Select source IDs only for evidence_targets; the host will explicitly materialize the displayed exact quote. '
        'For objective_targets, each source key and authoritative_text are bound together. Read THAT text and write its own coverage reason '
        'and appropriate existing requirement_ids. These are zero-based JSON indices, not scientific record IDs. Do not infer a neighboring '
        'record by index or copy a prior response. The host will cite the full authoritative_text of the selected target as its evidence. '
        'No old erroneous objective rows are supplied. If no existing need covers this source, return [] and explain the uncovered gap and '
        'follow-up; do not force an association. All other original patch fields, five method feasibility summaries, tasks, needs and data links '
        'are immutable. requirements_index is a previous model candidate, not source authority; project_rules are source-bound project constraints. '
        'Return each target exactly once. This is only a citation/coverage correction, not scientific approval.'}


def derive(answer,c):
    if c['version']!=VERSION:sf.fail('Unknown continuation version')
    for k in ['parent_contract_ref','failed_request_ref','fixed_patch_ref']:check_ref(c[k])
    parent=read_json(c['parent_contract_ref']['path']);q=read_json(c['failed_request_ref']['path']);fixed=read_json(c['fixed_patch_ref']['path'])
    if digest(fixed)!=c['fixed_patch_sha256'] or digest(q['payload'])!=q['request_sha256'] or fixed['request_sha256']!=q['request_sha256']:sf.fail('Continuation parent binding differs')
    expected=prior.payload(parent)
    if any(q['payload'].get(k)!=v for k,v in expected.items() if k!='instructions') or expected['instructions'] not in q['payload']['instructions']:sf.fail('Continuation parent scope differs')
    d.exact([t['path'] for t in c['evidence_targets']],list(EVIDENCE_PATHS),'Frozen continuation scope')
    d.exact([t['source'] for t in c['objective_targets']],[t['source'] for t in parent['objective_replacements']],'Frozen objective scope')
    if c['requirements_index']!=parent['requirements_index']:sf.fail('Existing requirements index changed')
    for t in c['evidence_targets']:
        e=prior.get_at(fixed,t['path']);sources=parent['repair_sources']
        if t['path']==EVIDENCE_PATHS[0]:
            s='main:/missing_information/items/15/clarification';expected_choices=[{'source':s,'quote':sources[s]}]
        else:
            expected_choices=[{'source':s,'quote':e['quote']} for s,text in sources.items()
                if s.startswith('main:/scientific_context/') and s.endswith('/statement') and e['quote'] in text]
        if t['choices']!=expected_choices:sf.fail('Continuation evidence choices changed')
    d.validate_schema(answer,schema(c));patched=copy.deepcopy(fixed);patched['request_sha256']=answer['request_sha256']
    d.exact([x['path'] for x in answer['evidence_selections']],[x['path'] for x in c['evidence_targets']],'Continuation evidence targets')
    d.exact([x['source'] for x in answer['objective_replacements']],[x['source'] for x in c['objective_targets']],'Continuation coverage targets')
    for op in answer['evidence_selections']:
        target=next(t for t in c['evidence_targets'] if t['path']==op['path'])
        choices=[e for e in target['choices'] if e['source']==op['source']]
        if len(choices)!=1:sf.fail('Unlisted source selection')
        d.evidence_check(choices,parent['repair_sources']);prior.put_at(patched,op['path'],choices[0])
    for op in answer['objective_replacements']:
        target=next(t for t in c['objective_targets'] if t['source']==op['source'])
        if parent['repair_sources'].get(op['source'])!=target['authoritative_text']:sf.fail('Authoritative target text changed')
        i=next(i for i,t in enumerate(patched['objective_replacements']) if t['source']==op['source'])
        patched['objective_replacements'][i]={**op,'evidence':[{'source':op['source'],'quote':target['authoritative_text']}]}
    # Complete original narrow patch and original DR validation still run, including every locked field.
    return prior.derive(patched,parent),patched


def verify_proof(path):
    proof=read_json(path)
    if proof['version']!=VERSION or proof['attribution']!='HOST_MATERIALIZED_MODEL_SOURCE_SELECTIONS':sf.fail('Invalid continuation attribution')
    for k in ['contract_ref','request_ref','raw_response_ref','corrected_patch_ref','derived_response_ref']:check_ref(proof[k])
    c=read_json(proof['contract_ref']['path']);q=read_json(proof['request_ref']['path']);a=read_json(proof['raw_response_ref']['path'])
    if digest(q['payload'])!=q['request_sha256'] or a['request_sha256']!=q['request_sha256']:sf.fail('Continuation request binding differs')
    expected=payload(c)
    if any(q['payload'].get(k)!=v for k,v in expected.items() if k!='instructions') or expected['instructions'] not in q['payload']['instructions']:sf.fail('Continuation request scope differs')
    result,patch=derive(a,c)
    if result!=read_json(proof['derived_response_ref']['path']) or patch!=read_json(proof['corrected_patch_ref']['path']):sf.fail('Continuation replay differs')
    return {'status':'VALID_CONTINUATION_PROOF','scientific_approval':False}


def execute(run,contract_path,*,generator=None):
    run=Path(run);sf.verify_run(run)
    if (run/'requirements.json').exists():sf.fail('DR already published')
    c=read_json(contract_path);bound=file_ref(contract_path);checked={}
    def check(a):
        check_ref(bound);checked[a['request_sha256']]=derive(a,c);return True
    a=sf.invoke(run,'DR',payload(c),schema(c),generator=generator,check=check)
    result,patch=checked[a['request_sha256']];sf.verify_run(run)
    requests=[p for p in (run/'data_agents/audit/DR').glob('*/request.json') if read_json(p)['request_sha256']==a['request_sha256']]
    if not requests:sf.fail('Continuation actual request missing')
    directory=run/'data_agents/dr_continue'/a['request_sha256'][:16]
    proof={'version':VERSION,'attribution':'HOST_MATERIALIZED_MODEL_SOURCE_SELECTIONS','contract_ref':bound,
        'request_ref':file_ref(requests[0]),'raw_response_ref':file_ref(write_json(directory/'raw_response.json',a)),
        'corrected_patch_ref':file_ref(write_json(directory/'corrected_patch.json',patch)),
        'derived_response_ref':file_ref(write_json(directory/'derived_response.json',result)),
        'code_ref':file_ref(__file__),'scientific_approval':False}
    proof_path=write_json(directory/'proof.json',proof);verify_proof(proof_path)
    parent=read_json(c['parent_contract_ref']['path'])
    status=prior.organizer.publish_checked(run,result,file_ref(run/'data_agents/method_context.json'),parent['source_catalog_ref'],file_ref(proof_path))
    stopped=run/'data_agents/stopped.json'
    if stopped.exists():
        stop=read_json(stopped);allowed={str(Path(c['failed_request_ref']['path']).parent.resolve()),*(str(p.parent.resolve()) for p in requests)}
        if stop.get('stage')=='DR' and str(Path(stop.get('audit_path','')).resolve()) in allowed:
            archived=directory/'prior_stopped.json';archived.write_bytes(stopped.read_bytes())
            write_json(directory/'stop_resolution.json',{'prior_stop_ref':file_ref(archived),'resolved_by':file_ref(proof_path)})
            if stopped.resolve().is_relative_to(run.resolve()):stopped.unlink()
    return {**status,'continuation_proof_ref':file_ref(proof_path),'targeted_continuation':True}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--out',required=True);parser.add_argument('--contract',required=True)
    args=parser.parse_args();run=Path(args.out).resolve();lock=run/'.stage.lock'
    fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY);os.close(fd)
    try:
        sf.emit(run,'STAGE_START',stage='organize_target_continuation',model_for_new_calls=sf.MODEL)
        result=execute(run,args.contract);write_json(run/'receipts/organize.json',result)
        sf.emit(run,'STAGE_END',stage='organize_target_continuation',result=result);print(json.dumps(result,ensure_ascii=False))
    except Exception as exc:
        sf.emit(run,'STAGE_ERROR',stage='organize_target_continuation',error_type=type(exc).__name__,error=str(exc));raise
    finally:lock.unlink()


if __name__=='__main__':main()
