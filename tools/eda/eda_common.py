"""Shared helpers for the three EDA modules and their runners.

* ``workspace()`` finds the project workspace independent of folder depth.
* ``design_of`` / ``board_design`` / ``board_id`` give every board one identity
  that is the same in absorption, distribution and elimination.
* ``hypothesis_v1`` builds the common hypothesis record.
* ``input_coverage`` lists which source tables each section's boards use.
* ``rules_entry`` / ``check_rules`` give the one rules version per section (rules/rules_manifest.json).
"""
import hashlib
import json
import math
import os
import re
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_MARKERS = ("data", "deliverables", "outputs")

_TIME_FACTORS = {alias: factor for factor, aliases in (
    (1.0, ("h", "hr", "hrs", "hour", "hours")), (1 / 60, ("min", "mins", "minute", "minutes")),
    (1 / 3600, ("s", "sec", "secs", "second", "seconds")), (24.0, ("d", "day", "days")))
    for alias in aliases}


def observation_time_h(record, column):
    for value, factor in ((record.get("time_h"), 1.0),
                          (record.get(column.get("id")), _TIME_FACTORS.get(str(column.get("unit")).strip().lower()))):
        if factor is None or isinstance(value, bool):
            continue
        try:
            result = float(value) * factor
        except (ValueError, TypeError):
            continue
        if math.isfinite(result):
            return result
    return None


_UNKNOWN_SUBJECT = {"", "unknown", "not_found", "not reported", "n/a", "none"}


def column_subject(column):
    """The source animal of one concentration column (``subject_id``), or None when not given."""
    value = column.get("subject_id")
    if isinstance(value, bool) or not isinstance(value, (int, str)) or str(value).strip().lower() in _UNKNOWN_SUBJECT:
        return None
    return str(value).strip()


def serial_identity_verified(entry):
    text = (entry.get("experimental_unit") or "").lower()
    meta = entry.get("metadata", {})
    flag = meta.get("serial_identity_verified")
    if re.search(r"\b(?:unverified|unknown|unavailable|not verified|not confirmed|not identified)\b", text):
        return False
    if flag is not None:
        return flag is True
    columns = [c for c in entry.get("columns", []) if c.get("meaning") == "CONCENTRATION"]
    keys = [(column_subject(c), str(c.get("occasion") or "").strip()) for c in columns]
    if keys and all(k[0] for k in keys) and len(set(keys)) == len(keys):
        return True
    subject = meta.get("subject_id")
    if isinstance(subject, (int, str)) and not isinstance(subject, bool) and str(subject).strip().lower() not in {
            "", "unknown", "not_found", "not reported", "n/a", "none"}:
        return True
    if re.search(r"\b(?:verified serial individual|one (?:concentration )?column per identified animal)\b", text):
        return True
    labels = [str(c.get("header") or "").strip() for c in entry.get("columns", []) if c.get("meaning") == "CONCENTRATION"]
    return bool(re.search(r"\bidentified individual animals\b", text) and labels and len(set(labels)) == len(labels)
                and all(re.fullmatch(r"[A-Za-z]+[-_ ]?\d+", label) for label in labels))


# R6: one limiting-flag list shared by the three modules. A check result that carries any of these flags is not a
# full answer (PARTLY_ANSWERABLE at most); the codes stay in the structured result and the audit detail.
LIMITING_FLAGS = frozenset({"SENSITIVITY_ONLY", "BORDERLINE", "SINGLE_POINT_SUPPORT", "LOO_NOT_ASSESSABLE",
                            "CONDITIONAL_ON_LABEL_IDENTITY", "CONDITIONAL_ON_FIXED_COHORT"})

# Rule decision R10 (2026-11-24): a formal result that stops at the premises or at the interval basis (CANNOT_ASSESS) carries only
# the reason for that step. Removal and widening outcomes of the sensitivity calculation belong to the sensitivity record.
SENSITIVITY_RECORD_FLAGS = frozenset({"SINGLE_POINT_SUPPORT", "LOO_NOT_ASSESSABLE", "BORDERLINE"})


# ---------------------------------------------------------------- M1 (2026-11-24): one IV window for Distribution and Absorption
# Both modules compute the post-distribution IV window from the same normalised samples (quantified, after the end of input, on the
# clock "time after the end of dosing"), the same precision basis and this one function, and write a record with the same name.

WIN_SPLIT_R, WIN_SPLIT_Z = 1.5, 2.0        # Distribution item 24 rule 3 (screen thresholds)
WIN_MIN_POINTS = 5
WIN_BORDERLINE_Z = 0.5
WIN_SIGMA_IND, WIN_SIGMA_GROUP_DEFAULT, WIN_DIGIT_TERM = 0.15, 0.158, 0.05
IV_WINDOW_NAME = "iv_post_distribution_window"


def win_slope(ts, ys):
    tb, yb = sum(ts) / len(ts), sum(ys) / len(ys)
    sxx = sum((t - tb) ** 2 for t in ts)
    return sum((t - tb) * (y - yb) for t, y in zip(ts, ys)) / sxx, sxx


def win_split_half(pts, sigma):
    """Split-half screen of a log-linear decline (Distribution item 24 rule 3 and r1.5 sections 2.2 and 2.5)."""
    n = len(pts)
    if n < WIN_MIN_POINTS:
        return {"curvature": "NOT_ASSESSABLE", "reason": "TOO_FEW_POINTS", "n": n}
    k = math.ceil(n / 2)
    early, late = pts[:k], pts[n - k:]
    se, sxe = win_slope([p["t"] for p in early], [math.log(p["c"]) for p in early])
    sl, sxl = win_slope([p["t"] for p in late], [math.log(p["c"]) for p in late])
    be, bl = -se, -sl
    out = {"n": n, "b_early": be, "b_late": bl, "early_times": [p["t"] for p in early], "late_times": [p["t"] for p in late]}
    if be <= 0 or bl <= 0:
        return out | {"curvature": "NOT_ASSESSABLE", "reason": "NON_DECLINING_HALF"}
    R = be / bl
    z = (be - bl) / (sigma * math.sqrt(1 / sxe + 1 / sxl))
    cur = ("FLATTENING" if (R >= WIN_SPLIT_R and z >= WIN_SPLIT_Z) else
           "STEEPENING" if (R <= 1 / WIN_SPLIT_R and z <= -WIN_SPLIT_Z) else "NONE_DETECTED")
    borderline = n % 2 == 1 and abs(abs(z) - WIN_SPLIT_Z) < WIN_BORDERLINE_Z
    detectable = 2 * sigma * math.sqrt(1 / sxe + 1 / sxl) <= (WIN_SPLIT_R - 1) * bl
    return out | {"curvature": cur, "R": R, "z": z, "reason": None, "borderline_shared_point": borderline,
                  "min_detectable_rate_difference": 2 * sigma * math.sqrt(1 / sxe + 1 / sxl), "power_ok": detectable}


EV_SPLIT_UP, EV_SPLIT_DOWN, EV_SPLIT_MIN_POINTS, EV_SPLIT_ZERO_Q = 1.25, 0.80, 4, 1.96


def ev_split_sigma(level):
    """The ln C noise used by the EV post-peak description: the project tier by record level only (individual 0.15, group mean
    0.158), so both sections compute the same value from the same samples whatever SD or n each parser recovered."""
    return WIN_SIGMA_GROUP_DEFAULT if level == "GROUP_MEAN" else WIN_SIGMA_IND


def ev_post_peak_split(pts, level):
    """L5 (2026-11-24): the extravascular post-peak shape description of Absorption A0.7, written once and reused by Distribution.
    `pts` are the quantified post-peak samples (c > 0) in time order. Halves of (n + 1) // 2 samples; ratio = late slope / early
    slope, 1.25 or more steepens, 0.80 or less flattens. The ratio is computed only when both halves decline and the early slope is
    distinguished from zero (|early slope| >= 1.96 standard errors, the error from the project ln C noise of the record level,
    ev_split_sigma). It is a description; no z gate on the ratio (the z threshold of Distribution's IV task does not apply here)."""
    sigma = ev_split_sigma(level)
    n = len(pts)
    if n < EV_SPLIT_MIN_POINTS:
        return None
    h = (n + 1) // 2
    early, late = pts[:h], pts[n - h:]
    e, sxe = win_slope([p["t"] for p in early], [math.log(p["c"]) for p in early])
    l, sxl = win_slope([p["t"] for p in late], [math.log(p["c"]) for p in late])
    out = {"early_slope": float(e), "late_slope": float(l), "ratio": None, "class": "NOT_ASSESSABLE", "n": n, "sigma": sigma,
           "early_t": [float(early[0]["t"]), float(early[-1]["t"])], "late_t": [float(late[0]["t"]), float(late[-1]["t"])],
           "rule": "Absorption A0.7 post-peak split (shared)", "reason": None}
    if e >= 0 or l >= 0:
        return out | {"reason": "the " + ("early" if e >= 0 else "late") + " half does not decline"}
    se = sigma / math.sqrt(sxe) if sigma and sxe > 0 else None
    if se is None or abs(e) < EV_SPLIT_ZERO_Q * se:
        return out | {"reason": "the early slope is not distinguished from zero", "early_slope_se": se}
    ratio = float(l / e)
    cls = "DECLINE_STEEPENS" if ratio >= EV_SPLIT_UP else "DECLINE_FLATTENS" if ratio <= EV_SPLIT_DOWN else "NEITHER"
    return out | {"ratio": ratio, "class": cls, "early_slope_se": se}


def window_sigma(level, digitized, pts):
    """Item 24 rule 3: sigma on ln C. Individual 0.15; group means sqrt(0.05^2 + CV^2/n) (0.05 only when digitized), or 0.158
    when SD and n are not reported at every point."""
    if level != "GROUP_MEAN":
        return WIN_SIGMA_IND, "individual data, project setting 0.15"
    if pts and all(_pnum(p.get("sd")) and _pnum(p.get("n")) for p in pts):
        dig = WIN_DIGIT_TERM if digitized else 0.0
        v = [dig ** 2 + (float(p["sd"]) / p["c"]) ** 2 / float(p["n"]) for p in pts]
        return math.sqrt(sum(v) / len(v)), "group means: sqrt(" + ("0.05^2 + " if dig else "") + "(SD/mean)^2/n), root mean square over points"
    return WIN_SIGMA_GROUP_DEFAULT, "group means without SD and n at every point, project setting 0.158"


NOISE_TIER_LABEL = {1: "SOURCE_ASSAY", 2: "SOURCE_REPLICATES", 3: "DEFAULT"}   # r1.5b YAML labels.noise_tier (M4)


def window_noise(level, digitized, pts, src):
    """r1.5 section 2.8: sigma on ln C set before any test. Tier 1 source assay precision, tier 2 source replicates, tier 3 the
    project default. Returns dict(sigma, tier, basis, source, source_sigma)."""
    src = src or {}
    cv = None
    for key, scale in (("assay_cv", 1.0), ("assay_precision_cv", 1.0), ("assay_cv_pct", 0.01)):
        v = _pnum(src.get(key))
        if v is not None and v > 0:
            cv = v * scale
            if cv > 1.5 and scale == 1.0:
                cv /= 100
            break
    if cv and level != "GROUP_MEAN":
        sg = math.sqrt(math.log(1 + cv * cv))
        return {"sigma": sg, "tier": 1, "tier_label": NOISE_TIER_LABEL[1], "basis": f"source assay precision CV {100 * cv:.3g}%",
                "source": src.get("assay_precision_source") or "source metadata", "source_sigma": sg}
    rep = _pnum(src.get("replicate_sigma_ln"))
    if rep is not None and rep > 0 and level != "GROUP_MEAN":
        return {"sigma": rep, "tier": 2, "tier_label": NOISE_TIER_LABEL[2], "basis": "source replicate measurements", "source": src.get("replicate_source") or "source metadata",
                "source_sigma": rep}
    sg, basis = window_sigma(level, digitized, pts)
    return {"sigma": sg, "tier": 3, "tier_label": NOISE_TIER_LABEL[3], "basis": basis, "source": "DEFAULT (r1.3 project setting)", "source_sigma": None}


def entry_text(entry):
    meta = entry.get("metadata", {})
    return " ".join(str(x or "") for x in (entry.get("title"), entry.get("notes"), entry.get("experimental_unit"),
                                            meta.get("dosing_regimen"), meta.get("matrix")))


def panel_view(panel, file, label, tier=1):
    """One figure view of a question row (Distribution and Elimination)."""
    return {"panel": panel, "file": file, "label": label, "tier": tier}


def load_section_config(root, filename, default):
    """A section's run configuration: the defaults without their _example entries, updated key by key from <root>/<filename>."""
    p = Path(root) / filename
    cfg = json.loads(json.dumps(default))
    for k in list(cfg):
        if isinstance(cfg[k], dict):
            cfg[k] = {kk: vv for kk, vv in cfg[k].items() if not str(kk).startswith("_example")}
    if p.exists():
        user = json.loads(p.read_text(encoding="utf-8-sig"))
        for k, v in user.items():
            if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                cfg[k].update({kk: vv for kk, vv in v.items() if not str(kk).startswith("_example")})
            else:
                cfg[k] = v
        cfg["_loaded_from"] = str(p.name)
    return cfg


def is_digitized(entry):
    return (entry.get("metadata", {}).get("observation_source") == "DIGITIZED_FROM_FIGURE"
            or "digitiz" in entry_text(entry).lower())


def series_level(entry):
    """Record level used for the IV-window precision (Distribution rule; M1 shares it with Absorption)."""
    rc = entry.get("metadata", {}).get("record_category", "NOT_FOUND")
    if rc == "INDIVIDUAL":
        return "INDIVIDUAL" if serial_identity_verified(entry) else "INDIVIDUAL_IDENTITY_UNVERIFIED"
    if rc == "GROUP_SUMMARY":
        return "GROUP_MEAN"
    one = bool(re.search(r"one (?:\w+ )?(?:animal|dog|rat|mouse|monkey|rabbit) per time", entry_text(entry).lower()))
    return "INDIVIDUAL_IDENTITY_UNVERIFIED" if one else "GROUP_MEAN"


def iv_window_for_entry(entry, points, cfg=None, column=None):
    """M1: the IV window record for one IV column of a source table, computed exactly as Distribution computes it for item 24
    (same dosing clock, same normalised samples, same precision tier). Absorption calls this for its own IV references.
    Round 3: the column's own input duration, when the input gives one."""
    mode, inf_h, _src = iv_dosing(entry, cfg, column)
    base = {"name": IV_WINDOW_NAME, "time_basis": "time after the end of dosing", "iv_mode": mode, "input_h": inf_h,
            "input_source": _src, "time_origin_basis": time_origin_record(entry)[1]}
    if mode not in ("BOLUS", "INFUSION") or inf_h is None:
        return base | {"status": "NOT_DETERMINED", "start_h": None, "end_h": None, "sample_times_h": [], "sample_ids": [], "n": 0,
                       "slope_per_h": None, "rate_per_h": None, "thalf_h": None,
                       "reason": "end of input not known" if mode != "ONGOING_INPUT" else "ongoing input: no post-stop interval"}
    q, shift = iv_window_samples(points, inf_h, time_origin(entry))
    if len({p["t"] for p in q}) != len(q):
        return base | {"status": "NOT_DETERMINED", "start_h": None, "end_h": None, "sample_times_h": [], "sample_ids": [], "n": 0,
                       "slope_per_h": None, "rate_per_h": None, "thalf_h": None, "reason": "duplicate times in a single series"}
    meta = entry.get("metadata", {})
    src = {k: meta.get(k) for k in PRECISION_SOURCE_KEYS if meta.get(k) not in (None, "")}
    src.update(((cfg or {}).get("noise_by_dataset") or {}).get(entry.get("dataset_id")) or {})
    noise = window_noise(series_level(entry), is_digitized(entry), q, src)
    return base | iv_window(q, noise["sigma"], noise["basis"], shift=shift)


def dose_regimen(entry):
    """L8 (2026-11-24): loading dose, infusion rate and a known delivered amount are kept apart and never collapsed into one dose.
    A loading-plus-infusion table has a supportable dose denominator only when the source states the delivered amount and the
    input has ended; otherwise the denominator is None and dose normalisation and the F reading are suspended."""
    meta = entry.get("metadata", {})
    text = entry_text(entry)
    loading, rate = _pnum(meta.get("loading_dose_mg_kg")), _pnum(meta.get("infusion_rate_mg_kg_h"))
    if loading is None:
        m = re.search(r"([\d.]+)\s*mg/kg\s*(?:loading|(?:iv )?bolus)|loading\s+(?:dose|injection|bolus)\s+of\s+([\d.]+)\s*mg/kg", text, re.I)
        loading = float(m.group(1) or m.group(2)) if m else None
    if rate is None:
        m = re.search(r"([\d.]+)\s*mg/kg/(?:h|hr|hour)\b", text, re.I)
        rate = float(m.group(1)) if m else None
    stated = bool(re.search(r"loading\b.{0,120}?(?:followed|then|thereafter|and)\b.{0,80}?infus", text, re.I | re.S))
    lpi = stated or (loading is not None and rate is not None)
    delivered = _pnum(meta.get("delivered_dose_mg_kg")) or _pnum(meta.get("total_dose_mg_kg"))
    ongoing = ongoing_input(entry)
    denom = delivered if (lpi and delivered and not ongoing) else None
    reason = None
    if lpi and denom is None:
        reason = ("loading dose plus " + ("ongoing " if ongoing else "") + "infusion: "
                  + ("the delivered amount is not stated" if not delivered else "input continues during sampling")
                  + "; dose normalisation and the F reading are suspended")
    return {"loading_plus_infusion": lpi, "loading_dose_mg_kg": loading, "infusion_rate_mg_kg_h": rate,
            "delivered_dose_mg_kg": delivered, "ongoing_input": ongoing, "denominator_mg_kg": denom, "reason": reason}


def ongoing_input(entry):
    meta = entry.get("metadata", {})
    text = entry_text(entry).lower()
    if (not any(meta.get(k) is True for k in ("ongoing_input", "input_ongoing", "infusion_ongoing_at_all_samples"))
            and re.search(r"(?:over|for)\s*\d+(?:\.\d+)?\s*(?:min|minutes?|h|hours?)\b", text)
            and not re.search(r"ongoing input|during (?:continuous )?infusion", text)):
        return False
    return (meta.get("ongoing_input") is True or meta.get("input_ongoing") is True or meta.get("infusion_ongoing_at_all_samples") is True
            or bool(re.search(r"ongoing input|during (?:continuous )?infusion|continuous (?:iv )?infusion|(?:loading|bolus).*(?:followed|thereafter|infus)", text)))


# Round 3 (2026-11-24): the dosing input contract. Structured fields are read first: the run configuration, then the
# concentration column, then the table metadata. Prose is a fallback only, and its source says so ("source text (fallback)").
#   table metadata:        dose_mg_kg (dose level), infusion_h (input duration in h; 0 = bolus), time_origin
#   concentration column:  subject_id; with a subject_id, dose_mg_kg is that animal's administered dose and infusion_h its own
#                          input duration; dose_level_mg_kg names the dose group when one table holds several dose levels
# The dose level groups series (dose groups, dose proportionality); the administered dose divides (Vc and CL bounds, AUC/D).
TIME_ORIGIN_START = ("START_OF_DOSING", "START_OF_INPUT", "START_OF_INFUSION", "START_OF_INJECTION", "START_OF_ADMINISTRATION")
TIME_ORIGIN_END = ("END_OF_INFUSION", "END_OF_DOSING", "END_OF_INPUT", "END_OF_INJECTION", "END_OF_ADMINISTRATION")
_INPUT_WORDS = r"(?:the\s+)?(?:iv\s+|intravenous\s+)?(?:injection|infusion|dosing|dose|administration|input|treatment)"
_ORIGIN_START_TEXT = re.compile(rf"after\s+(?:the\s+)?(?:start|beginning|onset|initiation)\s+of\s+{_INPUT_WORDS}", re.I)
_ORIGIN_END_TEXT = re.compile(rf"after\s+(?:the\s+)?(?:end|completion|stop|cessation|termination)\s+of\s+{_INPUT_WORDS}", re.I)


def _duration(value):
    x = _pnum(value)
    return x if x is not None and x >= 0 else None


_SLOW_INPUT = re.compile(r"\bslow(?:ly)?\s+(?:i\.?v\.?\s+|intravenous\s+)?(?:injection|injected|administration|administered|push|bolus)\b")


def _input_duration_unknown(meta, text):
    """2026-11-25: a SLOW IV injection has an input of unknown length (INFUSION_TIMING_UNKNOWN), whatever the word 'injection'
    says, when no duration is given. The statement may be in the prose or in a metadata field named *duration*. A plain IV
    injection whose duration is not reported stays a bolus (the usual reading, unchanged from round 3)."""
    fields = " ".join(str(v) for k, v in (meta or {}).items() if "duration" in str(k).lower() and isinstance(v, str))
    return bool(_SLOW_INPUT.search(text) or _SLOW_INPUT.search(fields.lower()))


def iv_dosing(entry, cfg=None, column=None):
    """IV mode and end of input: (mode, infusion_h, source). Modes BOLUS, INFUSION (with end), ONGOING_INPUT,
    INFUSION_TIMING_UNKNOWN, IV_MODE_UNKNOWN. Order (round 3): run configuration, ongoing input, the column's own infusion_h,
    the table's infusion_h, route_detail, then prose (flagged as a fallback). A stated duration is never overridden by the
    word 'injection' in the prose."""
    if ongoing_input(entry):
        return "ONGOING_INPUT", None, "source protocol: ongoing input; no post-stop interval"
    ov = ((cfg or {}).get("iv_mode") or {}).get(entry["dataset_id"])
    if ov and ov.get("mode"):
        mode = str(ov["mode"]).upper()
        if mode == "INFUSION":
            h = _pnum(ov.get("infusion_h"))
            return ("INFUSION", h, "run configuration") if h is not None else ("INFUSION_TIMING_UNKNOWN", None, "run configuration")
        return mode, 0.0, "run configuration"
    meta = entry.get("metadata", {})
    for where, holder in (("column", column or {}), ("metadata", meta)):
        h = _duration(holder.get("infusion_h"))
        if h is not None:
            return ("INFUSION", h, f"{where}.infusion_h") if h > 0 else ("BOLUS", 0.0, f"{where}.infusion_h")
    rd = str(meta.get("route_detail", "")).upper()
    if rd == "IV_BOLUS":
        return "BOLUS", 0.0, "route_detail"
    t = entry_text(entry).lower()
    m = re.search(r"(?:over|infus\w*(?: for)?)\s*(\d+(?:\.\d+)?)\s*(min|minutes?|h|hours?)\b", t)
    if m:
        v = float(m.group(1)) / (60 if m.group(2).startswith("min") else 1)
        return "INFUSION", v, "source text (fallback)"
    if _input_duration_unknown(meta, t):
        return "INFUSION_TIMING_UNKNOWN", None, "source text (fallback)"
    if re.search(r"\bbolus\b|i\.?v\.? push|\binjection\b|\binjected\b", t):
        return "BOLUS", 0.0, "source text (fallback)"
    if rd == "IV_INFUSION" or "infus" in t:
        return "INFUSION_TIMING_UNKNOWN", None, "route_detail" if rd == "IV_INFUSION" else "source text (fallback)"
    return "IV_MODE_UNKNOWN", None, "not reported"


def time_origin_record(entry):
    """(origin, basis): the clock of the source times. basis is 'metadata.time_origin', 'source text (fallback)', 'conflict'
    or 'not stated'. A stated origin wins; prose naming both clocks, or neither, leaves it not stated."""
    v = str(entry.get("metadata", {}).get("time_origin") or "").strip().upper().replace(" ", "_")
    if v in TIME_ORIGIN_END:
        return "END_OF_INFUSION", "metadata.time_origin"
    if v in TIME_ORIGIN_START:
        return "START_OF_DOSING", "metadata.time_origin"
    t = " ".join(str(x or "") for x in (entry.get("notes"), entry.get("title"), entry.get("experimental_unit")))
    start, end = bool(_ORIGIN_START_TEXT.search(t)), bool(_ORIGIN_END_TEXT.search(t))
    if start != end:
        return ("START_OF_DOSING" if start else "END_OF_INFUSION"), "source text (fallback)"
    return "START_OF_DOSING", "conflict" if start else "not stated"


def time_origin(entry):
    """M1: the clock of the source times. END_OF_INFUSION only when the source states it; then no second shift is applied."""
    return time_origin_record(entry)[0]


def subject_dosing(entry, column):
    """Round 3: the administered dose and input duration of the animal in one concentration column. Only a column that names
    its subject carries them; a column without a subject_id that prints dose_mg_kg names a dose level instead.
    Returns {"subject_id", "dose_mg_kg", "infusion_h", "dose_level_mg_kg", "source"}."""
    column = column or {}
    subject = column_subject(column)
    out = {"subject_id": subject, "dose_mg_kg": None, "infusion_h": None,
           "dose_level_mg_kg": _pnum(column.get("dose_level_mg_kg")), "source": None}
    if subject is None:
        return out
    d = _pnum(column.get("dose_mg_kg"))
    if d is None:
        d = _pnum(column.get("dose_mg_per_kg"))
    out["dose_mg_kg"] = d if d is not None and d > 0 else None
    out["infusion_h"] = _duration(column.get("infusion_h"))
    if out["dose_mg_kg"] is not None or out["infusion_h"] is not None:
        out["source"] = "column"
    return out


def dose_given(series):
    """The dose a series received (mg/kg): the animal's own administered dose when the input states it, else the dose level.
    Every division by dose (Vc and CL bounds, dose-normalised concentrations and AUC) goes through this accessor."""
    d = series.get("dose_given")
    return d if isinstance(d, (int, float)) and not isinstance(d, bool) and d > 0 else series.get("dose")


def dose_text(series, fallback="dose not found"):
    """Display (George 2026-11-25): the dose the series received, so a table never shows the dose level against an animal whose
    own dose was recorded."""
    d = dose_given(series)
    return f"{d:.4g} mg/kg" if d else fallback


def dose_range_text(series_list, fallback="not found"):
    """Dataset-level dose: one value, or the per-animal range with the dose level (median) in brackets."""
    ds = sorted({round(dose_given(s), 6) for s in series_list if dose_given(s)})
    if not ds:
        return fallback
    if len(ds) == 1:
        return f"{ds[0]:.4g} mg/kg"
    lvl = next((s.get("dose") for s in series_list if s.get("dose")), None)
    return f"{ds[0]:.4g}–{ds[-1]:.4g} mg/kg per animal" + (f" (dose level {lvl:.4g})" if lvl else "")


def input_nominal(series):
    """The table-level input duration, used to group series. The clock of each series uses its own infusion_h."""
    return series.get("infusion_h_nominal", series.get("infusion_h"))


def input_contract(entry):
    """Round 3: what the dosing and clock fields of one source table say, and what is missing. Each issue is a code; a
    missing field never silently takes a permissive default (the reader that needs it reports it, and the dependent
    formal result is withheld)."""
    meta = entry.get("metadata", {})
    issues = []
    rc = str(meta.get("route_class") or "").upper()
    cols = [c for c in entry.get("columns", []) if c.get("meaning") == "CONCENTRATION"]
    subj = [subject_dosing(entry, c) for c in cols]
    origin, origin_basis = time_origin_record(entry)
    out = {"dataset_id": entry.get("dataset_id"), "route_class": rc or None, "time_origin": origin, "time_origin_basis": origin_basis,
           "dose_level_mg_kg": _pnum(meta.get("dose_mg_kg") or meta.get("dose_mg_per_kg")),
           "subject_columns": sum(1 for x in subj if x["subject_id"]),
           "subject_doses": sum(1 for x in subj if x["dose_mg_kg"] is not None),
           "subject_durations": sum(1 for x in subj if x["infusion_h"] is not None)}
    if rc == "IV":
        modes = {iv_dosing(entry, None, c) for c in cols} or {iv_dosing(entry)}
        out["iv_modes"] = sorted({m[0] for m in modes})
        out["iv_mode_sources"] = sorted({m[2] for m in modes})
        durations = [m[1] for m in modes if m[1]]
        if any("fallback" in m[2] for m in modes):
            issues.append("IV_INPUT_FROM_TEXT")
        if any(m[0] in ("INFUSION_TIMING_UNKNOWN", "IV_MODE_UNKNOWN") for m in modes):
            issues.append("IV_INPUT_DURATION_NOT_STATED")
        if durations and origin_basis in ("not stated", "conflict"):
            issues.append("TIME_ORIGIN_NOT_STATED" if origin_basis == "not stated" else "TIME_ORIGIN_CONFLICT")
        elif durations and origin_basis.startswith("source text"):
            issues.append("TIME_ORIGIN_FROM_TEXT")
    if out["subject_columns"] and out["subject_doses"] and out["subject_doses"] < out["subject_columns"]:
        issues.append("SUBJECT_DOSE_PARTIAL")
    if out["subject_doses"] and out["dose_level_mg_kg"] is None and not all(x["dose_level_mg_kg"] for x in subj if x["subject_id"]):
        issues.append("DOSE_LEVEL_NOT_STATED")
    text = " ".join(str(x or "") for x in (entry.get("notes"), entry.get("experimental_unit")))
    if not out["subject_doses"] and re.search(r"per[- ]animal doses?|individual doses?|dose(?:s)? (?:recorded )?per animal", text, re.I):
        issues.append("SUBJECT_DOSES_ONLY_IN_TEXT")
    if (rc == "IV" and not out["subject_durations"]
            and re.search(r"duration recorded per animal|per[- ]animal (?:injection|infusion) (?:duration|time)", text, re.I)):
        issues.append("SUBJECT_DURATIONS_ONLY_IN_TEXT")
    out["issues"] = issues
    return out


# L1 (2026-11-24): one data convention for a source-reported predose zero in every section. It keeps its own status (it is not
# a quantified concentration and is never counted as one) and may serve as an area anchor where the section justifies it.
PREDOSE_ZERO = "REPORTED_ZERO_PREDOSE"


# L4 (2026-11-24): one species registry for every section, so build() in the tests and the production launcher give the same
# species and board ids. Order matters: the first match names the species ("guinea pig" before "pig"). species_aliases.json
# beside this file may add names; the launcher's append is then a no-op.
SPECIES = [("Guinea pig", r"guinea[\s-]*pigs?"), ("Mouse", r"\b(?:mouse|mice|murine)\b"), ("Rat", r"\brats?\b"),
           ("Rabbit", r"\brabbits?\b"), ("Hamster", r"\bhamsters?\b"), ("Koala", r"\bkoalas?\b"),
           ("Donkey", r"\b(?:donkeys?|jenn(?:y|ies))\b"), ("Cat", r"\b(?:cats?|feline)\b"),
           ("Dog", r"\b(?:dogs?|beagles?|canine)\b"), ("Monkey", r"\b(?:monkeys?|macaques?|primates?|cynomolgus|rhesus|marmosets?)\b"),
           ("Pig", r"\b(?:pigs?|piglets?|minipigs?|swine|porcine)\b"), ("Sheep", r"\b(?:sheep|ovine|lambs?)\b"),
           ("Horse", r"\b(?:horses?|equine|foals?|pony|ponies)\b"), ("Human", r"\b(?:humans?|patients?|volunteers?)\b")]


def _load_species_aliases():
    path = Path(__file__).resolve().with_name("species_aliases.json")
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    for name, pattern in rows:
        if all(row[0] != name for row in SPECIES):
            SPECIES.append((name, pattern))


_load_species_aliases()


_N_WORDS = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "twelve": 12}
_ANIMALS = (r"(?:mice|mouse|rats?|animals?|rabbits?|dogs?|beagles?|monkeys?|pigs?|piglets?|minipigs?|cats?|horses?|ponies|cattle|"
            r"calves|cows?|sheep|goats?|koalas?|donkeys?|jennies|subjects?|birds?|chickens?|fish)")
_NUM = r"(\d+|" + "|".join(_N_WORDS) + r")"


def _n_int(x):
    return None if x is None else int(x) if str(x).isdigit() else _N_WORDS.get(str(x).lower())


def sample_size(text, meta=None, header_suffix=False):
    """L2 (2026-11-24): the one sample-size reader of every section. Returns (n, n_range, basis).
    Policy, the same everywhere: a stated n per group or per time point is used as stated; a range ('n = 3-4', '3 or 4 mice per
    time') is kept as a range and no single n is assigned to every time point (a lower bound would shrink an SD derived from an SE).
    A per-time n from an n column or a per-time statement wins over this reader and is applied by the caller."""
    meta = meta or {}
    for k in ("n", "n_animals", "n_per_group", "n_per_time"):
        v = meta.get(k)
        try:
            v = float(v)
        except (TypeError, ValueError):
            continue
        if v >= 1 and v == int(v):
            return int(v), None, "metadata " + k
    s = str(text or "")
    pats = [r"\bn\s*=\s*(\d+)(?:\s*(?:[–—-]|to|or)\s*(\d+))?",
            _NUM + r"(?:\s*(?:or|-|–|to)\s*" + _NUM + r")?\s*" + _ANIMALS + r"\s*(?:/|per)\s*(?:time|sampling|group)",
            r"(?:group mean of|groups? of)\s+" + _NUM + r"(?:\s*(?:or|-|–|to)\s*" + _NUM + r")?\s+" + _ANIMALS,
            r"\bfor\s+" + _NUM + r"\s+" + _ANIMALS + r"\b",
            r"(?<!total )\bof\s+(\d+)\s+" + _ANIMALS + r"\b"]
    if header_suffix:
        pats.append(r"\((\d+)\)\s*$")
    for pat in pats:
        m = re.search(pat, s, re.I)
        if m:
            vals = sorted({v for v in (_n_int(g) for g in m.groups()) if v})
            if not vals:
                continue
            return (vals[0], None, "source text") if len(vals) == 1 else (None, [vals[0], vals[-1]], "source text (range)")
    return None, None, "not reported"


def is_predose_zero(p):
    return p.get("status") == PREDOSE_ZERO and p.get("t") is not None and p["t"] <= 0 and p.get("c") == 0


def is_quantified(p):
    """A quantified concentration: status QUANTIFIED with a positive value (a printed zero is not a quantified point)."""
    return p.get("status") == "QUANTIFIED" and p.get("c") is not None and p["c"] > 0 and p.get("t") is not None


def iv_window_samples(points, infusion_h=0.0, origin="START_OF_DOSING"):
    """The normalised IV samples: quantified, positive, after the end of input, on the clock "time after the end of dosing".
    Returns (samples, shift); the shift is the infusion duration unless the source clock already starts at the end of input."""
    shift = 0.0 if origin == "END_OF_INFUSION" else float(infusion_h or 0.0)
    q = [dict(p, t=p["t"] - shift) for p in points
         if p.get("status") == "QUANTIFIED" and p.get("c") is not None and p["c"] > 0 and p.get("t") is not None and p["t"] > shift + 1e-12]
    return sorted(q, key=lambda p: p["t"]), shift


def iv_window(q, sigma, precision_basis, shift=0.0, base=None):
    """M1: the post-distribution IV window (Distribution item 24 step 7). The slope is refitted on the samples the record lists."""
    base = base or win_split_half(q, sigma)
    cur = base["curvature"]
    start, reason, trail, low_power = None, None, [], False
    if cur == "FLATTENING":
        for k in range(1, len(q)):
            sub = q[k:]
            if len(sub) < WIN_MIN_POINTS:
                break
            sh = win_split_half(sub, sigma)
            trail.append({"from_h": q[k]["t"], "n": len(sub), "reading": sh["curvature"], "power_ok": sh.get("power_ok"),
                          "min_detectable_rate_difference": sh.get("min_detectable_rate_difference"), "b_late": sh.get("b_late")})
            if sh["curvature"] == "NONE_DETECTED":
                if sh.get("power_ok"):
                    start = q[k]["t"]
                    break
                low_power = True
        if start is None:
            reason = ("LOW_POWER" if low_power else "TOO_FEW_POINTS" if not trail
                      else "SLOWING_IN_EVERY_SUFFIX" if all(x["reading"] == "FLATTENING" for x in trail) else "NO_NULL_SUFFIX")
    elif cur == "NONE_DETECTED":
        if base.get("power_ok"):
            start = q[0]["t"]
        else:
            reason = "LOW_POWER"
    else:
        reason = "PROFILE_STEEPENING" if cur == "STEEPENING" else "SCREEN_NOT_ASSESSABLE"
    rec = {"name": IV_WINDOW_NAME, "time_basis": "time after the end of dosing", "shift_applied_h": shift, "precision_basis": precision_basis,
           "sigma": sigma, "curvature": cur, "suffix_screen": trail}
    if start is None:
        return rec | {"status": "NOT_DETERMINED", "start_h": None, "end_h": None, "sample_times_h": [], "sample_ids": [], "n": 0,
                      "slope_per_h": None, "rate_per_h": None, "thalf_h": None, "reason": reason}
    w = [p for p in q if p["t"] >= start - 1e-12]
    slope = None
    if len(w) >= 2 and len({p["t"] for p in w}) >= 2:
        slope = win_slope([p["t"] for p in w], [math.log(p["c"]) for p in w])[0]
    rate = -slope if slope is not None else None
    return rec | {"status": "DETERMINED", "start_h": start, "end_h": w[-1]["t"], "sample_times_h": [p["t"] for p in w],
                  "sample_ids": [p.get("record_id") or f"t={p['t']:g}h" for p in w], "n": len(w), "slope_per_h": slope,
                  "rate_per_h": rate, "thalf_h": (math.log(2) / rate) if rate and rate > 0 else None, "reason": None}


# ---------------------------------------------------------------- rule decision R8 (2026-11-24): precision admission

PRECISION_SOURCE_KEYS = ("assay_cv", "assay_cv_pct", "assay_precision_cv", "assay_precision_source", "assay_cv_match", "assay_cv_df",
                         "replicate_sigma_ln", "replicate_source", "replicate_df", "replicate_n", "replicate_target", "replicate_k",
                         "reading_error", "calibration_shift_pct")
CV_MATCH_KEYS = ("source", "method", "analyte", "matrix", "range_covered", "run", "cv_kind")
READING_BASES = ("AXIS_TICKS", "RESOLUTION", "POINT_OVERLAP", "SOURCE_TABLE_CHECK")
DEFAULT_READING_PCT = 5.0


def _pnum(v):
    return to_float(v)          # round 3: the one number reader (defined below with the parser)


def precision_admission(src, *, analyte="PARENT", matrix=None, digitized=False, level="INDIVIDUAL", group_sd_n=True):
    """One admission rule for a formal interval in the three modules (R8). Returns the precision source, the matched scope, the
    degrees of freedom or coverage, every component that enters the joint interval, whether a formal interval is admitted, what is
    missing and the short board label. A missing key component makes the formal status CANNOT_ASSESS; a sensitivity reading may
    still be reported beside it."""
    src = src or {}
    comps, missing, out = [], [], {"kind": "PROJECT_DEFAULT", "sigma": None, "se_target": None, "df": None, "source": None,
                                     "scope_match": None, "coverage": "family-wise two-sided 95 %, Bonferroni over the searched points"}
    group = level == "GROUP_MEAN"
    cv = None
    for key, scale in (("assay_cv", 1.0), ("assay_precision_cv", 1.0), ("assay_cv_pct", 0.01)):
        v = _pnum(src.get(key))
        if v is not None and v > 0:
            cv = v * scale
            if cv > 1.5 and scale == 1.0:
                cv /= 100
            break
    rep = _pnum(src.get("replicate_sigma_ln"))
    rep = rep if rep is not None and rep > 0 else None
    available = []
    if group:
        out.update(kind="GROUP_SAMPLING", source="group SD and n of each mean")
        if group_sd_n:
            comps.append({"component": "sampling error of the group summary", "basis": "SD and n of each mean", "df": "n - 1 per mean"})
            available.append("group SD and n")
        else:
            missing.append("group SD and n at every point")
        if cv:
            comps.append({"component": "assay", "note": "contained in the group SD; not counted twice"})
    elif cv:
        sg = math.sqrt(math.log(1 + cv * cv))
        m = src.get("assay_cv_match") if isinstance(src.get("assay_cv_match"), dict) else {}
        unshown = [k for k in CV_MATCH_KEYS if not m.get(k)]
        miss = [f"match of the assay CV to this analysis ({', '.join(unshown)})"] if unshown else []
        if str(m.get("cv_kind", "")).upper() == "ACCEPTANCE_LIMIT":
            miss.append("an observed CV (a validation acceptance limit is not one)")
        if m.get("analyte") and str(m["analyte"]).upper() != str(analyte).upper():
            miss.append(f"a CV for this analyte ({analyte}; the CV is for {m['analyte']})")
        if m.get("matrix") and matrix and str(m["matrix"]).upper() != str(matrix).upper():
            miss.append(f"a CV for this matrix ({matrix}; the CV is for {m['matrix']})")
        df = _pnum(src.get("assay_cv_df"))
        out.update(kind="ASSAY_CV", sigma=sg, se_target=sg, df=df, source=src.get("assay_precision_source") or m.get("source") or "source metadata",
                   scope_match={k: m.get(k) for k in CV_MATCH_KEYS})
        comps.append({"component": "assay", "cv": cv, "sigma_ln": sg, "df": df if df else "treated as known",
                      "scope_match": "matched" if not miss else "not shown"})
        available.append("assay precision")
        missing += miss
    elif rep:
        df = _pnum(src.get("replicate_df"))
        if df is None and _pnum(src.get("replicate_n")):
            df = _pnum(src.get("replicate_n")) - 1
        target = str(src.get("replicate_target") or "").upper()
        k = _pnum(src.get("replicate_k"))
        se = rep if target == "SINGLE_MEASUREMENT" else rep / math.sqrt(k) if (target == "MEAN_OF_REPLICATES" and k and k >= 1) else None
        out.update(kind="REPLICATES", sigma=rep, se_target=se, df=df, source=src.get("replicate_source") or "source metadata")
        comps.append({"component": "replicate scatter", "sigma_ln": rep, "df": df, "target": target or None, "k": k, "se_target": se})
        available.append("replicate precision")
        if not df or df < 1:
            missing.append("replicate degrees of freedom")
        if se is None:
            missing.append("whether the value is one measurement or a replicate mean")
    else:
        missing.append("source assay precision or replicates")
    if digitized:
        rd = src.get("reading_error") if isinstance(src.get("reading_error"), dict) else {}
        bound, basis = _pnum(rd.get("bound_pct")), str(rd.get("basis") or "").upper()
        if bound is not None and bound >= 0 and basis in READING_BASES:
            comps.append({"component": "figure reading", "bound_pct": bound, "basis": basis})
            out["reading_pct"] = bound
        else:
            comps.append({"component": "figure reading", "bound_pct": DEFAULT_READING_PCT, "basis": "project default (sensitivity only)"})
            out["reading_pct"] = DEFAULT_READING_PCT
            missing.append("figure-reading range")
        if _pnum(src.get("calibration_shift_pct")) is not None:
            comps.append({"component": "panel calibration shift", "pct": _pnum(src["calibration_shift_pct"]),
                          "note": "common to every point of the panel; kept as one shift, does not enter the shape checks"})
    out.update(components=comps, missing=missing, formal_ok=not missing)
    if missing:
        have = ", ".join(available) + " available" if available else "no source precision"
        out["short_label"] = "Insufficient evidence: " + have + ", " + "; ".join(missing) + " missing"
    else:
        out["short_label"] = None
    return out


# Round 3 (2026-11-24), shared rule S12: one premise gate for every formal comparison between groups (dose groups, routes,
# matrices). It looks at every member, never at the first one only, and it fails closed: a premise that is unknown or differs
# between the members makes the comparison a sensitivity reading, with the missing premise named. Checks: the summary type of
# each group mean (arithmetic, geometric, individual values), the concentration unit, and, where the caller says so, time
# alignment and sampling dependence.
_CONC_UNIT = {"mg/l": 1.0, "µg/ml": 1.0, "ug/ml": 1.0, "mcg/ml": 1.0, "µg/l": 1e-3, "ug/l": 1e-3, "ng/ml": 1e-3,
              "ng/l": 1e-6, "mg/ml": 1e3, "g/l": 1e3, "pg/ml": 1e-6, "nmol/l": None, "µmol/l": None, "µm": None}


def summary_type(card):
    """ARITHMETIC, GEOMETRIC, INDIVIDUAL (no group mean), CONFLICT (the source says both) or NOT_STATED."""
    level = str(card.get("record_level") or card.get("level") or "").upper()
    v = str(card.get("mean_type") or "").strip().upper()
    if level.startswith("INDIVIDUAL") or v == "N/A":
        return "INDIVIDUAL"
    if "UNKNOWN" in v or "CONFLICT" in v:
        return "CONFLICT"
    if "GEOMETRIC" in v:
        return "GEOMETRIC"
    if "ARITHMETIC" in v:
        return "ARITHMETIC"
    return "NOT_STATED"


def conc_unit_factor(unit):
    u = str(unit or "").strip().lower().replace(" ", "").replace("μ", "µ")
    u = re.sub(r"^(?:ug|mcg)", "µg", u)
    return _CONC_UNIT.get(u)


def formal_premises(cards, *, times_aligned=True, dependence_unresolved=(), check_units=True):
    """S12: {"formal": bool, "missing": [codes], "summary_types": [...]} for the cards (or series) of every compared group.
    Codes: SUMMARY_TYPE_CONFLICT, SUMMARY_TYPE_MIXED, GEOMETRIC_MEAN_LINEAR_SD (a geometric mean with a linear-scale SD),
    SUMMARY_TYPE_NOT_STATED_ACROSS_SOURCES (no stated type, and the groups come from different studies, so one reporting
    convention cannot be assumed), UNIT_NOT_CONVERTIBLE, UNIT_MISMATCH, TIME_NOT_ALIGNED, SAMPLING_DEPENDENCE_UNRESOLVED."""
    cards = [c for c in cards if c is not None]
    missing = []
    types = [summary_type(c) for c in cards]
    kinds = set(types)
    if "CONFLICT" in kinds:
        missing.append("SUMMARY_TYPE_CONFLICT")
    elif len(kinds) > 1:
        missing.append("SUMMARY_TYPE_MIXED")
    elif kinds == {"GEOMETRIC"} and not all(str(c.get("dispersion_scale") or "").upper() == "LN" for c in cards):
        missing.append("GEOMETRIC_MEAN_LINEAR_SD")
    elif kinds == {"NOT_STATED"} and len({str(c.get("study") or "") for c in cards}) > 1:
        missing.append("SUMMARY_TYPE_NOT_STATED_ACROSS_SOURCES")
    if check_units:
        units = [c.get("unit") for c in cards if c.get("unit") not in (None, "")]
        factors = [conc_unit_factor(u) for u in units]
        if units and any(f is None for f in factors) and len({str(u).strip().lower() for u in units}) > 1:
            missing.append("UNIT_NOT_CONVERTIBLE")
        elif len({f for f in factors if f is not None}) > 1 and not all(c.get("units_harmonised") for c in cards):
            missing.append("UNIT_MISMATCH")
    if not times_aligned:
        missing.append("TIME_NOT_ALIGNED")
    if dependence_unresolved:
        missing.append("SAMPLING_DEPENDENCE_UNRESOLVED")
    return {"formal": not missing, "missing": missing, "summary_types": types}


PREMISE_WORDS = {
    "SUMMARY_TYPE_CONFLICT": "the source gives conflicting summary types (arithmetic and geometric)",
    "SUMMARY_TYPE_MIXED": "the groups use different summary types (e.g. arithmetic in one, geometric in the other)",
    "GEOMETRIC_MEAN_LINEAR_SD": "geometric means with a linear-scale SD",
    "SUMMARY_TYPE_NOT_STATED_ACROSS_SOURCES": "no summary type is stated and the groups come from different sources",
    "UNIT_NOT_CONVERTIBLE": "a concentration unit cannot be converted",
    "UNIT_MISMATCH": "the groups are on different concentration units",
    "TIME_NOT_ALIGNED": "sampling times differ between the groups without a sourced timing bound",
    "SAMPLING_DEPENDENCE_UNRESOLVED": "sampling dependence is not stated",
}


def separate_sensitivity_flags(obj):
    """Walk a result and, for every ``<test>_label == CANNOT_ASSESS``, move removal and widening flags from ``<test>_flags``
    to ``<test>_sensitivity_flags``. Returns the number of records changed."""
    changed = 0
    stack = [obj]
    seen = set()
    while stack:
        cur = stack.pop()
        if id(cur) in seen:
            continue
        seen.add(id(cur))
        if isinstance(cur, dict):
            for key in list(cur.keys()):
                if isinstance(key, str) and key.endswith("_label") and cur[key] == "CANNOT_ASSESS":
                    test = key[:-len("_label")]
                    flags = cur.get(test + "_flags")
                    if isinstance(flags, list):
                        moved = [f for f in flags if f in SENSITIVITY_RECORD_FLAGS]
                        if moved:
                            cur[test + "_flags"] = [f for f in flags if f not in SENSITIVITY_RECORD_FLAGS]
                            cur[test + "_sensitivity_flags"] = list(dict.fromkeys(list(cur.get(test + "_sensitivity_flags") or []) + moved))
                            changed += 1
            stack.extend(v for v in cur.values() if isinstance(v, (dict, list)))
        elif isinstance(cur, list):
            stack.extend(v for v in cur if isinstance(v, (dict, list)))
    return changed


def test_flags(rec, test):
    """Formal and sensitivity flags of one test together (for readers that describe the sensitivity reading)."""
    return list(rec.get(test + "_flags") or []) + list(rec.get(test + "_sensitivity_flags") or [])


# 2026-11-24 review (parser): one number pattern for every 'mean ± dispersion' reader. The dispersion is read as a whole
# number, exponent included; '2.5 ± 1e-3' had been read as SD 1.0 because the old pattern stopped before the exponent.
# Round 3 (2026-11-24): one ingress normalisation for every numeric cell in every section. Typographic minus signs, superscript
# powers of ten, full-width digits and thin or no-break spaces are rewritten once, before any pattern runs, so a reader can no
# longer see '2e−3' (U+2212) as the number 2 followed by a unit 'e−3'. Text that still is not a complete number after
# normalisation is not read (fail closed), never truncated to its leading digits.
NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
_MINUS_SIGNS = dict.fromkeys(map(ord, "\u2212\u2012\ufe63\uff0d\u2010\u2011"), "-")
_WIDE = {0xFF10 + i: str(i) for i in range(10)} | {0xFF0E: ".", 0xFF0B: "+", 0xFF1C: "<", 0xFF1E: ">"}
_THIN_SPACES = dict.fromkeys(map(ord, "\u00a0\u2009\u202f\u2007\u200a\u2002\u2003"), " ")
_SUPERSCRIPT = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺", "0123456789-+")
_TIMES = r"[×xX*·∙⋅]"
# a power of ten: '× 10^-3', '×10^(−3)', '× 10**-3', '×10⁻³' (normalised to '^-3'), or a signed exponent '× 10-3'
POWER10 = rf"\s*{_TIMES}\s*10\s*(?:(?:\^|\*\*)\s*\(?\s*([+-]?\d+)\s*\)?|([+-]\d+))"


def normalize_numeric_text(text):
    """The one ingress rewrite of a printed numeric cell (round 3). Non-strings pass through unchanged."""
    if not isinstance(text, str):
        return text
    t = text.translate(_MINUS_SIGNS).translate(_WIDE).translate(_THIN_SPACES)
    t = re.sub(r"(?<=\d[eE])[\u2013\u2014](?=\d)", "-", t)                  # an en dash used as an exponent sign
    t = re.sub(r"(?<=10)\s*([⁻⁺]?[⁰¹²³⁴⁵⁶⁷⁸⁹]+)", lambda m: "^" + m.group(1).translate(_SUPERSCRIPT), t)
    t = re.sub(r"(?<=\^)\s*[\u2013\u2014](?=\s*\d)", "-", t)
    return t.translate(_SUPERSCRIPT)


def _power(match, first_group):
    g = match.group(first_group) or match.group(first_group + 1)
    return int(g) if g is not None else None


def to_float(value):
    """A finite float from a number or a complete printed number (after normalisation); otherwise None. Booleans are not numbers."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        x = float(value)
        return x if math.isfinite(x) else None
    m = re.fullmatch(rf"\s*({NUMBER})(?:{POWER10})?\s*", normalize_numeric_text(str(value)))
    if not m:
        return None
    x = float(m.group(1))
    p = _power(m, 2)
    if p is not None:
        x *= 10.0 ** p
    return x if math.isfinite(x) else None


_MEAN_DISP = re.compile(rf"^\s*(\()?\s*({NUMBER})\s*(?:±|\+/-|\+-)\s*({NUMBER})(?![\d.eE])\s*(\))?(?:{POWER10})?")


def mean_dispersion(text):
    """'2.5 ± 0.001' and '2.5 ± 1e-3 mg/L' -> (2.5, 0.001, rest); '(2.5 ± 0.3) × 10^-3' scales both numbers. A power of ten
    after an unbracketed 'mean ± dispersion' is ambiguous (does it scale the mean too?) and gives None, as does any text that
    is not 'mean ± dispersion'. The rest (unit, footnote, '(n)') is returned as printed."""
    if text is None or isinstance(text, (int, float)):
        return None
    t = normalize_numeric_text(str(text))
    m = _MEAN_DISP.match(t)
    if not m:
        return None
    opened, closed, power = bool(m.group(1)), bool(m.group(4)), _power(m, 5)
    if opened != closed or (power is not None and not opened):
        return None
    mean, disp = float(m.group(2)), float(m.group(3))
    if power is not None:
        mean, disp = mean * 10.0 ** power, disp * 10.0 ** power
    if not (math.isfinite(mean) and math.isfinite(disp)):
        return None
    return mean, disp, t[m.end():].strip()


ASSAY_LABELS = {"NOT_DETECTED": "not detected", "BLQ": "below quantification",
                "ALQ": "above quantification", "CENSORED": "censored"}
_PRINTED_BOUND = re.compile(rf"(<=|>=|<|>|≤|≥)\s*({NUMBER})(?:{POWER10})?\s*(.*)")
# what may follow a printed limit: a unit or nothing. Anything that still looks like part of a number is not read.
_NUMBER_REMNANT = re.compile(r"^(?:[eE]\s*[+-]?\d|[\d.^(]|[×xX*·∙⋅]\s*10|[-+]\s*\d)")
PERCENT_UNIT = re.compile(r"^%(?:\s*(?:of\s+(?:the\s+)?(?:administered\s+|given\s+|iv\s+|oral\s+)?dose|dose))?\.?$", re.I)


def assay_class(text):
    """Round 3 addendum: one assay reader for the structured field and the prose fallback. A method named only to say it was
    not used ("no LC-MS confirmation") is not the method. Immunoassays are kept apart from chromatographic methods: a binding
    assay does not show selectivity for the parent."""
    named = re.sub(r"\b(?:no|not|without|lacking)\b[^;,.]{0,40}", " ", str(text or ""), flags=re.I)
    if re.search(r"bioassay|microbiolog|agar (?:well )?diffusion|disc[- ]plate|cup[- ]plate", named, re.I):
        return "MICROBIOLOGICAL"
    if re.search(r"14\s*c\b|radioactiv|scintillation", named, re.I):
        return "RADIOACTIVITY"
    if re.search(r"elisa|immunoassay|\beia\b|\bria\b|radioimmuno|fpia|immunochrom", named, re.I):
        return "IMMUNOASSAY"
    if re.search(r"\bhplc\b|\buplc\b|lc[-/ ]?ms|gc[-/ ]?ms|chromatograph|mass spec", named, re.I):
        return "SPECIFIC"
    return None


def printed_assay_bound(raw):
    """'<2 ng/mL' -> {'relation': '<', 'threshold': 2.0, 'unit_as_printed': 'ng/mL'}. Round 3: read after the one ingress
    normalisation; a power of ten scales the threshold; a remainder that still looks like part of a number makes the cell
    unreadable (None), so no threshold is invented from its leading digits."""
    if not isinstance(raw, str):
        return None
    text = re.sub(r"\s*(?:\([a-z]\)|\b[a-z]\)|\*+)$", "", normalize_numeric_text(raw).strip(), flags=re.I).strip()
    match = _PRINTED_BOUND.fullmatch(text)
    if match:
        relation, number, unit = match.group(1), match.group(2), match.group(5)
        if unit and _NUMBER_REMNANT.match(unit.strip()):
            return None
        threshold = float(number)
        p = _power(match, 3)
        if p is not None:
            threshold *= 10.0 ** p
        if math.isfinite(threshold):
            return {"relation": relation, "threshold": threshold, "unit_as_printed": unit.strip() or None}
    return None


def bound_unit_class(bound, column_unit=None):
    """Round 3: the unit a printed limit is on. 'PERCENT' only when the limit itself prints '%' (or prints no unit while its
    column is a percent-of-dose column); 'OTHER' for any other printed unit; 'NOT_STATED' when neither says."""
    if not bound:
        return "NOT_STATED"
    u = (bound.get("unit_as_printed") or "").strip()
    if u:
        return "PERCENT" if PERCENT_UNIT.match(u) else "OTHER"
    cu = (column_unit or "").strip()
    if cu:
        return "PERCENT" if PERCENT_UNIT.match(cu) or cu.startswith("%") else "OTHER"
    return "NOT_STATED"


# 2026-11-25: a sample the source authors excluded is not analysed. It is set either as the cell's value_status or as a
# record-level source_flags entry for that column; a flagged BLQ cell stays BLQ (its censoring is still a fact).
SOURCE_EXCLUSIONS = {"AUTHOR_EXCLUDED", "MDV_1_SOURCE_FLAG"}


def source_flags(record, column):
    v = (record.get("source_flags") or {}).get(column)
    return [str(x).strip().upper() for x in (v if isinstance(v, (list, tuple)) else [v]) if x not in (None, "")]


def cell_status(record, column):
    """value_status of one cell, with a source exclusion flag applied to a quantified value."""
    st = (record.get("value_status") or {}).get(column)
    if str(st or "QUANTIFIED").strip().upper() == "QUANTIFIED" and set(source_flags(record, column)) & SOURCE_EXCLUSIONS:
        return "AUTHOR_EXCLUDED"
    return st


def assay_qualifier(status, raw=None):
    """A numeric placeholder cannot override an explicit assay or availability qualifier."""
    raw = normalize_numeric_text(raw)
    key = str(status or "").strip().upper()
    if key.startswith(("MISSING", "QUARANTINED")) or key in {
            "EMPTY_SLOT", "NOT_SAMPLED", "NOT_TESTED", "NOT_APPLICABLE", "NOT_COLLECTED"} | SOURCE_EXCLUSIONS:
        return "MISSING"
    for token in (key, str(raw).strip().upper() if isinstance(raw, str) else ""):
        token = re.sub(r"\s*(?:\([A-Z]\)|\b[A-Z]\)|\*+)$", "", token).strip()
        if token in {"ND", "N.D.", "N.D", "NOT DETECTED", "NOT_DETECTED", "BELOW_LOD", "<LOD",
                     "BELOW DETECTION", "BELOW DETECTION LIMIT", "BELOW THE LIMIT OF DETECTION"}:
            return "NOT_DETECTED"
        if token in {"BLQ", "BQL", "BLOQ", "BELOW_LLOQ", "<LLOQ", "<LOQ", "BELOW QUANTIFICATION",
                     "BELOW THE LIMIT OF QUANTIFICATION", "BELOW THE LLOQ"}:
            return "BLQ"
        if token in {"ALQ", "ABOVE_ULOQ", ">ULOQ"}:
            return "ALQ"
        if token == "CENSORED":
            return "CENSORED"
    if isinstance(raw, str) and raw.lstrip().startswith(("<", ">", "≤", "≥")):
        return "CENSORED"
    return None


def workspace(start=None):
    """Return the project workspace: $EDA_WORKSPACE, else the nearest parent with data/, deliverables/ and outputs/."""
    env = os.environ.get("EDA_WORKSPACE")
    if env:
        return Path(env).resolve()
    here = Path(start or _HERE).resolve()
    for folder in (here, *here.parents):
        if all((folder / name).is_dir() for name in _MARKERS):
            return folder
    return _HERE.parents[1]


WORKSPACE = workspace()

# ---------------------------------------------------------------- rules version (one per section)
RULES_DIR = _HERE / "rules"
UNRECORDED = {"version": "unrecorded", "items": "", "file": None, "sha256": None}


# Page wording for EDA004. Slopes and the named dose and slope tests are log-linear regressions on observed points,
# so "no fitting" alone would be wrong; no PK model is fitted and nothing is extrapolated.
FIT_NOTE = "no PK model fitted; any slope or named test shown is a descriptive regression"


def rules_manifest(folder=None):
    path = Path(folder or RULES_DIR) / "rules_manifest.json"
    return json.loads(path.read_text(encoding="utf-8"))


def rules_entry(section, folder=None):
    """The rules version this code implements for a section. A copy without its rules folder reports 'unrecorded'."""
    try:
        return dict(rules_manifest(folder)["sections"][section])
    except (OSError, KeyError, ValueError):
        return dict(UNRECORDED)


def check_rules(folder=None):
    """Problems with the rules folder: a missing file or a file whose SHA-256 differs from the manifest. A current entry binds
    the Markdown rules (file, sha256) and, from the 2026-11-24 revisions on (M3), the machine YAML (yaml, yaml_sha256); a module
    entry with a YAML also names the current shared rules and its output_version. Superseded revisions listed under
    `history` must still be present with their original SHA-256."""
    folder = Path(folder or RULES_DIR)
    try:
        manifest = rules_manifest(folder)
        sections = manifest["sections"]
    except (OSError, KeyError, ValueError, TypeError) as exc:
        return [f"rules manifest unreadable in {folder}: {exc}"]
    if not isinstance(sections, dict):
        return ["rules manifest sections must be an object"]
    problems = [f"{s}: section missing from rules manifest" for s in ("absorption", "distribution", "elimination") if s not in sections]

    def bound(label, name, digest):
        if not isinstance(name, str) or not digest:
            problems.append(f"{label}: incomplete rule binding")
            return
        path = folder / name
        if not path.is_file():
            problems.append(f"{label}: {name} is missing")
        elif hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            problems.append(f"{label}: {name} differs from the manifest SHA-256")

    shared_version = (sections.get("shared") or {}).get("version") if isinstance(sections.get("shared"), dict) else None
    for section, entry in sections.items():
        if not isinstance(entry, dict):
            problems.append(f"{section}: incomplete rule binding")
            continue
        bound(section, entry.get("file"), entry.get("sha256"))
        if "yaml" in entry or "yaml_sha256" in entry:
            bound(section + " machine YAML", entry.get("yaml"), entry.get("yaml_sha256"))
            if section != "shared":
                if entry.get("shared") != shared_version or shared_version is None:
                    problems.append(f"{section}: shared rules {entry.get('shared')} are not the current shared entry")
                if not entry.get("output_version"):
                    problems.append(f"{section}: output_version missing")
    history = manifest.get("history") or []
    if not isinstance(history, list):
        problems.append("rules manifest history must be a list")
        history = []
    for old in history:
        if not isinstance(old, dict) or old.get("status") != "superseded" or not old.get("sha256"):
            problems.append(f"history entry incomplete: {old!r}")
        elif old.get("file"):
            bound(f"{old.get('section')} {old.get('version')} (superseded)", old["file"], old["sha256"])
    return problems

# ---------------------------------------------------------------- board identity
SINGLE = "SINGLE"
REPEAT = "REPEAT"
LOADING_PLUS_INFUSION = "LOADING_PLUS_INFUSION"
INFUSION = "INFUSION"
IN_VITRO = "IN_VITRO"
EXCRETA = "EXCRETA"
REPORTED = "REPORTED"
# Ordering used when a board mixes designs: the most specific design wins the board's label.
_PRECEDENCE = {LOADING_PLUS_INFUSION: 0, INFUSION: 1, REPEAT: 2, IN_VITRO: 3, EXCRETA: 4, SINGLE: 5, REPORTED: 6}
_EXCRETA_ROLES = {"URINE_EXCRETION", "FECES_EXCRETION", "BILE_EXCRETION", "MASS_BALANCE", "EXCRETION"}
_IN_VITRO_ROLES = {"BINDING", "IN_VITRO", "METABOLISM_IN_VITRO", "BLOOD_PLASMA_RATIO"}
_OCCASION = re.compile(r"\bday\s*(\d+)\s*of\s*(\d+)\b", re.I)


def _text(*values):
    return " ".join(str(v) for v in values if v not in (None, "")).lower()


def design_of(table):
    """Design of one source table from its role, route and dosing_regimen."""
    md = table.get("metadata") or {}
    role = str(table.get("role") or "").upper()
    if role in _EXCRETA_ROLES:
        return EXCRETA
    if role in _IN_VITRO_ROLES or str(md.get("origin") or "").upper() == "IN_VITRO":
        return IN_VITRO
    regimen = _text(md.get("dosing_regimen"), md.get("regimen"), md.get("route_detail"))
    route = _text(md.get("route"), md.get("route_class"), md.get("route_detail"))
    if "loading" in regimen and "infusion" in regimen:
        return LOADING_PLUS_INFUSION
    if ("continuous" in regimen and "infusion" in regimen) or "continuous infusion" in route:
        return INFUSION
    occasion = _OCCASION.search(regimen)
    if occasion and int(occasion.group(2)) > 1:
        return REPEAT
    if re.search(r"\b(daily|repeat(ed)?|multiple|q\d+h|b\.?i\.?d|t\.?i\.?d|for \d+ days|once a day|twice)\b", regimen):
        return REPEAT
    return SINGLE


def board_design(tables):
    """Design label of a board from the source tables it uses.

    One design → that design.  Several → the designs joined with "+" in a fixed
    order, so a repeat-dose or infusion table can never sit on a board that is
    labelled SINGLE.  Excreta and in-vitro tables label a board only when it has
    no in-vivo dosing design of its own (urine beside a single-dose plasma curve
    stays a SINGLE board).
    """
    designs = {design_of(t) for t in tables if t is not None}
    if designs - {EXCRETA, IN_VITRO}:
        designs -= {EXCRETA, IN_VITRO}
    designs = sorted(designs, key=_PRECEDENCE.get)
    if not designs:
        return SINGLE
    return "+".join(designs)


def _slug(value):
    return re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-") or "na"


def board_id(study, species_group, design, qualifier=None):
    """One identity for the same experiment in all three sections: study/species/design[/qualifier]."""
    parts = [_slug(study), _slug(species_group), _slug(design)]
    if qualifier:
        parts.append(_slug(qualifier))
    return "/".join(parts)


def species_group_of(value):
    text = str(value or "").strip()
    return text[:1].upper() + text[1:].lower() if text else ""


def annotate_board(board, tables_by_id, dataset_ids, study=None, species=None, qualifier=None):
    """Add board_id and design to a board in place; existing keys stay unchanged."""
    used = [tables_by_id[i] for i in dataset_ids if i in tables_by_id]
    design = board_design(used)
    group = species_group_of(board.get("species_group") or species or board.get("species"))
    board["design"] = design
    board["board_id"] = board_id(study or board.get("study"), group, design, qualifier)
    return board


def disambiguate(boards):
    """Give boards that still share a board_id a qualifier from their own scope labels."""
    seen = {}
    for b in boards:
        seen.setdefault(b["board_id"], []).append(b)
    for bid, same in seen.items():
        if len(same) < 2:
            continue
        for b in same:
            label = b.get("experiment_arm") or b.get("cohort") or b.get("regimen") or b.get("scope_key") or b.get("key")
            b["board_id"] = bid + "/" + _slug(label)
        # Still identical (no distinguishing label): number them in their output order.
        again = {}
        for b in same:
            again.setdefault(b["board_id"], []).append(b)
        for bid2, rest in again.items():
            if len(rest) > 1:
                for n, b in enumerate(rest, 1):
                    b["board_id"] = f"{bid2}/{n}"
    return boards


def table_index(tables):
    return {t.get("dataset_id"): t for t in tables or [] if isinstance(t, dict) and t.get("dataset_id")}


# --------------------------------------------------------------- M5 (2026-11-24): guide question numbers and stable row ids
# Pages and text use the question numbers of each module's review guide. `q` stays the engine row id that the code and
# older readers use; every row also carries `qid` (stable id, never renumbered), `guide_q` (the guide question the row
# answers, empty when the guide has no question for it), `also_guide_q` (guide questions whose material the row shows
# without giving them a status), `legacy_q` (engine row numbers before the guide numbering) and `display_ref` (what the
# page prints). A guide question without an engine row is recorded on the board under `guide_coverage`.
GUIDE_QUESTIONS = {
    "absorption": {1: "Onset and peak sampling", 2: "Within-animal trough", 3: "Half-life and window choice",
                   4: "Immediate non-increasing input", 5: "Flip-flop kinetics", 6: "Systemic bioavailability",
                   7: "Dose proportionality", 8: "Shared one-compartment disposition", 9: "One multiplier between conditions"},
    "distribution": {1: "Could one compartment explain the IV decline?",
                     2: "How well do the observations support a change in slope?",
                     3: "Which late IV interval can serve as a reference for Absorption?",
                     4: "Do dose-normalized IV profiles differ across doses or conditions?",
                     5: "Which tissues reach the highest concentrations, and how long is drug measurable?",
                     6: "Does tissue exposure track plasma or blood?",
                     7: "Does repeated dosing change tissue and circulating concentrations to the same extent?",
                     8: "What do unbound measurements add to the exposure comparison?",
                     9: "Do reported volumes or half-lives differ across doses or conditions?"},
    "elimination": {1: "How much systemic exposure did the study observe?",
                    2: "Are the dose comparisons consistent with linear elimination, or is there evidence to investigate saturation?",
                    3: "Can carryover from earlier doses explain the repeated-dose profile?",
                    4: "How much parent was excreted unchanged in urine, and can renal clearance be assessed?",
                    5: "Which products were identified, how much was recovered, and what supports their formation?",
                    6: "Was unchanged parent recovered in bile, and which excretion routes can be compared?",
                    7: "Could protein binding explain a difference in total concentration or filtration?",
                    8: "Did drug delivered in bile return to the circulation?"},
}
# engine row id -> (stable id, guide question it answers or None, guide questions whose material it shows, page name when unnumbered)
ENGINE_ROWS = {
    "absorption": {1: ("onset_and_peak_sampling", 1, (), None), 2: ("within_animal_trough", 2, (), None),
                   3: ("half_life_and_window_choice", 3, (), None), 4: ("immediate_non_increasing_input", 4, (), None),
                   5: ("flip_flop_kinetics", 5, (), None), 6: ("systemic_bioavailability", 6, (), None),
                   7: ("dose_proportionality", 7, (), None), 8: ("shared_one_compartment_disposition", 8, (), None),
                   9: ("one_multiplier_between_conditions", 9, (), None)},
    "distribution": {1: ("systemic_disposition", 1, (), None),
                     4: ("systemic_shape_evidence", 2, (4,), None),
                     5: ("tissue_exposure", 6, (5, 7), None),
                     6: ("unbound_plasma_exposure", 8, (), None),
                     2: ("central_volume", None, (), "Vc bound"),
                     3: ("shared_iv_ev_disposition", None, (), "IV and EV routes"),
                     7: ("cross_species_transfer", None, (4, 9), "Across species")},
    "elimination": {1: ("observed_exposure", 1, (), None), 2: ("dose", 2, (), None), 3: ("repeated_dosing", 3, (), None),
                    5: ("urine", 4, (), None), 7: ("components_in_vitro_species", 5, (), None), 6: ("recovery", 6, (), None)},
}
# what the board record says for a guide question that no row answers
GUIDE_GAP_NOTES = {
    ("distribution", 3): "No row. The late IV interval is written to the iv_reference_window record that Absorption reads.",
    ("distribution", 4): "No row with its own status. IV dose series are shown under Q2 and condition overlays under Across species.",
    ("distribution", 5): "No row with its own status. Tissue concentrations over time (Figure 3a) are shown under Q6.",
    ("distribution", 7): "No row with its own status. Later/first ratios within each matrix (Figure 3c) are shown under Q6.",
    ("distribution", 9): "No row with its own status. Source-reported parameters are shown under Across species and in Table 3.",
    ("elimination", 7): "No row. Measured binding is read in Distribution (unbound plasma exposure).",
    ("elimination", 8): "No row. Bile-diversion and bile-transfer designs are not assessed by the engine.",
}
# Cross-module test ids (M5): the module that owns a test and what the test asks, so a reader keeps each test's meaning.
UPSTREAM_TESTS = {
    "absorption:T3": "Does dose-normalized exposure over the common window differ between doses?",
    "absorption:T3p": "Does the dose-normalized concentration differ at any matched time (Holm over the times)?",
    "absorption:T5": "Can one multiplier map one occasion's profile onto the other over the common window?",
    "distribution:T9": "Are later-dose concentrations no lower than first-dose concentrations at matched times?",
}


def guide_fields(section, engine_q):
    """The M5 fields of one question row, from its engine row id."""
    qid, guide, also, place = ENGINE_ROWS.get(section, {}).get(engine_q, (f"q{engine_q}", engine_q, (), None))
    return {"qid": qid, "guide_q": [guide] if guide else [], "also_guide_q": list(also),
            "display_number": guide, "display_ref": f"Q{guide}" if guide else place}


def guide_order(section, row):
    """Sort key: numbered rows in guide order, then unnumbered rows in their fixed order."""
    rows = ENGINE_ROWS.get(section, {})
    q = row.get("q") if isinstance(row, dict) else row
    spec = rows.get(q)
    if not spec:
        return (2, 0, str(q))
    if spec[1]:
        return (0, spec[1], "")
    return (1, list(rows).index(q), "")


def display_ref(section, engine_q):
    return guide_fields(section, engine_q)["display_ref"]


def question_key(section, row, board_id_value=None):
    """Stable reference to one question row: section:qid, or section:board:qid for one board."""
    qid = row.get("qid") if isinstance(row, dict) else ENGINE_ROWS.get(section, {}).get(row, (f"q{row}",))[0]
    if not qid:
        qid = f"q{row.get('q')}"
    return f"{section}:{board_id_value}:{qid}" if board_id_value is not None else f"{section}:{qid}"


def guide_coverage(section, questions):
    """One record per guide question: ROW (a row answers it), SHOWN_IN_ROW (material shown in a row without a status of its
    own) or NO_ENGINE_ROW. The last two are the recorded gaps (M5)."""
    out = []
    for n, ask in GUIDE_QUESTIONS.get(section, {}).items():
        rows = [q for q in questions or [] if n in (q.get("guide_q") or [])]
        shows = [q for q in questions or [] if n in (q.get("also_guide_q") or [])]
        if rows:
            out.append({"guide_q": n, "question": ask, "coverage": "ROW", "rows": [q.get("qid") for q in rows], "note": ""})
        else:
            out.append({"guide_q": n, "question": ask, "coverage": "SHOWN_IN_ROW" if shows else "NO_ENGINE_ROW",
                        "rows": [q.get("qid") for q in shows],
                        "note": GUIDE_GAP_NOTES.get((section, n), "No row answers this guide question.")})
    return out


def guide_gap_words(coverage):
    """One sentence for a page: the guide questions without a row of their own."""
    gaps = [c for c in coverage or [] if c["coverage"] != "ROW"]
    if not gaps:
        return ""
    return ("Guide questions without a row of their own: " + "; ".join(f"Q{c['guide_q']} ({c['note'][:-1] if c['note'].endswith('.') else c['note']})"
                                                                       for c in gaps) + ".")


# --------------------------------------------------------------- hypothesis v1
HYPOTHESIS_V1_FIELDS =("id", "section", "board_id", "text", "observation", "candidates", "alternatives",
                        "next_test", "rests_on", "missing", "checks", "state", "sha256")


def _strs(values):
    out = []
    for v in values or []:
        if v in (None, ""):
            continue
        if isinstance(v, dict):
            v = v.get("text") or v.get("label") or v.get("name") or json.dumps(v, ensure_ascii=False, sort_keys=True)
        out.append(str(v))
    return out


def hypothesis_v1(section, board_id_value, *, text, observation, candidates, alternatives, next_test,
                  question_numbers, missing, checks, state):
    """Common hypothesis record; sha256 covers every other field."""
    cands = []
    for c in candidates or []:
        if isinstance(c, dict):
            cands.append({"name": str(c.get("name") or ""),
                          "extra_parameters": [str(x) for x in (c.get("extra_parameters") or [])],
                          "must_show": str(c.get("must_show") or "")})
        else:
            cands.append({"name": str(c), "extra_parameters": [], "must_show": ""})
    record = {
        "id": f"{section}:{board_id_value}:H1",
        "section": section,
        "board_id": board_id_value,
        "text": str(text or ""),
        "observation": str(observation or ""),
        "candidates": cands,
        "alternatives": _strs(alternatives),
        "next_test": str(next_test or ""),
        # M5: a stable row id (qid) when the row has one; a bare number only for rows written before M5
        "rests_on": [f"{section}:{board_id_value}:" + (n if isinstance(n, str) else f"Q{n}") for n in question_numbers],
        "missing": _strs(missing),
        "checks": _strs(checks),
        "state": str(state or ""),
    }
    record["sha256"] = hashlib.sha256(json.dumps(record, sort_keys=True, ensure_ascii=False).encode("utf8")).hexdigest()
    return record


def question_number(question, index):
    """Q number of a board question: its own numeric id when it has one, else its position (1-based)."""
    for key in ("q", "number", "n", "qid", "id"):
        value = question.get(key) if isinstance(question, dict) else None
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            m = re.search(r"(\d+)", value)
            if m:
                return int(m.group(1))
    return index + 1


_ITEM = re.compile(r"\b(item\s?\d+[a-z]?|EM-\d+[a-z]?|DIS\d+[a-z]?)\b", re.I)


def rests_on_questions(questions, rests_text="", source_ids=(), explicit=None):
    """Q numbers a hypothesis rests on.

    Explicit numbers (absorption brief.qs) win; otherwise Qn written in the text, then
    the board rows whose evidence cites the same item codes or source table IDs.
    """
    numbers = [question_number(q, i) for i, q in enumerate(questions or [])]
    if explicit:
        return [int(n) for n in explicit]
    text = str(rests_text or "")
    direct = [int(n) for n in re.findall(r"\bQ(\d+)\b", text)]
    if direct:
        return list(dict.fromkeys(n for n in direct if n in numbers))
    codes = {re.sub(r"\s+", " ", c.lower()) for c in _ITEM.findall(text)}
    ids = {s for s in source_ids or [] if s}
    found = []
    for q, n in zip(questions or [], numbers):
        blob = json.dumps(q.get("evidence") or [], ensure_ascii=False)
        low = re.sub(r"\s+", " ", blob.lower())
        hit = any(re.search(r"\b" + re.escape(c) + r"\b", low) for c in codes)
        hit = hit or any(i in blob for i in ids)
        if hit:
            found.append(n)
    return found


def _ladder_candidates(rows, with_params):
    out = []
    for row in rows or []:
        row = [str(x) for x in row]
        if not row:
            continue
        name = f"{row[0]}: {row[1]}" if len(row) > 1 else row[0]
        if with_params:
            extra = [] if len(row) < 3 or row[2] in ("—", "-", "") else [row[2]]
            must = row[3] if len(row) > 3 else ""
        else:
            extra, must = [], row[2] if len(row) > 2 else ""
        out.append({"name": name, "extra_parameters": extra, "must_show": must})
    return out


def _alt_names(candidates):
    return [c["name"].split(": ", 1)[-1] for c in candidates if c["name"].startswith("Alt")]


def _row_ids(questions, numbers):
    """M5 / L3: rests_on names rows by their stable id, so a reader cannot resolve a number against another numbering."""
    ids = {question_number(q, i): q.get("qid") for i, q in enumerate(questions or []) if isinstance(q, dict)}
    return [ids.get(n) or n for n in numbers]


def hypothesis_v1_for(section, board, bid):
    """Fill hypothesis_v1 from a section's own hypothesis fields (the old 'hypothesis' stays as an alias)."""
    h = board.get("hypothesis")
    if not isinstance(h, dict):
        return None
    questions = board.get("questions") or []
    if section == "absorption":
        primary = h.get("primary") or {}
        rows = primary.get("rows") if (primary.get("head") or [None])[0] == "Step" else []
        candidates = _ladder_candidates(rows, True)
        brief = h.get("brief") or {}
        alternatives = _alt_names(candidates) + _strs(h.get("alternatives"))
        alternatives += [" or ".join(map(str, pair)) for pair in brief.get("either") or [] if pair]
        alternatives += _strs(brief.get("deferred")) + _strs(brief.get("readings"))
        nxt = brief.get("next")
        next_test = (f"{nxt[0]}: {nxt[1]} ({nxt[2]})" if isinstance(nxt, list) and len(nxt) >= 3 else
                     " ".join(map(str, nxt)) if isinstance(nxt, list) else str(nxt or ""))
        if not next_test:
            steps = [c for c in candidates if not c["name"].startswith(("M0", "Alt"))]
            if steps:
                next_test = f"{steps[0]['name']}; the fit has to show {steps[0]['must_show']}"
            elif h.get("checks_before_modelling"):
                first = h["checks_before_modelling"][0]
                next_test = first.get("text") if isinstance(first, dict) else str(first)
        checks = [c.get("text") if isinstance(c, dict) else c for c in h.get("checks_before_modelling") or []]
        checks += [c.get("detail") or c.get("check") for c in h.get("checks") or []
                   if isinstance(c, dict) and c.get("result") not in (None, "PASS")]
        rests = rests_on_questions(questions, h.get("rests_on"), explicit=brief.get("qs"))
        observation = re.sub(r"^(This rests on|The observations remain descriptive:)\s*", "", str(h.get("rests_on") or ""))
        for q in questions:
            if q.get("reported_condition_comparisons") or q.get("observed_individual_ranges"):
                observation = " ".join(filter(None, [observation, q["observed"]]))
                rests = sorted(set(rests) | {q["q"]})
        return hypothesis_v1(section, bid, text=h.get("text"), observation=observation, candidates=candidates,
                             alternatives=list(dict.fromkeys(a for a in alternatives if a)), next_test=next_test,
                             question_numbers=_row_ids(questions, rests), missing=h.get("missing"), checks=checks, state=h.get("state"))
    if section == "distribution":
        candidates = _ladder_candidates(h.get("ladder"), False)
        steps = [c for c in candidates if not c["name"].startswith(("M0", "Alt"))]
        next_test = (h.get("check_first") or [None])[0] or (
            f"{steps[0]['name']}; the fit has to show {steps[0]['must_show']}" if steps else "")
        observation = " ".join(f"{l.get('label')}: {l.get('text')}" for l in h.get("lines") or [] if isinstance(l, dict))
        ids = board.get("datasets") or []
        rests = rests_on_questions(questions, h.get("rests_on"), source_ids=ids)
        return hypothesis_v1(section, bid, text=h.get("text"), observation=observation or h.get("text"),
                             candidates=candidates, alternatives=_alt_names(candidates), next_test=next_test,
                             question_numbers=_row_ids(questions, rests), missing=h.get("missing"), checks=h.get("check_first"),
                             state=h.get("state"))
    # elimination
    kind = str(h.get("kind") or "")
    state = h.get("state") or ("PENDING" if "pending" in kind.lower() else kind.upper())
    rests = rests_on_questions(questions, h.get("rests_on"), source_ids=h.get("source_ids"))
    alternatives = [h["alternative"]] if h.get("alternative") else []
    return hypothesis_v1(section, bid, text=h.get("text"), observation=h.get("observation"), candidates=[],
                         alternatives=alternatives, next_test=h.get("next_test"), question_numbers=_row_ids(questions, rests),
                         missing=h.get("missing"), checks=h.get("check_first"), state=state)


def annotate_section(section, result, root):
    """Add board_id, design and hypothesis_v1 to every board of one section result, in place."""
    tables = json.loads((Path(root) / "source_tables.json").read_text(encoding="utf-8-sig"))
    by_id = table_index(tables)
    boards = result.get(BOARD_LIST[section]) or []
    for b in boards:
        qualifier = (b.get("experiment_arm") or b.get("cohort")) if section == "absorption" else None
        annotate_board(b, by_id, b.get("datasets") or [], qualifier=qualifier)
    disambiguate(boards)
    for b in boards:
        # M5: every row carries its stable id and guide number; the board records guide questions without a row
        for q in b.get("questions") or []:
            if isinstance(q, dict) and "q" in q and "qid" not in q:
                fields = guide_fields(section, q["q"])
                fields.pop("display_number") if "display_number" in q else None
                q.update(fields)
                q.setdefault("legacy_q", [q["q"]])
        b["guide_coverage"] = guide_coverage(section, b.get("questions"))
    for b in boards:
        v1 = hypothesis_v1_for(section, b, b["board_id"])
        if v1 is not None:
            b["hypothesis_v1"] = v1
    return boards


# --------------------------------------------------------------- input coverage
SECTIONS = ("absorption", "distribution", "elimination")
BOARD_LIST = {"absorption": "status_boards", "distribution": "boards", "elimination": "boards"}
# Roles each section has questions for.
SECTION_ROLES = {
    "absorption": {"PK_OBSERVATIONS", "REPORTED_PARAMETERS"},
    "distribution": {"PK_OBSERVATIONS", "REPORTED_PARAMETERS", "BINDING", "TISSUE_DISTRIBUTION"},
    "elimination": {"PK_OBSERVATIONS", "REPORTED_PARAMETERS", "URINE_EXCRETION", "FECES_EXCRETION",
                    "BILE_EXCRETION", "MASS_BALANCE", "EXCRETION", "METABOLISM_IN_VITRO", "IN_VITRO"},
}
REASONS = ("NOT_PK_ROLE", "NO_QUESTION_FOR_TYPE", "GATED_OUT", "DESIGN_NOT_SUPPORTED", "UNKNOWN")
STRUCTURAL_REASONS = ("NOT_PK_ROLE", "NO_QUESTION_FOR_TYPE")


def _skip_reason(result, dataset_id):
    """Gate named by a module's own 'skipped' list for this dataset, if any."""
    skipped = result.get("skipped") or []
    if isinstance(skipped, dict):
        skipped = [dict(v, dataset_id=k) if isinstance(v, dict) else {"dataset_id": k, "reason": v}
                   for k, v in skipped.items()]
    for row in skipped:
        if not isinstance(row, dict):
            continue
        ident = row.get("dataset_id") or row.get("id") or row.get("dataset")
        if ident == dataset_id:
            gate = row.get("gate") or row.get("reason") or row.get("code") or "SKIPPED"
            return _slug(gate).upper().replace("-", "_")[:60]
    return None


def _mentions(obj, ids, found):
    if isinstance(obj, dict):
        for v in obj.values():
            _mentions(v, ids, found)
    elif isinstance(obj, list):
        for v in obj:
            _mentions(v, ids, found)
    elif isinstance(obj, str) and obj in ids:
        found.add(obj)
    return found


def _type_supported(section, table):
    md = table.get("metadata") or {}
    route_class = str(md.get("route_class") or "").upper()
    category = str(md.get("matrix_category") or "").upper()
    matrix = str(md.get("matrix") or "").upper()
    if section == "absorption":
        # Absorption boards are extravascular inputs; IV curves serve only as module-level references.
        return route_class != "IV"
    if section == "elimination" and table.get("role") in ("PK_OBSERVATIONS", None):
        # Elimination reads systemic plasma/serum/blood; tissue and CSF concentrations have no elimination row.
        return category in ("", "PLASMA_SERUM_BLOOD") and "CSF" not in matrix
    return True


def _assay_gate(section, result, table):
    """Elimination reads parent drug; a non-specific assay (config or metadata) keeps a table off its boards."""
    if section != "elimination":
        return None
    md = table.get("metadata") or {}
    assay = str(md.get("assay") or "").upper()
    rule = ((result.get("config_used") or {}).get("assay_by_dataset") or {}).get(table.get("dataset_id"))
    if isinstance(rule, dict) and rule.get("assay"):
        assay = str(rule["assay"]).upper()
    role = str(md.get("analyte_role") or "").upper()
    if assay and assay not in ("SPECIFIC", "SELECTIVE", "LC-MS/MS", "HPLC"):
        return "ASSAY_" + _slug(assay).upper().replace("-", "_")
    if role and role not in ("PARENT",) and table.get("role") == "PK_OBSERVATIONS":
        return "ANALYTE_" + role
    return None


def _design_on_boards(section, result, table, by_id):
    """True when some board of the same study and species in this section already carries the table's design."""
    md = table.get("metadata") or {}
    studies = set(table.get("study_source_ids") or [])
    species = species_group_of(md.get("species")).lower()
    design = design_of(table)
    peers = [b for b in result.get(BOARD_LIST[section]) or []
             if species_group_of(b.get("species_group") or b.get("species")).lower() == species
             and (not studies or b.get("study") in studies)]
    if not peers:
        return True  # no board for this study/species at all: not a design question
    for b in peers:
        designs = {design_of(by_id[i]) for i in b.get("datasets") or [] if i in by_id}
        if design in designs:
            return True
    return False


def _section_unused_reason(section, result, table, by_id):
    role = str(table.get("role") or "").upper()
    if role not in SECTION_ROLES[section]:
        return "NOT_PK_ROLE"
    gate = _skip_reason(result, table.get("dataset_id"))
    if gate:
        return "GATED_OUT:" + gate
    if not _type_supported(section, table):
        return "NO_QUESTION_FOR_TYPE"
    gate = _assay_gate(section, result, table)
    if gate:
        return "GATED_OUT:" + gate
    design = design_of(table)
    if section == "absorption" and design in (LOADING_PLUS_INFUSION, INFUSION):
        return "DESIGN_NOT_SUPPORTED"
    if not _design_on_boards(section, result, table, by_id):
        return "DESIGN_NOT_SUPPORTED"
    return "UNKNOWN"


def input_coverage(tables, results):
    """coverage.json body: per dataset, the boards that use it in each section or an unused reason."""
    ids = [t.get("dataset_id") for t in tables if isinstance(t, dict) and t.get("dataset_id")]
    by_id = table_index(tables)
    datasets = []
    for dataset_id in ids:
        table = by_id[dataset_id]
        md = table.get("metadata") or {}
        entry = {"dataset_id": dataset_id, "role": table.get("role"), "design": design_of(table),
                 "species": md.get("species"), "route": md.get("route"),
                 "dosing_regimen": md.get("dosing_regimen"), "sections": {}}
        for section in SECTIONS:
            result = results.get(section)
            if result is None:
                entry["sections"][section] = {"status": "unused", "reason": "UNKNOWN", "detail": "section not run"}
                continue
            boards = [b for b in result.get(BOARD_LIST[section]) or [] if dataset_id in (b.get("datasets") or [])]
            if boards:
                entry["sections"][section] = {"status": "used",
                                              "boards": [b.get("board_id") or b.get("key") or b.get("study") for b in boards]}
                continue
            outside = bool(_mentions({k: v for k, v in result.items() if k != BOARD_LIST[section]}, {dataset_id}, set()))
            row = {"status": "unused", "reason": _section_unused_reason(section, result, table, by_id)}
            if outside:
                row["referenced_outside_boards"] = True
            entry["sections"][section] = row
        used_any = any(s["status"] == "used" for s in entry["sections"].values())
        entry["status"] = "used" if used_any else "unused"
        datasets.append(entry)
    summary = {
        "datasets": len(datasets),
        "used_any_section": sum(d["status"] == "used" for d in datasets),
        "unused_all_sections": [d["dataset_id"] for d in datasets if d["status"] == "unused"],
        "unused_by_section": {s: {d["dataset_id"]: d["sections"][s]["reason"] for d in datasets
                                  if d["sections"][s]["status"] == "unused"} for s in SECTIONS},
    }
    return {"version": "EDA_INPUT_COVERAGE_1", "reason_codes": list(REASONS), "summary": summary, "datasets": datasets}


def write_coverage(out):
    """Write <out>/coverage.json from the run's source tables and the three section JSON files."""
    out = Path(out)
    tables = json.loads((out / "source_tables.json").read_text(encoding="utf8"))
    results = {}
    for section in SECTIONS:
        path = out / section / (section + ".json")
        if path.is_file():
            results[section] = json.loads(path.read_text(encoding="utf8"))
    body = input_coverage(tables, results)
    (out / "coverage.json").write_text(json.dumps(body, indent=2, ensure_ascii=False), encoding="utf8")
    return body


def coverage_table_html(coverage):
    """Short 'Input coverage' table for the portal overview: unused datasets only."""
    from html import escape
    rows = []
    structural = 0
    for d in coverage["datasets"]:
        unused = [(s, d["sections"][s]["reason"]) for s in SECTIONS if d["sections"][s]["status"] == "unused"]
        if not unused:
            continue
        # A role or type a section has no question for is expected; list it only when no section uses the table.
        notable = [(s, r) for s, r in unused if r not in STRUCTURAL_REASONS]
        if d["status"] == "used" and not notable:
            structural += 1
            continue
        unused = unused if d["status"] == "unused" else notable
        used = [s for s in SECTIONS if d["sections"][s]["status"] == "used"]
        rows.append("<tr><td><code>{}</code></td><td>{}</td><td>{}</td><td>{}</td></tr>".format(
            escape(d["dataset_id"]), escape(str(d.get("role") or "")),
            escape(", ".join(used) or "none"),
            "<br>".join(escape(f"{s}: {r}") for s, r in unused)))
    summary = coverage["summary"]
    intro = (f'{summary["datasets"]} input tables, {summary["used_any_section"]} used by at least one section. '
             f'{structural} of them are not used in some sections simply because those sections do not ask about that kind of data; '
             'the reasons are listed in <a href="coverage.json">coverage.json</a>.')
    if not rows:
        body = "<p>No input table is unused for any other reason.</p>"
    else:
        body = ("<table class=\"coverage tbl\"><thead><tr><th>Dataset</th><th>Role</th><th>Used in</th>"
                "<th>Not used (reason)</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table>")
    return '<section id="input-coverage"><h2>Input coverage</h2><p>' + intro + "</p>" + body + "</section>"


# ---------------------------------------------------------------------------------------------------------------------------
# S13 rule 9 (George 2026-11-25): one standard figure title that says which data are drawn and what is plotted.
#   "<Species> · <route> · <profile or group> (<dose>[, <input>]) — <y quantity> vs time, <linear|semi-log>"
#   Non-time plots name both quantities: "<Species> · <route> · <group> — Tmax and Cmax/D by animal".
#   No panel codes, no questions, no test names.
def _g3(x):
    return f"{x:.3g}" if isinstance(x, (int, float)) and not isinstance(x, bool) else str(x)


def input_text(mode=None, infusion_h=None):
    """Plain input description for a title: '2-min infusion', '1.5-h infusion', 'bolus', or '' when nothing is known."""
    if infusion_h:
        m = infusion_h * 60
        return f"{m:.2g}-min infusion" if m < 60 else f"{infusion_h:.2g}-h infusion"
    if mode in ("INFUSION_TIMING_UNKNOWN", "UNKNOWN"):
        return "infusion length not reported"
    if mode == "BOLUS":
        return "bolus"
    return ""


def _species_word(s):
    s = str(s or "").strip()
    return "" if not s or s.upper() == "NOT_FOUND" else s[:1].upper() + s[1:]


def _clean(x):
    x = str(x or "").strip()
    return "" if x.upper() in ("NOT_FOUND", "NONE", "NOT REPORTED") else x


def std_title(species=None, route=None, who=None, dose=None, input_txt="", what="concentration", scale=None, matrix=None,
              vs="time", part=None):
    """Build the standard title. `dose` is a number (mg/kg) or a ready text (e.g. a range); `what` is the plotted quantity;
    `vs` the x quantity (None for a non-time plot whose `what` already names both)."""
    head = " · ".join(p for p in (_species_word(species), _clean(route), _clean(who)) if p)
    dose_s = (f"{_g3(dose)} mg/kg" if isinstance(dose, (int, float)) and not isinstance(dose, bool) and dose > 0
              else _clean(dose))
    br = ", ".join(p for p in (dose_s, input_txt) if p)
    if br:
        head += f" ({br})"
    m = _clean(matrix).lower()
    q = what
    if what == "concentration" and m:
        q = f"{m} concentration"
    tail = q + (f" vs {vs}" if vs else "") + (f", {scale}" if scale else "") + (f", {part}" if part else "")
    return f"{head} — {tail}" if head else tail[:1].upper() + tail[1:]


TITLE_CODE = re.compile(r"\b(?:DIS-?\d[a-z]?|EM-\d[a-z]?|A[1-9](?:w|ind)?|B[12](?:ind)?|T[1-9]p?|Q[1-9]b?|D1[a-d]?|E[1-9])\b"
                        r"|\?|\bTable \d|\bitem \d|\b[A-Z]+_[A-Z_]+\b|λ|\bz\b")


def title_problems(title):
    """S13 rule 9 check: codes, questions or test names in a title."""
    return TITLE_CODE.findall(str(title or ""))


# ------------------------------------------------------------------------------------------------
# Plain readings (shared rule 10, s1.0)
# Plain readings (shared rule 10, s1.0): two human-readable sentences per question.
# 
# Sentence 1 says what the plot shows; sentence 2 gives the PK modelling suggestion. Animal counts are allowed
# ("all 6 horses", "4 of 11 rats"); beyond them a pair carries at most one number, and only when it changes a
# modelling choice (for example a starting value). Ratios, z, tolerances, noise settings and test labels stay in the
# "Numbers behind this" block of the report and in the JSON.
# 
# The wording is built only from the tool's own results (statuses, per-curve readings, counts); it carries no
# knowledge of any compound.
# ------------------------------------------------------------------------------------------------
import statistics as _pl_statistics

_pl_IRREGULAR = {"mouse": "mice", "sheep": "sheep", "cattle": "cattle", "fish": "fish", "deer": "deer", "swine": "pigs",
              "goose": "geese", "calf": "calves", "ox": "oxen", "bison": "bison"}


def _pl_plural(species, individual=True):
    """Plural noun for the animals of one species; 'profiles' when the curves are not single animals."""
    if not individual:
        return "group profiles"
    w = str(species or "").strip().lower()
    if not w or w == "not_found" or not re.fullmatch(r"[a-z][a-z \-]*", w):
        return "animals"
    last = w.split()[-1]
    if last in _pl_IRREGULAR:
        return w[: len(w) - len(last)] + _pl_IRREGULAR[last]
    if last.endswith(("s", "x", "ch", "sh")):
        return w + "es"
    if last.endswith("y") and last[-2:-1] not in "aeiou":
        return w[:-1] + "ies"
    return w + "s"


def _pl_singular(noun):
    m = re.search(r" after | \(", noun)
    if m:   # "pigs after IV dosing" -> "pig after IV dosing"
        return _pl_singular(noun[:m.start()]) + noun[m.start():]
    back = {v: k for k, v in _pl_IRREGULAR.items() if k != "swine"}
    last = noun.split()[-1]
    if last in back:
        return noun[: len(noun) - len(last)] + back[last]
    if noun.endswith("ies"):
        return noun[:-3] + "y"
    if noun.endswith(("ses", "xes", "ches", "shes")):
        return noun[:-2]
    return noun[:-1] if noun.endswith("s") else noun


def _pl_count(k, n, noun):
    if n == 1:
        return ("the one " if k else "no ") + _pl_singular(noun)
    if k == n:
        return f"all {n} {noun}"
    if k == 0:
        return f"none of the {n} {noun}"
    if k == 1:
        return f"one of the {n} {noun}"
    return f"{k} of {n} {noun}"


def _pl_word(k):
    """Small counts as words, so they do not read as measured numbers."""
    return ("no", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten")[k] if 0 <= k <= 10 else str(k)


def _pl_verb(k, n, verb):
    """Agree a plural verb with a counted subject: 'one of the 6 horses shows'."""
    if k == 1 or n == 1:
        return {"have": "has", "do": "does"}.get(verb, verb + "s")
    return verb


_PL_ROUTE = {"PO": "oral", "ORAL": "oral", "IM": "IM", "SC": "SC", "SQ": "SC", "IP": "IP", "TOPICAL": "topical", "RECTAL": "rectal",
             "INTRANASAL": "intranasal", "INHALED": "inhaled", "TRANSDERMAL": "transdermal"}


def _pl_route(ds):
    r = {str((d.get("card") or {}).get("route_detail") or "").strip().upper() for d in ds}
    r.discard("")
    if len(r) == 1:
        x = r.pop()
        return _PL_ROUTE.get(x, "non-IV")
    return "non-IV"


def _pl_cap(s):
    return s[:1].upper() + s[1:] if s else s


def _pl_g2(x):
    """A number in plain form: two significant figures."""
    x = float(x)
    if x == 0:
        return "0"
    s = f"{x:.2g}"
    if "e" in s:
        s = f"{x:.2f}"
    return s


def _pl_pair(shows, suggests):
    return {"shows": _pl_cap(shows.strip()), "suggests": _pl_cap(suggests.strip())}


_pl_FALLBACK = {
    "NOT_APPLICABLE": ("This question does not apply to the data in this study.", "Nothing to add to the model for this question."),
    "NOT_ANSWERABLE_YET": ("The data in this package cannot answer this question yet.",
                           "Keep the simplest model for this part until better data are available."),
}


def _pl_fallback(q):
    a, b = _pl_FALLBACK.get(q.get("status_code"), ("The plot is described in the numbers below.", "No specific modelling change is suggested."))
    return _pl_pair(a, b)


# ---------------------------------------------------------------------------------------------------- absorption

def _pl_curves(ds):
    return [s for d in ds for s in d.get("series", []) if "tmax" in (s.get("metrics") or {})]


def _pl_individual(ds):
    return bool(ds) and all(str(d["card"].get("record_level", "")).startswith("INDIVIDUAL") for d in ds)


def plain_absorption(b, ds, tol=0.05, n_iv=0):
    """{q number: {"shows", "suggests"}} for one absorption status board, plus "H" for the working hypothesis."""
    curves = _pl_curves(ds)
    n = len(curves)
    noun = _pl_plural(b.get("species_group") or b.get("species"), _pl_individual(ds))
    hyp = (b.get("hypothesis") or {}).get("components") or {}
    out = {}
    for q in b.get("questions", []):
        f = _pl_ABS.get(q["q"])
        r = None
        if f and (q.get("status_code") != "NOT_APPLICABLE" or f in (_pl_a5, _pl_a6, _pl_a7, _pl_a8, _pl_a9)):
            try:
                r = f(q, curves, n, noun, hyp, ds, tol, n_iv)
            except (KeyError, TypeError, ValueError, _pl_statistics.StatisticsError):
                r = None
        out[q["q"]] = r or _pl_fallback(q)
    out["H"] = _pl_ah(b, curves, n, noun, hyp, tol, ds)
    return out


def _pl_a1(q, curves, n, noun, hyp, ds, tol, n_iv):
    if not n:
        return None
    late = sum(1 for s in curves if s["metrics"].get("onset_status") == "ONSET_NOT_OBSERVED")
    if late == n:
        shows = f"Drug is already measurable at the first sample in {_pl_count(n, n, noun)}, so the rise from zero was not captured."
    elif late:
        shows = f"Drug is already measurable at the first sample in {_pl_count(late, n, noun)}; in the others the rise from zero is sampled."
    else:
        shows = f"The rise from zero to the peak is sampled in {_pl_count(n, n, noun)}."
    if late:
        sug = "Start with first-order absorption and no lag time; expect the absorption rate to be poorly defined, because the early rise was not sampled."
    else:
        sug = "Fit first-order absorption; add a lag time only if the samples before the rise stay at zero."
    return _pl_pair(shows, sug)


def _pl_t2(s):
    return s.get("t2") or {}


DIP_MIN_AFTER_PEAK = 3   # a fall, a dip and a rise need at least three samples after the peak (George 2026-11-26)


def _pl_after_peak(s):
    m = s.get("metrics") or {}
    nq, nb = m.get("n_quantified"), m.get("n_before_peak")
    return nq - nb - 1 if isinstance(nq, int) and isinstance(nb, int) else None


def _pl_a2(q, curves, n, noun, hyp, ds, tol, n_iv):
    if not n:
        return None
    v = sum(1 for s in curves if _pl_t2(s).get("valley") is not None)
    r = sum(1 for s in curves if _pl_t2(s).get("valley") is not None and _pl_t2(s).get("robust"))
    if not v:
        few = sum(1 for s in curves if _pl_after_peak(s) is not None and _pl_after_peak(s) < DIP_MIN_AFTER_PEAK)
        if few == n:
            return _pl_pair(f"In {_pl_count(n, n, noun)} there are too few samples after the peak to show a dip and a second rise.",
                            "Start with one absorption input, and note that a second input cannot be ruled out from these samples.")
        if few:
            return _pl_pair(f"None of the curves that could be checked show a dip and a second rise; in {_pl_count(few, n, noun)} there are too "
                            "few samples after the peak to check.",
                            "Start with one absorption input; a second input is not ruled out in the animals that could not be checked.")
        return _pl_pair(f"{_pl_count(0, n, noun)} show a dip and a second rise after the first peak.",
                        "Start with one absorption input; the samples after the peak show no sign of a second one.")
    if r:
        shows = f"{_pl_count(r, n, noun)} {_pl_verb(r, n, 'show')} a clear dip followed by a second rise after the first peak" + (
            f"; in {_pl_word(v - r)} more it rests on a single sample" if v > r else "") + "."
        if hyp.get("second") in ("two_inputs", "recirculation"):
            sug = "Keep one first-order input as the reference fit, and test a second input episode (or enterohepatic recycling) as the alternative."
        else:
            sug = "Keep one first-order input; add a second input only if the second rise repeats across animals."
        return _pl_pair(shows, sug)
    return _pl_pair(f"{_pl_count(v, n, noun)} {_pl_verb(v, n, 'show')} a dip and a second rise, but each rests on a single sample.",
                "Treat it as possible noise and keep one first-order input.")


def _pl_a3(q, curves, n, noun, hyp, ds, tol, n_iv):
    if not n:
        return None
    th = [((s["metrics"].get("terminal_selected") or {}).get("thalf")) for s in curves]
    th = [x for x in th if isinstance(x, (int, float)) and x > 0]
    if not th:
        return _pl_pair(f"{_pl_cap(_pl_count(0, n, noun))} have a late straight-line part long enough to read a half-life.",
                    "Take the terminal half-life from the IV data, not from these curves.")
    return _pl_pair(f"{_pl_count(len(th), n, noun)} {_pl_verb(len(th), n, 'show')} a straight late decline on the semi-log plot, with an apparent half-life of about "
                f"{_pl_g2(_pl_statistics.median(th))} h.",
                "Use it only as a starting value, and compare it with the IV half-life before reading elimination from it.")


def _pl_a4(q, curves, n, noun, hyp, ds, tol, n_iv):
    if not n:
        return None
    up = sum(1 for s in curves if isinstance(s["metrics"].get("mt1"), (int, float)) and s["metrics"]["mt1"] > tol)
    if not up:
        if all(s["metrics"].get("onset_status") == "ONSET_NOT_OBSERVED" for s in curves):   # nothing sampled before the rise
            return _pl_pair(f"In {_pl_count(n, n, noun)} drug is already measurable at the first sample, so the early samples cannot show a delayed start.",
                            "Start without a lag time, and note that a delay cannot be ruled out from these samples.")
        return _pl_pair(f"In {_pl_count(n, n, noun)} the early samples are consistent with absorption starting at the time of dosing.",
                    "Do not add a lag time or transit compartments.")
    return _pl_pair(f"In {_pl_count(up, n, noun)} the early samples rise faster than a plain first-order start allows.",
                "Try a lag time or a short transit chain, and keep it only if it clearly improves the fit.")


def _pl_a5(q, curves, n, noun, hyp, ds, tol, n_iv):
    reads = [((d.get("group_flip_flop") or {}).get("flip_flop_reading")) for d in ds]
    obs = (q.get("observed") or "").lower()
    if hyp.get("tail") == "absorption" or "ABSORPTION_INFLUENCED_CANDIDATE" in reads or "absorption-influenced" in obs:
        return _pl_pair(f"After {_pl_route(ds)} dosing the decline after the peak is much slower than the decline after IV dosing.",
                    "Suspect flip-flop kinetics: the late slope may reflect slow absorption, so do not read elimination from it and fit together with the IV data.")
    if "COMMON_TERMINAL_COMPATIBLE" in reads or "common terminal compatible" in obs:
        return _pl_pair("The decline after the peak runs about as fast as the decline after IV dosing.",
                    "Read elimination from the shared late slope; absorption is faster than elimination.")
    return _pl_pair("No IV curve can be matched to these animals, so the late decline cannot be checked against IV." if n_iv
                else "There is no IV curve to compare the late decline with.",
                "Do not read elimination from the late slope alone; fit these curves together with IV data when they are available.")


def _pl_a6(q, curves, n, noun, hyp, ds, tol, n_iv):
    if q.get("status_code") == "ANSWERABLE":
        return _pl_pair("Bioavailability can be computed from IV and non-IV curves in the same animals.",
                    "Use it as the starting value for F in a joint fit of the IV and non-IV data.")
    if not n_iv:
        return _pl_pair("There are no IV data, so bioavailability cannot be computed.",
                    "Fix F from the literature, or estimate it in a joint fit once IV data are available.")
    rt = _pl_route(ds)
    return _pl_pair(f"Bioavailability is not computed, because the source does not confirm that the IV and {rt} doses were given to the same animals on separate occasions.",
                f"Estimate F in a joint fit of the IV and {rt} data.")


def _pl_a7(q, curves, n, noun, hyp, ds, tol, n_iv):
    sc = q.get("status_code")
    if sc == "NOT_APPLICABLE":
        return _pl_pair("Only one dose level was given, so dose proportionality cannot be checked.", "Use linear kinetics as a working assumption, not as a finding.")
    if sc == "NOT_ANSWERABLE_YET":
        return _pl_pair("The dose levels cannot be compared cleanly in these data.", "Use linear kinetics as a working assumption until a clean dose comparison is available.")
    if hyp.get("dose", "linear") == "linear":
        return _pl_pair("Exposure rises in step with dose across the doses given.", "Keep one linear model for all doses.")
    return _pl_pair("Exposure does not rise in step with dose.", "Test a dose-dependent absorption term before fitting all doses with one model.")


def _pl_a8(q, curves, n, noun, hyp, ds, tol, n_iv):
    sc = q.get("status_code")
    if sc == "NOT_APPLICABLE" or not n_iv:
        return _pl_pair("There is no IV curve to compare these curves with.", "Estimate absorption and disposition from these curves alone, and expect them to trade off.")
    obs = (q.get("observed") or "").lower()
    if sc in ("ANSWERABLE", "PARTLY_ANSWERABLE") and "compatible" in obs and "not compatible" not in obs:
        return _pl_pair("The non-IV curves decline in line with the IV disposition.", "Share the disposition parameters between routes and estimate only absorption on top.")
    if sc in ("ANSWERABLE", "PARTLY_ANSWERABLE") and ("differ" in obs or "not compatible" in obs):
        return _pl_pair("The non-IV curves do not decline in line with the IV disposition.", "Check for flip-flop or a route-specific disposition before sharing parameters between routes.")
    return _pl_pair(f"The {_pl_route(ds)} curves cannot be checked against the IV disposition from these data.",
                "Take the disposition from the IV data and estimate only absorption on top of it.")


def _pl_a9(q, curves, n, noun, hyp, ds, tol, n_iv):
    if q.get("status_code") in ("NOT_APPLICABLE", "NOT_ANSWERABLE_YET"):
        if q.get("status_code") == "NOT_APPLICABLE":
            return _pl_pair("All curves in this study come from one route and one condition.", "No condition effect is needed in the model.")
        return _pl_pair("The conditions in this study cannot be compared cleanly.",
                        "A condition effect cannot be judged from these data; leave it out unless other data point to one.")
    return _pl_pair("The curves under the different conditions are compared in the plot.", "Test a condition effect on F or on the absorption rate, and keep it only if the fit needs it.")


_pl_ABS = {1: _pl_a1, 2: _pl_a2, 3: _pl_a3, 4: _pl_a4, 5: _pl_a5, 6: _pl_a6, 7: _pl_a7, 8: _pl_a8, 9: _pl_a9}

_pl_H_SIGNAL = {"onset": "a delayed start", "second": "a second rise after the first peak", "tail": "a slow late decline set by absorption",
             "dose": "exposure that does not follow dose", "shape": "an input shape other than first order"}
_pl_H_TEST = {"fixed_lag": "a lag time", "transit": "transit compartments", "variable_lag": "between-animal variability in the delay",
           "two_inputs": "a second input episode", "recirculation": "enterohepatic recycling", "absorption": "flip-flop kinetics",
           "zero_order": "zero-order input", "zero_then_first": "zero-order then first-order input", "parallel_first": "two parallel inputs",
           "parallel_zero_first": "parallel zero- and first-order input", "weibull_front": "a Weibull input", "weibull_sigmoid": "a Weibull input",
           "inverse_gaussian": "an inverse Gaussian input", "saturable_rate": "saturable absorption", "extent_down": "F falling with dose",
           "extent_up": "F rising with dose"}
_pl_DEFAULT = {"onset": "immediate", "shape": "first_order", "second": "none", "tail": "disposition", "dose": "linear"}


def _pl_ah(b, curves, n, noun, hyp, tol, ds=()):
    if not b.get("hypothesis"):
        return None
    extra = [(a, hyp[a]) for a in ("onset", "shape", "second", "tail", "dose") if hyp.get(a) and hyp[a] != _pl_DEFAULT[a]]
    if hyp.get("tail") != "absorption" and any((d.get("group_flip_flop") or {}).get("flip_flop_reading") == "ABSORPTION_INFLUENCED_CANDIDATE" for d in ds):
        extra.append(("tail", "absorption"))
    if not n:
        return _pl_ah_notes(_pl_pair("These data hold no full concentration–time curves after non-IV dosing.",
                                     "Take the absorption model from the literature or from the reported parameters."), _pl_ranked(b))
    rc = _pl_ranked(b)
    sup = [c for c in rc if c["group"] == "SUPPORTED"]
    if not extra and not sup:
        p = _pl_pair("Taken together, the curves show nothing with direct support beyond a simple rise, peak and decline."
                     if any(c["group"] == "INDIRECT_SUPPORT" for c in rc) else "Taken together, the curves show nothing beyond a simple rise, peak and decline.",
                     "Start with one first-order absorption input from the time of dosing; no other input model has direct support in these data.")
        return _pl_ah_notes(p, rc)
    sig = [_pl_H_SIGNAL[a] for a, _ in extra]
    if any(a == "second" for a, _ in extra):   # George 2026-11-25: say in how many animals, and that it is not the next dose
        v = sum(1 for s in curves if _pl_t2(s).get("valley") is not None)
        r = sum(1 for s in curves if _pl_t2(s).get("valley") is not None and _pl_t2(s).get("robust"))
        multi = any(s.get("first_interval_end_h") for s in curves)
        if v:
            sig[[a for a, _ in extra].index("second")] = (f"a second rise after the first peak in {_pl_count(r or v, n, noun)}"
                                                         + (", before the second dose," if multi else ""))
    tests = list(dict.fromkeys([_pl_H_TEST.get(v, v.replace("_", " ")) for _, v in extra] + [_pl_cand_word(c) for c in sup]))
    if not sig:
        sig = ["a pattern that one simple input does not explain"]
    p = _pl_pair("Taken together, the curves point to " + _pl_join(sig) + ".",
                 "Start with one first-order absorption input as the reference fit, then test " + _pl_join(tests) + " against it.")
    return _pl_ah_notes(p, rc)


_PL_OTHER = {"multicompartment": "more than one disposition compartment", "saturable_elimination": "saturable elimination",
             "binding": "concentration-dependent binding"}


def _pl_cand_word(c):
    fam, _, key = str(c.get("candidate") or "").partition(".")
    if fam == "other":
        return _PL_OTHER.get(key, key.replace("_", " "))
    return _pl_H_TEST.get(key, key.replace("_", " "))


_PL_FAMILY = {"onset": "a delayed start", "shape": "other input shapes", "second": "a second input", "tail": "flip-flop kinetics",
              "dose": "dose-dependent absorption"}


def _pl_cand_family(c):
    """Short family words for the notes (the single candidates stay in the model steps)."""
    fam, _, key = str(c.get("candidate") or "").partition(".")
    return _PL_OTHER.get(key, key.replace("_", " ")) if fam == "other" else _PL_FAMILY.get(fam, _pl_cand_word(c))


def _pl_ranked(b):
    """The Absorption ranked candidates (the analysis layer), without the reference and board-level exclusions."""
    rc = (b.get("ranked_candidates") or {}).get("candidates") or []
    return [c for c in rc if c.get("group") in ("SUPPORTED", "INDIRECT_SUPPORT", "UNTESTED") and not c.get("board_excluded")]


def _pl_ah_notes(p, rc):
    """George 2026-11-26: the working hypothesis names every candidate the ranking keeps: indirect hints, then untested ones."""
    if not p:
        return p
    named = plain_text(p).lower()
    left = [c for c in rc if _pl_cand_word(c).lower() not in named]
    ind = list(dict.fromkeys(_pl_cand_family(c) for c in left if c["group"] == "INDIRECT_SUPPORT"))
    unt = list(dict.fromkeys(w for w in (_pl_cand_family(c) for c in left if c["group"] == "UNTESTED") if w not in ind))
    notes = []
    if ind:
        notes.append("Indirect hints also point to " + _pl_join(ind) + "; try these only if the reference fit leaves a pattern.")
    if unt:
        notes.append("These data hold no evidence for or against " + _pl_join(unt) + ", so they stay untested.")
    if notes:
        p["notes"] = notes
    return p


def _pl_join(xs):
    xs = list(xs)
    if not xs:
        return ""
    return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " and " + xs[-1]


# -------------------------------------------------------------------------------------------------- distribution

def _pl_iv_individual(b):
    refs = b.get("iv_refs") or []
    return bool(refs) and all(str(s.get("level") or s.get("record_level") or "INDIVIDUAL").upper().startswith("INDIVIDUAL") for s in refs)


def plain_distribution(b, species_with_bound=()):
    rows = b.get("item24") or []
    noun = _pl_plural(b.get("species"), _pl_iv_individual(b))
    out = {}
    for q in b.get("questions", []):
        f = _pl_DIS.get(q["q"])
        try:
            r = f(q, b, rows, noun, species_with_bound) if f else None
        except (KeyError, TypeError, ValueError, _pl_statistics.StatisticsError):
            r = None
        out[q["q"]] = r or _pl_fallback(q)
    out["H"] = _pl_dh(b, rows, noun)
    return out


def _pl_phase_counts(rows):
    pv = [r.get("phases_visible") for r in rows]
    return pv.count("TWO_OR_MORE"), pv.count("TWO_OR_MORE_TENTATIVE"), pv.count("ONE_APPARENT")


THREE_MIN_EARLY = 4   # samples before the terminal window needed to see a second bend (George 2026-11-25)


def three_phase_reading(rows):
    """George 2026-11-25: curvature shows more than one exponential phase, not exactly two. Per IV profile with a visible bend:
    CANDIDATE when the decline still slows after the early points are dropped (no straight terminal window is reached, a second
    bend), SPARSE when fewer than THREE_MIN_EARLY samples lie before the terminal window, NONE when the points after the early
    phase follow one straight line. Returns {"candidate": [...], "sparse": [...], "none": [...], "n": n}."""
    out = {"candidate": [], "sparse": [], "none": [], "n": 0}
    for r in rows or []:
        if r.get("phases_visible") not in ("TWO_OR_MORE", "TWO_OR_MORE_TENTATIVE"):
            continue
        out["n"] += 1
        w = r.get("iv_window") or {}
        lab = r.get("label") or r.get("sid")
        if r.get("post_distribution_reason") == "SLOWING_IN_EVERY_SUFFIX" or w.get("reason") == "SLOWING_IN_EVERY_SUFFIX":
            out["candidate"].append(lab)
        elif w.get("status") == "DETERMINED" and isinstance(r.get("n_points"), int) and r["n_points"] - (w.get("n") or 0) >= THREE_MIN_EARLY:
            out["none"].append(lab)
        else:
            out["sparse"].append(lab)
    return out


def _pl_ordering(b):
    """{candidate: entry} of the board's model ordering (the analysis layer), without board-level exclusions."""
    a = b.get("apod_ordering") or {}
    return {c["candidate"]: c for c in a.get("candidates") or [] if c.get("group") and not c.get("board_excluded")}


def _pl_three_note(rows, noun, b=None):
    order = _pl_ordering(b or {})
    if order and "three-compartment" not in order:
        return None
    t = three_phase_reading(rows)
    n, k, sp = t["n"], len(t["candidate"]), len(t["sparse"])
    if not n:
        return None
    if k:
        return (f"In {_pl_count(k, n, noun)} the decline still bends after the early points are dropped, so a three-compartment model "
                "is a candidate; test it against two.")
    if sp:
        return (f"In {_pl_count(sp, n, noun)} there are too few samples before the terminal phase to tell whether a third compartment is present.")
    return ("After the early phase the later points follow one straight line, so the data give no sign of a third compartment; "
            "keep a three-compartment model only as an untested alternative.")


_PL_NONLINEAR = "nonlinear elimination or binding"


def _pl_nl_units(c):
    return set(c.get("supported_by") or []) | set(c.get("sensitivity_support") or []) | set(c.get("indirect") or [])


def _pl_nonlinear_note(b, rows, noun):
    """The ordering's nonlinear candidate (late steepening), when it is not excluded and an observation stands behind it."""
    c = _pl_ordering(b).get(_PL_NONLINEAR)
    if not c or c.get("group") == "CONTRARY_EVIDENCE" or not _pl_nl_units(c):
        return None
    k = len(_pl_nl_units(c))
    n = max(len(rows), k)
    if c.get("group") == "SUPPORTED":
        return (f"In {_pl_count(k, n, noun)} the last points fall faster than a straight line, which supports nonlinear elimination or "
                "binding; test it against linear elimination.")
    return (f"In {_pl_count(k, n, noun)} the last points fall slightly faster than a straight line, so nonlinear elimination or binding "
            "stays an untested alternative.")


def _pl_d1_notes(rows, noun, b):
    return [x for x in (_pl_three_note(rows, noun, b), _pl_nonlinear_note(b or {}, rows, noun)) if x]


def _pl_d1(q, b, rows, noun, _):
    if not rows:
        return _pl_pair("This study has no IV profile.", "Read distribution from IV data of the same species, if there are any.")
    n = len(rows)
    a, t, o = _pl_phase_counts(rows)
    if a + t + o == 0:
        return _pl_pair("The IV profiles have too few samples to read the shape of the decline.",
                    "Choose the number of compartments from the literature or from richer data.")
    if a == n:
        p = _pl_pair(f"{_pl_count(n, n, noun)} show a fast early decline followed by a slower terminal phase on the semi-log plot.",
                     "Use at least two compartments and start with a two-compartment model (central + one peripheral), because the early points bend away from a single straight line.")
        p["notes"] = _pl_d1_notes(rows, noun, b)
        return p
    if o == n:
        return _pl_pair(f"{_pl_count(n, n, noun)} {_pl_verb(n, n, 'show')} one straight decline on the semi-log plot.",
                    "Start with a one-compartment model; a two-compartment model stays untested, because earlier samples would be needed to see a fast distribution phase.")
    if a + t > o:
        weak = f", but in {t} of them the early phase rests on few samples" if t > 1 else ", but in one of them the early phase rests on few samples" if t else ""
        p = _pl_pair(f"{_pl_count(a + t, n, noun)} {_pl_verb(a + t, n, 'show')} a fast early decline followed by a slower phase" + weak + ".",
                     "Use at least two compartments where the bend is clear: start with a two-compartment model and compare it with a one-compartment fit, because the early phase is not clear in every animal.")
        p["notes"] = _pl_d1_notes(rows, noun, b)
        return p
    return _pl_pair(f"{_pl_count(o, n, noun)} {_pl_verb(o, n, 'show')} one straight decline; the rest show signs of a faster early phase.",
                "Start with a one-compartment model and test a two-compartment model as the alternative.")


def _pl_d2(q, b, rows, noun, _):
    v = b.get("vc_summary")
    if not v or not v.get("median"):
        return _pl_pair("The central volume cannot be bounded, because the infusion timing or the IV mode is not reported.",
                    "Let the fit estimate the central volume freely, starting from a literature value.")
    wide = v.get("min") and v.get("max") and v["max"] / v["min"] > 2
    n = v.get("n") or len(rows)
    shows = (f"The first sample after dosing caps the central volume in {_pl_count(n, n, noun)}"
             + (", and the cap varies a lot between animals." if wide else ", and the cap is similar across animals."))
    return _pl_pair(shows, f"Start the central volume at or below about {_pl_g2(v['median'])} L/kg" + (" and allow between-animal variability on it." if wide else "."))


def _pl_d3(q, b, rows, noun, _):
    sc = q.get("status_code")
    obs = (q.get("observed") or "").lower()
    if sc == "NOT_APPLICABLE":
        return _pl_pair("This study has no non-IV profile to compare with IV.", "Fit the disposition from the IV data alone.")
    if "compatible" in obs and "not compatible" not in obs and sc in ("ANSWERABLE", "PARTLY_ANSWERABLE"):
        return _pl_pair("Late on, the non-IV profiles decline the same way as the IV profiles.", "Share the disposition parameters between routes.")
    return _pl_pair("The IV and non-IV profiles cannot show whether absorption hides a fast distribution phase.",
                "Take the disposition from the IV data and estimate absorption on top of it.")


def _pl_d4(q, b, rows, noun, _):
    ok, dep = q.get("robust_profiles"), q.get("depends_on_one_point")
    if ok is None or dep is None:
        m = re.search(r"in (\d+) of (\d+)", q.get("observed") or "")
        if not m:
            return None
        k, n, dep = int(m[1]), int(m[2]), []
    else:
        k, n = len(ok), len(ok) + len(dep)
    if not n:
        return None
    if k == n:
        return _pl_pair(f"Removing a single point (the first, the last or a flagged one) does not change the pattern of the curve in {_pl_count(n, n, noun)}.",
                        "The choice of compartments does not depend on any single sample.")
    who = (" (" + ", ".join(dep[:6]) + (" and others" if len(dep) > 6 else "") + ")") if dep else ""
    p = _pl_pair(f"Removing a single point does not change the pattern of the curve in {_pl_count(k, n, noun)}; in the rest{who} the shape depends on one point.",
                 "Check those points when fitting; without them a one-compartment model may describe those animals.")
    p["labels"] = list(dep[:6])
    return p


def _pl_d5(q, b, rows, noun, _):
    t = b.get("tissues") or []
    if not t or q.get("status_code") == "NOT_APPLICABLE":
        return _pl_pair("This study has no tissue concentrations.", "Model plasma only; no tissue compartment is needed for these data.")
    names = sorted({str(x.get("tissue") or x.get("site") or x.get("matrix") or "") for x in t if isinstance(x, dict)} - {""})
    return _pl_pair("Tissue concentrations are available" + (f" for {_pl_join(names)}." if names else "."),
                "Add a tissue compartment only if the tissue time course matters for the effect.")


def _pl_d6(q, b, rows, noun, _):
    bd = b.get("binding") or {}
    if bd.get("fu_table") or bd.get("plasma_unbound_status") not in (None, "UNKNOWN"):
        return _pl_pair("An unbound fraction in plasma is reported.", "Use it to convert total to unbound concentration when the effect depends on free drug.")
    return _pl_pair("The package gives no unbound fraction in plasma.",
                "Model total plasma concentration, and add protein binding once an unbound fraction is available.")


def _pl_d7(q, b, rows, noun, species_with_bound):
    sp = list(species_with_bound or [])
    if len(sp) >= 2:
        return _pl_pair(f"A central-volume cap is available for {_pl_join(sp)}.",
                    "Compare the volumes per kg across species before scaling between them.")
    one = (sp[0] if sp else str(b.get("species") or "")).lower()
    return _pl_pair(f"Only one species ({one}) has IV data in this package." if one else "No species has a central-volume cap in this package.",
                "Cross-species scaling is not possible from this package; keep the model species-specific.")


_pl_DIS = {1: _pl_d1, 2: _pl_d2, 3: _pl_d3, 4: _pl_d4, 5: _pl_d5, 6: _pl_d6, 7: _pl_d7}


def _pl_dh(b, rows, noun):
    if not b.get("hypothesis"):
        return None
    base = _pl_d1(None, b, rows, noun, ())
    sp = b.get("animal_spread") or {}
    first, auc = (sp.get("first") or {}).get("fold"), (sp.get("auc") or {}).get("fold")
    if first and auc and first > auc:
        bsv = "with between-animal variability on the central volume as well as on clearance"
    else:
        bsv = "with between-animal variability on clearance and the central volume"
    model = "one-compartment" if base["suggests"].startswith(("A one", "Start with a one")) else "two-compartment"
    lead = f"Start with a {model} model"
    if model == "two-compartment" and "at least two" in base["suggests"]:
        lead = ("Use at least two compartments where the bend is clear: start with a two-compartment model, compared with a one-compartment fit,"
                if "compare it with a one" in base["suggests"] else "Use at least two compartments: start with a two-compartment model")
    p = _pl_pair(base["shows"], f"{lead} {bsv}, and choose the terminal window by eye on each profile.")
    if base.get("notes"):
        p["notes"] = list(base["notes"])
    if model == "one-compartment" and "two-compartment" in base["suggests"]:
        p.setdefault("notes", []).append("A two-compartment model stays untested, because earlier samples would be needed to see a fast distribution phase.")
    for cand, c in _pl_ordering(b).items():   # anything else the ordering keeps is still named (meaning check)
        if (c.get("group") in ("SUPPORTED", "INDIRECT_SUPPORT", "UNTESTED") and cand in _PL_CAND_WORDS
                and not (cand == _PL_NONLINEAR and not _pl_nl_units(c))
                and not any(w in plain_text(p).lower() for w in _PL_CAND_WORDS[cand])):
            p.setdefault("notes", []).append(
                "A one-compartment model is kept only as the baseline fit, because the data do not formally rule it out." if cand == "one-compartment"
                else f"A {cand} model stays an untested alternative." if "compartment" in cand else f"{_pl_cap(cand)} stays an untested alternative.")
    return p


# ------------------------------------------------------------------------------------------------------ checking

# --------------------------------------------------------------------------------------------------- elimination

def plain_elimination(b):
    """{engine question id: pair} for one Elimination board, plus "H" and "terminal" (the terminal-phase figures)."""
    rows = [r for r in b.get("item29") or [] if isinstance(r.get("window_proxy"), (int, float)) and r["window_proxy"] > 0]
    indiv = all(str(r.get("analysis_unit") or "INDIVIDUAL").startswith("INDIVIDUAL") for r in rows) if rows else True
    noun = _pl_plural(b.get("species"), indiv)
    tp = [t for t in b.get("terminal") or []]
    out = {}
    for q in b.get("questions", []):
        f = _pl_ELIM.get(q["q"])
        try:
            r = f(q, b, rows, noun) if f else None
        except (KeyError, TypeError, ValueError, ZeroDivisionError, _pl_statistics.StatisticsError):
            r = None
        out[q["q"]] = r or _pl_fallback(q)
    iv_tp = [t for t in tp if str(t.get("route") or "").upper() == "IV"]
    use = iv_tp or tp   # George 2026-11-26: with IV data, the half-life shown is the IV one; other routes get their own note
    routes = {t.get("route") for t in use}
    one = _PL_ROUTE.get(str(next(iter(routes))).upper(), str(next(iter(routes)))) if len(routes) == 1 else None
    term = _pl_terminal(use, (noun + f" after {one} dosing") if one else
                        "profiles (" + _pl_join(sorted(_PL_ROUTE.get(str(r).upper(), str(r)) for r in routes)) + ")")
    model = _pl_elim_model(b, rows, indiv, out, tp)
    out["H"] = _pl_eh(b, rows, noun, term, model)
    out["terminal"] = dict(out["H"]) if out["H"] and term else term
    return out


def _pl_elim_model(b, rows, indiv, qs, tp):
    """George 2026-11-25: Elimination always ends in an explicit model suggestion taken from the data, then what the data can and
    cannot support (dose dependence, renal or metabolic split, which route to anchor on), with the half-life check last."""
    plasma = b.get("plasma") or []
    routes = {str(r.get("route") or "").upper() for r in rows} | {str(t.get("route") or "").upper() for t in tp}
    routes |= {str(s.get("route_detail") or s.get("route_class") or "").upper() for s in plasma if isinstance(s, dict)}
    iv = "IV" in routes or any(isinstance(s, dict) and s.get("route_class") == "IV" for s in plasma)
    bav = ", with between-animal variability on clearance" if indiv else ""
    sug = (f"Model elimination as one linear clearance from the central compartment{bav}." if iv else
           f"Model elimination as one linear apparent clearance (clearance divided by bioavailability) from the central compartment{bav}.")
    notes = []
    q = {x["q"]: x for x in b.get("questions") or []}
    if 2 in q and q[2].get("status_code") not in ("NOT_APPLICABLE", "NOT_ANSWERABLE_YET"):
        notes.append("More than one dose level was given, so dose-dependent (nonlinear) clearance can be tested against the linear one.")
    else:
        notes.append(f"Only one dose level{' per route' if len(routes - {''}) > 1 else ''} was given, so dose-dependent (nonlinear) clearance cannot be tested.")
    urine, met = bool(b.get("urine")), bool(b.get("components") or b.get("in_vitro"))
    notes.append("There are no urine or metabolite data, so only total clearance can be estimated." if not urine and not met else
                 "There are no urine data, so renal and non-renal clearance cannot be separated." if not urine else
                 "Urine data are available, so a renal part of clearance can be tested.")
    th = [t["thalf_h"] for t in tp if str(t.get("route") or "").upper() == "IV" and isinstance(t.get("thalf_h"), (int, float)) and t["thalf_h"] > 0]
    slow = [g for g in b.get("ev_late") or [] if g.get("flip_flop_reading") == "ABSORPTION_INFLUENCED_CANDIDATE"]
    ev_notes = _pl_ev_terminal_note(tp, th) or []
    notes.extend(ev_notes)
    if iv and slow and not any("absorption" in x for x in ev_notes):
        ev_routes = sorted({_PL_ROUTE.get(str(r).upper(), str(r)) for s in plasma if isinstance(s, dict) and s.get("route_class") == "EV"
                            for r in [s.get("route_detail") or s.get("route")] if r}) or ["non-IV"]
        notes.append(f"After {_pl_join(ev_routes)} dosing the late decline is much slower than after IV dosing (half-life about "
                     f"{_pl_g2(_pl_statistics.median(g['ev_thalf_median_h'] for g in slow))} h), so absorption sets it there; "
                     "anchor elimination on the IV data.")
    if th:
        notes.append(f"As a check, the slowest phase of the fitted model should decline with a half-life of about {_pl_g2(_pl_statistics.median(th))} h.")
    return {"suggests": sug, "notes": notes}


def _pl_em1a(b):
    """George 2026-11-27: the plain reading of EM-1a (dose-normalized AUC vs dose), or None with one dose."""
    g = next((g for g in b.get("em1a") or [] if g.get("ratio_high_low") and (g.get("file") or g.get("reused"))), None)
    if not g:
        return None
    r = g["ratio_high_low"]
    route = "IV" if g.get("route") == "IV" else _PL_ROUTE.get(str(g.get("route_word")).upper(), str(g.get("route_word")))
    if 0.8 <= r <= 1.25:
        return (f"After {route} dosing, exposure divided by dose stays about level across the doses over the shared observed window.",
                "Keep linear clearance as a reference model.")
    if r > 1.25:
        return (f"After {route} dosing, exposure divided by dose rises with dose.",
                "Check delivery, binding and assay before testing saturable clearance against linear clearance." if route == "IV" else
                "Test a saturable clearance against the linear one; a change in bioavailability with dose could give the same rise.")
    return (f"After {route} dosing, exposure divided by dose falls with dose.",
            "Check absorption and protein binding at the higher doses before adding a dose-dependent clearance.")


def _pl_e1(q, b, rows, noun):
    base = _pl_e1_window(q, b, rows, noun)
    em = _pl_em1a(b)
    if em:
        return _pl_pair(em[0], em[1] + (" " + base["suggests"] if base else ""))
    return base


def _pl_e1_window(q, b, rows, noun):
    iv = [r["window_proxy"] for r in rows if str(r.get("route") or "").upper() == "IV"]
    if iv:
        n = len(iv)
        f = max(iv) / min(iv)
        spread = "is similar across" if f <= 1.5 else "differs somewhat across" if f <= 2 else "varies a lot across"
        return _pl_pair(f"After IV dosing, dose divided by the observed exposure {spread} {_pl_count(n, n, noun)}.",
                        f"Start clearance at or below about {_pl_g2(_pl_statistics.median(iv))} L/h/kg; the samples miss part of the curve, so this is an upper estimate.")
    if rows:
        return _pl_pair("Only non-IV profiles are available, so dose divided by exposure mixes clearance with bioavailability.",
                        "Estimate clearance divided by bioavailability, not clearance itself, from these data.")
    return None


def _pl_e2(q, b, rows, noun):
    if q.get("status_code") in ("NOT_APPLICABLE", "NOT_ANSWERABLE_YET"):
        return _pl_pair("Only one dose level is available, so it cannot be checked whether clearance changes with dose.",
                        "Assume clearance does not depend on dose.")
    return _pl_pair("Exposure divided by dose is compared across the doses given.", "Keep linear clearance unless the comparison shows a clear trend with dose.")


def _pl_e3(q, b, rows, noun):
    if q.get("status_code") == "NOT_APPLICABLE":
        return _pl_pair("There is no repeated dosing in this study.", "No time-dependent clearance is needed.")
    return _pl_pair("Repeated doses are available for this study.", "Check whether exposure after later doses matches what a single-dose model predicts.")


def _pl_e5(q, b, rows, noun):
    if not b.get("urine"):
        return _pl_pair("No urine was collected in this study.", "Renal and non-renal clearance cannot be separated; model total clearance only.")
    return _pl_pair("Unchanged drug recovered in urine is shown over the collection intervals.",
                    "Split clearance into renal and non-renal parts only if the urine collection covers most of the excretion.")


def _pl_e7(q, b, rows, noun):
    if not (b.get("components") or b.get("in_vitro")):
        return _pl_pair("There are no metabolite or in vitro data for this study.", "Treat elimination as one lumped clearance.")
    return _pl_pair("Metabolite or in vitro data are available for this study.",
                    "Use them to judge which pathway dominates before adding pathway-specific clearance.")


def _pl_e6(q, b, rows, noun):
    if not b.get("recovery"):
        return _pl_pair("This study has no mass-balance design, so total recovery of the dose cannot be checked.", "No change to the model is needed for this question.")
    return _pl_pair("Recovery of the dose in excreta is shown by route of excretion.", "Use the main excretion route to decide which clearance pathway to model.")


_pl_ELIM = {1: _pl_e1, 2: _pl_e2, 3: _pl_e3, 5: _pl_e5, 7: _pl_e7, 6: _pl_e6}


def _pl_terminal(tp, noun):
    if not tp:
        return None
    n = len(tp)
    th = [t["thalf_h"] for t in tp if isinstance(t.get("thalf_h"), (int, float)) and t["thalf_h"] > 0]
    if not th:
        return _pl_pair(f"In {_pl_count(0, n, noun)} do the late points fall on a straight line long enough to read a half-life.",
                        "Do not fix the terminal half-life from these profiles; let the model estimate it.")
    return _pl_pair(f"In {_pl_count(len(th), n, noun)} the late points fall on a straight line on the semi-log plot, with a terminal half-life of about "
                    f"{_pl_g2(_pl_statistics.median(th))} h.",
                    "Use this half-life to check the fitted model: its slowest phase should decline at the same rate.")


EV_TERMINAL_MATCH = 1.25   # apparent EV / IV terminal half-life up to this ratio reads as the same decline
EV_TERMINAL_SLOWER = 1.5   # above this ratio the EV decline reads as absorption-limited (George 2026-11-26)


def _pl_ev_terminal_note(tp, iv_th):
    """The apparent terminal half-life after each non-IV route, reported apart from IV and compared with it."""
    if not iv_th:
        return []
    iv = _pl_statistics.median(iv_th)
    out = []
    for r in sorted({str(t.get("route") or "") for t in tp} - {"IV", ""}):
        th = [t["thalf_h"] for t in tp if str(t.get("route") or "") == r and isinstance(t.get("thalf_h"), (int, float)) and t["thalf_h"] > 0]
        if not th:
            continue
        ev = _pl_statistics.median(th)
        word = _PL_ROUTE.get(r.upper(), r)
        ratio = ev / iv
        if ratio <= EV_TERMINAL_MATCH and ratio >= 1 / EV_TERMINAL_MATCH:
            tail = "close to the IV value, so the late decline there also reflects elimination"
        elif ratio > EV_TERMINAL_SLOWER:
            tail = "much slower than after IV dosing, so absorption limits it there; read elimination from the IV data"
        elif ratio > 1:
            tail = "somewhat slower than after IV dosing, so absorption may still shape it; read elimination from the IV data"
        else:
            tail = "faster than after IV dosing, so check the late samples after that route"
        out.append(f"After {word} dosing the apparent late half-life is about {_pl_g2(ev)} h, {tail}.")
    return out


def _pl_eh(b, rows, noun, term, model):
    e1 = _pl_e1({}, b, rows, noun) if rows else None
    shows = (term or e1 or {}).get("shows")
    if not shows:
        return None
    p = _pl_pair(shows, model["suggests"])
    p["notes"] = list(model["notes"])
    return p


_pl_COUNT = re.compile(r"\b(?:all|none of the|one of the|the one)\s+\d+\b|\b\d+\s+of\s+\d+\b|\b(?:all|none of the)\s+\d+\s+\w+", re.I)
_pl_NUM = re.compile(r"(?<![A-Za-z0-9_.])\d+(?:\.\d+)?(?![A-Za-z0-9_])")
_pl_CODE = re.compile(r"\b[A-Z][A-Z0-9]*_[A-Z0-9_]+\b|\b(?:T[1-9]|Q[1-9]|DIS-?\d|EM-?\d|A1w?|B[12])\b|±|\bz\b|σ")


def plain_problems(p):
    """Rule-10 problems of one plain pair: codes, statistic symbols, or more than one number beyond animal counts."""
    out = []
    text = f"{p.get('shows', '')} {p.get('suggests', '')}"
    for lab in p.get("labels") or []:   # animal or profile labels named in the sentence are data, not codes
        text = text.replace(str(lab), "animal")
    if _pl_CODE.search(text):
        out.append("code or statistic symbol: " + _pl_CODE.search(text)[0])
    rest = _pl_COUNT.sub("", text).replace("one-compartment", "").replace("two-compartment", "").replace("three-compartment", "")
    nums = _pl_NUM.findall(rest)
    if len(nums) > 1:
        out.append(f"{len(nums)} numbers beyond animal counts: {nums}")
    for k in ("shows", "suggests"):
        s = p.get(k, "")
        if not s or len(re.findall(r"[.!?](?:\s|$)", s)) > 1 and not re.search(r"\d\.\d", s):
            out.append(f"{k} is not one sentence")
    for i, s in enumerate(p.get("notes") or []):   # each further note: one sentence, at most one number, no codes
        if _pl_CODE.search(s):
            out.append(f"note {i + 1}: code or statistic symbol: " + _pl_CODE.search(s)[0])
        if len(_pl_NUM.findall(_pl_COUNT.sub("", s))) > 1:
            out.append(f"note {i + 1}: more than one number")
        if len(re.findall(r"[.!?](?:\s|$)", re.sub(r"\d\.\d", "", s))) != 1:
            out.append(f"note {i + 1} is not one sentence")
    return out


_PL_CAND_WORDS = {"one-compartment": ("one-compartment",), "two-compartment": ("two-compartment", "two compartments"),
                  "three-compartment": ("three-compartment", "third compartment"), _PL_NONLINEAR: ("nonlinear",)}


def plain_meaning_problems(b, p):
    """Meaning, not style (George 2026-11-25): the plain text of a Distribution board must not claim more than the analysis layer.
    A bend (more than one phase) never reads as exactly two compartments, and every candidate the ordering keeps (SUPPORTED,
    INDIRECT_SUPPORT, UNTESTED) is named; an untested nonlinear candidate with no observation behind it stays in the model steps."""
    out = []
    text = plain_text(p).lower() if p else ""
    pv = {r.get("phases_visible") for r in b.get("item24") or []}
    if pv & {"TWO_OR_MORE", "TWO_OR_MORE_TENTATIVE"} and "two-compartment" in text and "at least two" not in text:
        out.append("a bend (more than one phase) is written as exactly two compartments")
    for cand, c in _pl_ordering(b).items():
        if c.get("group") not in ("SUPPORTED", "INDIRECT_SUPPORT", "UNTESTED") or cand not in _PL_CAND_WORDS:
            continue
        if cand == _PL_NONLINEAR and not _pl_nl_units(c):
            continue
        if not any(w in text for w in _PL_CAND_WORDS[cand]):
            out.append(f"the ordering keeps {cand} ({c['group'].lower()}) but the plain text does not name it")
    return out


def plain_meaning_problems_absorption(b, p):
    """Meaning check for an Absorption working hypothesis: every candidate the ranking keeps is named, and the text does not say
    one input is enough when a candidate has direct support."""
    out = []
    text = plain_text(p).lower() if p else ""
    for c in _pl_ranked(b):
        if _pl_cand_word(c).lower() not in text and _pl_cand_family(c).lower() not in text:
            out.append(f"the ranking keeps {c['candidate']} ({c['group'].lower()}) but the plain text does not name it")
    if any(c["group"] == "SUPPORTED" for c in _pl_ranked(b)) and ("nothing in the data asks for more" in text or "no other input model" in text):
        out.append("a directly supported candidate is denied")
    return out


# Strength rules (George 2026-11-26): a sentence may not claim more than the status of the answer it translates.
_PL_STRONG = re.compile(r"\bis enough\b|\bnot needed\b|\bno [\w -]+ is needed\b|\bdo not add\b|\bnothing in the data asks for more\b|\brules? out\b", re.I)
_PL_WEAK_STATUS = ("NOT_ANSWERABLE_YET", "PARTLY_ANSWERABLE", "CANNOT_ASSESS")


def plain_gate(section, b):
    """The translation gate, run on every board before the pages are written: style (one sentence, no codes, at most one number),
    meaning (every candidate the analysis keeps is named; a bend is never exactly two) and strength (no 'enough' or 'not needed'
    for an answer the analysis could not give). Returns a list of problems; an empty list means the wording may be shown."""
    out = []
    pairs = [(f"Q{q.get('q')}", q.get("plain"), q.get("status_code")) for q in b.get("questions") or []]
    pairs.append(("H", (b.get("hypothesis") or {}).get("plain"), None))
    for where, p, status in pairs:
        if not p:
            continue
        out += [f"{where}: {x}" for x in plain_problems(p)]
        if status in _PL_WEAK_STATUS and _PL_STRONG.search(plain_text(p)):
            out.append(f"{where}: '{_PL_STRONG.search(plain_text(p))[0]}' for an answer with status {status.lower().replace('_', ' ')}")
    h = (b.get("hypothesis") or {}).get("plain")
    if h and section == "distribution":
        out += [f"H: {x}" for x in plain_meaning_problems(b, h)]
    if h and section == "absorption":
        out += [f"H: {x}" for x in plain_meaning_problems_absorption(b, h)]
    return out


def plain_text(p):
    return " ".join([p["shows"], p["suggests"]] + list(p.get("notes") or []))


# ------------------------------------------------------------------------------------------------
# Reader text (shared rule 10): rule ids, item numbers and internal codes stay out of the visible page text
# ------------------------------------------------------------------------------------------------
_RT_SPLIT = re.compile(r"(<details\b.*?</details>|<script\b.*?</script>|<style\b.*?</style>|<[^>]+>)", re.S)
_RT_RULE = r"(?:[A-Z]\d+\.\d+|[rs]\d+\.\d+(?:\.\d+)?)"
_RT_SUBS = [
    (re.compile(r"\s*\((?:rules?\s+)?" + _RT_RULE + r"(?:,?\s*(?:items?\s+[\d–\-, ]+\d|" + _RT_RULE + r"))*\)"), ""),
    (re.compile(r"\s*\((?:rules?\s+)?" + _RT_RULE + r"\s+items?\s+[\d–\-]+\)"), ""),
    (re.compile(r"\s*\(items?\s+\d+(?:\s*[–\-]\s*\d+)?(?:\s+step\s+\d+)?\)"), ""),
    (re.compile(r"\brules\s+" + _RT_RULE + r"\b"), "rules"),
    (re.compile(r"Host-computed from observed points"), "Computed from the observed points"),
    (re.compile(r"no PK model fitted; any slope or named test shown is a descriptive regression"), "no PK model was fitted"),
    (re.compile(r"\bEDA_[A-Z]+_R\d+_\d+_\d{8}\b\s*(?:·\s*)?"), ""),
    (re.compile(r"\b(?:EM|DIS)-\d[a-z]?(?:/\d[a-z]?)?(?:\s*\((?:T\d/?)+\))?\s*·\s*"), ""),
    (re.compile(r"\b(SINGLE|MULTIPLE|REPEAT(?:ED)?|FIRST|LAST)_DOSE(S?)\b"), lambda m: m[1].lower() + " dose" + m[2]),
    (re.compile(r"\bUpstream [A-Z]\d+[a-z]?\s*·\s*(?:absorption|distribution) item \d+(?: via \w+)?\s*(?:\(\))?"), "from the upstream section"),
    (re.compile(r"\b(?:absorption|distribution|elimination) items? \d+(?:[–\-]\d+)?"), "the upstream section"),
    (re.compile(r"\bDECLINE_(FLATTENS|STEEPENS)\b"), lambda m: "the late decline " + m[1].lower()),
    (re.compile(r"\bKA_NOT_IDENTIFIABLE\b"), "absorption rate not identifiable"),
    (re.compile(r"\bLATE_FIRST_SAMPLE\b"), "late first sample"), (re.compile(r"\bONSET_NOT_OBSERVED\b"), "onset not observed"),
    (re.compile(r"\bR_GGPLOT2\b"), "R (ggplot2)"), (re.compile(r"\bMATPLOTLIB_FALLBACK\b"), "matplotlib"),
    (re.compile(r"\bSENSITIVITY_ONLY\b"), "a sensitivity-only label"), (re.compile(r"\bCANNOT_ASSESS\b"), "cannot assess"),
]


def reader_text(page):
    """Visible page text without rule ids, item numbers or internal codes; collapsed blocks, tags and scripts are left as they are."""
    parts = _RT_SPLIT.split(page)
    for i in range(0, len(parts), 2):
        t = parts[i]
        for rx, rep in _RT_SUBS:
            t = rx.sub(rep, t)
        parts[i] = t
    return "".join(parts)


# ------------------------------------------------------------------------------------------------
# Overall summary on the main page (George 2026-11-25): what data there are, one or two lines per section, the starting model,
# and the main gaps. Plain words (rule 10), built only from the section outputs of the run.
# ------------------------------------------------------------------------------------------------
def _sum_json(root, rel):
    import json as _json
    p = Path(root) / rel
    try:
        return _json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
    except (OSError, ValueError):
        return {}


def overall_summary(root):
    """List of (label, sentence) lines for the main page."""
    root = Path(root)
    mf, ab, di, el = (_sum_json(root, r) for r in ("modeling_facts.json", "absorption/absorption.json", "distribution/distribution.json",
                                                    "elimination/elimination.json"))
    lines = []
    data = []
    for sp in mf.get("species") or []:
        occ = sp.get("occasions") or {}
        routes = sorted({_PL_ROUTE.get(str(p.get("route")).upper(), str(p.get("route"))) for p in sp.get("profiles") or []})
        n_an, n_pr = occ.get("n_animals"), len(sp.get("profiles") or [])
        indiv = all(str(p.get("level") or "").startswith("INDIVIDUAL") for p in sp.get("profiles") or [])
        who = (f"{n_an} {_pl_plural(sp['species'])}" if n_an and indiv else f"{n_pr} {_pl_plural(sp['species'], indiv)}")
        rtxt = []
        for r in routes:   # George 2026-11-25: say how many doses each route had
            ev = [p.get("dose_events_h") or [] for p in sp.get("profiles") or [] if _PL_ROUTE.get(str(p.get("route")).upper(), str(p.get("route"))) == r]
            k = max((len(e) for e in ev), default=0)
            if k > 1:
                gaps = {round(b - a, 0) for e in ev for a, b in zip(e, e[1:])}
                rtxt.append(f"{r} ({_pl_word(k)} doses" + (f", {_pl_g2(next(iter(gaps)))} h apart)" if len(gaps) == 1 else ")"))
            else:
                rtxt.append(f"{r} (one dose)" if any(len(p.get("dose_events_h") or []) > 1 for p in sp.get("profiles") or []) else r)
        data.append(f"{who} dosed by {_pl_join(rtxt)}" + (f" ({n_pr} plasma profiles)" if n_an and n_pr != n_an else ""))
    if data:
        lines.append(("Data", _pl_join(data) + "; concentrations were measured in plasma."))
    def hplain(boards):
        return list(dict.fromkeys(plain_text(b["hypothesis"]["plain"]) for b in boards or [] if (b.get("hypothesis") or {}).get("plain")))
    a = hplain(ab.get("status_boards"))
    if a:
        lines.append(("Absorption", " ".join(a)))
    elif ab:
        lines.append(("Absorption", "This study has IV dosing only, so there is no absorption phase to describe." if ab.get("iv_references")
                      else "There are no concentration profiles after non-IV dosing."))
    d = hplain(di.get("boards"))
    if d:
        lines.append(("Distribution", " ".join(d)))
    e_boards = el.get("boards") or []
    e = list(dict.fromkeys(plain_text(b["terminal_plain"]) for b in e_boards if b.get("terminal_plain"))) or hplain(e_boards)
    if e:
        lines.append(("Elimination", " ".join(e)))
    # starting model: compartments from Distribution, input from Absorption, clearance from Elimination
    dsug = " ".join(((b.get("hypothesis") or {}).get("plain") or {}).get("suggests", "") for b in di.get("boards") or []).lower()
    dnotes = " ".join(n for b in di.get("boards") or [] for n in (((b.get("hypothesis") or {}).get("plain") or {}).get("notes") or [])).lower()
    comp = ("a two-compartment model (at least two compartments" + ("; test three" if "three-compartment model is a candidate" in dnotes else "") + ")"
            if "at least two" in dsug else "a two-compartment model" if "two-compartment" in dsug else
            "a one-compartment model" if "one-compartment" in dsug else None)
    parts = [comp] if comp else []
    if ab.get("status_boards"):
        parts.append("first-order absorption from the time of dosing")
    if e_boards:
        parts.append("one linear clearance")
    if parts:
        lines.append(("Starting model", "Start with " + _pl_join(parts) + "; compare it with simpler and richer models before keeping it."))
    gaps = []
    if any((b.get("binding") or {}).get("plasma_unbound_status") in (None, "UNKNOWN") and not (b.get("binding") or {}).get("fu_table")
           for b in di.get("boards") or []):
        gaps.append("no unbound fraction in plasma")
    if e_boards and not any(b.get("urine") for b in e_boards):
        gaps.append("no urine data, so renal clearance cannot be separated")
    if ab.get("status_boards") and any(q.get("q") == 6 and q.get("status_code") != "ANSWERABLE" for b in ab["status_boards"] for q in b.get("questions") or []):
        gaps.append("bioavailability is not computed from these data")
    if any(r.get("phases_visible") == "TWO_OR_MORE_TENTATIVE" for b in di.get("boards") or [] for r in b.get("item24") or []):
        gaps.append("in some animals the early phase rests on few samples")
    if gaps:
        lines.append(("Gaps", _pl_cap("; ".join(gaps)) + "."))
    checks = [f"{sec} {b.get('species') or ''}: {x}" for sec, bs in (("absorption", ab.get("status_boards")), ("distribution", di.get("boards")),
                                                                  ("elimination", e_boards)) for b in bs or [] for x in b.get("plain_check") or []]
    if checks:   # the translation gate failed somewhere: say so on the main page instead of showing the text as if it were checked
        lines.append(("Wording check", f"{_pl_cap(_pl_word(len(checks)))} plain-language statement{'s' if len(checks) != 1 else ''} failed the "
                      "automatic check that the wording does not claim more than the analysis; see plain_check.json before relying on them."))
        try:
            import json as _json
            (root / "plain_check.json").write_text(_json.dumps(checks, indent=1), encoding="utf-8")
        except OSError:
            pass
    return lines


def overall_summary_html(root):
    from html import escape
    lines = overall_summary(root)
    if not lines:
        return ""
    return ('<!--SUMMARY-START--><section class="panel" id="summary"><h2>Summary</h2>'
            + "".join(f'<p><b>{escape(k)}.</b> {escape(v)}</p>' for k, v in lines) + '</section><!--SUMMARY-END-->')


def add_summary(root):
    """Put the summary at the top of the main page (before the category cards) and of report.html; replaces an older one."""
    root = Path(root)
    block = overall_summary_html(root)
    done = False
    for name in ("index.html", "human_review.html", "report.html"):
        p = root / name
        if not p.is_file() or not block:
            continue
        text = re.sub(r"<!--SUMMARY-START-->.*?<!--SUMMARY-END-->", "", p.read_text(encoding="utf-8"), flags=re.S)
        m = re.search(r'<div class="categories">', text) if name != "report.html" else None
        m = m or re.search(r"<section\b", text) or re.search(r"</h1>", text)
        if not m:
            continue
        pos = m.start() if m.group(0) != "</h1>" else m.end()
        p.write_text(text[:pos] + block + text[pos:], encoding="utf-8")
        done = True
    for p in [root / "index.html", root / "human_review.html", root / "report.html", root / "figures" / "index.html"]:
        if p.is_file():   # rule 10 on the portal's own pages too
            p.write_text(reader_text(p.read_text(encoding="utf-8")), encoding="utf-8")
    return done


# --------------------------------------------------------------------------------------------------- shared with absorption
# Calculations, statistics and label helpers that Absorption, Distribution and Elimination all use (moved here from
# eda_absorption.py on 2026-11-26 without change; eda_absorption.py keeps the old names as aliases).
import html  # noqa: E402
import itertools  # noqa: E402

import numpy as np  # noqa: E402


TOL = 0.05            # project-set relative tolerance (digitization / unreported analytic error)


SPAN_MIN = 2.0        # project-set minimum span ratio for terminal windows (A0.7)


ADJ_R2_MIN = 0.80     # project-set (George 2026-11-25): a window must itself be log-linear; a fit through a bend does not qualify


LATE_FIRST = 1 / 3    # LATE_FIRST_SAMPLE: first sample >= Tmax/3 (item 16)


ADJ_R2_TIE = 1e-4     # review guide Q3: the longest window whose adjusted R² is within 0.0001 of the highest value


DOSE_TIME_ABS = 1e-3  # same-study dose series share digitized times exactly


def _num(v):
    return to_float(v)   # round 3 (2026-11-24): the one number reader, after the shared ingress normalisation


_DISP_MEANINGS = ("SD", "SE", "DISPERSION", "ERROR", "SUMMARY_STATISTIC", "ERROR_BAR_UPPER", "ERROR_BAR_LOWER")


def _dispersion_columns(cols, conc_cols):
    """Pair each concentration column with its SD / SE / error-bar-end columns (by shared dose label,
    or the only concentration column)."""
    out = {}
    cands = [c for c in cols if c.get("meaning") in _DISP_MEANINGS
             or re.search(r"\bsd\b|\bse\b|standard (deviation|error)|bar end|error bar", str(c.get("header", "")).lower())]
    for cc in conc_cols:
        m = re.search(r"(\d+(?:\.\d+)?)\s*mg/kg", str(cc.get("header", "")))
        mine = [c for c in cands if (len(conc_cols) == 1 or (m and re.search(r"(^|\D)" + re.escape(m.group(1)) + r"\s*mg/kg", str(c.get("header", "")))))]
        d = {"sd": None, "se": None, "upper": None, "lower": None, "kind": None}
        for c in mine:
            hd = str(c.get("header", "")).lower()
            if c.get("meaning") == "ERROR_BAR_UPPER" or "upper" in hd:
                d["upper"] = c["id"]
            elif c.get("meaning") == "ERROR_BAR_LOWER" or "lower" in hd:
                d["lower"] = c["id"]
            elif c.get("meaning") == "SE" or re.search(r"\bse\b|standard error", hd):
                d["se"] = c["id"]
            else:
                d["sd"] = c["id"]
        d["kind"] = "SD" if d["sd"] else "BAR_ENDS" if (d["upper"] or d["lower"]) else "SE" if d["se"] else None
        if d["kind"]:
            out[cc["id"]] = d
    return out


def _point_sd(r, dc, mean):
    """Return (sd, note) for one record. Error-bar ends give SD as the mean half-width; SE is not SD."""
    if not dc:
        return None, None
    if dc.get("sd"):
        v = _num(r.get(dc["sd"]))
        return (v, None) if v is not None else (None, "no SD at this point")
    if dc.get("upper") or dc.get("lower"):
        up = _num(r.get(dc["upper"])) if dc.get("upper") else None
        lo = _num(r.get(dc["lower"])) if dc.get("lower") else None
        if mean is None:
            return None, None
        half = [x for x in ((up - mean) if up is not None else None, (mean - lo) if lo is not None else None) if x is not None and x > 0]
        if not half:
            return None, "error bar hidden by the marker or not read"
        return sum(half) / len(half), ("asymmetric error bar" if len(half) == 2 and abs(half[0] - half[1]) > 0.2 * max(half) else None)
    return None, "SE only (SE is not SD)"


def auc(t, c):
    """A0.6: linear-up / log-down, observed points only."""
    a = 0.0
    for i in range(len(t) - 1):
        dt, c0, c1 = t[i + 1] - t[i], c[i], c[i + 1]
        a += dt * (c0 - c1) / math.log(c0 / c1) if (c0 > 0 and c1 > 0 and c1 < c0) else dt * (c0 + c1) / 2
    return a


def curve_metrics(points, level, *, total_signal_only=False, digitized=False):
    q = [p for p in points if p["status"] == "QUANTIFIED" and p["c"] is not None and p["c"] > 0 and p["t"] > 0]
    blq = [p for p in points if p["status"] == "BLQ"]
    censored = [p for p in points if p["status"] in ASSAY_LABELS]
    out = {"n_quantified": len(q), "n_blq": len(blq),
           "n_not_detected": sum(p["status"] == "NOT_DETECTED" for p in points),
           "last_sample_h": max((p["t"] for p in points), default=None)}
    if censored:
        out["censored_samples"] = [{k: p[k] for k in ("t", "status", "source_status", "record_id", "censoring") if k in p}
                                   for p in censored]
    observed_times = [p["t"] for p in points if p["t"] >= 0 and
                      (p["status"] in ASSAY_LABELS or p.get("c") is not None)]
    if len(observed_times) != len(set(observed_times)):
        out["not_assessable_reason"] = "duplicate sampling time: resolve animal, occasion or replicate before curve calculations"
        return out
    if len(q) < 3:
        out["not_assessable_reason"] = "fewer than 3 quantified points"
        return out
    tq = np.array([p["t"] for p in q]); cq = np.array([p["c"] for p in q])
    L, U = cq * (1 - TOL), cq * (1 + TOL)
    imax = int(np.argmax(cq)); tmax, cmax = float(tq[imax]), float(cq[imax])
    first_t = float(tq[0])
    if total_signal_only:
        return {**out, "tmax": tmax, "cmax": cmax, "first_t": first_t, "first_frac_cmax": float(cq[0] / cmax),
                "tlast": float(tq[-1]), "_t": tq.tolist(), "_c": cq.tolist(), "caveats": ["ENDOGENOUS_REVIEW_REQUIRED"]}
    # item 16 onset
    earlier_blq = [p for p in censored if 0 < p["t"] < first_t]
    positive_predose = any(p["t"] <= 0 and p["status"] == "QUANTIFIED" and (p.get("c") or 0) > 0 for p in points)
    censored_predose = any(p["t"] <= 0 for p in censored)
    if positive_predose:
        onset = "NOT_ASSESSABLE"; onset_reason = "positive predose concentration; the first positive sample cannot isolate input from this dose"
    elif censored_predose:
        onset = "NOT_ASSESSABLE"; onset_reason = "censored predose concentration; a drug-free baseline is unresolved"
    elif earlier_blq:
        onset = "NOT_ASSESSABLE"; onset_reason = "censored sample before the first quantified sample; onset unresolved (A0.5)"
    else:
        onset = "ONSET_NOT_OBSERVED"; onset_reason = f"first sample ({first_t:.3g} h) already quantified: any delay is shorter than {first_t:.3g} h"
    # T1 on all quantified pairs (A0.10)
    best = None
    for i in range(len(tq)):
        for j in range(i + 1, len(tq)):
            m = L[j] / tq[j] - U[i] / tq[i]
            if best is None or m > best[0]:
                best = (m, i, j)
    mt1, wi, wj = best
    mt1_exact = max(cq[j] / tq[j] - cq[i] / tq[i] for i in range(len(tq)) for j in range(i + 1, len(tq)))
    t1_removal = None
    if mt1 > 0:
        # R2: drop each quantified point and rescan; T1 needs two points, so with three or more every rerun is assessable
        lost = []
        for k in range(len(tq)):
            keep = [x for x in range(len(tq)) if x != k]
            if not any(L[b] / tq[b] - U[a] / tq[a] > 0 for a, b in itertools.combinations(keep, 2)):
                lost.append(float(tq[k]))
        t1_removal = {"unit": "quantified sample", "required": len(tq), "assessable": len(tq), "not_assessable": [],
                      "lost_when_removed_h": lost, "status": "DEFERRED" if lost else "PASSED"}
        flags = ["SENSITIVITY_ONLY"] + (["SINGLE_POINT_SUPPORT"] if lost else [])
    else:
        flags = ["SENSITIVITY_ONLY"]
    if positive_predose or censored_predose:
        flags.append("DRUG_FREE_BASELINE_UNRESOLVED")
    # item 17
    n_pre = imax
    rising_n = imax + 1
    ka_ni = n_pre < 2 or imax == 0
    rise_shape = "NOT_ASSESSABLE" if rising_n < 3 else "DESCRIBED_IN_INCREMENTS"
    increments = [{"t0": float(tq[i]), "t1": float(tq[i + 1]), "dcdt": float((cq[i + 1] - cq[i]) / (tq[i + 1] - tq[i]))}
                  for i in range(imax)]
    # item 20: split-half (A0.7)
    # L5 (2026-11-24): the shared description (eda_common), also used by Distribution for the same curve
    pp = [p for p in sorted(q, key=lambda p: p["t"]) if p["t"] > float(tq[imax])]
    split = ev_post_peak_split(pp, level) if len(pp) >= EV_SPLIT_MIN_POINTS else None
    # dips (descriptive for group means; T2 only for verified serial individuals)
    dips = [(int(i), int(j), int(k)) for i, j, k in itertools.combinations(range(len(cq)), 3) if U[j] < min(L[i], L[k])]
    # item 18: terminal windows (A0.7)
    wins = []
    # A8: windows start strictly after the last sample equal to the peak, and never span a censored sample
    # (3 or more consecutive quantified samples): start after the latest censored sample inside the post-peak range
    imax_last = int(np.flatnonzero(cq == cmax)[-1])
    cut = max((p["t"] for p in censored if tq[imax_last] < p["t"] < tq[-1]), default=None)
    first_s = imax_last + 1 if cut is None else max(imax_last + 1, int(np.searchsorted(tq, cut, side="right")))
    for s in range(first_s, len(tq) - 2):
        tw, cw = tq[s:], cq[s:]
        if np.all(cw == cw[0]):
            continue
        b, a0 = np.polyfit(tw, np.log(cw), 1)
        r = np.corrcoef(tw, np.log(cw))[0, 1] ** 2
        k = len(tw); adj = 1 - (1 - r) * (k - 1) / (k - 2) if k > 2 else float("nan")
        th = math.log(2) / -b if b < 0 else None
        span = (tw[-1] - tw[0]) / th if th else None
        # 2026-11-24 review: slope and t½ are stored unrounded, so every ratio and grade built on them uses the fitted values
        # (a ratio of 1.24996 had been graded as 1.2500); displays format their own digits
        wins.append({"start": round(float(tw[0]), 4), "n": k, "slope": float(b), "intercept": float(a0),
                     "thalf": float(th) if th else None, "adjR2": round(float(adj), 4), "adjR2_exact": float(adj),
                     "span_ratio": round(float(span), 3) if span else None,
                     # A8: qualification uses the unrounded slope and span; the rounded values are for display only
                     "qualified": bool(b < 0 and span is not None and span >= SPAN_MIN and adj >= ADJ_R2_MIN)})
    qual = [w for w in wins if w["qualified"]]
    if censored and cut is not None:
        out["terminal_window_censoring"] = f"windows start after the censored sample at {cut:g} h"
    best_adj = max(w["adjR2_exact"] for w in qual) if qual else None
    # review guide Q3: among the qualified windows, the longest one whose adjusted R² is within 0.0001 of the highest value
    sel = (max((w for w in qual if best_adj - w["adjR2_exact"] <= ADJ_R2_TIE + 1e-12), key=lambda w: (w["n"], w["adjR2_exact"]))
           if qual else None)
    q_th = [w["thalf"] for w in qual if w["thalf"]]
    baseline = next((p["c"] for p in points if p["t"] == 0 and p["status"] in
                     ("QUANTIFIED", "REPORTED_ZERO_PREDOSE") and p.get("c") is not None), None)
    out["auc_baseline_basis"] = "ASSUMED_ZERO" if baseline is None else "SOURCE_AT_DOSING"
    out["auc_baseline_concentration"] = 0.0 if baseline is None else baseline
    blocked = any(0 <= p["t"] <= tq[-1] for p in censored)
    a_last = None if blocked else auc(np.r_[0.0, tq], np.r_[out["auc_baseline_concentration"], cq])
    lam = -sel["slope"] if sel else None
    tail = float(cq[-1] / (lam * a_last + cq[-1])) if lam and a_last is not None else None
    caveats = ["AUC_WITHHELD_CENSORED_WINDOW"] if blocked else []
    if first_t >= tmax * LATE_FIRST:
        caveats.append("LATE_FIRST_SAMPLE")
    if level == "GROUP_MEAN":
        caveats.append("GROUP_MEAN")
    if ka_ni:
        caveats.append("KA_NOT_IDENTIFIABLE")
    out.update({
        "tmax": tmax, "cmax": cmax, "first_t": first_t, "first_frac_cmax": float(cq[0] / cmax),
        "onset_status": onset, "onset_reason": onset_reason,
        "t1_label": "CANNOT_ASSESS", "t1_flags": flags, "t1_removal": t1_removal, "mt1": float(mt1), "mt1_exact": float(mt1_exact),
        "mt1_witness": [float(tq[wi]), float(tq[wj])],
        "n_before_peak": n_pre, "rise_shape": rise_shape, "increments": increments,
        "split": split, "dips_described": len(dips),
        "terminal_windows": wins, "terminal_selected": sel,
        "terminal_status": "SELECTED" if sel else "TERMINAL_SLOPE_NOT_ASSESSABLE",
        "terminal_rule": "longest qualified window whose adjusted R² is within 0.0001 of the highest; a window has 3 or more consecutive "
                         "quantified samples strictly after the peak, a negative slope and a span of at least 2 apparent half-lives",
        "terminal_n_qualified": len(qual), "terminal_thalf_range": [min(q_th), max(q_th)] if q_th else None,
        "auc_0_tlast": a_last, "tlast": float(tq[-1]), "tail_share": tail, "caveats": caveats,
        "_t": tq.tolist(), "_c": cq.tolist(),
    })
    return out


def _p_t(t, df):
    """Two-sided p of a t statistic; a statistic of zero is p = 1 (the incomplete beta is not evaluated at its end point)."""
    return 1.0 if abs(t) < 1e-9 else float(max(0.0, min(1.0, 2 * (1 - _t_cdf(abs(t), df)))))


_INDEPENDENT = {"INDEPENDENT", "INDEPENDENT_GROUPS", "INDEPENDENT_COHORTS", "DESTRUCTIVE_INDEPENDENT",
                "INDEPENDENT_GROUPS_ACROSS_MATRICES_AND_TIMES"}


def _dependence_unresolved(members, across_times=False):
    """R1: absent dependence metadata no longer counts as independence. The calculation still runs, as a sensitivity
    reading (CANNOT_ASSESS + SENSITIVITY_ONLY + SAMPLING_DEPENDENCE_UNRESOLVED)."""
    reasons = []
    if across_times and any(m[0].get("sampling_dependence") is None for m in members):
        reasons.append("independence across sampling times is not stated (metadata.sampling_dependence absent)")
    if any(m[0].get("dose_group_dependence") is None for m in members):
        reasons.append("independence between dose groups is not stated (metadata.dose_group_dependence absent)")
    return reasons


def _independence_restrictions(members, across_times=False):
    """Gate explicitly documented unsafe/unknown dependence (variance withheld). Absent metadata is handled by
    _dependence_unresolved (R1: sensitivity reading, never assumed independent)."""
    independent = _INDEPENDENT
    reasons = []
    if across_times and any(m[0].get("sampling_dependence") is not None and
                            str(m[0]["sampling_dependence"]).upper() not in independent for m in members):
        reasons.append("independent-time Bailer variance withheld: serial or unresolved sampling needs time covariance or individual AUCs")
    if any(m[0].get("dose_group_dependence") is not None and
           str(m[0]["dose_group_dependence"]).upper() not in independent for m in members):
        reasons.append("independent-dose variance withheld: cross-dose pairing or independence is not established")
    return reasons


def _removal_outcome(full_label, reruns, unit):
    """R2. reruns: [(removed unit, label or None)]; None = the rerun falls below the check's own minimum (or breaks the
    window). Returns (label, flags, record). Only a full-data contradiction goes through the removal gate."""
    if not str(full_label).startswith("EXCLUDED"):
        return full_label, [], None
    not_ok = [u for u, lab in reruns if lab is None]
    lost = [u for u, lab in reruns if lab is not None and not str(lab).startswith("EXCLUDED")]
    flags = (["LOO_NOT_ASSESSABLE"] if (not reruns or not_ok) else []) + (["SINGLE_POINT_SUPPORT"] if lost else [])
    record = {"unit": unit, "required": len(reruns), "assessable": len(reruns) - len(not_ok),
              "not_assessable": not_ok, "lost_when_removed": lost, "status": "DEFERRED" if flags else "PASSED"}
    if flags:
        record["reason"] = ("contradiction in the full data; " + ("removal robustness unknown" if "LOO_NOT_ASSESSABLE" in flags else "")
                            + ("; " if len(flags) == 2 else "") + (f"lost when {', '.join(map(str, lost))} is removed" if lost else "")
                            + "; formal exclusion deferred")
    return ("NOT_EXCLUDED" if flags else full_label), flags, record


def _l(v):
    return [float(x) for x in v]


def _wrap(text, n):
    import textwrap
    return textwrap.wrap(text, n) or [""]


def _t_cdf(x, df):
    # regularized incomplete beta via continued fraction (Numerical Recipes betacf)
    def betacf(a, b, xx):
        qab, qap, qam = a + b, a + 1, a - 1
        cc, d = 1.0, 1 - qab * xx / qap
        d = 1 / (d if abs(d) > 1e-30 else 1e-30); h = d
        for m in range(1, 300):
            m2 = 2 * m
            aa = m * (b - m) * xx / ((qam + m2) * (a + m2))
            d = 1 + aa * d; d = 1 / (d if abs(d) > 1e-30 else 1e-30)
            cc = 1 + aa / cc if abs(1 + aa / cc) > 1e-30 else 1e-30
            h *= d * cc
            aa = -(a + m) * (qab + m) * xx / ((a + m2) * (qap + m2))
            d = 1 + aa * d; d = 1 / (d if abs(d) > 1e-30 else 1e-30)
            cc = 1 + aa / cc if abs(1 + aa / cc) > 1e-30 else 1e-30
            de = d * cc; h *= de
            if abs(de - 1) < 3e-14:
                break
        return h
    xx = df / (df + x * x)
    a, b = df / 2, 0.5
    bt = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(xx) + b * math.log(1 - xx))
    ib = bt * betacf(a, b, xx) / a if xx < (a + 1) / (a + b + 2) else 1 - bt * betacf(b, a, 1 - xx) / b
    return 1 - 0.5 * ib if x > 0 else 0.5 * ib


def _t_upper(x, df):
    """Upper-tail probability P(T > x) for x >= 0, computed on the tail so that far quantiles keep their precision."""
    if x <= 0:
        return 0.5
    if df / (df + x * x) <= 0:
        return 0.0
    return _t_cdf(-x, df)   # for a negative argument _t_cdf returns the tail 0.5·I_x(df/2, 1/2) directly


def t_ppf(p, df):
    """Student t quantile. R8: the upper search bracket grows until it covers p, so the extreme quantiles that a large
    comparison family needs (for example 1 - 0.025/m with df = 1) are not truncated at a fixed ceiling; p below 0.5 is
    answered by symmetry instead of returning 0."""
    df = float(df)
    if not (math.isfinite(df) and df > 0):
        raise ValueError("t_ppf needs positive finite degrees of freedom")
    if p <= 0:
        return -math.inf
    if p >= 1:
        return math.inf
    if p == 0.5:
        return 0.0
    if p < 0.5:
        return -t_ppf(1 - p, df)
    tail = 1 - p
    lo, hi = 0.0, 1.0
    while _t_upper(hi, df) > tail:
        lo, hi = hi, hi * 2
        if hi > 1e300:
            return math.inf
    for _ in range(300):
        mid = (lo + hi) / 2
        if _t_upper(mid, df) > tail:
            lo = mid
        else:
            hi = mid
        if hi - lo <= 1e-12 * max(1.0, hi):
            break
    return (lo + hi) / 2


T3P_TIME_DEV = 0.10   # pairing distance: a candidate time pair needs |t_H - t_L| <= 10 % of t (r4.1)


T3P_ALPHA = 0.05


def _t3p_neighbour_slopes(pts, t):
    """Absolute ln-concentration secant slopes from t to the samples just before and just after it on the same curve.
    None when t is the first or last sample or a neighbour (or t itself) is not a quantified positive concentration."""
    times = sorted(pts)
    k = times.index(t)
    if k == 0 or k == len(times) - 1:
        return None
    out = []
    for a, b in ((times[k - 1], t), (t, times[k + 1])):
        pa, pb = pts[a], pts[b]
        if not all(p["status"] == "QUANTIFIED" and (p.get("c") or 0) > 0 for p in (pa, pb)) or b <= a:
            return None
        out.append(abs(math.log(pb["c"]) - math.log(pa["c"])) / (b - a))
    return out


def _sourced_time_bound(card):
    """Round 3: a timing-error bound the input states, with its source: metadata t3p_time_offset_bound_ln (a bound on the
    |ln C| change the sampling-time offset can cause) and t3p_time_offset_bound_source. Either missing: None."""
    b = (card or {}).get("t3p_time_offset_bound") or {}
    ln, src = _num(b.get("ln")), str(b.get("source") or "").strip()
    return (ln, src) if ln is not None and ln >= 0 and src else None


def _t3p_offset_bound(pts_l, pts_h, tl, th, cards=()):
    """r4.4 item 19, round 3 (2026-11-24): an offset time enters the formal family only with a timing-error bound the input
    states with its source (on either dose's card). The secant estimate (|t_H - t_L| x the largest ln secant next to either
    time) is kept as an illustration only: it assumes a monotone slope between neighbouring samples, which the samples
    cannot test (a fast drop between two samples breaks it). Returns (bound, record); bound is None without a sourced bound."""
    off = th - tl
    sl, sh = _t3p_neighbour_slopes(pts_l, tl), _t3p_neighbour_slopes(pts_h, th)
    rec = {"t_low": tl, "t_high": th, "offset_h": off, "aligned": False,
           "secant_estimate_ln": abs(off) * max(sl + sh) if sl is not None and sh is not None else None,
           "secant_note": "illustration only: assumes a monotone ln slope between neighbouring samples (not testable)"}
    sourced = next((x for x in (_sourced_time_bound(c) for c in cards) if x), None)
    if sourced:
        return sourced[0], rec | {"bound_ln": sourced[0], "bound_basis": "SOURCED", "bound_source": sourced[1]}
    return None, rec | {"bound_ln": None, "bound_reason": "no timing-error bound stated in the input with its source"}


def _p_two_sided(tstat, df):
    return _p_t(tstat, df)


def holm(ps):
    """Holm step-down adjusted p values (valid under any dependence between time points)."""
    m = len(ps)
    order = sorted(range(m), key=lambda i: ps[i])
    adj, run = [None] * m, 0.0
    for rank, i in enumerate(order):
        run = max(run, min(1.0, (m - rank) * ps[i]))
        adj[i] = run
    return adj


def _tp_summary(h, l, dh, dl):
    """d(t) = ln(m_H/D_H) - ln(m_L/D_L); SE = sqrt(CV_H^2/n_H + CV_L^2/n_L); Welch-Satterthwaite df."""
    mh, ml, sh, sl = h["c"], l["c"], h["sd"], l["sd"]
    d = math.log(mh / dh) - math.log(ml / dl)
    vh, vl = (sh / mh) ** 2 / h["n"], (sl / ml) ** 2 / l["n"]
    se = math.sqrt(vh + vl)
    df = (vh + vl) ** 2 / (vh ** 2 / (h["n"] - 1) + vl ** 2 / (l["n"] - 1))
    tq = t_ppf(1 - T3P_ALPHA / 2, df)
    return {"d": d, "se": se, "df": df, "ci": [d - tq * se, d + tq * se], "p": _p_two_sided(d / se, df)}


def t3p_series(members, rows, common, pts):
    """Pre-specified pair: the lowest and the highest dose that have SD and n at a shared time
    (chosen from data availability only, before any ratio is seen); tested times: every shared
    nominal time with SD and n >= 2 at both doses."""
    res = {"t3p_label": "CANNOT_ASSESS", "t3p_flags": [], "t3p_data_level": None, "t3p_dose_pair": None,
           "t3p_times": [], "t3p_ln_ratio_ci": [], "t3p_p_holm": [], "skipped": []}
    design_reasons = _independence_restrictions(members)
    if design_reasons:
        res.update(reason="; ".join(design_reasons), t3p_flags=["SAMPLING_DEPENDENCE_UNRESOLVED"])
        return res
    unresolved = _dependence_unresolved(members)   # R1: absent metadata -> the contrast runs as a sensitivity reading
    if not any(p.get("sd") is not None for d in pts for p in d.values()):
        res["reason"] = "no SD or n at the concentration points"; return res
    order = range(len(members))
    pairs = sorted(((i, j) for i in order for j in order if i < j), key=lambda ij: (-(rows[ij[1]]["dose"] / rows[ij[0]]["dose"]), ij[0]))
    first_skipped, fallback = None, None
    for i, j in pairs:
        tested, skipped = [], []
        for tl in sorted(pts[i]):
            if not pts[j]:
                break
            th = min(pts[j], key=lambda x: abs(x - tl))
            pl, ph = pts[i][tl], pts[j][th]
            why = None
            if abs(th - tl) > T3P_TIME_DEV * max(tl, 1e-9):
                why = "no matching sampling time at the other dose"
            elif "BLQ" in (pl["status"], ph["status"]) or not pl["c"] or not ph["c"]:
                why = "BLQ or read as 0"
            elif pl.get("sd") is None or ph.get("sd") is None:
                why = (pl.get("sd_note") or ph.get("sd_note") or "no SD")
            elif not (pl["sd"] > 0 and ph["sd"] > 0):   # A9: a zero SD gives no usable spread (and no division by zero)
                why = "SD is zero or negative at one dose: no usable spread"
            elif min(pl.get("n") or 0, ph.get("n") or 0) < 2:
                why = "n < 2 or not reported"
            if why:
                skipped.append({"t": tl, "t_high": th, "reason": why})
            else:
                tested.append((tl, th, pl, ph))
        if first_skipped is None:
            first_skipped = skipped
        # r4.4 item 19: the pair needs one time that is aligned or has a timing-error bound (data availability only, no ratio)
        cards_ij = (members[i][0], members[j][0])
        if any(abs(th - tl) <= DOSE_TIME_ABS or _t3p_offset_bound(pts[i], pts[j], tl, th, cards_ij)[0] is not None for tl, th, _, _ in tested):
            break
        if tested and fallback is None:
            fallback = (i, j, tested, skipped)
    else:
        if fallback is None:
            res["reason"] = "no dose pair has SD and n ≥ 2 at a shared time point"
            res["skipped"] = first_skipped or []
            return res
        i, j, tested, skipped = fallback   # only offset times without a bound: sensitivity reading below
    dl, dh = rows[i]["dose"], rows[j]["dose"]
    # r4.4 item 19 (2026-11-24): both actual times are kept. An aligned time is tested against 0; an offset time is tested
    # against the band the offset alone can produce (|d| beyond the bound), and enters the formal family only with that bound
    timing = []
    for tl, th, _, _ in tested:
        if abs(th - tl) <= DOSE_TIME_ABS:
            timing.append({"t_low": tl, "t_high": th, "offset_h": th - tl, "aligned": True, "bound_ln": 0.0})
        else:
            timing.append(_t3p_offset_bound(pts[i], pts[j], tl, th, (members[i][0], members[j][0]))[1])
    stats_all = [_tp_summary(ph, pl, dh, dl) for _, _, pl, ph in tested]
    for x, tm in zip(stats_all, timing):
        b = tm["bound_ln"]
        x["p_tested"] = x["p"] if not b else (1.0 if abs(x["d"]) <= b else _p_two_sided((abs(x["d"]) - b) / x["se"], x["df"]))
    eligible = [k for k, tm in enumerate(timing) if tm["bound_ln"] is not None]
    unbounded = [k for k, tm in enumerate(timing) if tm["bound_ln"] is None]
    offset_rec = None
    if any(not tm["aligned"] for tm in timing):
        offset_rec = {"rule": "r4.4 item 19 (round 3): sampling times differ between the doses; an offset time is formal only with a timing-error bound stated in the input with its source",
                      "pairs": timing, "n_aligned": sum(tm["aligned"] for tm in timing),
                      "n_bounded": sum(not tm["aligned"] and tm["bound_ln"] is not None for tm in timing), "n_unbounded": len(unbounded)}
        if unbounded:
            nominal = holm([x["p"] for x in stats_all])
            offset_rec["all_pairs_nominal_label"] = ("EXCLUDED_UNDER_STATED_ASSUMPTIONS" if any(p < T3P_ALPHA for p in nominal) else "NOT_EXCLUDED")
            offset_rec["all_pairs_nominal_note"] = "sensitivity reading: every paired time tested against 0 as if the times were aligned"
        res["t3p_time_offset"] = offset_rec
    time_only = False
    if eligible:
        for k in unbounded:
            skipped.append({"t": timing[k]["t_low"], "t_high": timing[k]["t_high"],
                            "reason": f"sampling times differ ({timing[k]['t_low']:g} h vs {timing[k]['t_high']:g} h) without a timing-error bound: "
                                      + timing[k]["bound_reason"] + "; sensitivity only"})
        tested = [tested[k] for k in eligible]
        timing = [timing[k] for k in eligible]
        stats = [stats_all[k] for k in eligible]
    else:
        # no time is aligned or bounded: the contrast runs as if aligned, as a sensitivity reading only
        time_only = True
        stats = stats_all
        for x in stats:
            x["p_tested"] = x["p"]
    p_holm = holm([x["p_tested"] for x in stats])
    sig = [p < T3P_ALPHA for p in p_holm]
    # round 3 (shared rule S12): the premises of the comparison are checked on both dose groups, never on the first only
    gate = formal_premises([members[i][0], members[j][0]])
    res["t3p_premises"] = gate
    flags = []
    if not gate["formal"]:
        flags += ["SENSITIVITY_ONLY"] + [m for m in gate["missing"] if m not in flags]
    if any(p[2].get("sd_note") or p[3].get("sd_note") for p in tested) and "SENSITIVITY_ONLY" not in flags:
        flags.append("SENSITIVITY_ONLY")
    if time_only:
        flags = (flags if "SENSITIVITY_ONLY" in flags else flags + ["SENSITIVITY_ONLY"]) + ["TIME_OFFSET_UNBOUNDED"]
    if unresolved:
        flags = (flags if "SENSITIVITY_ONLY" in flags else flags + ["SENSITIVITY_ONLY"]) + ["SAMPLING_DEPENDENCE_UNRESOLVED"]
    full = "EXCLUDED_UNDER_STATED_ASSUMPTIONS" if any(sig) else "NOT_EXCLUDED"
    # R2: deleted unit = tested time point; Holm is redone on the remaining points. Removing the only matched time
    # leaves nothing to test (LOO_NOT_ASSESSABLE). R3: no default widening; digitization error is not a formal gate here.
    reruns = []
    if full.startswith("EXCLUDED"):
        for k in range(len(tested)):
            rest = [x["p_tested"] for n_, x in enumerate(stats) if n_ != k]
            reruns.append((f"{tested[k][0]:g} h", None if not rest else
                           "EXCLUDED_UNDER_STATED_ASSUMPTIONS" if any(p < T3P_ALPHA for p in holm(rest)) else "NOT_EXCLUDED"))
    label, rflags, rec = _removal_outcome(full, reruns, "matched sampling time")
    flags += rflags
    res["t3p_removal"] = rec
    if rflags:
        res["t3p_sensitivity_label"] = full
    if "SENSITIVITY_ONLY" in flags:
        res["t3p_sensitivity_label"] = full
        label = "CANNOT_ASSESS"
    k_min = min(range(len(p_holm)), key=lambda k: p_holm[k])
    res["t3p_margin"] = {"t": tested[k_min][0], "t_high": tested[k_min][1], "ln_ratio": stats[k_min]["d"], "ci95": stats[k_min]["ci"],
                         "time_offset_bound_ln": timing[k_min]["bound_ln"], "p_holm": p_holm[k_min],
                         "note": "decisive contrast: the matched time with the smallest Holm-adjusted p (R3: the margin is always reported)"}
    if label in ("EXCLUDED_UNDER_STATED_ASSUMPTIONS", "NOT_EXCLUDED") and "SENSITIVITY_ONLY" not in flags:
        # R4: one dose pair is included, so the family is its matched time contrasts
        res["t3p_family"] = {"scope": f"dose-normalised concentration, {dl:g} vs {dh:g} mg/kg, at matched times in this dose series",
                             "analysis_unit": "matched sampling time (group mean, SD and n at both doses)",
                             "members": [f"{t:g} h" if abs(th - t) <= DOSE_TIME_ABS else f"{t:g} h / {th:g} h" for t, th, _, _ in tested],
                             "m": len(tested), "dose_pairs_included": 1,
                             "method": "Holm, two-sided", "family_alpha": T3P_ALPHA}
    res.update({"t3p_label": label, "t3p_flags": flags, "t3p_data_level": "GROUP_SUMMARY_SD",
                "t3p_dose_pair": [dl, dh], "t3p_times": [t for t, _, _, _ in tested],
                "t3p_time_pairs": [[tm["t_low"], tm["t_high"]] for tm in timing],
                "t3p_ln_ratio_ci": [{"t": tm["t_low"], "t_low": tm["t_low"], "t_high": tm["t_high"], "time_offset_h": tm["offset_h"],
                                     "aligned": tm["aligned"], "time_offset_bound_ln": tm["bound_ln"],
                                     "ln_ratio": x["d"], "ci95": x["ci"], "se": x["se"], "df": x["df"], "p_raw": x["p"], "p_tested": x["p_tested"],
                                     **({"ci95_with_offset_bound": [x["ci"][0] - tm["bound_ln"], x["ci"][1] + tm["bound_ln"]]} if tm["bound_ln"] else {})}
                                    for tm, x in zip(timing, stats)],
                "t3p_p_holm": p_holm, "significant": sig, "skipped": skipped,
                "method": "d(t) = ln(m_H/D_H) − ln(m_L/D_L); SE = √(CV_H²/n_H + CV_L²/n_L); Welch–Satterthwaite df; Holm, two-sided family-wise 5 %"
                          + ("; an offset time is tested for |d| beyond its timing-error bound" if any(not tm["aligned"] for tm in timing) and not time_only else ""),
                "pair_rule": "lowest and highest doses with SD and n ≥ 2 at a shared time (chosen on data availability only, before any ratio is seen)"})
    return res


# R6: the code NOT_ANSWERABLE_YET is kept; the board shows "Insufficient evidence".
ST_YES, ST_PART, ST_NO, ST_NA = "Answerable", "Partly answerable", "Insufficient evidence", "Not applicable"


ST_CODE = {ST_YES: "ANSWERABLE", ST_PART: "PARTLY_ANSWERABLE", ST_NO: "NOT_ANSWERABLE_YET", ST_NA: "NOT_APPLICABLE"}


def _e(x):
    return html.escape(str(x))


def _f(x, nd=3):
    return "—" if x is None else f"{x:.{nd}g}"


def page_slug(x):
    return re.sub(r"[^a-z0-9]+", "-", str(x).lower()).strip("-")


ST_CLASS = {ST_YES: "st-yes", ST_PART: "st-part", ST_NO: "st-no", ST_NA: "st-na"}


ST_SHORT = {ST_YES: "Answerable", ST_PART: "Partly", ST_NO: "Not yet", ST_NA: "N/A"}


ST_ORDER = (ST_YES, ST_PART, ST_NO, ST_NA)


def _wb(x):
    """Escaped text that may wrap after underscores (long state labels in narrow table cells)."""
    return _e(x).replace("_", "_<wbr>")


def _hjoin(xs):
    xs = list(xs)
    return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " and " + xs[-1] if xs else ""


def _hnum(n):
    return ("no", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten")[n] if 0 <= n <= 10 else str(n)


def _hcap(x):
    w = x.split(" ")[0]
    return x[:1].upper() + x[1:] if w.isalpha() and w.islower() and len(w) > 2 else x  # keep symbols such as ka, tlag or F
