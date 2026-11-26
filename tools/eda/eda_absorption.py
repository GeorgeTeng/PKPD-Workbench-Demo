"""EDA Absorption section (r4 items 16-23), host code only.

Reads an EDA run root (``source_tables.json`` and ``dose_normalization_assessment.json``),
selects extravascular (EV) concentration datasets and writes ``<root>/absorption/``:

* ``absorption.json``  every computed value, label, reason and panel path;
* ``<panel>_*.png``    panels of figures A–F (each panel carries only its own marks) and ``Q<n>_<study>.png``,
                       the single most explanatory evidence of each question row;
* ``index.html``, ``species-*.html``  the Absorption category of the EDA review.

Page structure (A0.11 question-first draft, 2026-11-05): species → study → data card → nine question
rows. Each row has its status, one conclusion in three parts (what was observed; which points, animals
or test result it rests on; how far it reaches given the record level), the primary evidence beside it
(one panel, or one data row) with the record level beneath, what is missing, and the other panels by tier.
Figures A–F are panel templates: A rise and onset, B decline and dips, C dose, D EV against IV,
E conditions, F reported parameters.

No PK model fitting, smoothing, back-extrapolation, imputation or scientific release. Only the
descriptive regressions allowed by r4 A0.7 are computed. Every test result carries the
r4 A0.3 label; project-set tolerances make results SENSITIVITY_ONLY.
"""
from __future__ import annotations

import html
import hashlib
import itertools
import json
import math
import re
import sys
from pathlib import Path
from urllib.parse import quote

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402


def _eda_common():
    """Shared board identity, hypothesis_v1 and coverage helpers (eda_common.py beside this module)."""
    import hashlib as _hashlib
    import importlib.util as _util
    path = Path(__file__).resolve().with_name("eda_common.py")
    if not path.is_file():
        import eda_common  # a frozen copy without its sibling: use the one on sys.path
        return eda_common
    name = "_eda_common_" + _hashlib.sha256(str(path).encode()).hexdigest()[:12]
    if name not in sys.modules:
        spec = _util.spec_from_file_location(name, path)
        module = _util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


RULES = _eda_common().rules_entry("absorption")  # the one rules version for this section: rules/rules_manifest.json
RULES_VERSION = RULES["version"]
FIT_NOTE = _eda_common().FIT_NOTE
COMMON = _eda_common()

VERSION = RULES.get("output_version") or "unrecorded"   # M3/L7: one version source, rules/rules_manifest.json (r4.4: EDA_ABSORPTION_R4_4_20261124)
TOL = COMMON.TOL
SPAN_MIN = COMMON.SPAN_MIN
ADJ_R2_MIN = COMMON.ADJ_R2_MIN
LATE_FIRST = COMMON.LATE_FIRST
TAIL_FLAG = 0.05      # review guide Q6: an estimated tail fraction of 5 % or less at the common endpoint, for each route
GUIDE = "EDA_absorption_rules_r4.3_review_guide_20261124.md (Appendix A holds the examples)"   # the human review guide this build follows
ADJ_R2_TIE = COMMON.ADJ_R2_TIE
HL_CUTS = (0.80, 1.25, 2.0)   # review guide Q5: EV/IV apparent half-life ratio grades
HL_GRADES = ("STEEPER", "APPROXIMATELY_PARALLEL", "MODERATELY_SHALLOWER", "MARKEDLY_SHALLOWER")
HL_WORDS = {"STEEPER": "steeper than", "APPROXIMATELY_PARALLEL": "approximately parallel to",
            "MODERATELY_SHALLOWER": "moderately shallower than", "MARKEDLY_SHALLOWER": "markedly shallower than"}
FF_READING = {"STEEPER": "EV_STEEPER_REVIEW", "APPROXIMATELY_PARALLEL": "COMMON_TERMINAL_COMPATIBLE",
              "MODERATELY_SHALLOWER": "ABSORPTION_INFLUENCED_CANDIDATE", "MARKEDLY_SHALLOWER": "ABSORPTION_INFLUENCED_CANDIDATE"}
DOSE_TIME_ABS = COMMON.DOSE_TIME_ABS
PAIR_TIME_REL, PAIR_TIME_ABS = 0.05, 0.02  # EV/IV and condition pairs: matched within tolerance

# ---------------------------------------------------------------- data extraction


_num = COMMON._num


def _dose(entry):
    meta = entry.get("metadata", {})
    reg = COMMON.dose_regimen(entry)
    if reg["loading_plus_infusion"]:
        # L8: never the loading dose; a stated delivered amount for a completed input, otherwise no denominator
        return (reg["denominator_mg_kg"], "metadata delivered dose") if reg["denominator_mg_kg"] else (None, "SUSPENDED: " + reg["reason"])
    for key in ("dose_mg_kg", "dose_mg_per_kg"):
        value = _num(meta.get(key))
        if value is not None and value > 0:
            return value, "metadata." + key
    for field, text in (("title", entry.get("title", "")), ("dosing_regimen", meta.get("dosing_regimen", "")),
                        ("notes", entry.get("notes", "") or "")):
        m = re.search(r"(\d+(?:\.\d+)?)\s*mg/kg", str(text))
        if m:
            return float(m.group(1)), field
    return None, "NOT_FOUND"


def _status(raw_status, raw=None):
    qualifier = COMMON.assay_qualifier(raw_status, raw)
    if qualifier:
        return qualifier if qualifier != "MISSING" else "OTHER"
    s = str(raw_status or "").strip().upper()
    if s == "REPORTED_ZERO_PREDOSE":
        return s
    if s == "QUANTIFIED":
        return "QUANTIFIED"
    return "OTHER"


# Cross-route pairing facts. A table sets them in metadata; a concentration column may set them for itself
# (with subject_id and occasion), and the column value wins. Only a source statement sets them to true.
PAIRING_FLAGS = ("cross_route_identity_verified", "washout_verified", "occasion_compatibility_verified")


def _series_card(card, s, n_series):
    """The card of one column: its own subject, dose and pairing facts; the dataset id names the column."""
    ref_id = quote(str(card["dataset_id"]), safe="") + "::" + quote(str(s["series_id"]), safe="")
    flags = {k: (s.get("pairing") or {}).get(k, card.get(k)) is True for k in PAIRING_FLAGS}
    return dict(card, source_dataset_id=card["dataset_id"], source_column_id=s["series_id"], reference_id=ref_id,
                source_title=card["title"], dataset_id=ref_id if n_series > 1 else card["dataset_id"],
                title=card["title"] + " · " + s["label"], dose_mg_per_kg=s["dose"],
                dose_given_mg_per_kg=s.get("dose_given") or s["dose"], dose_given_from=s.get("dose_given_from"),
                cross_route_subject_id=s.get("subject_id") or card.get("cross_route_subject_id"),
                subject_occasion=s.get("occasion"), iv_input=s.get("iv_input") or card.get("iv_input"), **flags)


def extract(entry):
    """Return the dataset card and one series per concentration column."""
    meta = entry.get("metadata", {})
    cols = entry.get("columns", [])
    time_col = next((c for c in cols if c.get("meaning") == "TIME"), {})
    conc_cols = [c for c in cols if c.get("meaning") == "CONCENTRATION"]
    unit = conc_cols[0].get("unit") if conc_cols else "NOT_FOUND"
    record_category = meta.get("record_category", "NOT_FOUND")
    unit_text = entry.get("experimental_unit", "") or ""
    identity_unverified = not COMMON.serial_identity_verified(entry)
    if record_category == "INDIVIDUAL":
        level = "INDIVIDUAL_IDENTITY_UNVERIFIED" if identity_unverified else "INDIVIDUAL"
    elif record_category == "GROUP_SUMMARY":
        level = "GROUP_MEAN"
    else:
        level = record_category or "NOT_FOUND"
    digitized = meta.get("observation_source") == "DIGITIZED_FROM_FIGURE"
    dose, dose_from = _dose(entry)
    regimen = str(meta.get("dosing_regimen", ""))
    single = "single" in regimen.lower()
    disp = _dispersion_columns(cols, conc_cols)
    sd_cols = [x for v in disp.values() for x in v.values() if x]
    notes_all = " ".join([str(entry.get("notes") or ""), entry.get("title", ""), unit_text])
    n_col = next((c["id"] for c in cols if c.get("meaning") in ("N", "N_ANIMALS") or re.fullmatch(r"\s*n\s*(\(.*\))?\s*", str(c.get("header", "")).lower())), None)
    # L2: the same reader and range policy as Distribution and Elimination (metadata n, then the source text incl. the unit)
    n_note, n_range, n_basis = COMMON.sample_size(" ".join([notes_all, str(entry.get("experimental_unit") or "")]), meta)
    series = []
    for c in conc_cols:
        dc = disp.get(c["id"], {})
        pts = []
        for r in entry.get("records", []):
            if r.get("qc_status") not in (None, "TECHNICALLY_RETAINED"):
                continue
            t = COMMON.observation_time_h(r, time_col)
            if t is None:
                continue
            raw = r.get("source_raw_values", {}).get(c["id"], r.get(c["id"]))
            st = _status(COMMON.cell_status(r, c["id"]), raw)
            y = _num(r.get(c["id"])) if st in ("QUANTIFIED", "REPORTED_ZERO_PREDOSE") else None
            if st == "REPORTED_ZERO_PREDOSE" and not (t <= 0 and y == 0):
                continue
            if st == "OTHER":
                continue
            sd, sd_note = _point_sd(r, dc, y)
            se = _num(r.get(dc["se"])) if dc.get("se") else None
            n = _num(r.get(n_col)) if n_col else None
            pts.append({"t": t, "c": y, "status": st, "record_id": r.get("record_id"), "sd": sd, "se": se, "sd_note": sd_note,
                        "n": int(n) if n else n_note, "source_row": r.get("source_row"),
                        "source_cell": r.get("source_cells", {}).get(c["id"]),
                        "source_raw_value": r.get("source_raw_values", {}).get(c["id"]),
                        "source_status": COMMON.cell_status(r, c["id"]),
                        **({"source_flags": COMMON.source_flags(r, c["id"])} if COMMON.source_flags(r, c["id"]) else {})})
            if st in COMMON.ASSAY_LABELS and (bound := COMMON.printed_assay_bound(raw)):
                pts[-1]["censoring"] = bound
        pts.sort(key=lambda p: p["t"])
        m = re.search(r"(\d+(?:\.\d+)?)\s*mg/kg", str(c.get("header", "")))
        # round 3 (2026-11-24): a column that names its subject carries that animal's administered dose (dose_given); its dose
        # level is dose_level_mg_kg or the table dose. A column without a subject that prints dose_mg_kg names a dose level.
        subj = COMMON.subject_dosing(entry, c)
        col_level = None if subj["subject_id"] else next((v for v in (_num(c.get("dose_mg_kg")), _num(c.get("dose_mg_per_kg"))) if v is not None and v > 0), None)
        series.append({"series_id": c["id"], "label": c.get("header", c["id"]), "points": pts,
                       "dose": next((v for v in (subj["dose_level_mg_kg"], col_level,
                                   _num(meta.get("series_doses_mg_kg", {}).get(c["id"])), float(m.group(1)) if m else None)
                                    if v is not None and v > 0), None), "dispersion_kind": dc.get("kind"),
                       "dose_given": subj["dose_mg_kg"], "dose_given_from": "column" if subj["dose_mg_kg"] is not None else None,
                       "column": c,
                       "subject_id": COMMON.column_subject(c), "occasion": str(c.get("occasion") or "").strip() or None,
                       "pairing": {k: c[k] for k in PAIRING_FLAGS if k in c}})
    series_doses = {s["dose"] for s in series if s["dose"] is not None}
    predose = [p for s in series for p in s["points"] if p["t"] <= 0]
    baseline = ("REPORTED_ZERO_PREDOSE (source-reported zeros; not proof of absence below LLOQ)"
                if predose and all(p["status"] == "REPORTED_ZERO_PREDOSE" for p in predose) else
                "PREDOSE_OBSERVED (see source values and statuses)" if predose else "DESIGN_ZERO (no pre-dose sample)")
    lloq = _num(meta.get("lloq_ug_mL"))
    unit_scale = {"ug/ml": 1, "µg/ml": 1, "μg/ml": 1, "mg/l": 1, "ng/ml": 1000, "mg/ml": .001}.get(str(unit).lower())
    lloq = lloq * unit_scale if lloq is not None and lloq > 0 and unit_scale is not None else None
    series_kind = "DOSE_COLUMNS" if len(conc_cols) > 1 and len(series_doses) == len(conc_cols) else (
        "INDIVIDUALS" if len(conc_cols) > 1 else "SINGLE")
    for s in series:
        if s["dose"] is None:
            s["dose"] = dose
        if s["dose_given"] is None:
            s["dose_given"], s["dose_given_from"] = s["dose"], dose_from
    # 2026-11-25 multiple dosing: a column that lists its doses (dose_events, the first at time 0) gives a single first-dose
    # curve up to the second dose. Absorption reads only those samples; the later samples are kept for display, never analysed.
    first_interval = _first_dose_intervals(series)
    if first_interval and not single:
        single = True
    route_class = meta.get("route_class", "NOT_FOUND")
    route_detail = meta.get("route_detail", "NOT_FOUND")
    iv_input = None
    if route_class == "IV":   # display only (plot rule P1): the shaded input band; no analysis reads it
        mode, h, src = COMMON.iv_dosing(entry)
        iv_input = {"mode": mode, "infusion_h": h, "source": src}
        for s in series:
            sm, sh, ss = COMMON.iv_dosing(entry, None, s.get("column"))
            s["iv_input"] = {"mode": sm, "infusion_h": sh, "source": ss}
    card = {
        "dataset_id": entry["dataset_id"], "title": entry.get("title", ""),
        "study": ",".join(entry.get("study_source_ids", [])) or "NOT_FOUND",
        "species": meta.get("species", "NOT_FOUND"), "drug": meta.get("drug", "NOT_FOUND"),
        "experiment_arm": meta.get("experiment_arm"), "cohort": meta.get("cohort"),
        "condition": meta.get("condition", "not reported"),
        "route_class": route_class, "route_detail": route_detail, "iv_input": iv_input,
        "matrix": meta.get("matrix", "NOT_FOUND"), "matrix_category": meta.get("matrix_category", "NOT_FOUND"),
        "record_level": level, "digitized": digitized,
        "sampling_dependence": meta.get("sampling_dependence"), "experimental_unit": unit_text,
        "dose_group_dependence": meta.get("dose_group_dependence"),
        # round 3: a sourced timing-error bound for T3p offset times (both fields or none)
        "t3p_time_offset_bound": {"ln": meta.get("t3p_time_offset_bound_ln"), "source": meta.get("t3p_time_offset_bound_source")},
        "dose_proportionality_auc": meta.get("dose_proportionality_auc"),
        "dose_proportionality_equivalence_margin": meta.get("dose_proportionality_equivalence_margin"),
        "n_per_time": ("n column" if n_col else f"{n_note} ({n_basis})" if n_note else
                       f"{n_range[0]}–{n_range[1]} (range in the source; not assigned per time)" if n_range else "not reported"),
        "dispersion": _disp_text(disp) if sd_cols else "not reported",
        "mean_type": _mean_type(notes_all) if level == "GROUP_MEAN" else "n/a",
        "series_kind": series_kind,
        "lloq": lloq if lloq is not None else "not reported", "lloq_unit": unit,
        "lloq_from": "metadata.lloq_ug_mL" if lloq is not None else "NOT_FOUND",
        "dose_mg_per_kg": dose, "dose_from": dose_from, "dose_regimen": COMMON.dose_regimen(entry),
        "dose_basis": meta.get("dose_basis", "NOT_FOUND"), "dosing_regimen": regimen or "NOT_FOUND",
        "single_dose": single, "dose_time_basis": "DESIGN_ZERO", "unit": unit,
        "error_bound": "±5 % (project-set; " + ("digitization reading" if digitized else "analytical error not reported") + ")",
        "identity_verified": "n/a" if level == "GROUP_MEAN" else ("no" if identity_unverified else "yes"),
        "analyte_role": meta.get("analyte_role", "not reported"), "origin": meta.get("origin", "not reported"),
        "baseline_status": baseline, "assay_specificity": meta.get("assay_specificity", "UNKNOWN"), "assay": meta.get("assay"),
        # G5: early coverage counts as justified only when the metadata says so (a source-reported back-extrapolated
        # share or another independent upper bound on the missing early area); the basis text is carried with it
        "early_exposure_justified": meta.get("early_exposure_justified") is True,
        "early_exposure_basis": meta.get("early_exposure_basis") if meta.get("early_exposure_justified") is True else None,
        "cross_route_subject_id": meta.get("cross_route_subject_id"),
        "cross_route_identity_verified": meta.get("cross_route_identity_verified") is True,
        "washout_verified": meta.get("washout_verified") is True,
        "occasion_compatibility_verified": meta.get("occasion_compatibility_verified") is True,
        "dose_occasion": ("first dose (samples up to the second dose of a multiple-dose regimen)" if first_interval else
                          "first dose" if single else "not reported"),
        "first_dose_interval": first_interval,
        "error_bars_hidden": ("some bars hidden by the marker" if "inside the marker" in notes_all.lower() else "not reported") if digitized else "n/a",
        "data_form": "CURVE",
        "source_reported_absolute_f": _source_absolute_f(meta.get("source_reported_absolute_f") or entry.get("source_reported_absolute_f")),
        "notes": (entry.get("notes") or "").strip(),
    }
    gates = []
    if route_class != "EV":
        gates.append("NOT_EV")
    if card["matrix_category"] != "PLASMA_SERUM_BLOOD":
        gates.append("NOT_CENTRAL_MATRIX")
    if not single:
        gates.append("NOT_SINGLE_DOSE")
    if route_detail in ("NOT_FOUND", "", None):
        gates.append("ROUTE_UNKNOWN")
    if str(card["origin"]).upper() in ("ENDOGENOUS", "MIXED") and str(card["assay_specificity"]).upper() != "EXOGENOUS_SPECIFIC":
        gates.append("ENDOGENOUS_REVIEW_REQUIRED")
    card["gates"] = gates
    card["tests_allowed"] = not gates
    # item 19 compares doses given at the same occasion; a repeated-dose occasion (e.g. day 2) is
    # allowed when every dose in the series shares it (steady-state and single-dose AUC are not mixed)
    card["dose_series_allowed"] = not (set(gates) - {"NOT_SINGLE_DOSE"})
    card["occasion"] = "SINGLE_DOSE" if single else _occasion(notes_all + " " + regimen)
    return card, series


def _dose_events(column):
    out = []
    for e in (column or {}).get("dose_events") or []:
        t = _num((e or {}).get("time_h"))
        if t is not None:
            out.append({"time_h": t, "dose_mg_kg": _num(e.get("dose_mg_kg"))})
    return sorted(out, key=lambda e: e["time_h"])


def _first_dose_intervals(series):
    """Cut each series that lists two or more doses, the first at time 0, at its second dose. A sample at the second-dose time
    is a pre-dose trough of the first interval and stays. Returns a summary when every series was cut, else None (then the
    table keeps its NOT_SINGLE_DOSE gate and nothing is cut)."""
    plans = []
    for s in series:
        ev = _dose_events(s.get("column"))
        if len(ev) < 2 or abs(ev[0]["time_h"]) > 1e-9:
            return None
        plans.append((s, ev))
    if not plans:
        return None
    for s, ev in plans:
        cut = ev[1]["time_h"]
        s["dose_events"] = ev
        s["first_interval_end_h"] = cut
        s["points_after_next_dose"] = [p for p in s["points"] if p["t"] > cut + 1e-9]
        s["points"] = [p for p in s["points"] if p["t"] <= cut + 1e-9]
        if ev[0]["dose_mg_kg"] is not None:
            s["dose_given"], s["dose_given_from"] = ev[0]["dose_mg_kg"], "column.dose_events[0]"
    cuts = [s["first_interval_end_h"] for s, _ in plans]
    return {"n_doses": sorted({len(ev) for _, ev in plans}), "second_dose_h": [min(cuts), max(cuts)],
            "n_samples_after_second_dose": sum(len(s["points_after_next_dose"]) for s, _ in plans),
            "basis": "column dose_events"}


def _n_from_notes(text):
    """L2 (2026-11-24): the shared sample-size reader. '3 mice per time point' -> 3; 'source n=10' -> 10; a range such as
    '3 or 4 mice/time' gives no single n (kept as a range by the caller through COMMON.sample_size)."""
    return COMMON.sample_size(text)[0]


def _mean_type(text):
    s = str(text or "").lower()
    g, a = "geometric mean" in s, "arithmetic mean" in s
    if g and a:
        return "UNKNOWN (source conflict: caption says geometric, methods say arithmetic)"
    return "GEOMETRIC" if g else "ARITHMETIC" if a else "not reported"


def _occasion(text):
    m = re.search(r"day\s*(\d+)\s*of\s*treatment|on day\s*(\d+)", str(text).lower())
    return f"REPEATED_DOSE_DAY_{next(x for x in m.groups() if x)}" if m else "REPEATED_OR_UNKNOWN"


_DISP_MEANINGS = COMMON._DISP_MEANINGS


_dispersion_columns = COMMON._dispersion_columns


def _disp_text(disp):
    kinds = sorted({v["kind"] for v in disp.values()})
    return {"SD": "SD column", "SE": "SE column", "BAR_ENDS": "digitized error-bar ends (SD ≈ half-width)"}.get(kinds[0], kinds[0]) if len(kinds) == 1 else ", ".join(kinds)


_point_sd = COMMON._point_sd


# ---------------------------------------------------------------- per-curve calculations (r4 items 16-18, 20)


auc = COMMON.auc


AUC_METHOD = "linear-up/log-down (A0.6)"


def auc_record(points, route_class, *, total_signal_only=False):
    """Rule decision M2 (2026-11-24): the one observed-window AUC record that downstream sections consume directly. It holds the
    status, method, start and end, the grid and sample ids, the truncation reason and, when the area is withheld, why. Observed
    points only: no design zero is added (auc_0_tlast adds one and is a different quantity). An EV area may start at a zero the
    source reports at the dosing time (L1); an IV zero at the dosing time is never an anchor."""
    rec = {"target": "observed-window AUC", "method": AUC_METHOD, "status": None, "value": None, "start_h": None, "end_h": None,
           "grid_h": [], "sample_ids": [], "truncation_reason": None, "zero_anchor": None, "reason": None}
    if total_signal_only:
        return rec | {"status": "WITHHELD_TOTAL_SIGNAL", "reason": "total signal only; endogenous or predose review required"}
    pos_pre = [p for p in points if p.get("t") is not None and p["t"] <= 0 and p.get("status") == "QUANTIFIED" and (p.get("c") or 0) > 0]
    if pos_pre:
        return rec | {"status": "WITHHELD_PREDOSE_SIGNAL", "reason": "quantified predose concentration; drug-free baseline unresolved"}
    q = sorted((p for p in points if p.get("status") == "QUANTIFIED" and p.get("c") is not None and p["c"] > 0
                and p.get("t") is not None and p["t"] > 0), key=lambda p: p["t"])
    cens = sorted(p["t"] for p in points if p.get("status") in COMMON.ASSAY_LABELS and p.get("t") is not None and p["t"] > 0)
    if q:
        inner = [t for t in cens if q[0]["t"] < t < q[-1]["t"]]
        if inner:
            q = [p for p in q if p["t"] < inner[0]]
            rec["truncation_reason"] = (f"the censored sample at {inner[0]:g} h is not bridged; the window ends at the last quantified "
                                        "sample before it")
    anchor = None
    if route_class == "EV":
        anchor = next((p for p in points if p.get("t") == 0 and p.get("c") == 0
                       and p.get("status") in ("QUANTIFIED", COMMON.PREDOSE_ZERO)), None)
    pts = ([anchor] if anchor else []) + q
    t = [float(p["t"]) for p in pts]
    if len({x for x in t if x > 0}) < 3:
        return rec | {"status": "NOT_COMPUTED", "reason": f"fewer than 3 quantified post-dose times ({len({x for x in t if x > 0})})"}
    if len(set(t)) != len(t):
        return rec | {"status": "WITHHELD_DUPLICATE_TIMES", "reason": "duplicate times in one profile; resolve the analysis unit first"}
    return rec | {"status": "OBSERVED_WINDOW", "value": auc(t, [float(p["c"]) for p in pts]), "start_h": t[0], "end_h": t[-1],
                  "grid_h": t, "sample_ids": [p.get("record_id") for p in pts],
                  "zero_anchor": "zero reported by the source at the dosing time" if anchor else None}


def _window_eligible(start, end, thalf, n):
    """r4.4 item 18 (2026-11-24 review): one eligibility rule for every terminal window the flip-flop reading uses, on unrounded
    values: a declining fit (t½ > 0), at least 3 samples and a span of at least SPAN_MIN apparent half-lives."""
    try:
        return bool(thalf and thalf > 0 and (n or 0) >= 3 and (float(end) - float(start)) / float(thalf) >= SPAN_MIN)
    except (TypeError, ValueError):
        return False


def _ratio_txt(r, cuts=None):
    """A ratio shown with enough decimals to stay on the same side of every grade cut as its unrounded value
    (1.24996 is shown as 1.24996, not 1.25)."""
    cuts = HL_CUTS if cuts is None else cuts
    for d in range(2, 7):
        txt = f"{r:.{d}f}"
        if all((float(txt) >= c) == (r >= c) for c in cuts):
            return txt
    return f"{r:.8g}"


def _qualified(w):
    """A terminal window qualifies on its unrounded slope and span (A8); older records fall back to the stored values."""
    if "qualified" in w:
        return bool(w["qualified"])
    return bool(w.get("span_ratio") and w["span_ratio"] >= SPAN_MIN and w.get("slope") is not None and w["slope"] < 0
                and (w.get("adjR2") is None or w["adjR2"] >= ADJ_R2_MIN))


curve_metrics = COMMON.curve_metrics


# ---------------------------------------------------------------- multi-curve tests (items 19, 18/22, 23)


def _common_times(curves, rel=0.0, absolute=DOSE_TIME_ABS, clip_endpoint=False):
    """Times present in every curve (within tolerance) and <= the earliest tlast."""
    base = curves[0]["_t"]; tl = min(c["tlast"] for c in curves)
    out = []
    for t in base:
        if t > tl + (max(absolute, rel * t) if clip_endpoint else 1e-9):
            continue
        hit = []
        for c in curves:
            j = min(range(len(c["_t"])), key=lambda k: abs(c["_t"][k] - t))
            if abs(c["_t"][j] - t) <= max(absolute, rel * t):
                hit.append(j)
            else:
                break
        if len(hit) == len(curves):
            out.append(hit)
    return out


def _censored_interval(curve, start, end):
    """Include the observations bracketing each interpolated endpoint."""
    censored = curve.get("censored_samples")
    if not censored:
        return False
    left = max((t for t in curve["_t"] if t <= start), default=start)
    right = min((t for t in curve["_t"] if t >= end), default=end)
    return any(left <= p["t"] <= right for p in censored)


def _window_auc(c, T):
    if _censored_interval(c, 0, T):
        return None
    anchored = {"_t": np.r_[0.0, c["_t"]], "_c": np.r_[c.get("auc_baseline_concentration", 0.0), c["_c"]]}
    t, y = _interval_profile(anchored, 0.0, T)
    return auc(t, y)


def _source_absolute_f(raw):
    """Explicit, curated source result; never infer an absolute F from a window ratio."""
    if not raw:
        return None
    value = _num(raw.get("value"))
    unit = str(raw.get("unit", "")).strip().lower()
    if value is None or value < 0 or unit not in ("%", "percent", "fraction", "1"):
        raise ValueError("source_reported_absolute_f requires a nonnegative value and explicit % or fraction unit")
    if not raw.get("method") or not raw.get("provenance"):
        raise ValueError("source_reported_absolute_f requires method and provenance")
    return {**raw, "fraction": value / 100 if unit in ("%", "percent") else value,
            "status": "SOURCE_REPORTED_ABSOLUTE_F", "independently_recomputed": False}


def _source_f_text(result, compact=False):
    f = result.get("source_reported_absolute_f")
    if not f:
        return "Source-reported absolute F: not supplied."
    provenance = f["provenance"]
    if compact and isinstance(provenance, dict):
        # Long integrity hashes remain in structured evidence; plots cite the human-readable source.
        preferred = {k: v for k, v in provenance.items() if k.lower() in ("citation", "url", "doi", "location", "table", "page")}
        provenance = preferred or {k: v for k, v in provenance.items() if "sha" not in k.lower() and "hash" not in k.lower()}
    loc = "; ".join(f"{k}: {v}" for k, v in provenance.items()) if isinstance(provenance, dict) else str(provenance)
    method = str(f["method"]).strip().rstrip(".")
    return f"Source-reported absolute F = {100 * f['fraction']:g}%. Method: {method}. Provenance: {loc.rstrip('.')}."


def _interval_profile(curve, start, end, dense=False):
    """Clip without extrapolation using the same linear-up/log-down segments as auc()."""
    t, c = np.asarray(curve["_t"], float), np.asarray(curve["_c"], float)
    if start < t[0] - 1e-10 or end > t[-1] + 1e-10 or end <= start:
        raise ValueError("integration interval must lie inside the observed profile")
    ts, cs = [], []
    for i in range(len(t) - 1):
        lo, hi = max(start, t[i]), min(end, t[i + 1])
        if hi <= lo:
            continue
        xs = np.linspace(lo, hi, 33) if dense else np.asarray([lo, hi])
        w = (xs - t[i]) / (t[i + 1] - t[i])
        ys = c[i] * np.exp(w * math.log(c[i + 1] / c[i])) if 0 < c[i + 1] < c[i] else c[i] + w * (c[i + 1] - c[i])
        ts.extend(xs if not ts else xs[1:]); cs.extend(ys if not cs else ys[1:])
    return np.asarray(ts), np.asarray(cs)


def _ratio_window_text(result):
    return f"{result['window_start_h']:g}–{result['window_end_h']:g} h"


def _e6_point_reading(ratio):
    if 0.80 <= ratio <= 1.25:
        return "NO_SIGN"
    return "POINTS_TO_NONLINEARITY" if ratio < 0.50 or ratio > 2.0 else "INCONCLUSIVE"


def _half_life_dose_reading(rows):
    ranges = [row.get("thalf_range") for row in rows]
    if len(rows) < 2 or not all(ranges) or not all(row.get("thalf") for row in rows):
        return "NOT_AVAILABLE"
    if max(r[0] for r in ranges) <= min(r[1] for r in ranges):
        return "NO_SIGN"
    if all(a[1] < b[0] for a, b in zip(ranges, ranges[1:])):
        return "POINTS_TO_NONLINEARITY"
    return "INCONCLUSIVE"


def _reported_oral_summary(table):
    doses, peaks, areas = (table[k] for k in ("dose_mg_kg", "cmax_ug_ml", "auc_inf_ug_h_ml"))
    if (len(doses) < 2 or len(peaks) != len(doses) or len(areas) != len(doses)
            or sorted(set(doses)) != doses or not all(math.isfinite(v) and v > 0 for v in doses + peaks + areas)
            or not table.get("source") or not table.get("location")):
        raise ValueError("Invalid source-reported oral dose series")
    for key in ("cmax_se", "auc_inf_se"):
        if key in table and (len(table[key]) != len(doses) or not all(math.isfinite(v) and v >= 0 for v in table[key])):
            raise ValueError("Invalid source-reported standard errors")
    peak_ratio = peaks[-1] / peaks[0] * doses[0] / doses[-1]
    area_ratio = areas[-1] / areas[0] * doses[0] / doses[-1]
    return (f"Published oral summaries at {doses[-1]:g} versus {doses[0]:g} mg/kg give a Cmax/dose ratio of "
            f"{peak_ratio:.2f} and an AUC(0–∞)/dose ratio of {area_ratio:.2f}.")


CMAX_SCREEN_SHARE_MIN = 0.8   # R7 item 3: comparable exposure windows (the common window holds at least 80 % of each group's observed AUC)


def dose_series(members, dose_block):
    """Item 19. members: list of (card, metrics) with distinct doses."""
    members = sorted(members, key=lambda m: _mdose(m))
    curves = [m[1] for m in members]
    common = _common_times(curves, clip_endpoint=True)
    if not common:
        return {"status": "NOT_ASSESSABLE", "reason": "no sampling time shared by all doses"}
    T = min(curves[0]["_t"][common[-1][0]], *(c["tlast"] for c in curves))
    rows = []
    for mem in members:
        card, m = mem[0], mem[1]
        d = _mdose(mem)
        aw = _window_auc(m, T)
        if aw is None:
            return {"status": "NOT_ASSESSABLE", "reason": "censored observation in the common AUC interval"}
        th = m["terminal_selected"]["thalf"] if m["terminal_selected"] else None
        qths = [w["thalf"] for w in m["terminal_windows"] if w["thalf"] and _qualified(w)]
        rows.append({"dataset_id": card["dataset_id"], "series_id": mem[2]["series_id"] if len(mem) > 2 else None, "dose": d, "tmax": m["tmax"], "cmax_d": m["cmax"] / d,
                     "thalf": th, "thalf_range": [min(qths), max(qths)] if qths else None,
                     "aucW_d": aw / d, "auc_last_d": m["auc_0_tlast"] / d if m["auc_0_tlast"] else None,
                     "share_window": aw / m["auc_0_tlast"] if m["auc_0_tlast"] else None,
                     "tail_share": m["tail_share"], "split_class": (m["split"] or {}).get("class")})
    lo, hi = rows[0], rows[-1]
    R = hi["aucW_d"] / lo["aucW_d"]
    cmax_ratio = hi["cmax_d"] / lo["cmax_d"]
    e6 = _e6_point_reading(R)
    cm = "POINTS_TO_NONLINEARITY" if (cmax_ratio < 0.5 or cmax_ratio > 2.0) else "NO_SIGN"
    # R7 item 3: Cmax/D below 0.5 or above 2.0 with common-window AUC/D within 0.80-1.25 is a registered descriptive screen.
    # It applies only when every dose group has its peak bracketed by samples and the common window holds most of each group's
    # observed exposure; passing it gives indirect support at most, whatever T3/T3p say.
    peak_sampled = all(c.get("tmax") is not None and len(c["_t"]) >= 3 and c["_t"][0] < c["tmax"] < c["_t"][-1] for c in curves)
    shares = [r["share_window"] for r in rows]
    windows_comparable = all(isinstance(x, (int, float)) and x >= CMAX_SCREEN_SHARE_MIN for x in shares)
    applicable = peak_sampled and windows_comparable
    auc_kept = 0.80 <= R <= 1.25
    cmax_screen = {"check": "CMAX_D_SCREEN", "kind": "registered descriptive screen (rule decision R7 item 3)",
                   "cmax_d_ratio": cmax_ratio, "auc_window_d_ratio": R, "cmax_limits": [0.5, 2.0], "auc_band": [0.80, 1.25],
                   "peak_bracketed_by_samples": peak_sampled, "windows_comparable": windows_comparable,
                   "min_window_share": min(shares) if all(isinstance(x, (int, float)) for x in shares) else None,
                   "result": ("NOT_APPLICABLE" if not applicable else
                              "CMAX_D_LOW_AUC_KEPT" if cmax_ratio < 0.5 and auc_kept else
                              "CMAX_D_HIGH_AUC_KEPT" if cmax_ratio > 2.0 and auc_kept else "NOT_MET"),
                   "reason": None if applicable else ("a peak is not bracketed by samples in every dose group" if not peak_sampled
                                                      else "the common window does not hold most of each group's observed exposure"),
                   "max_support": "INDIRECT_SUPPORT"}
    e2 = _half_life_dose_reading(rows)
    # E1 per-time descriptive ratios, highest vs lowest
    per_time = []
    a, b = curves[0], curves[-1]
    for idx in common:
        ta = a["_t"][idx[0]]
        ca, cb = a["_c"][idx[0]] / lo["dose"], b["_c"][idx[-1]] / hi["dose"]
        mt3 = max(cb * (1 - TOL) - ca * (1 + TOL), ca * (1 - TOL) - cb * (1 + TOL))
        per_time.append({"t": ta, "ratio": cb / ca, "m_t3": mt3})
    x = np.log([r["dose"] for r in rows])
    b1 = {"auc_window": float(np.polyfit(x, np.log([r["aucW_d"] * r["dose"] for r in rows]), 1)[0]),
          "auc_last": float(np.polyfit(x, np.log([r["auc_last_d"] * r["dose"] for r in rows]), 1)[0]) if all(r["auc_last_d"] for r in rows) else None,
          "cmax": float(np.polyfit(x, np.log([r["cmax_d"] * r["dose"] for r in rows]), 1)[0])}
    return {"status": "ASSESSED", "window_end_h": T, "doses": [r["dose"] for r in rows], "rows": rows,
            "assumed_zero_doses": [r["dose"] for r, c in zip(rows, curves) if c.get("auc_baseline_basis") == "ASSUMED_ZERO"],
            "R_window": R, "R_own_tlast": hi["auc_last_d"] / lo["auc_last_d"] if hi["auc_last_d"] and lo["auc_last_d"] else None, "e6_label": e6,
            "cmax_d_ratio": cmax_ratio, "cmax_label": cm, "cmax_screen": cmax_screen, "e2_label": e2, "per_time": per_time, "b1": b1,
            "overlay_block": dose_block} | _t3_all(members, rows, common, T)


def _mdose(mem):
    return mem[2]["dose"] if len(mem) > 2 and mem[2].get("dose") else mem[0]["dose_mg_per_kg"]


_p_t = COMMON._p_t


def t3_power(rows, level=0.95):
    """Dose proportionality from the group AUCs of three or more doses, when no SD per time point exists (no Bailer variance).
    Power model ln AUC = a + b·ln dose; b = 1 is proportionality. The scatter of the dose groups about the line gives the SE of b,
    with k − 2 degrees of freedom, so three groups can exclude only a large departure. The residual SD has the reading tolerance
    (TOL) as its floor."""
    x = np.log([r["dose"] for r in rows])
    y = np.log([r["aucW_d"] * r["dose"] for r in rows])
    k = len(rows)
    if k < 3 or len(set(x.tolist())) < k:
        return None
    b, a = np.polyfit(x, y, 1)
    sse = float(np.sum((y - (a + b * x)) ** 2))
    sxx = float(np.sum((x - x.mean()) ** 2))
    df = k - 2
    # the scatter about the line is never taken below the reading tolerance, so groups that happen to line up cannot exclude anything
    sd = max(math.sqrt(sse / df), math.log(1 + TOL))
    se = sd / math.sqrt(sxx)
    tq = t_ppf(1 - (1 - level) / 2, df)
    ci = [float(b - tq * se), float(b + tq * se)]
    p = _p_t((b - 1) / se, df)
    return {"beta": float(b), "se": float(se), "df": df, "ci": ci, "ci_level": level, "p": p, "n_doses": k,
            "residual_sd": float(sd), "sd_floor_applied": bool(math.sqrt(sse / df) < math.log(1 + TOL)),
            "inference_scope": "nominal regression across dose-level mean-curve AUCs; not an animal-level variance estimate",
            "label": "EXCLUDED_UNDER_STATED_ASSUMPTIONS" if (ci[0] > 1 or ci[1] < 1) else "NOT_EXCLUDED",
            "method": "power model on the group AUC over the common window, ln AUC = a + b·ln dose; t interval for b, k − 2 df"}


def _t3_all(members, rows, common, T):
    """T3 (AUC/D ratio CI) and T3p (per-time ln ratios, Holm) for a dose series (A0.10)."""
    out = {"t3_label": "CANNOT_ASSESS", "t3_flags": ["SENSITIVITY_ONLY"], "t3_data_level": "GROUP_MEAN_NO_SD"}
    pts = [{p["t"]: p for p in mem[2]["points"]} if len(mem) > 2 else {} for mem in members]
    lo_i, hi_i = 0, len(members) - 1
    design_reasons = _independence_restrictions(members, across_times=True)
    if any(pts[k] and T not in pts[k] for k in (lo_i, hi_i)):
        design_reasons.append("Bailer variance requires an observed endpoint in both dose groups")
    if any(members[k][1].get("auc_baseline_concentration", 0) != 0 for k in (lo_i, hi_i)):
        design_reasons.append("Bailer design-zero variance does not apply to a nonzero baseline")
    out["sampling_design_restrictions"] = design_reasons
    unresolved = _dependence_unresolved(members, across_times=True)
    out["sampling_design_unresolved"] = unresolved
    point_list = [p for d in pts for p in d.values() if p.get("t", 0) <= T + 1e-9]
    se_count = sum(p.get("se") is not None for p in point_list)
    sd_count = sum(p.get("sd") is not None for p in point_list)
    out["dispersion_coverage"] = {"points": len(point_list), "with_se": se_count, "with_sd": sd_count,
                                  "with_n": sum((p.get("n") or 0) >= 2 for p in point_list)}
    # T3 by Bailer: every sampled time in [0, T] of both pre-specified doses needs SD and n >= 2, no BLQ
    need = []
    for k in (lo_i, hi_i):
        ts = [t for t in sorted(pts[k]) if t <= T + 1e-9]
        miss = [t for t in ts if not (pts[k][t]["status"] == "QUANTIFIED" and pts[k][t].get("sd") is not None and (pts[k][t].get("n") or 0) >= 2)]
        need.append((ts, miss))
    if not design_reasons and pts[lo_i] and all(not miss for _, miss in need):
        lo = {"dose": rows[lo_i]["dose"], **_bailer_input(pts[lo_i], T)}
        hi = {"dose": rows[hi_i]["dose"], **_bailer_input(pts[hi_i], T)}
        r = t3_bailer(lo, hi, T)
        gate = COMMON.formal_premises([members[lo_i][0], members[hi_i][0]])   # round 3 (S12): both dose groups
        out["t3_premises"] = gate
        flags = ["SENSITIVITY_ONLY"] if (any(members[k][0]["digitized"] for k in (lo_i, hi_i)) or not gate["formal"]) else []
        flags += [m for m in gate["missing"]]
        if unresolved:   # R1: independence across times and doses must be stated for the Bailer variance
            flags = ["SENSITIVITY_ONLY", "SAMPLING_DEPENDENCE_UNRESOLVED"] if "SENSITIVITY_ONLY" not in flags else flags + ["SAMPLING_DEPENDENCE_UNRESOLVED"]
        full = r["t3_label"]
        label, rflags, rec = _removal_outcome(full, _t3_bailer_removal(lo, hi, T) if str(full).startswith("EXCLUDED") else [],
                                              "sampled time (both dose groups; window [0, T] kept)")
        out.update({k: v for k, v in r.items() if k != "t3_flags"}); out["t3_flags"] = flags + rflags
        out["t3_removal"] = rec
        if flags:
            out.update(t3_sensitivity_label=full, t3_label="CANNOT_ASSESS")
        elif rflags:   # R2: the full-data reading is kept as a sensitivity reading; the formal exclusion is deferred
            out.update(t3_sensitivity_label=full, t3_label=label)
        else:
            out["t3_label"] = label
        if out["t3_label"] in ("EXCLUDED_UNDER_STATED_ASSUMPTIONS", "NOT_EXCLUDED") and not flags:
            out["t3_family"] = _t3_family(r["dose_pair"], T, "dose-group mean curve with SD and n per time (Bailer)")
        out["t3_reason"] = "Bailer sparse-sampling AUC (SD and n per time point)" + (
            "; sensitivity only: " + "; ".join(unresolved) if unresolved else "") + (
            "; " + rec["reason"] if rec and rec.get("reason") else "")
    else:
        missing = []
        for k, (ts, miss) in zip((lo_i, hi_i), need):
            if miss:
                missing.append(f"{rows[k]['dose']:g} mg/kg lacks SD or n at {', '.join(f'{t:g}' for t in miss)} h")
        no_sd = not any(p.get("sd") is not None for d in pts for p in d.values())
        has_n = bool(pts[lo_i]) and all((p.get("n") or 0) >= 2 for k in (lo_i, hi_i) for p in pts[k].values())
        lack = (f"native SE available at {se_count}/{len(point_list)} points (n is given); SE retained, not treated as SD" if se_count else
                "no SD per time point (n is given)" if has_n else "no SD or n per time point")
        if design_reasons:
            lack += "; " + "; ".join(design_reasons)
        out["t3_reason"] = (f"group means only, {lack}: no CI for R (A0.10 T3)" if no_sd
                            else "Bailer AUC needs SD and n at every time in the window: " + "; ".join(missing))
        out["t3_reason_en"] = (f"group means only: {lack}" if no_sd else
                               "Bailer AUC needs SD and n at every time in the window; missing at "
                               + ", ".join(f"{rows[k]['dose']:g} mg/kg" for k, (ts, miss) in zip((lo_i, hi_i), need) if miss))
        if design_reasons:
            out["t3_reason"] = out["t3_reason_en"] = lack + "; no supported CI for R"
        pm = t3_power(rows)
        if pm:
            # the question T3 asks (is exposure dose-proportional) can still be tested on the dose groups themselves
            said = (f"power model on the group AUCs of {pm['n_doses']} doses: slope {pm['beta']:.2f}, 95 % CI {pm['ci'][0]:.2f}–{pm['ci'][1]:.2f}, "
                    f"p = {pm['p']:.2g} for slope 1, {pm['df']} df")
            flags = ["SENSITIVITY_ONLY", ("PARTIAL_SE" if se_count < len(point_list) else "NATIVE_SE") if se_count else "GROUP_MEANS_NO_SD"]
            if design_reasons:
                flags.append("SAMPLING_DEPENDENCE_UNRESOLVED")
            out.update(t3_power=pm, t3_label="CANNOT_ASSESS", t3_sensitivity_label=pm["label"], t3_data_level="GROUP_MEAN_POWER_MODEL", t3_flags=flags,
                       R=rows[hi_i]["aucW_d"] / rows[lo_i]["aucW_d"], dose_pair=[rows[lo_i]["dose"], rows[hi_i]["dose"]])
            out["t3_reason"] = said + f"; {lack}, so no supported CI for the AUC/D ratio R"
            out["t3_reason_en"] = out["t3_reason"]
        elif no_sd:
            out["t3_reason"] += "; two dose groups leave no degree of freedom for a power-model test"
            out["t3_reason_en"] += "; two dose groups leave no degree of freedom for a power-model test"
    auc_inputs = {json.dumps(m[0]["dose_proportionality_auc"], sort_keys=True): m[0]["dose_proportionality_auc"]
                  for m in members if m[0].get("dose_proportionality_auc")}
    if auc_inputs:
        animal = (_bound_animal_auc(next(iter(auc_inputs.values())), [m[0] for m in members], [r["dose"] for r in rows]) if len(auc_inputs) == 1 else
                  {"status": "CANNOT_ASSESS", "reason": "conflicting animal-level AUC configurations"})
        out["animal_auc"] = animal
        if animal.get("status") == "ASSESSED" and animal["dose_pair"] != [rows[0]["dose"], rows[-1]["dose"]]:
            animal.update(status="CANNOT_ASSESS", population_inference=False, reason="animal AUC dose pair does not match this dose series")
        if animal.get("status") == "ASSESSED":
            out.pop("t3_sensitivity_label", None)
            out.pop("t3_family", None)
            out.update(R=animal["R"], ci=animal["ci"], ci_level=animal["ci_level"], dose_pair=animal["dose_pair"], t3_label=animal["t3_label"],
                       t3_flags=list(animal.get("t3_flags") or []), t3_removal=animal.get("t3_removal"),
                       t3_data_level="VERIFIED_ANIMAL_AUC", t3_reason=animal["method"], t3_reason_en=animal["method"])
            if animal.get("t3_sensitivity_label"):
                out["t3_sensitivity_label"] = animal["t3_sensitivity_label"]
            if animal.get("t3_family"):
                out["t3_family"] = animal["t3_family"]
    out["t3p"] = t3p_series(members, rows, common, pts)
    return out


def t3_animal_auc(config):
    """Explicit metadata.dose_proportionality_auc: verified INDEPENDENT/PAIRED design, source, auc_definition,
    observations [{animal_id, dose, auc}]; optional sourced, predeclared equivalence_margin. Lowest/highest contrast only."""
    bad = lambda reason: {"status": "CANNOT_ASSESS", "reason": reason, "population_inference": False}
    if not isinstance(config, dict) or config.get("design_verified") is not True:
        return bad("animal-level AUC analysis requires explicitly verified dose-group design")
    design = str(config.get("design", "")).upper()
    if design not in ("INDEPENDENT", "PAIRED") or not config.get("source") or not config.get("auc_definition"):
        return bad("verified independent or paired design, AUC definition and source are required")
    groups = {}
    for row in config.get("observations") or []:
        if not isinstance(row, dict):
            return bad("animal AUC observations must be records")
        dose, area = _num(row.get("dose")), _num(row.get("auc"))
        identity = str(row.get("animal_id") or "").strip()
        if not identity or dose is None or dose <= 0 or area is None or area <= 0:
            return bad("each AUC requires an animal identifier, positive dose and positive finite AUC")
        group = groups.setdefault(dose, {})
        if identity in group:
            return bad("duplicate animal identifier within a dose; repeated readings are not independent animals")
        group[identity] = math.log(area / dose)
    if len(groups) < 2:
        return bad("at least two dose groups are required")
    low, high = min(groups), max(groups)
    a, b = groups[low], groups[high]
    if min(len(a), len(b)) < 2:
        return bad("at least two animals per contrasted dose are required")
    if design == "PAIRED":
        if set(a) != set(b):
            return bad("paired analysis requires the same verified animal identifiers at both doses; no unmatched animals are dropped")
    elif set(a) & set(b):
        return bad("independent groups contain repeated animal identifiers; verify pairing")

    def contrast(a, b):
        """(estimate, variance, df, n) of the log dose-normalised AUC contrast, or None below the check's minimum."""
        if min(len(a), len(b)) < 2:
            return None
        if design == "PAIRED":
            values = np.array([b[k] - a[k] for k in sorted(a)])
            est, var, dfx = float(values.mean()), float(np.var(values, ddof=1)) / len(values), len(values) - 1
            n_ = {"pairs": len(values)}
        else:
            av, bv = np.array(list(a.values())), np.array(list(b.values()))
            est = float(bv.mean() - av.mean())
            va, vb = float(np.var(av, ddof=1)) / len(av), float(np.var(bv, ddof=1)) / len(bv)
            var = va + vb
            den = va * va / (len(av) - 1) + vb * vb / (len(bv) - 1)
            dfx = var * var / den if den > 0 else None
            n_ = {"low": len(a), "high": len(b)}
        if var <= 0 or dfx is None or not math.isfinite(var):
            return None
        return est, var, dfx, n_

    def label_of(c):
        q_ = t_ppf(.975, c[2]); se_ = math.sqrt(c[1])
        lo_, hi_ = math.exp(c[0] - q_ * se_), math.exp(c[0] + q_ * se_)
        return "EXCLUDED_UNDER_STATED_ASSUMPTIONS" if lo_ > 1 or hi_ < 1 else "NOT_EXCLUDED"

    full = contrast(a, b)
    if full is None:
        return bad("zero or unavailable animal-level variance cannot calibrate this t interval")
    estimate, variance, df, ns = full
    se = math.sqrt(variance)
    q = t_ppf(.975, df)
    ci = [math.exp(estimate - q * se), math.exp(estimate + q * se)]
    full_label = label_of(full)
    reruns = []
    if full_label.startswith("EXCLUDED"):
        # R2: leave one animal out (both doses for a paired design); a rerun below two animals per dose is not assessable
        for animal_id in sorted(set(a) | set(b)):
            c_ = contrast({k: v for k, v in a.items() if k != animal_id}, {k: v for k, v in b.items() if k != animal_id})
            reruns.append((animal_id, None if c_ is None else label_of(c_)))
    t3_label, rflags, rec = _removal_outcome(full_label, reruns, "animal")
    out = {"status": "ASSESSED", "population_inference": True, "design": design, "dose_pair": [low, high], "n": ns,
           "R": math.exp(estimate), "ci": ci, "ci_level": .95, "df": df, "se_log_ratio": se, "p": _p_t(estimate / se, df),
           "t3_label": t3_label, "t3_removal": rec,
           **({"t3_sensitivity_label": full_label} if rflags else {}),
           **({"t3_family": _t3_family([low, high], None, "animal-level AUC (" + design.lower() + " design)")} if not rflags else {}),
           "t3_data_level": "VERIFIED_ANIMAL_AUC", "t3_flags": rflags,
           "source": config["source"], "auc_definition": config["auc_definition"],
           "method": ("paired t interval for animal log dose-normalized AUC differences" if design == "PAIRED" else
                      "Welch t interval for independent animal log dose-normalized AUCs"),
           "scope": "lowest versus highest dose only; not proof of proportionality at intermediate doses or of an absorption/clearance mechanism",
           "equivalence": {"status": "NOT_ASSESSED", "reason": "no predeclared acceptable ratio range"}}
    margin = config.get("equivalence_margin")
    if margin and not isinstance(margin, dict):
        out["equivalence"] = {"status": "CANNOT_ASSESS", "reason": "equivalence margin must be a sourced predeclared record"}
    elif margin:
        lo, hi = _num(margin.get("lower")), _num(margin.get("upper"))
        if margin.get("predeclared") is not True or not margin.get("source") or lo is None or hi is None or not 0 < lo < 1 < hi:
            out["equivalence"] = {"status": "CANNOT_ASSESS", "reason": "equivalence needs a sourced, predeclared positive ratio range straddling 1"}
        else:
            q90 = t_ppf(.95, df)
            ci90 = [math.exp(estimate - q90 * se), math.exp(estimate + q90 * se)]
            out["equivalence"] = {"status": "WITHIN_PREDECLARED_MARGIN" if lo < ci90[0] and ci90[1] < hi else "NOT_ESTABLISHED",
                                  "margin": [lo, hi], "ci90": ci90, "alpha": .05, "source": margin["source"],
                                  "method": "two one-sided 5% tests via a 90% confidence interval"}
    return out


def _t3_family(dose_pair, T, unit):
    """R4: the record of one formal T3 result (one dose contrast, one interval)."""
    window = f" over [0, {T:g}] h" if T is not None else " (AUC as defined by the source)"
    return {"scope": f"dose-normalised exposure, {dose_pair[0]:g} vs {dose_pair[1]:g} mg/kg{window}",
            "analysis_unit": unit, "members": ["AUC/D ratio, lowest vs highest dose"], "m": 1,
            "method": "single two-sided 95 % interval", "family_alpha": 0.05}


def _bound_animal_auc(config, cards, native_doses):
    """Bind curated individual endpoints to the native scope before performing population inference."""
    bad = lambda reason: {"status": "CANNOT_ASSESS", "reason": reason, "population_inference": False}
    if not isinstance(config, dict):
        return bad("animal AUC configuration must be a record")
    context = config.get("context") or {}
    declared = config.get("native_dataset_ids")
    if not isinstance(context, dict) or not isinstance(declared, list) or set(map(str, declared)) != {str(c["dataset_id"]) for c in cards}:
        return bad("animal AUC native_dataset_ids must bind exactly the native source datasets")
    normalize = lambda value: re.sub(r"\s+", " ", str(value or "").strip()).lower()
    required = ("study", "species", "drug", "route_class", "route_detail", "occasion")
    for key in required + ("experiment_arm", "cohort"):
        for card in cards:
            expected = normalize(card.get(key))
            if key in required and (not expected or expected in ("not_found", "not reported")):
                return bad(f"native {key} is unresolved for the animal AUC comparison")
            if (key in required or expected) and normalize(context.get(key)) != expected:
                return bad(f"animal AUC context does not match native {key}")
    doses = sorted({v for v in (_num(d) for d in native_doses) if v is not None and v > 0})
    if len(doses) < 2:
        return bad("animal AUC comparison requires at least two native AUC dose anchors")
    result = t3_animal_auc(config)
    if result.get("status") == "ASSESSED" and result["dose_pair"] != [doses[0], doses[-1]]:
        return bad("animal AUC dose pair does not match the native AUC dose anchors")
    result["native_dataset_ids"] = sorted(set(declared))
    result["context"] = context
    return result


def _animal_auc_text(result):
    if result.get("status") != "ASSESSED":
        return "Animal-level AUC inference unavailable: " + result.get("reason", "design or data missing") + "."
    eq = result["equivalence"]
    text = f"Animal AUC source: {result['source']}; {result['auc_definition']}; n = {result['n']}. "
    if eq["status"] in ("WITHIN_PREDECLARED_MARGIN", "NOT_ESTABLISHED"):
        text += (f"Predeclared acceptable ratio range {eq['margin'][0]:g}–{eq['margin'][1]:g}: "
                 f"90% CI {eq['ci90'][0]:.2f}–{eq['ci90'][1]:.2f}; "
                 + ("within the range for this dose contrast. " if eq["status"] == "WITHIN_PREDECLARED_MARGIN" else "equivalence not established. "))
    else:
        text += "Equivalence not assessed: " + eq.get("reason", "a predeclared margin is required") + ". "
    return text + result["scope"] + "."


_INDEPENDENT = COMMON._INDEPENDENT


_dependence_unresolved = COMMON._dependence_unresolved


_independence_restrictions = COMMON._independence_restrictions


_removal_outcome = COMMON._removal_outcome


def _bailer_input(pmap, T):
    ts = [t for t in sorted(pmap) if t <= T + 1e-9]
    return {"t": ts, "c": [pmap[t]["c"] for t in ts], "sd": [pmap[t]["sd"] for t in ts], "n": [pmap[t]["n"] for t in ts]}


def _tail_at_endpoint(m, T, c_T, area):
    """Estimated tail fraction at the common endpoint T: C(T)/λz ÷ (observed window area + C(T)/λz). λz comes from the selected
    terminal window and is used only when T lies inside that window (review guide Q6)."""
    sel = m.get("terminal_selected") or {}
    lam = -sel["slope"] if sel.get("slope") is not None and sel["slope"] < 0 else None
    if not lam or sel.get("start") is None or T < sel["start"] - 1e-9 or area is None or c_T is None or c_T < 0:
        return None
    rem = c_T / lam
    return float(rem / (area + rem)) if area + rem > 0 else None


def _f_reason(r):
    """M4 (2026-11-24): every branch writes f_status_reason; output written before the change carries f_reason (alias)."""
    return (r or {}).get("f_status_reason") or (r or {}).get("f_reason") or ""


def hl_grade(ratio):
    """Review guide Q5: below 0.80 steeper, 0.80 to below 1.25 approximately parallel, 1.25 to below 2 moderately shallower, 2 or more
    markedly shallower (EV apparent half-life divided by IV apparent half-life)."""
    return HL_GRADES[sum(ratio >= c for c in HL_CUTS)]


def _dose_given(card):
    """Round 3: the administered dose of a (series) card, the divisor of every dose-normalised area; the dose level otherwise."""
    d = card.get("dose_given_mg_per_kg")
    return d if isinstance(d, (int, float)) and not isinstance(d, bool) and d > 0 else card["dose_mg_per_kg"]


def ev_iv(ev_card, ev, iv_card, iv):
    """T4 and a finite-window dose-normalized exposure ratio, never absolute F."""
    pairs = _common_times([ev, iv], rel=PAIR_TIME_REL, absolute=PAIR_TIME_ABS)
    res = {"ev": ev_card["dataset_id"], "iv": iv_card["dataset_id"],
           "comparison_basis": "IV_SAME_STUDY" if _known(ev_card["study"]) and ev_card["study"] == iv_card["study"] else "IV_OTHER_STUDY",
           "dose_ev": ev_card["dose_mg_per_kg"], "dose_iv": iv_card["dose_mg_per_kg"],
           "dose_given_ev": _dose_given(ev_card), "dose_given_iv": _dose_given(iv_card),
           "source_reported_absolute_f": ev_card.get("source_reported_absolute_f"),
           "absolute_f_status": "NOT_RECOMPUTED_FROM_CURVES"}
    source_f = res["source_reported_absolute_f"]
    if source_f and source_f.get("iv_dataset_id") and source_f["iv_dataset_id"] not in (iv_card["dataset_id"], iv_card.get("source_dataset_id")):
        res["source_reported_absolute_f"] = None
    if source_f and source_f.get("ev_dataset_id") and source_f["ev_dataset_id"] not in (ev_card["dataset_id"], ev_card.get("source_dataset_id")):
        res["source_reported_absolute_f"] = None
    if not _iv_pair_allowed(ev_card, iv_card):
        res.update(t4_label="CANNOT_ASSESS", t4_reason=_UNPAIRED_REASON,
                   f_status="NOT_ESTIMABLE", f_status_reason="unpaired individual IV; labels do not establish pairing")
        return res
    if not all(_num(c.get("dose_mg_per_kg")) and c["dose_mg_per_kg"] > 0 for c in (ev_card, iv_card)):
        why = next((c["dose_from"][len("SUSPENDED: "):] for c in (ev_card, iv_card) if str(c.get("dose_from", "")).startswith("SUSPENDED: ")), None)
        res.update(t4_label="CANNOT_ASSESS", t4_reason=why or "positive dose not reported", f_status="NOT_ESTIMABLE",
                   f_status_reason=why or "dose missing")
        return res
    # G4: concentrations are compared only in the same unit and the same matrix, before any T4 ratio or area
    unit_ok = ev_card.get("unit") == iv_card.get("unit") and ev_card.get("unit") not in (None, "", "NOT_FOUND")
    m_ev, m_iv = (str(c.get("matrix") or "").strip().lower() for c in (ev_card, iv_card))
    matrix_ok = _known(m_ev) and m_ev == m_iv and ev_card.get("matrix_category", "NOT_FOUND") == iv_card.get("matrix_category", "NOT_FOUND")
    if not unit_ok or not matrix_ok:
        why = ("concentration units differ or are not confirmed" if not unit_ok else
               f"matrix differs or is not reported (EV: {ev_card.get('matrix', 'NOT_FOUND')}; IV: {iv_card.get('matrix', 'NOT_FOUND')})")
        res.update(t4_label="CANNOT_ASSESS", t4_reason=why, f_status="NOT_ESTIMABLE", f_status_reason=why)
        return res
    if len(pairs) < 2:
        res.update(t4_label="CANNOT_ASSESS", t4_reason="fewer than 2 common sampling times")
        # Exposure integration uses overlapping observed support, not nearest-time T4 pairs.
    q = []
    for i, j in pairs:
        ce, ci = ev["_c"][i], iv["_c"][j]
        q.append({"t": ev["_t"][i], "q": ce / ci, "lo": ce * (1 - TOL) / (ci * (1 + TOL)), "hi": ce * (1 + TOL) / (ci * (1 - TOL))})
    group = "GROUP_MEAN" in ev["caveats"] or iv_card["record_level"] == "GROUP_MEAN"
    if len(q) >= 2:
        best = max(((q[a]["lo"] - q[b]["hi"], a, b) for a in range(len(q)) for b in range(a + 1, len(q))), key=lambda z: z[0])
        mt4 = best[0]
        rflags, removal = [], None
        if mt4 > 0:
            # R2: T4 needs 2 matched times, so with exactly two a rerun cannot be tested (LOO_NOT_ASSESSABLE)
            reruns = []
            for k in range(len(q)):
                rest = [x for x in range(len(q)) if x != k]
                reruns.append((f"{q[k]['t']:g} h", None if len(rest) < 2 else
                               "EXCLUDED" if any(q[a]["lo"] - q[b]["hi"] > 0 for a in rest for b in rest if a < b) else "NOT_EXCLUDED"))
            _, rflags, removal = _removal_outcome("EXCLUDED", reruns, "matched time")
        flags = ["SENSITIVITY_ONLY"] + rflags + (["CONDITIONAL_ON_COMMON_K"] if group else [])
        res.update(q=q, mt4=mt4, mt4_pair=[q[best[1]]["t"], q[best[2]]["t"]], t4_label="CANNOT_ASSESS", t4_flags=flags, t4_removal=removal,
                   time_match="TIMES_MATCHED_WITHIN_TOLERANCE")
    # item 22
    caveats = []
    if ev_card["dose_basis"] != iv_card["dose_basis"] or "NOT_FOUND" in (ev_card["dose_basis"], iv_card["dose_basis"]):
        res.update(f_status="NOT_ESTIMABLE", f_status_reason=f"dose basis differs or not reported (EV: {ev_card['dose_basis']}; IV: {iv_card['dose_basis']})")
        return res
    start, T = max(ev["_t"][0], iv["_t"][0]), min(ev["_t"][-1], iv["_t"][-1])
    if T <= start:
        res.update(f_status="NOT_ESTIMABLE", f_status_reason="no overlapping observed time interval")
        return res
    if any(_censored_interval(m, start, T) for m in (ev, iv)):
        res.update(f_status="NOT_ESTIMABLE", f_status_reason="censored observation in the common AUC interval")
        return res
    et, ec = _interval_profile(ev, start, T)
    it, ic = _interval_profile(iv, start, T)
    aev = auc(et, ec) / _dose_given(ev_card)
    aiv = auc(it, ic) / _dose_given(iv_card)
    if aiv <= 0:
        res.update(f_status="NOT_ESTIMABLE", f_status_reason="nonpositive IV area in the common interval")
        return res
    fw = aev / aiv
    caveats.extend(["FINITE_OBSERVED_WINDOW", "NOT_ABSOLUTE_BIOAVAILABILITY", "NO_ABSOLUTE_F_BOUND"])
    if start > 0:
        caveats.append("EARLY_EXPOSURE_OUTSIDE_WINDOW")
    if any(not any(abs(t - x) < 1e-9 for x in m["_t"]) for t in (start, T) for m in (ev, iv)):
        caveats.append("ENDPOINT_INTERPOLATION")
    if ev_card["dose_mg_per_kg"] != iv_card["dose_mg_per_kg"]:
        caveats.append("DOSE_MISMATCH_LINEARITY_NOT_ESTABLISHED")
    if ev_card.get("digitized") or iv_card.get("digitized"):
        caveats.append("DIGITIZED_SOURCE")
    if iv_card["route_detail"] in ("NOT_FOUND", "", None):
        caveats.append("IV_MODE_UNKNOWN")
    ev_own, iv_own = ev.get("tail_share"), iv.get("tail_share")
    ev_tail = _tail_at_endpoint(ev, T, float(ec[-1]), float(auc(et, ec)))
    iv_tail = _tail_at_endpoint(iv, T, float(ic[-1]), float(auc(it, ic)))
    if ev_tail is None or iv_tail is None:
        caveats.append("TAIL_NOT_ASSESSABLE")
    else:
        if ev_tail > TAIL_FLAG: caveats.append("EV_TRUNCATED")
        if iv_tail > TAIL_FLAG: caveats.append("IV_TRUNCATED")
    if group:
        caveats.append("GROUP_MEAN")
    if "PULMONARY" not in " ".join(caveats) and ev_card["route_detail"] in ("OTHER_EV", "INTRATRACHEAL", "INHALED_NOSE_ONLY", "INHALED_WHOLE_BODY"):
        caveats.append("PULMONARY_AND_GI_UNRESOLVED")
    same_study = res["comparison_basis"] == "IV_SAME_STUDY"
    # G5: the window starts at the later first sample, so exposure before it is missing on both routes; each card
    # must carry its own justification (review guide Q6, rules A0.12 "justified IV early coverage")
    early_missing = [] if start <= 0 else [r for r, c in (("EV", ev_card), ("IV", iv_card)) if c.get("early_exposure_justified") is not True]
    early_ok = not early_missing
    tails_ok = ev_tail is not None and iv_tail is not None and max(ev_tail, iv_tail) <= TAIL_FLAG
    ratio_kind = "FINITE_WINDOW_EXPOSURE_RATIO" if same_study else "INDIRECT_FINITE_WINDOW_EXPOSURE_RATIO"
    # review guide Q6: a window-based estimate needs a same-study comparison, justified early coverage and an estimated tail
    # fraction of 5 % or less for each route; otherwise the observed window ratio is reported. No directional bound is assigned here.
    status = "WINDOW_BASED_ESTIMATE" if same_study and early_ok and tails_ok else "OBSERVED_WINDOW_RATIO"
    why = ([] if same_study else ["the IV reference is from another study"]) + ([] if early_ok else [
        f"exposure before {start:g} h lies outside the common window and its share is not bounded ({', '.join(early_missing)} early coverage not justified)"]) + ([] if tails_ok else [
        "the tail fraction at the common endpoint cannot be estimated for both routes" if ev_tail is None or iv_tail is None
        else f"the estimated tail fraction exceeds {TAIL_FLAG:.0%} (EV {ev_tail:.1%}, IV {iv_tail:.1%})"])
    if status == "WINDOW_BASED_ESTIMATE":
        caveats[:] = [x for x in caveats if x != "NOT_ABSOLUTE_BIOAVAILABILITY"] + ["TAIL_ESTIMATE_DEPENDS_ON_FITTED_SLOPE"]
    if fw > 1:
        caveats.append("ABOVE_100_PERCENT_REVIEW_DOSE_BASIS_AND_IV_EXPOSURE")
    res.update(f_status=status, f_status_reason="; ".join(why) or "same study, early coverage justified, tail fraction ≤ 5 % for both routes",
               window_ratio_status=ratio_kind, window_auc_ratio=fw, f_above_100pct=bool(fw > 1), early_coverage_justified=bool(early_ok),
               window_start_h=start, window_end_h=T, window_h=T,
               auc_ev_window_per_dose=aev, auc_iv_window_per_dose=aiv,
               integration_method="linear-up/log-down; interpolated endpoints on identical observed time support; no extrapolation",
               ev_tail_share=ev_tail, iv_tail_share=iv_tail, ev_tail_share_own_last=ev_own, iv_tail_share_own_last=iv_own,
               tail_share_basis="at the common endpoint T: C(T)/λz ÷ (area over the common window + C(T)/λz); λz from the route's selected "
                                "terminal window, used only when T lies inside it",
               ev_tail_reference_h=ev["_t"][-1], iv_tail_reference_h=iv["_t"][-1], f_caveats=caveats)
    # Reproduce the historic display without promoting its unequal supports or IV rectangle to an F bound.
    if pairs and ev_card.get("single_dose") and ev["_t"][0] > 0 and not str(ev_card.get("baseline_status", "")).startswith("PREDOSE_OBSERVED"):
        old_T = ev["_t"][pairs[-1][0]]
        old_it = [x for x in iv["_t"] if x <= old_T * (1 + PAIR_TIME_REL)]
        if len(old_it) >= 2 and not (_censored_interval(ev, 0, old_T) or _censored_interval(iv, old_it[0], old_it[-1])):
            old_ev = _window_auc(ev, old_T) / _dose_given(ev_card)
            old_iv = auc(old_it, iv["_c"][:len(old_it)]) / _dose_given(iv_card)
            rectangle = iv["_t"][0] * iv["_c"][0] / _dose_given(iv_card)
            if old_iv > 0:
                res["legacy_different_support_sensitivity"] = {
                    "ratio": old_ev / old_iv, "ratio_with_assumed_iv_rectangle": old_ev / (old_iv + rectangle),
                    "ev_interval_h": [0.0, old_T], "iv_interval_h": [iv["_t"][0], old_it[-1]],
                    "method": "linear-up/log-down; historic nearest-time end inclusion; unequal intervals",
                    "assumptions": ["designed EV zero at dosing", "IV C(t)=C(first) on [0, first] for rectangle sensitivity only"],
                    "interpretation": "legacy sensitivity only; neither value is absolute F or an upper/lower bound",
                    "iv_rectangle_per_dose": rectangle}
    return res


def condition_pair(a_card, a, b_card, b):
    """Item 23 T5 (amplitude family) on matched times; b is the reference."""
    diff = [k for k in ("route_detail", "dose_mg_per_kg", "matrix", "species", "study", "record_level", "dose_basis")
            if a_card[k] != b_card[k]]
    pairs = _common_times([a, b], rel=PAIR_TIME_REL, absolute=PAIR_TIME_ABS)
    res = {"a": a_card["dataset_id"], "b": b_card["dataset_id"], "differing_attributes": diff,
           "confounded": len(diff) > 1}
    if len(pairs) < 3:
        res.update(t5_label="NOT_ASSESSABLE", t5_reason="fewer than 3 matched time points")
        return res
    iv = []
    for i, j in pairs:
        ca, cb = a["_c"][i], b["_c"][j]
        iv.append({"t": a["_t"][i], "c": ca / cb, "lo": ca * (1 - TOL) / (cb * (1 + TOL)), "hi": ca * (1 + TOL) / (cb * (1 - TOL))})
    lo, hi = max(x["lo"] for x in iv), min(x["hi"] for x in iv)
    flags = ["SENSITIVITY_ONLY", "TIMES_MATCHED_WITHIN_TOLERANCE"]
    if "GROUP_MEAN" in a["caveats"]:
        flags.append("GROUP_MEAN")
    removal = None
    if lo > hi:
        # R2: T5 needs 3 matched times, so a rerun on fewer cannot be tested (LOO_NOT_ASSESSABLE)
        reruns = []
        for k in range(len(iv)):
            rest = [x for n, x in enumerate(iv) if n != k]
            reruns.append((f"{iv[k]['t']:g} h", None if len(rest) < 3 else
                           "EXCLUDED" if max(x["lo"] for x in rest) > min(x["hi"] for x in rest) else "NOT_EXCLUDED"))
        _, rflags, removal = _removal_outcome("EXCLUDED", reruns, "matched time")
        flags += rflags
    res.update(intervals=iv, c_lower=lo, c_upper=hi, t5_label="CANNOT_ASSESS", t5_flags=flags, t5_removal=removal,
               rate_only_label="CANNOT_ASSESS",
               rate_only_reason="no two-sided tail bounds on the full exposure (item 23, test 2)")
    return res


# ---------------------------------------------------------------- figures
#
# Python computes every plotted value and writes one plot spec per figure; the R renderer
# (pkpd_r/eda/absorption_figures.R, ggplot2) draws them, the same route as the EDA source
# display. If R or ggplot2 is not available, the same specs are drawn with matplotlib and the
# page says so. Figures never compute anything themselves.

# colours and sizes follow pkpd_r/eda/plot_style.R (pkpd_theme, pkpd_colours) so absorption figures
# look like the other EDA displays
INK, INK2, MUTED, GRID, SURF = "#17364b", "#4b6273", "#8a9aa6", "#e4eaf0", "#ffffff"
BLUE, ORANGE, GREEN, PURPLE = "#0072B2", "#D55E00", "#009E73", "#CC79A7"
RAMP = ["#9cc3f0", "#6aa5e8", "#2a78d6", "#1c5cab", "#104281", "#0a2d5c"]
RENDER_DPI = 150
_SPECS = []          # figure specs collected during build(); rendered in one batch
_RENDER = {"engine": None, "note": ""}
_SPECS_DONE = []


_l = COMMON._l


class Panel:
    """One plot panel in a renderer-neutral form (layers in data coordinates unless npc=True)."""

    def __init__(self, title="", x="", y="", ylog=False, xlog2=False):
        self.d = {"title": title, "xlab": x, "ylab": y, "ylog": ylog, "xlog2": xlog2, "xbreaks": None, "xlabels": None,
                  "xlim": None, "ylim": None, "legend": "none", "blank": False, "yticks": True, "xlog": False, "layers": []}

    def add(self, kind, **kw):
        self.d["layers"].append({"kind": kind, **kw}); return self

    def points(self, x, y, color=BLUE, shape="circle", size=2.6, label=None, stroke=1.0):
        return self.add("points", x=_l(x), y=_l(y), color=color, shape=shape, size=size, label=label, stroke=stroke)

    def line(self, x, y, color=BLUE, lty="solid", lw=0.8, label=None, alpha=1.0):
        return self.add("line", x=_l(x), y=_l(y), color=color, lty=lty, lw=lw, label=label, alpha=alpha)

    def segments(self, x, y, xend, yend, color=BLUE, lw=1.6, label=None, lty="solid"):
        return self.add("segment", x=_l(x), y=_l(y), xend=_l(xend), yend=_l(yend), color=color, lw=lw, label=label, lty=lty)

    def band(self, xmin, xmax, color=ORANGE, alpha=0.12, label=None):
        return self.add("band", xmin=float(xmin), xmax=float(xmax), color=color, alpha=alpha, label=label)

    def area(self, x, y, color=BLUE, alpha=0.10):
        return self.add("area", x=_l(x), y=_l(y), color=color, alpha=alpha)

    def hline(self, y, color=MUTED, lty="solid", lw=0.5, label=None):
        return self.add("hline", y=float(y), color=color, lty=lty, lw=lw, label=label)

    def vline(self, x, color=MUTED, lty="solid", lw=0.5, label=None):
        return self.add("vline", x=float(x), color=color, lty=lty, lw=lw, label=label)

    def bars(self, x, y, color=BLUE):
        return self.add("bars", x=_l(x), y=_l(y), color=color)

    def text(self, x, y, label, hjust=0.0, vjust=1.0, size=3.0, color=INK2, npc=False, repel=False):
        """repel=True (S13 point notes): the R renderer places the label with ggrepel next to (x, y), clear of the data, with a
        leader line; without ggrepel, and in the matplotlib fallback, it is placed as given."""
        d = dict(x=float(x), y=float(y), label=str(label), hjust=hjust, vjust=vjust, size=size, color=color, npc=npc)
        if repel:
            d["repel"] = True
        return self.add("text", **d)

    def set(self, **kw):
        self.d.update(kw); return self


# Plot rules P1-P7 (2026-11-25, George): one clock for every time-course figure, the time after the START of dosing; an IV
# input of known length is drawn as a shaded band from 0 to its end, so its length is visible; every observation is drawn.
TIME_AXIS = "Time after start of dosing (h)"
INPUT_FILL = "#8a9aa6"
INPUT_ALPHA = 0.22


def _hours(x):
    return f"{x:.3g}"


def input_band(panel, hours, mode="INFUSION"):
    """Shade the IV input from the start of dosing to its end (P1). hours: the input durations of the profiles drawn in the
    panel (one per profile). Profiles with different durations give one band to the longest, labelled with the range.
    Nothing is drawn for a bolus or an input of unknown length; returns the label or None."""
    hs = sorted({round(float(h), 6) for h in hours if isinstance(h, (int, float)) and h > 0})
    if mode != "INFUSION" or not hs:
        return None
    label = (f"IV infusion 0–{_hours(hs[0])} h" if len(hs) == 1 else
             f"IV infusion, 0–{_hours(hs[0])} to 0–{_hours(hs[-1])} h by animal")
    panel.band(0.0, hs[-1], color=INPUT_FILL, alpha=INPUT_ALPHA, label=label)
    panel.d["layers"].insert(0, panel.d["layers"].pop())   # drawn underneath the data
    if panel.d.get("legend", "none") == "none":
        panel.set(legend="bottom_left")                    # the band always has its legend entry
    return label


CLOSE_TIME_FRACTION = 0.02   # S13: samples closer than 2 % of the plotted time span are labelled with their times


def label_close_times(panel, ts, cs, span=None, ylog=False):
    """S13 (George 2026-11-25): where adjacent samples sit so close in time that the axis cannot separate them, each sample of
    the cluster is labelled with its own time, next to the point. Returns the labelled times."""
    pts = sorted((float(t), float(c)) for t, c in zip(ts, cs) if t is not None and c is not None and (c > 0 or not ylog))
    if len(pts) < 2:
        return []
    span = span or (pts[-1][0] - min(0.0, pts[0][0])) or 1.0
    close = set()
    for (t0, _), (t1, _) in zip(pts, pts[1:]):
        if t1 - t0 < CLOSE_TIME_FRACTION * span:
            close.update((t0, t1))
    done = []
    for i, (t, c) in enumerate(p for p in pts if p[0] in close):
        up = i % 2 == 0                      # alternate above/below so neighbours do not overlap
        panel.text(t, c, f"{_hours(t)} h", hjust=-0.15, vjust=0 if up else 1, size=2.4, repel=True)
        done.append(t)
    return done


def card_input_h(card):
    """Input duration of an IV card when the input states one (iv_mode INFUSION), else None."""
    iv = (card or {}).get("iv_input") or {}
    return iv.get("infusion_h") if iv.get("mode") == "INFUSION" else None


def _figure(out, name, title, panels, width, height, widths=None, ncol=None):
    ncol = min(ncol or len(panels), len(panels))
    _SPECS.append({"file": name, "title": title, "width": width, "height": height, "dpi": RENDER_DPI, "ncol": ncol,
                   "widths": widths or [1] * ncol, "panels": [p.d for p in panels]})
    return name


def render_all(out):
    """Draw every collected spec: R/ggplot2 first, matplotlib if R is unavailable or fails."""
    specs = list(_SPECS)
    _SPECS.clear()
    _SPECS_DONE[:] = specs
    path = out / "plot_specs.json"
    path.write_text(json.dumps({"version": VERSION, "rules": RULES, "figures": specs}, ensure_ascii=False, default=float), encoding="utf-8")
    if not specs:
        _RENDER.update(engine="none", note=""); return
    script = _r_script()
    rs = _rscript()
    if rs and script.is_file():
        import subprocess
        try:
            done = subprocess.run([rs, "--vanilla", str(script), str(path), str(out)], capture_output=True, text=True,
                                  encoding="utf-8", timeout=600)
            (out / "r_stderr.txt").write_text(done.stderr or "", encoding="utf-8")
            if done.returncode == 0 and all((out / s["file"]).is_file() for s in specs):
                _RENDER.update(engine="R_GGPLOT2", note=done.stdout.strip()); return
            reason = f"R renderer failed (exit {done.returncode}); see absorption/r_stderr.txt"
        except Exception as exc:  # noqa: BLE001 - reported on the page
            reason = f"R renderer could not run: {exc!r}"
    else:
        reason = "Rscript not found (set PKPD_RSCRIPT)" if not rs else f"R script missing: {script}"
    for s in specs:
        _render_mpl(s, out)
    _RENDER.update(engine="MATPLOTLIB_FALLBACK", note=reason)


def _rscript():
    import os
    import shutil
    try:
        from .engine import rscript_path  # the pipeline's own R location
        p = rscript_path()
        if p:
            return str(p)
    except Exception:  # noqa: BLE001 - outside the pipeline, or PKPD_RSCRIPT unset
        pass
    return os.environ.get("PKPD_RSCRIPT") or shutil.which("Rscript")


def _r_script():
    import os
    if os.environ.get("ABSORPTION_R_SCRIPT"):
        return Path(os.environ["ABSORPTION_R_SCRIPT"])
    here = Path(__file__).resolve()
    for base in here.parents:
        cand = base / "pkpd_r" / "eda" / "absorption_figures.R"
        if cand.is_file():
            return cand
    return here.parent / "absorption_figures.R"


# ---- matplotlib fallback (draws the same spec)

_MPL_SHAPE = {"circle": dict(marker="o"), "open": dict(marker="o", mfc="none"), "ring": dict(marker="o", mfc="none"),
              "diamond_open": dict(marker="D", mfc=SURF), "cross": dict(marker="x"), "dash": dict(marker="_"),
              "square": dict(marker="s")}


def _render_mpl(spec, out):
    plt.rcParams.update({"font.size": 9.5, "axes.edgecolor": MUTED, "axes.labelcolor": INK2, "xtick.color": INK2,
                         "ytick.color": INK2, "axes.facecolor": SURF, "figure.facecolor": SURF, "axes.grid": True,
                         "grid.color": GRID, "grid.linewidth": 0.6, "axes.spines.top": False, "axes.spines.right": False,
                         "legend.frameon": False})
    n = len(spec["panels"])
    ncol = spec.get("ncol") or n
    nrow = -(-n // ncol)
    fig, axs = plt.subplots(nrow, ncol, figsize=(spec["width"], spec["height"]), squeeze=False,
                            gridspec_kw={"width_ratios": spec["widths"][:ncol]})
    for ax in axs.flat[n:]:
        ax.axis("off")
    for ax, p in zip(axs.flat, spec["panels"]):
        if p["blank"]:
            ax.axis("off")
        for L in p["layers"]:
            k, c = L["kind"], L.get("color", INK)
            if k == "points":
                st = dict(_MPL_SHAPE.get(L["shape"], {"marker": "o"}))
                st.setdefault("mfc", c)
                ax.plot(L["x"], L["y"], ls="none", color=c, mec=c, ms=L["size"] * 2.2, mew=L.get("stroke", 1) * 1.2, label=L.get("label"), **st)
            elif k == "line":
                ax.plot(L["x"], L["y"], color=c, ls="--" if L["lty"] == "dashed" else ":" if L["lty"] == "dotted" else "-",
                        lw=L["lw"] * 2.2, alpha=L.get("alpha", 1), label=L.get("label"))
            elif k == "segment":
                for x0, y0, x1, y1 in zip(L["x"], L["y"], L["xend"], L["yend"]):
                    ax.plot([x0, x1], [y0, y1], color=c, lw=L["lw"] * 2.2, solid_capstyle="butt", ls="--" if L.get("lty") == "dashed" else "-")
                if L.get("label"):
                    ax.plot([], [], color=c, lw=L["lw"] * 2.2, label=L["label"])
            elif k == "band":
                ax.axvspan(L["xmin"], L["xmax"], color=c, alpha=L["alpha"], lw=0, label=L.get("label"))
            elif k == "area":
                ax.fill_between(L["x"], 0, L["y"], color=c, alpha=L["alpha"], lw=0)
            elif k == "hline":
                ax.axhline(L["y"], color=c, lw=L["lw"] * 2.2, ls="--" if L["lty"] == "dashed" else "-", label=L.get("label"))
            elif k == "vline":
                ax.axvline(L["x"], color=c, lw=L["lw"] * 2.2, ls="--" if L["lty"] == "dashed" else ":" if L["lty"] == "dotted" else "-",
                           label=L.get("label"))
            elif k == "bars":
                ax.bar(L["x"], L["y"], color=c, width=0.7)
            elif k == "text":
                kw = {"transform": ax.transAxes} if L["npc"] else {}
                ax.text(L["x"], L["y"], L["label"], ha={0: "left", 0.5: "center", 1: "right"}.get(L["hjust"], "left"),
                        va={0: "bottom", 0.5: "center", 1: "top"}.get(L["vjust"], "top"), fontsize=L["size"] * 2.6, color=L["color"], **kw)
        if p["ylog"]:
            ax.set_yscale("log"); ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:g}"))
        if p["xlog"]:
            ax.set_xscale("log"); ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:g}"))
        if p["xlog2"]:
            ax.set_xscale("log", base=2)
        if p["xbreaks"] is not None:
            ax.set_xticks(p["xbreaks"]); ax.set_xticklabels(p["xlabels"] or [f"{x:g}" for x in p["xbreaks"]])
        if p["xlim"]:
            ax.set_xlim(*p["xlim"])
        if p["ylim"]:
            ax.set_ylim(*p["ylim"])
        if not p["yticks"]:
            ax.set_yticks([])
        ax.set_title(p["title"], loc="left", fontsize=10, color=INK)
        ax.set_xlabel(p["xlab"]); ax.set_ylabel(p["ylab"])
        if p.get("caption"):
            import textwrap
            ax.text(0, -0.23, textwrap.fill(p["caption"], 110), transform=ax.transAxes, ha="left", va="top", fontsize=6.5, color=INK2)
        if p["legend"] != "none" and ax.get_legend_handles_labels()[0]:
            ax.legend(fontsize=7.5, loc={"top_right": "upper right", "top_left": "upper left", "bottom_left": "lower left",
                                         "bottom_right": "lower right", "top": "upper center"}.get(p["legend"], "best"))
    if spec["title"]:
        fig.suptitle(spec["title"], x=0.01, ha="left", fontsize=10.5, color=INK)
    fig.tight_layout()
    fig.savefig(out / spec["file"], dpi=spec["dpi"])
    plt.close(fig)


# ---- panels of figures A–F (A0.11, question-first draft 2026-11-05)
# Every figure is a set of panels; each panel is saved as its own PNG so that the question rows can open exactly the
# panel they need. A panel carries only its own annotations. The question views (Q1–Q9 primary evidence) are drawn
# from the same builders with the subset of marks that question needs.

IND_SMALL_MULTIPLES = 8   # project setting: more animals than this → one panel per animal


def _tag(card, series):
    return f"{card['dataset_id']}{' · ' + series['label'] if series.get('label') else ''}"


def _route_word(card):
    if card.get("route_class") == "IV":
        return "IV"
    rd = str(card.get("route_detail") or "").strip()
    return rd if rd and rd.upper() != "NOT_FOUND" else str(card.get("route_class") or "")


def _dose_span(series_list, card):
    ds = sorted({round(g, 6) for g in (_given(s, card) for s in series_list) if g})
    if not ds:
        return None
    return ds[0] if len(ds) == 1 else f"{ds[0]:.4g}–{ds[-1]:.4g} mg/kg"


def _input_word(card, series=None):
    if card.get("route_class") != "IV":
        return ""
    iv = (series or {}).get("iv_input") or card.get("iv_input") or {}
    return COMMON.input_text(iv.get("mode"), iv.get("infusion_h"))


def _std(card, series=None, scale=None, what="concentration", who=None, dose="auto", part=None, vs="time", group=None, all_doses=False):
    """S13 rule 9: the standard title of an Absorption figure (which data, what is plotted)."""
    s = series or {}
    if group is not None:
        who = who or f"{len(group)} animal{'s' if len(group) != 1 else ''}"
        dose = _dose_span(group, card) if dose == "auto" else dose
    else:
        who = who if who is not None else (s.get("label") or ("mean" if card.get("record_level") == "GROUP_MEAN" else ""))
        dose = _given(s, card) if dose == "auto" else dose
    ev = s.get("dose_events") or next((g.get("dose_events") for g in (group or []) if g.get("dose_events")), None) or []
    inp = ", ".join(x for x in (_input_word(card, s), (("" if all_doses else "first of ") + f"{len(ev)} doses at " + ", ".join(_hours(e["time_h"]) for e in ev) + " h")
                                if len(ev) > 1 else "") if x)
    return COMMON.std_title(card.get("species"), _route_word(card), who, dose, inp, what, scale, card.get("matrix"), vs, part)


def _rstd(r, what, scale=None, vs="time", part=None):
    """Standard title for a dose-series figure (r: the dose-series result)."""
    card = r.get("_card0") or {}
    ds = sorted({x.get("dose") for x in r.get("rows", []) if x.get("dose")} | set(r.get("doses") or []) | set(r.get("dose_pair") or []))
    dose = f"{ds[0]:g}–{ds[-1]:g} mg/kg" if len(ds) > 1 else (ds[0] if ds else None)
    return COMMON.std_title(card.get("species"), _route_word(card) if card else None, f"{len(ds)} doses" if ds else None, dose, "",
                            what, scale, card.get("matrix"), vs, part)


Q_SUB = {   # S13 rule 9: the subtitle is the question the figure answers
    "A1": "When does drug first appear, and is there a delay?",
    "A1w": "How does concentration change over the sampling period?",
    "A3": "How fast does concentration rise before the peak?",
    "A4": "How do Tmax and Cmax/dose vary between animals?",
    "B1": "How does concentration decline after the peak?",
    "T2": "Is there a dip followed by a second rise?",
    "B2": "Does the half-life depend on where the terminal fit starts?",
    "IND": "How do the individual animals compare?",
    "FIRST": "When is drug first quantified in each animal?",
    "TMAX": "When is the peak reached in each animal?",
    "DOSE": "Does exposure rise in proportion to dose?",
    "DOSE_T": "At which times does concentration divided by dose differ between doses?",
    "EVIV": "How does the EV profile compare with IV once divided by dose?",
    "COND": "Do the two conditions give the same profile?",
    "SHAPE": "Do the two profiles have the same shape?",
    "PARAM": "How do the reported parameters change with dose?",
}


def _sid(series):
    return re.sub(r"[^A-Za-z0-9]+", "_", str(series.get("series_id") or "mean"))


def _free_corner(x, y, order=("top_right", "bottom_right", "top_left", "bottom_left")):
    """The legend corner of a linear panel that covers the fewest points (box: 45 % wide, 35 % high)."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    if not len(x):
        return order[0]
    xs = (x - min(0.0, x.min())) / ((x.max() - min(0.0, x.min())) or 1.0)
    ys = (y - min(0.0, y.min())) / ((y.max() - min(0.0, y.min())) or 1.0)
    box = {"top_right": (xs > 0.55) & (ys > 0.65), "bottom_right": (xs > 0.55) & (ys < 0.35),
           "top_left": (xs < 0.45) & (ys > 0.65), "bottom_left": (xs < 0.45) & (ys < 0.35)}
    return min(order, key=lambda k: (int(box[k].sum()), order.index(k)))


def _lloq_value(card):
    v = _num(card.get("lloq"))
    return v if v and v > 0 else None


def _blq_marks(p, card, series, m, tmax_x=None):
    """Unknown concentrations appear as sampling times. Only a documented limit has a y coordinate."""
    ll = _lloq_value(card)
    notes = []
    for status, label in COMMON.ASSAY_LABELS.items():
        times = [b["t"] for b in series["points"] if b["status"] == status and (tmax_x is None or b["t"] <= tmax_x)]
        if not times:
            continue
        if status == "BLQ" and ll:
            p.points(times, [ll] * len(times), color=INK2, shape="open", label="BLQ at LLOQ")
        else:
            notes.append(label.capitalize() + " at " + ", ".join(f"{t:g}" for t in times) + " h")
    if notes:
        p.d["xlab"] += "\n" + "\n".join(notes)


def _predose(series):
    return [x for x in series["points"] if x["status"] in ("QUANTIFIED", "REPORTED_ZERO_PREDOSE", "BLQ") and x.get("c") is not None and x["t"] <= 0]


def _baseline_reading(series):
    points = [p for p in series["points"] if p["t"] <= 0]
    if not points:
        return "no predose sample reported"
    return ", ".join(f"{p['t']:g} h: " + ("source-reported zero" if p["status"] == "REPORTED_ZERO_PREDOSE"
                     else f"{p['c']:g}" if p.get("c") is not None else COMMON.ASSAY_LABELS.get(p["status"], p["status"]))
                     for p in points)


def _early_end(m):
    t, c = m["_t"], m["_c"]
    imax = int(np.argmax(c))
    return t[imax + 1] if imax + 1 < len(t) else t[imax]


def pA1(card, m, series, marks=("tmax", "delay", "zero", "blq", "predose"), whole=False, first=False, frac=False, title=None):
    """A1 linear concentration–time; default view the early window (0 to the first sample after Tmax)."""
    t, c = np.array(m["_t"]), np.array(m["_c"])
    tend = max(t[-1], m.get("last_sample_h") or t[-1]) if whole else _early_end(m)
    k = t <= tend + 1e-9
    # S13 rule 9: standard title; only standard PK markers (no delay band, no design-zero point, no time labels)
    p = Panel(_std(card, series, "linear", part=None if whole else f"0–{tend:.3g} h"), TIME_AXIS, f"Concentration ({card['unit']})")
    p.set(subtitle=Q_SUB["A1w" if whole else "A1"])
    input_band(p, [card_input_h(card)])
    reading = []
    if "delay" in marks and m["onset_status"] != "NOT_ASSESSABLE":
        reading.append(f"The first sample ({m['first_t']:.3g} h) is already quantified, so any delay before absorption is shorter than that.")
    if "delay" in marks and (m.get("mt1") or 0) > 0 and m.get("mt1_witness"):
        a_, b_ = m["mt1_witness"]
        reading.append(f"Concentration divided by time rises from {a_:.3g} to {b_:.3g} h, which points to a delayed start of absorption.")
    pre = _predose(series)
    if "predose" in marks and pre:
        p.points([x["t"] for x in pre], [x["c"] for x in pre], color=PURPLE, shape="square", size=2.6,
                 label="predose " + ", ".join(f"{x['c']:.3g} ({100 * x['c'] / m['cmax']:.0f} % of Cmax)" for x in pre))
    p.points(t[k], c[k], color=BLUE, size=3 if not whole else 2.6, label="quantified")
    if "blq" in marks:
        _blq_marks(p, card, series, m, None if whole else tend)
    if first:
        p.points([t[0]], [c[0]], color=ORANGE, shape="ring", size=5.2, stroke=1.5, label=f"first quantified sample, {t[0]:.3g} h")
    if "tmax" in marks:
        p.points([m["tmax"]], [m["cmax"]], color=ORANGE, shape="ring", size=5, stroke=1.4, label=f"Tmax {m['tmax']:.3g} h")
    if frac:
        reading.append(f"At the first sample ({t[0]:.3g} h) the concentration is already {100 * m['first_frac_cmax']:.0f} % of Cmax.")
    lo = min(-0.05 * tend, min((p["t"] for p in pre), default=0) - 0.02 * tend)
    ymax = max([m["cmax"]] + [p["c"] for p in pre])
    p.set(xlim=[lo, tend * 1.08], ylim=[-0.04 * ymax, ymax * 1.18],
          legend="bottom_right" if not whole else _free_corner(list(t) + [0], list(c) + [0]))
    if reading:
        p.set(caption=" ".join(reading[:2]))
    first_interval_note(p, series)
    return p


def pA3(card, m, series):
    """A3 rising-limb increments ΔC/Δt (description only)."""
    inc = m["increments"]
    p = Panel(_std(card, series, what="rate of rise before the peak by sampling interval", vs=None),
              "Sampling interval before the peak (h)", f"Rise in concentration per hour ({card['unit']} per h)")
    p.set(subtitle=Q_SUB["A3"])
    p.bars(list(range(1, len(inc) + 1)), [x["dcdt"] for x in inc], color=BLUE)
    p.set(xbreaks=list(range(1, len(inc) + 1)), xlabels=[f"{x['t0']:.2g}–\n{x['t1']:.2g}" for x in inc])
    first_interval_note(p, series)
    return p


def _given(s, card=None):
    """The dose this curve received (mg/kg): the animal's own recorded dose (first dose of a multiple-dose column), else the
    dose level. Every Cmax/D and C/D of a single curve divides by this (George 2026-11-25)."""
    for v in (s.get("dose_given"), s.get("dose"), (card or {}).get("dose_given_mg_per_kg"), (card or {}).get("dose_mg_per_kg")):
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0:
            return v
    return None


def pA4(card, series_list):
    """A4 individual metrics: Tmax and Cmax/D per animal by dose (description)."""
    rows = [(s["label"], s.get("dose") or card.get("dose_mg_per_kg"), s["metrics"]) for s in series_list if "tmax" in s["metrics"]]
    doses = sorted({d for _, d, _ in rows if d})
    out = []
    for key, lab, word in (("tmax", "Tmax (h)", "Tmax by animal"),
                           ("cmax_d", f"Cmax/dose ({card['unit']} per mg/kg)", "Cmax divided by each animal's dose, by animal")):
        p = Panel(_std(card, what=word, vs=None, group=[s for s in series_list if "tmax" in s["metrics"]]),
                  "Dose (mg/kg)" if len(doses) > 1 else "Animal", lab)
        p.set(subtitle=Q_SUB["A4"])
        if len(doses) > 1:
            xs = [d * (1 + 0.04 * ((k % 5) - 2)) for k, (_, d, _) in enumerate(rows)]
            p.set(xlog2=True, xbreaks=doses)
        else:
            xs = list(range(1, len(rows) + 1))
            p.set(xbreaks=xs, xlabels=[r[0] for r in rows])
        given = [_given(s, card) for s in series_list if "tmax" in s["metrics"]]
        ys = [m["tmax"] if key == "tmax" else m["cmax"] / (g or d or 1) for (_, d, m), g in zip(rows, given)]
        p.points(xs, ys, color=BLUE, size=2.8)
        out.append(p)
    return out


def _say_split(cls, ratio):
    """S13 corner reading of the post-peak split, in PK terms (George 2026-11-25)."""
    head = {"DECLINE_FLATTENS": "The decline after the peak slows",
            "DECLINE_STEEPENS": "The decline after the peak speeds up",
            "NEITHER": "The decline after the peak is about log-linear"}.get(cls, "Post-peak decline: " + str(cls).lower().replace("_", " "))
    rate = {"DECLINE_FLATTENS": "slower", "DECLINE_STEEPENS": "faster"}.get(cls)
    return (f"{head}: the decline rate over the later half of the post-peak samples is {ratio:.2f} times the rate over the earlier half."
            if rate else f"{head}.")


LATER_DOSE_LABEL = "samples after the 2nd dose"


def first_interval_note(panel, series):
    """George 2026-11-25: a per-animal figure of a multiple-dose curve shows only the first dosing interval (the samples the
    readings use); the caption states it. The full course is drawn only in the group overview."""
    ev = (series or {}).get("dose_events") if isinstance(series, dict) else None
    if not ev or len(ev) < 2 or "first of " in str(panel.d.get("title") or ""):
        return panel     # S13 rule 9: the standard title already names the first of N doses and their times
    end = ev[1]["time_h"]
    note = (f"First dosing interval, 0–{_hours(end)} h, of {len(ev)} doses at " + ", ".join(_hours(e["time_h"]) for e in ev) + " h")
    cap = panel.d.get("caption")
    panel.set(caption=(note + (". " + cap if cap else "")))
    return panel


def later_doses(panel, series_list, single_label=True):
    """S13 (2026-11-25): in a multiple-dose table the samples after the second dose are drawn (open grey diamonds) and every
    later dose time is a dashed line. Absorption reads only the first dose interval."""
    # George 2026-11-25: the samples after the 2nd dose are drawn by the caller in each animal's own colour (open symbols),
    # joined to its first interval; this helper draws only the later dose times and states the regimen in the caption
    times = sorted({e["time_h"] for s in series_list for e in (s.get("dose_events") or [])[1:]})
    if not times:
        return
    groups = []
    for t in times:      # one line per dose occasion: times within 0.5 h are the same occasion across animals
        if groups and t - groups[-1][-1] <= 0.5:
            groups[-1].append(t)
        else:
            groups.append([t])
    for i, g in enumerate(groups):
        panel.vline(sum(g) / len(g), color=INK2, lty="dashed", lw=0.45,
                    label=("later doses at " + ", ".join(f"{_hours(sum(x) / len(x))}" for x in groups) + " h") if i == 0 else None)
    if panel.d.get("legend", "none") == "none":
        panel.set(legend="bottom_left")
    ev = next((s.get("dose_events") for s in series_list if s.get("dose_events")), None) or []
    note = (f"{len(ev)} doses at " + ", ".join(_hours(e["time_h"]) for e in ev) + " h; absorption readings use the first dosing "
            "interval only (open symbols: samples after the 2nd dose).")
    cap = panel.d.get("caption")
    panel.set(caption=(note + (" " + cap if cap else "")))


def _later_q(s):
    return [x for x in s.get("points_after_next_dose") or s.get("_later_points") or [] if x["status"] == "QUANTIFIED" and x.get("c")]


def pB1(card, m, series, marks=("blq", "terminal", "split"), valley=None, title=None, highlight_post=False):
    """B1 semilog, whole profile: terminal window, split halves, dip points."""
    t, c = np.array(m["_t"]), np.array(m["_c"])
    p = Panel(_std(card, series, "semi-log"), TIME_AXIS, f"Concentration ({card['unit']})", ylog=True)
    p.set(subtitle=Q_SUB["B1"])
    input_band(p, [card_input_h(card)])
    p.line(t, c, color=MUTED, lw=0.35)
    p.points(t, c, color=BLUE, size=2.6, label="quantified")
    reading = []
    if "blq" in marks:
        _blq_marks(p, card, series, m)
    sel = m.get("terminal_selected")
    if "terminal" in marks and sel:
        xx = np.linspace(sel["start"], t[-1], 40)
        p.line(xx, np.exp(sel["intercept"] + sel["slope"] * xx), color=ORANGE, lw=1.1,
               label=f"terminal fit: {sel['n']} samples from {sel['start']:.3g} h, apparent half-life {sel['thalf']:.3g} h")
    sp = m.get("split")
    if "split" in marks and sp and sp.get("ratio") is not None:
        # S13 (George 2026-11-25): no split-half lines (a count split of the post-peak samples, not PK phases); the reading only
        reading.append(_say_split(sp["class"], sp["ratio"]))
    if valley:
        a, b, cc = valley
        reading.append(f"Concentration dips at {t[b]:.3g} h between {t[a]:.3g} and {t[cc]:.3g} h, then rises again.")
    p.set(legend="bottom_left")
    if reading:
        p.set(caption=" ".join(reading[:2]))
    if m.get("last_sample_h", t[-1]) > t[-1]:
        p.set(xlim=[min(0, t[0]), m["last_sample_h"] * 1.05])
    first_interval_note(p, series)
    return p


def pA1_dip(card, m, series, valley, title=None):
    """A1 whole profile (linear) with the dip and the points before and after it marked (question 4)."""
    t, c = np.array(m["_t"]), np.array(m["_c"])
    a, b, cc = valley
    p = pA1(card, m, series, marks=("predose", "blq"), whole=True, title=title)
    p.line(t, c, color=MUTED, lw=0.35)
    p.set(legend=_free_corner(list(t) + [0], list(c) + [0]),
          caption=f"Concentration dips at {t[b]:.3g} h between {t[a]:.3g} and {t[cc]:.3g} h, then rises again.")
    return p


def pT2(card, series, res, t2lab, flags):
    """Per-animal semi-log profile asking whether there is a dip and a second rise (S13 rule 9: standard markers only; the
    reading is the caption)."""
    t, c = np.array(res["_t"]), np.array(res["_c"])
    p = Panel(_std(card, series, "semi-log"), TIME_AXIS, f"Concentration ({card['unit']})", ylog=True)
    p.set(subtitle=Q_SUB["T2"])
    input_band(p, [card_input_h(card)])
    p.line(t, c, color=MUTED, lw=0.35).points(t, c, color=BLUE, size=2.6, label="quantified")
    a, b, cc = res["valley_idx"]
    u = card["unit"]
    margin = res["t2_margin"]
    if margin is not None and margin > 0:
        verdict = ("supported by one point only, so not decided" if "SINGLE_POINT_SUPPORT" in flags else
                   "a sample-removal check was not possible, so not decided" if "LOO_NOT_ASSESSABLE" in flags else
                   "described only" if t2lab == "DESCRIPTIVE_ONLY" else f"both larger than ±{TOL * 100:g} %")
        cap = (f"Drop of {res['m_drop']:.3g} {u} to {t[b]:.3g} h, then a rise of {res['m_rise']:.3g} {u} to {t[cc]:.3g} h; {verdict}.")
    else:
        cap = f"No dip larger than ±{TOL * 100:g} % between {t[a]:.3g} and {t[cc]:.3g} h."
    p.set(caption=cap, legend="bottom_left")
    return p

def pB2(card, m, series):
    """B2 terminal-window sensitivity: apparent t½ of every qualified window, the selected one highlighted."""
    q = [w for w in m["terminal_windows"] if _qualified(w)]
    sel = m.get("terminal_selected") or {}
    p = Panel(_std(card, series, what="apparent half-life by start of the terminal fit", vs=None),
              "Start of the terminal fit (h after start of dosing)", "Apparent half-life (h)")
    p.set(subtitle=Q_SUB["B2"])
    p.points([w["start"] for w in q], [w["thalf"] for w in q], color=BLUE, size=2.8, label="terminal fits that qualify")
    if sel:
        p.points([sel["start"]], [sel["thalf"]], color=ORANGE, shape="ring", size=5, stroke=1.4, label="fit used (best adjusted R²)")
    p.set(legend="top_left")
    first_interval_note(p, series)
    return p


def _ind_points(s):
    return [x for x in s["points"] if x["status"] == "QUANTIFIED" and x.get("c")]


def pInd(card, series_list, verified, log=False, title=None, mark_first=False, mark_tmax=False, early=False):
    """Individual layer on A1 (linear) or B1 (semi-log): one thin line per animal and a bold mean; unverified identity →
    points only with a small time offset, no lines. Returns one panel, or one panel per animal (small multiples)."""
    cols = [BLUE, ORANGE, GREEN, PURPLE, "#E69F00", "#56B4E9", "#444444", "#8C6D31"]
    unit = card["unit"]
    if len(series_list) > IND_SMALL_MULTIPLES:
        out = []
        for s in series_list:
            q = _ind_points(s)
            p = Panel(_std(card, s, "semi-log" if log else "linear", all_doses=not early and bool(_later_q(s))), TIME_AXIS,
                      f"Concentration ({unit})", ylog=log)
            input_band(p, [card_input_h(s) or card_input_h(card)])
            p.points([x["t"] for x in q], [x["c"] for x in q], color=BLUE, size=2.0)
            lq = _later_q(s) if not early else []
            if verified:
                p.line([x["t"] for x in q + lq], [x["c"] for x in q + lq], color=BLUE, lw=0.4)
            if lq:
                p.points([x["t"] for x in lq], [x["c"] for x in lq], color=BLUE, shape="open", size=2.0, label=LATER_DOSE_LABEL)
            if s.get("dose_events") and not early:
                later_doses(p, [s])
            out.append(p)
        return out
    end_ = max(_early_end(s["metrics"]) for s in series_list if "tmax" in s.get("metrics", {})) if early else None
    whole = not early and any(_later_q(s) for s in series_list)
    p = Panel(_std(card, scale="semi-log" if log else "linear", group=series_list, part=f"0–{end_:.3g} h" if early else None, all_doses=whole),
              TIME_AXIS, f"Concentration ({unit})", ylog=log)
    p.set(subtitle=Q_SUB["FIRST" if mark_first else "TMAX" if mark_tmax else "IND"])
    input_band(p, [card_input_h(s) or card_input_h(card) for s in series_list])
    for k, s in enumerate(series_list):
        q = _ind_points(s)
        if not q:
            continue
        tt = np.array([x["t"] for x in q]) * (1 if verified else 1 + 0.012 * (k - (len(series_list) - 1) / 2))
        cc = [x["c"] for x in q]
        col = cols[k % len(cols)]
        p.points(tt, cc, color=col, size=2.3, label=s["label"] + ("" if verified else " (label from the source)"))
        lq = _later_q(s) if not early else []
        if lq:   # the whole course of each animal in its own colour, later doses open (George 2026-11-25)
            p.points([x["t"] for x in lq], [x["c"] for x in lq], color=col, shape="open", size=2.0)
        if verified:
            p.line(list(tt) + [x["t"] for x in lq], cc + [x["c"] for x in lq], color=col, lw=0.35, alpha=0.8)
        m = s.get("metrics") or {}
        if mark_first and m.get("first_t") is not None:
            p.points([tt[0]], [cc[0]], color=col, shape="ring", size=4.6, stroke=1.2,
                     label="first quantified sample" if k == 0 else None)
        if mark_tmax and m.get("tmax") is not None:
            i = int(np.argmax(cc))
            p.points([tt[i]], [cc[i]], color=col, shape="ring", size=4.6, stroke=1.2, label="Tmax" if k == 0 else None)
    if verified:
        times = sorted({x["t"] for x in _ind_points(series_list[0])})
        mean = [(t, np.mean([x["c"] for s in series_list for x in _ind_points(s) if x["t"] == t]))
                for t in times if all(any(x["t"] == t for x in _ind_points(s)) for s in series_list)]
        if mean:
            p.line([x for x, _ in mean], [y for _, y in mean], color=INK, lw=1.4, label="mean (all animals quantified)")
    if early:  # 0 to the latest first sample after Tmax over the animals
        end = max(_early_end(s["metrics"]) for s in series_list if "tmax" in s.get("metrics", {}))
        p.set(xlim=[-0.04 * end, end * 1.06])
    p.set(legend="top_right" if not early else "bottom_right")
    if not early and any(s.get("dose_events") for s in series_list):
        later_doses(p, series_list)
    return p


def pC1(r, members):
    """C1 C/D overlay: linear (0 to about 1.5 × the latest Tmax) and semi-log (whole profile); common window shaded."""
    ms = sorted(members, key=lambda x: x[0])
    T = r["window_end_h"]
    tmx = max(mem[1]["tmax"] for mem in ms)
    ramp = RAMP[-len(ms):] if len(ms) <= len(RAMP) else [RAMP[min(len(RAMP) - 1, int(k * len(RAMP) / len(ms)))] for k in range(len(ms))]
    out = []
    for log in (False, True):
        p = Panel(_rstd(r, "concentration divided by dose", "semi-log" if log else "linear", part=None if log else f"0–{1.5 * tmx:.2g} h"),
                  TIME_AXIS, "Concentration / dose\n(per mg/kg)", ylog=log)
        p.set(subtitle=Q_SUB["DOSE"])
        if log or T < 1.5 * tmx:
            p.band(0, T, color=ORANGE, alpha=0.08)
        se_labelled = False
        for mem, col in zip(ms, ramp):
            dose, m, unit = mem[:3]
            t = np.array(m["_t"]); y = np.array(m["_c"]) / dose
            k = np.ones(len(t), bool) if log else t <= 1.5 * tmx + 1e-9
            p.line(t[k], y[k], color=col, lw=0.6).points(t[k], y[k], color=col, size=2.3, label=f"{dose:g} mg/kg")
            bars = [x for x in (mem[3] if len(mem) > 3 else []) if x.get("se") is not None and x.get("c") is not None
                    and x["status"] == "QUANTIFIED" and (log or x["t"] <= 1.5 * tmx + 1e-9)]
            if bars:
                p.segments([x["t"] for x in bars], [max(x["c"] - x["se"], 1e-12) / dose for x in bars],
                           [x["t"] for x in bars], [(x["c"] + x["se"]) / dose for x in bars], color=col, lw=0.6,
                           label="readable source SE" if not se_labelled else None)
                se_labelled = True
        p.set(caption=f"Shaded: the common window 0–{T:g} h over which AUC/dose is compared" + ("." if log or T < 1.5 * tmx else " (beyond this view)."))
        if not log:
            p.set(xlim=[0, 1.5 * tmx * 1.02], legend="top_right")
        else:
            p.set(legend="none")
        out.append(p)
    return out


def pC2(r, t3=None):
    """C2 metrics by log2 dose: Cmax/D, apparent t½ (range + selected), AUC/D (common window; 0–tlast dashed);
    the T3 R with its CI against 1 when the T3 data exist."""
    rows = r["rows"]; d = [x["dose"] for x in rows]
    a = Panel(_rstd(r, "Cmax/dose by dose", vs=None), "Dose (mg/kg)", "Cmax / dose (per mg/kg)", xlog2=True).set(xbreaks=d, subtitle=Q_SUB["DOSE"])
    a.line(d, [x["cmax_d"] for x in rows], color=BLUE).points(d, [x["cmax_d"] for x in rows], color=BLUE)
    b = Panel(_rstd(r, "apparent half-life by dose", vs=None), "Dose (mg/kg)", "Apparent half-life (h)", xlog2=True).set(xbreaks=d)
    rr = [x for x in rows if x["thalf_range"]]
    if rr:
        b.segments([x["dose"] for x in rr], [x["thalf_range"][0] for x in rr], [x["dose"] for x in rr], [x["thalf_range"][1] for x in rr],
                   color=MUTED, lw=3.5, label="range over the terminal fits that qualify")
    th = [x for x in rows if x["thalf"]]
    if th:
        b.points([x["dose"] for x in th], [x["thalf"] for x in th], color=BLUE, label="fit used")
        b.set(legend="top_left")
    else:
        b.points(d, [0] * len(d), color=SURF, size=0.1)
        b.text(0.5, 0.5, "no terminal fit qualifies\n(fewer than 3 samples after the peak, or the\nfit covers less than 2 half-lives)", hjust=0.5, vjust=0.5, npc=True)
        b.set(yticks=False)
    c = Panel(_rstd(r, "AUC/dose by dose", vs=None), "Dose (mg/kg)", "AUC / dose", xlog2=True).set(
        xbreaks=d, caption=f"AUC/dose at the highest dose is {r['R_window']:.2f} times that at the lowest (common window 0–{r['window_end_h']:g} h).")
    c.line(d, [x["aucW_d"] for x in rows], color=BLUE, label=f"0–{r['window_end_h']:g} h (common window)").points(d, [x["aucW_d"] for x in rows], color=BLUE)
    if all(x["auc_last_d"] is not None for x in rows):
        c.line(d, [x["auc_last_d"] for x in rows], color=MUTED, lty="dashed", label="0 to each dose's last sample (windows differ)").points(
            d, [x["auc_last_d"] for x in rows], color=MUTED)
    c.set(legend="top_left")
    out = [a, b, c]
    if t3 and t3.get("ci"):
        out.append(pT3(t3, r))
    return out


def pT3(t3, r=None):
    """T3: R of AUC/D with its CI against 1."""
    lo, hi = t3["ci"]
    win = f", 0–{t3['window_end_h']:g} h" if t3.get("window_end_h") else ""
    if (t3.get("animal_auc") or {}).get("status") == "ASSESSED":
        win = ", " + t3["animal_auc"]["auc_definition"]
    xlo, xhi = min(lo, 1) / 1.6, max(hi, 1) * 1.6
    a = Panel(_rstd(r or t3, f"ratio of AUC/dose, {t3['dose_pair'][1]:g} over {t3['dose_pair'][0]:g} mg/kg, with confidence interval", vs=None))
    a.set(subtitle=Q_SUB["DOSE"], xlab=f"AUC/dose at {t3['dose_pair'][1]:g} mg/kg ÷ AUC/dose at {t3['dose_pair'][0]:g} mg/kg{win}",
          xlog=True, yticks=False, ylim=[-1, 1.4], xlim=[xlo, xhi])
    a.vline(1, color=ORANGE, lty="dashed", lw=0.6)
    a.segments([lo], [0], [hi], [0], color=BLUE, lw=3)
    a.points([t3["R"]], [0], color=INK, size=3.4)
    inside = lo <= 1 <= hi
    a.set(caption=f"Ratio {t3['R']:.3g} ({t3['ci_level'] * 100:.0f} % CI {lo:.3g}–{hi:.3g}); the interval "
          + ("includes 1, so no departure from dose proportionality is shown." if inside else "excludes 1: exposure is not proportional to dose."))
    return a


def _t3p_offset_words(p):
    """r4.4 item 19 (2026-11-24): a short note when the two doses were sampled at different times."""
    o = p.get("t3p_time_offset") or {}
    if not o:
        return ""
    bits = []
    if o.get("n_bounded"):
        bits.append(f"{o['n_bounded']} offset time{'s' if o['n_bounded'] != 1 else ''} tested beyond a timing-error bound stated in the input")
    if o.get("n_unbounded"):
        bits.append(f"{o['n_unbounded']} offset time{'s' if o['n_unbounded'] != 1 else ''} without a stated timing-error bound"
                    + (" (the whole contrast is sensitivity only)" if "TIME_OFFSET_UNBOUNDED" in (p.get("t3p_flags") or []) else ", left out of the formal family"))
    return "; sampling times differ between the doses: " + ", ".join(bits) if bits else ""


def pC3(r):
    """C3 per-time ln(C/D) ratio, highest over lowest dose: with T3p data 95 % CI and Holm marks; otherwise point ratios."""
    p3 = r.get("t3p") or {}
    if p3.get("t3p_times"):
        dl, dh = p3["t3p_dose_pair"]
        rows = p3["t3p_ln_ratio_ci"]
        offset = any(not x.get("aligned", True) for x in rows)
        # 2026-11-24 review: the bars are pointwise unadjusted 95 % CIs; the colour is the Holm-adjusted test
        b = Panel(_rstd(r, "log ratio of concentration/dose between doses", vs="time"),
                  "Time after start of dosing (h, low-dose sampling time)   (× = not tested)" + ("\ngrey bar: interval widened for the timing offset" if offset else ""),
                  f"ln(C/dose at {dh:g}) − ln(C/dose at {dl:g})")
        b.set(subtitle=Q_SUB["DOSE_T"], caption="Bars: 95 % confidence interval at each time (not adjusted); colour: significant after Holm correction across times.")
        b.hline(0, color=INK2, lw=0.5)
        wide = [x for x in rows if x.get("ci95_with_offset_bound")]
        if wide:
            b.segments([x["t"] for x in wide], [x["ci95_with_offset_bound"][0] for x in wide], [x["t"] for x in wide],
                       [x["ci95_with_offset_bound"][1] for x in wide], color=MUTED, lw=1)
        for want, col, shape, name in ((True, ORANGE, "circle", "significant after Holm"), (False, BLUE, "open", "not significant after Holm")):
            sel = [(x, ph) for x, s, ph in zip(rows, p3["significant"], p3["t3p_p_holm"]) if s == want]
            if not sel:
                b.points([], [], color=col, shape=shape, size=3, label=name, stroke=1.3)
                continue
            b.segments([x["t"] for x, _ in sel], [x["ci95"][0] for x, _ in sel], [x["t"] for x, _ in sel], [x["ci95"][1] for x, _ in sel], color=col, lw=2)
            b.points([x["t"] for x, _ in sel], [x["ln_ratio"] for x, _ in sel], color=col, shape=shape, size=3.2, label=name, stroke=1.3)
            for x, ph in sel:
                b.text(x["t"], (x.get("ci95_with_offset_bound") or x["ci95"])[1],
                       f"p {ph:.2g}" + ("" if x.get("aligned", True) else f"\nhigh dose {x['t_high']:g} h"), hjust=0.5, vjust=0, size=2.6)
        sk = p3.get("skipped", [])
        if sk:
            b.points([s["t"] for s in sk], [0] * len(sk), color=MUTED, shape="cross", size=2.4)
        b.set(legend="top")
        return b
    x = [q["t"] for q in r["per_time"]]; y = [q["ratio"] for q in r["per_time"]]
    p = Panel(_rstd(r, "ratio of concentration/dose between the highest and lowest dose"), TIME_AXIS,
              f"C/dose at {r['doses'][-1]:g} ÷ C/dose at {r['doses'][0]:g}")
    p.set(subtitle=Q_SUB["DOSE_T"], caption="Description only, not a test.")
    p.hline(1, color=MUTED).line(x, y, color=BLUE, lw=0.6).points(x, y, color=BLUE)
    return p


def pD1(ev_card, ev, iv_card, iv, res):
    """D1 semilog dose-normalized EV and IV with terminal windows, and the T4 Q intervals."""
    a = Panel(COMMON.std_title(ev_card.get("species"), f"{_route_word(ev_card)} and IV", "", None, "", "concentration divided by dose", "semi-log",
                               ev_card.get("matrix")), TIME_AXIS, f"Concentration / dose\n({iv_card['unit']} per mg/kg)", ylog=True)
    a.set(subtitle=Q_SUB["EVIV"])
    input_band(a, [card_input_h(iv_card)])
    for card, m, lty in ((ev_card, ev, "solid"), (iv_card, iv, "dashed")):
        d = card["dose_mg_per_kg"]
        lab = f"{card['dataset_id']} {card['route_detail'] if card['route_class'] == 'EV' else 'IV'} {d:g} mg/kg"
        a.points(m["_t"], np.array(m["_c"]) / d, color=BLUE if lty == "solid" else PURPLE, shape="circle" if lty == "solid" else "open", label=lab)
        sel = m.get("terminal_selected")
        if sel:
            xx = np.linspace(sel["start"], m["_t"][-1], 30)
            a.line(xx, np.exp(sel["intercept"] + sel["slope"] * xx) / d, color=BLUE if lty == "solid" else PURPLE, lty=lty, lw=0.8)
    a.set(legend="top_right")
    out = [a]
    if res.get("q"):
        b = Panel(COMMON.std_title(ev_card.get("species"), f"{_route_word(ev_card)} and IV", "", None, "",
                                   "EV/IV ratio of concentration divided by dose", None, None, "time"), TIME_AXIS, "EV / IV")
        b.set(subtitle="Does the EV/IV ratio fall over time?")
        input_band(b, [card_input_h(iv_card)])
        tq = [x["t"] for x in res["q"]]
        b.line(tq, [x["q"] for x in res["q"]], color=MUTED, lw=0.4).points(tq, [x["q"] for x in res["q"]], color=BLUE, size=2.6)
        b.set(caption=("The ratio falls by more than the assumed ±5 % error between matched times." if (res.get("mt4") or 0) > 0
                       else "No fall in the ratio beyond the assumed ±5 % error."))
        out.append(b)
    return out


def _dose_range(doses):
    doses = sorted({round(float(d), 3) for d in doses if d})
    return f"{doses[0]:g}" if len(doses) == 1 else f"{doses[0]:g}–{doses[-1]:g}" if doses else "?"


def pD1d(ev_card, ev_series, iv_refs, reason):
    """Unpaired EV and IV individuals divided by dose, semi-log: whole profile, and the first fifth of the sampling
    range (description only)."""
    unit = ev_card["unit"]
    route = ev_card["route_detail"] if ev_card["route_detail"] not in (None, "", "NOT_FOUND") else "EV"
    last = max((x["t"] for item in list(ev_series) + list(iv_refs) for x in _ind_points(item)), default=0)
    end = last / 5 if last > 0 else None
    panels = []
    for whole in (True, False):
        log = True
        p = Panel(COMMON.std_title(ev_card.get("species"), f"{route} and IV", f"{len(ev_series)} + {len(iv_refs)} profiles", None, "",
                                   "concentration divided by dose", "semi-log", ev_card.get("matrix"), "time",
                                   None if whole else f"0–{end:.2g} h"), TIME_AXIS, f"Concentration / dose\n({unit} per mg/kg)", ylog=log)
        p.set(subtitle=Q_SUB["EVIV"])
        input_band(p, [card_input_h(i) or card_input_h(i.get("card")) for i in iv_refs])
        for k, (items, col, shape, lty, lab) in enumerate((
                ([(s, _given(s, ev_card)) for s in ev_series], BLUE, "circle", "solid",
                 f"{route} {_dose_range(_given(s, ev_card) for s in ev_series)} mg/kg (n = {len(ev_series)})"),
                ([(i, _given({}, i["card"])) for i in iv_refs], PURPLE, "open", "dashed",
                 f"IV {_dose_range(_given({}, i['card']) for i in iv_refs)} mg/kg (n = {len(iv_refs)})"))):
            first = True
            for item, dose in items:
                q = [x for x in _ind_points(item) if x["t"] > 0]
                if not q or not dose:
                    continue
                tt = np.array([x["t"] for x in q]); yy = np.array([x["c"] for x in q]) / dose
                if not whole and end:
                    keep = tt <= end + 1e-9; tt, yy = tt[keep], yy[keep]
                    if not len(tt):
                        continue
                p.line(tt, yy, color=col, lty=lty, lw=0.35, alpha=0.8)
                p.points(tt, yy, color=col, shape=shape, size=2.0, label=lab if first else None)
                first = False
        if not whole and end:
            p.set(xlim=[0, end * 1.04])
        p.set(legend="top_right")
        panels.append(p)
    panels[0].set(caption=_d1d_caption(reason))
    return panels


def _d1d_caption(reason):
    """At most two plain sentences: why there is no paired comparison, and the group-level hint when there is one."""
    first = ("The EV and IV curves are not paired within animals (the interval between occasions is not supplied), "
             "so F and paired tests are not computed.")
    m = re.search(r"Group-level, unpaired \(hint\): median (EV apparent t½(?: after the last dose)?) ([\d.]+) h \(n (\d+)\) against median "
                  r"IV terminal t½ ([\d.]+) h \(n (\d+)\), ratio ([\d.]+): ([^.]+)\.", reason or "")
    if not m:
        return first
    what = "half-life after the last EV dose" if "last dose" in m.group(1) else "apparent EV half-life"
    words = {"absorption-influenced candidate": "absorption may set the EV decline (possible flip-flop)",
             "compatible with a common terminal process": "EV and IV share the terminal decline"}
    reading = next((v for k, v in words.items() if m.group(7).strip().lower().startswith(k)), m.group(7).strip())
    return (first + f" Group level, unpaired (hint): the median {what} ({m.group(2)} h, n {m.group(3)}) is {m.group(6)} times the median IV "
            f"terminal half-life ({m.group(4)} h, n {m.group(5)}), so {reading}.")


def pD1a(pairs):
    """Per-animal EV/IV pairs: the D1 semi-log panel of each pair, titled with the subject."""
    out = []
    for r in pairs:
        a = pD1(r["_ev_card"], r["_em"], r["_iv_card"], r["_im"], r)[0]
        # T4 is descriptive (CANNOT_ASSESS) for every pair, so the panel names the animal and its window AUC ratio only.
        ec = r["_ev_card"]
        a.set(title=COMMON.std_title(ec.get("species"), f"{_route_word(ec)} and IV", f"animal {r['subject_id']}", None, "",
                                     "concentration divided by dose", "semi-log", ec.get("matrix")), legend="none",
              caption=(f"EV/IV ratio of AUC/dose over the common window: {r['window_auc_ratio']:.3g}." if r.get("window_auc_ratio") is not None
                       else "EV/IV ratio of AUC/dose not estimable."))
        out.append(a)
    return out


def pD2(ev_card, ev, iv_card, iv, res):
    """D2 shades precisely the interval and interpolation used for the exposure ratio."""
    start, T = res["window_start_h"], res["window_end_h"]
    p = Panel(COMMON.std_title(ev_card.get("species"), f"{_route_word(ev_card)} and IV", "", None, "", "concentration divided by dose",
                               "linear", ev_card.get("matrix")), TIME_AXIS, f"Concentration / dose ({iv_card['unit']} per mg/kg)")
    p.set(subtitle="How large is EV exposure relative to IV over the same window?")
    input_band(p, [card_input_h(iv_card)])
    for card, m, col, lty in ((ev_card, ev, BLUE, "solid"), (iv_card, iv, PURPLE, "dashed")):
        d = card["dose_mg_per_kg"]
        t, y = _interval_profile(m, start, T, dense=True)
        p.area(t, y / d, color=col, alpha=0.10)
        p.line(t, y / d, color=col, lty=lty, lw=0.5)
        p.points(m["_t"], np.asarray(m["_c"]) / d, color=col, size=2.2, label=card["dataset_id"])
    p.vline(start, color=INK2, lty="dotted", label=f"AUC window {_hours(start)}–{_hours(T)} h")
    p.vline(T, color=INK2, lty="dotted")
    p.set(legend="top_right", caption=f"EV/IV ratio of AUC/dose over {_ratio_window_text(res)}: {res['window_auc_ratio']:.3g} "
          "(same samples, linear-up/log-down). This is not the absolute bioavailability.")
    return p


def pE1(a_card, a, b_card, b, log=True):
    p = Panel(COMMON.std_title(a_card.get("species"), " and ".join(dict.fromkeys((_route_word(b_card), _route_word(a_card)))), "two conditions",
                               None, "", "concentration", "semi-log" if log else "linear", a_card.get("matrix")),
              TIME_AXIS, f"Concentration ({a_card['unit']})", ylog=log)
    p.set(subtitle=Q_SUB["COND"], caption="Reference condition solid, test condition dashed.")
    input_band(p, [card_input_h(a_card), card_input_h(b_card)])
    for card, m, col, lty in ((b_card, b, INK2, "solid"), (a_card, a, GREEN, "dashed")):
        lab = f"{card['dataset_id']} {card['route_detail']} {card['dose_mg_per_kg']:g} mg/kg"
        p.line(m["_t"], m["_c"], color=col, lty=lty, lw=0.5).points(m["_t"], m["_c"], color=col, size=2.2, label=lab)
    p.set(legend="top_right")
    return p


def pE2(res):
    p2 = Panel("Concentration ratio between the two conditions vs matched time", "Matched time (h after start of dosing)",
               "Test / reference concentration")
    p2.set(subtitle="Is the ratio the same at every time?")
    tt = [x["t"] for x in res["intervals"]]
    p2.line(tt, [x["c"] for x in res["intervals"]], color=MUTED, lw=0.4).points(tt, [x["c"] for x in res["intervals"]], color=BLUE, size=2.6)
    p2.set(caption=("The ratio is not the same at every time (beyond the assumed ±5 % error)." if res["c_lower"] > res["c_upper"]
                    else "One constant ratio fits every time within the assumed ±5 % error."))
    return p2


def pE3(a_card, a, b_card, b):
    """E3 shape-normalized overlay: each curve divided by its own window AUC (common window = last matched time)."""
    pairs = _common_times([a, b], rel=PAIR_TIME_REL, absolute=PAIR_TIME_ABS, clip_endpoint=True)
    p = Panel(COMMON.std_title(a_card.get("species"), " and ".join(dict.fromkeys((_route_word(b_card), _route_word(a_card)))), "two conditions",
                               None, "", "concentration divided by its AUC", "linear", a_card.get("matrix")), TIME_AXIS,
              "Concentration / AUC over the window (1/h)")
    p.set(subtitle=Q_SUB["SHAPE"], caption="Each curve is divided by its own AUC over the common window, so only the shapes are compared.")
    T = min(a["_t"][pairs[-1][0]], b["tlast"])
    for card, m, col, lty in ((b_card, b, INK2, "solid"), (a_card, a, GREEN, "dashed")):
        area = _window_auc(m, T)
        if area is None:
            return None
        y = np.array(m["_c"]) / area
        p.line(m["_t"], y, color=col, lty=lty, lw=0.5).points(m["_t"], y, color=col, size=2.2, label=f"{card['dataset_id']} (÷ AUC0–{T:.3g} h)")
    p.set(legend="top_right")
    return p


_PNAME = {"CMAX": "Cmax/dose", "AUC": "AUC/dose", "TMAX": "Tmax", "THALF": "half-life", "CL_F": "CL/F", "F": "F"}


def pF(card, params):
    """F reported parameters: one panel per parameter by dose; bars = reported dispersion."""
    names = [n for n, _ in PARAM_PATTERNS if any(p["param"] == n and p["dose"] for p in params)]
    panels = []
    for name in names:
        ps = sorted([p for p in params if p["param"] == name and p["dose"]], key=lambda p: p["dose"])
        d = [p["dose"] for p in ps]
        norm = name in ("CMAX", "AUC")
        y = [p["value"] / p["dose"] if norm else p["value"] for p in ps]
        e = [(p["dispersion"] / p["dose"] if norm else p["dispersion"]) if p["dispersion"] is not None else None for p in ps]
        unit = ps[0].get("unit") or ""
        pan = Panel(_std(card, what=f"reported {_PNAME[name]} by dose", vs=None, who="", dose=None), "Dose (mg/kg)",
                    _PNAME[name] + (f" ({unit}{' per mg/kg' if norm else ''})" if unit and unit != "NOT_FOUND" else ""), xlog2=len(d) > 1)
        pan.set(subtitle=Q_SUB["PARAM"])
        pan.set(xbreaks=d)
        withe = [(x, v, s) for x, v, s in zip(d, y, e) if s]
        if withe:
            pan.segments([x for x, _, _ in withe], [v - s for _, v, s in withe], [x for x, _, _ in withe], [v + s for _, v, s in withe], color=BLUE, lw=0.7)
        if len(d) > 1:
            pan.line(d, y, color=BLUE, lw=0.6)
        pan.points(d, y, color=BLUE, size=2.8)
        panels.append(pan)
    return panels


def _w(n, each=4.3, extra=0.3):
    return each * n + extra


_wrap = COMMON._wrap


def t2_curve(points):
    """A0.10 T2 on one series: confirmed valley U_b < min(L_a, L_c); drop-one robustness."""
    q = [p for p in points if p["status"] == "QUANTIFIED" and p["c"] is not None and p["c"] > 0 and p["t"] > 0]
    t = [p["t"] for p in q]; c = [p["c"] for p in q]
    L = [x * (1 - TOL) for x in c]; U = [x * (1 + TOL) for x in c]

    def scan(keep):
        best = None
        for a, b, cc in itertools.combinations(keep, 3):
            if U[b] < min(L[a], L[cc]):
                m = min(L[a] - U[b], L[cc] - U[b])
                if best is None or m > best[0]:
                    best = (m, a, b, cc)
        return best
    allk = list(range(len(c)))
    best = scan(allk)
    if not best:
        return {"t2_margin": None, "valley": None, "robust": None, "_t": t, "_c": c}
    m, a, b, cc = best
    # R2: a rerun that leaves fewer than 3 quantified samples cannot be tested (LOO_NOT_ASSESSABLE); a valley that
    # disappears in a valid rerun is SINGLE_POINT_SUPPORT, naming the removed sample
    not_assessable = [t[d] for d in allk if len(allk) - 1 < 3]
    lost = [t[d] for d in allk if len(allk) - 1 >= 3 and not scan([k for k in allk if k != d])]
    removal = {"unit": "quantified sample", "required": len(allk), "assessable": len(allk) - len(not_assessable),
               "not_assessable": not_assessable, "lost_when_removed_h": lost,
               "status": "PASSED" if not (lost or not_assessable) else "DEFERRED"}
    return {"t2_margin": m, "m_drop": L[a] - U[b], "m_rise": L[cc] - U[b], "relative": m / U[b],
            "valley": [t[a], t[b], t[cc]], "valley_idx": [a, b, cc], "robust": removal["status"] == "PASSED",
            "removal": removal, "_t": t, "_c": c}


def t2_label(res, level, card=None, baseline_unresolved=False):
    """A4: T2 runs only on a verified serially sampled animal, single dose, with a drug-free baseline (review guide Q2).
    Group means, unverified identity, destructive sampling and an unresolved baseline are described only."""
    if level == "GROUP_MEAN":
        return "DESCRIPTIVE_ONLY", ["T2_NOT_APPLICABLE_TO_GROUP_MEANS"]
    if level == "INDIVIDUAL_IDENTITY_UNVERIFIED":
        return "DESCRIPTIVE_ONLY", ["T2_NOT_APPLICABLE_IDENTITY_UNVERIFIED"]
    if card is not None and _destructive(card):
        return "DESCRIPTIVE_ONLY", ["T2_NOT_APPLICABLE_DESTRUCTIVE_SAMPLING"]
    if baseline_unresolved:
        return "DESCRIPTIVE_ONLY", ["T2_NOT_APPLICABLE_BASELINE_UNRESOLVED", "DRUG_FREE_BASELINE_UNRESOLVED"]
    flags = ["SENSITIVITY_ONLY"]
    rem = res.get("removal") or {}
    if res["t2_margin"] is not None and rem.get("lost_when_removed_h"):
        flags.append("SINGLE_POINT_SUPPORT")
    if res["t2_margin"] is not None and rem.get("not_assessable"):
        flags.append("LOO_NOT_ASSESSABLE")
    return "CANNOT_ASSESS", flags


# ---------------------------------------------------------------- t quantile without scipy

_t_cdf = COMMON._t_cdf


_t_upper = COMMON._t_upper


t_ppf = COMMON.t_ppf


# ---------------------------------------------------------------- T3 paths (A0.10, A0.12)

def t3_group_sd(lo, hi, level=0.95, sensitivity=False, equivalence_margin=None):
    """A0.12: parallel groups with AUC mean, between-animal SD and n per dose. Log-ratio CI with
    delta-method SE = CV/sqrt(n) and Welch-Satterthwaite df."""
    R = (hi["auc"] / hi["dose"]) / (lo["auc"] / lo["dose"])
    s1, s2 = (hi["sd"] / hi["auc"]) ** 2 / hi["n"], (lo["sd"] / lo["auc"]) ** 2 / lo["n"]
    se = math.sqrt(s1 + s2)
    df = (s1 + s2) ** 2 / (s1 ** 2 / (hi["n"] - 1) + s2 ** 2 / (lo["n"] - 1))
    tq = t_ppf(1 - (1 - level) / 2, df)
    ci = (R * math.exp(-tq * se), R * math.exp(tq * se))
    label = "EXCLUDED_UNDER_STATED_ASSUMPTIONS" if (ci[0] > 1 or ci[1] < 1) else "NOT_EXCLUDED"
    equivalence = {"status": "NOT_ASSESSED", "reason": "no predeclared acceptable ratio range"}
    if equivalence_margin:
        low, high = _num(equivalence_margin.get("lower")), _num(equivalence_margin.get("upper"))
        if sensitivity or equivalence_margin.get("predeclared") is not True or not equivalence_margin.get("source") or low is None or high is None or not 0 < low < 1 < high:
            equivalence = {"status": "CANNOT_ASSESS", "reason": "verified animal-summary uncertainty and a sourced, predeclared margin are required"}
        else:
            q90 = t_ppf(.95, df)
            ci90 = [R * math.exp(-q90 * se), R * math.exp(q90 * se)]
            equivalence = {"status": "WITHIN_PREDECLARED_MARGIN" if low < ci90[0] and ci90[1] < high else "NOT_ESTABLISHED",
                           "ci90": ci90, "margin": [low, high], "alpha": .05, "source": equivalence_margin["source"]}
    # R2: two summary AUCs leave no removable unit, so a full-data contradiction is deferred (LOO_NOT_ASSESSABLE)
    formal, rflags, rec = _removal_outcome(label, [], "dose-group AUC summary (no removable unit)")
    return {"R": R, "ci": ci, "ci_level": level, "df": df, "method": "log ratio, delta SE, Welch df",
            "equivalence": equivalence, "population_inference": not sensitivity,
            "t3_data_level": "GROUP_SUMMARY_SD", "t3_label": "CANNOT_ASSESS" if sensitivity else formal,
            **({"t3_sensitivity_label": label} if sensitivity or rflags else {}),
            "t3_flags": (["SENSITIVITY_ONLY"] if sensitivity else []) + rflags, "t3_removal": rec,
            **({"t3_family": _t3_family([lo["dose"], hi["dose"]], None, "dose-group AUC summary with between-animal SD and n")}
               if not sensitivity and not rflags else {}),
            "dose_pair": [lo["dose"], hi["dose"]]}


def bailer_auc(t, c, sd, n, T, parts=False):
    """Bailer 1988: AUC(0,T) of the mean curve with design zero; Var = sum w_i^2 s_i^2 / n_i.
    parts=True also returns the per-time variance terms and their n (for the Satterthwaite df)."""
    tt = [0.0] + [x for x in t if x <= T + 1e-9]
    k = len(tt) - 1
    w = [0.0] * (k + 1)
    for i in range(k):
        dt = tt[i + 1] - tt[i]
        w[i] += dt / 2; w[i + 1] += dt / 2
    cc = [0.0] + c[:k]; ss = [0.0] + sd[:k]; nn = [1] + n[:k]
    a = sum(w[i] * cc[i] for i in range(k + 1))
    terms = [(w[i] ** 2 * ss[i] ** 2 / nn[i], nn[i]) for i in range(1, k + 1)]
    v = sum(x for x, _ in terms)
    return (a, v, terms) if parts else (a, v)


def t3_bailer(lo, hi, T, level=0.95):
    """R1: log-ratio interval with a t quantile on Satterthwaite degrees of freedom (each time-point variance term
    carries n_i - 1 df) instead of the normal quantile. The conclusion is limited to dose-normalised exposure over [0, T]."""
    a1, v1, p1 = bailer_auc(lo["t"], lo["c"], lo["sd"], lo["n"], T, parts=True)
    a2, v2, p2 = bailer_auc(hi["t"], hi["c"], hi["sd"], hi["n"], T, parts=True)
    R = (a2 / hi["dose"]) / (a1 / lo["dose"])
    comps = [(x / a1 ** 2, n_) for x, n_ in p1] + [(x / a2 ** 2, n_) for x, n_ in p2]
    var = sum(x for x, _ in comps)
    se = math.sqrt(var)
    den = sum(x * x / (n_ - 1) for x, n_ in comps if n_ > 1 and x > 0)
    df = var * var / den if den > 0 else None
    if df is None or not math.isfinite(se) or se <= 0:
        return {"R": R, "ci": None, "ci_level": level, "t3_label": "CANNOT_ASSESS", "t3_flags": [],
                "t3_reason": "zero or unavailable Bailer variance", "t3_data_level": "DESTRUCTIVE_SAMPLING_SD",
                "dose_pair": [lo["dose"], hi["dose"]], "window_end_h": T}
    q = t_ppf(1 - (1 - level) / 2, df)
    ci = (R * math.exp(-q * se), R * math.exp(q * se))
    label = "EXCLUDED_UNDER_STATED_ASSUMPTIONS" if (ci[0] > 1 or ci[1] < 1) else "NOT_EXCLUDED"
    return {"R": R, "ci": ci, "ci_level": level, "df": df, "se_log_ratio": se,
            "method": "Bailer 1988 sparse-sampling AUC, linear trapezoid; log-ratio t interval with Satterthwaite df",
            "conclusion_scope": f"dose-normalised exposure over [0, {T:g}] h (equal or unequal); the mechanism is judged separately",
            "t3_data_level": "DESTRUCTIVE_SAMPLING_SD", "t3_label": label, "t3_flags": [], "dose_pair": [lo["dose"], hi["dose"]],
            "window_end_h": T}


def _t3_bailer_removal(lo, hi, T):
    """R2 for T3 Bailer: drop each sampled time (from both dose groups where present) and recompute over the same window
    [0, T]. Removing the endpoint T breaks the window: that rerun is not assessable."""
    times = sorted(set(lo["t"]) | set(hi["t"]))
    reruns = []
    for t_ in times:
        if abs(t_ - T) < 1e-9:
            reruns.append((f"{t_:g} h", None)); continue
        def drop(g):
            keep = [i for i, x in enumerate(g["t"]) if abs(x - t_) > 1e-9]
            return {**g, **{k: [g[k][i] for i in keep] for k in ("t", "c", "sd", "n")}}
        a, b = drop(lo), drop(hi)
        if not a["t"] or not b["t"]:
            reruns.append((f"{t_:g} h", None)); continue
        r = t3_bailer(a, b, T)
        reruns.append((f"{t_:g} h", None if r.get("ci") is None else r["t3_label"]))
    return reruns


# ---------------------------------------------------------------- A0.12 reported parameters

PARAM_PATTERNS = [
    ("CL_F", r"\bcl\w*\s*/\s*f\b|clss/f"),
    ("CMAX", r"c\s*max|maximum (serum |plasma )?concentration"),
    ("TMAX", r"t\s*max"),
    ("AUC", r"\bauc|\basc\b|area under"),
    ("THALF", r"half|t\s*1\s*/\s*2|t½"),
    ("F", r"^\s*f\s*(\(%\))?\s*$|bioavailab"),
]


def _param_name(text):
    s = str(text or "").lower()
    if "dose-normalized" in s or "dose normalized" in s or "fauc" in s or "unbound" in s:
        return None
    for name, pat in PARAM_PATTERNS:
        if re.search(pat, s):
            return name
    return None


def _value_pm(raw, disp=None):
    """'27.2 ± 12.2' -> (27.2, 12.2); numbers pass through; decimal commas accepted."""
    if raw is None:
        return None, None
    if isinstance(raw, (int, float)):
        return float(raw), _num(disp)
    txt = str(raw).replace(",", ".").replace("*", "").strip()
    pm = COMMON.mean_dispersion(txt)   # 2026-11-24 review: whole numbers, exponent included
    if pm:
        return pm[0], pm[1]
    x = COMMON.to_float(txt)
    return (x, _num(disp)) if x is not None else (None, None)


def _dispersion_type(text):
    s = str(text or "").lower()
    if re.search(r"standard error|\bse\b|s\.e\.", s):
        return "SE"
    if re.search(r"standard deviation|\bsd\b|± sd|mean ± sd", s):
        return "SD"
    if "confidence interval" in s or "95% ci" in s:
        return "CI"
    return "UNKNOWN"


def reported_parameters(entry):
    """Return (card, params) for a REPORTED_PARAMETERS EV dataset in long or wide layout."""
    card, _ = extract({**entry, "columns": [c for c in entry.get("columns", []) if c.get("meaning") != "CONCENTRATION"]})
    card["data_form"] = "REPORTED_PARAMETER"
    cols = entry.get("columns", [])
    notes = (entry.get("notes") or "") + " " + entry.get("title", "")
    disp_type = _dispersion_type(notes)
    model_se = bool(re.search(r"standard errors? of the estimates|model|nonmem|population", notes.lower()))
    n_note = _n_from_notes(notes) or (lambda m: int(m.group(1)) if m else None)(re.search(r"\(\s*n\s*=\s*(\d+)\s*\)", notes))
    params = []
    dose_col = next((c["id"] for c in cols if c.get("meaning") == "DOSE" or "dose" in str(c.get("header", "")).lower()), None)
    card["reported_dose_unit"] = next((c.get("unit") for c in cols if c["id"] == dose_col), None)
    card["reported_analyte"] = (entry.get("metadata") or {}).get("analyte")
    card["reported_formulation"] = (entry.get("metadata") or {}).get("formulation")
    measure_col = next((c["id"] for c in cols if re.search(r"measure|parameter", str(c.get("header", "")).lower())), None)
    value_cols = [c for c in cols if c.get("meaning") == "PARAMETER_VALUE"]
    disp_col = next((c["id"] for c in cols if c.get("meaning") in ("SUMMARY_STATISTIC", "SD", "SE", "DISPERSION")), None)
    unit_col = next((c["id"] for c in cols if str(c.get("header", "")).lower() == "unit"), None)
    for r in entry.get("records", []):
        if measure_col and value_cols:   # long layout: one row per parameter
            name = _param_name(r.get(measure_col))
            if not name:
                continue
            v, sd = _value_pm(r.get(value_cols[0]["id"]), r.get(disp_col) if disp_col else None)
            if v is None:
                continue
            params.append({"param": name, "label": str(r.get(measure_col)), "value": v, "dispersion": sd,
                           "unit": r.get(unit_col) if unit_col else value_cols[0].get("unit"),
                           "dose": _num(r.get(dose_col)) if dose_col else card["dose_mg_per_kg"], "record_id": r.get("record_id")})
        else:                             # wide layout: one row per dose, one column per parameter
            dose = _num(r.get(dose_col)) if dose_col else card["dose_mg_per_kg"]
            for c in cols:
                if c["id"] == dose_col:
                    continue
                name = _param_name(c.get("header"))
                if not name:
                    continue
                v, sd = _value_pm(r.get(c["id"]))
                if v is None:
                    continue
                n = re.search(r"n\s*=\s*(\d+)", str(c.get("header", "")))
                params.append({"param": name, "label": c.get("header"), "value": v, "dispersion": sd,
                               "unit": c.get("unit"), "dose": dose, "record_id": r.get("record_id"),
                               "n": int(n.group(1)) if n else None})
    for p in params:
        p.setdefault("n", None)
        if p.get("unit") in (None, "", "NOT_FOUND"):
            m = re.search(r"\(([^()]*)\)\s*$", str(p.get("label", "")))
            p["unit"] = m.group(1) if m and m.group(1).strip() not in ("%",) else ("%" if m else None)
        if p["n"] is None and n_note:
            p["n"] = n_note; p["n_from"] = "source text"
        p["dispersion_type"] = disp_type if p["dispersion"] is not None else "none"
        p["sd_kind"] = "MODEL_SE" if model_se else ("BETWEEN_ANIMAL_SD" if disp_type == "SD" else "UNKNOWN")
        p["definition"] = _definition(p)
        p["source"] = f"{card['study']} · {card['title']}"
    return card, params


def _definition(p):
    lab = str(p.get("label", ""))
    if p["param"] == "AUC":
        m = re.search(r"(0\s*[-–_]\s*(?:\d+\s*h|t|inf|∞|τ|tau)\w*)", lab, re.I)
        return f"AUC interval {m.group(1) if m else 'not stated'}; NCA or model not stated; extrapolation not stated"
    if p["param"] == "F":
        return "source-reported F (AUC_EV/AUC_IV as defined by the source)"
    return "source-reported value; method not stated"


def reported_analysis(card, params, iv_refs=(), linearity=None):
    """A0.12. iv_refs: same-study IV references [{dose, dose_basis, dataset_id}];
    linearity: 'POINTS_TO_NONLINEARITY' / 'NO_SIGN' / None from item 19 of the same study."""
    res = {"dataset_id": card["dataset_id"], "params": params}
    aucs = sorted([p for p in params if p["param"] == "AUC" and p["dose"]], key=lambda p: p["dose"])
    defs = {p["definition"] for p in aucs}
    if len({p["dose"] for p in aucs}) >= 2 and len(defs) == 1:
        lo, hi = aucs[0], aucs[-1]
        summary_restrictions = _independence_restrictions([(card,)])
        unresolved = _dependence_unresolved([(card,)])
        if summary_restrictions:
            res["t3_reason"] = "; ".join(summary_restrictions)
        elif all(p["dispersion"] is not None and p["n"] and p["n"] > 1 for p in (lo, hi)):
            sd_unsure = any(p["sd_kind"] != "BETWEEN_ANIMAL_SD" for p in (lo, hi)) or any(p.get("n_from") for p in (lo, hi))
            sens = sd_unsure or bool(unresolved)
            res["t3"] = t3_group_sd({"auc": lo["value"], "sd": lo["dispersion"], "n": lo["n"], "dose": lo["dose"]},
                                    {"auc": hi["value"], "sd": hi["dispersion"], "n": hi["n"], "dose": hi["dose"]}, sensitivity=sens,
                                    equivalence_margin=card.get("dose_proportionality_equivalence_margin"))
            if sens:
                res["t3"]["sensitivity_reason"] = "; ".join(
                    (["SD type uncertain (may be a model SE or derived from the mean curve), or n taken from animals per time point"] if sd_unsure else [])
                    + unresolved)
            if unresolved:
                res["t3"]["t3_flags"].append("SAMPLING_DEPENDENCE_UNRESOLVED")
        else:
            res["t3_reason"] = "AUC lacks SD or n: description only (E5)"
    fs = [p for p in params if p["param"] == "F"]
    if card.get("dose_proportionality_auc"):
        animal = _bound_animal_auc(card["dose_proportionality_auc"], [card], [p["dose"] for p in aucs])
        res["animal_auc"] = animal
        if animal.get("status") == "ASSESSED":
            res["t3"] = animal
    if fs:
        f = fs[0]["value"]; f = f / 100 if f > 1.5 else f
        flags = ["F_ABOVE_ONE"] if f > 1.0 else []
        ivd = [r for r in iv_refs if r.get("dose")]
        checks = {"same_study_iv": [r["dataset_id"] for r in iv_refs] or "no same-study IV"}
        if ivd and card["dose_mg_per_kg"] and any(abs(r["dose"] - card["dose_mg_per_kg"]) > 1e-9 for r in ivd):
            flags.append("DOSE_MISMATCH")
            flags.append("NONLINEAR_DOSE_MISMATCH" if linearity == "POINTS_TO_NONLINEARITY" else "LINEARITY_UNTESTED")
            checks["doses"] = f"EV {card['dose_mg_per_kg']:g} mg/kg, IV " + ", ".join(f"{r['dose']:g}" for r in ivd) + " mg/kg"
        bases = {str(r.get("dose_basis")) for r in ivd} | {str(card["dose_basis"])}
        checks["dose_basis"] = "consistent" if len(bases) == 1 and "NOT_FOUND" not in bases else "not confirmed (" + ", ".join(sorted(bases)) + ")"
        res["f"] = {"f_status": "SOURCE_REPORTED", "value": f, "flags": flags, "checks": checks,
                    "definition": fs[0]["definition"]}
    return res


# ---------------------------------------------------------------- T3p: per-time ln ratios with Holm (A0.10, r4.1)

T3P_TIME_DEV = COMMON.T3P_TIME_DEV
T3P_ALPHA = COMMON.T3P_ALPHA
# r4.4 item 19 (2026-11-24): times within DOSE_TIME_ABS count as aligned; any larger offset needs a timing-error bound (below)
# before the time enters the formal family, otherwise it is read as sensitivity only


_t3p_neighbour_slopes = COMMON._t3p_neighbour_slopes


_sourced_time_bound = COMMON._sourced_time_bound


_t3p_offset_bound = COMMON._t3p_offset_bound


_p_two_sided = COMMON._p_two_sided


holm = COMMON.holm


_tp_summary = COMMON._tp_summary


t3p_series = COMMON.t3p_series


# ---------------------------------------------------------------- orchestration

# The nine questions of the review guide (GUIDE), in its order. The computation below still builds the r4.3 rows
# (onset, input speed, excluded combinations, second rise, tail, extent, dose, conditions, individuals); _guide_rows()
# turns them into these nine rows, and GUIDE_Q says where each r4.3 row goes.
QUESTIONS = [
    (1, "Onset and peak sampling", "By when had drug appeared, and did sampling capture the peak?"),
    (2, "Within-animal trough", "Did the same animal's concentration fall and rise again?"),
    (3, "Half-life and window choice", "How much does the apparent half-life depend on the samples used?"),
    (4, "Immediate non-increasing input", "Is the early rise compatible with input that starts immediately and never speeds up?"),
    (5, "Flip-flop kinetics", "Does the terminal decline suggest flip-flop kinetics?"),
    (6, "Systemic bioavailability", "How much parent drug reached the circulation?"),
    (7, "Dose proportionality", "Do the curves scale with dose?"),
    (8, "Shared one-compartment disposition", "Can the two routes share one-compartment disposition?"),
    (9, "One multiplier between conditions", "Could one multiplier explain the difference between conditions?"),
]
GUIDE_Q = {1: 1, 2: 1, 3: 4, 4: 2, 5: 5, 6: 6, 7: 7, 8: 9, 9: 2}   # r4.3 row -> review-guide question (rows 3 and 8 of the guide are built from the tail and T4 results)
_QFILE = {2: "1b", 3: 4, 4: 2, 8: 9, 9: "2b"}                      # Q<n>_<study>.png carries the guide number; the second part of a merged row gets "b"


def _study_key(card):
    return card.get("absorption_scope_id", card["study"])


def _board_key(board):
    return board.get("scope_id", board["study"])


def _known(value):
    """A12: a study or species that is not reported never matches anything, including another unreported one."""
    text = str(value if value is not None else "").strip()
    return bool(text) and text.upper() not in ("NOT_FOUND", "NOT REPORTED", "UNKNOWN", "NONE")


def _comparable_scope(a, b):
    """Same scope tuple and a reported study and species (A12)."""
    return _scope_tuple(a) == _scope_tuple(b) and _known(a.get("study")) and _known(a.get("species"))


def _scope_tuple(card):
    # Dose is deliberately absent: comparable doses belong in Q7 together.
    # Conditions and routes remain comparable within a regimen (Q8); an explicit
    # experimental arm/cohort, when supplied, prevents unrelated arms pooling.
    occasion = card.get("occasion", "NOT_FOUND")
    text = str(card.get("dosing_regimen", ""))
    regimen = "SINGLE_DOSE" if card.get("single_dose") or re.search(r"day\s*1\s*of\s*1\b", text, re.I) else occasion
    if regimen != "SINGLE_DOSE":
        regimen = str(card.get("dosing_regimen", "NOT_FOUND"))
        regimen = re.sub(r"\d+(?:\.\d+)?\s*(?:mg|ug|µg|μg|g)\s*/\s*kg", "DOSE", regimen, flags=re.I)
        regimen = re.sub(r"\s+", " ", regimen).strip().lower()
    return (card["study"], str(card["species"]), str(regimen),
            str(card.get("experiment_arm") or ""), str(card.get("cohort") or ""))


def _assign_scopes(datasets, param_sets):
    cards = [x["card"] for x in list(datasets) + list(param_sets)]
    scopes = {}
    for c in cards:
        scopes.setdefault(c["study"], set()).add(_scope_tuple(c))
    safe_names = {}
    for study in scopes:
        safe_names.setdefault(_slug(study), set()).add(study)
    for c in cards:
        identity = _scope_identity(c)
        c["absorption_scope_key"] = identity
        c["absorption_scope_id"] = c["study"] if len(scopes[c["study"]]) == 1 and len(safe_names[_slug(c["study"])]) == 1 else identity


def _scope_identity(card):
    digest = hashlib.sha256(json.dumps(_scope_tuple(card), ensure_ascii=False).encode("utf-8")).hexdigest()[:12]
    return f"{card['study']}__{re.sub(r'[^A-Za-z0-9]+', '_', card['species'])}__{digest}"


def _scope_ivs(board, ivs):
    return [i for i in ivs if _known(board["study"]) and _known(board["species"]) and i["card"]["study"] == board["study"]
            and i["card"]["species"] == board["species"]
            and _scope_identity(i["card"]) == board.get("scope_key", _scope_identity(i["card"]))]


def _iv_observations(card, series):
    """Retain each observed IV column; labels alone never establish cross-route pairing."""
    if card["matrix_category"] != "PLASMA_SERUM_BLOOD":
        return []
    refs = []
    for s in series:
        c = _series_card(card, s, len(series))
        ref_id = c["reference_id"]
        refs.append({"card": c, "series_id": s["series_id"], "label": s["label"], "reference_id": ref_id,
                     "metrics": curve_metrics(s["points"], card["record_level"], total_signal_only="ENDOGENOUS_REVIEW_REQUIRED" in card.get("gates", []),
                                             digitized=bool(card.get("digitized")))
                     | {"auc_record": auc_record(s["points"], "IV", total_signal_only="ENDOGENOUS_REVIEW_REQUIRED" in card.get("gates", []))},
                     "points": s["points"],
                     "reference_scope": "DESCRIPTIVE_INDIVIDUAL_IV" if card["record_level"].startswith("INDIVIDUAL") else "GROUP_REFERENCE",
                     "pairing_status": "NOT_ESTABLISHED_FROM_COLUMN_LABEL" if card["record_level"].startswith("INDIVIDUAL") else "NOT_APPLICABLE"})
    return refs


_UNPAIRED_REASON = "cross-route individual identity, period order or washout not verified"


def _safe(text):
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(text))


def _iv_pair_allowed(ev_card, iv_card):
    if any("ENDOGENOUS_REVIEW_REQUIRED" in card.get("gates", []) for card in (ev_card, iv_card)):
        return False
    if not _comparable_scope(ev_card, iv_card):
        return False
    if ev_card["record_level"] == iv_card["record_level"] == "GROUP_MEAN":
        return True
    return (ev_card["record_level"] == iv_card["record_level"] == "INDIVIDUAL"
            and bool(ev_card.get("cross_route_subject_id"))
            and ev_card.get("cross_route_subject_id") == iv_card.get("cross_route_subject_id")
            and all(c.get(k) is True for c in (ev_card, iv_card)
                    for k in ("cross_route_identity_verified", "washout_verified", "occasion_compatibility_verified")))


def terminal_after_last_dose(series):
    """Multiple dosing: the A0.7 window rules applied to the samples after the LAST dose (from its peak on). Used only for the
    group-level flip-flop hint; Absorption's own readings stay on the first dosing interval."""
    ev = series.get("dose_events") or []
    pts = sorted((x["t"], x["c"]) for x in (series.get("_later_points") or series.get("points_after_next_dose") or [])
                 if x["status"] == "QUANTIFIED" and x.get("c") and x["c"] > 0 and len(ev) > 1 and x["t"] > ev[-1]["time_h"])
    if len(pts) < 4:
        return None
    imax = max(range(len(pts)), key=lambda i: pts[i][1])
    wins = []
    for k in range(imax + 1, len(pts) - 2):
        tw = np.array([t for t, _ in pts[k:]]); cw = np.array([c for _, c in pts[k:]])
        b, a0 = np.polyfit(tw, np.log(cw), 1)
        r = np.corrcoef(tw, np.log(cw))[0, 1] ** 2
        n = len(tw); adj = 1 - (1 - r) * (n - 1) / (n - 2)
        if b >= 0:
            continue
        th = math.log(2) / -b
        if (tw[-1] - tw[0]) / th >= SPAN_MIN and adj >= ADJ_R2_MIN:
            wins.append({"start": float(tw[0]), "n": n, "thalf": float(th), "adjR2_exact": float(adj)})
    if not wins:
        return None
    best = max(w["adjR2_exact"] for w in wins)
    return max((w for w in wins if best - w["adjR2_exact"] <= ADJ_R2_TIE + 1e-12), key=lambda w: (w["n"], w["adjR2_exact"]))


def group_flip_flop(ev_metrics, ev_card, iv_refs, ev_series=None):
    """George 2026-11-25: without within-animal pairs, a GROUP-LEVEL flip-flop reading (a hint) is given when the EV and IV curves
    come from the same study, the same species and the same stated assay: the median EV apparent t½ over the median IV terminal
    t½ (qualified windows only), graded as in R9. Pairing with a verified washout stays required for F and for paired tests."""
    refs = [i for i in iv_refs if _comparable_scope(i["card"], ev_card)]
    a_ev = str(ev_card.get("assay") or "").strip().lower()
    refs = [i for i in refs if a_ev and str(i["card"].get("assay") or "").strip().lower() == a_ev]
    ev_th = [m["terminal_selected"]["thalf"] for m in ev_metrics if (m.get("terminal_selected") or {}).get("thalf")]
    basis_ev = "EV apparent t½"
    if not ev_th and ev_series:
        last = [terminal_after_last_dose(x) for x in ev_series]
        ev_th = [w["thalf"] for w in last if w]
        basis_ev = "EV apparent t½ after the last dose"
    iv_th = []
    for i in refs:
        w, _ = _qualified_iv_windows(i["metrics"])
        if w:
            iv_th.append(max(w, key=lambda x: (x["n"], x.get("adjR2_exact", 0)))["thalf"])
    if not ev_th or not iv_th:
        return None
    e, v = float(np.median(ev_th)), float(np.median(iv_th))
    reading = FF_READING[hl_grade(e / v)]
    return {"basis": "group-level, unpaired (hint)", "ev_thalf_median_h": e, "ev_thalf_range_h": [min(ev_th), max(ev_th)], "n_ev": len(ev_th),
            "iv_thalf_median_h": v, "iv_thalf_range_h": [min(iv_th), max(iv_th)], "n_iv": len(iv_th), "ratio": e / v,
            "flip_flop_reading": reading,
            "ev_basis": basis_ev,
            "text": (f"Group-level, unpaired (hint): median {basis_ev} {_g(e)} h (n {len(ev_th)}) against median IV terminal t½ {_g(v)} h "
                     f"(n {len(iv_th)}), ratio {_ratio_txt(e / v)}: {FF_TEXT.get(reading, reading)}. Same study, species and assay; not paired "
                     "within animals, so F and paired tests are not computed.")}


def _same_study_ivs(ivs, ds):
    return [i for i in ivs if any(_comparable_scope(i["card"], d["card"]) for d in ds)]


def _cross_route_subjects(ivs, ds):
    """Subjects with an EV curve in ds and an IV curve of the same study: (both, ev subjects, iv subjects)."""
    ev = {s.get("subject_id") for d in ds for s in d["series"] if s.get("subject_id")}
    iv = {i["card"].get("cross_route_subject_id") for i in _same_study_ivs(ivs, ds) if i["card"].get("cross_route_subject_id")}
    return ev & iv, ev, iv


def _iv_unpaired_text(ivs, ds):
    # A2: animals with a formed within-animal EV/IV pair are not "unpaired"; only the remaining IV curves are described here
    paired = {r.get("subject_id") for d in ds for r in d.get("iv_pairs") or [] if r.get("subject_id")}
    refs = [i for i in _same_study_ivs(ivs, ds) if i["card"].get("cross_route_subject_id") not in paired or not paired]
    n = len(refs)
    if not refs:
        return ""
    both, ev, iv = _cross_route_subjects(ivs, ds)
    both, ev, iv = both - paired, ev - paired, iv - paired
    head = f"{n} individual IV curve{'s' if n != 1 else ''} from this study and species retained descriptively"
    if both:
        return (f"{head}; {len(both)} animal{'s' if len(both) != 1 else ''} also have an EV curve here (same subject id), but washout, "
                "period order or occasion compatibility is not stated for {'them' if len(both) != 1 else 'it'}, so no paired EV/IV test or F is computed."
                ).replace("{'them' if len(both) != 1 else 'it'}", "them" if len(both) != 1 else "it")
    if ev and iv:
        return (f"{head}; they come from other animals than the EV curves (parallel groups), so no paired EV/IV test or F is computed "
                "(T4 needs individual pairs or a stated common-k assumption).")
    return f"{head}; cross-route subject identity, period order and washout are not verified, so no paired EV/IV test or F is computed."




def build(root):
    root = Path(root)
    tables = json.loads((root / "source_tables.json").read_text(encoding="utf-8-sig"))
    config_path = root / "absorption_config.json"
    evidence = (json.loads(config_path.read_text(encoding="utf-8-sig")).get("modeling_evidence", {})
                if config_path.is_file() else {})
    unknown = set(evidence) - {t["dataset_id"] for t in tables}
    if unknown:
        raise ValueError(f"Unmatched modeling evidence dataset IDs: {sorted(unknown)}")
    # the same tables in any order give the same pages: tables by dataset id, records by source row when every record has one
    tables = sorted(tables, key=lambda e: str(e.get("dataset_id", "")))
    for e in tables:
        rs = e.get("records")
        if isinstance(rs, list) and rs and all(isinstance(r.get("source_row"), (int, float)) for r in rs):
            e["records"] = sorted(rs, key=lambda r: r["source_row"])
    dose_report = {}
    p = root / "dose_normalization_assessment.json"
    if p.exists():
        dose_report = json.loads(p.read_text(encoding="utf-8-sig"))
    stability = _hstability(tables, dose_report)  # leave-one-sample-out rebuilds, before any figure of this run is collected
    out = root / "absorption"
    out.mkdir(exist_ok=True)
    datasets, ivs = [], []
    # M1 (2026-11-24): the IV window uses the dosing clock and precision settings of the run configuration that Distribution reads
    dcfg_path = root / "distribution_config.json"
    win_cfg = {k: v for k, v in (json.loads(dcfg_path.read_text(encoding="utf-8-sig")) if dcfg_path.is_file() else {}).items()
               if k in ("iv_mode", "noise_by_dataset")}
    reported = [e["dataset_id"] for e in tables if e.get("role") == "REPORTED_PARAMETERS" and e.get("metadata", {}).get("route_class") == "EV"]
    param_sets, iv_param_refs = [], []
    for entry in tables:
        if entry.get("role") == "REPORTED_PARAMETERS":
            rc = entry.get("metadata", {}).get("route_class")
            pc, pp = reported_parameters(entry)
            if rc == "EV" and pp:
                param_sets.append({"card": pc, "params": pp})
            elif rc == "IV":
                iv_param_refs.append({"dataset_id": pc["dataset_id"], "study": pc["study"], "species": pc["species"],
                                      "dose": pc["dose_mg_per_kg"], "dose_basis": pc["dose_basis"], "params": pp, "scope_key": _scope_identity(pc)})
            continue
        if entry.get("role") != "PK_OBSERVATIONS":
            continue
        card, series = extract(entry)
        if not series:
            continue
        if card["route_class"] == "IV":
            refs = _iv_observations(card, series)
            for ref, s_ in zip(refs, [s_ for s_ in series] if refs else []):
                ref["metrics"]["iv_window"] = COMMON.iv_window_for_entry(entry, s_["points"], win_cfg, s_.get("column"))   # M1: shared record
            ivs.extend(refs)
            for ref in refs:
                c = ref["card"]
                iv_param_refs.append({"dataset_id": c["dataset_id"], "study": c["study"], "species": c["species"],
                                      "dose": c["dose_mg_per_kg"], "dose_basis": c["dose_basis"], "params": [], "scope_key": _scope_identity(c)})
            continue
        if card["route_class"] != "EV":
            continue
        source_guidance = evidence.get(card["dataset_id"], {})
        if source_guidance:
            card["modeling_evidence"] = dict(source_guidance)
            dose_table = source_guidance.get("reported_oral_doses")
            if dose_table:
                if card["route_detail"] != "PO":
                    raise ValueError("Oral literature series attached to a different route")
                card["modeling_evidence"]["comparator"] = {
                    "text": _reported_oral_summary(dose_table), "source": dose_table["source"], "location": dose_table["location"]}
        ds = {"card": card, "series": [], "figures": {}}
        for s in series:
            m = curve_metrics(s["points"], card["record_level"], total_signal_only="ENDOGENOUS_REVIEW_REQUIRED" in card["gates"],
                              digitized=bool(card.get("digitized")))
            m["auc_record"] = auc_record(s["points"], card["route_class"], total_signal_only="ENDOGENOUS_REVIEW_REQUIRED" in card["gates"])
            ds["series"].append({"series_id": s["series_id"], "label": s["label"], "metrics": m, "points": s["points"],
                                 "dose": s["dose"], "dose_given": s.get("dose_given"), "dose_given_from": s.get("dose_given_from"),
                                 "dispersion_kind": s["dispersion_kind"], "subject_id": s.get("subject_id"),
                                 "occasion": s.get("occasion"), "pairing": s.get("pairing") or {},
                                 **({"dose_events": s["dose_events"], "first_interval_end_h": s["first_interval_end_h"],
                                     "_later_points": s.get("points_after_next_dose") or [],
                                     "n_quantified_after_next_dose": sum(1 for x in s.get("points_after_next_dose") or []
                                                                         if x["status"] == "QUANTIFIED" and x.get("c"))}
                                    if s.get("dose_events") else {})})
        if card["tests_allowed"] and not any("tmax" in s["metrics"] for s in ds["series"]):
            # Eligibility follows the actual retained points, including leave-one rebuilds.
            # Keep the sparse observations, but do not enter the question calculations
            # that require the three-point curve_metrics result.
            card["tests_allowed"] = False
            if any("duplicate" in s["metrics"].get("not_assessable_reason", "") for s in ds["series"]):
                card["gates"].append("UNRESOLVED_DUPLICATE_TIMES")
            else:
                card["gates"].append("INSUFFICIENT_QUANTIFIED_POINTS")
        datasets.append(ds)

    _assign_scopes(datasets, param_sets)

    def one(name, panel, w=5.6, h=3.7):
        return _figure(out, name, "", [panel], w, h)

    # T2 first (item 20): the test runs whenever its data precondition holds; a confirmed valley marks the dip on B1,
    # and the T2 layer is drawn per animal (T2 does not apply to group means)
    for ds in datasets:
        card = ds["card"]
        if not card["tests_allowed"] or card["series_kind"] == "DOSE_COLUMNS":
            continue
        for s in ds["series"]:
            if "tmax" not in s["metrics"]:
                continue
            r = t2_curve(s["points"])
            lab, flags = t2_label(r, card["record_level"], card,
                                  baseline_unresolved="DRUG_FREE_BASELINE_UNRESOLVED" in (s["metrics"].get("t1_flags") or []))
            s["t2"] = {k: v for k, v in r.items() if not k.startswith("_")} | {"t2_label": lab, "t2_flags": flags,
                                                                                "trigger": r["t2_margin"] is not None}
            limit = card.get("modeling_evidence", {}).get("low_concentration_sensitivity")
            if limit:
                if (limit["unit"] != card["unit"] or not math.isfinite(limit["value"]) or limit["value"] <= 0
                        or not limit.get("source")):
                    raise ValueError(f"Invalid source sensitivity or concentration unit for {card['dataset_id']}")
                q = [p for p in s["points"] if p["status"] == "QUANTIFIED" and p["t"] > 0 and p["c"] is not None and p["c"] > 0]
                kept = [p for p in q if p["c"] >= limit["value"]]
                trial = t2_curve(kept)
                half = curve_metrics(kept, card["record_level"]).get("terminal_selected") or {}
                s["t2"]["low_concentration_sensitivity"] = {
                    "retained": len(kept), "omitted": len(q) - len(kept), "evaluable": len(kept) >= 3,
                    "has_valley": bool(trial["valley"]) if len(kept) >= 3 else None, "thalf_h": half.get("thalf")}
            if r["t2_margin"] is not None:
                s["metrics"]["_valley"] = r["valley_idx"]
                s["_t2res"] = r

    # figures A and B, per curve; the individual layer (A1, B1) and A4 per dataset of single animals
    for ds in datasets:
        card = ds["card"]
        main = ds["series"]
        cid = card["dataset_id"]
        verified = card["record_level"] == "INDIVIDUAL"
        for s in main:
            m = s["metrics"]
            if "tmax" not in m:
                continue
            src = {"series_id": s["series_id"], "points": s["points"], "label": s["label"] if len(main) > 1 else "",
                   **{k: s[k] for k in ("dose_events", "_later_points", "dose_given", "dose", "iv_input") if k in s}}
            tag = f"{cid}_{_sid(s)}"
            if card["tests_allowed"]:
                s["A1"] = one(f"A1_{tag}.png", pA1(card, m, src))
                s["A1w"] = one(f"A1w_{tag}.png", pA1(card, m, src, marks=("tmax", "zero", "blq", "predose"), whole=True))
                # S13 rule 9 (George 2026-11-25): no test-construction figures (C/t intervals, dip triplets); their readings
                # are one plain sentence in the caption of the standard profile figures
                b1 = pB1(card, m, src)
                s["B1"] = one(f"B1_{tag}.png", b1, 6.0, 3.8)
                if s.get("_t2res") and card["record_level"] != "GROUP_MEAN":
                    s["T2"] = one(f"T2_{tag}.png", first_interval_note(pT2(card, src, s["_t2res"], s["t2"]["t2_label"], s["t2"]["t2_flags"]), src), 6.0, 3.8)
                if m["n_before_peak"] >= 2:
                    s["A3"] = one(f"A3_{tag}.png", pA3(card, m, src), 5.6, 3.4)
                if len([w for w in m["terminal_windows"] if _qualified(w)]) >= 2:
                    s["B2"] = one(f"B2_{tag}.png", pB2(card, m, src), 5.6, 3.4)
            elif card["series_kind"] == "DOSE_COLUMNS" or "ENDOGENOUS_REVIEW_REQUIRED" in card["gates"] or s is main[0]:
                s["A1w"] = one(f"A1w_{tag}.png", pA1(card, m, src, marks=("tmax", "zero", "blq", "predose"), whole=True))
                s["B1"] = one(f"B1_{tag}.png", pB1(card, m, src, marks=("blq",)), 6.0, 3.8)
        if card["series_kind"] == "INDIVIDUALS" and "ENDOGENOUS_REVIEW_REQUIRED" not in card["gates"]:
            sl = [s for s in main if "tmax" in s["metrics"]]
            if sl:
                for key, log in (("A1ind", False), ("B1ind", True)):
                    p = pInd(card, sl, verified, log=log)
                    if isinstance(p, list):
                        rows_n = -(-len(p) // 4)
                        ds[key] = _figure(out, f"{key}_{cid}.png", "", p, 12, 2.5 * rows_n + 0.2, ncol=4)
                    else:
                        ds[key] = one(f"{key}_{cid}.png", p, 6.4, 3.9)
            if len(sl) > 1:
                ds["A4"] = _figure(out, f"A4_{cid}.png", "", pA4(card, sl), 10.5, 3.6)

    # figure C (item 19): dose series at one study, species, route, matrix, record level and occasion
    groups = {}
    for ds in datasets:
        c = ds["card"]
        if not (c["dose_series_allowed"] and c["record_level"] == "GROUP_MEAN"):
            continue
        sers = ds["series"] if c["series_kind"] == "DOSE_COLUMNS" else ds["series"][:1]
        for s in sers:
            if s["dose"] and "tmax" in s["metrics"]:
                # A12: an unreported study or species groups only the dose columns of one table
                own = "" if _known(c["study"]) and _known(c["species"]) else c["dataset_id"]
                groups.setdefault((c["study"], c["species"], c["route_detail"], c["matrix_category"], c["record_level"], c["occasion"], _scope_tuple(c), c.get("condition", "not reported")) + ((own,) if own else ()), []).append((ds, s))
    dose_series_res = []
    for key, members in groups.items():
        doses = sorted({s["dose"] for _, s in members})
        if len(doses) < 2 or len(doses) != len(members):
            continue
        ids = sorted({d["card"]["dataset_id"] for d, _ in members})
        block = next((g for g in dose_report.get("groups", []) if set(ids) & set(g.get("dataset_ids", []))), None)
        block_info = {"group_id": block["group_id"], "status": block["status"], "execution_status": block.get("execution_status"),
                      "reason": block.get("reason", ""), "view_ids": list(block.get("selected_view_ids") or [])} if block else None
        res = dose_series([(d["card"], s["metrics"], s) for d, s in members], block_info)
        res["key"] = "_".join(re.sub(r"\W+", "", str(k)) for k in key[:3]) + "_" + hashlib.sha256(json.dumps(key, ensure_ascii=False).encode("utf8")).hexdigest()[:10]
        res["dataset_ids"] = ids; res["label"] = f"{key[0]} · {key[1]} · {key[2]}"
        res["scope_key"] = _scope_identity(members[0][0]["card"])
        res["condition"] = members[0][0]["card"].get("condition", "not reported")
        res["occasion"] = key[5]
        res["_card0"] = members[0][0]["card"]
        if res["status"] == "ASSESSED":
            k = res["key"]
            res["C1"] = _figure(out, f"C1_{k}.png", "", pC1(res, [(s["dose"], s["metrics"], d["card"]["unit"], s["points"]) for d, s in members]), 10.5, 3.8)
            res["C2"] = _figure(out, f"C2_{k}.png", "", pC2(res), 14, 3.8)
            res["trigger"] = ("POINTS_TO_NONLINEARITY" in (res["e6_label"], res["cmax_label"], res["e2_label"])
                              or res["t3_label"].startswith("EXCLUDED") or res["t3p"]["t3p_label"].startswith("EXCLUDED"))
            t3p = res["t3p"]
            if res["trigger"] and res.get("ci"):
                res["C2T3"] = one(f"C2T3_{k}.png", pT3(res), 6.0, 3.3)
            if res["trigger"] and t3p.get("t3p_times"):
                res["C3"] = one(f"C3_{k}.png", pC3(res), 7.0, 3.9)
            if not t3p.get("t3p_times"):
                res["C3d"] = one(f"C3d_{k}.png", pC3(res), 6.0, 3.6)
        dose_series_res.append(res)

    # figure F (A0.12 reported-parameter path; T3 by group SD; reported F)
    for ps in param_sets:
        c = ps["card"]
        lin = next((r["e6_label"] for r in dose_series_res if r.get("status") == "ASSESSED" and _known(c["study"]) and _known(c["species"]) and r.get("scope_key") == _scope_identity(c) and r.get("condition", "not reported") == c.get("condition", "not reported")), None)
        refs = [r for r in iv_param_refs if _known(c["study"]) and _known(c["species"]) and r.get("scope_key") == _scope_identity(c)]
        ana = reported_analysis(c, ps["params"], refs, lin)
        ps["analysis"] = {k: v for k, v in ana.items() if k != "params"}
        if any(p["dose"] for p in ps["params"]):
            pans = pF(c, ps["params"])
            if pans:
                ps["F"] = _figure(out, f"F_{c['dataset_id']}.png", "", pans, _w(len(pans), 3.9), 3.5)
        t3 = ana.get("t3")
        if t3:
            ps["C2T3"] = one(f"C2T3_params_{c['dataset_id']}.png", pT3(t3), 6.0, 3.3)

    # figure D (items 18 and 22): EV against a same-study, same-species IV curve
    ev_iv_res = []
    for ds in datasets:
        c = ds["card"]
        if not c["tests_allowed"] or "tmax" not in ds["series"][0]["metrics"] or len(ds["series"]) != 1:
            continue
        if c["record_level"] == "INDIVIDUAL" and ds["series"][0].get("subject_id"):
            continue  # one identified animal: paired (or described) with the other animals below
        for iv in ivs:
            ic = iv["card"]
            if not _iv_pair_allowed(c, ic):
                continue
            if _comparable_scope(ic, c) and "tmax" in iv["metrics"]:
                res = ev_iv(c, ds["series"][0]["metrics"], ic, iv["metrics"])
                res["key"] = f"{c['dataset_id']}_vs_{ic['dataset_id']}"
                em, im = ds["series"][0]["metrics"], iv["metrics"]
                ev_th = (em.get("terminal_selected") or {}).get("thalf"); iv_th = (im.get("terminal_selected") or {}).get("thalf")
                res["trigger"] = ((em.get("split") or {}).get("class") == "DECLINE_FLATTENS") or bool(ev_th and iv_th and ev_th > iv_th)
                res["tail"] = tail_compare(em, im)
                res["trigger_text"] = (f"EV apparent t½ {_th_text(ev_th)}, IV {_th_text(iv_th)}; EV decline "
                                       + ((em.get('split') or {}).get('class') or "not classified (fewer than 4 samples after the peak)"))
                if res.get("q") and res["trigger"]:
                    res["D1"] = _figure(out, f"D1_{res['key']}.png", "", pD1(c, em, ic, im, res), 10.5, 3.8)
                if res.get("window_auc_ratio") is not None:
                    res["D2"] = one(f"D2_{res['key']}.png", pD2(c, em, ic, im, res), 6.0, 3.7)
                ev_iv_res.append(res)

    # figure D for individual columns: within-animal EV/IV pairs (subject_id and stated washout), else a description
    for ds in datasets:
        c = ds["card"]
        if not c["tests_allowed"] or c["dataset_id"] in {r["ev"] for r in ev_iv_res if r.get("t4_reason") != _UNPAIRED_REASON}:
            continue
        sl = [s for s in ds["series"] if "tmax" in s["metrics"]]
        refs = [i for i in ivs if _comparable_scope(i["card"], c) and "tmax" in i["metrics"]]
        if not sl or not refs:
            continue
        pairs = []
        if c["record_level"] == "INDIVIDUAL":
            for s in sl:
                ec = _series_card(c, s, len(ds["series"]))
                for iv in refs:
                    ic = iv["card"]
                    if s.get("subject_id") and ic.get("cross_route_subject_id") == s["subject_id"] and _iv_pair_allowed(ec, ic):
                        res = ev_iv(ec, s["metrics"], ic, iv["metrics"])
                        res.update(key=f"{c['dataset_id']}_{_sid(s)}_vs_{ic['dataset_id']}", subject_id=s["subject_id"],
                                   ev_dataset=c["dataset_id"], ev_series=s["series_id"], tail=tail_compare(s["metrics"], iv["metrics"]),
                                   _ev_card=ec, _em=s["metrics"], _iv_card=ic, _im=iv["metrics"])
                        if res.get("q"):
                            res["D1"] = _figure(out, f"D1_{_safe(res['key'])}.png", "", pD1(ec, s["metrics"], ic, iv["metrics"], res), 10.5, 3.8)
                        if res.get("window_auc_ratio") is not None:
                            res["D2"] = one(f"D2_{_safe(res['key'])}.png", pD2(ec, s["metrics"], ic, iv["metrics"], res), 6.0, 3.7)
                        pairs.append(res)
        if pairs:
            ds["iv_pairs"] = pairs
            n = len(pairs)
            ds["D1a"] = _figure(out, f"D1a_{c['dataset_id']}.png", "", pD1a(pairs), 4.2 * min(n, 3), 3.4 * -(-n // 3) + 0.2, ncol=min(n, 3))
        unpaired = [s for s in sl if s["series_id"] not in {r["ev_series"] for r in pairs}]
        if unpaired:
            ds["D1d_reason"] = _iv_unpaired_text(refs, [dict(ds, series=unpaired)])
            gff = group_flip_flop([x["metrics"] for x in unpaired], c, refs, unpaired)
            if gff:
                ds["group_flip_flop"] = gff
                ds["D1d_reason"] = (ds["D1d_reason"] + " " if ds["D1d_reason"] else "") + gff["text"]
            ds["D1d"] = _figure(out, f"D1d_{c['dataset_id']}.png", "", pD1d(c, unpaired, refs, ds["D1d_reason"]), 11.0, 4.1)
            ds["_D1d_args"] = (c, unpaired, refs, ds["D1d_reason"])

    # figure E (item 23): two curves of one study, species and matrix that differ by route or condition
    cond_res = []
    cands = [ds for ds in datasets if ds["card"]["tests_allowed"] and len(ds["series"]) == 1 and "tmax" in ds["series"][0]["metrics"]]
    for a, b in itertools.combinations(cands, 2):
        ca, cb = a["card"], b["card"]
        if not _comparable_scope(ca, cb) or ca["matrix_category"] != cb["matrix_category"]:
            continue
        if ca["route_detail"] == cb["route_detail"] and ca["dose_mg_per_kg"] != cb["dose_mg_per_kg"]:
            continue  # dose-only difference belongs to item 19
        ref, test = (b, a) if cb["route_detail"] == "SC" else (a, b)
        tm, rm = test["series"][0]["metrics"], ref["series"][0]["metrics"]
        res = condition_pair(test["card"], tm, ref["card"], rm)
        res["key"] = f"{test['card']['dataset_id']}_vs_{ref['card']['dataset_id']}"
        if res.get("intervals"):
            res["E1"] = _figure(out, f"E1_{res['key']}.png", "", [pE1(test["card"], tm, ref["card"], rm, log=False),
                                                                  pE1(test["card"], tm, ref["card"], rm, log=True)], 10.5, 3.7)
            res["E2"] = one(f"E2_{res['key']}.png", pE2(res), 6.0, 3.7)
            overlay = pE3(test["card"], tm, ref["card"], rm)
            if overlay is not None:
                res["E3"] = one(f"E3_{res['key']}.png", overlay, 6.0, 3.7)
        cond_res.append(res)

    boards = status_boards(datasets, dose_series_res, ev_iv_res, cond_res, param_sets, ivs, out=out)
    hypotheses(boards, datasets, param_sets, dose_series_res, ev_iv_res, cond_res, ivs, out,  # after the nine questions; context file not shown
               stability=stability, write=not _QUICK[0])
    attach_plain(boards, datasets, ivs)
    if _QUICK[0]:
        _SPECS.clear()
        return {"status_boards": boards, "iv_reference_count": len(ivs)}
    result = {"version": VERSION, "rules": RULES, "guide": guide_meta(), "tolerance_rel": TOL, "span_ratio_min": SPAN_MIN,
              "datasets": [{"card": d["card"], "series": [{k: v for k, v in s.items() if k != "points" and not k.startswith("_")}
                                                          | {"metrics": {k: v for k, v in s["metrics"].items() if not k.startswith("_")}} for s in d["series"]],
                            "A1ind": d.get("A1ind"), "B1ind": d.get("B1ind"), "A4": d.get("A4"), "D1a": d.get("D1a"),
                            "D1d": d.get("D1d"), "D1d_reason": d.get("D1d_reason"), "group_flip_flop": d.get("group_flip_flop"),
                            "iv_pairs": [{k: v for k, v in r.items() if not k.startswith("_")} for r in d.get("iv_pairs") or []]}
                           for d in datasets],
              "reported_parameter_ev_datasets": reported,
              "reported_parameters": [{"card": p["card"], "params": p["params"], "analysis": p.get("analysis"),
                                       "F": p.get("F"), "C2T3": p.get("C2T3")} for p in param_sets],
              "iv_references": [{k: v for k, v in i.items() if k != "metrics"}
                                | {"metrics": {k: v for k, v in i["metrics"].items() if not k.startswith("_")}} for i in ivs],
              "dose_series": dose_series_res, "ev_iv": ev_iv_res, "conditions": cond_res, "status_boards": boards,
              "hypothesis_files": {"context": "hypothesis_context.json", "review_template": "hypothesis_review.template.json", "reviews": "reviews/",
                                   "model_context": "model_context.txt"}}
    _eda_common().annotate_section("absorption", result, Path(root))
    _eda_common().separate_sensitivity_flags(result)   # R10: formal CANNOT_ASSESS keeps only its own reason
    (out / "absorption.json").write_text(json.dumps(result, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    _FIG_DIR[0] = out
    render_all(out)
    result["render"] = dict(_RENDER)
    portal = (root / "index.html").exists() and '<div class="categories">' in (root / "index.html").read_text(encoding="utf-8")
    pages, result["presentation"] = render_pages(result, datasets, param_sets, base=out, portal=portal, ivs=ivs)
    (out / "absorption.json").write_text(json.dumps(result, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    ctx = json.loads((out / "hypothesis_context.json").read_text(encoding="utf-8"))
    (out / "model_context.txt").write_text(model_context(result, ctx), encoding="utf-8")  # compact context for a downstream model
    for name, page_html in pages.items():
        (out / name).write_text(COMMON.reader_text(page_html), encoding="utf-8")
    return result


# ---------------------------------------------------------------- status board (9 questions)

def _rng(v):
    lo, hi = min(v), max(v)
    return f"{lo:.3g}" if abs(hi - lo) < 1e-9 else f"{lo:.3g}–{hi:.3g}"


ST_YES = COMMON.ST_YES
ST_PART = COMMON.ST_PART
ST_NO = COMMON.ST_NO
ST_NA = COMMON.ST_NA
ST_CODE = COMMON.ST_CODE


_RANK = {ST_YES: 3, ST_PART: 2, ST_NO: 1, ST_NA: 0}
_HOLD = set(COMMON.LIMITING_FLAGS)   # R6: the shared list


def _test_state(label, flags):
    if label in (None, "CANNOT_ASSESS", "NOT_ASSESSABLE", "NOT_ESTIMABLE"):
        return ST_NO
    return ST_PART if set(flags or []) & _HOLD else ST_YES


def _merge(rows, qn, new):
    """A0.11: a row takes the highest state among its parts; the other parts go into the text."""
    if qn not in rows:
        rows[qn] = new; return
    old = rows[qn]
    st = old[0] if _RANK[old[0]] >= _RANK[new[0]] else new[0]
    rows[qn] = (st, old[1] + "; " + new[1], old[2] + [f for f in new[2] if f not in old[2]])


def slope_diff_test(t1, c1, t2, c2):
    """Two-sided t test that two log-linear declines share one slope (pooled residual variance, n1 + n2 − 4 df; the residual SD
    has the reading tolerance TOL as its floor)."""
    fits = []
    for t, c in ((t1, c1), (t2, c2)):
        x, c = np.asarray(t, float), np.asarray(c, float)
        if len(x) < 2 or len(x) != len(c) or not np.all(np.isfinite(x)) or not np.all(np.isfinite(c)) or np.any(c <= 0):
            return None
        if float(np.sum((x - x.mean()) ** 2)) <= 1e-12:
            return None
        y = np.log(c)
        b, a = np.polyfit(x, y, 1)
        fits.append((float(b), float(np.sum((y - (a + b * x)) ** 2)), float(np.sum((x - x.mean()) ** 2)), len(x)))
    df = fits[0][3] + fits[1][3] - 4
    if df < 1 or min(f[2] for f in fits) <= 0:
        return None
    # pooled residual SD, never below the reading tolerance: a three-point window that happens to be straight proves nothing
    sd = max(math.sqrt((fits[0][1] + fits[1][1]) / df), math.log(1 + TOL))
    se = sd * math.sqrt(1 / fits[0][2] + 1 / fits[1][2])
    tv = (fits[0][0] - fits[1][0]) / se
    return {"slope_ev": fits[0][0], "slope_iv": fits[1][0], "se_diff": float(se), "df": df, "t": float(tv),
            "p": _p_t(tv, df), "n_ev": fits[0][3], "n_iv": fits[1][3], "residual_sd": float(sd),
            "sd_floor_applied": bool(math.sqrt((fits[0][1] + fits[1][1]) / df) < math.log(1 + TOL)),
            "p_is_nominal": True,
            "inference_scope": "selected time-point regression residuals; window selection and within-animal/time covariance are not propagated; not proof of flip-flop",
            "method": "difference of two log-linear slopes, pooled residual variance, two-sided t test"}


def tail_compare(em, im):
    """EV against IV apparent t½ over each curve's selected terminal window. SLOWER needs a ratio above the tolerance and a slope
    test that separates the two declines; a ratio within the tolerance is not a difference."""
    es, is_ = em.get("terminal_selected"), im.get("terminal_selected")
    if not (es and is_ and es.get("thalf") and is_.get("thalf")):
        return None
    ratio = es["thalf"] / is_["thalf"]
    te, ce = em["_t"][-es["n"]:], em["_c"][-es["n"]:]
    ti, ci = im["_t"][-is_["n"]:], im["_c"][-is_["n"]:]
    test = slope_diff_test(te, ce, ti, ci)
    if ratio > 1 + TOL:
        cls = "SLOWER" if (test and test["p"] < TAIL_ALPHA) else "SLOWER_NOT_SEPARATED"
    else:
        cls = "WITHIN_TOLERANCE" if ratio >= 1 / (1 + TOL) else "NOT_SLOWER"
    lo, hi = max(te[0], ti[0]), min(te[-1], ti[-1])
    e = [(t, c) for t, c in zip(te, ce) if lo <= t <= hi and c > 0 and math.isfinite(c)]
    i = [(t, c) for t, c in zip(ti, ci) if lo <= t <= hi and c > 0 and math.isfinite(c)]
    shared, reason = None, None
    if hi > lo and min(len({t for t, _ in e}), len({t for t, _ in i})) >= 3:
        et, ec = zip(*e)
        it, ic = zip(*i)
        shared = slope_diff_test(et, ec, it, ic)
        if not shared or not (shared["slope_ev"] < 0 and shared["slope_iv"] < 0):
            shared = None
            reason = "the overlap does not contain two nondegenerate declining log-linear fits"
    else:
        reason = "the selected terminal-window overlap has fewer than three real positive observations per route"
    corroborated = bool(shared and shared["slope_iv"] < shared["slope_ev"] < 0
                        and shared["slope_iv"] / shared["slope_ev"] >= FLIP_RATIO and shared["p"] < TAIL_ALPHA)
    ff = flip_flop_reading(em, im)
    grade = hl_grade(ratio)
    return {"ratio": float(ratio), "terminal_difference_grade": grade, "grade_cuts": list(HL_CUTS),
            "ratio_basis": "the two selected terminal windows (descriptive); the reading uses the qualified window pairs",
            **ff,
            "class": cls, "class_basis": "ORIGINAL_SELECTED_WINDOWS_NOMINAL", "test": test, "alpha": TAIL_ALPHA, "tolerance": TOL,
            "common_tail": {"window_h": [float(lo), float(hi)] if lo <= hi else [], "n_ev": len(e), "n_iv": len(i),
                            "status": "ASSESSED" if shared else "CANNOT_ASSESS", "reason": reason,
                            "ev_times_h": [float(p[0]) for p in e], "iv_times_h": [float(p[0]) for p in i],
                            "method": "refit real observed points within the intersection of the original selected windows; no interpolation or extrapolation",
                            "ratio": float(shared["slope_iv"] / shared["slope_ev"]) if shared else None,
                            "test": shared, "corroborates_slower_ev": corroborated},
            "ev_window_h": [float(te[0]), float(te[-1])], "iv_window_h": [float(ti[0]), float(ti[-1])]}


def _qualified_iv_windows(im):
    """R9 and M1 (2026-11-24): the IV side of the flip-flop comparison. A window qualifies only when the shared post-distribution
    window record is DETERMINED and the window lies inside it (same samples, same clock); the shared record itself, refitted on
    its own samples, counts when no Absorption window lies inside it."""
    rec = im.get("iv_window")
    if rec is None:          # a record built before M1 (or a summary record): no post-distribution check exists
        if "terminal_windows" in im:
            return [x for x in im["terminal_windows"] if x.get("thalf") and _qualified(x)], None
        return ([im["terminal_selected"]] if (im.get("terminal_selected") or {}).get("thalf") else []), None
    if rec.get("status") != "DETERMINED":
        return [], f"IV: no post-distribution window ({rec.get('reason') or 'not determined'})"
    shift = rec.get("shift_applied_h") or 0.0
    start = rec["start_h"] + shift - 1e-9          # on the Absorption clock (time after the start of dosing)
    w = [x for x in im.get("terminal_windows") or [] if x.get("thalf") and _qualified(x) and x.get("start") is not None and x["start"] >= start]
    why = "IV: the post-distribution window has fewer than three samples or no declining fit"
    if not w and rec.get("thalf_h") and rec.get("n", 0) >= 3:
        # 2026-11-24 review: the shared record passes the same eligibility as an Absorption window (span >= SPAN_MIN half-lives)
        if _window_eligible(rec["start_h"], rec["end_h"], rec["thalf_h"], rec["n"]):
            w = [{"thalf": rec["thalf_h"], "start": rec["start_h"] + shift, "end": rec["end_h"] + shift, "n": rec["n"], "source": rec["name"],
                  "span_ratio": (rec["end_h"] - rec["start_h"]) / rec["thalf_h"], "qualified": True}]
        else:
            why = (f"IV: the post-distribution window spans {(rec['end_h'] - rec['start_h']) / rec['thalf_h']:.3g} apparent half-lives "
                   f"(at least {SPAN_MIN:g} required, as for every terminal window)")
    return w, (None if w else why)


def flip_flop_reading(em, im):
    """Rule decision R9: grade every qualified window pair, map each grade to a reading, and record UNRESOLVED only when the
    qualified pairs give different readings. NOT_ASSESSABLE names the side that lacks a qualified window."""
    if "terminal_windows" in em:
        ev_w = [x for x in em["terminal_windows"] if x.get("thalf") and _qualified(x)]
    else:                    # a summary record that keeps only the selected window, which is chosen among qualified windows
        ev_w = [em["terminal_selected"]] if (em.get("terminal_selected") or {}).get("thalf") else []
    iv_w, iv_why = _qualified_iv_windows(im)
    missing = ([] if ev_w else ["EV: no qualified terminal window"]) + ([] if iv_w else [iv_why or "IV: no qualified terminal window"])
    if missing:
        return {"flip_flop_reading": "NOT_ASSESSABLE", "missing_side": missing, "ratio_range": None, "n_window_pairs": 0,
                "grades_over_window_pairs": [], "readings_over_window_pairs": [], "reading_text": "not assessable: " + "; ".join(missing),
                "iv_window": im.get("iv_window")}
    ratios = [a["thalf"] / b["thalf"] for a in ev_w for b in iv_w]
    grades = [g for g in HL_GRADES if g in {hl_grade(r) for r in ratios}]
    readings = sorted({FF_READING[g] for g in grades})
    lo, hi = float(min(ratios)), float(max(ratios))
    reading = readings[0] if len(readings) == 1 else "UNRESOLVED"
    rng = f"half-life ratio {_ratio_txt(lo)} to {_ratio_txt(hi)}" if _ratio_txt(lo) != _ratio_txt(hi) else f"half-life ratio {_ratio_txt(lo)}"
    text = (FF_TEXT.get(reading, reading) + f", {rng}" + (", degree of shallowing varies with the window" if reading == "ABSORPTION_INFLUENCED_CANDIDATE" and len(grades) > 1 else "")
            + f" ({len(ratios)} qualified window pair{'s' if len(ratios) != 1 else ''})")
    return {"flip_flop_reading": reading, "missing_side": [], "ratio_range": [lo, hi], "n_window_pairs": len(ratios),
            "grades_over_window_pairs": grades, "readings_over_window_pairs": readings, "reading_text": text,
            "iv_window": im.get("iv_window")}


FF_TEXT = {"EV_STEEPER_REVIEW": "EV steeper: review the windows and the comparability of the groups",
           "COMMON_TERMINAL_COMPATIBLE": "compatible with a common terminal process",
           "ABSORPTION_INFLUENCED_CANDIDATE": "absorption-influenced candidate",
           "UNRESOLVED": "unresolved: the qualified window pairs give different readings"}
# R9: these readings are not evidence against flip-flop
FF_NOT_AGAINST = ("UNRESOLVED", "NOT_ASSESSABLE", "INDIRECT_COMPARATOR")
FF_INDIRECT_LIMITS = {
    "LITERATURE_IV_TERMINAL": "another study, population, assay and dose range; indirect support at most",
    "OTHER_EV_CURVE": ("the faster EV decline bounds the disposition half-life from above only under shared, dose-linear disposition, "
                       "and may itself be absorption-limited; indirect support at most")}


def _ff_key(card):
    return tuple(str(card.get(k) or "").strip().casefold() for k in ("route_detail", "formulation", "condition"))


def ff_indirect_comparators(mets):
    """Rule decision R9: indirect comparators for an EV terminal decline, used only when no qualified same-study IV comparison
    exists (the direct NOT_ASSESSABLE is kept beside them). (1) A literature IV terminal half-life declared on the EV card as
    comparator_iv_terminal = {thalf_h, source, limits}; a value without a source is not listed. (2) Another EV curve of the same
    board, analyte and matrix, with a different route, formulation or condition and a qualified terminal window: the faster EV
    decline bounds the disposition half-life from above. Each comparator is listed with its source and limits and gives
    indirect support at most."""
    rows = [(c, d["card"], (m.get("terminal_selected") or {}).get("thalf")) for c, d, s, m in mets]
    rows = [r for r in rows if r[2]]
    out = []
    for c, card, th in rows:
        ref = card.get("comparator_iv_terminal") or {}
        try:
            rt = float(ref.get("thalf_h"))
        except (TypeError, ValueError):
            rt = None
        if rt and rt > 0 and str(ref.get("source") or "").strip():
            r = th / rt
            out.append({"kind": "LITERATURE_IV_TERMINAL", "ev": c, "ev_dataset": card["dataset_id"], "thalf_ev_h": th, "thalf_ref_h": rt,
                        "ratio": r, "grade": hl_grade(r), "reading": FF_READING[hl_grade(r)], "source": str(ref["source"]).strip(),
                        "limits": str(ref.get("limits") or FF_INDIRECT_LIMITS["LITERATURE_IV_TERMINAL"])})
        others = [o for o in rows if o[1] is not card and _ff_key(o[1]) != _ff_key(card) and o[2] < th
                  and str(o[1].get("analyte") or "").casefold() == str(card.get("analyte") or "").casefold()
                  and str(o[1].get("matrix") or "").casefold() == str(card.get("matrix") or "").casefold()]
        if others:
            oc, ocard, oth = min(others, key=lambda o: o[2])
            r = th / oth
            out.append({"kind": "OTHER_EV_CURVE", "ev": c, "ev_dataset": card["dataset_id"], "thalf_ev_h": th, "thalf_ref_h": oth,
                        "ratio": r, "grade": hl_grade(r), "reading": FF_READING[hl_grade(r)], "source": ocard["dataset_id"],
                        "limits": FF_INDIRECT_LIMITS["OTHER_EV_CURVE"]})
    return out


def _ff_indirect_hint(sig, comps):
    """R9: an indirect comparator gives indirect support at most (a HINT), and only for an absorption-influenced reading."""
    up = [x for x in comps if x["reading"] == "ABSORPTION_INFLUENCED_CANDIDATE"]
    if up:
        sig(_hsig("tail_slower_than_indirect", 5, HINT, "Indirect comparator only: " + ff_indirect_text(up) + ".",
                  "an EV decline slower than an indirect comparator", [["tail.absorption"], ["other.multicompartment"]],
                  sorted({x["ev_dataset"] for x in up} | {x["source"] for x in up if x["kind"] == "OTHER_EV_CURVE"})))


def _ff_word(reading):
    return {"ABSORPTION_INFLUENCED_CANDIDATE": "absorption-influenced candidate", "COMMON_TERMINAL_COMPATIBLE": "common terminal compatible",
            "EV_STEEPER_REVIEW": "EV steeper, review", "UNRESOLVED": "unresolved", "NOT_ASSESSABLE": "not assessable",
            "INDIRECT_COMPARATOR": "indirect comparator"}.get(reading, "not compared")


def ff_indirect_text(comps):
    return "; ".join(f"{x['ev']}: apparent t½ {x['thalf_ev_h']:.3g} h against {x['thalf_ref_h']:.3g} h "
                     + ("(literature IV terminal value, " if x["kind"] == "LITERATURE_IV_TERMINAL" else "(the faster EV decline of ")
                     + f"{x['source']}), ratio {_ratio_txt(x['ratio'])}, {FF_TEXT.get(x['reading'], x['reading'])}; limits: {x['limits']}" for x in comps)


def _matched_slow_tail(pair, tail):
    return bool(pair.get("dose_ev") and pair["dose_ev"] == pair.get("dose_iv") and tail.get("class") == "SLOWER"
                and tail["ratio"] >= FLIP_RATIO and tail.get("flip_flop_reading", "ABSORPTION_INFLUENCED_CANDIDATE") == "ABSORPTION_INFLUENCED_CANDIDATE"
                and (tail.get("common_tail") or {}).get("corroborates_slower_ev"))


def _tail_test_text(tc):
    t = (tc or {}).get("test")
    if not t:
        return "too few points in the two terminal windows for a slope test"
    return (f"original selected-window nominal slope test p = {t['p']:.2g}, {t['df']} time-point residual df: "
            + ("the selected declines differ" if t["p"] < tc["alpha"] else "the selected declines are not told apart"))


def _common_tail_text(tc):
    common = (tc or {}).get("common_tail") or {}
    if not common:
        return "Common-window sensitivity was not available."
    label = "–".join(f"{v:g}" for v in common.get("window_h", [])) or "no overlap"
    text = f"Common-window sensitivity ({label} h; {common['n_ev']} EV and {common['n_iv']} IV real points): "
    if common.get("test"):
        test = common["test"]
        return text + f"t½ ratio {common['ratio']:.2f}, nominal p = {test['p']:.2g}, {test['df']} time-point residual df; " + (
            "corroborates the slower EV tail under these regression assumptions." if common["corroborates_slower_ev"] else
            "does not corroborate a slower EV tail meeting both the ratio and p thresholds.")
    return text + common.get("reason", "not assessable") + "."


def _th_text(v):
    return f"{_f(v)} h" if v else "not readable (no qualified terminal window)"


def _t3_text(r):
    t3 = f"T3 = {r['t3_label']}" + "".join(" + " + f for f in r.get("t3_flags", []))
    if r.get("ci"):
        t3 += f" (R {r['R']:.2f}, 95 % CI {r['ci'][0]:.2f}–{r['ci'][1]:.2f}, {r.get('t3_data_level')})"
    else:
        t3 += f" ({r.get('t3_reason', '')})"
    p = r.get("t3p") or {}
    if p.get("t3p_times"):
        t3 += (f"; T3p = {p['t3p_label']}" + "".join(" + " + f for f in p["t3p_flags"])
               + f" ({p['t3p_dose_pair'][1]:g} vs {p['t3p_dose_pair'][0]:g} mg/kg, {len(p['t3p_times'])} time points tested, {sum(p['significant'])} significant after Holm"
               + _t3p_offset_words(p) + ")")
    elif p:
        t3 += f"; T3p = CANNOT_ASSESS ({p.get('reason', '')})"
    return t3


def _dose_param_sets(pss):
    """Choose a comparable reported dose series, never a mixture of conditions.

    All sets remain on the board and in the source evidence. The primary dose
    comparison uses the homogeneous group with the most distinct doses.
    """
    groups = {}
    for ps in pss:
        c = ps["card"]
        key = (_scope_tuple(c), str(c.get("condition", "not reported")).strip().lower(),
               c.get("route_detail"), c.get("matrix"), c.get("dose_basis"))
        groups.setdefault(key, []).append(ps)
    def rank(group):
        doses = {p.get("dose") for ps in group for p in ps["params"] if p.get("dose") is not None}
        return (-len(doses), tuple(sorted(ps["card"]["dataset_id"] for ps in group)))
    return min(groups.values(), key=rank) if groups else []


def _dose_param_condition(pss):
    values = sorted({str(ps["card"].get("condition", "not reported")) for ps in pss})
    return "Reported dose comparison condition: " + ", ".join(values) + "."


def _param_rows(pss):
    rows = {}
    ids = ", ".join(ps["card"]["dataset_id"] for ps in pss)
    for qn in (1, 3, 4):
        rows[qn] = (ST_NO, f"Reported parameters only ({ids}): this question needs concentration points (A0.12)", ["fig3f"])
    tm = [p for ps in pss for p in ps["params"] if p["param"] == "TMAX"]
    rows[2] = (ST_PART, f"Reported Tmax {_rng([p['value'] for p in tm])} {tm[0].get('unit') or ''} (description)", ["fig3f"]) if tm else (ST_NO, "Reported parameters only, no Tmax", ["fig3f"])
    th = [p for ps in pss for p in ps["params"] if p["param"] == "THALF"]
    rows[5] = (ST_PART, f"Reported EV t½ {_rng([p['value'] for p in th])}: description only, not a disposition t½ (missing: same-study IV)", ["fig3f"]) if th else (ST_NO, "Reported parameters only, no t½", [])
    fs = [ps["analysis"]["f"] for ps in pss if ps.get("analysis", {}).get("f")]
    rows[6] = (ST_PART, "f_status = SOURCE_REPORTED, F = " + ", ".join(f"{f['value']:.2f}" + (" (" + ", ".join(f["flags"]) + ")" if f["flags"] else "") for f in fs), ["fig3f"]) if fs else (ST_NO, "No reported F", [])
    pss = _dose_param_sets(pss)
    t3s = [ps["analysis"]["t3"] for ps in pss if ps.get("analysis", {}).get("t3")]
    if t3s:
        t = t3s[0]
        rows[7] = (_test_state(t["t3_label"], t["t3_flags"]),
                   f"T3 (group AUC mean, SD, n) = {t['t3_label']}" + "".join(" + " + f for f in t["t3_flags"]) + f"; {t['dose_pair'][1]:g} vs {t['dose_pair'][0]:g} mg/kg R = {t['R']:.2f}, 95 % CI {t['ci'][0]:.2f}–{t['ci'][1]:.2f}", ["fig7", "fig3f"])
    elif len({p["dose"] for ps in pss for p in ps["params"] if p["param"] in ("AUC", "CMAX") and p["dose"]}) >= 2:
        why = "; ".join(ps["analysis"].get("t3_reason", "") for ps in pss if ps["analysis"].get("t3_reason"))
        rows[7] = (ST_PART, "Reported parameters across doses (E5 description)" + (f"; {why}" if why else ""), ["fig3f"])
    else:
        rows[7] = (ST_NA, "Reported parameters at one dose only", [])
    rows[8] = (ST_NA, "No comparable conditions in the reported parameters", [])
    rows[9] = (ST_NO, "Reported parameters only (missing: individual curves)", [])
    return rows


# ---------------------------------------------------------------- evidence behind each board row
# Every board row (a conclusion) carries the rule that decided its state, the numbers it was decided from,
# and the datasets those numbers come from. The species pages show it under "Evidence" in each row;
# absorption.json keeps it under status_boards[*].evidence.

def _cid(d, s):
    """Curve name: dataset id, plus the column label when one dataset holds several curves."""
    return d["card"]["dataset_id"] + (f" · {s['label']}" if len(d["series"]) > 1 else "")


def _tbl(caption, head, rows):
    return {"caption": caption, "head": list(head), "rows": [["—" if v is None else str(v) for v in r] for r in rows]}


def _part(rule, tables=(), data=()):
    return {"rule": rule, "tables": [t for t in tables if t and t["rows"]], "data": sorted(set(data))}


def _pct(x):
    return "—" if x is None else f"{100 * x:.1f} %"


def _flags(label, flags):
    return (label or "—") + "".join(" + " + f for f in flags or [])


def _note_hit(notes, pattern):
    """The source sentence that matches pattern, quoted as evidence (or None)."""
    for s in re.split(r"(?<=\.)\s+|\n+", str(notes or "")):
        if re.search(pattern, s, re.I):
            return s.strip(" -")
    return None


def _iv_table(ivs, study, species):
    rows = [[i["card"]["dataset_id"], i["card"]["study"], i["card"]["species"], _dose_txt(i["card"]), i["card"]["matrix"],
             ("descriptive individual IV; cross-route pairing unverified" if i["card"]["record_level"].startswith("INDIVIDUAL") else "same study and species")
            if (i["card"]["study"], i["card"]["species"]) == (study, species) else "different study or species"]
            for i in ivs]
    return _tbl("IV curves in the source tables (plasma, serum or blood)", ("Dataset", "Study", "Species", "Dose", "Matrix", "Usable here"),
                rows or [["none", "", "", "", "", "no IV curve was extracted"]])


def _curve_attr_table(caption, curves):
    return _tbl(caption, ("Curve", "Route", "Dose (mg/kg)", "Matrix", "Data", "Occasion"),
                [[_cid(d, s), d["card"]["route_detail"], _f(s.get("dose") or d["card"]["dose_mg_per_kg"]), d["card"]["matrix"],
                  _data_level(d["card"]), d["card"].get("occasion")] for d, s in curves])


def _dose_series_parts(r):
    ids = r["dataset_ids"]
    T = r["window_end_h"]
    per_dose = _tbl(f"Each dose over the common window 0–{T:g} h", ("Curve", "Dose (mg/kg)", "Tmax (h)", "Cmax/D", f"AUC 0–{T:g} h / D",
                                                                     "Share of AUC in window", "Apparent t½ (h), range", "Decline"),
                    [[x["dataset_id"], _f(x["dose"]), _f(x["tmax"]), _f(x["cmax_d"]), _f(x["aucW_d"]), _pct(x["share_window"]),
                      (_f(x["thalf"]) + (f" ({_f(x['thalf_range'][0])}–{_f(x['thalf_range'][1])})" if x.get("thalf_range") else "")),
                      x.get("split_class")] for x in r["rows"]])
    rng = "; ".join(f"{x['dose']:g} mg/kg {_f(x['thalf_range'][0])}–{_f(x['thalf_range'][1])} h" for x in r["rows"] if x.get("thalf_range")) or "no window with span ratio ≥ 2"
    p = r.get("t3p") or {}
    t3 = (f"R {r['R']:.3g}, 95 % CI {r['ci'][0]:.3g}–{r['ci'][1]:.3g} ({r.get('t3_data_level')})" if r.get("ci") else r.get("t3_reason", ""))
    t3p = (f"{len(p['t3p_times'])} times tested, {sum(p.get('significant') or [])} significant after Holm" + _t3p_offset_words(p)
           if p.get("t3p_times") else p.get("reason", ""))
    lo, hi = r["doses"][0], r["doses"][-1]
    ratios = _tbl(f"Highest ({hi:g} mg/kg) against lowest ({lo:g} mg/kg) dose", ("Measure", "Value", "Rule", "Reading"), [
        ["E6 · AUC/D ratio over the window", f"{r['R_window']:.3g}", "Point estimate: no sign at 0.80–1.25, signal below 0.50 or above 2.00, otherwise inconclusive", r["e6_label"]],
        ["Cmax/D ratio", f"{r['cmax_d_ratio']:.3g}", "no sign if 0.5–2.0", r["cmax_label"]],
        ["E2 · apparent t½ across doses", rng, "points to nonlinearity only if the ranges do not overlap and t½ rises with dose", r["e2_label"]],
        ["Power model slope (ln AUC vs ln dose)", f"{r['b1']['auc_window']:.3g}", "1 means proportional; description only", "—"],
        ["T3 · AUC/D ratio with 95 % CI", t3, "excluded when the CI does not contain 1", _flags(r["t3_label"], r["t3_flags"])],
        ["T3p · ln(C/D) per time, Holm", t3p, "excluded when a time stays significant after Holm", _flags(p.get("t3p_label"), p.get("t3p_flags"))]])
    times = _tbl("Dose-normalized concentration per shared time (description)", ("Time (h)", f"(C/D) {hi:g} ÷ (C/D) {lo:g}", "Margin beyond ±5 %"),
                 [[_f(x["t"]), f"{x['ratio']:.3g}", _f(x["m_t3"])] for x in r["per_time"]])
    tests = []
    if p.get("t3p_times"):
        if any(not x.get("aligned", True) for x in p["t3p_ln_ratio_ci"]):
            # r4.4 item 19: both actual times and the timing-offset bound are shown; an offset time is tested for |ln ratio| beyond the bound
            tests.append(_tbl("T3p per time (sampling times differ between the doses)",
                              ("Time low dose (h)", "Time high dose (h)", "ln ratio", "95 % CI (unadjusted)", "Timing-offset bound (ln)", "Holm p", "Significant after Holm"),
                              [[_f(x["t_low"]), _f(x["t_high"]), f"{x['ln_ratio']:.3g}", f"{x['ci95'][0]:.3g} to {x['ci95'][1]:.3g}",
                                "aligned" if x.get("aligned") else ("none (sensitivity only)" if x.get("time_offset_bound_ln") is None else f"±{x['time_offset_bound_ln']:.3g}"),
                                f"{ph:.3g}", "yes" if sg else "no"]
                               for x, ph, sg in zip(p["t3p_ln_ratio_ci"], p["t3p_p_holm"], p["significant"])]))
        else:
            tests.append(_tbl("T3p per time", ("Time (h)", "ln ratio", "95 % CI (unadjusted)", "Holm p", "Significant after Holm"),
                              [[_f(x["t"]), f"{x['ln_ratio']:.3g}", f"{x['ci95'][0]:.3g} to {x['ci95'][1]:.3g}", f"{ph:.3g}", "yes" if sg else "no"]
                               for x, ph, sg in zip(p["t3p_ln_ratio_ci"], p["t3p_p_holm"], p["significant"])]))
    rule = (f"Curves of one study, route, matrix, record level and occasion are compared at the times all doses share, over 0–{T:g} h "
            "(trapezoids on observed points, no extrapolation). The descriptions E6, Cmax/D and E2 only point to nonlinearity; the tests T3 "
            "and T3p need SD and n at the sampled times. A row that only describes stays 'partly answerable'.")
    return _part(rule, [per_dose, ratios, times] + tests, ids)


def _param_evidence(pss):
    rows = [[ps["card"]["dataset_id"], ps["card"].get("condition", "not reported"), p.get("label") or p["param"], _f(p["value"]), p.get("unit"), _f(p.get("dispersion")),
             _f(p.get("dose")), p.get("n")] for ps in pss for p in ps["params"]]
    return _tbl("Reported parameters as printed in the source", ("Dataset", "Condition", "Parameter", "Value", "Unit", "SD", "Dose (mg/kg)", "n"), rows)


def board_evidence(study, ds, pss, dose_series_res, ev_iv_res, cond_res, ivs, rows):
    ev = {}
    add = ev.setdefault
    central = [d for d in ds if d["card"]["tests_allowed"]]
    curves = [(d, s) for d in central for s in d["series"] if "tmax" in s["metrics"]]
    ids = {d["card"]["dataset_id"] for d in ds}
    all_ids = [d["card"]["dataset_id"] for d in ds]
    if ds and not central:
        gate = _tbl("Test gates of each dataset", ("Dataset", "Matrix", "Matrix category", "Route", "Gates failed"),
                    [[d["card"]["dataset_id"], d["card"]["matrix"], d["card"]["matrix_category"], d["card"]["route_detail"],
                      ", ".join(d["card"]["gates"]) or "none"] for d in ds])
        part = _part("T1–T5 need an extravascular single first dose measured in the central compartment (plasma, serum or blood). "
                     "Every curve of this study fails at least one gate, so only the overview figure is drawn and no question can be answered.",
                     [gate], all_ids)
        for qn, *_ in QUESTIONS:
            add(qn, []).append(part)
        for r in dose_series_res:
            if set(r["dataset_ids"]) <= ids and r["status"] == "ASSESSED":
                ev[7] = [_dose_series_parts(r)]
    elif curves:
        unit = central[0]["card"]["unit"]
        cur_ids = sorted({d["card"]["dataset_id"] for d, _ in curves})
        # Q1 onset
        add(1, []).append(_part(
            "Time is measured from dosing. The table gives the source baseline for each profile. "
            "The first quantified postdose sample can bound a delay when its concentration is attributable to this dose.",
            [_tbl("First quantified sample of each curve", ("Curve", "Dose (mg/kg)", "First quantified sample (h)", f"C there ({unit})",
                                                            "% of Cmax", "Predose result", "Postdose BLQ samples before it", "Onset"),
                  [[_cid(d, s), _f(s.get("dose")), _f(m["first_t"]), _f(m["first_frac_cmax"] * m["cmax"]), _pct(m["first_frac_cmax"]),
                    _baseline_reading(s), sum(1 for p in s["points"] if p["status"] == "BLQ" and 0 < p["t"] < m["first_t"]), m["onset_status"]]
                   for d, s in curves for m in [s["metrics"]]])], cur_ids))
        # Q2 input speed
        add(2, []).append(_part(
            "Tmax and Cmax are the observed maximum (no fitting). A curve is KA_NOT_IDENTIFIABLE when fewer than 2 quantified samples "
            "precede Tmax, and LATE_FIRST_SAMPLE when the first sample is at or after Tmax/3. The row is 'answerable' only when every curve "
            "is a verified individual and none is KA_NOT_IDENTIFIABLE; otherwise it is a description ('partly answerable').",
            [_tbl("Rising limb of each curve", ("Curve", "Data", "Tmax (h)", f"Cmax ({unit})", "Samples before Tmax", f"Rise between samples ({unit}/h)", "Caveats"),
                  [[_cid(d, s), _data_level(d["card"]), _f(m["tmax"]), _f(m["cmax"]), m["n_before_peak"],
                    "; ".join(f"{i['t0']:.3g}–{i['t1']:.3g} h: {i['dcdt']:.3g}" for i in m["increments"]) or "none (first sample is the peak)",
                    ", ".join(m["caveats"]) or "none"] for d, s in curves for m in [s["metrics"]]])], cur_ids))
        # Q3 T1
        add(3, []).append(_part(
            "T1 (A0.10) tests M0: non-increasing input from dosing with linear mammillary disposition, under which C/t cannot increase. "
            "Each value is widened by ±5 % (L = 0.95·C, U = 1.05·C) and M_T1 = max over an earlier sample i and a later sample j of "
            "L_j/t_j − U_i/t_i. A positive margin shows a rise at the assumed tolerance. Point deletion checks whether one sample drives it. "
            "Formal exclusion requires a justified error bound. This analysis cannot establish lag or transit. "
            "The T2 part is shown under Q4.",
            [_tbl("T1 on each curve", ("Curve", f"M_T1 with ±5 % ({unit}/h)", "Same without the bound", "Samples giving the maximum (h)", "T1 result"),
                  [[_cid(d, s), _f(m["mt1"]), _f(m["mt1_exact"]), f"{m['mt1_witness'][0]:.3g} and {m['mt1_witness'][1]:.3g}",
                    _flags(m["t1_label"], m["t1_flags"])] for d, s in curves for m in [s["metrics"]]])], cur_ids))
        # Q4 T2
        t2rows = []
        for d, s in curves:
            t2, m = s.get("t2"), s["metrics"]
            if not t2:
                t2rows.append([_cid(d, s), _data_level(d["card"]), "not run (dose-column dataset)", None, None, None, None, m["dips_described"]])
                continue
            v = t2.get("valley")
            t2rows.append([_cid(d, s), _data_level(d["card"]), ", ".join(f"{x:.3g}" for x in v) if v else "no confirmed valley",
                           _f(t2.get("m_drop")), _f(t2.get("m_rise")), _f(t2.get("t2_margin")),
                           ("yes" if t2.get("robust") else "no") if v else None, _flags(t2["t2_label"], t2["t2_flags"])])
        add(4, []).append(_part(
            "T2 (A0.10) looks for a confirmed valley: three samples a < b < c with U_b < min(L_a, L_c) at ±5 %, so M_drop = L_a − U_b and "
            "M_rise = L_c − U_b are both positive; M_T2 is the smaller one, and the valley must survive dropping any single sample. T2 applies "
            "only to serial samples of one animal. On group means a valley is a description, because averaging unimodal curves can produce two peaks.",
            [_tbl("Valley search on each curve", ("Curve", "Data", "Valley a, b, c (h)", f"M_drop ({unit})", f"M_rise ({unit})", f"M_T2 ({unit})",
                                                  "Survives drop-one", "T2 result"), t2rows)], cur_ids))
        # Q5 and Q6
        evs = [r for r in ev_iv_res if r["ev"] in ids]
        sp_cards = {d["card"]["species"] for d in ds}
        if evs:
            r = evs[0]
            q = r.get("q") or []
            add(5, []).append(_part(
                "T4 compares Q = C_EV / C_IV at matched times (±5 % on each value). Under a shared one-compartment disposition Q cannot "
                "decrease, so M_T4 = max over an earlier time a and a later time b of lower(Q_a) − upper(Q_b). A positive margin shows a fall "
                "at the assumed tolerance. Test its stability by dropping each time. Formal exclusion requires justified error bounds. "
                "T4 does not test flip-flop, group means assume a common k, and "
                "the apparent t½ is a description only.",
                [_tbl("T4 summary", ("EV", "IV", "Basis", "M_T4", "Times giving it (h)", "T4 result", "Apparent t½"),
                      [[r["ev"], r["iv"], r["comparison_basis"], _f(r.get("mt4")), ", ".join(f"{x:.3g}" for x in r.get("mt4_pair") or []) or None,
                        _flags(r.get("t4_label"), r.get("t4_flags")) + (f" ({r['t4_reason']})" if r.get("t4_reason") else ""), r.get("trigger_text")]]),
                 _tbl("Q at matched times", ("Time (h)", "Q = C_EV / C_IV", "Lower (±5 %)", "Upper (±5 %)"),
                      [[_f(x["t"]), f"{x['q']:.3g}", f"{x['lo']:.3g}", f"{x['hi']:.3g}"] for x in q])], [r["ev"], r["iv"]]))
            add(6, []).append(_part(
                "The finite-window dose-normalized AUC ratio = (AUC_EV[start,end]/D_EV) ÷ (AUC_IV[start,end]/D_IV). "
                "Both integrals use the identical overlapping observed interval, linear-up/log-down segments and interpolated endpoints; "
                "there is no extrapolation or assumed predose value. Missing early and terminal exposure prevents interpreting this as absolute F "
                "or a bound on F. t_first·C_first is an assumed IV rectangle sensitivity, not the largest missing IV area. "
                + " ".join(_source_f_text(x) for x in evs),
                [_tbl("Finite-window dose-normalized exposure ratios", ("EV / IV", "EV dose (mg/kg)", "IV dose (mg/kg)", "Identical interval", "AUC ratio",
                                                   "EV tail beyond own tlast", "IV tail beyond own tlast", "Ratio status", "Caveats"),
                      [[f"{x['ev']} / {x['iv']}", _f(x["dose_ev"]), _f(x["dose_iv"]), _ratio_window_text(x) if x.get("window_auc_ratio") is not None else None,
                        _f(x.get("window_auc_ratio")), _pct(x.get("ev_tail_share")), _pct(x.get("iv_tail_share")), x.get("f_status", "NOT_ESTIMABLE"),
                        ", ".join(x.get("f_caveats", [])) or _f_reason(x) or "none"] for x in evs]),
                 _tbl("Historic unequal-support sensitivity (not absolute F or a bound)",
                      ("EV / IV", "EV interval (h)", "IV interval (h)", "Historic ratio", "With assumed IV rectangle", "Method / assumptions"),
                      [[f"{x['ev']} / {x['iv']}", z["ev_interval_h"], z["iv_interval_h"], _f(z["ratio"]), _f(z["ratio_with_assumed_iv_rectangle"]),
                        z["method"] + "; " + "; ".join(z["assumptions"])] for x in evs for z in [x.get("legacy_different_support_sensitivity")] if z])],
                list(dict.fromkeys(y for x in evs for y in (x["ev"], x["iv"])))) )
        else:
            ivt = _iv_table(ivs, study, next(iter(sp_cards)) if len(sp_cards) == 1 else None)
            term = _tbl("Terminal phase of each curve (description)", ("Curve", "Window start (h), points", "Apparent t½ (h)", "adj R²",
                                                                      f"Span ratio (≥ {SPAN_MIN:g})", "Late ÷ early slope", "Tail share beyond tlast"),
                        [[_cid(d, s), (f"{sel['start']:.3g}, {sel['n']}" if sel else "no window qualifies"), _f(sel and sel["thalf"]),
                          _f(sel and sel["adjR2"]), _f(sel and sel["span_ratio"]),
                          (f"{m['split']['ratio']:.2f} ({m['split']['class']})" if m.get("split") and m["split"].get("ratio") is not None
                           else ((m.get("split") or {}).get("reason") or (m.get("split") or {}).get("class", "fewer than 4 post-peak samples"))),
                          _pct(m.get("tail_share"))]
                         for d, s in curves for m in [s["metrics"]] for sel in [m.get("terminal_selected")]])
            add(5, []).append(_part(
                "Telling a long absorption tail (flip-flop) from slow elimination needs an IV curve from the same study and species. "
                + (_iv_unpaired_text(ivs, ds) + " " if _iv_unpaired_text(ivs, ds) else "None is in the source tables. ") + "flip_flop_reading = NOT_ASSESSABLE (missing side: IV), which is not evidence against flip-flop. The apparent "
                f"terminal t½ is a log-linear fit over the best window with span ratio ≥ {SPAN_MIN:g} and is a description only; it is not "
                "passed on as an elimination rate k.", [ivt, term], cur_ids))
            source_cards = [d["card"] for d in ds if d["card"].get("source_reported_absolute_f")]
            add(6, []).append(_part("Absolute F was not recomputed from the curves. " +
                                    (_iv_unpaired_text(ivs, ds) or "No eligible same-study IV comparison is in the source tables.") + " "
                                    + " ".join(_source_f_text(c) for c in source_cards)
                                    + (" These are source-level parameters; no pairing of the available individuals is inferred." if source_cards else ""), [ivt], cur_ids))
        # Q7
        dsr = [r for r in dose_series_res if set(r["dataset_ids"]) <= ids and r["status"] == "ASSESSED"]
        if dsr:
            add(7, []).append(_dose_series_parts(dsr[0]))
        else:
            add(7, []).append(_part("Dose dependence needs at least two doses of one study, route, matrix, record level and occasion that share "
                                    "sampling times. The curves of this study do not form such a series.",
                                    [_curve_attr_table("Curves of this study", curves)], cur_ids))
        # Q8
        crs = [r for r in cond_res if {r["a"], r["b"]} <= ids]
        if crs:
            r = crs[0]
            iv8 = r.get("intervals") or []
            add(8, []).append(_part(
                "T5 asks whether one constant c = C_A / C_ref fits every matched time (±5 % on each value). No common c exists when the highest "
                "lower end lies above the lowest upper end. This is a sensitivity comparison under an assumed error range. "
                "A common scale could reflect F or proportional changes in CL and V. A pair that differs in more than one attribute "
                "is confounded.",
                [_tbl("Condition pair", ("Test vs reference", "Differing", "Confounded", "Highest lower end", "Lowest upper end", "T5 result", "Rate-only check"),
                      [[f"{r['a']} vs {r['b']}", ", ".join(r["differing_attributes"]), "yes" if r["confounded"] else "no", _f(r.get("c_lower")),
                        _f(r.get("c_upper")), _flags(r.get("t5_label"), r.get("t5_flags")) + (f" ({r['t5_reason']})" if r.get("t5_reason") else ""),
                        (r.get("rate_only_label") or "—") + (f" ({r['rate_only_reason']})" if r.get("rate_only_reason") else "")]]),
                 _tbl("c at matched times", ("Time (h)", "c = C_A / C_ref", "Lower (±5 %)", "Upper (±5 %)"),
                      [[_f(x["t"]), f"{x['c']:.3g}", f"{x['lo']:.3g}", f"{x['hi']:.3g}"] for x in iv8])], [r["a"], r["b"]]))
        else:
            add(8, []).append(_part("A condition pair needs two curves of the same study, species and matrix that differ in something other than "
                                    "dose alone (dose differences belong to Q7). No such pair is in this study.",
                                    [_curve_attr_table("Curves of this study", curves)], cur_ids))
        # Q9
        add(9, []).append(_part(
            "Shared kinetics versus an artefact of averaging can be judged only from serial curves of several animals. Group means cannot "
            "answer it, destructive sampling (one time point per animal) cannot answer it in principle, and individual values whose "
            "cross-time identity is not verified give points only.",
            [_tbl("Sampling design of each dataset", ("Dataset", "Data", "Curves", "n per time", "Identity verified", "Source wording on sampling"),
                  [[d["card"]["dataset_id"], _data_level(d["card"]), len(d["series"]), d["card"].get("n_per_time"), d["card"].get("identity_verified"),
                    _note_hit(d["card"]["notes"], r"mice/time|animals?/time|per time|destructive|serial|sacrific|terminal") or "not stated"]
                   for d in central])], [d["card"]["dataset_id"] for d in central]))
    if pss:
        pt = _param_evidence(pss)
        pids = [ps["card"]["dataset_id"] for ps in pss]
        prow_rule = ("Reported parameters are taken as printed (A0.12). They describe the curve but cannot answer questions that need "
                     "concentration points.")
        extra = {6: [], 7: []}
        for ps in pss:
            a = ps.get("analysis") or {}
            f = a.get("f")
            if f:
                extra[6].append(_tbl("Reported F", ("Dataset", "F", "f_status", "Flags"),
                                     [[ps["card"]["dataset_id"], _f(f.get("value")), f.get("f_status"), ", ".join(f.get("flags", [])) or "none"]]))
            t = a.get("t3")
            if t:
                extra[7].append(_tbl("T3 from reported group AUC (mean, SD, n)", ("Dataset", "Dose pair (mg/kg)", "R", "95 % CI", "T3 result"),
                                     [[ps["card"]["dataset_id"], f"{t['dose_pair'][0]:g} → {t['dose_pair'][1]:g}", f"{t['R']:.3g}",
                                       f"{t['ci'][0]:.3g}–{t['ci'][1]:.3g}", _flags(t["t3_label"], t["t3_flags"])]]))
        merge_q = (6, 7) if central else (2, 5, 6, 7) if ds else tuple(rows)  # as status_boards merges the rows
        for qn in merge_q:
            add(qn, []).append(_part(prow_rule, [pt] + extra.get(qn, []), pids))
    return {str(qn): parts for qn, parts in ev.items()}


def _names(xs, n=4):
    xs = list(dict.fromkeys(xs))
    return ", ".join(xs[:n]) + (f" and {len(xs) - n} more" if len(xs) > n else "")


# ---------------------------------------------------------------- the nine question rows (A0.11 page structure)
# Inside a study the main view is the nine questions. Each row has its status, one conclusion sentence in three parts
# (what was observed; which points, animals or test result it rests on; how far it reaches given the record level),
# the single most explanatory evidence beside it (one panel drawn with only this question's marks, or one data row),
# and what is missing. Other panels open from the row by tier. The r4.1 board rows stay in absorption.json (status_boards[*].rows).

# panel id: (figure, name, tier, how to read)
PANELS = {
    "A1": ("A", "A1 · Early window (linear)", 1, "Linear concentrations from 0 to the first sample after Tmax. The shaded band is the time before the "
           "first quantified sample when a lag bound is applicable. The orange ring marks Tmax. An open diamond marks an assumed baseline."),
    "A1w": ("A", "A1 · Whole profile (linear)", 1, "The same curve over all samples on a linear axis."),
    "A1ind": ("A", "A1 · Individual layer (linear)", 1, "One thin line per animal and the bold mean; with unverified identity, points only with a small time offset."),
    "A2": ("A", "A2 · C/t intervals (T1)", 1, "C/t at each sample with ±5 % intervals. Under M0 (input that never increases, linear disposition) C/t "
           "cannot rise; the dashed line joins the pair with the largest margin M_T1."),
    "A3": ("A", "A3 · Rising-limb increments", 3, "ΔC/Δt between consecutive quantified samples before the peak (description only)."),
    "A4": ("A", "A4 · Individual Tmax and Cmax/D", 3, "One point per animal (description only)."),
    "B1": ("B", "B1 · Whole profile (semi-log)", 1, "All samples on a log axis: the selected terminal window with its apparent t½, the split halves "
           "(shifted up) with their slope ratio, and dip points when present."),
    "B1ind": ("B", "B1 · Individual layer (semi-log)", 1, "One thin line per animal and the bold mean on a log axis."),
    "T2": ("B", "B1 · T2 dip test (per animal)", 2, "The three valley points with ±5 % intervals; a dip is confirmed when the middle point lies below both "
           "neighbours by more than the intervals (M_drop, M_rise; M_T2 is the smaller)."),
    "B2": ("B", "B2 · Terminal-window sensitivity", 3, "Apparent t½ of every qualified window (span ratio ≥ 2); the selected window is ringed."),
    "C1": ("C", "C1 · C/D overlay", 1, "Each dose divided by dose, linear (early part) and semi-log (whole profile); the common window is shaded."),
    "C2": ("C", "C2 · Metrics by dose", 1, "Cmax/D, apparent t½ (range over qualified windows and the selected value) and AUC/D over the common window "
           "(0–tlast dashed: different windows, not comparable) against log2 dose."),
    "C2T3": ("C", "C2 · T3 AUC/D ratio with CI", 2, "The ratio R of AUC/D between two doses with its confidence interval; the dashed line is R = 1."),
    "C3": ("C", "C3 · Per-time ln ratio (T3p)", 2, "ln(C/D) of the highest over the lowest dose at each common time with 95 % CI; orange times stay "
           "significant after Holm."),
    "C3d": ("C", "C3 · Per-time C/D ratio (description)", 3, "C/D of the highest over the lowest dose at each common time; a description, not a test."),
    "D1": ("D", "D1 · EV vs IV (T4)", 2, "Both curves divided by dose (semi-log) with their terminal windows, and Q = C_EV / C_IV at matched times; "
           "under a shared one-compartment disposition Q cannot decrease."),
    "D2": ("D", "D2 · finite-window AUC ratio", 2, "Both curves divided by dose (linear); the areas up to the end of the common window are shaded."),
    "D1a": ("D", "D1 · EV vs IV per animal", 2, "One panel per animal that received both routes with a stated washout: both curves divided by dose "
            "(semi-log) with their terminal windows; T4 and the window AUC ratio are computed within the animal."),
    "D1d": ("D", "D1 · EV vs IV individuals (description)", 3, "Every EV and IV curve of the study divided by its dose, semi-log, over the "
            "whole profile and over the first fifth of the sampling range. Drawn when the curves are not paired within animals; no T4 and no exposure ratio."),
    "E1": ("E", "E1 · Condition overlay", 2, "Both conditions, reference solid, linear and semi-log."),
    "E2": ("E", "E2 · c intervals (T5)", 2, "c = C_A / C_ref at matched times with ±5 % intervals; no common c exists when the highest lower end lies "
           "above the lowest upper end."),
    "E3": ("E", "E3 · Shape-normalized overlay", 3, "Each curve divided by its own window AUC (description only)."),
    "F": ("F", "F · Reported parameters", 1, "One panel per reported parameter against dose; bars are the reported dispersion."),
}

# question: (short label, question, other panels opened from the row, assumptions line, cannot-show line)
_LSPEC = {
    1: ("Onset and delay", "When does drug start to reach the circulation; is there a delay?", ("A2", "A1", "A1ind"),
        "Time zero is dosing. Predose observations are listed in the evidence table.", "The exact onset between samples."),
    2: ("Input speed", "Is input concentrated or sustained?", ("A1w", "A1ind", "B1ind", "A3"),
        "Observed points only; Tmax is the observed maximum, not a model value.", "An absorption rate constant, or zero- against first-order input."),
    3: ("Excluded input + disposition", "Which complete input + disposition combinations are excluded?", ("A2", "A1", "T2"),
        "M0 assumes a zero initial state, a single dose and an observed central compartment; the ±5 % bound is project-set.",
        "Which input is present; whether there is a lag or a transit."),
    4: ("Second rise", "Is there a dip and a second rise that one input peak cannot explain?", ("B1", "A1w", "T2", "A1ind", "B1ind", "A3"),
        "A dip is three samples with the middle one below both neighbours by more than ±5 %.",
        "The cause of a second rise (enterohepatic cycling, split absorption, sampling)."),
    5: ("Long tail and flip-flop", "Could slow absorption control the tail; can the EV half-life be read as disposition?", ("B1", "D1", "D1a", "D1d", "B2"),
        "A terminal window needs three or more post-peak points and a span ratio of at least 2 (project-set).",
        "Whether the tail is absorption-limited, without an IV curve of the same study."),
    6: ("Extent of absorption (F)", "How much of the dose reaches the circulation?", ("D2", "D1a", "D1d", "F"),
        "Equal clearance in both arms (same study); consistent dose basis; no extrapolation.", "F itself when the window ratio is incomplete."),
    7: ("Dose dependence", "Does absorption-related behaviour change with dose?", ("C1", "C2", "C2T3", "C3", "C3d", "F"),
        "Same study, route, occasion and record level; the common window ends at the latest time shared by all doses.",
        "Whether absorption or elimination is the part that changes with dose."),
    8: ("Comparison across conditions", "Does a condition (route, formulation, food, occasion) change rate, extent or disposition?", ("E1", "E2", "E3", "D1d"),
        "Same drug, analyte and matrix; times matched within tolerance; group means need the same-population premise.",
        "A mechanism; with T5 not excluded, F only and CL and V scaled together cannot be separated."),
    9: ("Individuals or averaging", "Is the shape shared by individuals, or produced by averaging?", ("A4", "A1ind", "B1ind"),
        "Labels follow the source table.", "Single-animal shapes from group means or destructive sampling."),
}


# review-guide question: (label, question, panels opened from the row, assumptions line, cannot-show line)
QSPEC = {
    1: (QUESTIONS[0][1], QUESTIONS[0][2], ("A1", "A1w", "A1ind", "A2", "A3"),
        "Time zero is dosing; a drug-free start and a specific assay are needed to read the first quantified sample as onset.",
        "The exact onset between samples, or an absorption rate constant."),
    2: (QUESTIONS[1][1], QUESTIONS[1][2], ("B1", "T2", "A1w", "A1ind", "B1ind", "A4"),
        "A trough is three ordered samples of one animal with the middle upper bound below both outer lower bounds.",
        "The cause of a second rise (a second release, interrupted gastric emptying or recirculation)."),
    3: (QUESTIONS[2][1], QUESTIONS[2][2], ("B1", "B2", "B1ind"),
        "A window needs 3 or more consecutive quantified samples strictly after the peak, a negative slope and a span of at least 2 apparent half-lives.",
        "Whether the apparent half-life reflects disposition or absorption."),
    4: (QUESTIONS[3][1], QUESTIONS[3][2], ("A2", "A1", "A3", "T2"),
        "A single dose, a drug-free start, immediate non-increasing input into the central compartment and linear, time-invariant disposition.",
        "Which input is present; whether there is a lag or a transit delay."),
    5: (QUESTIONS[4][1], QUESTIONS[4][2], ("B1", "D1", "D1a", "D1d", "B2"),
        "Apparent half-lives over comparable qualified windows of the extravascular and the IV curve.",
        "Whether the tail is absorption-limited; a finite window can give a longer extravascular half-life when absorption is faster."),
    6: (QUESTIONS[5][1], QUESTIONS[5][2], ("D2", "D1a", "D1d", "F"),
        "Same parent analyte, matrix and dose basis; shared linear clearance; areas over one common interval.",
        "Absolute bioavailability when early IV exposure or the tails are not covered."),
    7: (QUESTIONS[6][1], QUESTIONS[6][2], ("C1", "C2", "C2T3", "C3", "C3d", "F"),
        "Same study, route, occasion and record level; one common window for all doses.",
        "Whether input, systemic bioavailability or clearance changes with dose."),
    8: (QUESTIONS[7][1], QUESTIONS[7][2], ("D1", "D1a"),
        "Shared, linear, time-invariant one-compartment disposition, zero initial drug, central measurement, nonnegative extravascular input; "
        "the IV input has ended.", "Flip-flop kinetics; this check answers a different question from the half-life comparison."),
    9: (QUESTIONS[8][1], QUESTIONS[8][2], ("E1", "E2", "E3", "D1d"),
        "Same drug, analyte and matrix; times matched within tolerance; at least three quantified samples per arm in the common window.",
        "A mechanism; when one multiplier fits, a change in bioavailability and a proportional change in clearances and volumes stay together."),
}


def _as_view(prim):
    """The primary panel of the second part of a merged row, shown with the row's other panels."""
    if not prim or prim.get("kind") != "panel" or not prim.get("file"):
        return None
    pid = next((x for x in prim.get("panels") or [] if x in PANELS), "A1")
    return {"panel": pid, "file": prim["file"], "label": prim["lines"][1], "ids": [], "gated": False, "tier": 1, "name": PANELS[pid][1]}


def _as_evidence(prim):
    if not prim or prim.get("kind") != "row":
        return None
    return {"rule": prim["lines"][1], "tables": [{"caption": prim["lines"][0], "head": prim["head"], "rows": prim["rows"]}], "data": []}


_ROW_KEYS = {"q", "label", "question", "status", "status_code", "observed", "basis", "reach", "text", "missing", "primary", "views", "evidence"}


def _guide_row(g, status, observed, basis, reach, missing, primary, views, evidence, legacy, extra=None):
    row = {"q": g, "label": QSPEC[g][0], "question": QSPEC[g][1], "status": status, "status_code": ST_CODE[status],
           "observed": observed, "basis": basis, "reach": reach, "text": " ".join(x for x in (observed, basis, reach) if x),
           "missing": [m for m in dict.fromkeys(missing) if m], "primary": primary, "views": list(views), "evidence": list(evidence),
           "legacy_q": list(legacy)}
    row.update(extra or {})
    # M5: stable id and guide number, the same fields as Distribution and Elimination rows
    row.update({k: v for k, v in COMMON.guide_fields("absorption", g).items()})
    return row


def _guide_from(g, parts):
    """One review-guide row from one or two r4.3 rows. The first part leads: it gives the status unless it has none to give
    (insufficient evidence, not applicable), in which case the row takes the highest state among its parts (A0.11)."""
    status = parts[0]["status"]
    if status in (ST_NO, ST_NA):
        status = max((x["status"] for x in parts), key=lambda v: _RANK[v])
    primary = next((x["primary"] for x in parts if x.get("primary")), None)
    if status in (ST_NO, ST_NA) and primary and primary.get("kind") == "panel":
        primary = None
    views, evidence, seen = [], [], {(primary or {}).get("file")}
    for x in parts:
        other = x.get("primary")
        if other and other is not primary:
            v, e = _as_view(other), _as_evidence(other)
            if v and v["file"] not in seen:
                seen.add(v["file"]); views.append(v)
            if e:
                evidence.append(e)
        for v in x["views"]:
            if v["file"] not in seen:
                seen.add(v["file"]); views.append(v)
        evidence += x["evidence"]
    extra = {k: v for x in parts for k, v in x.items() if k not in _ROW_KEYS}
    if len(parts) > 1:
        extra["parts"] = [{"legacy_q": x["q"], "legacy_label": x["label"], "status_code": x["status_code"], "text": x["text"],
                           "primary": x.get("primary")} for x in parts]

    def join(key):
        return " ".join(dict.fromkeys(x[key] for x in parts if x[key]))
    return _guide_row(g, status, join("observed"), join("basis"), join("reach"), [m for x in parts for m in x["missing"]], primary,
                      sorted(views, key=lambda v: v["tier"]), evidence, [x["q"] for x in parts], extra)


def _gviews(g, study_panels):
    want, seen, out = QSPEC[g][2], set(), []
    for pid in want:
        for v in study_panels.get(pid, []):
            if v["file"] not in seen and not v.get("gated"):
                seen.add(v["file"]); out.append(v)
    return sorted(out, key=lambda v: (v["tier"], want.index(v["panel"])))


def _g3_half_life(curves_m, study_panels, level, fallback):
    """Guide Q3: how much the apparent half-life depends on the samples used."""
    if not curves_m:
        return _guide_row(3, ST_NO, fallback["observed"], "Terminal windows need concentration points of a curve that passes the gates.", "",
                          ["at least 3 quantified samples after the peak of one curve"], None, [], [], [5])
    parts = []
    for c, m in curves_m:
        sel, rng, nq = m.get("terminal_selected"), m.get("terminal_thalf_range"), m.get("terminal_n_qualified", 0)
        if sel:
            parts.append(f"{c}: apparent t½ {sel['thalf']:.3g} h from {sel['start']:g} h ({sel['n']} samples)"
                         + (f", {rng[0]:.3g}–{rng[1]:.3g} h over {nq} qualified windows" if nq > 1 and rng else ", the only qualified window"))
    none = [c for c, m in curves_m if not m.get("terminal_selected")]
    multi = any(m.get("terminal_selected") and m.get("terminal_n_qualified", 0) > 1 for _, m in curves_m)
    status = ST_YES if multi else ST_PART if parts else ST_NO
    observed = ("; ".join(parts) + "." + (f" No window qualifies in {_names(none)}." if none else "") if parts
                else "No terminal window qualifies, so the apparent half-life is left unestimated.")
    basis = ("Each window keeps the last quantified sample and moves its start back one sample at a time. It needs 3 or more consecutive "
             f"quantified samples strictly after the peak, a negative slope and a span of at least {SPAN_MIN:g} apparent half-lives. "
             "The longest window whose adjusted R² is within 0.0001 of the highest is selected.")
    missing = ([] if multi else ["more quantified samples after the peak (a second qualified window)"] if parts
               else [f"at least 3 quantified samples after the peak spanning {SPAN_MIN:g} apparent half-lives"])
    return _guide_row(3, status, observed, basis, (level + " " if level else "") + "The half-life is apparent: it describes the fitted window.",
                      missing, None, _gviews(3, study_panels), [], [5])


def _g8_route_ratio(evs, study_panels, level, unpaired, fallback, has_curves):
    """Guide Q8: the raw extravascular/IV concentration ratio at matched times (T4)."""
    if not has_curves:
        return _guide_row(8, ST_NO, fallback["observed"], "The route ratio needs matched extravascular and IV concentration points.", "",
                          ["a same-study IV curve with at least 2 matched sampling times"], None, [], [], [5])
    tested = [r for r in evs if r.get("q")]
    if not tested:
        why = next((r.get("t4_reason") for r in evs if r.get("t4_reason")), None)
        observed = (f"The matched-time route ratio could not be formed: {why}." if why else
                    unpaired or "No IV curve from this study and species, so the matched-time route ratio cannot be formed.")
        return _guide_row(8, ST_NO, observed, "", level, ["a same-study IV curve with at least 2 matched sampling times"], None,
                          _gviews(8, study_panels), [], [5])

    def name(r):
        return f"animal {r['subject_id']}" if r.get("subject_id") else f"{r['ev']} / {r['iv']}"
    tested = sorted(tested, key=lambda r: -r["mt4"])
    texts = [f"{name(r)}: {len(r['q'])} matched times, largest supported decrease of the ratio {r['mt4']:.3g} between {r['mt4_pair'][0]:g} h and "
             f"{r['mt4_pair'][1]:g} h" + (" (a decrease beyond the bounds)" if r["mt4"] > 0 else " (no decrease beyond the bounds)") for r in tested[:6]]
    flags = sorted({f for r in tested for f in r.get("t4_flags", [])})
    labels = sorted({str(r.get("t4_label")) for r in tested})
    basis = ("After the IV input has ended, the raw extravascular/IV concentration ratio can only stay constant or rise under shared, linear, "
             "time-invariant one-compartment disposition with zero initial drug and nonnegative extravascular input. Each earlier lower bound "
             f"is compared with each later upper bound (T4 = {'/'.join(labels)}{' + ' + '+'.join(flags) if flags else ''}).")
    reach = ((level + " ") if level else "") + (f"The ±{TOL:.0%} bounds are assumed, so the margin is a sensitivity result and not a formal exclusion."
            + (" Group means assume a common elimination rate." if "CONDITIONAL_ON_COMMON_K" in flags else ""))
    return _guide_row(8, ST_PART, "Raw extravascular/IV concentration ratio. " + "; ".join(texts) + ("." if len(tested) <= 6 else f"; and {len(tested) - 6} more."),
                      basis, reach, ["justified concentration and time bounds (assay, timing, digitization)"], None, _gviews(8, study_panels), [], [5],
                      {"t4": [{"pair": name(r), "margin": r["mt4"], "times_h": r["mt4_pair"], "label": r.get("t4_label"), "flags": r.get("t4_flags", [])} for r in tested]})


def _guide_rows(qs, study_panels, curves_m, evs, level, unpaired=""):
    """The nine review-guide rows from the nine r4.3 rows (see GUIDE_Q)."""
    rows = {1: _guide_from(1, [qs[1], qs[2]]), 2: _guide_from(2, [qs[4], qs[9]]), 4: _guide_from(4, [qs[3]]), 5: _guide_from(5, [qs[5]]),
            6: _guide_from(6, [qs[6]]), 7: _guide_from(7, [qs[7]]), 9: _guide_from(9, [qs[8]]),
            3: _g3_half_life(curves_m, study_panels, level, qs[5]),
            8: _g8_route_ratio(evs, study_panels, level, unpaired, qs[5], bool(curves_m))}
    return [rows[g] for g in range(1, 10)]


# ---------------------------------------------------------------- review guide: input patterns, figures and tables
# The sixteen input patterns of the review guide and which formal shape check covers each one, as the guide states it.
#   t1: a supported rise of concentration/time since dosing (guide Q4)        t2: a supported within-animal trough (guide Q2)
#   APPLIES      the prediction holds for this pattern under the stated disposition, baseline and measurement assumptions
#   CONDITIONAL  the prediction holds only under the condition in the note
#   OUTSIDE      the pattern falls outside the check, so the check cannot challenge it
#   NOT_STATED   the guide gives no coverage; name the eligible check for the complete model or keep the comparison descriptive
# hyp: the options of this module's hypothesis layer that carry the pattern ([] = outside the machine-readable r4.3 list).
# group and mistaken_for follow the guide paragraph "How to sort a profile" (2026-11-24): A starts at dosing and never speeds up,
# B delayed or gradual start in one episode, C two episodes or a switch, D differs across doses, E no fixed shape.
# Example studies and simulated reference values stay in the guide's Appendix A and are not carried in code or absorption.json.
INPUT_PATTERNS = (
    {"id": "immediate_first_order", "name": "Immediate first-order", "hyp": ["shape.first_order"], "group": "A",
     "t1": "APPLIES", "t1_note": "The rate falls from dosing.", "t2": "APPLIES", "t2_note": "At most one peak under the stated disposition.",
     "mistaken_for": ["parallel_common_start", "weibull", "finite_zero_order"]},
    {"id": "finite_zero_order", "name": "Finite zero-order", "hyp": ["shape.zero_order"], "group": "A",
     "t1": "APPLIES", "t1_note": "Constant rate from dosing, then none.", "t2": "APPLIES", "t2_note": "Meets the single-peak prediction.",
     "mistaken_for": ["finite_absorption_window", "capacity_limited_uptake"]},
    {"id": "fixed_lag", "name": "Fixed lag before a chosen input", "hyp": ["onset.fixed_lag"], "group": "B",
     "t1": "OUTSIDE", "t1_note": "A fixed lag falls outside the immediate-input check.",
     "t2": "CONDITIONAL", "t2_note": "Shifting a single-peaked response in time preserves its shape; coverage follows the chosen input.",
     "mistaken_for": ["transit_gamma"]},
    {"id": "transit_gamma", "name": "Serial transit, Erlang or gamma input", "hyp": ["onset.transit"], "group": "B",
     "t1": "CONDITIONAL", "t1_note": "Gamma shape 0 < a <= 1 gives a rate that falls from dosing; a > 1 gives a gradual rise and falls outside.",
     "t2": "CONDITIONAL", "t2_note": "The density is log-concave for shape a >= 1.",
     "mistaken_for": ["fixed_lag", "weibull", "inverse_gaussian", "other_smooth_arrival"]},
    {"id": "zero_release_first_uptake", "name": "Zero-order release into a depot with first-order uptake", "hyp": ["shape.zero_then_first"], "group": "B",
     "t1": "OUTSIDE", "t1_note": "The input rate rises from zero, then falls.",
     "t2": "APPLIES", "t2_note": "The two processes in series give a log-concave rate for a single release.",
     "mistaken_for": ["transit_gamma", "weibull", "sequential_two_fractions"]},
    {"id": "parallel_common_start", "name": "Parallel inputs with a common start", "hyp": ["shape.parallel_first", "shape.parallel_zero_first"], "group": "A",
     "t1": "APPLIES", "t1_note": "When both components start at dosing, the total rate is non-increasing.",
     "t2": "CONDITIONAL", "t2_note": "Needs a single-peak argument for the particular mixture.",
     "mistaken_for": ["weibull"]},
    {"id": "staggered_pulsed", "name": "Staggered or pulsed inputs", "hyp": ["second.two_inputs"], "group": "C",
     "t1": "OUTSIDE", "t1_note": "A second onset after dosing can raise the total rate.",
     "t2": "OUTSIDE", "t2_note": "A reproducible trough and second rise in one animal is what this pattern predicts.",
     "mistaken_for": []},
    {"id": "sequential_two_fractions", "name": "Sequential input from two dose fractions", "hyp": [], "group": "C",
     "t1": "CONDITIONAL", "t1_note": "Holds only without an upward jump at the switch: w/T at least (1 - w)·ka on the same fractional basis.",
     "t2": "NOT_STATED", "t2_note": "",
     "mistaken_for": ["zero_release_first_uptake", "time_dependent_uptake"]},
    {"id": "weibull", "name": "Weibull", "hyp": ["shape.weibull_front", "shape.weibull_sigmoid"], "group": "A or B",
     "t1": "CONDITIONAL", "t1_note": "With no lag, shape 0 < beta <= 1 gives non-increasing input.",
     "t2": "CONDITIONAL", "t2_note": "The single-peak proof covers shape beta >= 1 under the stated disposition.",
     "mistaken_for": ["parallel_common_start", "transit_gamma"]},
    {"id": "inverse_gaussian", "name": "Inverse Gaussian", "hyp": ["shape.inverse_gaussian"], "group": "B",
     "t1": "OUTSIDE", "t1_note": "The input rate rises, then falls.",
     "t2": "CONDITIONAL", "t2_note": "Holds with one-compartment disposition; a multicompartment model requires a separate argument.",
     "mistaken_for": ["other_smooth_arrival", "transit_gamma", "weibull"]},
    {"id": "distributed_release_uptake", "name": "Distributed release followed by uptake", "hyp": [], "group": "B",
     "t1": "NOT_STATED", "t1_note": "", "t2": "NOT_STATED", "t2_note": "",
     "mistaken_for": ["inverse_gaussian", "transit_gamma"]},
    {"id": "other_smooth_arrival", "name": "Other smooth arrival-time distributions (lognormal, log-logistic)", "hyp": [], "group": "B",
     "t1": "NOT_STATED", "t1_note": "Empirical sensitivity models.", "t2": "NOT_STATED", "t2_note": "",
     "mistaken_for": ["inverse_gaussian", "transit_gamma"]},
    {"id": "finite_absorption_window", "name": "Finite absorption window", "hyp": [], "group": "A",
     "t1": "NOT_STATED", "t1_note": "", "t2": "NOT_STATED", "t2_note": "",
     "mistaken_for": ["finite_zero_order"]},
    {"id": "time_dependent_uptake", "name": "Time-dependent uptake rate", "hyp": [], "group": "C",
     "t1": "CONDITIONAL", "t1_note": "Apply the argument to the total rate ka(t)·A(t) over the full window; the coefficient alone leaves its direction open.",
     "t2": "NOT_STATED", "t2_note": "",
     "mistaken_for": ["fixed_lag", "staggered_pulsed"]},
    {"id": "capacity_limited_uptake", "name": "Capacity-limited uptake, with optional passive uptake", "hyp": ["dose.saturable_rate"], "group": "D",
     "t1": "CONDITIONAL", "t1_note": "If site concentration only falls, both uptake terms fall within that dose.",
     "t2": "NOT_STATED", "t2_note": "",
     "mistaken_for": ["finite_zero_order"]},
    {"id": "flexible_input", "name": "Flexible input estimated from the data", "hyp": [], "group": "E",
     "t1": "NOT_STATED", "t1_note": "Estimated in Modeling.", "t2": "NOT_STATED", "t2_note": "",
     "mistaken_for": []},
)
COVERAGE = ("APPLIES", "CONDITIONAL", "OUTSIDE", "NOT_STATED")

# review-guide figure -> panels of this module that draw it (the insets are the guide's optional insets)
GUIDE_FIGURES = {
    "1a": {"title": "Early measured concentration", "panels": ["A1", "A1ind"]},
    "1b": {"title": "Full measured concentration profile", "panels": ["B1", "B1ind", "T2"], "insets": ["B2"]},
    "2": {"title": "Concentration divided by elapsed time", "panels": ["A2"], "insets": ["A3"]},
    "3a": {"title": "Dose-normalized concentration, linear view", "panels": ["C1", "D2", "E1"], "insets": ["E3"]},
    "3b": {"title": "Dose-normalized concentration, semilog view", "panels": ["C1", "D1", "D1a", "D1d", "E1"]},
    "4a": {"title": "Matched-time ratio across doses", "panels": ["C3", "C3d"]},
    "4b": {"title": "Matched-time ratio across routes", "panels": ["D1", "D1a"]},
    "4c": {"title": "Matched-time ratio across conditions", "panels": ["E2"]},
    "5": {"title": "Pharmacokinetic parameters by dose", "panels": ["C2", "C2T3", "F", "A4"]},
}
# review-guide table -> where its entries sit in absorption.json
GUIDE_TABLES = {
    "1": {"title": "Study data and sampling design", "source": ["datasets[].card", "datasets[].series[].metrics"]},
    "2": {"title": "Terminal decline and exposure by route", "source": ["ev_iv[].tail", "ev_iv[].q", "ev_iv[].f_status", "datasets[].iv_pairs"]},
    "3": {"title": "Pharmacokinetic measurements by dose and source", "source": ["dose_series[].rows", "reported_parameters[].params"]},
    "4": {"title": "Comparison of study conditions", "source": ["conditions"]},
}


def guide_meta():
    """What this build takes from the review guide, written once into absorption.json under "guide"."""
    panels = {p for f in GUIDE_FIGURES.values() for p in f["panels"] + f.get("insets", [])}
    return {"name": GUIDE, "version": VERSION,
            "questions": [{"q": n, "label": lab, "question": text, "r43_rows": [k for k, g in GUIDE_Q.items() if g == n]} for n, lab, text in QUESTIONS],
            "terminal_window": {"min_samples_after_peak": 3, "min_span_half_lives": SPAN_MIN, "adjusted_r2_tie": ADJ_R2_TIE,
                                "rule": "longest qualified window within the tie of the highest adjusted R²"},
            "half_life_ratio": {"cuts": list(HL_CUTS), "grades": list(HL_GRADES), "reading": dict(FF_READING),
                                "unresolved_when": "the grade changes with the window pair"},
            "bioavailability": {"tail_fraction_max": TAIL_FLAG, "statuses": ["WINDOW_BASED_ESTIMATE", "OBSERVED_WINDOW_RATIO"],
                                "needs": ["same-study comparison", "justified early coverage", "tail fraction within the limit for each route"]},
            # decisions of 2026-11-24 shared with Distribution and Elimination
            "uncertainty": {"formal_needs": ["a matched source assay coefficient of variation converted to joint bounds over every searched "
                                             "observation (Bonferroni)", "replicate-based bounds with stated coverage",
                                             "a statistical procedure covering the full search"],
                            "admission_rule": "rule decision R8 (eda_common.precision_admission): a CV needs its source, method, analyte, matrix, "
                                              "range covered, within or between run and an observed (not acceptance-limit) value; replicates "
                                              "need df and the standard error that matches the value; digitized data need a figure-level "
                                              "reading range, and the project default of 5 % keeps the result a sensitivity analysis",
                            "sensitivity_only": ["pointwise intervals", "unconverted assay precision", "an assumed project tolerance"],
                            "this_build": f"every interval uses the assumed ±{TOL:.0%} tolerance, so every shape check is SENSITIVITY_ONLY"},
            "removal": {"formal_checks": "remove every eligible observation in turn and repeat the full calculation on the rest",
                        "applies_to": ["T1", "T2", "T3p", "T4", "T5"]},
            "ranking": {"groups": list(RANK_GROUPS),
                        "sensitivity_rule": RANK_SENSITIVITY_RULE,
                        "board_level": "a formal rule excludes a combination at board level only when every required unit is formally "
                                       "excluded in the same direction; otherwise the combination stays as CONTRARY_EVIDENCE with n, m, k",
                        "field": "status_boards[].ranked_candidates"},
            "flip_flop_thresholds_owner": "absorption",
            "input_patterns": [dict(p) for p in INPUT_PATTERNS], "coverage_values": list(COVERAGE),
            "figures": GUIDE_FIGURES, "tables": GUIDE_TABLES, "panels_outside_guide_figures": sorted(set(PANELS) - panels)}


_ATTR = {"route_detail": "route", "dose_mg_per_kg": "dose", "formulation": "formulation", "fed_state": "food", "occasion": "occasion"}


def _all(n):
    return "both curves" if n == 2 else f"all {n} curves" if n > 2 else "the curve"


def _fixed_cohort(card):
    """The text states serial sampling of the same animals (as Distribution's SERIAL design); a destructive design never is."""
    text = (str(card.get("experimental_unit", "")) + " " + str(card.get("notes", ""))).lower()
    return not _destructive(card) and bool(re.search(r"serial|same animals?|cannula", text))


def _destructive(card):
    unit = str(card.get("experimental_unit", "")).lower()
    n = str(card.get("notes", "")).lower()
    return ("terminal cohorts by sampling time" in unit or "mice/time" in n or "destructive" in n
            or "terminal sampling" in n or "different group" in n)


def _n_text(card):
    v = str(card.get("n_per_time") or "")
    m = re.match(r"\s*(\d+)", v)
    return m.group(1) if m else None


def _level_text(cards):
    """The record level beneath a primary panel and the reach part of a conclusion."""
    cards = list(cards)
    levels = {c["record_level"] for c in cards}
    ns = sorted({x for x in (_n_text(c) for c in cards) if x})
    nt = f", n = {'/'.join(ns)} per time" if ns else ""
    dig = ", digitized" if any(c.get("digitized") for c in cards) else ""
    if levels == {"INDIVIDUAL"}:
        return f"Serial samples of single animals (identity verified{dig})."
    if "INDIVIDUAL_IDENTITY_UNVERIFIED" in levels:
        return f"Values by source label{dig}; the same label at different times is not verified to be one animal."
    if any(_destructive(c) for c in cards):
        return f"Group mean of different animals at each time (destructive sampling{nt}{dig}); single-animal profiles cannot be judged."
    return f"Group mean{nt}{dig}; single-animal profiles cannot be judged."


def _q(qn, status, observed, basis, reach, missing=(), primary=None, views=(), evidence=()):
    lab, question = _LSPEC[qn][0], _LSPEC[qn][1]
    if status in (ST_NO, ST_NA) and primary and primary.get("kind") == "panel":
        primary = None  # A0.11: with NOT_ANSWERABLE_YET or NOT_APPLICABLE no figure is shown
    return {"q": qn, "label": lab, "question": question, "status": status, "status_code": ST_CODE[status],
            "observed": observed, "basis": basis, "reach": reach, "text": " ".join(x for x in (observed, basis, reach) if x),
            "missing": [m for m in dict.fromkeys(missing) if m], "primary": primary, "views": list(views), "evidence": list(evidence)}


def _prim(file, panels, qn, label_line, level, kind="panel"):
    return {"kind": kind, "file": file, "panels": list(panels),
            "lines": [f"Answers Q{GUIDE_Q[qn]} · {QSPEC[GUIDE_Q[qn]][0]}", label_line, _LSPEC[qn][3], "Cannot show: " + _LSPEC[qn][4]], "level": level}


def _row(qn, head, rows, label_line, level):
    return {"kind": "row", "head": list(head), "rows": [list(r) for r in rows],
            "lines": [f"Answers Q{GUIDE_Q[qn]} · {QSPEC[GUIDE_Q[qn]][0]}", label_line, _LSPEC[qn][3], "Cannot show: " + _LSPEC[qn][4]], "level": level}


def _views_for(qn, study_panels, primary):
    """The other panels of this study that open from row qn, ordered by tier."""
    want = _LSPEC[qn][2]
    skip = (primary or {}).get("file")
    seen, out = set(), []
    for pid in want:
        for v in study_panels.get(pid, []):  # overview panels of gated curves answer no question (they stay under "Other panels")
            if v["file"] != skip and v["file"] not in seen and not v.get("gated"):
                seen.add(v["file"]); out.append(v)
    return sorted(out, key=lambda v: (v["tier"], want.index(v["panel"]) if v["panel"] in want else 99))


def _study_panels(ds, pss, dose_series_res, ev_iv_res, cond_res):
    """Every drawn panel of one study, by panel id."""
    ids = {d["card"]["dataset_id"] for d in ds}
    out = {}

    def add(pid, file, label, ids_, tier=None, gated=False):
        if file:
            out.setdefault(pid, []).append({"panel": pid, "file": file, "label": label, "ids": list(ids_), "gated": gated,
                                            "tier": tier if tier is not None else PANELS[pid][2], "name": PANELS[pid][1]})
    for d in ds:
        c = d["card"]
        for s in d["series"]:
            lab = _cid(d, s) + ("" if c["tests_allowed"] else f" ({c['matrix']}, overview only)")
            for pid in ("A1", "A1w", "A2", "A3", "B1", "T2", "B2"):
                add(pid, s.get(pid), lab, [c["dataset_id"]], gated=not c["tests_allowed"])
        add("A1ind", d.get("A1ind"), c["dataset_id"], [c["dataset_id"]])
        add("B1ind", d.get("B1ind"), c["dataset_id"], [c["dataset_id"]])
        add("A4", d.get("A4"), c["dataset_id"], [c["dataset_id"]])
        add("D1d", d.get("D1d"), c["dataset_id"], [c["dataset_id"]])
        add("D1a", d.get("D1a"), c["dataset_id"], [c["dataset_id"]])
        for r in d.get("iv_pairs") or []:
            add("D1", r.get("D1"), f"{r['ev']} vs {r['iv']}", [c["dataset_id"]])
            add("D2", r.get("D2"), f"{r['ev']} vs {r['iv']}", [c["dataset_id"]])
    for r in dose_series_res:
        if set(r["dataset_ids"]) <= ids:
            lab = f"{r['label']} · {', '.join(r['dataset_ids'])}"
            for pid in ("C1", "C2", "C2T3", "C3", "C3d"):
                add(pid, r.get(pid), lab, r["dataset_ids"])
    for ps in pss:
        c = ps["card"]
        add("F", ps.get("F"), c["dataset_id"], [c["dataset_id"]], tier=1 if not ds else 3)
        add("C2T3", ps.get("C2T3"), f"{c['dataset_id']} · reported AUC", [c["dataset_id"]])
    for r in ev_iv_res:
        if r["ev"] in ids:
            add("D1", r.get("D1"), f"{r['ev']} vs {r['iv']}", [r["ev"], r["iv"]])
            add("D2", r.get("D2"), f"{r['ev']} vs {r['iv']}", [r["ev"], r["iv"]])
    for r in cond_res:
        if {r["a"], r["b"]} <= ids:
            for pid in ("E1", "E2", "E3"):
                add(pid, r.get(pid), f"{r['a']} vs {r['b']}", [r["a"], r["b"]])
    return out


def _meal_contrasts(parameter_sets):
    """Descriptive comparisons of unambiguous, dose-matched printed endpoints on this board."""
    meals = {"fasted": "fasted", "fasting": "fasted", "fed": "fed", "nonfasted": "fed", "non-fasted": "fed"}
    buckets = {}
    for ps in parameter_sets:
        c = ps["card"]
        meal = meals.get(str(c.get("condition", "")).strip().casefold())
        identity = tuple(c.get(k) for k in ("study", "species", "drug", "matrix", "reported_analyte",
                                             "route_detail", "dosing_regimen", "reported_dose_unit"))
        if not meal or c.get("route_class") != "EV" or any(v in (None, "", "NOT_FOUND", "not reported") for v in identity):
            continue
        scope = identity + tuple(c.get(k) for k in ("cohort", "experiment_arm", "dose_basis", "reported_formulation"))
        for p in ps["params"]:
            if (p["param"] not in ("CMAX", "AUC") or not isinstance(p.get("dose"), (int, float)) or p["dose"] <= 0
                    or p.get("unit") in (None, "", "NOT_FOUND", "not reported") or not p.get("record_id")):
                continue
            key = scope + (p["dose"], p["param"], p["label"], p["unit"], p.get("definition"))
            buckets.setdefault(key, {}).setdefault(meal, []).append((p, c))
    rows = []
    for pair in buckets.values():
        if any(len(pair.get(k, [])) != 1 for k in ("fed", "fasted")):
            continue
        (fed, fc), = pair["fed"]
        (fasted, bc), = pair["fasted"]
        if fasted["value"] <= 0 or fed["value"] < 0:
            continue
        rows.append({"endpoint": fed["label"], "unit": fed["unit"], "dose": fed["dose"], "dose_unit": fc["reported_dose_unit"],
                     "condition": fc["condition"], "reference_condition": bc["condition"],
                     "fed": fed["value"], "fasted": fasted["value"], "ratio": fed["value"]/fasted["value"],
                     "datasets": [fc["dataset_id"], bc["dataset_id"]], "records": [fed["record_id"], fasted["record_id"]]})
    return rows


def _repeat_individual_ranges(datasets):
    """Compare observed concentrations only within dataset, dose and time; retain source animal identity."""
    rows = []
    for d in datasets:
        c = d["card"]
        if (c.get("route_class") != "EV" or c.get("matrix_category") != "PLASMA_SERUM_BLOOD"
                or set(c.get("gates", [])) != {"NOT_SINGLE_DOSE"} or c.get("record_level") != "INDIVIDUAL"
                or c.get("identity_verified") != "yes" or c.get("series_kind") != "INDIVIDUALS"):
            continue
        times = {}
        for s in d["series"]:
            for p in s["points"]:
                if p["status"] == "QUANTIFIED" and p["t"] >= 0 and p.get("c") is not None:
                    times.setdefault((s.get("dose") or c.get("dose_mg_per_kg"), p["t"]), {}).setdefault(
                        s["label"], []).append((p["c"], p.get("record_id")))
        for (dose, t), animals in times.items():
            if dose is None or len(animals) < 2 or any(len(v) != 1 for v in animals.values()):
                continue
            values = [v[0][0] for v in animals.values()]
            rows.append({"dataset": c["dataset_id"], "dose": dose, "time_h": t, "n": len(values),
                         "min": min(values), "max": max(values), "unit": c["unit"], "animals": list(animals),
                         "records": list(dict.fromkeys(v[0][1] for v in animals.values()))})
    return rows


def _bq_onset(curves, draw, firsts, ind_series, indiv, level, mets, n, put, src):
    """Q1 onset and delay. Part of board_questions (split 2026-11-26 without change)."""
    early = [x for x in mets if x[3]["onset_status"] == "NOT_ASSESSABLE"]
    pick = (early or sorted(mets, key=lambda x: x[3]["first_t"]))[0]
    c_, d_, s_, m_ = pick
    missing_baseline = any(not any(p["t"] <= 0 for p in s["points"]) for _, s in curves)
    if early:
        obs = f"Onset remains unresolved in {_names([x[0] for x in early])}. The first quantified postdose samples in these profiles were at {_rng([x[3]['first_t'] for x in early])} h."
        basis = ". ".join(dict.fromkeys(x[3]["onset_reason"] for x in early)) + "."
    else:
        obs = (f"Drug was already quantified at the first sample of {_all(n)} "
               f"({_rng(firsts)} h after dosing). Each curve has its own first-sample upper bound; across these curves any delay is shorter than {max(firsts):.3g} h.")
        basis = "This rests on the first quantified postdose sample of each curve."
    baseline = list(dict.fromkeys(_baseline_reading(s) for _, s in curves))
    basis += (" Baseline across these profiles: " + baseline[0] + "." if len(baseline) == 1
              else " Predose results vary by profile and are listed in the evidence table.")
    miss = [f"an earlier postdose sample before {min(firsts):.3g} h"] + (["predose sampling in profiles without baseline data"] if missing_baseline else []) + (
        ["LLOQ"] if early and not _lloq_value(d_["card"]) else [])
    if indiv(d_):
        p = pInd(d_["card"], ind_series(d_), d_["card"]["record_level"] == "INDIVIDUAL", log=False, mark_first=True, early=True,
                 title=f"{d_['card']['dataset_id']}: first quantified sample per animal")
        f = (draw(1, p, 12, 2.5 * -(-len(p) // 4) + 0.2, ncol=4) if isinstance(p, list) else draw(1, [p], 6.4, 3.8))
    else:
        f = draw(1, [pA1(d_["card"], m_, src(d_, s_), marks=("delay", "zero", "blq", "predose"), first=True, title=f"{c_}: to the first sample after Tmax (linear)")], 5.6, 3.7)
    put(1, obs, basis, level + " The exact onset between samples remains unresolved.", miss,
        _prim(f, ["A1"], 1, m_["onset_reason"], _level_text([d_["card"]])))


def _bq_input_speed(draw, firsts, ind_series, indiv, level, mets, n, put, src):
    """Q2 input speed. Part of board_questions (split 2026-11-26 without change)."""
    kani = [x[0] for x in mets if "KA_NOT_IDENTIFIABLE" in x[3]["caveats"]]
    c_, d_, s_, m_ = max(mets, key=lambda x: (x[3]["n_before_peak"], -x[3]["tmax"]))
    fr = [100 * x[3]["first_frac_cmax"] for x in mets]
    obs = (f"Tmax {_rng([x[3]['tmax'] for x in mets])} h; at the first sample ({_rng(firsts)} h) concentrations were already "
           f"{_rng(fr)} % of Cmax" + (f", and the rise of {c_} is described by {len(m_['increments'])} increments" if m_["n_before_peak"] >= 2 else "") + ".")
    basis = f"This is read from the observed maximum and the samples before it ({c_}: {m_['n_before_peak']} sample{'s' if m_['n_before_peak'] != 1 else ''} before Tmax)."
    reach = (level + (f" ka is not identifiable in {len(kani)} of {n} curves (fewer than 2 samples before Tmax)." if kani else "")
             + " Zero- and first-order input are not told apart from observed points.")
    if indiv(d_):
        pa = pInd(d_["card"], ind_series(d_), d_["card"]["record_level"] == "INDIVIDUAL", log=False, mark_tmax=True, early=True,
                  title=f"{d_['card']['dataset_id']}: Tmax per animal")
        pa = pa if isinstance(pa, list) else [pa]
    else:
        pa = [pA1(d_["card"], m_, src(d_, s_), marks=("tmax", "zero", "blq"), frac=True, title=f"{c_}: to the first sample after Tmax (linear)")]
    if m_["n_before_peak"] >= 2 and len(pa) == 1:
        pa.append(pA3(d_["card"], m_, src(d_, s_)))
    if len(pa) > 2:  # small multiples, one panel per animal
        f = draw(2, pa, 12, 2.5 * -(-len(pa) // 4) + 0.2, ncol=4)
    else:  # stacked, so the panel keeps its size beside the text
        f = draw(2, pa, 5.6, 3.7 * len(pa), ncol=1)
    put(2, obs, basis, reach, ["at least 2 samples before Tmax"] if kani else [],
        _prim(f, ["A1"] + (["A3"] if len(pa) == 2 else []), 2, f"Tmax {_rng([x[3]['tmax'] for x in mets])} h"
              + (f"; KA_NOT_IDENTIFIABLE in {len(kani)}/{n}" if kani else ""), _level_text([d_["card"]])))


def _bq_excluded_shapes(group, level, mets, put):
    """Q3 excluded combinations (T1, T2); returns the T2 curves for Q4. Part of board_questions (split 2026-11-26 without change)."""
    c_, d_, s_, m_ = max(mets, key=lambda x: x[3]["mt1"])
    wi, wj = m_["mt1_witness"]
    count = sum(m["mt1"] > 0 for *_, m in mets)
    obs = (f"C/t rose beyond the assumed ±5 % tolerance in {count} of {len(mets)} profiles. "
           f"The largest margin was {m_['mt1']:.3g} at {wi:.3g} and {wj:.3g} h in {c_}. "
           "The study does not establish an error bound for excluding a non-increasing input.")
    t2i = [(x, x[2]["t2"]) for x in mets if x[2].get("t2") and x[1]["card"]["record_level"] != "GROUP_MEAN"]
    if t2i:
        obs += f" T2 on {len(t2i)} single-animal curves: {'/'.join(sorted({t['t2_label'] for _, t in t2i}))}."
    basis = "This rests on C/t at every quantified sample with ±5 % intervals; the error bound is project-set (SENSITIVITY_ONLY)."
    reach = level + " Keep immediate input as the reference when checking fixed lag and transit."
    t2pick = next((x for x, t in t2i if x[2].get("T2")), None)
    if t2pick:
        prim = _prim(t2pick[2]["T2"], ["T2"], 3, f"T2 {t2pick[2]['t2']['t2_label']} · M_T2 {t2pick[2]['t2']['t2_margin']:.3g}", _level_text([t2pick[1]["card"]]))
    else:
        prim = _prim(s_.get("A1"), ["A1"], 3, f"T1 {m_['t1_label']}" + "".join(" + " + x for x in m_["t1_flags"]) + f" · max M_T1 {m_['mt1']:.3g}",
                     _level_text([d_["card"]])) if s_.get("A1") else None
    put(3, obs, basis, reach, ["analytical error of the assay (the ±5 % bound is project-set)"]
        + (["serial samples of single animals (for T2)"] if group else []), prim)
    return t2i


def _bq_second_rise(draw, level, mets, put, src, t2i):
    """Q4 second rise. Part of board_questions (split 2026-11-26 without change)."""
    if t2i:
        # A4: T2 applies only to verified serial animals with a drug-free baseline; other records are described only
        applies = [(x, t) for x, t in t2i if t.get("t2_label") != "DESCRIPTIVE_ONLY"]
        shown = [x for x, t in applies if t.get("robust")]
        weak = [x for x, t in applies if t.get("valley") and not t.get("robust")]
        desc = [x for x, t in t2i if t.get("valley") and t.get("t2_label") == "DESCRIPTIVE_ONLY"]
        cond = (" T2 does not apply to " + str(len(t2i) - len(applies)) + " of these records (identity not verified, destructive "
                "sampling, or drug-free baseline unresolved); they are described only.") if len(applies) < len(t2i) else ""
        if shown or weak or desc:
            x = (shown or weak or desc)[0]
            t = x[2]["t2"]
            untestable = bool((t.get("removal") or {}).get("not_assessable"))
            obs = (f"A dip and a second rise beyond ±5 % in {len(shown)} of {len(applies)} single-animal curves ({_names([y[0] for y in shown])})."
                   if shown else f"A dip and a second rise in {_names([y[0] for y in weak])}, " +
                   ("which could not be rechecked with a sample removed." if untestable else "resting on one sample.")
                   if weak else f"A dip and a second rise in {_names([y[0] for y in desc])}, described only.")
            basis = (f"This rests on three samples of {x[0]} ({', '.join(f'{v:g}' for v in t['valley'])} h) with ±5 % intervals; "
                     + ("The dip survives dropping any one sample within the assumed tolerance." if shown else
                        "Removal robustness is unknown (too few samples for a rerun)." if weak and untestable else
                        "The dip depends on one sample." if weak else
                        "These records are not verified serial curves of one animal with a drug-free baseline."))
            prim = _prim(x[2].get("T2"), ["T2"], 4, f"T2 {t['t2_label']} · M_T2 {t['t2_margin']:.3g}", _level_text([x[1]["card"]]))
        else:
            c_, d_, s_, m_ = max(mets, key=lambda x: len(x[3]["_t"]) - int(np.argmax(x[3]["_c"])))
            obs = f"No dip and second rise beyond the assumed ±5 % tolerance in the {len(t2i)} single-animal curves."
            basis = f"This rests on all post-peak samples of each curve ({c_} shown)."
            prim = _prim(draw(4, [pB1(d_["card"], m_, src(d_, s_), marks=("blq",), highlight_post=True, title=f"{c_}: post-peak samples (semi-log)")], 6.2, 3.8),
                         ["B1"], 4, "No dip beyond the assumed tolerance", _level_text([d_["card"]]))
        put(4, obs, basis, level + cond + " The cause of a second rise is not identified.", [], prim)
    else:
        vals = []
        for c, d, s, m in mets:
            r = t2_curve(s["points"])
            if r["t2_margin"] is not None:
                vals.append((c, d, s, m, r))
        if vals:
            c_, d_, s_, m_, r = vals[0]
            a, bb, cc = r["valley_idx"]
            t, cv = r["_t"], r["_c"]
            unit = d_["card"]["unit"]
            obs = (f"The group mean of {c_} dips at {t[bb]:.3g} h ({cv[bb]:.3g} {unit}) between {t[a]:.3g} h and {t[cc]:.3g} h and rises again; "
                   f"the dip is larger than ±5 % (margin {r['t2_margin']:.3g} {unit})"
                   + (f". Dips are also seen on {_names([v[0] for v in vals[1:]])}." if len(vals) > 1 else "."))
            basis = ("This rests on these three points of the mean curve" + ("." if r["robust"] else
                     ", and could not be rechecked with a point removed (LOO_NOT_ASSESSABLE)." if (r.get("removal") or {}).get("not_assessable")
                     else ", and on one point only (SINGLE_POINT_SUPPORT)."))
            reach = ("Group mean of different animals; whether single animals have two peaks cannot be judged "
                     "(averaging single-peaked curves can create a dip).")
            mi = {"_t": t, "_c": cv, "cmax": max(cv)}
            if cv[bb] >= 0.2 * max(cv):
                pan = pA1_dip(d_["card"], mi, src(d_, s_), (a, bb, cc), title=f"{c_}: whole profile (linear)")
            else:
                pan = pB1(d_["card"], m_, src(d_, s_), marks=("blq",), valley=(a, bb, cc), title=f"{c_}: whole profile (semi-log)")
            prim = _prim(draw(4, [pan], 6.4, 3.8), ["A1" if cv[bb] >= 0.2 * max(cv) else "B1"], 4,
                         f"Dip at {t[bb]:.3g} h, margin {r['t2_margin']:.3g} {unit} (description; T2 does not apply to group means)", _level_text([d_["card"]]))
            put(4, obs, basis, reach, ["serial samples of single animals (for T2)"], prim)
        else:
            post = [x for x in mets if len(x[3]["_t"]) - int(np.argmax(x[3]["_c"])) - 1 >= 2]
            if post:
                c_, d_, s_, m_ = max(post, key=lambda x: len(x[3]["_t"]) - int(np.argmax(x[3]["_c"])))
                prim = _prim(draw(4, [pB1(d_["card"], m_, src(d_, s_), marks=("blq",), highlight_post=True, title=f"{c_}: post-peak samples (semi-log)")], 6.2, 3.8),
                             ["B1"], 4, "No dip beyond ±5 % (description)", _level_text([d_["card"]]))
                put(4, f"No dip and second rise beyond ±5 % on the mean curve{'s' if len(mets) > 1 else ''} of {_names([x[0] for x in mets])}.",
                    f"This rests on all post-peak samples of {len(post)} curve{'s' if len(post) > 1 else ''} ({c_} shown).",
                    "Group means can hide a second peak in single animals.", ["serial samples of single animals (for T2)"], prim)
            else:
                put(4, "Too few samples after the peak to look for a dip.", "", level, ["at least 2 samples after the peak"], None, status=ST_NO)


def _bq_tail(central, curves, draw, ds, ev_iv_res, group, ids, ivs, level, mets, put, src):
    """Q5 long tail and flip-flop; returns what Q6 reuses. Part of board_questions (split 2026-11-26 without change)."""
    unpaired_iv = _iv_unpaired_text(ivs, ds)
    evr = next((r for r in ev_iv_res if r["ev"] in ids), None)
    pairs = [r for d in central for r in d.get("iv_pairs") or []]
    d1d = next((d for d in central if d.get("D1d")), None)
    ths = [(x, (x[3].get("terminal_selected") or {}).get("thalf")) for x in mets]
    flat = [x for x in mets if (x[3].get("split") or {}).get("class") == "DECLINE_FLATTENS"]
    steep = [x for x in mets if (x[3].get("split") or {}).get("class") == "DECLINE_STEEPENS"]
    if pairs:
        rows5 = []
        for r in pairs:
            e_th = (r["_em"].get("terminal_selected") or {}).get("thalf"); i_th = (r["_im"].get("terminal_selected") or {}).get("thalf")
            rows5.append(f"animal {r['subject_id']} {_th_text(e_th)} vs {_th_text(i_th)}"
                         + (f" ({_ratio_txt(e_th / i_th)}×, {_ff_word((r.get('tail') or {}).get('flip_flop_reading'))})" if e_th and i_th else ""))
        ffc = {}
        for r in pairs:
            w = _ff_word((r.get("tail") or {}).get("flip_flop_reading"))
            ffc[w] = ffc.get(w, 0) + 1
        t4 = {}
        for r in pairs:
            t4[r.get("t4_label")] = t4.get(r.get("t4_label"), 0) + 1
        n = len(pairs)
        obs = ("Flip-flop reading within animals: " + "; ".join(f"{k} in {v}" for k, v in sorted(ffc.items())) + ". "
               f"{n} animal{'s' if n != 1 else ''} received both the extravascular route and IV with a stated washout. "
               f"Apparent t½ after extravascular dosing against IV in the same animal: " + "; ".join(rows5) + ".")
        basis = ("This rests on the terminal windows of each animal's dose-normalized EV and IV curves and on Q = C_EV / C_IV at matched "
                 "times within the animal (T4: " + ", ".join(f"{k} in {v}" for k, v in sorted(t4.items(), key=lambda kv: str(kv[0]))) + "; T4 tests a shared "
                 "one-compartment disposition, not flip-flop).")
        reach = (level + " Comparisons are within animals; a slower EV decline points to an absorption-limited tail only when it holds "
                 "across comparable windows." + ((f" {d1d['card']['dataset_id']}: " + d1d["D1d_reason"]) if d1d else ""))
        prim = _prim(draw(5, pD1a(pairs), 4.2 * min(n, 3), 3.4 * -(-n // 3) + 0.2, ncol=min(n, 3)), ["D1a"], 5,
                     f"{n} within-animal EV/IV pairs, dose-normalized", level)
        put(5, obs, basis, reach, [], prim)
    elif evr:
        em = next(s["metrics"] for d, s in curves if d["card"]["dataset_id"] == evr["ev"])
        im = next((i["metrics"] for i in ivs if i["card"]["dataset_id"] == evr["iv"]), {})
        e_th = (em.get("terminal_selected") or {}).get("thalf"); i_th = (im.get("terminal_selected") or {}).get("thalf")
        tc = evr.get("tail") or {}
        reading = tc.get("flip_flop_reading")
        if e_th and i_th and reading == "NOT_ASSESSABLE":
            # R9: no qualified window on one side; the selected-window half-lives are described, not read
            ind = [x for x in ff_indirect_comparators(mets) if x["ev_dataset"] == evr["ev"]]
            g_ = hl_grade(e_th / i_th)
            obs = (f"Flip-flop reading: {tc.get('reading_text') or 'not assessable'}. Selected-window apparent t½ {e_th:.3g} h ({evr['ev']}) "
                   f"against {i_th:.3g} h ({evr['iv']}), ratio {_ratio_txt(e_th / i_th)} ({HL_WORDS[g_].replace(' than', '').replace(' to', '')}), "
                   "description only" + (f" ({_tail_test_text(tc)})" if tc.get("test") else "")
                   + "; this is not evidence for or against an absorption-limited tail."
                   + (" Indirect comparator (INDIRECT_COMPARATOR): " + ff_indirect_text(ind) + "." if ind else ""))
        elif e_th and i_th and tc.get("terminal_difference_grade"):
            grade, rr = tc["terminal_difference_grade"], tc["ratio_range"]
            obs = ((f"Flip-flop reading: {tc['reading_text']}. " if tc.get("reading_text") else "")
                   + f"The selected-window decline after extravascular dosing is {HL_WORDS[grade]} the decline after IV in the same study: apparent t½ {e_th:.3g} h "
                   f"({evr['ev']}) against {i_th:.3g} h ({evr['iv']}), ratio {_ratio_txt(tc['ratio'])}"
                   + (f" (range {rr[0]:.2f}–{rr[1]:.2f} over {tc['n_window_pairs']} qualified window pairs)" if (tc.get("n_window_pairs") or 0) > 1 and rr else "") + ". ")
            if reading == "UNRESOLVED":
                obs += "The qualified window pairs give different readings, so the directional reading is unresolved; this is not evidence against flip-flop."
            elif reading == "COMMON_TERMINAL_COMPATIBLE":
                obs += "Parallel declines are compatible with a common terminal process; this does not point to an absorption-limited tail."
            elif reading == "EV_STEEPER_REVIEW":
                obs += "Check the selected intervals, the distribution phase, arm differences and data quality."
            else:
                obs += (f"{_tail_test_text(tc).capitalize()}; " + ("this points to an absorption-limited tail."
                        if _matched_slow_tail(evr, tc) else "this is a hint of an absorption-limited tail, not an established one."))
        elif e_th and i_th:
            obs = (f"Apparent t½ {e_th:.3g} h ({evr['ev']}) against {i_th:.3g} h ({evr['iv']}); the two terminal windows could not be compared.")
        else:
            obs = f"An IV curve exists ({evr['iv']}), but no terminal window with span ratio ≥ {SPAN_MIN:g} could be read on both curves."
        basis = (f"This rests on the terminal windows of both dose-normalized curves and on Q = C_EV / C_IV at matched times "
                 f"(T4 = {evr.get('t4_label')}{' + ' + '+'.join(evr.get('t4_flags', [])) if evr.get('t4_flags') else ''}; T4 tests a shared "
                 "one-compartment disposition, not flip-flop).")
        reach = level + (" Group means assume a common k." if group else "")
        if tc.get("test"):
            reach += " The slope p is nominal across selected time points, not an animal-level test or proof of flip-flop; compare common late windows and individual curves."
        reach += " " + _common_tail_text(tc)
        if evr.get("D1"):
            prim = _prim(evr["D1"], ["D1"], 5, f"T4 {evr.get('t4_label')} · EV t½ {_th_text(e_th)} vs IV {_th_text(i_th)}", _level_text([d["card"] for d in central]))
        else:
            d_, s_ = next((d, s) for d, s in curves if d["card"]["dataset_id"] == evr["ev"])
            prim = _prim(draw(5, [pB1(d_["card"], em, src(d_, s_), marks=("blq", "terminal", "split"), title=f"{evr['ev']}: decline (semi-log)")], 6.4, 3.8),
                         ["B1"], 5, f"EV apparent t½ {_th_text(e_th)}; D1 not drawn (no tier-1 trigger)", _level_text([d_["card"]]))
        put(5, obs, basis, reach, ["individual data (T4 without a common-k assumption)"] if group else [], prim)
    else:
        # L5: the split-half slopes are a description even when no ratio is formed (a half not declining, or an early slope
        # not distinguished from zero)
        cand = [x for x in mets if x[3].get("terminal_selected") or x[3].get("split")]
        if cand:
            c_, d_, s_, m_ = (flat or [x for x in cand if x[3].get("terminal_selected")] or cand)[0] if flat else max(
                cand, key=lambda x: ((x[3].get("terminal_selected") or {}).get("n", 0), len(x[3]["_t"])))
            tv = [v for _, v in ths if v]
            ind = ff_indirect_comparators(mets)
            obs = ("Flip-flop reading: not assessable (IV: " + ("no verified cross-route pairing for the retained IV curves" if unpaired_iv
                                                                else "no same-study, same-species IV curve") + "). "
                   + (f"Apparent terminal t½ {_rng(tv)} h (description)" if tv else "No qualified terminal window (span ratio < 2)")
                   + (f"; the late decline flattens in {_names([x[0] for x in flat])}" if flat else "")
                   + (f"; it steepens in {_names([x[0] for x in steep])}" if steep else "") + "."
                   + (" Indirect comparator (INDIRECT_COMPARATOR): " + ff_indirect_text(ind) + "." if ind else ""))
            sel = m_.get("terminal_selected")
            basis = (f"This rests on the selected terminal window of {c_} ({sel['n']} points from {sel['start']:.3g} h, span ratio "
                     f"{(sel.get('span_ratio') or 0):.2g}) and its split-half slopes." if sel else f"This rests on the split-half slopes of {c_}.")
            reach = ((unpaired_iv + " ") if unpaired_iv else "Without an IV curve of the same study and species, ") + (
                     "An absorption-limited tail and slow elimination remain unresolved; the apparent t½ is not passed on as k.")
            over = [pD1d(*d1d["_D1d_args"])[0]] if d1d else []
            prim = _prim(draw(5, [pB1(d_["card"], m_, src(d_, s_), marks=("blq", "terminal", "split"), title=f"{c_}: decline (semi-log)")] + over,
                              12.4 if over else 6.4, 3.8 if not over else 4.1),
                         ["B1"] + (["D1d"] if over else []), 5, (f"Apparent t½ {sel['thalf']:.3g} h" if sel else "No terminal window")
                         + (f"; {(m_.get('split') or {}).get('class')}" if (m_.get("split") or {}).get("ratio") is not None else ""), _level_text([d_["card"]]))
            put(5, obs, basis, reach, ["verified cross-route identity, period order and washout" if unpaired_iv else "a same-study, same-species IV curve"], prim, status=ST_PART)
        else:
            put(5, "Fewer than 3 samples after the peak, so no terminal window can be read.", "", level,
                ["at least 3 post-peak samples", "a same-study, same-species IV curve"], None, status=ST_NO)
    return d1d, evr, pairs, unpaired_iv


def _bq_extent(central, d1d, draw, ev_iv_res, evr, ids, level, pairs, pss, put, unpaired_iv):
    """Q6 extent. Part of board_questions (split 2026-11-26 without change)."""
    pr6 = [r for r in pairs if r.get("window_auc_ratio") is not None]
    if pr6:
        vals = sorted(r["window_auc_ratio"] for r in pr6)
        obs = ("Within-animal dose-normalized EV/IV AUC ratio over the common observed window: "
               + "; ".join(f"animal {r['subject_id']} {r['window_auc_ratio']:.3g} ({_ratio_window_text(r)})" for r in pr6)
               + (f"; range {vals[0]:.3g}–{vals[-1]:.3g}, median {float(np.median(vals)):.3g} over {len(vals)} animals." if len(vals) > 1 else "."))
        sts = sorted({r["f_status"] for r in pr6})
        cav = sorted({x for r in pr6 for x in r.get("f_caveats", [])})
        k6 = len(pr6)
        d2s = [pD2(r["_ev_card"], r["_em"], r["_iv_card"], r["_im"], r).set(
            title=f"Animal {r['subject_id']}: AUC ratio {r['window_auc_ratio']:.3g}", legend="none", caption=None) for r in pr6]
        prim = _prim(draw(6, d2s, 4.2 * min(k6, 3), 3.4 * -(-k6 // 3) + 0.4, ncol=min(k6, 3)), ["D2"], 6,
                     f"Within-animal finite-window AUC ratio {vals[0]:.3g}–{vals[-1]:.3g} ({k6} animals)", level)
        put(6, obs, "Each ratio uses one animal's EV and IV curves on identical observed support, linear-up/log-down, with no extrapolation.",
            f"Ratio status = {', '.join(sts)}; " + ("window-based estimates of systemic bioavailability that depend on the fitted terminal slopes"
                                                    if sts == ["WINDOW_BASED_ESTIMATE"] else "these are neither absolute F nor bounds on F") + f" ({', '.join(cav)})."
            + ((f" {d1d['card']['dataset_id']}: " + d1d["D1d_reason"]) if d1d else ""), [], prim, status=ST_PART)
    elif evr and evr.get("window_auc_ratio") is not None:
        evs6 = [x for x in ev_iv_res if x["ev"] in ids and x.get("window_auc_ratio") is not None]
        obs = " ".join(f"{x['ev']} / {x['iv']}: over {_ratio_window_text(x)}, the dose-normalized EV/IV AUC ratio is {x['window_auc_ratio']:.3g}. "
                        + _source_f_text(x) for x in evs6)
        prim = _prim(evr.get("D2"), ["D2"], 6, f"Finite-window AUC ratio {evr['window_auc_ratio']:.3g}; absolute F not recomputed", _level_text([d["card"] for d in central]))
        put(6, obs, "Both areas use identical observed support and linear-up/log-down interpolation, with no extrapolation.",
            f"Ratio status = {evr['f_status']} ({_f_reason(evr)}); " + ("a window-based estimate of systemic bioavailability that depends on the fitted terminal slopes"
                                                    if evr["f_status"] == "WINDOW_BASED_ESTIMATE" else "this is neither absolute F nor a bound on F") + f" ({', '.join(evr.get('f_caveats', []))}).",
            [{"EARLY_EXPOSURE_OUTSIDE_WINDOW": "observations before the common interval", "GROUP_MEAN": "individual curves",
              "IV_MODE_UNKNOWN": "the IV administration mode"}.get(x, "") for x in evr.get("f_caveats", [])], prim)
    elif evr:
        put(6, f"f_status = {evr.get('f_status', 'NOT_ESTIMABLE')}: {_f_reason(evr)}.", "", level, ["an IV curve with a common window"], None)
    else:
        f_ = next(((ps["card"], ps["analysis"]["f"]) for ps in pss if (ps.get("analysis") or {}).get("f")), None)
        source_cards = [d["card"] for d in central if d["card"].get("source_reported_absolute_f")]
        if source_cards:
            put(6, " ".join(_source_f_text(c) for c in source_cards),
                "These are source-level parameters with the authors' exposure definition; absolute F was not independently recomputed.",
                (unpaired_iv or "No eligible curve comparison is available.") + " No cross-route individual pairing is inferred.", [],
                _row(6, ["Dataset", "Source-reported absolute F", "Method"],
                     [[c["dataset_id"], f"{100*c['source_reported_absolute_f']['fraction']:g}%", c['source_reported_absolute_f']['method']] for c in source_cards],
                     "SOURCE_REPORTED_ABSOLUTE_F", "Reported parameter"), status=ST_PART)
        elif f_:
            put(6, f"Reported F = {f_[1]['value']:.2f} ({f_[0]['dataset_id']}, as printed).",
                "This is taken as printed (A0.12); it is checked against the dose basis and linearity, not recomputed.",
                "Flags: " + (", ".join(f_[1]["flags"]) or "none") + ".", [],
                _row(6, ["Dataset", "F", "Flags"], [[f_[0]["dataset_id"], f"{f_[1]['value']:.2f}", ", ".join(f_[1]["flags"]) or "none"]],
                     "f_status SOURCE_REPORTED", "Reported parameter"), status=ST_PART)
        else:
            put(6, unpaired_iv or "No IV curve from this study and species, so the fraction of the dose that reaches the circulation cannot be computed.",
                "f_status = NOT_ESTIMABLE.", "", ["verified cross-route identity, period order and washout" if unpaired_iv else "a same-species IV curve with a consistent dose basis"], None)


def _bq_conditions(cond_res, draw, ds, ids, level, put):
    """Q8 conditions. Part of board_questions (split 2026-11-26 without change)."""
    crs = next((r for r in cond_res if {r["a"], r["b"]} <= ids), None)
    if crs:
        r = crs
        cs = [x["c"] for x in r.get("intervals") or []]
        diff = ", ".join(_ATTR.get(x, x.replace("_", " ")) for x in r["differing_attributes"])
        if cs and r["c_lower"] > r["c_upper"]:
            obs = (f"{r['a']} against {r['b']} (differing: {diff}): the sampled ratios span {min(cs):.2f}–{max(cs):.2f}. "
                   "No common scale fits within the assumed tolerance. Check measurement uncertainty before attributing a shape difference to absorption.")
        elif cs:
            obs = (f"{r['a']} against {r['b']} (differing: {diff}): a common factor in "
                   f"{r['c_lower']:.2f}–{r['c_upper']:.2f} fits all matched times within the assumed tolerance.")
        else:
            obs = f"{r['a']} against {r['b']}: {r.get('t5_reason', r['t5_label'])}."
        basis = (f"This rests on c = C_A / C_ref at {len(cs)} matched times with ±5 % intervals (T5 = {r['t5_label']}"
                 + ("".join(" + " + x for x in r.get("t5_flags", []))) + ")." if cs else "")
        reach = level + (" The two curves differ in more than one attribute, so the comparison is confounded." if r["confounded"] else "")
        prim = None
        if r.get("intervals"):
            a_ = next(d for d in ds if d["card"]["dataset_id"] == r["a"]); b_ = next(d for d in ds if d["card"]["dataset_id"] == r["b"])
            prim = _prim(draw(8, [pE1(a_["card"], a_["series"][0]["metrics"], b_["card"], b_["series"][0]["metrics"]), pE2(r)], 5.8, 7.4, ncol=1),
                         ["E1", "E2"], 8, f"T5 {r['t5_label']} · rate-only check {r.get('rate_only_label', '—')}", _level_text([a_["card"], b_["card"]]))
        put(8, obs, basis, reach, [r["rate_only_reason"]] if r.get("rate_only_label") == "CANNOT_ASSESS" and r.get("rate_only_reason") else [], prim)
    else:
        put(8, "No two curves of this study differ by route or condition (dose differences are under question 7).", "", "", [], None)


def _bq_individuals(central, draw, ind_series, indiv, put):
    """Q9 individuals or averaging. Part of board_questions (split 2026-11-26 without change)."""
    levels = {d["card"]["record_level"] for d in central}
    dind = next((d for d in central if indiv(d)), None)
    if dind and levels & {"INDIVIDUAL", "INDIVIDUAL_IDENTITY_UNVERIFIED"}:
        ver = dind["card"]["record_level"] == "INDIVIDUAL"
        sl = ind_series(dind)
        obs = (f"{len(sl)} {'animals' if ver else 'source labels'} in {dind['card']['dataset_id']}: Tmax {_rng([s['metrics']['tmax'] for s in sl])} h, "
               f"Cmax/D {_rng([s['metrics']['cmax'] / (_given(s, dind['card']) or 1) for s in sl])}.")
        basis = ("This rests on each animal's own serial curve (individual layer)." if ver else
                 "This rests on the values as labelled in the source, shown as points.")
        reach = _level_text([dind["card"]]) + ("" if ver else " These are not single-animal curves.")
        p1 = pInd(dind["card"], sl, ver, log=False); p2 = pInd(dind["card"], sl, ver, log=True)
        if isinstance(p1, list):
            f = dind.get("A1ind"); pids = ["A1ind"]
        else:
            f = draw(9, [p1, p2], 6.2, 7.6, ncol=1); pids = ["A1ind", "B1ind"]
        put(9, obs, basis, reach, [] if ver else ["verified cross-time identity of the animals"],
            _prim(f, pids, 9, ("Serial individual sampling" if ver else "Identity not verified: points only"), _level_text([dind["card"]])))
    else:
        destr = [d for d in central if _destructive(d["card"])]
        if destr:
            put(9, "Each time point comes from different animals (destructive sampling), so single-animal curves do not exist.",
                f"This rests on the data card of {_names([d['card']['dataset_id'] for d in destr])}.",
                "Whether the mean shape is shared or produced by averaging cannot be judged in principle.",
                ["serial curves from several animals"],
                _row(9, ["Dataset", "Record level", "n per time", "Sampling"],
                     [[d["card"]["dataset_id"], _data_level(d["card"]), _n_text(d["card"]) or "not reported", "different animals at each time"] for d in destr],
                     "Destructive sampling", _level_text([d["card"] for d in destr])))
        else:
            put(9, "Group means only: single-animal curves are not reported.", "",
                "Whether the mean shape is shared or produced by averaging cannot be judged.", ["serial curves from several animals"], None)


def board_questions(b, ds, pss, dose_series_res, ev_iv_res, cond_res, ivs=(), out=None):
    rows, ev = b["rows"], b.get("evidence") or {}
    slug = re.sub(r"[^A-Za-z0-9]+", "_", _board_key(b))
    sp = _study_panels(ds, pss, dose_series_res, ev_iv_res, cond_res)
    central = [d for d in ds if d["card"]["tests_allowed"]]
    curves = [(d, s) for d in central for s in d["series"] if "tmax" in s["metrics"]]
    ids = {d["card"]["dataset_id"] for d in ds}
    params = [p for ps in pss for p in ps["params"]]
    qs = {}

    def evid(qn):
        return ev.get(str(qn), [])

    def put(qn, observed, basis, reach, missing=(), primary=None, status=None):
        st = status or rows[qn][0]
        qs[qn] = _q(qn, st, observed, basis, reach, missing, primary, _views_for(qn, sp, primary), evid(qn))

    def draw(name, panels, width, height, widths=None, ncol=None):
        return _figure(out, f"Q{_QFILE.get(name, name)}_{slug}.png", "", panels, width, height, widths, ncol) if out is not None else None

    def src(d, s):
        return {"series_id": s["series_id"], "points": s["points"], "label": s["label"] if len(d["series"]) > 1 else "",
                **{k: s[k] for k in ("dose_events", "_later_points", "dose_given", "dose", "iv_input") if k in s}}

    def indiv(d):
        return d["card"]["series_kind"] == "INDIVIDUALS" and len([s for s in d["series"] if "tmax" in s["metrics"]]) > 1

    def ind_series(d):
        return [s for s in d["series"] if "tmax" in s["metrics"]]

    if curves:
        mets = [(_cid(d, s), d, s, s["metrics"]) for d, s in curves]
        n = len(mets)
        level = _level_text(d["card"] for d in central)
        group = all(d["card"]["record_level"] == "GROUP_MEAN" for d in central)
        firsts = [m["first_t"] for *_, m in mets]
        # Q1 onset and delay
        _bq_onset(curves, draw, firsts, ind_series, indiv, level, mets, n, put, src)
        # Q2 input speed
        _bq_input_speed(draw, firsts, ind_series, indiv, level, mets, n, put, src)
        # Q3 excluded combinations (T1, T2)
        t2i = _bq_excluded_shapes(group, level, mets, put)
        # Q4 second rise
        _bq_second_rise(draw, level, mets, put, src, t2i)
        # Q5 long tail and flip-flop
        d1d, evr, pairs, unpaired_iv = _bq_tail(central, curves, draw, ds, ev_iv_res, group, ids, ivs, level, mets, put, src)
        # Q6 extent
        _bq_extent(central, d1d, draw, ev_iv_res, evr, ids, level, pairs, pss, put, unpaired_iv)
        # Q7 dose dependence
        _q7(qs, put, draw, b, ds, pss, dose_series_res, ids, level)
        # Q8 conditions
        _bq_conditions(cond_res, draw, ds, ids, level, put)
        # Q9 individuals or averaging
        _bq_individuals(central, draw, ind_series, indiv, put)
    else:
        why = ("No curve of this study passes the test gates: " + "; ".join(sorted({_GATE_WHY.get(g, g) for d in ds for g in d["card"]["gates"]
                                                                                     if g in _GATE_WHY})) + ".") if ds else \
            "Reported parameters only: this question needs concentration points."
        for qn in range(1, 10):
            put(qn, why, "", "Overview panels only (A1, B1); no test runs." if ds else "Reported parameters as printed (A0.12).",
                ["a plasma, serum or blood curve after a single first dose"] if ds else ["concentration–time points"], None, status=rows[qn][0] if rows[qn][0] in (ST_NO, ST_NA) else ST_NO)
        tm = [p for p in params if p["param"] == "TMAX"]
        if tm and rows[2][0] == ST_PART:
            put(2, f"Reported Tmax {_rng([p['value'] for p in tm])} {tm[0].get('unit') or ''} (as printed).", "This is taken as printed (A0.12).",
                "Reported parameters; the rise cannot be described.", ["concentration–time points"],
                _fprim(draw, 2, pss, "TMAX", "Reported Tmax by dose"))
        th = [p for p in params if p["param"] == "THALF"]
        if th and rows[5][0] == ST_PART:
            put(5, f"Reported extravascular t½ {_rng([p['value'] for p in th])} {th[0].get('unit') or ''} (as printed).",
                "This is taken as printed (A0.12).", "A description only, not a disposition t½.", ["a same-study IV curve"],
                _fprim(draw, 5, pss, "THALF", "Reported t½ by dose"))
        f_ = next(((ps["card"], ps["analysis"]["f"]) for ps in pss if (ps.get("analysis") or {}).get("f")), None)
        if f_:
            put(6, f"Reported F = {f_[1]['value']:.2f} ({f_[0]['dataset_id']}, as printed).",
                "This is taken as printed (A0.12); it is checked against the dose basis and linearity, not recomputed.",
                "Flags: " + (", ".join(f_[1]["flags"]) or "none") + ".", [],
                _row(6, ["Dataset", "F", "Flags"], [[f_[0]["dataset_id"], f"{f_[1]['value']:.2f}", ", ".join(f_[1]["flags"]) or "none"]],
                     "f_status SOURCE_REPORTED", "Reported parameter"), status=rows[6][0] if rows[6][0] != ST_NO else ST_PART)
        _q7(qs, put, draw, b, ds, pss, dose_series_res, ids, _level_text([d["card"] for d in ds]) if ds else "Reported parameters.")
        if ds:
            gated = [v for pid in ("A1", "A1w", "B1") for v in sp.get(pid, [])]
            qs[1]["views"] = sorted(gated, key=lambda v: v["tier"])
    comparisons = _meal_contrasts(pss)
    if comparisons:
        description = " ".join(f"At {r['dose']:g} {r['dose_unit']}, {r['condition']} {r['endpoint']} was {r['ratio']:.0%} of the {r['reference_condition']} value."
                               for r in comparisons)
        if qs[8]["status"] in (ST_NA, ST_NO):
            put(8, description, "Ratios use reported group parameters at the same dose, route, occasion and endpoint.",
                "This describes exposure. Absorption rate, clearance and the shape of the fed curve remain unresolved.",
                ["matched concentration-time curves and group uncertainty"], status=ST_PART)
        qs[8]["reported_condition_comparisons"] = comparisons
        qs[8]["evidence"].append({"rule": "Compare like reported endpoints descriptively (item 23).",
            "data": sorted({v for r in comparisons for v in r["datasets"]}),
            "tables": [{"caption": "Reported fed and fasted group endpoints", "head": ["Endpoint", "Dose", "Fed", "Fasted", "Unit", "Source records"],
                        "rows": [[r["endpoint"], f"{r['dose']:g} {r['dose_unit']}", r["fed"], r["fasted"], r["unit"], ", ".join(r["records"])] for r in comparisons]}]})
    if qs[9]["status"] in (ST_NA, ST_NO) and (ranges := _repeat_individual_ranges(ds)):
        r = ranges[0]
        put(9, f"At {r['time_h']:g} h in {r['dataset']}, observed concentrations ranged from {r['min']:g} to {r['max']:g} {r['unit']} across {r['n']} animals.",
            "Each comparison uses identified animals at the same dose and sampled time on the same dosing occasion.",
            "The spread is descriptive. These repeated-dose measurements do not identify first-dose absorption or between-animal variation in ka.",
            ["comparable first-dose profiles to assess variation in absorption rate"], status=ST_PART)
        qs[9]["observed_individual_ranges"] = ranges
        qs[9]["evidence"].append({"rule": "Individual observations remain descriptive when first-dose tests are gated.",
            "data": sorted({r["dataset"] for r in ranges}), "tables": [{"caption": "Within-group observed concentrations",
            "head": ["Dataset", "Dose (mg/kg)", "Time (h)", "Animals", "Minimum", "Maximum", "Unit"],
            "rows": [[r[k] for k in ("dataset","dose","time_h","n","min","max","unit")] for r in ranges]}]})
    pairs_all = [r for r in ev_iv_res if r["ev"] in ids] + [r for d in ds for r in d.get("iv_pairs") or []]
    return _guide_rows(qs, sp, [(_cid(d, s), s["metrics"]) for d, s in curves], pairs_all,
                       _level_text(d["card"] for d in central) if central else "", _iv_unpaired_text(ivs, ds) or "")


_GATE_WHY = {"NOT_CENTRAL_MATRIX": "the matrix is not plasma, serum or blood", "NOT_SINGLE_DOSE": "the curves do not follow a single first dose",
             "ENDOGENOUS_REVIEW_REQUIRED": "total signal includes an endogenous or mixed contribution; exogenous input requires assay review",
             "UNRESOLVED_DUPLICATE_TIMES": "duplicate sampling times need animal, occasion or replicate resolution",
             "NOT_EV": "the route is not extravascular", "ROUTE_UNKNOWN": "the route is not stated",
             "INSUFFICIENT_QUANTIFIED_POINTS": "fewer than 3 quantified positive post-dose points remain in every curve"}


def _fprim(draw, qn, pss, name, label_line):
    """Reported-parameter primary evidence: only this question's parameter against dose (panel F)."""
    ps = next((ps for ps in pss if any(p["param"] == name and p["dose"] for p in ps["params"])), None)
    pans = pF(ps["card"], [p for p in ps["params"] if p["param"] == name]) if ps else []
    if not pans:
        return None
    pr = _prim(draw(qn, pans[:1], 5.2, 3.6), ["F"], qn, label_line, "Reported parameters")
    pr["lines"][2] = "Values as printed in the source (A0.12); not recomputed."
    return pr


def _q7(qs, put, draw, b, ds, pss, dose_series_res, ids, level):
    """Question 7, dose dependence: C3, or C2 with the T3 CI, when T3 or T3p excluded or deferred; otherwise C1."""
    pss = _dose_param_sets(pss)
    dsr = next((r for r in dose_series_res if set(r["dataset_ids"]) <= ids and r["status"] == "ASSESSED"), None)
    rows = b["rows"]
    if dsr:
        r = dsr
        lo, hi = r["doses"][0], r["doses"][-1]
        p = r.get("t3p") or {}
        occ = "" if r.get("occasion") in (None, "SINGLE_DOSE") else f" ({r['occasion'].replace('_', ' ').lower()})"
        held = lambda lab, fl: lab.startswith("EXCLUDED") or (lab == "NOT_EXCLUDED" and set(fl or []) & _HOLD)  # noqa: E731
        signs = []
        if r["cmax_label"] == "POINTS_TO_NONLINEARITY":
            signs.append(f"Cmax/D at {hi:g} mg/kg is {r['cmax_d_ratio']:.2f}× that at {lo:g} mg/kg (outside 0.5–2)")
        if r["e6_label"] == "POINTS_TO_NONLINEARITY":
            signs.append(f"AUC/D over 0–{r['window_end_h']:g} h is {r['R_window']:.2f}× (outside the 0.50–2.00 descriptive limits)")
        if r["e2_label"] == "POINTS_TO_NONLINEARITY":
            th = [x["thalf"] for x in r["rows"] if x.get("thalf")]
            signs.append(f"apparent t½ rises with dose ({_f(th[0])} → {_f(th[-1])} h) and the ranges do not overlap")
        if (r.get("animal_auc") or {}).get("status") == "ASSESSED":
            animal = r["animal_auc"]
            obs = (f"Verified animal-level AUC contrast at {lo:g} and {hi:g} mg/kg: geometric dose-normalized AUC ratio "
                   f"{animal['R']:.2f}, 95 % CI {animal['ci'][0]:.2f}–{animal['ci'][1]:.2f}, p = {animal['p']:.2g} ({animal['design'].lower()}).")
        elif r["t3_label"].startswith("EXCLUDED") and r.get("t3_power"):
            pm = r["t3_power"]
            obs = (f"The nominal power-model slope of group-mean AUC on dose between {lo:g} and {hi:g} mg/kg{occ} is "
                   f"{pm['beta']:.2f}, 95 % CI {pm['ci'][0]:.2f}–{pm['ci'][1]:.2f}, excluding 1 under its regression assumptions; animal-level nonproportionality remains unresolved.")
        elif r["t3_label"].startswith("EXCLUDED"):
            # R1: the conclusion is about exposure over the window; the mechanism is judged separately
            obs = (f"Dose-normalised exposure over 0–{r['window_end_h']:g} h is unequal between {lo:g} and {hi:g} mg/kg{occ}: AUC/D ratio R = {r['R']:.2f}, "
                   f"95 % CI {r['ci'][0]:.2f}–{r['ci'][1]:.2f} excludes 1 (T3); the mechanism is judged separately.")
        elif p.get("t3p_label", "").startswith("EXCLUDED"):
            obs = (f"Dose-normalized concentrations differ between {p['t3p_dose_pair'][0]:g} and {p['t3p_dose_pair'][1]:g} mg/kg{occ} at "
                   f"{sum(p['significant'])} time(s) after Holm (T3p).")
        else:
            if r["e6_label"] != "POINTS_TO_NONLINEARITY":
                signs.append(f"Common-window AUC/D ratio was {r['R_window']:.2f}× ({r['e6_label'].replace('_',' ').lower()} by the E6 point-estimate rule)")
            if r["cmax_label"] != "POINTS_TO_NONLINEARITY":
                signs.append(f"Cmax/D ratio was {r['cmax_d_ratio']:.2f}×")
            if r["e2_label"] != "POINTS_TO_NONLINEARITY":
                signs.append("the half-life trend was " + r["e2_label"].replace("_", " ").lower())
            obs = ". ".join(signs) + f"{occ}."
            if r.get("t3_power") and not r["t3_label"].startswith("EXCLUDED"):
                pm = r["t3_power"]
                obs += (f" The power-model slope of AUC on dose is {pm['beta']:.2f} (95 % CI {pm['ci'][0]:.2f}–{pm['ci'][1]:.2f}, "
                        f"{pm['n_doses']} dose groups), so dose proportionality is not excluded.")
        for key, name in (("t3_removal", "T3"), ):
            rec = r.get(key) or (r.get("animal_auc") or {}).get("t3_removal")
            if rec and rec.get("status") == "DEFERRED":
                obs += (f" The full data contradict equal dose-normalised exposure ({name}), but "
                        + ("removal robustness cannot be assessed" if rec.get("not_assessable") else "")
                        + (" and " if rec.get("not_assessable") and rec.get("lost_when_removed") else "")
                        + (f"the contradiction is lost when {', '.join(map(str, rec['lost_when_removed']))} is removed" if rec.get("lost_when_removed") else "")
                        + "; formal exclusion deferred.")
        prec = (p or {}).get("t3p_removal")
        if prec and prec.get("status") == "DEFERRED":
            obs += (" T3p contradicts equal dose-normalised concentrations in the full data, but "
                    + ("removal robustness cannot be assessed" if prec.get("not_assessable") else
                       f"the contradiction is lost when {', '.join(map(str, prec['lost_when_removed']))} is removed")
                    + "; formal exclusion deferred.")
        why = r.get("t3_reason_en") or r.get("t3_reason", "")
        basis = (f"This rests on Cmax/D, apparent t½ and AUC/D over the common window 0–{r['window_end_h']:g} h of {len(r['doses'])} dose groups"
                 + (f"; T3 = {r['t3_label']}" + ("" if r.get("ci") else f" ({why})") if r.get("t3_label") else "") + ".")
        if (r.get("animal_auc") or {}).get("status") == "ASSESSED":
            basis = (f"This inference uses separately sourced animal AUCs ({r['animal_auc']['auc_definition']}); their endpoint, units and design require upstream curation. "
                     f"It is distinct from the descriptive mean-curve AUC ratio over 0–{r['window_end_h']:g} h ({r['R_window']:.2f}).")
        reach = level + " Whether absorption or elimination changes with dose cannot be told apart."
        if r.get("t3_power"):
            reach += " The power-model interval uses scatter across dose-group means, not animal-level variability."
        if r.get("sampling_design_restrictions"):
            reach += " Serial covariance or cross-dose pairing is unresolved; readable SE remain descriptive."
        if r.get("animal_auc"):
            reach += " " + _animal_auc_text(r["animal_auc"])
        if p.get("t3p_times") and held(p["t3p_label"], p.get("t3p_flags")) and r.get("C3"):
            k = sum(p["significant"])
            prim = _prim(r["C3"], ["C3"], 7, f"T3p {p['t3p_label']} · {k or 'no'} of {len(p['significant'])} tested times significant after Holm", level)
        elif r.get("ci") and held(r["t3_label"], r.get("t3_flags")):
            prim = _prim(draw(7, pC2(r, r), 15, 3.9, widths=[1, 1, 1, 1.2]), ["C2", "C2T3"], 7,
                         f"T3 {r['t3_label']} · R {r['R']:.2f} (CI {r['ci'][0]:.2f}–{r['ci'][1]:.2f})", level)
        else:
            prim = _prim(r.get("C1"), ["C1"], 7, f"Cmax/D {r['cmax_d_ratio']:.2f}× ({r['cmax_label']}); AUC/D {r['R_window']:.2f}× ({r['e6_label']})", level)
        miss = ["individual AUC, or SD and n at each time (for T3 or T3p)"] if r["t3_label"] == "CANNOT_ASSESS" and not p.get("t3p_times") else []
        put(7, obs, basis, reach, miss, prim)
        return
    t3 = next(((ps["card"], ps["analysis"]["t3"], ps) for ps in pss if (ps.get("analysis") or {}).get("t3")), None)
    if t3:
        c, t, ps = t3
        animal_route = t.get("t3_data_level") == "VERIFIED_ANIMAL_AUC"
        eq = t.get("equivalence") or {}
        summary_reach = "Reported parameters as printed (A0.12)."
        if eq.get("ci90"):
            summary_reach += f" Predeclared margin {eq['margin']}; 90% CI {eq['ci90'][0]:.2f}–{eq['ci90'][1]:.2f}: {eq['status'].replace('_', ' ').lower()}."
        put(7, f"{'Verified animal-level' if animal_route else 'Reported group'} AUC: AUC/D ratio R = {t['R']:.2f} from {t['dose_pair'][0]:g} to {t['dose_pair'][1]:g} mg/kg, 95 % CI "
               f"{t['ci'][0]:.2f}–{t['ci'][1]:.2f} (T3 = {t['t3_label']}).",
            t.get("method", "This rests on the reported AUC mean, SD and n per dose (T3, group summary)."), _animal_auc_text(t) if animal_route else summary_reach, [],
            _prim(ps.get("C2T3"), ["C2T3"], 7, f"T3 {t['t3_label']} · R {t['R']:.2f}", "Reported group AUC, SD, n"))
        return
    params = [p for ps in pss for p in ps["params"]]
    aucs = sorted({(p["dose"], p["value"]) for p in params if p["param"] == "AUC" and p.get("dose")})
    if len({d for d, _ in aucs}) >= 2:
        (dl, al), (dh, ah) = aucs[0], aucs[-1]
        ratio = (ah / dh) / (al / dl)
        put(7, f"Reported AUC/D at {dh:g} mg/kg is {ratio:.2f}× that at {dl:g} mg/kg" + (" (within 0.80–1.25)." if 0.8 <= ratio <= 1.25 else " (outside 0.80–1.25)."),
            "This rests on the reported AUC divided by dose (E5 description); the reported AUC has no SD or n. " + _dose_param_condition(pss), "Reported parameters as printed (A0.12).",
            ["SD and n of the reported AUC (for T3)"], _fprim(draw, 7, pss, "AUC", f"AUC/D ratio {ratio:.2f} (description)"),
            status=rows[7][0] if rows[7][0] != ST_NA else ST_PART)
        return
    for dataset in ds:
        notes = dataset["card"].get("modeling_evidence", {})
        table = notes.get("reported_oral_doses")
        if table:
            values = []
            for i, dose in enumerate(table["dose_mg_kg"]):
                cells = [f"{dose:g}"]
                for key, se in (("cmax_ug_ml", "cmax_se"), ("auc_inf_ug_h_ml", "auc_inf_se")):
                    cell = f"{table[key][i]:g}"
                    if se in table:
                        cell += f" ± {table[se][i]:g}"
                    cells.append(cell)
                values.append(cells)
            panel = _row(7, ["Dose (mg/kg)", "Cmax (µg/mL)", "AUC(0–∞) (µg·h/mL)"], values,
                         table["location"], "Source-reported estimates. Errors, where printed, are SE.")
            put(7, notes["comparator"]["text"], f"Source: {table['location']}. Reported n: {table['n_as_printed']}.",
                "These parameter summaries describe a dose trend. They do not supply time-matched curves across doses or identify the mechanism.",
                ["comparable profiles or animal-level AUCs across doses"], panel, status=ST_PART)
            return
    if rows[7][0] == ST_NA or not ds:
        put(7, "No comparable multi-dose contrast is available in these inputs.", "", "", [], None, status=ST_NA)
    else:
        put(7, rows[7][1] + ".", "", level, [], None)


def status_boards(datasets, dose_series_res, ev_iv_res, cond_res, param_sets=(), ivs=(), out=None):
    _assign_scopes(datasets, param_sets)
    by_study, by_study_p = {}, {}
    for d in datasets:
        by_study.setdefault(_study_key(d["card"]), []).append(d)
    for ps in param_sets:
        by_study_p.setdefault(_study_key(ps["card"]), []).append(ps)
        by_study.setdefault(_study_key(ps["card"]), [])
    boards = []
    for scope_id, ds in by_study.items():
        pss = by_study_p.get(scope_id, [])
        card = (ds or pss)[0]["card"]
        study = card["study"]
        scope = {"scope_id": scope_id, "scope_key": card["absorption_scope_key"],
                 "regimen": _scope_tuple(card)[2], "experiment_arm": card.get("experiment_arm"), "cohort": card.get("cohort")}
        species = " / ".join(sorted({d["card"]["species"] for d in ds} | {p["card"]["species"] for p in pss}))
        central = [d for d in ds if d["card"]["tests_allowed"]]
        ids = {d["card"]["dataset_id"] for d in ds}
        allids = sorted(ids | {p["card"]["dataset_id"] for p in pss})
        rows = {}
        if not central:
            if ds:
                reason = "; ".join(sorted({", ".join(d["card"]["gates"]) for d in ds}))
                for qn, *_ in QUESTIONS:
                    rows[qn] = (ST_NO, f"No curve passes the test gates ({reason})", [])
                for r in dose_series_res:
                    if set(r["dataset_ids"]) <= ids and r["status"] == "ASSESSED":
                        rows[7] = (ST_PART, f"Dose series at one occasion ({r['occasion']}): Cmax/D ratio {r['cmax_d_ratio']:.2f} ({r['cmax_label']}), "
                                   f"common window 0–{r['window_end_h']:g} h R = {r['R_window']:.2f} ({r['e6_label']})", ["fig4"])
                        _merge(rows, 7, (_test_state(r["t3_label"], r["t3_flags"]), _t3_text(r), ["fig7"]))
                        p = r.get("t3p") or {}
                        if p.get("t3p_times"):
                            rows[7] = (max(rows[7][0], _test_state(p["t3p_label"], p["t3p_flags"]), key=lambda x: _RANK[x]), rows[7][1], rows[7][2])
            if pss:
                for qn, v in _param_rows(pss).items():
                    if ds:
                        if qn in (2, 5, 6, 7):
                            _merge(rows, qn, v)
                    else:
                        rows[qn] = v
            boards.append({"study": study, "species": species, "datasets": allids, "rows": rows, **scope}); continue
        mets = [s["metrics"] for d in central for s in d["series"] if "tmax" in s["metrics"]]
        levels = {d["card"]["record_level"] for d in central}
        onset = sorted({m["onset_status"] for m in mets})
        first = [m["first_t"] for m in mets]
        rows[1] = (ST_PART, f"{'/'.join(onset)}: first quantified postdose sample at {_rng(first)} h; " + "; ".join(sorted({d["card"].get("baseline_status", "baseline not reported") for d in central})), ["fig1", "fig2"])
        kani = sum("KA_NOT_IDENTIFIABLE" in m["caveats"] for m in mets)
        q2 = ST_YES if levels == {"INDIVIDUAL"} and kani == 0 else ST_PART
        rows[2] = (q2, f"Description only: Tmax {_rng([m['tmax'] for m in mets])} h; {kani}/{len(mets)} curves KA_NOT_IDENTIFIABLE", ["fig1", "fig2"])
        t1s = sorted({m["t1_label"] for m in mets})
        t2s = [(d, s) for d in central for s in d["series"] if s.get("t2")]
        t2_ind = [s["t2"] for d, s in t2s if d["card"]["record_level"] != "GROUP_MEAN"]
        t2_txt = ("T2: " + "/".join(sorted({x["t2_label"] for x in t2_ind})) + " + " + "+".join(sorted({f for x in t2_ind for f in x["t2_flags"]}))) if t2_ind else (
            "T2 does not apply to group means" if "GROUP_MEAN" in levels else "T2: see Q4")
        rows[3] = (ST_PART, f"T1: {'/'.join(t1s)} + SENSITIVITY_ONLY (against M0 only); {t2_txt}; no dedicated exclusion test for lag or transit", ["fig2", "fig6"])
        mean_valleys = [d["card"]["dataset_id"] for d, s in t2s if d["card"]["record_level"] == "GROUP_MEAN" and s["t2"]["trigger"]]
        if t2_ind:
            labs = sorted({x["t2_label"] for x in t2_ind}); flags = sorted({f for x in t2_ind for f in x["t2_flags"]})
            n_v = sum(1 for x in t2_ind if x["trigger"])
            rows[4] = (ST_PART,
                       f"T2 ({len(t2_ind)} individual curves, {n_v} with a confirmed re-rise) = {'/'.join(labs)} + {'+'.join(flags)}"
                       + ("; cross-time identity not verified, so the result assumes each source label is one animal" if "CONDITIONAL_ON_LABEL_IDENTITY" in flags else ""), ["fig5", "fig6"])
        else:
            post2 = any(len(m["_t"]) - int(np.argmax(m["_c"])) - 1 >= 2 for m in mets)  # draft A0.11: the valley search on a mean is a description
            rows[4] = (ST_PART if post2 else ST_NO, "Group means only, T2 does not apply (missing: serial individual sampling)"
                       + ("; the dip search on the mean is a description" if post2 else "")
                       + (f"; dip beyond ±5 % on the mean of {', '.join(sorted(set(mean_valleys)))}, description only" if mean_valleys else ""), ["B1", "A1w"])
        evs = [r for r in ev_iv_res if r["ev"] in ids]
        if evs:
            r = evs[0]
            t4 = r.get("t4_label", "CANNOT_ASSESS")
            st5 = ST_PART if r.get("q") or r.get("tail") else ST_NO
            rows[5] = (st5, f"T4: {t4} {'+'.join(r.get('t4_flags', []))} (group means assume a common k); apparent t½ is description only"
                       + ("" if r.get("trigger") else "; no tier-1 trigger, D1 not drawn"), ["fig3", "fig8"])
            st = r.get("f_status", "NOT_ESTIMABLE")
            rows[6] = (ST_NO if st == "NOT_ESTIMABLE" else ST_YES if st == "WINDOW_BASED_ESTIMATE" else ST_PART,
                       f"Ratio status = {st}" + (f"; AUC ratio over {_ratio_window_text(r)} = {r['window_auc_ratio']:.3g}; absolute F not recomputed. " + _source_f_text(r) if r.get('window_auc_ratio') is not None else f"; {_f_reason(r)}"), ["fig9"])
        else:
            desc5 = any(m.get("terminal_selected") or m.get("split") for m in mets)  # draft A0.11; L5: the split slopes describe
            unpaired_iv = _iv_unpaired_text(ivs, ds)
            gffs = [d["group_flip_flop"] for d in ds if d.get("group_flip_flop")]
            if gffs:
                rows[5] = (ST_PART, gffs[0]["text"] + " Apparent t½ is not passed on as k.", ["B1", "D1d"])
            else:
                rows[5] = (ST_PART if desc5 else ST_NO, (unpaired_iv + " " if unpaired_iv else "No same-study, same-species IV: ") + "flip_flop_reading = NOT_ASSESSABLE (missing side: IV); apparent t½ is "
                       "not passed on as k" + ("; the terminal window and split-half slopes are a description" if desc5 else ""), ["B1"])
            rows[6] = (ST_NO, "f_status = NOT_ESTIMABLE: " + (unpaired_iv or "no same-study IV (missing: same-species IV with a consistent dose basis)"), [])
            source_cards = [d["card"] for d in ds if d["card"].get("source_reported_absolute_f")]
            if source_cards:
                rows[6] = (ST_PART, " ".join(_source_f_text(c) for c in source_cards)
                           + " Absolute F was not independently recomputed; source-level results do not verify pairing of the available individuals.", [])
        dsr = [r for r in dose_series_res if set(r["dataset_ids"]) <= ids and r["status"] == "ASSESSED"]
        if dsr:
            r = dsr[0]
            rows[7] = (ST_PART, f"Description: Cmax/D ratio {r['cmax_d_ratio']:.2f} ({r['cmax_label']}), t½ {r['e2_label']}, common window 0–{r['window_end_h']:g} h R = {r['R_window']:.2f} ({r['e6_label']})", ["fig4"])
            _merge(rows, 7, (_test_state(r["t3_label"], r["t3_flags"]), _t3_text(r), ["fig7"]))
            p = r.get("t3p") or {}
            if p.get("t3p_times"):
                rows[7] = (max(rows[7][0], _test_state(p["t3p_label"], p["t3p_flags"]), key=lambda x: _RANK[x]), rows[7][1], rows[7][2])
        else:
            rows[7] = (ST_NA, "One dose only", [])
        crs = [r for r in cond_res if {r["a"], r["b"]} <= ids]
        if crs:
            r = crs[0]
            rows[8] = (ST_PART, f"{r['a']} vs {r['b']}, differing: {', '.join(r['differing_attributes'])}; T5 = {r.get('t5_label')}; rate-only check = {r.get('rate_only_label','—')}", ["fig10"])
        else:
            rows[8] = (ST_NA, "No comparable condition pair (dose differences belong to Q7)", [])
        destructive = any("mice/time" in d["card"]["notes"] or "DESTRUCTIVE" in d["card"]["notes"].upper() for d in central)
        if "INDIVIDUAL" in levels:
            rows[9] = (ST_YES, "Verified serial individual sampling; see the individual figure", ["fig5"])
        elif "INDIVIDUAL_IDENTITY_UNVERIFIED" in levels:
            rows[9] = (ST_PART, "Individual values by source label, but cross-time identity not verified: points only", ["fig5"])
        else:
            rows[9] = (ST_NO, ("Destructive sampling (one time point per animal) cannot answer this in principle" if destructive else "Group means only") + " (missing: serial curves from several animals)", [])
        if pss:
            for qn, v in _param_rows(pss).items():
                if qn in (6, 7):
                    _merge(rows, qn, v)
        boards.append({"study": study, "species": species, "datasets": allids, "rows": rows, **scope})
    for b in boards:
        b["species_group"] = species_group(b["species"])
        b["status_codes"] = {q: ST_CODE[v[0]] for q, v in b["rows"].items()}
        scoped_ivs = _scope_ivs(b, ivs)
        b["evidence"] = board_evidence(b["study"], by_study.get(_board_key(b), []), by_study_p.get(_board_key(b), []),
                                       dose_series_res, ev_iv_res, cond_res, scoped_ivs, b["rows"])
        b["questions"] = board_questions(b, by_study.get(_board_key(b), []), by_study_p.get(_board_key(b), []),
                                         dose_series_res, ev_iv_res, cond_res, scoped_ivs, out)
        legacy = b["rows"]
        b["rows_r43"], b["evidence_r43"], b["rows"] = legacy, b["evidence"], {}
        for q in b["questions"]:  # one status per question, in the review-guide numbering; the r4.3 rows stay in rows_r43
            src = [k for k in q.get("legacy_q", []) if k in legacy]
            txt = "; ".join(dict.fromkeys(legacy[k][1] for k in src)) if q["q"] not in (3, 8) else q["observed"]
            figs = [f for k in src for f in legacy[k][2]]
            if q.get("reported_condition_comparisons") or q.get("observed_individual_ranges"):
                txt = q["observed"]
            b["rows"][q["q"]] = (q["status"], txt or q["observed"], list(dict.fromkeys(x for f in figs for x in _OLD_FIG.get(f, [f]))))
        b["evidence"] = {str(q["q"]): q["evidence"] for q in b["questions"]}
        b["status_codes"] = {q["q"]: q["status_code"] for q in b["questions"]}
    return boards


# r4.1 board rows name the old figure numbers; the question-first page names panels
_OLD_FIG = {"fig1": ["A1w", "B1"], "fig2": ["A1", "A2"], "fig3": ["B1"], "fig4": ["C1", "C2"], "fig5": ["A1ind", "B1ind"], "fig6": ["T2"],
            "fig7": ["C2T3", "C3"], "fig8": ["D1"], "fig9": ["D2"], "fig10": ["E1", "E2"], "fig3f": ["F"]}


_FIG_DIR = [None]


_e = COMMON._e


_f = COMMON._f


# ---------------------------------------------------------------- HTML: the EDA review portal's own style
# The Absorption page is one more category of the EDA figure review (index.html → absorption/index.html),
# drawn with the portal's stylesheet. Figures of one kind and one species form one gallery, and one
# description follows each gallery. report.html gets a short Absorption section in its own plain style.

_SPECIES = COMMON.SPECIES          # L4: the shared registry (same list object as Distribution's)


def species_group(text):
    """Species for grouping only (the source wording stays in the card): 'neutropenic thigh-infected mice' → Mouse."""
    t, out = str(text or "").lower(), []
    for name, pat in _SPECIES:
        if re.search(pat, t):
            out.append(name)
            t = re.sub(pat, " ", t)
    return " / ".join(out) if out else "Species not stated"


_slug = COMMON.page_slug


ST_CLASS = COMMON.ST_CLASS
ST_SHORT = COMMON.ST_SHORT
# R6 (2026-11-24): output written before the display rename carries the old label; pages built again from it still render
for _old, _new in {"Not answerable yet": ST_NO}.items():
    ST_CLASS[_old], ST_SHORT[_old] = ST_CLASS[_new], ST_SHORT[_new]
ST_MEANING = {ST_YES: "the data answer it under the stated assumptions",
              ST_PART: "a description, or a test with limits, answers part of it; the row says which part",
              ST_NO: "these data cannot answer it yet; the row says what is missing",
              ST_NA: "the question does not arise in this study"}
ST_ORDER = COMMON.ST_ORDER
Q_SHORT = {1: "Onset and peak", 2: "Trough", 3: "Half-life", 4: "Early rise", 5: "Flip-flop", 6: "Extent (F)", 7: "Dose", 8: "Route ratio",
           9: "Conditions"}
TIER_NAME = {1: "Look at the data", 2: "Tier 2 · tests", 3: "Tier 3 · supplements"}

PORTAL_CSS_FALLBACK = (
    ':root{--ink:#173547;--muted:#61747c;--line:#dce6e6;--accent:#156f68}*{box-sizing:border-box}html{scroll-behavior:smooth}'
    'body{margin:0;background:#f4f7f6;color:var(--ink);font:16px/1.65 "Segoe UI",Arial,sans-serif}a{color:var(--accent);text-underline-offset:3px}'
    'main{max-width:1220px;margin:auto;padding:36px 28px 70px}h1{font-size:38px;line-height:1.15;letter-spacing:-.03em;margin:14px 0}'
    'h2{font-size:25px;margin:0 0 14px}h3{font-size:19px;margin:0 0 6px}p{margin:8px 0}.muted,small{color:var(--muted)}'
    '.eyebrow{font-size:12px;letter-spacing:.12em;font-weight:700;text-transform:uppercase}.badge{display:inline-block;border:1px solid #c8ded7;'
    'border-radius:24px;padding:3px 12px;background:#edf6f1;font-size:12px}.panel,.category{background:white;border:1px solid var(--line);'
    'border-radius:16px;padding:25px;margin-top:22px}.lead{font-size:18px;max-width:840px}.limit{display:grid;grid-template-columns:220px 1fr;'
    'gap:20px;padding:15px 0;border-top:1px solid var(--line)}.limit p{margin:0}.label{font-weight:650}.notice{border-left:3px solid #d7af69;'
    'padding:10px 16px;background:#fff9ed;margin:22px 0}.section-head{display:flex;align-items:baseline;justify-content:space-between;'
    'margin:38px 0 16px;gap:16px}details{margin-top:20px}summary{cursor:pointer;font-weight:650}footer{font-size:13px;'
    'color:var(--muted);margin-top:30px}nav{display:flex;flex-wrap:wrap;gap:18px;margin-bottom:24px;font-size:14px}[hidden]{display:none!important}'
    '.categories{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:18px}.category{display:block;text-decoration:none;'
    'color:inherit;margin-top:0}.thumbs{display:flex;gap:6px;margin-top:12px}.thumbs img{width:33%;height:auto;border:1px solid var(--line);'
    'border-radius:6px}.open{display:block;margin-top:12px;color:var(--accent);font-weight:650}'
    ':focus-visible{outline:3px solid #4d9b9a;outline-offset:4px}@media(max-width:760px){main{padding:24px 16px}.limit{grid-template-columns:1fr;'
    'gap:4px}h1{font-size:30px}.section-head{display:block}}')

# Additions for question rows, result tables and states; same tokens as the portal.
ABS_CSS = (
    '.res{width:100%;border-collapse:collapse;font-size:14px;line-height:1.5;margin:4px 0 8px}'
    '.res th,.res td{text-align:left;vertical-align:top;padding:7px 14px 7px 0;border-top:1px solid var(--line)}'
    '.res th{font-size:12px;color:var(--muted);font-weight:650;border-top:0}.res td:first-child{font-weight:600;white-space:nowrap}'
    '.res td.muted{font-weight:400}.tw{overflow-x:auto}'
    '.st{display:inline-block;border:1px solid;border-radius:24px;padding:0 10px;font-size:12px;font-weight:650;white-space:nowrap}'
    '.st-yes{background:#156f68;border-color:#156f68;color:white}.st-part{background:#fff5df;border-color:#e8d6b4;color:#8a5a00}'
    '.st-no{background:#fbeeea;border-color:#ecc9bd;color:#9b3d1f}.st-na{background:#f1f3f3;border-color:#dce3e3;color:#61747c}'
    '.section-head h2{white-space:nowrap;margin:0}.section-head .muted{text-align:right;max-width:640px}'
    '.limit>*{min-width:0}.limit p,.res td{overflow-wrap:anywhere}'
    'details.evi{margin:10px 0 2px}.evi>summary{font-size:13px;color:var(--accent);font-weight:650}'
    '.evi[open]{background:white;border:1px solid var(--line);border-radius:8px;padding:2px 14px 10px}.evi[open]>summary{padding-top:8px}'
    '.evi p{font-size:14px;margin:8px 0}.evt{font-size:13px}.evt td:first-child{white-space:normal;min-width:80px}.evt td{overflow-wrap:normal}'
    '.evt caption{text-align:left;font-weight:650;font-size:13px;color:var(--ink);padding:10px 0 2px}.ev{font-size:13px;color:var(--muted)}'
    '.pts{border-top:1px solid var(--line);margin:0;padding:12px 0}.pts>summary{font-weight:600}'
    '.facts{display:grid;grid-template-columns:170px 1fr;gap:4px 16px;font-size:14px;margin:12px 0}.facts dt{color:var(--muted)}.facts dd{margin:0}'
    '.notes{white-space:pre-line}:target{scroll-margin-top:16px}'
    '.legend{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:6px 18px;font-size:13px;color:var(--muted);margin:4px 0 12px}'
    '.legend .st{min-width:92px;text-align:center;margin-right:6px}'
    '.fthumbs{display:flex;flex-wrap:wrap;gap:8px;margin:6px 0 4px}.fthumbs a{display:block;width:190px;border:1px solid var(--line);'
    'border-radius:6px;overflow:hidden;background:white;text-decoration:none}.fthumbs img{display:block;width:100%;height:auto}'
    '.fthumbs span{display:block;font-size:11.5px;line-height:1.35;color:var(--muted);padding:4px 6px;border-top:1px solid #edf1f1}'
    '.study>h2{margin:0}.study>.muted{margin:2px 0 10px}.card{font-size:13.5px}.card td,.card th{padding:5px 12px 5px 0}'
    '.qchips{display:flex;flex-wrap:wrap;gap:6px 8px;margin:14px 0 6px}.qchip{text-decoration:none;color:var(--ink);font-size:13px;'
    'white-space:nowrap}.qchip .st{margin-left:3px}'
    '.qrow{border-top:1px solid var(--line);padding:20px 0 12px;scroll-margin-top:12px}'
    '.qhead{display:flex;flex-wrap:wrap;align-items:baseline;gap:4px 10px}.qhead h3{margin:0;font-size:19px}'
    '.qn{font-weight:700;color:var(--accent);font-size:14px}.qhead .q{flex-basis:100%;margin:0;font-size:14px;color:var(--muted)}'
    '.qbody{display:grid;grid-template-columns:minmax(0,5fr) minmax(0,6fr);gap:24px;margin-top:10px;align-items:start}'
    '.qbody.noprim{grid-template-columns:minmax(0,1fr)}.qbody.noprim .qtext{max-width:860px}'
    '.concl{font-size:16px;margin:0 0 10px}.concl .sub{color:#455c69}.concl.plain b{font-weight:600}details.nums{margin:0 0 10px;color:#455c69;font-size:13px}details.nums summary{cursor:pointer}.qtext{min-width:0}.concl,.miss,.prim figcaption{overflow-wrap:anywhere}'
    '.miss{font-size:14px;margin:8px 0 0;padding:6px 12px;border-left:3px solid #e8d6b4;background:#fffaf0}'
    '.prim{margin:0;border:1px solid var(--line);border-radius:10px;overflow:hidden;background:white}'
    '.prim a{display:block}.prim img{display:block;width:100%;height:auto}.prim .tw{padding:4px 12px 0}'
    '.prim figcaption{font-size:12.5px;line-height:1.5;color:var(--muted);padding:8px 12px 10px;border-top:1px solid #edf1f1}'
    '.prim figcaption b,.prim .lvl{color:var(--ink)}'
    '.more{margin:12px 0 0}.more>summary{font-size:14px;color:var(--accent)}'
    '.more[open]{background:#f7f9f8;border-radius:8px;padding:4px 14px 12px}.more[open]>summary{padding-top:6px}'
    '.pgrp{margin:12px 0 0}.pgrp>p{margin:0;font-size:13px;color:var(--muted)}.pgrp>p b{color:var(--ink)}'
    '.tier{margin:14px 0 0}.tier>summary{font-size:14px}'
    '.qtab{font-size:13px}.qtab th,.qtab td{padding:6px 6px 6px 0;white-space:nowrap}.qtab th{font-weight:650;line-height:1.3}'
    '.qtab th .muted{font-weight:400}.qtab td:first-child{white-space:normal;min-width:120px}'
    '.qtab a{text-decoration:none}.qtab .st{min-width:66px;text-align:center}'
    '.qbody.noprim .prim{max-width:100%}'
    '@media(max-width:860px){.qbody{grid-template-columns:minmax(0,1fr)}}'
    '@media(max-width:760px){.res td:first-child{white-space:normal}.facts{grid-template-columns:1fr}.facts dd{margin-bottom:6px}'
    '.fthumbs a{width:calc(50% - 4px)}.qchip{white-space:normal}}')


def _portal_css():
    try:
        from .eda_review_portal import CSS as css  # the portal's own stylesheet, so the pages cannot drift apart
        return css
    except Exception:  # noqa: BLE001 - standalone use outside the package
        return PORTAL_CSS_FALLBACK


def _data_level(card):
    lvl = {"GROUP_MEAN": "Group mean", "INDIVIDUAL": "Individual",
           "INDIVIDUAL_IDENTITY_UNVERIFIED": "Individual, identity not verified"}.get(card["record_level"], card["record_level"])
    return lvl + (", digitized" if card.get("digitized") else "")


def _dose_txt(card):
    d = card.get("dose_mg_per_kg")
    return (f"{d:g} mg/kg " if isinstance(d, (int, float)) else "") + str(card.get("route_detail", ""))


def _skips(res, datasets, param_sets):
    """Every panel not drawn, with its reason: (panel, item, reason, species or None)."""
    cards = {d["card"]["dataset_id"]: d["card"] for d in datasets}
    cards.update({p["card"]["dataset_id"]: p["card"] for p in param_sets})
    out = []

    def skip(card, k, lab, t):
        out.append((k, lab, t, species_group(card["species"]) if card else None))

    for d in datasets:
        c = d["card"]
        multi = len(d["series"]) > 1
        if not c["tests_allowed"]:
            why = ("not a central-compartment matrix, so the T1–T5 premises fail" if "NOT_CENTRAL_MATRIX" in c["gates"] else
                   "not a single first dose" if "NOT_SINGLE_DOSE" in c["gates"] else "a test gate failed")
            skip(c, "A2, B2, T2 and the tests", f"{c['dataset_id']} ({c['study']})", f"overview panels only (A1, B1); {why} ({', '.join(c['gates'])}).")
        for s in d["series"]:
            m = s["metrics"]
            lab = c["dataset_id"] + (f" · {s['label']}" if multi else "")
            if "tmax" not in m:
                skip(c, "All panels", lab, f"not assessable, {m.get('not_assessable_reason', '')}.")
                continue
            t2 = s.get("t2")
            if t2 and not s.get("T2") and c["record_level"] != "GROUP_MEAN":
                skip(c, "B1 · T2 dip test", lab, f"no confirmed dip. T2 still ran: {t2['t2_label']}" + "".join(" + " + x for x in t2["t2_flags"]) + " (Q4).")
    for r in res["dose_series"]:
        c = cards[r["dataset_ids"][0]]
        if r["status"] != "ASSESSED":
            skip(c, "C · Dose panels", r["label"], f"not assessable, {r.get('reason')}.")
            continue
        ob = r.get("overlay_block")
        if ob and not ob.get("view_ids") and (ob.get("execution_status") or ob["status"]) not in ("READY", "RENDERED_AND_VERIFIED"):
            skip(c, "C1 · overlay of the dose-normalization step", r["label"], f"not drawn by that step ({ob['group_id']}, "
                 f"{ob.get('execution_status') or ob['status']}): {str(ob.get('reason', '')).rstrip('.')}. C1 is drawn here from the same points.")
        p = r.get("t3p") or {}
        if not r.get("C2T3") and not r.get("C3"):
            skip(c, "C2 · T3 and C3 · T3p", r["label"],
                 ("triggered (descriptive values point to nonlinearity)" if r.get("trigger") else "no tier-1 trigger") + f". {_t3_text(r)}."
                 + (" Missing: individual AUC, or SD and n at each time point." if not p.get("t3p_times") and r.get("t3_label") == "CANNOT_ASSESS" else ""))
    if not res["ev_iv"] and not any(d.get("iv_pairs") or d.get("D1d") for d in res.get("datasets", [])):
        skip(None, "D · Extravascular vs IV", None, "IV retained descriptively; no eligible EV/IV comparison with verified cross-route pairing." if res.get("iv_references") else "No same-study, same-species IV plasma curve.")
    for r in res["ev_iv"]:
        c = cards[r["ev"]]
        lab = f"{r['ev']} vs {r['iv']}"
        if not r.get("D1") and r.get("q"):
            skip(c, "D1 · EV vs IV (T4)", lab, f"no tier-1 trigger ({r['trigger_text']}). T4 still ran: {r['t4_label']}"
                 + "".join(" + " + x for x in r["t4_flags"]) + " (Q5).")
        if not r.get("D2") and r.get("f_status"):
            skip(c, "D2 · finite-window AUC ratio", lab, f"f_status = {r['f_status']}, {_f_reason(r)}")
    if not res["conditions"]:
        skip(None, "E · Condition comparison (T5)", None, "No pair from one study, species and matrix that differs only by condition.")
    for r in res["conditions"]:
        if not r.get("E1"):
            skip(cards[r["a"]], "E · Condition comparison (T5)", f"{r['a']} vs {r['b']}", str(r.get("t5_reason")))
    return out


def _board_species(b):
    return [x.strip() for x in (b.get("species_group") or species_group(b["species"])).split(" / ")]


_wb = COMMON._wb


def _evidence_html(parts, note=""):
    """The rule, the numbers and the source data behind one question."""
    if not parts:
        return ""
    h, ids = ['<details class="evi"><summary>Evidence: rule, numbers and source points</summary>'], []
    for p in parts:
        h.append(f'<p class="rule"><strong>Rule.</strong> {_e(p["rule"])}</p>')
        for t in p["tables"]:
            h.append('<div class="tw"><table class="res evt"><caption>' + _e(t["caption"]) + '</caption><tr>'
                     + "".join(f"<th>{_e(x)}</th>" for x in t["head"]) + "</tr>"
                     + "".join("<tr>" + "".join(f"<td>{_wb(v)}</td>" for v in r) + "</tr>" for r in t["rows"]) + "</table></div>")
        ids += [i for i in p["data"] if i not in ids]
    if ids:
        h.append('<p class="ev">Source data points: ' + ", ".join(f'<a href="#data-{_e(i)}">{_e(i)}</a>' for i in ids) + '</p>')
    if note:
        h.append(f'<p class="ev">{_e(note)}</p>')
    h.append('</details>')
    return "".join(h)


def _thumbs(views):
    """Panels grouped by panel id: one line on how to read it, then the thumbnails."""
    by = {}
    for v in views:
        by.setdefault(v["panel"], []).append(v)
    h = []
    for pid, vs in by.items():
        name, read = PANELS[pid][1], PANELS[pid][3]
        th = "".join(f'<a href="{_e(v["file"])}" target="_blank" rel="noopener" title="{_e(name + " · " + v["label"])}">'
                     f'<img loading="lazy" src="{_e(v["file"])}" alt="{_e(name + " · " + v["label"])}"><span>{_e(v["label"])}</span></a>' for v in vs)
        h.append(f'<div class="pgrp"><p><b>{_e(name)}</b> · {_e(read)}</p><div class="fthumbs">{th}</div></div>')
    return "".join(h)


def _primary_html(p):
    if not p or (p.get("kind") == "panel" and not p.get("file")):
        return ""
    cap = (f'<figcaption><b>{_e(p["lines"][0])}</b> · {_e(p["lines"][1])}<br>{_e(p["lines"][2])}<br>{_e(p["lines"][3])}'
           f'<br><span class="lvl">Record level: {_e(p["level"])}</span></figcaption>')
    if p["kind"] == "row":
        tab = ('<div class="tw"><table class="res evt"><tr>' + "".join(f"<th>{_e(x)}</th>" for x in p["head"]) + "</tr>"
               + "".join("<tr>" + "".join(f"<td>{_wb(v)}</td>" for v in r) + "</tr>" for r in p["rows"]) + "</table></div>")
        return f'<figure class="prim row">{tab}{cap}</figure>'
    alt = f'{p["lines"][0]}: {p["lines"][1]}'
    return (f'<figure class="prim"><a href="{_e(p["file"])}" target="_blank" rel="noopener" aria-label="Open full-size {_e(alt)}">'
            f'<img src="{_e(p["file"])}" alt="{_e(alt)}" loading="lazy"></a>{cap}</figure>')


def _dn_see(res, root):
    """Study → links to the C/D overlay drawn by the dose-normalization step (shown under question 7)."""
    see = {}
    scopes = {d["card"]["dataset_id"]: _study_key(d["card"]) for d in res.get("datasets", [])}
    for r in res["dose_series"]:
        ob = r.get("overlay_block")
        if not (ob and ob.get("view_ids")):
            continue
        links = []
        for vid in ob["view_ids"]:
            png = next(iter(sorted((root / "EV").glob(f"{vid}*.png"))), None) if root else None
            href = f"../EV/{png.name}" if png else f"../sections/Q_PK_SHAPE/index.html#figure-{vid}"
            links.append(f'<a class="dn-link" href="{_e(href)}" data-portal="../sections/Q_PK_SHAPE/index.html#figure-{_e(vid)}">{_e(vid)}</a>')
        for scope in sorted({scopes[x] for x in r["dataset_ids"] if x in scopes}):
            see.setdefault(scope, []).append(
                f'The dose-normalization step draws the same C/D overlay ({_e(ob["group_id"])}, {_e(ob.get("execution_status") or ob["status"])}): '
                + ", ".join(links) + ".")
    return see


def _qid(study, n):
    return f"q-{_slug(study)}-{n}"


def _png_ratio(path):
    try:
        import struct
        w, h = struct.unpack(">II", Path(path).read_bytes()[16:24])
        return w / h
    except Exception:  # noqa: BLE001 - layout hint only
        return 1.6


def _qrow_html(q, study, base=None, see=()):
    st = q["status"]
    prim = _primary_html(q["primary"])
    pr = q.get("primary") or {}
    wide = bool(prim and pr.get("kind") == "panel" and base is not None and _png_ratio(Path(base) / pr["file"]) > 2.2)
    sub = " ".join(x for x in (q["basis"], q["reach"]) if x)
    miss = (f'<p class="miss"><b>Missing:</b> ' + "; ".join(_e(m) for m in q["missing"]) + '</p>') if q["missing"] else ""
    h = [f'<article class="qrow" id="{_qid(study, q["q"])}"><div class="qhead"><span class="qn">Q{q["q"]}</span><h3>{_e(q["label"])}</h3>'
         f'<span class="st {ST_CLASS[st]}">{_e(st)}</span><p class="q">{_e(q["question"])}</p></div>'
         f'<div class="qbody{"" if prim and not wide else " noprim"}"><div class="qtext">'
         + (_plain_html(q["plain"], [q["observed"], sub]) if q.get("plain") else f'<p class="concl">{_e(q["observed"])}'
            + (f' <span class="sub">{_e(sub)}</span>' if sub else "") + '</p>') + f'{miss}</div>{prim}</div>']
    views = q["views"]
    if views or q["evidence"] or see:
        t1 = [v for v in views if v["tier"] == 1]
        t2 = [v for v in views if v["tier"] == 2]
        t3 = [v for v in views if v["tier"] == 3]
        bits = [f"{len(views)} more panel{'s' if len(views) != 1 else ''}"] if views else []
        if q["evidence"]:
            bits.append("evidence")
        h.append(f'<details class="more"><summary>More for Q{q["q"]}: {" · ".join(bits)}</summary>' + _thumbs(t1)
                 + (f'<details class="tier"><summary>{TIER_NAME[2]} ({len(t2)})</summary>{_thumbs(t2)}</details>' if t2 else "")
                 + (f'<details class="tier"><summary>{TIER_NAME[3]} ({len(t3)})</summary>{_thumbs(t3)}</details>' if t3 else "")
                 + "".join(f'<p class="ev">See also: {x}</p>' for x in see) + _evidence_html(q["evidence"]) + '</details>')
    h.append('</article>')
    return "".join(h)


def _qchips(b, page=""):
    return "".join(f'<a class="qchip" href="{_e(page)}#{_qid(_board_key(b), q["q"])}" title="{_e(q["text"])}">Q{q["q"]} {_e(q["label"])}'
                   f'<span class="st {ST_CLASS[q["status"]]}">{_e(ST_SHORT[q["status"]])}</span></a>' for q in b.get("questions", [])) + (
        f'<a class="qchip" href="{_e(page)}#{_hid(_board_key(b))}" title="{_e(b["hypothesis"]["text"])}">H Working hypothesis{_hchip(b["hypothesis"])}</a>'
        if b.get("hypothesis") else "")


def _study_card(ds, pss, ivs):
    """Step 0, the data card of one study: what each dataset is and what it allows."""
    rows = []
    for d in ds:
        c = d["card"]
        gate = "Tests run" if c["tests_allowed"] else ("Dose series only" if c.get("dose_series_allowed") else "Overview only")
        n = len([s for s in d["series"] if "tmax" in s["metrics"]])
        doses = sorted({s["dose"] for s in d["series"] if s.get("dose")})
        dose = (", ".join(f"{x:g}" for x in doses) + f" mg/kg {c.get('route_detail', '')}") if len(doses) > 1 else _dose_txt(c)
        rows.append([c["dataset_id"], dose, c["matrix"], _data_level(c) + (f" · {n} curves" if n > 1 else ""),
                     c.get("n_per_time") or "—", c.get("lloq") or "not reported", (c.get("dose_time_basis") or "—") + "; " + c.get("baseline_status", "baseline not reported"),
                     gate + (": " + ", ".join(c["gates"]) if c["gates"] else "")])
    for i in ivs:
        c = i["card"]
        rows.append([c["dataset_id"], _dose_txt(c) + " (IV reference)", c["matrix"], _data_level(c), c.get("n_per_time") or "—",
                     c.get("lloq") or "not reported", (c.get("dose_time_basis") or "—") + "; " + c.get("baseline_status", "baseline not reported"), "Descriptive IV; pairing requires verified identity, occasions and washout" if c["record_level"].startswith("INDIVIDUAL") else "Reference for Q5, Q6"])
    for ps in pss:
        c = ps["card"]
        rows.append([c["dataset_id"], _dose_txt(c), c.get("matrix", ""), "Reported parameters", "—", "—", "—", "As printed (A0.12)"])
    head = ["Dataset", "Dose and route", "Matrix", "Data", "n per time", "LLOQ", "Time zero", "Gate"]
    return ('<div class="tw"><table class="res evt card"><tr>' + "".join(f"<th>{_e(x)}</th>" for x in head) + "</tr>"
            + "".join("<tr>" + "".join(f'<td>{_wb(v) if j == 7 else _e(v)}</td>' for j, v in enumerate(r)) + "</tr>" for r in rows)
            + "</table></div>")


def _study_html(b, ds, pss, ivs, base=None, see=()):
    sp = b.get("species_group") or species_group(b["species"])
    slug = _slug(_board_key(b))
    h = [f'<section class="panel study" id="study-{_e(slug)}"><h2>{_e(b["study"])} · {_e(sp)}</h2>'
         f'<p class="muted">{_e(b["species"])} · {_e(b.get("regimen", ""))} · {_e(b.get("experiment_arm") or "")} · {_e(", ".join(b["datasets"]))}</p>', _study_card(ds, pss, ivs),
         f'<div class="qchips">{_qchips(b)}</div>']
    h += [_qrow_html(q, _board_key(b), base, see if q["q"] == 7 else ()) for q in b.get("questions", [])]
    h.append(_hrow_html(b))
    h.append('</section>')
    return "".join(h)


def _points_html(datasets, param_sets, ivs, species):
    """Every observed point behind a species page, one collapsible block per dataset (targets of the evidence links)."""
    h = []
    for kind, d in [("EV", d) for d in datasets] + [("IV", i) for i in ivs]:
        c = d["card"]
        if species_group(c["species"]) != species:
            continue
        series = d["series"] if kind == "EV" else [{"label": c["title"], "points": d.get("points") or []}]
        facts = [("Source", c["title"]), ("Study", c["study"]), ("Species as written", c["species"]), ("Route", f'{c["route_class"]} · {c["route_detail"]}'),
                 ("Dose", _dose_txt(c) + " · dose basis " + (c.get("dose_basis") if c.get("dose_basis") not in (None, "", "NOT_FOUND") else "not reported")), ("Matrix", c["matrix"]), ("Data", _data_level(c)),
                 ("n per time", c.get("n_per_time")), ("Dispersion", c.get("dispersion")), ("LLOQ", str(c.get("lloq")) + " " + c.get("lloq_unit", c["unit"])), ("Baseline", c.get("baseline_status")),
                 ("Error bound", c.get("error_bound")), ("Time zero", c.get("dose_time_basis"))]
        h.append(f'<details class="pts" id="data-{_e(c["dataset_id"])}"><summary>{_e(c["dataset_id"])} · {_e(c["title"])}'
                 + (' <span class="muted">(IV reference)</span>' if kind == "IV" else "") + '</summary><dl class="facts">'
                 + "".join(f"<dt>{_e(k)}</dt><dd>{_e(v)}</dd>" for k, v in facts if v not in (None, "")) + '</dl>')
        for s in series:
            pts = s.get("points") or []
            h.append('<div class="tw"><table class="res evt"><caption>' + _e(s["label"]) + f' · {len(pts)} points</caption><tr><th>Time (h)</th>'
                     f'<th>Concentration ({_e(c["unit"])})</th><th>Status</th><th>SD</th><th>n</th><th>Record</th></tr>'
                     + "".join(f'<tr><td>{_f(p["t"], 4)}</td><td>{_f(p["c"], 4)}</td><td>{_e(p["status"])}</td><td>{_f(p.get("sd"))}</td>'
                               f'<td>{_e(p.get("n") if p.get("n") is not None else "—")}</td><td>{_e(p.get("record_id") or "—")}</td></tr>' for p in pts)
                     + '</table></div>')
        if c.get("notes"):
            h.append(f'<p class="ev notes">{_e(html.unescape(str(c["notes"])))}</p>')
        h.append('</details>')
    for ps in param_sets:
        c = ps["card"]
        if species_group(c["species"]) != species:
            continue
        t = _param_evidence([ps])
        h.append(f'<details class="pts" id="data-{_e(c["dataset_id"])}"><summary>{_e(c["dataset_id"])} · {_e(c["title"])}</summary>'
                 '<div class="tw"><table class="res evt"><tr>' + "".join(f"<th>{_e(x)}</th>" for x in t["head"]) + "</tr>"
                 + "".join("<tr>" + "".join(f"<td>{_e(v)}</td>" for v in r) + "</tr>" for r in t["rows"]) + '</table></div></details>')
    if not h:
        return ""
    return ('<section class="panel" id="points"><h2>Source data points</h2><p class="muted">Every observed point this page uses, as extracted '
            'from the source table (digitized values are readings of the published figure). Evidence links open the matching dataset.</p>'
            + "".join(h) + '</section>')


def _portal_links(portal):
    if portal:
        return ('<!--ABS-NAV--><a href="../index.html#categories">← All categories</a><a href="../index.html#handoff">Handoff summary</a>'
                '<a href="../report.html#absorption">Question report</a><!--/ABS-NAV-->')
    return '<!--ABS-NAV--><a href="../report.html#absorption">← EDA report</a><!--/ABS-NAV-->'


def _nav(portal, overview=True, studies=(), *, has_hypotheses=True):
    first = "" if overview else '<a href="index.html">← All species</a>'
    if studies:
        jump = "".join(f'<a href="#study-{_e(_slug(s[1] if isinstance(s, tuple) else s))}">{_e(s[0] if isinstance(s, tuple) else s)}</a>' for s in studies)
    else:
        jump = '<a href="#hypotheses">Hypotheses</a>' if has_hypotheses else ''
        jump += '<a href="#questions">Nine questions</a>'
    return f'<nav>{first}{_portal_links(portal)}{jump}</nav>'


_HASH_JS = ('<script>function openHash(){const id=decodeURIComponent(location.hash.slice(1));const el=id&&document.getElementById(id);'
            'if(!el)return;for(let p=el;p;p=p.parentElement){if(p.tagName==="DETAILS")p.open=true}el.scrollIntoView()}'
            'addEventListener("hashchange",openHash);openHash();</script>')


def _shell(title, body, script=""):
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{_e(title)} · EDA review</title><style>' + _portal_css() + ABS_CSS + HYP_CSS + '</style></head><body><main id="main">'
            + body + '</main>' + script + '</body></html>')


def _not_drawn_html(skips, intro):
    if not skips:
        return ""
    by = {}
    for k, lab, t in skips:  # one line per reason; items with the same reason share it
        by.setdefault(k, {}).setdefault(t, []).append(lab)
    by = {k: [(", ".join(x for x in labs if x) + ": " if any(labs) else "") + t for t, labs in v.items()] for k, v in by.items()}
    return ('<details class="panel" id="not-drawn"><summary>Panels not drawn, and why</summary><p class="muted">' + _e(intro) + '</p>'
            + "".join(f'<div class="limit"><div class="label">{_e(k)}</div><p>' + "<br>".join(_e(x) for x in v) + '</p></div>' for k, v in by.items())
            + '</details>')


def _footer():
    return ('<footer><a href="../report.html#absorption">Back to the EDA report</a><p>Source data are unchanged. The ±5 % error bound and the '
            f'span ratio of {SPAN_MIN:g} are project-set, so every test result carries SENSITIVITY_ONLY. This page does not record approval or '
            'start modeling.</p></footer>')


def _legend():
    return '<div class="legend">' + "".join(f'<span><span class="st {ST_CLASS[s]}">{_e(ST_SHORT[s])}</span>{_e(ST_MEANING[s])}</span>' for s in ST_ORDER) + '</div>'


def species_page_name(species):
    return f"species-{_slug(species)}.html"


def _by_study(datasets, param_sets, ivs):
    ds, ps, iv = {}, {}, {}
    for d in datasets:
        ds.setdefault(_study_key(d["card"]), []).append(d)
    for p in param_sets:
        ps.setdefault(_study_key(p["card"]), []).append(p)
    for i in ivs:
        iv.setdefault((i["card"]["study"], i["card"]["species"]), []).append(i)
    return ds, ps, iv


def render_pages(res, datasets, param_sets=(), base=None, portal=False, ivs=()):
    """Absorption in the EDA review portal's style: absorption/index.html lists the species and the nine questions per study;
    each species has its own page (absorption/species-<name>.html): species → study → nine question rows."""
    base = Path(base) if base else Path(".")
    skips = _skips(res, datasets, param_sets)
    see = _dn_see(res, base.parent)
    ren = res.get("render", {})
    engine = {"R_GGPLOT2": "R (ggplot2)", "MATPLOTLIB_FALLBACK": "matplotlib (R unavailable)"}.get(ren.get("engine"), ren.get("engine") or "not rendered")
    fallback = (f'<p class="notice">Figures were drawn with the matplotlib fallback because R was not available: {_e(ren.get("note"))}.</p>'
                if ren.get("engine") == "MATPLOTLIB_FALLBACK" else "")
    boards = res["status_boards"]
    bds, bps, bivs = _by_study(datasets, param_sets, ivs)
    labels = _absorption_names(boards, bds, bps)
    panels = {_board_key(b): _study_panels(bds.get(_board_key(b), []), bps.get(_board_key(b), []), res["dose_series"], res["ev_iv"], res["conditions"])
              for b in boards}
    files = {_board_key(b): {v["file"] for vs in panels[_board_key(b)].values() for v in vs} for b in boards}
    species = {sp for b in boards for sp in _board_species(b)}
    n_fig = {sp: len(set().union(*[files[_board_key(b)] for b in boards if sp in _board_species(b)])) for sp in species}
    order = sorted(species, key=lambda sp: (sp == "Species not stated", -n_fig[sp], sp))
    pages, info = {}, []
    for sp in order:
        sb = sorted((b for b in boards if sp in _board_species(b)), key=lambda b: b["study"])
        studies = [b["study"] for b in sb]
        sk = [x[:3] for x in skips if x[3] == sp]
        h = [_nav(portal, overview=False, studies=[(b["study"] + " / " + b.get("regimen", ""), _board_key(b)) for b in sb]), '<div class="eyebrow">EDA figure review · Absorption</div>', f'<h1>{_e(sp)}</h1>',
             f'<p class="lead">Nine questions on how the drug enters the circulation, for {"study" if len(studies) == 1 else "studies"} '
             f'{_e(", ".join(studies))}. Each row gives the status, one conclusion, the evidence that explains it best, and what is missing. After the '
             'nine questions, one working hypothesis per study, species and regimen says what a model should verify next.</p>',
             f'<p class="muted">{n_fig[sp]} panels · Computed by host code from observed points; {FIT_NOTE} · Figures drawn with {_e(engine)} · '
             'Human review pending</p>', fallback, _legend()]
        for b in sb:
            ivs_b = _scope_ivs(b, ivs)
            h.append(_study_html(b, bds.get(_board_key(b), []), bps.get(_board_key(b), []), ivs_b, base, see.get(_board_key(b), [])))
        used = {v["file"] for b in sb for q in b.get("questions", []) for v in q["views"]} | {
            (q.get("primary") or {}).get("file") for b in sb for q in b.get("questions", [])}
        loose = [v for b in sb for vs in panels[_board_key(b)].values() for v in vs if v["file"] not in used]
        if loose:
            h.append(f'<details class="panel" id="loose"><summary>Other panels ({len(loose)})</summary><p class="muted">Panels that no question row '
                     'opens, such as the overview panels of curves outside plasma, serum and blood.</p>' + _thumbs(loose) + '</details>')
        h.append(_not_drawn_html(sk, "A panel is drawn only when its data allow it and, for tier 2, when tier 1 shows what it tests. "
                                     "Test results are still in the question rows."))
        h.append(_points_html(datasets, param_sets, ivs, sp))
        h.append(_footer())
        name = species_page_name(sp)
        pages[name] = _shell(f"Absorption · {sp}", "".join(h), _HASH_JS + HYP_JS)
        prim = [q["primary"]["file"] for b in sb for q in b.get("questions", []) if (q.get("primary") or {}).get("kind") == "panel" and q["primary"].get("file")]
        counts = {}
        for b in sb:
            for q in b.get("questions", []):
                counts[q["status"]] = counts.get(q["status"], 0) + 1
        info.append({"species": sp, "page": name, "figures": n_fig[sp], "studies": studies, "thumbnails": prim[:3],
                     "counts": {ST_CODE[k]: v for k, v in counts.items()}, "_counts": counts})
    # overview: one card per species, then the nine questions of every study at a glance
    n_curves = sum(1 for d in datasets for s in d["series"] if "tmax" in s["metrics"])
    total = len(set().union(*files.values())) if files else 0
    h = [_nav(portal, has_hypotheses=bool(boards)), '<div class="eyebrow">EDA figure review</div><h1>Absorption</h1>',
         f'<p class="lead">How the drug enters the circulation, as nine questions for each study ({RULES_VERSION} items 16–23): onset, input speed, '
         'excluded input models, second rise, long tail, extent, dose and condition effects, and individuals against the mean. Open a species, '
         'then a study; each question shows its conclusion next to the evidence that explains it best.</p>',
         (f'<p class="muted">{total} panels · {len(order)} species · {len(boards)} study/species/regimen scopes · {len(datasets)} curve datasets ({n_curves} curves) and '
          f'{len(param_sets)} reported-parameter datasets · Computed by host code from observed points; {FIT_NOTE} · Figures drawn with {_e(engine)} · '
          'Human review pending</p>' if boards else   # nothing to show: say why in plain words, not as a row of zeros
          f'<p class="concl plain"><b>{_e(_absorption_empty_reason({"datasets": datasets, "reported_parameter_ev_datasets": param_sets, "iv_reference_count": len(ivs)}).replace("No absorption figures: t", "T"))}</b></p>'),
         fallback,
         _hoverview_html(sorted(boards, key=lambda b: (min(order.index(x) if x in order else len(order) for x in _board_species(b)), b["study"])),
                         lambda b: species_page_name(_board_species(b)[0]), bds, labels),
         '<div class="section-head" id="species"><h2>Review by species</h2><span class="muted">Open a species for its studies and their nine questions.</span></div>'
         '<div class="categories">']
    for x in info:
        thumbs = "".join(f'<img src="{_e(s)}" alt="Preview of {_e(s)}" loading="lazy">' for s in x["thumbnails"])
        chips = " ".join(f'<span class="st {ST_CLASS[s]}">{x["_counts"][s]} {_e(ST_SHORT[s].lower())}</span>' for s in ST_ORDER if x["_counts"].get(s))
        h.append(f'<a class="category" id="sp-{_e(_slug(x["species"]))}" href="{_e(x["page"])}"><span class="badge">{len(x["studies"])} '
                 f'stud{"y" if len(x["studies"]) == 1 else "ies"}</span><h3>{_e(x["species"])}</h3><p class="muted">'
                 f'{x["figures"]} panels</p><p>{chips}</p>' + (f'<div class="thumbs">{thumbs}</div>' if thumbs else "")
                 + '<span class="open">Open the nine questions →</span></a>')
    h.append('</div>')
    rank = {sp: k for k, sp in enumerate(order)}
    head = "".join(f'<th title="{_e(QSPEC[n][1])}">Q{n}<br><span class="muted">{_e(Q_SHORT[n])}</span></th>' for n in range(1, 10)) + (
        '<th title="The working hypothesis a model should verify">H<br><span class="muted">Hypothesis</span></th>')
    trs = []
    for b in sorted(boards, key=lambda b: (min(rank.get(x, len(rank)) for x in _board_species(b)), b["study"])):
        page = species_page_name(_board_species(b)[0])
        cells = "".join(f'<td><a href="{_e(page)}#{_qid(_board_key(b), q["q"])}" title="{_e(q["text"])}"><span class="st {ST_CLASS[q["status"]]}">'
                        f'{_e(ST_SHORT[q["status"]])}</span></a></td>' for q in b.get("questions", [])) + (
            f'<td><a href="{_e(page)}#{_hid(_board_key(b))}" title="{_e(b["hypothesis"]["text"])}">{_hchip(b["hypothesis"])}</a></td>' if b.get("hypothesis") else "<td></td>")
        trs.append(f'<tr><td><a href="{_e(page)}#study-{_e(_slug(_board_key(b)))}">{_e(labels[_board_key(b)])}</a></td>{cells}</tr>')
    h.append('<section class="panel" id="questions"><h2>The nine questions by study</h2><p class="muted">Each cell opens the question row on the '
             'species page; hover for the conclusion. H opens the working hypothesis and its review.</p>' + _legend()
             + f'<div class="tw"><table class="res qtab"><tr><th>Study</th>{head}</tr>{"".join(trs)}</table></div></section>')
    h.append(_not_drawn_html([x[:3] for x in skips if x[3] is None], "Panels that no species can have with these data."))
    h.append(_footer())
    pages["index.html"] = _shell("Absorption", "".join(h))
    for x in info:
        x.pop("_counts", None)
    thumbs = [x["thumbnails"][0] for x in info if x["thumbnails"]][:3]
    presentation = {"page": "absorption/index.html", "figures": total, "species": info, "thumbnails": thumbs,
                    "questions": [{"study": b["study"], "scope_id": _board_key(b), "species": b.get("species_group"), "page": species_page_name(_board_species(b)[0]),
                                   "statuses": {str(q["q"]): q["status_code"] for q in b.get("questions", [])},
                                   "hypothesis": {k: (b.get("hypothesis") or {}).get(k) for k in ("id", "state", "text")}} for b in boards],
                    "not_drawn": [{"figure": k, "item": lab, "reason": t, "species": sp} for k, lab, t, sp in skips]}
    return pages, presentation


# ---------------------------------------------------------------- working hypothesis per study (after the nine questions)
#
# The nine questions describe what the observed points show. For each study, this part states one general suspicion that
# a model has to verify. It is chosen from a fixed space of absorption cases and their combinations. Every case and every
# combination is evaluated against the same findings and kept in absorption/hypothesis_context.json, which the pages do
# not show, so that the choice can be double-checked. A reviewer adds an opinion as a file in absorption/reviews/; the
# next build (the revision round) applies it and writes a new revision of the hypothesis.

HYP_VERSION = "EDA_ABSORPTION_HYPOTHESIS_3"   # 2: a dose or tail difference is a strong signal only when a test supports it
FLIP_RATIO = HL_CUTS[1]   # review guide Q5: an EV apparent t½ at least 1.25× the IV value is "shallower" and makes slow absorption a candidate
SHARE_MIN = 0.8     # project-set: the common AUC window holds at least 80 % of each dose group's observed exposure (AUC to its last sample)
TREND_RATIO = 2.0   # project-set: Tmax or t1/2 that changes 2-fold or more across doses is a hint
SUG, HINT = "POINTS_TO", "HINT"
TAIL_ALPHA = 0.05   # project-set: two-sided level of the EV-against-IV slope test

# axis -> (title, [(level, label, n extra parameters, parameter names, ladder label, what the fit has to show)])
HYP_AXES = {
    "onset": ("Onset", [
        ("immediate", "input from the dosing time", 0, "", "", ""),
        ("fixed_lag", "a short fixed lag before input starts", 1, "tlag", "fixed lag (tlag)",
         "tlag above 0 with a CI, and shorter than the first quantified sample"),
        ("transit", "a gradual delay through transit compartments", 2, "MTT, n", "transit chain (MTT, n)",
         "MTT and n estimable from the rising samples, and better than a fixed lag on the same data"),
        ("variable_lag", "a lag or absorption rate that differs between animals", 1, "BSV on tlag or ka", "between-animal variability on tlag or ka",
         "a between-animal variance on tlag or ka estimable from single-animal curves"),
    ]),
    "shape": ("Input shape", [
        ("first_order", "first-order input", 1, "ka", "first-order input (ka)", ""),
        ("zero_order", "zero-order input of finite duration", 1, "D1", "zero-order input (D1)",
         "a D1 estimate that fits better than first-order input with the same number of parameters (AIC)"),
        ("zero_then_first", "zero-order release followed by first-order absorption", 2, "D1, ka", "zero-order release, then ka",
         "both D1 and ka estimable"),
        ("parallel_first", "two parallel first-order inputs, one fast and one slow", 3, "ka1, ka2, fraction", "two parallel first-order inputs",
         "two separated ka values and a fraction between 0 and 1"),
        ("parallel_zero_first", "parallel zero-order and first-order input", 3, "D1, ka, fraction", "parallel zero- and first-order input",
         "a fraction between 0 and 1 with a CI"),
        ("weibull_front", "front-loaded input with a long slow tail (Weibull, β < 1)", 2, "τ, β", "Weibull input (β < 1)",
         "β below 1 with a CI that excludes 1"),
        ("weibull_sigmoid", "input that starts slowly and then speeds up (Weibull, β > 1)", 2, "τ, β", "Weibull input (β > 1)",
         "β above 1 with a CI that excludes 1"),
        ("inverse_gaussian", "input times spread as an inverse Gaussian", 2, "MAT, CV²", "inverse Gaussian input",
         "MAT and CV² estimable, and better than a Weibull input with the same number of parameters"),
    ]),
    "second": ("Second input", [
        ("none", "one input episode", 0, "", "", ""),
        ("two_inputs", "a second, separate input episode (two sites, or interrupted emptying)", 2, "second lag, fraction", "second input episode",
         "the dip and the second rise reproduced, with an estimable second lag and fraction"),
        ("recirculation", "enterohepatic recirculation", 3, "release time, fraction, rate", "enterohepatic recirculation",
         "a release time that matches feeding, with bile or IV evidence"),
    ]),
    "tail": ("Terminal phase", [
        ("disposition", "a decline set by disposition (ka > k)", 0, "", "", ""),
        ("absorption", "a decline set by slow absorption (flip-flop, ka < k)", 0, "ka < k", "flip-flop (ka < k)",
         "ka below k with the IV disposition fixed, and equal to the terminal slope"),
    ]),
    "dose": ("Dose dependence", [
        ("linear", "input linear in dose", 0, "", "", ""),
        ("saturable_rate", "an absorption rate that saturates as the dose rises, with extent kept", 1, "Vmax, Km", "saturable absorption (Vmax, Km)",
         "Km inside the dose range, so that Cmax/D falls with dose while AUC/D stays"),
        ("extent_down", "a fraction absorbed that falls as the dose rises", 1, "F by dose", "F falling with dose",
         "F falling with dose while IV clearance stays constant over the range"),
        ("extent_up", "a fraction absorbed that rises with dose (saturable efflux or first pass)", 1, "F by dose", "F rising with dose",
         "F rising with dose while IV clearance stays constant over the range"),
    ]),
    "other": ("Explanation outside absorption", [
        ("none", "no explanation outside absorption", 0, "", "", ""),
        ("saturable_elimination", "saturable elimination (outside absorption)", 1, "Vmax, Km of CL", "Michaelis–Menten elimination",
         "Michaelis–Menten clearance from IV curves across doses"),
        ("multicompartment", "multi-compartment disposition (outside absorption)", 2, "Q, V2", "two-compartment disposition",
         "a second disposition compartment from the IV curve"),
        ("binding", "concentration-dependent binding or distribution (outside absorption)", 1, "fu by concentration",
         "concentration-dependent binding", "free and total concentrations at matched times"),
    ]),
}
HYP_ORDER = tuple(HYP_AXES)
HYP_DEFAULT = {"onset": "immediate", "shape": "first_order", "second": "none", "tail": "disposition", "dose": "linear", "other": "none"}
COND_LEVELS = [
    ("same", "the {a} changes nothing", 0, "", "", ""),
    ("extent_only", "the {a} changes extent only", 1, "F by {a}", "F by {a}", "only F differs between the two curves"),
    ("rate_shape", "the {a} changes the input rate or shape, not only extent", 1, "ka or shape by {a}", "ka or input shape by {a}",
     "a {a}-specific ka or input shape with shared disposition"),
    ("disposition_scaling", "CL and V scale together between the two curves", 1, "CL and V by {a}", "CL and V by {a}",
     "IV curves under both conditions"),
]
HYP_CODES = {"onset": {"immediate": "I", "fixed_lag": "L", "transit": "T", "variable_lag": "V"},
             "shape": {"first_order": "FO", "zero_order": "ZO", "zero_then_first": "ZF", "parallel_first": "PF", "parallel_zero_first": "PZ",
                       "weibull_front": "W<1", "weibull_sigmoid": "W>1", "inverse_gaussian": "IG"},
             "second": {"none": "1", "two_inputs": "2", "recirculation": "EHC"}, "tail": {"disposition": "D", "absorption": "FF"},
             "dose": {"linear": "LIN", "saturable_rate": "SAT", "extent_down": "F-", "extent_up": "F+"},
             "other": {"none": "0", "saturable_elimination": "MM", "multicompartment": "2CMT", "binding": "BIND"}}
HYP_STATE = {"PENDING": ("st-hyp", "Review pending"), "AGREED": (ST_CLASS[ST_YES], "Agreed"), "REVISED": (ST_CLASS[ST_PART], "Revised"),
             "REJECTED": (ST_CLASS[ST_NO], "Rejected")}

# GPT's r4.3 candidate list (absorption_mechanisms_r43.json, kept in _backup_20261106_port58_absorption): where each entry sits here
GPT_CROSSWALK = {
    "first_order": ("case", "shape.first_order", ""), "first_order_lag": ("combination", "onset.fixed_lag + shape.first_order", ""),
    "zero_order": ("case", "shape.zero_order", ""), "zero_order_lag": ("combination", "onset.fixed_lag + shape.zero_order", ""),
    "weibull_lt1_immediate": ("case", "shape.weibull_front", ""), "weibull_lt1_lag": ("combination", "onset.fixed_lag + shape.weibull_front", ""),
    "weibull_eq1_immediate": ("alias", "shape.first_order", "Weibull with β = 1 is first-order input with ka = 1/τ."),
    "weibull_eq1_lag": ("alias", "onset.fixed_lag + shape.first_order", "Same model as first_order_lag."),
    "weibull_gt1_immediate": ("case", "shape.weibull_sigmoid", ""), "weibull_gt1_lag": ("combination", "onset.fixed_lag + shape.weibull_sigmoid", ""),
    "transit": ("case", "onset.transit + shape.first_order", ""),
    "transit_lag": ("not_kept", "onset.transit", "A fixed lag before a transit chain is not separately identifiable from the chain's delay."),
    "parallel_immediate": ("case", "shape.parallel_first", ""), "separated_inputs": ("case", "second.two_inputs", ""),
    "burst_sustained": ("alias", "shape.parallel_zero_first or shape.parallel_first", "A burst is the fast fraction of two parallel inputs."),
    "inverse_gaussian": ("case", "shape.inverse_gaussian", ""), "input_rate_limited": ("case", "dose.saturable_rate", ""),
    "uptake_extent_loss": ("case", "dose.extent_down", ""),
    "efflux_saturation": ("mechanism", "dose.extent_up", "A physiological reading of F rising with dose (enteral); needs gut data."),
    "first_pass_saturation": ("mechanism", "dose.extent_up", "A physiological reading of F rising with dose (PO, IP); needs portal or metabolite data."),
    "solubility_limited": ("mechanism", "dose.saturable_rate or shape.zero_order", "Dose-dependent dissolution acts as a saturable rate or a dose-dependent D1."),
    "gastric_emptying": ("mechanism", "onset.fixed_lag or second.two_inputs", "Enteral only; needs feeding and emptying records."),
    "absorption_window": ("mechanism", "dose.extent_down or shape.zero_order", "Enteral only; needs regional or formulation data."),
    "depot_release": ("mechanism", "shape.zero_order, shape.weibull_front or shape.parallel_first", "SC or IM only; needs injection-site data."),
    "pulmonary_enteral": ("mechanism", "shape.parallel_first", "Lung plus swallowed fraction as two parallel inputs; needs deposition data."),
    "enterohepatic": ("case", "second.recirculation", ""), "flip_flop": ("case", "tail.absorption", ""),
    "ongoing_input": ("alias", "tail.absorption", "Absorption that continues through the sampled decline."),
    "multicompartment": ("outside_absorption", "other.multicompartment", ""),
    "nonlinear_elimination": ("outside_absorption", "other.saturable_elimination", ""),
    "parallel_linear_saturable_elimination": ("outside_absorption", "other.saturable_elimination", "Linear plus Michaelis–Menten clearance."),
    "binding_distribution": ("outside_absorption", "other.binding", ""),
    "changing_clearance": ("data_check", "occasion", "Time- or state-dependent clearance is checked with the dosing history."),
    "occasion_effect": ("data_check", "occasion", ""), "baseline_carryover": ("data_check", "baseline", "Predose drug, carryover or assay signal."),
    "timing_sampling": ("data_check", "sampling", "Dose and draw times, BLQ, units, animal identity."),
    "f_change": ("condition_level", "condition.extent_only", ""), "cl_v_coscaling": ("condition_level", "condition.disposition_scaling", ""),
    "rate_only": ("condition_level", "condition.rate_shape", ""),
    "mixed_rate_extent": ("not_kept", "condition.rate_shape", "Separating rate and extent changes needs more than one condition pair."),
    "parallel_linear_saturable_input": ("not_kept", "dose.saturable_rate", "A linear plus a saturable input path is not identifiable from these designs."),
    "variable_lag": ("case", "onset.variable_lag", ""), "finite_administration": ("alias", "shape.zero_order", "A known administration time fixes D1."),
    "parallel_zero_first": ("case", "shape.parallel_zero_first", ""),
    "dose_proportional": ("observation", "Q7", "A T3 or T3p result, not an absorption case."),
    "shared_one_compartment": ("observation", "Q5", "A T4 premise, not an absorption case."),
}


# short names for summaries (the full phrases stay in the hypothesis sentence and the model ladder)
HYP_SHORT = {"onset.fixed_lag": "fixed lag", "onset.transit": "transit delay", "onset.variable_lag": "variable lag or ka",
             "shape.zero_order": "zero-order input", "shape.zero_then_first": "zero-order then first-order input",
             "shape.parallel_first": "two parallel inputs", "shape.parallel_zero_first": "parallel zero/first-order input",
             "shape.weibull_front": "Weibull input (β<1)", "shape.weibull_sigmoid": "Weibull input (β>1)",
             "shape.inverse_gaussian": "inverse Gaussian input", "second.two_inputs": "second input episode",
             "second.recirculation": "enterohepatic recirculation", "tail.absorption": "flip-flop",
             "dose.saturable_rate": "saturable absorption", "dose.extent_down": "F falling with dose", "dose.extent_up": "F rising with dose",
             "other.saturable_elimination": "saturable elimination", "other.multicompartment": "two-compartment disposition",
             "other.binding": "concentration-dependent binding"}
SUMMARY_WORDS = 230   # the overview summary stays under the 240 words that verify_suite allows


def _hshort(comp, F):
    return HYP_SHORT.get(comp) or _hphrase(comp, F, True)


def _hlev(axis, level):
    for x in (COND_LEVELS if axis == "condition" else HYP_AXES[axis][1]):
        if x[0] == level:
            return x
    raise KeyError(f"{axis}.{level}")


def _hcost(c, cond=None):
    return sum(_hlev(a, c[a])[2] for a in HYP_ORDER) + (_hlev("condition", cond)[2] if cond else 0)


def _hvalid(c):
    if c["onset"] == "transit" and c["shape"] != "first_order":
        return False  # the transit chain feeds a first-order absorption step
    if c["tail"] == "absorption" and c["shape"] in ("zero_order", "weibull_sigmoid"):
        return False  # a flip-flop tail needs an input with a first-order-like or heavier tail
    return True


def _hspace():
    return [c for c in (dict(zip(HYP_ORDER, v)) for v in itertools.product(*[[x[0] for x in HYP_AXES[a][1]] for a in HYP_ORDER])) if _hvalid(c)]


def _hcode(c):
    return "-".join(HYP_CODES[a][c[a]] for a in HYP_ORDER)


def _hsig(sid, q, strength, text, short, explain, data=(), factor="main"):
    return {"id": sid, "q": q, "strength": strength, "text": text, "short": short, "explained_by": [list(x) for x in explain],
            "datasets": sorted(set(data)), "factor": factor}


def _hrule(rid, q, text, pattern, factor="main", units=None):
    """A formal rule sets aside the complete combinations in `pattern`. Rule decision R5 (2026-11-24): `units` holds the required
    units fixed before the results (an unassessable one stays in the denominator), the assessable ones, the formal contradictions
    and their directions; `level` is BOARD only when every required unit is formally excluded in the same direction."""
    r = {"id": rid, "q": q, "text": text, "pattern": pattern, "factor": factor}
    if units is not None:
        n, k = len(units["required"]), len(units["formal"])
        dirs = sorted(set(units["directions"]))
        r["units"] = {"check": units.get("check", rid), "unit_kind": units["unit_kind"], "required": list(units["required"]),
                      "assessable": list(units["assessable"]), "formal": list(units["formal"]), "required_n": n,
                      "assessable_m": len(units["assessable"]), "formal_k": k, "directions": dirs,
                      "correction": units.get("correction", "one prespecified comparison per unit; no family beyond the unit")}
        r["level"] = "BOARD" if n and k == n and len(dirs) == 1 else "FORMAL_UNIT"
    return r


def _hexplains(c, s, cond=None):
    for alt in s["explained_by"]:
        if all((cond == lv if ax == "condition" else c.get(ax) == lv) for ax, lv in (x.split(".") for x in alt)):
            return alt
    return None


def _hpair_key(r):
    """EV against IV: the dose-matched pair first (a dose difference lets saturable elimination explain a slower tail), then the
    closest doses, then dataset ids."""
    de, di = r.get("dose_ev"), r.get("dose_iv")
    gap = abs(math.log(de / di)) if isinstance(de, (int, float)) and isinstance(di, (int, float)) and de > 0 and di > 0 else math.inf
    return (gap, str(r.get("ev")), str(r.get("iv")))


def _dose_units(series, check):
    """R5 units of the dose-proportionality rule: every dose series of the board (fixed before the results; one that could not be
    assessed stays in the denominator), the assessable ones and those with a formal exclusion, with its direction."""
    req, ass, frm, dirs = [], [], [], []
    for r in series:
        uid = r.get("label") or ",".join(r.get("dataset_ids") or [])
        req.append(uid)
        if r.get("status") != "ASSESSED":
            continue
        if check == "T3":
            lab, flags, ratio = r.get("t3_label", ""), r.get("t3_flags"), r.get("R")
        else:
            p = r.get("t3p") or {}
            lab, flags, ratio = p.get("t3p_label", ""), p.get("t3p_flags"), r.get("R_window")
        if lab in ("NOT_EXCLUDED",) or str(lab).startswith("EXCLUDED"):
            ass.append(uid)
        if str(lab).startswith("EXCLUDED") and not set(flags or []) & _HOLD:
            frm.append(uid)
            dirs.append("exposure per dose rises" if (ratio or 1) > 1 else "exposure per dose falls")
    return {"check": check, "unit_kind": "dose series (study, species, route, matrix)", "required": req, "assessable": ass,
            "formal": frm, "directions": dirs}


def _hf_dose(F, chk, dose_series_res, ds, ids, levels, pss, rule, sig):
    """Question 7: dose and exposure findings. Part of _hfindings (split 2026-11-26 without change)."""
    dose_pss = _dose_param_sets(pss)
    if len(dose_pss) != len(pss):
        F["notes"].append(_dose_param_condition(dose_pss) + " Other reported conditions remain separate source evidence and are not pooled in this dose comparison.")
    pss = dose_pss
    params = [p for ps in pss for p in ps["params"]]
    dsr = next((r for r in dose_series_res if set(r["dataset_ids"]) <= ids and r["status"] == "ASSESSED"), None)
    t3r = next(((ps["card"], ps["analysis"]["t3"]) for ps in pss if (ps.get("analysis") or {}).get("t3")), None)
    by_dose = lambda name: sorted({(p["dose"], p["value"]) for p in params if p["param"] == name and p.get("dose")})  # noqa: E731
    aucs = by_dose("AUC")

    tested = [False]   # a test (T3 or T3p) excludes dose-proportional exposure

    def exposure(R_, lo, hi, where, extra, data, test_out=None):
        rng = f"from {lo:g} to {hi:g} mg/kg"
        # a ratio outside 0.80–1.25 points to a case only when a test excludes proportionality; otherwise it is a hint
        # The exposure test evaluates proportionality. Even a precise area difference
        # cannot distinguish bioavailability from clearance or a truncated input.
        firm = HINT
        if R_ > 1.25 or (test_out == "up"):
            sig(_hsig("exposure_rises", 7, firm, f"Exposure per dose rises with dose: {where} is {R_:.2f}× {rng}{extra}.", f"{where} {R_:.2f}× {rng}",
                      [["dose.extent_up"], ["other.saturable_elimination"]], data))
            return "up"
        if R_ < 0.8 or (test_out == "down"):
            sig(_hsig("exposure_falls", 7, firm, f"Exposure per dose falls with dose: {where} is {R_:.2f}× {rng}{extra}.", f"{where} {R_:.2f}× {rng}",
                      [["dose.extent_down"], ["other.binding"]], data))
            return "down"
        return "kept"

    if dsr:
        F["assessable"].append("dose")
        lo, hi, R_, cr, T = dsr["doses"][0], dsr["doses"][-1], dsr["R_window"], dsr["cmax_d_ratio"], dsr["window_end_h"]
        t3x = dsr["t3_label"].startswith("EXCLUDED") and not set(dsr.get("t3_flags") or []) & _HOLD
        p = dsr.get("t3p") or {}
        t3px = p.get("t3p_label", "").startswith("EXCLUDED") and not set(p.get("t3p_flags") or []) & _HOLD
        out_dir = ("up" if (dsr.get("R") or 1) > 1 else "down") if t3x else None
        tested[0] = bool(t3x or t3px)
        pm = None if (dsr.get("animal_auc") or {}).get("status") == "ASSESSED" else dsr.get("t3_power")
        extra = ((f" (power-model slope {pm['beta']:.2f}, 95 % CI {pm['ci'][0]:.2f}–{pm['ci'][1]:.2f}, which "
                  + ("excludes" if t3x else "does not exclude") + " dose proportionality)") if pm else
                 f" (T3 = {dsr['t3_label']}, R = {dsr['R']:.2f})" if t3x else "" if t3px else " (no test: group means without SD)")
        d_ids = dsr["dataset_ids"]
        rows = dsr["rows"]
        shares = [x["share_window"] for x in rows if isinstance(x.get("share_window"), (int, float))]
        t_lo, t_hi = rows[0].get("tmax"), rows[-1].get("tmax")
        short = bool(shares and min(shares) < SHARE_MIN and not t3x)
        F["bounds"]["auc_window"] = {"end_h": T, "min_share": float(min(shares)) if shares else None, "short": short, "tmax_low_dose": t_lo, "tmax_high_dose": t_hi}
        if short:
            # a common window that ends early holds more of the exposure of the group that peaks earlier: a ratio that moves against that
            # bias still reads as exposure; one that moves with it can also be slower or faster absorption
            later = t_lo is not None and t_hi is not None and t_hi > t_lo
            earlier = t_lo is not None and t_hi is not None and t_hi < t_lo
            why = (f"the common window 0–{T:g} h holds only {min(shares):.0%} of the observed exposure of one dose group, so it favours the group "
                   "that peaks earlier")
            if (R_ > 1.25 and not earlier) or (R_ < 0.8 and not later):
                e = exposure(R_, lo, hi, f"AUC/D over 0–{T:g} h", f"; {why}, which runs against this direction", d_ids)
            elif R_ < 0.8 or R_ > 1.25:
                up = R_ > 1.25
                sig(_hsig("auc_short_window", 7, HINT, f"AUC/D over 0–{T:g} h is {R_:.2f}× from {lo:g} to {hi:g} mg/kg, but {why} and the "
                          f"{'higher' if up else 'lower'} dose peaks earlier ({t_lo:.3g} → {t_hi:.3g} h): faster or slower absorption can make this "
                          "ratio as well as extent.", f"AUC/D over 0–{T:g} h {R_:.2f}× in a short window",
                          [["dose.extent_up"], ["other.saturable_elimination"]] if up else
                          [["dose.saturable_rate"], ["dose.extent_down"], ["other.binding"]], d_ids))
                e = "short"
            else:
                e = "short"   # AUC/D kept over a short window says nothing about extent
            if cr < 0.5:
                # R7 item 3: the screen needs comparable windows, so here the number is reported without supporting a candidate
                sig(_hsig("peak_falls", 7, HINT, f"Cmax/D at {hi:g} mg/kg is {cr:.2f}× that at {lo:g} mg/kg; {why}, so AUC/D cannot tell slower "
                          "absorption from lower extent here.", f"Cmax/D {cr:.2f}× from {lo:g} to {hi:g} mg/kg (AUC window short)",
                          [], d_ids))
        else:
            e = exposure(R_, lo, hi, f"AUC/D over 0–{T:g} h", extra, d_ids, out_dir)
        # R7 item 3: the Cmax/D screen is descriptive; when its conditions hold it gives indirect support at most (HINT), also when
        # T3 or T3p has a formal result, because those answer window exposure and matched-time concentration, not the absorption rate
        screen = dsr.get("cmax_screen") or {}
        if e == "kept" and cr < 0.5 and screen.get("result") == "CMAX_D_LOW_AUC_KEPT":
            sig(_hsig("rate_saturates", 7, HINT, f"Cmax/D at {hi:g} mg/kg is {cr:.2f}× that at {lo:g} mg/kg while AUC/D over 0–{T:g} h stays within "
                      f"0.80–1.25 ({R_:.2f}×) (descriptive screen).", f"Cmax/D {cr:.2f}× from {lo:g} to {hi:g} mg/kg with AUC/D {R_:.2f}×",
                      [["dose.saturable_rate"]], d_ids))
        elif e == "kept" and cr > 2.0 and screen.get("result") == "CMAX_D_HIGH_AUC_KEPT":
            sig(_hsig("peak_rises_only", 7, HINT, f"Cmax/D at {hi:g} mg/kg is {cr:.2f}× that at {lo:g} mg/kg while AUC/D stays within 0.80–1.25 "
                      f"({R_:.2f}×) (descriptive screen).", f"Cmax/D {cr:.2f}× with AUC/D {R_:.2f}×", [], d_ids))
        elif e == "kept" and (cr < 0.5 or cr > 2.0):
            sig(_hsig("peak_outside_screen", 7, HINT, f"Cmax/D at {hi:g} mg/kg is {cr:.2f}× that at {lo:g} mg/kg; the screen does not apply "
                      f"({screen.get('reason') or 'conditions not met'}).", f"Cmax/D {cr:.2f}× (screen not applicable)", [], d_ids))
        formal_area = t3x and dsr.get("t3_data_level") != "GROUP_MEAN_POWER_MODEL"
        if formal_area or t3px:
            rule(_hrule("T3" if formal_area else "T3p", 7, ("T3 (Q7) excludes dose-proportional exposure." if formal_area else
                                                    "T3p (Q7) excludes equal dose-normalized concentrations across doses."),
                        {"dose": ["linear"], "other": ["none", "multicompartment"]},
                        units=_dose_units([r for r in dose_series_res if set(r["dataset_ids"]) <= ids], "T3" if formal_area else "T3p")))
        if dsr["e2_label"] == "POINTS_TO_NONLINEARITY":
            th = [x["thalf"] for x in dsr["rows"] if x.get("thalf")]
            sig(_hsig("thalf_rises", 7, HINT, f"The apparent t½ rises with dose ({_f(th[0])} → {_f(th[-1])} h) and the ranges do not overlap.",
                      f"apparent t½ {_f(th[0])} → {_f(th[-1])} h with dose", [["dose.saturable_rate", "tail.absorption"], ["other.saturable_elimination"]], d_ids))
        tm = [x["tmax"] for x in dsr["rows"]]
        if all(tm) and all(a <= b for a, b in zip(tm, tm[1:])) and tm[-1] / tm[0] >= TREND_RATIO:
            sig(_hsig("tmax_rises", 7, HINT, f"Tmax rises with dose ({tm[0]:.3g} → {tm[-1]:.3g} h).", f"Tmax {tm[0]:.3g} → {tm[-1]:.3g} h with dose",
                      [["dose.saturable_rate"]], d_ids))
        if dsr.get("occasion") not in (None, "SINGLE_DOSE"):
            chk({"id": "occasion", "q": 7, "text": f"The dose series comes from {str(dsr['occasion']).replace('_', ' ').lower()}: model the dosing "
                 "history, because accumulation or time-dependent clearance can change exposure per dose."})
    elif t3r:
        F["assessable"].append("dose")
        c, t = t3r
        x = t["t3_label"].startswith("EXCLUDED") and not set(t.get("t3_flags") or []) & _HOLD
        exposure(t["R"], t["dose_pair"][0], t["dose_pair"][1], "the reported AUC/D", f" (T3 = {t['t3_label']}, 95 % CI {t['ci'][0]:.2f}–{t['ci'][1]:.2f})",
                 [c["dataset_id"]], ("up" if t["R"] > 1 else "down") if x else None)
        if x:
            req = [(ps["card"], ps["analysis"]["t3"]) for ps in pss if (ps.get("analysis") or {}).get("t3")]
            ok = lambda t: t.get("t3_label") in ("NOT_EXCLUDED", "EXCLUDED_UNDER_STATED_ASSUMPTIONS") or str(t.get("t3_label", "")).startswith("EXCLUDED")  # noqa: E731
            fx = [(cd, t) for cd, t in req if str(t.get("t3_label", "")).startswith("EXCLUDED") and not set(t.get("t3_flags") or []) & _HOLD]
            rule(_hrule("T3", 7, "T3 on the reported AUC, SD and n (Q7) excludes dose-proportional exposure.",
                        {"dose": ["linear"], "other": ["none", "multicompartment"]},
                        units={"unit_kind": "reported AUC set with SD and n", "required": [cd["dataset_id"] for cd, _ in req],
                               "assessable": [cd["dataset_id"] for cd, t in req if ok(t)], "formal": [cd["dataset_id"] for cd, _ in fx],
                               "directions": ["exposure per dose rises" if t["R"] > 1 else "exposure per dose falls" for _, t in fx]}))
    elif len({d for d, _ in aucs}) >= 2:
        F["assessable"].append("dose")
        (dl, al), (dh, ah) = aucs[0], aucs[-1]
        exposure((ah / dh) / (al / dl), dl, dh, "the reported AUC/D", " (description; no SD or n)", [ps["card"]["dataset_id"] for ps in pss])
    if not dsr:
        for name, sid, txt in (("THALF", "thalf_rises", "reported t½"), ("TMAX", "tmax_rises", "reported Tmax")):
            v = by_dose(name)
            unit = next((p.get("unit") or "" for p in params if p["param"] == name), "")
            if (len({d for d, _ in v}) == len(v) and len(v) >= 2 and v[0][1]
                    and all(a[1] <= b[1] for a, b in zip(v, v[1:])) and v[-1][1] / v[0][1] >= TREND_RATIO):
                F["assessable"] = sorted(set(F["assessable"]) | {"dose"})
                expl = [["dose.saturable_rate", "tail.absorption"], ["other.saturable_elimination"]] if name == "THALF" else [["dose.saturable_rate"]]
                sig(_hsig(sid, 7, HINT, f"The {txt} rises with dose ({v[0][1]:.3g} {unit} at {v[0][0]:g} mg/kg to {v[-1][1]:.3g} {unit} at {v[-1][0]:g} mg/kg, as printed). " + _dose_param_condition(pss),
                          f"{txt} {v[0][1]:.3g} → {v[-1][1]:.3g} {unit} from {v[0][0]:g} to {v[-1][0]:g} mg/kg", expl, [ps["card"]["dataset_id"] for ps in pss]))
    if (any(s["q"] == 7 and s["strength"] != SUG for s in F["signals"]) and not levels & {"INDIVIDUAL", "INDIVIDUAL_IDENTITY_UNVERIFIED"}
            and not any(r["id"] in ("T3", "T3p") for r in F["rules"])):
        chk({"id": "group_means", "q": 7, "text": "No test confirms the dose difference: it rests on group means or printed values, so a "
             "difference of this size can also lie within between-animal variability or reading error. Check the SD and n behind each "
             "mean, or single-animal values, before reading it as dose dependence."})
    if "dose" not in F["assessable"]:
        for d in ds:
            context = d["card"].get("modeling_evidence", {})
            if context.get("reported_oral_doses"):
                F["notes"].append(context["comparator"]["text"] + " Source-reported parameters only.")
        for lv in HYP_AXES["dose"][1][1:]:
            F["untestable"][f"dose.{lv[0]}"] = "no mechanism-resolving multi-dose contrast in the retained curves (Q7)"


def _hf_conditions(F, chk, cond_res, ids, sig):
    """Question 8: condition contrasts (a separate factor). Part of _hfindings (split 2026-11-26 without change)."""
    crs = next((r for r in cond_res if {r["a"], r["b"]} <= ids), None)
    if crs and crs.get("intervals"):
        attr = ", ".join(_ATTR.get(x, x.replace("_", " ")) for x in crs["differing_attributes"]) or "condition"
        cs = [x["c"] for x in crs["intervals"]]
        F["cond"] = {"a": crs["a"], "b": crs["b"], "attr": attr, "confounded": crs["confounded"], "t5": crs["t5_label"]}
        if crs["c_lower"] > crs["c_upper"]:
            sig(_hsig("condition_changes_shape", 8, SUG, f"{crs['a']} against {crs['b']} (differing: {attr}): no single factor fits all matched times "
                      f"within the assumed tolerance (c {min(cs):.2f}–{max(cs):.2f}).", f"scale varies at the assumed tolerance (c {min(cs):.2f}–{max(cs):.2f})",
                      [["condition.rate_shape"]], [crs["a"], crs["b"]], factor="condition"))
        elif crs["c_upper"] < 1 or crs["c_lower"] > 1:
            sig(_hsig("condition_scales", 8, SUG, f"{crs['a']} against {crs['b']} (differing: {attr}): one factor between {crs['c_lower']:.2f} and "
                      f"{crs['c_upper']:.2f} fits all matched times.", f"one factor {crs['c_lower']:.2f}–{crs['c_upper']:.2f} fits {crs['a']} against {crs['b']}",
                      [["condition.extent_only"], ["condition.disposition_scaling"]], [crs["a"], crs["b"]], factor="condition"))
        if crs["confounded"]:
            chk({"id": "confounded", "q": 8, "text": f"{crs['a']} and {crs['b']} differ in more than one attribute ({attr}): the condition effect is confounded."})


def _hf_level(F, central, ds, levels):
    """Question 9: the level a model can work at. Part of _hfindings (split 2026-11-26 without change)."""
    if "INDIVIDUAL" in levels:
        F["model"] = "Population model on serial single-animal curves; between-animal variability can be estimated."
    elif "INDIVIDUAL_IDENTITY_UNVERIFIED" in levels:
        F["model"] = "Source-labelled values: fit them as animals only once cross-time identity is confirmed; otherwise a naive pooled fit."
    elif any(_destructive(d["card"]) for d in central):
        F["model"] = "Fit the published means from successive terminal cohorts. Individual trajectories and between-animal PK variability are unavailable."
    elif central:
        F["model"] = "Fit to group means (naive averaged data); no between-animal variability, and averaging can change the shape."
    elif ds:
        F["model"] = "No curve passes the test gates; the hypothesis can be fitted only once single-dose plasma curves exist."
    else:
        F["model"] = "Reported parameters only; no curve can be fitted, so the hypothesis is carried forward as an expectation."
    if not levels & {"INDIVIDUAL", "INDIVIDUAL_IDENTITY_UNVERIFIED"}:
        F["untestable"].setdefault("onset.variable_lag", "needs serial curves of single animals (Q2)")
    F["level"] = _level_text([d["card"] for d in central]) if central else ("Reported parameters." if not ds else _level_text([d["card"] for d in ds]))


def _hf_t1(F, mets, sig):
    """Question 3: the T1 early-window check. Part of _hfindings (split 2026-11-26 without change)."""
    t1x = [x for x in mets if x[3]["mt1"] > 0 and "DRUG_FREE_BASELINE_UNRESOLVED" not in x[3]["t1_flags"]]
    if t1x:
        c_, d_, s_, m_ = max(t1x, key=lambda x: x[3]["mt1"])
        wi, wj = m_["mt1_witness"]
        sig(_hsig("t1_rise", 3, HINT, f"C/t rises in {_names([x[0] for x in t1x])}; the largest margin is "
                  f"between {wi:.3g} h and {wj:.3g} h under the assumed ±5 % tolerance.", f"C/t rise under the assumed tolerance ({c_})",
                  [["onset.fixed_lag"], ["onset.transit"], ["onset.variable_lag"], ["shape.zero_then_first"], ["shape.weibull_sigmoid"],
                   ["shape.inverse_gaussian"], ["second.two_inputs"], ["second.recirculation"]], [x[1]["card"]["dataset_id"] for x in t1x]))
        # A5: the sensitivity contradiction is recorded only for a rise that survives removing any one sample, on a curve of
        # one animal or a group mean of a fixed cohort (review guide Q4 group_curve); otherwise the rise is described only
        t1c = [x for x in t1x if not ({"SINGLE_POINT_SUPPORT", "LOO_NOT_ASSESSABLE"} & set(x[3]["t1_flags"]))
               and (x[1]["card"]["record_level"] != "GROUP_MEAN" or _fixed_cohort(x[1]["card"]))]
        if t1c:
            c_, d_, s_, m_ = max(t1c, key=lambda x: x[3]["mt1"])
            wi, wj = m_["mt1_witness"]
            text = (f"C/t rises between {wi:.3g} h and {wj:.3g} h in {c_} under the assumed ±{TOL:.0%} "
                    "tolerance (SENSITIVITY_ONLY); applies to this input started at dosing, without a lag.")
            for comp in T1_COVERED + ("reference",):   # review guide Q4: these inputs, started at dosing, predict that C/t never rises
                F.setdefault("against", {})[comp] = text
                F.setdefault("against_source", {})[comp] = "t1_rise"
        else:
            F["notes"].append("A C/t rise is seen but rests on one sample, could not be rechecked, or comes from a group mean of "
                              "unverified cohort composition, so no input option is marked as contradicted (Q4).")


def _hf_second_rise(chk, mets, sig):
    """Question 4: second rise (T2). Part of _hfindings (split 2026-11-26 without change)."""
    t2i = [(x, x[2]["t2"]) for x in mets if x[2].get("t2") and x[1]["card"]["record_level"] != "GROUP_MEAN"]
    if t2i:
        # A4: only a T2 that applies (verified serial animal, drug-free baseline) can raise the stronger signal
        applies = [(x, t) for x, t in t2i if t.get("t2_label") != "DESCRIPTIVE_ONLY"]
        shown = [x for x, t in applies if t.get("robust")]
        weak = [x for x, t in applies if t.get("valley") and not t.get("robust")]
        desc = [x for x, t in t2i if t.get("valley") and t.get("t2_label") == "DESCRIPTIVE_ONLY"]
        lab = any("CONDITIONAL_ON_LABEL_IDENTITY" in t["t2_flags"] for _, t in t2i)
        if shown:
            sig(_hsig("rerise_within_animal", 4, SUG, f"A dip and a second rise beyond ±5 % within {len(shown)} of {len(t2i)} single-animal curves "
                      f"({_names([x[0] for x in shown])})" + ("; each source label is taken as one animal" if lab else "") + ".",
                      f"second rise within {len(shown)} single-animal curve{'s' if len(shown) > 1 else ''}",
                      [["second.two_inputs"], ["second.recirculation"]], [x[1]["card"]["dataset_id"] for x in shown]))
        elif weak:
            sig(_hsig("rerise_single_point", 4, HINT, f"A dip and a second rise in {_names([x[0] for x in weak])} that rests on one sample "
                      "or could not be rechecked with a sample removed.",
                      "a second rise resting on one sample", [["second.two_inputs"], ["second.recirculation"]],
                      [x[1]["card"]["dataset_id"] for x in weak]))
        elif desc:
            sig(_hsig("rerise_descriptive", 4, HINT, f"A dip and a second rise in {_names([x[0] for x in desc])}; these records are not "
                      "verified serial curves of one animal with a drug-free baseline, so the rise is described only.",
                      "a second rise in records that are described only", [["second.two_inputs"], ["second.recirculation"]],
                      [x[1]["card"]["dataset_id"] for x in desc]))
    else:
        for c_, d_, s_, m_ in mets:
            r = t2_curve(s_["points"])
            if r["t2_margin"] is not None:
                a, bb, cc = r["valley_idx"]
                sig(_hsig("rerise_group_mean", 4, HINT, f"The group mean of {c_} dips at {r['_t'][bb]:.3g} h between {r['_t'][a]:.3g} h and "
                          f"{r['_t'][cc]:.3g} h and rises again (margin {r['t2_margin']:.3g} {d_['card']['unit']}); group means only.",
                          f"the group mean of {c_} dips at {r['_t'][bb]:.3g} h and rises again",
                          [["second.two_inputs"], ["second.recirculation"], ["onset.variable_lag"]], [d_["card"]["dataset_id"]]))
                chk({"id": "averaging", "q": 4, "text": "Averaging animals whose peaks or lags differ can make a dip in a group mean: check "
                     "single-animal curves before reading it as a second input."})
                break


def _hf_tail(F, central, chk, ds, ev_iv_res, ids, ivs, mets, rule, sig):
    """Question 5: the tail and route pairing. Part of _hfindings (split 2026-11-26 without change)."""
    evr = next((r for r in ev_iv_res if r["ev"] in ids), None)
    animal_pairs = [r for d in central for r in d.get("iv_pairs") or []]
    if not evr and animal_pairs:
        # A2: verified within-animal EV/IV pairs (subject id, washout, period order and occasion verified) reach the ranking
        rows5 = []
        for r in animal_pairs:
            e_th = (r["_em"].get("terminal_selected") or {}).get("thalf"); i_th = (r["_im"].get("terminal_selected") or {}).get("thalf")
            if e_th and i_th:
                rows5.append((r, e_th, i_th, e_th / i_th, r.get("tail") or {}))
        # R9 (2026-11-24): the board, the ranking and the hand-off read the same flip-flop reading of each pair
        slow = [x for x in rows5 if x[4].get("flip_flop_reading") == "ABSORPTION_INFLUENCED_CANDIDATE"]
        open_ = [x for x in rows5 if x[4].get("flip_flop_reading") in FF_NOT_AGAINST or not x[4].get("flip_flop_reading")]
        if slow:
            firm = [x for x in slow if _matched_slow_tail(x[0], x[4])]
            # a reproducible individual feature: the matched slower tail holds in every compared animal, and in at least two
            strong = len(rows5) >= 2 and len(firm) == len(rows5)
            elim = [["other.saturable_elimination"]] if any(x[0].get("dose_ev") != x[0].get("dose_iv") for x in slow) else []
            sig(_hsig("tail_slower_than_iv_within_animal", 5, SUG if strong else HINT,
                      f"Within the same animal, the extravascular decline is slower than after IV in {len(slow)} of {len(rows5)} animals "
                      f"(EV/IV apparent t½ ratio {_rng([x[3] for x in slow])}; matched-window corroboration in {len(firm)}).",
                      f"within-animal EV t½ longer than IV in {len(slow)} of {len(rows5)} animals",
                      [["tail.absorption"], ["other.multicompartment"]] + elim,
                      sorted({x[0]["ev_dataset"] for x in slow} | {x[0]["iv"] for x in slow})))
            if not strong:
                chk({"id": "within_animal_tail", "q": 5, "text": "The slower within-animal decline is not corroborated over matched windows in "
                     "every animal (or only one animal is paired); compare both slopes over a common late window before reading it as slow absorption."})
        elif rows5 and open_:
            F["flipflop_unresolved"] = True
            F["notes"].append("Within the same animal the flip-flop reading is " + "; ".join(sorted({(x[4].get("reading_text") or "not compared") for x in open_}))
                              + "; this is not evidence for or against an absorption-limited tail (Q5).")
        elif rows5:
            F["notes"].append(f"Within the same animal, the extravascular decline is not markedly slower than after IV "
                              f"(EV/IV apparent t½ ratio {_rng([x[3] for x in rows5])}), so a slow-absorption tail is not pointed to (Q5).")
            if all((x[4].get("flip_flop_reading") in ("COMMON_TERMINAL_COMPATIBLE", "EV_STEEPER_REVIEW")) for x in rows5):
                F.setdefault("against", {})["tail.absorption"] = (f"within-animal EV/IV apparent t½ ratio {_rng([x[3] for x in rows5])} "
                                                                  f"in {len(rows5)} animal{'s' if len(rows5) != 1 else ''}")
                F.setdefault("against_source", {})["tail.absorption"] = "within_animal_tail"
        else:
            F["flipflop_unresolved"] = True
            F["notes"].append("Within-animal EV/IV pairs exist, but no pair has a qualified terminal window on both curves (Q5).")
    elif evr:
        em = next(s["metrics"] for d in central for s in d["series"] if d["card"]["dataset_id"] == evr["ev"])
        im = next((i["metrics"] for i in ivs if i["card"]["dataset_id"] == evr["iv"]), {})
        e_th = (em.get("terminal_selected") or {}).get("thalf")
        i_th = (im.get("terminal_selected") or {}).get("thalf")
        tc = evr.get("tail") or (tail_compare(em, im) if e_th and i_th else None) or {}
        if tc.get("test"):
            chk({"id": "tail_nominal", "q": 5, "text": "The slope p uses selected time-point residuals, not animal-level variability; window selection and time covariance are unresolved. Check common late windows and individual curves before identifying flip-flop."})
            chk({"id": "common_tail", "q": 5, "text": _common_tail_text(tc)})
            if 0.02 <= tc["test"]["p"] <= 0.1:
                chk({"id": "tail_threshold", "q": 5, "text": "The nominal slope p is near 0.05; treat the tail classification as threshold-sensitive and inspect the leave-one-sample-out results."})
        reading = tc.get("flip_flop_reading")
        if e_th and i_th and reading in FF_NOT_AGAINST:
            # R9: UNRESOLVED and NOT_ASSESSABLE neither point to nor argue against an absorption-limited tail
            F["flipflop_unresolved"] = True
            # round 3 addendum: the same-study IV curve exists; what is missing is a readable comparison
            F["ff_block"] = str(tc.get("reading_text") or reading).strip()
            F["notes"].append(f"Flip-flop reading for {evr['ev']} against {evr['iv']}: {tc.get('reading_text') or reading}; "
                              "not evidence for or against an absorption-limited tail (Q5).")
            if reading == "NOT_ASSESSABLE":
                _ff_indirect_hint(sig, [x for x in ff_indirect_comparators(mets) if x["ev_dataset"] == evr["ev"]])
        elif e_th and i_th and reading == "ABSORPTION_INFLUENCED_CANDIDATE":
            ratio = e_th / i_th
            firm = _matched_slow_tail(evr, tc)
            elim = [["other.saturable_elimination"]] if evr.get("dose_ev") != evr.get("dose_iv") else []
            sig(_hsig("tail_slower_than_iv", 5, SUG if (ratio >= FLIP_RATIO and firm) else HINT, f"The extravascular decline is slower than after IV "
                      f"in the same study: apparent t½ {e_th:.3g} h ({evr['ev']}) against {i_th:.3g} h ({evr['iv']}), {ratio:.2g}× ({_tail_test_text(tc)}).",
                      f"EV t½ {e_th:.3g} h against IV {i_th:.3g} h", [["tail.absorption"], ["other.multicompartment"]] + elim,
                      [evr["ev"], evr["iv"]]))
            e_w, i_w = tc["ev_window_h"], tc["iv_window_h"]
            if any(abs(x - y) > TOL * max(x, y) for x, y in zip(e_w, i_w)):
                chk({"id": "window", "q": 5, "text": f"The two half-lives come from different sampling windows ({evr['ev']} from {e_w[0]:.3g} h to "
                     f"{e_w[1]:.3g} h, {evr['iv']} from {i_w[0]:.3g} h to {i_w[1]:.3g} h): a slower extravascular decline can also mean that one "
                     "curve had not reached its terminal phase. Compare both slopes over a common late window before reading it as slow absorption."})
            # cross-check: one first-order input whose ka equals the EV terminal slope, with the IV k
            ka, k = math.log(2) / e_th, math.log(2) / i_th
            t, c = em["_t"], em["_c"]
            i_pk = int(np.argmax(c))
            t_up = t[i_pk + 1] if i_pk + 1 < len(t) else None
            t_pred = math.log(ka / k) / (ka - k)
            if firm and t_up and t_pred > t_up * (1 + TOL):
                # this cross-check assumes the slower tail is real: it is no firmer than the slope test behind it
                sig(_hsig("early_peak_slow_tail", 5, SUG if firm else HINT, f"{evr['ev']} peaks by {t_up:.3g} h (observed Tmax {em['tmax']:.3g} h), but one first-order "
                          f"input with ka equal to its terminal slope ({ka:.3g}/h) and the IV k ({k:.3g}/h) would peak at {t_pred:.3g} h.",
                          f"an early peak by {t_up:.3g} h with a slow tail that one first-order input would put at {t_pred:.3g} h",
                          [["shape.weibull_front", "tail.absorption"], ["shape.inverse_gaussian", "tail.absorption"],
                           ["shape.parallel_first", "tail.absorption"], ["shape.parallel_zero_first", "tail.absorption"],
                           ["other.multicompartment"]] + elim, [evr["ev"], evr["iv"]]))
                if firm:
                    pair = f"{evr['ev']} | {evr['iv']}"
                    rule(_hrule("TMAX", 5, f"One first-order input cannot both peak by {t_up:.3g} h and give the slow tail of {evr['ev']} with the IV "
                                f"k of {evr['iv']} (it would peak at {t_pred:.3g} h; shared one-compartment disposition).",
                                {"shape": ["first_order", "zero_then_first"], "tail": ["absorption"], "second": ["none"], "other": ["none"]},
                                units={"unit_kind": "same-study EV/IV pair chosen by dose match before the results", "required": [pair],
                                       "assessable": [pair], "formal": [pair], "directions": ["peak earlier than the slow tail allows"]}))
        elif e_th and i_th:
            grade = tc.get("terminal_difference_grade") or hl_grade(e_th / i_th)
            F["notes"].append(f"The extravascular decline is {HL_WORDS[grade]} the decline after IV ({e_th:.3g} h against {i_th:.3g} h, "
                              f"ratio {_ratio_txt(e_th / i_th)}), so a slow-absorption tail is not pointed to (Q5).")
            if tc.get("flip_flop_reading") in ("COMMON_TERMINAL_COMPATIBLE", "EV_STEEPER_REVIEW"):
                F.setdefault("against", {})["tail.absorption"] = (f"EV/IV apparent t½ ratio {_ratio_txt(e_th / i_th)} ({grade.lower().replace('_', ' ')}) "
                                                                  "in the same study")
                F.setdefault("against_source", {})["tail.absorption"] = "tail_vs_iv"
    else:
        F["flipflop_unresolved"] = True
        F["unpaired_iv"] = bool(_same_study_ivs(ivs, ds))
        F["notes"].append((_iv_unpaired_text(ivs, ds) + " " if F["unpaired_iv"] else "Without a same-study IV curve, ") + "the decline can be set by disposition or by slow absorption: ka and k can swap (Q5).")
        _ff_indirect_hint(sig, ff_indirect_comparators(mets))
    flat = [x for x in mets if (x[3].get("split") or {}).get("class") == "DECLINE_FLATTENS"]
    steep = [x for x in mets if (x[3].get("split") or {}).get("class") == "DECLINE_STEEPENS"]
    if flat:
        sig(_hsig("decline_flattens", 5, HINT, f"The late decline flattens in {_names([x[0] for x in flat])} (split-half slope ratio "
                  f"{_rng([x[3]['split']['ratio'] for x in flat])}).", f"the late decline flattens in {_names([x[0] for x in flat], 3)}",
                  [["shape.weibull_front"], ["shape.inverse_gaussian"], ["shape.parallel_first"], ["shape.parallel_zero_first"],
                   ["second.two_inputs"], ["second.recirculation"], ["other.multicompartment"]], [x[1]["card"]["dataset_id"] for x in flat]))
    if steep:
        chk({"id": "steepens", "q": 5, "text": f"The late decline steepens in {_names([x[0] for x in steep])}: check BLQ handling near the LLOQ "
             "and saturable elimination before reading it as absorption."})


def _hfindings(b, ds, pss, dose_series_res, ev_iv_res, cond_res, ivs):
    """What the nine questions found for one study, as signals that point to cases, rules that set combinations aside,
    cases these data cannot test, and checks that come before any model."""
    # the same data in any order give the same findings: every list is put in a fixed order first
    ds = sorted(ds, key=lambda d: d["card"]["dataset_id"])
    pss = sorted(pss, key=lambda p: p["card"]["dataset_id"])
    ivs = sorted(ivs, key=lambda i: i["card"]["dataset_id"])
    dose_series_res = sorted(dose_series_res, key=lambda r: tuple(r.get("dataset_ids") or ()))
    cond_res = sorted(cond_res, key=lambda r: (str(r.get("a")), str(r.get("b"))))
    ev_iv_res = sorted(ev_iv_res, key=_hpair_key)
    ids = {d["card"]["dataset_id"] for d in ds}
    central = [d for d in ds if d["card"]["tests_allowed"]]
    mets = [(_cid(d, s), d, s, s["metrics"]) for d in central for s in d["series"] if "tmax" in s["metrics"]]
    params = [p for ps in pss for p in ps["params"]]
    levels = {d["card"]["record_level"] for d in central}
    F = {"signals": [], "rules": [], "untestable": {}, "bounds": {}, "checks": [], "notes": [], "assessable": [], "cond": None,
         "flipflop_unresolved": False, "shape_identifiable": True, "nocurve": ""}
    sig, rule, chk = F["signals"].append, F["rules"].append, F["checks"].append
    if mets:
        F["assessable"] += ["onset", "shape", "second", "tail"]
        firsts = [m["first_t"] for *_, m in mets]
        # Q1 onset
        early = [x for x in mets if x[3]["onset_status"] == "NOT_ASSESSABLE"]
        if early:
            below = [x for x in early if any(p["status"] == "BLQ" and 0 < p["t"] < x[3]["first_t"]
                                            for p in x[3].get("censored_samples", []))]
            if below:
                sig(_hsig("early_blq", 1, HINT, f"Samples before the first quantified one are below the quantification limit in {_names([x[0] for x in below])}"
                          f" (first quantified at {_rng([x[3]['first_t'] for x in below])} h).", "BLQ before the first quantified sample",
                          [["onset.fixed_lag"], ["onset.transit"], ["shape.zero_then_first"], ["shape.weibull_sigmoid"]],
                          [x[1]["card"]["dataset_id"] for x in below]))
            chk({"id": "early_assay", "q": 1, "text": "Check early assay qualifiers and documented limits before interpreting a delay."})
        else:
            F["bounds"]["tlag_max_h"] = max(firsts)
            F["bounds"]["tlag_by_curve_h"] = {name: m["first_t"] for name, _, _, m in mets}
            F["notes"].append(f"Any lag is shorter than {max(firsts):.3g} h across these curves; each curve is bounded by its own first sample ({_rng(firsts)} h; Q1).")
        # Q2 input speed
        if all("KA_NOT_IDENTIFIABLE" in m["caveats"] for *_, m in mets):
            F["shape_identifiable"] = False
            F["notes"].append("Fewer than 2 samples before Tmax in every curve, so ka and the input shape are not identifiable from the rise (Q2).")
        # Q3 T1
        _hf_t1(F, mets, sig)
        # Q4 second rise
        _hf_second_rise(chk, mets, sig)
        # Q5 tail
        _hf_tail(F, central, chk, ds, ev_iv_res, ids, ivs, mets, rule, sig)
        # Q6 extent
        for ratio_result in (x for x in ev_iv_res if x["ev"] in ids and x.get("window_auc_ratio") is not None):
            F["notes"].append(f"{ratio_result['ev']} / {ratio_result['iv']}: the dose-normalized EV/IV AUC ratio over {_ratio_window_text(ratio_result)} is {ratio_result['window_auc_ratio']:.3g}; "
                              "this is neither absolute F nor a bound. Absolute F was not recomputed; any future joint fit requires an appropriate disposition model and compatible doses (Q6). "
                              + _source_f_text(ratio_result))
    else:
        evr = None
        why = F["nocurve"] = "no curve passes the test gates" if ds else "reported parameters only"
        for a in ("onset", "shape", "second", "tail"):
            for lv in HYP_AXES[a][1]:
                if lv[0] != HYP_DEFAULT[a]:
                    F["untestable"][f"{a}.{lv[0]}"] = f"{why} (Q1–Q5)"
    for dataset in ds:
        if dataset["card"].get("source_reported_absolute_f"):
            F["notes"].append(_source_f_text(dataset["card"]) + " Source-level parameter; no cross-route individual pairing is inferred.")
    f_ = next(((ps["card"], ps["analysis"]["f"]) for ps in pss if (ps.get("analysis") or {}).get("f")), None)
    if f_ and f_[1]["value"] > 1.0:
        chk({"id": "f_above_one", "q": 6, "text": f"Reported F = {f_[1]['value']:.2f} ({f_[0]['dataset_id']}) is above 1: check the dose basis and "
             "linearity before using it."})
    # Q7 dose
    _hf_dose(F, chk, dose_series_res, ds, ids, levels, pss, rule, sig)
    # Q8 conditions (a separate factor: no rule couples it to the other axes)
    _hf_conditions(F, chk, cond_res, ids, sig)
    # Q9 the level a model can work at
    _hf_level(F, central, ds, levels)
    for group in ("signals", "rules", "checks"):   # found on the r4.3 rows; named by the review-guide question
        for x in F[group]:
            if "q" in x:
                x["q"] = GUIDE_Q.get(x["q"], x["q"])
    F.setdefault("against", {})
    return F


def _heval(c, F, cond=None):
    rules = [r["id"] for r in F["rules"] if r["factor"] == "main" and all(c.get(a) in lv for a, lv in r["pattern"].items())]
    unt = [f"{a}.{c[a]}" for a in HYP_ORDER if f"{a}.{c[a]}" in F["untestable"]]
    expl = [s["id"] for s in F["signals"] if s["factor"] == "main" and _hexplains(c, s)]
    sug = [s["id"] for s in F["signals"] if s["factor"] == "main" and s["strength"] == SUG]
    reading = "DISFAVORED" if rules else "ACCOUNTS_FOR_ALL" if set(sug) <= set(expl) else "PARTIAL" if set(sug) & set(expl) else "NONE"
    return {"reading": reading, "rules": rules, "untestable": unt, "explains": expl}


# Ranked candidates for Modeling (review guide, rule decision R5): the reference fit first, then candidates with direct support, with
# only indirect support, untested, and with contrary evidence, in that order. A sensitivity-only contradiction keeps a candidate in its
# group; it never leaves the list.
RANK_GROUPS = ("REFERENCE", "SUPPORTED", "INDIRECT_SUPPORT", "UNTESTED", "CONTRARY_EVIDENCE")
T1_COVERED = ("shape.zero_order", "shape.parallel_first", "shape.parallel_zero_first", "shape.weibull_front")


def _hranked(F, ev, space):
    """Every option of every axis once, in the groups of rule decision R5 (2026-11-24). A formal rule attaches to the complete
    combinations it tested: an option is CONTRARY_EVIDENCE when every combination holding it is set aside, and each option shows the
    contradicted combinations it depends on, with n, m, k and direction. A rule at BOARD level (every required unit formally excluded
    in one direction) is recorded separately. Inside a group, options are ordered by independent evidence sources (distinct original
    curves), then by added parameters. A sensitivity-only contradiction moves an option only below another option of the same group
    that the same observation supports; otherwise it is marked and the order is kept."""
    sigs = [s for s in F["signals"] if s["factor"] == "main"]
    sugs = [s for s in sigs if s["strength"] == SUG]
    hints = [s for s in sigs if s["strength"] != SUG]
    data_of = {s["id"]: set(s.get("datasets") or []) or {s["id"]} for s in sigs}
    against = F.get("against") or {}
    against_src = F.get("against_source") or {}
    rules = {r["id"]: r for r in F["rules"] if r["factor"] == "main"}

    def combos(holds_rules):
        out = []
        for c, e in holds_rules:
            for rid in e["rules"]:
                r = rules.get(rid) or {}
                u = r.get("units") or {}
                out.append({"combination": _hcode(c), "rule": rid, "level": r.get("level", "FORMAL_UNIT"),
                            "required_n": u.get("required_n"), "assessable_m": u.get("assessable_m"), "formal_k": u.get("formal_k"),
                            "directions": u.get("directions"), "correction": u.get("correction")})
        return out
    m0 = _heval(dict(HYP_DEFAULT), F)
    ref_c = combos([(dict(HYP_DEFAULT), m0)]) if m0["rules"] else []
    ref_board = bool(ref_c) and all(x["level"] == "BOARD" for x in ref_c)
    rows = [{"candidate": "reference", "label": "immediate first-order, single-input, dose-linear, disposition-controlled combination",
             "group": "REFERENCE", "supported_by": [], "indirect": [], "sensitivity_contradiction": against.get("reference"),
             "sensitivity_source": against_src.get("reference"), "demoted": False, "moved_below": None,
             "added_parameters": 0, "not_testable": None, "independent_sources": 0,
             "formally_contradicted_by": m0["rules"], "contradicted_combinations": ref_c, "board_excluded": ref_board,
             "note": ("Excluded at board level within the declared conditions and windows; shown only as the fit comparator." if ref_board
                      else "Formal contrary evidence in some required units; kept as the comparison benchmark." if m0["rules"]
                      else "The reference fit.")}]
    cands = []
    for a in HYP_ORDER:
        for lv in HYP_AXES[a][1]:
            if lv[0] == HYP_DEFAULT[a]:
                continue
            comp = f"{a}.{lv[0]}"
            firm = [s["id"] for s in sugs if any(comp in alt for alt in s["explained_by"])]
            weak = [s["id"] for s in hints if any(comp in alt for alt in s["explained_by"])]
            group = "SUPPORTED" if firm else "INDIRECT_SUPPORT" if weak else "UNTESTED"
            holds = [(c, e) for c, e in zip(space, ev) if c[a] == lv[0]]
            hit = [(c, e) for c, e in holds if e["rules"]]
            cc = combos(hit)
            all_set_aside = bool(holds) and len(hit) == len(holds)
            if all_set_aside:
                group = "CONTRARY_EVIDENCE"
            src_firm = set().union(*(data_of[x] for x in firm)) if firm else set()
            src_all = src_firm.union(*(data_of[x] for x in weak)) if weak else src_firm
            cands.append({"candidate": comp, "label": lv[1], "group": group, "supported_by": firm, "indirect": weak,
                          "sensitivity_contradiction": against.get(comp), "sensitivity_source": against_src.get(comp),
                          "demoted": False, "moved_below": None, "added_parameters": lv[2], "not_testable": F["untestable"].get(comp),
                          "independent_sources": len(src_all), "direct_sources": len(src_firm),
                          "formally_contradicted_by": sorted({x["rule"] for x in cc}) if all_set_aside else [],
                          "contradicted_combinations": cc,
                          "board_excluded": all_set_aside and all(x["level"] == "BOARD" for x in cc),
                          "untested_state": (None if group != "UNTESTED" else "not assessed" if comp in F["untestable"]
                                             else "assessed but undecided" if against.get(comp) else "no evidence usable for ranking"),
                          "note": ""})
    order = {g: i for i, g in enumerate(RANK_GROUPS)}
    cands.sort(key=lambda r: (order[r["group"]], -r["direct_sources"], -r["independent_sources"], r["added_parameters"],
                              HYP_TRY.index(r["candidate"])))
    # R5: a sensitivity-only contradiction moves an option below the last option of its group that the same observation supports
    base = {r["candidate"]: i for i, r in enumerate(cands)}
    target = {}
    for i, r in enumerate(cands):
        sid = r["sensitivity_source"]
        if not (r["sensitivity_contradiction"] and sid) or r["group"] == "CONTRARY_EVIDENCE":
            continue
        hits = [k for k in range(i + 1, len(cands)) if cands[k]["group"] == r["group"] and sid in cands[k]["supported_by"] + cands[k]["indirect"]]
        if hits:
            target[r["candidate"]] = cands[hits[-1]]["candidate"]

    def key(name):
        return key(target[name]) + (1, base[name]) if name in target else (base[name],)
    cands.sort(key=lambda r: key(r["candidate"]))
    for r in cands:
        if r["candidate"] in target:
            r["demoted"], r["moved_below"] = True, target[r["candidate"]]
    rows += cands
    for i, r in enumerate(rows):
        r["position"] = i + 1
        # options the data cannot tell apart share a tie key; added parameters then decide which to fit first
        r["tie"] = f'{r["group"]}:{",".join(sorted(r["supported_by"] + r["indirect"]))}'
    excluded = [{"rule": r["id"], "question": r["q"], "text": r["text"], "pattern": r["pattern"], "level": r.get("level", "FORMAL_UNIT"),
                 "units": r.get("units")} for r in F["rules"] if r["factor"] == "main"]
    return {"groups": list(RANK_GROUPS), "candidates": rows, "formally_contradicted_combinations": excluded,
            "board_exclusions": [x for x in excluded if x["level"] == "BOARD"],
            "sensitivity_rule": RANK_SENSITIVITY_RULE}


RANK_SENSITIVITY_RULE = ("A contradiction supported only at sensitivity level keeps the option in its group and is marked; it moves the option "
                         "below another option of the same group only when the same observation supports that option (rule decision R5).")


# on equal cost, the order in which a modeller would usually try the parts
HYP_TRY = ["onset.fixed_lag", "tail.absorption", "dose.saturable_rate", "dose.extent_down", "dose.extent_up", "shape.zero_order",
           "shape.weibull_front", "shape.weibull_sigmoid", "shape.zero_then_first", "onset.transit", "shape.inverse_gaussian", "second.two_inputs",
           "shape.parallel_first", "shape.parallel_zero_first", "onset.variable_lag", "second.recirculation", "other.multicompartment",
           "other.saturable_elimination", "other.binding"]


def _hpref(c):
    return sorted(HYP_TRY.index(f"{a}.{c[a]}") for a in HYP_ORDER if c[a] != HYP_DEFAULT[a])


def _hnondefault(c):
    return sum(c[a] != HYP_DEFAULT[a] for a in HYP_ORDER)


def _hselect(F, space, ev):
    """Select the simplest testable combination covering qualifying findings. Retain hints for review."""
    sug = [s["id"] for s in F["signals"] if s["factor"] == "main" and s["strength"] == SUG]
    hint = [s for s in F["signals"] if s["factor"] == "main" and s["strength"] == HINT]
    usable = [(c, e) for c, e in zip(space, ev) if e["reading"] != "DISFAVORED" and not e["untestable"]]
    ok = [(c, e) for c, e in usable if e["reading"] == "ACCOUNTS_FOR_ALL"]
    if not ok and usable:  # no combination accounts for every pattern: account for as many as possible
        n = max(len(set(e["explains"]) & set(sug)) for _, e in usable)
        ok = [(c, e) for c, e in usable if len(set(e["explains"]) & set(sug)) == n]
    if not ok:
        return dict(HYP_DEFAULT), dict(HYP_DEFAULT), [], [s["id"] for s in hint]
    # Fragile patterns retain their candidate explanations in the audit. They do not
    # add components or break ties between equally parsimonious supported models.
    primary = min(ok, key=lambda ce: (_hcost(ce[0]), _hnondefault(ce[0]), _hpref(ce[0])))[0]
    return primary, dict(primary), [], [s["id"] for s in hint if not _hexplains(primary, s)]


def _hcond_rows(F):
    if not F["cond"]:
        return []
    rows = []
    for lv in COND_LEVELS:
        rules = [r["id"] for r in F["rules"] if r["factor"] == "condition" and lv[0] in r["pattern"]["condition"]]
        expl = [s["id"] for s in F["signals"] if s["factor"] == "condition" and _hexplains({}, s, lv[0])]
        rows.append({"level": lv[0], "label": lv[1].format(a=F["cond"]["attr"]), "params": lv[2], "rules": rules, "explains": expl})
    return rows


def _hcond_select(F, rows):
    if not rows:
        return None
    sug = {s["id"] for s in F["signals"] if s["factor"] == "condition" and s["strength"] == SUG}
    ok = [r for r in rows if not r["rules"] and sug <= set(r["explains"])] or [r for r in rows if not r["rules"]] or rows
    return min(ok, key=lambda r: (r["params"], [x[0] for x in COND_LEVELS].index(r["level"])))["level"]


def _hphrase(comp, F, ladder=False):
    ax, lv = comp.split(".")
    x = _hlev(ax, lv)
    t = x[4] if ladder else x[1]
    return t.format(a=(F["cond"] or {}).get("attr", "condition")) if ax == "condition" else t


_hjoin = COMMON._hjoin


def _hroles(F, c, cond):
    roles = {}
    for s in F["signals"]:
        alt = _hexplains(c, s, cond)
        if alt:
            for comp in alt:
                roles.setdefault(comp, []).append(s)
    comps = [f"{a}.{c[a]}" for a in HYP_ORDER if c[a] != HYP_DEFAULT[a]] + ([f"condition.{cond}"] if cond and cond != "same" else [])
    prim = [x for x in comps if any(s["strength"] == SUG for s in roles.get(x, []))]
    sec = [x for x in comps if x not in prim and roles.get(x)]
    free = [x for x in comps if not roles.get(x)]
    return comps, prim, sec, free, roles


def _hextra(comps, F):
    n = sum(_hlev(*x.split("."))[2] for x in comps) - sum(_hlev(x.split(".")[0], (HYP_DEFAULT.get(x.split(".")[0]) or "same"))[2] for x in comps)
    names = [(_hlev(*x.split("."))[3] or "").format(a=(F["cond"] or {}).get("attr", "condition")) for x in comps]
    return n, ", ".join(x for x in names if x)


def _halternatives(F, c, cond, full=False):
    """Other cases that would account for the same finding instead of the chosen one, under the same rules; the best two per finding.
    With full=True every such case is returned: the summary keeps all possibilities, the model ladder keeps the short list."""
    sug_main = {x["id"] for x in F["signals"] if x["strength"] == SUG and x["factor"] == "main"}
    need = set(_heval(c, F)["explains"]) & sug_main
    free_cond = [r["level"] for r in _hcond_rows(F) if not r["rules"]]
    best = {}
    for s in F["signals"]:
        used = _hexplains(c, s, cond)
        if not used:
            continue
        for alt in s["explained_by"]:
            use = [x for x in alt if x not in used]
            inst = [x for x in used if x not in alt]
            if not use:
                continue
            if s["factor"] == "condition":
                lv = alt[0].split(".")[1]
                if lv not in free_cond:
                    continue
                row = {"delta": _hlev("condition", lv)[2] - _hlev("condition", cond)[2], "untestable": [], "combination": None}
            else:
                cand = dict(c)
                for x in used:
                    cand[x.split(".")[0]] = HYP_DEFAULT[x.split(".")[0]]
                for x in alt:
                    ax, lv = x.split(".")
                    cand[ax] = lv
                if not _hvalid(cand):
                    continue
                e = _heval(cand, F)
                if e["reading"] == "DISFAVORED" or not need <= set(e["explains"]):
                    continue
                row = {"delta": _hcost(cand) - _hcost(c), "untestable": e["untestable"], "combination": _hcode(cand)}
            key = (s["id"], tuple(use), tuple(inst))
            if key not in best or row["delta"] < best[key]["delta"]:
                best[key] = {"instead_of": inst, "use": use, "signal": s["id"], "q": s["q"], "pointing": s["strength"] == SUG} | row
    per = {}
    # the same swap offered by a firm finding and by a hint is kept under the firm one
    for a in sorted(best.values(), key=lambda a: (not a["pointing"], bool(a["untestable"]), a["delta"])):
        if any(x["use"] == a["use"] and x["instead_of"] == a["instead_of"] for v in per.values() for x in v):
            continue
        per.setdefault(a["signal"], [])
        if full or len(per[a["signal"]]) < 2:
            per[a["signal"]].append(a)
    out = [a for v in per.values() for a in v]
    out.sort(key=lambda a: (not a["pointing"], a["q"], bool(a["untestable"]), a["delta"]))
    return out if full else out[:4]


def _ff_need(F):
    """What the flip-flop reading lacks. A same-study IV curve that is present but gives no readable comparison is not 'missing'."""
    if F.get("unpaired_iv"):
        return "verified cross-route identity, period order and washout"
    if F.get("ff_block"):
        return f"a readable EV/IV comparison window (the same-study IV curve is present; {F['ff_block']})"
    return "a same-study IV curve"


def _hneeds(F, comps, alts):
    need = []
    allc = set(comps) | {x for a in alts for x in a["use"]}
    if F["flipflop_unresolved"] and allc & {"tail.absorption", "other.multicompartment", "other.saturable_elimination", "dose.extent_up", "dose.extent_down"}:
        need.append(_ff_need(F))
    elif F["flipflop_unresolved"] and "tail" in F["assessable"]:
        need.append(_ff_need(F) + ", to tell ka from k")
    if "onset.variable_lag" in F["untestable"] and any(["onset.variable_lag"] in s["explained_by"] for s in F["signals"]):
        need.append("serial curves of single animals")
    if not F["shape_identifiable"]:
        need.append("at least 2 samples before Tmax")
    if any(s["id"] == "early_blq" for s in F["signals"]):
        need.append("the LLOQ")
    if allc & {"dose.extent_up", "dose.extent_down", "other.saturable_elimination"}:
        need.append("IV curves across the dose range")
    if not F["assessable"] or F["model"].startswith(("No curve", "Reported")):
        need.append("concentration–time points after a single first dose")
    elif any(x["id"] == "occasion" for x in F["checks"]):
        need.append("single-dose (first-dose) curves")
    return list(dict.fromkeys(need))[:4]


def _hcompose(b, F, c, cond, origin="selection"):
    """Text, model ladder and alternatives for one combination (chosen here, or set by a reviewer)."""
    comps, prim, sec, free, roles = _hroles(F, c, cond)
    alts = _halternatives(F, c, cond)
    every = _halternatives(F, c, cond, full=True)
    also = {}
    attr = (F["cond"] or {}).get("attr", "condition")
    nocurve = (" Onset, input shape and tail cannot be read here (" + F["nocurve"] + ").") if "onset" not in F["assessable"] else ""
    eq = []
    if not comps:
        if "onset" not in F["assessable"]:
            lead = ("Nothing here points to an absorption case yet: no curve can be read for onset, input shape or tail"
                    + (", and the dose comparison points to no further case." if "dose" in F["assessable"] else ", and dose dependence is not shown."))
            nocurve = ""
        else:
            lead = ("The simplest input accounts for everything the nine questions found: first-order absorption from the dosing time"
                    + (", linear in dose" if "dose" in F["assessable"] else "") + (", with the decline set by disposition" if not F["flipflop_unresolved"] else "")
                    + "." + ((" Without verified cross-route pairing the retained individual IV curves do not resolve whether the decline is set by slow absorption."
                              if F.get("unpaired_iv") else (" The same-study IV comparison gives no reading (" + F["ff_block"] + "), so the decline could equally be set by slow absorption, because ka and k can swap.")
                              if F.get("ff_block") else " Without a same-study IV curve the decline could equally be set by slow absorption, because ka and k can swap.")
                             if F["flipflop_unresolved"] and "tail" in F["assessable"] else ""))
    else:
        lead = ("Suspected: " + _hjoin(_hphrase(x, F) for x in prim) + "." if prim else "")
        if sec:
            lead += (" Less firm: " if prim else "Suspected, less firmly: ") + _hjoin(_hphrase(x, F) for x in sec) + "."
        if free:
            lead += " Kept by the reviewer without support in these findings: " + _hjoin(_hphrase(x, F) for x in free) + "."
        # a fork between axes, or between dose mechanisms; not a reparameterization of the same input shape
        eq = [a for a in alts if a["pointing"] and a["delta"] <= 0 and not a["untestable"]
              and ({x.split(".")[0] for x in a["use"]} != {x.split(".")[0] for x in a["instead_of"]}
                   or {x.split(".")[0] for x in a["use"]} == {"dose"})][:2]
        if eq:
            lead += " " + " ".join(f"Equally possible: {_hjoin(_hphrase(x, F) for x in a['use'])}, in place of "
                                   f"{_hjoin(_hphrase(x, F, True) for x in a['instead_of'])}." for a in eq)
        # every other case that accounts for the same findings stays in the sentence, whatever its cost or the strength of its finding
        for a in every:
            if any(a["use"] == x["use"] and a["instead_of"] == x["instead_of"] for x in eq):
                continue
            # one case offered in place of a part and in place of the whole is written once, for the whole
            if any(x["use"] == a["use"] and set(a["instead_of"]) < set(x["instead_of"]) for x in every):
                continue
            k = " + ".join(_hshort(x, F) for x in a["instead_of"])
            u = " + ".join(_hshort(x, F) for x in a["use"]) + (" (not testable here)" if a.get("untestable") else "")
            if u not in also.setdefault(k, []):
                also[k].append(u)
        if also:
            lead += " Also possible: " + "; ".join(_hor(us) + (f" in place of {k}" if k else " in addition") for k, us in also.items()) + "."
        lead = (lead + nocurve).strip()
    used = [s for s in F["signals"] if _hexplains(c, s, cond)]
    used_q = {s["q"] for s in used}
    readings = list(dict.fromkeys(k["id"] for k in F["checks"] if k["q"] in used_q)) if comps else []
    if any(k["id"] == "group_means" for k in F["checks"]) and "group_means" not in readings:
        readings.append("group_means")
    if readings:
        lead += " Check the data first: " + "; ".join(HYP_CHECK_SHORT.get(i, i) for i in readings) + "."
    unused = [s for s in F["signals"] if s["strength"] != SUG and not _hexplains(c, s, cond)]
    deferred = list(dict.fromkeys(_hshort(part, F) for signal in unused
                                  for option in signal["explained_by"] for part in option))
    if unused:
        if not comps and "onset" in F["assessable"]:
            lead = "Use a single first-order input as the reference fit. These curves leave the mechanism unresolved."
        lead += " Candidates to check: " + ", ".join(deferred) + "."
        lead += " Hints not taken up: " + "; ".join(f"Q{s['q']}, {s['short']}" for s in unused) + "."
    unexplained = [s for s in F["signals"] if s["strength"] == SUG and not _hexplains(c, s, cond)]
    # R9: an unresolved or not assessable flip-flop reading is neither for nor against an absorption-limited tail; it stays an open case
    open_ff = ([_hshort("tail.absorption", F)] if F["flipflop_unresolved"] and "tail" in F["assessable"] and "tail.absorption" not in comps
               else [])
    if used:
        rests = "This rests on " + "; ".join(f"Q{s['q']}, {s['short']}" for s in sorted(used, key=lambda s: (s["strength"] != SUG, s["q"]))) + "."
    else:
        rests = "No finding of Q1–Q9 points to a further case." if F["assessable"] else ""
        if unused:
            rests = "The observations remain descriptive: " + "; ".join(s["short"] for s in unused) + "."
    if unexplained:
        rests += " Not accounted for: " + "; ".join(f"Q{s['q']}, {s['short']}" for s in unexplained) + " (check these data first)."
    ax = {x.split(".")[0] for x in comps}
    notes = [n for n in F["notes"] if ("lag is shorter" in n and "onset" in ax) or ("not identifiable" in n and ax & {"onset", "shape"})
             or ("ka and k can swap" in n and comps and "ka and k can swap" not in lead)]
    reach = " ".join([F["model"]] + notes + ["This is a suspicion for a model to verify, not a result."])
    rules = _heval(c, F)["rules"] + ([r["id"] for r in F["rules"] if r["factor"] == "condition" and cond in r["pattern"]["condition"]] if cond else [])
    m0 = dict(HYP_DEFAULT)
    m0_rules = _heval(m0, F)["rules"] + ([r["id"] for r in F["rules"] if r["factor"] == "condition" and "same" in r["pattern"]["condition"]] if cond else [])
    base = ("One compartment, first-order input from the dosing time, linear" + (f", one input model shared by both {attr} arms" if F["cond"] else ""))
    ladder = [["M0", base, "—", "The reference fit for every later step" + (f" (set aside by {', '.join(m0_rules)}; kept as the reference)" if m0_rules else "") + "."]]
    shows = lambda xs: "; ".join(dict.fromkeys(x for x in (_hlev(*y.split("."))[5].format(a=attr) for y in xs) if x)) or "—"  # noqa: E731
    if prim:
        n, nm = _hextra(prim, F)
        ladder.append(["M1", "M0 + " + "; ".join(_hphrase(x, F, True) for x in prim), f"{n:+d}" + (f" ({nm})" if nm else ""), shows(prim) + "."])
    rest = sec + free
    if rest:
        n, nm = _hextra(rest, F)
        ladder.append(["M2" if prim else "M1", ("M1 + " if prim else "M0 + ") + "; ".join(_hphrase(x, F, True) for x in rest),
                       f"{n:+d}" + (f" ({nm})" if nm else ""), shows(rest) + "."])
    for a in alts[:3]:
        what = "; ".join(_hphrase(x, F, True) for x in a["use"])
        inst = "; ".join(_hphrase(x, F, True) for x in a["instead_of"])
        ladder.append(["Alt", f"{what} instead of {inst}", f"{a['delta']:+d}", shows(a["use"]) + "."
                       + (" Not testable with these data: " + ", ".join(F["untestable"][u] for u in a.get("untestable", [])) + "." if a.get("untestable") else "")])
    prim_row = {"kind": "row", "head": ["Step", "Model", "Added parameters", "What the fit has to show"], "rows": ladder, "file": None,
                "lines": ["Model ladder", "each step adds only what a finding points to", F["model"],
                          "Compare nested steps by likelihood ratio and the rest by AIC, on the same observations, error model and BLQ handling."],
                "level": F["level"].rstrip(".")}
    return {"components": dict(c), "condition": cond, "parts": comps, "primary_parts": prim, "secondary_parts": sec, "reviewer_parts": free,
            "text": lead, "rests_on": rests, "reach": reach, "missing": _hneeds(F, comps, alts), "primary": prim_row,
            "signals_used": [s["id"] for s in used], "unexplained": [s["id"] for s in unexplained], "alternatives": alts,
            "possibilities": every,
            "rules_hit": rules, "origin": origin, "combination": _hcode(c) + (f" | {cond}" if cond else ""),
            "brief": {"suspected": [_hphrase(x, F, True) for x in prim], "less_firm": [_hphrase(x, F, True) for x in sec],
                      "kept": [_hphrase(x, F, True) for x in free],
                      "either": [[_hjoin(_hphrase(x, F, True) for x in a["use"]), _hjoin(_hphrase(x, F, True) for x in a["instead_of"])] for a in eq],
                      "short": {"suspected": [_hshort(x, F) for x in prim], "less_firm": [_hshort(x, F) for x in sec]},
                      "also": list(dict.fromkeys([" + ".join(_hshort(x, F) for x in a["use"]) for a in eq]
                                                 + [u.replace(" (not testable here)", "") for us in also.values() for u in us] + deferred
                                                 + open_ff)),
                      "open": open_ff,
                      "also_groups": [[k, us] for k, us in also.items()], "deferred": deferred,
                      "readings": [HYP_CHECK_TINY.get(i, HYP_CHECK_SHORT.get(i, i)) for i in readings],
                      "unused": [f"Q{s['q']}, {s['short']}" for s in unused],
                      "none": None if comps else ("unreadable" if "onset" not in F["assessable"] else "reference" if deferred else "simplest"),
                      "qs": sorted({s["q"] for s in used}), "unexplained_qs": sorted({s["q"] for s in unexplained}),
                      "next": ladder[1][:3] if len(ladder) > 1 else None}}


def _hsha(h):
    import hashlib
    core = {k: h[k] for k in ("id", "components", "condition", "text")}
    return hashlib.sha256(json.dumps(core, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def _hchecks(F, space, ev, h, origin):
    """Double-check of one hypothesis against the full list of combinations."""
    c, cond = h["components"], h["condition"]
    out = []

    def add(name, ok, detail, kind=None):
        out.append({"check": name, "result": kind or ("PASS" if ok else "FAIL"), "detail": detail})
    n_all = 1
    for a in HYP_ORDER:
        n_all *= len(HYP_AXES[a][1])
    add("space_complete", len(ev) == len(space) == len({_hcode(x) for x in space}),
        f"{len(space)} combinations evaluated ({n_all} before removing {n_all - len(space)} invalid pairs)"
        + (f"; condition factor with {len(COND_LEVELS)} levels" if F["cond"] else ""))
    e = _heval(c, F)
    crules = [r["id"] for r in F["rules"] if r["factor"] == "condition" and cond and cond in r["pattern"]["condition"]]
    add("not_set_aside", not e["rules"] and not crules, "no rule sets this combination aside" if not e["rules"] + crules
        else "set aside by " + ", ".join(e["rules"] + crules), None if origin == "selection" or not (e["rules"] + crules) else "REVIEWER_CHOICE")
    sug = [s["id"] for s in F["signals"] if s["strength"] == SUG]
    miss = [x for x in sug if x not in h["signals_used"]]
    possible = any(set(x for x in sug if next(s for s in F["signals"] if s["id"] == x)["factor"] == "main") <= set(z["explains"])
                   for z in ev if z["reading"] != "DISFAVORED")
    add("pointing_patterns_covered", not miss, "every pattern that points to a case is accounted for" if not miss else
        "not accounted for: " + ", ".join(miss), None if not miss else "REVIEWER_CHOICE" if origin != "selection" else None if possible else "UNEXPLAINED_IN_SPACE")
    add("parts_traced", not h["reviewer_parts"], "every added part accounts for a finding" if not h["reviewer_parts"] else
        "added without a finding: " + ", ".join(h["reviewer_parts"]), None if origin == "selection" or not h["reviewer_parts"] else "REVIEWER_CHOICE")
    if origin == "selection" and not miss:
        cheaper = [_hcode(x) for x, z in zip(space, ev) if z["reading"] != "DISFAVORED" and not z["untestable"]
                   and set(h["signals_used"]) - {s["id"] for s in F["signals"] if s["factor"] == "condition"} <= set(z["explains"]) and _hcost(x) < _hcost(c)]
        add("parsimony", not cheaper, "no cheaper testable combination accounts for the same findings" if not cheaper else
            "cheaper: " + ", ".join(cheaper[:5]))
    bad = [a for a in h["alternatives"] if a.get("combination") and next((z for x, z in zip(space, ev) if _hcode(x) == a["combination"]), {}).get("reading") == "DISFAVORED"]
    add("alternatives_valid", not bad, f"{len(h['alternatives'])} alternatives, none set aside by a rule" if not bad else
        "set aside: " + ", ".join(a["combination"] for a in bad))
    lost = [x for x in h["primary_parts"] + h["secondary_parts"] + h["reviewer_parts"] if _hphrase(x, F) not in h["text"]]
    add("text_matches_parts", not lost, "the sentence names every part" if not lost else "missing in the sentence: " + ", ".join(lost))
    return out


def _hreviews(out):
    """Review files in absorption/reviews/, oldest first. Each names the hypothesis revision it reviews."""
    d = Path(out) / "reviews"
    entries, log = [], []
    if not d.is_dir():
        return entries, log
    for f in sorted(d.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8-sig"))
            assert data.get("actor_type") == "HUMAN", "actor_type must be HUMAN"
            assert str(data.get("reviewer", "")).strip(), "reviewer must be named"
            from datetime import datetime
            ts = datetime.fromisoformat(str(data["reviewed_at"]).replace("Z", "+00:00")).isoformat()
            for r in data.get("reviews", []):
                assert r.get("decision") in ("AGREE", "REVISE", "REJECT"), f"decision {r.get('decision')!r} is not AGREE, REVISE or REJECT"
                entries.append((ts, f.name, data["reviewer"].strip(), r))
        except Exception as exc:  # noqa: BLE001 - a bad file is reported, not applied
            log.append({"file": f.name, "status": "REJECTED_FILE", "reason": str(exc) or repr(exc)})
    entries.sort(key=lambda x: (x[0], x[1]))
    return entries, log


_QUICK = [False]   # True inside the leave-one-sample-out rebuilds: hypotheses only, no figures, pages or files


def _hsample_label(e, r):
    cols = {c["id"]: c for c in e.get("columns", [])}
    t = COMMON.observation_time_h(r, next((v for v in cols.values() if v.get("meaning") == "TIME"), {}))
    if isinstance(t, (int, float)):
        return f"{e.get('dataset_id')} at {t:.4g} h"
    d = next((r[c] for c, v in cols.items() if v.get("meaning") == "DOSE" and isinstance(r.get(c), (int, float))), None)
    return f"the {d:g} mg/kg row of {e.get('dataset_id')}" if isinstance(d, (int, float)) else f"{e.get('dataset_id')} {r.get('record_id')}"


def _his_sample(e, r):
    keep = ("CONCENTRATION",) if e.get("role") == "PK_OBSERVATIONS" else ("PARAMETER_VALUE",)
    return any(c.get("meaning") in keep and (r.get("value_status") or {}).get(c["id"]) == "QUANTIFIED" for c in e.get("columns", []))


def _hbrief_plain(h):
    br = h.get("brief") or {}
    if br.get("none"):
        return {"simplest": "the simplest input", "reference": "single-input reference; mechanism unresolved"}.get(br["none"], "no case yet")
    main = " · ".join(br.get("suspected") or []) or " · ".join(br.get("less_firm") or [])
    return main + (" (less firm: " + " · ".join(br["less_firm"]) + ")" if br.get("suspected") and br.get("less_firm") else "")


def _hloo_one(tabs, dose_report, tmp):
    """One rebuild without figures, pages or files: {scope key: hypothesis}. Called with _QUICK set."""
    import shutil
    d = Path(tmp) / "run"
    shutil.rmtree(d, ignore_errors=True)
    d.mkdir()
    (d / "source_tables.json").write_text(json.dumps(tabs, ensure_ascii=False, default=float), encoding="utf-8")
    if dose_report:
        (d / "dose_normalization_assessment.json").write_text(json.dumps(dose_report, ensure_ascii=False, default=float), encoding="utf-8")
    return {b.get("scope_key", _board_key(b)): b["hypothesis"] for b in build(d)["status_boards"]}


def _hloo_drop(tables, ti, ri):
    """The tables with record ri of table ti left out."""
    e = tables[ti]
    recs = e.get("records") or []
    t2 = list(tables)
    t2[ti] = dict(e, records=recs[:ri] + recs[ri + 1:])
    return t2


def _hloo_worker(job_file):
    """Worker process of _hloo_parallel: rebuild each (ti, ri) deletion of its share and pickle the results in order.
    A rebuild that raises is returned as ("error", repr(exc)), as the serial loop records it."""
    import pickle
    import tempfile
    job = pickle.loads(Path(job_file).read_bytes())
    COMMON.SPECIES[:] = job["species"]   # the run's registry, including aliases added by the launcher
    _QUICK[0] = True
    res = []
    with tempfile.TemporaryDirectory(prefix="absorption_loo_") as tmp:
        for ti, ri in job["drops"]:
            try:
                res.append(("ok", _hloo_one(_hloo_drop(job["tables"], ti, ri), job["dose_report"], tmp)))
            except Exception as exc:  # noqa: BLE001 - recorded like the serial loop does
                res.append(("error", repr(exc)))
            _SPECS.clear()
    Path(job_file).with_suffix(".out").write_bytes(pickle.dumps(res))


def _hloo_workers(n_jobs):
    """Worker processes for the deletion rebuilds: ABSORPTION_STABILITY_WORKERS, else up to 8 by CPU count; 1 = serial."""
    import os
    try:
        n = int(os.environ.get("ABSORPTION_STABILITY_WORKERS", "0"))
    except ValueError:
        n = 0
    if n <= 0:
        n = min(8, os.cpu_count() or 1)
    return max(1, min(n, n_jobs // 4))   # each worker re-imports the modules; a few rebuilds each pays for it


def _hloo_parallel(tables, dose_report, drops, n, tmp):
    """Run the deletion rebuilds in n separate Python processes (round-robin shares) and return the results in the order of
    drops. Separate processes, not multiprocessing, so the launcher script is never re-imported on Windows. None if any
    worker fails to start or finish, and the caller then runs the serial loop."""
    import pickle
    import subprocess
    here = Path(__file__).resolve().parent
    procs = []
    for k in range(n):
        f = Path(tmp) / f"job{k}.pkl"
        f.write_bytes(pickle.dumps({"tables": tables, "dose_report": dose_report, "drops": drops[k::n], "species": list(COMMON.SPECIES)}))
        code = (f"import sys; sys.path.insert(0, {str(here)!r}); import importlib; "
                f"importlib.import_module({Path(__file__).stem!r})._hloo_worker({str(f)!r})")
        procs.append((f, subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)))
    shares = []
    for f, proc in procs:
        _, err = proc.communicate()
        out = f.with_suffix(".out")
        if proc.returncode != 0 or not out.is_file():
            return None
        shares.append(pickle.loads(out.read_bytes()))
    res = [None] * len(drops)
    for k, share in enumerate(shares):
        res[k::n] = share
    return res


def _hstability(tables, dose_report):
    """Leave each quantified sample (or reported row) out once, rebuild the hypotheses without figures, and record which r1
    hypotheses change (combination or the parts the firm findings point to). Off with ABSORPTION_STABILITY=0.
    The rebuilds are independent and run in parallel processes (ABSORPTION_STABILITY_WORKERS=1 runs them in this process);
    the result is the same either way."""
    import os
    import tempfile
    if _QUICK[0] or os.environ.get("ABSORPTION_STABILITY", "1") == "0":
        return None
    saved = (list(_SPECS), list(_SPECS_DONE), dict(_RENDER))
    _QUICK[0] = True
    try:
        with tempfile.TemporaryDirectory(prefix="absorption_loo_") as tmp:
            base = _hloo_one(tables, dose_report, tmp)
            # Losing curve eligibility is a change even if the empty/default
            # combination happens to have the same code before and after deletion.
            key = lambda h: (h["combination"], tuple(h["primary_parts"]), (h.get("brief") or {}).get("none") == "unreadable")  # noqa: E731
            out = {st: {"checks": 0, "changed": [], "errors": []} for st in base}
            jobs = []   # (table index, record index, label, scopes) in the serial order
            for ti, e in enumerate(tables):
                if e.get("role") not in ("PK_OBSERVATIONS", "REPORTED_PARAMETERS"):
                    continue
                sample_scope = _scope_identity(extract(e)[0])
                own = [st for st in base if st == sample_scope]
                if not own:
                    continue
                for ri, r in enumerate(e.get("records") or []):
                    if _his_sample(e, r):
                        jobs.append((ti, ri, _hsample_label(e, r), own))
            drops = [(ti, ri) for ti, ri, _, _ in jobs]
            n = _hloo_workers(len(drops))
            results = _hloo_parallel(tables, dose_report, drops, n, tmp) if n > 1 else None
            if results is None:
                results = []
                for ti, ri in drops:
                    try:
                        results.append(("ok", _hloo_one(_hloo_drop(tables, ti, ri), dose_report, tmp)))
                    except Exception as exc:  # noqa: BLE001 - a rebuild that fails without one sample is itself a finding
                        results.append(("error", repr(exc)))
            for (ti, ri, lab, own), (kind, cur) in zip(jobs, results):
                e, r = tables[ti], (tables[ti].get("records") or [])[ri]
                for st in own:
                    out[st]["checks"] += 1
                if kind == "error":
                    for st in own:
                        out[st]["errors"].append({"left_out": lab, "error": cur})
                    continue
                for st in own:
                    h = base[st]
                    c = cur.get(st)
                    if c is None or key(c) != key(h):
                        unreadable = bool(c and (c.get("brief") or {}).get("none") == "unreadable")
                        out[st]["changed"].append({"left_out": lab, "dataset": e.get("dataset_id"), "record": r.get("record_id"),
                                                   "combination": c["combination"] if c else None,
                                                   "becomes": "not assessable after deletion (no eligible curve remains)" if unreadable else _hbrief_plain(c) if c else "study no longer built",
                                                   **({"assessment": "NOT_ASSESSABLE"} if unreadable else {})})
    finally:
        _QUICK[0] = False
        _SPECS[:] = saved[0]
        _SPECS_DONE[:] = saved[1]
        _RENDER.clear()
        _RENDER.update(saved[2])
    return out


def _hstab_text(st, revision=1):
    """One line on the page: does the r1 hypothesis survive leaving out any one sample?"""
    if not st or not st.get("checks"):
        return None, False
    pre = "For r1: " if revision > 1 else ""
    n, ch, err = st["checks"], st["changed"], st["errors"]
    if not ch and not err:
        return f"{pre}unchanged when any one of {n} samples is left out.", False
    groups = {}
    for x in ch:
        groups.setdefault(x["becomes"], []).append(x["left_out"])
    parts = [f"without {_hjoin(v[:3]) + (f' and {len(v) - 3} more' if len(v) > 3 else '')}, it becomes {k}" for k, v in groups.items()]
    txt = f"{pre}changes in {len(ch)} of {n} checks: " + "; ".join(parts) + "."
    if err:
        txt += f" {len(err)} rebuild{'s' if len(err) > 1 else ''} failed without one sample (see hypothesis_context.json)."
    return txt, True


def hypotheses(boards, datasets, param_sets, dose_series_res, ev_iv_res, cond_res, ivs, out, stability=None, write=True):
    """One working hypothesis per study, species and regimen, the full case and combination space behind it (absorption/hypothesis_context.json),
    the review template, and the revision round for any review files in absorption/reviews/."""
    by_ds, by_ps = {}, {}
    for d in datasets:
        by_ds.setdefault(_study_key(d["card"]), []).append(d)
    for p in param_sets:
        by_ps.setdefault(_study_key(p["card"]), []).append(p)
    space = _hspace()
    ctx_studies = []
    for b in boards:
        ds, pss = by_ds.get(_board_key(b), []), by_ps.get(_board_key(b), [])
        ivb = _scope_ivs(b, ivs)
        F = _hfindings(b, ds, pss, dose_series_res, ev_iv_res, cond_res, ivb)
        ev = [_heval(c, F) for c in space]
        primary, chosen, added, not_added = _hselect(F, space, ev)
        crow = _hcond_rows(F)
        cond = _hcond_select(F, crow)
        h = _hcompose(b, F, chosen, cond)
        h.update(id=f"{_board_key(b)}-H-r1", revision=1, state="PENDING", review=None, changes=[], conflicts=[],
                 stability=(stability or {}).get(b.get("scope_key", _board_key(b))))
        h["sha256"] = _hsha(h)
        h["checks"] = _hchecks(F, space, ev, h, "selection")
        readings = {}
        for a in HYP_ORDER:
            for lv in HYP_AXES[a][1]:
                comp = f"{a}.{lv[0]}"
                pts = [s["id"] for s in F["signals"] if any(comp in alt for alt in s["explained_by"])]
                rl = [r["id"] for r in F["rules"] if r["factor"] == "main" and lv[0] in r["pattern"].get(a, [])]
                readings[comp] = {"label": lv[1], "parameters": lv[3], "reading": "NOT_TESTABLE" if comp in F["untestable"] else
                                  "POINTED_TO" if pts else "COMPATIBLE", "pointed_to_by": pts, "in_rule_patterns": rl,
                                  "why_not_testable": F["untestable"].get(comp)}
        counts = {}
        for e in ev:
            counts[e["reading"]] = counts.get(e["reading"], 0) + 1
        counts["WITH_UNTESTABLE_PART"] = sum(1 for e in ev if e["untestable"])
        sig_ix = {s["id"]: i for i, s in enumerate(F["signals"])}
        ctx = {"study": b["study"], "scope_id": _board_key(b), "scope_key": b.get("scope_key"), "regimen": b.get("regimen"), "species": b["species"], "species_group": b.get("species_group"), "datasets": b["datasets"],
               "findings": {k: F[k] for k in ("signals", "rules", "untestable", "bounds", "checks", "notes", "assessable", "cond", "model", "level")},
               "axis_readings": readings,
               "ranked_candidates": _hranked(F, ev, space),
               "combinations": {"axes": list(HYP_ORDER), "codes": HYP_CODES, "columns": ["combination", "reading", "parameters", "explains", "set_aside_by", "untestable"],
                                "rows": [[_hcode(c), e["reading"], _hcost(c), [sig_ix[x] for x in e["explains"]], e["rules"], e["untestable"]]
                                         for c, e in zip(space, ev)], "signal_index": [s["id"] for s in F["signals"]], "counts": counts},
               "condition_factor": crow,
               "selection": {"primary": _hcode(primary), "chosen": _hcode(chosen), "added_for_hints": added, "hints_not_added": not_added,
                             "cost": _hcost(chosen, cond), "condition": cond},
               "revisions": [h]}
        ctx_studies.append((b, F, ev, ctx))
    # revision round: apply review files in order
    entries, log = _hreviews(out)
    by_study = {_board_key(b): (b, F, ev, ctx) for b, F, ev, ctx in ctx_studies}
    for ts, fname, who, r in entries:
        item = by_study.get(r.get("scope_id", r.get("study")))
        if not item:
            log.append({"file": fname, "study": r.get("study"), "status": "UNKNOWN_STUDY"})
            continue
        b, F, ev, ctx = item
        cur = ctx["revisions"][-1]
        if r.get("hypothesis_id") != cur["id"] or r.get("hypothesis_sha256") != cur["sha256"]:
            log.append({"file": fname, "study": b["study"], "status": "STALE", "reason": f"names {r.get('hypothesis_id')}; the current revision is {cur['id']}"
                        + ("" if r.get("hypothesis_id") != cur["id"] else " with different content")})
            continue
        rv = {"reviewer": who, "reviewed_at": ts, "decision": r["decision"], "opinion": str(r.get("opinion", "")).strip(), "file": fname}
        if r["decision"] in ("AGREE", "REJECT"):
            cur.update(state="AGREED" if r["decision"] == "AGREE" else "REJECTED", review=rv)
            log.append({"file": fname, "study": b["study"], "status": "APPLIED", "decision": r["decision"], "revision": cur["id"]})
            continue
        comps = dict(cur["components"])
        cond = cur["condition"]
        bad = []
        for ax, lv in (r.get("components") or {}).items():
            try:
                _hlev(ax, lv)
            except KeyError:
                bad.append(f"{ax}.{lv}")
                continue
            if ax == "condition":
                cond = lv if F["cond"] else None
            elif ax in comps:
                comps[ax] = lv
        if not _hvalid(comps):
            bad.append(_hcode(comps) + " is not a valid combination")
            comps = dict(cur["components"])
        nh = _hcompose(b, F, comps, cond, origin="review")
        n = cur["revision"] + 1
        nh.update(id=f"{_board_key(b)}-H-r{n}", revision=n, state="PENDING", review=None, based_on=cur["id"], revised_from_review=rv)
        before, after = set(cur["parts"]), set(nh["parts"])
        nh["changes"] = ([f"added: {_hphrase(x, F)}" for x in nh["parts"] if x not in before] + [f"removed: {_hphrase(x, F)}" for x in cur["parts"] if x not in after])
        nh["conflicts"] = ([next(x["text"] for x in F["rules"] if x["id"] == rid) for rid in nh["rules_hit"]]
                           + [f"{_hphrase(u, F)}: not testable here, {F['untestable'][u]}" for u in nh["parts"] if u in F["untestable"]]
                           + [f"no longer accounted for: Q{s['q']}, {s['short']}" for s in F["signals"] if s["id"] in cur["signals_used"] and s["id"] not in nh["signals_used"]]
                           + [f"unknown part {x}, ignored" for x in bad])
        if not nh["changes"]:
            nh["changes"] = ["no change to the parts; the opinion is passed on to modelling with this revision"]
        nh["sha256"] = _hsha(nh)
        nh["checks"] = _hchecks(F, _hspace(), ev, nh, "review")
        cur["review"] = rv
        cur["state"] = "REVISED"
        ctx["revisions"].append(nh)
        log.append({"file": fname, "study": b["study"], "status": "APPLIED", "decision": "REVISE", "revision": nh["id"]})
    for b, F, ev, ctx in ctx_studies:
        cur = ctx["revisions"][-1]
        b["hypothesis"] = {k: v for k, v in cur.items() if k not in ("alternatives",)} | {
            "alternatives": [{k: v for k, v in a.items() if k != "untestable"} for a in cur["alternatives"]],
            "history": [{"id": x["id"], "state": x["state"], "text": x["text"], "review": x.get("review"), "changes": x.get("changes", []),
                         "conflicts": x.get("conflicts", [])} for x in ctx["revisions"]],
            "checks_before_modelling": F["checks"], "stability": ctx["revisions"][0].get("stability")}
        b["ranked_candidates"] = ctx["ranked_candidates"]   # the full ordered list for Modeling; the hypothesis above is its first reading
    context = {"version": HYP_VERSION, "rules_version": VERSION,
               "purpose": ("Every absorption case and every combination of cases, evaluated per study against the findings of Q1–Q9, so the "
                           "working hypothesis can be double-checked. Not shown on the pages."),
               "method": ("A combination is set aside only by a formal test (T1–T5) or a hard bound (the Tmax cross-check). A descriptive "
                          "pattern points to cases; it never sets one aside. The working hypothesis is the testable combination with the fewest "
                          "added parameters that accounts for qualifying patterns. Descriptive hints remain open alternatives and cannot add "
                          "mechanisms or break a tie. Conditions are a separate factor, because no rule couples them to the other axes."),
               "thresholds": {"tolerance_rel": TOL, "flip_ratio": FLIP_RATIO, "trend_ratio": TREND_RATIO, "auc_window_share_min": SHARE_MIN,
                              "project_set": True},
               "axes": {a: {"title": HYP_AXES[a][0], "levels": [{"id": f"{a}.{x[0]}", "label": x[1], "extra_parameters": x[2], "parameters": x[3],
                                                                "the_fit_has_to_show": x[5], "default": x[0] == HYP_DEFAULT[a]} for x in HYP_AXES[a][1]]}
                        for a in HYP_ORDER} | {"condition": {"title": "Condition effect (separate factor)", "levels": [
                            {"id": f"condition.{x[0]}", "label": x[1], "extra_parameters": x[2], "parameters": x[3], "the_fit_has_to_show": x[5]}
                            for x in COND_LEVELS]}},
               "invalid_pairs": ["onset.transit only with shape.first_order (the chain feeds first-order absorption)",
                                 "tail.absorption not with shape.zero_order or shape.weibull_sigmoid"],
               "catalog_crosswalk": {"source": "absorption_mechanisms_r43.json (GPT r4.3 handoff; copy in _backup_20261106_port58_absorption)",
                                     "entries": {k: {"kind": v[0], "here": v[1], "note": v[2]} for k, v in GPT_CROSSWALK.items()}},
               "review_log": log, "studies": [ctx for *_, ctx in ctx_studies]}
    if not write:
        return context
    (out / "hypothesis_context.json").write_text(json.dumps(context, ensure_ascii=False, separators=(",", ":"), default=float), encoding="utf-8")
    template = {"actor_type": "HUMAN", "reviewer": "", "reviewed_at": "",
                "how": ("Fill one entry per study, save this file into absorption/reviews/ and run "
                        "python -m research_pipeline.eda_absorption <run folder> --attach. decision is AGREE, REVISE or REJECT. For REVISE, "
                        "components may set any axis to one of its levels (see hypothesis_context.json, axes); leave it out to change nothing."),
                "reviews": [{"study": b["study"], "scope_id": _board_key(b), "hypothesis_id": b["hypothesis"]["id"], "hypothesis_sha256": b["hypothesis"]["sha256"],
                             "decision": "PENDING", "opinion": "", "components": dict(b["hypothesis"]["components"])
                             | ({"condition": b["hypothesis"]["condition"]} if b["hypothesis"]["condition"] else {})} for b in boards]}
    (out / "hypothesis_review.template.json").write_text(json.dumps(template, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "reviews").mkdir(exist_ok=True)
    return context


# ---- page parts

def _hid(study):
    return f"h-{_slug(study)}"


def _hchip(h):
    cls, lab = HYP_STATE[h["state"]]
    if h["state"] == "PENDING" and h["revision"] > 1:
        lab = f"Revised (r{h['revision']}) · review pending"
    return f'<span class="st {cls}">{_e(lab)}</span>'


def _hform(b, h):
    F_cond = h.get("condition")
    sel = []
    for a in HYP_ORDER:
        opts = "".join(f'<option value="{_e(x[0])}"{" selected" if h["components"][a] == x[0] else ""}>{_e(x[1])}</option>' for x in HYP_AXES[a][1])
        sel.append(f'<label>{_e(HYP_AXES[a][0])}<select data-axis="{a}">{opts}</select></label>')
    if F_cond:
        opts = "".join(f'<option value="{_e(x[0])}"{" selected" if F_cond == x[0] else ""}>{_e(x[1].format(a="condition"))}</option>' for x in COND_LEVELS)
        sel.append(f'<label>Condition<select data-axis="condition">{opts}</select></label>')
    dec = "".join(f'<label class="hdec"><input type="radio" name="decision" value="{v}"> {t}</label>'
                  for v, t in (("AGREE", "Agree"), ("REVISE", "Revise"), ("REJECT", "Reject")))
    return (f'<details class="more hrev-form"><summary>Add your opinion</summary><form class="hform" data-study="{_e(b["study"])}" data-scope="{_e(_board_key(b))}" data-hid="{_e(h["id"])}" '
            f'data-sha="{_e(h["sha256"])}"><fieldset><legend>Decision</legend>{dec}</fieldset>'
            '<label class="hwide">Opinion<textarea name="opinion" rows="4" placeholder="What should change, and why"></textarea></label>'
            '<details class="tier"><summary>Change parts of the hypothesis (optional, for Revise)</summary><div class="hsel">' + "".join(sel) + '</div></details>'
            '<label class="hwide">Reviewer<input name="reviewer" autocomplete="name"></label>'
            '<p><button type="submit">Save review file</button> <span class="hmsg muted" aria-live="polite"></span></p>'
            '<p class="ev">The file goes into absorption/reviews/ of this run. Running <code>python -m research_pipeline.eda_absorption &lt;run folder&gt; '
            '--attach</code> then makes the next revision. Nothing is approved by this page.</p></form></details>')


def attach_plain(boards, datasets, ivs=()):
    """Shared rule 10: two plain sentences per question (what the plot shows; the modelling suggestion) and for the hypothesis."""
    by_ds = {}
    for d in datasets:
        by_ds.setdefault(_study_key(d["card"]), []).append(d)
    for b in boards:
        pl = COMMON.plain_absorption(b, by_ds.get(_board_key(b), []), TOL, len(_scope_ivs(b, ivs)))
        for q in b.get("questions", []):
            q["plain"] = pl.get(q["q"])
        if b.get("hypothesis") and pl.get("H"):
            b["hypothesis"]["plain"] = pl["H"]
        b["plain_check"] = COMMON.plain_gate("absorption", b)   # translation gate; problems are listed on the main page


def section_card(tag, title, folder, what, n, thumbs_files, species, empty_reason):
    """Portal card of one section (George 2026-11-25): a count only when there are figures; otherwise one plain sentence saying why
    there are none, with no empty preview bar and no 'View all 0' link."""
    if n:
        thumbs = "".join(f'<img src="{folder}/{_e(s)}" alt="Preview of {_e(s)}" loading="lazy">' for s in thumbs_files)
        sp = [x for x in species if x.get("figures")]
        per = (" " + ("One page per species: " + ", ".join(f'{x["species"]} ({x["figures"]})' for x in sp) + ".") if sp else "")
        body = (f'<span class="badge">{n} figure{"s" if n != 1 else ""}</span><h3>{_e(title)}</h3><p class="muted">{_e(what)}{_e(per)}</p>'
                f'<div class="thumbs">{thumbs}</div><span class="open">Open {_e(title)} ({n} figure{"s" if n != 1 else ""}) →</span>')
    else:
        body = (f'<span class="badge">No figures</span><h3>{_e(title)}</h3><p class="muted">{_e(what)}</p><p>{_e(empty_reason)}</p>'
                f'<span class="open">Open {_e(title)} →</span>')
    return f'<!--{tag}-CARD-START--><a class="category" id="{tag}" href="{folder}/index.html">{body}</a><!--{tag}-CARD-END-->'


def _absorption_empty_reason(res):
    if res.get("datasets") or res.get("reported_parameter_ev_datasets"):
        return "No absorption figures: the non-IV curves in this package could not be drawn; the findings are in the text."
    if res.get("iv_references") or res.get("iv_reference_count"):
        return "No absorption figures: this study has IV dosing only, so there is no absorption phase to show."
    return "No absorption figures: this package has no concentration profiles after non-IV dosing."


def _plain_html(p, numbers):
    """The two plain sentences, with every number and test detail collapsed below them (shared rule 10)."""
    nums = [x for x in numbers if x]
    notes = "".join(f" {_e(x)}" for x in p.get("notes") or [])
    return (f'<p class="concl plain">{_e(p["shows"])} <b>{_e(p["suggests"])}</b>{notes}</p>'
            + ('<details class="nums"><summary>Numbers behind this</summary>' + "".join(f'<p class="ev">{_e(x)}</p>' for x in nums) + '</details>' if nums else ""))


def _hrow_html(b):
    h = b.get("hypothesis")
    if not h:
        return ""
    prim = _primary_html(h["primary"])
    sub = " ".join(x for x in (h["rests_on"], h["reach"]) if x)
    miss = ('<p class="miss"><b>Missing:</b> ' + "; ".join(_e(m) for m in h["missing"]) + '</p>') if h["missing"] else ""
    stx, warn = _hstab_text(h.get("stability"), h["revision"])
    if stx:
        miss += f'<p class="hstab{" warn" if warn else ""}"><b>One sample left out:</b> {_e(stx)}</p>'
    hist = []
    for x in h["history"]:
        rv = x.get("review")
        if rv:
            hist.append(f'<div class="hop"><p><b>{_e(rv["reviewer"])}</b> · {_e(rv["reviewed_at"][:10])} · {_e(rv["decision"].lower())} {_e(x["id"])}</p>'
                        + (f'<blockquote>{_e(rv["opinion"])}</blockquote>' if rv["opinion"] else "") + '</div>')
    if h["revision"] > 1:
        hist.append('<div class="hop"><p><b>' + _e(h["id"]) + '</b> · ' + _e("; ".join(h.get("changes", []))) + '</p>'
                    + ('<p class="miss"><b>Conflicts with the findings:</b> ' + "; ".join(_e(c) for c in h["conflicts"]) + '</p>' if h.get("conflicts") else "")
                    + '</div>')
    fails = [c for c in h["checks"] if c["result"] not in ("PASS",)]
    chk = (f'<p class="ev">Double-check against the full list of combinations: {sum(c["result"] == "PASS" for c in h["checks"])} of '
           f'{len(h["checks"])} checks passed' + ("; " + "; ".join(f'{c["check"]}: {c["result"]}, {c["detail"]}' for c in fails) if fails else "") + '.</p>')
    pre = "".join(f'<li>{_e(c["text"])} (Q{c["q"]})</li>' for c in h["checks_before_modelling"])
    more = ('<details class="more"><summary>More for H: how it was chosen' + (" · checks before modelling" if pre else "") + '</summary>'
            '<p class="ev">Each absorption case and each combination of cases is compared with the findings of Q1–Q9. Only a formal test '
            '(T1–T5) or a hard bound sets a combination aside; a descriptive pattern points to cases but never sets one aside. The hypothesis is '
            'the simplest testable combination covering qualifying findings. Descriptive hints keep alternatives open. '
            'The full list stays in hypothesis_context.json for checking.</p>' + chk
            + (f'<p class="ev"><b>Checks before modelling</b></p><ul class="ev">{pre}</ul>' if pre else "") + '</details>')
    return (f'<article class="qrow hrow" id="{_hid(_board_key(b))}"><div class="qhead"><span class="qn">H</span><h3>Working hypothesis</h3>{_hchip(h)}'
            '<p class="q">Taken together, which suspicion should a model verify next?</p></div>'
            f'<div class="qbody{"" if prim else " noprim"}"><div class="qtext">'
            + (_plain_html(h["plain"], [h["text"], sub]) if h.get("plain") else f'<p class="concl">{_e(h["text"])}'
               + (f' <span class="sub">{_e(sub)}</span>' if sub else "") + '</p>') + f'{miss}</div>{prim}</div>'
            f'<div class="hrev">{"".join(hist)}{_hform(b, h)}</div>{more}</article>')


HYP_CHECK_SHORT = {"lloq": "BLQ before the first quantified sample", "averaging": "a group-mean dip that averaging can make",
                   "steepens": "a late decline that steepens (BLQ handling)", "f_above_one": "reported F above 1",
                   "occasion": "a dose series from repeated dosing", "confounded": "a condition comparison that differs in more than one attribute",
                   "window": "t½ read over different sampling windows", "group_means": "a dose difference that no test confirms"}

# the same checks in two or three words, for the overview summary
HYP_CHECK_TINY = {"lloq": "early BLQ", "averaging": "averaging of animals", "steepens": "BLQ near the end", "f_above_one": "F above 1",
                  "occasion": "repeated dosing", "confounded": "confounded condition", "window": "t½ windows differ",
                  "group_means": "between-animal variability can contribute to the group contrast; check group uncertainty and any figure-reading error"}



_hnum = COMMON._hnum


def _hor(xs):
    xs = list(dict.fromkeys(xs))
    return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " or " + xs[-1]


_hcap = COMMON._hcap


def _hbrief_html(h):
    """The working hypothesis in a few words, for the overview."""
    br = h.get("brief") or {}
    if br.get("none") == "simplest":
        main = "Simplest input: first-order from the dosing time; nothing points further"
    elif br.get("none") == "reference":
        main = "Single-input reference fit; the observed shape leaves alternatives open"
    elif br.get("none"):
        main = "Nothing points to an absorption case yet"
    else:
        main = " · ".join(br.get("suspected") or [])
    sub = []
    if br.get("suspected") and br.get("less_firm"):
        sub.append("Less firm: " + " · ".join(br["less_firm"]))
    elif br.get("less_firm"):
        main = " · ".join(br["less_firm"]) + " (less firm)"
    main = _hcap(main)
    if br.get("kept"):
        sub.append("Kept by the reviewer: " + " · ".join(br["kept"]))
    sub += [f"Or: {u} instead of {i}" for u, i in br.get("either") or []]
    rest = [u for u in br.get("also") or [] if not any(u == e[0] for e in br.get("either") or [])]
    if rest:
        sub.append("Also possible: " + " · ".join(rest))
    if br.get("readings"):
        sub.append("Check the data first: " + " · ".join(br["readings"]))
    if br.get("unused"):
        sub.append("Hints not taken up: " + "; ".join(br["unused"]))
    return f'<b>{_e(main)}</b>' + "".join(f'<span class="sub">{_e(x)}</span>' for x in sub)


def _absorption_names(boards, by_scope, parameters):
    """Name reader-facing rows using species, administration and sampling occasion."""
    labels = {}
    for board in boards:
        key = _board_key(board)
        data = by_scope.get(key, [])
        cards = [item["card"] for item in (data or parameters.get(key, []))]
        routes = {c["route_detail"] for c in cards}
        route = {"PO": "oral dosing", "SC": "subcutaneous injection", "IM": "intramuscular injection"}.get(
            next(iter(routes)) if len(routes) == 1 else None, "extravascular dosing")
        species = species_group(board["species"])
        # a reported-parameter table carries no matrix category (NOT_FOUND); only a measured non-plasma matrix is tissue sampling
        multiple_matrices = any(c.get("matrix_category") not in (None, "", "NOT_FOUND", "PLASMA_SERUM_BLOOD") for c in cards)
        occasion = re.search(r"day\s+(\d+)\b", board.get("regimen", ""), re.I)
        label = f"{species} · {route}"
        if multiple_matrices:
            label += " with tissue sampling"
        if occasion:
            label += f", day {occasion[1]} of repeated dosing"
        labels[key] = label
    # Distinct source arms can still have identical recorded designs.
    duplicates = {}
    for key, label in labels.items():
        duplicates.setdefault(label, []).append(key)
    for label, keys in duplicates.items():
        if len(keys) > 1:
            for number, key in enumerate(sorted(keys), 1):
                labels[key] = f"{label} (study {number})"
    return labels


def _absorption_overview_paras(hs, by_scope, labels, plain=False):
    peaks, sparse, sensitive = [], [], []
    for board, hypothesis in hs:
        key = _board_key(board)
        metrics = [series["metrics"] for item in by_scope.get(key, [])
                   if item["card"]["tests_allowed"] and item["card"]["matrix_category"] == "PLASMA_SERUM_BLOOD"
                   for series in item["series"] if "tmax" in series["metrics"]]
        if metrics:
            times = [m["tmax"] for m in metrics]
            time = f"{min(times):.3g}" if min(times) == max(times) else f"{min(times):.3g}–{max(times):.3g}"
            peaks.append((labels[key], time))
            if any(m.get("n_before_peak", 0) < 2 for m in metrics):
                sparse.append(labels[key])
        stability = hypothesis.get("stability") or {}
        if stability.get("changed"):
            sensitive.append(labels[key])
    observations = "The highest measured concentration occurred at " + "; ".join(
        f"{time} h ({name})" for name, time in peaks[:6]) + "." if peaks else (
        "The available summaries do not establish when concentrations peaked after dosing.")
    if len(peaks) > 6:
        observations += " Other experiments are listed by species below."
    paras = [("What the data point to", observations)]
    readings = list(dict.fromkeys(f'{h["plain"]["shows"]} {h["plain"]["suggests"]}' for _, h in hs if h.get("plain")))
    if plain and readings:  # shared rule 10: the plain reading leads; the peak times are the numbers behind it
        paras = [("What the data point to", " ".join(readings), observations)]
    cand_at = len(paras)
    if sparse:
        paras.append(("What is missing", "At least one curve had fewer than two measurements before its observed peak in "
                      + _hjoin(sparse[:3]) + (" and other experiments" if len(sparse) > 3 else "")
                      + ". Earlier samples would better resolve the rise."))
    if sensitive:
        paras.append(("How firm it is", "Leaving out one sample changed a candidate explanation in " + _hjoin(sensitive[:3])
                      + (" and other experiments" if len(sensitive) > 3 else "") + "."))
    paras.append(("How to review", "Select a species to see the curves, alternative explanations and review status."))

    # every candidate explanation, by experiment, in short names; trimmed to the word budget of the summary
    per_species = {}
    for board, _ in hs:
        per_species[species_group(board["species"])] = per_species.get(species_group(board["species"]), 0) + 1

    def name(board):   # the species alone where it has one experiment; the full label otherwise
        sp = species_group(board["species"])
        return sp if per_species[sp] == 1 else labels[_board_key(board)]

    def candidates(cap, checks):
        out = []
        for board, hypothesis in hs:
            br = hypothesis.get("brief") or {}
            sh = br.get("short") or {}
            main = " + ".join(sh.get("suspected") or []) or " + ".join(sh.get("less_firm") or [])
            if not main and br.get("deferred"):
                main = "reference fit; mechanism unresolved"
            if not main:
                continue
            if sh.get("suspected") and sh.get("less_firm"):
                main += ", less firmly " + " + ".join(sh["less_firm"])
            elif sh.get("less_firm"):
                main += " (less firm)"
            also = br.get("also") or []
            shown = also if cap is None else also[:cap]
            text = f"{name(board)}: {main}"
            if shown:
                text += "; also possible: " + ", ".join(shown) + (f" (+{len(also) - len(shown)} more)" if len(also) > len(shown) else "")
            elif also:
                text += f"; {len(also)} other candidates"
            if checks and br.get("readings"):
                text += "; check first: " + ", ".join(br["readings"])
            out.append(text + ".")
        return " ".join(out)

    def words(ps):
        return sum(len(f"{p[0]}. {p[1]}".split()) for p in ps)
    for cap, checks in ((None, True), (5, True), (3, True), (3, False), (2, False), (1, False), (0, False)):
        text = candidates(cap, checks)
        trial = paras[:cand_at] + ([("Candidate explanations", text)] if text else []) + paras[cand_at:]
        if words(trial) <= SUMMARY_WORDS or (cap, checks) == (0, False):
            break
    return trial


def _hoverview_html(boards, page_of, by_scope, labels):
    """Describe observed peaks and sampling limits; keep the model comparisons in the table."""
    hs = [(b, b["hypothesis"]) for b in boards if b.get("hypothesis")]
    if not hs:
        return ""
    br = {_board_key(b): h.get("brief") or {} for b, h in hs}
    paras = _absorption_overview_paras(hs, by_scope, labels, plain=True)
    rows = []
    for b, h in hs:
        x = br[_board_key(b)]
        qs = ", ".join(f"Q{q}" for q in x.get("qs") or [])
        rests = (qs or '<span class="muted">' + ("Nothing yet" if x.get("none") == "unreadable" else "No finding points further") + '</span>') + (
            f'<span class="sub">Not accounted for: {", ".join(f"Q{q}" for q in x["unexplained_qs"])}</span>' if x.get("unexplained_qs") else "")
        stx = h.get("stability") or {}
        if stx.get("checks"):
            k = len(stx["changed"])
            rests += ('<span class="sub">' + (f"{k} of {stx['checks']} samples change{'s' if k == 1 else ''} it" if k else f"No single sample changes it ({stx['checks']} checked)")
                      + '</span>')
        nxt = x.get("next")
        step = f'{_e(nxt[0])}: {_e(_hcap(nxt[1].replace("M0 + ", "")))}<span class="sub">{_e(nxt[2])}</span>' if nxt else '<span class="muted">M0 only</span>'
        miss_b = "; ".join(dict.fromkeys(m.split(", to ")[0] for m in h.get("missing") or [])) or "—"
        href = f'{page_of(b)}#{_hid(_board_key(b))}'
        rows.append(f'<tr><td><a href="{_e(href)}">{_e(labels[_board_key(b)])}</a></td>'
                    f'<td>{_hbrief_html(h)}</td><td data-l="Rests on">{rests}</td><td data-l="First model step">{step}</td>'
                    f'<td data-l="Missing">{_e(miss_b)}</td><td><a href="{_e(href)}">{_hchip(h)}</a></td></tr>')
    return ('<section class="panel" id="hypotheses"><h2>Working hypotheses: first review</h2><p class="muted">One working hypothesis per study, species and regimen, '
            'drawn from its nine questions. Each is a suspicion for a model to verify, not a result.</p>'
            '<div class="hsumtext">' + "".join(f'<p><b>{_e(p[0])}.</b> {_e(p[1])}</p>' for p in paras) + '</div>'
            + "".join(f'<details class="nums"><summary>Numbers behind this</summary><p class="ev">{_e(p[2])}</p></details>' for p in paras if len(p) > 2) +
            '<details><summary>Compare hypotheses by experiment</summary><div class="tw"><table class="res hsum"><tr><th>Experiment</th><th>Hypothesis, in short</th><th>Rests on</th><th>First model step</th>'
            '<th>Missing</th><th>Review</th></tr>' + "".join(rows) + '</table></div></details></section>')


HYP_CSS = ('.st-hyp{background:#eef4fb;border-color:#c9d9ec;color:#24507a}.hstab{font-size:14px;margin:8px 0 0;padding:6px 12px;'
           'border-left:3px solid #c9d9ec;background:#f5f9fd;overflow-wrap:anywhere}.hstab.warn{border-left-color:#e8d6b4;background:#fffaf0}.hsum .sub{display:block;color:#455c69;font-size:13px;font-weight:400;margin-top:2px}'
           '.hsum td:nth-child(2){min-width:260px}.hsum td:nth-child(3){min-width:150px}.hsum td:nth-child(4){min-width:180px}.hsum td:last-child{white-space:nowrap}.hsum a{text-decoration:none}'
           '.hsumtext{max-width:880px;margin:4px 0 14px}.hsumtext p{margin:0 0 10px;line-height:1.55}.hsumtext b{font-weight:650}@media(max-width:760px){'
           '.hsum,.hsum tbody,.hsum tr,.hsum td{display:block}.hsum tr:first-child{display:none}.hsum tr{border-top:1px solid var(--line);padding:8px 0}'
           '.hsum td,.hsum td:nth-child(n){border:0;padding:3px 0;min-width:0;white-space:normal}.hsum td[data-l]::before{content:attr(data-l);display:block;'
           'font-size:12px;color:var(--muted)}}.hrow{border-top:2px solid var(--accent)}'
           '.hrev{margin:12px 0 0}.hop{font-size:14px;margin:8px 0;padding:6px 12px;border-left:3px solid #c9d9ec;background:#f5f9fd}.hop p{margin:2px 0}'
           '.hop blockquote{margin:4px 0;white-space:pre-line}.hform{display:grid;gap:10px;font-size:14px;margin-top:8px}'
           '.hform fieldset{border:0;padding:0;margin:0;display:flex;flex-wrap:wrap;gap:6px 18px}.hform legend{font-weight:650;padding:0;margin-bottom:4px}'
           '.hform label{display:grid;gap:4px}.hform .hdec{display:inline-flex;gap:6px;align-items:center}'
           '.hform textarea,.hform input,.hform select{font:inherit;padding:6px 8px;border:1px solid var(--line);border-radius:6px;background:white;'
           'color:var(--ink);max-width:100%;min-width:0}.hform select{width:100%}.hsel{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(240px,100%),1fr));'
           'gap:8px 16px;margin-top:8px}.hsel label,.hform label{min-width:0}.hform{min-width:0}.hrev{min-width:0}'
           '.hform button{font:inherit;font-weight:650;padding:6px 14px;border-radius:8px;border:1px solid var(--accent);background:var(--accent);'
           'color:white;cursor:pointer}.hform code{font-size:12.5px;overflow-wrap:anywhere}ul.ev{margin:4px 0 0;padding-left:20px}')

HYP_JS = ('<script>(function(){document.querySelectorAll("form.hform").forEach(function(f){var key="abs-hyp-"+f.dataset.hid;'
          'function dec(){var r=f.querySelector("input[name=decision]:checked");return r?r.value:""}'
          'try{var d=JSON.parse(localStorage.getItem(key)||"null");if(d){f.opinion.value=d.opinion||"";f.reviewer.value=d.reviewer||"";'
          'var r=d.decision&&f.querySelector("input[name=decision][value="+d.decision+"]");if(r)r.checked=true}}catch(e){}'
          'f.addEventListener("input",function(){try{localStorage.setItem(key,JSON.stringify({opinion:f.opinion.value,reviewer:f.reviewer.value,decision:dec()}))}catch(e){}});'
          'f.addEventListener("submit",function(ev){ev.preventDefault();var msg=f.querySelector(".hmsg");'
          'if(!dec()||!f.reviewer.value.trim()){msg.textContent="Choose a decision and enter your name.";return}'
          'var rec={study:f.dataset.study,scope_id:f.dataset.scope,hypothesis_id:f.dataset.hid,hypothesis_sha256:f.dataset.sha,decision:dec(),opinion:f.opinion.value.trim()};'
          'if(dec()==="REVISE"){rec.components={};f.querySelectorAll("select[data-axis]").forEach(function(s){rec.components[s.dataset.axis]=s.value})}'
          'var out={actor_type:"HUMAN",reviewer:f.reviewer.value.trim(),reviewed_at:new Date().toISOString(),reviews:[rec]};'
          'var a=document.createElement("a");a.href=URL.createObjectURL(new Blob([JSON.stringify(out,null,2)],{type:"application/json"}));'
          'a.download="hypothesis_review_"+f.dataset.hid+".json";document.body.appendChild(a);a.click();a.remove();'
          'msg.textContent="Saved "+a.download+". Put it in absorption/reviews/ of this run."})})})();</script>')


# ---------------------------------------------------------------- compact context for a downstream model
#
# absorption.json and hypothesis_context.json hold everything (about 1 MB for four studies, more than one model input may carry).
# model_context.txt keeps what a model needs to set up and test the fit, in about 30 lines per study: the numbers behind each
# curve and comparison figure, the findings that point to cases, the rules that set combinations aside, and the working
# hypothesis with its model ladder. It leaves out page text, figure files and the full combination table (that stays in
# hypothesis_context.json).

MC_STATUS = {"ANSWERABLE": "Y", "PARTLY_ANSWERABLE": "P", "NOT_ANSWERABLE_YET": "N", "NOT_APPLICABLE": "-"}
MC_LEVEL = {"GROUP_MEAN": "group mean", "INDIVIDUAL": "individual animals", "INDIVIDUAL_IDENTITY_UNVERIFIED": "individual (identity unverified)",
            "GROUP_SUMMARY": "group summary"}
MC_STATE = {"PENDING": "review pending", "AGREED": "agreed", "REJECTED": "rejected"}
MC_PARAM = {"AUC": "AUC", "CMAX": "Cmax", "TMAX": "Tmax", "THALF": "t½", "CL_F": "CL/F", "F": "F"}


def _g(x):
    if not isinstance(x, (int, float)):
        return "?"
    return f"{x:.0f}" if abs(x) >= 1000 else f"{x:.3g}"


def _mc_part(p):
    return p.split(".", 1)[1] if "." in p else p


def _mc_curves(sets, ev_iv, conds, dser):
    """One line per curve (the numbers behind A1/A2 and the question figures), then the comparison figures."""
    out = []
    for d in sets:
        c = d["card"]
        for s in d.get("series") or []:
            m = s.get("metrics") or {}
            if not m.get("n_quantified"):
                continue
            dose = _given(s, c)
            bits = [f"{m['n_quantified']} pts to {_g(m.get('tlast'))} h" + (f", {m['n_blq']} BLQ" if m.get("n_blq") else "")]
            if m.get("n_not_detected"):
                bits.append(f"{m['n_not_detected']} not detected; last sample {_g(m['last_sample_h'])} h")
            if m.get("first_t") is not None:
                bits.append(f"first {_g(m['first_t'])} h" + (f" at {m['first_frac_cmax']:.0%} Cmax" if isinstance(m.get("first_frac_cmax"), (int, float)) else ""))
            if m.get("tmax") is not None:
                bits.append(f"Tmax {_g(m['tmax'])} h, Cmax {_g(m.get('cmax'))} {c.get('unit') or ''}".rstrip()
                            + (f" (Cmax/D {_g(m['cmax'] / dose)})" if isinstance(dose, (int, float)) and dose and isinstance(m.get("cmax"), (int, float)) else ""))
            t = m.get("terminal_selected") or {}
            if t.get("thalf"):
                bits.append(f"t½ {_g(t['thalf'])} h from {_g(t['start'])} h (n {t['n']})")
            sp = (m.get("split") or {}).get("class") or ""
            if sp.startswith("DECLINE_"):
                bits.append("late decline " + sp.split("_", 1)[1].lower())
            if (m.get("mt1") or 0) > 0:
                bits.append("C/t rose beyond the assumed tolerance")
            flags = [x for x in m.get("caveats") or [] if x not in ("GROUP_MEAN",)]
            lab = f"/{s.get('label')}" if len(d.get("series") or []) > 1 and s.get("label") and "mg/kg" not in s["label"] else ""
            out.append(f"  {c['dataset_id']}{lab} {c.get('route_detail') or c.get('route_class')}"
                       + (f" {_g(dose)} mg/kg" if isinstance(dose, (int, float)) else "") + ": " + "; ".join(bits)
                       + (f" [{', '.join(flags).lower()}]" if flags else ""))
    for x in dser:
        r = x.get("rows") or []
        th = [y.get("thalf") for y in r]
        tm = [y.get("tmax") for y in r]
        out.append(f"  dose series {_g(x['doses'][0])}→{_g(x['doses'][-1])} mg/kg: Cmax/D {_g(x.get('cmax_d_ratio'))}×; AUC/D 0–{_g(x.get('window_end_h'))} h "
                   f"{_g(x.get('R_window'))}×, to own tlast {_g(x.get('R_own_tlast'))}×"
                   + (f"; t½ {_g(th[0])}→{_g(th[-1])} h" if th and th[0] and th[-1] else "")
                   + (f"; Tmax {_g(tm[0])}→{_g(tm[-1])} h" if tm and tm[0] and tm[-1] else "")
                   + f"; T3 {x.get('t3_label')}" + (f"; {str(x['occasion']).replace('_', ' ').lower()}" if x.get("occasion") not in (None, "SINGLE_DOSE") else ""))
    for x in ev_iv:
        trig = (x.get("trigger_text") or "").replace("DECLINE_FLATTENS", "flattens").replace("DECLINE_STEEPENS", "steepens").replace("NEITHER", "neither")
        out.append(f"  EV {x['ev']} vs IV {x['iv']} ({_g(x.get('dose_ev'))}/{_g(x.get('dose_iv'))} mg/kg): {trig}"
                   + (f"; finite-window dose-normalized AUC ratio over {_ratio_window_text(x)} = {_g(x.get('window_auc_ratio'))} ({x.get('f_status')}); neither absolute F nor a bound; " + _source_f_text(x)
                      if isinstance(x.get("window_auc_ratio"), (int, float)) else f"; ratio {x.get('f_status')}") + f"; T4 {x.get('t4_label')}")
    for x in conds:
        cs = [i["c"] for i in x.get("intervals") or [] if isinstance(i.get("c"), (int, float))]
        out.append(f"  condition {x['a']} vs {x['b']} ({', '.join(x.get('differing_attributes') or [])}): "
                   + (f"c(t) {_g(min(cs))}–{_g(max(cs))}; " if cs else "") + f"T5 {x.get('t5_label')}"
                   + ("; confounded" if x.get("confounded") else ""))
    return out


def _mc_reported(ps):
    out = []
    for p in ps:
        by = {}
        for r in p.get("params") or []:
            if isinstance(r.get("value"), (int, float)):
                by.setdefault(r.get("dose"), []).append(f"{MC_PARAM.get(r['param'], r['param'])} {_g(r['value'])}"
                                                      + (f"±{_g(r['dispersion'])}" if isinstance(r.get("dispersion"), (int, float)) else "")
                                                      + (f" {r['unit']}" if r.get("unit") else ""))
        t3 = ((p.get("analysis") or {}).get("t3") or {})
        out.append(f"  reported {p['card']['dataset_id']}: " + "; ".join(f"{_g(d)} mg/kg {', '.join(v)}" for d, v in sorted(by.items(), key=lambda kv: kv[0] or 0))
                   + (f" | T3 R {_g(t3.get('R'))} ({t3.get('t3_label')})" if t3.get("R") else ""))
    return out


def _mc_plain(b, ref=lambda q: f"Q{q['q']}"):
    """Shared rule 10: the plain readings first, so a reader (or a downstream model) gets the gist before the numbers."""
    rows = [f"  {ref(q)}: {COMMON.plain_text(q['plain'])}" for q in b.get("questions", []) if q.get("plain")]
    h = (b.get("hypothesis") or {}).get("plain")
    if h:
        rows.append(f"  Taken together: {COMMON.plain_text(h)}")
    return ["in plain words:"] + rows if rows else []


def _mc_study(st, b, sets, ps, ev_iv, conds, dser):
    h, F, br = b["hypothesis"], st["findings"], b["hypothesis"].get("brief") or {}
    cards = [d["card"] for d in sets] + [p["card"] for p in ps]
    doses = sorted({c["dose_mg_per_kg"] for c in cards if isinstance(c.get("dose_mg_per_kg"), (int, float))}
                   | {r["dose"] for p in ps for r in p.get("params") or [] if isinstance(r.get("dose"), (int, float))}
                   | {d for x in dser for d in x.get("doses") or []})
    routes = "/".join(sorted({c.get("route_detail") or c.get("route_class") or "?" for c in cards}))
    lv = "/".join(sorted({MC_LEVEL.get(c.get("record_level"), str(c.get("record_level")).lower()) for c in cards}))
    n = sorted({c["n_per_time"].split(" ")[0] for c in cards if str(c.get("n_per_time") or "")[:1].isdigit()})
    ids = [c["dataset_id"] for c in cards]
    out = [f"{st['study']} | {b.get('species_group') or ''} ({st['species']}) | {'/'.join(sorted({c.get('drug') for c in cards if c.get('drug')}))} "
           f"{routes} {','.join(_g(d) for d in doses)} mg/kg | {lv}{' n=' + '/'.join(n) if n else ''}"
           f"{' digitized' if any(c.get('digitized') for c in cards) else ''} | {', '.join(ids)}",
           "Q1-9: " + " ".join(MC_STATUS.get(q["status_code"], "?") for q in b["questions"])]
    out += _mc_plain(b)
    cur = _mc_curves(sets, ev_iv, conds, dser) + _mc_reported(ps)
    if cur:
        out += ["curves and comparisons:"] + cur
    sig = [f"  Q{s['q']} {'firm' if s['strength'] == SUG else 'hint'}: {s['short']} -> "
           + " | ".join("+".join(_mc_part(p) for p in e) for e in s["explained_by"][:4]) + (" ..." if len(s["explained_by"]) > 4 else "")
           for s in F["signals"]]
    sig += [f"  rule: {r['text']}" for r in F["rules"]]
    bd = F.get("bounds") or {}
    bits = ([f"tlag < {_g(bd['tlag_max_h'])} h"] if bd.get("tlag_max_h") is not None else []) + (
        [f"AUC window 0–{_g(bd['auc_window']['end_h'])} h" + (f" short (min share {bd['auc_window']['min_share']:.0%})" if bd["auc_window"].get("short") else "")]
        if bd.get("auc_window") else [])
    if bits:
        sig.append("  bounds: " + "; ".join(bits))
    if F.get("untestable"):
        by = {}
        for k, v in F["untestable"].items():
            by.setdefault(v, []).append(k)
        txt = []
        for why, ks in by.items():
            names = []
            for ax in HYP_ORDER:
                lv = [k for k in ks if k.startswith(ax + ".")]
                every = [f"{ax}.{x[0]}" for x in HYP_AXES[ax][1] if x[0] != HYP_DEFAULT[ax]]
                short = {f"{ax}.{x[0]}": x[4] for x in HYP_AXES[ax][1]}
                names += ([HYP_AXES[ax][0].lower()] if lv and set(every) <= set(lv) and len(every) > 1 else [short.get(k) or _mc_part(k) for k in lv])
            txt.append(f"{why}: {', '.join(names)}")
        sig.append("  untestable here: " + "; ".join(txt))
    out += (["findings:"] + sig) if sig else []
    out.append(f"hypothesis {h['id']} ({MC_STATE.get(h['state'], h['state'].lower())}) {h['combination']}:")
    if br.get("suspected") or br.get("less_firm"):
        out.append("  suspect: " + ("; ".join(br.get("suspected") or []) or "nothing firm")
                   + (" | less firm: " + "; ".join(br["less_firm"]) if br.get("less_firm") else ""))
    else:
        out.append("  reference: " + {"simplest": "first-order input", "reference": "single input; mechanism unresolved", "unreadable": "no readable curve"}.get(br.get("none"), "—"))
    if br.get("deferred"):
        out.append("  still possible: " + ", ".join(br["deferred"]))
    if br.get("either"):
        out.append("  equally possible: " + "; ".join(f"{u} instead of {i}" for u, i in br["either"]))
    if br.get("also_groups"):
        out.append("  also possible: " + "; ".join(" | ".join(us) + (f" instead of {i}" if i else " in addition") for i, us in br["also_groups"]))
    if br.get("unused"):
        out.append("  hints not taken up: " + "; ".join(br["unused"]))
    for step, model, added, show in h["primary"]["rows"]:
        model = model.replace("M0 + ", "").replace("M1 + ", "")
        out.append(f"  {step}: {model}" + ("" if step == "M0" else f" [{added}] must show: {show.rstrip('.')}"))
    if h.get("missing"):
        out.append("  missing: " + "; ".join(h["missing"]))
    if h.get("checks_before_modelling"):
        out.append("  check first: " + "; ".join(c["text"].rstrip(".") for c in h["checks_before_modelling"]) + ".")
    out.append("  fit: " + F["model"].rstrip("."))
    stb = h.get("stability") or {}
    if stb.get("checks"):
        out.append(f"  one sample left out: {stb['checks'] - len(stb['changed'])}/{stb['checks']} unchanged"
                   + "".join(f"; without {x['left_out']} -> {x['combination']}" for x in stb["changed"][:3]))
    fails = [c["check"] for c in h.get("checks") or [] if c["result"] != "PASS"]
    out.append("  checks: " + ("all 7 pass" if not fails else "FAIL " + ", ".join(fails)))
    if h.get("review") and (h["review"].get("opinion") or "").strip():
        out.append(f"  reviewer: {h['review']['opinion'].strip()}")
    return "\n".join(out)


def model_context(result, ctx):
    """Compact text for a downstream model: one block per study, codes and thresholds once at the top."""
    boards = {_board_key(b): b for b in result["status_boards"]}
    sets, ps = {}, {}
    for d in result["datasets"]:
        sets.setdefault(_study_key(d["card"]), []).append(d)
    for p in result.get("reported_parameters") or []:
        ps.setdefault(_study_key(p["card"]), []).append(p)
    st_of = {d["card"]["dataset_id"]: _study_key(d["card"]) for d in result["datasets"]}
    codes = ctx["studies"][0]["combinations"]["codes"] if ctx["studies"] else {}
    head = [f"ABSORPTION CONTEXT · EDA {result['version']} · hypotheses {ctx['version']}",
            f"Q status Y answerable, P partly, N not yet, - not applicable. Error bound ±{TOL:.0%}; AUC/D 0.80–1.25 kept; Cmax/D below 0.5 or above 2 "
            f"points to nonlinearity; slow input needs comparable dose and a corroborating shared-window slope (EV t½ ≥ {FLIP_RATIO:g}× IV); AUC window short below {SHARE_MIN:.0%} of a group's exposure.",
            "firm = a pattern points to it; hint = less firm; -> lists the cases that would explain a finding. A hypothesis is a suspicion for a model "
            "to verify, not a result.",
            "Code onset-shape-second-tail-dose-other: " + "; ".join(f"{ax} " + " ".join(f"{v}={k}" for k, v in m.items()) for ax, m in codes.items()) + ".",
            "Full detail: absorption/absorption.json, absorption/hypothesis_context.json (all 2112 combinations per study)."]
    blocks = []
    for st in ctx["studies"]:
        s = st.get("scope_id", st["study"])
        own = lambda xs, *ks: [x for x in xs if any(st_of.get(x.get(k)) == s for k in ks)]  # noqa: E731
        dser = [x for x in result.get("dose_series") or [] if any(st_of.get(i) == s for i in x.get("dataset_ids") or [])]
        blocks.append(_mc_study(st, boards[s], sets.get(s, []), ps.get(s, []), own(result.get("ev_iv") or [], "ev"),
                                own(result.get("conditions") or [], "a", "b"), dser))
    return "\n".join(head) + "\n\n" + "\n\n".join(blocks) + "\n"

def report_section(res, error=None):
    """Absorption in report.html, written in that report's own plain style."""
    h = ['<section id="absorption"><h2>Absorption: how does the drug enter the circulation?</h2>',
         '<p>How the drug gets into the blood after non-IV dosing: when it starts, how fast, whether there is a second rise or a long tail, '
         'and how much gets in.</p>']
    if error is not None or not res:
        h.append(f'<p><b>Not generated:</b> {_e(error)}. The reason is recorded in absorption/error.json.</p></section>')
        return "".join(h)
    scoped, parameters, _ = _by_study(res.get("datasets", []), res.get("reported_parameters", []), [])
    labels = _absorption_names(res["status_boards"], scoped, parameters)
    hs = [(b, b["hypothesis"]) for b in res["status_boards"] if b.get("hypothesis")]
    if not res["status_boards"]:   # rule 10: say plainly why there is nothing, instead of empty lists
        h.append(f'<p>{_e(_absorption_empty_reason(res).replace("No absorption figures: t", "T").replace("No absorption figures: ", ""))}</p></section>')
        return "".join(h)
    if hs:
        title, observation = _absorption_overview_paras(hs, scoped, labels, plain=True)[0][:2]
        h.append(f'<p><b>{_e(title)}.</b> {_e(observation)}</p>')
    h.append('<p><a href="absorption/index.html#hypotheses">Read the full findings</a></p><details><summary>Questions by experiment</summary><ul>')
    for b in res["status_boards"]:
        page = species_page_name(_board_species(b)[0])
        by = {}
        for q in b.get("questions", []):
            by.setdefault(q["status"], []).append(f'Q{q["q"]}')
        h.append(f'<li><a href="absorption/{_e(page)}#study-{_e(_slug(_board_key(b)))}">{_e(labels[_board_key(b)])}</a>: '
                 + "; ".join(f'{_e(s.lower())} {", ".join(by[s])}' for s in ST_ORDER if by.get(s))
                 + (f'; working hypothesis {_e(HYP_STATE[b["hypothesis"]["state"]][1].lower())}' if b.get("hypothesis") else "") + '</li>')
    pres = res.get("presentation", {})
    sp = "; ".join(f'<a href="absorption/{_e(x["page"])}">{_e(x["species"])}</a> ({len(x["studies"])} stud{"y" if len(x["studies"]) == 1 else "ies"})'
                   for x in pres.get("species", []))
    h.append('</ul></details><p>' + (f'<b>By species:</b> {sp}. ' if sp else "")
             + '<a href="absorption/index.html">Open the Absorption overview</a></p></section>')
    return "".join(h)


def _grid_end(text):
    """Position of the closing tag of the portal's category grid, or None."""
    i = text.find('<div class="categories">')
    if i < 0:
        return None
    depth = 0
    for m in re.finditer(r"<div\b|</div>", text[i:]):
        depth += 1 if m.group(0) != "</div>" else -1
        if depth == 0:
            return i + m.start()
    return None


def add_to_portal(root):
    """Add the Absorption card to the EDA review portal home (index.html and human_review.html) and point the
    Absorption page's navigation at the portal. Called by the portal build; never raises."""
    root = Path(root)
    try:
        page_path = root / "absorption" / "index.html"
        if not page_path.exists():
            return False
        res = json.loads((root / "absorption" / "absorption.json").read_text(encoding="utf-8"))
        pres = res.get("presentation", {})
        n = pres.get("figures", 0)
        card = section_card("ABSORPTION", "Absorption", "absorption", "How the drug gets into the blood after non-IV dosing: when it starts, "
                            "how fast, whether there is a second rise or a long tail, and how much gets in.", n, pres.get("thumbnails", []),
                            pres.get("species", []), _absorption_empty_reason(res))
        done = False
        for name in ("index.html", "human_review.html"):
            p = root / name
            if not p.exists():
                continue
            text = re.sub(r"<!--ABSORPTION-CARD-START-->.*?<!--ABSORPTION-CARD-END-->", "", p.read_text(encoding="utf-8"), flags=re.S)
            pos = _grid_end(text)
            if pos is None:
                continue
            p.write_text(text[:pos] + card + text[pos:], encoding="utf-8")
            done = True
        if done:  # point every Absorption page's navigation and dose-normalization links at the portal
            for pg in [page_path] + sorted((root / "absorption").glob("species-*.html")):
                s = re.sub(r"<!--ABS-NAV-->.*?<!--/ABS-NAV-->", lambda _: _portal_links(True), pg.read_text(encoding="utf-8"), flags=re.S)
                s = re.sub(r'<a class="dn-link" href="[^"]*" data-portal="([^"]+)"', r'<a class="dn-link" href="\1" data-portal="\1"', s)
                pg.write_text(s, encoding="utf-8")
        return done
    except Exception as exc:  # noqa: BLE001 - the portal must not fail because of this card
        try:
            (root / "absorption" / "portal_error.json").write_text(json.dumps({"error": repr(exc)}), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
        return False


def attach(root):
    """Build the Absorption category: absorption/index.html (portal style) and a short section in report.html.

    A failure here never stops the EDA run: the reason is written to ``absorption/error.json``
    and shown in the report instead.
    """
    root = Path(root)
    res, err = None, None
    try:
        res = build(root)
    except Exception as exc:  # noqa: BLE001 - recorded, shown, not swallowed silently
        err = exc
        (root / "absorption").mkdir(exist_ok=True)
        (root / "absorption" / "error.json").write_text(json.dumps({"error": repr(exc)}, ensure_ascii=False), encoding="utf-8")
    report = root / "report.html"
    body = report.read_text(encoding="utf-8") if report.exists() else '<html lang="en"><meta charset="utf-8"></html>'
    body = re.sub(r'<!--ABSORPTION-START-->.*?<!--ABSORPTION-END-->', '', body, flags=re.S)
    block = '<!--ABSORPTION-START-->' + COMMON.reader_text(report_section(res, err)) + '<!--ABSORPTION-END-->'
    anchor = '<section><h2>Review issues</h2>'
    if anchor in body:
        body = body.replace(anchor, block + anchor, 1)
    elif '</html>' in body:
        body = body.replace('</html>', block + '</html>', 1)
    else:
        body += block
    report.write_text(body, encoding="utf-8")
    add_to_portal(root)  # when the portal home already exists; otherwise the portal build adds the card
    return root / "absorption"


def main(argv=None):
    argv = argv or sys.argv[1:]
    root = Path(argv[0])
    if len(argv) > 1 and argv[1] == "--attach":
        attach(root)
    res = json.loads((root / "absorption" / "absorption.json").read_text(encoding="utf-8")) if (root / "absorption" / "absorption.json").exists() and len(argv) > 1 else build(root)
    print(json.dumps({"datasets": len(res["datasets"]), "dose_series": len(res["dose_series"]),
                      "ev_iv": len(res["ev_iv"]), "conditions": len(res["conditions"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
