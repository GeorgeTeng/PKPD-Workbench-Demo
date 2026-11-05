"""Constructed profiles exercise operation-level r4.3 decisions; no study values are used."""

import json
import math

import pytest

from research_pipeline import eda_absorption as absorption


def card(**extra):
    return {"route_class": "EV", "route_detail": "SC", "matrix_category": "PLASMA_SERUM_BLOOD",
            "single_dose": True, "tests_allowed": True, "origin": "EXOGENOUS", "record_level": "INDIVIDUAL",
            "time_origin_verified": True, "identity_verified": "yes", "t1_premises_verified": True,
            "t2_premises_verified": True, **extra}


def points(times, values, bounded=True):
    result = []
    for i, (t, v) in enumerate(zip(times, values)):
        row = {"t": t, "c": v, "status": "QUANTIFIED", "record_id": f"P{i}"}
        if bounded:
            row.update(lo=v * .98, hi=v * 1.02, bounds_basis="DETERMINISTIC", bound_source="synthetic absolute envelope")
        result.append(row)
    return result


def calc(p, **kwargs):
    c = card(**kwargs)
    result = absorption.curve_metrics(p, c["record_level"], c)
    json.dumps(result, allow_nan=False)
    return result


def test_full_pair_search_time_order_and_witness_surviving_removal():
    p = points([0, 1, 2, 3, 4, 5], [0, 20, 1, 9, 1, 9])
    p[0]["status"] = "MEASURED_ZERO"
    m = calc(p)
    assert m["t1"]["eligible_count"] == 10
    assert m["t1_rising_subset"]["count"] == 0
    assert m["t1_label"] == "EXCLUDED_UNDER_STATED_ASSUMPTIONS"
    assert m["t1"]["best"]["times_h"] == [2, 3]
    assert all(r["outcome"] == "CONTRADICTION_REMAINS" for r in m["t1"]["removals"])
    p[2].update(t_lo=1.8, t_hi=3.2)
    m = calc(p)
    assert m["t1"]["eligible_count"] == 9
    assert m["t1"]["best"]["times_h"] != [2, 3]


def test_single_witness_and_insufficient_removal_are_distinct():
    m = calc(points([1, 2, 3], [1, 8, 2], bounded=False))
    assert m["mt1"] > 0 and m["t1_label"] == "CANNOT_ASSESS"
    assert {"SINGLE_POINT_SUPPORT", "SENSITIVITY_ONLY"} <= set(m["t1_flags"])
    two = calc(points([1, 2], [1, 8]))
    assert two["t1_label"] == "NOT_EXCLUDED"
    assert two["t1_flags"] == ["INDEPENDENT_SUPPORT_NOT_ASSESSABLE"]
    assert all(r["outcome"] == "NOT_ASSESSABLE" for r in two["t1"]["removals"])


def test_bounded_blq_onset_reports_only_assumption_dependent_hard_lag():
    p = points([2, 3, 4], [10, 6, 3])
    p.insert(0, {"t": 1, "c": None, "lloq": 1, "status": "BLQ", "record_id": "BLQ"})
    m = calc(p, hard_lag_concave_rise_supported=True)
    assert m["onset_status"] == "DELAYED_ONSET" and m["observation_interval_h"] == [1, 2]
    assert m["conditional_hard_lag_lower_bound_h"] == pytest.approx((1 - 2 / 9.8) / (1 - 1 / 9.8))
    assert calc(p)["conditional_hard_lag_lower_bound_h"] is None
    assert m["auc_observed"] is None
    p[0].pop("lloq")
    assert calc(p)["onset_status"] == "NOT_ASSESSABLE"
    assert calc(p)["observation_interval_h"] == [1, 2]


def test_carryover_and_exogenous_design_zero_keep_actual_auc_start():
    p = points([1, 2, 3], [10, 7, 3])
    assert calc(p)["auc_window_start_h"] == 0
    m = calc(p, origin="not reported")
    assert m["auc_window_start_h"] == 1 and m["auc_0_tlast"] is None and m["auc_observed"] > 0
    pre = points([-0.1], [1])[0]
    m = calc([pre, *p])
    assert m["baseline_status"] == "UNEXPLAINED" and m["onset_status"] == "NOT_ASSESSABLE"
    assert "RESIDUAL_BASELINE" in m["caveats"] and m["auc_0_tlast"] is None
    assert calc(p, known_finite_administration=True)["t1"]["eligible_count"] == 0
    iv = calc(p, route_class="IV")
    assert iv["auc_window_start_h"] == 1 and iv["auc_0_tlast"] is None


def test_t2_group_unknown_and_verified_units_and_triple_removal():
    p = points([1, 2, 3, 4, 5, 6], [9, 1, 9, 9, 1, 9])
    for level in ["GROUP_MEAN", "INDIVIDUAL_IDENTITY_UNVERIFIED"]:
        r = absorption.t2_curve(p, card(record_level=level), level)
        assert r["formal_status"] == "CANNOT_ASSESS" and r["valley"] and not r["test_executed"]
        assert r["T2_NUMERIC_CONTRADICTION"] is None
    r = absorption.t2_curve(p, card())
    assert r["formal_status"] == "EXCLUDED_UNDER_STATED_ASSUMPTIONS" and r["test_executed"]
    assert len(r["removals"]) == 6 and r["robust"] and r["eligible_count"] == math.comb(6, 3)
    r = absorption.t2_curve(p[:3], card())
    assert r["formal_status"] == "NOT_EXCLUDED" and "INDEPENDENT_SUPPORT_NOT_ASSESSABLE" in r["flags"]
    p[1].update(status="BLQ", c=None, lloq=.6, hi=.6)
    r = absorption.t2_curve(p[:3], card())
    assert r["m_rise"] > 0 and r["relative"] is None


def test_censoring_duplicates_sparse_and_suffix_selection():
    p = points([1, 2, 3, 4, 5, 6, 7], [64, 32, 16, 8, 4, 2, 1])
    m = calc(p)
    assert m["terminal_selected"]["n"] == 6 and m["terminal_selected"]["thalf"] == pytest.approx(1)
    p[3].update(status="BLQ", c=None, lloq=.2)
    m = calc(p)
    assert "INTERIOR_BLQ" in m["caveats"] and m["auc_observed"] is None
    assert m["terminal_selected"]["record_ids"] == ["P4", "P5", "P6"]
    p.append({"t": 5, "c": 3.5, "status": "QUANTIFIED", "record_id": "conflict"})
    assert calc(p)["terminal_selected"] is None and "CONFLICTING_DUPLICATE" in calc(p)["caveats"]
    p[3].update(status="ABOVE_ULOQ", uloq=100)
    assert calc(p)["cmax_status"] == "LOWER_BOUND_ONLY" and calc(p)["cmax_lower_bound"] == 100
    assert calc(points([1], [2]))["t1_label"] == "CANNOT_ASSESS"
    assert calc([{"t": 2, "c": None, "lloq": .1, "status": "BLQ"}])["not_assessable_reason"] == "all postdose samples BLQ"


def test_original_extraction_preserves_missingness_and_rejects_unverified_identity():
    entry = {"dataset_id": "X", "role": "PK_OBSERVATIONS", "experimental_unit": "individual rats",
             "metadata": {"record_category": "INDIVIDUAL", "dosing_regimen": "single dose", "route_class": "EV",
                          "route_detail": "SC", "matrix_category": "PLASMA_SERUM_BLOOD"},
             "columns": [{"id": "t", "meaning": "TIME", "unit": "h"}, {"id": "v", "meaning": "CONCENTRATION", "unit": "mg/L"}],
             "records": [{"record_id": f"R{i}", "t": t, "v": v, "value_status": {"v": st}, "lo": lo, "hi": hi}
                         for i, (t, v, st, lo, hi) in enumerate([(0, 0, "MEASURED_ZERO", 0, .1), (1, 1, "QUANTIFIED", .9, 1.1),
                                                                  (2, None, "NOT_SAMPLED", None, None), (3, None, "ABOVE_ULOQ", None, None)])]}
    c, [s] = absorption.extract(entry)
    assert c["identity_verified"] == "no" and c["dose_time_basis"] == "MEASURED"
    assert [p["status"] for p in s["points"]] == ["MEASURED_ZERO", "QUANTIFIED", "NOT_SAMPLED", "ABOVE_ULOQ"]
    assert c["record_level"] == "INDIVIDUAL_IDENTITY_UNVERIFIED"
    entry["metadata"]["serial_identity_verified"] = True
    assert absorption.extract(entry)[0]["record_level"] == "INDIVIDUAL"


def test_all_blq_profiles_have_no_numerical_or_formal_search():
    p = [{"record_id": f"B{i}", "t": i + 1, "c": None, "status": "BLQ", "lloq": .1}
         for i in range(4)]
    p.insert(1, {"record_id": "lost", "t": 1.5, "c": None, "status": "SAMPLE_LOST"})
    m = calc(p)
    assert m["n_blq"] == 4 and m["not_assessable_reason"] == "all postdose samples BLQ"
    for r in (m["t1"], absorption.t2_curve(p, card())):
        assert r["formal_status"] == "CANNOT_ASSESS" and r["test_executed"] is False
        assert r["eligible_count"] == 0 and r["best"] is None and r["removals"] == []
        assert r["numeric_contradiction"] is None
    assert m["auc_observed"] is None


def test_noncentral_profile_keeps_quantified_observations_without_absorption_estimates():
    p = points([1, 2, 3, 4, 5, 6, 7], [2, 80, 40, 20, 10, 5, 2.5])
    m = calc(p, matrix_category="ELF")
    assert m["observation_scope"] == "NONCENTRAL_OBSERVED_VALUES_ONLY"
    assert m["observed_quantified_cmax"] == 80 and m["observed_quantified_tmax_h"] == 2
    assert m["_t"] == [v["t"] for v in p] and m["_c"] == [v["c"] for v in p]
    assert m["auc_status"] == "WITHHELD_NONCENTRAL_MATRIX" and m["auc_observed"] is None
    assert m["terminal_selected"] is None and not m["terminal_windows"]
    assert m["tail_share"] is None and m["split"] is None and m["dips_described"] is None
    assert m["onset_status"] == m["rise_shape"] == "NOT_ASSESSABLE" and not m["increments"]
    assert m["t1"]["eligible_count"] == 0 and m["t1_label"] == "CANNOT_ASSESS"
    assert absorption.t2_curve(p, card(matrix_category="ELF"))["eligible_count"] == 0


def test_subject_and_period_design_only_propagate_if_supplied():
    meta = {"period_by_subject": {"S1": 2}, "subject_by_series": {"column_A": "S1"},
            "carryover_controlled": True}
    c, _ = absorption.extract({"dataset_id": "designed", "metadata": meta})
    assert all(c[k] == v for k, v in meta.items())
    missing, _ = absorption.extract({"dataset_id": "unknown"})
    assert all(k not in missing for k in meta)
