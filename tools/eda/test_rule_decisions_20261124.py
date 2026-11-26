"""Regression tests for the rule decisions of 2026-11-24 (R1 to R10, M1 to M8, L1 to L8). Synthetic data only."""
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import conftest  # noqa: F401,E402
from research_pipeline import eda_absorption as ab  # noqa: E402
from research_pipeline import eda_distribution as dist  # noqa: E402
from research_pipeline import eda_elimination as el  # noqa: E402
import eda_common as COMMON  # noqa: E402


# ---------------------------------------------------------------- R8 item 4: quantiles in the far tail

@pytest.mark.parametrize("m,df", [(10, 1), (400, 1), (2000, 2), (10 ** 5, 5), (3, 30)])
def test_t_quantile_is_not_truncated_for_large_families(m, df):
    stats = pytest.importorskip("scipy.stats")
    q = 1 - 0.025 / m
    assert ab.t_ppf(q, df) == pytest.approx(stats.t.ppf(q, df), rel=1e-8)


def test_t_quantile_lower_tail_by_symmetry():
    assert ab.t_ppf(0.025, 4) == pytest.approx(-ab.t_ppf(0.975, 4))
    assert ab.t_ppf(0.9975, 1) == pytest.approx(127.321, abs=1e-3)   # the m = 10, df = 1 factor quoted in R8


# ---------------------------------------------------------------- R6: display label

def test_insufficient_evidence_label_keeps_the_code():
    assert ab.ST_NO == "Insufficient evidence"
    assert ab.ST_CODE[ab.ST_NO] == "NOT_ANSWERABLE_YET"


# ---------------------------------------------------------------- R6 / E8: Q3 does not depend on row order

def _q3(rows):
    return el.q3_row({"item31": {"applies": True, "clearance_contrasts": [], "repeat_regimens": [], "urine_by_occasion": [],
                                 "reported_by_occasion": [], "alternatives": [], "upstream": rows}})


def test_q3_status_and_sentence_are_order_independent():
    rows = [{"source": "distribution T9 (v)", "first": "a", "later": "b", "t9": "CANNOT_ASSESS", "flags": ["SENSITIVITY_ONLY"]},
            {"source": "distribution T9 (v)", "first": "c", "later": "d", "t9": "NOT_EXCLUDED", "flags": []}]
    one, two = _q3(rows), _q3(list(reversed(rows)))
    assert one["status_code"] == two["status_code"] == "PARTLY_ANSWERABLE"
    assert one["observed"] == two["observed"]
    assert "1 of 2" in one["basis"]


def test_q3_confounded_formal_result_is_not_answerable():
    q = _q3([{"source": "absorption item 23 (v)", "first": "a", "later": "b", "t9": "EXCLUDED_UNDER_STATED_ASSUMPTIONS",
              "flags": ["OCCASION_CONFOUNDED"]}])
    assert q["status_code"] == "PARTLY_ANSWERABLE"


# ---------------------------------------------------------------- R10: formal record versus sensitivity record

def test_formal_cannot_assess_keeps_only_its_own_flags():
    rec = {"t2_label": "CANNOT_ASSESS", "t2_flags": ["SENSITIVITY_ONLY", "SINGLE_POINT_SUPPORT", "LOO_NOT_ASSESSABLE"],
           "inner": [{"t4_label": "CANNOT_ASSESS", "t4_flags": ["SENSITIVITY_ONLY", "BORDERLINE", "CONDITIONAL_ON_COMMON_K"]}],
           "ok": {"t6_label": "NOT_EXCLUDED", "t6_flags": ["SINGLE_POINT_SUPPORT"]}}
    assert COMMON.separate_sensitivity_flags(rec) == 2
    assert rec["t2_flags"] == ["SENSITIVITY_ONLY"] and rec["t2_sensitivity_flags"] == ["SINGLE_POINT_SUPPORT", "LOO_NOT_ASSESSABLE"]
    assert rec["inner"][0]["t4_flags"] == ["SENSITIVITY_ONLY", "CONDITIONAL_ON_COMMON_K"]
    assert rec["ok"]["t6_flags"] == ["SINGLE_POINT_SUPPORT"]   # a formal NOT_EXCLUDED keeps its removal flag


# ---------------------------------------------------------------- R10: quantified predose value (T6 and T7)

def _iv_series(ts, cs, **extra):
    import test_distribution_r15 as T
    s = T._series(ts, cs, noise=T._matched())
    s.update(extra)
    return s


def _with_predose(**extra):
    import test_distribution_r15 as T
    ts = [0.25, 0.5, 1, 2, 4, 6, 8, 12]
    s = _iv_series(ts, [T._biexp(t) for t in ts], **extra)
    s["points"].insert(0, dict(s["points"][0], t=0.0, c=0.05, status="QUANTIFIED"))
    return s


def test_unexplained_predose_value_stops_both_tests():
    r = dist.item24_profile(_with_predose())
    assert r["t6_label"] == r["t7_label"] == "CANNOT_ASSESS"
    assert "predose" in r["t6_reason"] and "predose" in r["t7_reason"]


def test_predose_residue_from_completed_central_input_keeps_t7_only():
    r = dist.item24_profile(_with_predose(predose_residue_central_completed=True))
    assert r["t7_label"] != "CANNOT_ASSESS"
    assert r["t6_label"] == "CANNOT_ASSESS" and "unexplained" in r["t6_reason"]


def test_stated_residue_assumption_gives_a_t6_sensitivity_reading_only():
    r = dist.item24_profile(_with_predose(predose_residue_assumption="residue decays with this disposition"))
    assert r["t6_label"] == "CANNOT_ASSESS" and r.get("t6_sensitivity_label") in ("NOT_EXCLUDED", "EXCLUDED_UNDER_STATED_ASSUMPTIONS")
    assert "stated residue assumption" in r["t6_reason"]
    assert r["t7_label"] == "CANNOT_ASSESS" and "central" in r["t7_reason"]


def test_unwashed_earlier_extravascular_dose_stops_t7():
    import test_distribution_r15 as T
    ts = [0.25, 0.5, 1, 2, 4, 6, 8, 12]
    r = dist.item24_profile(_iv_series(ts, [T._biexp(t) for t in ts]), None, True, {"EV"})
    assert r["t7_label"] == "CANNOT_ASSESS" and "input may continue" in r["t7_reason"]
    r = dist.item24_profile(_iv_series(ts, [T._biexp(t) for t in ts]), None, True, {"IV"})
    assert r["t7_label"] != "CANNOT_ASSESS"


# ---------------------------------------------------------------- R7 item 3 / M8 item 7: Cmax/D is a descriptive screen

def _curve(times, values, dose):
    from test_observation_integrity import curve
    return curve(times, values, dose=dose)


def test_cmax_screen_is_registered_and_gives_indirect_support_at_most():
    t = [0.5, 1, 2, 4, 8, 12]
    low = _curve(t, [2, 6, 4, 2.4, 1.0, 0.45], 1)
    high = _curve(t, [1.2, 2.4, 3.8, 4.6, 2.4, 1.2], 2)
    r = ab.dose_series([low, high], False)
    sc = r["cmax_screen"]
    assert sc["check"] == "CMAX_D_SCREEN" and sc["max_support"] == "INDIRECT_SUPPORT"
    assert sc["cmax_d_ratio"] == pytest.approx(r["cmax_d_ratio"])
    if sc["peak_bracketed_by_samples"] and sc["windows_comparable"] and r["cmax_d_ratio"] < 0.5 and 0.8 <= r["R_window"] <= 1.25:
        assert sc["result"] == "CMAX_D_LOW_AUC_KEPT"
    # the screen signals of the hypothesis layer are hints (indirect), never firm signals
    src = Path(ab.__file__).read_text(encoding="utf-8")
    for sid in ("rate_saturates", "peak_rises_only", "peak_falls"):
        i = src.index(f'_hsig("{sid}"')
        assert src[i:i + 60].split(",")[2].strip() == "HINT", sid


def test_cmax_screen_needs_a_bracketed_peak():
    t = [0.5, 1, 2, 4]
    low = _curve(t, [6, 4, 2, 1], 1)        # peak at the first sample
    high = _curve(t, [6, 4, 2, 1], 2)
    assert ab.dose_series([low, high], False)["cmax_screen"]["result"] == "NOT_APPLICABLE"


# ---------------------------------------------------------------- R9: the modeling hand-off reads the shared flip-flop reading

def _handoff_pair(reading, cls="SLOWER", missing=None):
    tail = {"test": {"p": 0.01, "df": 4}, "class": cls, "ev_window_h": [4, 12], "iv_window_h": [4, 12], "ratio": 2.4,
            "common_tail": {}, "flip_flop_reading": reading, "missing_side": missing or [],
            "reading_text": "not assessable: " + "; ".join(missing) if missing else reading}
    if reading is None:
        del tail["flip_flop_reading"]
    board = {"species": "rat", "study": "S1", "questions": []}
    ds = {"EV1": {"card": {"route_detail": "PO", "dataset_id": "EV1"}, "series": [{"metrics": {"terminal_selected": {"thalf": 6.0}}}]}}
    refs = {"IV1": {"metrics": {"terminal_selected": {"thalf": 2.5}}}}
    return board, {"ev": "EV1", "iv": "IV1", "tail": tail, "dose_ev": 1, "dose_iv": 1}, ds, refs


def test_handoff_does_not_read_a_slower_class_as_flip_flop_when_the_reading_is_open():
    import modeling_handoff as mh
    b, pair, ds, refs = _handoff_pair("NOT_ASSESSABLE", missing=["IV: no post-distribution window (LOW_POWER)"])
    kind, row = mh.terminal_pattern(b, pair, ds, refs, None)
    assert kind == "route_reference"
    assert "not evidence for or against" in row["still_possible"] and "IV: no post-distribution window" in row["next_check"]
    b, pair, ds, refs = _handoff_pair("UNRESOLVED")
    assert mh.terminal_pattern(b, pair, ds, refs, None)[0] == "sensitive_shape"
    b, pair, ds, refs = _handoff_pair("COMMON_TERMINAL_COMPATIBLE")      # the slope class alone does not make a slow-input finding
    assert mh.terminal_pattern(b, pair, ds, refs, None)[0] == "route_reference"
    b, pair, ds, refs = _handoff_pair("ABSORPTION_INFLUENCED_CANDIDATE")
    assert "flip-flop" in mh.terminal_pattern(b, pair, ds, refs, None)[1]["still_possible"]
    b, pair, ds, refs = _handoff_pair(None)                              # a record built before R9 keeps the class-based reading
    assert "flip-flop" in mh.terminal_pattern(b, pair, ds, refs, None)[1]["still_possible"]


# ---------------------------------------------------------------- R9: indirect comparators give indirect support at most

def _ev_met(cid, th, **card):
    c = {"dataset_id": cid, "route_detail": "PO", "analyte": "parent", "matrix": "plasma"}
    c.update(card)
    return (cid, {"card": c}, {}, {"terminal_selected": {"thalf": th}})


def test_indirect_comparators_are_listed_with_source_and_limits():
    mets = [_ev_met("EV_po", 9.0, comparator_iv_terminal={"thalf_h": 3.0, "source": "a published IV study"}),
            _ev_met("EV_im", 2.5, route_detail="IM"),
            _ev_met("EV_po_nosrc", 9.0, comparator_iv_terminal={"thalf_h": 3.0})]
    out = ab.ff_indirect_comparators(mets)
    lit = [x for x in out if x["kind"] == "LITERATURE_IV_TERMINAL"]
    assert [x["ev"] for x in lit] == ["EV_po"]                       # a value without a source is not listed
    assert lit[0]["reading"] == "ABSORPTION_INFLUENCED_CANDIDATE" and lit[0]["limits"]
    other = [x for x in out if x["kind"] == "OTHER_EV_CURVE" and x["ev"] == "EV_po"]
    assert other and other[0]["source"] == "EV_im" and other[0]["ratio"] == pytest.approx(3.6)
    assert not [x for x in out if x["kind"] == "OTHER_EV_CURVE" and x["ev"] == "EV_im"]   # the faster curve has no faster comparator
    sigs = []
    ab._ff_indirect_hint(sigs.append, out)
    assert len(sigs) == 1 and sigs[0]["strength"] == ab.HINT and sigs[0]["id"] == "tail_slower_than_indirect"


def test_indirect_comparator_needs_the_same_analyte_and_matrix_and_another_input():
    mets = [_ev_met("A", 9.0), _ev_met("B", 2.0, route_detail="IM", matrix="serum"), _ev_met("C", 2.0)]
    assert ab.ff_indirect_comparators(mets) == []


# ---------------------------------------------------------------- L1: a source-reported predose zero keeps its identity

def test_predose_zero_keeps_its_status_in_distribution():
    assert dist.parse_value(0, "REPORTED_ZERO_PREDOSE") == (0.0, None, None, "REPORTED_ZERO_PREDOSE")
    assert dist.parse_value(0, "QUANTIFIED")[3] == "QUANTIFIED"
    assert COMMON.is_predose_zero({"status": "REPORTED_ZERO_PREDOSE", "t": 0.0, "c": 0.0})
    assert not COMMON.is_quantified({"status": "QUANTIFIED", "t": 0.0, "c": 0.0})      # a printed zero is not a quantified point


def test_elimination_area_anchor_accepts_the_predose_zero_for_ev_only():
    pts = [{"t": 0.0, "c": 0.0, "status": "REPORTED_ZERO_PREDOSE"}, {"t": 1.0, "c": 2.0, "status": "QUANTIFIED"},
           {"t": 2.0, "c": 1.0, "status": "QUANTIFIED"}]
    assert [p["t"] for p in el._pts({"points": pts, "route_class": "EV"})] == [0.0, 1.0, 2.0]
    assert [p["t"] for p in el._pts({"points": pts, "route_class": "IV"})] == [1.0, 2.0]


# ---------------------------------------------------------------- L2: one sample-size reader and range policy

@pytest.mark.parametrize("text,n,rng", [("terminal cohorts by sampling time; published mean ± SE; source n=10", 10, None),
                                        ("3 or 4 mice/time", None, [3, 4]), ("n = 3–4", None, [3, 4]),
                                        ("groups of three rats", 3, None), ("a total of 24 rats", None, None)])
def test_sample_size_is_read_once_for_every_section(text, n, rng):
    assert COMMON.sample_size(text)[:2] == (n, rng)
    assert ab._n_from_notes(text) == n and dist._sample_size(text) == (n, rng) and el.n_from(text) == n


# ---------------------------------------------------------------- L4: tests and production share the species registry

def test_species_registry_is_shared():
    assert ab._SPECIES is dist._SP_HEAD is ab.COMMON.SPECIES
    for text, sp in (("koala", "Koala"), ("jenny", "Donkey"), ("minipig", "Pig"), ("Guinea pig", "Guinea pig"), ("canine", "Dog")):
        assert ab.species_group(text) == dist.species_in(text) == el.species_of(text) == sp


# ---------------------------------------------------------------- L5: one EV post-peak description

def _pp(ts, cs):
    return [{"t": t, "c": c} for t, c in zip(ts, cs)]


def test_ev_split_needs_two_declining_halves_and_a_nonzero_early_slope():
    flat = COMMON.ev_post_peak_split(_pp([2, 4, 8, 12, 24, 36], [10, 6, 2.5, 1.8, 1.0, 0.6]), "INDIVIDUAL")
    assert flat["class"] == "DECLINE_FLATTENS" and flat["ratio"] < 0.8
    rise = COMMON.ev_post_peak_split(_pp([2, 4, 6, 8], [10, 6, 5, 5.5]), "INDIVIDUAL")
    assert rise["ratio"] is None and "late half does not decline" in rise["reason"]
    shallow = COMMON.ev_post_peak_split(_pp([4, 6, 8, 12], [10, 9.6, 8.0, 6.0]), "GROUP_MEAN")
    assert shallow["ratio"] is None and shallow["reason"] == "the early slope is not distinguished from zero"
    assert COMMON.ev_post_peak_split(_pp([2, 4, 8], [10, 6, 3]), "INDIVIDUAL") is None


# ---------------------------------------------------------------- L6: the mixing caution ends exactly at 5 minutes

def test_early_mixing_bound_is_inclusive_of_five_minutes():
    assert dist.early_mixing(5 / 60) and dist.early_mixing(35 / 60 - 0.5) and dist.early_mixing(0.0833)
    assert not dist.early_mixing(0.0834) and not dist.early_mixing(None)


# ---------------------------------------------------------------- L8: loading dose plus infusion

def test_loading_plus_infusion_never_uses_the_loading_dose_as_denominator():
    e = {"metadata": {"loading_dose_mg_kg": 3.86, "dosing_regimen": "loading injection followed after five minutes by continuous IV infusion"}}
    reg = COMMON.dose_regimen(e)
    assert reg["loading_plus_infusion"] and reg["loading_dose_mg_kg"] == 3.86 and reg["denominator_mg_kg"] is None
    dose, why = ab._dose(e)
    assert dose is None and why.startswith("SUSPENDED") and "F reading are suspended" in why
    done = {"metadata": {"loading_dose_mg_kg": 2, "infusion_rate_mg_kg_h": 1, "delivered_dose_mg_kg": 6, "dosing_regimen": "loading dose then an infusion over 4 h"}}
    assert ab._dose(done) == (6, "metadata delivered dose")


# ---------------------------------------------------------------- G8: the portal freezes the local figure renderer

def test_portal_prefers_the_local_figure_renderer():
    import publish_portal as pp
    src = Path(pp.__file__).read_text(encoding="utf-8")
    i = src.index('source = Path(__file__).resolve().with_name("figure_notes.py")')
    assert i < src.index('source = owner.with_name("figure_notes.py")')


# ---------------------------------------------------------------- M5: guide question numbers and stable references

def test_rows_carry_guide_numbers_and_stable_ids():
    d6 = dist._qrow(6, ab.ST_PART, "x")
    assert (d6["q"], d6["qid"], d6["guide_q"], d6["display_ref"], d6["legacy_q"], d6["legacy_display_number"]) == \
        (6, "unbound_plasma_exposure", [8], "Q8", [6], 3)
    d2 = dist._qrow(2, ab.ST_PART, "x")
    assert d2["guide_q"] == [] and d2["display_number"] is None and d2["display_ref"] == "Vc bound"
    assert dist._qrow(5, ab.ST_PART, "x")["also_guide_q"] == [5, 7]
    e5, e7 = el._qrow(5, ab.ST_PART, "x"), el._qrow(7, ab.ST_PART, "x")
    assert (e5["display_ref"], e7["display_ref"], el._qrow(6, ab.ST_PART, "x")["display_ref"]) == ("Q4", "Q5", "Q6")
    assert e5["qid"] == "urine" and e5["legacy_q"] == [5]


def test_rows_are_ordered_by_guide_number_then_unnumbered_rows():
    rows = [dist._qrow(q, ab.ST_PART, "x") for q in (1, 2, 3, 4, 5, 6, 7)]
    rows.sort(key=lambda r: COMMON.guide_order("distribution", r))
    assert [r["display_ref"] for r in rows] == ["Q1", "Q2", "Q6", "Q8", "Vc bound", "IV and EV routes", "Across species"]
    erows = sorted((el._qrow(q, ab.ST_PART, "x") for q in (1, 2, 3, 5, 6, 7)), key=lambda r: COMMON.guide_order("elimination", r))
    assert [r["q"] for r in erows] == [1, 2, 3, 5, 7, 6]


def test_guide_questions_without_a_row_are_recorded():
    cov = {c["guide_q"]: c for c in COMMON.guide_coverage("elimination", [el._qrow(q, ab.ST_PART, "x") for q in (1, 2, 3, 5, 6, 7)])}
    assert [n for n, c in cov.items() if c["coverage"] == "NO_ENGINE_ROW"] == [7, 8]
    assert cov[4]["rows"] == ["urine"]
    dcov = {c["guide_q"]: c for c in COMMON.guide_coverage("distribution", [dist._qrow(q, ab.ST_PART, "x") for q in range(1, 8)])}
    assert dcov[3]["coverage"] == "NO_ENGINE_ROW" and "iv_reference_window" in dcov[3]["note"]
    assert {n for n, c in dcov.items() if c["coverage"] == "SHOWN_IN_ROW"} == {4, 5, 7, 9}
    assert "Q3 (No row" in COMMON.guide_gap_words(list(dcov.values()))


def test_rests_on_names_rows_by_stable_id():
    board = {"board_id": "s/dog/single", "hypothesis": {"text": "t", "rests_on": "Rests on: Q6 recovery table (x).", "source_ids": []},
             "questions": [el._qrow(6, ab.ST_PART, "x"), el._qrow(5, ab.ST_PART, "y")]}
    v1 = COMMON.hypothesis_v1_for("elimination", board, "s/dog/single")
    assert v1["rests_on"] == ["elimination:s/dog/single:recovery"]


def test_elimination_keeps_absorption_t5_and_distribution_t9_apart():
    plasma = [{"sid": "d1:a", "dataset_id": "d1", "route_class": "EV", "occasion": "LATER_DOSE"}]
    dist_data = {"version": "dv", "repeat_dosing": [{"first_sid": "d1:a", "later_sid": "d1:b", "t9_label": "NOT_EXCLUDED", "t9_flags": [], "rows": []}]}
    abs_data = {"version": "av", "conditions": [{"a": "d1", "b": "d0", "differing_attributes": ["occasion"], "t5_label": "CANNOT_ASSESS",
                                                 "t5_flags": ["SENSITIVITY_ONLY"]}]}
    out = el.item31({"study": "s", "species": "dog"}, plasma, dist_data, abs_data, [], [])
    by = {u["test_id"]: u for u in out["upstream"]}
    assert set(by) == {"distribution:T9", "absorption:T5"}
    assert by["absorption:T5"]["result"] == "CANNOT_ASSESS" and by["absorption:T5"]["upstream_question"] == "absorption:one_multiplier_between_conditions"
    assert by["distribution:T9"]["asks"] != by["absorption:T5"]["asks"]
    q = _q3(out["upstream"])
    assert "absorption T5" in q["observed"] and "one multiplier" in q["observed"]
    assert q["status_code"] == "PARTLY_ANSWERABLE"


def test_elimination_handoff_question_ids_are_stable():
    assert COMMON.question_key("elimination", 5) == "elimination:urine"
    assert COMMON.question_key("distribution", dist._qrow(6, ab.ST_PART, "x"), "b1") == "distribution:b1:unbound_plasma_exposure"


# ---------------------------------------------------------------- M6: Vc upper bound

def _vc_series(ts, cs, **extra):
    import test_distribution_r15 as T
    s = T._series(ts, cs, noise=extra.pop("noise", {}))
    s.update(species="dog", matrix_class="PLASMA", dose=10.0, **extra)
    return s


def test_vc_bound_uses_the_highest_eligible_sample_not_the_earliest():
    s = _vc_series([0.1, 0.25, 0.5, 1, 2], [5.0, 20.0, 12.0, 6.0, 3.0])
    r = dist.item25_bound(s, None, {})
    assert r["vc_upper_bound_l_per_kg"] == pytest.approx(0.5) and r["sample_time_h"] == pytest.approx(0.25)
    assert r["earliest_sample_bound_l_per_kg"] == pytest.approx(2.0)


def test_vc_fit_constraint_covers_every_candidate_sample_and_needs_source_precision():
    ts, cs = [0.1, 0.25, 0.5, 1, 2], [5.0, 20.0, 12.0, 6.0, 3.0]
    import test_distribution_r15 as T
    default = dist.item25_bound(_vc_series(ts, cs), None, {})
    mc = default["modeling_constraint"]
    assert mc["status"] == "SENSITIVITY_ONLY" and mc["family_m"] == 5 and default["lower_bound_basis"] == "SENSITIVITY_ONLY"
    assert any("upper limit on the delivered dose" in x for x in mc["reasons"])
    formal = dist.item25_bound(_vc_series(ts, cs, noise=T._matched(0.05), dose_upper_mg_per_kg=10.5), None, {})
    fm = formal["modeling_constraint"]
    assert fm["status"] == "FORMAL" and fm["dose_mg_per_kg"] == 10.5 and fm["interval_basis"] == "SOURCE_PRECISION"
    z = ab.t_ppf(1 - 0.025 / 5, 1000) * math.sqrt(math.log(1 + 0.05 ** 2))
    assert fm["c_lower_mg_per_l"] == pytest.approx(20.0 * math.exp(-z))
    assert formal["conservative_l_per_kg"] == pytest.approx(10.5 / fm["c_lower_mg_per_l"])
    assert formal["conservative_l_per_kg"] > formal["vc_upper_bound_l_per_kg"]


def test_vc_limit_is_kept_with_unresolved_residue_or_mixing():
    s = _vc_series([0.0, 0.05, 0.25, 0.5, 1], [0.3, 20.0, 12.0, 8.0, 5.0])
    r = dist.item25_bound(s, None, {})
    assert r.get("data_check") != "NOT_ASSESSABLE" or r.get("vc_upper_bound_l_per_kg")
    assert r["vc_upper_bound_l_per_kg"] == pytest.approx(0.5)
    assert "RESIDUE_UNRESOLVED" in r["caveats"] and "EARLY_MIXING_POSSIBLE" in r["caveats"]
    assert r["modeling_constraint"]["status"] == "SENSITIVITY_ONLY"
    assert any("residue" in x for x in r["modeling_constraint"]["reasons"]) and any("mixing" in x for x in r["modeling_constraint"]["reasons"])


# ---------------------------------------------------------------- M8 item 7: regression case of rule decision R7

def _oral(t, ka, k, dose):
    return [dose * ka / (ka - k) * (math.exp(-k * x) - math.exp(-ka * x)) for x in t]


def _group_table(did, t, c, dose):
    recs = [{"record_id": f"{did}_{i}", "time_h": a, "conc": b, "value_status": {"conc": "QUANTIFIED", "time_h": "QUANTIFIED"},
             "source_raw_values": {"conc": str(b)}, "source_row": i + 1, "qc_status": "TECHNICALLY_RETAINED"} for i, (a, b) in enumerate(zip(t, c))]
    meta = {"species": "rat", "drug": "x", "matrix": "plasma", "matrix_category": "PLASMA_SERUM_BLOOD", "analyte_role": "PARENT",
            "origin": "EXOGENOUS", "record_category": "GROUP_SUMMARY", "observation_source": "SOURCE_VALUES", "dosing_regimen": f"single {dose} mg/kg",
            "dose_basis": "as reported mg/kg", "route_class": "EV", "route_detail": "PO", "condition": "fasted", "dose_mg_kg": dose}
    return {"dataset_id": did, "title": did, "study_source_ids": ["S1"], "role": "PK_OBSERVATIONS", "experimental_unit": "Group mean",
            "metadata": meta, "records": recs, "notes": "arithmetic mean",
            "columns": [{"id": "time_h", "header": "Time", "unit": "h", "meaning": "TIME"},
                        {"id": "conc", "header": "Plasma parent", "unit": "ug/mL", "meaning": "CONCENTRATION"}]}


def test_screen_without_sd_and_n_cannot_raise_an_absorption_rate_candidate_to_supported(tmp_path, monkeypatch):
    """Two oral group-mean curves without SD or n; the higher dose has slower input and the same exposure per dose (review A3)."""
    import json
    t = [0.25, 0.5, 1, 2, 4, 6, 8, 12, 16, 24]
    tables = [_group_table("PO_10", t, _oral(t, 4.0, 0.4, 10), 10), _group_table("PO_40", t, _oral(t, 0.30, 0.4, 40), 40)]
    (tmp_path / "source_tables.json").write_text(json.dumps(tables), encoding="utf8")
    monkeypatch.setenv("ABSORPTION_STABILITY", "0")
    monkeypatch.setattr(ab, "render_all", lambda out: None)
    res = ab.build(tmp_path)
    d = res["dose_series"][0]
    assert d["cmax_d_ratio"] < 0.5 and 0.8 <= d["R_window"] <= 1.25 and d["t3_label"] == "CANNOT_ASSESS"
    cands = {c["candidate"]: c for c in res["status_boards"][0]["ranked_candidates"]["candidates"]}
    assert cands["dose.saturable_rate"]["group"] != "SUPPORTED"
    assert not any(c["group"] == "SUPPORTED" and c["candidate"].startswith("dose.") for c in cands.values())
