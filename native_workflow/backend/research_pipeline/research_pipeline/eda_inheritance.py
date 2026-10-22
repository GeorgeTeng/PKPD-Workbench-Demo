"""Lossless issue inheritance with explicit, verified source ownership."""
import copy,json,re
from pathlib import Path
from ctxcomp.io import digest
from . import context_builder as cb
from .common import read_json,write_json

def require(ok,message):
    if not ok:raise ValueError('EDA inheritance: '+message)

def project(inputs, selected_sources, known_sources, selected_datasets, known_datasets, owners=None):
    result=copy.deepcopy(inputs);h=result['data_handoff']
    original=copy.deepcopy(h)
    registry={};by_hash={};excluded=[];kept={};unknown_positions={}
    def include(record):
        affected=record.get('affected_id')
        # Cross-source conflicts remain relevant if either endpoint is selected.
        text=json.dumps(record,ensure_ascii=False)
        if any(re.search(r'(?<![A-Za-z0-9])'+re.escape(s)+r'(?![A-Za-z0-9])',text)
               for s in selected_sources | selected_datasets):
            return True
        bound_sources=(owners or {}).get(digest(record),set())
        if bound_sources:
            return bool(bound_sources & selected_sources)
        if affected in known_sources:
            return affected in selected_sources
        if affected in known_datasets:
            return affected in selected_datasets
        # Global, requirement-level and ambiguous scope is retained verbatim.
        return True
    def ref(record):
        key=digest(record)
        if key not in by_hash:
            iid='INHERITED_%04d'%(len(registry)+1);by_hash[key]=iid
            registry[iid]=copy.deepcopy(record)
        return by_hash[key]
    for key in ('unknowns','unresolved_items'):
        values=[];kept[key]=[]
        for index,item in enumerate(original.get(key,[])):
            record=item if key=='unknowns' else item['record']
            if not include(record):
                excluded.append({'field':key,'index':index,'affected_id':record.get('affected_id'),
                                 'source_ids':sorted((owners or {}).get(digest(record),set())),
                                 'reason':'Exact request/response lineage or explicit source ID binds this item only to unselected source tables.'})
                continue
            kept[key].append(index)
            iid=ref(record)
            if key=='unknowns':
                unknown_positions.setdefault(iid,[]).append(index)
            else:
                envelope=copy.deepcopy(item);envelope['record']={'inherited_issue_ref':iid}
                values.append(envelope)
        h[key]=( [{'inherited_issue_ref':iid,'original_indices':indices}
                  for iid,indices in unknown_positions.items()] if key=='unknowns' else values)
    h['inherited_issue_registry']=registry
    h['inheritance_encoding']=(
        'INHERITED_ISSUES_1: inherited_issue_registry contains every included issue record in full, once. '
        'Resolve each inherited_issue_ref to its full registry record before interpreting unknowns or unresolved_items. '
        'unknowns.original_indices records exact repeated occurrences in the upstream list, not independent problems. '
        'unresolved_items retains every included envelope, status, history and provenance; only its nested record is referenced. '
        'Source-specific issues outside the explicitly selected tables are retained in the bound scope audit; '
        'all global and ambiguously scoped issues remain visible. No issue has been resolved or weakened.')
    restored_unknowns={index:registry[item['inherited_issue_ref']]
                       for item in h['unknowns'] for index in item['original_indices']}
    assert [restored_unknowns[i] for i in kept['unknowns']]==[original['unknowns'][i] for i in kept['unknowns']]
    restored=[]
    for item in h['unresolved_items']:
        value=copy.deepcopy(item);value['record']=registry[value['record']['inherited_issue_ref']];restored.append(value)
    assert restored==[original['unresolved_items'][i] for i in kept['unresolved_items']]
    for key in original:
        if key not in ('unknowns','unresolved_items'):assert h[key]==original.get(key,[])
    audit={'excluded':excluded,'kept_original_indices':kept,'exact_round_trip':True,
           'original_unknown_occurrences':len(original['unknowns']),
           'original_unresolved_occurrences':len(original['unresolved_items']),
           'visible_unique_issue_records':len(registry),'scoped_unknown_occurrences':len(kept['unknowns']),
           'scoped_unresolved_occurrences':len(kept['unresolved_items']),
           'original_handoff_characters':len(json.dumps(original,ensure_ascii=False)),
           'projected_handoff_characters':len(json.dumps(h,ensure_ascii=False))}
    return result,audit


def prepare(inputs_path,out,manifest_path=None):
    """Derive issue scope from selected bound metadata; never discover files implicitly.

    Optional manifest: version EDA_INHERITANCE_SCOPE_1, dataset_metadata maps
    dataset ID to a file_ref, lineage lists {request:file_ref,response:file_ref}.
    Without lineage, ambiguous/global issues remain; exact duplicates are factored.
    """
    original_ref=cb.file_ref(inputs_path)
    inputs=read_json(inputs_path);h=inputs['data_handoff']
    if 'inherited_issue_registry' in h:
        require(manifest_path is None,'cannot rescope encoded input; use its original inputs')
        require('inheritance_audit_ref' in h,'encoded input lacks bound scope audit')
        cb.check_refs({'audit':h['inheritance_audit_ref']})
        cb.check_refs(read_json(h['inheritance_audit_ref']['path']).get('lineage_refs',{}))
        return Path(inputs_path)
    refs={'original_inputs':original_ref,'projector':cb.file_ref(__file__)}
    selected={f['id'] for f in h['files']}
    require(len(selected)==len(h['files']),'duplicate selected dataset')
    metadata={f['id']:f['metadata_file'] for f in h['files']}
    pairs=[]
    if manifest_path is not None:
        refs['scope_manifest']=cb.file_ref(manifest_path)
        manifest=read_json(manifest_path)
        require(manifest['version']=='EDA_INHERITANCE_SCOPE_1','unknown manifest version')
        supplied=manifest['dataset_metadata']
        require(all(supplied.get(k)==v for k,v in metadata.items()),'selected metadata differs from scope manifest')
        metadata=supplied;pairs=manifest['lineage']
    cb.check_refs(metadata)
    mapping={did:read_json(ref['path'])['metadata']['source_item_id'] for did,ref in metadata.items()}
    refs.update({'metadata:'+k:v for k,v in metadata.items()})
    owners={}
    for n,pair in enumerate(pairs):
        cb.check_refs(pair)
        request=read_json(pair['request']['path']);response=read_json(pair['response']['path'])
        require(digest(request['payload'])==request['request_sha256']==response['request_sha256'],'lineage request digest mismatch')
        item=request['payload']['item_id']
        require(isinstance(item,str) and bool(item),'lineage source ID absent')
        require(response.get('labels') and all(x['item_id']==item for x in response['labels']),'lineage response owner mismatch')
        for finding in response.get('findings',[]):owners.setdefault(digest(finding),set()).add(item)
        refs.update({f'lineage:{n}:{k}':v for k,v in pair.items()})
    result,audit=project(inputs,{mapping[i] for i in selected},set(mapping.values()),selected,set(mapping),owners)
    audit.update(lineage_refs=refs,original_inputs_ref=original_ref,projector_ref=refs['projector'])
    cb.check_refs(refs)
    out=Path(out);out.mkdir(parents=True,exist_ok=False)
    write_json(out/'inheritance_audit.json',audit)
    result['data_handoff'].update(inheritance_audit_ref=cb.file_ref(out/'inheritance_audit.json'),
        inheritance_projector_ref=refs['projector'],inheritance_lineage_refs=refs)
    return write_json(out/'inputs.json',result)
