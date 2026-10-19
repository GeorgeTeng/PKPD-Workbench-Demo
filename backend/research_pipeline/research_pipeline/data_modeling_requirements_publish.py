"""Zero-model publication after auditable inheritance along existing requirement links."""
import argparse
import copy
import json
from pathlib import Path
from . import data_modeling_requirements_repair as repair
from .adequacy import check_ref, file_ref
from .common import read_json, write_json

VERSION = 'MODELING_REQUIREMENTS_EVIDENCE_INHERITANCE_1.0'
ADJUDICATION = 'MODELING_REQUIREMENTS_HOST_ADJUDICATION_1.0'


def adjudicate(raw, path, raw_ref, sources):
    """Apply only the explicitly supplied host decisions; never infer scientific repairs."""
    if path is None: return copy.deepcopy(raw), []
    supplied=read_json(path)
    if supplied.get('version')!=ADJUDICATION or supplied.get('raw_response_ref')!=raw_ref:
        repair.m.fail('Adjudication must bind the exact original response')
    check_ref(raw_ref)
    candidate=copy.deepcopy(raw); audit=[]
    for index, operation in enumerate(supplied['operations']):
        pointer=operation['path']
        if not pointer.startswith('/') or pointer.split('/')[1] not in {'requirements','branches','data_links','objective_assignments','findings'}:
            repair.m.fail('Adjudication path outside planning fields')
        keys=[k.replace('~1','/').replace('~0','~') for k in pointer[1:].split('/')]
        node=candidate
        for key in keys[:-1]: node=node[int(key)] if isinstance(node,list) else node[key]
        key=int(keys[-1]) if isinstance(node,list) else keys[-1]
        if node[key]!=operation['before']: repair.m.fail('Adjudication before value differs: '+pointer)
        ids=operation['evidence_source_ids']
        if not operation['reason'].strip() or not ids or not repair.m.unique(ids,'adjudication sources')<=sources.keys():
            repair.m.fail('Adjudication requires reason and actual bound source citations')
        node[key]=copy.deepcopy(operation['after'])
        audit.append({'operation':'EXPLICIT_HOST_ADJUDICATION','index':index,'path':pointer,
            'before':operation['before'],'after':operation['after'],'reason':operation['reason'],
            'evidence':[{'source':s,'quote':sources[s]} for s in ids]})
    return candidate,audit


def inherit(raw, knowledge):
    """Append only missing citations already present on valid, explicitly linked needs."""
    candidate = copy.deepcopy(raw); audit = []; needs = {n['id']: n for n in raw['requirements']}
    repair.m.unique([n['id'] for n in raw['requirements']], 'need IDs')
    valid = {}
    for key, need in needs.items():
        material = {k: v for k, v in need.items() if k != 'evidence_source_ids'}
        material['evidence'] = [{'source': s, 'quote': 'inheritance checks source identity; full quotes checked by materialize'} for s in need['evidence_source_ids']]
        try: repair.m.mp.validate_requirements([material], knowledge)
        except Exception: valid[key] = False
        else: valid[key] = True
    for branch, approaches in candidate['branches'].items():
        for ai, approach in enumerate(approaches):
            target = f'/branches/{branch}/{ai}/evidence_source_ids'
            linked = [(key, needs[key]) for key in approach['requirement_ids'] if key in needs and valid[key]]
            wanted = {'method:'+pid for pid in approach['method_profile_ids']}
            missing = wanted-set(approach['evidence_source_ids'])
            need_project = not any(s.startswith(('main:', 'rule:')) for s in approach['evidence_source_ids'])
            for key, need in linked:
                for ei, source in enumerate(need['evidence_source_ids']):
                    method_ok = source in missing and source.removeprefix('method:') in need['method_profile_ids']
                    project_ok = need_project and source.startswith(('main:', 'rule:'))
                    if (method_ok or project_ok) and source not in approach['evidence_source_ids']:
                        approach['evidence_source_ids'].append(source)
                        audit.append({'operation': 'INHERIT_EXISTING_LINKED_REQUIREMENT_EVIDENCE',
                            'approach_id': approach['id'], 'to_path': target, 'source': source,
                            'from_requirement_id': key,
                            'from_path': '/requirements/'+str(next(i for i,n in enumerate(raw['requirements']) if n['id']==key))+'/evidence_source_ids/'+str(ei)})
                        missing.discard(source)
    return candidate, audit


def diagnose(candidate, payload, sources, knowledge):
    """Enumerate independent visible predicates; original complete validator remains authoritative."""
    faults = []
    def bad(code, target, detail): faults.append({'code': code, 'target': target, 'detail': detail})
    try: repair.m.d.validate_schema(candidate, repair.response_schema(payload))
    except Exception as exc: bad('SCHEMA', 'response', str(exc)); return faults
    needs = {n['id']: n for n in candidate['requirements']}
    links = {r['item_id']: r for r in candidate['data_links']}
    datasets = {r['item_id']: r for r in payload['data_profiles']}
    def citation_check(row, target):
        for s in row['evidence_source_ids']:
            if s not in sources: bad('UNKNOWN_SOURCE', target, s)
        if len(row['evidence_source_ids']) != len(set(row['evidence_source_ids'])): bad('DUPLICATE_SOURCE', target, '')
    for n in needs.values():
        citation_check(n, n['id'])
        test = {k: v for k,v in n.items() if k != 'evidence_source_ids'}
        test['evidence'] = [{'source': s, 'quote': sources.get(s, '')} for s in n['evidence_source_ids']]
        try: repair.m.mp.validate_requirements([test], knowledge)
        except Exception as exc: bad('METHOD_REQUIREMENT_CONTRACT', n['id'], str(exc))
        if not set(n['method_profile_ids']) <= repair.m.METHODS[n['analysis']]: bad('METHOD_WRONG_ANALYSIS', n['id'], n['method_profile_ids'])
    for pid in ('MP004', 'MP009'):
        if not any(n['origin']=='METHOD_CANDIDATE' and pid in n['method_profile_ids'] for n in needs.values()):
            bad('MISSING_FORMAL_METHOD_CANDIDATE', pid, 'No linked METHOD_CANDIDATE requirement; host cannot change origin or add a scientific need')
    for link in links.values():
        citation_check(link, link['item_id'])
        if not any(s==link['item_id'] or s.startswith(link['item_id']+':') for s in link['evidence_source_ids']): bad('MISSING_ITEM_EVIDENCE', link['item_id'], '')
        for nid in link['requirement_ids']:
            if nid not in needs: bad('UNKNOWN_NEED', link['item_id'], nid)
    for branch, rows in candidate['branches'].items():
        for a in rows:
            target=a['id']; citation_check(a,target)
            linked=[needs[k] for k in a['requirement_ids'] if k in needs]
            covered={pid for n in linked for pid in n['method_profile_ids']}
            for pid in a['method_profile_ids']:
                if pid not in covered: bad('METHOD_WITHOUT_LINKED_NEED',target,pid)
                if 'method:'+pid not in a['evidence_source_ids']: bad('METHOD_EVIDENCE_NOT_INHERITABLE',target,pid)
            if not any(s.startswith(('main:','rule:')) for s in a['evidence_source_ids']): bad('PROJECT_EVIDENCE_NOT_INHERITABLE',target,'')
            for n in linked:
                if n['analysis'] not in (branch,'SHARED'): bad('UNRELATED_NEED_ANALYSIS',target,n['id'])
                if n['analysis']!='SHARED' and not any(n['id'] in links.get(i,{}).get('requirement_ids',[]) for i in a['dataset_ids']): bad('UNRELATED_DATASET_NEED',target,n['id'])
            for item in a['dataset_ids']:
                if item not in datasets: bad('UNKNOWN_DATASET',target,item)
                if not set(links.get(item,{}).get('requirement_ids',[])) & {n['id'] for n in linked if n['analysis']==branch}:
                    bad('MISSING_SAME_ANALYSIS_DATA_LINK',target,item)
            sp=set().union(*(repair.m.species(datasets[i].get('species','')) for i in a['dataset_ids'] if i in datasets))
            if len(sp)>1: bad('CROSS_SPECIES_APPROACH',target,sorted(sp))
    for row in candidate['objective_assignments']:
        linked=set(row['requirement_ids'])
        named=repair.m.species(sources.get(row['source'],''))
        related=set().union(*(repair.m.species(datasets[i].get('species','')) for i,link in links.items()
            if i in datasets and set(link['requirement_ids'])&linked))
        if len(named)==1 and related and named.isdisjoint(related): bad('OBJECTIVE_WRONG_SPECIES',row['source'],sorted(related))
        if not linked<=needs.keys(): bad('OBJECTIVE_UNKNOWN_NEED',row['source'],sorted(linked-needs.keys()))
    targets=set(needs)|set(datasets)|set(repair.m.TASKS)|{a['id'] for rows in candidate['branches'].values() for a in rows}
    targets.update(v for k,v in payload['context_sources'].items() if k.endswith('/id'))
    for row in candidate['findings']:
        if row['affected_id'] not in targets: bad('FINDING_STALE_TARGET',row['code'],row['affected_id'])
    return faults


def derive_saved(parent_run, adjudication_path=None):
    parent=Path(parent_run).resolve()
    bindings=read_json(parent/'bindings.json')
    for ref in bindings['inputs'].values(): check_ref(ref)
    payload,schema,sources,knowledge,original=[read_json(parent/(n+'.json')) for n in ('payload','schema','source_catalog','method_context','original')]
    request=read_json(parent/'request.json')
    if request!=repair.m.governed_request(payload,schema): repair.m.fail('Saved governed request changed')
    matches=[]
    for path in (parent/'data_agents/audit/DR').glob('*/response.json'):
        if read_json(path).get('request_sha256')==request['request_sha256']:
            if read_json(path.parent/'request.json')!=request: repair.m.fail('Model call request differs')
            matches.append(path)
    if len(matches)!=1: repair.m.fail('Require one immutable raw model response')
    raw=read_json(matches[0]); repair.m.d.validate_schema(raw,schema)
    ruled,adjudication_audit=adjudicate(raw,adjudication_path,file_ref(matches[0]),sources)
    repair.m.d.validate_schema(ruled,schema)
    candidate,audit=inherit(ruled,knowledge)
    faults=diagnose(candidate,payload,sources,knowledge)
    derived=None; materialization=[]
    try: derived,materialization=repair.materialize(candidate,payload,sources,knowledge,original)
    except Exception as exc: faults.append({'code':'ORIGINAL_V21_VALIDATOR','target':'response','detail':str(exc)})
    if faults: derived=None
    refs={n:file_ref(parent/(n+'.json')) for n in ('bindings','payload','schema','source_catalog','method_context','original','request')}
    refs.update(raw_response=file_ref(matches[0]),publisher_code=file_ref(__file__),validator_code=file_ref(repair.__file__))
    input_checks=None
    if adjudication_path is not None:
        refs['adjudication']=file_ref(adjudication_path)
        input_ref=read_json(adjudication_path).get('input_checks_ref')
        if input_ref is not None:
            check_ref(input_ref);refs['input_checks']=input_ref;input_checks=read_json(input_ref['path'])
    return {'status':'VALID' if derived is not None else 'UNRESOLVED','candidate':candidate,'derived':derived,
        'input_checks':input_checks,'adjudication_audit':adjudication_audit,'inheritance_audit':audit,'materialization_audit':materialization,'faults':faults,'refs':refs}


def publish(parent_run,out,adjudication_path=None):
    parent,out=Path(parent_run).resolve(),Path(out).resolve()
    if parent==out or parent in out.parents or out in parent.parents: repair.m.fail('Use isolated publication directory')
    if out.exists() and any(out.iterdir()): repair.m.fail('Publication output already exists')
    result=derive_saved(parent,adjudication_path)
    if result['status']!='VALID': repair.m.fail('Unresolved saved candidate: '+json.dumps(result['faults'],ensure_ascii=False))
    refs=result['refs']
    for ref in refs.values(): check_ref(ref)
    for name,key in [('inherited_candidate','candidate'),('derived','derived'),('adjudication_audit','adjudication_audit'),('inheritance_audit','inheritance_audit'),('materialization_audit','materialization_audit')]: write_json(out/(name+'.json'),result[key])
    attribution='HOST_ADJUDICATED_DERIVED' if adjudication_path is not None else 'HOST_INHERITED_ONLY_EXISTING_LINKED_REQUIREMENT_EVIDENCE'
    proof={'version':VERSION,'refs':refs,'attribution':attribution,
        'candidate_ref':file_ref(out/'inherited_candidate.json'),'derived_ref':file_ref(out/'derived.json'),
        'adjudication_audit_ref':file_ref(out/'adjudication_audit.json'),
        'inheritance_audit_ref':file_ref(out/'inheritance_audit.json'),'materialization_audit_ref':file_ref(out/'materialization_audit.json'),
        'model_calls':0}
    write_json(out/'proof.json',proof)
    bindings=read_json(parent/'bindings.json');write_json(out/'bindings.json',bindings)
    # Renderer-compatible evidence scope is copied exactly, never re-extracted.
    write_json(out/'payload.json',read_json(parent/'payload.json'))
    permissions=read_json(bindings['inputs']['permissions.json']['path'])['access']
    links={r['item_id']:r for r in result['derived']['data_links']}
    final={'schema_version':VERSION,**result['derived'],
        'access':[{**copy.deepcopy(a),'requirement_ids':links.get(a['item_id'],{}).get('requirement_ids',[])} for a in permissions],
        'provenance':{'attribution':attribution,'proof_ref':file_ref(out/'proof.json'),'original_response_ref':refs['raw_response'],
            'historical_findings_ref':file_ref(parent/'historical_findings.json'),'source_scope_ref':file_ref(parent/'build.json')},
        'scientific_approval':False,'can_enter_qc':False,'fit_ready':False}
    if result['input_checks'] is not None:
        final['input_checks']=copy.deepcopy(result['input_checks'])
        final['provenance']['input_checks_ref']=refs['input_checks']
    staged=write_json(out/'staged/requirements.json',final);staged.replace(out/'requirements.json')
    return final


def verify_proof(path):
    proof=read_json(path)
    if proof['version']!=VERSION or proof['model_calls']!=0: repair.m.fail('Invalid inheritance proof')
    for ref in list(proof['refs'].values())+[proof[k] for k in ('candidate_ref','derived_ref','adjudication_audit_ref','inheritance_audit_ref','materialization_audit_ref')]: check_ref(ref)
    expected='HOST_ADJUDICATED_DERIVED' if 'adjudication' in proof['refs'] else 'HOST_INHERITED_ONLY_EXISTING_LINKED_REQUIREMENT_EVIDENCE'
    if proof['attribution']!=expected: repair.m.fail('False derivation attribution')
    result=derive_saved(Path(proof['refs']['request']['path']).parent,proof['refs'].get('adjudication',{}).get('path'))
    if result['status']!='VALID': repair.m.fail('Inheritance no longer validates')
    for name,key in [('candidate','candidate_ref'),('derived','derived_ref'),('adjudication_audit','adjudication_audit_ref'),('inheritance_audit','inheritance_audit_ref'),('materialization_audit','materialization_audit_ref')]:
        if result[name]!=read_json(proof[key]['path']): repair.m.fail('Inheritance replay differs')
    return result['derived']


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--parent-run',required=True);p.add_argument('--out');p.add_argument('--adjudication');a=p.parse_args()
    result=publish(a.parent_run,a.out,a.adjudication) if a.out else derive_saved(a.parent_run,a.adjudication)
    print(json.dumps({'status':result.get('status','PUBLISHED_UNAPPROVED'),'faults':result.get('faults',[]),'model_calls':0},ensure_ascii=False))


if __name__=='__main__':main()
