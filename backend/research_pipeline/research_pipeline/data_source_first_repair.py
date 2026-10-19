"""One source-bound citation append; all historical facts and findings are immutable."""
import copy
from pathlib import Path
from ctxcomp.io import digest
from . import data_source_first_workflow as sf
from . import data_label_citation_patch as cp
from . import data_agents as d
from .adequacy import file_ref
from .common import read_json,write_json


def repair(run,*,generator=None):
    run=Path(run);manifest,verified=sf.verify_run(run)
    if (run/'repaired_document.json').exists():sf.fail('Repair already published; do not resample a completed correction')
    spec=read_json(manifest['bindings']['repair_spec']['path'])
    old_request=read_json(spec['failed_request_ref']['path']);old=read_json(spec['failed_response_ref']['path'])
    item_id=old_request['payload']['item_id'];inv=read_json(run/'inventory.json')
    if read_json(run/'source_view.json')['pending_item_ids']!=[item_id]:sf.fail('Repair is limited to the one explicitly pending item')
    pending=read_json(run/'pending_repairs.json')['items']
    if len(pending)!=1 or pending[0]['item_id']!=item_id:sf.fail('Unexpected pending repair scope')
    legacy=read_json(read_json(run/'legacy_import.json')['historical_requirements_ref']['path'])
    directory=run/'audit/repair_validation'
    invpath=write_json(directory/'inventory.json',{**copy.deepcopy(inv),'items':[i for i in inv['items'] if i['id']==item_id]})
    reqpath=write_json(directory/'historical_requirements.json',{**copy.deepcopy(legacy),'inventory':file_ref(invpath),
        'access':[a for a in legacy['access'] if a['item_id']==item_id]})
    correction={'source_main_ref':verified['main_ref'],'corrections':[copy.deepcopy(spec)]}
    correction_ref=file_ref(write_json(run/'citation_patch_manifest.json',correction))
    # Frozen prior request fields are audit context, not instructions for a new extraction.
    payload=copy.deepcopy(old_request['payload'])
    for key in ('stage','agent','policy_version','processing_rules','response_schema','governance'):
        payload.pop(key,None)
    payload['instructions']=spec['instruction']
    payload['contract_correction']={**copy.deepcopy(spec),'manifest_ref':correction_ref,
        'prior_rejected_response':copy.deepcopy(old),'classification':'NON_EVIDENCE_LOCKED_CANDIDATE'}
    module=sf.private_module();calls=[]
    def patch_call(_,stage,current,schema,check=None,**options):
        if stage!='DC-label' or check is None or current['item_id']!=item_id or current['page']!=spec['page']:
            sf.fail('Unexpected repair page or missing original host checker')
        if current['source_units']!=payload['source_units']:sf.fail('Repair source page changed')
        def actual(out,stage,body,schema,**options):
            return sf.invoke(out,stage,body,schema,generator=generator,check=options['check'])
        result=cp.invoke(actual,run,stage,payload,check=check)
        calls.append(result)
        return result
    module.invoke=patch_call
    module.label(directory,manifest['bindings']['main']['path'],invpath,reqpath,directory/'checked.json',model=sf.MODEL)
    if len(calls)!=1:sf.fail('Citation repair must make exactly one narrowly scoped call')
    result=calls[0]
    expected=copy.deepcopy(old);expected['request_sha256']=result['request_sha256']
    c=spec['response_constraint'];li,vi=c['label_index'],c['stated_value_index']
    added=result['labels'][li]['stated_values'][vi]['evidence'][-1]
    expected['labels'][li]['stated_values'][vi]['evidence'].append(added)
    if result!=expected:sf.fail('Citation repair changed a locked fact, label or finding')
    proof=run/'data_agents/citation_patches'/result['request_sha256']/'proof.json';cp.verify_proof(proof)
    write_json(run/'repaired_document.json',{'labels':result['labels'],'findings':result['findings'],
        'provenance':{'original_model':'gpt-6-sol','citation_patch_model':sf.MODEL,'proof_ref':file_ref(proof)},
        'scientific_approval':False})
    # Do not alter the old run, cache or response; this is a separately attributed derived candidate.
    sf.build_source_view(run)
    sf.bind_outputs(run,('repaired_document.json','citation_patch_manifest.json','source_view.json'))
    return {'status':'CITATION_REPAIRED_AND_ORIGINAL_CHECKS_PASSED','item_id':item_id,
        'model':sf.MODEL,'proof_ref':file_ref(proof),'locked_stated_values':len(old['labels'][li]['stated_values']),
        'locked_findings':len(old['findings']),'can_enter_qc':False,'scientific_approval':False}
