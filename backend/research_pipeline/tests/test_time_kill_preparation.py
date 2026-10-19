from copy import deepcopy

import pytest

from research_pipeline.common import PipelineError
from research_pipeline.time_kill_preparation import normalize_static_time_kill


def table(y=".", cens=0):
    base = {"c001_id": 1, "source_file_id": "F0004", "source_sheet": "Source tables",
            "source_cells": {"c001_id": "A161", "c002_amt": "B161", "c004_time": "D161",
                             "c005_y": "E161", "c006_cens": "F161"}}
    return {"table_id": "T0012", "records": [
        {**deepcopy(base), "record_id": "event", "record_type": "EXPOSURE_EVENT", "c003_amt_cmt": 2,
         "c002_amt": 1e-8, "c004_time": 0, "c005_y": ".", "c006_cens": 0},
        {**deepcopy(base), "record_id": "T0012_R161", "record_type": "OBSERVATION", "c003_amt_cmt": 1,
         "c002_amt": ".", "c004_time": 16, "c005_y": y, "c006_cens": cens},
    ]}


@pytest.mark.parametrize("raw,cens,status,value", [
    (".", 0, "MISSING_OBSERVATION", None),
    (None, 0, "MISSING_OBSERVATION", None),
    ("", 0, "MISSING_OBSERVATION", None),
    (".", 1, "MISSING_CENSORED_OBSERVATION", None),
    (0, 0, "QUANTIFIED", 0),
    (3.2, 0, "QUANTIFIED", 3.2),
    (2, 1, "CENSORED", 2),
])
def test_preserve_observation_semantics_and_all_source_rows(raw, cens, status, value):
    source = table(raw, cens)
    before = deepcopy(source)
    events, observations = normalize_static_time_kill(source)
    assert source == before
    assert len(events) + len(observations) == len(source["records"])
    event, obs = events[0], observations[0]
    assert event["Y_status"] == "STRUCTURAL_NOT_APPLICABLE"
    assert event["nominal_concentration_mg_L"] == 1e-8
    assert obs["status"] == status and obs["log10_CFU_mL"] == value
    assert obs["Y_raw"] == raw and obs["CENS"] == cens
    assert obs["source_cells"]["c005_y"] == "E161"
    assert obs["AMT_status"] == "STRUCTURAL_NOT_APPLICABLE"
    assert obs["censor_limit"] == "NOT_FOUND" and obs["fit_ready"] is False


@pytest.mark.parametrize("bad", ["oops", "NaN", float("nan"), float("inf"), True])
def test_malformed_values_fail_with_source_location(bad):
    with pytest.raises(PipelineError) as caught:
        normalize_static_time_kill(table(bad))
    assert caught.value.code == "TIME_KILL_INVALID_RESPONSE"
    assert "T0012_R161 / E161" in str(caught.value)


@pytest.mark.parametrize("bad", [2, -1, None, "0", True])
def test_invalid_censor_flag_is_not_accepted_as_missing(bad):
    with pytest.raises(PipelineError) as caught:
        normalize_static_time_kill(table(".", bad))
    assert caught.value.code == "TIME_KILL_INVALID_CENS"


def test_exposure_must_be_unique_and_in_same_table():
    source = table(5)
    other_event = deepcopy(source["records"][0])
    other_event["record_id"] = "another_event"
    source["records"].append(other_event)
    with pytest.raises(PipelineError) as caught:
        normalize_static_time_kill(source)
    assert caught.value.code == "TIME_KILL_AMBIGUOUS_EXPOSURE"
    source = table(5)
    source["records"] = source["records"][1:]
    with pytest.raises(PipelineError) as caught:
        normalize_static_time_kill(source)
    assert caught.value.code == "TIME_KILL_MISSING_EXPOSURE"


def test_exposure_cannot_follow_observation():
    source = table(5)
    source["records"][0]["c004_time"] = 17
    with pytest.raises(PipelineError) as caught:
        normalize_static_time_kill(source)
    assert caught.value.code == "TIME_KILL_EVENT_AFTER_OBSERVATION"
