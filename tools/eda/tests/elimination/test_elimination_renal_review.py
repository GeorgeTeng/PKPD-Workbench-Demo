"""Numerical and assay gates for items 29 and 33."""
import copy
import math

from test_eda_elimination import el


def plasma(times=(1, 2, 3)):
    return {"sid": "T9:c1", "label": "Rat", "dataset_id": "T9", "study": "S1", "species": "Rat", "route_class": "IV",
            "route_detail": "iv bolus", "iv_mode": "BOLUS", "dose": 10., "dose_basis": "mg/kg", "matrix_class": "PLASMA",
            "level": "GROUP_MEAN", "occasion": "FIRST_DOSE", "uf": 1., "notes": "Plasma by HPLC.",
            "analyte": "PARENT", "unbound": False, "points": [
                {"t": t, "c": 12 / t, "status": "QUANTIFIED", "record_id": f"r{t}"} for t in times]}


def test_t0004_override_is_source_bound():
    row = {"dataset_id": "T0004", "source_item_id": "F1:S1:T4", "source_refs": [{"sha256": "table-hash"}],
           "study_source_ids": ["S01"], "metadata": {"drug": "meropenem"}, "title": "Urinary recovery",
           "notes": "Plasma assayed by bioassay."}
    cfg = {"assay_by_dataset": {"T0004": {"assay": "MICROBIOLOGICAL", "source": "methods §8-1",
           "match": {"study": "S01", "drug": "meropenem", "source_item_id": "F1:S1:T4", "source_sha256": "table-hash"}}}}
    assert el.assay_of(row, cfg)[0] == "MICROBIOLOGICAL"
    assert el.assay_of(dict(row, source_refs=[]), cfg)[0] == "NOT_REPORTED"


def test_item29_activity_retains_measurement_and_suppresses_parent_targets():
    s = plasma()
    s["notes"] = "Plasma assayed by bioassay."
    r = el.item29(s, {}, {}, None, None, [], {})
    assert r["window_proxy"] > 0 and r["analyte"] == "ACTIVE_MATERIAL"
    assert r["window_quantity"] == "dose/activity AUC" and not r["sensitivity_rows"] and r["cl_u_upper"] is None
    assert "antimicrobial activity" in r["value_row"]


def test_item29_rechecks_points_and_grid_before_reuse():
    m = {"auc_status": "PARTIAL_OBSERVED_WINDOW", "auc_observed": 100., "auc_window_start_h": 1, "auc_window_end_h": 3,
         "auc_grid_h": [1, 2, 3], "auc_record_ids": ["r1", "r2", "r3"], "auc_method": "linear-up/log-down"}
    up = {("T9", "c1"): {"metrics": m}}
    assert el.item29(plasma((1, 3)), up, {}, None, None, [], {})["window_proxy"] is None
    r = el.item29(plasma(), up, {}, None, None, [], {})
    assert r["auc_window"] == 100.
    m["auc_grid_h"] = [1, 2.5, 3]
    r = el.item29(plasma(), up, {}, None, None, [], {})
    assert math.isclose(r["auc_window"], el.ab.auc([1, 2, 3], [12, 6, 4]))
    m["auc_status"] = "WITHHELD_UNVERIFIED_SERIAL_IDENTITY"
    assert el.item29(plasma(), up, {}, None, None, [], {})["window_proxy"] is None


def test_unmatched_gfr_never_changes_formal_status():
    ref = {"low": 3., "high": 5., "matched_to_study": False}
    fu = {"low": .5, "high": .5}
    for limits in ((1., 3.), (3., None), (None, .1)):
        result = el.t10({"limits": limits}, fu, ref)
        assert result["status"] == "CANNOT_ASSESS" and result["filtration_range_l_h_kg"] == [1.5, 2.5]
    assert el.t10({"limits": (1., 3.)}, fu, {"low": 3., "high": None})["status"] == "CANNOT_ASSESS"


def test_fu_conversion_tracks_the_profile_and_binding_scope():
    s = plasma()
    s["drug"], s["condition"] = "X", "control"
    source = {"series": s["sid"], "dataset_id": "binding-1", "drug": "X", "condition": "control", "fu_range": [.4, .42]}
    other = dict(source, series="other", fu_range=[.01, .02])
    r = el.item29(s, {}, {}, None, {"constant_fu_sources": [source, other]}, [], {})
    assert math.isclose(r["cl_u_window_proxy"], r["window_proxy"] / .4)
    assert r["fu_used"]["scope"] == "observed window only" and r["cl_u_upper"] is None
    assert el.item29(s, {}, {}, None, {"constant_fu_sources": [other]}, [], {})["cl_u_window_proxy"] is None


def test_clr_only_from_compatible_interval_pair_and_no_blq_bridge():
    u = {"key": "u", "analyte": "PARENT", "dose": 10., "study": "S1", "species": "Rat", "route": "IV", "assay": "SPECIFIC",
         "level": "GROUP_MEAN", "occasion": "FIRST_DOSE", "flags": [], "collection": {"pairing": "PARALLEL_COHORT_SAME_STUDY",
          "collection_complete": "YES", "bladder_emptying": "catheter emptied at both boundaries"},
         "intervals": [{"interval": [1, 3], "state": "QUANTIFIED", "value": 15., "record_id": "u3"}]}
    def row(urine, s):
        return el.item33_clr(urine, [s], {}, {}, None)[0]
    assert row(u, plasma())["kind"] == "INTERVAL_ESTIMATE"
    assert "RATIO_OF_MEANS" in row(u, plasma())["caveats"]
    assert row(u, plasma((1.5, 2, 3)))["kind"] == "WINDOW_PROXY"
    for key, value in (("collection_complete", "NO"), ("pairing", "OTHER_STUDY"), ("pairing", "NOT_REPORTED"),
                       ("bladder_emptying", "not reported")):
        blocked = copy.deepcopy(u)
        blocked["collection"][key] = value
        assert row(blocked, plasma())["clr"] is None
    s = plasma()
    s["points"][1].update(status="BLQ", c=None)
    assert row(u, s)["clr"] is None
    assert row(dict(u, assay="NOT_REPORTED"), plasma())["clr"] is None
    assert el.item33_clr(dict(u, occasion="DAY_14"), [plasma()], {}, {}, None) == []
