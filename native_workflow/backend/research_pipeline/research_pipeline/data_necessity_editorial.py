"""Traceable reviewer wording corrections; never mutate a model response or approve it."""
import copy
from pathlib import Path
from . import data_necessity_decisions as necessity, data_direct_runtime as rt
from .common import read_json,write_json,utcnow


def apply(original,corrections):
    result=copy.deepcopy(original)
    seen=set()
    for patch in corrections:
        key=(patch['analysis_id'],patch['field'])
        if key in seen or patch['field'] not in {'next_action','conditions_to_verify'}:
            rt.fail('Editorial correction changes an unsupported or repeated field')
        seen.add(key)
        if not patch.get('reason') or not patch.get('basis'):
            rt.fail('Editorial correction needs an explanation and source basis')
        row=next((a for a in result['analyses'] if a['id']==patch['analysis_id']),None)
        if row is None or row[patch['field']]!=patch['before']:
            rt.fail('Editorial correction does not match original text')
        after=patch['after']
        if patch['field']=='next_action' and (not isinstance(after,str) or not after.strip()):
            rt.fail('Corrected action must be a nonempty string')
        if patch['field']=='conditions_to_verify' and (not isinstance(after,list) or not all(isinstance(x,str) for x in after)):
            rt.fail('Corrected conditions must be strings')
        row[patch['field']]=copy.deepcopy(after)
    # Readiness, source evidence, gap mapping and all permission fields are untouched.
    return result


def create(original_path,corrections,out):
    out=Path(out)
    original=necessity.verify_result(original_path)
    record={'version':'NECESSITY_EDITORIAL_1.0','at':utcnow(),
        'author':'assistant reviewer after independent agent review',
        'bindings':{'original':rt.file_ref(original_path),'editorial_code':rt.file_ref(__file__)},
        'corrections':corrections,'human_approval':False}
    result=apply(original,corrections)
    record_path=out/'editorial_corrections.json'
    if record_path.exists() or (out/'necessity.reviewed.json').exists():
        rt.fail('Use a new editorial directory; original revisions are immutable')
    write_json(record_path,record)
    result['editorial_review']={'corrections':rt.file_ref(record_path),
        'original':rt.file_ref(original_path),'human_approval':False}
    write_json(out/'necessity.reviewed.json',result)
    return result


def verify_result(path):
    value=read_json(path)
    review=value['editorial_review']
    rt.verify_refs({'corrections':review['corrections'],'original':review['original']})
    record=read_json(review['corrections']['path'])
    rt.verify_refs(record['bindings'])
    if record['bindings']['original']!=review['original'] or record.get('human_approval') is not False:
        rt.fail('Editorial provenance or approval boundary changed')
    expected=apply(necessity.verify_result(review['original']['path']),record['corrections'])
    expected['editorial_review']={'corrections':review['corrections'],'original':review['original'],'human_approval':False}
    if expected!=value:rt.fail('Reviewed Necessity differs from its recorded corrections')
    return value
