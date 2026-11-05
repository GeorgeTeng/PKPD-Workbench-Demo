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

No fitting, smoothing, back-extrapolation, imputation or scientific release. Only the
descriptive regressions allowed by r4 A0.7 are computed. Every test result carries the
r4 A0.3 label; project-set tolerances make results SENSITIVITY_ONLY.
"""
from __future__ import annotations

import html
import itertools
import json
import math
import re
import sys
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402

from . import eda_absorption_curve as curve

from . import eda_absorption_comparisons as comparisons

VERSION = "EDA_ABSORPTION_R4_3"
TOL = 0.05            # project-set relative tolerance (digitization / unreported analytic error)
SPAN_MIN = 2.0        # project-set minimum span ratio for terminal windows (A0.7)
LATE_FIRST = 1 / 3    # LATE_FIRST_SAMPLE: first sample >= Tmax/3 (item 16)
SPLIT_UP, SPLIT_DOWN = 1.25, 0.80
TAIL_FLAG = 0.05
DOSE_TIME_ABS = 1e-3  # same-study dose series share digitized times exactly
PAIR_TIME_REL, PAIR_TIME_ABS = 0.05, 0.02  # EV/IV and condition pairs: matched within tolerance

# ---------------------------------------------------------------- data extraction


def _num(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _dose(entry):
    meta = entry.get("metadata", {})
    for field, text in (("title", entry.get("title", "")), ("dosing_regimen", meta.get("dosing_regimen", "")),
                        ("notes", entry.get("notes", "") or "")):
        m = re.search(r"(\d+(?:\.\d+)?)\s*mg/kg", str(text))
        if m:
            return float(m.group(1)), field
    return None, "NOT_FOUND"


def _status(raw_status):
    return curve.source_status(raw_status)


def extract(entry):
    """Return the dataset card and one series per concentration column."""
    meta = entry.get("metadata", {})
    cols = entry.get("columns", [])
    time_col = next((c["id"] for c in cols if c.get("meaning") == "TIME"), None)
    conc_cols = [c for c in cols if c.get("meaning") == "CONCENTRATION"]
    unit = conc_cols[0].get("unit") if conc_cols else "NOT_FOUND"
    record_category = meta.get("record_category", "NOT_FOUND")
    unit_text = entry.get("experimental_unit", "") or ""
    design_text = " ".join(str(x or "") for x in (unit_text, entry.get("notes"), meta.get("study_design")))
    identity_verified, destructive = curve.sampling_design(meta, design_text)
    if record_category == "INDIVIDUAL":
        level = "INDIVIDUAL" if identity_verified else "INDIVIDUAL_IDENTITY_UNVERIFIED"
    elif record_category == "GROUP_SUMMARY":
        level = "GROUP_MEAN"
    else:
        level = record_category or "NOT_FOUND"
    digitized = meta.get("observation_source") == "DIGITIZED_FROM_FIGURE"
    dose, dose_from = _dose(entry)
    regimen = str(meta.get("dosing_regimen", ""))
    single = bool(re.search(r"\bsingle\b", regimen, re.I)) and not re.search(r"repeat|multiple|steady.state", regimen, re.I)
    disp = _dispersion_columns(cols, conc_cols)
    sd_cols = [x for v in disp.values() for x in v.values() if x]
    notes_all = " ".join([str(entry.get("notes") or ""), entry.get("title", ""), unit_text])
    meta = dict(meta)
    matrix = str(meta.get("matrix","")).strip().lower()
    if matrix in {"plasma","balf"} and unit.lower()=="mg/l" and not _num(meta.get("lloq")):
        limit = re.search(r"\b(plasma/BALF|plasma|BALF)\s+(?:LLOQ|LOQ)\s*[:=]?\s*([\d.]+)\s*mg/L\b",notes_all,re.I)
        if limit and matrix in limit[1].lower().split("/"):
            meta.update(lloq=float(limit[2]),lloq_evidence=limit[0])
    n_col = next((c["id"] for c in cols if c.get("meaning") in ("N", "N_ANIMALS") or re.fullmatch(r"\s*n\s*(\(.*\))?\s*", str(c.get("header", "")).lower())), None)
    n_note = _n_from_notes(notes_all)
    digitization = curve.pixel_calibration(meta.get("source_table", {}).get("notes", "") if isinstance(meta.get("source_table"), dict) else "")
    series = []
    for c in conc_cols:
        dc = disp.get(c["id"], {})
        pts = []
        for r in entry.get("records", []):
            t = _num(r.get("time_h", r.get(time_col)))
            if t is None:
                continue
            raw_status = r.get("value_status", {}).get(c["id"])
            st = _status(raw_status)
            y = _num(r.get(c["id"])) if st in ("QUANTIFIED", "MEASURED_ZERO") else None
            sd, sd_note = _point_sd(r, dc, y)
            n = _num(r.get(n_col)) if n_col else None
            pt = curve.source_point(r, c, cols, meta, t, y, st, digitization)
            pt.update(sd=sd, sd_note=sd_note, n=int(n) if n is not None and n.is_integer() and n >= 1 else n_note)
            pts.append(pt)
        pts.sort(key=lambda p: p["t"])
        curve.mark_duplicates(pts)
        m = re.search(r"(\d+(?:\.\d+)?)\s*mg/kg", str(c.get("header", "")))
        series.append({"series_id": c["id"], "label": c.get("header", c["id"]), "points": pts,
                       "dose": float(m.group(1)) if m else None, "dispersion_kind": dc.get("kind")})
    series_doses = {s["dose"] for s in series if s["dose"] is not None}
    series_kind = "DOSE_COLUMNS" if len(conc_cols) > 1 and len(series_doses) == len(conc_cols) else (
        "INDIVIDUALS" if len(conc_cols) > 1 else "SINGLE")
    for s in series:
        if s["dose"] is None:
            s["dose"] = dose
    route_class = meta.get("route_class", "NOT_FOUND")
    route_detail = meta.get("route_detail", "NOT_FOUND")
    card = {
        "dataset_id": entry["dataset_id"], "title": entry.get("title", ""),
        "study": ",".join(entry.get("study_source_ids", [])) or "NOT_FOUND",
        "species": meta.get("species", "NOT_FOUND"), "drug": meta.get("drug", "NOT_FOUND"),
        "route_class": route_class, "route_detail": route_detail,
        "matrix": meta.get("matrix", "NOT_FOUND"), "matrix_category": meta.get("matrix_category", "NOT_FOUND"),
        "record_level": level, "digitized": digitized,
        "n_per_time": (f"{n_note} (source text)") if n_note else ("n column" if n_col else "point-specific n not established"),
        "dispersion": _disp_text(disp) if sd_cols else "not reported",
        "mean_type": _mean_type(notes_all) if level == "GROUP_MEAN" else "n/a",
        "series_kind": series_kind,
        "lloq": meta.get("lloq", "not reported"), "dose_mg_per_kg": dose, "dose_from": dose_from,
        "dose_basis": meta.get("dose_basis", "NOT_FOUND"), "dosing_regimen": regimen or "NOT_FOUND",
        "single_dose": single, "unit": unit,
        "error_bound": "See point bounds; ±5% exploratory concentration tolerance where source bounds are unavailable.",
        "identity_verified": "n/a" if level == "GROUP_MEAN" else ("yes" if identity_verified else "no"),
        "destructive_sampling": destructive,
        "analyte_role": meta.get("analyte_role", "not reported"), "origin": meta.get("origin", "not reported"),
        "dose_occasion": meta.get("dose_occasion", "single dose" if single else "not reported"),
        "error_bars_hidden": ("some bars hidden by the marker" if "inside the marker" in notes_all.lower() else "not reported") if digitized else "n/a",
        "data_form": "CURVE",
        "notes": (entry.get("notes") or "").strip(),
    }
    curve.enrich_card(card, meta, notes_all)
    card["lloq_evidence"] = meta.get("lloq_evidence")
    card["sampling_time_basis"] = "SOURCE_NOMINAL" if re.search(r"nominal times?",notes_all,re.I) else (
        "SOURCE_ACTUAL" if meta.get("actual_time_verified") is True else "AS_RECORDED")
    baselines = [curve.baseline(s["points"], card) for s in series] or [curve.baseline([], card)]
    for key in ("baseline_status", "dose_time_basis", "zero_anchor_allowed", "zero_state_supported"):
        values = {b[key] for b in baselines}
        card[key] = values.pop() if len(values) == 1 else (False if key.endswith(("allowed", "supported")) else "VARIES_BY_SERIES")
    gates = []
    if route_class != "EV":
        gates.append("NOT_EV")
    if card["matrix_category"] != "PLASMA_SERUM_BLOOD":
        gates.append("NOT_CENTRAL_MATRIX")
    if not single and not card["washout_supported"]:
        gates.append("NOT_SINGLE_DOSE")
    if route_detail in ("NOT_FOUND", "", None):
        gates.append("ROUTE_UNKNOWN")
    card["gates"] = gates
    if card["endogenous_review_required"]:
        gates.append("ENDOGENOUS_REVIEW_REQUIRED")
    card["tests_allowed"] = not gates
    # item 19 compares doses given at the same occasion; a repeated-dose occasion (e.g. day 2) is
    # allowed when every dose in the series shares it (steady-state and single-dose AUC are not mixed)
    card["dose_series_allowed"] = not ({"NOT_EV", "NOT_CENTRAL_MATRIX", "ROUTE_UNKNOWN", "ENDOGENOUS_REVIEW_REQUIRED"} & set(gates))
    card["occasion"] = "SINGLE_DOSE" if single else _occasion(notes_all + " " + regimen)
    return card, series


def _n_from_notes(text):
    """Accept an exact count explicitly applicable at each time; a range cannot supply one."""
    s = str(text or "").lower()
    counts = re.findall(r"(\d+)(?:\s*(?:or|-|–|to)\s*(\d+))?\s*(?:mice|rats|animals|rabbits)\s*(?:/|per)\s*time", s)
    values = {int(v) for pair in counts for v in pair if v}
    return values.pop() if len(values) == 1 else None


def _mean_type(text):
    s = str(text or "").lower()
    g, a = "geometric mean" in s, "arithmetic mean" in s
    if g and a:
        return "UNKNOWN (source conflict: caption says geometric, methods say arithmetic)"
    return "GEOMETRIC" if g else "ARITHMETIC" if a else "not reported"


def _occasion(text):
    m = re.search(r"day\s*(\d+)\s*of\s*treatment|on day\s*(\d+)", str(text).lower())
    return f"REPEATED_DOSE_DAY_{next(x for x in m.groups() if x)}" if m else "REPEATED_OR_UNKNOWN"


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


def _disp_text(disp):
    kinds = sorted({v["kind"] for v in disp.values()})
    return {"SD": "SD column", "SE": "SE column", "BAR_ENDS": "digitized error-bar ends; see source definition"}.get(kinds[0], kinds[0]) if len(kinds) == 1 else ", ".join(kinds)


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


# ---------------------------------------------------------------- per-curve calculations (r4 items 16-18, 20)


def auc(t, c):
    """A0.6: linear-up / log-down, observed points only."""
    a = 0.0
    for i in range(len(t) - 1):
        dt, c0, c1 = t[i + 1] - t[i], c[i], c[i + 1]
        a += dt * (c0 - c1) / math.log(c0 / c1) if (c0 > 0 and c1 > 0 and c1 < c0) else dt * (c0 + c1) / 2
    return a


def curve_metrics(points, level, card=None):
    """Single-profile quantities and their operation-specific evidence and support."""
    return curve.metrics(points, level, card or {}, auc, SPAN_MIN)


# ---------------------------------------------------------------- multi-curve tests (items 19, 18/22, 23)


def _common_times(curves, rel=0.0, absolute=DOSE_TIME_ABS):
    """Times present in every curve (within tolerance) and <= the earliest tlast."""
    base = curves[0]["_t"]; tl = min(c["tlast"] for c in curves)
    out = []
    for t in base:
        if t > tl + 1e-9:
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


def _window_auc(c, T):
    pts = c.get("_source_points", [{"t": t, "c": v, "status": "QUANTIFIED"} for t,v in zip(c["_t"],c["_c"])])
    result = comparisons.window([comparisons.grid(pts,c)], end=T)
    return result["areas"][0] if result["areas"] else None

def dose_series(members, dose_block):
    """Item 19. members: list of (card, metrics) with distinct doses."""
    members = sorted(members, key=lambda m: _mdose(m))
    curves = [m[1] for m in members]
    grids = [comparisons.grid(mem[2]["points"],mem[1]) for mem in members]
    win = comparisons.window(grids)
    if not win["areas"] or any(area <= 0 for area in win["areas"]):
        return {"status":"NOT_ASSESSABLE","reason":win.get("reason","No positive window AUC"),"observed_window":win}
    common = _common_times(curves, absolute=0.0)
    if not common:
        return {"status": "NOT_ASSESSABLE", "reason": "no sampling time shared by all doses"}
    T = win["end_h"]
    rows = []
    for mem, aw in zip(members, win["areas"]):
        card, m = mem[0], mem[1]
        d = _mdose(mem)
        own = m.get("auc_observed", m.get("auc_0_tlast"))
        th = m["terminal_selected"]["thalf"] if m["terminal_selected"] else None
        qths = [w["thalf"] for w in m["terminal_windows"] if w["thalf"] and w["span_ratio"] and w["span_ratio"] >= SPAN_MIN]
        rows.append({"dataset_id": card["dataset_id"], "series_id": mem[2]["series_id"] if len(mem) > 2 else None, "dose": d, "tmax": m["tmax"], "cmax_d": m["cmax"] / d,
                     "thalf": th, "thalf_range": [min(qths), max(qths)] if qths else None,
                     "aucW_d": aw / d, "auc_last_d": own / d if own else None, "share_window": aw / own if own else None,
                     "tail_share": m["tail_share"], "split_class": (m["split"] or {}).get("class")})
    lo, hi = rows[0], rows[-1]
    R = hi["aucW_d"] / lo["aucW_d"]
    cmax_ratio = hi["cmax_d"] / lo["cmax_d"]
    def contrast_band(value):
        return "NO_SIGN" if 0.80 <= value <= 1.25 else "POINTS_TO_NONLINEARITY" if value < .5 or value > 2 else "INCONCLUSIVE"
    e6 = contrast_band(R)
    cm = contrast_band(cmax_ratio)
    ranges = [r["thalf_range"] for r in rows if r["thalf_range"]]
    overlap = all(ranges[i][1] >= ranges[i + 1][0] for i in range(len(ranges) - 1)) if len(ranges) > 1 else None
    monotone_up = all(rows[i]["thalf"] and rows[i + 1]["thalf"] and rows[i + 1]["thalf"] > rows[i]["thalf"]
                      for i in range(len(rows) - 1))
    e2 = "POINTS_TO_NONLINEARITY" if (overlap is False and monotone_up) else "NO_SIGN" if overlap else "INCONCLUSIVE"
    # E1 per-time descriptive ratios, highest vs lowest
    per_time = []
    a, b = curves[0], curves[-1]
    for idx in common:
        ta = a["_t"][idx[0]]
        ca, cb = a["_c"][idx[0]] / lo["dose"], b["_c"][idx[-1]] / hi["dose"]
        mt3 = max(cb * (1 - TOL) - ca * (1 + TOL), ca * (1 - TOL) - cb * (1 + TOL))
        per_time.append({"t": ta, "ratio": cb / ca, "m_t3": mt3})
    # Report the effect of unequal internal sampling without interpolating.
    common_grids = [{t:g[t] for t in win["common_times_h"]} for g in grids]
    common_only = comparisons.window(common_grids)
    win["shared_grid_sensitivity"] = common_only
    win["shared_grid_R"] = ((common_only["areas"][-1]/hi["dose"])/(common_only["areas"][0]/lo["dose"])) if common_only["areas"] and common_only["areas"][0]>0 else None
    x = np.log([r["dose"] for r in rows])
    b1 = {"auc_window": float(np.polyfit(x, np.log([r["aucW_d"] * r["dose"] for r in rows]), 1)[0]),
          "auc_last": float(np.polyfit(x, np.log([r["auc_last_d"] * r["dose"] for r in rows]), 1)[0]) if all(r["auc_last_d"] for r in rows) else None,
          "cmax": float(np.polyfit(x, np.log([r["cmax_d"] * r["dose"] for r in rows]), 1)[0])} if len(rows)>=3 else None
    return {"status": "ASSESSED", "observed_window": win, "window_start_h": win["start_h"], "window_end_h": T, "doses": [r["dose"] for r in rows], "rows": rows,
            "R_window": R, "R_own_tlast": hi["auc_last_d"] / lo["auc_last_d"] if lo["auc_last_d"] and hi["auc_last_d"] else None, "e6_label": e6,
            "cmax_d_ratio": cmax_ratio, "cmax_label": cm, "e2_label": e2, "per_time": per_time, "b1": b1,
            "overlay_block": dose_block} | _t3_all(members, rows, common, T)


def _mdose(mem):
    return mem[2]["dose"] if len(mem) > 2 and mem[2].get("dose") else mem[0]["dose_mg_per_kg"]


def _t3_all(members, rows, common, T):
    # The hybrid AUC is nonlinear in falling concentrations. A linear-weight Bailer
    # variance is a different estimand. Retain the observed contrast independently.
    pts = [{p["t"]: p for p in mem[2]["points"]} for mem in members]
    return {"t3_label": "CANNOT_ASSESS", "t3_flags": ["SENSITIVITY_ONLY"],
            "t3_data_level":"GROUP_MEAN", "t3_reason":"No justified variance for the hybrid group-mean AUC and sampling design",
            "t3_reason_en":"Individual AUCs or a design-matched variance for the stated integration rule are required",
            "t3_primary_pair":[rows[0]["dose"],rows[-1]["dose"]],"t3p":t3p_series(members, rows, common, pts)}

def _bailer_input(pmap, T):
    ts = [t for t in sorted(pmap) if t <= T + 1e-9]
    return {"t": ts, "c": [pmap[t]["c"] for t in ts], "sd": [pmap[t]["sd"] for t in ts], "n": [pmap[t]["n"] for t in ts]}


ev_iv = comparisons.ev_iv
condition_pair = comparisons.condition_pair

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


def _l(v):
    return [float(x) for x in v]


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

    def band(self, xmin, xmax, color=ORANGE, alpha=0.12):
        return self.add("band", xmin=float(xmin), xmax=float(xmax), color=color, alpha=alpha)

    def area(self, x, y, color=BLUE, alpha=0.10):
        return self.add("area", x=_l(x), y=_l(y), color=color, alpha=alpha)

    def hline(self, y, color=MUTED, lty="solid", lw=0.5, label=None):
        return self.add("hline", y=float(y), color=color, lty=lty, lw=lw, label=label)

    def vline(self, x, color=MUTED, lty="solid", lw=0.5):
        return self.add("vline", x=float(x), color=color, lty=lty, lw=lw)

    def bars(self, x, y, color=BLUE):
        return self.add("bars", x=_l(x), y=_l(y), color=color)

    def text(self, x, y, label, hjust=0.0, vjust=1.0, size=3.0, color=INK2, npc=False):
        return self.add("text", x=float(x), y=float(y), label=str(label), hjust=hjust, vjust=vjust, size=size, color=color, npc=npc)

    def set(self, **kw):
        self.d.update(kw); return self


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
    path.write_text(json.dumps({"version": VERSION, "figures": specs}, ensure_ascii=False, default=float), encoding="utf-8")
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
                ax.axvspan(L["xmin"], L["xmax"], color=c, alpha=L["alpha"], lw=0)
            elif k == "area":
                ax.fill_between(L["x"], 0, L["y"], color=c, alpha=L["alpha"], lw=0)
            elif k == "hline":
                ax.axhline(L["y"], color=c, lw=L["lw"] * 2.2, ls="--" if L["lty"] == "dashed" else "-", label=L.get("label"))
            elif k == "vline":
                ax.axvline(L["x"], color=c, lw=L["lw"] * 2.2, ls="--" if L["lty"] == "dashed" else "-")
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
    scope = " · source label, serial identity unverified" if card["record_level"] == "INDIVIDUAL_IDENTITY_UNVERIFIED" else ""
    return f"{card['dataset_id']}{' · ' + series['label'] if series.get('label') else ''}{scope}"


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
    """Show the censoring threshold only where the source supplies its value."""
    blq = [b for b in series["points"] if b["status"] == "BLQ" and (tmax_x is None or b["t"] <= tmax_x + 1e-9)]
    if not blq:
        return
    bounded = [b for b in blq if (b.get("lloq") or 0) > 0]
    if bounded:
        p.points([b["t"] for b in bounded], [b["lloq"] for b in bounded], color=INK2, shape="open", label="BLQ at source LLOQ")
    unbounded = [b for b in blq if b not in bounded]
    if unbounded:
        p.text(0.02, 0.03, "BLQ, LLOQ unknown at " + ", ".join(f"{b['t']:.3g}" for b in unbounded) + " h", npc=True)


def _predose(series):
    return [x for x in series["points"] if x["status"] in ("QUANTIFIED", "MEASURED_ZERO") and x.get("c") is not None and x["t"] <= 0 and x.get("sample_phase") != "POSTDOSE"]


def _early_end(m):
    t, c = m["_t"], m["_c"]
    imax = int(np.argmax(c))
    return t[imax + 1] if imax + 1 < len(t) else t[imax]


def pA1(card, m, series, marks=("tmax", "delay", "zero", "blq", "predose"), whole=False, first=False, frac=False, title=None):
    """A1 linear concentration–time; default view the early window (0 to the first sample after Tmax)."""
    t, c = np.array(m["_t"]), np.array(m["_c"])
    tend = t[-1] if whole else _early_end(m)
    k = t <= tend + 1e-9
    p = Panel(title or f"{_tag(card, series)}: {'whole profile' if whole else 'early window'} (linear)",
              "Time after dose (h)", f"Concentration ({card['unit']})")
    p.vline(0, color=INK2)
    if card.get("known_finite_administration"):
        end = _num(card.get("administration_end"))
        if end is None and _num(card.get("administration_duration_h")) is not None:
            end = (_num(card.get("administration_start")) or 0) + _num(card["administration_duration_h"])
        if end is not None:
            p.vline(end, color=PURPLE, lty="dashed")
    if "delay" in marks and m["zero_state_supported"] and m["onset_status"] != "NOT_ASSESSABLE":
        p.band(0, m["first_t"], color=ORANGE, alpha=0.12)
        p.text(m["first_t"] / 2, m["cmax"] * 1.32, f"First quantified at {m['first_t']:.3g} h\nearlier onset unresolved", hjust=0.5, vjust=1, size=3.0)
    if "zero" in marks and m["dose_time_basis"] == "DESIGN_ZERO":
        p.points([0], [0], color=INK2, shape="diamond_open", size=2.8, label="design zero (not measured)")
    if "zero" in marks and m["dose_time_basis"] == "WASHOUT_ZERO":
        p.points([0], [0], color=INK2, shape="diamond_open", size=2.8, label="washout zero (assumed)")
    measured = [x for x in series["points"] if x["status"] == "MEASURED_ZERO" and 0 < x["t"] <= tend]
    if measured:
        p.points([x["t"] for x in measured], [0] * len(measured), color=BLUE, shape="square", label="measured zero")
    upper = [x for x in series["points"] if x["status"] == "ABOVE_ULOQ" and x["t"] <= tend and x.get("lo") is not None]
    if upper:
        p.points([x["t"] for x in upper], [x["lo"] for x in upper], color=PURPLE, shape="open", label="above ULOQ (lower bound)")
    if "delay" in marks and m.get("conditional_hard_lag_lower_bound_h"):
        lb = m["conditional_hard_lag_lower_bound_h"]
        p.vline(lb, color=PURPLE, lty="dashed")
        p.text(0.98, 0.97, f"Hard lag ≥ {lb:.3g} h conditional on a concave post-lag rise", hjust=1, npc=True)
    if card.get("endogenous_review_required") and _num(card.get("baseline_concentration")) is not None:
        p.hline(_num(card["baseline_concentration"]), color=PURPLE, label="source endogenous baseline")
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
        lab = "maximum quantified sample" if m.get("cmax_status") == "LOWER_BOUND_ONLY" else "observed Tmax"
        p.points([m["tmax"]], [m["cmax"]], color=ORANGE, shape="ring", size=5, stroke=1.4, label=f"{lab} at {m['tmax']:.3g} h")
    if frac:
        p.text(t[0], c[0] * 0.86, f"{100 * m['first_frac_cmax']:.0f} % of Cmax\nat {t[0]:.3g} h", hjust=0, vjust=1, size=2.8)
    lo = min([-0.05 * tend] + [x["t"] for x in pre])
    ymax = max([m["cmax"]] + [x["lo"] for x in upper] + [x["c"] for x in pre])
    p.set(xlim=[lo, tend * 1.08], ylim=[-0.04 * ymax, ymax * (1.4 if "delay" in marks else 1.18)],
          legend="bottom_right" if not whole else _free_corner(list(t) + [0], list(c) + [0]))
    return p


def pA2(card, m, series, title=None):
    """Plot exactly the full-profile C/t intervals and witness used by the search."""
    group = m["t1_points"]
    log = bool(group) and all(p["lo"] is not None and p["lo"] > 0 for p in group)
    b = Panel(title or f"{_tag(card, series)}: full-profile C/t intervals (T1)", "Time after dose (h)",
              f"C / t ({card['unit']} per h)", ylog=log)
    best = m["t1"]["best"]
    if not best:
        b.text(0.5, 0.5, "No eligible positive-time pair", npc=True, hjust=0.5)
        return b
    for p in group:
        low = p["lo"] / p["t_hi"] if p["lo"] is not None else None
        high = p["hi"] / p["t_lo"] if p["hi"] is not None else None
        if low is not None and high is not None:
            b.segments([p["t"]], [low], [p["t"]], [high], color=BLUE, lw=1.8)
        else:
            b.points([p["t"]], [low if low is not None else high], color=BLUE, shape="open", size=2.5)
        if p["c"] is not None:
            b.points([p["t"]], [p["c"] / p["t"]], color=INK, shape="dash", size=3)
    a, z = best["observations"]
    b.line([a["t"], z["t"]], [a["hi"] / a["t_lo"], z["lo"] / z["t_hi"]],
           color=ORANGE if best["margin"] > 0 else MUTED, lty="dashed", lw=0.7)
    b.text(0.02, 0.03, f"largest M_T1 = {best['margin']:.3g} ({a['t']:.3g} h vs {z['t']:.3g} h)\n{m['t1_label']}"
           + "".join(" + " + f for f in m["t1_flags"]), hjust=0, vjust=0, npc=True)
    return b


def _series_line(p, card, series):
    if card["record_level"] not in ("GROUP_MEAN", "INDIVIDUAL"):
        return
    for ok, run in itertools.groupby(series["points"], key=lambda x: x["status"] == "QUANTIFIED" and x["t"] > 0 and (x.get("c") or 0) > 0):
        data = list(run)
        if ok and len(data) >= 2:
            p.line([v["t"] for v in data], [v["c"] for v in data], color=MUTED, lw=0.35)


def _witness_bar(p, series, time, color):
    x = next((x for x in series["points"] if x["t"] == time), {})
    if x.get("lo") is not None and x.get("hi") is not None:
        p.segments([time], [x["lo"]], [time], [x["hi"]], color=color, lw=2.2)


def pA3(card, m, series):
    """A3 rising-limb increments ΔC/Δt (description only)."""
    inc = m["increments"]
    p = Panel(f"{_tag(card, series)}: rising-limb increments (description only)", "Interval before the peak", f"ΔC/Δt ({card['unit']} per h)")
    p.bars(list(range(1, len(inc) + 1)), [x["dcdt"] for x in inc], color=BLUE)
    p.set(xbreaks=list(range(1, len(inc) + 1)), xlabels=[f"{x['t0']:.2g}–{x['t1']:.2g} h" for x in inc])
    return p


def pA4(card, series_list):
    """A4 individual metrics: Tmax and Cmax/D per animal by dose (description)."""
    rows = [(s["label"], s.get("dose") or card.get("dose_mg_per_kg"), s["metrics"]) for s in series_list if "tmax" in s["metrics"]]
    doses = sorted({d for _, d, _ in rows if d})
    out = []
    for key, lab in (("tmax", "Tmax (h)"), ("cmax_d", f"Cmax/D ({card['unit']} per mg/kg)")):
        p = Panel(lab, "Dose (mg/kg)" if len(doses) > 1 else "Animal (source label)", "")
        if len(doses) > 1:
            xs = [d * (1 + 0.04 * ((k % 5) - 2)) for k, (_, d, _) in enumerate(rows)]
            p.set(xlog2=True, xbreaks=doses)
        else:
            xs = list(range(1, len(rows) + 1))
            p.set(xbreaks=xs, xlabels=[r[0] for r in rows])
        ys = [m["tmax"] if key == "tmax" else m["cmax"] / (d or 1) for _, d, m in rows]
        p.points(xs, ys, color=BLUE, size=2.8)
        out.append(p)
    return out


def pB1(card, m, series, marks=("blq", "terminal", "split", "dips"), valley=None, title=None, highlight_post=False):
    """B1 semilog, whole profile: terminal window, split halves, dip points."""
    t, c = np.array(m["_t"]), np.array(m["_c"])
    p = Panel(title or f"{_tag(card, series)}: whole profile (semi-log)", "Time after dose (h)", f"Concentration ({card['unit']})", ylog=True)
    _series_line(p, card, series)
    p.points(t, c, color=BLUE, size=2.6, label="quantified")
    if "blq" in marks:
        _blq_marks(p, card, series, m)
    imax = int(np.argmax(c))
    if highlight_post and imax + 1 < len(t):
        p.points(t[imax + 1:], c[imax + 1:], color=ORANGE, shape="ring", size=4.2, stroke=1.1, label="post-peak points searched for a dip")
    sel = m.get("terminal_selected")
    if "terminal" in marks and sel:
        xx = np.linspace(sel["start"], t[-1], 40)
        p.line(xx, np.exp(sel["intercept"] + sel["slope"] * xx), color=ORANGE, lw=1.1,
               label=f"terminal window: {sel['n']} pts from {sel['start']:.3g} h, apparent t½ {sel['thalf']:.3g} h")
    sp = m.get("split")
    if "split" in marks and sp and sp.get("ratio") is not None:
        first = True
        for (t0, t1), slope in ((sp["early_t"], sp["early_slope"]), (sp["late_t"], sp["late_slope"])):
            sel_t = [k for k in range(len(t)) if t0 - 1e-9 <= t[k] <= t1 + 1e-9]
            anchor = np.mean(np.log(c[sel_t])) - slope * np.mean(t[sel_t])
            xx = np.linspace(t0, t1, 20)
            p.line(xx, np.exp(anchor + slope * xx) * 1.35, color=INK2, lty="dashed", lw=0.6,
                   label=(f"split halves (shifted up): late/early slope {sp['ratio']:.2f} → {sp['class']}" if first else None))
            first = False
    if valley:
        a, b, cc = valley
        for k, col in ((a, BLUE), (b, ORANGE), (cc, BLUE)):
            _witness_bar(p, series, t[k], col)
        p.points([t[a], t[cc]], [c[a], c[cc]], color=BLUE, shape="ring", size=5, stroke=1.3, label=f"before and after the dip ({t[a]:.3g} h, {t[cc]:.3g} h)")
        p.points([t[b]], [c[b]], color=ORANGE, shape="ring", size=5, stroke=1.3, label=f"dip at {t[b]:.3g} h")
    elif "dips" in marks and m.get("_valley"):
        a, b, cc = m["_valley"]
        p.points([t[a], t[b], t[cc]], [c[a], c[b], c[cc]], color=ORANGE, shape="ring", size=4.6, stroke=1.2, label="dip and second rise")
    p.set(legend="bottom_left")
    return p


def pA1_dip(card, m, series, valley, title=None):
    """A1 whole profile (linear) with the dip and the points before and after it marked (question 4)."""
    t, c = np.array(m["_t"]), np.array(m["_c"])
    a, b, cc = valley
    p = Panel(title or f"{_tag(card, series)}: whole profile (linear)", "Time after dose (h)", f"Concentration ({card['unit']})")
    if m["dose_time_basis"] == "DESIGN_ZERO":
        p.points([0], [0], color=INK2, shape="diamond_open", size=2.8, label="design zero (not measured)")
    _series_line(p, card, series)
    p.points(t, c, color=BLUE, size=2.6, label="quantified")
    for k, col in ((a, BLUE), (b, ORANGE), (cc, BLUE)):
        _witness_bar(p, series, t[k], col)
    p.points([t[a], t[cc]], [c[a], c[cc]], color=BLUE, shape="ring", size=5, stroke=1.3, label=f"before and after the dip ({t[a]:.3g} h, {t[cc]:.3g} h)")
    p.points([t[b]], [c[b]], color=ORANGE, shape="ring", size=5, stroke=1.3, label=f"dip at {t[b]:.3g} h (stated bounds)")
    p.set(legend=_free_corner(list(t) + [0], list(c) + [0]))
    return p


def pT2(card, label, res, t2lab, flags):
    """B1, T2 layer (per animal): [L, U] of the three valley points, M_drop, M_rise, M_T2."""
    t, c = np.array(res["_t"]), np.array(res["_c"])
    p = Panel(f"{card['dataset_id']}{' · ' + label if label else ''}: dip test T2 (semi-log)", "Time after dose (h)", f"Concentration ({card['unit']})", ylog=True)
    p.line(t, c, color=MUTED, lw=0.4).points(t, c, color=MUTED, size=1.8)
    a, b, cc = res["valley_idx"]
    for k, col, obs in zip((a, b, cc), (BLUE, ORANGE, BLUE), res["best"]["observations"]):
        if obs["lo"] is not None and obs["hi"] is not None:
            p.segments([t[k]], [obs["lo"]], [t[k]], [obs["hi"]], color=col, lw=2.2)
        p.points([t[k]], [c[k]], color=col, shape="ring", size=5, stroke=1.3)
    p.text(t[b], c[b] * (1 - TOL) * 0.93, f"M_drop {res['m_drop']:.3g}\nM_rise {res['m_rise']:.3g}", hjust=0.5, vjust=1, size=2.8)
    rel = f" ({res['relative'] * 100:.0f} % of U_b)" if res.get("relative") is not None else ""
    p.text(0.98, 0.96, f"M_T2 = {res['t2_margin']:.3g}{rel}\n{t2lab}"
           + ("\nSINGLE_POINT_SUPPORT" if "SINGLE_POINT_SUPPORT" in flags else ""), hjust=1, npc=True)
    return p


def pB2(card, m, series):
    """B2 terminal-window sensitivity: apparent t½ of every qualified window, the selected one highlighted."""
    q = [w for w in m["terminal_windows"] if w["span_ratio"] and w["span_ratio"] >= SPAN_MIN and w["slope"] < 0]
    sel = m.get("terminal_selected") or {}
    p = Panel(f"{_tag(card, series)}: terminal-window sensitivity", "Window start (h)", "Apparent t½ (h)")
    p.points([w["start"] for w in q], [w["thalf"] for w in q], color=BLUE, size=2.8, label="qualified window")
    if sel:
        p.points([sel["start"]], [sel["thalf"]], color=ORANGE, shape="ring", size=5, stroke=1.4, label="longest within 0.0001 of best adj R²")
    p.set(legend="top_left")
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
            p = Panel(s["label"], "Time (h)", f"C ({unit})", ylog=log)
            p.points([x["t"] for x in q], [x["c"] for x in q], color=BLUE, size=2.0)
            if verified:
                p.line([x["t"] for x in q], [x["c"] for x in q], color=BLUE, lw=0.4)
            out.append(p)
        return out
    p = Panel(title or (f"{card['dataset_id']}: individuals ({'semi-log' if log else 'linear'})"
                        + ("" if verified else ", identity not verified")), "Time after dose (h)", f"Concentration ({unit})", ylog=log)
    for k, s in enumerate(series_list):
        q = _ind_points(s)
        if not q:
            continue
        tt = np.array([x["t"] for x in q]) * (1 if verified else 1 + 0.012 * (k - (len(series_list) - 1) / 2))
        cc = [x["c"] for x in q]
        col = cols[k % len(cols)]
        p.points(tt, cc, color=col, size=2.3, label=s["label"] + ("" if verified else " (as labelled in the source)"))
        if verified:
            p.line(tt, cc, color=col, lw=0.35, alpha=0.8)
        m = s.get("metrics") or {}
        if mark_first and m.get("first_t") is not None:
            p.points([tt[0]], [cc[0]], color=col, shape="ring", size=4.6, stroke=1.2)
        if mark_tmax and m.get("tmax") is not None:
            i = int(np.argmax(cc))
            p.points([tt[i]], [cc[i]], color=col, shape="ring", size=4.6, stroke=1.2)
    if verified:
        times = sorted({x["t"] for x in _ind_points(series_list[0])})
        mean = [(t, np.mean([x["c"] for s in series_list for x in _ind_points(s) if x["t"] == t]))
                for t in times if all(any(x["t"] == t for x in _ind_points(s)) for s in series_list)]
        if mean:
            p.line([x for x, _ in mean], [y for _, y in mean], color=INK, lw=1.4, label="mean (all animals quantified)")
    if mark_first:
        f = min((s["metrics"]["first_t"] for s in series_list if "first_t" in s.get("metrics", {})), default=None)
        if f:
            p.band(0, f, color=ORANGE, alpha=0.12)
    if early:  # 0 to the latest first sample after Tmax over the animals
        end = max(_early_end(s["metrics"]) for s in series_list if "tmax" in s.get("metrics", {}))
        p.set(xlim=[-0.04 * end, end * 1.06])
    p.set(legend="top_right" if not early else "bottom_right")
    return p


def pC1(r, members):
    """C1 C/D overlay: linear (0 to about 1.5 × the latest Tmax) and semi-log (whole profile); common window shaded."""
    ms = sorted(members, key=lambda x: x[0])
    T = r["window_end_h"]
    tmx = max(m["tmax"] for _, m, _ in ms)
    ramp = RAMP[-len(ms):] if len(ms) <= len(RAMP) else [RAMP[min(len(RAMP) - 1, int(k * len(RAMP) / len(ms)))] for k in range(len(ms))]
    out = []
    for log in (False, True):
        p = Panel(f"C/D {'semi-log, whole profile' if log else f'linear, 0–{1.5 * tmx:.2g} h'}", "Time after dose (h)", "C / Dose (per mg/kg)", ylog=log)
        if log or T < 1.5 * tmx:
            p.band(r["window_start_h"], T, color=ORANGE, alpha=0.08)
        for (dose, m, unit), col in zip(ms, ramp):
            t = np.array(m["_t"]); y = np.array(m["_c"]) / dose
            k = np.ones(len(t), bool) if log else t <= 1.5 * tmx + 1e-9
            p.line(t[k], y[k], color=col, lw=0.6).points(t[k], y[k], color=col, size=2.3, label=f"{dose:g} mg/kg")
        if not log:
            p.text(T / 2 if T < 1.5 * tmx else 0.75 * tmx, 0, f"common window {r['window_start_h']:g}–{T:g} h" + ("" if T < 1.5 * tmx else " (beyond this view)"),
                   hjust=0.5, vjust=0, size=2.7)
            p.set(xlim=[0, 1.5 * tmx * 1.02], legend="top_right")
        else:
            p.set(legend="none")
        out.append(p)
    return out


def pC2(r, t3=None):
    """C2 metrics by log2 dose: Cmax/D, apparent t½ (range + selected), AUC/D (common window; 0–tlast dashed);
    the T3 R with its CI against 1 when the T3 data exist."""
    rows = r["rows"]; d = [x["dose"] for x in rows]
    a = Panel(f"Cmax/D  ({r['cmax_label']})", "Dose (mg/kg)", "", xlog2=True).set(xbreaks=d)
    a.line(d, [x["cmax_d"] for x in rows], color=BLUE).points(d, [x["cmax_d"] for x in rows], color=BLUE)
    b = Panel(f"Apparent t½, h  ({r['e2_label']})", "Dose (mg/kg)", "", xlog2=True).set(xbreaks=d)
    rr = [x for x in rows if x["thalf_range"]]
    if rr:
        b.segments([x["dose"] for x in rr], [x["thalf_range"][0] for x in rr], [x["dose"] for x in rr], [x["thalf_range"][1] for x in rr],
                   color=MUTED, lw=3.5, label="range over qualified windows")
    th = [x for x in rows if x["thalf"]]
    if th:
        b.points([x["dose"] for x in th], [x["thalf"] for x in th], color=BLUE, label="selected window")
        b.set(legend="top_left")
    else:
        b.points(d, [0] * len(d), color=SURF, size=0.1)
        b.text(0.5, 0.5, "no qualified terminal window\n(span ratio < 2 or < 3 post-peak points)", hjust=0.5, vjust=0.5, npc=True)
        b.set(yticks=False)
    c = Panel(f"AUC/D  ({r['e6_label']}, R = {r['R_window']:.2f})", "Dose (mg/kg)", "", xlog2=True).set(xbreaks=d)
    c.line(d, [x["aucW_d"] for x in rows], color=BLUE, label=f"{r['window_start_h']:g}–{r['window_end_h']:g} h (common window)").points(d, [x["aucW_d"] for x in rows], color=BLUE)
    c.line(d, [x["auc_last_d"] for x in rows], color=MUTED, lty="dashed", label="own observed window (different coverage)").points(
        d, [x["auc_last_d"] for x in rows], color=MUTED)
    c.set(legend="top_left")
    out = [a, b, c]
    if t3 and t3.get("ci"):
        out.append(pT3(t3))
    return out


def pT3(t3):
    """T3: R of AUC/D with its CI against 1."""
    lo, hi = t3["ci"]
    win = f", 0–{t3['window_end_h']:g} h" if t3.get("window_end_h") else ""
    xlo, xhi = min(lo, 1) / 1.6, max(hi, 1) * 1.6
    a = Panel("T3: AUC/D ratio R with CI")
    a.set(xlab=f"R = (AUC/D) {t3['dose_pair'][1]:g} ÷ (AUC/D) {t3['dose_pair'][0]:g}{win}", xlog=True, yticks=False, ylim=[-1, 1.4], xlim=[xlo, xhi])
    a.vline(1, color=ORANGE, lty="dashed", lw=0.6)
    a.segments([lo], [0], [hi], [0], color=BLUE, lw=3)
    a.points([t3["R"]], [0], color=INK, size=3.4)
    right = -math.log(xlo) / (math.log(xhi) - math.log(xlo)) < 0.5  # keep the text clear of the R = 1 line
    a.text(0.98 if right else 0.02, 0.97, f"R = {t3['R']:.3g}, {t3['ci_level'] * 100:.0f} % CI [{lo:.3g}, {hi:.3g}]\n{t3['t3_label']}"
           + "".join(" + " + f for f in t3.get("t3_flags", [])) + f"\n{t3.get('t3_data_level', '')}", npc=True, size=2.9, hjust=1 if right else 0)
    return a


def pC3(r):
    """C3 per-time ln(C/D) ratio, highest over lowest dose: with T3p data 95 % CI and Holm marks; otherwise point ratios."""
    p3 = r.get("t3p") or {}
    if p3.get("t3p_times"):
        dl, dh = p3["t3p_dose_pair"]
        lab = p3["t3p_label"] + "".join(" + " + f for f in p3["t3p_flags"])
        b = Panel(f"Per-time ln ratio, 95 % CI (T3p): {lab}", "Time after dose (h)   (× = not tested)", f"ln[(C/D) {dh:g}] − ln[(C/D) {dl:g}]")
        b.hline(0, color=INK2, lw=0.5)
        rows = p3["t3p_ln_ratio_ci"]
        for want, col, shape, name in ((True, ORANGE, "circle", "significant after Holm"), (False, BLUE, "open", "not significant")):
            sel = [(x, ph) for x, s, ph in zip(rows, p3["significant"], p3["t3p_p_holm"]) if s == want]
            if not sel:
                b.points([], [], color=col, shape=shape, size=3, label=name, stroke=1.3)
                continue
            b.segments([x["t"] for x, _ in sel], [x["ci95"][0] for x, _ in sel], [x["t"] for x, _ in sel], [x["ci95"][1] for x, _ in sel], color=col, lw=2)
            b.points([x["t"] for x, _ in sel], [x["ln_ratio"] for x, _ in sel], color=col, shape=shape, size=3.2, label=name, stroke=1.3)
            for x, ph in sel:
                b.text(x["t"], x["ci95"][1], f"p_Holm {ph:.2g}", hjust=0.5, vjust=0, size=2.6)
        sk = p3.get("skipped", [])
        if sk:
            b.points([s["t"] for s in sk], [0] * len(sk), color=MUTED, shape="cross", size=2.4)
        b.set(legend="top")
        return b
    x = [q["t"] for q in r["per_time"]]; y = [q["ratio"] for q in r["per_time"]]
    p = Panel("Per-time C/D ratio (description, not a test)", "Common time (h)", f"(C/D) {r['doses'][-1]:g} ÷ (C/D) {r['doses'][0]:g}")
    p.hline(1, color=MUTED).line(x, y, color=BLUE, lw=0.6).points(x, y, color=BLUE)
    return p


def pD1(ev_card, ev, iv_card, iv, res):
    """D1 semilog dose-normalized EV and IV with terminal windows, and the T4 Q intervals."""
    a = Panel("EV vs IV, dose-normalized (semi-log)", "Time after dose (h)", "C / Dose", ylog=True)
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
        b = Panel("T4: Q = C_EV / C_IV must not decrease (shared one-compartment)", "Matched time (h)", "Q")
        tq = [x["t"] for x in res["q"]]
        b.segments(tq, [x["lo"] for x in res["q"]], tq, [x["hi"] for x in res["q"]], color=BLUE, lw=1.8)
        b.points(tq, [x["q"] for x in res["q"]], color=INK, shape="dash", size=3)
        b.text(0.98, 0.96, f"max M_T4 = {res['mt4']:.3g}\n{res['t4_label']}", hjust=1, npc=True)
        out.append(b)
    return out


def pD2(ev_card, ev, iv_card, iv, res):
    """D2 linear dose-normalized EV and IV, window area shaded (F window)."""
    T = res["window_h"]
    p = Panel(f"Observed exposure ratio, {res['window_start_h']:g}–{T:g} h", "Time after dose (h)", "C / Dose (linear)")
    ymax = max(max(ev["_c"]) / ev_card["dose_mg_per_kg"], max(iv["_c"]) / iv_card["dose_mg_per_kg"])
    for card, m, col, lty in ((ev_card, ev, BLUE, "solid"), (iv_card, iv, PURPLE, "dashed")):
        d = card["dose_mg_per_kg"]
        t = np.r_[0.0, m["_t"]] if m.get("zero_anchor_allowed") else np.array(m["_t"])
        y = (np.r_[0.0, m["_c"]] if m.get("zero_anchor_allowed") else np.array(m["_c"])) / d
        k = (t >= res["window_start_h"]) & (t <= T)
        p.area(t[k], y[k], color=col, alpha=0.10)
        p.line(t, y, color=col, lty=lty, lw=0.5).points(t, y, color=col, size=2.2, label=card["dataset_id"])
    p.vline(T, color=MUTED)
    p.text(T, ymax, f"  window {res['window_start_h']:g}–{T:g} h", hjust=0, size=2.9)
    p.set(legend="top_right")
    return p


def pE1(a_card, a, b_card, b, log=True):
    p = Panel(f"Condition overlay ({'semi-log' if log else 'linear'}; reference solid)", "Time after dose (h)", f"Concentration ({a_card['unit']})", ylog=log)
    for card, m, col, lty in ((b_card, b, INK2, "solid"), (a_card, a, GREEN, "dashed")):
        lab = f"{card['dataset_id']} {card['route_detail']} {_f(card.get('dose_mg_per_kg'))} mg/kg"
        p.line(m["_t"], m["_c"], color=col, lty=lty, lw=0.5).points(m["_t"], m["_c"], color=col, size=2.2, label=lab)
    p.set(legend="top_right")
    return p


def pE2(res):
    p2 = Panel("T5 sensitivity at paired sample times", "Matched time (h)", "c = C_A / C_ref")
    tt = [x["t"] for x in res["intervals"]]
    p2.segments(tt, [x["lo"] for x in res["intervals"]], tt, [x["hi"] for x in res["intervals"]], color=GREEN, lw=1.8)
    p2.points(tt, [x["c"] for x in res["intervals"]], color=INK, shape="dash", size=3)
    p2.hline(res["c_lower"], color=ORANGE, lty="dashed", lw=0.6, label=f"highest lower end {res['c_lower']:.2f}")
    p2.hline(res["c_upper"], color=PURPLE, lty="dashed", lw=0.6, label=f"lowest upper end {res['c_upper']:.2f}")
    p2.text(0.98, 0.96, res["t5_label"] + ("\n(highest lower > lowest upper: no common c in this scenario)" if res["c_lower"] > res["c_upper"] else "\n(a common c in this scenario)"),
            hjust=1, npc=True)
    ends = [x["lo"] for x in res["intervals"]] + [x["hi"] for x in res["intervals"]] + [res["c_lower"], res["c_upper"]]
    lo, hi = min(ends), max(ends)
    pad = (hi - lo) or abs(hi) or 1.0
    p2.set(legend="bottom_left", ylim=[lo - 0.42 * pad, hi + 0.42 * pad])  # room for the label (top) and the legend (bottom)
    return p2


def pE3(a_card, a, b_card, b, window):
    """E3 shape-normalized overlay: each curve divided by its own window AUC (common window = last matched time)."""
    pairs = _common_times([a, b], rel=PAIR_TIME_REL, absolute=PAIR_TIME_ABS)
    p = Panel("Shape-normalized overlay (description only)", "Time after dose (h)", "C / AUC_window (1/h)")
    for card, m, col, lty, idx in ((b_card, b, INK2, "solid", 1), (a_card, a, GREEN, "dashed", 0)):
        T = window["end_h"]
        y = np.array(m["_c"]) / window["areas"][idx]
        p.line(m["_t"], y, color=col, lty=lty, lw=0.5).points(m["_t"], y, color=col, size=2.2, label=f"{card['dataset_id']} (÷ AUC{window['start_h']:.3g}–{T:.3g} h)")
    p.set(legend="top_right")
    return p


_PNAME = {"CMAX": "Cmax/D", "AUC": "AUC/D", "TMAX": "Tmax", "THALF": "t½", "CL_F": "CL/F", "F": "F"}


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
        pan = Panel(_PNAME[name] + (f" ({unit}{' per mg/kg' if norm else ''})" if unit and unit != "NOT_FOUND" else ""), "Dose (mg/kg)", "", xlog2=len(d) > 1)
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


def _wrap(text, n):
    import textwrap
    return textwrap.wrap(text, n) or [""]


def t2_curve(points, card=None, level=None):
    return curve.t2_result(points, card, level)


def t2_label(res, level):
    return res["formal_status"], res["flags"]


# ---------------------------------------------------------------- t quantile without scipy

def _t_cdf(x, df):
    from scipy.special import stdtr
    return float(stdtr(df,x))


def t_ppf(p, df):
    lo, hi = 0.0, 1e3
    for _ in range(200):
        mid = (lo + hi) / 2
        if _t_cdf(mid, df) < p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


# ---------------------------------------------------------------- T3 paths (A0.10, A0.12)

def t3_group_sd(lo, hi, level=0.95, sensitivity=False):
    """A0.12: parallel groups with AUC mean, between-animal SD and n per dose. Log-ratio CI with
    delta-method SE = CV/sqrt(n) and Welch-Satterthwaite df."""
    R = (hi["auc"] / hi["dose"]) / (lo["auc"] / lo["dose"])
    s1, s2 = (hi["sd"] / hi["auc"]) ** 2 / hi["n"], (lo["sd"] / lo["auc"]) ** 2 / lo["n"]
    se = math.sqrt(s1 + s2)
    df = (s1 + s2) ** 2 / (s1 ** 2 / (hi["n"] - 1) + s2 ** 2 / (lo["n"] - 1))
    tq = t_ppf(1 - (1 - level) / 2, df)
    ci = (R * math.exp(-tq * se), R * math.exp(tq * se))
    label = "EXCLUDED_UNDER_STATED_ASSUMPTIONS" if (ci[0] > 1 or ci[1] < 1) else "NOT_EXCLUDED"
    return {"R": R, "ci": ci, "ci_level": level, "df": df, "method": "log ratio, delta SE, Welch df",
        "t3_data_level": "GROUP_SUMMARY_SD", "t3_label": "CANNOT_ASSESS" if sensitivity else label, "statistical_direction":label, "t3_flags": ["SENSITIVITY_ONLY"] if sensitivity else [],
            "dose_pair": [lo["dose"], hi["dose"]]}


def bailer_auc(t, c, sd, n, T):
    """Bailer 1988: AUC(0,T) of the mean curve with design zero; Var = sum w_i^2 s_i^2 / n_i."""
    tt = [0.0] + [x for x in t if x <= T + 1e-9]
    k = len(tt) - 1
    w = [0.0] * (k + 1)
    for i in range(k):
        dt = tt[i + 1] - tt[i]
        w[i] += dt / 2; w[i + 1] += dt / 2
    cc = [0.0] + c[:k]; ss = [0.0] + sd[:k]; nn = [1] + n[:k]
    a = sum(w[i] * cc[i] for i in range(k + 1))
    v = sum(w[i] ** 2 * ss[i] ** 2 / nn[i] for i in range(1, k + 1))
    return a, v


def t3_bailer(lo, hi, T, level=0.95):
    a1, v1 = bailer_auc(lo["t"], lo["c"], lo["sd"], lo["n"], T)
    a2, v2 = bailer_auc(hi["t"], hi["c"], hi["sd"], hi["n"], T)
    R = (a2 / hi["dose"]) / (a1 / lo["dose"])
    se = math.sqrt(v1 / a1 ** 2 + v2 / a2 ** 2)
    z = 1.959963984540054
    ci = (R * math.exp(-z * se), R * math.exp(z * se))
    label = "EXCLUDED_UNDER_STATED_ASSUMPTIONS" if (ci[0] > 1 or ci[1] < 1) else "NOT_EXCLUDED"
    return {"R": R, "ci": ci, "ci_level": level, "method": "Bailer 1988 sparse-sampling AUC, linear trapezoid, normal log-ratio CI",
            "t3_data_level": "DESTRUCTIVE_SAMPLING_SD", "t3_label": label, "t3_flags": [], "dose_pair": [lo["dose"], hi["dose"]],
            "window_end_h": T}


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
    m = re.match(r"^\s*([-+]?\d+(?:\.\d+)?)\s*(?:±|\+/-|\+-)\s*(\d+(?:\.\d+)?)", txt)
    if m:
        return float(m.group(1)), float(m.group(2))
    m = re.match(r"^\s*([-+]?\d+(?:\.\d+)?)\s*$", txt)
    return (float(m.group(1)), _num(disp)) if m else (None, None)


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
    measure_col = next((c["id"] for c in cols if re.search(r"measure|parameter", str(c.get("header", "")).lower())), None)
    value_cols = [c for c in cols if c.get("meaning") == "PARAMETER_VALUE"]
    disp_col = next((c["id"] for c in cols if c.get("meaning") in ("SUMMARY_STATISTIC", "SD", "SE", "DISPERSION")), None)
    stated_dose = {str(n) for n in re.findall(r"(\d+(?:\.\d+)?)\s*mg/kg",notes+" "+str(entry.get("metadata",{}).get("dosing_regimen","")))}
    dose_meta=entry.get("metadata",{}).get("dose") or {}
    homogeneous_dose = (card["dose_mg_per_kg"] if len(stated_dose)<=1 and not re.search(r"\d\s*[–‐-]\s*\d|dose groups|doses ranging|four groups",notes,re.I)
                        and (not isinstance(dose_meta,dict) or dose_meta.get("status") not in {"SOURCE_REPORTED_APPLICABILITY_UNRESOLVED","NOT_FOUND"}) else None)
    explicit_disp = next((c for c in cols if c["id"]==disp_col),{})
    column_type = _dispersion_type(str(explicit_disp.get("header",""))+" "+str(explicit_disp.get("meaning","")))
    if column_type!="UNKNOWN":
        disp_type=column_type
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
                           "dose": _num(r.get(dose_col)) if dose_col else homogeneous_dose, "record_id": r.get("record_id")})
        else:                             # wide layout: one row per dose, one column per parameter
            dose = _num(r.get(dose_col)) if dose_col else homogeneous_dose
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
        p["sd_kind"] = "MODEL_SE" if model_se and disp_type == "SE" else "BETWEEN_ANIMAL_SD" if disp_type=="SD" and re.search(r"between[- ]animal|interindividual",notes,re.I) else "SOURCE_SD" if disp_type=="SD" else "UNKNOWN"
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
        if all(p["value"]>0 and p["dispersion"] is not None and p["dispersion"]>0 and p["n"] and p["n"]>1 and p["dispersion_type"]=="SD" for p in (lo,hi)) and not any("interval not stated" in v for v in defs):
            sens = str(card.get("study_design","")).upper() not in {"PARALLEL","INDEPENDENT_PARALLEL"} or card.get("superposition_premises_supported") is not True or any(p["sd_kind"] != "BETWEEN_ANIMAL_SD" for p in (lo, hi)) or any(p.get("n_from") for p in (lo, hi))
            res["t3"] = t3_group_sd({"auc": lo["value"], "sd": lo["dispersion"], "n": lo["n"], "dose": lo["dose"]},
                                    {"auc": hi["value"], "sd": hi["dispersion"], "n": hi["n"], "dose": hi["dose"]}, sensitivity=sens)
            if sens:
                res["t3"]["sensitivity_reason"] = "SD type uncertain (may be a model SE or derived from the mean curve), or n taken from animals per time point"
        else:
            res["t3_reason"] = "AUC lacks SD or n: description only (E5)"
    fs = [p for p in params if p["param"] == "F"]
    if fs:
        f = fs[0]["value"]; unit = str(fs[0].get("unit","")).lower(); f = f / 100 if unit in {"%","percent","percentage"} else f
        flags = ["F_ABOVE_ONE"] if f > 1.0 else []
        ivd = [r for r in iv_refs if r.get("dose")]
        checks = {"same_study_iv": [r["dataset_id"] for r in iv_refs] or "no same-study IV"}
        if ivd and card["dose_mg_per_kg"] and any(abs(r["dose"] - card["dose_mg_per_kg"]) > 1e-9 for r in ivd):
            flags.append("DOSE_MISMATCH")
            flags.append("NONLINEAR_DOSE_MISMATCH" if linearity == "POINTS_TO_NONLINEARITY" else "LINEARITY_UNTESTED")
            checks["doses"] = f"EV {_f(card.get('dose_mg_per_kg'))} mg/kg, IV " + ", ".join(f"{r['dose']:g}" for r in ivd) + " mg/kg"
        bases = {str(r.get("dose_basis")) for r in ivd} | {str(card["dose_basis"])}
        checks["dose_basis"] = "consistent" if len(bases) == 1 and "NOT_FOUND" not in bases else "not confirmed (" + ", ".join(sorted(bases)) + ")"
        res["f"] = {"f_status": "SOURCE_REPORTED", "value": f, "flags": flags, "checks": checks,
                    "definition": fs[0]["definition"]}
    return res


# ---------------------------------------------------------------- T3p: per-time ln ratios with Holm (A0.10, r4.1)

T3P_TIME_DEV = 0.10   # a tested time point needs |t_H - t_L| <= 10 % of t
T3P_ALPHA = 0.05


def _p_two_sided(tstat, df):
    return max(0.0, min(1.0, 2 * (1 - _t_cdf(abs(tstat), df))))


def holm(ps):
    """Holm step-down adjusted p values (valid under any dependence between time points)."""
    m = len(ps)
    order = sorted(range(m), key=lambda i: ps[i])
    adj, run = [None] * m, 0.0
    for rank, i in enumerate(order):
        run = max(run, min(1.0, (m - rank) * ps[i]))
        adj[i] = run
    return adj


def _tp_summary(h, l, dh, dl, widen=0.0):
    """d(t) = ln(m_H/D_H) - ln(m_L/D_L); SE = sqrt(CV_H^2/n_H + CV_L^2/n_L); Welch-Satterthwaite df.
    widen > 0 moves both means towards each other and inflates both SDs (BORDERLINE check)."""
    mh, ml, sh, sl = h["c"], l["c"], h["sd"], l["sd"]
    if widen:
        up = math.log(mh / dh) > math.log(ml / dl)
        mh, ml = (mh * (1 - widen), ml * (1 + widen)) if up else (mh * (1 + widen), ml * (1 - widen))
        sh, sl = sh * (1 + widen), sl * (1 + widen)
    d = math.log(mh / dh) - math.log(ml / dl)
    vh, vl = (sh / mh) ** 2 / h["n"], (sl / ml) ** 2 / l["n"]
    se = math.sqrt(vh + vl)
    df = (vh + vl) ** 2 / (vh ** 2 / (h["n"] - 1) + vl ** 2 / (l["n"] - 1))
    tq = t_ppf(1 - T3P_ALPHA / 2, df)
    return {"d": d, "se": se, "df": df, "ci": [d - tq * se, d + tq * se], "p": _p_two_sided(d / se, df)}


def _testable(p):
    return p["status"] == "QUANTIFIED" and p["c"] and p.get("sd") is not None and p["sd"] > 0 and (p.get("n") or 0) >= 2


def t3p_series(members, rows, common, pts):
    """Pre-specified pair: the lowest and the highest dose that have SD and n at a shared time
    (chosen from data availability only, before any ratio is seen); tested times: every shared
    nominal time with SD and n >= 2 at both doses."""
    res = {"t3p_label": "CANNOT_ASSESS", "t3p_flags": [], "t3p_data_level": None, "t3p_dose_pair": None,
           "t3p_times": [], "t3p_ln_ratio_ci": [], "t3p_p_holm": [], "skipped": []}
    if not any(p.get("sd") is not None for d in pts for p in d.values()):
        res["reason"] = "no SD or n at the concentration points"; return res
    order = range(len(members))
    pairs = [(0,len(members)-1)]  # fixed highest/lowest dose pair, including when data are missing
    first_skipped = None
    for i, j in pairs:
        tested, skipped = [], []
        for tl in sorted(pts[i]):
            if not pts[j]:
                break
            th = min(pts[j], key=lambda x: abs(x - tl))
            pl, ph = pts[i][tl], pts[j][th]
            why = None
            if th != tl or tl <= 0:
                why = "no matching sampling time at the other dose"
            elif "BLQ" in (pl["status"], ph["status"]) or not pl["c"] or not ph["c"]:
                why = "BLQ or read as 0"
            elif not pl.get("sd") or not ph.get("sd"):
                why = (pl.get("sd_note") or ph.get("sd_note") or "no SD")
            elif min(pl.get("n") or 0, ph.get("n") or 0) < 2:
                why = "n < 2 or not reported"
            if why:
                skipped.append({"t": tl, "reason": why})
            else:
                tested.append((tl, pl, ph))
        if first_skipped is None:
            first_skipped = skipped
        if tested:
            break
    else:
        res["reason"] = "no dose pair has SD and n ≥ 2 at a shared time point"
        res["skipped"] = first_skipped or []
        return res
    dl, dh = rows[i]["dose"], rows[j]["dose"]
    stats = [_tp_summary(ph, pl, dh, dl) for _, pl, ph in tested]
    p_holm = holm([x["p"] for x in stats])
    sig = [p < T3P_ALPHA for p in p_holm]
    card = members[0][0]
    flags = []
    if any(m[0].get("mean_type") != "ARITHMETIC" or str(m[0].get("study_design","")).upper() not in {"PARALLEL","INDEPENDENT_PARALLEL","DESTRUCTIVE_PARALLEL"} or m[0].get("superposition_premises_supported") is not True for m in members):
        flags.append("SENSITIVITY_ONLY")   # geometric means with arithmetic-type SD, or mean type unclear
    if any(p[1].get("sd_note") or p[2].get("sd_note") for p in tested) and "SENSITIVITY_ONLY" not in flags:
        flags.append("SENSITIVITY_ONLY")
    label = "NOT_EXCLUDED"
    if any(sig):
        label = "EXCLUDED_UNDER_STATED_ASSUMPTIONS"
        # deleted unit = tested time point: redo Holm on the remaining points
        for k in range(len(tested)):
            rest = [x["p"] for n_, x in enumerate(stats) if n_ != k]
            if not rest:
                flags.append("REMOVAL_NOT_ASSESSABLE"); label = "CANNOT_ASSESS"; break
            if not any(p < T3P_ALPHA for p in holm(rest)):
                label = "NOT_EXCLUDED"; flags.append("SINGLE_POINT_SUPPORT"); break
        if label.startswith("EXCLUDED") and card["digitized"]:
            wide = holm([_tp_summary(ph, pl, dh, dl, widen=TOL)["p"] for _, pl, ph in tested])
            if not any(p < T3P_ALPHA for p in wide):
                flags.append("BORDERLINE")
    res.update({"t3p_numerical_result": label, "t3p_estimand": "log ratio of independent arithmetic group means, conditional on design", "t3p_role":"supplementary Holm family", "t3p_label": "CANNOT_ASSESS" if "SENSITIVITY_ONLY" in flags else "NOT_EXCLUDED" if "BORDERLINE" in flags else label, "t3p_flags": flags, "t3p_data_level": "GROUP_SUMMARY_SD",
                "t3p_dose_pair": [dl, dh], "t3p_times": [t for t, _, _ in tested],
                "t3p_ln_ratio_ci": [{"t": t, "ln_ratio": x["d"], "ci95": x["ci"], "se": x["se"], "df": x["df"], "p_raw": x["p"]}
                                    for (t, _, _), x in zip(tested, stats)],
                "t3p_p_holm": p_holm, "significant": sig, "skipped": skipped,
                "method": "d(t) = ln(m_H/D_H) − ln(m_L/D_L); SE = √(CV_H²/n_H + CV_L²/n_L); Welch–Satterthwaite df; Holm, two-sided family-wise 5 %",
                "pair_rule": "highest and lowest doses; exact positive common times with SD and n ≥ 2; other doses do not replace this contrast"})
    return res


# ---------------------------------------------------------------- orchestration

QUESTIONS = [
    (1, "Onset and delay", "When does drug start reaching the circulation; is there evidence of delayed onset?"),
    (2, "Input speed", "Is input fast or slow, concentrated or prolonged; can an absorption rate be estimated?"),
    (3, "Excluded input + disposition", "Which complete input + disposition combinations are incompatible with the data?"),
    (4, "Re-rise", "Is there a re-rise that a unimodal model cannot explain?"),
    (5, "Long tail / flip-flop", "Could slow absorption control the tail; can the EV half-life be read as disposition?"),
    (6, "Extent (F)", "How much drug reaches the circulation; can F be estimated?"),
    (7, "Dose dependence", "Does absorption-related behaviour change with dose?"),
    (8, "Condition effects", "Does a condition (route, formulation, food, co-medication, occasion) change rate, extent or disposition?"),
    (9, "Shared vs averaging", "Is the absorption shape shared by individuals, or produced by averaging?"),
]


def _study_key(card):
    return card["study"]


def build(root):
    root = Path(root)
    _SPECS.clear()
    tables = json.loads((root / "source_tables.json").read_text(encoding="utf-8-sig"))
    dose_report = {}
    p = root / "dose_normalization_assessment.json"
    if p.exists():
        dose_report = json.loads(p.read_text(encoding="utf-8-sig"))
    out = root / "absorption"
    out.mkdir(exist_ok=True)
    datasets, ivs = [], []
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
                                      "dose": pc["dose_mg_per_kg"], "dose_basis": pc["dose_basis"], "params": pp})
            continue
        if entry.get("role") != "PK_OBSERVATIONS":
            continue
        card, series = extract(entry)
        if not series:
            continue
        if card["route_class"] == "IV":
            ser = series[0] if len(series) == 1 else None
            if ser and card["matrix_category"] == "PLASMA_SERUM_BLOOD":
                ivs.append({"card": card, "metrics": curve_metrics(ser["points"], card["record_level"], card), "points": ser["points"]})
                iv_param_refs.append({"dataset_id": card["dataset_id"], "study": card["study"], "species": card["species"],
                                      "dose": card["dose_mg_per_kg"], "dose_basis": card["dose_basis"], "params": []})
            continue
        if card["route_class"] != "EV":
            continue
        ds = {"card": card, "series": [], "figures": {}}
        for s in series:
            m = curve_metrics(s["points"], card["record_level"], card)
            ds["series"].append({"series_id": s["series_id"], "label": s["label"], "metrics": m, "points": s["points"],
                                 "dose": s["dose"], "dispersion_kind": s["dispersion_kind"]})
        datasets.append(ds)

    def one(name, panel, w=5.6, h=3.7):
        return _figure(out, name, "", [panel], w, h)

    # T2 first (item 20): the test runs whenever its data precondition holds; a confirmed valley marks the dip on B1,
    # and the T2 layer is drawn per animal (T2 does not apply to group means)
    for ds in datasets:
        card = ds["card"]
        for s in ds["series"]:
            r = t2_curve(s["points"], card, card["record_level"])
            lab, flags = t2_label(r, card["record_level"])
            s["t2"] = {k: v for k, v in r.items() if not k.startswith("_")} | {"t2_label": lab, "t2_flags": flags,
                                                                                "trigger": bool(r["valley"])}
            if r["valley_idx"]:
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
            src = {"series_id": s["series_id"], "points": s["points"], "label": s["label"] if len(main) > 1 else ""}
            tag = f"{cid}_{_sid(s)}"
            if card["tests_allowed"]:
                s["A1"] = one(f"A1_{tag}.png", pA1(card, m, src))
                s["A1w"] = one(f"A1w_{tag}.png", pA1(card, m, src, marks=("tmax", "zero", "blq", "predose"), whole=True))
                if m["t1"]["eligible_count"]:
                    s["A2"] = one(f"A2_{tag}.png", pA2(card, m, src))
                s["B1"] = one(f"B1_{tag}.png", pB1(card, m, src), 6.0, 3.8)
                if m["n_before_peak"] >= 2:
                    s["A3"] = one(f"A3_{tag}.png", pA3(card, m, src), 5.6, 3.4)
                if len([w for w in m["terminal_windows"] if w["span_ratio"] and w["span_ratio"] >= SPAN_MIN and w["slope"] < 0]) >= 2:
                    s["B2"] = one(f"B2_{tag}.png", pB2(card, m, src), 5.6, 3.4)
                if s.get("_t2res") and s["t2"]["test_executed"]:
                    s["T2"] = one(f"T2_{tag}.png", pT2(card, src["label"], s["_t2res"], s["t2"]["t2_label"], s["t2"]["t2_flags"]), 6.0, 3.8)
            elif card["series_kind"] == "DOSE_COLUMNS" or s is main[0]:
                s["A1w"] = one(f"A1w_{tag}.png", pA1(card, m, src, marks=("tmax", "zero", "blq", "predose"), whole=True))
                s["B1"] = one(f"B1_{tag}.png", pB1(card, m, src, marks=("blq",)), 6.0, 3.8)
        if card["series_kind"] == "INDIVIDUALS":
            sl = [s for s in main if "tmax" in s["metrics"]]
            if sl:
                for key, log in (("A1ind", False), ("B1ind", True)):
                    p = pInd(card, sl, verified, log=log)
                    if isinstance(p, list):
                        rows_n = -(-len(p) // 4)
                        ds[key] = _figure(out, f"{key}_{cid}.png", "", p, 12, 2.5 * rows_n + 0.2, ncol=4)
                    else:
                        ds[key] = one(f"{key}_{cid}.png", p, 6.4, 3.9)
            if len(sl) > 1 and verified:
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
                groups.setdefault((c["study"], c["species"], c["route_detail"], c["matrix_category"], c["record_level"], c["occasion"]), []).append((ds, s))
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
        res["key"] = "_".join(re.sub(r"\W+", "", str(k)) for k in key[:3])
        res["dataset_ids"] = ids; res["label"] = f"{key[0]} · {key[1]} · {key[2]}"
        res["occasion"] = key[5]
        if res["status"] == "ASSESSED":
            k = res["key"]
            res["C1"] = _figure(out, f"C1_{k}.png", "", pC1(res, [(s["dose"], s["metrics"], d["card"]["unit"]) for d, s in members]), 10.5, 3.8)
            res["C2"] = _figure(out, f"C2_{k}.png", "", pC2(res), 14, 3.8)
            res["trigger"] = "POINTS_TO_NONLINEARITY" in (res["e6_label"], res["cmax_label"], res["e2_label"])
            t3p = res["t3p"]
            if res.get("ci"):
                res["C2T3"] = one(f"C2T3_{k}.png", pT3(res), 6.0, 3.3)
            if t3p.get("t3p_times"):
                res["C3"] = one(f"C3_{k}.png", pC3(res), 7.0, 3.9)
            if not t3p.get("t3p_times"):
                res["C3d"] = one(f"C3d_{k}.png", pC3(res), 6.0, 3.6)
        dose_series_res.append(res)

    individual_groups = {}
    for dataset in datasets:
        card = dataset["card"]
        if card["record_level"] != "INDIVIDUAL" or card.get("identity_verified") != "yes" or not card["dose_series_allowed"] or not card.get("dose_mg_per_kg"):
            continue
        key = tuple(card.get(k) for k in ("study","species","route_detail","matrix","unit","dose_basis","occasion"))
        individual_groups.setdefault(key, []).append(dataset)
    for key, members in individual_groups.items():
        doses = {d["card"]["dose_mg_per_kg"] for d in members}
        if len(doses) < 2 or len(doses) != len(members):
            continue
        res = comparisons.individual_contrast(members)
        res.update(label=" · ".join(str(v) for v in key[:3]), occasion=key[-1], dataset_ids=[d["card"]["dataset_id"] for d in members])
        dose_series_res.append(res)

    # figure F (A0.12 reported-parameter path; T3 by group SD; reported F)
    for ps in param_sets:
        c = ps["card"]
        lin = next((r["e6_label"] for r in dose_series_res if r.get("status") == "ASSESSED" and c["study"] in r["label"].split(" · ")[0]), None)
        refs = [r for r in iv_param_refs if r["study"] == c["study"] and r["species"] == c["species"]]
        ana = reported_analysis(c, ps["params"], refs, lin)
        ps["analysis"] = {k: v for k, v in ana.items() if k != "params"}
        ps["analysis"]["reported_iv_references"] = [r for r in refs if r.get("params")]
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
        for iv in ivs:
            ic = iv["card"]
            if ic["study"] == c["study"] and ic["species"] == c["species"] and "tmax" in iv["metrics"]:
                res = ev_iv(c, ds["series"][0]["metrics"], ic, iv["metrics"], ds["series"][0]["points"], iv["points"])
                res["key"] = f"{c['dataset_id']}_vs_{ic['dataset_id']}"
                em, im = ds["series"][0]["metrics"], iv["metrics"]
                ev_th = (em.get("terminal_selected") or {}).get("thalf"); iv_th = (im.get("terminal_selected") or {}).get("thalf")
                res["trigger"] = ((em.get("split") or {}).get("class") == "DECLINE_FLATTENS") or bool(ev_th and iv_th and ev_th > iv_th)
                res["trigger_text"] = (f"EV apparent t½ {_f(ev_th)} h, IV {_f(iv_th)} h; EV decline {(em.get('split') or {}).get('class', '—')}")
                if res.get("mt4") is not None and all(res.get(k) for k in ("dose_ev","dose_iv")):
                    res["D1"] = _figure(out, f"D1_{res['key']}.png", "", pD1(c, em, ic, im, res), 10.5, 3.8)
                if res.get("f_window") is not None:
                    res["D2"] = one(f"D2_{res['key']}.png", pD2(c, em, ic, im, res), 6.0, 3.7)
                ev_iv_res.append(res)

    # figure E (item 23): two curves of one study, species and matrix that differ by route or condition
    cond_res = []
    cands = [ds for ds in datasets if ds["card"]["tests_allowed"] and len(ds["series"]) == 1 and "tmax" in ds["series"][0]["metrics"]]
    for a, b in itertools.combinations(cands, 2):
        ca, cb = a["card"], b["card"]
        if (ca["study"], ca["species"], ca["matrix_category"]) != (cb["study"], cb["species"], cb["matrix_category"]):
            continue
        if ca["route_detail"] == cb["route_detail"] and ca["dose_mg_per_kg"] != cb["dose_mg_per_kg"]:
            continue  # dose-only difference belongs to item 19
        ref, test = (b, a) if cb["route_detail"] == "SC" else (a, b)
        tm, rm = test["series"][0]["metrics"], ref["series"][0]["metrics"]
        res = condition_pair(test["card"], tm, ref["card"], rm, test["series"][0]["points"], ref["series"][0]["points"])
        res["key"] = f"{test['card']['dataset_id']}_vs_{ref['card']['dataset_id']}"
        if res.get("intervals"):
            res["E1"] = _figure(out, f"E1_{res['key']}.png", "", [pE1(test["card"], tm, ref["card"], rm, log=False),
                                                                  pE1(test["card"], tm, ref["card"], rm, log=True)], 10.5, 3.7)
            res["E2"] = one(f"E2_{res['key']}.png", pE2(res), 6.0, 3.7)
            if res["observed_window"]["areas"] and all(v > 0 for v in res["observed_window"]["areas"]):
                res["E3"] = one(f"E3_{res['key']}.png", pE3(test["card"], tm, ref["card"], rm, res["observed_window"]), 6.0, 3.7)
        cond_res.append(res)

    boards = status_boards(datasets, dose_series_res, ev_iv_res, cond_res, param_sets, ivs)
    rules_dir = Path(__file__).resolve().parents[2] / "rules" / "eda"
    spec = json.loads((rules_dir / "eda_rules.json").read_bytes())["source"]["absorption_rule_specification"]
    import hashlib
    actual = hashlib.sha256((rules_dir / spec["file"]).read_bytes()).hexdigest()
    if actual != spec["sha256"] or spec["version"] != "r4.3":
        raise ValueError("Absorption r4.3 rules missing or changed")
    result = {"version": VERSION, "rule_specification": {"file":spec["file"], "version":spec["version"], "sha256":actual}, "tolerance_rel": TOL, "span_ratio_min": SPAN_MIN,
              "datasets": [{"card": d["card"], "series": [{k: v for k, v in s.items() if k != "points" and not k.startswith("_")}
                                                          | {"metrics": {k: v for k, v in s["metrics"].items() if not k.startswith("_")}} for s in d["series"]],
                            "A1ind": d.get("A1ind"), "B1ind": d.get("B1ind"), "A4": d.get("A4")} for d in datasets],
              "reported_parameter_ev_datasets": reported,
              "reported_parameters": [{"card": p["card"], "params": p["params"], "analysis": p.get("analysis"),
                                       "F": p.get("F"), "C2T3": p.get("C2T3")} for p in param_sets],
              "iv_references": [{"card": i["card"]} for i in ivs],
              "dose_series": dose_series_res, "ev_iv": ev_iv_res, "conditions": cond_res, "status_boards": boards}
    (out / "absorption.json").write_text(json.dumps(result, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    render_all(out)
    result["render"] = dict(_RENDER)
    portal = (root / "index.html").exists() and '<div class="categories">' in (root / "index.html").read_text(encoding="utf-8")
    pages, result["presentation"] = render_pages(result, datasets, param_sets, base=out, portal=portal, ivs=ivs)
    (out / "absorption.json").write_text(json.dumps(result, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    for name, page_html in pages.items():
        (out / name).write_text(page_html, encoding="utf-8")
    return result


# ---------------------------------------------------------------- status board (9 questions)

def _rng(v):
    lo, hi = min(v), max(v)
    return f"{lo:.3g}" if abs(hi - lo) < 1e-9 else f"{lo:.3g}–{hi:.3g}"


ST_YES, ST_PART, ST_NO, ST_NA = "Answerable", "Partly answerable", "Not answerable yet", "Not applicable"
ST_CODE = {ST_YES: "ANSWERABLE", ST_PART: "PARTLY_ANSWERABLE", ST_NO: "NOT_ANSWERABLE_YET", ST_NA: "NOT_APPLICABLE"}


_RANK = {ST_YES: 3, ST_PART: 2, ST_NO: 1, ST_NA: 0}
_HOLD = {"SENSITIVITY_ONLY", "BORDERLINE", "SINGLE_POINT_SUPPORT", "CONDITIONAL_ON_LABEL_IDENTITY"}


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


def _t3_text(r):
    t3 = f"T3 = {r['t3_label']}" + "".join(" + " + f for f in r.get("t3_flags", []))
    if r.get("ci"):
        t3 += f" (R {r['R']:.2f}, 95 % CI {r['ci'][0]:.2f}–{r['ci'][1]:.2f}, {r.get('t3_data_level')})"
    else:
        t3 += f" ({r.get('t3_reason', '')})"
    p = r.get("t3p") or {}
    if p.get("t3p_times"):
        t3 += (f"; T3p = {p['t3p_label']}" + "".join(" + " + f for f in p["t3p_flags"])
               + f" ({p['t3p_dose_pair'][1]:g} vs {p['t3p_dose_pair'][0]:g} mg/kg, {len(p['t3p_times'])} time points tested, {sum(p['significant'])} significant after Holm)")
    elif p:
        t3 += f"; T3p = CANNOT_ASSESS ({p.get('reason', '')})"
    return t3


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
             "same study and species" if (i["card"]["study"], i["card"]["species"]) == (study, species) else "different study or species"]
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
    t3p = (f"{len(p['t3p_times'])} times tested, {sum(p.get('significant') or [])} significant after Holm" if p.get("t3p_times") else p.get("reason", ""))
    lo, hi = r["doses"][0], r["doses"][-1]
    ratios = _tbl(f"Highest ({hi:g} mg/kg) against lowest ({lo:g} mg/kg) dose", ("Measure", "Value", "Rule", "Reading"), [
        ["E6 · AUC/D ratio over the window", f"{r['R_window']:.3g}", "no sign of nonlinearity if 0.80–1.25", r["e6_label"]],
        ["Cmax/D ratio", f"{r['cmax_d_ratio']:.3g}", "no sign if 0.5–2.0", r["cmax_label"]],
        ["E2 · apparent t½ across doses", rng, "points to nonlinearity only if the ranges do not overlap and t½ rises with dose", r["e2_label"]],
        ["Power model slope (ln AUC vs ln dose)", f"{r['b1']['auc_window']:.3g}", "1 means proportional; description only", "—"],
        ["T3 · AUC/D ratio with 95 % CI", t3, "excluded when the CI does not contain 1", _flags(r["t3_label"], r["t3_flags"])],
        ["T3p · ln(C/D) per time, Holm", t3p, "excluded when a time stays significant after Holm", _flags(p.get("t3p_label"), p.get("t3p_flags"))]])
    times = _tbl("Dose-normalized concentration per shared time (description)", ("Time (h)", f"(C/D) {hi:g} ÷ (C/D) {lo:g}", "Margin beyond ±5 %"),
                 [[_f(x["t"]), f"{x['ratio']:.3g}", _f(x["m_t3"])] for x in r["per_time"]])
    tests = []
    if p.get("t3p_times"):
        tests.append(_tbl("T3p per time", ("Time (h)", "ln ratio", "95 % CI (unadjusted)", "Holm p", "Significant after Holm"),
                          [[_f(x["t"]), f"{x['ln_ratio']:.3g}", f"{x['ci95'][0]:.3g} to {x['ci95'][1]:.3g}", f"{ph:.3g}", "yes" if sg else "no"]
                           for x, ph, sg in zip(p["t3p_ln_ratio_ci"], p["t3p_p_holm"], p["significant"])]))
    rule = (f"Curves of one study, route, matrix, record level and occasion are compared at the times all doses share, over 0–{T:g} h "
            "(trapezoids on observed points, no extrapolation). The descriptions E6, Cmax/D and E2 only point to nonlinearity; the tests T3 "
            "and T3p need SD and n at the sampled times. A row that only describes stays 'partly answerable'.")
    return _part(rule, [per_dose, ratios, times] + tests, ids)


def _param_evidence(pss):
    rows = [[ps["card"]["dataset_id"], p.get("label") or p["param"], _f(p["value"]), p.get("unit"), _f(p.get("dispersion")),
             _f(p.get("dose")), p.get("n")] for ps in pss for p in ps["params"]]
    return _tbl("Reported parameters as printed in the source", ("Dataset", "Parameter", "Value", "Unit", "SD", "Dose (mg/kg)", "n"), rows)


def board_evidence(study, ds, pss, dose_series_res, ev_iv_res, cond_res, ivs, rows):
    return next(b["evidence"] for b in status_boards(ds,dose_series_res,ev_iv_res,cond_res,pss,ivs) if b["study"]==study)

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
           "first sample; read the time origin and baseline on the data card. The ring marks the observed peak."),
    "A1w": ("A", "A1 · Whole profile (linear)", 1, "The same curve over all samples on a linear axis."),
    "A1ind": ("A", "A1 · Individual layer (linear)", 1, "One thin line per animal and the bold mean; with unverified identity, points only with a small time offset."),
    "A2": ("A", "A2 · C/t intervals (T1)", 1, "C/t at eligible positive times with the available bounds. Under M0 (input that never increases, linear disposition) C/t "
           "cannot rise; the dashed line joins the pair with the largest margin M_T1."),
    "A3": ("A", "A3 · Rising-limb increments", 3, "ΔC/Δt between consecutive quantified samples before the peak (description only)."),
    "A4": ("A", "A4 · Individual Tmax and Cmax/D", 3, "One point per animal (description only)."),
    "B1": ("B", "B1 · Whole profile (semi-log)", 1, "All samples on a log axis: the selected terminal window with its apparent t½, the split halves "
           "(shifted up) with their slope ratio, and dip points when present."),
    "B1ind": ("B", "B1 · Individual layer (semi-log)", 1, "One thin line per animal and the bold mean on a log axis."),
    "T2": ("B", "B1 · T2 dip test (per animal)", 2, "The three candidate valley points with their stated bounds; a dip is confirmed when the middle point lies below both "
           "neighbours by more than the intervals (M_drop, M_rise; M_T2 is the smaller)."),
    "B2": ("B", "B2 · Terminal-window sensitivity", 3, "Apparent t½ of every qualified window (span ratio ≥ 2); the selected window is ringed."),
    "C1": ("C", "C1 · C/D overlay", 1, "Each dose divided by dose, linear (early part) and semi-log (whole profile); the common window is shaded."),
    "C2": ("C", "C2 · Metrics by dose", 1, "Cmax/D, apparent t½ (range over qualified windows and the selected value) and AUC/D over the common window "
           "(own observed window dashed: differing coverage) against log2 dose."),
    "C2T3": ("C", "C2 · T3 AUC/D ratio with CI", 2, "The ratio R of AUC/D between two doses with its confidence interval; the dashed line is R = 1."),
    "C3": ("C", "C3 · Per-time ln ratio (T3p)", 2, "ln(C/D) of the highest over the lowest dose at each common time with 95 % CI; orange times stay "
           "significant after Holm."),
    "C3d": ("C", "C3 · Per-time C/D ratio (description)", 3, "C/D of the highest over the lowest dose at each common time; a description, not a test."),
    "D1": ("D", "D1 · EV vs IV (T4)", 2, "Both curves divided by dose (semi-log) with their terminal windows, and Q = C_EV / C_IV at matched times; "
           "under a shared one-compartment disposition Q cannot decrease."),
    "D2": ("D", "D2 · F window", 2, "Both curves divided by dose (linear); the areas up to the end of the common window are shaded."),
    "E1": ("E", "E1 · Condition overlay", 2, "Both conditions, reference solid, linear and semi-log."),
    "E2": ("E", "E2 · c intervals (T5)", 2, "c = C_A / C_ref at paired times with the recorded bounds; no common c exists when the highest lower end lies "
           "above the lowest upper end."),
    "E3": ("E", "E3 · Shape-normalized overlay", 3, "Each curve divided by its own window AUC (description only)."),
    "F": ("F", "F · Reported parameters", 1, "One panel per reported parameter against dose; bars are the reported dispersion."),
}

# question: (short label, question, other panels opened from the row, assumptions line, cannot-show line)
QSPEC = {
    1: ("Onset and delay", "When does drug start to reach the circulation; is there a delay?", ("A2", "A1", "A1ind"),
        "Time zero is the design zero (the dosing time, not measured).", "A delay shorter than the first sample."),
    2: ("Input speed", "Is input concentrated or sustained?", ("A1w", "A1ind", "B1ind", "A3"),
        "Observed points only; Tmax is the observed maximum, not a model value.", "An absorption rate constant, or zero- against first-order input."),
    3: ("Excluded input + disposition", "Which complete input + disposition combinations are excluded?", ("A2", "A1", "T2"),
        "M0 assumes a zero initial state, a single dose and an observed central compartment; the ±5 % bound is project-set.",
        "Which input is present; whether there is a lag or a transit."),
    4: ("Second rise", "Is there a dip and a second rise that one input peak cannot explain?", ("B1", "A1w", "T2", "A1ind", "B1ind", "A3"),
        "A dip is three samples with the middle one below both neighbours by more than ±5 %.",
        "The cause of a second rise (enterohepatic cycling, split absorption, sampling)."),
    5: ("Long tail and flip-flop", "Could slow absorption control the tail; can the EV half-life be read as disposition?", ("B1", "D1", "B2"),
        "A terminal window needs three or more post-peak points and a span ratio of at least 2 (project-set).",
        "Whether the tail is absorption-limited, without an IV curve of the same study."),
    6: ("Extent of absorption (F)", "How much of the dose reaches the circulation?", ("D2", "F"),
        "Equal clearance in both arms (same study); consistent dose basis; no extrapolation.", "F itself when the window ratio is incomplete."),
    7: ("Dose dependence", "Does absorption-related behaviour change with dose?", ("C1", "C2", "C2T3", "C3", "C3d", "F"),
        "Same study, route, occasion and record level; the common window ends at the latest time shared by all doses.",
        "Whether absorption or elimination is the part that changes with dose."),
    8: ("Comparison across conditions", "Does a condition (route, formulation, food, occasion) change rate, extent or disposition?", ("E1", "E2", "E3"),
        "Same drug, analyte and matrix; times matched within tolerance; group means need the same-population premise.",
        "A mechanism; with T5 not excluded, F only and CL and V scaled together cannot be separated."),
    9: ("Individuals or averaging", "Is the shape shared by individuals, or produced by averaging?", ("A4", "A1ind", "B1ind"),
        "Labels follow the source table.", "Single-animal shapes from group means or destructive sampling."),
}


_ATTR = {"route_detail": "route", "dose_mg_per_kg": "dose", "formulation": "formulation", "fed_state": "food", "occasion": "occasion"}


def _all(n):
    return "both curves" if n == 2 else f"all {n} curves" if n > 2 else "the curve"


def _any(n):
    return "either curve" if n == 2 else f"any of the {n} curves" if n > 2 else "the curve"


def _destructive(card):
    n = str(card.get("notes", ""))
    return "mice/time" in n or "DESTRUCTIVE" in n.upper() or "terminal sampling" in n.lower() or "different group" in n.lower()


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
    lab, question = QSPEC[qn][0], QSPEC[qn][1]
    if status in (ST_NO, ST_NA) and primary and primary.get("kind") == "panel":
        primary = None  # A0.11: with NOT_ANSWERABLE_YET or NOT_APPLICABLE no figure is shown
    return {"q": qn, "label": lab, "question": question, "status": status, "status_code": ST_CODE[status],
            "observed": observed, "basis": basis, "reach": reach, "text": " ".join(x for x in (observed, basis, reach) if x),
            "missing": [m for m in dict.fromkeys(missing) if m], "primary": primary, "views": list(views), "evidence": list(evidence)}


def _prim(file, panels, qn, label_line, level, kind="panel"):
    return {"kind": kind, "file": file, "panels": list(panels),
            "lines": [f"Answers Q{qn} · {QSPEC[qn][0]}", label_line, QSPEC[qn][3], "Cannot show: " + QSPEC[qn][4]], "level": level}


def _row(qn, head, rows, label_line, level):
    return {"kind": "row", "head": list(head), "rows": [list(r) for r in rows],
            "lines": [f"Answers Q{qn} · {QSPEC[qn][0]}", label_line, QSPEC[qn][3], "Cannot show: " + QSPEC[qn][4]], "level": level}


def _views_for(qn, study_panels, primary):
    """The other panels of this study that open from row qn, ordered by tier."""
    want = QSPEC[qn][2]
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
        for pid in ("A1ind","B1ind","A4"):
            add(pid, d.get(pid), c["dataset_id"], [c["dataset_id"]], gated=not c["tests_allowed"])
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
        if r["a"] in ids:
            for pid in ("E1", "E2", "E3"):
                add(pid, r.get(pid), f"{r['a']} vs {r['b']}", [r["a"], r["b"]])
    return out


def status_boards(datasets, dose_series_res, ev_iv_res, cond_res, param_sets=(), ivs=(), out=None):
    from .eda_absorption_board43 import boards
    return boards(datasets,dose_series_res,ev_iv_res,cond_res,param_sets,ivs)


def board_questions(b, ds, pss, dose_series_res, ev_iv_res, cond_res, ivs=(), out=None):
    return next(x["questions"] for x in status_boards(ds,dose_series_res,ev_iv_res,cond_res,pss,ivs) if x["study"]==b["study"])

def _e(x):
    return html.escape(str(x))


def _f(x, nd=3):
    return "—" if x is None else f"{x:.{nd}g}"


# ---------------------------------------------------------------- HTML: the EDA review portal's own style
# The Absorption page is one more category of the EDA figure review (index.html → absorption/index.html),
# drawn with the portal's stylesheet. Figures of one kind and one species form one gallery, and one
# description follows each gallery. report.html gets a short Absorption section in its own plain style.

_SPECIES = [("Guinea pig", r"guinea[\s-]*pigs?"), ("Mouse", r"\b(?:mouse|mice|murine)\b"), ("Rat", r"\brats?\b"),
            ("Rabbit", r"\brabbits?\b"), ("Hamster", r"\bhamsters?\b"), ("Dog", r"\b(?:dogs?|beagles?|canine)\b"),
            ("Monkey", r"\b(?:monkeys?|macaques?|primates?|cynomolgus|rhesus|marmosets?)\b"),
            ("Pig", r"\b(?:pigs?|piglets?|minipigs?|swine|porcine)\b"), ("Sheep", r"\b(?:sheep|ovine|lambs?)\b"),
            ("Horse", r"\b(?:horses?|equine|foals?|pony|ponies)\b"), ("Human", r"\b(?:humans?|patients?|volunteers?)\b")]


def species_group(text):
    """Species for grouping only (the source wording stays in the card): 'neutropenic thigh-infected mice' → Mouse."""
    t, out = str(text or "").lower(), []
    for name, pat in _SPECIES:
        if re.search(pat, t):
            out.append(name)
            t = re.sub(pat, " ", t)
    return " / ".join(out) if out else "Species not stated"


def _slug(x):
    return re.sub(r"[^a-z0-9]+", "-", str(x).lower()).strip("-")


ST_CLASS = {ST_YES: "st-yes", ST_PART: "st-part", ST_NO: "st-no", ST_NA: "st-na"}
ST_SHORT = {ST_YES: "Answerable", ST_PART: "Partly", ST_NO: "Not yet", ST_NA: "N/A"}
ST_MEANING = {ST_YES: "the data answer it under the stated assumptions",
              ST_PART: "a description, or a test with limits, answers part of it; the row says which part",
              ST_NO: "these data cannot answer it yet; the row says what is missing",
              ST_NA: "the question does not arise in this study"}
ST_ORDER = (ST_YES, ST_PART, ST_NO, ST_NA)
# r4.3 presents the cross-animal question before terminal interpretation.
_QUESTION_SOURCE_ORDER = (1,2,3,4,9,5,6,7,8)
QSPEC = {n: QSPEC[old] for n,old in enumerate(_QUESTION_SOURCE_ORDER,1)}
QSPEC[1] = (*QSPEC[1][:3], "Check the recorded time origin and baseline separately.", "A mechanism for a delay.")
Q_SHORT = dict(enumerate(("Onset", "Rise", "Input models", "Second rise", "Individuals", "Terminal decline", "Availability", "Dose", "Conditions"),1))
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
    '.concl{font-size:16px;margin:0 0 10px}.concl .sub{color:#455c69}.qtext{min-width:0}.concl,.miss,.prim figcaption{overflow-wrap:anywhere}'
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
    if not res["ev_iv"]:
        skip(None, "D · Extravascular vs IV", None, "No same-study, same-species IV plasma curve.")
    for r in res["ev_iv"]:
        c = cards[r["ev"]]
        lab = f"{r['ev']} vs {r['iv']}"
        if not r.get("D1") and r.get("q"):
            skip(c, "D1 · EV vs IV (T4)", lab, f"No eligible ratio panel ({r['trigger_text']}). T4 status: {r['t4_label']}"
                 + "".join(" + " + x for x in r["t4_flags"]) + " (Q6).")
        if not r.get("D2") and r.get("f_status"):
            skip(c, "D2 · F window", lab, f"f_status = {r['f_status']}, {r.get('f_reason', '')}")
    if not res["conditions"]:
        skip(None, "E · Condition comparison (T5)", None, "No pair from one study, species and matrix that differs only by condition.")
    for r in res["conditions"]:
        if not r.get("E1"):
            skip(cards[r["a"]], "E · Condition comparison (T5)", f"{r['a']} vs {r['b']}", str(r.get("t5_reason")))
    return out


def _board_species(b):
    return [x.strip() for x in (b.get("species_group") or species_group(b["species"])).split(" / ")]


def _wb(x):
    """Escaped text that may wrap after underscores (long state labels in narrow table cells)."""
    return _e(x).replace("_", "_<wbr>")


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
    """Study → links to the C/D overlay drawn by the dose-normalization step (shown under question 8)."""
    see = {}
    for r in res["dose_series"]:
        ob = r.get("overlay_block")
        if not (ob and ob.get("view_ids")):
            continue
        links = []
        for vid in ob["view_ids"]:
            png = next(iter(sorted((root / "EV").glob(f"{vid}*.png"))), None) if root else None
            if png is None:
                continue
            href = f"../EV/{png.name}"
            links.append(f'<a class="dn-link" href="{_e(href)}" data-portal="../sections/Q_PK_SHAPE/index.html#figure-{_e(vid)}">{_e(vid)}</a>')
        if not links:
            continue
        see.setdefault(r["label"].split(" · ")[0], []).append(
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
         f'<div class="qbody{"" if prim and not wide else " noprim"}"><div class="qtext"><p class="concl">{_e(q["observed"])}'
         + (f' <span class="sub">{_e(sub)}</span>' if sub else "") + f'</p>{miss}</div>{prim}</div>']
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
    return "".join(f'<a class="qchip" href="{_e(page)}#{_qid(b["study"], q["q"])}" title="{_e(q["text"])}">Q{q["q"]} {_e(q["label"])}'
                   f'<span class="st {ST_CLASS[q["status"]]}">{_e(ST_SHORT[q["status"]])}</span></a>' for q in b.get("questions", []))


def _study_card(ds, pss, ivs):
    """Step 0, the data card of one study: what each dataset is and what it allows."""
    rows = []
    for d in ds:
        c = d["card"]
        gate = "Per-test assessment" if c["tests_allowed"] else ("Dose series only" if c.get("dose_series_allowed") else "Overview only")
        n = len([s for s in d["series"] if "tmax" in s["metrics"]])
        doses = sorted({s["dose"] for s in d["series"] if s.get("dose")})
        dose = (", ".join(f"{x:g}" for x in doses) + f" mg/kg {c.get('route_detail', '')}") if len(doses) > 1 else _dose_txt(c)
        rows.append([c["dataset_id"], dose, c["matrix"], _data_level(c) + (f" · {n} curves" if n > 1 else ""),
                     c.get("n_per_time") or "—", c.get("lloq") or "not reported", c.get("dose_time_basis") or "—",
                     gate + (": " + ", ".join(c["gates"]) if c["gates"] else "")])
    for i in ivs:
        c = i["card"]
        rows.append([c["dataset_id"], _dose_txt(c) + " (IV reference)", c["matrix"], _data_level(c), c.get("n_per_time") or "—",
                     c.get("lloq") or "not reported", c.get("dose_time_basis") or "—", "Reference for Q6, Q7"])
    for ps in pss:
        c = ps["card"]
        rows.append([c["dataset_id"], _dose_txt(c), c.get("matrix", ""), "Reported parameters", "—", "—", "—", "As printed (A0.12)"])
    head = ["Dataset", "Dose and route", "Matrix", "Data", "n per time", "LLOQ", "Time zero", "Gate",
            "Origin / analyte", "Assay", "Baseline / occasion", "Mean / spread", "Serial identity", "Hidden error bars"]
    cards = {x["card"]["dataset_id"]:x["card"] for x in [*ds,*ivs,*pss]}
    for row in rows:
        card=cards[row[0]]
        row.extend([" / ".join(str(card.get(k) or "unreported") for k in keys) for keys in
                    [("origin","analyte"),("assay_specificity",),("baseline_status","occasion"),("mean_type","dispersion"),
                     ("identity_verified",),("error_bars_hidden",)]])
    return ('<div class="tw"><table class="res evt card"><tr>' + "".join(f"<th>{_e(x)}</th>" for x in head) + "</tr>"
            + "".join("<tr>" + "".join(f'<td>{_wb(v) if j == 7 else _e(v)}</td>' for j, v in enumerate(r)) + "</tr>" for r in rows)
            + "</table></div>")


def _study_html(b, ds, pss, ivs, base=None, see=()):
    sp = b.get("species_group") or species_group(b["species"])
    slug = _slug(b["study"])
    h = [f'<section class="panel study" id="study-{_e(slug)}"><h2>{_e(b["study"])} · {_e(sp)}</h2>'
         f'<p class="muted">{_e(b["species"])} · {_e(", ".join(b["datasets"]))}</p>', _study_card(ds, pss, ivs),
         f'<div class="qchips">{_qchips(b)}</div>']
    h += [_qrow_html(q, b["study"], base, see if q["q"] == 8 else ()) for q in b.get("questions", [])]
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
                 ("n per time", c.get("n_per_time")), ("Dispersion", c.get("dispersion")), ("LLOQ", c.get("lloq")),
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


def _nav(portal, overview=True, studies=()):
    first = "" if overview else '<a href="index.html">← All species</a>'
    jump = "".join(f'<a href="#study-{_e(_slug(s))}">{_e(s)}</a>' for s in studies) if studies else '<a href="#questions">Nine questions</a>'
    return f'<nav>{first}{_portal_links(portal)}{jump}</nav>'


_HASH_JS = ('<script>function openHash(){const id=decodeURIComponent(location.hash.slice(1));const el=id&&document.getElementById(id);'
            'if(!el)return;for(let p=el;p;p=p.parentElement){if(p.tagName==="DETAILS")p.open=true}el.scrollIntoView()}'
            'addEventListener("hashchange",openHash);openHash();</script>')


def _shell(title, body, script=""):
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{_e(title)} · EDA review</title><style>' + _portal_css() + ABS_CSS + '</style></head><body><main id="main">'
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


def _datasets_html(datasets, param_sets, species=None):
    rows = []
    for d in datasets:
        c = d["card"]
        if species and species_group(c["species"]) != species:
            continue
        gate = "Per-test assessment" if c["tests_allowed"] else ("Dose series only" if c.get("dose_series_allowed") else "Overview only")
        rows.append(f'<tr><td>{_e(c["dataset_id"])}</td><td>{_e(species_group(c["species"]))}</td><td>{_e(c["study"])}</td><td>{_e(_dose_txt(c))}</td>'
                    f'<td>{_e(c["matrix"])}</td><td>{_e(_data_level(c))}</td><td>{_e(gate)}{": " + _e(", ".join(c["gates"])) if c["gates"] else ""}</td></tr>')
    for ps in param_sets:
        c = ps["card"]
        if species and species_group(c["species"]) != species:
            continue
        rows.append(f'<tr><td>{_e(c["dataset_id"])}</td><td>{_e(species_group(c["species"]))}</td><td>{_e(c["study"])}</td><td>{_e(_dose_txt(c))}</td>'
                    f'<td>{_e(c["matrix"])}</td><td>Reported parameters</td><td>Panel F replaces figures A–C</td></tr>')
    if not rows:
        return ""
    return ('<section class="panel" id="data"><h2>Datasets used</h2><p class="muted">Extravascular datasets and reported-parameter tables that '
            'entered the Absorption pages. The full data card of each dataset is in absorption.json.</p>'
            '<div class="tw"><table class="res"><tr><th>Dataset</th><th>Species</th><th>Study</th><th>Dose</th><th>Matrix</th><th>Data</th>'
            '<th>Gate</th></tr>' + "".join(rows) + '</table></div></section>')


def _footer():
    return '<footer>Absorption rules r4.3 · Technical EDA. Each test records its evidence, numerical assumptions and limits. Human review pending.</footer>'


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
    panels = {b["study"]: _study_panels(bds.get(b["study"], []), bps.get(b["study"], []), res["dose_series"], res["ev_iv"], res["conditions"])
              for b in boards}
    files = {b["study"]: {v["file"] for vs in panels[b["study"]].values() for v in vs} for b in boards}
    species = {sp for b in boards for sp in _board_species(b)}
    n_fig = {sp: len(set().union(*[files[b["study"]] for b in boards if sp in _board_species(b)])) for sp in species}
    order = sorted(species, key=lambda sp: (sp == "Species not stated", -n_fig[sp], sp))
    pages, info = {}, []
    for sp in order:
        sb = sorted((b for b in boards if sp in _board_species(b)), key=lambda b: b["study"])
        studies = [b["study"] for b in sb]
        sk = [x[:3] for x in skips if x[3] == sp]
        h = [_nav(portal, overview=False, studies=studies), '<div class="eyebrow">EDA figure review · Absorption</div>', f'<h1>{_e(sp)}</h1>',
             f'<p class="lead">Nine questions on how the drug enters the circulation, for {"study" if len(studies) == 1 else "studies"} '
             f'{_e(", ".join(studies))}. Each row gives the status, one conclusion, the evidence that explains it best, and what is missing.</p>',
             f'<p class="muted">{n_fig[sp]} panels · Computed by host code from observed points; no fitting · Figures drawn with {_e(engine)} · '
             'Human review pending</p>', fallback, _legend()]
        for b in sb:
            ivs_b = [i for (st_, spc), v in bivs.items() for i in v if st_ == b["study"]]
            h.append(_study_html(b, bds.get(b["study"], []), bps.get(b["study"], []), ivs_b, base, see.get(b["study"], [])))
        used = {v["file"] for b in sb for q in b.get("questions", []) for v in q["views"]} | {
            (q.get("primary") or {}).get("file") for b in sb for q in b.get("questions", [])}
        loose = [v for b in sb for vs in panels[b["study"]].values() for v in vs if v["file"] not in used]
        if loose:
            h.append(f'<details class="panel" id="loose"><summary>Other panels ({len(loose)})</summary><p class="muted">Panels that no question row '
                     'opens, such as the overview panels of curves outside plasma, serum and blood.</p>' + _thumbs(loose) + '</details>')
        h.append(_not_drawn_html(sk, "A panel is drawn only when its data allow it and, for tier 2, when tier 1 shows what it tests. "
                                     "Test results are still in the question rows."))
        h.append(_points_html(datasets, param_sets, ivs, sp))
        h.append(_footer())
        name = species_page_name(sp)
        pages[name] = _shell(f"Absorption · {sp}", "".join(h), _HASH_JS)
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
    h = [_nav(portal), '<div class="eyebrow">EDA figure review</div><h1>Absorption</h1>',
         '<p class="lead">How the drug enters the circulation, as nine questions for each study (r4.3 items 16–23): onset, rise, '
         'input models, second rise, individual animals, terminal decline, availability, dose and conditions. Open a species, '
         'then a study; each question shows its conclusion next to the evidence that explains it best.</p>',
         f'<p class="muted">{total} panels · {len(order)} species · {len(boards)} studies · {len(datasets)} curve datasets ({n_curves} curves) and '
         f'{len(param_sets)} reported-parameter datasets · Computed by host code from observed points; no fitting · Figures drawn with {_e(engine)} · '
         'Human review pending</p>', fallback,
         '<div class="section-head" id="species"><h2>Review by species</h2><span class="muted">Open a species for its studies and their nine questions.</span></div>'
         '<div class="categories">']
    for x in info:
        thumbs = "".join(f'<img src="{_e(s)}" alt="Preview of {_e(s)}" loading="lazy">' for s in x["thumbnails"])
        chips = " ".join(f'<span class="st {ST_CLASS[s]}">{x["_counts"][s]} {_e(ST_SHORT[s].lower())}</span>' for s in ST_ORDER if x["_counts"].get(s))
        h.append(f'<a class="category" id="sp-{_e(_slug(x["species"]))}" href="{_e(x["page"])}"><span class="badge">{len(x["studies"])} '
                 f'stud{"y" if len(x["studies"]) == 1 else "ies"}</span><h3>{_e(x["species"])}</h3><p class="muted">{_e(", ".join(x["studies"]))} · '
                 f'{x["figures"]} panels</p><p>{chips}</p>' + (f'<div class="thumbs">{thumbs}</div>' if thumbs else "")
                 + '<span class="open">Open the nine questions →</span></a>')
    h.append('</div>')
    rank = {sp: k for k, sp in enumerate(order)}
    head = "".join(f'<th title="{_e(QSPEC[n][1])}">Q{n}<br><span class="muted">{_e(Q_SHORT[n])}</span></th>' for n in range(1, 10))
    trs = []
    for b in sorted(boards, key=lambda b: (min(rank.get(x, len(rank)) for x in _board_species(b)), b["study"])):
        page = species_page_name(_board_species(b)[0])
        cells = "".join(f'<td><a href="{_e(page)}#{_qid(b["study"], q["q"])}" title="{_e(q["text"])}"><span class="st {ST_CLASS[q["status"]]}">'
                        f'{_e(ST_SHORT[q["status"]])}</span></a></td>' for q in b.get("questions", []))
        trs.append(f'<tr><td><a href="{_e(page)}#study-{_e(_slug(b["study"]))}">{_e(b["study"])}</a> · {_e(b.get("species_group") or b["species"])}</td>{cells}</tr>')
    h.append('<section class="panel" id="questions"><h2>The nine questions by study</h2><p class="muted">Each cell opens the question row on the '
             'species page; hover for the conclusion.</p>' + _legend()
             + f'<div class="tw"><table class="res qtab"><tr><th>Study</th>{head}</tr>{"".join(trs)}</table></div></section>')
    h.append(_not_drawn_html([x[:3] for x in skips if x[3] is None], "Panels that no species can have with these data."))
    h.append(_datasets_html(datasets, param_sets))
    h.append(_footer())
    pages["index.html"] = _shell("Absorption", "".join(h))
    for x in info:
        x.pop("_counts", None)
    thumbs = [x["thumbnails"][0] for x in info if x["thumbnails"]][:3]
    presentation = {"page": "absorption/index.html", "figures": total, "species": info, "thumbnails": thumbs,
                    "questions": [{"study": b["study"], "species": b.get("species_group"), "page": species_page_name(_board_species(b)[0]),
                                   "statuses": {str(q["q"]): q["status_code"] for q in b.get("questions", [])}} for b in boards],
                    "not_drawn": [{"figure": k, "item": lab, "reason": t, "species": sp} for k, lab, t, sp in skips]}
    return pages, presentation


def report_section(res, error=None):
    """Absorption in report.html, written in that report's own plain style."""
    h = ['<section id="absorption"><h2>Absorption: how does the drug enter the circulation?</h2>',
         '<p><b>Need to understand:</b> when drug starts to appear, how fast and how much of it enters, whether there is a second rise or a long '
         'tail, and whether dose or condition changes this (r4.3 items 16–23). Host-computed from observed points; no fitting.</p>']
    if error is not None or not res:
        h.append(f'<p><b>Not generated:</b> {_e(error)}. The reason is recorded in absorption/error.json.</p></section>')
        return "".join(h)
    h.append('<p><b>The nine questions by study:</b></p><ul>')
    for b in res["status_boards"]:
        page = species_page_name(_board_species(b)[0])
        by = {}
        for q in b.get("questions", []):
            by.setdefault(q["status"], []).append(f'Q{q["q"]}')
        h.append(f'<li><a href="absorption/{_e(page)}#study-{_e(_slug(b["study"]))}">{_e(b["study"])}</a> · '
                 f'{_e(b.get("species_group") or species_group(b["species"]))}: '
                 + "; ".join(f'{_e(s.lower())} {", ".join(by[s])}' for s in ST_ORDER if by.get(s)) + '</li>')
    pres = res.get("presentation", {})
    sp = "; ".join(f'<a href="absorption/{_e(x["page"])}">{_e(x["species"])}</a> ({len(x["studies"])} stud{"y" if len(x["studies"]) == 1 else "ies"})'
                   for x in pres.get("species", []))
    h.append(f'</ul><p><b>By species:</b> {sp}. Each study shows its nine questions, each with one conclusion, the evidence that explains it '
             'best, and what is missing. <a href="absorption/index.html">Open the Absorption overview</a></p></section>')
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
        thumbs = "".join(f'<img src="absorption/{_e(s)}" alt="Preview of {_e(s)}" loading="lazy">' for s in pres.get("thumbnails", []))
        sp = ", ".join(f'{x["species"]} ({x["figures"]})' for x in pres.get("species", []))
        card = ('<!--ABSORPTION-CARD-START--><a class="category" id="ABSORPTION" href="absorption/index.html">'
                f'<span class="badge">{n} figures</span><h3>Absorption</h3><p class="muted">How the drug enters the circulation: onset, input '
                f'speed, re-rise, long tail, extent, dose and condition effects. One page per species: {_e(sp)}.</p><div class="thumbs">{thumbs}</div>'
                f'<span class="open">View all {n} figures →</span></a><!--ABSORPTION-CARD-END-->')
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
    block = '<!--ABSORPTION-START-->' + report_section(res, err) + '<!--ABSORPTION-END-->'
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
