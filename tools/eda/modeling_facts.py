"""Data facts for modeling, computed from the EDA input and the section results. No model is fitted.

Writes three things into a finished run folder:

* ``modeling_facts.json``: per species, the profiles with their points per phase and identifiability notes, BLQ counts
  by route and time bin, animal and occasion structure, dose levels per route, and the modeling figures with the EDA
  questions they serve. Species physiology values belong to the modeling stage and are not written here.
* ``modeling_facts.txt``: the same facts as a short plain-text block for a prompt.
* ``modeling_figures/``: blinded copies of the EDA figures that show the data (individual layers, EV against IV), with
  ``figures.json`` listing for each the profiles it draws. Titles name species, route and dose only; legends that name a
  profile, study or dataset are removed; animals in within-animal pairs become "Pair 1", "Pair 2", ...

Nothing here names the drug or the study. Profiles are referred to as ``<route>/<source column header>`` (for example
``IM/H01b0``), the form the modeling side maps to its own blinded identifiers. ``dataset_id`` values are kept in the JSON
for traceability and never written to the text block or the figures.

Inputs: the run folder (source_tables.json, absorption/, distribution/) and, optionally, the case folder. If the case
folder has exactly one ``inputs/*_individual.csv`` long table, it supplies what the EDA tables do not carry: BLQ and
author-excluded samples of the analysed profiles, and the animal and occasion of each profile. Every fact says which
of the two it came from.

Usage: python modeling_facts.py <run folder> [--case <case folder>]
"""
import argparse
import csv
import hashlib
import json
import math
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

SCHEMA = "eda-modeling-facts.1"
HERE = Path(__file__).resolve().parent
TIME_BINS_H = (0, 0.25, 0.5, 1, 2, 4, 8, 12, 24, 48, 96)   # display bins only; no threshold depends on them
NOT_QUANTIFIED = ("BLQ", "AUTHOR_EXCLUDED", "MDV_1_SOURCE_FLAG")
SOURCE_EXCLUSIONS = {"AUTHOR_EXCLUDED", "MDV_1_SOURCE_FLAG"}   # the same set as eda_common.SOURCE_EXCLUSIONS


def _source_flags(record, column):
    v = (record.get("source_flags") or {}).get(column)
    return [str(x).strip().upper() for x in (v if isinstance(v, (list, tuple)) else [v]) if x not in (None, "")]


def _cell_status(record, column):
    """As eda_common.cell_status: a quantified cell flagged by the source authors counts as excluded."""
    st = (record.get("value_status") or {}).get(column)
    if str(st or "QUANTIFIED").strip().upper() == "QUANTIFIED" and set(_source_flags(record, column)) & SOURCE_EXCLUSIONS:
        return "AUTHOR_EXCLUDED"
    return st


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _g(x, digits=4):
    if x is None:
        return "—"
    return f"{float(x):.{digits}g}"


def _range(values):
    values = sorted(v for v in values if v is not None)
    if not values:
        return "—"
    if values[0] == values[-1]:
        return _g(values[0])
    return f"median {_g(statistics.median(values))} (range {_g(values[0])}–{_g(values[-1])})"


def _bin(t):
    for lo, hi in zip(TIME_BINS_H, TIME_BINS_H[1:]):
        if lo <= t < hi:
            return lo, hi
    return TIME_BINS_H[-1], None


# ---------------------------------------------------------------- inputs

def column_headers(tables):
    """(dataset_id, column id) -> source column header, for concentration columns."""
    return {(t["dataset_id"], c["id"]): c.get("header") or c["id"]
            for t in tables for c in t.get("columns", []) if c.get("meaning") == "CONCENTRATION"}


def long_table(case):
    if case is None:
        return None, None
    found = sorted(Path(case).glob("inputs/*_individual.csv"))
    if len(found) != 1:
        return None, None
    with found[0].open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f)), found[0]


# ---------------------------------------------------------------- profiles and phases

def _clk(t_after_end, end):
    """S13 one clock: a time after the end of the input, reported after the start of dosing (after-end time in brackets)."""
    if end <= 0:
        return f"{_g(t_after_end)} h"
    d = t_after_end * 60
    return f"{_g(t_after_end + end)} h (end of infusion + " + (f"{_g(d)} min)" if d < 60 else f"{_g(t_after_end)} h)")


def iv_phases(series, r24):
    end = series.get("infusion_h") or 0.0
    q = sorted(p["t"] - end for p in series["points"] if p["status"] == "QUANTIFIED" and p["t"] > end)
    pv = (r24 or {}).get("phases_visible", "NOT_ASSESSED")
    cut = (r24 or {}).get("post_distribution_from_h")
    # George 2026-11-25: every time is reported after the START of dosing (S13); the after-end values are kept alongside
    out = {"time_basis": "after start of dosing", "reading": pv, "first_sample_h": q[0] + end if q else None,
           "first_sample_after_end_h": q[0] if q else None,
           "later_part_from_h": cut + end if isinstance(cut, (int, float)) else None,
           "later_part_from_after_end_h": cut if isinstance(cut, (int, float)) else None}
    notes = []
    if pv in ("TWO_OR_MORE", "TWO_OR_MORE_TENTATIVE") and isinstance(cut, (int, float)):
        out["n_before_later_part"] = sum(t < cut for t in q)
        out["n_from_later_part"] = sum(t >= cut for t in q)
        k = out["n_before_later_part"]
        notes.append(f"{k} quantified point{'s' if k != 1 else ''} before the later part starts at {_clk(cut, end)}"
                     + (", so a further early phase cannot be separated from these points." if k < 3 else "."))
        if pv == "TWO_OR_MORE_TENTATIVE":
            notes.append("The slowing rests on one point (item 24).")
    elif pv == "ONE_APPARENT":
        notes.append(f"One apparent decline phase from the first sample at {_clk(q[0], end)}; a faster phase before that time "
                     "would not be visible." if q else "One apparent decline phase.")
    elif pv in ("TWO_OR_MORE", "TWO_OR_MORE_TENTATIVE"):
        notes.append("The decline slows, but no point was found from which at least 5 remaining points decline as one "
                     "straight line (item 24 step 7), so the later part has no start time.")
    elif pv == "NOT_LOG_CONVEX_DESCRIPTIVE":
        notes.append("The decline steepens on the semilog scale (descriptive, item 24).")
    else:
        reason = (r24 or {}).get("not_assessable_reason")
        notes.append("Decline phases not assessed" + (f": {reason}." if reason else "."))
    return out, notes


def ev_phases(metrics):
    m = metrics or {}
    tmax, nbp, nq = m.get("tmax"), m.get("n_before_peak"), m.get("n_quantified")
    sel = m.get("terminal_selected")
    out = {"time_basis": "after dose", "first_sample_h": m.get("first_t"), "sampled_peak_h": tmax,
           "n_before_peak": nbp, "n_after_peak": (nq - nbp - 1) if (nq is not None and nbp is not None) else None,
           "terminal_window_from_h": sel["start"] if sel else None, "n_terminal_window": sel["n"] if sel else None,
           "terminal_status": m.get("terminal_status")}
    notes = []
    caveats = m.get("caveats") or []
    if tmax is not None and nbp is not None:
        notes.append(f"{nbp} quantified point{'s' if nbp != 1 else ''} before the sampled peak at {_g(tmax)} h"
                     + ("; too few to inform an absorption rate (KA_NOT_IDENTIFIABLE, item 17)." if "KA_NOT_IDENTIFIABLE" in caveats else "."))
    if "LATE_FIRST_SAMPLE" in caveats:
        notes.append(f"The first sample ({_g(m.get('first_t'))} h) is late relative to the sampled peak.")
    if sel:
        notes.append(f"Terminal window from {_g(sel['start'])} h with {sel['n']} points (A0.7).")
    elif m.get("terminal_status"):
        notes.append(f"No terminal window qualifies ({m['terminal_status']}, A0.7).")
    return out, notes


def profiles(tables, dist, ab):
    headers = column_headers(tables)
    routes = {t["dataset_id"]: (t.get("metadata") or {}).get("route") for t in tables}
    species = {t["dataset_id"]: str((t.get("metadata") or {}).get("species") or "").strip() for t in tables}
    metrics = {(d["card"]["dataset_id"], s["series_id"]): s["metrics"] for d in ab.get("datasets", []) for s in d["series"]}
    later = {(d["card"]["dataset_id"], s["series_id"]): s for d in ab.get("datasets", []) for s in d["series"] if s.get("dose_events")}
    r24 = {r["sid"]: r for b in dist.get("boards", []) for r in b.get("item24", [])}
    rows = []
    for s in dist.get("series", []):
        if s.get("matrix_class") != "PLASMA":
            continue
        did, col = s["sid"].split(":", 1)
        header = headers.get((did, col), col)
        route = routes.get(did) or s.get("route_source") or s.get("route_detail")
        # L1 (2026-11-24): a source-reported predose zero (or a printed 0) is not a quantified point
        quant = [p for p in s["points"] if p["status"] == "QUANTIFIED" and p.get("c") is not None and p["c"] > 0]
        zeros = [p for p in s["points"] if p.get("t") is not None and p["t"] <= 0 and p.get("c") == 0
                 and p["status"] in ("QUANTIFIED", "REPORTED_ZERO_PREDOSE")]
        row = {"profile": f"{route}/{header}", "route": route, "route_class": s["route_class"],
               "species": species.get(did).capitalize() if species.get(did) else s["species"],
               "dose_mg_kg": s.get("dose"), "unit": s.get("unit"),
               # round 3: the animal's administered dose when the input states it (the dose level stays the grouping key)
               "dose_given_mg_kg": s.get("dose_given") if s.get("dose_given_from") == "column" else None, "level": s.get("level"), "analyte_role": s.get("analyte_role"),
               "dataset_id": did, "column": col, "header": header,
               "n_quantified": len(quant), "n_not_quantified_in_input": len(s["points"]) - len(quant) - len(zeros),
               "n_reported_zero_predose": len(zeros),
               "first_quantified_h": min((p["t"] for p in quant), default=None),
               "last_quantified_h": max((p["t"] for p in quant), default=None),
               "times_h": sorted(p["t"] for p in quant)}
        if s["route_class"] == "IV":
            row["phases"], row["notes"] = iv_phases(s, r24.get(s["sid"]))
            row["iv_mode"] = s.get("iv_mode")
        else:
            row["phases"], row["notes"] = ev_phases(metrics.get((did, col)))
            md = later.get((did, col))
            if md:   # 2026-11-25: multiple dosing; absorption read the first dose interval only
                row["dose_events_h"] = [e["time_h"] for e in md["dose_events"]]
                row["first_interval_end_h"] = md["first_interval_end_h"]
                row["notes"].insert(0, f"{len(md['dose_events'])} doses at " + ", ".join(_g(e["time_h"]) for e in md["dose_events"])
                                    + f" h; the absorption readings use the first dose interval (to {_g(md['first_interval_end_h'])} h); "
                                    + f"{md['n_quantified_after_next_dose']} quantified points after the second dose are not used.")
        rows.append(row)
    return rows


# ---------------------------------------------------------------- BLQ, occasions, doses

def blq_facts(rows, dist, long_rows, route_of_table, tables=()):
    """Samples by route and time bin. BLQ comes from the EDA input when it has any, otherwise from the long table."""
    input_flags = defaultdict(list)          # profile -> [(t, status)] from the EDA input
    for s in dist.get("series", []):
        if s.get("matrix_class") == "PLASMA":
            for p in s["points"]:
                if p["status"] != "QUANTIFIED":
                    input_flags[s["sid"]].append((p["t"], p["status"]))
    input_has_blq = any(st == "BLQ" for v in input_flags.values() for _, st in v)
    analysed = {(r["route"], r["header"]): r for r in rows}
    long_flags = defaultdict(list)
    for x in long_rows or []:
        key = (x.get("route"), x.get("profile_id"))
        if key in analysed and x.get("source_status") in NOT_QUANTIFIED and not (x.get("scope_note") or "").strip():
            try:
                long_flags[key].append((float(x["time_h"]), x["source_status"]))
            except (KeyError, ValueError):
                continue
    # 2026-11-25: exclusions the source sets in the EDA input itself (value_status or record source_flags of a column)
    flagged = defaultdict(lambda: [0, 0])     # (dataset_id, column) -> [quantified values excluded, BLQ cells also flagged]
    for t in tables or ():
        for rec in t.get("records", []):
            for col, st in ((c, _cell_status(rec, c)) for c in set(rec.get("value_status") or {}) | set(rec.get("source_flags") or {})):
                if str(st or "").upper() in SOURCE_EXCLUSIONS:
                    flagged[(t["dataset_id"], col)][0] += 1
                elif set(_source_flags(rec, col)) & SOURCE_EXCLUSIONS:
                    flagged[(t["dataset_id"], col)][1] += 1
    by_route = defaultdict(lambda: {"n_samples": 0, "n_blq": 0, "n_author_excluded": 0, "n_blq_author_flagged": 0, "n_blq_after_last_quantified": 0,
                                    "bins": defaultdict(lambda: [0, 0])})
    sources = set()
    for r in rows:
        acc = by_route[r["route"]]
        sid = r["dataset_id"] + ":" + r["column"]
        long_here = long_flags.get((r["route"], r["header"]), [])
        fq, fb = flagged.get((r["dataset_id"], r["column"]), (0, 0))
        acc["n_author_excluded"] += fq
        acc["n_blq_author_flagged"] += fb
        if fq or fb:
            sources.add("EDA input")
        if input_has_blq:
            flags = [f for f in input_flags.get(sid, []) if f[1] == "BLQ"] + [f for f in long_here if f[1] != "BLQ"]
            if any(f[1] == "BLQ" for f in flags):
                sources.add("EDA input")
            if any(f[1] != "BLQ" for f in flags):
                sources.add("case long table (author exclusions)")
        else:
            flags = input_flags.get(sid) or long_here
            if flags:
                sources.add("EDA input" if input_flags.get(sid) else "case long table")
        for t in r["times_h"]:
            acc["n_samples"] += 1
            acc["bins"][_bin(t)][0] += 1
        for t, status in flags:
            if status == "BLQ":
                acc["n_samples"] += 1
                acc["n_blq"] += 1
                acc["bins"][_bin(t)][0] += 1
                acc["bins"][_bin(t)][1] += 1
                if r["last_quantified_h"] is not None and t > r["last_quantified_h"]:
                    acc["n_blq_after_last_quantified"] += 1
            else:
                acc["n_author_excluded"] += 1
    out = []
    for route, acc in sorted(by_route.items()):
        out.append({"route": route, "n_samples": acc["n_samples"], "n_blq": acc["n_blq"],
                    "fraction_blq": round(acc["n_blq"] / acc["n_samples"], 4) if acc["n_samples"] else None,
                    "n_blq_after_last_quantified": acc["n_blq_after_last_quantified"],
                    "n_author_excluded": acc["n_author_excluded"], "n_blq_author_flagged": acc["n_blq_author_flagged"],
                    "bins": [{"from_h": lo, "to_h": hi, "n_samples": n, "n_blq": b}
                             for (lo, hi), (n, b) in sorted(acc["bins"].items(), key=lambda kv: kv[0][0])]})
    if not sources:
        basis = ("No BLQ or excluded sample is recorded for the analysed profiles, in the EDA input"
                 + (" or the case long table." if long_rows is not None else "; no case long table was supplied."))
    else:
        basis = "Counted from " + " and ".join(sorted(sources)) + "."
    if long_rows is not None and "case long table" in sources:
        basis += " These samples are not in the EDA input tables, so the EDA readings did not use them."
    lloq = sorted({str(v) for t in route_of_table.values() for v in [t.get("lloq")] if v not in (None, "")})
    return {"basis": basis, "time_bins_h": list(TIME_BINS_H), "lloq_reported": lloq or "not reported", "by_route": out}


# ---------------------------------------------------------------- cross-occasion exposure (George 2026-11-25)

ADJ_TIE = 1e-4
F_ABOVE = 1.25


def _lambda_z(ts, cs, after=0.0):
    """Best-adjusted-R² log-linear fit over the last >= 3 quantified points after `after` and after the last peak; ties within
    1e-4 go to the longer window. Returns (lambda_z, n) or None."""
    pts = [(t, c) for t, c in zip(ts, cs) if t > after and c > 0]
    if len(pts) < 3:
        return None
    imax = max(range(len(pts)), key=lambda i: pts[i][1])
    best = []
    for k in range(imax + 1, len(pts) - 2):
        w = pts[k:]
        n = len(w)
        mt = sum(t for t, _ in w) / n
        ly = [math.log(c) for _, c in w]
        my = sum(ly) / n
        sxx = sum((t - mt) ** 2 for t, _ in w)
        if sxx <= 0:
            continue
        b = sum((t - mt) * (y - my) for (t, _), y in zip(w, ly)) / sxx
        ss_res = sum((y - (my + b * (t - mt))) ** 2 for (t, _), y in zip(w, ly))
        ss_tot = sum((y - my) ** 2 for y in ly)
        if b >= 0 or ss_tot <= 0:
            continue
        r2 = 1 - ss_res / ss_tot
        adj = 1 - (1 - r2) * (n - 1) / (n - 2)
        best.append((adj, n, -b))
    if not best:
        return None
    top = max(a for a, _, _ in best)
    adj, n, lam = max((x for x in best if top - x[0] <= ADJ_TIE), key=lambda x: x[1])
    return lam, n


def _auc_lin_up_log_down(ts, cs):
    a = 0.0
    for (t0, c0), (t1, c1) in zip(zip(ts, cs), zip(ts[1:], cs[1:])):
        dt = t1 - t0
        if c1 < c0 and c1 > 0 and c0 > 0:
            a += (c0 - c1) * dt / math.log(c0 / c1)
        else:
            a += (c0 + c1) * dt / 2
    return a


def _auc_inf(points, iv_bolus=False, after=0.0):
    q = sorted((p["t"], p["c"]) for p in points if p["status"] == "QUANTIFIED" and p.get("c") and p["c"] > 0 and p["t"] >= 0)
    if len(q) < 3:
        return None
    ts, cs = [t for t, _ in q], [c for _, c in q]
    if ts[0] > 0:
        if iv_bolus and len(cs) > 1 and cs[1] < cs[0]:
            c0 = math.exp(math.log(cs[0]) - (math.log(cs[1]) - math.log(cs[0])) / (ts[1] - ts[0]) * ts[0])
        else:
            c0 = 0.0
        ts, cs = [0.0] + ts, [c0] + cs
    lz = _lambda_z(ts, cs, after)
    if not lz:
        return None
    last = _auc_lin_up_log_down(ts, cs)
    tail = cs[-1] / lz[0]
    return {"auc_inf": last + tail, "tail_pct": 100 * tail / (last + tail), "thalf_h": math.log(2) / lz[0], "n_lambda": lz[1]}


def cross_occasion_facts(rows, dist, tables):
    """Same animals given IV and EV on different occasions, washout not verified: a descriptive exposure check, never F.
    AUC0-inf / total EV dose (all doses: valid for multiple dosing under linear, time-invariant PK) over AUC0-inf / IV dose."""
    cols = {(t["dataset_id"], c["id"]): c for t in tables for c in t.get("columns", []) if c.get("meaning") == "CONCENTRATION"}
    series = {s["sid"]: s for s in dist.get("series", [])}
    by_subject = defaultdict(dict)
    for r in rows:
        c = cols.get((r["dataset_id"], r["column"]), {})
        subj = str(c.get("subject_id") or "").strip()
        s = series.get(r["dataset_id"] + ":" + r["column"])
        if not subj or not s:
            continue
        side = "IV" if r["route_class"] == "IV" else "EV"
        if side == "IV" and c.get("washout_verified") is True:
            return None      # a verified pair: Absorption computes F itself
        ev = sorted(((e.get("time_h"), e.get("dose_mg_kg")) for e in c.get("dose_events") or [] if e.get("time_h") is not None), key=lambda x: x[0])
        given = s.get("dose_given") or s.get("dose")
        dose_sum = sum(d for _, d in ev if d) if ev else given
        after = ev[-1][0] if len(ev) > 1 else 0.0
        a = _auc_inf(s["points"], iv_bolus=(side == "IV" and not (s.get("infusion_h") or 0)), after=after)
        by_subject[subj][side] = {"profile": r["profile"], "dose_total": dose_sum, "n_doses": max(1, len(ev)), "nca": a}
    out = []
    for subj, d in sorted(by_subject.items()):
        if "IV" in d and "EV" in d and d["IV"]["nca"] and d["EV"]["nca"] and d["IV"]["dose_total"] and d["EV"]["dose_total"]:
            ratio = (d["EV"]["nca"]["auc_inf"] / d["EV"]["dose_total"]) / (d["IV"]["nca"]["auc_inf"] / d["IV"]["dose_total"])
            out.append({"animal": subj, "ev_profile": d["EV"]["profile"], "iv_profile": d["IV"]["profile"], "ratio": ratio,
                        "ev_n_doses": d["EV"]["n_doses"], "ev_tail_pct": d["EV"]["nca"]["tail_pct"], "iv_tail_pct": d["IV"]["nca"]["tail_pct"],
                        "ev_thalf_h": d["EV"]["nca"]["thalf_h"], "iv_thalf_h": d["IV"]["nca"]["thalf_h"]})
    if not out:
        return None
    rs = [x["ratio"] for x in out]
    gm = math.exp(sum(math.log(x) for x in rs) / len(rs))
    return {"label": "description, not an F estimate", "method": "AUC0-inf by linear-up/log-down trapezoids; lambda_z by the best adjusted R2 "
            "over >= 3 points after the last dose and the last peak; EV AUC0-inf divided by the total EV dose (all doses)",
            "animals": out, "median_ratio": statistics.median(rs), "range": [min(rs), max(rs)], "geometric_mean_ratio": gm,
            "above_1_25": gm > F_ABOVE or any(x > F_ABOVE for x in rs)}


def occasion_facts(rows, long_rows, ab, tables=()):
    analysed = {(r["route"], r["header"]): r["profile"] for r in rows}
    cols = {(t["dataset_id"], c["id"]): c for t in tables for c in t.get("columns", []) if c.get("meaning") == "CONCENTRATION"}
    from_input = {r["profile"]: cols.get((r["dataset_id"], r["column"]), {}) for r in rows}
    if from_input and all(str(c.get("subject_id") or "").strip() for c in from_input.values()):
        long_rows = [{"route": r["route"], "profile_id": r["header"], "in_analysis": "1",
                      "animal_id": str(from_input[r["profile"]]["subject_id"]), "occasion": str(from_input[r["profile"]].get("occasion") or "")}
                     for r in rows]
        basis = "EDA input (subject_id and occasion of each concentration column)"
        paired = {r["profile"]: from_input[r["profile"]].get("pairing_source") for r in rows
                  if from_input[r["profile"]].get("washout_verified") is True}
    else:
        basis = "case long table (animal_id and occasion columns)"
        paired = {}
    if long_rows is not None:
        by_profile = {}
        for x in long_rows:
            key = (x.get("route"), x.get("profile_id"))
            if key in analysed and x.get("in_analysis") == "1":
                by_profile[analysed[key]] = (x.get("animal_id") or "", x.get("occasion") or "", x.get("route"))
        animals = defaultdict(list)
        for profile, (animal, occasion, route) in sorted(by_profile.items()):
            if animal:
                animals[animal].append({"profile": profile, "route": route, "occasion": occasion})
        groups = []
        for i, (_, items) in enumerate(sorted(animals.items(), key=lambda kv: [p["profile"] for p in kv[1]]), 1):
            groups.append({"animal": f"animal {i}", "profiles": items})
        multi = [g for g in groups if len(g["profiles"]) > 1]
        cross = [g for g in multi if len({p["route"] for p in g["profiles"]}) > 1]
        occ = defaultdict(set)
        for g in groups:
            for p in g["profiles"]:
                occ[p["route"]].add(p["occasion"] or "not recorded")
        washout = (f"stated in the source for the {len(paired)} profiles of animals that received both routes"
                   if paired else "not stated in the inputs")
        return {"basis": basis, "n_profiles": len(rows),
                "n_profiles_with_animal": sum(len(g["profiles"]) for g in groups), "n_animals": len(groups),
                "n_animals_with_several_profiles": len(multi), "n_animals_with_several_routes": len(cross),
                "occasion_labels_by_route": {k: sorted(v) for k, v in sorted(occ.items())},
                "route_sets": dict(Counter(" + ".join(sorted({p["route"] for p in g["profiles"]})) for g in groups)),
                "animals": groups,
                "period_order": "Occasion labels are as recorded; the inputs do not state whether they give the period order.",
                "washout": washout, "paired_profiles": sorted(paired),
                "washout_source": sorted({v for v in paired.values() if v})}
    cards = [d["card"] for d in ab.get("datasets", [])]
    linked = sorted({c["cross_route_subject_id"] for c in cards if c.get("cross_route_subject_id")})
    return {"basis": "EDA input", "n_profiles": len(rows), "n_animals": None,
            "animal_identity": ("cross-route subject ids: " + ", ".join(linked)) if linked else
            "Animal identity across profiles is not encoded in the EDA input; each profile is its own subject there.",
            "washout": "verified" if any(c.get("washout_verified") for c in cards) else "not verified"}


def dose_facts(rows, long_rows):
    per_animal = defaultdict(list)
    codes = defaultdict(set)
    analysed = {(r["route"], r["header"]): r for r in rows}
    for x in long_rows or []:
        key = (x.get("route"), x.get("profile_id"))
        if key in analysed and x.get("in_analysis") == "1":
            r = analysed[key]
            try:
                per_animal[(r["route"], r["dose_mg_kg"])].append(float(x["dose_mg_kg"]))
            except (KeyError, ValueError, TypeError):
                pass
            if x.get("formulation_code"):
                codes[(r["route"], r["dose_mg_kg"])].add(x["formulation_code"])
    out = []
    for route in sorted({r["route"] for r in rows}):
        levels = Counter(r["dose_mg_kg"] for r in rows if r["route"] == route)
        entries = []
        for dose, n in sorted(levels.items(), key=lambda kv: (kv[0] is None, kv[0])):
            e = {"dose_mg_kg": dose, "n_profiles": n}
            vals = per_animal.get((route, dose)) or [r["dose_given_mg_kg"] for r in rows if r["route"] == route
                                                     and r["dose_mg_kg"] == dose and r.get("dose_given_mg_kg")]
            if vals:
                e["per_animal_mg_kg"] = [round(min(vals), 4), round(max(vals), 4)]
            if codes.get((route, dose)):
                e["formulation_codes"] = sorted(codes[(route, dose)])
            entries.append(e)
        notes = []
        doses = [e["dose_mg_kg"] for e in entries if e["dose_mg_kg"]]
        if len(entries) == 1:
            notes.append(f"One {route} dose level, so dose dependence cannot be checked within {route}.")
        elif doses:
            notes.append(f"Highest/lowest {route} dose ratio {_g(max(doses) / min(doses), 3)}.")
            sets = [tuple(e.get("formulation_codes", ())) for e in entries]
            if all(sets) and len(set(sets)) > 1:
                notes.append(f"The {route} dose levels differ in formulation code, so dose and formulation are not separated.")
        out.append({"route": route, "levels": entries, "notes": notes})
    return out


# ---------------------------------------------------------------- figures

# Modeling figures are EDA figures, redrawn without identity: no new plot type is drawn here.
# file prefix -> (section, panel ids, kind, EDA questions by label)
FIGURE_SOURCES = (
    ("B1ind_", "absorption", "B1ind", "extravascular individuals, semi-log",
     {"absorption": ["Onset and peak sampling", "Within-animal trough", "Half-life and window choice"]}),
    ("DIS1ind_", "distribution", "DIS-1a/1b individual layer", "intravenous individuals, linear and semi-log",
     {"distribution": ["Systemic disposition", "Evidence for the systemic shape"]}),
    ("Q5_", "absorption", "D1a", "extravascular against IV within animals, dose-normalized, semi-log",
     {"absorption": ["Flip-flop kinetics", "Shared one-compartment disposition"]}),
    ("D1d_", "absorption", "D1d", "extravascular and IV individuals without a verified within-animal pair, dose-normalized, semi-log (description)",
     {"absorption": ["Flip-flop kinetics", "Systemic bioavailability", "One multiplier between conditions"]}),
    ("D1_", "absorption", "D1", "extravascular against IV, dose-normalized, semi-log, with T4",
     {"absorption": ["Flip-flop kinetics", "Shared one-compartment disposition"]}),
    ("D2_", "absorption", "D2", "extravascular against IV, dose-normalized, linear, window AUC ratio",
     {"absorption": ["Systemic bioavailability"]}),
    ("Q6_", "absorption", "D2 within animals", "extravascular against IV within animals, window AUC ratio per animal",
     {"absorption": ["Systemic bioavailability"]}),
)


def _serves(questions, panel):
    return "; ".join(f"{sec}: {', '.join(q)}" for sec, q in questions.items()) + f" (EDA panel {panel})"


def _slug(text):
    return "".join(ch if ch.isalnum() else "-" for ch in str(text)).strip("-").lower() or "x"


def _file_stem(panel):
    """Panel label -> file-name part. Labels such as 'DIS-1a/1b' carry a slash, which must not reach a path."""
    return "_".join("".join(ch if ch.isalnum() or ch == "-" else " " for ch in str(panel)).split()) or "x"


def _figure_profiles(run, tables, ab):
    """EDA figure file -> the profiles (ROUTE/HEADER) it draws, and the species and route it belongs to."""
    route = {t["dataset_id"]: (t.get("metadata") or {}).get("route") for t in tables}
    species = {t["dataset_id"]: str((t.get("metadata") or {}).get("species") or "").strip().capitalize() for t in tables}
    head = column_headers(tables)
    cols = {t["dataset_id"]: [c["id"] for c in t.get("columns", []) if c.get("meaning") == "CONCENTRATION"] for t in tables}
    key = lambda did, col: f"{route.get(did)}/{head.get((did, col), col)}"
    out = {}
    for t in tables:
        did = t["dataset_id"]
        whole = [key(did, c) for c in cols[did]]
        out[f"B1ind_{did}.png"] = (whole, species[did], route[did])
        out[f"DIS1ind_{_slug(did)}.png"] = (whole, species[did], route[did])
    ivs = [(i["card"].get("source_dataset_id") or i["card"]["dataset_id"], i.get("series_id")) for i in ab.get("iv_references", [])]
    for d in ab.get("datasets", []):
        c = d["card"]
        did = c["dataset_id"]
        pairs = d.get("iv_pairs") or []
        if d.get("D1d"):
            paired = {r["ev_series"] for r in pairs}
            out[d["D1d"]] = ([key(did, s["series_id"]) for s in d["series"] if s["series_id"] not in paired]
                             + [key(i, col) for i, col in ivs if species.get(i) == species[did]], species[did], route[did])
    for r in ab.get("ev_iv", []):
        prof = [key(r["ev"], cols.get(r["ev"], [""])[0])] + [key(r["iv"].split("::")[0], r["iv"].split("::")[-1])]
        for k in ("D1", "D2"):
            if r.get(k):
                out[r[k]] = (prof, species.get(r["ev"]), route.get(r["ev"]))
    for b in ab.get("status_boards", []):
        for qn, panels in ((5, ["D1a"]), (6, ["D2"])):
            q = next((q for q in b.get("questions", []) if q["q"] == qn), None)
            prim = (q or {}).get("primary") or {}
            if prim.get("file") and prim.get("panels") == panels and str(prim["file"]).startswith(f"Q{qn}_"):
                ds = [d for d in ab.get("datasets", []) if d.get("iv_pairs") and d["card"]["study"] == b.get("study")]
                prof = [p for d in ds for r in d["iv_pairs"] if qn == 5 or r.get("window_auc_ratio") is not None
                        for p in (key(d["card"]["dataset_id"], r["ev_series"]), key(r["iv"].split("::")[0], r["iv"].split("::")[-1]))]
                if prof:
                    out[prim["file"]] = (prof, species.get(ds[0]["card"]["dataset_id"]), route.get(ds[0]["card"]["dataset_id"]))
    return out


def _forbidden(tables):
    words = set()
    for t in tables:
        meta = t.get("metadata") or {}
        words.update(str(x) for x in [t.get("dataset_id"), meta.get("drug")] + list(t.get("study_source_ids") or []) if x)
        for c in t.get("columns", []):
            if c.get("meaning") == "CONCENTRATION":
                words.update(str(x) for x in (c.get("id"), c.get("header")) if x)
    return sorted((w for w in words if len(w) >= 3), key=len, reverse=True)


def _blind(spec, words, title, pair_no=None):
    """A copy of one EDA figure spec with every identifying string removed; 'Animal <id>' becomes 'Pair k'."""
    import copy
    import re
    spec = copy.deepcopy(spec)
    hit = lambda text: any(w.casefold() in str(text).casefold() for w in words)
    for p in spec["panels"]:
        t = p.get("title") or ""
        m = re.search(r"\b[Aa]nimal (\S+?)(?=[:\s(]|$)", t)
        if m:
            t = t[:m.start()] + f"{'P' if t[m.start()] == 'A' else 'p'}air {(pair_no or {}).get(m.group(1), '?')}" + t[m.end():]
        p["title"] = "" if hit(t) else t
        if p.get("caption") and hit(p["caption"]):
            p["caption"] = None
        layers = []
        for layer in p.get("layers", []):
            if layer.get("kind") == "text" and hit(layer.get("label", "")):
                continue
            if layer.get("label") and hit(layer["label"]):
                layer["label"] = None
            layers.append(layer)
        p["layers"] = layers
        if not any(layer.get("label") for layer in layers):
            p["legend"] = "none"
    # S13 rule 9: the panels keep their standard titles; the figure title is used only when every panel title had to go
    spec["title"] = "" if any(p.get("title") for p in spec["panels"]) else title
    return spec


def render_figures(run, rows, species, tables=(), ab_result=None):
    """Blinded copies of the EDA figures that show the data to a modeler; drawn by the absorption renderer."""
    run = Path(run)
    engine = run / "_engine"
    sys.path.insert(0, str(engine if (engine / "eda_absorption.py").is_file() else HERE))
    import eda_absorption as ab
    out = run / "modeling_figures"
    out.mkdir(exist_ok=True)
    specs = {}
    for section in ("absorption", "distribution"):
        path = run / section / "plot_specs.json"
        if path.is_file():
            specs.update({(section, f["file"]): f for f in read(path).get("figures", [])})
    owners = _figure_profiles(run, tables, ab_result or {})
    pair_no = {}
    for d in (ab_result or {}).get("datasets", []):
        for r in d.get("iv_pairs") or []:
            pair_no.setdefault(str(r["subject_id"]), len(pair_no) + 1)
    words = _forbidden(tables)
    dose = {r["profile"]: r["dose_mg_kg"] for r in rows}
    made = []
    for (section, file), spec in sorted(specs.items()):
        src = next((x for x in FIGURE_SOURCES if file.startswith(x[0]) and x[1] == section), None)
        if not src or file not in owners:
            continue
        profiles_, sp, route = owners[file]
        if sp not in species or not profiles_:
            continue
        doses = sorted({dose.get(x) for x in profiles_ if x.startswith(f"{route}/") and dose.get(x)})
        dtext = f"{_g(doses[0])} mg/kg" if len(doses) == 1 else f"{_g(doses[0])}–{_g(doses[-1])} mg/kg" if doses else ""
        name = f"{_slug(sp)}_{_slug(route)}_{_file_stem(src[2])}_{len([m for m in made if m['panel'] == src[2] and m['route'] == route]) + 1}.png"
        title = f"{sp} · {route} · {len(profiles_)} profiles" + (f" ({dtext})" if dtext else "") + f" — {src[3]}"
        blinded = _blind(spec, words, title, pair_no)
        blinded["file"] = name
        ab._SPECS.append(blinded)
        made.append({"file": f"modeling_figures/{name}", "kind": src[3], "species": sp, "route": route, "panel": src[2],
                     "section": section, "profiles": profiles_, "questions": src[4], "serves": _serves(src[4], src[2])})
    if made:
        ab.render_all(out)
        engine_used = dict(ab._RENDER)
    else:
        engine_used = {"engine": "none"}
    for f in made:
        f["exists"] = (run / f["file"]).is_file()
    (out / "figures.json").write_text(json.dumps({"schema": SCHEMA, "figures": made}, indent=1, ensure_ascii=False), encoding="utf-8")
    return made, engine_used


# ---------------------------------------------------------------- assemble

def build(run, case=None, figures=True):
    run = Path(run)
    tables = read(run / "source_tables.json")
    dist = read(run / "distribution" / "distribution.json")
    ab = read(run / "absorption" / "absorption.json")
    long_rows, long_path = long_table(case)
    rows = profiles(tables, dist, ab)
    points = {s["sid"]: sorted((p["t"], p["c"]) for p in s["points"] if p["status"] == "QUANTIFIED" and p.get("c"))
              for s in dist.get("series", [])}
    for r in rows:
        r["_points"] = points.get(r["dataset_id"] + ":" + r["column"], [])
    tmeta = {t["dataset_id"]: {"lloq": (t.get("metadata") or {}).get("lloq_ug_mL")} for t in tables}
    species = sorted({r["species"] for r in rows})
    result = {"schema": SCHEMA, "about": "Data facts computed from the observations and the EDA readings; no model fitted, "
                                         "no drug or study identity. Profiles are <route>/<source column header>.",
              "inputs": {"source_tables_sha256": sha(run / "source_tables.json"),
                         "long_table": {"file": long_path.name, "sha256": sha(long_path)} if long_path else None},
              "species": []}
    figs, engine = (render_figures(run, rows, species, tables, ab) if figures else ([], {"engine": "not requested"}))
    for sp in species:
        sp_rows = [r for r in rows if r["species"] == sp]
        result["species"].append({
            "species": sp,
            "profiles": [{k: v for k, v in r.items() if not k.startswith("_") and k != "times_h"} for r in sp_rows],
            "phase_summary": phase_summary(sp_rows),
            "blq": blq_facts(sp_rows, dist, long_rows, tmeta, tables),
            "occasions": occasion_facts(sp_rows, long_rows, ab, tables),
            "cross_occasion_exposure": cross_occasion_facts(sp_rows, dist, tables),
            "doses": dose_facts(sp_rows, long_rows),
            "plain": plain_summary(sp, dist, ab),
            "figures": [f for f in figs if f["species"] == sp]})
    result["figure_render"] = engine
    return result


def plain_summary(species, dist, ab):
    """Shared rule 10: the 'taken together' readings of Distribution and Absorption for this species, in plain words (no study names)."""
    key = str(species).strip().lower()
    out = []
    for label, boards, sp_key in (("Distribution", (dist or {}).get("boards") or [], "species"),
                                  ("Absorption", (ab or {}).get("status_boards") or [], "species_group")):
        for b in boards:
            if str(b.get(sp_key) or b.get("species") or "").strip().lower() != key:
                continue
            h = (b.get("hypothesis") or {}).get("plain")
            if h and f"{label}: {h['shows']} {h['suggests']}" not in out:
                out.append(f"{label}: {h['shows']} {h['suggests']}")
    return out


def phase_summary(rows):
    out = {}
    for route in sorted({r["route"] for r in rows}):
        rr = [r for r in rows if r["route"] == route]
        if rr[0]["route_class"] == "IV":
            out[route] = {"n_profiles": len(rr), "readings": dict(Counter(r["phases"]["reading"] for r in rr)),
                          "input_end_unknown": any(r.get("iv_mode") in ("INFUSION_TIMING_UNKNOWN", "IV_MODE_UNKNOWN") for r in rr),
                          "first_sample_h": _range(r["phases"]["first_sample_h"] for r in rr),
                          "n_with_later_part_start": sum(r["phases"].get("later_part_from_h") is not None for r in rr),
                          "n_before_later_part": _range(r["phases"].get("n_before_later_part") for r in rr),
                          "later_part_from_h": _range(r["phases"].get("later_part_from_h") for r in rr)}
        else:
            out[route] = {"n_profiles": len(rr), "first_sample_h": _range(r["phases"].get("first_sample_h") for r in rr),
                          "sampled_peak_h": _range(r["phases"].get("sampled_peak_h") for r in rr),
                          "n_before_peak": _range(r["phases"].get("n_before_peak") for r in rr),
                          "ka_not_identifiable": sorted(r["profile"] for r in rr if any("KA_NOT_IDENTIFIABLE" in n for n in r["notes"])),
                          "with_terminal_window": sum(r["phases"].get("n_terminal_window") is not None for r in rr),
                          **({"first_dose_interval_only": True} if any(r.get("first_interval_end_h") is not None for r in rr) else {})}
    return out


def text(result):
    lines = ["EDA DATA FACTS (computed from the observations and the EDA readings; no model fitted)"]
    for sp in result["species"]:
        rows = sp["profiles"]
        routes = Counter(r["route"] for r in rows)
        levels = Counter(r["level"] for r in rows)
        lines.append(f"Species: {sp['species']}. Profiles: " + ", ".join(f"{k} {v}" for k, v in sorted(routes.items()))
                     + " (" + ", ".join(f"{k.lower().replace('_', ' ')} {v}" for k, v in sorted(levels.items())) + ").")
        if sp.get("plain"):
            lines.append("In plain words:")
            lines.extend("  " + x for x in sp["plain"])
        dose_bits = []
        for d in sp["doses"]:
            lv = "; ".join(f"{_g(e['dose_mg_kg'])} mg/kg (" + f"{e['n_profiles']} profile{'s' if e['n_profiles'] != 1 else ''}"
                           + (f", per animal {_g(e['per_animal_mg_kg'][0])}–{_g(e['per_animal_mg_kg'][1])}"
                              if e.get("per_animal_mg_kg") and e["per_animal_mg_kg"][0] != e["per_animal_mg_kg"][1] else "")
                           + (f", formulation code {'/'.join(e['formulation_codes'])}" if e.get("formulation_codes") else "") + ")"
                           for e in d["levels"])
            dose_bits.append(f"  {d['route']}: {lv}." + "".join(" " + n for n in d["notes"]))
        lines.append("Dose levels:")
        lines.extend(dose_bits)
        o = sp["occasions"]
        xo = sp.get("cross_occasion_exposure")
        if xo:
            more = [x for x in xo["animals"] if x["ratio"] > F_ABOVE]
            xo_lines = [f"Cross-occasion exposure ({xo['label']}): (AUC0–∞/ΣD of the extravascular regimen) / (AUC0–∞/D IV) per animal "
                        + ", ".join(f"{x['animal']} {_g(x['ratio'])}" for x in xo["animals"])
                        + f"; median {_g(xo['median_ratio'])}, geometric mean {_g(xo['geometric_mean_ratio'])}. Tail extrapolated: EV "
                        + _range(x["ev_tail_pct"] for x in xo["animals"]) + " %, IV " + _range(x["iv_tail_pct"] for x in xo["animals"])
                        + " %. Apparent t½: EV after the last dose " + _range(x["ev_thalf_h"] for x in xo["animals"]) + " h, IV "
                        + _range(x["iv_thalf_h"] for x in xo["animals"]) + " h."]
            if xo["geometric_mean_ratio"] > F_ABOVE or more:
                top = xo["geometric_mean_ratio"] if xo["geometric_mean_ratio"] > F_ABOVE else max(x["ratio"] for x in more)
                who = "" if xo["geometric_mean_ratio"] > F_ABOVE else " (" + ", ".join(x["animal"] for x in more) + ")"
                xo_lines.append(f"  Apparent F above 1 ({_g(top)}){who}: the two occasions do not share clearance, or the inputs are not "
                                "comparable; F is not interpretable.")
        else:
            xo_lines = []
        if o.get("n_animals"):
            pattern = "; ".join(f"{k}: {v} animal{'s' if v != 1 else ''}" for k, v in sorted(o["route_sets"].items()))
            lines.append(f"Animals and occasions ({o['basis']}): {o['n_profiles_with_animal']} profiles from {o['n_animals']} animals; "
                         f"{o['n_animals_with_several_profiles']} animals have more than one profile, {o['n_animals_with_several_routes']} "
                         f"have more than one route. Routes per animal: {pattern}. Occasion labels by route: "
                         + ", ".join(f"{k} {'/'.join(v)}" for k, v in o["occasion_labels_by_route"].items())
                         + f". {o['period_order']} Washout: {o['washout']}.")
            for g in o["animals"]:
                if len(g["profiles"]) > 1:
                    lines.append(f"  {g['animal']}: " + ", ".join(f"{p['profile']} (occasion {p['occasion'] or 'not recorded'})" for p in g["profiles"]))
        else:
            lines.append(f"Animals and occasions: {o.get('animal_identity')} Washout: {o.get('washout')}.")
        lines.extend(xo_lines)
        b = sp["blq"]
        lines.append("BLQ: " + "; ".join(f"{x['route']} {x['n_blq']}/{x['n_samples']} samples"
                                         + (f" ({x['n_blq_after_last_quantified']} after the last quantified sample)" if x["n_blq"] else "")
                                         + (f", {x['n_author_excluded']} author-excluded" if x["n_author_excluded"] else "")
                                         + (f"; {x['n_blq_author_flagged']} of the BLQ samples also excluded by the source authors"
                                            if x.get("n_blq_author_flagged") else "")
                                         for x in b["by_route"]) + f". {b['basis']} LLOQ: "
                     + (", ".join(b["lloq_reported"]) if isinstance(b["lloq_reported"], list) else b["lloq_reported"]) + ".")
        for x in b["by_route"]:
            if x["n_blq"]:
                lines.append(f"  {x['route']} BLQ by time bin: " + ", ".join(
                    f"{_g(c['from_h'])}–{_g(c['to_h']) if c['to_h'] is not None else ''} h {c['n_blq']}/{c['n_samples']}"
                    for c in x["bins"] if c["n_blq"]))
        lines.append("Points per phase:")
        for route, s in sp["phase_summary"].items():
            if "readings" in s:
                lines.append(f"  {route} ({'reported time; the end of the IV input is not recorded' if s.get('input_end_unknown') else 'time after start of dosing'}): readings " + ", ".join(f"{k} {v}" for k, v in s["readings"].items())
                             + f"; first sample {s['first_sample_h']} h; start of the later part found in {s['n_with_later_part_start']}/{s['n_profiles']} profiles"
                             + (f" (from {s['later_part_from_h']} h; points before it {s['n_before_later_part']})" if s["n_with_later_part_start"] else "") + ".")
            else:
                lines.append(f"  {route} (time after dose{', first dose interval' if s.get('first_dose_interval_only') else ''}): first sample {s['first_sample_h']} h; sampled peak {s['sampled_peak_h']} h; "
                             f"points before the peak {s['n_before_peak']}; terminal window in {s['with_terminal_window']}/{s['n_profiles']} profiles"
                             + (f"; KA_NOT_IDENTIFIABLE: {', '.join(s['ka_not_identifiable'])}" if s["ka_not_identifiable"] else "") + ".")
        for r in rows:
            lines.append(f"  {r['profile']}: {r['n_quantified']} quantified points. " + " ".join(r["notes"]))
        if sp["figures"]:
            lines.append("Figures:")
            for k, f in enumerate(sp["figures"], 1):
                # The file name stays in figures.json; the text names the figure by number so it carries no file names.
                lines.append(f"  Figure {k}: {f['kind']}" + (f" ({f['route']})" if f.get("route") else "") + f"; serves {f['serves']}.")
    return "\n".join(lines) + "\n"


def write(run, case=None, figures=True):
    result = build(run, case, figures)
    run = Path(run)
    (run / "modeling_facts.json").write_text(json.dumps(result, indent=1, ensure_ascii=False, default=float), encoding="utf-8")
    (run / "modeling_facts.txt").write_text(text(result), encoding="utf-8")
    return result


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("run", type=Path)
    ap.add_argument("--case", type=Path, default=None)
    ap.add_argument("--no-figures", action="store_true")
    a = ap.parse_args()
    write(a.run, a.case, not a.no_figures)
