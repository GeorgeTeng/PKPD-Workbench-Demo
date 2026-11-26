"""r1.5 Distribution rules: noise tiers, window-start power, prior-dose residue, EV profiles, animal x occasion, APOD ordering."""
import math

import eda_distribution as d


def _series(times, conc, **kw):
    s = {"sid": kw.get("sid", "D:c1"), "label": kw.get("label", "c1"), "dataset_id": "D", "study": "S", "level": "INDIVIDUAL",
         "digitized": False, "design": "SERIAL", "iv_mode": "BOLUS", "infusion_h": 0.0, "flags": [], "source_conflicts": [],
         "analyte": "PARENT", "assay": "parent by LC-MS/MS", "sampling_site": "NOT_REPORTED", "endogenous": False,
         "mean_type": "n/a", "target_binding": "NOT_STATED", "target_binding_quote": "", "matrix_text": "plasma", "uf": 1.0,
         "dose": 1.0, "unbound": False, "route_class": kw.get("route", "IV"), "subject_id": kw.get("subject"),
         "source_occasion": kw.get("occasion"), "washout_verified": kw.get("washout", True), "noise_source": kw.get("noise", {}),
         "lloq_meta": None, "points": [{"t": t, "c": c, "status": "QUANTIFIED", "lim": None} for t, c in zip(times, conc)]}
    return s


# rule decision R8: an assay CV carries a formal interval only with its match to this analysis
CV_MATCH = {"source": "method validation table", "method": "LC-MS/MS", "analyte": "PARENT", "matrix": "PLASMA",
            "range_covered": "QC low to high", "run": "BETWEEN_RUN", "cv_kind": "OBSERVED"}


def _matched(cv=0.03, **extra):
    return dict({"assay_cv": cv, "assay_cv_match": dict(CV_MATCH)}, **extra)


def _biexp(t, a=1.0, al=3.0, b=0.2, be=0.3):
    return a * math.exp(-al * t) + b * math.exp(-be * t)


def test_noise_tier_follows_source_then_default():
    s = _series([0.1, 0.5, 1, 2, 4, 8], [1, .5, .3, .2, .1, .05], noise={"assay_cv": 0.08})
    n = d.noise_setting(s, d._q(s["points"]))
    assert n["tier"] == 1 and abs(n["sigma"] - math.sqrt(math.log(1 + 0.08 ** 2))) < 1e-12
    s2 = _series([0.1, 0.5, 1, 2, 4, 8], [1, .5, .3, .2, .1, .05], noise={"assay_cv_pct": 12})
    assert d.noise_setting(s2, d._q(s2["points"]))["tier"] == 1
    s3 = _series([0.1, 0.5, 1, 2, 4, 8], [1, .5, .3, .2, .1, .05])
    n3 = d.noise_setting(s3, d._q(s3["points"]))
    assert n3["tier"] == 3 and n3["sigma"] == d.SIGMA_IND and n3["source"].startswith("DEFAULT")


def test_source_precision_allows_a_formal_t6_and_default_does_not():
    ts = [0.08, 0.17, 0.33, 0.5, 1, 2, 3, 4, 6, 8]
    cs = [_biexp(t) for t in ts]
    formal = d.item24_profile(_series(ts, cs, noise=_matched()))
    default = d.item24_profile(_series(ts, cs))
    assert formal["t6_label"] == "EXCLUDED_UNDER_STATED_ASSUMPTIONS"
    assert formal["precision"]["kind"] == "ASSAY_CV" and formal["precision"]["formal_ok"]
    assert default["t6_label"] == "CANNOT_ASSESS" and default["t6_sensitivity_label"] == "EXCLUDED_UNDER_STATED_ASSUMPTIONS"


def test_precision_admission_r8():
    ts = [0.08, 0.17, 0.33, 0.5, 1, 2, 3, 4, 6, 8]
    cs = [_biexp(t) for t in ts]
    # a CV without its match to this analysis: formal CANNOT_ASSESS, the sensitivity reading beside it
    r = d.item24_profile(_series(ts, cs, noise={"assay_cv": 0.03}))
    assert r["t6_label"] == "CANNOT_ASSESS" and r["t6_sensitivity_label"] == "EXCLUDED_UNDER_STATED_ASSUMPTIONS"
    assert r["t6_reason"].startswith("Insufficient evidence: assay precision available, match of the assay CV to this analysis")
    # a validation acceptance limit is not an observed CV
    r = d.item24_profile(_series(ts, cs, noise=_matched(assay_cv_match=dict(CV_MATCH, cv_kind="ACCEPTANCE_LIMIT"))))
    assert r["t6_label"] == "CANNOT_ASSESS" and "acceptance limit" in r["t6_reason"]
    # a CV of another analyte (for example the active moiety formed from a prodrug) is checked separately
    r = d.item24_profile(_series(ts, cs, noise=_matched(assay_cv_match=dict(CV_MATCH, analyte="ACTIVE_MOIETY"))))
    assert r["t6_label"] == "CANNOT_ASSESS"
    # digitized data (finding D7): a matched 1 % CV no longer replaces the reading error; the project default keeps it sensitivity
    dig = _series(ts, cs, noise=_matched(0.01))
    dig["digitized"] = True
    r = d.item24_profile(dig)
    assert r["t6_label"] == "CANNOT_ASSESS"
    assert r["t6_reason"] == "Insufficient evidence: assay precision available, figure-reading range missing"
    comps = [c["component"] for c in r["precision"]["components"]]
    assert comps == ["assay", "figure reading"]
    # a reading range bounded from the figure is combined with the statistical interval and may be formal
    dig["noise_source"] = _matched(0.01, reading_error={"bound_pct": 2.0, "basis": "AXIS_TICKS"})
    r = d.item24_profile(dig)
    assert r["precision"]["formal_ok"] and r["t6_label"] in ("EXCLUDED_UNDER_STATED_ASSUMPTIONS", "NOT_EXCLUDED")
    # replicates need df and the standard error that matches the value
    rep = _series(ts, cs, noise={"replicate_sigma_ln": 0.03})
    r = d.item24_profile(rep)
    assert r["t6_label"] == "CANNOT_ASSESS" and "replicate degrees of freedom" in r["t6_reason"]
    rep["noise_source"] = {"replicate_sigma_ln": 0.03, "replicate_df": 1, "replicate_target": "MEAN_OF_REPLICATES", "replicate_k": 2}
    r = d.item24_profile(rep)
    assert r["precision"]["formal_ok"] and r["precision"]["df"] == 1
    c = next(x for x in r["precision"]["components"] if x["component"] == "replicate scatter")
    assert abs(c["se_target"] - 0.03 / math.sqrt(2)) < 1e-12


def test_window_start_needs_power_and_sparse_late_sampling_is_not_given_the_earliest_time():
    # one apparent decline but a narrow time span: the screen cannot detect R = 1.5, so no candidate start
    ts = [0.08, 0.12, 0.17, 0.2, 0.25]
    r = d.item24_profile(_series(ts, [math.exp(-0.5 * t) for t in ts]))
    assert r["curvature"] == "NONE_DETECTED"
    assert r["post_distribution_from_h"] == "NOT_DETERMINED" and r["post_distribution_reason"] == "LOW_POWER"
    # a well-spread monoexponential keeps the earliest time
    ts2 = [0.25, 1, 2, 4, 8, 12, 24]
    r2 = d.item24_profile(_series(ts2, [math.exp(-0.4 * t) for t in ts2]))
    assert r2["post_distribution_from_h"] == 0.25


def test_prior_dose_without_washout_downgrades_t6_but_not_t7():
    ts = [0.08, 0.17, 0.33, 0.5, 1, 2, 3, 4, 6, 8]
    first = _series(ts, [_biexp(t) for t in ts], sid="D:a1", subject="A1", occasion="1", noise=_matched())
    later = _series(ts, [_biexp(t) for t in ts], sid="D:a2", subject="A1", occasion="2", washout=False, noise=_matched())
    assert d.prior_unwashed(later, [first, later]) and not d.prior_unwashed(first, [first, later])
    r = d.item24_profile(later, None, True)
    assert r["t6_label"] == "CANNOT_ASSESS" and r["t6_sensitivity_label"] == "EXCLUDED_UNDER_STATED_ASSUMPTIONS"
    assert r["t7_label"] == "NOT_EXCLUDED"
    assert r["slowing_alternatives"][0]["status"] == "POSSIBLE"
    later["washout_verified"] = True
    assert not d.prior_unwashed(later, [first, later])


def test_ev_profile_is_description_only_with_vc_over_f_and_iv_window():
    ts = [0.25, 0.5, 1, 1.5, 2, 3, 4, 6, 8, 10]
    ka, k = 0.3, 0.9
    cs = [(math.exp(-ka * t) - math.exp(-k * t)) for t in ts]
    ev = _series(ts, cs, route="EV", subject="A1", occasion="2")
    # M1 (2026-11-24): the shared window record; the rate is the one refitted on the listed samples, not the later-half slope
    iv_r = {"sid": "iv1", "post_distribution_from_h": 2.0, "split": {"b_late": 0.9, "late_times": [2, 4, 8]},
            "iv_window": {"name": "iv_post_distribution_window", "status": "DETERMINED", "start_h": 2.0, "end_h": 8,
                          "sample_ids": ["t=2h", "t=4h", "t=8h"], "rate_per_h": 0.85}}
    r = d.item24_ev(ev, None, iv_r)
    assert r["t6_label"] == "CANNOT_ASSESS" and r["t7_label"] == "CANNOT_ASSESS"
    assert r["separability"] == "ABSORPTION_AND_DISTRIBUTION_NOT_SEPARABLE"
    assert "flip_flop" not in r and "ev_over_iv_late_rate" not in r     # r1.5b: Absorption owns flip-flop
    w = r["iv_reference_window"]
    assert (w["iv_sid"], w["name"], w["from_h"], w["to_h"], w["b_late_iv_per_h"], w["sample_ids"]) == (
        "iv1", "iv_post_distribution_window", 2.0, 8, 0.85, ["t=2h", "t=4h", "t=8h"])
    assert d.item24_ev(ev, None, None)["iv_reference_window"] is None
    assert abs(r["vc_over_f_upper_bound_l_per_kg"] - 1.0 / max(cs)) < 1e-12


def test_apod_ordering_removes_only_formal_results():
    b = {"item24": [{"label": "a", "curvature": "FLATTENING", "phases_visible": "TWO_OR_MORE", "t6_label": "CANNOT_ASSESS",
                     "t6_sensitivity_label": "EXCLUDED_UNDER_STATED_ASSUMPTIONS", "t7_label": "NOT_EXCLUDED"}], "item24_ev": []}
    o = d.apod_ordering(b)
    assert "one-compartment" in o["order"] and not o["removed"]
    b["item24"][0]["t6_label"] = "EXCLUDED_UNDER_STATED_ASSUMPTIONS"
    o = d.apod_ordering(b)
    # 2026-11-24: the removal uses the name of the order, so a formal T6 in every unit removes one-compartment
    assert o["removed"][0]["test"] == "T6" and "one-compartment" not in o["order"]
    assert o["removed_for_all_units"] == ["one-compartment"]


def test_odd_n_split_half_near_threshold_is_borderline():
    ts = [0.1, 0.3, 0.6, 1, 1.5, 2.5, 4]
    sh = d.split_half([{"t": t, "c": c} for t, c in zip(ts, [_biexp(t, a=0.15) for t in ts])], 0.15)
    assert sh["n"] % 2 == 1 and "borderline_shared_point" in sh


def test_leave_one_out_that_leaves_too_few_points_is_not_assessable_not_a_lost_contradiction():
    # three points with a clear T7 contradiction: any removal leaves two points, so the check is unavailable
    ts, lo, hi = [1.0, 2.0, 3.0], [math.log(1.0), math.log(0.9), math.log(0.1)], [math.log(1.0), math.log(0.9), math.log(0.1)]
    loo = d._loo(d.t7_scan, 3, ts, lo, hi)
    assert not loo["robust"] and loo["not_assessable"] == [0, 1, 2] and not loo["lost"]
    # the same for T6 (rule decision R2, 2026-11-24): a rerun on two points is below the three-time minimum
    loo = d._loo(d.t6_margin, 3, ts, [x - 0.01 for x in lo], [x + 0.01 for x in hi], eps=1e-12)
    assert not loo["robust"] and loo["reruns"] == 0 and len(loo["not_assessable"]) == 3
    # five points where dropping the middle witness removes the contradiction: SINGLE_POINT_SUPPORT case
    ts = [1.0, 2.0, 3.0, 4.0, 5.0]
    ys = [math.log(c) for c in (1.0, 0.3, 0.25, 0.1, 0.08)]
    loo = d._loo(d.t7_scan, 5, ts, ys, ys)
    assert not loo["robust"] and loo["lost"] and not loo["not_assessable"]


def test_dis3_is_off_by_default_and_q1_conclusion_names_model_and_limitation():
    assert d.DEFAULT_CONFIG["optional_figures"]["DIS3"] is False
    ts = [0.08, 0.17, 0.33, 0.5, 1, 2, 3, 4, 6, 8]
    iv = [dict(d.item24_profile(_series(ts, [_biexp(t) for t in ts], sid=f"D:c{i}", label=f"c{i}")), label=f"c{i}") for i in range(3)]
    o = d.apod_ordering({"item24": iv, "item24_ev": []})
    c = o["q1_conclusion"]
    assert c["simplest_plausible_model"] == o["order"][0]
    assert c["motivating_observations"] and c["main_limitation"].startswith("no source assay precision")


def test_sensitivity_only_contradiction_moves_only_within_its_group():
    # rule decision R5 (2026-11-24): a sensitivity-only contradiction is marked and keeps the candidate in its group; it moves the
    # candidate only below another candidate of the same group that the same observation supports
    row = {"label": "a", "curvature": "FLATTENING", "phases_visible": "TWO_OR_MORE", "t6_label": "CANNOT_ASSESS",
           "t6_sensitivity_label": "NOT_EXCLUDED", "t7_label": "NOT_EXCLUDED"}
    base = d.apod_ordering({"item24": [dict(row, curvature="NONE_DETECTED", phases_visible="ONE_APPARENT")], "item24_ev": []})
    assert base["order"] == ["one-compartment", "two-compartment"]
    sens = d.apod_ordering({"item24": [dict(row, curvature="NONE_DETECTED", phases_visible="ONE_APPARENT",
                                            t6_sensitivity_label="EXCLUDED_UNDER_STATED_ASSUMPTIONS")], "item24_ev": []})
    # a T6 failure alone does not put two compartments ahead of one
    assert sens["order"] == ["one-compartment", "two-compartment"] and not sens["removed"] and not sens["demoted"]
    one = next(c for c in sens["candidates"] if c["candidate"] == "one-compartment")
    assert one["group"] == "SUPPORTED" and one["sensitivity_contradiction"][0]["level"] == "SENSITIVITY"
    # the contradicting profile supports two compartments, in another group: no move
    flat = dict(row, t6_sensitivity_label="EXCLUDED_UNDER_STATED_ASSUMPTIONS")
    o = d.apod_ordering({"item24": [flat], "item24_ev": []})
    assert o["order"][:3] == ["two-compartment", "one-compartment", "three-compartment"] and not o["demoted"]
    # same group, and the same profile supports the other candidate: the contradicted candidate moves below it
    lone = dict(row, label="b", curvature="NONE_DETECTED", phases_visible="ONE_APPARENT")
    o = d.apod_ordering({"item24": [lone, flat], "item24_ev": []})
    groups = {c["candidate"]: c["group"] for c in o["candidates"]}
    assert groups["one-compartment"] == groups["two-compartment"] == "SUPPORTED"
    assert o["order"][:2] == ["two-compartment", "one-compartment"]
    assert o["demoted"] == [{"candidate": "one-compartment", "below": "two-compartment", "positions": 1, "group": "SUPPORTED",
                             "units": ["a"], "reason": "sensitivity-only contradiction; the same observation supports the candidate above"}]


def test_sensitivity_late_steepening_does_not_lift_the_nonlinear_alternative_into_another_group():
    steep = {"label": "s", "curvature": "STEEPENING", "phases_visible": None, "t6_label": "CANNOT_ASSESS", "t7_label": "CANNOT_ASSESS",
             "t7_flags": ["SENSITIVITY_ONLY"], "t7_sensitivity_label": "EXCLUDED_UNDER_STATED_ASSUMPTIONS"}
    lone = {"label": "o", "curvature": "NONE_DETECTED", "phases_visible": "ONE_APPARENT", "t6_label": "CANNOT_ASSESS", "t7_label": "CANNOT_ASSESS"}
    o = d.apod_ordering({"item24": [lone, steep], "item24_ev": []})
    g = {c["candidate"]: c for c in o["candidates"]}
    assert g["one-compartment"]["group"] == "SUPPORTED" and g[d.NONLINEAR_CANDIDATE]["group"] == "UNTESTED"
    assert g[d.NONLINEAR_CANDIDATE]["untested_state"] == "assessed but undecided" and o["order"][0] == "one-compartment"
    # all UNTESTED: the steepening supports the nonlinear candidate inside the group; the linear ones keep their own order
    o = d.apod_ordering({"item24": [steep], "item24_ev": []})
    assert o["order"] == [d.NONLINEAR_CANDIDATE, "one-compartment", "two-compartment"]
    assert [m["candidate"] for m in o["demoted"]] == ["one-compartment", "two-compartment"]


def test_formal_contradiction_in_some_units_is_contrary_evidence_not_removal():
    # R5: the required units are fixed before the results; one formal exclusion out of two is unit-level contrary evidence
    ok = {"label": "a", "curvature": "NONE_DETECTED", "phases_visible": "ONE_APPARENT", "t6_label": "NOT_EXCLUDED", "t7_label": "NOT_EXCLUDED"}
    bad = {"label": "b", "curvature": "FLATTENING", "phases_visible": "TWO_OR_MORE", "t6_label": "EXCLUDED_UNDER_STATED_ASSUMPTIONS",
           "t7_label": "NOT_EXCLUDED"}
    unk = {"label": "c", "curvature": "NOT_ASSESSABLE", "phases_visible": None, "t6_label": "CANNOT_ASSESS", "t7_label": "CANNOT_ASSESS"}
    o = d.apod_ordering({"item24": [ok, bad, unk], "item24_ev": []})
    one = next(c for c in o["candidates"] if c["candidate"] == "one-compartment")
    assert one["group"] == "CONTRARY_EVIDENCE" and "one-compartment" in o["order"] and o["order"][-1] == "one-compartment"
    c = one["contradictions"][0]
    assert (c["level"], c["required_n"], c["assessable_m"], c["formal_k"], c["directions"]) == ("FORMAL_UNIT", 3, 2, 1, ["slowing"])
    assert not o["board_exclusions"] and o["removed_for_all_units"] == [] and o["required_units"] == ["a", "b", "c"]
    # every required unit formally excluded in the same direction: board-level exclusion
    o = d.apod_ordering({"item24": [bad, dict(bad, label="d")], "item24_ev": []})
    assert o["removed_for_all_units"] == ["one-compartment"] and "one-compartment" not in o["order"]
    assert o["board_exclusions"][0]["required_n"] == 2


def test_bend_count_among_individual_animals():
    mean = {"label": "mean", "analysis_unit": "ARITHMETIC_MEAN_FIXED", "curvature": "FLATTENING", "phases_visible": "TWO_OR_MORE"}
    ind = [{"label": f"a{i}", "analysis_unit": "INDIVIDUAL", "curvature": c, "phases_visible": pv}
           for i, (c, pv) in enumerate([("FLATTENING", "TWO_OR_MORE"), ("NONE_DETECTED", "ONE_APPARENT"), ("FLATTENING", "TWO_OR_MORE_TENTATIVE")])]
    o = d.apod_ordering({"item24": [mean] + ind, "item24_ev": []})
    assert o["bend_count"] == {"shown": 2, "sampled_both_sides": 3}
    assert any("2 of 3 individually sampled animals" in w for w in o["basis"])


def test_modeling_figure_names_never_carry_a_label_slash():
    """Renumbered labels such as 'DIS-1a/1b individual layer' must not turn into a sub-directory in modeling_figures/."""
    import modeling_facts as mf
    for src in mf.FIGURE_SOURCES:
        stem = mf._file_stem(src[2])
        assert "/" not in stem and "\\" not in stem and " " not in stem and stem
    assert mf._file_stem("DIS-1a/1b individual layer") == "DIS-1a_1b_individual_layer"
    assert mf._file_stem("D2 within animals") == "D2_within_animals"
