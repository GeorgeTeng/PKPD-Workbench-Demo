"""Permanent coverage checks for the published r4.3 mechanism inventory."""
import json
from pathlib import Path

import pytest

from research_pipeline import eda_absorption_assessment as assess
from research_pipeline import eda_absorption_mechanisms as handoff
from research_pipeline.eda_absorption_reader import alternatives


RULES = Path(__file__).resolve().parents[2] / "rules" / "eda"
REGISTRY = RULES / handoff.CATALOG_FILE
CORE = """
first_order first_order_lag zero_order zero_order_lag transit transit_lag parallel_immediate
parallel_zero_first separated_inputs burst_sustained inverse_gaussian input_rate_limited
uptake_extent_loss efflux_saturation first_pass_saturation solubility_limited gastric_emptying
absorption_window depot_release pulmonary_enteral enterohepatic flip_flop ongoing_input
multicompartment nonlinear_elimination changing_clearance binding_distribution f_change
cl_v_coscaling rate_only mixed_rate_extent occasion_effect baseline_carryover timing_sampling
parallel_linear_saturable_input parallel_linear_saturable_elimination variable_lag
finite_administration dose_proportional shared_one_compartment
""".split()
MATRIX = {
    "lt1_immediate": (True, False), "eq1_immediate": (True, True), "gt1_immediate": (False, True),
    "lt1_lag": (False, False), "eq1_lag": (False, True), "gt1_lag": (False, True),
}


def entries():
    catalog, _ = handoff.read_catalog(REGISTRY, "r4.3")
    return {c["id"]: c for c in catalog["candidates"]}


def test_named_families_and_all_nine_questions_remain_covered():
    by_id = entries()
    assert set(CORE) <= by_id.keys()
    assert {n for c in by_id.values() for n in c["questions"]} == set(range(1, 10))
    for suffix, expected in MATRIX.items():
        c = by_id["weibull_" + suffix]
        assert (c["t1"], c["t2"]) == expected
        assert "piotrovskii1987" in c["sources"]
    assert by_id["inverse_gaussian"]["rule"].startswith("Literature extension")


def test_missing_weibull_cell_stops_generation(tmp_path):
    data = json.loads(REGISTRY.read_bytes())
    data["candidates"] = [c for c in data["candidates"] if c["id"] != "weibull_lt1_lag"]
    path = tmp_path / REGISTRY.name
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="Weibull"):
        handoff.read_catalog(path, "r4.3")


@pytest.mark.parametrize("test", ["T1", "T2"])
def test_exclusion_stays_with_proven_shape_and_named_profile(test):
    by_id = entries()
    card = {"dataset_id": "SYN", "route_detail": "SC", "record_level": "INDIVIDUAL", "tests_allowed": True}
    result = {"formal_status": assess.EXCLUDED, "test_executed": True}
    series = {"metrics": {"n_quantified": 7, "t1": result if test == "T1" else {}},
              "t2": result if test == "T2" else {}}
    for suffix, expected in MATRIX.items():
        c = by_id["weibull_" + suffix]
        profile = assess.profile_candidate(c, card, series, False)
        applicable = dict(zip(("T1", "T2"), expected))
        assert (profile["formal_status"] == assess.EXCLUDED) == applicable[test]
    result["flags"] = ["SENSITIVITY_ONLY"]
    assert assess.profile_candidate(by_id["first_order"], card, series, False)["formal_status"] != assess.EXCLUDED


def test_ambiguous_route_and_same_drug_other_route_stay_separate():
    by_id = entries()
    profiles = [({"dataset_id": str(n), "route_detail": route}, {}, True)
                for n, route in enumerate(("IT", "SC"))]
    lung = assess.evaluate(by_id["pulmonary_enteral"], profiles, [], {})
    assert lung["status"] == "ROUTE_SCOPE_UNRESOLVED"
    assert lung["score"] == 0
    assert {p["route_scope"] for p in lung["profile_assessments"]} == {"ROUTE_SCOPE_UNRESOLVED", "OUTSIDE_ROUTE_SCOPE"}
    assert assess.evaluate(by_id["depot_release"], profiles, [], {})["status"] == "INSUFFICIENT_DATA"


def test_reader_does_not_offer_a_scoped_exclusion_as_an_open_alternative():
    c = {"dataset_id": "SYN", "record_level": "INDIVIDUAL", "route_detail": "SC", "tests_allowed": True}
    s = {"metrics": {"n_quantified": 6, "t1": {"formal_status": assess.EXCLUDED, "test_executed": True}}}
    rows = {k: assess.evaluate(v, [(c, s, False)], [], {}) for k, v in entries().items()}
    text = alternatives(rows["first_order"], rows)
    assert rows["zero_order"]["status"] == "EXCLUDED_IN_SPECIFIED_PROFILES"
    assert "zero-order input from dosing" not in text
    assert "first-order input after a fixed lag" in text


def test_fixed_lag_limit_requires_positive_lower_bound_and_ordered_sample_time():
    card = {"dataset_id": "SYN", "tests_allowed": True, "record_level": "GROUP_MEAN"}
    p = {"record_id": "OBS", "t": 1, "t_lo": .95, "t_hi": 1.05, "status": "QUANTIFIED", "c": 2, "lo": 1}
    series = {"metrics": {"first_t": 1, "n_quantified": 1, "t1_points": [p]}}
    def lag_clues():
        return [c for c in assess.curve_cues(card, series) if c.kind == "CONDITIONAL_LIMIT_ON_FIXED_LAG"]
    assert len(lag_clues()) == 1
    p["lo"] = 0
    assert lag_clues() == []
    p.update(lo=1, t_hi=.99)
    assert lag_clues() == []


@pytest.mark.parametrize("lower,latest,should_bound", [(1, 1.05, True), (0, 1.05, False), (1, .99, False)])
def test_reader_respects_conditional_lag_evidence(lower, latest, should_bound):
    card = {"dataset_id": "EXAMPLE", "tests_allowed": True, "matrix_category": "PLASMA_SERUM_BLOOD",
            "record_level": "GROUP_MEAN", "unit": "mg/L", "route_detail": "SC"}
    point = {"record_id": "OBS", "t": 1, "t_lo": .95, "t_hi": latest, "status": "QUANTIFIED", "c": 2, "lo": lower}
    series = {"series_id": "mean", "metrics": {"first_t": 1, "first_sample_h": 1, "tmax": 1, "cmax": 2,
                                               "n_quantified": 1, "t1_points": [point]}}
    candidate = entries()["first_order_lag"]
    row = assess.evaluate(candidate, [(card, series, False)], list(assess.curve_cues(card, series)), {})
    reading = handoff.support_text(row, candidate, [{"card": card, "series": [series]}], [], [], [])
    assert ("1.05 h" in reading) is should_bound


def test_unequal_terminal_windows_retain_a_directional_flip_flop_check():
    windows = {"ev_window_h": [1, 8], "iv_window_h": [1, 4], "ratio": 2,
               "grade": "EV_SHALLOWER_MARKED", "same_window": False}
    comparison = {"ev": "EV_SYN", "iv": "IV_SYN",
                  "terminal_comparison": {"comparison_status": "DIFFERENT_WINDOWS", "pairs": [windows]}}
    clue, = [c for c in assess.reference_cues(comparison) if "flip_flop" in c.candidates]
    assert clue.score == 1 and "remains unresolved" in clue.text
    windows.update(grade="COMPARABLE", ratio=1)
    assert all("flip_flop" not in c.candidates for c in assess.reference_cues(comparison))
