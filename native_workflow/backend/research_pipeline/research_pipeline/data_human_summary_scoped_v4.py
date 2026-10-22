"""The existing short-summary schema, bound to a scoped v4 assessment."""
from pathlib import Path
from . import data_human_summary_v3 as old, data_necessity_scoped_v5 as necessity, data_direct_runtime as rt
from .common import read_json, write_json
from .data_necessity_direct import obj

# Summary uses the existing concise immutable v3 result format; the new adapter
# verifies Necessity5 before binding the exact opinion. Historical readers stay.
run_prepared = old.run_prepared
verify_result = old.verify_result


def prepare(necessity_path, out):
    reference = rt.file_ref(necessity_path)
    nec = necessity.verify_result(necessity_path)
    rows = {key:obj({'readiness':{'type':'string','enum':[nec['action_decisions'][key]['readiness']]},
        'finding':{'type':'string','minLength':1},'next_step':{'type':'string','minLength':1}}) for key in old.PRIMARY}
    schema = obj({'request_sha256':{'type':'string'},'decision':{'type':'string','enum':[nec['assessment']['decision']]},
        'headline':{'type':'string','minLength':1},'rows':obj(rows),'later_and_optional':{'type':'string','minLength':1}})
    p = {'version':'DATA_HUMAN_SUMMARY_PREPARED_3.0',
        'bindings':{**rt.runtime_bindings(),'summary_code':rt.file_ref(__file__),
                    'summary_contract':rt.file_ref(old.__file__),'necessity':reference},
        'request':rt.make_request({'stage':'HUMAN_REVIEW_SUMMARY_ONLY','instructions':old.INSTRUCTIONS,
                    'assessment':nec['assessment'],'action_decisions':nec['action_decisions']},schema)}
    path = Path(out)/'prepared.json'
    if path.exists() and read_json(path) != p:
        rt.fail('Summary directory belongs to different inputs')
    rt.verify_refs(p['bindings'])
    write_json(path,p)
    return p
