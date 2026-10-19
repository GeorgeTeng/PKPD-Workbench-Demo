import math
from pathlib import Path
import pytest
from research_pipeline.animal_pk_summary import validate_summary_request
from research_pipeline.adequacy import file_ref
from research_pipeline.common import write_json,PipelineError


def test_summary_requires_exact_prefit_scope_and_no_random_effects(tmp_path):
    preflight=file_ref(write_json(tmp_path/'preflight.json',{'scope':'synthetic'}))
    approval=file_ref(write_json(tmp_path/'approval.json',{'status':'APPROVED','scope':'EXPLORATORY_MOUSE_MEAN_CURVES','preflight_ref':preflight}))
    req={'species':'mouse','random_effects':False,'approval_ref':approval,'preflight_ref':preflight,'source_refs':[]}
    ref=file_ref(write_json(tmp_path/'request.json',req))
    assert validate_summary_request(ref)==req
    req['random_effects']=True
    with pytest.raises(PipelineError):validate_summary_request(file_ref(write_json(tmp_path/'other.json',req)))
    write_json(tmp_path/'preflight.json',{'changed':True})
    with pytest.raises(ValueError):validate_summary_request(ref)
