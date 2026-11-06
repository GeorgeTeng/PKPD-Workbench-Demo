"""Short modeling checks selected from the study's own r4.3 observations."""
from .eda_absorption_assessment import EXCLUDED, firm
from .eda_absorption_reader_evidence import Profile, group_provenance, number, route_name, time, time_window


def item(title, observation, check, *candidates):
    return {"title": title, "observation": observation, "check": check, "candidate_ids": list(candidates)}


def exclusions(rows):
    sources, candidates = [], []
    for row in rows:
        if row.get("status") not in {"EXCLUDED_IN_SPECIFIED_PROFILES", "EXCLUDED_IN_SPECIFIED_COMPARISONS"}:
            continue
        candidates.append(row["id"])
        for p in row.get("profile_assessments", []):
            if p.get("formal_status") != EXCLUDED:
                continue
            for t in p.get("tests", []):
                if t.get("formal_status") == EXCLUDED and t.get("executed") and firm(t):
                    who = p["dataset_id"] + (f" ({p['series_label']})" if p.get("series_label") else "")
                    what = {"T1": "concentration per hour since dosing increased",
                            "T2": "a verified animal showed a trough followed by a rise"}.get(t["test"], "the predicted shape failed")
                    sources.append(f"{who}: {what}")
        for z in row.get("contrast_assessments", []):
            if z.get("formal_status") != EXCLUDED or not firm(z):
                continue
            what = {"T3": "dose-normalized exposures differed", "T3p": "dose-normalized concentrations differed",
                    "T4": "the extravascular-to-IV ratio declined", "T5": "a single concentration multiplier failed",
                    "RATE_ONLY": "complete dose-normalized exposures differed"}.get(z["test"], "the tested prediction failed")
            sources.append(f"{' versus '.join(z['dataset_ids'])}: {what}")
    if not candidates:
        return None
    unique = list(dict.fromkeys(sources))
    observation = ". ".join(unique[:2]) + "." if unique else "The assessment excludes specific model combinations under its stated assumptions."
    if len(unique) > 2:
        observation += f" The linked assessments cover {len(unique)} scoped findings."
    return item("Keep exclusions tied to their observed scope", observation,
                "Apply each exclusion only to the named profile or comparison and its documented input, disposition and sampling assumptions.",
                *dict.fromkeys(candidates))


def identity_check(profiles):
    by_label = [p for p in profiles if p.card.get("record_level") == "INDIVIDUAL_IDENTITY_UNVERIFIED"]
    if not by_label:
        return None
    p = by_label[0]
    same = [z for z in by_label if z.cid == p.cid and z.arm == p.arm]
    peaks = [z.m["tmax"] for z in same if z.m.get("tmax") is not None and z.m.get("cmax_status") != "LOWER_BOUND_ONLY"]
    prefix = f"{p.cid}, {p.arm}: {len(same)} source-labelled series."
    if peaks and len(peaks) == len(same):
        when = time(peaks[0]) if min(peaks) == max(peaks) else time_window(min(peaks), max(peaks))
        prefix += f" Their highest sampled concentrations occurred at {when}."
    return item("Verify which observations belong to the same animal",
                prefix + " Cross-time animal identity is unverified.",
                "Reconcile animal identifiers, dosing times and draw times. Use within-time observations until serial linkage supports individual trajectories or variation in lag.",
                "timing_sampling", "variable_lag", "first_order_lag")


def dose_checks(doses, profiles, overview=False):
    by_id = {(p.cid,p.series.get("series_id")): p for p in profiles}
    for d in doses:
        rows = sorted([r for r in d.get("rows", []) if r.get("dose") is not None], key=lambda r:r["dose"])
        dp = d.get("dose_pair") or d.get("t3_primary_pair") or d.get("doses") or []
        peak, exposure = d.get("cmax_d_ratio"), d.get("R_window")
        w = d.get("observed_window") or {}
        if len(dp) < 2 or w.get("start_h") is None or w.get("end_h") is None or exposure is None:
            continue
        low, high = min(dp), max(dp)
        named = {(r["dataset_id"], r["series_id"]) for r in rows if r.get("dataset_id") and r.get("series_id")}
        selected = [p for p in profiles if p.cid in d.get("dataset_ids", []) and
                    (not named or (p.cid, p.series.get("series_id")) in named)]
        if not selected or {p.cid for p in selected} != set(d["dataset_ids"]):
            continue
        unit = group_provenance(selected)
        tw = time_window(w["start_h"], w["end_h"])
        occasion = str(d.get("occasion") or "").replace("_", " ").strip().lower()
        later = occasion and occasion not in {"single dose","unknown","not found","not reported"}
        period = f" on {occasion}" if later else ""
        if overview:
            yield item("Check dose-normalized exposure on the same occasion",
                       f"At {number(high)} versus {number(low)} mg/kg{period}, exposure per dose from the {unit} had a high/low ratio of {exposure:.3g} over {tw}.",
                       "Check the actual dosing histories and exposure coverage before extending this within-occasion comparison to a first dose or to another dosing interval.",
                       "dose_proportional","occasion_effect","changing_clearance")
            continue
        if peak is not None and peak < .8 and peak < exposure and d.get("cmax_label") == "POINTS_TO_NONLINEARITY":
            obs = (f"At {number(high)} versus {number(low)} mg/kg{period}, the {unit} gave high/low ratios of {peak:.3g} for peak concentration per dose "
                   f"and {exposure:.3g} for exposure per dose over {tw}")
            different_grids = w.get("same_grid") is False
            obs += " on unequal sampling grids." if different_grids else "."
            grid_note = "Repeat on shared times" if different_grids else "Check peak coverage"
            yield item("Compare the peak with exposure over the same window", obs,
                       grid_note + ". Check complete exposure and IV clearance before attributing the lower peak per unit dose to slower or capacity-limited input.",
                       "input_rate_limited", "dose_proportional", "changing_clearance")
        elif d.get("e6_label") == "POINTS_TO_NONLINEARITY":
            yield item("Test whether the exposure difference persists",
                       f"The {unit} gave a high/low ratio of {exposure:.3g} for exposure per dose at {number(high)} versus {number(low)} mg/kg{period} over {tw}.",
                       "Compare complete exposure on consistent grids and matched IV data before assigning the difference to systemic availability or clearance.",
                       "dose_proportional", "uptake_extent_loss", "changing_clearance")
        if d.get("e2_label") == "POINTS_TO_NONLINEARITY" and rows:
            a,b = rows[0], rows[-1]
            if a.get("thalf") is None or b.get("thalf") is None:
                continue
            words = []
            for r in (a,b):
                p = by_id.get((r.get("dataset_id"),r.get("series_id")))
                s = (p.m.get("terminal_selected") or {}) if p else {}
                tw = f" over {s['start']:.3g}–{s['end']:.3g} h" if s.get("start") is not None and s.get("end") is not None else ""
                words.append(f"{r['thalf']:.3g} h{tw} at {number(r['dose'])} mg/kg")
            yield item("Compare terminal half-lives on overlapping times",
                       "The apparent half-lives were " + " and ".join(words) + ".",
                       "Recheck late coverage and compare dose-matched IV disposition before linking the longer half-life to nonlinear clearance or prolonged input.",
                       "nonlinear_elimination", "ongoing_input", "changing_clearance")


def trough_check(profiles):
    eligible = [p for p in profiles if (p.series.get("t2") or {}).get("positive_count") and
                p.card.get("record_level") != "INDIVIDUAL_IDENTITY_UNVERIFIED"]
    for p in eligible:
        t = p.series["t2"]
        obs = (t.get("best") or {}).get("observations", [])
        if len(obs) != 3 or not all(z.get("c") is not None and z.get("t") is not None for z in obs):
            continue
        times = ", ".join(number(z["t"]) for z in obs)
        values = ", ".join(number(z["c"]) for z in obs)
        within = p.card.get("record_level") == "INDIVIDUAL" and p.card.get("identity_verified") == "yes" and t.get("test_executed")
        unit = p.unit_name if within else "the group means" if p.card.get("record_level") == "GROUP_MEAN" else "the observed series"
        qualifier = ("Verify dose history and replicate observations bracketing the trough before comparing one input with separated inputs."
                     if within else "Verify the dip in serial samples from individual animals before comparing separated inputs or recirculation.")
        return item("Check whether the rebound occurs within animals",
                    f"For {p.cid} ({p.arm}), {unit} were {values} {p.unit} at {times} h, respectively.",
                    qualifier,"separated_inputs","variable_lag","enterohepatic")
    return None


def alignment_check(conditions, profiles):
    by_id = {p.cid:p for p in profiles}
    for r in conditions:
        n = len(r.get("intervals") or [])
        exact = r.get("exact_pairs", 0)
        if n <= exact:
            continue
        a,b = by_id[r["a"]], by_id[r["b"]]
        return item("Align the collection times before comparing conditions",
                    f"{a.cid} ({a.arm}) versus {b.cid} ({b.arm}): {n-exact} nearby time pairs and {exact} exact matches.",
                    "Reconcile the collection times and check the concentration change possible between draws before testing a constant multiplier. Assess rate-only changes separately using complete exposures.",
                    "timing_sampling", "cl_v_coscaling", "rate_only")
    return None


def early_peak(profiles, constrained):
    arms = [p for p in profiles if p.card.get("record_level") != "INDIVIDUAL_IDENTITY_UNVERIFIED" and
            p.m.get("first_t") is not None and p.m["first_t"] == p.m.get("tmax") and p.m.get("cmax") is not None and
            p.m.get("cmax_status") == "OBSERVED_QUANTIFIED"]
    if not arms:
        return None
    p = arms[0]
    first_draw = p.m.get("first_sample_h") == p.m["first_t"]
    timing = "the first postdose draw" if first_draw else "the first quantified postdose draw"
    obs = (f"In {p.cid} ({p.arm}), {p.unit_name} reached their highest sampled value, {number(p.m['cmax'])} {p.unit}, "
           f"at {time(p.m['tmax'])}, {timing}. The rise and any shorter lag remain unresolved.")
    check = ("Compare only the input shapes retained for this arm using earlier draws, documented baseline and matched disposition."
             if constrained else "Obtain earlier draws and verify baseline before comparing immediate or lagged first-order, finite zero-order, transit and Weibull inputs.")
    return item("Resolve the rise before assigning an input shape", obs, check,
                "first_order","first_order_lag","zero_order","transit","weibull_gt1_immediate")


def iv_checks(refs, profiles):
    by_id = {p.cid:p for p in profiles}
    for r in refs:
        p = by_id[r["ev"]]
        t = r.get("terminal_comparison") or {}
        sel = p.m.get("terminal_selected") or {}
        pairs = [z for z in t.get("pairs", []) if z.get("ev_window_h") == [sel.get("start"),sel.get("end")] and
                 (z.get("ratio") or 0) > 0 and len(z.get("iv_window_h") or []) == 2]
        if not pairs or not sel.get("thalf"):
            continue
        pair = next((z for z in pairs if z.get("same_window")),pairs[0])
        same = pair.get("same_window")
        if same and not (str(pair.get("grade","")).startswith("EV_SHALLOWER") or pair.get("grade") == "EV_STEEPER"):
            continue
        ew, iw = time_window(*pair["ev_window_h"]), time_window(*pair["iv_window_h"])
        obs = (f"{p.cid} ({p.arm}) gave an apparent half-life of {sel['thalf']:.3g} h over {ew}. "
                f"The IV reference {r['iv']} gave {sel['thalf']/pair['ratio']:.3g} h over {iw}.")
        check = ("Check IV administration, dose comparability and window sensitivity before assigning the terminal slope to input or disposition."
                 if same else "Re-estimate the slopes over comparable time windows before interpreting the difference as absorption-limited decline (flip-flop).")
        yield item("Separate terminal-window effects from slow input",obs,check,"flip_flop","ongoing_input","multicompartment")
        break
    incomplete = [r for r in refs if r.get("f_status") == "INCOMPLETE_EXPOSURE_RATIO" and r.get("f_window") is not None]
    if incomplete:
        details = []
        for r in incomplete[:2]:
            w = r.get("observed_window") or {}
            tw = " over " + time_window(w["start_h"],w["end_h"]) if w.get("start_h") is not None and w.get("end_h") is not None else ""
            details.append(f"{r['f_window']:.4g} for {by_id[r['ev']].arm}{tw}")
        yield item("Keep the observed exposure ratio separate from absolute availability",
                   "The dose-normalized extravascular-to-IV exposure ratio was " + " and ".join(details) + ".",
                   "Check IV early coverage, both terminal tails and shared clearance before interpreting window ratios as absolute bioavailability.",
                   "f_change","changing_clearance")


def fallback(profiles, raw, parameters):
    if profiles:
        p = profiles[0]
        m = p.m
        if m.get("cmax_status") == "LOWER_BOUND_ONLY":
            return item("Resolve concentrations above the assay range",
                        f"In {p.cid} ({p.arm}), one or more samples exceeded the upper assay limit. The peak time and height are unresolved.",
                        "Recover dilution measurements or use the assay bounds when comparing early input shapes.","timing_sampling","first_order")
        if m.get("first_t") is not None and m.get("tmax") is not None and m.get("cmax") is not None:
            return item("Anchor the input comparison to measured times",
                        f"In {p.cid} ({p.arm}), {p.unit_name} were first quantifiable at {time(m['first_t'])}. The highest sampled value was {number(m['cmax'])} {p.unit} at {time(m['tmax'])}.",
                        "Compare input shapes on the same observations, with matched disposition and fit sensitivity to the peak sample.",
                        "first_order","zero_order","transit","timing_sampling")
        return item("Verify the observations available for modeling",
                    f"{p.cid} contains quantified concentrations, but the sampled rise and peak cannot be summarized from the recorded measurements.",
                    "Check sampling times, assay bounds and dose history before assessing input shape.","timing_sampling","first_order")
    if parameters:
        d = parameters[0]
        name = d["card"]["dataset_id"]
        types = {"TMAX":"peak time","THALF":"half-life","AUC":"exposure","CMAX":"peak concentration","F":"systemic availability"}
        value = next((v for v in d.get("params", []) if v.get("param") in types and v.get("value") is not None), None)
        observation = (f"{name} provides source-reported parameters without a timed concentration series." if not value else
                       f"{name} reports a {types[value['param']]} of {number(value['value'])} {value.get('unit') or '(unit unreported)'}. The underlying concentration series is unavailable.")
        return item("Verify what the reported parameter measures", observation,
                    "Check its definition, dose assignment and uncertainty before using it as a constraint. Request timed measurements to evaluate curve shape.",
                    "timing_sampling","first_order","f_change")
    if raw:
        c = raw[0]["card"]
        m = next((s.get("metrics", {}) for s in raw[0].get("series", [])), {})
        if "all postdose samples blq" in str(m.get("not_assessable_reason","")).lower():
            return item("Preserve the assay limits", f"All postdose measurements in {c['dataset_id']} were below quantification.",
                        "Keep the censored observations and assay limits. A quantified time series is needed to locate the rise or estimate a terminal slope.",
                        "timing_sampling","first_order","ongoing_input")
        if c.get("endogenous_review_required"):
            observation = f"{c['dataset_id']} contains a signal with unresolved endogenous contribution."
            check = "Verify assay specificity and baseline history before interpreting the signal as drug from this dose."
        elif c.get("matrix_category") != "PLASMA_SERUM_BLOOD":
            observation = f"The available observations in {c['dataset_id']} are from {c.get('matrix') or 'an unspecified matrix'}."
            check = "Obtain timed systemic concentrations or an independently justified observation model before applying central absorption predictions."
        else:
            observation = f"{c['dataset_id']} lacks an eligible quantified systemic profile for this comparison."
            check = "Verify the route, dosing and assay records and identify usable sampling times before comparing input models."
        return item("Resolve the source-data limitation",observation,check,"timing_sampling","baseline_carryover")
    return item("Identify an eligible source profile","No measured curve or source-reported parameter is available for this study.",
                "Identify the source, route, dose and timed systemic observations before assessing absorption.","timing_sampling")


def modeling_plan(studies, result):
    """State the next modeling comparisons once across studies; keep their scope in Context."""
    ids = {key for study in studies for key in study["dataset_ids"]}
    measured = any(d["card"]["dataset_id"] in ids and d["card"].get("tests_allowed")
                   and any(s.get("metrics", {}).get("n_quantified", 0) for s in d.get("series", []))
                   for d in result.get("datasets", []))
    rows = [row for study in studies for row in study["candidate_assessments"]]
    excluded = any(row["status"].startswith("EXCLUDED_IN_") for row in rows)
    rebound = any(cue["kind"] in {"WITHIN_ANIMAL_TROUGH", "GROUP_TROUGH_DESCRIPTION"}
                  for row in rows for cue in row.get("evidence", []))
    dose = any(d.get("dataset_ids") and set(d["dataset_ids"]) <= ids and d.get("status") in {"ASSESSED", "INDIVIDUAL_CONTRAST"}
               for d in result.get("dose_series", []))
    references = [r for r in result.get("ev_iv", []) if r.get("ev") in ids]
    conditions = any({pair["a"], pair["b"]} <= ids for pair in result.get("conditions", []))
    steps = []
    if excluded:
        steps.append("Apply the exclusions in each study’s Context when choosing model comparisons.")
    if not measured:
        steps.append("Verify the dose history, sampling times, assay limits and source-reported parameters. Obtain serial systemic concentrations before comparing absorption models.")
    else:
        steps.append("Check baseline and animal IDs. Use early samples to compare zero-order, first-order, transit and Weibull absorption with and without lag.")
        if rebound:
            steps.append("For confirmed within-animal rebounds, test parallel or sequential inputs and enterohepatic recirculation.")
    if dose:
        steps.append("Test saturable absorption against nonlinear clearance using dose-normalized Cmax, AUC and dose-matched IV data.")
    if any((r.get("terminal_comparison") or {}).get("pairs") for r in references):
        steps.append("Assess flip-flop kinetics using EV and IV half-lives from matched terminal windows.")
    if conditions:
        steps.append("Compare rate and extent across time-aligned conditions.")
    if any(r.get("f_window") is not None for r in references):
        steps.append("Estimate absolute bioavailability (F) from total dose-normalized EV/IV AUC ratios after verifying sampling coverage and shared clearance.")
    return " ".join(steps)


def study_brief(study, result):
    """Return up to three nonredundant checks in evidence order, independent of model preference."""
    if isinstance(study,str):
        study = next((b for b in result.get("status_boards", []) if b.get("study") == study), {"study_id":study})
    sid = study.get("study_id") or study.get("study")
    ids = set(study.get("dataset_ids",study.get("datasets",[])))
    def belongs(d):
        c = d["card"]
        if ids:
            return c["dataset_id"] in ids and (not sid or not c.get("study") or c["study"] == sid)
        return sid is not None and c.get("study") == sid
    ds = [d for d in result.get("datasets", []) if belongs(d)]
    ps = [d for d in result.get("reported_parameters", []) if belongs(d)]
    measured = [Profile(d["card"], s, {}) for d in ds for s in d.get("series", [])
                if s.get("metrics",{}).get("n_quantified",0)]
    profiles = [p for p in measured if p.card.get("tests_allowed")]
    dose_profiles = [p for p in measured if p.card.get("dose_series_allowed", p.card.get("tests_allowed"))]
    eligible = {p.cid for p in profiles}
    rows = study.get("candidate_assessments", [])
    available = {r["id"] for r in rows}
    formal = exclusions(rows)
    excluded = set(formal["candidate_ids"]) if formal else set()
    dose_ids = {p.cid for p in dose_profiles}
    doses = [d for d in result.get("dose_series", []) if d.get("dataset_ids") and set(d["dataset_ids"]) <= dose_ids and
             d.get("status") in {None, "ASSESSED", "INDIVIDUAL_CONTRAST"}]
    single_series = {d["card"]["dataset_id"] for d in ds if len(d.get("series", [])) == 1} & eligible
    refs = [r for r in result.get("ev_iv", []) if r["ev"] in single_series]
    pairs = [r for r in result.get("conditions", []) if {r["a"],r["b"]} <= single_series]
    options = [formal, identity_check(profiles), *dose_checks(doses, dose_profiles), trough_check(profiles),
               alignment_check(pairs, profiles), early_peak(profiles, bool(excluded)), *iv_checks(refs, profiles)]
    if not any(options):
        options.extend(dose_checks(doses, dose_profiles, overview=True))
    if not any(options):
        options.append(fallback(profiles, ds, ps))
    out = []
    for o in options:
        if not o or any(r["title"] == o["title"] for r in out):
            continue
        if available:
            o["candidate_ids"] = [k for k in o["candidate_ids"] if k in available and (o is formal or k not in excluded)]
        out.append(o)
        if len(out) == 3:
            break
    return out


