"""Study-level r4.3 questions assembled from the recorded per-condition results."""
from . import eda_absorption as ab


NO = ab.ST_NO
PART = ab.ST_PART
YES = ab.ST_YES
NA = ab.ST_NA
UNKNOWN = "not reported"
EXCLUDED = "EXCLUDED_UNDER_STATED_ASSUMPTIONS"
UNCERTAIN_ID = "INDIVIDUAL_IDENTITY_UNVERIFIED"

# The named premises also apply to the candidate table on Q3.
M0 = ("Single dose, zero initial amounts, central input and central concentration, "
      "linear time-invariant one-compartment or reversible mammillary disposition.")
RULE = {
    1: ("When is drug first quantified, and what time interval bounds onset?",
        "A biological onset bound needs a justified dose time, drug-free baseline and assay limits.",
        "First detection alone cannot distinguish a hard lag from a gradual rise."),
    2: ("What do the sampled rise and peak show?",
        "The peak refers to the measured signal and sampled times.",
        "Concentration increments combine systemic input with distribution and elimination."),
    3: ("Which complete input and disposition combinations are excluded?",
        M0, "T1 and T2 cannot rank the surviving models."),
    4: ("Is there a within-animal trough and secondary rise?",
        "T2 requires definitely ordered observations of one verified animal after one dose or washout.",
        "A change in group means cannot establish a within-animal trough or its cause."),
    5: ("Is the shape shared across animals or produced by averaging?",
        "A within-animal trajectory requires verified cross-time identity.",
        "Source labels or group means alone cannot establish a feature in individual animals."),
    6: ("Could slow absorption account for the terminal decline?",
        "Interpret terminal windows separately from T4, which tests a matched EV/IV concentration ratio.",
        "A ratio decline alone cannot identify the cause of the terminal slope."),
    7: ("Can EV and IV exposure estimate systemic bioavailability?",
        "Absolute F requires comparable dose and analyte bases, common clearance and adequate exposure coverage.",
        "An incomplete exposure ratio alone cannot identify absolute F."),
    8: ("Do Cmax and AUC increase in proportion to dose?",
        "Compare like doses and occasions on a shared observed window, with uncertainty appropriate to the design.",
        "A point ratio alone cannot establish dose proportionality or identify its mechanism."),
    9: ("Can one concentration ratio describe both conditions at all matched times?",
        "T5 compares a positive multiplier on raw concentrations with aligned times and supported uncertainty.",
        "Timing sensitivity alone cannot exclude a multiplier, estimate F or separate rate from extent."),
}
LABEL = ("Onset and delay", "Sampled rise and peak", "Input and disposition models", "Trough and secondary rise",
         "Individual trajectories", "Terminal decline and flip-flop", "Systemic bioavailability",
         "Dose proportionality", "Scaling across conditions")
PANELS = {1: ("A1", "A1ind", "A2"), 2: ("A1", "A1ind", "A3", "F"), 3: ("A2", "T2", "A1"),
          4: ("B1", "T2", "A1ind", "B1ind", "A3"), 5: ("A1ind", "B1ind", "A4"),
          6: ("D1", "B1", "B2", "F"), 7: ("D2", "F"), 8: ("C1", "C2T3", "C3", "C2", "C3d", "F"),
          9: ("E1", "E2", "E3")}


def show(x):
    if x is None or x == "":
        return UNKNOWN
    if isinstance(x, float):
        return f"{x:.5g}"
    if isinstance(x, (tuple, list)):
        return ", ".join(show(z) for z in x) or "none"
    if isinstance(x, dict):
        return ". ".join(str(k).replace("_", " ") + " " + show(v) for k, v in x.items()) or UNKNOWN
    return str(x)


def span(times):
    return "–".join(show(t) for t in times) + " h" if times else UNKNOWN


def status(result, label_key, flags_key, descriptive=False):
    label = result.get(label_key)
    if label in {EXCLUDED, "NOT_EXCLUDED"} and not set(result.get(flags_key, ())) & ab._HOLD:
        return YES
    return PART if descriptive or label in {"BORDERLINE", "SINGLE_POINT_SUPPORT", "SENSITIVITY_ONLY"} else NO


def condition(c, series=None):
    route = c.get("route_detail")
    if route in {None, "", "OTHER_EV", "NOT_FOUND"}:
        # Keep the source title for unresolved route codes (e.g. IT).
        route = c.get("title") or route
    dose = series.get("dose") if series else c.get("dose_mg_per_kg")
    label = f"{c['dataset_id']} · {route}"
    if dose is not None and route != c.get("title"):
        label += f" {show(dose)} mg/kg"
    if series and c.get("series_kind") == "INDIVIDUALS":
        label += " · " + series["label"]
    return label


def add(rows, n, ids, name, state, result, details=None, *, missing=(), fig=None, priority=0, table=None):
    rows[n].append(dict(ids=list(ids), name=name, state=state, result=result, details=details or {},
                        missing=list(filter(None, missing)), fig=fig, priority=priority, table=table))


def handoff(t1, t2):
    families = [
        ("Immediate first-order, no lag (single Weibull β = 1), or finite zero-order from dosing", True, True),
        ("Single Weibull, no lag, 0 < β < 1", True, False),
        ("Positive mixture of immediate non-increasing input rates", True, False),
        ("Single Weibull, no lag, β > 1", False, True),
        ("Fixed lag then finite zero-order, first-order or single Weibull β ≥ 1", False, True),
        ("Fixed lag then single Weibull 0 < β < 1", False, False),
        ("Serial first-order transit with fixed positive rates, with or without a final first-order step", False, True),
    ]
    result = []
    for family, in_t1, in_t2 in families:
        labels = []
        for code, applies, test in (("T1", in_t1, t1), ("T2", in_t2, t2)):
            labels.append(f"{code}: " + (ab._flags(test.get("formal_status"), test.get("flags"))
                                        if applies else "outside this guarantee"))
        result.append([family, *labels])
    return ab._tbl("Unranked input candidates under the stated dose, observation and disposition premises",
                   ["Input family", "Non-increasing C/t", "Single peak region"], result)


def curve_questions(rows, d, s):
    c, m = d["card"], s["metrics"]
    cid = c["dataset_id"]
    name = condition(c, s)
    def item(n, state, message, evidence=None, **options):
        add(rows, n, [cid], name, state, message, evidence, **options)
    if not c["tests_allowed"]:
        return
    count = m.get("n_quantified", 0)
    uncertain = c["record_level"] == UNCERTAIN_ID
    if not count:
        reason = m.get("not_assessable_reason", "no quantified postdose observations")
        for n in (1, 2, 3, 4, 6):
            item(n, NO, f"{reason} ({m.get('n_blq', 0)} BLQ).", missing=["Quantified postdose measurements"])
        return
    ind_view = d.get("A1ind") if uncertain else None
    first = m["first_t"]
    item(1, PART, f"First quantified at {show(first)} h. Onset {m['onset_status']}.",
         {"Observation interval": span(m.get("observation_interval_h")), "Baseline": m.get("baseline_status"),
          "Time origin": m.get("dose_time_basis"), "Predose record": m.get("predose_record_id"),
          "Hard-lag lower bound (h), conditional": m.get("conditional_hard_lag_lower_bound_h"), "Reason": m.get("onset_reason")},
         fig=ind_view or s.get("A1"), missing=[m.get("onset_reason") if m["onset_status"] == "NOT_ASSESSABLE" else None])
    verified = c["record_level"] == "INDIVIDUAL" and c.get("identity_verified") == "yes"
    adequate = verified and m["n_before_peak"] >= 2 and m.get("rise_shape") not in (None, "NOT_ASSESSABLE")
    censored = m.get("cmax_status") == "LOWER_BOUND_ONLY"
    peak = (f"Cmax ≥ {show(m.get('cmax_lower_bound'))} {c.get('unit', '')}; maximum quantified sample at"
            if censored else f"Sampled maximum {show(m['cmax'])} {c.get('unit', '')} at")
    item(2, YES if adequate and not censored else PART, f"{peak} {show(m['tmax'])} h with {m['n_before_peak']} earlier quantified sample(s).",
         {"Rise shape": m.get("rise_shape"), "Peak status": m.get("cmax_status"),
          "ΔC/Δt between quantified pre-peak observations": [i.get("dcdt") for i in m.get("increments", [])],
          "Censored peak rows": m.get("censored_peak_rows")},
         fig=ind_view or s.get("A1"), priority=m["n_before_peak"],
         missing=[] if adequate else ["Adequate early samples in verified individuals"])
    t1 = m.get("t1", {})
    t2 = s.get("t2", {})
    states = [status(t, "formal_status", "flags", bool(t.get("eligible_count"))) for t in (t1, t2)]
    t1_label, t2_label = t1.get("formal_status", "CANNOT_ASSESS"), t2.get("formal_status", "CANNOT_ASSESS")
    best1 = t1.get("best") or {}
    best2 = t2.get("best") or {}
    t2_active = bool(t2.get("test_executed"))
    state = max((states[0], states[1] if t2_active else NO), key=ab._RANK.get)
    t2_primary = t2_active and (t2_label == EXCLUDED or (t2.get("numeric_contradiction") and t1_label != EXCLUDED))
    chosen = (s.get("T2") if t2_primary else s.get("A2")) if not uncertain else ind_view
    rising = m.get("t1_rising_subset", {})
    q3message = (f"T1 {t1_label}: {t1.get('positive_count', 0)} positive of {t1.get('eligible_count', 0)} full-window pairs, "
                 f"maximum C/t margin {show(best1.get('margin'))} {c.get('unit', '')}/h. "
                 + (f"Within-animal T2 {t2_label}." if t2_active else "Within-animal T2 unavailable."))
    item(3, state, q3message, {"T1 window": span(t1.get("window_h")), "Positive T1 pairs": t1.get("positive_count"),
         "Eligible T1 pairs": t1.get("eligible_count"), "Witness times": span(best1.get("times_h")),
         "Witness source rows": best1.get("record_ids"), "T1 flags": t1.get("flags"),
         "T1 witness: time, value and bounds": best1.get("observations"),
         "T1 witness removal outcomes": [z for z in t1.get("removals", []) if z.get("removed_record_id") in best1.get("record_ids", [])],
         "Widened margin": ((t1.get("widening") or {}).get("best") or {}).get("margin"),
         "Rising subset, positive / eligible": f"{rising.get('positive_count', 0)} / {rising.get('count', 0)}",
         "T1 missing premises": t1.get("missing_premises"), "T2 classification": t2.get("basis"),
         "T2 witness rows": best2.get("record_ids") if t2_active else None,
         "T2 margin": best2.get("margin") if t2_active else None,
         "Next discriminating evidence": "Earlier and replicated serial samples, a comparable IV disposition reference, independent release or administration data.",
         "Disposition alternatives": "Changes in distribution, metabolism or elimination remain pending DME. Sparse sampling gives weak information."},
         fig=chosen, priority=3 if t2_primary or t1_label == EXCLUDED else int(bool(t1.get("positive_count"))),
         table=handoff(t1, t2), missing=[*t1.get("missing_premises", []), *t2.get("missing_premises", [])])
    observed_triples = t2.get("positive_count", 0)
    post_count = max(0, count - m["n_before_peak"] - 1)
    has_description = bool(observed_triples or post_count >= 2)
    q4status = status(t2, "formal_status", "flags", has_description) if t2_active else PART if has_description else NO
    kind = "Within-animal T2" if t2_active else "Conditional source-label description" if uncertain else "Group-mean description"
    q4msg = (f"{kind}: {observed_triples} positive ordered triples of {t2.get('eligible_count', 0)} scanned. "
             + (f"T2 {t2_label}." if t2_active else "Within-animal T2 unavailable."))
    if observed_triples:
        q4msg += f" Strongest triple at {span(best2.get('times_h'))}, margin {show(best2.get('margin'))} {c.get('unit', '')}."
    item(4, q4status, q4msg, {"Times of strongest triple": span(best2.get("times_h")),
         "Concentrations": [p.get("c") for p in best2.get("observations", [])],
         "Record IDs": best2.get("record_ids"), "M_drop": best2.get("m_drop"), "M_rise": best2.get("m_rise"),
         "Minimum margin": best2.get("margin"), "Unit": c.get("unit"), "Flags": t2.get("flags"),
         "Quantified post-peak samples": post_count}, fig=(s.get("T2") or ind_view or s.get("B1")),
         priority=int(bool(observed_triples)), missing=t2.get("missing_premises", []))
    tail = m.get("terminal_selected") or {}
    item(6, PART if tail else NO,
         (f"EV apparent t½ {show(tail['thalf'])} h over {span([tail['start'], tail['end']])}."
          if tail else "Qualified EV terminal slope unavailable."),
         {"Window status": m.get("terminal_status"), "Window observations": tail.get("record_ids"),
          "Other qualified t½ (h)": [w.get("thalf") for w in m.get("terminal_windows", []) if w.get("qualified") and w != tail],
          "Cause of terminal decline": "UNRESOLVED"}, fig=s.get("B1") if tail else None,
         missing=["Independent comparable disposition or absorption evidence"])


def individuals(rows, d):
    c = d["card"]
    if not c["tests_allowed"]:
        return
    series = d["series"]
    valid = [s for s in series if s["metrics"].get("n_quantified", 0)]
    verified = c["record_level"] == "INDIVIDUAL" and c.get("identity_verified") == "yes"
    conditional = c["record_level"] == UNCERTAIN_ID
    enough = len(valid) >= 2 and len(valid) == len(series) and all(
        0 < s["metrics"]["n_before_peak"] < s["metrics"]["n_quantified"] - 1 for s in valid)
    state = YES if verified and enough else PART if valid and (verified or conditional) else NO
    points = [f"{s['label']} {show(s['metrics']['tmax'])} h" for s in valid]
    if valid and (conditional or verified):
        msg = (f"Observed maxima by {'source label' if conditional else 'animal'}: {', '.join(points)}. "
               + ("Cross-time identity unverified (CONDITIONAL_ON_LABEL_IDENTITY)." if conditional else "Serial identity verified."))
    else:
        msg = ("Destructive sampling" if c.get("destructive_sampling") else "Group-level or insufficient observations") + " cannot establish whether individual animals share the feature."
    add(rows, 5, [c["dataset_id"]], condition(c), state, msg,
        {"Source record level": c["record_level"], "Serial identity": c.get("identity_verified"), "n per time": c.get("n_per_time")},
        fig=d.get("A1ind"), missing=[] if state == YES else ["Verified cross-time identity and observations bracketing the feature in multiple animals"])


def reported(rows, ps):
    c, ana = ps["card"], ps.get("analysis") or {}
    cid = c["dataset_id"]
    for p in ps["params"]:
        n = {"TMAX": 2, "THALF": 6, "F": 7, "AUC": 8, "CMAX": 8}.get(p["param"])
        if not n:
            continue
        label = p["label"]
        source = p.get("record_id") or cid
        name = f"{cid} · {source}" if source != cid else cid
        dose = p.get("dose")
        details = {"Source": p.get("source"), "Record": source, "EV dose (mg/kg)": dose,
                   "Dose basis": c.get("dose_basis"), "Definition": p.get("definition"),
                   "Mean type": c.get("mean_type"), "n for this parameter": p.get("n") if not p.get("n_from") else None,
                   "Source n, unassigned to parameter" : p.get("n") if p.get("n_from") else None,
                   "Dispersion": p.get("dispersion"), "Spread type": p.get("dispersion_type"), "SD / SE basis": p.get("sd_kind")}
        msg = f"Source-reported {label} {show(p['value'])} {p.get('unit') or '(unit not reported)'}."
        missing = []
        if n == 6:
            msg += " The terminal definition and independent disposition reference determine its scope."
            for ref in ana.get("reported_iv_references", []):
                for ivp in ref.get("params", []):
                    if ivp["param"] == "THALF":
                        key = f"REPORTED_IV_PARAMETER · {ref['dataset_id']} · {ivp.get('record_id') or ivp['label']}"
                        details[key] = (f"{show(ivp['value'])} {ivp.get('unit') or '(unit not reported)'}. "
                                        f"{ivp.get('definition') or UNKNOWN}. IV dose {show(ivp.get('dose'))} mg/kg. "
                                        "Comparability needs a terminal λz definition, matching analyte, design and observation period.")
        if n == 7:
            f = ana.get("f") or {}
            # A dataset may report several F values. Associate flags with their own observation.
            raw_value = p["value"] / 100 if str(p.get("unit")).lower() in {"%", "percent", "percentage"} else p["value"]
            flags = [i for i in f.get("flags", []) if i != "F_ABOVE_ONE"] + (["F_ABOVE_ONE"] if raw_value > 1 else [])
            details.update({"Scope": "SOURCE_REPORTED", "Flags": flags, "Source IV checks": f.get("checks")})
            msg += " SOURCE_REPORTED" + (" · " + ", ".join(flags) if flags else "") + "."
        if n == 8:
            msg += (" Dose assignment unresolved." if dose is None else f" Assigned dose {show(dose)} mg/kg.") + " A reported value alone cannot establish dose dependence."
            missing = ["Comparable dose assignments, exposure definitions and design-matched uncertainty"]
        add(rows, n, [cid], name, PART, msg, details, missing=missing, priority=1 if p["param"] == "AUC" else 0)
    t = ana.get("t3") or {}
    if t:
        add(rows, 8, [cid], cid, status(t, "t3_label", "t3_flags", True),
            f"Reported AUC/D high:low ratio {show(t.get('R'))}, CI {show(t.get('ci'))}. T3 {t['t3_label']}.",
            {"Dose pair": t.get("dose_pair"), "Flags": t.get("t3_flags"), "Design": t.get("method")},
            fig=ps.get("C2T3"), priority=3, missing=[t.get("sensitivity_reason")])


def comparison_questions(rows, drows, refs, pairs, cards, ivs):
    for d in drows:
        w = d.get("observed_window", {})
        p = d.get("t3p") or {}
        ids = d["dataset_ids"]
        state = max((status(d, "t3_label", "t3_flags", d.get("R_window") is not None),
                     status(p, "t3p_label", "t3p_flags", bool(p.get("t3p_times")))), key=ab._RANK.get)
        label = d.get("t3_label", "CANNOT_ASSESS")
        supplement = p.get("t3p_label", "CANNOT_ASSESS")
        message = (f"High:low AUC/D ratio {show(d.get('R_window'))} over {span([w['start_h'], w['end_h']])}, "
                   f"Cmax/D ratio {show(d.get('cmax_d_ratio'))}. " if "start_h" in w else "Common exposure window unavailable. ")
        message += f"T3 {label}, T3p {supplement}."
        explanatory = set(d.get("t3_flags", ())) & ab._HOLD or label == EXCLUDED
        tp_explanatory = set(p.get("t3p_flags", ())) & ab._HOLD or supplement == EXCLUDED
        qpanel = (d.get("C2T3") if explanatory else None) or (d.get("C3") if tp_explanatory else None) or d.get("C1")
        dose_table = ab._tbl("Individual dose groups on the common observed window", ["Dataset", "Dose (mg/kg)", "Tmax (h)",
                             "Cmax/D", "AUC/D", "Integration times (h)"],
                             [[r.get("dataset_id"), show(r.get("dose")), show(r.get("tmax")), show(r.get("cmax_d")),
                               show(r.get("aucW_d")), show(g)] for r, g in zip(d.get("rows", []), w.get("grids_h", []))])
        add(rows, 8, ids, ", ".join(ids), state, message,
            {"High:low comparison, low/high doses (mg/kg)": d.get("t3_primary_pair"), "Rule": w.get("method"),
             "Grids identical": w.get("same_grid"), "Shared endpoints/times (h)": w.get("common_times_h"),
             "Unverified comparison attributes": d.get("unverified_comparison_fields"),
             "Shared-grid sensitivity AUC/D ratio": w.get("shared_grid_R"), "T3 CI": d.get("ci"),
             "T3p tested times (h)": p.get("t3p_times"), "T3p log ratio CI": p.get("t3p_ln_ratio_ci"),
             "T3p Holm p": p.get("t3p_p_holm"), "T3 flags": d.get("t3_flags"), "T3p flags": p.get("t3p_flags"),
             "Estimand": d.get("estimand"), "T3 method": d.get("method"),
             "T3 animal leave-one-out": d.get("removal") if d.get("t3_data_level") == "INDIVIDUAL" else None},
            fig=qpanel, table=dose_table, priority=4,
            missing=[d.get("t3_reason") or d.get("reason"), p.get("reason")])
    for r in refs:
        ev, iv = r["ev"], r["iv"]
        name = f"{condition(cards[ev])} / {iv}"
        t = r.get("t4") or {}
        witness = t.get("witness") or []
        match = [z for z in r.get("q", []) if z.get("records") in witness]
        ivsel = ((ivs.get(iv) or {}).get("metrics") or {}).get("terminal_selected") or {}
        ivtail = (f"IV apparent t½ {show(ivsel['thalf'])} h over {span([ivsel['start'], ivsel['end']])}. "
                  if ivsel else "")
        # trigger_text contains the two apparent half-lives even in a serialized result without IV point arrays.
        desc = r.get("trigger_text") or ivtail
        terminal = r.get("terminal_comparison") or {}
        windows = terminal.get("pairs", [])
        compare_status = terminal.get("comparison_status", UNKNOWN)
        reading = terminal.get("flip_flop_reading", "UNRESOLVED")
        if windows:
            ev_ends = sorted({p["ev_window_h"][-1] for p in windows})
            iv_ends = sorted({p["iv_window_h"][-1] for p in windows})
            grade_text = (f"{compare_status}: EV windows end at {show(ev_ends)} h, "
                          f"IV windows at {show(iv_ends)} h. Terminal reading {reading}. ")
        else:
            grade_text = f"Terminal reading {reading}. "
        win_table = ab._tbl("Apparent EV/IV half-life comparison by qualified window pair",
                            ["EV window", "IV window", "EV/IV t½ ratio", "Descriptive grade", "Same window"],
                            [[span(z["ev_window_h"]), span(z["iv_window_h"]), show(z["ratio"]), z["grade"],
                              show(z["same_window"])] for z in windows])
        t4_text = f"T4 {r.get('t4_label', 'CANNOT_ASSESS')}, maximum exact-pair margin {show(t.get('margin'))}."
        state = status(r, "t4_label", "t4_flags", bool(ivtail or r.get("mt4") is not None or
                       (desc and "apparent t½ —" not in desc)))
        message = (f"Terminal-window comparison: {desc}. " if desc else "Terminal-window comparison unavailable. ") + grade_text + t4_text
        add(rows, 6, [ev, iv], name, state, message,
            {"Terminal comparison basis": r.get("comparison_basis"), "IV window": ivtail or UNKNOWN,
             "Terminal interpretation": reading, "Terminal window comparability": compare_status,
             "Grades for comparable windows": terminal.get("comparable_grades"), "Window sensitive": terminal.get("window_sensitive"),
             "T4 conditional direction": t.get("conditional_direction"), "T4 flags": t.get("flags"),
             "T4 witness source records": witness, "Witness times EV / IV (h)": [[z["t"], z["reference_t"]] for z in match],
             "Witness Q and bounds": [[z["q"], z["lo"], z["hi"]] for z in match],
             "T4 timing sensitivity margin": (r.get("timing_sensitivity") or {}).get("margin"),
             "Leave-one-out outcomes": [z["outcome"] for z in t.get("removal", [])]},
            fig=r.get("D1"), table=win_table, priority=3, missing=t.get("missing_premises", []))
        w = r.get("observed_window") or {}
        value = r.get("f_window")
        shorter = r.get("shorter_window") or {}
        message = (f"Observed-window dose-normalized EV/IV AUC ratio {show(value)} over {span([w.get('start_h'), w.get('end_h')])}. "
                   if value is not None else "")
        message += f"{r.get('f_status', 'NOT_ESTIMABLE')}. Absolute F {r.get('absolute_f_status', 'NOT_ESTIMABLE')}."
        add(rows, 7, [ev, iv], name, YES if r.get("absolute_f") is not None else PART if value is not None else NO, message,
            {"EV / IV doses (mg/kg)": [r.get("dose_ev"), r.get("dose_iv")], "EV / IV areas": w.get("areas"),
             "EV / IV integration grids (h)": w.get("grids_h"), "EV / IV tail shares": [r.get("ev_tail_share"), r.get("iv_tail_share")],
             "Shorter common window": span([shorter["start_h"], shorter["end_h"]]) if "start_h" in shorter else None,
             "Shorter-window EV/IV ratio": shorter.get("normalized_exposure_ratio"),
             "IV early-area compensation": r.get("iv_early_area_direction"), "Absolute F": r.get("absolute_f"),
             "Caveats": r.get("f_caveats"), "Reason": r.get("f_reason")},
            fig=r.get("D2"), priority=3 if value is not None and value > 1 else 2,
            missing=[r.get("f_reason") if r.get("absolute_f") is None else None])
    for r in pairs:
        a, b = r["a"], r["b"]
        name = f"{condition(cards[a])} / {condition(cards[b])}"
        all_pairs = r.get("intervals", [])
        exact = r.get("exact_pairs", 0)
        lo, hi = r.get("c_lower"), r.get("c_upper")
        text = (f"Raw A/reference ratio: {len(all_pairs) - exact} near-time pairs and {exact} exact pairs. "
                f"T5 {r['t5_label']}.")
        if lo is not None and hi is not None:
            text += f" Timing sensitivity gives highest lower bound {show(lo)} and lowest upper bound {show(hi)}."
        t = r.get("t5") or {}
        scale_table = ab._tbl("Raw concentration pairs used for timing sensitivity",
                             ["Source rows (A / reference)", "A time (h)", "Ref time (h)", "Difference (h)", "Raw ratio", "Lower", "Upper"],
                             [[show(z["records"]), *[show(z.get(key)) for key in ("t", "reference_t", "delta_h", "c", "lo", "hi")]]
                              for z in all_pairs])
        add(rows, 9, [a,b], name, status(r, "t5_label", "t5_flags", bool(all_pairs)), text,
            {"Direction": r.get("ratio_direction"), "Differing attributes": r.get("differing_attributes"),
             "Exact-pair T5 margin": t.get("margin"), "Exact-pair witness rows": t.get("witness"),
             "Timing sensitivity margin": (r.get("timing_sensitivity") or {}).get("margin"),
             "Rate-only check": r.get("rate_only_label"), "Rate-only basis": r.get("rate_only_reason")},
            fig=r.get("E2") or r.get("E1"), table=scale_table, missing=t.get("missing_premises", []))


def absent(n, c, parameter, no_curve=False):
    if not c.get("tests_allowed") and not parameter:
        return NO, "Outside the central EV analysis: " + show(c.get("gates")) + "."
    if parameter:
        reason = {2: "Reported Tmax unavailable.", 6: "Comparable reported terminal half-life unavailable.",
                  7: "Source-reported F unavailable.", 8: "Comparable exposure parameters and dose assignments unavailable."}.get(n)
        return NO, reason or "Reported parameters only; requires time-resolved concentration observations."
    if n == 7:
        return NO, "Absolute F NOT_ESTIMABLE; comparable IV exposure or reported F unavailable."
    if n == 8:
        return (NO, "Dose assignments or quantifiable profiles for comparison unavailable.") if no_curve or c.get("dose_mg_per_kg") is None else (NA, "No within-condition multi-dose comparison.")
    if n == 9:
        return (NO, "Timed concentration observations for a condition comparison unavailable.") if no_curve else (NA, "No comparable second condition.")
    return NO, "Usable observations for this question unavailable."


def question(n, entries, panels, all_ids, cards):
    rank = lambda e: (ab._RANK[e["state"]], e["priority"])
    chosen = max(entries, key=rank)
    # Gated data remain visible under the study card, with their withheld reason, without setting the answer status.
    scoped = [e for e in entries if not e.get("gated")]
    if scoped:
        chosen = max(scoped, key=rank)
    state = chosen["state"]
    sources = sorted({i for e in scoped for i in e["ids"]})
    all_sources = sorted({i for e in entries for i in e["ids"]})
    msg = chosen["name"] + " · " + chosen["result"]
    other = [e for e in scoped if e is not chosen]
    if other:
        # Show the highest-status interpretation only for its named condition, with other conditions alongside.
        groups = {}
        for e in other:
            groups.setdefault(e["state"], []).append(e["name"])
        basis = "Other conditions or readings: " + ". ".join(st + " — " + ", ".join(dict.fromkeys(names)) for st, names in groups.items()) + "."
    else:
        basis = ""
    if n == 3:
        scanned = [e for e in scoped if e["details"].get("Eligible T1 pairs")]
        if len(scanned) > 1:
            positives = sum(e["details"]["Positive T1 pairs"] for e in scanned)
            total = sum(e["details"]["Eligible T1 pairs"] for e in scanned)
            basis = f"Across {len(scanned)} separately scanned series: {positives} of {total} full-window T1 pairs had positive margins. " + basis
    if n in (6, 7):
        pairs = [e for e in other if len(e["ids"]) == 2]
        if pairs:
            basis = " ".join(e["name"] + " — " + e["result"] + (
                " " + e["details"]["Reason"] if e["state"] == NO and e["details"].get("Reason") else "") for e in pairs)
    level = ", ".join(dict.fromkeys(
        "source-reported parameters" if cards[i].get("data_form") == "REPORTED_PARAMETER" else
        "source-labelled points; cross-time animal identity unverified" if cards[i].get("record_level") == UNCERTAIN_ID else
        ("destructive " if cards[i].get("destructive_sampling") else "") + str(cards[i].get("record_level", UNKNOWN)).lower().replace("_", " ")
        for i in chosen["ids"] if i in cards))
    missing = list(dict.fromkeys(m for e in scoped for m in e["missing"]))
    if not missing and state in (NO, NA):
        missing = [chosen["result"]]
    primary = None
    allowed = {i for e in scoped for i in e["ids"]}
    views = [v for pid in PANELS[n] for v in panels.get(pid, []) if not v.get("gated") and set(v["ids"]) <= allowed]
    view = next((v for v in views if v["file"] == chosen["fig"]), None)
    if state not in (NO, NA):
        if view:
            primary = ab._prim(view["file"], [view["panel"]], n, msg, level)
        else:
            # A data row can isolate one source parameter even when the only panel combines several parameters.
            primary = ab._row(n, ["Condition / source", "Observed evidence"], [[chosen["name"], chosen["result"]]], msg, level)
        primary["lines"] = [f"Q{n} · {LABEL[n-1]}", msg, RULE[n][1], RULE[n][2]]
    evidence = []
    comparison_table = ab._tbl("Status of every condition or source value", ["Condition / source", "Status", "Finding"],
                               [[e["name"], e["state"], e["result"]] for e in entries])
    evidence.append(ab._part(RULE[n][1], [comparison_table], all_sources))
    for e in scoped:
        tables = []
        if e["details"]:
            tables.append(ab._tbl(e["name"], ["Evidence", "Value"], [[k, show(v)] for k, v in e["details"].items()]))
        if e["table"]:
            tables.append(e["table"])
        if tables:
            evidence.append(ab._part(e["name"] + " · " + e["result"], tables, e["ids"]))
    more = [v for v in views if primary is None or v["file"] != primary.get("file")]
    q = ab._q(n, state, msg, basis, level + ". " + RULE[n][2], missing, primary, more, evidence)
    q.update(label=LABEL[n-1], question=RULE[n][0], dataset_ids=sources, other_study_datasets=sorted(all_ids-set(sources)))
    return q


def boards(datasets, doses, references, conditions, parameters, ivs):
    data, params, _ = ab._by_study(datasets, parameters, ivs)
    out = []
    for study in dict.fromkeys([*data, *params]):
        ds, ps = data.get(study, []), params.get(study, [])
        cards = {d["card"]["dataset_id"]: d["card"] for d in [*ds, *ps]}
        own = set(cards)
        drows = [r for r in doses if set(r["dataset_ids"]) <= own]
        refs = [r for r in references if r["ev"] in own]
        pairs = [r for r in conditions if {r["a"], r["b"]} <= own]
        iv_by_id = {iv["card"]["dataset_id"]: iv for iv in ivs if any(r["iv"] == iv["card"]["dataset_id"] for r in refs)}
        cards.update({k: d["card"] for k, d in iv_by_id.items()})
        panels = ab._study_panels(ds, ps, drows, refs, pairs)
        rows = {n: [] for n in range(1, 10)}
        for d in ds:
            for s in d["series"]:
                curve_questions(rows, d, s)
            individuals(rows, d)
        for p in ps:
            reported(rows, p)
        comparison_questions(rows, drows, refs, pairs, cards, iv_by_id)
        for n, entries in rows.items():
            covered = {i for e in entries for i in e["ids"]}
            for d in [*ds, *ps]:
                c = d["card"]
                cid = c["dataset_id"]
                if cid in covered:
                    continue
                is_param = "params" in d
                no_curve = not any(s["metrics"].get("n_quantified", 0) for s in d.get("series", []))
                state, reason = absent(n, c, is_param, no_curve)
                if no_curve and not is_param:
                    reasons = list(dict.fromkeys(s["metrics"].get("not_assessable_reason") for s in d.get("series", [])))
                    reason += " " + ". ".join(r for r in reasons if r)
                add(rows, n, [cid], cid, state, reason, missing=[reason] if state == NO else [])
                entries[-1]["gated"] = not c.get("tests_allowed") and not is_param
        qs = [question(n, entries, panels, own, cards) for n, entries in rows.items()]
        species = " / ".join(sorted({cards[i]["species"] for i in own}))
        out.append({"study": study, "species": species, "species_group": ab.species_group(species), "datasets": sorted(own),
                    "questions": qs, "rows": {q["q"]: [q["status"], q["observed"], [v["panel"] for v in q["views"]]] for q in qs},
                    "evidence": {q["q"]: q["evidence"] for q in qs}, "status_codes": {q["q"]: q["status_code"] for q in qs}})
    return out


