import copy
import pytest
from research_pipeline import eda_display_catalog as dc
from research_pipeline.eda_source_views import mean_sd


def fixture():
    table={"dataset_id":"D1","title":"Example","notes":"Source mean ± SD",
        "columns":[{"id":"time","header":"Time (h)","unit":"h","meaning":"TIME"},
                   {"id":"y","header":"Concentration","unit":"mg/L","meaning":"CONCENTRATION"}],
        "records":[dict(record_id="R1",source_file_id="F",source_sha256="a"*64,source_sheet="S",source_row=1,
            source_cells={"time":"A1","y":"B1"},source_raw_values={"time":1,"y":"2 ± 0.5"},
            value_status={"time":"QUANTIFIED","y":"SOURCE_TEXT_REQUIRES_REVIEW"})]}
    spec=dict(id="V",kind="source_projection",panels=[{"series":[{"dataset_id":"D1"}]}],
        source_recipe=dict(scale="linear",series=[dict(dataset_id="D1",y="y",x="time",panel="Source",
            group="",projection="reported_mean_sd",error="",n="",category_column="",category_prefix="",
            filters={},x_from_header=False)]))
    return {"D1":table},{"V":spec}


def test_reported_uncertainty_is_display_only():
    tables,c=fixture();r=dc.materialize(c["V"],tables)[0]["rows"][0]
    assert (r["y"],r["error"])==(2,.5)
    assert r["original_status"]=="SOURCE_TEXT_REQUIRES_REVIEW"
    assert not r["usable_for_modeling"]
    with pytest.raises(ValueError):mean_sd("2 ± .5","Unknown uncertainty definition")


def test_omissions_duplicates_and_false_display_fail():
    t,c=fixture()
    with pytest.raises(ValueError,match="exactly once"):dc.coverage([],[],c,t)
    d=dict(dataset_id="D1",status="DISPLAYED",reason="Source-native display",unshown_columns=[])
    with pytest.raises(ValueError):dc.coverage([d],[],c,t)
    with pytest.raises(ValueError,match="exactly once"):dc.coverage([d,d],["V"],c,t)
    assert dc.coverage([d],["V"],c,t)["status"]=="ALL_DATASETS_ACCOUNTED"


def test_unshown_fields_are_not_satisfied_by_any_figure():
    t,c=fixture()
    t["D1"]["columns"].append(dict(id="other",header="Other response",unit="mg/L",meaning="RESPONSE"))
    d=dict(dataset_id="D1",status="DISPLAYED",reason="Other endpoint retained separately",unshown_columns=[])
    with pytest.raises(ValueError,match="unshown"):dc.coverage([d],["V"],c,t)
    d["unshown_columns"]=["other"]
    assert dc.coverage([d],["V"],c,t)["datasets"][0]["fields_without_recipe"]==["other"]


def test_added_rows_are_materialized_without_embedded_observations():
    t,c=fixture();extra=copy.deepcopy(t["D1"]["records"][0]);extra["record_id"]="R2"
    extra["source_raw_values"]["y"]="3 ± .6";t["D1"]["records"].append(extra)
    assert [r["y"] for r in dc.materialize(c["V"],t)[0]["rows"]]==[2,3]


def test_censored_text_is_not_a_zero_or_mean():
    t,c=fixture();r=copy.deepcopy(t["D1"]["records"][0]);r["record_id"]="R2"
    r["source_raw_values"]["y"]="<LLOQ";r["value_status"]["y"]="BLQ";t["D1"]["records"].append(r)
    z=dc.materialize(c["V"],t)[0]["rows"][1]
    assert z["y"] is None and z["error"] is None and z["raw_y"]=="<LLOQ"
