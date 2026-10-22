"""Lossless interning of repeated evidence containers; authoritative Rules stay literal."""
import copy
import json
from collections import Counter

SKIP = {'project_rules', 'implemented_r_operations'}

def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))

def restore(value, shared):
    if isinstance(value, dict) and set(value) == {'$v'}:
        return copy.deepcopy(shared[value['$v']])
    if isinstance(value, dict):
        return {k: restore(v, shared) for k, v in value.items()}
    if isinstance(value, list):
        return [restore(v, shared) for v in value]
    return value

def encode(inputs, preserve=None):
    counts = Counter()
    def count(value):
        if preserve and preserve(value):
            if isinstance(value,dict) and value.get("encoding")=="EDA_EXPLICIT_ROWS_1":return
            if isinstance(value,dict):
                for k,v in value.items():
                    if k not in SKIP:count(v)
            elif isinstance(value,list):
                for v in value:count(v)
            return
        if isinstance(value, dict) and set(value) == {'$v'}:
            raise ValueError('Reserved shared-value key already present')
        if isinstance(value, (dict, list)):
            key = canonical(value)
            if len(key) > 40: counts[key] += 1
        if isinstance(value, dict):
            for k, v in value.items():
                if k not in SKIP: count(v)
        elif isinstance(value, list):
            for v in value: count(v)
    count(inputs)
    shared, ids = {}, {}
    def factor(value):
        if preserve and preserve(value):
            if isinstance(value,dict) and value.get("encoding")=="EDA_EXPLICIT_ROWS_1":return copy.deepcopy(value)
            if isinstance(value,dict):return {k:copy.deepcopy(v) if k in SKIP else factor(v) for k,v in value.items()}
            return [factor(v) for v in value]
        if isinstance(value, (dict, list)):
            key = canonical(value)
            if counts[key] > 1 and (counts[key]-1)*len(key) > counts[key]*18+25:
                if key not in ids:
                    ids[key] = str(len(ids)+1)
                    shared[ids[key]] = copy.deepcopy(value)
                return {'$v': ids[key]}
        if isinstance(value, dict):
            return {k: copy.deepcopy(v) if k in SKIP else factor(v) for k, v in value.items()}
        if isinstance(value, list): return [factor(v) for v in value]
        return value
    encoded = factor(inputs)
    if restore(encoded, shared) != inputs:
        raise ValueError('Shared evidence containers failed exact round trip')
    encoded['task_context']['shared_values'] = shared
    return encoded
