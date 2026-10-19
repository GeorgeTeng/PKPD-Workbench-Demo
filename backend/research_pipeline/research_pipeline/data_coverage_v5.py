"""Bounded, resumable coverage runtime. No automatic retry or scientific release.

Frozen v4 evidence is read through its original materializer; only new files are
written. Each provider attempt is budgeted before dispatch and durably accounted
for even if validation fails. Checkpoints are derived caches, never approval.
"""
import copy
import json
import math
import os
import time
from pathlib import Path
from uuid import uuid4
from ctxcomp.io import digest
from . import data_agents as d, data_requirement_plan_v4 as planning
from .adequacy import file_ref, check_ref
from .common import read_json, write_json, utcnow

VERSION = 'COVERAGE_FACTS_5.0'
MODEL = 'gpt-6-sol'
BUDGET_SECONDS = 1500.0
RESERVE_SECONDS = 20.0
GATES = dict(scientific_approval=False, can_enter_qc=False, fit_ready=False)
_VERIFIED_IMPORTS = {}
_VERIFIED_BUILDS = set()


def facts():
    from . import data_coverage_facts_v5
    return data_coverage_facts_v5


def fail(message):
    raise ValueError('COVERAGE_V5_RUNTIME: '+message)


def inherited_budget(value):
    elapsed = value.get('elapsed_seconds')
    if not isinstance(elapsed,(int,float)) or not math.isfinite(elapsed) or elapsed < 0:
        fail('Missing or invalid inherited elapsed time')
    counts=[value.get(k) for k in ('calls','prior_calls')]
    if any(not isinstance(x,int) or isinstance(x,bool) or x<0 for x in counts):
        fail('Invalid inherited call counts')
    return float(elapsed),sum(counts)


def admission(ledger, checks, *, remaining_seconds=None):
    remaining=(BUDGET_SECONDS-ledger['elapsed_seconds'] if remaining_seconds is None else remaining_seconds)
    rates=[s['seconds']/max(1,s['checks']) for s in ledger.get('samples',[]) if s.get('checks') and s.get('seconds',0)>0]
    predicted=max(30.0,checks*max([1.5]+rates)*1.20)
    return {'allowed':remaining >= predicted+RESERVE_SECONDS,
            'remaining_seconds':max(0.0,remaining),'predicted_seconds':predicted,
            'reserve_seconds':RESERVE_SECONDS,'checks':checks}


def emit(out,event,**fields):
    path=Path(out)/'events.jsonl';path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('a',encoding='utf-8') as stream:
        stream.write(json.dumps({'at':utcnow(),'event':event,**fields},ensure_ascii=False)+'\n')


def _diagnostics(directory):
    directory=Path(directory);result={'requested_model':None,'served_model':None,'served_models':[],'usage':None,'refs':{}}
    for name in ('call.json','events.jsonl','progress.json'):
        p=directory/name
        if p.exists():result['refs'][name]=file_ref(p)
    if (directory/'call.json').exists():
        call=read_json(directory/'call.json')
        result['requested_model']=call.get('requested_model')
        result['served_model']=call.get('served_model')
        if 'served_models' in call:
            result['served_models']=copy.deepcopy(call['served_models'])
            reported=call['served_models']
            result['served_model']=(reported[0] if isinstance(reported,list) and len(reported)==1
                and isinstance(reported[0],str) and reported[0].strip()
                and call.get('served_model') in (None,reported[0]) else None)
        result['provider']=call.get('provider');result['provider_status']=call.get('status')
    if (directory/'events.jsonl').exists():
        for line in (directory/'events.jsonl').read_text(encoding='utf-8').splitlines():
            try:event=json.loads(line)
            except ValueError:continue
            if event.get('type')=='turn.completed':result['usage']=event.get('usage')
    return result


def request_pause(out):
    p=Path(out)/'PAUSE';p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text('Pause at next safe provider boundary.\n',encoding='utf-8')
    return {'status':'PAUSE_REQUESTED','path':str(p.resolve())}


def governed_request(payload):
    class Capture(Exception):pass
    caller=planning.sf.private_module()
    def capture(p):
        exc=Capture();exc.request=d.governed_request(facts().transport_payload(p));raise exc
    caller.governed_request=capture
    try:caller.invoke(Path('.'),'DC-review',payload,facts().response_schema(payload),model=MODEL)
    except Capture as exc:return exc.request
    fail('Request capture unexpectedly reached provider')


def _checks(payload):
    return (len(payload['facts']) + sum(len(x) for x in payload.get('counterevidence_targets', {}).values())
            if 'facts' in payload else sum(len(u['criteria']) for u in payload['units']))


def import_v4(directory):
    """Read-only replay of accepted old parts, including original import proofs."""
    from . import data_coverage_v4 as old, data_coverage_v4_repair as repair
    directory=Path(directory).resolve();built=read_json(directory/'build.json')
    planning.check_refs(built['bindings'])
    plan=planning.verify_plan(built['bindings']['plan']['path'])
    replay=old.build(plan,Path(built['bindings']['source_view']['path']).parent)
    replay['bindings']['plan']=built['bindings']['plan']
    if 'repair_parent_build' in built['bindings']:replay=repair.replay_build(built,replay)
    if replay!=built:fail('Frozen v4 build cannot be replayed')
    ledger=read_json(directory/'model_budget.json')
    if ledger['build_sha256']!=digest(built):fail('Historical budget/build mismatch')
    seconds,calls=inherited_budget(ledger)
    accepted=[];records=[]
    for payload in built['payloads']:
        part=payload['part_id'];imported=repair.load_imported_response(directory,built,payload)
        if imported:
            raw,receipt=imported;refs={'import_receipt':receipt};origin='ORIGINAL_IMPORTED_MODEL'
            spec=read_json(receipt['path'])['parent']
            diagnostic=_diagnostics(Path(spec['response']['path']).parent/'model_call')
        else:
            request=old.governed_request(payload)
            original_request=directory/'requests'/(part+'.json')
            if read_json(original_request)!=request:fail('Historical request changed')
            caches=[]
            for path in (directory/part/'data_agents/kept').glob('*.json'):
                candidate=read_json(path)
                if candidate.get('request_sha256')==request['request_sha256']:caches.append((path,candidate))
            if not caches:continue
            if len(caches)!=1:fail('Ambiguous historical checked cache')
            path,raw=caches[0]
            audits=[p for p in (directory/part/'data_agents/audit/DC-review').glob('*/response.json') if read_json(p)==raw]
            if len(audits)!=1:fail('Historical cache lacks unique original raw response')
            original=audits[0]
            if read_json(original.with_name('request.json'))!=request:fail('Historical raw request mismatch')
            refs={'cache':file_ref(path),'raw':file_ref(original),'request':file_ref(original.with_name('request.json'))}
            metadata=original.parent/'model_call/call.json'
            if metadata.exists():refs['model_call']=file_ref(metadata)
            origin='ORIGINAL_SOL_MODEL'
            diagnostic=_diagnostics(original.parent/'model_call')
        matches=old.materialize(raw,payload)
        accepted.extend(matches)
        records.append({'part_id':part,'matches_sha256':digest(matches),'provenance':origin,'refs':refs,'model_record':diagnostic})
    semantic_path=directory/'root_semantic_findings.json'
    semantic=read_json(semantic_path).get('findings',[]) if semantic_path.exists() else []
    refs={'build':file_ref(directory/'build.json'),'budget':file_ref(directory/'model_budget.json'),
          'materializer':file_ref(old.__file__),'importer':file_ref(repair.__file__)}
    if semantic_path.exists():refs['semantic_findings']=file_ref(semantic_path)
    return {'directory':str(directory),'refs':refs,'parts':records,'accepted_matches':accepted,
            'semantic_rechecks':semantic,'prior_model_seconds':seconds,'prior_model_calls':calls}


def _store_build(built,out):
    out=Path(out).resolve()
    if out.exists() and any(out.iterdir()):fail('Use an empty new output directory')
    built['bindings']['runtime']=file_ref(__file__)
    built['bindings']['facts_runtime']=file_ref(facts().__file__)
    sizes=[]
    for p in built['payloads']:
        request=governed_request(p);size=len(json.dumps(request,ensure_ascii=False))
        if size>d.REQUEST_BUDGET:fail(f"{p['part_id']} exceeds transport budget: {size}")
        write_json(out/'requests'/(p['part_id']+'.json'),request)
        sizes.append({'part_id':p['part_id'],'checks':_checks(p),'request_chars':size})
    write_json(out/'build.json',built)
    write_json(out/'manifest.json',{'build_ref':file_ref(out/'build.json'),
        'requests':{p['part_id']:file_ref(out/'requests'/(p['part_id']+'.json')) for p in built['payloads']}})
    write_json(out/'preflight.json',{'parts':sizes,'model_calls':0,'new_calls_model':MODEL})
    _ledger(out,built)
    rebuild_checkpoint(out)
    return built


def prepare(plan_path,source_run,out,import_from=None):
    plan=planning.verify_plan(plan_path)
    imported=import_v4(import_from) if import_from else None
    built=facts().build(plan,source_run,accepted_matches=imported['accepted_matches'] if imported else (),
        semantic_rechecks=imported['semantic_rechecks'] if imported else ())
    built['bindings']['plan']=file_ref(plan_path)
    built['runtime_recipe']={'source_run':str(Path(source_run).resolve()),'kind':'INITIAL'}
    if imported:
        built['historical_import']=imported
        built['prior_model_seconds']=imported['prior_model_seconds'];built['prior_model_calls']=imported['prior_model_calls']
    return _store_build(built,out)


def _load(out):
    out=Path(out);manifest=read_json(out/'manifest.json');planning.check_refs(manifest)
    built=read_json(out/'build.json');planning.check_refs(built['bindings'])
    if 'historical_import' in built:
        saved=built['historical_import'];planning.check_refs(saved['refs']);planning.check_refs(saved['parts'])
        key=digest(saved)
        if key not in _VERIFIED_IMPORTS:
            if import_v4(saved['directory'])!=saved:fail('Historical import no longer replays')
            _VERIFIED_IMPORTS[key]=True
    for p in built['payloads']:
        if read_json(out/'requests'/(p['part_id']+'.json'))!=governed_request(p):fail('Prepared request drift')
    if digest(built) not in _VERIFIED_BUILDS:
        recipe=built['runtime_recipe']
        if recipe['kind']=='INITIAL':
            plan=planning.verify_plan(built['bindings']['plan']['path'])
            imported=built.get('historical_import')
            replay=facts().build(plan,recipe['source_run'],accepted_matches=imported['accepted_matches'] if imported else (),
                semantic_rechecks=imported['semantic_rechecks'] if imported else ())
            replay['bindings']['plan']=built['bindings']['plan'];replay['runtime_recipe']=recipe
            if imported:
                replay['historical_import']=imported
                replay['prior_model_seconds']=imported['prior_model_seconds'];replay['prior_model_calls']=imported['prior_model_calls']
        elif recipe['kind']=='SEARCH':
            parent=verify_result(built['bindings']['parent_coverage']['path'])
            parent_build=_load(Path(parent['provenance']['build_ref']['path']).parent)
            budget=read_json(built['bindings']['parent_budget']['path'])
            if budget['build_sha256']!=digest(parent_build):fail('Frozen parent ledger mismatch')
            replay=facts().build_search(parent_build,parent['matches'],recipe['targets'])
            replay['bindings']['parent_coverage']=built['bindings']['parent_coverage']
            replay['bindings']['parent_budget']=built['bindings']['parent_budget']
            replay['prior_model_seconds'],replay['prior_model_calls']=inherited_budget(budget)
            replay['runtime_recipe']=recipe
        else:fail('Unknown runtime build recipe')
        replay['bindings']['runtime']=file_ref(__file__);replay['bindings']['facts_runtime']=file_ref(facts().__file__)
        # Tuples used by the pure planner serialize as JSON arrays; compare the
        # exact canonical JSON contract, not Python tuple/list representation.
        if digest(replay)!=digest(built):fail('Prepared facts do not replay from bound source/plan')
        _VERIFIED_BUILDS.add(digest(built))
    return built


def _ledger(out,built, *, write=True):
    """Reconstruct accounting from immutable call records, not checkpoint totals."""
    attempts=[read_json(p) for p in sorted((Path(out)/'attempts').glob('*.json'))]
    elapsed=float(built.get('prior_model_seconds',0));calls=0;samples=[]
    for a in attempts:
        if a['build_sha256']!=digest(built):fail('Attempt belongs to another build')
        if a.get('provider_started'):
            calls+=1
            # Unknown crash duration consumes its reserved timeout, never resets it.
            seconds=a.get('elapsed_seconds',a['timeout_seconds'])
            if not isinstance(seconds,(int,float)) or not math.isfinite(seconds) or seconds<0:fail('Invalid call elapsed time')
            elapsed+=seconds
            if a.get('elapsed_seconds') is not None:samples.append({'seconds':seconds,'checks':a['checks']})
    result={'build_sha256':digest(built),'elapsed_seconds':elapsed,'calls':calls,
            'prior_calls':built.get('prior_model_calls',0),'samples':samples}
    previous=Path(out)/'model_budget.json'
    if previous.exists():
        prior=read_json(previous)
        if prior['build_sha256']!=digest(built):fail('Budget belongs to another build')
        if prior['elapsed_seconds']>elapsed+0.000001 or prior['calls']>calls:
            fail('Recorded budget cannot decrease; missing or changed attempt history')
    if write:write_json(Path(out)/'model_budget.json',result)
    return result


def _accepted(out,built):
    result={};receipts=[]
    for p in built['payloads']:
        path=Path(out)/'accepted'/(p['part_id']+'.json')
        if not path.exists():continue
        rec=read_json(path);planning.check_refs(rec['refs'])
        if rec['build_sha256']!=digest(built):fail('Accepted receipt belongs to another build')
        request=read_json(Path(out)/'requests'/(p['part_id']+'.json'))
        raw=read_json(rec['refs']['raw']['path'])
        if raw['request_sha256']!=request['request_sha256'] or read_json(rec['refs']['request']['path'])!=request:
            fail('Accepted raw request mismatch')
        attempt=read_json(Path(out)/'attempts'/(rec['attempt_id']+'.json'))
        if attempt['part_id']!=p['part_id'] or attempt['build_sha256']!=digest(built):fail('Accepted attempt binding changed')
        _check_duration(attempt)
        matches=facts().materialize(raw,p,built['catalog'])
        if digest(matches)!=rec['matches_sha256']:fail('Accepted derivation changed')
        result[p['part_id']]=matches;receipts.append(file_ref(path))
    return result,receipts


def rebuild_checkpoint(out, *, write=True):
    """Recover stale checkpoint from replayed accepted receipts. Never dispatch."""
    out=Path(out);built=_load(out);accepted,receipts=_accepted(out,built)
    assembled=facts().assemble_matches(built,accepted)
    ledger=_ledger(out,built,write=write)
    pending=[p['part_id'] for p in built['payloads'] if p['part_id'] not in accepted]
    result={'version':VERSION,'complete':bool(assembled['complete'] and not pending),
        'status':'COMPLETE_FACTS' if assembled['complete'] and not pending else 'PARTIAL_COVERAGE_CHECKPOINT',
        'planning_sha256':built['planning_sha256'],'bindings':built['bindings'],
        'matches':assembled['matches'],'scopes':built['scopes'],'pending_parts':pending,
        'pending_checks':assembled.get('pending',[]),'model_budget':ledger,
        'routing_not_assessed':built.get('routing_not_assessed',[]),
        'scoped_exclusions':assembled.get('scoped_exclusions',built.get('scoped_exclusions',[])),
        'upstream_missing_information':built.get('upstream_missing_information',[]),
        'pending_global_gates':built.get('pending_global_gates',[
            'DC006_METHOD_CONDITIONS','DC007_GLOBAL_CONFLICTS','DC008_ADEQUACY_HUMAN_REVIEW','G008_UNRESOLVED_CLOSURE']),
        'assessment_scope':'LOCAL_SOURCE_FACTS_ONLY; NOT_FULL_DC_ADEQUACY_OR_RELEASE',
        'provenance':{'build_ref':file_ref(out/'build.json'),'accepted_receipts':receipts,
            'attempt_refs':[file_ref(p) for p in sorted((out/'attempts').glob('*.json'))],
            'historical_import':built.get('historical_import',{}).get('parts',[]),
            'new_calls_requested_model':MODEL},**GATES}
    result['pending_searches']=[{'unit_id':m['unit_id'],'item_ids':m.get('search_item_ids',[]),
        'reason':m.get('search_reason',''),'lookup_query':m.get('lookup_query','')} for m in result['matches']
        if m.get('search_item_ids') or m.get('lookup_query')]
    result['open_semantic_rechecks']=built.get('historical_import',{}).get('semantic_rechecks',[])
    historical=built.get('historical_import',{})
    old_matches=historical.get('accepted_matches',[])
    result['retained_history']={'units':len(old_matches),'criteria':sum(len(m['criteria']) for m in old_matches),
        'source_refs':historical.get('refs',{}),'prior_model_seconds':historical.get('prior_model_seconds',0),
        'pending_searches':[{'unit_id':m['unit_id'],'item_ids':m.get('search_item_ids',[]),'reason':m.get('search_reason','')}
            for m in old_matches if m.get('search_item_ids')]}
    flagged={(x['unit_id'],x['criterion_id']) for x in result['open_semantic_rechecks']}
    result['prior_judgments']=[{'unit_id':m['unit_id'],'criterion':copy.deepcopy(c),
        'scope':'HISTORICAL_MODEL_JUDGMENT_PENDING_RECHECK_NOT_CURRENT_VALIDATION'}
        for m in old_matches for c in m['criteria'] if (m['unit_id'],c['id']) in flagged]
    attempts=[read_json(p) for p in sorted((out/'attempts').glob('*.json'))]
    result['part_states']={p['part_id']:('ACCEPTED' if p['part_id'] in accepted else next(
        (a['status'] for a in reversed(attempts) if a['part_id']==p['part_id']),'PENDING')) for p in built['payloads']}
    boundary=read_json(out/'boundary.json') if (out/'boundary.json').exists() else {}
    if boundary and boundary.get('build_sha256')!=digest(built):fail('Boundary belongs to another build')
    result['stop_reason']=('COMPLETE' if result['complete'] else
        'PAUSED' if (out/'PAUSE').exists() else
        'BUDGET_EXHAUSTED' if ledger['elapsed_seconds']>=BUDGET_SECONDS and not (out/'batch_binding.json').exists() else
        boundary.get('reason','PREPARED_OR_PENDING'))
    if write:
        write_json(out/'checkpoint.json',result)
        if result['complete']:write_json(out/'coverage.json',result)
    return result


def _boundary(out,built,reason,**details):
    write_json(Path(out)/'boundary.json',{'build_sha256':digest(built),'reason':reason,**details})


def _alive(pid):
    if not isinstance(pid,int) or pid<=0:return False
    if os.name=='nt':
        import ctypes
        handle=ctypes.windll.kernel32.OpenProcess(0x1000,False,pid)
        if not handle:return False
        code=ctypes.c_ulong();ok=ctypes.windll.kernel32.GetExitCodeProcess(handle,ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(handle)
        return bool(ok and code.value==259)
    try:os.kill(pid,0);return True
    except ProcessLookupError:return False


def _recover(out,built):
    """Only dead-owner calls are stale. Retained raw must re-pass all checks."""
    for path in sorted((Path(out)/'attempts').glob('*.json')):
        a=read_json(path)
        if a['status']!='RUNNING':continue
        if _alive(a['owner_pid']):fail('A recorded owner is still running')
        a['status']='INTERRUPTED';a['recovered_at']=utcnow()
        a['accounting']='RECORDED_ELAPSED' if 'elapsed_seconds' in a else 'UNKNOWN_DURATION_CHARGED_RESERVED_TIMEOUT'
        payload=next(p for p in built['payloads'] if p['part_id']==a['part_id'])
        raw_paths=list((Path(out)/'calls'/a['id']/'data_agents/audit/DC-review').glob('*/response.json'))
        if len(raw_paths)==1:
            try:
                _accept_raw(out,built,payload,a,raw_paths[0])
                a['status']='ACCEPTED';a['recovery']='REPLAYED_RETAINED_RAW_ZERO_PROVIDER'
            except (ValueError,KeyError,TypeError) as exc:
                a['status']='FAILED';a['error']='Recovered raw failed original checks: '+str(exc)
        write_json(path,a)
    return rebuild_checkpoint(out)


def _check_duration(attempt):
    elapsed=attempt.get('elapsed_seconds')
    if not isinstance(elapsed,(int,float)) or not math.isfinite(elapsed) or elapsed<0:
        fail('Cannot accept a response without measured provider duration')
    if elapsed>attempt['timeout_seconds']:
        fail('Provider returned beyond the reserved timeout; raw retained, not accepted')


def _accept_raw(out,built,payload,attempt,path):
    _check_duration(attempt)
    raw=read_json(path);request=read_json(Path(out)/'requests'/(payload['part_id']+'.json'))
    if read_json(path.with_name('request.json'))!=request or raw.get('request_sha256')!=request['request_sha256']:
        fail('Retained raw is not bound to the actual prepared request')
    matches=facts().materialize(raw,payload,built['catalog'])
    refs={'raw':file_ref(path),'request':file_ref(path.with_name('request.json'))}
    metadata=path.parent/'model_call/call.json'
    if metadata.exists():refs['model_call']=file_ref(metadata)
    model_record=_diagnostics(path.parent/'model_call')
    receipt={'part_id':payload['part_id'],'build_sha256':digest(built),'matches_sha256':digest(matches),
        'requested_model':MODEL,'served_model':model_record['served_model'],
        'served_models':model_record['served_models'],'refs':refs,'attempt_id':attempt['id']}
    write_json(Path(out)/'accepted'/(payload['part_id']+'.json'),receipt)
    return receipt


def run_prepared(out,max_new_calls=1,part_ids=None,retry_failed=False,generator=None,*,batch=None):
    if not isinstance(max_new_calls,int) or isinstance(max_new_calls,bool) or max_new_calls<0:fail('Invalid call limit')
    out=Path(out).resolve();built=_load(out)
    from .data_live_batch import require_stage_batch
    require_stage_batch(out,batch)
    if batch is not None:
        batch.bind_stage(out,'coverage')
        generator=batch.generator(out,generator)
    lock=out/'runtime.lock'
    if lock.exists():
        if _alive(read_json(lock).get('pid')):fail('Runtime already active')
        archive=out/'stale_locks';archive.mkdir(exist_ok=True)
        lock.replace(archive/(uuid4().hex+'.json'))
    fd=os.open(lock,os.O_WRONLY|os.O_CREAT|os.O_EXCL)
    with os.fdopen(fd,'w',encoding='utf-8') as stream:json.dump({'pid':os.getpid(),'at':utcnow()},stream)
    calls=0
    try:
        _recover(out,built)
        known={p['part_id'] for p in built['payloads']};selected=known if part_ids is None else set(part_ids)
        if not selected<=known:fail('Unknown selected part')
        for p in built['payloads']:
            part=p['part_id']
            if part not in selected:continue
            accepted,_=_accepted(out,built)
            if part in accepted:
                emit(out,'PART_REUSED',part_id=part,provider_calls=0);continue
            if (out/'PAUSE').exists():
                _boundary(out,built,'PAUSED');break
            if calls>=max_new_calls:
                _boundary(out,built,'CALL_LIMIT');break
            attempts=[read_json(q) for q in (out/'attempts').glob('*.json')]
            if not retry_failed and any(a['part_id']==part and a['status'] in ('FAILED','INTERRUPTED') for a in attempts):
                emit(out,'RETRY_REQUIRES_EXPLICIT_REQUEST',part_id=part)
                _boundary(out,built,'RETRY_REQUIRED',part_id=part);break
            ledger=_ledger(out,built);decision=(batch.admission(ledger,_checks(p)) if batch is not None else admission(ledger,_checks(p)))
            if not decision['allowed']:
                emit(out,'BUDGET_BOUNDARY_STOP',part_id=part,**decision)
                _boundary(out,built,'BUDGET_PREDICTION_RESERVE',part_id=part,decision=decision);break
            call_id=uuid4().hex;attempt_path=out/'attempts'/(call_id+'.json')
            request=read_json(out/'requests'/(part+'.json'))
            a={'id':call_id,'part_id':part,'build_sha256':digest(built),'status':'RUNNING',
                'owner_pid':os.getpid(),'started_at':utcnow(),'checks':_checks(p),'requested_model':MODEL,
                'served_model':None,'provider_started':False,'timeout_seconds':decision['remaining_seconds']-RESERVE_SECONDS,
                'request_ref':file_ref(out/'requests'/(part+'.json')),'prediction':decision}
            write_json(attempt_path,a)
            call_dir=out/'calls'/call_id
            caller=planning.sf.private_module()
            caller.governed_request=lambda payload:d.governed_request(facts().transport_payload(payload))
            def bounded(actual,**options):
                if actual!=request:fail('Actual governed request differs from prepared request')
                a['provider_started']=True;write_json(attempt_path,a)
                emit(out,'MODEL_START',part_id=part,call_id=call_id,model=MODEL,request_chars=len(json.dumps(actual,ensure_ascii=False)))
                start=time.monotonic()
                try:return (generator or d.codex_generate)(actual,timeout=a['timeout_seconds'],**options)
                finally:
                    a['elapsed_seconds']=time.monotonic()-start;a['ended_at']=utcnow();write_json(attempt_path,a)
                    _ledger(out,built)
                    emit(out,'MODEL_END',part_id=part,call_id=call_id,elapsed_seconds=a['elapsed_seconds'])
            # Runtime's immutable receipts are the only cache. invoke still archives raw.
            bounded.executor_id=None
            try:
                raw=caller.invoke(call_dir,'DC-review',p,facts().response_schema(p),model=MODEL,
                    generator=bounded,check=lambda raw:bool(facts().materialize(raw,p,built['catalog'])))
                raw_paths=list((call_dir/'data_agents/audit/DC-review').glob('*/response.json'))
                if len(raw_paths)!=1:fail('No unique archived model response')
                _accept_raw(out,built,p,a,raw_paths[0])
                a['model_record']=_diagnostics(raw_paths[0].parent/'model_call')
                a['status']='ACCEPTED';write_json(attempt_path,a);calls+=1
                emit(out,'PART_ACCEPTED',part_id=part,call_id=call_id)
                rebuild_checkpoint(out)
            except BaseException as exc:
                a['status']='INTERRUPTED' if isinstance(exc,(KeyboardInterrupt,SystemExit)) else 'FAILED'
                a['error']=str(exc);write_json(attempt_path,a)
                dirs=list((call_dir/'data_agents/audit/DC-review').glob('*/model_call'))
                if len(dirs)==1:a['model_record']=_diagnostics(dirs[0]);write_json(attempt_path,a)
                _boundary(out,built,a['status'],part_id=part,error=str(exc))
                rebuild_checkpoint(out);emit(out,'PART_FAILED',part_id=part,call_id=call_id,error=str(exc));raise
        else:_boundary(out,built,'SELECTED_PARTS_COMPLETE' if part_ids is not None else 'COMPLETE')
        return rebuild_checkpoint(out)
    finally:
        if lock.exists():lock.unlink()


def run(plan_path,source_run,out,generator=None,*,max_new_calls=1,part_ids=None,retry_failed=False,import_from=None,batch=None):
    prepare(plan_path,source_run,out,import_from=import_from)
    return run_prepared(out,max_new_calls,part_ids,retry_failed,generator,batch=batch)


def verify_result(path):
    path=Path(path);result=read_json(path)
    if result.get('version')!=VERSION or result.get('complete') is not True:fail('Incomplete facts are not a necessity input')
    if any(result.get(k) is not False for k in GATES):fail('Scientific approval is not provided')
    planning.check_refs(result['provenance']);planning.check_refs(result['bindings'])
    replay=rebuild_checkpoint(Path(result['provenance']['build_ref']['path']).parent,write=False)
    if result!=replay:fail('Published facts differ from replay')
    return result


def result_sources(path):
    result=verify_result(path)
    return read_json(result['provenance']['build_ref']['path'])['catalog']


def prepare_search(parent_path,out,unit_ids=None):
    parent=verify_result(parent_path);parent_dir=Path(parent['provenance']['build_ref']['path']).parent
    original=_load(parent_dir);ledger=_ledger(parent_dir,original)
    if ledger['build_sha256']!=digest(original):fail('Search parent budget mismatch')
    targets=unit_ids if unit_ids is not None else facts().lookup_targets(original,parent['matches'])
    if not targets:
        return {'status':'NO_PERMITTED_LOOKUP_TARGETS','model_calls':0,'complete':False,
            'parent_ref':file_ref(parent_path),'pending_searches':parent.get('pending_searches',[]),**GATES}
    built=facts().build_search(original,parent['matches'],targets)
    built['bindings']['parent_coverage']=file_ref(parent_path)
    built['bindings']['parent_budget']=file_ref(parent_dir/'model_budget.json')
    built['prior_model_seconds'],built['prior_model_calls']=inherited_budget(ledger)
    built['runtime_recipe']={'kind':'SEARCH','targets':targets}
    return _store_build(built,out)
