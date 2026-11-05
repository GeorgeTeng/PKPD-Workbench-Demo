"""Single-profile evidence for absorption EDA r4.3, items 16–18, 20 and 21."""

from __future__ import annotations

import itertools
import math
import re

import numpy as np


PROJECT_TOL = 0.05
WIDENING_FACTOR = 2.0  # Frozen sensitivity: double the distance to each concentration limit.
EARLY_SLOPE_EPS = 1e-8  # h^-1, numerical threshold for a descriptive slope ratio.


def numeric(v):
    if isinstance(v, bool):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def sourced(value):
    return value not in (None, "", "not reported", "UNKNOWN", "NOT_FOUND")


def confirmed(v):
    return v is True or str(v).upper() in {"YES", "VERIFIED", "CONFIRMED"}


def source_status(status):
    s = str(status or "NOT_REPORTED").upper()
    if s in {"<LLOQ", "BLQ", "BELOW_LLOQ", "BELOW_QUANTIFICATION_LIMIT"}:
        return "BLQ"
    if s in {">ULOQ", "ABOVE_ULOQ", "ABOVE_QUANTIFICATION_LIMIT"}:
        return "ABOVE_ULOQ"
    return s


def sampling_design(meta, text):
    destructive = confirmed(meta.get("destructive_sampling")) or bool(re.search(
        r"destructive sampling|terminal sampl|each time point is a different group|different animals at each time", text, re.I))
    verified = confirmed(meta.get("serial_identity_verified", meta.get("identity_verified"))) or bool(re.search(
        r"verified serial identit|cross-time (?:animal )?identity (?:is )?verified|same identified animal(?:s)? (?:at|across) (?:all|each) time", text, re.I))
    denied = bool(re.search(r"(?:identity|linkage) (?:is |are )?(?:not verified|unverified|not established)|do not verify cross-time", text, re.I))
    return bool(verified and not destructive and not denied), bool(destructive)


def pixel_calibration(notes):
    """Only interpret explicit time and log10 axes *and* a declared pixel tolerance."""
    tol = re.search(r"(?:\+/-|±)\s*([0-9.]+)[ -]*pixels?", notes, re.I)
    axes = re.search(r"x=([\d.]+),([\d.]+)\s*->\s*([\d.]+),([\d.]+)\s*(h|min);.*?y=([\d.]+),([\d.]+)\s*->\s*10\^(-?\d+),10\^(-?\d+)", notes, re.I)
    if not axes:
        axes = re.search(r"x=([\d.]+) to ([\d.]+) pixels is ([\d.]+) to ([\d.]+) (h|min); y=([\d.]+) to ([\d.]+) pixels is log10 concentration=(-?\d+) to (-?\d+)", notes, re.I)
    if not axes or not tol:
        return {}
    x0, x1, a, b, unit, y0, y1, l0, l1 = axes.groups()
    if float(x0) == float(x1) or float(y0) == float(y1):
        return {}
    pixels = float(tol[1])
    time_error = pixels * abs((float(b) - float(a)) / (float(x1) - float(x0))) / (60 if unit.lower() == "min" else 1)
    return {"time_error_h": time_error, "concentration_factor": 10 ** (pixels * abs((float(l1) - float(l0)) / (float(y1) - float(y0)))),
            "pixels": pixels}


def source_point(row, column, cols, meta, t, c, status, calibration):
    cid = column["id"]
    def read(key, default=None):
        for source in (row, column, meta):
            v = source.get(key)
            if isinstance(v, dict):
                v = v.get(cid)
            if v is not None:
                return v
        return default

    outcome = status
    if row.get("qc_status") not in (None, "TECHNICALLY_RETAINED"):
        # Prepared records marked for review cannot enter a calculation. Keep the original status.
        outcome = "QC_WITHHELD"
    raw = row.get("source_raw_values", {}).get(cid, row.get(cid))
    p = {"t": t, "c": c, "status": outcome, "source_status": status, "raw_value": raw,
         "record_id": row.get("record_id"), "source_cell": row.get("source_cells", {}).get(cid),
         "qc_status": row.get("qc_status"), "lloq": numeric(read("lloq")), "uloq": numeric(read("uloq")),
         "sample_phase": read("sample_phase"), "analytical_error": read("analytical_error"),
         "digitization_bounds": calibration or read("digitization_bounds"), "bound_source": read("bound_source"),
         "bounds_basis": read("bounds_basis"), "bounds_error_level": numeric(read("bounds_error_level")),
         "widened_lo": numeric(read("widened_lo")), "widened_hi": numeric(read("widened_hi")),
         "widening_source": read("widening_source"), "actual_time_verified": read("actual_time_verified"),
         "lo": numeric(read("lo", read("concentration_lower"))), "hi": numeric(read("hi", read("concentration_upper"))),
         "t_lo": numeric(read("t_lo", read("time_lower_h"))), "t_hi": numeric(read("t_hi", read("time_upper_h")))}
    if status == "MEASURED_ZERO" and c is None:
        p["c"] = 0.0
    if p["lloq"] is None and status == "BLQ":
        threshold = re.fullmatch(r"\s*<\s*(\d+(?:\.\d+)?)\s*", str(raw))
        if threshold:
            p["lloq"] = float(threshold[1])
    if p["uloq"] is None and status == "ABOVE_ULOQ":
        threshold = re.fullmatch(r"\s*>\s*(\d+(?:\.\d+)?)\s*", str(raw))
        if threshold:
            p["uloq"] = float(threshold[1])
    # Preserve secondary time definitions. A pixel-time alternative is never silently substituted.
    p["time_alternatives"] = {x["header"]: row[x["id"]] for x in cols if x.get("meaning") == "TIME" and x["id"] in row and x.get("header")}
    if calibration and p["t_lo"] is None and p["t_hi"] is None:
        pixel = next((numeric(v) for k, v in p["time_alternatives"].items() if "pixel" in k.lower()), t)
        if pixel is not None:
            p["t_lo"] = min(t, pixel - calibration["time_error_h"])
            p["t_hi"] = max(t, pixel + calibration["time_error_h"])
            p["time_basis"] = "PLOTTED_TIME_AND_AVAILABLE_NOMINAL_TIME_WITH_SOURCE_PIXEL_ALLOWANCE"
    return normalize(p)


def normalize(p, i=0):
    """Keep censoring as intervals; no invented upper bound for a zero or an unbounded BLQ."""
    p = dict(p)
    t, c = p["t"], numeric(p.get("c"))
    p["c"] = c
    p["record_id"] = p.get("record_id") or f"row_{i}"
    st = p["status"] = source_status(p.get("status"))
    time_declared = p.get("t_lo") is not None or p.get("t_hi") is not None
    p["t_lo"], p["t_hi"] = (numeric(p.get("t_lo")), numeric(p.get("t_hi"))) if time_declared else (t, t)
    p.setdefault("time_basis", "SOURCE_INTERVAL" if time_declared else "AS_RECORDED")
    p["time_valid"] = p["t_lo"] is not None and p["t_hi"] is not None and p["t_lo"] <= t <= p["t_hi"]
    lo, hi = numeric(p.get("lo")), numeric(p.get("hi"))
    basis, src = p.get("bounds_basis"), p.get("bound_source")
    if st == "BLQ":
        lim = numeric(p.get("lloq"))
        lo, hi = 0.0, (max(lim, hi) if hi is not None else lim) if lim is not None and lim > 0 else None
        src = src or ("source assay LLOQ" if hi is not None else "unknown LLOQ")
    elif st == "ABOVE_ULOQ":
        lo, hi = numeric(p.get("uloq")), None
        src = src or "source ULOQ; upper bound open"
    elif st == "MEASURED_ZERO" or (st == "QUANTIFIED" and c == 0):
        lo = 0.0
        src = src or "zero has no reported upper uncertainty bound"
    elif st == "QUANTIFIED" and c is not None and c > 0:
        if lo is None and hi is None:
            digitization = p.get("digitization_bounds") or {}
            factor = digitization.get("concentration_factor") if isinstance(digitization, dict) else None
            if factor is not None and factor >= 1:
                lo, hi = c / factor, c * factor
                src, basis = "source pixel reading tolerance", "DIGITIZATION_ONLY"
            else:
                lo, hi = c * (1 - PROJECT_TOL), c * (1 + PROJECT_TOL)
                src, basis = "project ±5% sensitivity", "PROJECT_SET"
        elif lo is None or hi is None or not lo <= c <= hi:
            lo, hi, basis = None, None, "INVALID_SOURCE_INTERVAL"
    else:
        lo, hi = None, None
    p.update(lo=lo, hi=hi, bound_source=src or "source not established", bounds_basis=basis or "UNVERIFIED")
    return p


def mark_duplicates(points):
    """Unresolved shared times cannot act as independent points. Keep every source row."""
    for _, items in itertools.groupby(points, key=lambda p: p["t"]):
        group = list(items)
        if len(group) > 1:
            for p in group:
                p.setdefault("source_status", p["status"])
                p["status"] = "DUPLICATE_CONFLICT"


def enrich_card(card, meta, text):
    fields = ("analyte", "exposure_basis", "study_design", "design", "iv_mode", "infusion_duration_h",
              "administration_start", "administration_end", "administration_duration_h", "administration_rate",
              "formulation", "feeding", "vehicle", "co_treatment", "condition", "iv_reference_compound",
              "baseline_behavior", "assay_specificity", "time_origin", "time_origin_verified", "first_dose",
              "prior_dose", "washout_half_lives", "dosing_history_verified", "zero_state_verified",
              "systemic_input_from_dose_verified", "t1_premises_verified", "t2_premises_verified",
              "comparable_group_composition", "hard_lag_concave_rise_supported", "bounds_procedure",
              "lloq_consistent", "population_uncertainty_covered", "inhaled_dose_basis", "gi_contribution_bounded",
              "baseline_concentration", "near_zero_concentration", "interval_since_previous_dose_h",
              "shared_one_compartment_supported", "shared_one_compartment_evidence", "common_population_supported",
              "common_population_evidence", "shared_linear_clearance_supported", "clearance_evidence",
              "superposition_premises_supported", "superposition_premises_evidence", "superposition_evidence",
              "actual_time_verified", "baseline_corrected", "baseline_correction_evidence", "analyte_evidence",
              "bounds_evidence", "identity_evidence", "t1_premises_evidence", "t2_premises_evidence",
              "source_sampling_design", "prespecified_window_h", "prespecified_dose_pair", "sampling_design",
              "period_by_subject", "subject_by_series", "carryover_controlled")
    for key in fields:
        if key in meta:
            card[key] = meta[key]
    # Compound, analyte, and exogenous origin have different meanings; keep absent fields unknown.
    card.setdefault("analyte", "NOT_FOUND")
    card.setdefault("assay_specificity", "UNKNOWN")
    card.setdefault("baseline_behavior", "UNKNOWN")
    if not sourced(card.get("iv_mode")) and card["route_detail"] in {"IV_BOLUS", "IV_INFUSION"}:
        card["iv_mode"] = card["route_detail"]
    if not sourced(card.get("iv_mode")) and card["route_class"] == "IV":
        if re.search(r"\bIV bolus\b|intravenous bolus", card["dosing_regimen"], re.I):
            card["iv_mode"] = "IV_BOLUS"
    duration = re.search(r"\bover\s+(\d+(?:\.\d+)?)\s*(min(?:ute)?s?|h(?:ours?)?)\b", card["dosing_regimen"], re.I)
    if duration and "administration_duration_h" not in card:
        card["administration_duration_h"] = float(duration[1]) / (60 if duration[2].lower().startswith("m") else 1)
    if card.get("iv_mode") == "IV_INFUSION" and "administration_duration_h" in card:
        card.setdefault("infusion_duration_h", card["administration_duration_h"])
    start, end = numeric(card.get("administration_start")), numeric(card.get("administration_end"))
    card["known_finite_administration"] = bool((numeric(card.get("administration_duration_h")) or 0) > 0 or end is not None and end > (start or 0))
    card["washout_supported"] = bool((numeric(card.get("washout_half_lives")) or 0) >= 5 and confirmed(card.get("dosing_history_verified")))
    card["endogenous_review_required"] = card["origin"] in {"ENDOGENOUS", "MIXED"} and card["assay_specificity"] != "EXOGENOUS_SPECIFIC"
    card["time_origin_conflict"] = bool(card.get("time_origin") in {"UNKNOWN", "UNCLEAR", "OTHER_DOSE"} or
        re.search(r"time origin.{0,53}(?:not established|unspecified|unknown)", text, re.I))
    if "time_origin_verified" not in card:
        card["time_origin_verified"] = bool(re.search(r"\bat time 0\b", card["dosing_regimen"], re.I) and not card["time_origin_conflict"])
    if card.get("destructive_sampling"):
        card.setdefault("study_design", "DESTRUCTIVE")
    if card.get("route_detail") in {"INTRATRACHEAL", "INHALED_NOSE_ONLY", "INHALED_WHOLE_BODY"}:
        card["pulmonary_and_gi_unresolved"] = not confirmed(card.get("gi_contribution_bounded"))


def baseline(points, card):
    pre = [p for p in points if p["t"] <= 0 and p.get("sample_phase") != "POSTDOSE"]
    pre = max(pre, key=lambda p: p["t"]) if pre else None
    first = confirmed(card.get("first_dose", card.get("single_dose"))) and not confirmed(card.get("prior_dose"))
    specific = card.get("origin") == "EXOGENOUS" or card.get("assay_specificity") == "EXOGENOUS_SPECIFIC"
    washout = card.get("washout_supported", False)
    positive = pre is not None and pre["status"] == "QUANTIFIED" and (pre.get("c") or 0) > 0
    measured_zero = pre is not None and pre["status"] == "MEASURED_ZERO"
    blq = pre is not None and pre["status"] == "BLQ"
    design = bool(card.get("route_class") == "EV" and first and specific and (pre is None or pre["status"] in {"NOT_SAMPLED", "EMPTY_SLOT", "NOT_REPORTED"}))
    if card.get("endogenous_review_required"):
        status = card["origin"]
    elif positive:
        status = "UNEXPLAINED" if first else "RESIDUAL_FROM_PRIOR_DOSE"
    elif measured_zero or blq:
        status = "ZERO_OR_BLQ"
    elif washout:
        status = "WASHOUT_ZERO"
    elif design:
        status = "DESIGN_ZERO"
    elif confirmed(card.get("prior_dose")) or str(card.get("occasion", "")).startswith("REPEATED_DOSE_DAY"):
        status = "RESIDUAL_FROM_PRIOR_DOSE"
    else:
        status = "NOT_ASSESSABLE"
    basis = "MEASURED" if positive or measured_zero or blq else status if status in {"DESIGN_ZERO", "WASHOUT_ZERO"} else "UNKNOWN"
    zero = bool(specific and not positive and not card.get("time_origin_conflict") and (design or
        (first and (measured_zero or blq)) or confirmed(card.get("zero_state_verified"))))
    anchor = bool(card.get("route_class") == "EV" and not card.get("time_origin_conflict") and
        (design or (washout and not positive) or (measured_zero and (pre["t"] == 0 or zero))))
    return {"baseline_status": status, "dose_time_basis": basis, "zero_state_supported": zero,
            "zero_anchor_allowed": anchor, "predose_record_id": pre["record_id"] if pre else None,
            "predose_value": pre.get("c") if pre else None, "predose_time_h": pre["t"] if pre else None,
            "predose_status": pre["status"] if pre else None, "predose_upper": pre.get("hi") if pre else None}


def scan(points, test):
    """Exhaustive pair/triple search over the remaining observations and their timing intervals."""
    best, count, positive = None, 0, 0
    for combo in itertools.combinations(points, 2 if test == "T1" else 3):
        if combo[0]["t_lo"] <= 0 or any(b["t_lo"] <= a["t_hi"] for a, b in zip(combo, combo[1:])):
            continue
        if test == "T1":
            a, b = combo
            if a["hi"] is None or b["lo"] is None:
                continue
            margin = b["lo"] / b["t_hi"] - a["hi"] / a["t_lo"]
            extra = {}
        else:
            a, b, c = combo
            if a["lo"] is None or b["hi"] is None or c["lo"] is None:
                continue
            drop, rise = a["lo"] - b["hi"], c["lo"] - b["hi"]
            margin = min(drop, rise)
            extra = {"m_drop": drop, "m_rise": rise}
        positive += int(margin > 0)
        count += 1
        if best is None or margin > best["margin"]:
            best = {"margin": margin, "record_ids": [p["record_id"] for p in combo],
                    "times_h": [p["t"] for p in combo], "observations": [
                        {k: p.get(k) for k in ("record_id", "t", "t_lo", "t_hi", "c", "lo", "hi", "bound_source", "status")} for p in combo], **extra}
    return {"count": count, "positive_count": positive, "best": best}


def _wider(p):
    # Preserve one-sided status. A true BLQ is never converted to a point at zero.
    q = dict(p)
    source_lo, source_hi = numeric(p.get("widened_lo")), numeric(p.get("widened_hi"))
    if (sourced(p.get("widening_source")) and source_lo is not None and source_hi is not None and
            p["lo"] is not None and p["hi"] is not None and 0 <= source_lo <= p["lo"] <= p["hi"] <= source_hi):
        q["lo"], q["hi"] = source_lo, source_hi
        return q
    if p["c"] is None or p["status"] == "MEASURED_ZERO":
        if p["hi"] is not None:
            q["hi"] = p["hi"] * WIDENING_FACTOR
        if p["status"] == "ABOVE_ULOQ" and p["lo"] is not None:
            q["lo"] = p["lo"] / WIDENING_FACTOR
    else:
        for key in ("lo", "hi"):
            if p[key] is not None:
                q[key] = max(0.0, p["c"] + WIDENING_FACTOR * (p[key] - p["c"]))
    return q


def search_result(points, test, card, level, base):
    sample = [p for p in points if p["time_valid"] and p["t_lo"] > 0 and p["status"] in {"QUANTIFIED", "MEASURED_ZERO", "BLQ", "ABOVE_ULOQ"}]
    context_block = []
    observations = [p for p in points if p["t"] > 0 and p["status"] in {"QUANTIFIED", "MEASURED_ZERO", "BLQ", "ABOVE_ULOQ"}]
    if observations and all(p["status"] == "BLQ" for p in observations):
        context_block.append("all postdose samples BLQ")
    if card.get("route_class") != "EV" or card.get("matrix_category") != "PLASMA_SERUM_BLOOD":
        context_block.append("route or observation matrix outside EV central-signal scope")
    if card.get("route_detail") in (None, "", "NOT_FOUND", "ROUTE_UNKNOWN"):
        context_block.append("route detail unknown")
    if card.get("endogenous_review_required") or card.get("time_origin") == "OTHER_DOSE":
        context_block.append("unresolved endogenous signal or time origin belongs to another dose")
    if card.get("single_dose") is False and not card.get("washout_supported"):
        context_block.append("single dose or sufficient washout unverified")
    if test == "T1" and card.get("known_finite_administration") and not confirmed(card.get("systemic_input_from_dose_verified")):
        context_block.append("finite administration without independent systemic-input support from dose time")
    # A group/label shape may be read descriptively. It never supplies a within-animal T2.
    descriptive = test == "T2" and (level != "INDIVIDUAL" or card.get("destructive_sampling") or card.get("identity_verified") != "yes")
    actual = [] if context_block else sample
    result = scan(actual, test)
    best = result["best"]
    widened = scan([_wider(p) for p in actual], test)
    removals = []
    for i, p in enumerate(actual):
        sub = scan(actual[:i] + actual[i + 1:], test)
        winner = sub["best"]
        state = "NOT_ASSESSABLE" if winner is None else ("CONTRADICTION_REMAINS" if winner["margin"] > 0 else "ASSESSABLE_WITHOUT_CONTRADICTION")
        removals.append({"removed_record_id": p["record_id"], "removed_time_h": p["t"], "outcome": state,
                         "eligible_count": sub["count"], "margin": winner["margin"] if winner else None,
                         "witness_ids": winner["record_ids"] if winner else []})
    missing = list(context_block)
    if best is None:
        missing.append("too few definitely ordered observations with the required concentration bounds")
    if descriptive:
        missing.append("within-animal longitudinal identity unavailable")
    if not base["zero_state_supported"]:
        missing.append("zero initial amounts and absence of relevant carryover unverified")
    if not confirmed(card.get("time_origin_verified")) or card.get("time_origin_conflict"):
        missing.append("dose-relative time origin unverified")
    if not confirmed(card.get(test.lower() + "_premises_verified")):
        missing.append("complete input/disposition/central-signal premises undocumented")
    if level == "GROUP_MEAN" and (not confirmed(card.get("comparable_group_composition")) or not confirmed(card.get("population_uncertainty_covered"))):
        missing.append("group composition and joint uncertainty of the means unverified")
    if level == "INDIVIDUAL_IDENTITY_UNVERIFIED":
        missing.append("serial animal identity unverified")
    accepted = {"DETERMINISTIC", "SIMULTANEOUS", "CALIBRATED_GLOBAL"}
    coverage = all(p["bounds_basis"] in accepted and sourced(p["bound_source"]) and p["bound_source"] != "source not established"
                   and (p["bounds_basis"] == "DETERMINISTIC" or (0 < (numeric(p.get("bounds_error_level")) or 0) < 1 and sourced(card.get("bounds_procedure"))))
                   for p in actual)
    if not coverage:
        missing.append("joint bounds covering all relevant observation uncertainties unavailable")
    contradiction = best is not None and best["margin"] > 0
    flags = []
    if missing and best is not None:
        flags.append("SENSITIVITY_ONLY")
    if descriptive:
        flags.append("T2_NOT_APPLICABLE_TO_GROUP_MEANS" if level == "GROUP_MEAN" else "SERIAL_IDENTITY_NOT_VERIFIED")
    if contradiction:
        if any(r["outcome"] == "ASSESSABLE_WITHOUT_CONTRADICTION" for r in removals):
            flags.append("SINGLE_POINT_SUPPORT")
        if any(r["outcome"] == "NOT_ASSESSABLE" for r in removals):
            flags.append("INDEPENDENT_SUPPORT_NOT_ASSESSABLE")
        if widened["best"] is None or widened["best"]["margin"] <= 0:
            flags.append("BORDERLINE")
    if missing:
        label = "CANNOT_ASSESS"
    elif contradiction and not flags:
        label = "EXCLUDED_UNDER_STATED_ASSUMPTIONS"
    else:
        label = "NOT_EXCLUDED"
    unit = ("SOURCE_LABEL_ONLY_CONDITIONAL_ON_SERIAL_IDENTITY" if level == "INDIVIDUAL_IDENTITY_UNVERIFIED" else level)
    return {"formal_status": label, "flags": flags, "missing_premises": missing, "eligible_count": result["count"],
            "positive_count": result["positive_count"], "numeric_contradiction": contradiction if best is not None else None,
            "analysis_unit": unit,
            "basis": "DESCRIPTIVE_SERIES_ONLY" if descriptive else "NECESSARY_CONDITION", "test_executed": bool(best and not descriptive),
            "window_rule": "all eligible definitely ordered positive source times of this dose",
            "window_h": [actual[0]["t"], actual[-1]["t"]] if actual else None, "best": best, "removals": removals,
            "widening": {"fallback_factor": WIDENING_FACTOR, "concentration_only": True, "best": widened["best"],
                         "rule": "prespecified wider source intervals when valid, otherwise double the main concentration-bound distances"},
            "bounds_procedure": card.get("bounds_procedure"), "bounds_error_levels": sorted({
                p["bounds_error_level"] for p in actual if p.get("bounds_error_level") is not None})}


def prepared(points):
    pts = sorted((normalize(p, i) for i, p in enumerate(points)), key=lambda p: p["t"])
    mark_duplicates(pts)
    return pts


def t2_result(points, card=None, level=None):
    """Group/identity-unknown series have descriptive margins only; the formal T2 is withheld."""
    card = card or {}
    level = level or card.get("record_level", "UNKNOWN")
    pts = prepared(points)
    r = search_result(pts, "T2", card, level, baseline(pts, card))
    best = r["best"]
    margin = best["margin"] if best else None
    valley = best["times_h"] if best and margin > 0 else None
    quant = [p for p in pts if p["t"] > 0 and p["status"] == "QUANTIFIED" and (p["c"] or 0) > 0]
    times = [p["t"] for p in quant]
    # Indices used in quant-only plot overlays require every witness to be quantified.
    idx = [times.index(t) for t in valley] if valley and all(t in times for t in valley) else None
    middle = best["observations"][1] if best else {}
    near_zero = numeric(card.get("near_zero_concentration")) or 0
    ratio_ok = middle.get("status") == "QUANTIFIED" and (middle.get("lo") or 0) > near_zero and (middle.get("hi") or 0) > near_zero
    return {**r, "t2_margin": margin, "m_drop": best["m_drop"] if best else None, "m_rise": best["m_rise"] if best else None,
            "relative": margin / middle["hi"] if ratio_ok else None, "valley": valley, "valley_idx": idx,
            "robust": all(x["outcome"] == "CONTRADICTION_REMAINS" for x in r["removals"]) if valley else None,
            "T2_NUMERIC_CONTRADICTION": r["numeric_contradiction"] if r["test_executed"] else None,
            "EXCLUSION_APPLIED": r["formal_status"] == "EXCLUDED_UNDER_STATED_ASSUMPTIONS",
            "_t": times, "_c": [p["c"] for p in quant]}


def terminal(points, q, imax, min_span):
    """Never skip a censored, missing or duplicate time within an otherwise eligible suffix."""
    tail = []
    for p in reversed(points):
        if p["t"] > q[-1]["t"]:
            continue
        if p["t"] <= q[imax]["t"] or p["status"] != "QUANTIFIED" or not p["time_valid"] or (p["c"] or 0) <= 0:
            break
        if tail and p["t_hi"] >= tail[-1]["t_lo"]:
            break
        tail.append(p)
    tail.reverse()
    wins = []
    for i in range(len(tail) - 2):
        window = tail[i:]
        t = np.asarray([p["t"] for p in window])
        y = np.log([p["c"] for p in window])
        b, intercept = np.polyfit(t, y, 1)
        ss = np.sum((y - y.mean()) ** 2)
        r2 = 1 - np.sum((y - (intercept + b * t)) ** 2) / ss if ss > 0 else None
        adj = 1 - (1 - r2) * (len(y) - 1) / (len(y) - 2) if r2 is not None else None
        th = math.log(2) / -b if b < 0 and ss > 0 else None
        span = (t[-1] - t[0]) / th if th else None
        wins.append({"start": float(t[0]), "end": float(t[-1]), "n": len(t), "slope": float(b), "intercept": float(intercept),
                     "lambda_z": float(-b) if th else None, "thalf": float(th) if th else None, "adjR2": float(adj) if adj is not None else None,
                     "span_ratio": float(span) if span is not None else None, "qualified": bool(span is not None and span >= min_span),
                     "record_ids": [p["record_id"] for p in window]})
    qualified = [w for w in wins if w["qualified"] and w["adjR2"] is not None]
    if not qualified:
        return wins, None
    best = max(w["adjR2"] for w in qualified)
    return wins, max((w for w in qualified if w["adjR2"] >= best - 0.0001), key=lambda w: w["n"])


def split_slopes(post):
    if len(post) < 3:
        return None
    n = len(post)
    half = (n + 1) // 2
    slices = (post[:half], post[n - half:])
    slopes = []
    for part in slices:
        if len(part) < 2 or any(not p["time_valid"] for p in part) or any(a["t_hi"] >= b["t_lo"] for a, b in zip(part, part[1:])):
            slopes.append(None)
        else:
            slopes.append(float(np.polyfit([p["t"] for p in part], np.log([p["c"] for p in part]), 1)[0]))
    early, late = slopes
    ratio = late / early if early is not None and late is not None and early < -EARLY_SLOPE_EPS and late < 0 else None
    cls = "NOT_ASSESSABLE" if ratio is None else "DECLINE_STEEPENS" if ratio >= 1.25 else "DECLINE_FLATTENS" if ratio <= 0.8 else "NEITHER"
    return {"early_slope": early, "late_slope": late, "ratio": ratio, "class": cls, "near_zero_early_slope_per_h": EARLY_SLOPE_EPS,
            "early_t": [post[0]["t"], post[half - 1]["t"]], "late_t": [post[n - half]["t"], post[-1]["t"]]}


def area(points, base, integrate, withhold=None):
    observed = [p for p in points if p["t"] >= 0 and p["status"] in {"QUANTIFIED", "MEASURED_ZERO"}
                and p["c"] is not None and p["c"] >= 0 and (p["t"] != 0 or p["status"] == "MEASURED_ZERO" or p["c"] > 0)]
    if base["zero_anchor_allowed"] and (not observed or observed[0]["t"] > 0):
        observed.insert(0, {"t": 0.0, "c": 0.0, "record_id": base["dose_time_basis"], "time_valid": True, "t_lo": 0.0, "t_hi": 0.0})
    start, end = (observed[0]["t"], observed[-1]["t"]) if observed else (None, None)
    inside = [p for p in points if start is not None and start <= p["t"] <= end and p["status"] not in {"QUANTIFIED", "MEASURED_ZERO"}]
    blocked = [p for p in inside if p["status"] in {"BLQ", "ABOVE_ULOQ", "DUPLICATE_CONFLICT", "QC_WITHHELD", "CENSORED"}]
    invalid_zero = [p for p in points if start is not None and start <= p["t"] <= end and p["status"] == "QUANTIFIED" and p["c"] == 0]
    # A source numeric zero with no measured-zero classification cannot anchor integration.
    if invalid_zero:
        blocked += invalid_zero
    ordered = all(p["time_valid"] for p in observed) and all(a["t_hi"] < b["t_lo"] for a, b in zip(observed, observed[1:]))
    value = float(integrate([p["t"] for p in observed], [p["c"] for p in observed])) if not withhold and len(observed) >= 2 and not blocked and ordered else None
    return {"auc_observed": value, "auc_0_tlast": value if start == 0 else None,
            "auc_window_start_h": start, "auc_window_end_h": end, "auc_grid_h": [p["t"] for p in observed],
            "auc_method": "linear-up/log-down; valid zero endpoints linear", "auc_record_ids": [p["record_id"] for p in observed],
            "auc_status": withhold or (("WITHHELD_CENSORED_OR_CONFLICTING_WINDOW" if blocked else "WITHHELD_TIMING_OR_TOO_FEW_POINTS") if value is None
                          else "OBSERVED_FROM_DOSE_TIME" if start == 0 else "PARTIAL_OBSERVED_WINDOW"),
            "auc_gaps": [{"record_id": p["record_id"], "t": p["t"], "status": p["status"]} for p in inside + invalid_zero],
            "leading_censored_ids": [p["record_id"] for p in points if start is not None and 0 <= p["t"] < start and p["status"] == "BLQ"],
            "terminal_censored_ids": [p["record_id"] for p in points if end is not None and p["t"] > end and p["status"] == "BLQ"]}


def metrics(points, level, card, integrate, min_span):
    pts = prepared(points)
    base = baseline(pts, card)
    q = [p for p in pts if p["t"] > 0 and p["status"] == "QUANTIFIED" and (p["c"] or 0) > 0]
    blq = [p for p in pts if p["t"] > 0 and p["status"] == "BLQ"]
    over = [p for p in pts if p["t"] > 0 and p["status"] == "ABOVE_ULOQ"]
    t1 = search_result(pts, "T1", card, level, base)
    best = t1["best"]
    exact = [b["c"] / b["t"] - a["c"] / a["t"] for a, b in itertools.combinations(q, 2)
             if a["time_valid"] and b["time_valid"] and a["t_lo"] > 0 and a["t_hi"] < b["t_lo"]]
    t1_points = [{k: p.get(k) for k in ("t", "c", "lo", "hi", "t_lo", "t_hi", "status", "bound_source", "record_id")}
                 for p in pts if p["time_valid"] and p["t_lo"] > 0 and (p["lo"] is not None or p["hi"] is not None)]
    noncentral = card.get("matrix_category") != "PLASMA_SERUM_BLOOD"
    withhold = "WITHHELD_NONCENTRAL_MATRIX" if noncentral else "WITHHELD_UNVERIFIED_SERIAL_IDENTITY" if level == "INDIVIDUAL_IDENTITY_UNVERIFIED" else None
    exposure = area(pts, base, integrate, withhold)
    result = {**base, **exposure, "n_quantified": len(q), "n_blq": len(blq), "n_above_uloq": len(over),
              "record_level": level, "t1": t1, "t1_label": t1["formal_status"], "t1_flags": t1["flags"],
              "mt1": best["margin"] if best else None, "t1_margin": best["margin"] if best else None,
              "mt1_exact": max(exact) if exact and t1["eligible_count"] else None, "mt1_witness": best["times_h"] if best else None,
              "t1_points": t1_points, "onset_status": "NOT_ASSESSABLE", "onset_reason": "no positive quantified postdose observation",
              "observation_interval_h": None, "first_sample_upper_bound_h": None, "conditional_hard_lag_lower_bound_h": None,
              "bound_assumptions": [], "tail_share": None, "terminal_selected": None, "terminal_windows": [],
              "terminal_status": "TERMINAL_SLOPE_NOT_ASSESSABLE", "terminal_span_min_half_lives": min_span,
              "terminal_adj_r2_tolerance": 0.0001, "split": None, "increments": [], "caveats": [],
              "auc_analysis_unit": level, "shape_analysis_unit": t1["analysis_unit"],
              "observation_scope": "NONCENTRAL_OBSERVED_VALUES_ONLY" if noncentral else "CENTRAL_MATRIX",
              "_t": [p["t"] for p in q], "_c": [p["c"] for p in q]}
    result["cmax_status"] = "LOWER_BOUND_ONLY" if over else "OBSERVED_QUANTIFIED" if q else "NOT_ASSESSABLE"
    result["cmax_lower_bound"] = max([p["lo"] for p in over if p["lo"] is not None] + [p["c"] for p in q], default=None) if over else None
    result["censored_peak_rows"] = [p["record_id"] for p in over]
    caveats = result["caveats"]
    if noncentral:
        caveats.append("NONCENTRAL_OBSERVED_VALUES_ONLY")
    if level == "GROUP_MEAN":
        caveats.append("GROUP_MEAN")
    if level == "INDIVIDUAL_IDENTITY_UNVERIFIED":
        caveats.append("SERIAL_IDENTITY_NOT_VERIFIED")
    if card.get("destructive_sampling"):
        caveats.append("DESTRUCTIVE_SAMPLING")
    if card.get("digitized"):
        caveats.append("DIGITIZED")
    if over:
        caveats.append("CMAX_ABOVE_ULOQ")
    if card.get("known_finite_administration"):
        caveats.append("KNOWN_INPUT_PERIOD")
    if any(p["status"] == "DUPLICATE_CONFLICT" for p in pts):
        caveats.append("CONFLICTING_DUPLICATE")
    if base["baseline_status"] == "UNEXPLAINED":
        caveats.append("UPSTREAM_ISSUE")
    if base["baseline_status"] == "NOT_ASSESSABLE":
        caveats.append("UNKNOWN_PREDOSE")
    if not confirmed(card.get("time_origin_verified")) or card.get("time_origin_conflict"):
        caveats.append("TIME_ORIGIN_UNCLEAR")
    if card.get("endogenous_review_required"):
        caveats.append("ENDOGENOUS_REVIEW_REQUIRED")
    if not q:
        result["not_assessable_reason"] = ("all postdose samples BLQ" if "all postdose samples BLQ" in t1["missing_premises"]
                                            else "no positive quantified postdose observation")
        return result
    first = q[0]
    imax = max(range(len(q)), key=lambda i: q[i]["c"])
    peak = q[imax]
    result.update(tmax=peak["t"], cmax=peak["c"], observed_quantified_cmax=peak["c"], observed_quantified_tmax_h=peak["t"],
                  tlast=q[-1]["t"], first_t=first["t"], first_frac_cmax=first["c"] / peak["c"], n_before_peak=imax,
                  rising_limb_n=imax + 1, rise_shape="NOT_ASSESSABLE", rise_shape_alt=None)
    if noncentral:
        reason = "observed concentrations in a noncentral matrix; central absorption calculations are withheld"
        result.update(not_assessable_reason=reason, onset_reason=reason, dips_described=None,
                      first_sample_h=next(p["t"] for p in pts if p["t"] > 0 and p["status"] in {"BLQ", "QUANTIFIED", "MEASURED_ZERO", "ABOVE_ULOQ"}),
                      t1_rising_subset={"best": None, "count": 0}, predose_to_cmax=None, baseline_size="NOT_APPLICABLE")
        return result
    if any(first["t"] < p["t"] < q[-1]["t"] for p in blq):
        caveats.append("INTERIOR_BLQ")
    if len({p.get("n") for p in q if p.get("n") is not None}) > 1:
        caveats.append("UNEQUAL_N_PER_TIME")
    positive_pre = (base.get("predose_value") or 0) > 0
    frac = base["predose_value"] / peak["c"] if base["predose_value"] is not None else None
    result["predose_to_cmax"] = frac
    result["baseline_size"] = ("RESIDUAL_BASELINE" if frac > 0.05 else "NEGLIGIBLE") if frac is not None and not over else "NOT_APPLICABLE"
    if base["predose_status"] == "BLQ" and (base.get("predose_upper") or 0) > .05 * peak["c"] and not over:
        result["baseline_size"] = "BLQ_ABOVE_5PCT_CMAX"
        caveats.append("BLQ_ABOVE_5PCT_CMAX")
    before = [p for p in pts if 0 < p["t"] < first["t"] and p["status"] in {"BLQ", "MEASURED_ZERO"}]
    early = before[-1] if before else None
    post_observations = [p for p in pts if p["t"] > 0 and p["status"] in {"BLQ", "QUANTIFIED", "MEASURED_ZERO", "ABOVE_ULOQ"}]
    result["first_sample_h"] = post_observations[0]["t"]
    if early:
        result["observation_interval_h"] = [early["t"], first["t"]]
    if post_observations[0]["t"] >= peak["t"] / 3:
        caveats.append("LATE_FIRST_SAMPLE")
    origin_ok = confirmed(card.get("time_origin_verified")) and not card.get("time_origin_conflict")
    onset_ok = (origin_ok and base["zero_state_supported"] and not positive_pre and not card.get("endogenous_review_required")
                and card.get("tests_allowed", False) and not card.get("known_finite_administration"))
    if not onset_ok:
        result["onset_reason"] = "dose-relative timing, justified drug-free baseline, and eligible administration are required"
    elif early is None and first["record_id"] == post_observations[0]["record_id"]:
        result.update(onset_status="ONSET_NOT_OBSERVED", first_sample_upper_bound_h=first["t_hi"],
                      onset_reason=f"first quantified observation at {first['t']:g} h; earlier onset unresolved")
    elif early:
        thresholds = {p.get("lloq") for p in blq}
        lloq_ok = early["status"] != "BLQ" or (len(thresholds) == 1 and None not in thresholds and card.get("lloq_consistent") is not False)
        special = scan([early, first], "T1") if early["time_valid"] and first["time_valid"] and lloq_ok and early.get("hi") is not None else {"best": None}
        pair = special["best"]
        result["onset_pair"] = pair
        if pair:
            result.update(onset_status="DELAYED_ONSET" if pair["margin"] > 0 else "ONSET_BELOW_LLOQ",
                          onset_reason=f"{early['status']} at {early['t']:g} h followed by quantified observation at {first['t']:g} h; conditional pair margin {pair['margin']:.5g}")
            if confirmed(card.get("hard_lag_concave_rise_supported")) and (first["lo"] or 0) > 0:
                ratio = early["hi"] / first["lo"]
                if 0 <= ratio < 1:
                    lower = (early["t_lo"] - ratio * first["t_hi"]) / (1 - ratio)
                    if lower > 0:
                        result.update(conditional_hard_lag_lower_bound_h=lower, bound_assumptions=[
                            "drug-free baseline", "hard lag followed by a concave rise over the stated interval",
                            "ordered sampling-time intervals and stated concentration bounds"])
        else:
            result["onset_reason"] = "onset pair lacks a comparable LLOQ, supported zero upper bound, or definite time order"
    else:
        result["onset_reason"] = "earlier samples have unresolved statuses"
    rise = q[:imax + 1]
    subset = scan([p for p in rise if p["time_valid"]], "T1") if t1["eligible_count"] else {"best": None, "count": 0}
    result["t1_rising_subset"] = subset
    if subset["best"] and subset["best"]["margin"] > 0:
        caveats.append("ONSET_NOT_CONCAVE")
    # Keep the raw consecutive changes even when a shape classification is withheld.
    for a, b in zip(rise, rise[1:]):
        if not (a["time_valid"] and b["time_valid"] and a["t_hi"] < b["t_lo"]):
            continue
        d = b["c"] - a["c"]
        interval = [b["lo"] - a["hi"], b["hi"] - a["lo"]] if all(p[k] is not None for p in (a, b) for k in ("lo", "hi")) else None
        duration = b["t"] - a["t"]
        gaps = [p["record_id"] for p in pts if a["t"] < p["t"] < b["t"]]
        rate_bounds = None
        if interval:
            candidates = [x / dt for x in interval for dt in (b["t_lo"] - a["t_hi"], b["t_hi"] - a["t_lo"])]
            rate_bounds = [min(candidates), max(candidates)]
        result["increments"].append({"t0": a["t"], "t1": b["t"], "dcdt": d / duration,
                                     "change_interval": interval, "rate_interval": rate_bounds,
                                     "record_ids": [a["record_id"], b["record_id"]], "intervening_records": gaps})
    if imax + 1 == 3:
        caveats.append("SPARSE_RISING_LIMB")
    flat = len(rise) >= 2 and all(p["lo"] is not None and p["hi"] is not None and p["lo"] <= first["hi"] and first["lo"] <= p["hi"]
                                  for p in rise) if first["lo"] is not None and first["hi"] is not None else False
    if flat:
        caveats.append("FLAT_TOP_WITHIN_TOLERANCE")
    if imax < 2 or flat:
        caveats.append("KA_NOT_IDENTIFIABLE")
    caveats.append("DISPOSITION_CONFOUNDED")
    if imax >= 2 and onset_ok and not over and len(result["increments"]) == imax and not any(x["intervening_records"] for x in result["increments"]):
        rates = [x["rate_interval"] for x in result["increments"]]
        shape = "UNCLEAR"
        if all(rates):
            separated_dip = any(b[1] < min(a[0], c[0]) for a, b, c in zip(rates, rates[1:], rates[2:]))
            separated_middle = any(r[0] > max(rates[0][1], rates[-1][1]) for r in rates[1:-1])
            if separated_dip:
                shape = "MULTIPHASE"
            elif separated_middle:
                shape = "SIGMOIDAL_DELAYED"
            elif rates[0][0] > 0 and rates[-1][1] < rates[0][0] / 2 and all(r[1] <= rates[0][0] for r in rates[1:]):
                shape = "FIRST_ORDER_LIKE"
            # A sustained rise needs an observed corner as well as mutually compatible positive rates.
            elif imax + 1 < len(q) and min(r[0] for r in rates) > 0 and max(r[0] for r in rates) <= min(r[1] for r in rates):
                after = q[imax + 1]
                if after["time_valid"] and peak["t_hi"] < after["t_lo"] and after["hi"] is not None and peak["lo"] > after["hi"]:
                    shape = "ZERO_ORDER_LIKE"
        result["rise_shape"] = shape
    serial_or_summary = level in {"INDIVIDUAL", "GROUP_MEAN"}
    wins, sel = terminal(pts, q, imax, min_span) if not over and serial_or_summary else ([], None)
    result.update(terminal_windows=wins, terminal_selected=sel, terminal_status="SELECTED" if sel else "TERMINAL_SLOPE_NOT_ASSESSABLE",
                  split=split_slopes(q[imax + 1:]) if not over and serial_or_summary else None)
    if positive_pre and (result["baseline_size"] == "RESIDUAL_BASELINE" or
                         base["predose_value"] > .05 * q[-1]["c"] or (sel and any(base["predose_value"] > .05 * p["c"] for p in q if p["t"] >= sel["start"]))):
        caveats.append("RESIDUAL_BASELINE")
    area_value = exposure["auc_observed"]
    if sel and area_value and exposure["auc_window_end_h"] == q[-1]["t"]:
        tail_area = q[-1]["c"] / sel["lambda_z"]
        result["tail_share"] = tail_area / (tail_area + area_value)
        result["tail_share_basis"] = {"window_start_h": exposure["auc_window_start_h"], "window_end_h": exposure["auc_window_end_h"],
                                      "terminal_suffix_record_ids": sel["record_ids"], "interpretation": "descriptive tail share relative to observed support"}
    result["dips_described"] = scan([p for p in q if p["time_valid"]], "T2")["positive_count"]
    return result
