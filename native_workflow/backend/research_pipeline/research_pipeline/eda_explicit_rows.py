"""Readable ER tables: share headers, never inherit or intern observed values."""
import copy
import json
from collections import Counter

ENCODING = 'EDA_EXPLICIT_ROWS_1'
LITERAL_KEYS = {'project_rules', 'implemented_r_operations'}


def pack(value):
    if isinstance(value, list):
        if value and all(isinstance(row, dict) for row in value):
            fields = list(dict.fromkeys(k for row in value for k in row))
            # Heterogeneous rows stay as objects in a protected container.
            if all(set(row) == set(fields) for row in value):
                return {'encoding': ENCODING, 'fields': fields,
                        'rows': [[pack(row[k]) for k in fields] for row in value]}
            return {'encoding': ENCODING, 'row_format':'OBJECTS',
                    'rows':[{k:pack(v) for k,v in row.items()} for row in value]}
        return [pack(v) for v in value]
    if isinstance(value, dict):
        if value.get('encoding') == ENCODING:
            raise ValueError('Explicit ER inputs must be supplied unencoded')
        return {k: copy.deepcopy(v) if k in LITERAL_KEYS else pack(v) for k,v in value.items()}
    return copy.deepcopy(value)


def unpack(value):
    if isinstance(value, dict) and value.get('encoding') == ENCODING:
        if value.get('row_format')=='OBJECTS':return [unpack(row) for row in value['rows']]
        fields=value['fields']
        if len(fields)!=len(set(fields)) or any(len(row)!=len(fields) for row in value['rows']):
            raise ValueError('Invalid explicit ER table')
        return [{k:unpack(v) for k,v in zip(fields,row)} for row in value['rows']]
    if isinstance(value,dict): return {k:unpack(v) for k,v in value.items()}
    if isinstance(value,list): return [unpack(v) for v in value]
    return copy.deepcopy(value)


def contains_literal(value):
    if isinstance(value,dict):
        return value.get('encoding')==ENCODING or any(contains_literal(v) for v in value.values())
    if isinstance(value,list):return any(contains_literal(v) for v in value)
    return False


def encode(inputs):
    from .eda_workflow import compact_grid
    from . import eda_shared_values
    def protect(value):
        if isinstance(value,dict):
            return {k:pack(v) if k in {'records','plotted_rows','context_rows'} and isinstance(v,list)
                    else copy.deepcopy(v) if k in LITERAL_KEYS else protect(v) for k,v in value.items()}
        if isinstance(value,list):return [protect(v) for v in value]
        return copy.deepcopy(value)
    def metadata_pack(value):
        if isinstance(value,dict) and value.get('encoding')==ENCODING:return copy.deepcopy(value)
        if isinstance(value,dict):return {k:copy.deepcopy(v) if k in LITERAL_KEYS else metadata_pack(v) for k,v in value.items()}
        if isinstance(value,list):
            rows=[metadata_pack(v) for v in value]
            return rows if contains_literal(rows) else compact_grid(rows)
        return value
    result=metadata_pack(protect(inputs))
    counts=Counter()
    def count(v):
        if isinstance(v,dict) and v.get('encoding')==ENCODING:return
        if isinstance(v,str) and len(v)>=100:counts[v]+=1
        elif isinstance(v,list):
            for x in v:count(x)
        elif isinstance(v,dict):
            for k,x in v.items():
                if k not in LITERAL_KEYS:count(x)
    count(result)
    texts={s:'TEXT_'+str(i+1) for i,s in enumerate(sorted(s for s,n in counts.items() if n>1 and (n-1)*len(s)>n*50+50))}
    def factor(v):
        if isinstance(v,dict) and v.get('encoding')==ENCODING:return copy.deepcopy(v)
        if isinstance(v,str) and v in texts:return {'evidence_text_ref':texts[v]}
        if isinstance(v,list):return [factor(x) for x in v]
        if isinstance(v,dict):return {k:copy.deepcopy(x) if k in LITERAL_KEYS else factor(x) for k,x in v.items()}
        return v
    result=factor(result)
    result['task_context']['shared_evidence_text']={key:s for s,key in texts.items()}
    result=eda_shared_values.encode(result, preserve=contains_literal)
    # Independently reconstruct both plain science rows and compact metadata.
    if restore(result)!=inputs: raise ValueError('Explicit ER encoding changed evidence')
    # Keep the partition ledger literal for at-most-once dispatch verification.
    if inputs.get('task_context',{}).get('review_batch'):
        result['task_context']['review_batch']=copy.deepcopy(inputs['task_context']['review_batch'])
    result['task_context']['input_encoding']=(
        'EDA_EXPLICIT_ROWS_1 shares column headers only. Pair fields with each rows cell in order; '
        'nested tables use the same rule. Every repeated scientific value and status is explicitly '
        'present in every corresponding row. There are no inherited defaults, value dictionaries, '
        'source-value aliases, or placeholder nulls. A null is an actual supplied null. '
        'Tables with row_format OBJECTS contain ordinary JSON row objects so absent keys remain absent. '
        'Outside these explicit scientific tables only, metadata may use EDA_COLUMNAR_1, defaults, '
        'evidence_text_ref (task_context.shared_evidence_text) or $v (task_context.shared_values). '
        'For EDA_COLUMNAR_1, pair fields and rows, remove absent_fields, expand nested_columns, '
        'inherit absent keys from defaults, then copy copy_from_source_raw_values keys. '
        'These metadata encodings never replace scientific rows or their cells. '
        'Rules, evidence, source identities and values are unchanged; the host verified exact reconstruction.')
    return result


def restore(value):
    from .eda_workflow import expand_grid
    from .eda_shared_values import restore as restore_shared
    out=restore_shared(value,value['task_context'].get('shared_values',{}))
    texts=out['task_context'].get('shared_evidence_text',{})
    def decode(v):
        if isinstance(v,dict) and set(v)=={'evidence_text_ref'}:return copy.deepcopy(texts[v['evidence_text_ref']])
        if isinstance(v,dict) and v.get('encoding')==ENCODING:return unpack(v)
        if isinstance(v,dict) and v.get('encoding')=='EDA_COLUMNAR_1':return decode(expand_grid(v))
        if isinstance(v,dict):return {k:decode(x) for k,x in v.items()}
        if isinstance(v,list):return [decode(x) for x in v]
        return v
    out=decode(out)
    for k in ('shared_values','shared_evidence_text'):out['task_context'].pop(k,None)
    return out
