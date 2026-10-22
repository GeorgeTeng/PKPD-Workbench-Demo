"""Mandatory Compression/Data/EDA provider boundary, including legacy entry points."""
import threading
from pathlib import Path
from ctxcomp import context_dispatch, providers
from ctxcomp.io import digest,canonical
from . import context_builder as cb,context_model_view as cmv,context_budget as budget,context_routes
from .common import read_json,write_json,PROJECT

_lock=threading.Lock()


def scope_root(context_scope,diagnostics,request=None):
    if context_scope:
        return Path(context_scope).resolve()
    if diagnostics:
        path=Path(diagnostics).resolve()
        # Existing adapters put UUID attempts below these stable run directories.
        for i,part in enumerate(path.parts):
            if part in {'attempts','audit','data_agents','calls','model_calls'}:
                return Path(*path.parts[:i])
    # Historical Data adapters omit diagnostics and must keep their hash-bound
    # code unchanged. Give the immutable request a durable receipt, not a UUID.
    # Identical requests cannot be sent again even after process restart.
    if request is not None:
        return PROJECT/'outputs/contextbuilder_calls'/request['request_sha256'][:20]
    raise ValueError('Model call requires a stable run scope for its no-repeat ledger')


def task_identity(payload):
    identity={'stage':payload['stage']}
    for key in ('part_id','item_id','file_id','branch','review_branch','review_dimension','operation'):
        if key in payload:identity[key]=payload[key]
    for key in ('requirement_ids','item_ids','source_ids'):
        if key in payload:identity[key]=sorted(payload[key])
    if len(identity)==1 or set(identity)=={'stage','operation'}:
        units=payload.get('source_units')
        if isinstance(units,dict):identity['source_unit_ids']=sorted(units)
        elif isinstance(units,list):identity['source_unit_ids']=sorted(u['id'] for u in units if isinstance(u,dict) and 'id' in u)
        requirements=payload.get('requirements')
        if isinstance(requirements,list):identity['requirement_ids']=sorted(r['id'] for r in requirements if isinstance(r,dict) and 'id' in r)
    return identity


def assemble(request):
    if digest(request['payload'])!=request['request_sha256']:cb.fail('Request hash mismatch')
    route=context_routes.select(request['payload'])
    bundle=cb.build_context(*route,request['payload'],request['payload']['schema'])
    if bundle['request']!=request:cb.fail('Builder changed the adapter request')
    return bundle


def dispatch(request,*,transport,context_scope=None,**kwargs):
    # Reject repairs even when they have a different request hash or attempt UUID.
    bundle=assemble(request)
    root=scope_root(context_scope,kwargs.get('diagnostics_dir'),request)/'contextbuilder'
    root.mkdir(parents=True,exist_ok=True)
    identity=task_identity(request['payload']);key=digest(identity)
    with _lock:
        lock=root/'dispatch.lock'
        with lock.open('x',encoding='utf-8') as stream:stream.write(key)
        try:
            # A directory is an at-most-once reservation, retained even on interruption.
            # Full identities stay in receipts; short directory names also work
            # under Windows path limits. A collision stops rather than reuses.
            slot=root/key[:20]
            if slot.exists():raise ValueError('Task already dispatched or attempted; automatic repeat is disabled')
            if (root/'FAILED.json').exists():raise ValueError('Previous provider failure retained; run is stopped')
            cb.save_bundle(slot,bundle)
            record={'status':'PREPARING','task_identity':identity,'request_sha256':request['request_sha256'],
                    'automatic_retries':0,'automatic_patches':0,'provider_started':False}
            write_json(slot/'status.json',record)
        except BaseException:
            lock.unlink()
            raise
    # The per-run file lock stays held. Independent roots may use the existing
    # Data worker pool; the process-wide reservation lock must not serialize I/O.
    try:
        visible,projection=cmv.project(bundle['request'])
        write_json(slot/'model_input.json',visible);write_json(slot/'projection_manifest.json',projection)
        prompt=providers.PROMPT+canonical(visible)
        (slot/'model_prompt.txt').write_text(prompt,encoding='utf-8')
        schema=kwargs.get('cli_schema') or request['payload']['schema']
        write_json(slot/'transport_schema.json',schema)
        write_json(slot/'budget.json',budget.check(prompt,schema))
        cb.verify_bundle(bundle);cb.check_refs(projection['bindings'])
        record.update(status='DISPATCHING',provider_started=True)
        write_json(slot/'status.json',record)
        if kwargs.get('diagnostics_dir') is None:kwargs['diagnostics_dir']=slot/'provider'
        with context_dispatch.sending(bundle['request'],visible,schema):
            raw=transport(bundle['request'],**kwargs)
        write_json(slot/'response.json',raw)
        cb.verify_bundle(bundle);cb.check_refs(projection['bindings'])
        record['status']='RETURNED_PENDING_STAGE_VALIDATION'
        return raw
    except BaseException as exc:
        record.update(status='FAILED',error=str(exc))
        if hasattr(exc,'budget_report'):write_json(slot/'budget.json',exc.budget_report)
        write_json(root/'FAILED.json',record)
        raise
    finally:
        try:
            write_json(slot/'status.json',record)
        finally:
            lock.unlink()
