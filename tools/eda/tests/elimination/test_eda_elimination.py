"""Unit tests for tools/eda/eda_elimination.py (elimination rules, items 29-36). Run: python -m pytest tools/eda"""
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))  # tools/eda
from load_fixed import load  # noqa: E402

el = sys.modules.get("research_pipeline.eda_elimination") or load()


def test_parse_cell_dash_is_missing_not_zero():
    assert el.parse_cell("—")["state"] == "MISSING"
    assert el.parse_cell("-")["value"] is None
    c = el.parse_cell("32.7 ± 2.1")
    assert c["state"] == "QUANTIFIED" and math.isclose(c["value"], 32.7) and math.isclose(c["sd"], 2.1)


def test_parse_interval_hours_and_minutes():
    assert list(el.parse_interval("0-6 h")) == [0.0, 6.0]
    assert list(el.parse_interval("6–24 hr")) == [6.0, 24.0]
    a, b = el.parse_interval("0 to 30 min")
    assert math.isclose(b, 0.5)


def test_dispersion_unknown_when_sd_or_se():
    assert el.dispersion_kind("Mean ± SD/SE, n = 3") == "UNKNOWN"


def test_ratio_check_allows_rounding_only():
    ok = el.ratio_check(0.30, 0.25, 1.2, ["0.30", "0.25", "1.2"])
    bad = el.ratio_check(0.30, 0.25, 1.7, ["0.30", "0.25", "1.7"])
    assert ok["consistent"] and not bad["consistent"]


def test_t10_cannot_assess_without_gfr():
    r = el.t10({"limits": (0.1, None)}, {"low": 0.9, "high": 1.0}, None)
    assert r["status"] == "CANNOT_ASSESS" and "GFR" in r["reason"]


def test_t10_directions_with_sourced_gfr():
    gfr = {"low": 0.30, "high": 0.36, "matched_to_study": True}
    fu = {"low": 0.9, "high": 1.0}
    assert el.t10({"limits": (0.5, None)}, fu, gfr)["direction"] == "above"
    assert el.t10({"limits": (None, 0.1)}, fu, gfr)["direction"] == "below"
    assert el.t10({"limits": (0.3, 0.33)}, fu, gfr)["status"] == "NOT_EXCLUDED"
    # literature GFR: sensitivity context only, never a formal exclusion
    assert el.t10({"limits": (0.5, None)}, fu, dict(gfr, matched_to_study=False))["status"] == "CANNOT_ASSESS"


def test_cl_unit_conversion():
    assert math.isclose(el.cl_to_l_h_kg(10, "mL/min/kg"), 0.6)
    assert el.cl_to_l_h_kg(3.4, "L/h") is None


def _obs(interval, value, basis="INTERVAL", state="QUANTIFIED", rid="r"):
    return {"excretum": "URINE", "analyte": "PARENT", "value_form": "PERCENT_OF_DOSE", "component": None, "dataset_id": "T1", "species": "Rat",
            "group": "Rat (3)", "level": "GROUP_MEAN", "occasion": "FIRST_DOSE", "amount_basis": basis, "interval": interval, "value": value,
            "sd": None, "state": state, "raw": str(value), "note": "", "record_id": rid, "flags": [], "denominator": "administered dose", "n": 3}


CARD = {"T1": {"study": "S1", "assay": "SPECIFIC", "assay_note": "", "route_class": "IV", "dose": 20.0, "dispersion": "UNKNOWN",
               "collection": {"pairing": "NOT_REPORTED", "bladder_emptying": "not reported"}}}


def test_urine_cumulative_late_increment_and_no_lower_limit():
    us = el.urine_series([_obs([0, 6], 24.7), _obs([6, 24], 0.3), _obs([0, 24], 25.0, "TOTAL")], CARD, {"late_increment_share": 0.05})
    u = us[0]
    assert [round(c["value"], 1) for c in u["cumulative"]] == [24.7, 25.0]
    assert u["r_u"] == 25.0 and u["reconcile"]["status"].startswith("reconciled")
    assert "LATE_INCREMENT_SMALL" in u["flags"]
    assert u["fe_lower"] is None and "dispersion" in u["fe_lower_reason"]


def test_urine_missing_interval_is_not_zero_and_not_a_gap_after_the_end():
    us = el.urine_series([_obs([0, 8], 49.1), _obs([6, 24], None, state="MISSING")], CARD, {"late_increment_share": 0.05})
    u = us[0]
    assert u["r_u"] == 49.1 and "COLLECTION_GAP" not in u["flags"]
    assert u["gaps"] and u["gaps"][0]["why"]


def test_item29_window_proxy_uses_shared_auc_routine():
    s = {"sid": "T9:c1", "label": "Rat", "dataset_id": "T9", "study": "S1", "species": "Rat", "route_class": "IV", "route_detail": "iv bolus",
         "iv_mode": "BOLUS", "dose": 10.0, "dose_basis": "mg/kg", "matrix_class": "PLASMA", "level": "GROUP_MEAN", "occasion": "FIRST_DOSE",
         "uf": 1.0, "notes": "", "design": "SERIAL", "digitized": False, "infusion_h": 0.0, "analyte": "PARENT", "unbound": False,
         "points": [{"t": t, "c": c, "status": "QUANTIFIED", "lim": None} for t, c in ((0.25, 20), (0.5, 15), (1, 9), (2, 3))]}
    r = el.item29(s, {}, {}, None, None, [], {})
    expect = 10.0 / el.ab.auc([0.25, 0.5, 1, 2], [20, 15, 9, 3])
    assert math.isclose(r["window_proxy"], expect)
    assert "WINDOW_PROXY" in r["caveats"] and "PARTIAL_WINDOW" in r["caveats"]
    assert r["justified_limit"]["value"] is None          # E0.6: a sampled trapezoid is not a justified limit
    assert r["bound_kind"] in ("none", "SENSITIVITY_ONLY")  # a conditional limit stays a folded sensitivity row
    assert r["cl_upper_tail"] is None                     # no eligible upstream T7, so no tail


def test_item29_respects_withheld_upstream_auc():
    s = {"sid": "T9:c1", "label": "Rat", "dataset_id": "T9", "study": "S1", "species": "Rat", "route_class": "EV", "route_detail": "sc",
         "iv_mode": None, "dose": 10.0, "dose_basis": "mg/kg", "matrix_class": "PLASMA", "level": "INDIVIDUAL", "occasion": "FIRST_DOSE",
         "uf": 1.0, "notes": "", "design": "SERIAL", "digitized": False, "analyte": "PARENT", "unbound": False,
         "points": [{"t": t, "c": 1.0, "status": "QUANTIFIED", "lim": None} for t in (1, 2, 3)]}
    idx = {("T9", "c1"): {"metrics": {"auc_status": "WITHHELD_X"}, "B1": "B1.png"}}
    r = el.item29(s, idx, {"version": "R4"}, None, None, [], {})
    assert r["window_proxy"] is None and "withholds" in r["not_assessable_reason"]


def test_no_new_plasma_panel_is_drawn():
    """Without plasma profiles nothing is drawn. Since 2026-11-25 (George, shared rule 10) the only plasma figure Elimination draws
    itself is the per-animal terminal phase (EMT); other plasma panels are repeated from Distribution and Absorption."""
    el._SPECS.clear()
    b = {"key": "k", "urine": [], "clr": [], "recovery": [], "components": [], "em7b": [], "figs": {}}
    el.figures([b], None)
    assert el._SPECS == []


def test_figure_set_is_limited_to_the_five_em_panels():
    import inspect
    src = inspect.getsource(el.figures)
    names = set(__import__("re").findall(r'_figure\(f"(EM\w+?)_', src))
    assert names <= {"EM1a", "EM5a", "EM5c", "EM6a", "EM7a", "EM7b", "EMT"}   # EMT: terminal phase per animal (George 2026-11-25); EM1a: AUC/dose vs dose (George 2026-11-27)
