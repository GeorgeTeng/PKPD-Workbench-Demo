"""Map r4.3 observations to scoped hypotheses without fitting or selecting a model.

Scores are priorities for checking a specific observation. They do not estimate
mechanism probabilities, likelihood ratios, or strength of causal evidence.
"""
from dataclasses import dataclass
import re


EXCLUDED = "EXCLUDED_UNDER_STATED_ASSUMPTIONS"
UNASSESSABLE = "CANNOT_ASSESS"
DEFERRING = {"SENSITIVITY_ONLY", "BORDERLINE", "SINGLE_POINT_SUPPORT", "INDEPENDENT_SUPPORT_NOT_ASSESSABLE"}
ROUTES = {
    "enteral": {"PO"}, "depot": {"SC", "IM"}, "portal": {"PO", "IP"}, "ip": {"IP"},
    "pulmonary": {"INTRATRACHEAL", "INHALED_NOSE_ONLY", "INHALED_WHOLE_BODY"},
}
UNKNOWN_ROUTES = {"", "NOT_FOUND", "UNKNOWN", "ROUTE_UNKNOWN", "OTHER_EV", "IT"}
PRIORITY = ["No case-specific clue", "Context or data check", "Descriptive follow-up", "Direct contrast to review"]
COMMON_PREMISES = ("Single dose or supported washout, zero initial amounts, time measured from that dose, "
                   "central input and observation, linear time-invariant one-compartment or reversible mammillary disposition.")
TEST_PREMISES = {
    "T1": "Systemic input is nonnegative and non-increasing from dosing. " + COMMON_PREMISES,
    "T2": "One globally log-concave systemic input on connected support, including any common lag. "
          "Observations belong to a verified serial animal. " + COMMON_PREMISES,
}
FOLLOW_UP = {
    "onset": "Earlier quantified draws, LLOQ, predose and documented administration times.",
    "shape": "Dense rising and peak samples with comparable IV disposition or independent release data.",
    "multiphase": "Verified serial observations on both sides of the trough, dose history and a comparable IV profile.",
    "tail": "Overlapping EV/IV terminal windows, adequate late samples and an independent disposition reference.",
    "dose": "Comparable total exposure, replicated dose groups, peak sampling and IV disposition across the relevant exposure range.",
    "extent": "Comparable parent EV/IV total exposures, dose basis and shared linear clearance.",
    "condition": "Well-matched actual sample times and exposure coverage, with the changed condition isolated.",
    "baseline": "Predose assay records, dosing/period history and evidence on residual amounts.",
}


def f(x):
    return "unavailable" if x is None else f"{x:.4g}" if isinstance(x, (float, int)) else str(x)


def window(d):
    return f"{f(d.get('start_h'))}–{f(d.get('end_h'))} h"


def route_scope(card, required):
    route = str(card.get("route_detail") or "").upper()
    if required == "any":
        return "APPLICABLE"
    if route in UNKNOWN_ROUTES or required not in ROUTES:
        return "ROUTE_SCOPE_UNRESOLVED"
    return "APPLICABLE" if route in ROUTES[required] else "OUTSIDE_ROUTE_SCOPE"


@dataclass
class Cue:
    candidates: tuple
    question: int
    sources: tuple
    kind: str
    score: int
    text: str
    series_id: str = ""


def curve_cues(card, series):
    cid = card["dataset_id"]
    m = series.get("metrics", {})
    source = f"{cid} ({series.get('label') or series.get('series_id')})"
    def cue(keys, n, kind, score, detail):
        return Cue(tuple(keys.split()), n, (cid,), kind, score, source + ": " + detail, series.get("series_id", ""))
    baseline = m.get("baseline_status", card.get("baseline_status"))
    if baseline in {"ENDOGENOUS", "MIXED", "UNEXPLAINED", "RESIDUAL_FROM_PRIOR_DOSE"} or m.get("baseline_size") == "RESIDUAL_BASELINE":
        yield cue("baseline_carryover", 1, "BASELINE_OBSERVATION", 2,
                  f"Baseline {baseline}; recorded predose {f(m.get('predose_value'))} {card.get('unit', '')} "
                  f"at {f(m.get('predose_time_h'))} h. Review the recorded origin, assay specificity and full dosing history.")
    elif baseline in {"NOT_ASSESSABLE", "WASHOUT_ZERO", "DESIGN_ZERO"} and card.get("matrix_category") == "PLASMA_SERUM_BLOOD":
        yield cue("baseline_carryover", 1, "BASELINE_CHECK", 1,
                  f"Baseline {baseline}; zero initial amounts {'supported' if m.get('zero_state_supported') else 'unverified'}. "
                  "A missing predose alone gives no positive evidence of carryover.")
    if not card.get("tests_allowed") or not m.get("n_quantified"):
        return
    caveats = set(m.get("caveats", ()))
    issues = sorted(caveats & {"TIME_ORIGIN_UNCLEAR", "SERIAL_IDENTITY_NOT_VERIFIED", "CONFLICTING_DUPLICATE",
                               "CMAX_ABOVE_ULOQ", "LATE_FIRST_SAMPLE", "INTERIOR_BLQ"})
    if issues:
        yield cue("timing_sampling", 2, "SAMPLING_AUDIT", 2,
                  f"First quantified {f(m.get('first_t'))} h, sampled peak {f(m.get('tmax'))} h. "
                  + ", ".join(issues) + ".")
    first = next((p for p in m.get("t1_points", []) if p.get("status") == "QUANTIFIED"
                  and p.get("t") == m.get("first_t") and (p.get("c") or 0) > 0), None)
    if (first and (first.get("lo") or 0) > 0 and first.get("t_lo") is not None
            and first.get("t_hi") is not None and 0 <= first["t_lo"] <= first["t"] <= first["t_hi"]
            and first["t_hi"] > 0):
        # A positive signal can rule out only lags extending beyond this draw, and only
        # if its timing and attribution to this dose are correct. Pixel-time bounds matter.
        upper = first["t_hi"]
        yield cue("first_order_lag zero_order_lag weibull_lt1_lag weibull_eq1_lag weibull_gt1_lag transit_lag",
                  1, "CONDITIONAL_LIMIT_ON_FIXED_LAG", 1,
                  f"{first.get('record_id')}: {f(first['c'])} {card.get('unit', '')} at {f(first['t'])} h "
                  f"(latest recorded time bound {f(upper)} h). If the stated bounds hold, time is relative to the correct dose, the signal "
                  f"comes from that dose, and residual/carryover is absent, a common fixed lag of {f(upper)} h "
                  "or longer is disfavored. Shorter lags remain open. Baseline " + str(baseline) + ".")
    if card.get("known_finite_administration"):
        yield cue("finite_administration", 1, "RECORDED_ADMINISTRATION_PERIOD", 2,
                  "Source records finite administration. Separate delivery duration from release at the site and systemic absorption.")
    if card.get("record_level") == "INDIVIDUAL_IDENTITY_UNVERIFIED":
        return
    if m.get("onset_status") == "DELAYED_ONSET":
        yield cue("first_order_lag zero_order_lag weibull_lt1_lag weibull_eq1_lag weibull_gt1_lag "
                  "weibull_gt1_immediate transit transit_lag", 1, "DELAYED_ONSET", 2,
                  f"First quantified {f(m.get('first_t'))} h. {m.get('onset_reason', '')}. "
                  "A fixed lag and gradual onset both remain possible.")
    shape = m.get("rise_shape")
    shape_keys = {"FIRST_ORDER_LIKE": "first_order zero_order weibull_eq1_immediate",
                  "ZERO_ORDER_LIKE": "first_order zero_order weibull_eq1_immediate",
                  "SIGMOIDAL_DELAYED": "weibull_gt1_immediate transit",
                  "MULTIPHASE": "separated_inputs burst_sustained"}
    if shape in shape_keys:
        descriptions = {"FIRST_ORDER_LIKE": "slowing rise with a rounded peak",
                        "ZERO_ORDER_LIKE": "sustained rise with an observed slope change near the peak",
                        "SIGMOIDAL_DELAYED": "slow–fast–slow concentration rise",
                        "MULTIPHASE": "multiphase rise or more than one sampled maximum"}
        yield cue(shape_keys[shape], 2, "SAMPLED_RISE", 2,
                  f"Observed {descriptions[shape]}, with {m.get('n_before_peak')} quantified pre-peak samples. "
                  + ("Compare finite zero-order and first-order inputs with matched lag, disposition and errors. "
                     if shape in {"FIRST_ORDER_LIKE", "ZERO_ORDER_LIKE"} else "") +
                  "This describes the measured plasma signal. The input family remains unresolved.")
    t2 = series.get("t2") or {}
    if t2.get("positive_count", 0):
        w = t2.get("best") or {}
        unit = t2.get("analysis_unit", card.get("record_level"))
        within = bool(t2.get("test_executed")) and unit == "INDIVIDUAL"
        yield cue("separated_inputs burst_sustained" + (" enterohepatic" if within else ""), 4,
                  "WITHIN_ANIMAL_TROUGH" if within else "GROUP_TROUGH_DESCRIPTION", 2 if within else 1,
                  f"{unit}: {t2['positive_count']} overlapping positive ordered triples. Strongest at "
                  f"{w.get('times_h')} h, margin {f(w.get('margin'))} {card.get('unit', '')}; records {w.get('record_ids')}. "
                  + ("A re-rise does not establish its cause." if within else "Group averages alone cannot establish a within-animal re-rise."))
    split = m.get("split") or {}
    if split.get("class") == "DECLINE_STEEPENS":
        yield cue("burst_sustained ongoing_input", 6, "DECLINE_STEEPENS", 1,
                  f"Post-peak slope class DECLINE_STEEPENS (ratio {f(split.get('ratio'))}). "
                  "Ordinary absorption can also give this pattern.")
    if card.get("route_detail") in ROUTES["pulmonary"]:
        yield cue("pulmonary_enteral", 2, "ROUTE_CONTEXT", 1,
                  f"Route recorded as {card['route_detail']}; separate pulmonary and swallowed contributions require independent evidence.")


def dose_cues(d):
    ids = tuple(d["dataset_ids"])
    peak = d.get("cmax_d_ratio")
    auc = d.get("R_window")
    w = d.get("observed_window") or {}
    if auc is None:
        return
    summary = (f"{', '.join(ids)}: high/low Cmax/dose {f(peak)}, AUC/dose {f(auc)} on {window(w)}. "
               f"T3 {d.get('t3_label', UNASSESSABLE)}. ")
    def cue(keys, kind, score, detail):
        return Cue(tuple(keys.split()), 8, ids, kind, score, summary + detail)
    if peak is not None and peak < .8 and peak < auc and d.get("cmax_label") == "POINTS_TO_NONLINEARITY":
        yield cue("input_rate_limited", "PEAK_FALLS_MORE_THAN_WINDOW_EXPOSURE", 3,
                  "Check whether higher-dose input is slower or prolonged. Peak sampling, later exposure and matched IV clearance are needed.")
        yield cue("depot_release solubility_limited parallel_linear_saturable_input", "INPUT_MECHANISM_CHECK", 1,
                  "The contrast motivates checking formulation or administration-site evidence; it does not locate an input bottleneck.")
    if d.get("e6_label") == "POINTS_TO_NONLINEARITY":
        if auc < 1:
            yield cue("uptake_extent_loss changing_clearance", "FALLING_WINDOW_EXPOSURE", 2,
                      "Test whether the change persists in complete exposure and compare IV clearance before assigning it to a loss of F.")
        if auc > 1:
            yield cue("efflux_saturation first_pass_saturation nonlinear_elimination", "RISING_WINDOW_EXPOSURE", 2,
                      "Compare complete exposure and IV across doses. Transport, first pass and elimination require independent evidence.")
    if d.get("e2_label") == "POINTS_TO_NONLINEARITY":
        halves = [f"{f(z.get('dose'))} mg/kg: {f(z.get('thalf'))} h" for z in d.get("rows", [])]
        yield cue("nonlinear_elimination parallel_linear_saturable_elimination", "DOSE_DEPENDENT_TERMINAL_SHAPE", 2,
                  "Apparent half-life by dose (" + ", ".join(halves) + "). Compare window sensitivity, input and IV across doses; pending elimination.")
    if d.get("t3_label") == EXCLUDED or (d.get("t3p") or {}).get("t3p_label") == EXCLUDED:
        yield cue("input_rate_limited uptake_extent_loss changing_clearance", "NON_SUPERPOSITION", 1,
                  "The comparison challenges the combined linear dose-independent input and disposition model. It does not locate the change.")


def reference_cues(r):
    ids = (r["ev"], r["iv"])
    terminal = r.get("terminal_comparison") or {}
    grade = terminal.get("comparison_status")
    matched = [p for p in terminal.get("pairs", []) if p.get("same_window")]
    slower = [p for p in matched if str(p.get("grade", "")).startswith("EV_SHALLOWER")]
    label = " / ".join(ids)
    if slower:
        p = slower[0]
        yield Cue(("flip_flop","ongoing_input"), 6, ids, "MATCHED_TERMINAL_WINDOW", 2,
                  f"{label}: apparent EV/IV t½ ratio {f(p['ratio'])} on matched {p['ev_window_h']} h. "
                  f"{len(slower)} of {len(matched)} comparable windows show a shallower EV slope. "
                  "Interpret with dose comparability and independent disposition evidence.")
    elif grade == "DIFFERENT_WINDOWS" and terminal.get("pairs"):
        # Unequal selected windows motivate reconciling the slopes. They cannot establish a slow input.
        yield Cue(("timing_sampling",), 6, ids, "DIFFERENT_TERMINAL_WINDOWS", 2,
                  f"{label}: {r.get('trigger_text') or 'EV and IV apparent terminal estimates available'}. "
                  "Qualified EV and IV windows differ; the contribution of absorption remains unresolved.")
        directional = next((p for p in terminal["pairs"] if str(p.get("grade", "")).startswith("EV_SHALLOWER")), None)
        if directional:
            yield Cue(("flip_flop", "ongoing_input"), 6, ids, "UNMATCHED_TERMINAL_DIRECTION", 1,
                      f"{label}: apparent EV/IV half-life ratio {f(directional['ratio'])} comparing EV "
                      f"{directional['ev_window_h']} h with IV {directional['iv_window_h']} h. The longer EV "
                      "half-life makes slow input worth checking. The windows differ, so flip-flop remains unresolved. "
                      "Re-estimate the slopes over matched windows with adequate sampling.")
    t4 = r.get("t4") or {}
    if t4.get("conditional_direction") == "CONTRADICTION":
        yield Cue(("multicompartment",), 6, ids, "EV_IV_RATIO_DECLINE", 2 if t4.get("formal_status") == EXCLUDED else 1,
                  f"{label}: T4 {t4.get('formal_status')}, exact-pair ratio margin {f(t4.get('margin'))}, "
                  f"witness rows {t4.get('witness')}. Check IV mode and the shared one-compartment premise. "
                  "A falling EV/IV ratio alone does not establish multiple compartments or flip-flop.")
    if r.get("f_window") is not None:
        yield Cue(("f_change",), 7, ids, "OBSERVED_EXPOSURE_RATIO", 1,
                  f"{label}: dose-normalized EV/IV exposure ratio {f(r['f_window'])} on {window(r.get('observed_window') or {})}. "
                  f"{r.get('f_status')}; absolute F {r.get('absolute_f_status', 'NOT_ESTIMABLE')}. This ratio alone cannot establish a change in F.")


def condition_cues(r):
    ids = (r["a"], r["b"])
    exact = r.get("exact_pairs", 0)
    readings = r.get("intervals") or []
    t = r.get("t5") or {}
    label = r.get("t5_label", UNASSESSABLE)
    desc = (f"{r['a']} / {r['b']} (raw concentrations): {exact} exact and {len(readings)-exact} near-time pairs, "
            f"T5 {label}. Recorded differences: {', '.join(r.get('differing_attributes', [])) or 'not established'}. "
            f"Timing-sensitivity highest lower/lowest upper bounds {f(r.get('c_lower'))}/{f(r.get('c_upper'))}. ")
    if label == EXCLUDED or r.get("rate_only_evidence"):
        yield Cue(("rate_only",), 9, ids, "RATE_ONLY_CONTRAST", 3 if r.get("rate_only_evidence") else 1,
                  desc + f"Separate rate-only test {r.get('rate_only_label', UNASSESSABLE)}. {r.get('rate_only_reason', '')}")
    if not readings and not t.get("witness"):
        return
    if len(readings) > exact:
        yield Cue(("timing_sampling",), 9, ids, "TIME_ALIGNMENT", 3, desc + "Check actual times and time-mismatch bounds.")
    if label == EXCLUDED or (r.get("timing_sensitivity") or {}).get("conditional_direction") == "CONTRADICTION":
        yield Cue(("mixed_rate_extent",), 9, ids, "CONDITION_SHAPE_CONTRAST", 2 if label == EXCLUDED else 1,
                  desc + "Inspect the condition-specific shape; separate rate, extent and disposition need independent data.")
    if exact >= 2:
        yield Cue(("cl_v_coscaling","f_change"), 9, ids, "AMPLITUDE_CONTRAST", 1,
                  desc + "T5 addresses a common scale. F and coordinated CL/V changes can share the same prediction under the stated linear model.")
    if "occasion" in r.get("differing_attributes", []):
        yield Cue(("occasion_effect",), 9, ids, "OCCASION_CONTRAST", 1,
                  desc + "Reconstruct each dosing history and assess accumulation before attributing a difference to occasion.")


def contrast(test, ids, state, scope, flags, evidence, missing=()):
    return {"test": test, "dataset_ids": list(ids), "formal_status": state or UNASSESSABLE,
            "scope": scope, "flags": list(flags or ()), "evidence": evidence, "missing": list(missing)}


def study_contrasts(doses, refs, conditions, parameters):
    contrasts = {}
    def add(keys, record):
        for key in keys.split():
            contrasts.setdefault(key, []).append(record)
    for d in [*doses, *parameters]:
        if "params" in d:
            t = (d.get("analysis") or {}).get("t3")
            if not t:
                continue
            ids, p = [d["card"]["dataset_id"]], {}
        else:
            t, ids, p = d, d["dataset_ids"], d.get("t3p") or {}
        scope = "Proportional systemic input and common linear disposition on the stated dose and occasion contrast."
        add("dose_proportional", contrast("T3", ids, t.get("t3_label"), scope, t.get("t3_flags"),
            {"low_high_doses_mg_kg": t.get("dose_pair") or t.get("t3_primary_pair"), "ratio": t.get("R", t.get("R_window")),
             "ci": t.get("ci"), "window_h": [t.get("window_start_h"), t.get("window_end_h")],
             "analysis_unit": t.get("t3_data_level")}, [t["t3_reason"]] if t.get("t3_label") == UNASSESSABLE and t.get("t3_reason") else []))
        if p:
            add("dose_proportional", contrast("T3p", ids, p.get("t3p_label"), scope, p.get("t3p_flags"),
                {"times_h": p.get("t3p_times"), "log_ratio_ci": p.get("t3p_ln_ratio_ci"), "holm_p": p.get("t3p_p_holm"),
                 "low_high_doses_mg_kg":p.get("t3p_dose_pair")}, [p["reason"]] if p.get("reason") else []))
    for r in refs:
        t = r.get("t4") or {}
        ids = [r["ev"], r["iv"]]
        add("shared_one_compartment", contrast("T4", ids, t.get("formal_status", r.get("t4_label")),
            "Shared linear one-compartment disposition with a common elimination rate, nonnegative EV input, matched central observations and justified IV input.",
            t.get("flags", r.get("t4_flags")), {"exact_pair_margin": t.get("margin"), "witness": t.get("witness"),
            "terminal_interpretation": (r.get("terminal_comparison") or {}).get("flip_flop_reading", "UNRESOLVED")}, t.get("missing_premises", [])))
    for r in conditions:
        ids = [r["a"], r["b"]]
        t = r.get("t5") or {}
        add("f_change cl_v_coscaling", contrast("T5", ids, t.get("formal_status", r.get("t5_label")),
            "One constant positive multiplier at all matched times, under otherwise shared input shape and disposition. A broader change in F or disposition is outside this statement.",
            t.get("flags", []), {"exact_pairs": r.get("exact_pairs"), "margin": t.get("margin"), "witness": t.get("witness"),
            "raw_constraints": {k:v for k,v in (r.get("raw_interval_constraints") or {}).items() if k in ("lower","upper","empty_intersection")}},
            t.get("missing_premises", [])))
        add("rate_only", contrast("RATE_ONLY", ids, r.get("rate_only_label"),
            "Only input rate differs; shared time-invariant linear disposition, common systemic site and equal complete dose-normalized exposure.",
            [], r.get("rate_only_evidence") or {}, [r["rate_only_reason"]] if r.get("rate_only_reason") and r.get("rate_only_label") == UNASSESSABLE else []))
    return contrasts


def formal_test(code, data):
    witness = data.get("best") or {}
    return {"test": code, "formal_status": data.get("formal_status", UNASSESSABLE),
            "executed": data.get("test_executed") is True, "premises": TEST_PREMISES[code],
            "basis": data.get("basis"), "analysis_unit": data.get("analysis_unit"), "flags": data.get("flags", []),
            "missing": data.get("missing_premises", []), "eligible_count": data.get("eligible_count", 0),
            "window_h": data.get("window_h"), "positive_count": data.get("positive_count", 0),
            "margin": witness.get("margin"), "witness_times_h": witness.get("times_h", []),
            "witness_records": witness.get("record_ids", []), "widened_margin":
            ((data.get("widening") or {}).get("best") or {}).get("margin")}


def firm(record):
    return not set(record.get("flags", [])) & DEFERRING and not record.get("missing")


def profile_candidate(candidate, card, series, is_param):
    route = route_scope(card, candidate.get("route", "any"))
    m = series.get("metrics") or {}
    tests = []
    limitations = []
    if route != "APPLICABLE":
        state = route
        limitations.append(f"Recorded route {card.get('route_detail') or 'unknown'}; candidate requires {candidate['route']}.")
    elif is_param:
        state = "REPORTED_PARAMETER_ONLY"
        limitations.append("Source-reported parameters have no within-profile time series for T1/T2.")
    elif not card.get("tests_allowed"):
        state = "GATED_PROFILE"
        limitations.extend(card.get("gates") or ["Central EV data gate unavailable."])
    elif not m.get("n_quantified"):
        state = "NO_QUANTIFIED_PROFILE"
        limitations.append(m.get("not_assessable_reason") or "No quantified postdose measurements.")
    else:
        for code, test in (("T1", m.get("t1")), ("T2", series.get("t2"))):
            if candidate.get(code.lower()):
                row = formal_test(code, test or {})
                row["margin_unit"] = str(card.get("unit") or "concentration") + ("/h" if code == "T1" else "")
                tests.append(row)
        for t in tests:
            limitations.extend(t["missing"])
        if any(t["formal_status"] == EXCLUDED and t["executed"] and firm(t) for t in tests):
            state = EXCLUDED
        elif any(t["formal_status"] == "NOT_EXCLUDED" and t["executed"] and firm(t) for t in tests):
            state = "NOT_EXCLUDED"
        elif tests:
            state = UNASSESSABLE
        else:
            state = "NO_APPLICABLE_SHAPE_TEST"
        if card.get("record_level") == "INDIVIDUAL_IDENTITY_UNVERIFIED":
            limitations.append("Source-labelled samples lack verified serial identity.")
    return {"dataset_id": card["dataset_id"], "series_id": series.get("series_id"),
            "series_label": series.get("label"), "record_level": card.get("record_level"),
            "route_detail": card.get("route_detail"), "route_scope": route, "formal_status": state,
            "tests": tests, "limitations": list(dict.fromkeys(limitations))}


def question_records(board, result):
    pages = (result.get("presentation") or {}).get("questions", [])
    slug = lambda v: re.sub(r"[^a-z0-9]+", "-", str(v).lower()).strip("-")
    page = next((p["page"] for p in pages if p.get("study") == board["study"]),
                f"species-{slug(board.get('species_group', board.get('species')))}.html")
    records = []
    for q in board["questions"]:
        n = q["q"]
        p = q.get("primary") or {}
        # Keep case-level caveats in the conclusion. Links point to the board's full provenance.
        rows = []
        for part in q.get("evidence", []):
            for tab in part.get("tables", []):
                if tab.get("caption") == "Status of every condition or source value":
                    rows.extend({"condition": row[0], "status": row[1], "text": row[2]}
                                for row in tab["rows"] if len(row) >= 3)
        records.append({"q": n, "label": q["label"], "question": q["question"], "status_code": q["status_code"],
                        "conclusion": q.get("text", q.get("observed", "")), "evidence": rows,
                        "dataset_ids": q.get("dataset_ids", []), "missing": q.get("missing", []),
                        "link": f"{page}#q-{slug(board['study'])}-{n}", "primary_file": p.get("file")})
    return records


def evaluate(candidate, profiles, cues, contrasts):
    key = candidate["id"]
    scoped = [profile_candidate(candidate, c, s, is_param) for c,s,is_param in profiles]
    by_id = {p["dataset_id"]: p for p in scoped}
    accepted = []
    for cue in cues:
        if key not in cue.candidates:
            continue
        ev_scope = [by_id[i] for i in cue.sources if i in by_id]
        if not ev_scope or any(p["route_scope"] != "APPLICABLE" for p in ev_scope):
            continue
        accepted.append({"kind": cue.kind, "dataset_ids": list(cue.sources), "series_id": cue.series_id or None,
                         "text": cue.text, "question": cue.question, "score": cue.score})
    checks = [z for z in contrasts.get(key, []) if all(by_id[i]["route_scope"] == "APPLICABLE" for i in z["dataset_ids"] if i in by_id)]
    for z in checks:
        score = 3 if z["formal_status"] in (EXCLUDED, "NOT_EXCLUDED") and firm(z) else 1 if any(
                    z["evidence"].get(k) is not None for k in ("ratio", "margin", "exact_pair_margin")) else 0
        n = {"T3":8, "T3p":8, "T4":6, "T5":9, "RATE_ONLY":9}[z["test"]]
        fields = [f"{k.replace('_', ' ')} {f(z['evidence'][k])}" for k in ("ratio","ci","exact_pairs","exact_pair_margin","margin")
                  if z["evidence"].get(k) is not None]
        accepted.append({"kind": z["test"], "dataset_ids": z["dataset_ids"], "series_id": None, "question": n, "score": score,
                         "text": f"{' / '.join(z['dataset_ids'])}: {z['test']} {z['formal_status']}. " +
                                 (", ".join(fields) + ". " if fields else "") + z["scope"]})
    for p in scoped:
        for t in p["tests"]:
            if t["margin"] is None:
                continue
            degree = 3 if t["formal_status"] in (EXCLUDED, "NOT_EXCLUDED") and t["executed"] and firm(t) else 1 if t["positive_count"] else 0
            detail = (f"{p['dataset_id']} ({p['series_label']}): {t['test']} {t['formal_status']}. "
                      f"{t['positive_count']}/{t['eligible_count']} positive, maximum margin {f(t['margin'])} {t['margin_unit']}, "
                      f"times {t['witness_times_h']} h, records {t['witness_records']}.")
            if t["test"] == "T2" and not t["executed"]:
                detail += " Series-level description only; within-animal T2 unavailable."
            if t["flags"]:
                detail += " " + ", ".join(t["flags"]) + "."
            accepted.append({"kind": t["test"], "dataset_ids": [p["dataset_id"]], "series_id": p["series_id"],
                             "text": detail, "question": 3 if t["test"] == "T1" else 4, "score": degree})
    applicable = [p for p in scoped if p["route_scope"] == "APPLICABLE"]
    excluded = [p for p in applicable if p["formal_status"] == EXCLUDED]
    ex_checks = [z for z in checks if z["formal_status"] == EXCLUDED and firm(z)]
    if ex_checks:
        state = "EXCLUDED_IN_SPECIFIED_COMPARISONS"
        rationale = " ".join(f"{z['test']} for {' / '.join(z['dataset_ids'])}: {z['scope']}" for z in ex_checks)
    elif excluded:
        state = "EXCLUDED_IN_SPECIFIED_PROFILES"
        rationale = "Formal exclusion is confined to " + ", ".join(f"{p['dataset_id']} ({p['series_label']})" for p in excluded) + " under the attached complete model premises."
    elif not applicable:
        state = "ROUTE_SCOPE_UNRESOLVED" if any(p["route_scope"] == "ROUTE_SCOPE_UNRESOLVED" for p in scoped) else "OUTSIDE_ROUTE_SCOPE"
        rationale = ("Route-specific assessment is withheld. The source route is unspecified or ambiguous." if state == "ROUTE_SCOPE_UNRESOLVED"
                     else "The candidate requires a different route from the eligible study records.")
    elif all(p["formal_status"] in {"GATED_PROFILE","NO_QUANTIFIED_PROFILE","REPORTED_PARAMETER_ONLY"} for p in applicable) and not accepted:
        state = "INSUFFICIENT_DATA"
        rationale = "The available profiles lack eligible timed observations for this candidate."
    else:
        state = "OPEN"
        rationale = "The study leaves this candidate open. Additional observations are needed to distinguish it."
    score = max((row["score"] for row in accepted), default=0)
    if accepted and state == "OPEN":
        strong = max(accepted, key=lambda e:e["score"])
        rationale = (strong["text"] if strong["score"] else "No candidate-specific positive finding. " + strong["text"])
    if not accepted and state == "OPEN":
        rationale = "No candidate-specific pattern or independent evidence was recorded. Plausibility remains unresolved."
    conditional_limits = [e for e in accepted if e["kind"] == "CONDITIONAL_LIMIT_ON_FIXED_LAG"]
    if conditional_limits and state == "OPEN" and not any(e["text"] in rationale for e in conditional_limits):
        rationale += " " + conditional_limits[0]["text"]
    if state.startswith("EXCLUDED_IN_"):
        balance = "Formal evidence against the explicitly scoped combination"
    elif conditional_limits:
        balance = "Conditional evidence against lags extending beyond the first quantification; shorter lags open"
    elif not applicable or state == "INSUFFICIENT_DATA":
        balance = "Outside the available evidence scope"
    elif score >= 2:
        balance = "Observed feature warrants a check; the cause is unresolved"
    else:
        balance = "No discriminating positive evidence for the mechanism"
    return {"id": key, "label": candidate["label"], "family": candidate["family"], "questions": list(candidate["questions"]),
            "route": candidate.get("route", "any"), "status": state, "priority": PRIORITY[score], "score": score,
            "rationale": rationale, "evidence_balance": balance, "evidence": accepted,
            "dataset_ids": sorted({i for e in accepted for i in e["dataset_ids"]}),
            "profile_assessments": scoped, "contrast_assessments": checks,
            "next_evidence": candidate.get("next_check") or FOLLOW_UP.get(candidate["family"], "Independent specified evidence for this mechanism.")}


def assess(result, catalog):
    """Return one unranked catalogue assessment per study in board order."""
    candidates = catalog["candidates"] if isinstance(catalog, dict) else catalog
    out = []
    for b in result["status_boards"]:
        ids = set(b["datasets"])
        ds = [d for d in result.get("datasets", []) if d["card"]["dataset_id"] in ids]
        ps = [d for d in result.get("reported_parameters", []) if d["card"]["dataset_id"] in ids]
        profiles = [(d["card"], s, False) for d in ds for s in d["series"]]
        profiles.extend((d["card"], {}, True) for d in ps)
        doses = [r for r in result.get("dose_series", []) if set(r["dataset_ids"]) <= ids]
        refs = [r for r in result.get("ev_iv", []) if r["ev"] in ids]
        conditions = [r for r in result.get("conditions", []) if {r["a"], r["b"]} <= ids]
        cues = [cue for d in ds for s in d["series"] for cue in curve_cues(d["card"], s)]
        for records, fn in ((doses, dose_cues), (refs, reference_cues), (conditions, condition_cues)):
            cues.extend(cue for r in records for cue in fn(r))
        for p in ps:
            cid = p["card"]["dataset_id"]
            for v in p["params"]:
                if v["param"] == "F":
                    cues.append(Cue(("f_change",), 7, (cid,), "SOURCE_REPORTED_F", 1,
                                    f"{cid}, {v.get('record_id')}: source-reported F {f(v['value'])} {v.get('unit') or ''}. "
                                    "The value gives source context; a change in availability requires a compatible comparison."))
        contrasts = study_contrasts(doses, refs, conditions, ps)
        out.append({"study_id": b["study"], "species": b["species"], "species_group": b.get("species_group", b["species"]),
                    "dataset_ids": sorted(ids), "questions": question_records(b, result),
                    "candidate_assessments": [evaluate(c, profiles, cues, contrasts) for c in candidates]})
    return out


