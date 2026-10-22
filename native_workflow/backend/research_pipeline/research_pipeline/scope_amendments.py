"""Explicit user-confirmed changes to a reviewed context; originals stay immutable."""
import copy
from pydantic import BaseModel, Field
from typing import Literal
from .common import read_json, sha256, utcnow, write_json


class ScopeChange(BaseModel):
    path: str
    before: str
    after: str = Field(min_length=1)


class ScopeAmendment(BaseModel):
    context_signature: str
    instruction: str = Field(min_length=1)
    submitted_by: str = Field(min_length=1)
    changes: list[ScopeChange] = Field(min_length=1)
    confirmed: Literal[True]


def apply_amendment(main, amendment):
    """Only replace existing scientific scalar fields, with exact before-value checks."""
    from .adequacy import context_values
    from ctxcomp.handoff import verify_main
    value=copy.deepcopy(main); allowed=context_values(main); seen=set()
    if amendment.get('confirmed') is not True: raise ValueError('Scope changes require explicit user confirmation')
    for change in amendment['changes']:
        path=change['path']
        if path in seen or path not in allowed: raise ValueError('Duplicate or non-scientific scope path: '+path)
        seen.add(path)
        if allowed[path]!=change['before']: raise ValueError('The scope change is stale at '+path)
        parent=value;parts=path.strip('/').split('/')
        for part in parts[:-1]: parent=parent[int(part)] if isinstance(parent,list) else parent[part]
        key=int(parts[-1]) if isinstance(parent,list) else parts[-1]
        parent[key]=change['after']
    verify_main(value)
    return value


def save_amendment(store, identifier, request):
    from fastapi import HTTPException
    from uuid import uuid4
    with store.lock:
        s=store.load(identifier); context=s['nodes']['context']; adequacy=s['nodes']['adequacy']
        if not store.approved(context) or not store.artifacts_valid(context['artifacts']):
            raise HTTPException(409,'An approved, unchanged Context is required')
        if s.get('control_status')!='READY' or adequacy['execution'] not in {'NOT_STARTED','FAILED'}:
            raise HTTPException(409,'Scope can be clarified before adequacy starts or after an execution failure')
        if any(n['execution']!='NOT_STARTED' for k,n in s['nodes'].items() if k not in {'intake','context','adequacy'}):
            raise HTTPException(409,'Downstream work has started; use a new study cycle for changed scope')
        if request.context_signature!=context['output_signature']:
            raise HTTPException(409,'The Context signature changed; inspect the current Context')
        if not request.instruction.strip() or not request.submitted_by.strip():
            raise HTTPException(422,'The user instruction and submitter are required')
        main=next(a for a in context['artifacts'] if a['name']=='main.json')
        amendment={'schema_version':'1.0', 'at':utcnow(), **request.model_dump(),
            'base_main':{'path':main['path'],'sha256':main['sha256']},
            'authority':'EXPLICIT_USER_SCOPE_CHANGE', 'scientific_results_accepted':False,
            'supersedes':s.get('scope_amendment')}
        try: apply_amendment(read_json(main['path']),amendment)
        except ValueError as exc: raise HTTPException(422,str(exc)) from exc
        p=write_json(store.outputs/'canvas_cycles'/identifier/('scope_amendment_'+uuid4().hex+'.json'),amendment)
        s['scope_amendment']={'path':str(p),'sha256':sha256(p)}
        s['events'].append({'at':utcnow(),'node':'adequacy','action':'USER_SCOPE_AMENDED',
            'changed_paths':[c.path for c in request.changes], 'scientific_results_accepted':False})
        write_json(store.path(identifier),s)
        return store.view(s)
