"""Plain-English observations for the r4.3 absorption mechanism reader."""
from dataclasses import dataclass
import re
from .eda_absorption_assessment import curve_cues, firm


EXCLUDED = "EXCLUDED_UNDER_STATED_ASSUMPTIONS"
LAGS = {"first_order_lag", "zero_order_lag", "weibull_lt1_lag", "weibull_eq1_lag", "weibull_gt1_lag", "transit_lag"}
TWO_INPUTS = {"separated_inputs", "burst_sustained", "gastric_emptying", "absorption_window", "enterohepatic", "pulmonary_enteral"}
DOSE_CASES = {"dose_proportional", "input_rate_limited", "uptake_extent_loss", "efflux_saturation", "first_pass_saturation",
              "parallel_linear_saturable_input", "nonlinear_elimination", "parallel_linear_saturable_elimination"}
CONDITION_CASES = {"cl_v_coscaling", "rate_only", "mixed_rate_extent", "occasion_effect"}
TAIL_CASES = {"flip_flop", "ongoing_input", "multicompartment", "binding_distribution", "shared_one_compartment"}
SECONDARY_INPUT = {"first_order", "zero_order", "parallel_immediate", "parallel_zero_first", "transit",
                   "weibull_lt1_immediate", "weibull_eq1_immediate", "weibull_gt1_immediate", "inverse_gaussian"}


def number(value):
    return f"{value:.5g}" if isinstance(value, (int, float)) else "unknown"


def time(value):
    if value is None:
        return "an unreported time"
    minutes = value * 60
    if 0 < value < 1 and abs(minutes - round(minutes)) < 1e-7:
        return f"{round(minutes)} min"
    return number(value) + " h"


def time_window(a, b):
    return f"{number(a)}–{number(b)} h"


def route_name(c):
    code = str(c.get("route_detail") or "").upper()
    if code in {"OTHER_EV", "IT", "", "NOT_FOUND", "ROUTE_UNKNOWN", "UNKNOWN"}:
        if code == "IT" or re.search(r"\bIT\b", c.get("title", "") + " " + str(c.get("dosing_regimen", ""))):
            return "IT-labelled"
        return "extravascular"
    return {"SC": "SC", "IP": "IP", "IM": "IM", "PO": "oral", "INTRATRACHEAL": "intratracheal",
            "INTRATHECAL": "intrathecal", "INHALED_WHOLE_BODY": "whole-body inhalation",
            "INHALED_NOSE_ONLY": "nose-only inhalation"}.get(code, "extravascular")


@dataclass
class Profile:
    card: dict
    series: dict
    assessment: dict

    @property
    def m(self):
        return self.series.get("metrics") or {}

    @property
    def cid(self):
        return self.card["dataset_id"]

    @property
    def unit(self):
        return self.card.get("unit") or "(unit unreported)"

    @property
    def arm(self):
        dose = self.series.get("dose")
        if dose is None:
            dose = self.card.get("dose_mg_per_kg")
        return (number(dose) + " mg/kg " if dose is not None else "") + route_name(self.card)

    @property
    def unit_name(self):
        level = self.card.get("record_level")
        if level == "INDIVIDUAL_IDENTITY_UNVERIFIED":
            return "the source-labelled observations for " + str(self.series.get("label") or "one label")
        if level == "INDIVIDUAL":
            return "the serial observations for " + str(self.series.get("label") or "one animal")
        if self.card.get("destructive_sampling"):
            return "the group means from animals sampled destructively"
        return "the group means" if level in {"GROUP_MEAN", "DESTRUCTIVE"} else "the recorded observations"


def observation(p):
    m = p.m
    point = next((z for z in m.get("t1_points", []) if z.get("t") == m.get("first_t") and
                  z.get("status") == "QUANTIFIED"), None)
    if point:
        return point
    # Older archived results may retain positive concentrations in the source series instead.
    return next((z for z in p.series.get("points", []) if z.get("t") == m.get("first_t") and
                 z.get("status") == "QUANTIFIED"), {})


def early(p):
    m = p.m
    point = observation(p)
    tf, tp, peak = m.get("first_t"), m.get("tmax"), m.get("cmax")
    amount = point.get("c")
    if amount is None and tf == tp:
        amount = peak
    start = f"For the {p.arm} profile, {p.unit_name} "
    at = f"{number(amount)} {p.unit} at {time(tf)}" if amount is not None else f"a quantifiable concentration at {time(tf)}"
    if tf is None:
        return start + "have no quantified postdose sample from which to read the rise."
    if m.get("cmax_status") == "LOWER_BOUND_ONLY":
        return (start + f"first show {at}. At least one observation exceeded the assay range, so the peak "
                "time and height of the whole signal remain unresolved.")
    first_draw = m.get("first_sample_h") == tf
    if tf == tp:
        return (start + f"first show {at}, already the highest sampled value. " +
                ("The rise before this first postdose draw was unsampled." if first_draw else
                 "No earlier postdose concentration was quantified to define the rise."))
    if tp is None or peak is None:
        return start + f"first show {at}. Peak timing is unresolved."
    n = m.get("n_before_peak")
    return (start + f"first show {at}. The highest sampled value was {number(peak)} {p.unit} at {time(tp)}."
            + (f" Only one quantified sample preceded that maximum." if n == 1 else
               f" {n} quantified samples preceded that maximum." if n is not None else ""))


def fixed_lag(p, row):
    z = observation(p)
    upper = z.get("t_hi")
    kind = "CONDITIONAL_LIMIT_ON_FIXED_LAG"
    scoped = any(e.get("kind") == kind and p.cid in e.get("dataset_ids", []) and
                 e.get("series_id") == p.series.get("series_id") for e in row.get("evidence", []))
    if not scoped or upper is None or not any(c.kind == kind for c in curve_cues(p.card, p.series)):
        return "A fixed lag can be bounded only with a positive concentration lower bound, justified draw times and a signal attributable to this dose."
    caveat = ""
    if p.card.get("time_origin_conflict") or "TIME_ORIGIN_UNCLEAR" in p.m.get("caveats", []):
        caveat = " The dosing clock and reported sampling times need reconciliation."
    notes = str(p.card.get("notes") or "")
    if re.search(r"(?i)(?:plotted|figure|digitized)[^.\n]{0,80}(?:differ|conflict|disagree)[^.\n]{0,65}(?:protocol|scheduled|nominal)", notes):
        caveat = " The source flags a discrepancy between the plotted times and the sampling schedule."
    return (f"If the stated bounds hold, the timing is correct and all measured drug came from this dose, a common fixed lag reaching "
            f"{time(upper)} or later is difficult to reconcile with that observation. This uses the draw’s upper "
            "time bound. Earlier fixed lags and gradual entry remain possible." + caveat)


def no_identity(p):
    if p.card.get("record_level") == "INDIVIDUAL_IDENTITY_UNVERIFIED":
        return "The same source label across draws has no verified link to one animal."
    if p.card.get("record_level") == "GROUP_MEAN":
        return "Group means alone cannot establish that individual animals share this pattern."
    return ""


def group_provenance(profiles):
    if all(p.card.get("record_level") == "GROUP_MEAN" for p in profiles):
        return "group means"
    if all(p.card.get("record_level") == "INDIVIDUAL" for p in profiles):
        return "verified animal records"
    return "available measurements"


def trough(p):
    t = p.series.get("t2") or {}
    best = t.get("best") or {}
    pts = best.get("observations") or []
    if t.get("positive_count") and len(pts) == 3 and all(z.get("c") is not None for z in pts):
        values = ", ".join(number(z["c"]) for z in pts)
        times = ", ".join(number(z["t"]) for z in pts)
        msg = f"In the {p.arm} profile, {p.unit_name} measured {values} {p.unit} at {times} h, respectively."
        return msg + " " + (no_identity(p) or "A within-animal fall and rise can motivate a second-input comparison, but several mechanisms can give this pattern.")
    if t.get("eligible_count"):
        return (f"In the {p.arm} profile, {p.unit_name} showed no resolved fall followed by a rise among "
                f"the {p.m.get('n_quantified', 0)} quantified samples under the recorded bounds. " +
                (no_identity(p) or "Events between draws remain unresolved."))
    return early(p) + " There are too few usable observations to establish a trough and secondary rise."


def baseline(p):
    m = p.m
    status = m.get("baseline_status", p.card.get("baseline_status"))
    value = m.get("predose_value")
    if value is not None:
        return (f"For the {p.arm} profile, the predose concentration was {number(value)} {p.unit} at "
                f"{time(m.get('predose_time_h'))}. A measured predose value must be interpreted against earlier doses and the assay.")
    describes = {"DESIGN_ZERO": "a zero baseline was assumed from the dosing design",
                 "WASHOUT_ZERO": "the zero baseline was assumed from washout",
                 "ZERO_OR_BLQ": "the predose result was zero or below quantification",
                 "ENDOGENOUS": "the source identifies an endogenous signal",
                 "MIXED": "the source identifies an endogenous contribution and prior-dose drug",
                 "RESIDUAL_FROM_PRIOR_DOSE": "the dosing history permits residual drug"}
    line = describes.get(status, "the available records do not establish a drug-free predose baseline")
    return f"For the {p.arm} profile, {line}. " + ("The first quantification was at " + time(m["first_t"]) + ". "
                    if m.get("first_t") is not None else "") + "The size of any residual contribution needs independent evidence."


def dose_reading(d, key, profiles):
    ids = set(d.get("dataset_ids", []))
    units = group_provenance([p for p in profiles if p.cid in ids])
    doses = d.get("dose_pair") or d.get("t3_primary_pair") or d.get("doses", [])
    if len(doses) < 2:
        return ""
    low, high = min(doses), max(doses)
    w = d.get("observed_window") or {}
    ratio, peak = d.get("R_window", d.get("R")), d.get("cmax_d_ratio")
    what = []
    if peak is not None:
        what.append(f"the peak concentration per dose was {number(peak)} times as high")
    if ratio is not None:
        metric = ("exposure per dose over " + time_window(w["start_h"], w["end_h"])) if w.get("start_h") is not None and w.get("end_h") is not None else "exposure per dose"
        what.append(f"{metric} was {number(ratio)} times as high")
    if not what:
        return ""
    msg = f"Comparing the {units} at {number(high)} versus {number(low)} mg/kg, " + " and ".join(what) + "."
    if key in {"nonlinear_elimination", "parallel_linear_saturable_elimination", "changing_clearance", "binding_distribution"}:
        by_dose = {r.get("dose"): r for r in d.get("rows", [])}
        a, b = by_dose.get(low, {}), by_dose.get(high, {})
        if a.get("thalf") is not None and b.get("thalf") is not None:
            msg += (f" Apparent terminal half-lives were {number(a['thalf'])} h at the lower dose and {number(b['thalf'])} h "
                    "at the higher dose. Compare the sampling windows and IV disposition before assigning that difference to clearance.")
        else:
            msg += " The source would need comparable IV exposure across doses to attribute this change to clearance."
    elif peak is not None and ratio is not None and peak < .8 and peak < ratio:
        msg += " The peak per dose fell more than observed exposure per dose. Sparse peak sampling and drug entering later can both produce that contrast."
    elif d.get("ci"):
        msg += f" The interval for the exposure ratio was {number(d['ci'][0])}–{number(d['ci'][1])}."
    else:
        msg += " The observed interval covers only part of total exposure, so this comparison cannot assign a change to absorption or clearance."
    return msg


def exposure_reading(refs, profiles):
    by_id = {p.cid:p for p in profiles}
    lines = []
    for r in refs:
        p = by_id.get(r["ev"])
        w = r.get("observed_window") or {}
        if p and r.get("f_window") is not None:
            lines.append(f"{number(r['f_window'])} for the {p.arm} profile on {time_window(w.get('start_h'), w.get('end_h'))}")
    if lines:
        origin = group_provenance([p for p in profiles if any(r["ev"] == p.cid for r in refs)])
        return (f"The dose-normalized extravascular-to-IV exposure ratio from the {origin} was " + " and ".join(lines[:2]) + ". " +
                ("Missing early or late exposure and uncertain clearance limit interpretation as absolute bioavailability."
                 if any(r.get("absolute_f") is None and r.get("f_window") is not None for r in refs) else
                 "Interpret these estimates under the documented coverage and shared-clearance assumptions."))
    return "The available IV exposure comparison lacks a compatible dose, exposure measure or shared observation window."


def tail_reading(p, refs):
    sel = p.m.get("terminal_selected") or {}
    if sel.get("thalf") is None:
        return early(p) + " This series has no qualified terminal half-life estimate."
    msg = (f"For the {p.arm} profile, {p.unit_name} give an apparent half-life of {number(sel['thalf'])} h "
           f"over {time_window(sel.get('start'), sel.get('end'))}.")
    if refs:
        r = next((v for v in refs if v["ev"] == p.cid), {})
        pairs = (r.get("terminal_comparison") or {}).get("pairs", [])
        compatible = [q for q in pairs if q.get("ev_window_h") == [sel.get("start"), sel.get("end")] and (q.get("ratio") or 0) > 0]
        if compatible:
            pair = next((q for q in compatible if q.get("same_window")), compatible[0])
            msg += (f" One qualified IV comparison gives {number(sel['thalf'] / pair['ratio'])} h over "
                    f"{time_window(*pair['iv_window_h'])}. " + ("The two sampling windows differ. " if not pair.get("same_window") else "") +
                    "The slopes alone do not identify whether absorption governs the terminal decline.")
            return msg
    return msg + " An independent disposition reference on comparable times is needed to separate prolonged input from slow disposition."


def condition_reading(r, profiles, key):
    a, b = (next((p for p in profiles if p.cid == r[k]), None) for k in ("a", "b"))
    if not (a and b):
        return ""
    exact = r.get("exact_pairs", 0)
    all_pairs = r.get("intervals", [])
    if key == "occasion_effect":
        if "occasion" not in r.get("differing_attributes", []):
            setup = ("Both arms received a single dose. " if all(p.card.get("single_dose") for p in (a,b))
                     else "The records do not establish a comparison of dosing occasions. ")
            return (f"The comparison is between {a.cid} ({a.arm}) and {b.cid} ({b.arm}). " + setup +
                    "There is no within-regimen comparison of the first and a later dose to assess accumulation or a change with occasion.")
        return (f"{a.cid} ({a.arm}) and {b.cid} ({b.arm}) differ in recorded dosing occasion. The concentration curves combine "
                "the current and any residual contributions. Comparison requires the dose history and expected accumulation.")
    if key == "rate_only" and not r.get("rate_only_evidence"):
        return (f"For {a.cid} ({a.arm}) and {b.cid} ({b.arm}), the records lack a qualified comparison of complete "
                "dose-normalized exposure under shared linear disposition. Whether only the absorption rate changed remains unresolved.")
    msg = f"The {group_provenance([a,b])} for {a.arm} versus {b.arm} have {exact} exact time matches"
    if len(all_pairs) > exact:
        msg += f" and {len(all_pairs)-exact} pairs at nearby times"
    msg += "."
    if key == "rate_only" and r.get("rate_only_evidence"):
        ci = r["rate_only_evidence"].get("ratio_ci")
        if ci:
            return msg + (f" The reported interval for the complete dose-normalized exposure ratio was {number(ci[0])}–{number(ci[1])}. "
                          "A rate-only change requires equal complete exposure under shared linear disposition.")
    if exact == 0:
        bounds = (r.get("timing_sensitivity") or {}).get("witness") or []
        examples = [z for z in all_pairs if z.get("records") in bounds and z.get("c") is not None]
        if len(examples) >= 2:
            intervals = [f"{number(z['c'])} at {number(z['t'])} versus {number(z['reference_t'])} h" for z in (examples[0], examples[-1])]
            msg += " Two observed concentration ratios were " + " and ".join(intervals) + ", with times listed in the same arm order."
        return msg + " The different sampling times limit a comparison of curve shape or a constant concentration multiplier."
    if all_pairs:
        exact_rows = [z for z in all_pairs if z.get("delta_h") == 0 and z.get("c") is not None]
        if exact_rows:
            values = [z["c"] for z in exact_rows]
            msg += f" At those exact times the observed concentration ratio ranged from {number(min(values))} to {number(max(values))}."
    return msg + " A difference in route or occasion alone cannot identify a change in absorption rate or availability."


def route_boundary(row, candidate, cards):
    required = {"pulmonary": "pulmonary delivery", "ip": "intraperitoneal delivery", "enteral": "enteral delivery",
                "depot": "an SC or IM injection", "portal": "oral or intraperitoneal administration"}.get(candidate.get("route"), "a verified administration route")
    unresolved = row["status"] == "ROUTE_SCOPE_UNRESOLVED"
    named = list(dict.fromkeys(route_name(c) for c in cards if c.get("matrix_category") == "PLASMA_SERUM_BLOOD"))
    descriptions = ", ".join(named) if named else "no comparable systemic route"
    if unresolved:
        return (f"The records describe {descriptions} dosing. This candidate requires {required}. "
                "The source label does not establish that delivery route.")
    return f"This candidate requires {required}. The available systemic concentration profiles describe {descriptions}."


def parameters_text(row, key, parameters):
    select = ("F",) if key == "f_change" else ("AUC","CMAX") if key in DOSE_CASES else ("THALF",) if key in TAIL_CASES else ("TMAX",)
    names = {"TMAX":"time of the peak", "CMAX":"peak concentration", "THALF":"half-life", "AUC":"exposure", "F":"systemic availability"}
    for typ in select:
        for d in parameters:
            for p in d.get("params", []):
                if p.get("param") != typ:
                    continue
                msg = f"The source reports {names[typ]} of {number(p.get('value'))} {p.get('unit') or '(unit unreported)'}"
                msg += (f" at {number(p['dose'])} mg/kg." if p.get("dose") is not None else ". The dose for this value is unresolved.")
                return msg + " The underlying concentration measurements are unavailable to check the curve shape independently."
    if key == "f_change":
        for e in row.get("evidence", []):
            if e.get("kind") == "SOURCE_REPORTED_F":
                v = re.search(r"source-reported F\s+([+\-\d.eE]+)\s*(%|percent(?:age)?|fraction)?", e.get("text", ""), re.I)
                if v:
                    return (f"The source reports systemic availability of {v.group(1)}{v.group(2) or ' (as reported)'}. "
                            "The underlying concentration measurements and a comparable control are needed to assess a change in availability.")
    return "Only source-reported parameter summaries are available. Timed concentration measurements are needed to test the proposed explanation."


def formal_exclusions(row, profiles, refs):
    outputs = []
    for p in profiles:
        if p.assessment.get("formal_status") != EXCLUDED:
            continue
        for t in p.assessment.get("tests", []):
            if t.get("formal_status") != EXCLUDED or not t.get("executed") or not firm(t):
                continue
            if t["test"] == "T1":
                ts = t.get("witness_times_h") or []
                where = f" between {time(ts[0])} and {time(ts[-1])}" if len(ts) >= 2 else ""
                reason = ("concentration divided by time since dosing increased" + where + " beyond the supported uncertainty. "
                          "That conflicts with an input rate that stays constant or decreases from dosing under the stated linear disposition.")
            elif t["test"] == "T2":
                ts = t.get("witness_times_h") or []
                where = " at " + ", ".join(time(v) for v in ts) if ts else ""
                reason = ("a verified individual trajectory fell and then rose" + where + " beyond the supported uncertainty. "
                          "That conflicts with the single-peak prediction under the stated input and linear disposition.")
            else:
                continue
            outputs.append(f"For {p.cid} ({p.arm}), using {p.unit_name}, " + reason +
                           " This exclusion requires a single dose, zero initial amounts and central input and observation.")
    for z in row.get("contrast_assessments", []):
        if z.get("formal_status") != EXCLUDED or not firm(z):
            continue
        ids = z.get("dataset_ids", [])
        label = z["test"]
        e = z.get("evidence") or {}
        by_id = {p.cid:p for p in profiles}
        if label in ("T3","T3p"):
            dp = e.get("low_high_doses_mg_kg") or []
            title = (f"The {number(dp[-1])} versus {number(dp[0])} mg/kg comparison" if len(dp) >= 2 else "The scoped dose comparison")
            title += " (" + ", ".join(ids) + ")" if ids else ""
            if label == "T3":
                ci = e.get("ci")
                numbers = (f" (ratio {number(e['ratio'])}" + (f", interval {number(ci[0])}–{number(ci[1])}" if ci else "") + ")"
                           if e.get("ratio") is not None else "")
                outputs.append(title + " excludes equal dose-normalized exposure" + numbers +
                               " under the stated design. The result alone cannot distinguish a change in input from a change in disposition.")
            else:
                outputs.append(title + " excludes proportional concentration profiles at the tested matched times after adjustment for multiple comparisons. "
                               "Attribution to absorption requires an independent disposition comparison.")
        elif label == "T4":
            pair = next((r for r in refs if [r["ev"],r["iv"]] == ids), None)
            source = by_id.get(ids[0]) if ids else None
            observed = "the matched extravascular-to-IV concentration ratio declined beyond the supported uncertainty"
            if pair:
                records = (pair.get("t4") or {}).get("witness", [])
                pts = [q for q in pair.get("q", []) if q.get("records") in records and q.get("delta_h") == 0]
                if len(pts) >= 2:
                    observed += f" from {number(pts[0]['q'])} at {time(pts[0]['t'])} to {number(pts[-1]['q'])} at {time(pts[-1]['t'])}"
            outputs.append((f"For {source.cid} ({source.arm}) against IV {ids[-1]}, " if source else
                            f"In the matched extravascular and IV comparison ({' / '.join(ids)}), ")
                           + observed + ". This rules out the shared linear one-compartment prediction for this comparison. The cause of the terminal slope remains separate.")
        elif label in ("T5","RATE_ONLY"):
            who = " versus ".join(f"{i} ({by_id[i].arm})" if i in by_id else i for i in ids)
            title = ("For " + who + ", " if who else "In the specified condition contrast, ")
            if label == "T5":
                outputs.append(title + "the concentrations at matched times cannot be reconciled with one constant multiplier under the stated uncertainty. "
                               "The exclusion applies only to a mechanism that rescales the whole curve without changing its shape.")
            else:
                ci = e.get("ratio_ci")
                val = (f" (interval {number(ci[0])}–{number(ci[1])})" if ci else "")
                outputs.append(title + "complete dose-normalized exposures differed" + val +
                               ". With common linear disposition and the same site of systemic input, a pure rate change cannot explain that difference.")
    return " ".join(dict.fromkeys(outputs))


def _select(profiles, row):
    def priority(p):
        scores = [e.get("score", 0) for e in row.get("evidence", []) if p.cid in e.get("dataset_ids", [])
                  and (not e.get("series_id") or e.get("series_id") == p.series.get("series_id"))]
        return max(scores, default=0)
    return max(profiles, key=priority)


def support_text(row, candidate, datasets, dose_series, ev_iv, conditions):
    """Explain one assessed candidate using only its own routes, profiles and comparison arms."""
    key = candidate["id"]
    scoped = row.get("profile_assessments", [])
    ids = {p["dataset_id"] for p in scoped}
    local = [d for d in datasets if d["card"]["dataset_id"] in ids]
    cards = [d["card"] for d in local]
    if row.get("status") in {"OUTSIDE_ROUTE_SCOPE", "ROUTE_SCOPE_UNRESOLVED"}:
        return route_boundary(row, candidate, cards)
    eligible = {(z["dataset_id"], z.get("series_id")): z for z in scoped if z.get("route_scope") == "APPLICABLE"}
    parameters = [d for d in local if "params" in d and (d["card"]["dataset_id"],None) in eligible]
    profiles = []
    withheld = []
    for d in local:
        c = d["card"]
        for s in d.get("series", []):
            a = eligible.get((c["dataset_id"],s.get("series_id")))
            if a is None:
                continue
            p = Profile(c,s,a)
            if c.get("tests_allowed") and p.m.get("n_quantified",0) and a.get("formal_status") not in {"GATED_PROFILE", "NO_QUANTIFIED_PROFILE"}:
                profiles.append(p)
            else:
                withheld.append(p)
    allowed = {p.cid for p in profiles}
    pairs = [r for r in conditions if {r["a"], r["b"]} <= allowed]
    refs = [r for r in ev_iv if r["ev"] in allowed]
    doses = [r for r in dose_series if r.get("dataset_ids") and set(r["dataset_ids"]) <= allowed]
    if row.get("status") in {"EXCLUDED_IN_SPECIFIED_PROFILES", "EXCLUDED_IN_SPECIFIED_COMPARISONS"}:
        # Reported AUC summaries may furnish a formal exposure comparison without timed concentrations.
        excluded = formal_exclusions(row, profiles, refs)
        if excluded:
            return excluded
        return "The assessment records an exclusion confined to its documented comparison and assumptions. The supplied profiles do not resolve its supporting observations."
    if not profiles:
        if parameters or any(z.get("formal_status") == "REPORTED_PARAMETER_ONLY" for z in eligible.values()):
            return parameters_text(row, key, parameters)
        if withheld:
            p = withheld[0]
            if p.m.get("n_blq") and not p.m.get("n_quantified") and "all postdose" in p.m.get("not_assessable_reason", "").lower():
                return f"All postdose samples for the {p.arm} profile were below the quantification limit. Their timing cannot establish a rise, peak or decline."
            if key == "baseline_carryover" and p.card.get("endogenous_review_required"):
                return baseline(p) + " A selective assay is needed to separate administered drug from the endogenous signal."
            if p.card.get("matrix_category") != "PLASMA_SERUM_BLOOD":
                return f"The available {p.arm} observations were collected in {p.card.get('matrix') or 'a noncentral matrix'}. They cannot support the central blood-concentration prediction for this candidate."
            return "The administration history, measured signal or observation timing prevented an eligible systemic concentration comparison."
        return "The assessment contains no eligible measured concentration profile for this candidate."
    p = _select(profiles, row)
    # Keep source-level joins on the same series, and mark a single example when other curves qualify.
    def example(message):
        identity = p.arm.replace(" mg/kg ", " mg/kg, ")
        name = f"{p.cid} ({identity})"
        lead = f"In one representative profile, {name}, " if len(profiles) > 1 else f"In {name}, "
        for prefix in (f"For the {p.arm} profile, ", f"In the {p.arm} profile, "):
            if message.startswith(prefix):
                return lead + message[len(prefix):]
        return message
    def best_pair(items, keys):
        return next((r for r in items if p.cid in [r.get(k) for k in keys]), items[0] if items else None)
    contrast = best_pair(pairs, ("a", "b"))
    if key in CONDITION_CASES and contrast:
        return condition_reading(contrast, profiles, key)
    if key == "timing_sampling" and contrast and (len(contrast.get("intervals", [])) > contrast.get("exact_pairs",0)):
        return condition_reading(contrast, profiles, key)
    if key == "f_change" and refs:
        return exposure_reading(refs, profiles)
    if key == "f_change" and contrast:
        return condition_reading(contrast, profiles, key)
    if (key in DOSE_CASES or key in {"changing_clearance", "depot_release", "solubility_limited"}) and doses:
        d = next((d for d in doses if p.cid in d["dataset_ids"]), doses[0])
        text = dose_reading(d,key,profiles)
        if text:
            if key in {"depot_release", "solubility_limited", "parallel_linear_saturable_input", "uptake_extent_loss"}:
                text += " A plasma comparison alone cannot locate a bottleneck in release, uptake or disposition."
            return text
    if key == "shared_one_compartment" and refs:
        r = best_pair(refs, ("ev",))
        records = (r.get("t4") or {}).get("witness") or []
        pts = [z for z in r.get("q", []) if z.get("records") in records and z.get("delta_h") == 0]
        if len(pts) >= 2:
            text = (f"For the {next(pp.arm for pp in profiles if pp.cid == r['ev'])} profile and its IV reference, the measured concentration ratio "
                    f"went from {number(pts[0]['q'])} at {time(pts[0]['t'])} to {number(pts[-1]['q'])} at {time(pts[-1]['t'])}.")
            if (r.get("t4") or {}).get("missing_premises"):
                text += " Uncertainty, IV delivery and comparability must be justified before using this contrast to exclude a common disposition."
            return text
    if key in TAIL_CASES:
        local_ref = next((r for r in refs if r["ev"] == p.cid), None)
        line = example(tail_reading(p,[local_ref] if local_ref else []))
        if p.card.get("record_level") == "INDIVIDUAL_IDENTITY_UNVERIFIED":
            line += " " + no_identity(p)
        return line
    if key == "baseline_carryover":
        return example(baseline(p))
    if key in TWO_INPUTS or key == "variable_lag":
        if key == "pulmonary_enteral":
            return example(early(p)) + " The plasma measurement combines any pulmonary and swallowed contributions. Separating these pathways requires independent route-specific evidence."
        if key == "variable_lag" and no_identity(p):
            return example(early(p)) + " " + no_identity(p) + " Variation in true onset across animals remains unresolved."
        if key == "variable_lag":
            animals = [z for z in profiles if z.cid == p.cid and z.arm == p.arm and
                       z.card.get("identity_verified") == "yes" and z.m.get("tmax") is not None and z.m.get("cmax_status") != "LOWER_BOUND_ONLY"]
            if len(animals) > 1:
                peaks = [z.m["tmax"] for z in animals]
                return (f"Across {len(peaks)} verified animals in the {p.arm} arm, the times of the highest sampled concentrations "
                        f"ranged from {time(min(peaks))} to {time(max(peaks))}. These peak times alone do not identify each animal’s absorption onset.")
            return example(early(p)) + " More than one adequately sampled, verified animal is needed to compare variation in onset."
        return example(trough(p))
    text = example(early(p))
    if p.card.get("record_level") == "INDIVIDUAL_IDENTITY_UNVERIFIED":
        text += " " + no_identity(p)
    if key in LAGS:
        return text + " " + fixed_lag(p, row)
    if key in SECONDARY_INPUT:
        by_draw = any(c.kind == "CONDITIONAL_LIMIT_ON_FIXED_LAG" for c in curve_cues(p.card, p.series))
        if by_draw:
            animals = " in at least some contributing animals" if p.card.get("record_level") == "GROUP_MEAN" else ""
            text += f" If that first signal came from the current dose, systemic input had begun by that draw{animals}."
        test = p.m.get("t1") or {}
        best = test.get("best") or {}
        ts = best.get("times_h") or []
        if candidate.get("t1") and test.get("positive_count") and len(ts) == 2 and ts[0] > p.m.get("tmax", float("inf")):
            return (text + f" Concentration divided by time since dosing increased between {time(ts[0])} and {time(ts[1])}, after the "
                    "sampled peak. That late pair gives no direct evidence about a delay on the rising limb. "
                    + ("Uncertainty and the model assumptions still limit the comparison." if test.get("missing_premises") else
                       "Its interpretation depends on the assumed input and disposition."))
        status = p.m.get("rise_shape")
        if status in {"FIRST_ORDER_LIKE","ZERO_ORDER_LIKE"}:
            return text + " The observed plasma rise is compatible with comparing first-order and finite constant-rate inputs under matched disposition. The plasma shape alone cannot distinguish them."
        return text + " The exact onset and input order remain unresolved."
    if key in DOSE_CASES or key == "changing_clearance":
        return text + " No comparable multi-dose series is available to establish how exposure or clearance changes with dose."
    if key == "f_change":
        return text + " These extravascular measurements lack a comparable IV exposure denominator for estimating absolute bioavailability."
    if key == "occasion_effect":
        return text + " There is no within-regimen comparison of the first and a later dose to assess an occasion effect."
    if key == "rate_only":
        return text + " A second condition with complete dose-normalized exposure and shared linear disposition is needed to assess a pure rate change."
    if key in CONDITION_CASES:
        return text + " There is no comparable second condition to distinguish changes in rate, availability and disposition."
    if key == "finite_administration":
        return text + (" The source documents a finite administration period; delivery and release can occur on different schedules."
                       if p.card.get("known_finite_administration") else " Delivery duration cannot be recovered from the plasma measurements alone.")
    return text


