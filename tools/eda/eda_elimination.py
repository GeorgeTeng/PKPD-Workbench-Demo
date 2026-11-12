"""EDA Elimination and metabolism section (items 29-36; rules version in rules/rules_manifest.json), host code only.

Reads an EDA run root (``source_tables.json``; ``absorption/absorption.json`` and ``distribution/distribution.json`` when
present; optional ``elimination_config.json``) and writes ``<root>/elimination/``:

* ``elimination.json``  every computed value, label, reason, upstream reference and hand-off record (E0.9);
* ``EM*_*.png``         urinary recovery, renal clearance, recovery by route, and matched in vitro comparisons;
* ``index.html``, ``species-*.html``, ``conditions-and-species.html``, ``figure-guide.html``  the Elimination pages;
* ``elimination_config.template.json``  the run settings of rules section B.7 (GFR, fu,p override, assay, collection).

Reuse rule (E0.11, B.9). Plasma questions read the absorption and distribution records by ID and version. The window AUC
of item 29 is the upstream A0.6 value when absorption holds it for the same profile; otherwise the same A0.6 routine
(``eda_absorption.auc``) is applied to the observed points. Upstream panels (B1, C2, E1, DIS-1a, DIS-2b, DIS-4c ...)
are linked, never redrawn. Q2 and Q3 take their test status from the upstream record.

Not computed (E0.7): terminal slope or half-life fits, AUC to infinity, excretion asymptotes, sigma-minus plots,
formation constants, IVIVE, allometry, metabolite/parent ratios, TR-derived parent CL. Formal exclusions come only from
T10 and the reused T3, T3p, T7, T9. T11 and item 32 are reserved. T12 is a data check.
"""
from __future__ import annotations

import hashlib
import html
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path

try:  # inside the pipeline package
    from . import eda_absorption as ab
    from . import eda_distribution as dist
except Exception:  # noqa: BLE001 - standalone use next to eda_absorption.py and eda_distribution.py
    import eda_absorption as ab  # type: ignore
    import eda_distribution as dist  # type: ignore


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


RULES = _eda_common().rules_entry("elimination")  # the one rules version for this section: rules/rules_manifest.json
RULES_VERSION = RULES["version"]
FIT_NOTE = _eda_common().FIT_NOTE

VERSION = "EDA_ELIMINATION_ANIMAL_CONTRASTS_20261111"
Q1_AMENDMENT = "EDA_elimination_Q1_observed_AUC.md"
Q2_AMENDMENT = "EDA_elimination_Q2_dose_proportionality.md"
Q3_AMENDMENT = "EDA_elimination_Q3_reported_occasions.md"
Q5_AMENDMENT = "EDA_elimination_Q5_urinary_evidence.md"
Q6_AMENDMENT = "EDA_elimination_Q6_recovery_display.md"
Q7_AMENDMENT = "EDA_elimination_Q7_components_and_systems.md"
SPECIES_AMENDMENT = "EDA_elimination_EM8a_common_windows.md"
REPORTED_DOSE_AMENDMENT = "EDA_elimination_reported_parameter_doses.md"
REPORTED_CONTEXT_AMENDMENT = "EDA_reported_parameter_route_matrix_phase.md"

TOL = dist.TOL                 # A0.4 project-set relative error for values without a reported error
H_PER_MIN = 1 / 60.0
ML_MIN_KG_PER_L_H_KG = 1000 / 60.0   # 1 L/h/kg = 16.667 mL/min/kg (E0.8: 1 mL/min/kg = 0.06 L/h/kg)

ST_YES, ST_PART, ST_NO, ST_NA = ab.ST_YES, ab.ST_PART, ab.ST_NO, ab.ST_NA
ST_CODE = ab.ST_CODE
INK, INK2, MUTED, SURF = ab.INK, ab.INK2, ab.MUTED, ab.SURF
BLUE, ORANGE, GREEN, PURPLE = ab.BLUE, ab.ORANGE, ab.GREEN, ab.PURPLE
GRAY = "#8a9aa6"
CAT = dist.CAT
_e, _f, _slug, _wb = ab._e, ab._f, ab._slug, ab._wb
_num = dist._num

DEFAULT_CONFIG = {
    "_about": (f"Run configuration for the Elimination section (rules {RULES_VERSION}, section B.7). Every value needs a source specific to the "
               "comparison it enters. Leave a field empty when no sourced value exists: the dependent result is then reported as "
               "not assessable and the continuous measurement is still shown. Nothing physiological is assumed by default."),
    "late_increment_share": 0.05,   # adopted 2026-11-10: descriptive label 'small last increment' only
    "recovery_review_tolerance_pp": None,   # proposal (5 pp); empty = tolerance unknown, point discrepancies are kept
    "gfr": {"_example_S01|Rat": {"gfr_ml_min_kg": None, "low": None, "high": None, "method": "", "kidney_function": "",
                             "matched_to_study": False, "source": ""}},
    "fu_p": {"_example_S01|Dog": {"low": None, "high": None, "constant_over_exposure": False, "method": "", "source": ""}},
    "reported_iv_clearance_contrasts": [],
    "renal_filtration_comparison": {"_example_S01|Rat": {
        "urine_dataset": "", "plasma_dataset": "", "interval_h": [], "design_source": "",
        "prespecified": False, "independent_animals": False, "physiology_matched": False,
        "fu_constant_over_interval": False, "animals": [
            {"animal_id": "", "gfr_ml_min_kg": None, "fu_p": None, "gfr_source": "", "fu_source": ""}]}},
    "assay_by_dataset": {"_example_T0004": {"assay": "SPECIFIC, MICROBIOLOGICAL, RADIOACTIVITY or NOT_REPORTED", "source": ""}},
    "reported_clearance_links": {"_example_profile:series": [
        {"parameter_cell": "dataset:record:column", "profile_item": "source figure ID",
         "parameter_item": "source table ID", "source": "Citation and location linking this series to the parameter estimate"}]},
    "collection": {"_example_T0004": {"bladder_emptying": "", "collection_complete": "YES or NO", "cagewash": "ALLOCATED, SEPARATE or NOT_REPORTED",
                                      "animals": "INTACT or BILE_CANNULATED", "pairing": "SAME_ANIMAL, PARALLEL_COHORT_SAME_STUDY, OTHER_STUDY or NOT_REPORTED",
                                      "cohort_id": "", "stability": "", "sample_loss_to_container": "ADDRESSED, RISK_SOURCED or NOT_REPORTED", "source": ""}},
    "excreta_layout": {"_example_T0099": {"layout": "INTERVAL_COLUMNS, SAMPLE_ROWS, COMPONENT_ROWS or QUANTITY_ROWS_BY_ANIMAL", "source": ""}},
    "show_sensitivity_rows": False,
}


def load_config(root):
    p = Path(root) / "elimination_config.json"
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
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
        cfg["_loaded_from"] = p.name
    return cfg


# ---------------------------------------------------------------- parsing helpers

_DASH = re.compile(r"^\s*[—–\-−]+\s*$")
_FOOT = re.compile(r"\s*(?:\b([a-z])\)|\*+)\s*$")
_ND = re.compile(r"^\s*(?:n\.?\s*d\.?|not detected|nd|<\s*ll?oq|blq|below)", re.I)
_NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
_CENSOR_VALUE = re.compile(rf"^(<=|>=|<|>|≤|≥)\s*({_NUMBER})\s*(.*?)$")
_INTERVAL = re.compile(r"(\d+(?:\.\d+)?)\s*(?:[-–~]|to)\s*(\d+(?:\.\d+)?)\s*(h|hr|hrs|hours?|min|mins|minutes?|d|days?)\b", re.I)
_UNIT_H = {"h": 1.0, "hr": 1.0, "hrs": 1.0, "hour": 1.0, "hours": 1.0, "min": H_PER_MIN, "mins": H_PER_MIN, "minute": H_PER_MIN,
           "minutes": H_PER_MIN, "d": 24.0, "day": 24.0, "days": 24.0}


def parse_cell(raw, status=None):
    """Read a source cell, keeping printed censoring limits separate from quantified values."""
    out = {"value": None, "sd": None, "state": "MISSING", "foot": None, "raw": raw}
    status = str(status or "").strip().upper()
    if status.startswith(("MISSING", "EMPTY_SLOT", "NOT_SAMPLED", "NOT_APPLICABLE", "NOT_COLLECTED", "QUARANTINED")):
        return out
    if status in {"BLQ", "BQL", "BELOW_LLOQ", "NOT_DETECTED", "CENSORED"}:
        out["state"] = "CENSORED" if status == "CENSORED" else "NOT_DETECTED"
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return out
    if isinstance(raw, (int, float)) and not isinstance(raw, bool) and out["state"] == "MISSING":
        out.update(value=float(raw), state="QUANTIFIED")
        return out
    txt = str(raw).replace("，", ",").replace("。", ".").strip()
    feet = re.findall(r"\b([a-z])\)", txt)
    out["foot"] = feet[-1] if feet else None
    core = re.sub(r"\b[a-z]\)", "", txt).replace("*", "").strip()
    limit = _CENSOR_VALUE.fullmatch(core)
    if limit:
        relation, number, unit = limit.groups()
        out["state"] = "NOT_DETECTED" if out["state"] == "NOT_DETECTED" and relation in ("<", "<=", "≤") else "CENSORED"
        out["censoring"] = {"relation": relation, "threshold": float(number), "unit_as_printed": unit or None}
        return out
    if out["state"] != "MISSING":
        return out  # a numeric placeholder without a printed inequality provides no assay threshold
    if _DASH.match(core) or not core:
        out["state"] = "MISSING"
        return out
    if _ND.match(core):
        out["state"] = "NOT_DETECTED"
        return out
    m = re.match(r"^\s*([-+]?\d+(?:\.\d+)?)\s*(?:±|\+/-|\+-)\s*(\d+(?:\.\d+)?)", core.replace(",", ""))
    if m:
        out.update(value=float(m.group(1)), sd=float(m.group(2)), state="QUANTIFIED")
        return out
    m = re.match(rf"^\s*(?:about|approx\.?|~)?\s*({_NUMBER})", core.replace(",", ""), re.I)
    if m:
        out.update(value=float(m.group(1)), state="QUANTIFIED" if re.fullmatch(rf"\s*{_NUMBER}\s*%?\s*", core.replace(",", "")) else "TEXT")
        return out
    out["state"] = "TEXT"
    return out


def _record_cell(record, column):
    status = (record.get("value_status") or {}).get(column)
    raw = (record.get("source_raw_values") or {}).get(column, record.get(column))
    return parse_cell(raw, status)


def parse_interval(text):
    """'0-6 h' -> (0, 6) in hours; None when no interval is printed."""
    m = _INTERVAL.search(str(text or ""))
    if not m:
        return None
    f = _UNIT_H.get(m.group(3).lower(), 1.0)
    a, b = float(m.group(1)) * f, float(m.group(2)) * f
    return (a, b) if b > a else None


def footnotes(text):
    """'a) not tested; b) 0-8 h urine.' -> {'a': 'not tested', 'b': '0-8 h urine'}"""
    out = {}
    for m in re.finditer(r"(?:^|[\s;(:])([a-z])\)\s*([^;\n]+?)(?=(?:;|\.\s|\.$|\n|\s[a-z]\)\s|$))", str(text or "")):
        out.setdefault(m.group(1), m.group(2).strip())
    return out


def dispersion_kind(text):
    s = str(text or "").lower()
    if re.search(r"unspecified|unknown|unclear|not (?:specified|reported|identified|stated|defined)", s):
        return "UNKNOWN"
    se = bool(re.search(r"standard error|\bs\.?e\.?m?\b", s))
    sd = bool(re.search(r"standard deviation|\bs\.?d\.?\b", s))
    return ("SD" if sd else "SE") if sd != se else "UNKNOWN"


def _declared_dispersion(entry, header="", marked_note=""):
    """Use the experimental-unit declaration, unqualified table-wide notes, or this cell's own legend."""
    statements = []
    for chunk in re.split(r"[;\n]|(?<=[a-z])\.\s+", str(entry.get("notes") or ""), flags=re.I):
        clause = chunk.strip(" -.\t")
        # A note about a figure, matrix, time point or separate endpoint is not a table-wide legend.
        if re.fullmatch(r"(?:(?:all |table )?(?:values|data|results)(?: in (?:this|the) table)?\s+(?:(?:are|were)\s+)?"
                        r"(?:(?:reported|shown|expressed|presented)\s+as\s+)?)?"
                        r"means?\s*(?:±|\+/-|\+-|\()\s*(?:s\.?[ed]\.?m?\.?|standard (?:error|deviation))\)?"
                        r"(?:\s+of\s+\d+\s+(?:animals|rats|dogs|monkeys|mice|rabbits))?\.?", clause, re.I):
            statements.append(clause)
        elif re.fullmatch(r"(?:the )?(?:table |reported )?dispersion(?: type)? (?:is |was )?"
                          r"(?:unknown|unreported|unspecified|not (?:reported|specified|stated))", clause, re.I) or re.fullmatch(
                              r"(?:all values (?:are )?)?means?\s*(?:±|\+/-)\s*(?:SD\s*(?:or|/)\s*SE|SE\s*(?:or|/)\s*SD)"
                              r"(?:\s+(?:not specified|not stated)(?: in the table)?)?", clause, re.I):
            statements.append("unknown")
    unit = str(entry.get("experimental_unit") or "")
    if not re.search(r"\b(?:fig(?:ure)?\.?\s*\d+|plot|other table)\b", unit, re.I):
        statements.append(unit)
    statements.extend([header, marked_note])
    declared = {dispersion_kind(text) for text in statements
                if re.search(r"\bs\.?[ed]\.?m?\b|standard (?:error|deviation)|\bunknown\b", text, re.I)}
    return declared.pop() if len(declared) == 1 else "UNKNOWN"


def n_from(text):
    m = re.search(r"\(\s*n\s*=\s*(\d+)\s*\)|\bn\s*=\s*(\d+)|\bof\s+(\d+)\s+(?:rats|mice|dogs|monkeys|animals|rabbits)|\((\d+)\)\s*$", str(text or ""), re.I)
    if not m:
        return None
    return int(next(g for g in m.groups() if g))


def species_of(text):
    t = str(text or "")
    sp = dist.species_in(t)
    if sp:
        return sp
    m = re.match(r"^\s*(rabbi|guinea|monk|mous|beagle|swine|pig)\w*", t, re.I)   # truncated or misspelled source labels
    if m:
        return dist.species_in({"rabbi": "rabbit", "guinea": "guinea pig", "monk": "monkey", "mous": "mouse", "beagle": "dog",
                                "swine": "pig", "pig": "pig"}[m.group(1).lower()]) or None
    return None


def _entry_text(e):
    meta = e.get("metadata", {})
    return " ".join(str(x or "") for x in (e.get("title"), e.get("notes"), e.get("experimental_unit"), meta.get("exposure_basis"),
                                            meta.get("analyte"), meta.get("matrix"), meta.get("dosing_regimen"), meta.get("record_level")))


def _study(e):
    return ",".join(e.get("study_source_ids") or []) or "study not stated"


def _restrictions(e):
    return [{"operation": r.get("operation"), "reason": (r.get("reasons") or [""])[0]} for r in e.get("operation_restrictions", [])]


def _conflict_reasons(e):
    return [r["reason"] for r in _restrictions(e) if "SOURCE_CONFLICT" in r["reason"] or "inconsistent" in r["reason"].lower()]


EXCRETA = [("CAGEWASH", r"cage\s*-?\s*wash|cage rinse"), ("FAECES", r"\bf(?:a)?eces\b|\bf(?:a)?ecal\b|\bstool"), ("BILE", r"\bbil(?:e|iary)\b"),
           ("EXPIRED_AIR", r"expired air|exhaled|\bco2\b"), ("CARCASS", r"carcass"), ("TISSUE_RESIDUE", r"tissue residue"),
           ("URINE", r"\burin(?:e|ary)\b")]


def excretum_of(text):
    s = str(text or "").lower()
    if re.search(r"total recovery|overall recovery|total excretion|\btotal\b", s) and not re.search(r"urin|f(?:a)?ec|bile|carcass|cage", s):
        return "TOTAL"
    hits = [k for k, p in EXCRETA if re.search(p, s)]
    if len(hits) > 1:
        return "+".join(hits)
    return hits[0] if hits else None


def analyte_kind(text, drug=""):
    s = str(text or "").lower()
    if re.search(r"14\s*c|radioactiv|\btr\b|\bdpm\b|mg\s*eq|µg\s*eq|ug\s*eq", s):
        return "TOTAL_RADIOACTIVITY"
    if re.search(r"unknown|unidentified|unassigned|peak\s*\d+\s*(?:\(unknown\))?$", s):
        return "UNRESOLVED_COMPONENT"
    if drug and re.search(re.escape(drug.lower().split(";")[0].strip()), s) or re.search(r"unchanged|parent", s):
        return "PARENT"
    if re.search(r"^\s*total\b", s):
        return "TOTAL"
    return "NAMED_COMPONENT"


def assay_of(e, cfg, matrix_word="urine"):
    """E0.2 gate 3. Returns (assay, note). A study note that names a bioassay only for plasma does not set the urine assay."""
    over = (cfg.get("assay_by_dataset") or {}).get(e["dataset_id"])
    if over and over.get("assay") and over.get("source"):
        binding = over.get("match", {})
        fields = {"study": _study(e), "drug": e.get("metadata", {}).get("drug"),
                  "source_item_id": e.get("source_item_id")}
        hashes = {r.get("sha256") for r in e.get("source_refs", [])}
        if all((value in hashes if key == "source_sha256" else fields.get(key) == value)
               for key, value in binding.items()):
            return over["assay"].upper(), f"declared in the run configuration ({over['source']})"
    # Process fields separately: the title's matrix cannot qualify an unrelated method in the notes.
    for field in ("notes", "title", "experimental_unit"):
        for clause in re.split(r"[;\n]|(?<=\.)\s+", e.get(field) or ""):
            if matrix_word not in clause.lower() and re.search(r"plasma|serum|blood|tissue|homogenate|urine", clause, re.I):
                continue
            if re.search(r"bioassay|microbiolog|agar diffusion|disc[- ]plate|cup[- ]plate", clause, re.I):
                return "MICROBIOLOGICAL", f"source note: '{clause.strip()[:160]}'"
            if re.search(r"\bhplc\b|lc[-/]ms|chromatograph|radioimmunoassay|\bria\b", clause, re.I):
                return "SPECIFIC", f"source note: '{clause.strip()[:160]}'"
    if re.search(r"14\s*c|radioactiv", _entry_text(e), re.I):
        return "RADIOACTIVITY", "radiolabel study"
    return "NOT_REPORTED", "assay not stated in the table record"


def _collection(e, cfg):
    over = dict((cfg.get("collection") or {}).get(e["dataset_id"]) or {})
    text = _entry_text(e).lower()
    card = {"bladder_emptying": over.get("bladder_emptying") or "not reported",
            "collection_complete": over.get("collection_complete") or "not reported",
            "cagewash": over.get("cagewash") or ("SEPARATE" if "cagewash" in text or "cage wash" in text else "NOT_REPORTED"),
            "animals": over.get("animals") or ("BILE_CANNULATED" if re.search(r"bile[- ]duct[- ]cannul|bile[- ]cannul", text) else ("INTACT" if "intact" in text else "not reported")),
            "pairing": over.get("pairing") or "NOT_REPORTED",
            "cohort_id": over.get("cohort_id") if over.get("source") else None,
            "stability": over.get("stability") or "not reported",
            "sample_loss_to_container": over.get("sample_loss_to_container") or "NOT_REPORTED",
            "pooling": "pooled" if "pool" in text else "not reported",
            "source": over.get("source") or ("run configuration" if over else "source table")}
    return card


def _level_of(e):
    s = (str(e.get("experimental_unit") or "") + " " + str(e.get("metadata", {}).get("record_level") or "")).lower()
    if "individual" in s and "mean" in s:
        return "MIXED"
    if "individual" in s:
        return "INDIVIDUAL"
    if "mean" in s or "group" in s:
        return "GROUP_MEAN"
    return "NOT_REPORTED"


# ---------------------------------------------------------------- excreta tables -> observation rows (E0.8 fields)

def _cols(e):
    return e.get("columns", [])


def _first_col(e):
    cs = _cols(e)
    return cs[0] if cs else None


def detect_layout(e, cfg):
    over = (cfg.get("excreta_layout") or {}).get(e["dataset_id"])
    if over and over.get("layout"):
        return over["layout"].upper(), "declared in the run configuration"
    cs = _cols(e)
    if not cs:
        return None, "no columns"
    h0 = str(cs[0].get("header", "")).lower()
    if re.search(r"animal|subject|\bno\.?\b", h0) and any(re.fullmatch(r"\s*\d+\s*", str(c.get("header", ""))) for c in cs[1:]):
        return "QUANTITY_ROWS_BY_ANIMAL", "first column names the quantity, other columns are animals"
    if re.search(r"component|compound|metabolite|peak|analyte", h0):
        return "COMPONENT_ROWS", "first column names components"
    if any(re.search(r"\bsample\b|excret|specimen", str(c.get("header", "")), re.I) for c in cs):
        return "SAMPLE_ROWS", "one row per excretum"
    if any(parse_interval(c.get("header")) for c in cs[1:]):
        return "INTERVAL_COLUMNS", "one column per collection interval"
    return None, "layout not recognized; declare it under excreta_layout in elimination_config.json"


def _table_context(e, cfg):
    meta = e.get("metadata", {})
    text = _entry_text(e)
    dose, dose_from = dist._dose(e)
    assay, assay_note = assay_of(e, cfg)
    feet = footnotes(e.get("notes", "") + "\n" + str(e.get("experimental_unit") or ""))
    return {"dataset_id": e["dataset_id"], "title": e.get("title"), "study": _study(e), "drug": str(meta.get("drug") or ""),
            "species_text": str(meta.get("species") or e.get("group") or ""), "table_species": species_of(meta.get("species") or e.get("group")),
            "route_class": meta.get("route_class") or "NOT_FOUND", "route_detail": meta.get("route_detail") or "NOT_FOUND",
            "condition": meta.get("condition") or meta.get("treatment_group"),
            "matching_identity": {key: meta.get(key, e.get(key)) for key in
                                  ("cohort", "cohort_id", "arm", "arm_id", "experiment_arm", "experiment_arm_id")},
            "source_item": e.get("source_item_id") or e.get("source_refs"),
            "dose": dose, "dose_from": dose_from, "dose_basis": meta.get("dose_basis") or "NOT_FOUND",
            "regimen": str(meta.get("dosing_regimen") or ""), "matrix": str(meta.get("matrix") or ""),
            "excretum_default": excretum_of(meta.get("matrix")) or excretum_of(e.get("title")) or "URINE",
            "analyte_text": str(meta.get("analyte") or ""), "exposure_basis": str(meta.get("exposure_basis") or ""),
            "assay": assay, "assay_note": assay_note, "collection": _collection(e, cfg), "level": _level_of(e),
            "dispersion": _declared_dispersion(e),
            "footnotes": feet, "conflicts": _conflict_reasons(e), "restrictions": _restrictions(e),
            "radiolabel": bool(re.search(r"14\s*c|\[14c\]|radiolab", text, re.I)), "notes": e.get("notes") or "",
            "repeat": bool(re.search(r"/\s*day|daily|\bdays?\s+\d+\s+and\s+\d+|repeated", text, re.I))}


def _obs(ctx, rec, **kw):
    o = {"obs_id": None, "dataset_id": ctx["dataset_id"], "record_id": rec.get("record_id"), "study": ctx["study"],
         "species": ctx["table_species"], "group": None, "excretum": ctx["excretum_default"], "analyte": "PARENT", "component": None,
         "assay": ctx["assay"], "interval": None, "interval_text": "", "amount_basis": "INTERVAL", "value_form": "PERCENT_OF_DOSE",
         "denominator": "administered dose", "value": None, "sd": None, "state": "MISSING", "raw": None, "occasion": "FIRST_DOSE",
         "animal": None, "cohort_id": rec.get("cohort_id"), "level": ctx["level"], "n": None, "unit": "% of dose", "flags": [], "note": ""}
    o.update(kw)
    o["obs_id"] = f'{ctx["dataset_id"]}:{rec.get("record_id")}:{kw.get("col", "")}'
    o.pop("col", None)
    if o["analyte"] == "TOTAL_RADIOACTIVITY" and "TR_NOT_PARENT" not in o["flags"]:
        o["flags"].append("TR_NOT_PARENT")
    if o["assay"] == "MICROBIOLOGICAL" and o["analyte"] == "PARENT":
        o["analyte"] = "ACTIVE_MATERIAL"
        o["flags"].append("ACTIVE_MATERIAL_ASSAY")
    if ctx["conflicts"]:
        sp = (o["species"] or "").lower()
        hit = [c for c in ctx["conflicts"] if not sp or sp in c.lower() or not any((x or "").lower() in c.lower() for x in ("mouse", "rat", "dog", "monkey", "rabbit", "guinea pig"))]
        if hit:
            o["flags"].append("SOURCE_CONFLICT")
            o["note"] = (o["note"] + " " + hit[0]).strip()
    return o


def _collection_basis(text):
    """Only a local source label declares whether a measurement is an increment or total."""
    text = re.sub(r"total\s+(?:radioactivity|radiolabel|14\s*c)", "radiolabel", str(text), flags=re.I)
    if re.search(r"cumul|\btotal\b|overall", text, re.I):
        return "CUMULATIVE"
    if re.search(r"increment|\binterval(?:s)?\b|non[- ]?overlap", str(text), re.I):
        return "INTERVAL"
    return None


def _classify_collection_windows(rows):
    """Infer nested collection totals from geometry, never from measured magnitudes.

    A window containing smaller windows is a total. Its shortest common-origin
    partner is also cumulative unless a later disjoint bin establishes an
    increment schedule. Explicit local source labels take precedence.
    """
    windows = {tuple(o["interval"]) for o in rows if o["interval"]}
    for o in rows:
        if o["amount_basis"] != "INTERVAL" or o.get("basis_declared") or not o["interval"]:
            continue
        a, b = o["interval"]
        contains = any(a <= c and d <= b and (a, b) != (c, d) for c, d in windows)
        nested_later = any(c == a and d > b for c, d in windows)
        next_bin = any(c == b and d > b for c, d in windows)
        if contains or (nested_later and not next_bin):
            o["amount_basis"] = "CUMULATIVE"
            o["note"] = (o["note"] + " Nested collection windows: reported cumulative amount, not an increment.").strip()



def _layout_interval_columns(e, ctx):
    cs = _cols(e)
    gcol = cs[0]["id"]
    out, group = [], None
    for rec in e.get("records", []):
        g = rec.get(gcol)
        group = str(g) if g not in (None, "") else group
        sp = species_of(group) or ctx["table_species"]
        n = n_from(group)
        ints = []
        for c in cs[1:]:
            hdr = str(c.get("header", ""))
            cell = _record_cell(rec, c["id"])
            iv = parse_interval(hdr)
            declared = _collection_basis(hdr) or ("CUMULATIVE" if re.search(r"cumul", ctx["title"], re.I) else None)
            basis = declared or "INTERVAL"
            note = ""
            if cell["foot"] and cell["foot"] in ctx["footnotes"]:
                ft = ctx["footnotes"][cell["foot"]]
                fiv = parse_interval(ft)
                if fiv and cell["state"] == "QUANTIFIED":
                    iv, note = fiv, f"footnote {cell['foot']}): {ft}"
                elif cell["state"] == "MISSING":
                    note = f"footnote {cell['foot']}): {ft}"
            if iv is None and declared == "CUMULATIVE":
                basis = "TOTAL"
            elif iv is None:
                continue
            o = _obs(ctx, rec, col=c["id"], group=group, species=sp, n=n, interval=list(iv) if iv else None,
                     interval_text=(f"{_f(iv[0])}–{_f(iv[1])} h" if iv else hdr), amount_basis=basis, basis_declared=bool(declared),
                     value=cell["value"], sd=cell["sd"], state=cell["state"], raw=cell["raw"], censoring=cell.get("censoring"), note=note,
                     analyte=analyte_kind(ctx["title"] + " " + ctx["analyte_text"], ctx["drug"]))
            form, denom, unit = _basis_of(ctx, f"{hdr} {c.get('unit') or ''}")
            o["dose_denominator_verified"] = form == "PERCENT_OF_DOSE" and denom == "administered dose"
            if ctx["level"] == "INDIVIDUAL":
                identity = rec.get("animal_id") or rec.get("subject_id")
                if cs[0].get("meaning") in ("ANIMAL_ID", "SUBJECT_ID"):
                    if identity is None or str(identity) == str(g):
                        identity = g
                    else:
                        identity = None
                o["animal"] = identity
            if form != "NOT_STATED":
                o.update(value_form=form, denominator=denom, unit=unit)
            if o["analyte"] == "TOTAL_RADIOACTIVITY" and o["denominator"] == "administered dose":
                o.update(denominator="administered radioactivity", unit="% of administered radioactivity")
            if cell["state"] == "MISSING":
                o["note"] = (o["note"] or "printed as a dash: missing, not zero (E0.5)")
            foot = cell["foot"] or next(iter(re.findall(r"\b([a-z])\)", hdr)), None)
            o["dispersion"] = _declared_dispersion(e, hdr, ctx["footnotes"].get(foot, ""))
            ints.append(o)
        _classify_collection_windows(ints)
        # Without its own window, retain the existing convention: total over
        # collected, quantified bins only. A missing later bin cannot extend it.
        quant = [o for o in ints if o["interval"] and o["state"] == "QUANTIFIED"]
        for o in ints:
            if o["amount_basis"] == "TOTAL":
                if quant:
                    o["interval"] = [min(q["interval"][0] for q in quant), max(q["interval"][1] for q in quant)]
                    o["interval_text"] = f"total over collected intervals ({_f(o['interval'][0])}–{_f(o['interval'][1])} h)"
                    o["amount_basis"] = "CUMULATIVE"
                else:
                    o["interval_text"] = "total (collection end not stated)"
        out += ints
    return out


def _layout_sample_rows(e, ctx):
    cs = _cols(e)
    scol = next(c["id"] for c in cs if re.search(r"\bsample\b|excret|specimen", str(c.get("header", "")), re.I))
    tcol = next((c["id"] for c in cs if c.get("meaning") == "TIME" or re.search(r"\btime\b|interval|period", str(c.get("header", "")), re.I)), None)
    time_col = next((c for c in cs if c["id"] == tcol), {})
    time_unit = str(time_col.get("unit") or "").lower()
    if time_unit not in _UNIT_H:
        match = re.search(r"\((h|hours?|min|minutes?|d|days?)\)", str(time_col.get("header", "")), re.I)
        time_unit = match.group(1) if match else "h"
    vcols = [c for c in cs if c["id"] not in (scol, tcol)]
    out = []
    for rec in e.get("records", []):
        label = str(rec.get(scol) or "")
        ex = excretum_of(label) or "OTHER"
        ttxt = rec.get(tcol) if tcol else None
        row_iv = parse_interval(f"{ttxt} {time_unit}" if ttxt is not None and re.fullmatch(r"\s*\d+(?:\.\d+)?\s*[-–]\s*\d+(?:\.\d+)?\s*", str(ttxt)) else ttxt) or parse_interval(label)
        for c in vcols:
            hdr = str(c.get("header", ""))
            iv = row_iv or parse_interval(hdr) or parse_interval(ctx["title"])
            cell = _record_cell(rec, c["id"])
            analyte = "TOTAL_RADIOACTIVITY" if ctx["radiolabel"] or "radioact" in ctx["exposure_basis"].lower() else analyte_kind(ctx["title"], ctx["drug"])
            declared = _collection_basis(" ".join((label, str(ttxt or ""), hdr))) or ("CUMULATIVE" if re.search(r"cumul", ctx["title"], re.I) else None)
            basis = "TOTAL" if ex in ("TOTAL", "CARCASS") else (declared or ("INTERVAL" if iv else "CUMULATIVE"))
            form, denom, unit = _basis_of(ctx, hdr)
            if form == "PERCENT_OF_DOSE" and analyte == "TOTAL_RADIOACTIVITY" and denom == "administered dose":
                denom, unit = "administered radioactivity", "% of administered radioactivity"
            out.append(_obs(ctx, rec, col=c["id"], group=label, excretum=ex, analyte=analyte, interval=list(iv) if iv else None,
                            interval_text=(f"{_f(iv[0])}–{_f(iv[1])} h" if iv else (str(ttxt) if ttxt else "window not stated")),
                            amount_basis=basis, basis_declared=bool(declared), value=cell["value"], sd=cell["sd"], state=cell["state"], raw=cell["raw"], censoring=cell.get("censoring"),
                            value_form=form, denominator=denom, unit=unit,
                            n=n_from(e.get("experimental_unit"))))
            # Time columns share a trajectory; parallel cohort columns do not.
            column_group = re.sub(r"cumul\w*|\btotal\b|overall", "", _INTERVAL.sub("", hdr), flags=re.I).strip()
            out[-1]["value_column_group"] = column_group
            if ex not in ("TOTAL", "CARCASS"):
                sample_group = re.sub(r"cumul\w*|\btotal\b|overall", "", _INTERVAL.sub("", label), flags=re.I)
                sample_group = re.sub(r"\(\s*\)|\[\s*\]", "", sample_group)
                out[-1]["source_sample_label"] = label
                out[-1]["group"] = re.sub(r"\s+", " ", sample_group).strip()
            if len(vcols) > 1 and column_group:
                out[-1]["group"] += f" / {column_group}"
    groups = {}
    for o in out:
        groups.setdefault((o["excretum"], o["group"], o["denominator"], o.get("cohort_id")), []).append(o)
    for rows in groups.values():
        _classify_collection_windows(rows)
    return out


def _basis_of(ctx, header=""):
    # A specific value-column denominator takes precedence over table context.
    if header:
        local_ctx = dict(ctx, exposure_basis=str(header), title="")
        local = _basis_of(local_ctx)
        if local[0] != "NOT_STATED":
            return local
    s = " ".join([ctx["exposure_basis"], ctx["title"]]).lower()
    if re.search(r"that day'?s dose|daily dose", s):
        return "PERCENT_OF_DOSE", "that day's dose", "% of that day's dose"
    if re.search(r"(?:%|percent(?:age)?) of (?:urinary|faecal|fecal|biliary) (?:radioactivity|14c)|of urinary radioactivity", s):
        return "PERCENT_OF_EXCRETUM", "radioactivity recovered in the excretum", "% of excretum radioactivity"
    if re.search(r"chromatogram|peak area", s):
        return "PERCENT_OF_CHROMATOGRAM", "profiled chromatogram area", "% of chromatogram"
    if re.search(r"(?:%|percent(?:age)?)\s*(?:of\s+)?(?:the\s+)?administered\s+(?:radioactivity|radiolabel|14\s*c)", s):
        return "PERCENT_OF_DOSE", "administered radioactivity", "% of administered radioactivity"
    if re.search(r"% of (?:the )?(?:administered )?dose|percent of dose", s):
        return "PERCENT_OF_DOSE", "administered dose", "% of dose"
    return "NOT_STATED", "not stated", "basis not stated"


def _layout_component_rows(e, ctx):
    cs = _cols(e)
    ccol = cs[0]["id"]
    out = []
    for c in cs[1:]:
        hdr = str(c.get("header", ""))
        occ = re.search(r"\bday\s*(\d+)", hdr, re.I)
        iv = parse_interval(hdr) or parse_interval(ctx["title"]) or parse_interval(e.get("notes"))
        rec_ex = re.search(r"(\d+(?:\.\d+)?)\s*%\s*of\s*dose", hdr)
        form, denom, unit = _basis_of(ctx, "")
        overall = bool(re.search(r"overall|all animals|combined", hdr, re.I))
        for rec in e.get("records", []):
            label = str(rec.get(ccol) or "")
            cell = _record_cell(rec, c["id"])
            kind = "TOTAL" if re.match(r"^\s*total\b", label, re.I) else analyte_kind(label, ctx["drug"])
            name = re.sub(r"\s*\b[a-z]\)\s*$", "", label).strip()
            o = _obs(ctx, rec, col=c["id"], group=re.sub(r"\s*\(.*?\)\s*", " ", hdr).strip() if not occ else f"Day {occ.group(1)}",
                     species=species_of(hdr) or ctx["table_species"], analyte=kind, component=name,
                     interval=list(iv) if iv else None, interval_text=(f"{_f(iv[0])}–{_f(iv[1])} h" if iv else "window not stated"),
                     value_form=form, denominator=denom, unit=unit, value=cell["value"], sd=cell["sd"], state=cell["state"], raw=cell["raw"], censoring=cell.get("censoring"),
                     occasion=(f"DAY_{occ.group(1)}" if occ else "FIRST_DOSE"))
            o["excretum_recovery_pct_dose"] = float(rec_ex.group(1)) if rec_ex else None
            o["printed_aggregate"] = overall
            if kind == "TOTAL" and o["analyte"] == "TOTAL" and "TR_NOT_PARENT" in o["flags"]:
                o["flags"].remove("TR_NOT_PARENT")
            out.append(o)
    return out


def _layout_quantity_rows(e, ctx):
    cs = _cols(e)
    qcol = cs[0]["id"]
    animals = [c for c in cs[1:] if re.fullmatch(r"\s*\d+\s*", str(c.get("header", "")))]
    meancol = next((c for c in cs[1:] if re.search(r"mean", str(c.get("header", "")), re.I)), None)
    m = re.search(r"within\s+(\d+(?:\.\d+)?)\s*(h|hours?|min)", ctx["title"] + " " + ctx["notes"], re.I)
    iv = (0.0, float(m.group(1)) * _UNIT_H.get(m.group(2).lower(), 1.0)) if m else parse_interval(ctx["title"])
    disp = _declared_dispersion(e, str(meancol.get("header", "")) if meancol else "")
    out = []
    for rec in e.get("records", []):
        label = str(rec.get(qcol) or "")
        low = label.lower()
        if re.search(r"percent(?:age)? of", low):
            form, unit, denom = "PERCENT_OF_EXCRETUM", "% of excretum radioactivity", "radioactivity recovered in the excretum"
            target = re.sub(r"percent(?:age)? of\s*", "", label, flags=re.I).strip()
        elif "% of dose" in low:
            form, unit, denom, target = "PERCENT_OF_DOSE", "% of dose", "administered radioactivity" if re.search(r"radioact|14c", low) else "administered dose", label
        else:
            mu = re.search(r"\(([^()]+)\)", label)
            form, unit, denom, target = "AMOUNT", (mu.group(1) if mu else "not stated"), "—", label
        kind = analyte_kind(target, ctx["drug"])
        for c in animals + ([meancol] if meancol else []):
            cell = _record_cell(rec, c["id"])
            is_mean = c is meancol
            o = _obs(ctx, rec, col=c["id"], group=("mean" if is_mean else f"animal {str(c.get('header')).strip()}"),
                     animal=None if is_mean else str(c.get("header")).strip(), level="GROUP_MEAN" if is_mean else "INDIVIDUAL",
                     analyte=kind, component=re.sub(r"\s*\(.*?\)\s*", "", target).strip(), interval=list(iv) if iv else None,
                     interval_text=(f"{_f(iv[0])}–{_f(iv[1])} h" if iv else "window not stated"), amount_basis="INTERVAL",
                     value_form=form, unit=unit, denominator=denom, value=cell["value"], sd=cell["sd"], state=cell["state"], raw=cell["raw"], censoring=cell.get("censoring"),
                     n=len(animals) if is_mean else 1)
            o["quantity_label"] = label
            o["dispersion"] = disp if is_mean else "n/a"
            out.append(o)
    return out


LAYOUTS = {"INTERVAL_COLUMNS": _layout_interval_columns, "SAMPLE_ROWS": _layout_sample_rows,
           "COMPONENT_ROWS": _layout_component_rows, "QUANTITY_ROWS_BY_ANIMAL": _layout_quantity_rows}


def excreta_dataset(e, cfg):
    ctx = _table_context(e, cfg)
    layout, why = detect_layout(e, cfg)
    obs = LAYOUTS[layout](e, ctx) if layout in LAYOUTS else []
    # collection schedule printed only in the note ("... every 1 h to 7 h after the dose")
    ends = [float(x) for x in re.findall(r"\bto\s+(\d+(?:\.\d+)?)\s*h\b(?!\s*for)", ctx["notes"])]
    for o in obs:
        if o["interval"] is None and ends and o["excretum"] not in ("TOTAL", "CARCASS"):
            o["interval"] = [0.0, max(ends)]
            o["interval_text"] = f"0–{_f(max(ends))} h (collection schedule in the source note)"
    # analyte-specific windows that differ from the table window (e.g. HPLC on shorter collections per animal)
    for sent in re.split(r"(?<=[.;\n])\s+", ctx["notes"]):
        wins = sorted({float(x) for x in re.findall(r"\bto\s+(\d+(?:\.\d+)?)\s*h\s+for", sent)})
        if len(wins) >= 2 and re.search(r"hplc|analys", sent, re.I):
            for o in obs:
                if o["analyte"] not in ("TOTAL_RADIOACTIVITY",):
                    o["interval"] = None
                    o["interval_text"] = f"0–{_f(wins[0])} to 0–{_f(wins[-1])} h by animal (source note); not the table window"
                    o["flags"].append("WINDOW_DIFFERS_BY_ANALYTE")
                    o["note"] = (o["note"] + " " + sent.strip()[:200]).strip()
    for o in obs:
        if o["species"] is None:
            o["species"] = ctx["table_species"] or "Species not stated"
        if ctx["repeat"] and o["occasion"] != "FIRST_DOSE" and "CARRYOVER_POSSIBLE" not in o["flags"] and o["occasion"] not in ("DAY_1",):
            o["flags"].append("CARRYOVER_POSSIBLE")
        if o["state"] in ("NOT_DETECTED", "CENSORED"):
            o["flags"].append("ASSAY_CENSORED")
        if ctx["collection"]["cagewash"] == "SEPARATE" and o["excretum"] == "CAGEWASH":
            o["flags"].append("CAGEWASH_UNASSIGNED")
    card = {k: v for k, v in ctx.items() if k not in ("notes",)}
    card.update(layout=layout, layout_reason=why, n_observations=len(obs),
                quarantined=[r["reason"] for r in ctx["restrictions"] if "QUARANTINED" in r["reason"]])
    return card, obs


# ---------------------------------------------------------------- in vitro tables (E0.8 in vitro fields; item 35 EM-7b)

READOUT = [("VMAX_KM", r"v\s*max\s*/\s*k\s*m|clint|intrinsic clearance"), ("KM", r"\bk\s*m\b"), ("VMAX", r"\bv\s*max\b"),
           ("HALF_LIFE", r"t\s*1\s*/\s*2|half[- ]?life|t½"), ("RESIDUAL_PCT", r"residual|remaining|% (?:of )?parent")]
READOUT_WORD = {"VMAX_KM": "Vmax/Km", "KM": "Km", "VMAX": "Vmax", "HALF_LIFE": "reported half-life", "RESIDUAL_PCT": "parent remaining"}


def _decimals(raw):
    s = str(raw)
    return len(s.split(".")[1]) if "." in s and re.fullmatch(r"\s*[-+]?\d+\.\d+\s*", s) else 0


def ratio_check(vmax, km, ratio, raws):
    """Printed Vmax/Km against printed Vmax and Km, allowing half a unit of the last printed digit on each (rounding only)."""
    hv, hk, hr = (0.5 * 10 ** -_decimals(r) for r in raws)
    lo, hi = (vmax - hv) / (km + hk), (vmax + hv) / max(km - hk, 1e-12)
    ok = not (ratio + hr < lo or ratio - hr > hi)
    return {"printed_ratio": ratio, "from_inputs": vmax / km, "allowed_range": [lo, hi], "consistent": ok}


def in_vitro_dataset(e):
    meta = e.get("metadata", {})
    cs = _cols(e)
    drugs = [d.strip() for d in str(meta.get("drug") or "").split(";") if d.strip()]
    primary = drugs[0] if drugs else ""
    restr = " ".join(r["reason"] for r in _restrictions(e))
    ambiguous = "COLUMN_HEADER_AMBIGUITY" in restr
    notes = e.get("notes") or ""
    m = re.search(r"(?:initial|starting|substrate)\s+concentration\s*(?:of\s*)?(\d+(?:\.\d+)?)\s*([µu]g/ml|mg/l|µm|mm|um)", notes, re.I)
    card = {"dataset_id": e["dataset_id"], "title": e.get("title"), "study": _study(e), "system": str(meta.get("matrix") or "not reported"),
            "drug": primary, "comparators": drugs[1:], "start_concentration": f"{m.group(1)} {m.group(2)}" if m else "not reported",
            "incubation": "; ".join(re.findall(r"incubat[^.;]*", notes, re.I)[:2]) or "not reported",
            "controls": "; ".join(re.findall(r"[^.;]*control[^.;]*", notes, re.I)[:2]) or "not reported",
            "normalization": "per enzyme unit" if re.search(r"enzyme unit", " ".join(str(c.get("unit")) + str(c.get("header")) for c in cs), re.I) else
                             ("homogenate dilution " + (re.search(r"\d+\s*%", card_sys).group(0) if (card_sys := str(meta.get("matrix") or "")) and re.search(r"\d+\s*%", card_sys) else "not reported")),
            "footnotes": footnotes(notes), "conflicts": _conflict_reasons(e), "restrictions": _restrictions(e)}
    rows = []
    gcol = cs[0]["id"] if cs else None
    prev_kind = None
    for c in cs[1:]:
        hdr = str(c.get("header", ""))
        drug = next((d for d in drugs if hdr.lower().startswith(d.lower().split("/")[0])), primary)
        kind = next((k for k, p in READOUT if re.search(p, hdr, re.I)), None)
        explicit = kind is not None
        tmin = None
        tm = re.search(r"(\d+(?:\.\d+)?)\s*min", hdr)
        if kind is None and tm and prev_kind == "RESIDUAL_PCT":
            kind = "RESIDUAL_PCT"
        if kind == "RESIDUAL_PCT" and tm:
            tmin = float(tm.group(1))
        if kind is None:
            continue
        prev_kind = kind
        um = re.search(r"\(([^()]+)\)\s*$", hdr)
        unit = c.get("unit") if c.get("unit") not in (None, "NOT_FOUND") else (um.group(1) if um else ("%" if kind == "RESIDUAL_PCT" else "not stated"))
        for rec in e.get("records", []):
            label = str(rec.get(gcol) or "")
            cell = _record_cell(rec, c["id"])
            flags, why = [], []
            if drug != primary:
                flags.append("COMPARATOR_DRUG"); why.append(f"comparator drug ({drug})")
            if ambiguous and not explicit:
                flags.append("HEADER_AMBIGUOUS"); why.append("the header does not state the quantity or unit (source restriction)")
            if cell["state"] == "NOT_DETECTED":
                why.append("not detected" + (f" ({card['footnotes'].get(cell['foot'])})" if cell["foot"] in card["footnotes"] else ""))
            rows.append({"row_id": f"{e['dataset_id']}:{rec.get('record_id')}:{c['id']}", "dataset_id": e["dataset_id"], "record_id": rec.get("record_id"),
                         "study": card["study"], "species": species_of(label) or (label.strip() or "not stated"), "row_label": label, "system": card["system"],
                         "drug": drug, "readout": kind, "time_min": tmin, "header": hdr, "unit": unit, "value": cell["value"], "raw": cell["raw"],
                         "state": cell["state"], "censoring": cell.get("censoring"), "flags": flags, "excluded_reason": "; ".join(why)})
    # Vmax/Km against its printed inputs (item 35 step 8)
    by = {}
    for r in rows:
        by.setdefault((r["record_id"], r["drug"]), {})[r["readout"]] = r
    checks = []
    for (rid, drug), d in by.items():
        if {"VMAX", "KM", "VMAX_KM"} <= d.keys():
            vmax_unit = d["VMAX"]["unit"].lower().replace("μ", "µ")
            ratio = d["VMAX_KM"]
            if (ratio["unit"] == "not stated" and d["KM"]["unit"] == "mM"
                    and vmax_unit in {"µmoles/min/enzyme unit", "µmol/min/enzyme unit", "umol/min/enzyme unit"}):
                ratio.update(unit="mL/min/enzyme unit", unit_basis="derived from the Vmax and Km column units",
                             unit_source_refs=[d["VMAX"]["row_id"], d["KM"]["row_id"]])
        if {"VMAX", "KM", "VMAX_KM"} <= set(d) and all(d[k]["value"] for k in ("VMAX", "KM", "VMAX_KM")):
            chk = ratio_check(d["VMAX"]["value"], d["KM"]["value"], d["VMAX_KM"]["value"], [d[k]["raw"] for k in ("VMAX", "KM", "VMAX_KM")])
            chk.update(record_id=rid, drug=drug, species=d["VMAX_KM"]["species"])
            checks.append(chk)
            if not chk["consistent"]:
                for k in ("VMAX", "KM", "VMAX_KM"):
                    d[k]["flags"].append("SOURCE_CONFLICT")
                    d[k]["excluded_reason"] = "; ".join(x for x in (d[k]["excluded_reason"], f"printed Vmax/Km {_f(chk['printed_ratio'])} conflicts with Vmax/Km from the printed inputs ({_f(chk['from_inputs'])}) beyond rounding") if x)
    card["ratio_checks"] = checks
    return card, rows


def em7b_groups(cards, rows):
    """Matched-system groups: same dataset, system, drug, readout, time; >= 2 eligible rows (item 35 step 5)."""
    out = []
    for card in cards:
        rs = [r for r in rows if r["dataset_id"] == card["dataset_id"]]
        keys = list(dict.fromkeys((r["readout"], r["time_min"], r["drug"], r["unit"]) for r in rs))
        for readout, tmin, drug, unit in keys:
            g = [r for r in rs if (r["readout"], r["time_min"], r["drug"], r["unit"]) == (readout, tmin, drug, unit)]
            ok = [r for r in g if not r["excluded_reason"] and r["state"] == "QUANTIFIED"
                  and r["value"] is not None and species_of(r["species"])]
            left = [r for r in g if r not in ok]
            if readout not in ("HALF_LIFE", "VMAX_KM", "RESIDUAL_PCT") or drug != card["drug"]:
                continue
            first_t = min((r["time_min"] for r in rs if r["readout"] == "RESIDUAL_PCT" and r["time_min"] is not None), default=None)
            direction = {"HALF_LIFE": "a shorter reported half-life denotes faster loss",
                         "VMAX_KM": "a higher Vmax/Km denotes a higher reported low-concentration efficiency",
                         "RESIDUAL_PCT": "at equal incubation time, less parent remaining denotes more loss"}[readout]
            key = f"{card['dataset_id']}-{readout}-{_f(tmin) if tmin is not None else ''}".strip("-")
            if sum(1 for v in keys if v[:3] == (readout, tmin, drug)) > 1:
                key += "-" + _slug(str(unit))
            comparable_species = {species_of(r["species"]) for r in ok}
            reason = ""
            if len(comparable_species) < 2:
                reason = "fewer than two comparable species in this assay"
            elif unit in (None, "", "NOT_FOUND", "not stated") or card["system"] in ("not reported", "NOT_FOUND", ""):
                reason = "the assay system or measurement unit is unspecified"
            elif readout == "RESIDUAL_PCT" and tmin == first_t:
                reason = "starting check of the incubation"
            out.append({"key": key, "dataset_id": card["dataset_id"], "study": card["study"],
                        "system": card["system"], "drug": drug, "readout": readout, "time_min": tmin, "unit": (ok or g)[0]["unit"],
                        "rows": ok, "left_out": [{"species": r["species"], "reason": r["excluded_reason"] or
                                                 ("species unspecified" if not species_of(r["species"]) else r["state"].lower())} for r in left],
                        "drawn": not reason, "not_drawn_reason": reason,
                        "direction": direction,
                        "ranking": [r["species"] for r in sorted(ok, key=lambda r: r["value"], reverse=readout == "VMAX_KM")],
                        "start_concentration": card["start_concentration"], "normalization": card["normalization"],
                        "controls": card["controls"]})
    return out


# ---------------------------------------------------------------- reported parameters (E0.12, EM-R)

EM_PARAMS = [("CL_F", r"\bcl\w*\s*/\s*f\b|clss/f"), ("CLNR", r"\bnon[\s\-‐‑–]*renal\s+clearance\b|\bcl\s*_?\s*nr\b"),
             ("CLR", r"\brenal\s+clearance\b|\bcl\s*_?\s*r\b"), ("FE", r"\bfe\b|fraction excreted|urinary (?:excretion|recovery)"),
             ("CL", r"\bcl(?:tot|\s*tot|_?total)?\b(?!\s*/\s*f)|\bclearance\b|total cl\b"),
             ("KE", r"elimination rate constant|\bke\b|\bkel\b|\bk10\b"), ("THALF", r"half[- ]?li|t\s*1\s*/\s*2|t½")]
EM_EXCLUDE = r"tissue fluid|absorption|\bcsf\b|\bvol|\bk12|\bk21|\bk13|\bk31|\bmic\b|binding"
PNAME = {"CL": "CL", "CL_F": "CL/F", "CLR": "CLR", "CLNR": "CLnr", "FE": "fe / urinary recovery", "KE": "elimination rate constant", "THALF": "half-life"}
PNAME["AUC"] = "AUC"
PNAME["CMAX"] = "Cmax"


def _table_occasion(entry):
    """DAY_N for a reported table of a multi-day regimen ("day N of M", M > 1 in metadata.dosing_regimen or the title); otherwise None."""
    meta = entry.get("metadata") or {}
    for text in (meta.get("dosing_regimen"), entry.get("title")):
        m = re.search(r"\bday\s*(\d+)\s*of\s*(\d+)\b", str(text or ""), re.I)
        if m:
            return f"DAY_{int(m.group(1))}" if int(m.group(2)) > 1 else None
    return None


def _dosing_interval_h(entry):
    declared = (entry.get("metadata") or {}).get("dosing_interval_h")
    if isinstance(declared, (int, float)) and not isinstance(declared, bool) and math.isfinite(declared) and declared > 0:
        return float(declared)
    text = " ".join(str(x or "") for x in ((entry.get("metadata") or {}).get("dosing_regimen"), entry.get("notes"), entry.get("title")))
    for pat, tau in ((r"\bonce\s+(?:a\s+day|daily)\b|\bq\s*24\s*h\b|\bq\.?d\.?\b|every\s+24\s*h", 24.0), (r"\btwice\s+(?:a\s+day|daily)\b|\bq\s*12\s*h\b|\bb\.?i\.?d\.?\b|every\s+12\s*h", 12.0)):
        if re.search(pat, text, re.I):
            return tau
    return None


def em_param(text):
    s = str(text or "").lower()
    if re.search(EM_EXCLUDE, s):
        return None
    for name, pat in EM_PARAMS:
        if re.search(pat, s):
            return name
    return None


def cl_to_l_h_kg(v, unit):
    u = str(unit or "").lower().replace(" ", "").replace("liters", "l").replace("liter", "l").replace("·", "")
    if v is None:
        return None
    if re.fullmatch(r"ml/min/kg", u):
        return v * 0.06
    if re.fullmatch(r"l/h(?:r)?/kg", u):
        return v
    if re.fullmatch(r"ml/h(?:r)?/kg", u):
        return v / 1000
    return None


def _unit_like(u):
    return bool(u) and bool(re.search(r"/|^(?:h|hr|hours?|min|%|h[-−]1|1/h|l|ml|mg|µg|ug)\b", str(u).strip(), re.I))


def _value_text(c):
    """'6.53 +/- 1.51 mL/min/kg' -> (6.53, 1.51, 'mL/min/kg', state). Free text such as '2 h and 5 min' keeps no number."""
    raw = c["raw"]
    um = re.search(r"\d\s*([a-zA-Zµμ%/·.\-−0-9]+(?:/[a-zA-Zµμ.\-−0-9]+)*)\s*$", str(raw or ""))
    unit = um.group(1) if um and _unit_like(um.group(1)) else None
    if c["state"] == "TEXT" and not re.fullmatch(r"\s*(?:about|approx\.?|~)?\s*[-+]?\d+(?:\.\d+)?\s*\S*\s*", str(raw or "")):
        return None, None, None, "TEXT"
    return c["value"], c["sd"], unit, c["state"]


def _occasion_auc_review(entry, unit):
    """Keep conflicting source units and their provenance without selecting a scale."""
    restrictions = entry.get("operation_restrictions") or []
    evidence = (entry.get("metadata") or {}).get("source_evidence", [])
    notes = entry.get("notes") or ""
    notes_lines = [{"quote": line, "source": entry["dataset_id"] + ":notes"} for line in notes.splitlines()]
    text_units, refs = [], []
    for snippet in [*evidence, *notes_lines]:
        match = re.search(r"\b(?:text|narrative)\b[^.;\n]{0,45}?\bAUC\b[^;\n]{0,80}?"
                          r"((?:[µμunm]?g)\s*[·*× ]\s*(?:min|h|hr)\s*/\s*(?:mL|L))\b",
                          snippet.get("quote", ""), re.I)
        if match and match[1] not in text_units:
            text_units.append(match[1])
            refs.append(snippet.get("source") or entry["dataset_id"])
    reasons = " ".join(reason for r in restrictions for reason in r.get("reasons", []))
    declared = bool(re.search(r"(?:AUC[^\n.;]{0,60}(?:different|differing|conflict|inconsistent)|"
                              r"(?:different|differing|conflict|inconsistent)[^\n.;]{0,60}AUC)", reasons + "\n" + notes, re.I))
    def normalized(u):
        return re.sub(r"[\s·*×]", "", u.lower().replace("μ", "u").replace("µ", "u"))
    conflict = declared or bool(unit and any(normalized(u) != normalized(unit) for u in text_units))
    return {"table_unit": unit, "text_units": text_units, "unit_conflict": conflict,
            "source_restrictions": restrictions, "unit_source_refs": refs}


_DOSE_NUMBER = r"\d+(?:\.\d+)?"
_DOSE_EXPRESSION = re.compile(
    rf"(?<![\w.+-])({_DOSE_NUMBER}(?:\s*(?:[-–—]|to\b|,\s*(?:and\s+)?|\band\b)\s*{_DOSE_NUMBER})*)"
    r"\s*(mg|[uµμ]g|ng|g)\s*/\s*kg\b(?!\s*/\s*(?:day|h)\b)", re.I)
_MG_FACTOR = {"mg": 1, "ug": .001, "µg": .001, "μg": .001, "ng": .000001, "g": 1000}


def _pk_regimen(meta):
    """Separate a PK dosing schedule from efficacy, pretreatment and sampling schedules."""
    regimen = str(meta.get("dosing_regimen") or "")
    pk = re.search(r"\b(?:PK|pharmacokinetics?)\s*:\s*(.+?)(?=\s*(?:[;.]\s*)?(?:efficacy|PD|pretreatment)\s*:|$)", regimen, re.I)
    if pk:
        return pk[1].strip(" ;.")
    if re.search(r"\b(?:efficacy|PD|pretreatment)\s*:", regimen, re.I):
        return ""
    return regimen


def _repeat_regimen(entry):
    meta = entry.get("metadata") or {}
    for clause in re.split(r";|\n", _pk_regimen(meta)):
        if re.search(r"\b(?:efficacy|pretreatment|recommend\w*|sampled|sampling|hypothetical)\b", clause, re.I):
            continue
        interval = re.search(r"\b(?:q\s*|every\s+)(\d+(?:\.\d+)?)\s*(?:h(?:ours?|rs?)?)\b", clause, re.I)
        repeated = re.search(r"\brepeat(?:ed)?[- ]dos(?:e|ing)|\bmultiple[- ]dos(?:e|ing)|\b(?:once|twice) daily\b|"
                             r"\bdaily (?:dos(?:e|ing)|for)|\bper day for\b|/day\b.{0,35}\bfor\s+\d+\s+days", clause, re.I)
        if not (interval or repeated) or re.search(r"\b(?:single[- ]dose(?:s)?|no repeated dosing|not administered)\b", clause, re.I):
            continue
        return {"dataset_id": entry["dataset_id"], "source_ref": entry["dataset_id"] + ":metadata.dosing_regimen",
                "as_reported": clause.strip(), "drug": str(meta.get("drug") or ""),
                "interval_h": float(interval[1]) if interval else None}
    return None


def _reported_dose_context(entry):
    """Read the PK regimen separately from efficacy and pretreatment doses."""
    meta = entry.get("metadata") or {}
    ds = entry["dataset_id"]
    candidates = meta.get("dose")
    candidates = candidates if isinstance(candidates, dict) else {}
    data = {"kind": "unresolved", "values_mg_per_kg": [], "source_refs": []}
    regimen = str(meta.get("dosing_regimen") or "")
    # Mixed PK/PD descriptions may place the efficacy arm before or after PK.
    pk = re.search(r"\b(?:PK|pharmacokinetics?)\s*:\s*(.+?)(?=\s*(?:[;.]\s*)?(?:efficacy|PD|pretreatment)\s*:|$)", regimen, re.I)
    if pk:
        regimen = pk[1]
    elif re.search(r"\b(?:efficacy|PD|pretreatment)\s*:", regimen, re.I):
        regimen = ""
    eligible = [c for c in candidates.get("candidates", []) if not re.search(
        r"recommended|not (?:a dose )?(?:given|administered)", " ".join(c.get("qualifiers") or []), re.I)]
    primary = str(meta.get("drug") or "").split(";")[0].lower().strip()
    for field, wording in (("metadata.dosing_regimen", regimen), ("title", str(entry.get("title") or ""))):
        matches = list(_DOSE_EXPRESSION.finditer(wording))
        if not matches:
            continue
        if re.search(r"\b(?:recommend\w*|not (?:a dose )?(?:given|administered)|pretreatment|pre-treatment)\b", wording, re.I) or re.search(r"\befficacy\b", wording[:matches[-1].end()], re.I):
            return data
        vals = sorted({float(n) * _MG_FACTOR[m[2].lower()] for m in matches for n in re.findall(_DOSE_NUMBER, m[1])})
        if not vals or vals[0] <= 0:
            return data
        # Reject an explicitly named co-medication in the dose-bearing clause.
        for m in matches:
            clause = re.split(r"[;:]", wording[:m.start()])[-1].lower()
            if any((subject := str(c.get("subject") or "").lower()) not in ("", "not_found", primary)
                   and subject in clause and (not primary or primary not in subject) for c in eligible):
                return data
        if len(matches) > 1 and len(vals) == 1 and not pk:
            return data
        rng = len(matches) == 1 and re.search(r"[-–—]|\bto\b", matches[0][1], re.I)
        refs = [f"{ds}:{field}"]
        for snippet in meta.get("source_evidence") or []:
            if snippet.get("source") and wording.strip(" ;.") in str(snippet.get("quote") or ""):
                refs.append(snippet["source"])
        return {"kind": "single" if len(vals) == 1 else ("range" if rng else "levels"),
                "values_mg_per_kg": vals, "source_refs": list(dict.fromkeys(refs))}
    if candidates.get("status") == "SOURCE_STATED":
        value, _ = dist._dose(entry)
        if value is not None:
            return {"kind": "single", "values_mg_per_kg": [value], "source_refs": [ds + ":metadata.dose"]}
    if len(eligible) == 1:
        c = eligible[0]
        subject = str(c.get("subject") or "").lower()
        refs = [s["source"] for s in c.get("evidence", []) if s.get("source")]
        expr = _DOSE_EXPRESSION.fullmatch(f"{c.get('value')} {c.get('unit')}")
        if (refs and expr and re.fullmatch(_DOSE_NUMBER, expr[1]) and float(expr[1]) > 0
                and (subject in ("", "not_found") or primary and primary in subject)
                and not re.search(r"efficacy|pretreatment|recommend", str(c.get("evidence", [])), re.I)):
            return {"kind": "single", "values_mg_per_kg": [float(expr[1]) * _MG_FACTOR[expr[2].lower()]], "source_refs": refs}
    return data


def _row_dose(entry, record, col):
    cell = _record_cell(record, col["id"])
    unit = str(col.get("unit") or "").lower().replace(" ", "")
    if unit in ("", "not_found"):
        match = re.search(r"\(([^()]+)\)", col.get("header", ""))
        unit = match[1].lower().replace(" ", "") if match else ""
    factor = _MG_FACTOR.get(unit.split("/")[0]) if unit.endswith("/kg") and unit.count("/") == 1 else None
    refs = [f"{entry['dataset_id']}:{record.get('record_id')}:{col['id']}"]
    if factor and cell["state"] == "QUANTIFIED" and cell["value"] is not None and cell["value"] > 0:
        return {"kind": "row", "values_mg_per_kg": [cell["value"] * factor], "source_refs": refs}
    return {"kind": "unresolved", "values_mg_per_kg": [], "source_refs": refs}


def _study_dose_text(context):
    values = context.get("values_mg_per_kg") or []
    if context.get("kind") == "range":
        return f"PK study range {_f(values[0])}–{_f(values[-1])} mg/kg"
    if context.get("kind") == "levels":
        return "PK study doses " + ", ".join(_f(x) for x in values) + " mg/kg"
    return ""


def _half_life_phase(label):
    words = str(label).lower()
    for phase, pattern in (("elimination", r"\belimination\b"), ("alpha", r"α|\balpha\b"), ("beta", r"β|\bbeta\b"), ("gamma", r"γ|\bgamma\b"),
                           ("initial", r"\binitial\b"), ("terminal", r"\bterminal\b")):
        if re.search(pattern, words):
            return phase
    return "unspecified"


def reported_dataset(e, abs_param_ids=(), reviewed=()):
    meta = e.get("metadata", {})
    cs = _cols(e)
    out, scope = [], []
    if not cs:
        return out, scope
    drugs = [d.strip() for d in str(meta.get("drug") or "").split(";") if d.strip()]
    primary = re.sub(r"\[14c\]", "", drugs[0], flags=re.I).strip() if drugs else ""
    study_dose = _reported_dose_context(e)
    repeat_regimen = _repeat_regimen(e)
    dose_col = next((c for c in cs if c.get("meaning") == "DOSE" or re.match(r"^\s*dose(?:\s*\(|$)", str(c.get("header", "")), re.I)), None)
    base = {"dataset_id": e["dataset_id"], "title": e.get("title"), "study": _study(e), "route": meta.get("route_class") or "NOT_FOUND",
            "route_detail": meta.get("route_detail") or "NOT_FOUND", "table_dose": study_dose["values_mg_per_kg"][0] if study_dose["kind"] == "single" else None, "method": "not reported",
            "dispersion_type": _declared_dispersion(e),
            "n_note": n_from(e.get("experimental_unit")), "matrix": meta.get("matrix") or "not reported",
            "source_restrictions": e.get("operation_restrictions") or []}
    txt = (e.get("notes") or "").lower()
    if re.search(r"non-?compartment|nca", txt):
        base["method"] = "non-compartmental"
    elif re.search(r"compartment", txt):
        base["method"] = "compartmental"
    elif re.search(r"population|nonmem|monolix", txt):
        base["method"] = "population model"
    tab_sp = species_of(meta.get("species") or e.get("group"))
    table_occ = _table_occasion(e)
    records_by_id = {r.get("record_id"): r for r in e.get("records", [])}
    base.update(dosing_interval_h=_dosing_interval_h(e), condition=meta.get("condition"), regimen=str(meta.get("dosing_regimen") or ""),
                table_notes=e.get("notes") or "", repeat_comparison_id=meta.get("repeat_comparison_id"),
                same_dose_across_occasions=meta.get("same_dose_across_occasions") is True,
                dose_conflict=meta.get("dose_conflict"), cohort_id=meta.get("cohort_id"),
                analysis_unit=meta.get("record_category") or meta.get("record_level"),
                reported_analyte=meta.get("analyte"), reported_analyte_role=meta.get("analyte_role"), exposure_window_h=meta.get("exposure_window_h"))
    h0 = str(cs[0].get("header", "")).lower()
    species_cols = [c for c in cs[1:] if species_of(c.get("header")) and not re.search(r"\(|mean|sd|value", str(c.get("header")), re.I)]

    def add(param, label, cell, unit, species, dose_context=None, analyte=None, occasion=None, record_id=None, sd=None, source_col=None, sd_type=None, sd_ref=None, qualifiers=None):
        raw = cell["raw"]
        v, sd2, unit2, state = _value_text(cell)
        unit = unit if unit not in (None, "", "NOT_FOUND") and _unit_like(unit) else unit2
        if v is None and state == "MISSING":
            return
        if analyte and primary and not re.search(re.escape(primary.split("/")[0][:6]), analyte, re.I):
            scope.append({"dataset_id": e["dataset_id"], "record_id": record_id, "analyte": analyte, "label": label, "raw": raw,
                          "study": base["study"], "species": species or tab_sp, "reason": "metabolite or other analyte; item 32 is reserved (SCOPE_REVIEW)"})
            return
        if analyte and re.search(r"14\s*c|radioact", analyte, re.I):
            scope.append({"dataset_id": e["dataset_id"], "record_id": record_id, "analyte": analyte, "label": label, "raw": raw,
                          "study": base["study"], "species": species or tab_sp, "reason": "total radioactivity; not parent (TR_NOT_PARENT); item 32 reserved"})
            return
        context = dose_context or study_dose
        if repeat_regimen and occasion is None:
            if re.search(r"\bfirst[- ]dose\b|\bafter (?:the )?initial dose\b", str(label), re.I):
                occasion = "FIRST_DOSE"
            else:
                day = re.search(r"\bday\s*(\d+)\b", str(label), re.I)
                occasion = f"DAY_{day[1]}" if day else "UNSPECIFIED"
        r = dict(base, param=param, name=PNAME[param], label=str(label), raw=raw, value=v, sd=sd if sd is not None else sd2, unit=unit or "not stated",
                 species=species or tab_sp or "Species not stated", dose=context["values_mg_per_kg"][0] if context["kind"] in ("single", "row") else None,
                 dose_context=context, occasion=occasion or "FIRST_DOSE",
                 record_id=record_id, analyte=analyte or primary or "parent", label_flag="REPORTED_PARAMETER",
                 state=state, censoring=cell.get("censoring"), as_printed_only=v is None)
        r["value_l_per_h_kg"] = cl_to_l_h_kg(v, r["unit"]) if param in ("CL", "CL_F", "CLR", "CLNR") else None
        if repeat_regimen:
            r["repeat_regimen"] = repeat_regimen
        r["shown_in_absorption_F"] = e["dataset_id"] in abs_param_ids and param in ("CL_F", "THALF")
        if sd is not None and sd_type:
            r.update(dispersion_type=sd_type, dispersion_ref=sd_ref)
        if source_col:
            r["source_cell"] = f"{e['dataset_id']}:{record_id}:{source_col}"
        if not qualifiers:
            tags = set(re.findall(r"\b(IV|SC|intravenous|subcutaneous)\b", str(label), re.I))
            routes = {"IV" if tag.lower() in ("iv", "intravenous") else "SC" for tag in tags}
            if len(routes) == 1:
                route = routes.pop()
                r["route"] = "IV" if route == "IV" else "EV"
                if route == "SC" or r["route_detail"] in ("MIXED", "NOT_FOUND"):
                    r["route_detail"] = route
            matrices = re.findall(r"\b(plasma|serum|whole blood|tissue fluid|interstitial fluid|CSF)\b", str(label), re.I)
            if len(set(m.lower() for m in matrices)) == 1:
                r["matrix"] = matrices[0].lower()
        else:
            r.update({k: qualifiers[k] for k in ("route", "route_detail", "matrix", "review_source", "cell_raw", "component_index", "dispersion_type")})
            r["n_note"] = qualifiers["n"]
        if param == "THALF":
            phase = _half_life_phase(label)
            r["half_life_phase"] = phase
            meaning = (qualifiers or {}).get("phase_meaning")
            if meaning:
                r["phase_meaning"] = meaning
            if phase != "unspecified":
                symbols = {"alpha": "α", "beta": "β", "gamma": "γ"}
                if meaning and phase in symbols:
                    r["name"] = f"{meaning.capitalize()} half-life ({symbols[phase]})"
                else:
                    r["name"] = f"{symbols[phase]}-phase half-life" if phase in symbols else phase.capitalize() + " half-life"
        if param == "AUC":
            r.update(_occasion_auc_review(e, unit))
            if r["unit_conflict"] or not unit:
                r.update(value=None, sd=None, unit="unit unresolved", as_printed_only=True)
        if param in ("CL", "CL_F"):
            r["source_item_id"] = e.get("source_item_id")
            r["source_analyte"] = analyte or (primary if qualifiers else meta.get("analyte"))
            r["source_dose_basis"] = meta.get("dose_basis")
            r["reported_assay"] = assay_of(e, {}, "plasma")[0]
        rec = records_by_id.get(record_id, {})
        r.update(animal_id=rec.get("animal_id") or rec.get("subject_id"),
                 clearance_comparison_id=meta.get("clearance_comparison_id"),
                 clearance_basis=meta.get("clearance_basis"), clearance_method=meta.get("clearance_method"),
                 clearance_assay=meta.get("clearance_assay"), clearance_regimen_id=meta.get("clearance_regimen_id"),
                 concentration_basis=meta.get("concentration_basis"), reported_source_refs=e.get("source_refs") or [])
        if rec.get("occasion") and r.get("analysis_unit") == "INDIVIDUAL" and param in ("CL", "CL_F", "CLR", "CLNR"):
            r["occasion"] = rec["occasion"]
        out.append(r)

    pcol = next((c for c in cs if re.search(r"parameter|quantity|measure", str(c.get("header", "")), re.I)), None)
    if pcol is not None:   # long layout
        qualified = {}
        for result in reviewed:
            qualified.setdefault((result["record_id"], result["source_col"]), []).append(result)
        vcols = [c for c in cs if c not in (pcol, dose_col) and not re.search(r"median|^\s*sd\s*$|^\s*se\s*$|unit|reported ±", str(c.get("header", "")), re.I)]
        sdcol = next((c for c in cs if re.fullmatch(r"\s*(sd|se)\s*", str(c.get("header", "")), re.I)), None)
        ucol = next((c for c in cs if str(c.get("header", "")).strip().lower() == "unit"), None)
        for rec in e.get("records", []):
            label = rec.get(pcol["id"])
            p = em_param(label)
            if re.match(r"^\s*AUC(?:\s*\(|\s*$)", str(label), re.I) and (
                meta.get("matrix_category") == "PLASMA_SERUM_BLOOD" or str(meta.get("matrix", "")).lower() in ("plasma", "serum", "blood")
            ):
                p = "AUC"
            if not p and not any((rec.get("record_id"), c["id"]) in qualified for c in vcols):
                continue
            um = re.search(r"\(([^()]+)\)\s*$", str(label))
            for c in vcols:
                matches = qualified.get((rec.get("record_id"), c["id"]))
                if matches:
                    for r in matches:
                        if r["matrix"] in ("plasma", "serum", "blood") and r["param"] in PNAME:
                            add(r["param"], label, parse_cell(r["raw"]), r["unit"], tab_sp, record_id=r["record_id"],
                                source_col=c["id"], qualifiers=r, dose_context=_row_dose(e, rec, dose_col) if dose_col else None)
                    continue
                if not p:
                    continue
                hdr = str(c.get("header", ""))
                occ = re.search(r"\bday\s*(\d+)", hdr, re.I)
                if p == "AUC" and not occ:
                    continue
                analyte = None if re.search(r"value|mean|printed|statement", hdr, re.I) or occ else hdr
                add(p, label, _record_cell(rec, c["id"]), (rec.get(ucol["id"]) if ucol else None) or (um.group(1) if um else None), tab_sp,
                    analyte=analyte, occasion=f"DAY_{occ.group(1)}" if occ else None, record_id=rec.get("record_id"),
                    sd=_record_cell(rec, sdcol["id"])["value"] if sdcol else None, source_col=c["id"],
                    sd_type=sdcol["header"].strip().upper() if sdcol else None,
                    sd_ref=f"{e['dataset_id']}:{rec.get('record_id')}:{sdcol['id']}" if sdcol else None,
                    dose_context=_row_dose(e, rec, dose_col) if dose_col else None)
    elif len(species_cols) >= 2:   # one column per species, one row per drug; parameter named in the title
        p = em_param(e.get("title"))
        if p:
            for rec in e.get("records", []):
                drug = str(rec.get(cs[0]["id"]) or "")
                for c in species_cols:
                    add(p, f"{e.get('title')} · {c.get('header')}", _record_cell(rec, c["id"]), c.get("unit"), species_of(c.get("header")),
                        analyte=drug, record_id=rec.get("record_id"), source_col=c["id"],
                        dose_context=_row_dose(e, rec, dose_col) if dose_col else None)
    else:                          # wide: one row per group or dose, one column per parameter
        gcol = cs[0] if cs[0].get("meaning") in ("GROUP_OR_TREATMENT", "COVARIATE") or re.search(r"species|group", h0) else None
        dcol = dose_col
        group = None
        for rec in e.get("records", []):
            if gcol is not None:
                g = rec.get(gcol["id"])
                group = str(g) if g not in (None, "") else group
            for c in cs:
                if c in (gcol, dcol):
                    continue
                p = em_param(c.get("header"))
                if not p and table_occ and str(meta.get("matrix", "")).lower() in ("plasma", "serum", "blood"):
                    # a table of one dosing day in a multi-day regimen: exposure by day is what Q3 compares
                    p = "AUC" if re.match(r"^\s*AUC\b", str(c.get("header")), re.I) else "CMAX" if re.match(r"^\s*C\s*max\b", str(c.get("header")), re.I) else None
                if not p:
                    continue
                um = re.search(r"\(([^()]+)\)\s*$", str(c.get("header")))
                add(p, c.get("header"), _record_cell(rec, c["id"]), c.get("unit") if c.get("unit") not in (None, "NOT_FOUND") else (um.group(1) if um else None),
                    species_of(group) or tab_sp, dose_context=_row_dose(e, rec, dcol) if dcol else None, record_id=rec.get("record_id"), source_col=c["id"],
                    occasion=table_occ)
    return out, scope


# ---------------------------------------------------------------- upstream records (B.4, B.9): bound by file, version and SHA-256

def load_upstream(root, name):
    p = Path(root) / name / f"{name}.json"
    if not p.is_file():
        return None, {"section": name, "present": False, "file": f"{name}/{name}.json"}
    raw = p.read_bytes()
    d = json.loads(raw.decode("utf-8-sig"))
    return d, {"section": name, "present": True, "file": f"{name}/{name}.json", "version": d.get("version"),
               "sha256": hashlib.sha256(raw).hexdigest(), "rule_specification": d.get("rule_specification")}


def absorption_index(a):
    """(dataset_id, series_id) -> {metrics, B1 file, card}; dataset_id -> card."""
    by, cards = {}, {}
    if not a:
        return by, cards
    for x in a.get("datasets", []) + a.get("iv_references", []):
        card = x.get("card") or {}
        cards[card.get("dataset_id")] = dict(card, _ind=x.get("B1ind") or x.get("A1ind"))
        for s in x.get("series", []) or []:
            by[(card.get("dataset_id"), s.get("series_id"))] = {"metrics": s.get("metrics") or {}, "B1": s.get("B1"), "A1": s.get("A1"), "card": card}
    return by, cards


def _upfile(section, f):
    return f"../{section}/{f}" if f else None


# ---------------------------------------------------------------- item 29: observed-window exposure and window clearance

def _pts(s):
    return sorted([p for p in s["points"] if p["status"] == "QUANTIFIED" and p["c"] is not None and p["c"] >= 0 and p["t"] is not None
                   and (p["t"] > 0 or (p["t"] == 0 and p["c"] == 0 and s.get("route_class") == "EV"))],
                  key=lambda p: p["t"])


def _assay_plasma(s):
    return assay_of(s, {}, "serum" if s.get("matrix_class") == "SERUM" else "plasma")[0]


def _clearance_compatibility(profile, parameter):
    """Check the quantities independently of the citation tying their experiments together."""
    issues = []
    def norm(value):
        return " ".join(str(value or "").casefold().replace("_", " ").split())

    name = norm(profile["source_analyte"])
    unknown = {"", "not found", "not reported", "unknown", "parent", "parent drug", "unspecified", "mixed"}
    if profile["analyte"] != "PARENT" or profile["assay"] in ("MICROBIOLOGICAL", "RADIOACTIVITY"):
        issues.append("The curve does not establish parent-specific exposure.")
    if name in unknown or ";" in name or name != norm(parameter.get("source_analyte")):
        issues.append("Matching analyte identity is unverified.")
    if parameter.get("reported_assay") in ("MICROBIOLOGICAL", "RADIOACTIVITY"):
        issues.append("The parameter table does not establish parent-specific exposure.")
    if norm(parameter.get("matrix")) != norm(profile["matrix"]):
        issues.append("Sample matrices differ or are unspecified.")
    pr, cr = norm(parameter.get("route_detail")), norm(profile["route_detail"])
    if profile["route"] == "EV":
        route_mismatch = pr in unknown | {"ev"} or pr != cr
    else:
        route_mismatch = pr not in unknown | {"iv"} and cr not in unknown | {"iv"} and pr != cr
    if parameter.get("route") != profile["route"] or route_mismatch:
        issues.append("The administration routes are incompatible or unresolved.")
    bases = [norm(x.get("source_dose_basis")) for x in (profile, parameter)]
    if all(b not in unknown | {"not stated"} for b in bases) and bases[0] != bases[1]:
        issues.append("The source dose bases differ.")
    restrictions = [*profile["source_restrictions"], *parameter.get("source_restrictions", [])]
    if any(x.get("operation") in {"CROSS_TABLE_LINKAGE", "PK_MODELING", "NCA", "TIME_AXIS_SELECTION"} for x in restrictions):
        issues.append("Source restrictions require review before comparison.")
    value = parameter.get("value_l_per_h_kg")
    if value is None or not math.isfinite(value) or value <= 0 or parameter.get("as_printed_only"):
        issues.append("A positive clearance in L/h/kg is unavailable.")
    return issues


def _compare_reported_clearance(profile, reported, source, cfg):
    """A reviewed link identifies an exact series and parameter cell, with their source items."""
    want = "CL_F" if profile["route"] == "EV" else "CL"
    links = (cfg.get("reported_clearance_links") or {}).get(profile["sid"], [])
    links = [link for link in links if isinstance(link, dict)] if isinstance(links, list) else []
    candidates = []
    for p in reported:
        if ((p["study"], p["species"], p["param"], p.get("dose"), p.get("occasion")) !=
                (profile["study"], profile["species"], want, profile["dose_mg_per_kg"], "FIRST_DOSE")):
            continue
        issues = _clearance_compatibility(profile, p)
        citations = sorted({link["source"].strip() for link in links
                            if p.get("source_cell") and link.get("parameter_cell") == p["source_cell"]
                            and source.get("source_item_id") and link.get("profile_item") == source["source_item_id"]
                            and p.get("source_item_id") and link.get("parameter_item") == p["source_item_id"]
                            and isinstance(link.get("source"), str) and link["source"].strip()})
        status = "LINK_UNVERIFIED" if not citations else ("INCOMPATIBLE" if issues else "MATCHED")
        candidates.append({"dataset_id": p["dataset_id"], "record_id": p["record_id"], "source_cell": p.get("source_cell"),
                           "label": p["label"], "raw": p["raw"], "unit": p["unit"], "source_item": p.get("source_item_id"),
                           "value_l_per_h_kg": p.get("value_l_per_h_kg"), "status": status, "issues": issues,
                           "citations": citations})
    if not candidates:
        return
    candidates.sort(key=lambda c: (c["dataset_id"], c["record_id"], c["source_cell"] or "", json.dumps(c, sort_keys=True)))
    profile["reported_cl_candidates"] = candidates
    eligible = [c for c in candidates if c["status"] == "MATCHED"]
    if len(eligible) != 1:
        for c in eligible:
            c.update(status="AMBIGUOUS", issues=["Multiple reported estimates match this profile."])
        return
    c, = eligible
    ratio = c["value_l_per_h_kg"] / profile["window_proxy"]
    direction = "above" if ratio > 1 else ("below" if ratio < 1 else "equal to")
    profile["reported_cl_check"] = {"dataset_id": c["dataset_id"], "record_id": c["record_id"], "label": c["label"],
        "profile_id": profile["sid"], "profile_item": source["source_item_id"], "parameter_item": c["source_item"],
        "source_cell": c["source_cell"], "source": " | ".join(c["citations"]), "as_printed": f"{c['raw']} {c['unit']}",
        "value_l_per_h_kg": c["value_l_per_h_kg"], "ratio_to_window": ratio,
        "flag": "REPORTED_CL_ABOVE_WINDOW" if ratio > 1 else None,
        "reading": f"The reported clearance is {direction} the dose-to-observed-AUC ratio for this profile."}
    if ratio > 1:
        profile["caveats"].append("REPORTED_CL_ABOVE_WINDOW")


def _ongoing_rate_ratio(s):
    """Descriptive input-rate/sample-mean ratio; sample stability cannot establish steady state."""
    regimen = s.get("regimen") or {}
    rate, factor = regimen.get("infusion_rate_mg_kg_h"), s.get("uf")
    if (s.get("route_class") != "IV" or s.get("iv_mode") != "ONGOING_INPUT"
            or s.get("matrix_class") not in ("PLASMA", "SERUM") or s.get("analyte") != "PARENT"
            or s.get("unbound") or _assay_plasma(s) != "SPECIFIC"
            or isinstance(rate, bool) or not isinstance(rate, (int, float)) or not math.isfinite(rate) or rate <= 0
            or isinstance(factor, bool) or not isinstance(factor, (int, float)) or not math.isfinite(factor) or factor <= 0):
        return None
    for p in s.get("points", []):
        if p.get("status") == "QUANTIFIED" and p.get("t") is not None and p["t"] > 0:
            c = p.get("c")
            if not isinstance(c, (int, float)) or not math.isfinite(c) or c <= 0:
                return None
    pts = _pts(s)
    start = regimen.get("infusion_start_h")
    if start is not None:
        pts = [p for p in pts if p["t"] >= start]
    if len(pts) < 2 or len({p["t"] for p in pts}) != len(pts):
        return None
    cs = [p["c"] * factor for p in pts]
    if any(not math.isfinite(c) or c <= 0 for c in cs):
        return None
    mean, fold = sum(cs) / len(cs), max(cs) / min(cs)
    return {"infusion_rate_mg_kg_h": rate, "mean_concentration_mg_l": mean, "n": len(cs), "window_h": [pts[0]["t"], pts[-1]["t"]], "fold": fold,
            "sample_variation": "WITHIN_BAND" if fold <= dist.BAND[1] else "OUTSIDE_BAND", "steady_state_established": False,
            "value_l_per_h_kg": rate / mean, "label": "CONDITIONAL_ON_STEADY_STATE", "mean_basis": "arithmetic mean at sampled times, not a time-weighted mean",
            "regimen": dist._regimen_text(s), "analysis_unit": s.get("level"), "profile_id": s.get("sid"), "dataset_id": s.get("dataset_id")}


def _ongoing_text(o):
    return (f"Infusion rate over the arithmetic mean concentration at {o['n']} sampled times across {_f(o['window_h'][0])}–{_f(o['window_h'][1])} h is "
            f"approximately {o['value_l_per_h_kg']:.3g} L/h/kg ({o['infusion_rate_mg_kg_h']:g} mg/kg/h over {_f(o['mean_concentration_mg_l'])} mg/L; concentrations vary "
            f"{o['fold']:.2f}-fold). This is a descriptive ratio of group means when the profile contains group summaries, without an uncertainty interval. "
            "It equals CL only under constant IV input at steady state with parent-specific total plasma exposure; small variation across these samples does not establish steady state.")


def item29(s, abs_idx, abs_meta, d24, board_binding, reported, cfg, *, source=None):
    sid_col = s["sid"].split(":", 1)[1] if ":" in s["sid"] else s["sid"]
    r = {"item_id": 29, "sid": s["sid"], "label": s["label"], "dataset_id": s["dataset_id"], "study": s["study"], "species": s["species"],
         "route": s["route_class"], "route_detail": s["route_detail"], "iv_mode": s.get("iv_mode"), "dose_mg_per_kg": s["dose"],
         "dose_basis": s["dose_basis"], "matrix": s["matrix_class"], "analysis_unit": s["level"], "assay": _assay_plasma(s),
         "dose_exposure_target": None, "auc_window": None, "auc_window_h": None, "auc_method": "linear-up/log-down (A0.6)", "auc_source": None,
         "window_proxy": None, "window_quantity": None, "cl_upper_window": None, "cl_upper_tail": None, "cl_upper_conditional_area": None,
         "bound_kind": "none", "cl_u_upper": None, "cl_blood_upper": None, "cl_u_window_proxy": None, "reported_cl_check": None,
         "caveats": [], "not_assessable_reason": None, "sensitivity_rows": [], "upstream_panel": None}
    cav = r["caveats"]
    active = r["assay"] == "MICROBIOLOGICAL"
    r["analyte"] = "ACTIVE_MATERIAL" if active else s.get("analyte", "PARENT")
    source = source or {}
    meta = source.get("metadata") or {}
    named = meta.get("analyte")
    named = None if named in (None, "", "NOT_FOUND", "NOT_REPORTED") else named
    r.update(source_restrictions=source.get("operation_restrictions") or [],
             source_analyte=meta.get("analyte"), source_dose_basis=meta.get("dose_basis"),
             full_exposure_target=None)
    if active:
        r["measurement_basis"] = "antimicrobial activity (bioassay)"
    elif r["assay"] == "SPECIFIC":
        r["measurement_basis"] = f"{named or 'parent drug'} (selective assay)"
    else:
        r["measurement_basis"] = (f"reported {named} concentration (assay unreported)" if named
                                  else "reported concentration (parent identity unverified)")
        if not named:
            cav.append("PARENT_IDENTITY_UNVERIFIED")
    if s["route_class"] not in ("IV", "EV"):
        r["not_assessable_reason"] = "route unknown"
        return r
    if s["occasion"] != "FIRST_DOSE":
        r["not_assessable_reason"] = "not an isolated first dose; a later dosing interval is never used as a single-dose area"
        return r
    if s["route_class"] == "IV" and s.get("iv_mode") == "ONGOING_INPUT":
        r["not_assessable_reason"] = f"samples were taken during ongoing IV input ({dist._regimen_text(s)}), not after an isolated dose"
        r["ongoing_input"] = _ongoing_rate_ratio(s)
        return r
    if not s["dose"] or s["dose"] <= 0:
        r["not_assessable_reason"] = "dose not found (gate 1)"
        return r
    if s.get("uf") is None:
        r["not_assessable_reason"] = "concentration unit not convertible to mg/L"
        return r
    if dist._baseline(s)[0]:
        r["not_assessable_reason"] = "unresolved endogenous or predose signal (ENDOGENOUS_REVIEW_REQUIRED)"
        cav.append("ENDOGENOUS_REVIEW_REQUIRED")
        return r
    ev = s["route_class"] == "EV"
    r["full_exposure_target"] = "CL/F" if ev else "CL"
    r["dose_exposure_target"] = f"Estimating {r['full_exposure_target']} requires verified parent-drug exposure over the full profile."
    r["window_quantity"] = "dose / observed AUC"
    if active:
        r["full_exposure_target"] = None
        r["dose_exposure_target"] = "Estimating parent-drug clearance requires parent-specific exposure over the full profile."
        r["window_quantity"] = "dose/activity AUC"
    if ev:
        cav.append("EV_OVER_F")
    if s["level"] in ("GROUP_MEAN",):
        cav += ["GROUP_MEAN", "GROUP_CURVE_RATIO"]
    if s.get("design") == "DESTRUCTIVE":
        cav.append("DESTRUCTIVE_SAMPLING")
    if s.get("digitized"):
        cav.append("DIGITIZED")
    if r["assay"] == "MICROBIOLOGICAL":
        cav.append("ACTIVE_MATERIAL_ASSAY")
    if s["route_class"] == "IV" and s.get("iv_mode") in ("INFUSION_TIMING_UNKNOWN", "IV_MODE_UNKNOWN"):
        cav.append("INFUSION_TIMING_UNKNOWN")
    if s["dose_basis"] in (None, "", "NOT_FOUND") or "not stated" in str(s["dose_basis"]):
        cav.append("DOSE_BASIS_NOT_STATED")
    q = _pts(s)
    # interior BLQ is not bridged (E0.5): keep the first contiguous quantified run
    blq_t = sorted(p["t"] for p in s["points"] if p["status"] == "BLQ" and p["t"] is not None and p["t"] > 0)
    if q and any(q[0]["t"] < t < q[-1]["t"] for t in blq_t):
        cut = min(t for t in blq_t if q[0]["t"] < t < q[-1]["t"])
        q = [p for p in q if p["t"] < cut]
        cav.append("INTERIOR_BLQ_NOT_BRIDGED")
    # the upstream panel this row sits under
    up = abs_idx.get((s["dataset_id"], sid_col))
    if ev and up and up.get("B1"):
        r["upstream_panel"] = {"section": "absorption", "panel": "B1", "file": _upfile("absorption", up["B1"])}
    # window AUC: upstream A0.6 record first
    m = up["metrics"] if up else {}
    if str(m.get("auc_status", "")).startswith("WITHHELD"):
        r["not_assessable_reason"] = f"the absorption record withholds the window AUC for this profile ({m['auc_status']}); it is not recomputed here"
        return r
    t = [p["t"] for p in q]
    postdose_n = len({time for time in t if time > 0})
    if postdose_n < 3 or len(set(t)) != len(t):
        r["not_assessable_reason"] = (f"fewer than 3 quantified post-dose times ({postdose_n})" if postdose_n < 3 else
                                      "duplicate times in this profile; resolve the analysis unit before integration")
        return r
    r["n_points"] = len(q)
    r["auc_record_ids"] = [p["record_id"] for p in q if p.get("record_id")]
    if (m.get("auc_observed") is not None and [m.get("auc_window_start_h"), m.get("auc_window_end_h")] == [t[0], t[-1]]
            and m.get("auc_grid_h") == t and m.get("auc_record_ids") == r["auc_record_ids"]
            and str(m.get("auc_method")).lower().startswith("linear-up/log-down")):
        r["auc_window"] = m["auc_observed"] * s["uf"]
        r["auc_window_h"] = [t[0], t[-1]]
        r["auc_source"] = f"absorption record {abs_meta.get('version')} · {s['dataset_id']}/{sid_col} ({m.get('auc_status')})"
        r["auc_method"] = m["auc_method"]
    if r["auc_window"] is None:
        c = [p["c"] * s["uf"] for p in q]
        r["auc_window"] = ab.auc(t, c)
        r["auc_window_h"] = [t[0], t[-1]]
        r["auc_source"] = "computed from the observed points with the shared A0.6 routine; no reusable upstream area on this grid"
    if not r["auc_window"] or r["auc_window"] <= 0:
        r["not_assessable_reason"] = "no positive supported area"
        return r
    a, b = r["auc_window_h"]
    if a and a > 0:
        cav.append("PARTIAL_WINDOW")
    cav.append("WINDOW_PROXY")
    r["window_proxy"] = s["dose"] / r["auc_window"]
    r["window_units"] = "L/h/kg"
    r["window_ml_min_kg"] = r["window_proxy"] * ML_MIN_KG_PER_L_H_KG
    r["value_row"] = (f"{r['dataset_id']} ({r['label']}, {_lvl(r['analysis_unit'])}): the dose-to-observed-AUC ratio "
                      f"was {_f(r['window_proxy'])} L/h/kg over {_f(a)}–{_f(b)} h, based on {r['measurement_basis']}.")
    r["direction_note"] = ("Leaving out the area before and after the window puts this value on the high side of D/AUC(0,∞) when the trapezoid "
                           "is accurate. Integration error is not bounded here, so the net direction for this profile is unresolved (E0.6).")
    _compare_reported_clearance(r, reported, source, cfg)
    r["justified_limit"] = {"value": None, "reason": "no justified positive lower limit on the true area: a sampled trapezoid is not one (E0.6)"}
    if active:
        r["direction_note"] = "The bioassay measures antimicrobial activity from the parent and any active products. Parent clearance needs an analyte-specific plasma assay."
        r["conditional_area_omitted"] = r["unbound_reason"] = "the antimicrobial activity signal is not specific to the parent"
        return r
    # conditional area limit (IV after input ended, non-rising window)
    q_all = q
    if not ev and s.get("iv_mode") in ("BOLUS", "INFUSION") and "INFUSION_TIMING_UNKNOWN" not in cav:
        t_end = s.get("infusion_h") or 0.0
        post = [p for p in q_all if p["t"] >= t_end - 1e-9]
        rising = any(post[j]["c"] * (1 - TOL) > post[i]["c"] * (1 + TOL) for i in range(len(post)) for j in range(i + 1, len(post)))
        if len(post) >= 2 and not rising:
            L = sum(post[i + 1]["c"] * s["uf"] * (1 - TOL) * (post[i + 1]["t"] - post[i]["t"]) for i in range(len(post) - 1))
            r["cl_upper_conditional_area"] = s["dose"] / L if L > 0 else None
            r["sensitivity_rows"].append({"kind": "CONDITIONAL_AREA", "bound_kind": "SENSITIVITY_ONLY", "quantity": "CL",
                                          "value": r["cl_upper_conditional_area"], "L_cond": L, "window": [post[0]["t"], post[-1]["t"]],
                                          "assumption": "the concentration does not rise over the window (stated, not tested); lower concentration at the "
                                                        f"right end of each interval, project tolerance ±{int(TOL * 100)} %",
                                          "text": f"CL ≤ {_f(r['cl_upper_conditional_area'])} L/h/kg if the curve does not rise over "
                                                  f"{_f(post[0]['t'])}–{_f(post[-1]['t'])} h (conditional area limit)"})
            # conditional tail: only with an eligible upstream T7 NOT_EXCLUDED (item 24)
            t7 = (d24 or {}).get("t7_label")
            t7_ok = t7 == "NOT_EXCLUDED" and "SENSITIVITY_ONLY" not in ((d24 or {}).get("t7_flags") or [])
            if (t7_ok and len(post) >= 2 and post[-1]["c"] > 0
                    and post[-1]["c"] * (1 + TOL) < post[-2]["c"] * (1 - TOL)):
                p1, p2 = post[-2], post[-1]
                s_neg = (math.log(p2["c"] * (1 - TOL)) - math.log(p1["c"] * (1 + TOL))) / (p2["t"] - p1["t"])
                if s_neg < 0:
                    tail = p2["c"] * s["uf"] * (1 - TOL) / (-s_neg)
                    r["cl_upper_tail"] = s["dose"] / (L + tail)
                    r["sensitivity_rows"].append({"kind": "CONDITIONAL_TAIL", "bound_kind": "SENSITIVITY_ONLY", "quantity": "CL", "value": r["cl_upper_tail"],
                                                  "tail_low": tail, "slope": s_neg, "t7": t7,
                                                  "assumption": "positive exponential sum, completed central IV input, zero initial state; ln C stays convex after the last sample",
                                                  "text": f"CL ≤ {_f(r['cl_upper_tail'])} L/h/kg with the last-chord tail (conditional tail limit)"})
                    cav.append("CONDITIONAL_TAIL")
            else:
                r["tail_omitted"] = (f"upstream T7 is {t7 or 'missing'}; the conditional tail needs an eligible NOT_EXCLUDED"
                                     if not t7_ok else "the last positive log-chord is not strictly negative throughout the allowed intervals")
            if r["cl_upper_conditional_area"]:
                cav.append("CONDITIONAL_AREA")
                r["bound_kind"] = "SENSITIVITY_ONLY"
        else:
            r["conditional_area_omitted"] = "a later point lies above an earlier one beyond their allowed intervals" if rising else "fewer than 2 post-input points"
    elif ev:
        r["conditional_area_omitted"] = "not formed for EV profiles"
    # unbound: divide a limit only by a supported lower limit of a constant fu,p (step 6)
    fu_cfg = (cfg.get("fu_p") or {}).get(f"{s['study']}|{s['species']}") or {}
    fu_low = _num(fu_cfg.get("low")) if fu_cfg.get("constant_over_exposure") is True and fu_cfg.get("source") else None
    src = fu_cfg.get("source") if fu_low else None
    exposure_supported = fu_low is not None
    if fu_low is None and board_binding:
        const = [x for x in board_binding.get("constant_fu_sources", []) if x.get("fu_range")
                 and x.get("series") == s["sid"] and x.get("condition") == s.get("condition") and x.get("drug") == s.get("drug")]
        if const:
            fu_low = min(x["fu_range"][0] for x in const)
            src = "item 27, sampled concentration range: " + ", ".join(sorted({x["dataset_id"] for x in const}))
    lim = r["cl_upper_tail"] or r["cl_upper_conditional_area"]
    if fu_low and 0 < fu_low <= 1:
        r["cl_u_window_proxy"] = r["window_proxy"] / fu_low
        if lim and exposure_supported:
            r["cl_u_upper"] = lim / fu_low
        r["fu_used"] = {"low": fu_low, "source": src, "scope": "full exposure" if exposure_supported else "observed window only"}
    else:
        r["unbound_reason"] = "no supported lower limit of a constant fu,p over the exposure (item 27)"
    r["caveats"] = list(dict.fromkeys(cav))
    return r


# ---------------------------------------------------------------- items 30 and 31: read the upstream results

FORMAL_RESULTS = {"NOT_EXCLUDED", "EXCLUDED_UNDER_STATED_ASSUMPTIONS"}
LIMITED_TEST_FLAGS = {"SENSITIVITY_ONLY", "BORDERLINE", "SINGLE_POINT_SUPPORT", "CONDITIONAL_ON_LABEL_IDENTITY"}


def _has_dose_test(row):
    return row.get("t3") in FORMAL_RESULTS or row.get("t3p") in FORMAL_RESULTS


def _reported_auc_series(table):
    """Read explicitly paired AUC and dose cells within a single reported table and group."""
    cols, meta = _cols(table), table.get("metadata") or {}
    if meta.get("matrix_category") != "PLASMA_SERUM_BLOOD" and str(meta.get("matrix") or "").lower() not in {"plasma", "serum", "blood"}:
        return []
    doses = [c for c in cols if c.get("meaning") == "DOSE" and str(c.get("unit") or "").lower() == "mg/kg"]
    aucs = [c for c in cols if re.match(r"^(?:total\s+)?auc(?:\s*\(|$)", c.get("header", ""), re.I)
            and c.get("unit") not in (None, "", "NOT_FOUND") and "/" not in c["header"].split("(")[0]]
    if len(doses) != 1 or not aucs:
        return []
    dose = doses[0]
    groups = [c["id"] for c in cols if c.get("meaning") == "GROUP_OR_TREATMENT"]
    labels = {key: None for key in groups}
    series = {}
    for row in table["records"]:
        labels.update({key: row[key] for key in groups if row.get(key) not in ("", None)})
        group = " / ".join(str(x) for x in labels.values() if x is not None)
        species = species_of(group) or species_of(meta.get("species") or "")
        amount = _record_cell(row, dose["id"])
        if (not species or (groups and any(x is None for x in labels.values()))
                or amount["state"] != "QUANTIFIED" or amount["value"] is None or amount["value"] <= 0):
            continue
        for col in aucs:
            key = (group, species, col["id"])
            if key not in series:
                series[key] = {"key": f"{table['dataset_id']} {group or species} {col['header']}", "dataset_id": table["dataset_id"],
                               "study": _study(table), "species": species, "route": meta.get("route_class"), "group": group,
                               "window": meta.get("endpoint_window"), "basis": "source-reported AUC", "auc_unit": col["unit"],
                               "unit": f"({col['unit']})/(mg/kg)", "source_restrictions": table.get("operation_restrictions") or [],
                               "source_analyte": meta.get("analyte"), "record_level": meta.get("record_level"),
                               "assay": assay_of(table, {}, "plasma")[0], "rows": []}
            cell = _record_cell(row, col["id"])
            value = cell["value"] if cell["state"] == "QUANTIFIED" else None
            series[key]["rows"].append({"dose": amount["value"], "auc": value, "auc_per_dose": value / amount["value"] if value is not None else None,
                                        "state": cell["state"], "refs": [f"{table['dataset_id']}:{row['record_id']}:{k}" for k in (dose["id"], col["id"])]})
    return [dict(s, rows=sorted(s["rows"], key=lambda r: r["dose"])) for s in series.values()
            if len({r["dose"] for r in s["rows"]}) == len(s["rows"])
            and len({r["dose"] for r in s["rows"] if r["auc_per_dose"] is not None}) >= 2]


def _curve_exposure(d, abs_data):
    cards = {x["card"]["dataset_id"]: x["card"] for x in abs_data.get("datasets", [])}
    rows = sorted(d.get("rows") or [], key=lambda row: row["dose"])
    units = {cards.get(r["dataset_id"], {}).get("unit") for r in rows}
    if len(units) != 1 or None in units or not rows:
        return None
    conc_unit = units.pop()
    # the absorption dose series is integrated from the dosing time, and carries only the end of its common window
    start = d.get("window_start_h")
    return {"basis": "observed common-window AUC", "window": [0.0 if start is None else start, d.get("window_end_h")],
            "unit": "h·kg/L" if conc_unit == "mg/L" else f"({conc_unit}·h)/(mg/kg)",
            "rows": [{"dose": r["dose"], "auc_per_dose": r.get("aucW_d"), "cmax_per_dose": r.get("cmax_d"),
                      "refs": [f"{r['dataset_id']}:{r['series_id']}"]} for r in rows],
            "peak_ratio": d.get("cmax_d_ratio"), "peak_reading": d.get("cmax_label"),
            "test_reason": d.get("t3_reason_en"), "pointwise_reason": (d.get("t3p") or {}).get("reason")}


def _reported_iv_clearance_contrasts(board, reported, specifications, kind):
    """Prespecified two-arm comparisons of source-reported individual true IV CL.

    Design assertions are explicit source-reviewed configuration, never inferred from
    a matching animal number, a group mean, or serial plasma samples.
    """
    results = []
    unknown = {'', 'unknown', 'not reported', 'not_reported', 'not_found', 'not stated', 'unspecified', 'none', 'not found'}
    norm = lambda x: ' '.join(str(x or '').casefold().split())
    positive = lambda x: isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) and x > 0
    for spec in specifications or ():
        if (not isinstance(spec, dict) or spec.get('kind') != kind or
                (spec.get('study'), norm(spec.get('species'))) != (board['study'], norm(board['species']))):
            continue
        out = dict(id=spec.get('id'), kind=kind, status='NOT_ASSESSABLE', reasons=[], source_cells=[],
                   design_source=spec.get('design_source'), design=spec.get('design'))
        results.append(out)
        def reject(message):
            out['reasons'].append(message)
        if (not spec.get('id') or not spec.get('comparison_id') or spec.get('prespecified') is not True
                or spec.get('design_verified') is not True or not str(spec.get('design_source') or '').strip()):
            reject('A prespecified contrast and source-reviewed design are required.'); continue
        design = spec.get('design')
        if design not in ('PAIRED_ANIMALS', 'INDEPENDENT_ANIMALS'):
            reject('Paired or independent animal design is unresolved.'); continue
        arms = [spec.get(k) or {} for k in ('a', 'b')]
        if any(not isinstance(a, dict) or not positive(a.get('dose_mg_kg')) or norm(a.get('occasion')) in unknown for a in arms):
            reject('Both arms need an exact positive dose and identified occasion.'); continue
        rosters = [a.get('animal_ids') for a in arms]
        if any(not isinstance(ids, list) or len(ids) < 2 or
               any(not isinstance(i, str) or not i.strip() for i in ids) or
               len({i.strip() for i in ids}) != len(ids) for ids in rosters):
            reject('Each arm requires an explicit unique enrolled animal_ids roster; missing animals are not silently dropped.'); continue
        expected_ids = [{i.strip() for i in ids} for ids in rosters]
        if kind == 'DOSE' and not (arms[0]['dose_mg_kg'] != arms[1]['dose_mg_kg'] and arms[0]['occasion'] == arms[1]['occasion']):
            reject('Dose comparison requires distinct doses at the same occasion.'); continue
        if kind == 'OCCASION' and not (arms[0]['dose_mg_kg'] == arms[1]['dose_mg_kg'] and arms[0]['occasion'] != arms[1]['occasion']):
            reject('Occasion comparison requires the same dose at distinct occasions.'); continue
        local = [p for p in reported if (p.get('study'), norm(p.get('species'))) == (board['study'], norm(board['species']))
                 and p.get('clearance_comparison_id') == spec['comparison_id'] and p.get('param') in ('CL', 'CL_F', 'CLR', 'CLNR')]
        groups = [[p for p in local if p.get('dose') == a['dose_mg_kg'] and p.get('occasion') == a['occasion']] for a in arms]
        ps = groups[0] + groups[1]
        if any(len(g) < 2 for g in groups):
            reject('At least two source-linked individual animals per arm are required.'); continue
        compatible = ('reported_analyte', 'matrix', 'concentration_basis', 'clearance_assay', 'clearance_method', 'source_dose_basis', 'clearance_regimen_id')
        contexts = set()
        for p in ps:
            if (p.get('param') != 'CL' or p.get('route') != 'IV' or p.get('clearance_basis') != 'TRUE_SYSTEMIC'
                    or p.get('analysis_unit') != 'INDIVIDUAL' or not p.get('animal_id')
                    or p.get('reported_analyte_role') != 'PARENT' or p.get('state') != 'QUANTIFIED'
                    or not positive(p.get('value')) or not positive(p.get('value_l_per_h_kg')) or p.get('as_printed_only') or p.get('dose_conflict')
                    or p.get('sd') is not None or p.get('censoring') or p.get('source_restrictions')
                    or not p.get('source_cell') or not any(isinstance(ref, dict) and ref.get('sha256') and ref.get('location') for ref in p.get('reported_source_refs', []))):
                reject('Only uncensored source-linked individual parent true IV clearance is eligible; summary/apparent/restricted values are excluded.'); break
            if (any(norm(p.get(k)) in unknown for k in compatible)
                    or norm(p.get('matrix')) not in ('plasma', 'serum', 'blood')
                    or norm(p.get('concentration_basis')) not in ('total', 'unbound')
                    or re.search(r'radioact|14\s*c|metabolite|mixed|active material', norm(p.get('reported_analyte')))
                    or norm(p.get('route_detail')) in unknown):
                reject('Analyte, matrix, total/unbound basis, assay, dose basis and clearance method must be identified.'); break
            contexts.add(tuple(norm(p.get(k)) for k in compatible) +
                         (p.get('route_detail'), p.get('condition'), p.get('dosing_interval_h')))
        if out['reasons']:
            continue
        if len(contexts) != 1:
            reject('Measurement or regimen conditions differ across the selected arms.'); continue
        by_id = [{str(p['animal_id']).strip(): p for p in g} for g in groups]
        if any(len(d) != len(g) for d, g in zip(by_id, groups)):
            reject('Duplicate animal estimates within an arm cannot be treated as replicate animals.'); continue
        ids = [set(d) for d in by_id]
        if ids != expected_ids:
            reject('Native animal sets differ from the prespecified enrolled rosters; missing, excluded or additional animals prevent inference.'); continue
        if design == 'PAIRED_ANIMALS' and ids[0] != ids[1]:
            reject('Verified paired design requires the same animal identities with complete pairs.'); continue
        if design == 'INDEPENDENT_ANIMALS' and ids[0] & ids[1]:
            reject('Independent arms must have distinct source-scoped animal identities.'); continue
        logs = [[math.log(p['value_l_per_h_kg']) for p in g] for g in groups]
        mean = lambda values: sum(values) / len(values)
        variance = lambda values: sum((v - mean(values)) ** 2 for v in values) / (len(values) - 1)
        effect = mean(logs[1]) - mean(logs[0])
        if design == 'PAIRED_ANIMALS':
            differences = [math.log(by_id[1][i]['value_l_per_h_kg']) - math.log(by_id[0][i]['value_l_per_h_kg']) for i in sorted(ids[0])]
            se, df = math.sqrt(variance(differences) / len(differences)), len(differences) - 1
            method = 'paired t test of individual log clearance'
        else:
            parts = [variance(v) / len(v) for v in logs]
            se = math.sqrt(sum(parts))
            denominator = sum(v * v / (len(g) - 1) for v, g in zip(parts, groups))
            df = sum(parts) ** 2 / denominator if denominator > 0 else None
            method = 'Welch t test of independent individual log clearance'
        if not se or not math.isfinite(se) or not df or df <= 0:
            reject('Sampling variance is not estimable; no artificial variance floor or p-value is used.'); continue
        half = ab.t_ppf(0.975, df) * se
        try:
            ratio, ci = math.exp(effect), [math.exp(effect - half), math.exp(effect + half)]
        except OverflowError:
            reject('The uncertainty interval is numerically unbounded.'); continue
        if not all(positive(v) for v in [ratio, *ci]):
            reject('The uncertainty interval is numerically unbounded.'); continue
        pvalue = ab._p_t(effect / se, df)
        out.update(status='ASSESSED', method=method, n=[len(g) for g in groups], arms=arms,
                   geometric_mean_clearance_l_h_kg=[math.exp(mean(v)) for v in logs],
                   ratio_b_over_a=ratio, ci95=ci, p=pvalue, df=df, log_ratio=effect, log_ratio_se=se,
                   source_cells=[p['source_cell'] for p in ps],
                   reading='DIFFERENCE_DETECTED' if pvalue < 0.05 else 'NO_DIFFERENCE_DETECTED',
                   multiplicity='Nominal per prespecified contrast; no multiplicity correction across contrasts.',
                   scope='Two-sided exploratory comparison of measured clearance; not equivalence, a mechanism test, or proof of dose proportionality/time invariance.')
    return results


def _clearance_contrast_question(qn, contrasts):
    """Render direct clearance measurements separately from upstream exposure patterns."""
    assessed = [r for r in contrasts if r.get('status') == 'ASSESSED']
    if not assessed:
        return None
    rows = [[r['id'], ', '.join(map(str, r['n'])), _f(r['ratio_b_over_a'], 4),
             ' to '.join(_f(x, 4) for x in r['ci95']), _f(r['p'], 4), r['reading']] for r in assessed]
    primary = _rowprim(qn, ['Contrast', 'Animals A, B', 'Geometric CL ratio B/A', '95% CI', 'Two-sided p', 'Reading'],
                       rows, 'Source-reported individual true IV clearance', 'Individual animals')
    evidence = [{'rule': r['method'] + '. ' + r['scope'], 'data': r['source_cells'],
                 'tables': [{'caption': 'Source-reviewed design', 'head': ['Contrast', 'Design', 'Source'],
                             'rows': [[r['id'], r['design'], r['design_source']]]}]} for r in assessed]
    first = assessed[0]
    return _qrow(qn, ST_YES,
        f"Source-reported individual true IV clearance: geometric ratio B/A {first['ratio_b_over_a']:.3g} "
        f"(95% CI {first['ci95'][0]:.3g}–{first['ci95'][1]:.3g}; two-sided p={first['p']:.3g}).",
        first['method'] + '; source-reviewed animal design and compatible measurements.',
        'A comparison of measured clearance does not establish a mechanism. A nonsignificant result does not establish equivalence, dose proportionality or time invariance. P-values and 95% intervals are nominal per prespecified contrast; no multiplicity adjustment across contrasts.',
        primary=primary, evidence=evidence)


def item30(board, plasma, dist_board, abs_data, reported, urine_obs, reported_auc=(), clearance_contrasts=()):
    doses = sorted({s["dose"] for s in plasma if s["dose"]})
    out = {"item_id": 30, "dose_range": [doses[0], doses[-1]] if doses else None, "doses": doses, "upstream": [], "caveats": [],
           "reported_by_dose": [], "urine_by_dose": [], "alternatives": [], "next_discriminator": None, "not_assessable_reason": None}
    out["reported_auc"] = [s for s in reported_auc if (s["study"], s["species"]) == (board["study"], board["species"])]
    for q8 in (dist_board or {}).get("q8_evidence", []):
        out["upstream"].append({"source": f"absorption item 19 via distribution ({q8.get('version')})", "route": q8["route"], "key": q8["key"],
                                "doses": q8["doses"], "window_h": q8["window"], "auc_ratio": q8.get("auc_ratio"), "t3": q8["t3"], "t3p": q8["t3p"],
                                "panel": q8.get("figure"), "panel_id": "C2" if q8["route"] == "EV" else "C1",
                                "caveats": q8.get("caveats", [])})
    for d in (dist_board or {}).get("dose_patterns", []):
        out["upstream"].append({"source": "distribution item 24 (DIS-2)", "route": "IV", "key": d.get("key"), "doses": d.get("doses"), "window_h": None,
                                "auc_ratio": None, "t3": "—", "t3p": (d.get("t3p") or {}).get("label", "CANNOT_ASSESS"), "pattern": d.get("dose_pattern"),
                                "panel": _upfile("distribution", (dist_board.get("figs") or {}).get(f"DIS2|{d.get('key')}")), "panel_id": "DIS-2b",
                                "caveats": list((d.get("t3p") or {}).get("flags") or []) + (["CONFOUNDED"] if d.get("confounded") else []),
                                "upstream_candidates": d.get("candidates") or []})
    # absorption dose series not carried by distribution (same study, any listed dataset)
    seen = {u["key"]: u for u in out["upstream"]}
    ds_ids = {s["dataset_id"] for s in plasma}
    for d in (abs_data or {}).get("dose_series", []):
        if not ds_ids.intersection(d.get("dataset_ids") or []):
            continue
        if d.get("key") in seen:
            via_distribution = seen[d["key"]]
            if via_distribution["route"] == "EV":
                via_distribution["exposure"] = _curve_exposure(d, abs_data)
            if via_distribution["route"] == "EV" and not via_distribution["panel"]:
                via_distribution["panel"] = _upfile("absorption", d.get("C2"))
            continue
        out["upstream"].append({"source": f"absorption item 19 ({abs_data.get('version')})", "route": "EV", "key": d.get("key"), "doses": d.get("doses"),
                                "window_h": f"{_f(d.get('window_start_h'))} to {_f(d.get('window_end_h'))}", "auc_ratio": d.get("R_window"),
                                "t3": d.get("t3_label") or "CANNOT_ASSESS", "t3p": (d.get("t3p") or {}).get("t3p_label") or "CANNOT_ASSESS",
                                "exposure": _curve_exposure(d, abs_data),
                                "panel": _upfile("absorption", d.get("C2")), "panel_id": "C2", "caveats": list(map(str, d.get("t3_flags") or []))})
    out["reported_by_dose"] = [p for p in reported if p["study"] == board["study"] and p["species"] == board["species"] and p["param"] in ("CL", "CL_F", "THALF")
                               and p.get("dose") is not None and len({x["dose"] for x in reported if x["dataset_id"] == p["dataset_id"] and x["species"] == p["species"] and x.get("dose") is not None}) >= 2]
    ub = {}
    for o in urine_obs:
        if o["analyte"] == "PARENT" and o["state"] == "QUANTIFIED" and o["value_form"] == "PERCENT_OF_DOSE" and o.get("dose"):
            ub.setdefault((tuple(o["interval"] or ()), o["amount_basis"]), {}).setdefault(o["dose"], o)
    out["urine_by_dose"] = [{"interval": list(k[0]), "values": {d: v["value"] for d, v in vs.items()}} for k, vs in ub.items() if len(vs) >= 2]
    tested = [u for u in out["upstream"] if _has_dose_test(u)]
    out["reported_doses"] = sorted({p["dose"] for p in out["reported_by_dose"]})
    out["multi_dose_study_context"] = any(
        p["study"] == board["study"] and p["species"] == board["species"]
        and (p.get("dose_context") or {}).get("kind") in ("range", "levels") for p in reported)
    if not out["upstream"]:
        if out["reported_auc"] or out["reported_by_dose"] or out["urine_by_dose"]:
            out["not_assessable_reason"] = "multi-dose summaries are available; no matched upstream profile test"
        elif out["multi_dose_study_context"]:
            out["not_assessable_reason"] = "multiple doses were studied, but the reported parameters have no dose-specific estimates"
        elif len(doses) < 2:
            out["caveats"].append("SINGLE_DOSE_ONLY")
            out["not_assessable_reason"] = "the retained systemic profiles cover one dose in this comparison"
        else:
            out["not_assessable_reason"] = "no matched upstream dose comparison for these profiles (absorption item 19, DIS-2)"
    elif not tested:
        out["caveats"].append("NO_UNCERTAINTY")
    if any(u["route"] == "EV" for u in out["upstream"]):
        out["caveats"].append("EV_INPUT_CONFOUNDED")
        peak_change = any((u.get("exposure") or {}).get("peak_reading") == "POINTS_TO_NONLINEARITY" for u in out["upstream"])
        out["next_discriminator"] = ("check whether the absorption time course explains the peak change, using earlier samples and matched IV doses"
                                     if peak_change else "check exposure outside the common window and compare matched IV dose profiles")
    elif out["upstream"]:
        out["alternatives"] = list(dict.fromkeys(candidate for u in out["upstream"] if "CONFOUNDED" not in u["caveats"]
                                                 for candidate in u.get("upstream_candidates", [])))
        out["next_discriminator"] = "compare total and unbound exposure on matched windows across the observed doses"
    elif out["reported_auc"] or out["reported_by_dose"] or out["multi_dose_study_context"]:
        out["next_discriminator"] = "obtain comparable concentration profiles and uncertainty at the reported doses"
    else:
        out["next_discriminator"] = "a second matched dose with the same timing, matrix and concentration basis"
    if any(s["level"] == "GROUP_MEAN" for s in plasma):
        out["caveats"].append("GROUP_MEAN")
    out["caveats"] = list(dict.fromkeys(out["caveats"]))
    out["clearance_contrasts"] = _reported_iv_clearance_contrasts(board, reported, clearance_contrasts, "DOSE")
    return out


def _reported_accumulation(rep):
    """Matched within-regimen ratios of source summaries; no dose normalization or inference test."""
    out = {"rows": [], "index": None, "reading": None, "dose_resolved": None, "interval_h": None, "condition": None, "notes": []}
    def norm(value):
        return " ".join(str(value or "").casefold().split())
    unknown = {"", "not_found", "not found", "unknown", "not reported", "not_reported"}
    groups = {}
    for p in rep:
        value = p.get("value")
        if (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0
                or p["param"] not in ("CMAX", "AUC", "THALF") or p.get("unit_conflict") or p.get("as_printed_only")
                or not re.fullmatch(r"DAY_[1-9]\d*", p.get("occasion", ""))):
            continue
        dose = p.get("dose")
        dose_known = isinstance(dose, (int, float)) and not isinstance(dose, bool) and math.isfinite(dose) and dose > 0 and not p.get("dose_conflict")
        comparison = p.get("repeat_comparison_id")
        if not dose_known and not (comparison and p.get("same_dose_across_occasions") is True):
            continue
        analyte = norm(p.get("reported_analyte") or p.get("analyte"))
        matrix, route = norm(p.get("matrix")), p.get("route")
        if (analyte in unknown or not (norm(p.get("reported_analyte_role")) == "parent" or re.search(r"\bparent\b|\bunchanged\b", analyte))
                or re.search(r"radioact|14\s*c|active material|bioassay|metabolite|mixture|mixed", analyte)
                or matrix not in ("plasma", "serum", "blood") or route not in ("IV", "EV")
                or norm(p.get("unit")) in unknown):
            continue
        regimen = re.sub(r"\bday\s*\d+\s*of\s*(\d+)\b", r"day N of \1", norm(p.get("regimen")))
        # An explicit source comparison identifier can establish one regimen when an absolute dose conflict is quarantined.
        identity = comparison or regimen
        if not identity:
            continue
        design = (p.get("study"), p.get("species"), identity, dose if dose_known else "SOURCE_SAME_DOSE_ABSOLUTE_UNRESOLVED",
                  route, p.get("route_detail"), matrix, analyte, p.get("condition"), p.get("cohort_id"),
                  p.get("analysis_unit"), p.get("dosing_interval_h"))
        label = norm(p.get("label"))
        parameter = (p["param"], label, norm(p["unit"]), p.get("half_life_phase"), str(p.get("exposure_window_h")))
        groups.setdefault((design, parameter), []).append(p)
    candidates = []
    for (design, parameter), ps in groups.items():
        by = {}
        for p in ps:
            by.setdefault(int(p["occasion"][4:]), []).append(p)
        if len(by) < 2 or min(by) != 1 or any(len(values) != 1 for values in by.values()):
            continue
        first, last = by[1][0], by[max(by)][0]
        candidates.append((design, first, last, max(by)))
    designs = {c[0] for c in candidates}
    if len(designs) > 1:
        out["notes"].append("More than one eligible regimen or arm: values remain listed by source; no pooled occasion ratio is formed.")
        return out
    for _, first, last, day in sorted(candidates, key=lambda c: ("CMAX", "AUC", "THALF").index(c[1]["param"])):
        out["rows"].append({"param": first["param"], "label": str(first["label"]), "unit": first["unit"], "route": first["route"],
                            "matrix": first["matrix"], "condition": first.get("condition"), "half_life_phase": first.get("half_life_phase"),
                            "first_day": 1, "last_day": day, "first": first["value"], "last": last["value"], "ratio": last["value"] / first["value"],
                            "datasets": [first["dataset_id"], last["dataset_id"]], "records": [first["record_id"], last["record_id"]], "n_note": first.get("n_note")})
        out["dose_resolved"] = first.get("dose") is not None and not first.get("dose_conflict")
        out["interval_h"], out["condition"] = first.get("dosing_interval_h"), first.get("condition")
        for note in (first.get("table_notes"), last.get("table_notes"), first.get("dose_conflict"), last.get("dose_conflict")):
            if note and note not in out["notes"]:
                out["notes"].append(note)
    if len({(r["first_day"], r["last_day"]) for r in out["rows"]}) > 1:
        out["rows"] = []
        out["notes"].append("Parameters refer to different dosing-day contrasts; no combined occasion comparison is formed.")
        return out
    factors = {"h": 1, "hr": 1, "hour": 1, "hours": 1, "min": 1 / 60, "minutes": 1 / 60, "d": 24, "day": 24, "days": 24}
    th = next((r for r in out["rows"] if r["param"] == "THALF" and r.get("half_life_phase") in ("terminal", "elimination")
               and norm(r["unit"]) in factors), None)
    expo = [r for r in out["rows"] if r["param"] in ("CMAX", "AUC")]
    tau = out["interval_h"]
    if th and expo and isinstance(tau, (int, float)) and not isinstance(tau, bool) and math.isfinite(tau) and tau > 0:
        half_lives = [th[k] * factors[norm(th["unit"])] for k in ("first", "last")]
        # expm1 remains stable for very long half-lives relative to the dosing interval.
        idx = sorted(-1 / math.expm1(-math.log(2) * tau / t) for t in half_lives)
        if all(math.isfinite(v) for v in idx):
            out["index"] = {"formula": "1 / (1 - 2^(-tau / t1/2))", "tau_h": tau, "thalf_h": half_lives, "range": idx,
                            "assumption": "steady-state reference for instantaneous input with one exponential decline, linear time-invariant kinetics; not an EV Cmax or AUC-window prediction"}
            out["reading"] = "REFERENCE_ONLY"
    return out


def item31(board, plasma, dist_data, abs_data, reported, urine_obs, regimens=(), clearance_contrasts=()):
    out = {"item_id": 31, "occasions": [], "upstream": [], "reported_by_occasion": [], "urine_by_occasion": [], "caveats": [],
           "direction": None, "alternatives": [], "not_assessable_reason": None, "applies": False}
    sids = {s["sid"] for s in plasma}
    for x in (dist_data or {}).get("repeat_dosing", []):
        if x.get("first_sid") in sids:
            out["upstream"].append({"source": f"distribution T9 ({dist_data.get('version')})", "first": x["first_sid"], "later": x["later_sid"],
                                    "t9": x.get("t9_label"), "flags": x.get("t9_flags"), "rows": x.get("rows")})
    ds_ids = {s["dataset_id"] for s in plasma}
    for c in (abs_data or {}).get("conditions", []):
        if {c.get("a"), c.get("b")} & ds_ids and "occasion" in " ".join(c.get("differing_attributes") or []):
            out["upstream"].append({"source": f"absorption item 23 ({abs_data.get('version')})", "first": c.get("b"), "later": c.get("a"),
                                    "t9": c.get("t5_label"), "flags": c.get("t5_flags") or [], "panel": _upfile("absorption", c.get("E1")), "panel2": _upfile("absorption", c.get("E2"))})
    local = [p for p in reported if p["study"] == board["study"] and p["species"] == board["species"]]
    regimens_by_ds = {r["dataset_id"]: r for r in regimens}
    regimens_by_ds.update({p["dataset_id"]: p["repeat_regimen"] for p in local if p.get("repeat_regimen")})
    out["repeat_regimens"] = [regimens_by_ds[k] for k in sorted(regimens_by_ds)]
    unspecified = {None, "", "UNSPECIFIED", "NOT_FOUND", "NOT_REPORTED"}
    rep_ids = {p["dataset_id"] for p in local if p["occasion"] not in unspecified | {"FIRST_DOSE"}}
    rep_first = [p for p in local if p["dataset_id"] in rep_ids and p["occasion"] not in unspecified]
    out["reported_by_occasion"] = rep_first
    out["reported_accumulation"] = _reported_accumulation(rep_first)
    occ = {}
    for o in urine_obs:
        if o["occasion"] not in unspecified | {"FIRST_DOSE"} and o["state"] == "QUANTIFIED":
            occ.setdefault((o["dataset_id"], o["component"] or o["analyte"]), []).append(o)
    out["urine_by_occasion"] = [{"dataset_id": k[0], "component": k[1], "values": [(o["occasion"], o["value"], o["unit"]) for o in sorted(v, key=lambda o: int(re.sub(r"\D", "", o["occasion"]) or 0))]}
                                for k, v in occ.items() if len({o["occasion"] for o in v}) >= 2]
    out["occasions"] = sorted({o["occasion"] for o in urine_obs if o["occasion"] not in unspecified | {"FIRST_DOSE"}} | {p["occasion"] for p in rep_first} |
                              {s["occasion"] for s in plasma if s["occasion"] not in unspecified | {"FIRST_DOSE"}},
                              key=lambda o: (int(re.sub(r"\D", "", o) or 0), o))
    out["applies"] = bool(out["repeat_regimens"] or out["occasions"] or out["upstream"])
    if len(out["occasions"]) == 2:
        out["caveats"].append("TWO_OCCASIONS_ONLY")
    if out["urine_by_occasion"]:
        out["caveats"].append("CARRYOVER_POSSIBLE")
    if not out["upstream"] and out["applies"]:
        out["not_assessable_reason"] = "no upstream plasma occasion contrast (absorption item 23, T9) for these data; reported values and urine are listed"
    if out["urine_by_occasion"] and not out["upstream"]:
        out["alternatives"] = ["carryover from earlier doses", "differences in urinary recovery or collection"]
    elif out["upstream"] or out["reported_by_occasion"]:
        out["alternatives"] = ["ordinary accumulation", "a change in disposition"]
        if any(s["route_class"] == "EV" for s in plasma):
            out["alternatives"].append("a change in absorption or F")
    out["caveats"] = list(dict.fromkeys(out["caveats"]))
    out["clearance_contrasts"] = _reported_iv_clearance_contrasts(board, reported, clearance_contrasts, "OCCASION")
    out["applies"] = out["applies"] or bool(out["clearance_contrasts"])
    return out


# ---------------------------------------------------------------- item 32 (reserved): inventory only

def item32(plasma_all, scope_rows):
    rows = [{"dataset_id": s["dataset_id"], "series": s["label"], "study": s["study"], "species": s["species"], "analyte": s["analyte"],
             "matrix": s["matrix_class"], "unit": s["unit"], "caveats": ["SCOPE_REVIEW"] + (["TR_NOT_PARENT"] if s["analyte"] == "TOTAL_RADIOACTIVITY" else [])}
            for s in plasma_all if s["analyte"] in ("TOTAL_RADIOACTIVITY", "METABOLITE") and s["matrix_class"] in dist.REF_CLASSES]
    rows += [{"dataset_id": x["dataset_id"], "series": f"{x['analyte']} · {x['label']}", "study": x["study"], "species": x["species"], "analyte": x["analyte"],
              "matrix": "plasma (reported parameter)", "unit": "as printed", "caveats": ["SCOPE_REVIEW"], "raw": x["raw"], "reason": x["reason"]} for x in scope_rows]
    return rows


# ---------------------------------------------------------------- item 33: urine

def _trace(o):
    return {"PARENT": "unchanged parent", "ACTIVE_MATERIAL": "active material (microbiological assay)",
            "TOTAL_RADIOACTIVITY": "total radioactivity"}.get(o["analyte"])


def _lower_mean(v, sd, n, kind):
    """One-sided 95 % lower limit of a group mean when the dispersion type and n are identified (E0.4)."""
    if v is None or sd is None or not n or n < 2 or kind not in ("SD", "SE"):
        return None
    se = sd / math.sqrt(n) if kind == "SD" else sd
    return v - ab.t_ppf(0.95, n - 1) * se


def urine_series(obs, cards_by_ds, cfg):
    """Group urine observations into one cumulative series per dataset, group, trace and occasion (EM-5a)."""
    groups = {}
    for o in obs:
        if o["excretum"] != "URINE" or _trace(o) is None or o["value_form"] != "PERCENT_OF_DOSE" or o.get("component") and o["analyte"] not in ("PARENT", "ACTIVE_MATERIAL", "TOTAL_RADIOACTIVITY"):
            continue
        groups.setdefault((o["dataset_id"], o["species"], o["group"], o["analyte"], o["occasion"],
                           o["denominator"], o.get("cohort_id"), o.get("animal")), []).append(o)
    out = []
    share_cut = _num(cfg.get("late_increment_share"))
    for (dsid, sp, grp, analyte, occ, denom, cohort, animal), os_ in groups.items():
        card = cards_by_ds[dsid]
        inc = sorted([o for o in os_ if o["amount_basis"] == "INTERVAL" and o["interval"]], key=lambda o: (o["interval"][0], o["interval"][1]))
        tot = sorted([o for o in os_ if o["amount_basis"] in ("CUMULATIVE", "TOTAL") and o["state"] == "QUANTIFIED"],
                     key=lambda o: (o["interval"] is None, tuple(o["interval"] or ()), str(o["record_id"]), str(o.get("obs_id", ""))))
        s = {"key": _slug(f"{dsid}-{sp}-{grp}-{analyte}-{occ}"), "dataset_id": dsid, "study": card["study"], "species": sp, "group": grp,
             "analyte": analyte, "trace": _trace(os_[0]), "occasion": occ, "assay": card["assay"], "assay_note": card["assay_note"],
             "route": card["route_class"], "dose": card["dose"], "denominator": os_[0]["denominator"], "level": os_[0]["level"],
             "animal": animal, "cohort_id": cohort,
             "dispersion": card["dispersion"], "n": next((o["n"] for o in os_ if o.get("n")), None), "collection": card["collection"],
             "intervals": [{"interval": o["interval"], "value": o["value"], "sd": o["sd"], "state": o["state"], "raw": o["raw"], "note": o["note"], "censoring": o.get("censoring"),
                            "record_id": o["record_id"], "source_ref": o.get("obs_id") or o["record_id"]} for o in inc],
             "printed_totals": [{"interval": o["interval"], "value": o["value"], "sd": o["sd"], "raw": o["raw"], "record_id": o["record_id"],
                                 "source_ref": o.get("obs_id") or o["record_id"]} for o in tot],
             "flags": sorted({f for o in os_ for f in o["flags"]}), "gaps": [], "cumulative": [], "notes": []}
        if sum(k[:5] == (dsid, sp, grp, analyte, occ) for k in groups) > 1:
            s["key"] += "-" + hashlib.sha256(repr((denom, cohort, animal)).encode()).hexdigest()[:10]
        s.update({k: card.get(k) for k in ("drug", "dose_basis", "regimen", "condition", "route_detail", "matching_identity", "source_item")})
        s["dose_denominator_verified"] = all(o.get("dose_denominator_verified",
            o["value_form"] == "PERCENT_OF_DOSE" and o["denominator"] == "administered dose") for o in os_)
        # cumulative from contiguous quantified increments starting at the first collected interval
        run, end, contiguous_from_zero = 0.0, None, None
        prev_dur = None
        for i in inc:
            if i["state"] != "QUANTIFIED":
                s["gaps"].append({"interval": i["interval"], "why": i["note"] or "missing, not zero"})
                continue
            a, b = i["interval"]
            if end is None and a > 0:
                anchors = [t for t in tot if t["interval"] == [0, a]]
                if anchors and len({t["value"] for t in anchors}) == 1:
                    # A directly reported cumulative prefix is an observed amount,
                    # so it may anchor later disjoint increments without inventing bins.
                    run, end, contiguous_from_zero = anchors[0]["value"], a, True
                    s["cumulative"].append({"t": a, "value": run, "basis": "printed total", "dur": None})
            if end is not None and a > end + 1e-9:
                s["gaps"].append({"interval": [end, a], "why": "not collected"})
            if end is not None and a < end - 1e-9:
                s["notes"].append(f"interval {_f(a)}–{_f(b)} h overlaps the previous one; not summed")
                continue
            if end is None:
                contiguous_from_zero = a == 0
            run += i["value"]
            end = b
            s["cumulative"].append({"t": b, "value": run,
                                    "basis": "printed cumulative plus increments" if s["cumulative"] and s["cumulative"][0]["basis"] == "printed total" else "sum of increments",
                                    "dur": b - a})
        if s["gaps"] and any(g["interval"][0] < (end or 0) - 1e-9 and g["interval"][1] <= (end or 0) + 1e-9 for g in s["gaps"]):
            s["flags"].append("COLLECTION_GAP")
        # Reconcile every printed window only with an exact contiguous partition.
        # A shared endpoint alone does not establish a matching collection window.
        s["reconciliations"] = []
        for t in tot:
            iv = t["interval"]
            bins = [o for o in inc if iv and iv[0] <= o["interval"][0] and o["interval"][1] <= iv[1]]
            full_partition = (bins and all(o["state"] == "QUANTIFIED" for o in bins)
                    and bins[0]["interval"][0] == iv[0] and bins[-1]["interval"][1] == iv[1]
                    and all(a["interval"][1] == b["interval"][0] for a, b in zip(bins, bins[1:])))
            anchored = next((c for c in s["cumulative"] if iv and iv[0] == 0 and c["t"] == iv[1]
                             and c["basis"] == "printed cumulative plus increments" and "COLLECTION_GAP" not in s["flags"]), None)
            if full_partition or anchored:
                summed = sum(o["value"] for o in bins) if full_partition else anchored["value"]
                diff = t["value"] - summed
                rec = {"interval": list(iv), "printed": t["value"], "sum_of_increments": summed, "difference": diff,
                       "calculation_basis": "contiguous increments" if full_partition else "printed cumulative prefix plus contiguous increments",
                       "source_ref": t.get("obs_id") or t["record_id"],
                       "status": "reconciled within rounding" if abs(diff) <= 0.1 + 1e-9 else "does not reconcile; both kept as printed"}
                s["reconciliations"].append(rec)
                s["reconcile"] = rec
                if abs(diff) > 0.1 + 1e-9:
                    s["flags"].append("SOURCE_CONFLICT")
            # Do not replace increment-derived points; retain their discrepancy above.
            if not any(c["t"] == (iv[1] if iv else None) for c in s["cumulative"]):
                s["cumulative"].append({"t": iv[1] if iv else None, "value": t["value"], "basis": "printed total", "dur": None})
        printed_by_window = {}
        for t in tot:
            printed_by_window.setdefault(tuple(t["interval"] or ()), []).append(t)
        for iv, rows in printed_by_window.items():
            if len({o["value"] for o in rows}) > 1:
                s["flags"].append("SOURCE_CONFLICT")
                s["notes"].append(f"conflicting printed totals for {list(iv)} h; all source cells retained")
        known_totals = [t for t in tot if t["interval"]]
        for earlier, later in zip(known_totals, known_totals[1:]):
            if earlier["interval"][0] == later["interval"][0] and earlier["interval"][1] < later["interval"][1] and later["value"] < earlier["value"]:
                s["flags"].append("SOURCE_CONFLICT")
                s["notes"].append("reported cumulative recovery decreases; measurements kept without correction")
        s["cumulative"].sort(key=lambda c: (c["t"] is not None, c["t"] or 0))
        if s["cumulative"]:
            last = s["cumulative"][-1]
            matching = [t for t in tot if (t["interval"][1] if t["interval"] else None) == last["t"]]
            values = {t["value"] for t in matching}
            windows = {tuple(t["interval"] or ()) for t in matching}
            ambiguous = len(values) > 1 or len(windows) > 1
            matching_total = matching[0] if matching and not ambiguous else None
            s["r_u"] = None if ambiguous else (matching_total["value"] if matching_total else last["value"])
            s["collection_end_h"] = last["t"]
            if matching_total:
                iv = matching_total["interval"]
                s["window_label"] = f"{_f(iv[0])}–{_f(iv[1])} h" if iv else "collection window not stated"
            else:
                s["window_label"] = (f"0–{_f(last['t'])} h" if contiguous_from_zero and "COLLECTION_GAP" not in s["flags"] else "sum over collected intervals")
            sd = matching_total["sd"] if matching_total else None
            if matching_total:
                s["dispersion"] = matching_total.get("dispersion", card["dispersion"])
            lo = _lower_mean(s["r_u"], sd, s["n"], s["dispersion"]) if s["r_u"] is not None and "SOURCE_CONFLICT" not in s["flags"] else None
            s["recovery_lower"] = lo
            s["recovery_lower_kind"] = "STATISTICAL_BOUND (one-sided 95 %, lower limit of the mean collected recovery on its reported basis)" if lo is not None else None
            s["fe_lower"] = lo if s["analyte"] == "PARENT" and s["route"] == "IV" and s["occasion"] in ("FIRST_DOSE", "DAY_1") else None
            s["fe_lower_kind"] = s["recovery_lower_kind"] if s["fe_lower"] is not None else None
            s["fe_lower_reason"] = None if lo is not None else (
                "dispersion type not identified (SD or SE): no lower limit is formed" if s["dispersion"] == "UNKNOWN" else "n or dispersion not reported")
            # late increment (step 8)
            q = [i for i in inc if i["state"] == "QUANTIFIED"]
            if (share_cut is not None and len(s["cumulative"]) >= 2 and not {"COLLECTION_GAP", "SOURCE_CONFLICT"}.intersection(s["flags"])
                    and last["value"] > 0):
                d_last, d_prev = s["cumulative"][-1]["dur"], s["cumulative"][-2]["dur"]
                inc_last = s["cumulative"][-1]["value"] - s["cumulative"][-2]["value"]
                if d_last is not None and d_prev is not None and d_last >= d_prev - 1e-9:
                    share = inc_last / last["value"]
                    s["late_increment"] = {"amount_pct_dose": inc_last, "duration_h": d_last, "share": share, "setting": share_cut,
                                           "small": share < share_cut}
                    if share < share_cut:
                        s["flags"].append("LATE_INCREMENT_SMALL")
            if s["route"] == "EV":
                s["flags"].append("ADMIN_DOSE_FRACTION")
            if s["level"] in ("GROUP_MEAN", "MIXED"):
                s["flags"].append("GROUP_MEAN")
            wording = None
            if s["analyte"] == "PARENT" and lo is not None and lo >= 50:
                wording = "a majority" if lo > 50 else "at least half"
            s["wording"] = wording
        s["flags"] = list(dict.fromkeys(s["flags"]))
        if s["cumulative"] or s["intervals"]:
            out.append(s)
    return out


def _plasma_auc_over(s, u, v):
    """Observed plasma area inside [u, v]: (AUC, J=[first, last], full_cover)."""
    q = [p for p in _pts(s) if u - 1e-9 <= p["t"] <= v + 1e-9]
    if len(q) < 2:
        return None, None, False
    t = [p["t"] for p in q]
    if len(set(t)) != len(t) or any(p.get("t") is not None and t[0] <= p["t"] <= t[-1] and p["status"] != "QUANTIFIED" for p in s["points"]):
        return None, None, False
    c = [p["c"] * s["uf"] for p in q]
    full = abs(t[0] - u) < 1e-6 and abs(t[-1] - v) < 1e-6
    return ab.auc(t, c), [t[0], t[-1]], full


def t10(clr, fu, gfr):
    """E0.10 T10 with measured CLR limits and filtration limits; CANNOT_ASSESS when either side is missing."""
    g_lo, g_hi = (_num((gfr or {}).get(k)) for k in ("low", "high"))
    if g_lo is None or g_hi is None or not 0 < g_lo <= g_hi:
        return {"status": "CANNOT_ASSESS", "direction": None, "reason": "no sourced GFR for this species (rules C.7a); EM-5c shows CLR only"}
    f_lo, f_hi = (_num((fu or {}).get(k)) for k in ("low", "high"))
    if f_lo is None or f_hi is None or not 0 < f_lo <= f_hi <= 1:
        return {"status": "CANNOT_ASSESS", "direction": None, "reason": "no supported fu,p for the total-plasma comparison"}
    fl, fh = f_lo * g_lo, f_hi * g_hi
    lo, hi = clr.get("limits") or (None, None)
    out = {"filtration_range_l_h_kg": [fl, fh], "matched": gfr.get("matched_to_study") is True,
           "gfr_source": gfr.get("source"), "fu_source": fu.get("source")}
    if not out["matched"]:
        return out | {"status": "CANNOT_ASSESS", "direction": None,
                      "reason": "The GFR is not matched to study physiology. The filtration range is sensitivity context only (FILTRATION_REFERENCE_UNMATCHED)."}
    if (lo is not None and (not math.isfinite(lo) or lo < 0)) or (hi is not None and (not math.isfinite(hi) or hi < 0)) or (lo is not None and hi is not None and lo > hi):
        return out | {"status": "CANNOT_ASSESS", "direction": None, "reason": "invalid renal clearance limits"}
    if lo is None and hi is None:
        return out | {"status": "CANNOT_ASSESS", "direction": None, "reason": "no supported CLR limit (point estimate or proxy only); conditional comparison kept"}
    if lo is not None and lo > fh:
        res = {"status": "EXCLUDED_UNDER_STATED_ASSUMPTIONS", "direction": "above", "reason": "CLR_L > F_U: net appearance beyond filtration, compatible with secretion"}
    elif hi is not None and hi < fl:
        res = {"status": "EXCLUDED_UNDER_STATED_ASSUMPTIONS", "direction": "below", "reason": "CLR_U < F_L: less parent in urine than filtration predicts"}
    elif lo is not None and hi is not None:
        res = {"status": "NOT_EXCLUDED", "direction": "two-sided", "reason": "ranges overlap; filtration alone is compatible"}
    else:
        res = {"status": "CANNOT_ASSESS", "direction": "one-sided limit on the wrong side", "reason": "the available limit cannot test this direction"}
    return out | res


def _same_renal_design(urine, plasma):
    def norm(value):
        text = " ".join(str(value or "").lower().replace("_", " ").split())
        return "" if text in ("not reported", "unknown", "not found", "unspecified") else text
    keys = ("drug", "dose_basis", "condition", "route_detail")
    if not all(norm(urine.get(k)) == norm(plasma.get(k)) for k in keys):
        return False
    if not norm(plasma.get("drug")) or not norm(plasma.get("dose_basis")):
        return False
    if norm(urine.get("regimen")) != norm((plasma.get("regimen") or {}).get("source_text")):
        return False
    urine_ids = dict(urine.get("matching_identity") or {})
    plasma_ids = plasma.get("matching_identity") or {}
    for aliases in (("cohort", "cohort_id"), ("arm", "arm_id", "experiment_arm", "experiment_arm_id")):
        left = {norm(urine_ids.get(k)) for k in aliases} - {""}
        if "cohort" in aliases and norm(urine.get("cohort_id") or urine["collection"].get("cohort_id")):
            left.add(norm(urine.get("cohort_id") or urine["collection"].get("cohort_id")))
        right = {norm(plasma_ids.get(k)) for k in aliases} - {""}
        if left != right:
            return False
    return (plasma.get("matrix_class") == "PLASMA" and norm(plasma.get("concentration_basis")) in ("total", "total plasma")
            and bool(urine.get("source_item") and (plasma.get("source_item_id") or plasma.get("source_refs"))))


def item33_clr(us, plasma, cards_by_ds, cfg, fu_rec):
    """Interval CLR or partial-window proxy for each urine interval of unchanged parent (EM-5c)."""
    rows = []
    if us["analyte"] != "PARENT" or not us["dose"] or us["occasion"] not in ("FIRST_DOSE", "DAY_1"):
        return rows
    cand = [s for s in plasma if s["study"] == us["study"] and s["species"] == us["species"] and s["route_class"] == us["route"] and s["dose"] == us["dose"]
            and s["occasion"] == "FIRST_DOSE" and s["matrix_class"] in ("PLASMA", "SERUM") and s["analyte"] == "PARENT" and not s["unbound"] and s.get("uf")]
    references = cfg.get("gfr") or {}
    study_key = f"{us['study']}|{us['species']}"
    gfr = references.get(study_key) or references.get(us["species"]) or {}
    filtration = None
    if gfr.get("source"):
        low = _num(gfr.get("low") if gfr.get("low") is not None else gfr.get("gfr_ml_min_kg"))
        high = _num(gfr.get("high") if gfr.get("high") is not None else gfr.get("gfr_ml_min_kg"))
        if low is not None and high is not None:
            filtration = {"low": low * 0.06, "high": high * 0.06, "source": gfr["source"],
                          "matched_to_study": (gfr.get("matched_to_study") is True and
                                               (study_key in references or gfr.get("study") == us["study"]))}
    fu = fu_rec if fu_rec and fu_rec.get("source") and fu_rec.get("constant_over_exposure") is True else None
    pairing = us["collection"]["pairing"]
    for i in us["intervals"]:
        if i["state"] != "QUANTIFIED" or i["interval"][1] <= i["interval"][0]:
            continue
        u, v = i["interval"]
        for s in cand:
            auc, J, full = _plasma_auc_over(s, u, v)
            ae = i["value"] / 100 * us["dose"]
            row = {"urine_key": us["key"], "sid": s["sid"], "plasma_label": s["label"], "urine_interval": [u, v], "plasma_window": J,
                   "ae_mg_per_kg": ae, "auc_mg_h_l": auc, "pairing": pairing, "caveats": [], "plasma_level": s["level"], "urine_level": us["level"],
                   "urine_source_ref": i.get("source_ref") or i.get("record_id"), "route": us["route"], "dose_mg_per_kg": us["dose"],
                   "plasma_source_refs": [p["record_id"] for p in s["points"] if p.get("record_id") and p.get("t") is not None and u <= p["t"] <= v],
                   "limits": None, "bound_direction": "none"}
            reasons = []
            if dist._baseline(s)[0]:
                reasons.append("the plasma baseline is unresolved")
            if auc is None or auc <= 0:
                reasons.append("a contiguous positive plasma area is unavailable inside the urine interval")
            if us["assay"] != "SPECIFIC" or _assay_plasma(s) != "SPECIFIC":
                reasons.append("analyte-specific assays for urine and plasma are not documented")
            if pairing not in ("SAME_ANIMAL", "PARALLEL_COHORT_SAME_STUDY"):
                reasons.append("a matched subject or parallel study cohort is not established")
            if pairing == "SAME_ANIMAL" and (us["level"] == "INDIVIDUAL" or s["level"] == "INDIVIDUAL"):
                identity = s.get("matching_identity") or {}
                plasma_ids = {str(v).strip() for v in (s.get("animal"), identity.get("animal_id"), identity.get("individual_id"),
                                                       identity.get("subject_id")) if v is not None and str(v).strip()}
                if us["level"] != s["level"] or plasma_ids != {str(us.get("animal") or us["group"]).strip()}:
                    reasons.append("the individual animal identifiers do not match")
            if str(us["collection"].get("collection_complete", "")).upper() != "YES":
                reasons.append("complete urine collection is not documented")
            if str(us["collection"].get("bladder_emptying") or "").strip().lower() in ("", "no", "not reported", "not_reported", "unknown"):
                reasons.append("bladder emptying at the interval boundaries is not documented")
            if "SOURCE_CONFLICT" in us["flags"] or s.get("source_conflicts"):
                reasons.append("a source conflict affects this comparison")
            if reasons:
                why = "; ".join(reasons)
                row.update(kind="CLR_NO_DIRECTION", clr=None, text=f"Urine and plasma are reported separately: {why}.",
                           t10={"status": "CANNOT_ASSESS", "direction": None, "reason": why})
                rows.append(row)
                continue
            clr = ae / auc
            row["clr"] = clr
            row["clr_ml_min_kg"] = clr * ML_MIN_KG_PER_L_H_KG
            if full:
                row["kind"] = "INTERVAL_ESTIMATE"
                row["rate_mg_kg_h"] = ae / (v - u)
                row["avg_plasma_mg_l"] = auc / (v - u)
                row["text"] = f"ΔAe/ÂUC over {_f(u)}–{_f(v)} h = {_f(clr)} L/h/kg ({_f(row['clr_ml_min_kg'])} mL/min/kg); interval estimate."
            else:
                row["kind"] = "WINDOW_PROXY"
                row["caveats"].append("WINDOW_PROXY")
                cover = (J[1] - J[0]) / (v - u)
                row["plasma_coverage"] = cover
                row["text"] = (f"ΔAe({_f(u)}–{_f(v)} h)/ÂUC({_f(J[0])}–{_f(J[1])} h) = {_f(clr)} L/h/kg ({_f(row['clr_ml_min_kg'])} mL/min/kg); "
                               f"partial-window proxy, plasma covers {_f(100 * cover, 2)} % of the urine interval. Omitting plasma area pushes the "
                               "ratio up if the sampled area is accurate; the net direction is unknown without bounds on integration and assay error.")
            if s["level"] == "GROUP_MEAN" or us["level"] in ("GROUP_MEAN", "MIXED") or pairing != "SAME_ANIMAL":
                row["caveats"].append("RATIO_OF_MEANS")
            if s["level"] == us["level"] == "INDIVIDUAL" and pairing == "SAME_ANIMAL":
                row.update(animal_id=next(iter(plasma_ids)), urine_dataset=us.get("dataset_id"),
                           plasma_dataset=s.get("dataset_id"), denominator=us.get("denominator"),
                           animal_pair_verified=bool(us.get("animal") and us.get("dose_denominator_verified") and _same_renal_design(us, s)))
            row["t10"] = t10(row, fu, filtration)
            rows.append(row)
    return rows


def renal_filtration_comparison(board, plan):
    """One prespecified interval per animal, renal clearance divided by that animal's fu × GFR."""
    out = {"status": "CANNOT_ASSESS", "method": "two-sided exact sign test for the median animal ratio",
           "null_median": 1.0, "experimental_unit": "independent animal", "p": None}
    if plan is None:
        if not board["urine"]:
            reason = "No interval urine data for this study."
        elif not any(u["analyte"] == "PARENT" for u in board["urine"]):
            reason = "Urinary measurements do not identify unchanged parent."
        elif not any(c.get("animal_id") and c["kind"] == "INTERVAL_ESTIMATE" for c in board["clr"]):
            reason = "No animal has a verified same-window parent urine and plasma clearance with paired physiology."
        else:
            reason = "Select a collection interval and supply animal-matched filtration and binding measurements."
        return out | {"reason": reason}
    if not isinstance(plan, dict) or not all(plan.get(key) is True for key in
            ("prespecified", "independent_animals", "physiology_matched", "fu_constant_over_interval")) or not plan.get("design_source"):
        return out | {"reason": "The prespecified interval, independent animals, matching physiology and binding over the interval need a sourced design."}
    def number(x):
        return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)
    window = plan.get("interval_h")
    animals = plan.get("animals")
    if not (isinstance(window, list) and len(window) == 2 and all(number(x) for x in window) and 0 <= window[0] < window[1]
            and isinstance(animals, list) and len(animals) >= 2 and plan.get("urine_dataset") and plan.get("plasma_dataset")):
        return out | {"reason": "Specify one urine dataset, one plasma dataset, an interval and the enrolled animal roster."}
    out.update(interval_h=window, design_source=plan["design_source"],
               urine_dataset=plan["urine_dataset"], plasma_dataset=plan["plasma_dataset"], animals=[])
    ids = set()
    for ref in animals:
        if not isinstance(ref, dict):
            return out | {"reason": "Invalid animal reference."}
        animal_id = str(ref.get("animal_id", "")).strip() if ref.get("animal_id") is not None else ""
        if not animal_id or animal_id in ids:
            return out | {"reason": "Each enrolled animal must have one unique identifier."}
        ids.add(animal_id)
        gfr, fu = ref.get("gfr_ml_min_kg"), ref.get("fu_p")
        if not (number(gfr) and gfr > 0 and number(fu) and 0 < fu <= 1 and ref.get("gfr_source") and ref.get("fu_source")):
            return out | {"reason": f"Missing or invalid animal-specific GFR, fu or sources for {animal_id}."}
        rows = [c for c in board["clr"] if c.get("animal_id") == animal_id and c.get("urine_dataset") == plan["urine_dataset"]
                and c.get("plasma_dataset") == plan["plasma_dataset"] and c["urine_interval"] == window and c.get("animal_pair_verified")
                and c["kind"] == "INTERVAL_ESTIMATE" and c.get("pairing") == "SAME_ANIMAL"
                and c.get("denominator") == "administered dose" and c.get("urine_source_ref") and c.get("plasma_source_refs")]
        if len(rows) != 1:
            return out | {"reason": f"Need exactly one verified full-interval parent clearance and its source records for {animal_id}."}
        row = rows[0]
        filtration = fu * gfr
        if not number(row["clr_ml_min_kg"]) or row["clr_ml_min_kg"] < 0 or filtration <= 0:
            return out | {"reason": f"Unusable clearance or filtration measurement for {animal_id}."}
        ratio = row["clr_ml_min_kg"] / filtration
        if not math.isfinite(ratio):
            return out | {"reason": f"Unusable clearance/filtration ratio for {animal_id}."}
        out["animals"].append({"animal_id": animal_id, "clr_ml_min_kg": row["clr_ml_min_kg"], "fu_p": fu,
                               "gfr_ml_min_kg": gfr, "ratio": ratio, "gfr_source": ref["gfr_source"],
                               "fu_source": ref["fu_source"], "plasma_series": row["sid"],
                               "urine_ref": row["urine_source_ref"], "plasma_refs": row["plasma_source_refs"]})
    ratios = sorted(a["ratio"] for a in out["animals"])
    n = len(ratios)
    # Keep ties in the denominator; rounded equality cannot strengthen either tail.
    above = sum(r > 1 and not math.isclose(r, 1, rel_tol=1e-12) for r in ratios)
    below = sum(r < 1 and not math.isclose(r, 1, rel_tol=1e-12) for r in ratios)
    majority = max(above, below)
    p = min(1.0, 2 * (sum(math.comb(n, k) for k in range(majority, n + 1)) / 2**n))
    # Invert the same two-sided sign test using order statistics, if sample size permits.
    cumulative = 0
    ci, coverage = None, None
    for k in range(n // 2):
        cumulative += math.comb(n, k)
        tail = cumulative / 2**n
        if tail > .025:
            break
        ci, coverage = [ratios[k], ratios[n - k - 1]], 1 - 2 * tail
    direction = ("above" if above > below else "below") if p < .05 else "unresolved"
    return out | {"status": "TESTED", "n_animals": n, "above": above, "below": below, "ties": n - above - below,
                  "median_ratio": ratios[(n - 1) // 2] / 2 + ratios[n // 2] / 2, "median_ci": ci,
                  "ci_coverage_at_least": coverage, "p": p, "direction": direction,
                  "scope": "One study and interval. Uncertainty comes from independent animals; assay and integration bias can shift the ratios."}


# ---------------------------------------------------------------- item 34: recovery

ROUTE_ORDER = ["URINE", "FAECES", "BILE", "CAGEWASH", "EXPIRED_AIR", "CARCASS", "TISSUE_RESIDUE", "OTHER"]


def _is_recovery_observation(o):
    return o["value_form"] == "PERCENT_OF_DOSE" and o["analyte"] in ("TOTAL_RADIOACTIVITY", "TOTAL")


def recovery_sets(obs, cards_by_ds, cfg):
    """One recovery set per dataset, species, group and occasion with a conserved quantity (item 34)."""
    sets = {}
    tol = _num(cfg.get("recovery_review_tolerance_pp"))
    for o in obs:
        if not _is_recovery_observation(o):
            continue
        grp = "individual animals" if o["level"] == "INDIVIDUAL" else (o["group"] if o["excretum"] in (None,) or o["analyte"] == "TOTAL" else "group")
        sets.setdefault((o["dataset_id"], o["species"], grp if o["analyte"] == "TOTAL" else ("individual animals" if o["level"] == "INDIVIDUAL" else "group mean"), o["occasion"]), []).append(o)
    out = []
    for (dsid, sp, grp, occ), os_ in sets.items():
        card = cards_by_ds[dsid]
        routes, totals, notes = [], [], []
        for o in os_:
            ex = o["excretum"]
            row = {"route": ex, "value": o["value"], "sd": o["sd"], "raw": o["raw"], "state": o["state"], "interval": o["interval"],
                   "interval_text": o["interval_text"], "animal": o["animal"], "record_id": o["record_id"], "denominator": o["denominator"],
                   "source_ref": o.get("obs_id") or o["record_id"], "amount_basis": o["amount_basis"],
                   "cohort_id": o.get("cohort_id") or card["collection"].get("cohort_id"),
                   "analyte": o["analyte"], "level": o["level"], "flags": list(o.get("flags", [])),
                   "label": o["group"] if o["analyte"] != "TOTAL" else f"{str(ex or 'unassigned').lower()} total ({o['component']})"}
            if o["state"] != "QUANTIFIED":
                notes.append(f"{row['label']}: {o['state'].lower()} (not zero)")
                continue
            if ex == "TOTAL":
                totals.append(dict(row, kind="SOURCE_REPORTED_TOTAL"))
            elif "+" in str(ex):
                totals.append(dict(row, kind="COMBINED_ROUTES"))
            else:
                routes.append(row)
        rs = {"key": _slug(f"{dsid}-{sp}-{grp}-{occ}"), "dataset_id": dsid, "study": card["study"], "species": sp, "group": grp, "occasion": occ,
              "conserved_quantity": "administered radiolabel" if card["radiolabel"] else "source-defined parent-equivalent total",
              "denominator": os_[0]["denominator"], "animals": card["collection"]["animals"], "cagewash": card["collection"]["cagewash"],
              "routes": routes, "source_totals": totals, "notes": notes, "caveats": [], "t12": [], "quarantined": card.get("quarantined", [])}
        by_route = {}
        for r in routes:
            by_route.setdefault(r["route"], []).append(r)
        indiv = any(r["animal"] for r in routes)
        if not indiv:
            def tot(keys):
                if not keys or any(len(by_route.get(k, [])) != 1 for k in keys):
                    return None
                if {"CARCASS", "TISSUE_RESIDUE"}.issubset(keys):
                    return None  # tissue may already be included in the whole-carcass total
                selected = [by_route[k][0] for k in keys]
                if len(selected) > 1 and (not all(x["interval"] and x["cohort_id"] for x in selected)
                        or len({(tuple(x["interval"]), x["denominator"], x["cohort_id"], x["analyte"], x["amount_basis"]) for x in selected}) != 1):
                    return None
                return sum(x["value"] for x in selected)
            rs["recovery_urine_faeces"] = tot(["URINE", "FAECES"])
            ex_keys = [k for k in by_route if k not in ("CARCASS", "TISSUE_RESIDUE")]
            rs["recovery_all_excreta"] = tot(ex_keys)
            rs["recovery_accounted"] = tot(list(by_route))
        else:
            rs["recovery_urine_faeces"] = rs["recovery_all_excreta"] = rs["recovery_accounted"] = None
            rs["notes"].append("individual animals: values are listed per animal; no mean is formed here")
        rs["route_split"] = {k: [x["value"] for x in v] for k, v in by_route.items()}
        rs["collection_ends"] = sorted({r["interval"][1] for r in routes if r["interval"]})
        missing_routes = [k for k in ("URINE", "FAECES") if k not in by_route]
        if missing_routes and totals:
            rs["notes"].append("route values not available here for " + ", ".join(x.lower() for x in missing_routes)
                               + (" (records quarantined at intake)" if rs["quarantined"] else "") + "; the printed total is shown as reported and no split is invented")
        if rs["cagewash"] == "SEPARATE" and "CAGEWASH" in by_route:
            rs["caveats"].append("CAGEWASH_UNASSIGNED")
        if card["radiolabel"]:
            rs["caveats"].append("TR_NOT_PARENT")
        if occ not in ("FIRST_DOSE", "DAY_1"):
            rs["caveats"].append("CARRYOVER_POSSIBLE")
        checks = []
        def check(name, status, row, detail, value=None):
            checks.append({"check": name, "status": status, "level": detail, "value": value,
                           "record": row["record_id"], "source_ref": row["source_ref"]})
        for x in routes + totals:
            v = x["value"]
            check("negative amount", "POINT_DISCREPANCY" if v < 0 else "NO_DISCREPANCY", x, "observed sign", v)
            ceiling = x["denominator"] != "that day's dose" or occ in ("FIRST_DOSE", "DAY_1")
            if not ceiling:
                check("recovery above the dose", "NOT_APPLICABLE", x, "a later day can include carryover", v)
            elif v > 100:
                lvl = ("tolerance unknown" if tol is None else
                       ("above the configured review tolerance" if v - 100 > tol else "within the configured review tolerance"))
                status = "ABOVE_REVIEW_TOLERANCE" if tol is not None and v - 100 > tol else "POINT_DISCREPANCY"
                check("recovery above the dose", status, x, lvl, v)
            else:
                check("recovery above the dose", "NO_DISCREPANCY", x, "on the reported denominator", v)
        for t in totals:
            if (t["kind"] == "SOURCE_REPORTED_TOTAL" and rs["recovery_accounted"] is not None
                    and set(by_route) >= {"URINE", "FAECES"} and t["interval"]
                    and all(row["interval"] == t["interval"] and row["denominator"] == t["denominator"]
                            and row["cohort_id"] == t["cohort_id"] and row["analyte"] == t["analyte"] for row in routes)):
                d = t["value"] - rs["recovery_accounted"]
                tokens = [re.match(r"\s*([-+]?\d+(?:\.\d+)?)", str(row["raw"])) for row in [t, *routes]]
                if all(tokens):
                    rounding_pp = sum(0.5 * 10 ** -_decimals(token.group(1)) for token in tokens)
                    outside = abs(d) > rounding_pp + 1e-9
                    check("printed total against its routes", "POINT_DISCREPANCY" if outside else "NO_DISCREPANCY", t,
                          "beyond printed rounding" if outside else "within printed rounding", d)
            else:
                check("printed total against its routes", "CANNOT_ASSESS", t,
                      "the admitted routes and collection windows do not establish comparable subtotals")
        rs["t12_checks"] = checks
        rs["t12"] = [c for c in checks if c["status"] in ("POINT_DISCREPANCY", "ABOVE_REVIEW_TOLERANCE")]
        if not routes and not totals:
            continue
        rs["t12_note"] = "T12 is a data check: printed values are kept, only dependent derivatives are quarantined, and no biological model is excluded."
        rs["unaccounted_candidates"] = ["later excretion", "retained material", "unmeasured routes", "loss of label", "collection or analytical losses"]
        out.append(rs)
    return out


# ---------------------------------------------------------------- item 35: components

def component_profiles(obs, cards_by_ds):
    sets = {}
    for o in obs:
        if o.get("component") is None or o["value_form"] not in ("PERCENT_OF_EXCRETUM", "PERCENT_OF_DOSE", "PERCENT_OF_CHROMATOGRAM"):
            continue
        if o["value_form"] == "PERCENT_OF_DOSE" and o["analyte"] == "TOTAL_RADIOACTIVITY":
            continue
        key = (o["dataset_id"], o["species"], o["group"], o["occasion"], o["excretum"], o["value_form"],
               tuple(o["interval"] or []), o["interval_text"], o["denominator"])
        sets.setdefault(key, []).append(o)
    profile_count = Counter(k[:4] for k in sets)
    out = []
    for key, os_ in sets.items():
        dsid, sp, grp, occ, ex, form, interval, interval_text, denominator = key
        card = cards_by_ds[dsid]
        comps = [o for o in os_ if o["analyte"] != "TOTAL" and o["state"] == "QUANTIFIED"]
        if not comps:
            continue
        total = next((o for o in os_ if o["analyte"] == "TOTAL" and o["state"] == "QUANTIFIED"), None)
        recoveries = {o["excretum_recovery_pct_dose"] for o in os_ if o.get("excretum_recovery_pct_dose") is not None}
        rec = next(iter(recoveries)) if len(recoveries) == 1 else None
        conv_block = None
        if form == "PERCENT_OF_EXCRETUM" and rec is None:
            conv_block = "no recovery of this excretum on the same cohort, interval and label; values stay on the reported basis"
        if len(recoveries) > 1:
            conv_block = "conflicting excretum recovery denominators for the same profile"
        if form == "PERCENT_OF_CHROMATOGRAM":
            conv_block = "chromatogram area requires quantitative recovery of the profiled fraction on the same mass or radiolabel basis"
        if any("WINDOW_DIFFERS_BY_ANALYTE" in o["flags"] for o in comps):
            conv_block = "the component windows differ from the excretum recovery window; no conversion"
        if any(o.get("printed_aggregate") for o in os_):
            conv_block = "printed aggregate across groups; aggregate by amounts, not by percentages, so it is kept as printed"
        rows = []
        for o in comps:
            share = o["value"]
            dose_share = share if form == "PERCENT_OF_DOSE" else (
                share * rec / 100 if form == "PERCENT_OF_EXCRETUM" and rec is not None and not conv_block else None)
            rows.append({"component": o["component"], "kind": o["analyte"], "share": share, "sd": o["sd"], "dose_share": dose_share,
                         "record_id": o["record_id"], "source_ref": o.get("obs_id") or o["record_id"], "flags": o["flags"]})
        s_sum = sum(r["share"] for r in rows)
        identified = sum(r["share"] for r in rows if r["kind"] in ("PARENT", "NAMED_COMPONENT"))
        unidentified = sum(r["share"] for r in rows if r["kind"] == "UNRESOLVED_COMPONENT")
        unprofiled = (100 - total["value"]) if (total and form == "PERCENT_OF_EXCRETUM") else None
        caveats = []
        if unprofiled is not None and unprofiled > 0:
            caveats.append("UNPROFILED_FRACTION")
        if any(r["kind"] == "NAMED_COMPONENT" for r in rows):
            caveats.append("PRODUCT_ORIGIN_OPEN")
        if card["radiolabel"] or form == "PERCENT_OF_EXCRETUM":
            caveats.append("TR_NOT_PARENT") if form == "PERCENT_OF_EXCRETUM" else None
        if occ not in ("FIRST_DOSE", "DAY_1"):
            caveats.append("CARRYOVER_POSSIBLE")
        if card["collection"]["stability"] == "not reported":
            caveats.append("STABILITY_NOT_REPORTED")
        largest = max(rows, key=lambda r: r["share"])
        profile_key = _slug(f"{dsid}-{sp}-{grp}-{occ}")
        if profile_count[key[:4]] > 1:
            profile_key += "-" + hashlib.sha256(json.dumps(key[4:]).encode()).hexdigest()[:16]
        out.append({"key": profile_key, "dataset_id": dsid, "study": card["study"], "species": sp, "group": grp, "occasion": occ,
                    "excretum": ex, "reported_basis": {"PERCENT_OF_EXCRETUM": "% of radioactivity recovered in the excretum", "PERCENT_OF_DOSE": f"% of {cards_by_ds[dsid] and os_[0]['denominator']}",
                                                       "PERCENT_OF_CHROMATOGRAM": "% of profiled chromatogram"}[form],
                    "interval_text": comps[0]["interval_text"], "excretum_recovery_pct_dose": rec, "conversion_blocked": conv_block,
                    "components": rows, "sum_check": {"sum": s_sum, "printed_total": total["value"] if total else None,
                                                      "difference": (total["value"] - s_sum) if total else None,
                                                      "status": ("reconciled within rounding" if total and abs(total["value"] - s_sum) <= 0.15 + 0.05 * len(rows) else
                                                                 ("does not reconcile; kept as printed" if total else "no printed total"))},
                    "identified_share": identified, "unidentified_share": unidentified, "unprofiled_share": unprofiled,
                    "largest": largest, "largest_product": max((r for r in rows if r["kind"] == "NAMED_COMPONENT"), key=lambda r: r["share"], default=None),
                    "assay": card["assay"], "caveats": [c for c in dict.fromkeys(caveats) if c]})
    return out


# ---------------------------------------------------------------- item 36: project species table (columns added to DIS-6b)

def _urine_windows(series):
    """Keep both the source interval measurements and any directly printed totals."""
    windows = {}
    for key, basis in (("intervals", "reported interval"), ("printed_totals", "printed total")):
        for item in series[key]:
            if (not item["interval"] or item["interval"][1] <= item["interval"][0]
                    or item.get("state", "QUANTIFIED") != "QUANTIFIED" or item["value"] is None):
                continue
            bounds = tuple(item["interval"])
            previous = windows.get(bounds)
            if previous and previous["basis"] == basis:
                previous["source_refs"].append(item["source_ref"])
                if previous["value"] != item["value"]:
                    previous["value"] = None
            else:
                windows[bounds] = {"value": item["value"], "source_refs": [item["source_ref"]], "basis": basis}
    return windows


def _align_urine_series(profiles):
    # Compare actual bins/totals and, for different binning schemes, the longest common
    # span bounded by measured endpoints. A larger window needs an exact gap-free tiling.
    indexed = [(sp, u, _urine_windows(u)) for sp, u in profiles]
    targets = set().union(*(set(w) for _, _, w in indexed))
    bounds = [{t for start_end in w for t in start_end} for _, _, w in indexed]
    for i, ends in enumerate(bounds):
        for other in bounds[i + 1:]:
            common = ends & other
            if len(common) >= 2:
                targets.add((min(common), max(common)))
    result = []
    for sp, u, windows in indexed:
        measured_bins = sorted((item for item in u["intervals"] if item["interval"] and item["state"] == "QUANTIFIED"
                                and item["value"] is not None and item["interval"][1] > item["interval"][0]),
                               key=lambda item: item["interval"])
        for start, end in targets - windows.keys():
            bins = [i for i in measured_bins if i["interval"][0] < end and i["interval"][1] > start]
            if (bins and bins[0]["interval"][0] == start and bins[-1]["interval"][1] == end
                    and all(a["interval"][1] == b["interval"][0] for a, b in zip(bins, bins[1:]))):
                windows[start, end] = {"value": sum(i["value"] for i in bins), "basis": "sum of contiguous intervals",
                                       "source_refs": [i["source_ref"] for i in bins]}
        result.append((sp, u["group"], windows, u["flags"]))
    return result


def _window_contrasts(boards):
    groups, urine = {}, {}
    for b in boards:
        for u in b["urine"]:
            key = (b["study"], u["dataset_id"], u["trace"], u["denominator"], u["route"], u["dose"], u["occasion"], u["assay"], u["level"])
            urine.setdefault(key, []).append((b["species"], u))
        for r in b["item29"]:
            if r.get("window_proxy") is None:
                continue
            key = (b["study"], r["dataset_id"], "dose / observed AUC, " + r["matrix"].lower() + ", " + r["measurement_basis"], "L/h/kg", r["route_detail"],
                   r["dose_mg_per_kg"], "FIRST_DOSE", r["assay"], r["analysis_unit"])
            value = {"value": r["window_proxy"], "basis": "observed plasma/serum window", "source_refs": [r["sid"], *r.get("auc_record_ids", [])]}
            groups.setdefault(key, []).append((b["species"], r["label"], {tuple(r["auc_window_h"]): value}, r["caveats"]))
    for key, profiles in urine.items():
        if len({sp for sp, _ in profiles}) > 1:
            groups[key] = _align_urine_series(profiles)
    out = []
    for (study, dataset, quantity, denominator, route, dose, occasion, assay, level), series in groups.items():
        species = sorted({s[0] for s in series})
        if len(species) < 2:
            continue
        series.sort(key=lambda s: (s[0], s[1]))
        windows = []
        unknown = {None, "", "NOT_FOUND", "NOT_REPORTED", "UNKNOWN"}
        eligible = bool(dose and route not in unknown and assay not in unknown and level not in unknown and occasion not in unknown)
        for bounds in sorted(set().union(*(set(s[2]) for s in series))):
            cells = [s[2].get(bounds) for s in series]
            measured = {s[0] for s, cell in zip(series, cells)
                        if cell and cell["value"] is not None and "SOURCE_CONFLICT" not in s[3]}
            windows.append({"window_h": list(bounds), "cells": cells, "comparability":
                            "descriptive_only" if eligible and len(measured) >= 2 else "incompatible"})
        shared = any(w["comparability"] == "descriptive_only" for w in windows)
        unmatched = [[a, b] for i, a in enumerate(species) for b in species[i + 1:]
                     if not any(w["comparability"] == "descriptive_only" and {a, b} <= {
                         s[0] for s, cell in zip(series, w["cells"]) if cell and cell["value"] is not None and "SOURCE_CONFLICT" not in s[3]} for w in windows)]
        out.append({"pair": species, "study": study, "dataset": dataset, "quantity": quantity, "denominator": denominator,
                    "route": route, "dose": dose, "occasion": occasion, "assay": assay, "analysis_unit": level,
                    "profiles": [{"species": sp, "group": group, "flags": flags} for sp, group, _, flags in series], "windows": windows,
                    "unmatched_pairs": unmatched, "comparability": "descriptive_only" if shared else "incompatible",
                    "reason": ("Compare values within each measured window only." if shared else
                               "No shared measured window with compatible dose, route, assay, occasion and record level.")})
    return out


def species_columns(boards, dist_data):
    rows = []
    dis_rows = {(r["species"], r["study"]): r for r in ((dist_data or {}).get("species_table") or {}).get("species_rows", [])}
    for b in boards:
        i29 = [r for r in b["item29"] if r["window_proxy"]]
        urine = [u for u in b["urine"] if u.get("r_u") is not None]
        rows.append({"species": b["species"], "study": b["study"], "board": b["key"], "dis6b": dis_rows.get((b["species"], b["study"])),
                     "window_cl": [{"profile": r["label"], "quantity": r["window_quantity"], "value": r["window_proxy"], "window": r["auc_window_h"],
                                    "description": r["value_row"], "analysis_unit": r["analysis_unit"], "measurement_basis": r["measurement_basis"],
                                    "kind": "window proxy", "unit": "L/h/kg", "assay": r["assay"], "dataset_id": r["dataset_id"], "sid": r["sid"],
                                    "source_restrictions": r.get("source_restrictions", [])} for r in i29],
                     "reported_cl": [{"label": p["label"], "as_printed": _reported_value_text(p), "value_l_per_h_kg": p.get("value_l_per_h_kg"), "dose": p.get("dose"), "dose_context": p.get("dose_context", {}),
                                      "dataset_id": p["dataset_id"], "kind": "source-reported"} for p in b["reported"] if p["param"] in ("CL", "CL_F")],
                     "urinary_recovery": [{"trace": u["trace"], "value": u["r_u"], "end_h": u["collection_end_h"], "window": u["window_label"], "group": u["group"],
                                           "occasion": u["occasion"], "denominator": u["denominator"], "dataset_id": u["dataset_id"],
                                           "flags": u["flags"], "kind": "observed collection"} for u in urine],
                     "clr": [{"kind": c["kind"], "value": c.get("clr"), "urine": c["urine_interval"], "plasma": c["plasma_window"],
                              "t10": (c.get("t10") or {}).get("status", "CANNOT_ASSESS")} for c in b["clr"] if c.get("clr")],
                     "recovery": [{"group": r["group"], "routes": r["route_split"], "accounted": r.get("recovery_accounted"),
                                   "source_totals": [t["value"] for t in r["source_totals"]], "denominator": r["denominator"]} for r in b["recovery"]],
                     "largest_product": [dict(c["largest_product"], basis=c["reported_basis"], group=c["group"])
                                         for c in b["components"] if c.get("largest_product")],
                     "in_vitro": [{"system": r["system"], "readout": READOUT_WORD[r["readout"]], "value": r["value"], "unit": r["unit"], "dataset_id": r["dataset_id"], "source_ref": r["row_id"],
                                   "eligible": not r["excluded_reason"]} for r in b["in_vitro"] if r["readout"] in ("HALF_LIFE", "VMAX_KM")]})
    contrasts = _window_contrasts(boards)
    for field, label in (("window_cl", "dose / observed AUC"), ("urinary_recovery", "urinary recovery")):
        animals = sorted({r["species"] for r in rows if r[field]})
        same_source = [c for c in contrasts if c.get("windows") and (c["denominator"] == "L/h/kg") == (field == "window_cl")]
        for i, a in enumerate(animals):
            for b in animals[i + 1:]:
                if not any(a in c["pair"] and b in c["pair"] for c in same_source):
                    contrasts.append({"pair": [a, b], "study": "across available records", "quantity": label,
                                      "comparability": "incompatible",
                                      "reason": "No source-matched study, measurement basis, dose, route and occasion for this pair. Values retain their own windows."})
    return rows, contrasts


# ---------------------------------------------------------------- figures: the five new EM panels only (E0.11)

Panel = ab.Panel
_SPECS = []
_RENDER = {"engine": None, "note": ""}
TRACE_STYLE = {"unchanged parent": (BLUE, "solid", "circle"), "active material (microbiological assay)": (GREEN, "dashed", "square"),
               "total radioactivity": (ORANGE, "dotted", "diamond_open")}
ROUTE_COLOR = {"URINE": BLUE, "FAECES": "#9a7d0a", "BILE": GREEN, "CAGEWASH": PURPLE, "EXPIRED_AIR": "#56B4E9", "CARCASS": GRAY,
               "TISSUE_RESIDUE": "#4b6273", "OTHER": "#E69F00"}
ROUTE_WORD = {"URINE": "urine", "FAECES": "faeces", "BILE": "bile", "CAGEWASH": "cage wash", "EXPIRED_AIR": "expired air", "CARCASS": "carcass",
              "TISSUE_RESIDUE": "tissue residue", "OTHER": "other"}


def _figure(name, panels, width, height, ncol=None, title=""):
    ncol = min(ncol or len(panels), len(panels))
    _SPECS.append({"file": name, "title": title, "width": width, "height": height, "dpi": ab.RENDER_DPI, "ncol": ncol,
                   "widths": [1] * ncol, "panels": [p.d for p in panels]})
    return name


def _r_script():
    import os
    if os.environ.get("ELIMINATION_R_SCRIPT"):
        return Path(os.environ["ELIMINATION_R_SCRIPT"])
    here = Path(__file__).resolve()
    for base in here.parents:
        cand = base / "pkpd_r" / "eda" / "elimination_figures.R"
        if cand.is_file():
            return cand
    return here.parent / "elimination_figures.R"


def render_all(out):
    """Draw every collected spec: R/ggplot2 first, matplotlib if R is unavailable or fails (same spec either way)."""
    specs = list(_SPECS)
    _SPECS.clear()
    path = out / "plot_specs.json"
    path.write_text(json.dumps({"version": VERSION, "rules": RULES, "figures": specs}, ensure_ascii=False, default=float), encoding="utf-8")
    if not specs:
        _RENDER.update(engine="none", note=""); return
    script, rs = _r_script(), ab._rscript()
    reason = ""
    if rs and script.is_file():
        import subprocess
        try:
            done = subprocess.run([rs, "--vanilla", str(script), str(path), str(out)], capture_output=True, text=True, encoding="utf-8", timeout=600)
            (out / "r_stderr.txt").write_text(done.stderr or "", encoding="utf-8")
            if done.returncode == 0 and all((out / s["file"]).is_file() for s in specs):
                _RENDER.update(engine="R_GGPLOT2", note=done.stdout.strip()); return
            reason = f"R renderer failed (exit {done.returncode}); see elimination/r_stderr.txt"
        except Exception as exc:  # noqa: BLE001 - reported on the page
            reason = f"R renderer could not run: {exc!r}"
    else:
        reason = "Rscript not found (set PKPD_RSCRIPT)" if not rs else f"R script missing: {script}"
    with dist._plain_log_minor_labels():
        for s in specs:
            ab._render_mpl(json.loads(json.dumps(s)), out)
    _RENDER.update(engine="MATPLOTLIB_FALLBACK", note=reason)


def _short(x, n=22):
    x = str(x or "")
    return x if len(x) <= n else x[: n - 1] + "…"


def pEM5a(urine):
    """Cumulative unchanged parent (and separate TR / active-material traces) at the observed collection ends."""
    dens = {u["denominator"] for u in urine}
    if len(dens) != 1 or not any(len({c["t"] for c in u["cumulative"] if c["t"] is not None}) >= 2 for u in urine):
        return None
    p = Panel("EM-5a · cumulative urinary recovery", "Collection end (h)", "Cumulative recovery (% of " + (dens.pop().replace("administered ", "") if len(dens) == 1 else "dose") + ")")
    ymax, xmax, n, banded = 0.0, 0.0, 0, False
    traces = {u["trace"] for u in urine}
    for i, u in enumerate(urine):
        cum = [c for c in u["cumulative"] if c["t"] is not None]
        if not cum:
            continue
        col, lty, shp = TRACE_STYLE[u["trace"]]
        if len(traces) == 1 or u["trace"] == "unchanged parent":
            col = CAT[i % len(CAT)] if len(urine) > 1 else col
        xs, ys = [c["t"] for c in cum], [c["value"] for c in cum]
        # points at the observed collection ends only; no line is drawn from time zero through unsampled time
        occ = "day " + u["occasion"].split("_")[-1] if u["occasion"].startswith("DAY_") else ""
        lab = " · ".join(x for x in (_short(u["group"]), u["trace"], occ if occ.lower() not in str(u["group"]).lower() else "") if x)
        if len(xs) >= 2 and not u["gaps"]:
            p.line(xs, ys, color=col, lty=lty, lw=0.6)
        p.points([c["t"] for c in cum], [c["value"] for c in cum], color=col, shape=shp, size=2.6, label=lab or u["trace"])
        for g in u["gaps"]:
            if g["interval"] and g["interval"][1] <= cum[-1]["t"] + 1e-9:
                p.band(g["interval"][0], g["interval"][1], color=GRAY, alpha=0.18)
                banded = True
        ymax, xmax, n = max(ymax, max(ys)), max(xmax, max(xs)), n + 1
    if not n:
        return None
    small = [u for u in urine if "LATE_INCREMENT_SMALL" in u["flags"]]
    note = []
    if small:
        note.append("small last increment (< %d %% of the total): " % round(100 * small[0]["late_increment"]["setting"]) + ", ".join(_short(u["group"], 14) for u in small[:4]))
    if banded:
        note.append("grey: interval not collected")
    for u in urine:
        rec = u.get("reconcile") or {}
        if rec.get("difference") is not None and abs(rec["difference"]) > 1e-8:
            note.append(f"{u['group']}: intervals sum to {_f(rec['sum_of_increments'])}%; printed total {_f(rec['printed'])}%.")
    if note:
        p.text(0.98, 0.04, "\n".join(note), hjust=1, vjust=0, size=2.6, npc=True)
    p.set(ylim=[0, max(ymax * 1.25, 5)], xlim=[0, xmax * 1.08 if xmax else 1], legend="top_left")
    return p


def pEM5c(rows):
    """One CLR value per urine interval; window proxies open, interval estimates filled. No band unless fu,p and GFR are sourced."""
    ok = [r for r in rows if r.get("clr") is not None and r["kind"] in ("INTERVAL_ESTIMATE", "WINDOW_PROXY")]
    reference = any((r.get("t10") or {}).get("filtration_range_l_h_kg") for r in ok)
    if not ok or (len({tuple(r["urine_interval"]) for r in ok}) < 2 and not reference):
        return None
    p = Panel("EM-5c · interval renal clearance", "", "CLR (mL/min/kg)")
    labs = list(dict.fromkeys(f"{_f(r['urine_interval'][0])}–{_f(r['urine_interval'][1])} h" for r in ok))
    plabs = list(dict.fromkeys(r["plasma_label"] for r in ok))
    ys = [r["clr_ml_min_kg"] for r in ok]
    has_reference = False
    for j, pl in enumerate(plabs):
        rr = [r for r in ok if r["plasma_label"] == pl]
        off = (j - (len(plabs) - 1) / 2) * 0.12
        est = [r for r in rr if r["kind"] == "INTERVAL_ESTIMATE"]
        prx = [r for r in rr if r["kind"] == "WINDOW_PROXY"]
        col = CAT[j % len(CAT)]
        if est:
            p.points([labs.index(f"{_f(r['urine_interval'][0])}–{_f(r['urine_interval'][1])} h") + 1 + off for r in est], [r["clr_ml_min_kg"] for r in est],
                     color=col, shape="circle", label=f"interval estimate · {_short(pl, 18)}")
        if prx:
            p.points([labs.index(f"{_f(r['urine_interval'][0])}–{_f(r['urine_interval'][1])} h") + 1 + off for r in prx], [r["clr_ml_min_kg"] for r in prx],
                     color=col, shape="open", size=3.0, label=f"partial-window proxy · {_short(pl, 18)}")
            for r in prx:
                x = labs.index(f"{_f(r['urine_interval'][0])}–{_f(r['urine_interval'][1])} h") + 1 + off
                p.text(x + 0.06, r["clr_ml_min_kg"], f"plasma {_f(100 * r['plasma_coverage'], 2)} %", hjust=0, vjust=0.5, size=2.5)
        for r in rr:
            t10_result = r.get("t10") or {}
            ref = t10_result.get("filtration_range_l_h_kg")
            if ref:
                xref = labs.index(f"{_f(r['urine_interval'][0])}–{_f(r['urine_interval'][1])} h") + 1 + off - 0.075
                low, high = [v * ML_MIN_KG_PER_L_H_KG for v in ref]
                label = "Filtration range" if t10_result["matched"] else "Filtration range (sensitivity context)"
                p.segments([xref], [low], [xref], [high], color=GRAY, lw=2.2, label=label)
                if high == low:
                    p.points([xref], [low], color=GRAY, size=1.9, label=label)
                ys.append(high)
                has_reference = True
            for lim, sign in ((r.get("limits") or (None, None))[0], 1), ((r.get("limits") or (None, None))[1], -1):
                if lim:
                    x = labs.index(f"{_f(r['urine_interval'][0])}–{_f(r['urine_interval'][1])} h") + 1 + off
                    p.add("segment", x=[x], y=[lim * ML_MIN_KG_PER_L_H_KG], xend=[x], yend=[lim * ML_MIN_KG_PER_L_H_KG * (1.4 if sign > 0 else 0.7)],
                          color=col, lw=1.2, label=None, lty="solid", arrow=True)
    t10s = sorted({(r.get("t10") or {}).get("status", "CANNOT_ASSESS") for r in ok})
    note = "" if has_reference else "Filtration reference unavailable\n"
    p.text(0.02, 0.98, note + "T10: " + ", ".join(x.replace("_", " ").lower() for x in t10s), hjust=0, vjust=1, size=2.6, npc=True)
    p.set(xbreaks=list(range(1, len(labs) + 1)), xlabels=labs, xlim=[0.4, len(labs) + 0.9], ylim=[0, max(ys) * 1.45], legend="bottom_left")
    return p


def _recovery_comparison(rs):
    """Require the same measured quantity and collection window within identified animals or a sourced cohort."""
    allowed = {"URINE", "FAECES", "EXPIRED_AIR"}
    if rs["animals"] == "BILE_CANNULATED":
        allowed.add("BILE")
    rows = [r for r in rs["routes"] if r["route"] in allowed]
    if len({r["route"] for r in rows}) < 2:
        return {}
    bases = {(tuple(r["interval"] or []), r["denominator"], r["analyte"], r["amount_basis"]) for r in rows}
    if len(bases) != 1:
        return {}
    interval, denominator, _, _ = bases.pop()
    if len(interval) != 2 or interval[0] >= interval[1] or denominator in (None, "", "not stated", "NOT_FOUND"):
        return {}
    units = {}
    for r in rows:
        unit = f"Animal {r['animal']}" if r["animal"] is not None else r.get("cohort_id")
        if not unit or r["value"] < 0 or "SOURCE_CONFLICT" in r["flags"]:
            return {}
        values = units.setdefault(str(unit), {})
        if r["route"] in values:
            return {}
        values[r["route"]] = r
    if len({r.get("cohort_id") for r in rows}) > 1 or len({r["animal"] is None for r in rows}) > 1:
        return {}
    if len({frozenset(values) for values in units.values()}) != 1:
        return {}
    return units


def pEM6a(rs):
    units = _recovery_comparison(rs)
    if not units:
        return None
    first = next(iter(units.values()))
    row = next(iter(first.values()))
    start, end = row["interval"]
    p = Panel(f"EM-6a · excretion by route, {_f(start)}–{_f(end)} h", "", f"% of {row['denominator']}")
    routes = [rt for rt in ROUTE_ORDER if rt in first]
    for index, route in enumerate(routes):
        offset = (index - (len(routes) - 1) / 2) * 0.12
        xs = [i + offset for i in range(1, len(units) + 1)]
        ys = [values[route]["value"] for values in units.values()]
        p.points(xs, ys, color=ROUTE_COLOR[route], size=3, label=ROUTE_WORD[route])
    p.set(xbreaks=list(range(1, len(units) + 1)), xlabels=list(units),
          xlim=[0.5, len(units) + 0.5], legend="bottom_left")
    return p


def _wrapw(x, n=14):
    import textwrap
    return "\n".join(textwrap.wrap(str(x), n, break_long_words=False)) or str(x)


def pEM7b(g):
    rows = sorted(g["rows"], key=lambda r: r["species"])
    unit = "unit not stated" if g["unit"] in (None, "not stated", "NOT_FOUND") else g["unit"]
    p = Panel(f"EM-7b · {READOUT_WORD[g['readout']]}" + (f" at {_f(g['time_min'])} min" if g["time_min"] else ""), "", f"{READOUT_WORD[g['readout']]} ({unit})")
    xs = list(range(1, len(rows) + 1))
    p.points(xs, [r["value"] for r in rows], color=BLUE, size=3.0)
    for x, r in zip(xs, rows):
        p.text(x + 0.1, r["value"], str(r["raw"]).strip(), hjust=0, vjust=0.5, size=2.6)
    exclusions = {}
    for x in g["left_out"]:
        exclusions.setdefault(x["reason"], []).append(x["species"])
    notes = [_wrapw(f"Excluded: {', '.join(species)} ({reason})", 48) for reason, species in exclusions.items()]
    p.text(0.98, 0.98, "\n".join([_wrapw(g["system"], 48), *notes]), hjust=1, vjust=1, size=2.5, npc=True)
    ys = [r["value"] for r in rows]
    p.set(xbreaks=xs, xlabels=[r["species"] for r in rows], xlim=[0.4, len(rows) + 0.8], ylim=[0, max(ys) * 1.4])
    return p


def figures(boards, out, assay_groups=()):
    for b in boards:
        figs = b["figs"]
        key = b["key"]
        by_ds = {}
        for u in b["urine"]:
            by_ds.setdefault(u["dataset_id"], []).append(u)
        for dsid, us in by_ds.items():
            p = pEM5a(us)
            if p:
                figs[f"EM5a|{dsid}"] = _figure(f"EM5a_{key}-{_slug(dsid)}.png", [p], 6.0, 4.0)
        if b["clr"]:
            p = pEM5c(b["clr"])
            if p:
                figs["EM5c|board"] = _figure(f"EM5c_{key}.png", [p], 6.0, 4.0)
        for rs in b["recovery"]:
            p = pEM6a(rs)
            if p:
                figs[f"EM6a|{rs['key']}"] = _figure(f"EM6a_{rs['key']}.png", [p], 5.6 if len(rs["routes"]) < 4 else 6.4, 4.0)
    comparisons = []
    for g in assay_groups:
        if g["drawn"]:
            file = _figure(f"EM7b_{_slug(g['key'])}.png", [pEM7b(g)], 5.4, 3.8)
            comparisons.append({k: g[k] for k in ("key", "study", "dataset_id", "system", "drug", "readout", "unit",
                                                    "time_min", "normalization", "controls", "direction")} | {"file": file})
    return comparisons


# ---------------------------------------------------------------- question rows (E0.11): Q1, Q2, Q3, Q5, Q6, Q7; Q4 reserved, no row

READING_MAP = [
    ("EM-1a (value row)", "Dose divided by observed AUC for the named measurement and profile",
     "Dose / observed AUC(a,b), with the window, assay basis and individual or group-mean level. Conditional limits have their own assumptions.",
     "A window-specific starting value. Missing exposure tends to raise the ratio if the numerical area is accurate. Check quadrature and definitions when a source-reported clearance lies above it"),
    ("Q2 (upstream C2 / DIS-2b)", "The upstream dose panel with its T3 / T3p result; urine by dose from EM-5a",
     "The reading table of item 30: which candidates remain and which measurement separates them", "Saturable elimination, F or input change (EV), binding, timing; candidates only"),
    ("Q3 (upstream E1, E2 / DIS-4c)", "The upstream occasion panel with the T9 or item 23 result; urine by occasion from EM-5a",
     "The measured change kept apart from its cause", "Increased clearance or reduced input (EV); carryover in urine"),
    ("EM-5a", "Cumulative unchanged parent at each collection end, by dose and occasion where measured; gaps; the last increment",
     "r_U with its lower limit; 'small last increment' when configured",
     "Report observed recovery on its source basis. Use 'at least' only for a supported lower limit. A conclusion about a minor route requires an upper limit on ultimate recovery"),
    ("EM-5c", "The CLR value of each interval and the coverage of urine and plasma; once the filtration range is sourced, the CLR limits against it",
     "Interval estimate or labelled partial-window proxy; T10: excluded above, excluded below, not excluded, cannot assess",
     "Net appearance beyond filtration (compatible with secretion); less parent in urine than filtration predicts; filtration alone compatible"),
    ("Recovery table / EM-6a", "Read each value with its collection window, denominator and animal or group",
     "Source totals have their own rows. An optional plot compares matched excretion routes.",
     "A route share requires a measurement on that route. A total alone leaves its allocation unresolved."),
    ("Component table", "Largest measured component in each excretum and window; unassigned and unprofiled parts", "Component share (of dose when the excretum recovery matches); identified share",
     "A product was observed. Its origin (enzymatic, chemical in vivo, after collection) stays open until controls and stability separate them"),
    ("EM-7b", "Ranking within matched systems only; controls", "More or less loss on one assay basis", "A species or system difference in loss on that basis. Not a pathway and not a scaled clearance"),
    ("EM-8a (columns of DIS-6b)", "Which cells are filled and which contrasts are comparable", "comparable / descriptive_only / incompatible, each with the reason",
     "Per species: one observation, its principal unresolved alternative and one feasible discriminator"),
]

QD = {
    1: ("Dose / observed plasma AUC", "What does the plasma window tell us about clearance?",
        "the dose over the observed-window AUC from the upstream record, with its window", "CL over all time: no tail is extrapolated and no limit is formed by default"),
    2: ("Dose", "Does exposure scale with dose?", "the upstream dose comparison and its test result", "a cause for a departure from proportionality"),
    3: ("Repeated dosing", "What changes on repeat dosing?", "the upstream occasion comparison and urine by occasion", "whether clearance or input changed"),
    5: ("Urine", "How much parent is in urine, and is CLR consistent with filtration?", "cumulative unchanged parent at the observed collection ends",
        "ultimate fe beyond the last collection, or secretion without a sourced filtration range"),
    6: ("Recovery", "Where did the dose go?", "route-specific recovery on its stated denominator", "how the unaccounted part divides between its candidate causes"),
    7: ("Components, in vitro, species", "What products, systems and species can be compared?", "measured component shares and matched in vitro readouts",
        "a pathway, the origin of a product, or a scaled clearance"),
}
STATUS_FROM = {"ANSWERABLE": ST_YES, "PARTLY_ANSWERABLE": ST_PART, "NOT_ANSWERABLE_YET": ST_NO, "NOT_APPLICABLE": ST_NA}


def _qrow(qn, status, observed, basis="", reach="", missing=(), primary=None, views=(), evidence=(), shown=True):
    return {"q": qn, "display_number": qn, "label": QD[qn][0], "question": QD[qn][1], "status": status, "status_code": ST_CODE[status],
            "observed": observed, "basis": basis, "reach": reach, "text": " ".join(x for x in (observed, basis, reach) if x),
            "missing": [m for m in dict.fromkeys(missing) if m], "primary": primary, "views": list(views), "evidence": list(evidence), "shown": shown}


def _prim(file, panel, qn, label_line, level):
    if not file:
        return None
    return {"kind": "panel", "file": file, "panels": [panel],
            "lines": [f"Q{qn} · {QD[qn][0]}", label_line, "Shows " + QD[qn][2], "Cannot show: " + QD[qn][3]], "level": level}


def _rowprim(qn, head, rows, label_line, level):
    return {"kind": "row", "head": list(head), "rows": [list(r) for r in rows],
            "lines": [f"Q{qn} · {QD[qn][0]}", label_line, "Shows " + QD[qn][2], "Cannot show: " + QD[qn][3]], "level": level}


def _view(panel, file, label, tier=1):
    return {"panel": panel, "file": file, "label": label, "tier": tier}


def _lvl(level):
    return {"GROUP_MEAN": "group mean", "INDIVIDUAL": "individual", "MIXED": "individual and group mean", "NOT_REPORTED": "not reported",
            "INDIVIDUAL_IDENTITY_UNVERIFIED": "individual, identity not verified"}.get(level, str(level or "not reported").lower())


def _words(flags):
    return ", ".join(str(f).replace("_", " ").lower() for f in flags) or "—"


def _reported_value_text(p):
    raw = str(p["raw"])
    if p.get("unit") not in (None, "not stated") and p["unit"] not in raw:
        raw += " " + p["unit"]
    if p.get("dispersion_ref"):
        raw += f" ({p['dispersion_type']} {_f(p['sd'], 4)} {p['unit']})"
    return raw


def _reported_routes(parameters, dataset):
    return " / ".join(dict.fromkeys(p["route_detail"] if p.get("route_detail") not in (None, "NOT_FOUND")
                                   else p["route"] for p in parameters if p["dataset_id"] == dataset))


def _rep_rows(ps):
    return [[p["name"] + (" (phase unspecified)" if p.get("half_life_phase") == "unspecified" else ""), p["label"], _reported_value_text(p),
             _f(p.get("value_l_per_h_kg")), _f(p.get("dose")) if p.get("dose") else _study_dose_text(p.get("dose_context", {})) or "—", p["occasion"].replace("_", " ").lower(), p["method"],
             f"{p['dataset_id']} · {p['record_id']}", p["route_detail"] if p.get("route_detail") not in (None, "NOT_FOUND") else p["route"], p["matrix"]] for p in ps]


REP_HEAD = ["Parameter", "As labelled", "As printed", "L/h/kg", "Dose (mg/kg)", "Occasion", "Method", "Dataset · record", "Route", "Matrix"]


def q1_row(b):
    rows = b["item29"]
    ok = [r for r in rows if r["window_proxy"]]
    rep = [p for p in b["reported"] if p["param"] in ("CL", "CL_F", "CLR", "CLNR", "THALF", "KE") and not p["shown_in_absorption_F"]]
    level = "; ".join(sorted({_lvl(r["analysis_unit"]) for r in rows})) or "—"
    ev, views, missing = [], [], []
    if rows:
        ev.append({"rule": "Item 29: D/ÂUC over the observed window, with the window AUC read from the upstream A0.6 record when it holds the same profile, "
                           "window and method; otherwise the same routine on the quantified points. Not extrapolated; no limit by default (E0.6).",
                   "data": sorted({r["dataset_id"] for r in rows}),
                   "tables": [{"caption": "EM-1a value rows", "head": ["Source profile", "Measured signal", "Record level", "Route", "Dose (mg/kg)", "Window (h)", "Observed AUC (mg·h/L)", "Dose / observed AUC (L/h/kg)", "AUC source", "Caveats", "Source restrictions"],
                               "rows": [[r["sid"], r["measurement_basis"], _lvl(r["analysis_unit"]), r["route"], _f(r["dose_mg_per_kg"]),
                                         " – ".join(_f(x) for x in (r["auc_window_h"] or [])) or "—", _f(r["auc_window"]), _f(r["window_proxy"]),
                                         r["auc_source"] or r["not_assessable_reason"] or "—", _words(r["caveats"]),
                                         ", ".join(v["operation"] for v in r["source_restrictions"] if v.get("operation")) or "—"] for r in rows]}]})
        sens = [(r, x) for r in rows for x in r["sensitivity_rows"]]
        if sens:
            ev.append({"rule": "Folded sensitivity rows (item 29 step 4). Each holds only under its stated assumption and is not a finding.", "data": [],
                       "tables": [{"caption": "Sensitivity rows (not shown by default)", "head": ["Profile", "Kind", "Statement", "Assumption"],
                                   "rows": [[r["label"], x["kind"].replace("_", " ").lower(), x["text"], x["assumption"]] for r, x in sens]}]})
        comparisons = []
        for r in ok:
            for c in r.get("reported_cl_candidates", []):
                check = r["reported_cl_check"] if c["status"] == "MATCHED" else None
                reason = " ".join(c["issues"])
                if c["status"] == "LINK_UNVERIFIED":
                    reason = ("Experiment linkage unverified. " + reason).strip()
                comparisons.append([r["sid"], c["source_cell"] or c["record_id"], f"{c['raw']} {c['unit']}",
                                    _f(check["ratio_to_window"]) if check else "—", check["reading"] if check else reason,
                                    " | ".join(c["citations"]) or "—"])
        if comparisons:
            ev.append({"rule": "Item 29 compares reported clearance with dose / observed AUC when the source links the estimate to the same profile and the measurements are compatible.",
                       "data": [], "tables": [{"caption": "Reported clearance and experiment linkage",
                       "head": ["Profile", "Parameter cell", "Reported clearance", "Ratio to window", "Interpretation", "Linking evidence"],
                       "rows": comparisons}]})
    if rep:
        ev.append({"rule": "EM-R: source-reported parameters, kept as printed and never substituted for the window value (E0.12).", "data": sorted({p["dataset_id"] for p in rep}),
                   "tables": [{"caption": "Source-reported parameters", "head": REP_HEAD, "rows": _rep_rows(rep)}]})
    if ok:
        iv = [r for r in ok if r["route"] == "IV"]
        parent_iv = [r for r in iv if r["assay"] != "MICROBIOLOGICAL" and "PARENT_IDENTITY_UNVERIFIED" not in r["caveats"]]
        r0 = (parent_iv or iv or ok)[0]
        st = ST_YES if parent_iv else ST_PART
        more = len(ok) - 1
        observed = r0["value_row"] + (f" See the evidence table for {more} additional profile{'s' if more > 1 else ''}." if more else "")
        basis = r0["direction_note"]
        reach = r0["dose_exposure_target"]
        restricted = sorted({v["operation"] for v in r0["source_restrictions"]
                             if v.get("operation") in {"PK_MODELING", "TIME_AXIS_SELECTION", "NCA"}})
        if restricted:
            reach += f" Source restrictions for {r0['sid']}: " + ", ".join(restricted) + "."
        if "REPORTED_CL_ABOVE_WINDOW" in r0["caveats"]:
            reach += f" The reported clearance for {r0['sid']} exceeds its window ratio. Check integration, definitions and dose units."
        for r in ok:
            f = r["upstream_panel"]["file"] if r.get("upstream_panel") else None
            if f and r is not r0:
                views.append(_view(r["upstream_panel"]["panel"], f, r["label"]))
        f0 = r0["upstream_panel"]["file"] if r0.get("upstream_panel") else None
        prim = (_prim(f0, r0["upstream_panel"]["panel"], 1, "EM-1a · " + r0["value_row"], _lvl(r0["analysis_unit"])) if f0 else
                _rowprim(1, ["Source profile", "Measured signal", "Record level", "Window (h)", "Dose / observed AUC (L/h/kg)"],
                         [[r["sid"], r["measurement_basis"], _lvl(r["analysis_unit"]), " – ".join(_f(x) for x in r["auc_window_h"]), _f(r["window_proxy"])]
                          for r in ok], "EM-1a value rows", level))
        if not f0:
            missing.append("upstream DIS-1a or B1 panel for this profile (mismatch recorded; value row shown)")
        missing += ["plasma area outside the observed window"] + ([] if iv else ["an IV reference for CL"])
        if r0.get("unbound_reason"):
            missing.append(r0["unbound_reason"])
        return _qrow(1, st, observed, basis, reach, missing, prim, views, ev)
    if rep:
        observed = "Only source-reported values: " + "; ".join(f"{p['name']} {p['raw']}" + (f" {p['unit']}" if p['unit'] != "not stated" and str(p['unit']) not in str(p['raw']) else "") for p in rep[:3]) + "."
        if any(p.get("review_source") for p in rep):
            observed = "The source reports plasma parameters for the conditions listed below."
        table = _rowprim(1, REP_HEAD, _rep_rows(rep), "EM-R · source-reported parameters", "as reported")
        table["lines"][2] = "Shows parameter definitions and estimates as reported in the source."
        q = _qrow(1, ST_PART, observed, "", "", ["a systemic parent plasma profile after a known dose"], table, [], ev)
        if b.get("distribution_tissue_table"):
            q["distribution_tissue_table"] = b["distribution_tissue_table"]
        return q
    in_f = [p for p in b["reported"] if p["shown_in_absorption_F"] and p["param"] in ("CL_F", "THALF")]
    if in_f and not rows:
        return _qrow(1, ST_PART, "No plasma profile here; the source-reported " + ", ".join(dict.fromkeys(p["name"] for p in in_f)) + " is shown in absorption F and not repeated.",
                     "A parameter-only answer is at most partly answerable (E0.12).", "", ["parent plasma concentrations after a known dose"], None, [], ev)
    if rows:
        why = "; ".join(dict.fromkeys(r["not_assessable_reason"] for r in rows if r["not_assessable_reason"]))
        og = [r["ongoing_input"] for r in rows if r.get("ongoing_input") and r["ongoing_input"]["sample_variation"] == "WITHIN_BAND"]
        if og:
            ev.append({"rule": "During a constant-rate infusion, rate over concentration equals CL at steady state only; reported as conditional (item 29).",
                       "data": sorted({r["dataset_id"] for r in rows if r.get("ongoing_input")}),
                       "tables": [{"caption": "Infusion rate over sampled mean concentration", "head": ["Regimen", "Window (h)", "n", "Mean C (mg/L)", "Max/min", "Rate / C (L/h/kg)", "Label"],
                                   "rows": [[o["regimen"], f"{_f(o['window_h'][0])}–{_f(o['window_h'][1])}", str(o["n"]), _f(o["mean_concentration_mg_l"]), f"{o['fold']:.2f}",
                                             _f(o["value_l_per_h_kg"]), o["label"]] for o in og]}]})
            q = _qrow(1, ST_PART, f"The dose-to-observed-AUC ratio is not formed: {why}. " + " ".join(_ongoing_text(o) for o in og), "", "",
                      ["samples after the infusion stops, or independent evidence of steady state"], None, [], ev)
            q["ongoing_input"] = og
            return q
        return _qrow(1, ST_NO, f"The dose-to-observed-AUC ratio is unavailable: {why}.", "", "", ["an eligible first-dose parent plasma profile"], None, [], ev)
    return _qrow(1, ST_NO, "No systemic parent plasma profile for this study and species.", "", "", ["parent plasma concentrations after a known dose"], None, [], ev)


def _dose_reading(series, *, reported=False):
    rows = series["rows"]
    doses = ", ".join(f"{r['dose']:g}" for r in rows)
    values = ", ".join(f"{r['auc_per_dose']:.4g}" if r["auc_per_dose"] is not None else "unavailable" for r in rows)
    if reported:
        window = series.get("window")
        basis = f"{series['dataset_id']} reports AUC" + (f" ({window})" if window not in (None, "", "NOT_FOUND") else " (window unspecified)")
    else:
        a, b = series["window"]
        basis = f"Observed profiles over {_f(a)}–{_f(b)} h"
    text = f"{basis}. At {doses} mg/kg, AUC/dose was {values} {series['unit']}, respectively."
    vals = [r["auc_per_dose"] for r in rows]
    if reported and None not in vals and min(vals) > 0:
        text += f" The largest value was {max(vals)/min(vals):.3g} times the smallest."
    elif len(vals) > 2 and None not in vals and min(vals[1:-1]) > max(vals[0], vals[-1]):
        text += " Intermediate doses had higher values than either endpoint."
    if series.get("peak_ratio") is not None:
        text += f" High-dose Cmax/dose was {100 * series['peak_ratio']:.0f}% of the low-dose value."
    return text


def q2_row(b):
    i30 = b["item30"]
    direct = _clearance_contrast_question(2, i30.get("clearance_contrasts", []))
    if direct:
        return direct
    level = "; ".join(sorted({_lvl(r["analysis_unit"]) for r in b["item29"]})) or "—"
    up = i30["upstream"]
    ev = [{"rule": "Individual true IV clearance contrast was not run: " + "; ".join(r["reasons"]),
           "data": [], "tables": [{"caption": "Prespecified clearance contrast", "head": ["ID", "Status", "Design source"],
           "rows": [[r.get("id"), r["status"], r.get("design_source") or "not supplied"]]}]}
          for r in i30.get("clearance_contrasts", []) if r.get("status") != "ASSESSED"]
    reported_auc = i30.get("reported_auc", [])
    for series in [u["exposure"] for u in up if u.get("exposure")] + reported_auc:
        ev.append({"rule": f"{series['basis']}; {series['unit']}.", "data": [series["dataset_id"]] if series.get("dataset_id") else [],
                   "tables": [{"caption": series.get("key") or "Common-window AUC by dose",
                               "head": ["Dose (mg/kg)", f"AUC/dose ({series['unit']})", "Source records"],
                               "rows": [[_f(r["dose"]), _f(r["auc_per_dose"], 4), ", ".join(r["refs"])] for r in series["rows"]]}]})
    if i30["urine_by_dose"]:
        ev.append({"rule": "Urine by dose from EM-5a (item 30 step 5): direction readings are candidates only.", "data": [],
                   "tables": [{"caption": "Unchanged parent in urine by dose (% of dose)", "head": ["Interval (h)", "Values by dose"],
                               "rows": [[" – ".join(_f(x) for x in u["interval"]), "; ".join(f"{_f(d)} mg/kg: {_f(v)}" for d, v in sorted(u["values"].items()))] for u in i30["urine_by_dose"]]}]})
    if i30["reported_by_dose"]:
        ev.append({"rule": "Source-reported values by dose (EM-R).", "data": sorted({p["dataset_id"] for p in i30["reported_by_dose"]}),
                   "tables": [{"caption": "Reported by dose", "head": REP_HEAD, "rows": _rep_rows(i30["reported_by_dose"])}]})
    reach = ("Remaining candidates: " + ", ".join(i30["alternatives"]) + f". Next: {i30['next_discriminator']}.") if i30["alternatives"] else (
        f"Next: {i30['next_discriminator']}." if i30["next_discriminator"] else "")
    if up:
        ev.append({"rule": "Read from the upstream record by ID and version; elimination repeats no figure and no test and does not upgrade the status.", "data": [],
                   "tables": [{"caption": "Upstream dose results", "head": ["Source", "Route", "Doses (mg/kg)", "Window (h)", "AUC ratio", "T3", "T3p", "Pattern"],
                               "rows": [[u["source"], u["route"], ", ".join(_f(d) for d in (u["doses"] or [])), u.get("window_h") or "—", _f(u.get("auc_ratio")),
                                         u["t3"], u["t3p"], u.get("pattern") or "—"] for u in up]}]})
        u0 = next((u for u in up if u.get("exposure")), next((u for u in up if u.get("panel")), up[0]))
        tested = [u for u in up if _has_dose_test(u)]
        st = ST_YES if len(tested) == len(up) and all(u["route"] == "IV" and not (LIMITED_TEST_FLAGS | {"CONFOUNDED"}).intersection(u["caveats"]) for u in up) else ST_PART
        observed = (_dose_reading(u0["exposure"]) if u0.get("exposure") else
                    f"{u0['source']}: doses {', '.join(_f(d) for d in (u0['doses'] or []))} mg/kg. "
                    + (f"The upstream profile pattern was {u0['pattern'].replace('_', ' ').lower()}." if u0.get("pattern")
                       else "Dose-specific common-window AUC values are unavailable in this record."))
        if u0.get("auc_ratio") is not None:
            observed += f" High/low AUC-per-dose ratio: {_f(u0['auc_ratio'])}."
        basis = f"T3: {u0['t3']}; T3p: {u0['t3p']}."
        reason = (u0.get("exposure") or {}).get("test_reason")
        if not _has_dose_test(u0):
            basis += " Dose proportionality remains unresolved." + (" " + reason.rstrip(".") + "." if reason else "")
        elif reason and reason.startswith("power model"):
            # absorption ran T3 as a power model on the dose groups (no SD per time point): say what the label rests on
            basis += " T3 is a " + reason.rstrip(".") + ". With so few dose groups only a large departure from proportionality could be excluded."
        if u0.get("caveats"):
            basis += " Comparison limits: " + _words(u0["caveats"]) + "."
        views = [_view(u["panel_id"], u["panel"], f"{u['key']}") for u in up if u.get("panel") and u is not u0]
        prim = _prim(u0.get("panel"), u0["panel_id"], 2, f"Upstream {u0['panel_id']} · {u0['source']}", level)
        return _qrow(2, st, observed, basis, reach, ["matched IV doses" if any(u["route"] == "EV" for u in up) else ""], prim, views, ev)
    if reported_auc:
        series = reported_auc[0]
        restrictions = [r["operation"] for r in series["source_restrictions"] if r.get("operation")]
        basis = "Descriptive comparison of source-reported parameters. The AUC window and sampling variance must be verified before formal interpretation." if series["window"] in (None, "", "NOT_FOUND") else "Descriptive comparison of source-reported parameters."
        if restrictions:
            basis += f" Source restrictions for {series['dataset_id']}: " + ", ".join(restrictions) + "."
        primary = _rowprim(2, ["Dose (mg/kg)", f"Reported AUC ({series['auc_unit']})", f"AUC/dose ({series['unit']})"],
                           [[_f(r["dose"]), _f(r["auc"]), _f(r["auc_per_dose"], 4)] for r in series["rows"]],
                           series["key"], "Source-reported parameters")
        return _qrow(2, ST_PART, _dose_reading(series, reported=True), basis, reach, ["profiles and uncertainty at the reported doses"], primary, [], ev)
    if i30["reported_by_dose"] or i30["urine_by_dose"]:
        rows = [[p["name"], _f(p["dose"]), f"{p['raw']}"] for p in i30["reported_by_dose"][:8]] + \
               [[f"urine {' – '.join(_f(x) for x in u['interval'])} h (% of dose)", _f(d), _f(v)] for u in i30["urine_by_dose"] for d, v in sorted(u["values"].items())]
        return _qrow(2, ST_PART, "No upstream plasma dose comparison; source-reported values or urine by dose are listed.", "", reach,
                     ["two or more matched plasma profiles at different doses"], _rowprim(2, ["Quantity", "Dose (mg/kg)", "Value"], rows, "Values by dose", level), [], ev)
    obs = i30["not_assessable_reason"] or "No dose comparison."
    if i30.get("multi_dose_study_context"):
        return _qrow(2, ST_NO, obs[0].upper() + obs[1:].rstrip(".") + ".", "", reach,
                     ["individual dose groups linked to comparable exposure measurements"], None, [], ev)
    return _qrow(2, ST_NO, obs[0].upper() + obs[1:] + ("" if obs.endswith(".") else "."), "", reach, ["a second dose with the same timing, matrix and concentration basis"], None, [], ev)


def _occasion_table(item):
    days = item["occasions"]
    reported = {}
    for p in item["reported_by_occasion"]:
        unit = p["unit"]
        if p.get("unit_conflict"):
            unit = f"Table: {p.get('table_unit') or 'unspecified'}. Text: {', '.join(p['text_units']) or 'verify source'}. Unit unresolved."
        basis = p["dispersion_type"]
        if basis in ("SD", "SE") and p.get("n_note"):
            basis = f"{basis}, n = {p['n_note']}"
        key = (p["dataset_id"], p["record_id"], p["label"], unit, basis)
        reported.setdefault(key, {}).setdefault(p["occasion"], []).append(str(p["raw"]))
    rows = [[label.split(" (")[0], *[", ".join(values.get(d, [])) or "—" for d in days], unit,
             basis if basis != "UNKNOWN" else "as reported", ds]
            for (ds, _, label, unit, basis), values in reported.items()]
    return ["Reported parameter", *[d.replace("_", " ").capitalize() for d in days], "Unit", "Dispersion", "Source"], rows


def q3_row(b):
    i31 = b["item31"]
    direct = _clearance_contrast_question(3, i31.get("clearance_contrasts", []))
    if direct:
        return direct
    if not i31["applies"]:
        return _qrow(3, ST_NA, "No repeat-dose regimen was identified for this study and species.", shown=False)
    ev = [{"rule": "Individual true IV clearance contrast was not run: " + "; ".join(r["reasons"]),
           "data": [], "tables": [{"caption": "Prespecified clearance contrast", "head": ["ID", "Status", "Design source"],
           "rows": [[r.get("id"), r["status"], r.get("design_source") or "not supplied"]]}]}
          for r in i31.get("clearance_contrasts", []) if r.get("status") != "ASSESSED"]
    design = i31.get("repeat_regimens") or []
    if design and not (i31["upstream"] or i31["reported_by_occasion"] or i31["urine_by_occasion"]):
        schedules = {r["interval_h"] for r in design}
        interval = next(iter(schedules)) if len(schedules) == 1 else None
        drugs = {r["drug"] for r in design}
        drug = next(iter(drugs)) if len(drugs) == 1 else ""
        subject = drug[:1].upper() + drug[1:] if drug and drug.upper() not in ("NOT_FOUND", "NOT_REPORTED") else "The study drug"
        timing = f"every {_f(interval)} h" if interval else "on a repeat-dose regimen"
        return _qrow(3, ST_NO, f"{subject} was given {timing}. Matched first- and later-dose plasma profiles are unavailable, so a change in clearance cannot be assessed.",
                     evidence=[{"rule": "Item 31. The study regimen establishes repeated dosing.", "data": [],
                                "tables": [{"caption": "Source regimen", "head": ["Source", "As reported"],
                                            "rows": [[r["source_ref"], r["as_reported"]] for r in design]}]}])
    if i31["urine_by_occasion"]:
        ev.append({"rule": "Urine by occasion from EM-5a (item 31). A later day can include carryover from earlier doses.", "data": sorted({u["dataset_id"] for u in i31["urine_by_occasion"]}),
                   "tables": [{"caption": "Urine by occasion", "head": ["Dataset", "Component", "Values"],
                               "rows": [[u["dataset_id"], u["component"], "; ".join(f"{o.replace('_', ' ').lower()}: {_f(v)} {un}" for o, v, un in u["values"])] for u in i31["urine_by_occasion"]]}]})
    if i31["reported_by_occasion"]:
        head, rows = _occasion_table(i31)
        ev.append({"rule": "Source-reported values by occasion (EM-R).", "data": sorted({p["dataset_id"] for p in i31["reported_by_occasion"]}),
                   "tables": [{"caption": "Reported by occasion", "head": head, "rows": rows}] if i31["upstream"] else []})
    reach = ("The measured change is kept apart from its cause: " + " or ".join(i31["alternatives"]) + ".") if i31["alternatives"] else ""
    up = i31["upstream"]
    if up:
        u0 = up[0]
        tested = [u for u in up if u.get("t9") in FORMAL_RESULTS]
        st = ST_YES if tested and all(not LIMITED_TEST_FLAGS.intersection(u.get("flags") or []) for u in tested) else ST_PART
        prim = _prim(u0.get("panel"), "E1" if "absorption" in u0["source"] else "DIS-4c", 3, f"Upstream · {u0['source']}", "—")
        return _qrow(3, st, f"Upstream occasion comparison ({u0['source']}): {str(u0.get('t9') or 'not assessed').replace('_', ' ').lower()}.", "", reach,
                     [], prim, [_view("E2", u0["panel2"], "E2")] if u0.get("panel2") else [], ev)
    if i31["reported_by_occasion"]:
        obs = "The source reports plasma parameters by dosing day." if all(
            p["matrix"].lower() in ("plasma", "serum", "blood") for p in i31["reported_by_occasion"]) else "The source reports parameters by dosing day."
        if any(p.get("unit_conflict") for p in i31["reported_by_occasion"]):
            reach = "Verify the AUC unit and integration window in the original study before comparing exposure. A change in clearance remains unresolved."
        else:
            reach = "A clearance change remains unresolved without comparable concentration profiles."
        shows = "Shows the parameters and units reported for each dosing day."
        acc = i31.get("reported_accumulation") or {}
        if acc.get("rows"):
            r0 = acc["rows"][0]
            name = lambda r: "t½" if r["param"] == "THALF" else re.sub(r"\s+", " ", r["label"]).strip()   # noqa: E731
            expo = [r for r in acc["rows"] if r["param"] != "THALF"]
            th = next((r for r in acc["rows"] if r["param"] == "THALF"), None)
            obs = (f"The source reports plasma parameters on day {r0['first_day']} and day {r0['last_day']}"
                   + (f" of dosing every {acc['interval_h']:g} h" if acc.get("interval_h") else "") + (f" ({acc['condition']})" if acc.get("condition") else "") + ".")
            if expo:
                obs += f" Day {r0['last_day']} over day {r0['first_day']}: " + "; ".join(
                    f"{name(r)} {r['ratio']:.2f}× ({_f(r['first'])} → {_f(r['last'])} {r['unit']})" for r in expo) + "."
            if th:
                obs += f" The reported {th.get('half_life_phase') or 'unspecified-phase'} t½ was {_f(th['first'])} {th['unit']} on day {th['first_day']} and {_f(th['last'])} {th['unit']} on day {th['last_day']} ({th['ratio']:.2f}×)."
            idx = acc.get("index")
            if idx:
                obs += (f" For an idealized instantaneous-input, single-exponential steady-state reference with these half-lives and a {idx['tau_h']:g} h interval, "
                        f"1/(1 − 2^(−τ/t½)) is approximately {idx['range'][0]:.2f}–{idx['range'][1]:.2f}. "
                        "This assumption-bounded reference is not a prediction for oral Cmax or the measured AUC window, and its difference from the reported ratios is not a mechanistic test.")
            reach = ("The measured change is kept apart from its cause: " + " or ".join(i31["alternatives"]) + ". ") if i31["alternatives"] else ""
            if th and dist.BAND[0] <= th["ratio"] <= dist.BAND[1]:
                reach += "The two reported half-lives are similar on a descriptive 0.80–1.25 band; this is not an equivalence test and does not establish unchanged clearance. "
            if acc.get("dose_resolved") is False:
                reach += "The source explicitly identifies the same dose regimen across occasions, but its absolute dose conflicts and remains quarantined; these raw ratios are not dose-normalized. "
            reach += "Values are group summaries as printed, with no uncertainty interval; a clearance change remains unresolved without comparable concentration profiles."
            ev.append({"rule": "Later-day over first-day ratio of the same source-reported parameter (item 31); the accumulation index is a reference under one "
                               "exponential decline, not a test.", "data": sorted({d for r in acc["rows"] for d in r["datasets"]}),
                       "tables": [{"caption": "Reported exposure by dosing day", "head": ["Parameter", f"Day {r0['first_day']}", f"Day {r0['last_day']}", "Unit", "Later / first", "n"],
                                   "rows": [[name(r), _f(r["first"]), _f(r["last"]), r["unit"], f"{r['ratio']:.2f}", str(r.get("n_note") or "—")] for r in acc["rows"]]}]
                       + ([{"caption": "Reference accumulation index", "head": ["Formula", "τ (h)", "t½ (h)", "Index", "Reading"],
                            "rows": [[idx["formula"], f"{idx['tau_h']:g}", f"{_f(idx['thalf_h'][0])}, {_f(idx['thalf_h'][1])}", f"{idx['range'][0]:.2f}–{idx['range'][1]:.2f}", acc["reading"]]]}] if idx else [])})
            head, rows = _occasion_table(i31)
            primary = _rowprim(3, head, rows, "Values by dosing day", "as reported") if rows else None
            if primary:
                primary["lines"][2] = shows
            miss = ["matched plasma profiles on the first and a later occasion"]
            if acc.get("dose_resolved") is False:
                miss.append("the dose of the repeated regimen (not resolved in the source table; see its notes)")
            q = _qrow(3, ST_PART, obs, "", reach, miss, primary, [], ev)
            q["reported_accumulation"] = acc
            return q
    else:
        head = ["Occasion", "Urinary component", "Recovery"]
        rows = [[o.replace("_", " ").lower(), u["component"], f"{_f(v)} {un}"] for u in i31["urine_by_occasion"] for o, v, un in u["values"]]
        obs = "Urinary recovery is reported by dosing day." if rows else "Comparable measurements by dosing day are unavailable."
        shows = "Shows the urinary components measured on each dosing day."
    primary = _rowprim(3, head, rows, "Values by dosing day", "as reported") if rows else None
    if primary:
        primary["lines"][2] = shows
    return _qrow(3, ST_PART if rows else ST_NO, obs, "", reach, ["matched plasma profiles on the first and a later occasion"],
                 primary, [], ev)


def _ru_text(u):
    occ = u["occasion"].replace("_", " ").lower()
    occ = "" if u["occasion"] == "FIRST_DOSE" or occ in str(u["group"]).lower() else f", {occ}"
    head = f"{_f(u['r_u'])}%"
    den = ("the " if u["denominator"].startswith("administered") else "") + u["denominator"]
    return f"{_short(u['group'], 28)}{occ}, {u['window_label']}: {head} of {den} recovered as {u['trace']}"


def _q5_observations(b):
    urine = [u for u in b["urine"] if u.get("r_u") is not None]
    parent = [u for u in urine if u["analyte"] == "PARENT"]
    other = [u for u in urine if u["analyte"] != "PARENT"]
    rep = [p for p in b["reported"] if p["param"] in ("FE", "CLR", "CLNR")]
    level = "; ".join(sorted({_lvl(u["level"]) for u in urine})) or "—"
    figs = b["figs"]
    ev, views, missing = [], [], []
    if urine:
        ev.append({"rule": "Item 33: cumulative amount from contiguous quantified increments; a printed total is reconciled, never added; missing intervals stay missing.",
                   "data": sorted({u["dataset_id"] for u in urine}),
                   "tables": [{"caption": "Urine series", "head": ["Group", "Trace", "Occasion", "Collected (h)", "r_U (% of dose)", "Lower limit", "Last increment", "Assay", "Flags"],
                               "rows": [[u["group"], u["trace"], u["occasion"].replace("_", " ").lower(), u["window_label"], _f(u["r_u"]),
                                         _f(u["recovery_lower"]) if u.get("recovery_lower") is not None else (u.get("fe_lower_reason") or "—"),
                                         (f"{_f(100 * u['late_increment']['share'])} % of total" if u.get("late_increment") else "—"),
                                         u["assay"].replace("_", " ").lower(), _words(u["flags"])] for u in urine]}]})
    clr = [c for c in b["clr"]]
    if clr:
        ev.append({"rule": "Interval CLR = ΔAe/ÂUC over the same interval from matched plasma; a partial plasma window is a labelled proxy. T10 needs a sourced GFR and fu,p.",
                   "data": [], "tables": [{"caption": "EM-5c rows", "head": ["Urine interval (h)", "Plasma", "Plasma window (h)", "CLR (mL/min/kg)", "Kind", "T10", "Caveats"],
                                           "rows": [[" – ".join(_f(x) for x in c["urine_interval"]), c["plasma_label"], " – ".join(_f(x) for x in (c["plasma_window"] or [])) or "—",
                                                     _f(c.get("clr_ml_min_kg")), c["kind"].replace("_", " ").lower(), ((c.get("t10") or {}).get("status") or "—").replace("_", " ").lower(),
                                                     _words(c["caveats"])] for c in clr]}]})
    if rep:
        ev.append({"rule": "EM-R: source-reported renal values, never substituted for EM-5a (E0.12).", "data": sorted({p["dataset_id"] for p in rep}),
                   "tables": [{"caption": "Reported", "head": REP_HEAD, "rows": _rep_rows(rep)}]})
    for k, f in figs.items():
        if k.startswith("EM5c|"):
            views.append(_view("EM-5c", f, "interval CLR", 2))
    em5a = [(k, f) for k, f in figs.items() if k.startswith("EM5a|")]
    for k, f in em5a[1:]:
        views.append(_view("EM-5a", f, k.split("|", 1)[1]))
    prim = None
    if em5a:
        key, file = em5a[0]
        plotted = next((u for u in parent + other if u["dataset_id"] == key.split("|", 1)[1]), None)
        if plotted:
            prim = _prim(file, "EM-5a", 5, "EM-5a · " + _ru_text(plotted), level)
    elif urine:
        prim = _rowprim(5, ["Group or occasion", "Measured material", "Collection", "Recovery (%)", "Denominator"],
                        [[u["group"], u["trace"], u["window_label"], _f(u["r_u"]), u["denominator"]] for u in urine],
                        "Observed urinary recovery", level)
    if parent:
        txt = "; ".join(_ru_text(u) for u in parent[:3]) + ("; more groups in the evidence" if len(parent) > 3 else "")
        basis = ("Later collections may include material from earlier doses." if any("CARRYOVER_POSSIBLE" in u["flags"] for u in parent) else "")
        conf = [u for u in parent if "SOURCE_CONFLICT" in u["flags"]]
        if conf:
            basis += f" The source gives conflicting values for {', '.join(_short(u['group'], 20) for u in conf)}; the table value is shown and flagged."
        if any("LATE_INCREMENT_SMALL" in u["flags"] for u in parent):
            basis += " The final interval contributed a small fraction of the collected amount."
        cl = [c for c in clr if c.get("clr") is not None and c["kind"] in ("INTERVAL_ESTIMATE", "WINDOW_PROXY")]
        if cl:
            c0 = next((c for c in cl if c["kind"] == "INTERVAL_ESTIMATE"), cl[0])
            t10_result = c0["t10"]
            reach = c0["text"]
            if t10_result.get("filtration_range_l_h_kg") or t10_result["status"] in FORMAL_RESULTS:
                reach += f" Filtration comparison: {t10_result['status'].replace('_', ' ').lower()}. {t10_result['reason']}."
            if t10_result["status"] == "CANNOT_ASSESS":
                missing.append(t10_result["reason"])
        elif clr:
            reach = "CLR: " + clr[0]["text"]
            missing.append(clr[0]["text"])
        else:
            reach = "CLR not formed: no matched plasma profile at the same dose, route and occasion."
            missing.append("matched plasma for the urine intervals")
        missing += (["bladder emptying at interval ends"] if any(u["collection"]["bladder_emptying"] == "not reported" for u in parent) else []) + \
                   (["SD or SE for the recovery"] if any(u["dispersion"] == "UNKNOWN" for u in parent) else []) + ["recovery after the last collection"]
        return _qrow(5, ST_PART, txt + ".", basis.strip(), reach, missing, prim, views, ev)
    derived = [(c, r) for c in b["components"] if c["excretum"] == "URINE"
               for r in c["components"] if r["kind"] == "PARENT" and r["dose_share"] is not None]
    if derived:
        c, r = derived[0]
        table = _rowprim(5, ["Source", "Group", "Collection", "Parent share (source basis)", "Parent recovered (% dose)"],
                         [[c["dataset_id"], c["group"], c["interval_text"], f"{_f(r['share'])} {c['reported_basis']}", _f(r["dose_share"])]
                          for c, r in derived], "Urinary parent recovery from component data", "Source-reported groups")
        return _qrow(5, ST_PART,
                     f"{c['group']} ({c['interval_text']}): the component table gives {_f(r['dose_share'])}% of dose as urinary parent.",
                     "The table lists groups with a compatible dose denominator. Q7 gives the component measurements.",
                     "Interval renal clearance requires matching plasma exposure.", ["matched parent plasma exposure"], table, [], ev)
    if other:
        txt = "; ".join(_ru_text(u) for u in other[:3])
        return _qrow(5, ST_PART, txt + ".", "The unchanged-parent fraction is unresolved.", "",
                     ["unchanged parent in urine by a specific assay"], prim, views, ev)
    if any(c["excretum"] == "URINE" for c in b["components"]):
        return _qrow(5, ST_NO, "Urinary components were measured (Q7). A matched interval series for unchanged drug is unavailable.",
                     "", "", ["urinary amounts of unchanged drug over defined collection intervals"], None, [], ev)
    if rep:
        return _qrow(5, ST_PART, "Only source-reported values: " + "; ".join(f"{p['name']} {p['raw']}" for p in rep[:3]) + ".", "A parameter-only answer is at most partly answerable (E0.12).", "",
                     ["urine amounts by collection interval"], _rowprim(5, REP_HEAD, _rep_rows(rep[:6]), "EM-R · source-reported", "as reported"), [], ev)
    return _qrow(5, ST_NO, "No urine data for this study and species: urinary recovery unknown.", "", "", ["unchanged parent in urine as amounts, or concentration with volume"], None, [], ev)


def q5_row(b):
    row = _q5_observations(b)
    measured = [u for u in b["urine"] if u.get("r_u") is not None]
    conflicts = [u for u in b["urine"] if "SOURCE_CONFLICT" in u["flags"]]
    if conflicts:
        rows = [[u["dataset_id"], u["group"], kind, " – ".join(_f(x) for x in (m["interval"] or [])) or "not stated",
                 m["raw"], u["denominator"], m.get("source_ref") or m["record_id"]]
                for u in conflicts for key, kind in (("intervals", "reported increment"), ("printed_totals", "reported cumulative / total"))
                for m in u[key]]
        row["evidence"].append({"rule": "Conflicting source cells are retained separately; no conflicting totals are averaged or added.",
                                "data": sorted({u["dataset_id"] for u in conflicts}),
                                "tables": [{"caption": "Urinary recovery source conflicts", "head": ["Dataset", "Group", "Basis", "Window (h)", "As printed", "Denominator", "Source"], "rows": rows}]})
        if not measured:
            row.update(status=ST_PART, status_code=ST_CODE[ST_PART],
                       observed="Source-reported urinary recoveries conflict; a single collected recovery is unresolved.",
                       basis="All reported values and collection windows remain in the evidence table.")
            row["text"] = " ".join(row[k] for k in ("observed", "basis", "reach") if row[k])
    parent_components = [c for c in b["components"] if c["excretum"] == "URINE"
                         and any(r["kind"] == "PARENT" and r["dose_share"] is not None for r in c["components"])]
    recovery = "UNAVAILABLE"
    if any(u["analyte"] == "PARENT" for u in measured):
        recovery = "OBSERVED_PARENT"
    elif parent_components:
        recovery = "DERIVED_PARENT_SHARE"
    elif measured:
        recovery = "OTHER_MEASURED_MATERIAL"
    elif any(p["param"] == "FE" for p in b["reported"]):
        recovery = "SOURCE_REPORTED_ONLY"
    clr = [c for c in b["clr"] if c.get("clr") is not None and c["kind"] in ("INTERVAL_ESTIMATE", "WINDOW_PROXY")]
    renal = "UNAVAILABLE"
    if any(c["kind"] == "INTERVAL_ESTIMATE" for c in clr):
        renal = "MATCHED_INTERVAL_ESTIMATE"
    elif clr:
        renal = "PARTIAL_WINDOW_PROXY_ONLY"
    elif any(p["param"] == "CLR" for p in b["reported"]):
        renal = "SOURCE_REPORTED_ONLY"
    comparisons = [c["t10"]["status"] for c in clr if c.get("t10")]
    results = sorted({status for status in comparisons if status in FORMAL_RESULTS})
    row["evidence_levels"] = {
        "urinary_recovery": {"status": recovery, "measured_traces": sorted({u["trace"] for u in measured}),
                             "datasets": sorted({u["dataset_id"] for u in measured} | {c["dataset_id"] for c in parent_components})},
        "interval_clr": {"status": renal},
        "filtration": {"status": "ASSESSED" if results else "CANNOT_ASSESS", "test_results": results},
    }
    contrast = b.get("renal_filtration_comparison")
    if contrast:
        row["evidence_levels"]["animal_filtration_comparison"] = contrast["status"]
        if contrast["status"] == "TESTED":
            ci = contrast["median_ci"]
            uncertainty = (f"median interval {_f(ci[0])}–{_f(ci[1])}" if ci else
                           "too few animals for a bounded 95% median interval")
            reading = (f"Renal clearance divided by matched filtration had a median of {_f(contrast['median_ratio'])} "
                       f"in {contrast['n_animals']} animals ({uncertainty}, two-sided sign test p = {contrast['p']:.3g}).")
            row["reach"] = (row["reach"] + " " + reading).strip()
            row["text"] = " ".join(row[k] for k in ("observed", "basis", "reach") if row[k])
            row["evidence"].append({"rule": contrast["scope"], "data": [contrast["urine_dataset"], contrast["plasma_dataset"]],
                                    "tables": [{"caption": "Animal-matched renal clearance and filtration",
                                                "head": ["Animal", "Renal clearance (mL/min/kg)", "GFR (mL/min/kg)", "Free fraction", "Ratio"],
                                                "rows": [[a["animal_id"], _f(a["clr_ml_min_kg"]), _f(a["gfr_ml_min_kg"]), _f(a["fu_p"]),
                                                          _f(a["ratio"])] for a in contrast["animals"]]}]})
        else:
            row["evidence"].append({"rule": "Animal-level filtration comparison. " + contrast["reason"], "data": [], "tables": []})
    if recovery == "OBSERVED_PARENT" and renal == "MATCHED_INTERVAL_ESTIMATE" and all(
        c["kind"] == "INTERVAL_ESTIMATE" and (c.get("t10") or {}).get("status") in FORMAL_RESULTS for c in b["clr"]
    ):
        row.update(status=ST_YES, status_code=ST_CODE[ST_YES])
    return row


def q6_row(b):
    sets = b["recovery"]
    if not sets:
        if b.get("recovery_design_sources"):
            return _qrow(6, ST_NO, "A recovery collection was reported. Its route amounts and totals are unavailable.",
                         evidence=[{"data": b["recovery_design_sources"], "rule": "Item 34. The source describes a recovery collection.", "tables": []}])
        return _qrow(6, ST_NA, "No recovery design in this study and species.", shown=False)

    sources = sorted({r["dataset_id"] for r in sets})
    rows, evidence_rows, views = [], [], []
    levels = set()
    for rs in sets:
        for r in rs["routes"] + rs["source_totals"]:
            unit = f"Animal {r['animal']}" if r["animal"] is not None else str(r.get("cohort_id") or rs["group"])
            occasion = rs["occasion"].replace("_", " ").capitalize()
            group = unit if unit.lower() == occasion.lower() else f"{unit.capitalize() if unit == 'group mean' else unit} · {occasion.lower()}"
            levels.add(_lvl(r["level"]))
            kind = r.get("kind")
            if kind == "SOURCE_REPORTED_TOTAL":
                material = "Source-reported total"
            elif kind == "COMBINED_ROUTES":
                material = "Source subtotal (" + r["route"].lower().replace("+", " + ") + ")"
            else:
                material = ROUTE_WORD.get(r["route"], r.get("label") or "unspecified").capitalize()
            window = f"{_f(r['interval'][0])}–{_f(r['interval'][1])} h" if r["interval"] else r["interval_text"] or "window not stated"
            rows.append([group, window, material, str(r["raw"]), r["denominator"]])
            if len(sources) > 1:
                rows[-1].append(rs["dataset_id"])
            checks = [c for c in rs["t12_checks"] if c["source_ref"] == r["source_ref"]]
            evidence_rows.append([r["source_ref"], r["label"], rs["conserved_quantity"], r["interval_text"], "; ".join(
                f"{c['check']} · {c['status'].replace('_', ' ').lower()} ({c['level']})" for c in checks)])
        file = b["figs"].get("EM6a|" + rs["key"])
        if file:
            views.append(_view("EM-6a", file, f"{rs['dataset_id']} · {rs['occasion'].replace('_', ' ').lower()} · matched routes"))
    head = ["Animal / group · occasion", "Collection", "Material", "Recovery (%)", "Denominator"]
    primary = _rowprim(6, head + (["Source"] if len(sources) > 1 else []), rows,
                       ", ".join(sources), ", ".join(sorted(levels)))
    evidence = [{"data": sources, "rule": "Item 34. T12 checks the consistency of the reported measurements.",
                 "tables": [{"caption": "Source cells and recovery checks", "head": ["Source cell", "Source label", "Measured quantity", "Source window", "T12"], "rows": evidence_rows}]}]

    routes = {k for rs in sets for k in rs["route_split"]}
    totals = [t for rs in sets for t in rs["source_totals"]]
    if routes == {"URINE"} and not totals:
        materials = {r["analyte"] for rs in sets for r in rs["routes"]}
        quantity = {"TOTAL_RADIOACTIVITY": "radioactivity", "TOTAL": "parent-equivalent material"}.get(
            next(iter(materials)) if len(materials) == 1 else None, "drug-related material")
        observed = f"Only urinary recovery of {quantity} was quantified."
    elif totals:
        if routes == {"CARCASS"} and all(t["kind"] == "SOURCE_REPORTED_TOTAL" for t in totals):
            observed = "Only the carcass measurement and the source-reported total are available."
        else:
            observed = "The table lists the totals and subtotals as reported by the source."
    else:
        observed = "Recovery is reported for " + ", ".join(ROUTE_WORD.get(k, str(k).lower()) for k in sorted(routes, key=str)) + "."
    readings = []
    for rs in sets:
        checks = [c for c in rs["t12_checks"] if c["check"] == "recovery above the dose"]
        label = rs["occasion"].replace("_", " ").capitalize()
        if any(c["status"] in ("POINT_DISCREPANCY", "ABOVE_REVIEW_TOLERANCE") for c in checks):
            readings.append(f"Reconcile the above-dose recovery on {label.lower()} with the dose and assay records.")
            if any(c["level"] == "tolerance unknown" for c in checks):
                readings.append("The review tolerance is unknown.")
        if any(c["status"] == "NOT_APPLICABLE" for c in checks):
            readings.append(f"{label} may include earlier doses, so a single-dose ceiling does not apply.")
    if not readings:
        if totals and any(c["check"] == "printed total against its routes" and c["status"] == "CANNOT_ASSESS"
                          for rs in sets for c in rs["t12_checks"]):
            readings.append("The available measurements cannot establish how the source total divides among routes.")
        elif routes == {"URINE"} and not totals:
            readings.append("These collections leave recovery outside urine unresolved.")
    missing = list(dict.fromkeys(n for rs in sets for n in rs["notes"] if not n.startswith("individual animals:")))
    if any("for urine, faeces (records quarantined at intake)" in n for n in missing):
        missing = [n for n in missing if not n.startswith("route values not available")] + ["Urine and faeces records were withheld at intake."]
    status = ST_YES if all(rs["recovery_urine_faeces"] is not None for rs in sets) else ST_PART
    return _qrow(6, status, observed, reach=" ".join(dict.fromkeys(readings)), missing=missing,
                 primary=primary, views=views, evidence=evidence)


def q7_row(b):
    comps, ivr = b["components"], b["in_vitro"]
    if not comps and not ivr:
        return _qrow(7, ST_NO, "No excreta component measurements or in vitro assay are available for this study and species.")
    evidence, observations, missing = [], [], []
    primary = None
    if comps:
        named = sorted({r["component"] for c in comps for r in c["components"] if r["kind"] == "NAMED_COMPONENT"})
        matrices = ", ".join(sorted({c["excretum"].lower() for c in comps}))
        if named:
            observations.append(f"The source identifies {', '.join(named)} in {matrices}.")
        elif len(comps) == 1 and len(comps[0]["components"]) == 1:
            measurements = comps[0]["components"]
            observations.append(f"Largest measured component in {matrices}: {measurements[0]['component']}.")
        elif all(r["kind"] == "PARENT" for c in comps for r in c["components"]):
            observations.append(f"The parent drug was the only quantified component in the {matrices} profile.")
        else:
            observations.append(f"The measured components in {matrices} are listed on their reported basis.")
        rows = []
        for c in comps:
            group = {"mean": "Reported mean", "overall": "Reported overall"}.get(c["group"].lower(), c["group"])
            for r in c["components"]:
                kind = {"PARENT": "Parent drug", "NAMED_COMPONENT": "Identified product",
                        "UNRESOLVED_COMPONENT": "Unidentified component"}.get(r["kind"], _words([r["kind"]]))
                share = _f(r["share"])
                if r.get("sd") is not None:
                    share += " ± " + _f(r["sd"])
                rows.append([group, c["interval_text"] or "not reported", c["excretum"].lower(), r["component"], kind,
                             f"{share} {c['reported_basis']}", _f(r["dose_share"], 4) if r["dose_share"] is not None else "—"])
        primary = _rowprim(7, ["Animal or group", "Collection window", "Matrix", "Component", "Identity",
                               "Share on reported basis", "Dose share (%)"], rows, "Excreta component measurements", "As reported")
        evidence.append({"rule": "A dose share requires a common recovery basis and collection window. Reported means and totals are retained as printed.",
                         "data": sorted({c["dataset_id"] for c in comps}),
                         "tables": [{"caption": "Dose conversion and reconciliation", "head": ["Dataset", "Group", "Recovery (% dose)", "Component sum", "Check", "Conversion limit"],
                                     "rows": [[c["dataset_id"], c["group"], _f(c.get("excretum_recovery_pct_dose")), _f(c["sum_check"]["sum"]),
                                               c["sum_check"]["status"], c.get("conversion_blocked") or "—"] for c in comps]}]})
        reach = ("Formation in vivo or after collection remains open." if named else "Product identity remains unresolved.")
        if any("WINDOW_DIFFERS_BY_ANALYTE" in r["flags"] for c in comps for r in c["components"]):
            reach += " The profiling and total-recovery windows differ, so a dose share cannot be calculated for those samples."
        missing.append("stability and controls for product origin" if named else "identified products in the same collection")
    else:
        reach = ""
    eligible = [r for r in ivr if not r["excluded_reason"] and r["state"] == "QUANTIFIED" and r["value"] is not None]
    if ivr:
        def assay_row(r):
            readout = READOUT_WORD[r["readout"]]
            if r.get("time_min") is not None:
                readout += f" ({_f(r['time_min'])} min)"
            return [r["system"], r["drug"], readout, r["raw"], r["unit"]]
        head = ["Assay system", "Substrate", "Readout", "As printed", "Unit"]
        for r in eligible:
            if r["readout"] in ("HALF_LIFE", "VMAX_KM"):
                observations.append(f"In {r['system']}, {READOUT_WORD[r['readout']]} was {r['raw']} {r['unit']}.")
        if not observations:
            observations.append("In vitro measurements are available for this species." if eligible else
                                "The reported in vitro measurements are ineligible for comparison.")
        if primary is None and eligible:
            primary = _rowprim(7, head, [assay_row(r) for r in eligible], "Assay results for this species", "In vitro")
        evidence.append({"rule": "Comparison uses measurements on the same assay basis. Source records retain excluded and comparator rows.",
                         "data": sorted({r["dataset_id"] for r in ivr}),
                         "tables": [{"caption": "Source assay records", "head": head + ["Source cell", "Exclusion"],
                                     "rows": [assay_row(r) + [r["row_id"], r["excluded_reason"] or "—"] for r in ivr]}]})
        if eligible:
            reach = (reach + " " if reach else "") + "These measurements describe the assay system; its contribution to in vivo clearance remains unresolved."
    q = _qrow(7, ST_PART if comps or eligible else ST_NO, " ".join(observations), "", reach, missing, primary, [], evidence)
    q["comparison_keys"] = [g["key"] for g in b["em7b"] if g["drawn"] and any(r["species"] == b["species"] for r in g["rows"])]
    return q


def board_questions(b):
    return [q1_row(b), q2_row(b), q3_row(b), q5_row(b), q6_row(b), q7_row(b)]


def _plasma_priority(study, profile):
    anchor = f"{study} / {profile['dataset_id']}"
    flags = {f["operation"] for f in profile.get("source_restrictions", [])}
    if "TIME_AXIS_SELECTION" in flags:
        return ("The calculated area depends on which sampling times can be used.",
                f"{anchor}: reconcile the plotted sample times with the study protocol and establish the time axis for this profile before assessing late sampling.")
    if "PK_MODELING" in flags or "NCA" in flags:
        return ("The source restricts the use of this profile.",
                f"{anchor}: resolve the recorded source restriction before using the observed exposure for modeling.")
    if "unverified" in profile.get("measurement_basis", ""):
        return ("The identity of the parent-drug signal is unresolved.",
                f"{anchor}: verify which analyte the assay measured before using the dose-to-observed-AUC ratio.")
    return ("Exposure outside the observed window is uncertain.",
            f"{anchor}: check early and late coverage against the sampling schedule before interpreting the ratio.")


def board_hypothesis(b):
    """Working hypothesis H (E0.9): one observation, one alternative still consistent with it, one next test."""
    urine = [u for u in b["urine"] if u.get("r_u") is not None and u["occasion"] in ("FIRST_DOSE", "DAY_1")]
    parent = [u for u in urine if u["analyte"] == "PARENT"]
    ok = [r for r in b["item29"] if r["window_proxy"]]
    clr = [c for c in b["clr"] if c.get("clr") is not None and c["kind"] in ("WINDOW_PROXY", "INTERVAL_ESTIMATE")]
    h = {"text": "", "observation": "", "alternative": "", "next_test": "", "rests_on": "", "missing": [], "check_first": [], "source_ids": [],
         "kind": "working hypothesis (review pending)"}
    if parent:
        u = parent[0]
        clr = [c for c in clr if c["urine_key"] == u["key"]]
        den = ("the " if u["denominator"].startswith("administered") else "") + u["denominator"]
        h["observation"] = f"{_f(u['r_u'])} % of {den} was collected in urine as {u['trace']} by {_f(u['collection_end_h'])} h ({_short(u['group'], 24)})."
        h["alternative"] = "The remaining dose could leave by non-renal elimination, later urinary excretion or be lost in collection; the data do not apportion it."
        if clr and any(c["kind"] == "WINDOW_PROXY" for c in clr):
            h["next_test"] = ("Plasma was sampled for only the first part of the urine collection. Matched plasma samples through the end of the collection would allow "
                              "interval renal clearance to be estimated.")
        elif not clr:
            h["next_test"] = "Measure parent plasma exposure across the same urine intervals and verify collection completeness before estimating renal clearance."
        else:
            h["next_test"] = "Check the joint uncertainty of renal clearance, matched GFR and fu,p before testing filtration."
        h["rests_on"] = f"Rests on: EM-5a ({u['dataset_id']})" + (f" and EM-5c ({len(clr)} interval value{'s' if len(clr) > 1 else ''})" if clr else "") + "."
        h["source_ids"] = sorted({u["dataset_id"]} | {c["sid"] for c in clr})
        if "SOURCE_CONFLICT" in u["flags"]:
            h["check_first"].append("source conflict on the urinary value")
    elif any(u["analyte"] == "ACTIVE_MATERIAL" for u in urine):
        u = next(u for u in urine if u["analyte"] == "ACTIVE_MATERIAL")
        h["observation"] = f"The urine bioassay measured {_f(u['r_u'])}% of the {u['denominator']} as active material by {_f(u['collection_end_h'])} h."
        h["alternative"] = "The assay cannot distinguish intact drug from other material that retains antimicrobial activity."
        h["next_test"] = "Measure intact drug in paired urine and plasma over the same collection interval."
        h["rests_on"] = f"Urine bioassay ({u['dataset_id']}, {u['window_label']})."
        h["source_ids"] = [u["dataset_id"], *[r["source_ref"] for r in u["intervals"] + u["printed_totals"]]]
        if "SOURCE_CONFLICT" in u["flags"]:
            h["check_first"].append("source conflict on the urinary value")
    elif ok:
        r = next((r for r in ok if r["route"] == "IV"), ok[0])
        h["observation"] = r["value_row"]
        h["alternative"], h["next_test"] = _plasma_priority(b["study"], r)
        h["rests_on"] = f"Rests on: EM-1a under {r['upstream_panel']['panel'] if r.get('upstream_panel') else 'the value row'} ({r['dataset_id']})."
        h["source_ids"] = [r["sid"]]
        if "REPORTED_CL_ABOVE_WINDOW" in r["caveats"]:
            h["check_first"].append("source-reported CL above the window value")
    elif b["recovery"]:
        r = b["recovery"][0]
        bits = "; ".join(f"{ROUTE_WORD.get(k, k.lower())} {', '.join(_f(x) for x in v)} %" for k, v in r["route_split"].items())
        tot = ", ".join(_f(t["value"]) for t in r["source_totals"])
        h["observation"] = (f"Recovery of {r['conserved_quantity']} ({r['group']}): " + (bits or "no route values") + (f"; printed total {tot} %" if tot else "")
                            + f" of {r['denominator']}.")
        h["alternative"] = ("The printed total is compatible with multiple allocations between the missing routes." if tot and not {"URINE", "FAECES"} <= set(r["route_split"])
                            else "The unaccounted part could be later excretion, unmeasured routes or retained material.")
        h["next_test"] = "Urine and faecal values for the same cohort and window." if "FAECES" not in r["route_split"] else "Later collections to close the balance."
        h["rests_on"] = f"Q6 recovery table ({r['dataset_id']})."
        h["source_ids"] = [r["dataset_id"]] + [x["source_ref"] for x in r["source_totals"] + r["routes"]]
    elif b["components"]:
        c = b["components"][0]
        largest = c["largest_product"] or c["largest"]
        h["observation"] = f"{largest['component']} accounted for {_f(largest['share'])} {c['reported_basis']} in {c['excretum'].lower()} ({c['group']})."
        h["alternative"] = "The timing and site of product formation remain open." if c["largest_product"] else "The remaining material may contain unresolved components."
        h["next_test"] = "Stability controls of the collected samples."
        h["rests_on"] = f"Source component table: {c['dataset_id']}."
        h["source_ids"] = [c["dataset_id"], largest["source_ref"]]
    elif b["in_vitro"]:
        eligible = [r for r in b["in_vitro"] if not r["excluded_reason"] and r["value"] is not None]
        r = next((r for r in eligible if r["readout"] == "VMAX_KM"), eligible[0] if eligible else b["in_vitro"][0])
        if eligible:
            h["observation"] = f"{r['system']} yielded {READOUT_WORD[r['readout']]} of {r['raw']} ({r['unit']}) for {r['drug']}."
            h["alternative"] = "The measured activity may depend on assay conditions and may contribute differently to clearance in vivo."
        else:
            h["observation"] = f"The in vitro readout is unavailable for comparison ({r['excluded_reason'] or r['state']})."
        h["next_test"] = "Compare the assay result with matched in vivo exposure and excretion data."
        h["rests_on"] = f"Source assay {r['row_id']}."
        h["source_ids"] = [r["row_id"]]
    elif b["reported"]:
        p = b["reported"][0]
        h["observation"] = f"The source reports {p['name']} of {_reported_value_text(p)}."
        study_dose_text = _study_dose_text(p.get("dose_context", {}))
        if study_dose_text:
            h["observation"] += f" {study_dose_text}. The source gives no dose-specific estimate."
        h["alternative"] = "The reported value depends on a method and window that cannot be checked here."
        h["next_test"] = "The underlying concentration-time or urine data."
        h["rests_on"] = f"Rests on: EM-R ({p['dataset_id']})."
        h["source_ids"] = [p["dataset_id"], p["record_id"]]
    elif b["item29"]:
        r = b["item29"][0]
        h["observation"] = f"Plasma observations are available. The window calculation was withheld: {r['not_assessable_reason']}."
        h["next_test"] = "Review the cited profile, including quantified sampling times and the experimental unit."
        og = next((x["ongoing_input"] for x in b["item29"] if x.get("ongoing_input") and x["ongoing_input"]["sample_variation"] == "WITHIN_BAND"), None)
        if og:
            h["observation"] += " " + _ongoing_text(og)
            h["alternative"] = "The concentrations may still be approaching steady state, so rate over concentration can sit above or below CL."
            h["next_test"] = "Samples after the infusion stops, or a justified steady-state assessment, to separate steady state from approach to it."
        h["rests_on"] = f"Plasma profile {r['sid']}."
        h["source_ids"] = [x["sid"] for x in b["item29"]]
    else:
        h["observation"] = "No elimination data for this study and species."
        h["next_test"] = "Plasma after a known dose, or urine amounts by interval."
    h["text"] = " ".join(x for x in (h["observation"], ("Alternative: " + h["alternative"]) if h["alternative"] else "", ("Next: " + h["next_test"]) if h["next_test"] else "") if x)
    h["reach"] = "A working hypothesis for review, not a mechanism."
    h["missing"] = [m for q in b["questions"] for m in q["missing"]][:3]
    return h


def handoff_records(b):
    """E0.9 quantities with their analytical target, source observations and admissible use."""
    recs = []
    statuses = {q["q"]: q["status_code"] for q in b["questions"]}

    def rec(item, question, quantity, value, units, refs, **kw):
        record = {"item_id": item, "question_id": f"Q{question}", "quantity": quantity, "value_or_limits": value, "units": units,
                  "analysis_unit": None, "analyte": None, "matrix": None, "route": None, "dose_basis": None, "time_window": None,
                  "estimate_or_bound": None, "limit_direction": "none", "evidence_kind": None, "answer_status": statuses.get(question),
                  "test_id_and_status": None, "source_refs": list(dict.fromkeys(x for x in refs if x)), "caveats": [], "missing": [], "next_step": None}
        record.update(kw)
        recs.append(record)

    for r in b["item29"]:
        common = dict(analysis_unit=r["analysis_unit"], analyte=r.get("analyte", "PARENT"), matrix=r["matrix"], route=r["route"],
                      dose_basis=r["dose_basis"], dose_mg_per_kg=r["dose_mg_per_kg"], source_restrictions=r.get("source_restrictions", []),
                      source_analyte=r.get("source_analyte"), source_dose_basis=r.get("source_dose_basis"), assay=r["assay"],
                      measurement_basis=r["measurement_basis"], interpretation_target=r["full_exposure_target"])
        formed = r["window_proxy"] is not None
        profile_refs = [r["sid"], *r.get("auc_record_ids", [])]
        comparison = {}
        if r.get("reported_cl_candidates"):
            comparison["reported_cl_candidates"] = [
                {key: c[key] for key in ("dataset_id", "source_cell", "record_id", "raw", "unit", "status", "issues", "citations")}
                for c in r["reported_cl_candidates"]]
            comparison["reported_cl_check"] = r["reported_cl_check"]
        rec(29, 1, "dose_over_observed_auc", r["window_proxy"], "L/h/kg", profile_refs, **common,
            time_window=r["auc_window_h"], estimate_or_bound="window proxy" if formed else None, **comparison,
            evidence_kind="observed window (A0.6)" if formed else "withheld", caveats=r["caveats"],
            missing=[r["not_assessable_reason"]] if r["not_assessable_reason"] else [],
            next_step=_plasma_priority(b["study"], r)[1] if formed else None)
        for x in r["sensitivity_rows"]:
            rec(29, 1, x["quantity"], x["value"], "L/h/kg", profile_refs, **common, time_window=x.get("window"),
                estimate_or_bound="conditional upper limit (sensitivity only)", limit_direction="upper",
                evidence_kind=x["kind"], caveats=[x["assumption"]])

    for u in b["item30"]["upstream"]:
        rec(30, 2, "upstream dose-normalized AUC ratio", u.get("auc_ratio"), "ratio", [u["source"], u.get("key")],
            route=u["route"], time_window=u["window_h"], evidence_kind="upstream dose comparison",
            test_id_and_status={"T3": u["t3"], "T3p": u["t3p"]}, caveats=u.get("caveats", []),
            dose_levels_mg_per_kg=u["doses"], exposure_by_dose=u.get("exposure"), comparison_pattern=u.get("pattern"),
            candidate_alternatives=b["item30"]["alternatives"], next_step=b["item30"]["next_discriminator"])
    for series in b["item30"].get("reported_auc", []):
        rec(30, 2, "source-reported AUC per dose", series["rows"], series["unit"],
            [ref for row in series["rows"] for ref in row["refs"]], evidence_kind=series["basis"], route=series["route"],
            assay=series["assay"], analyte=series["source_analyte"], analysis_unit=series["record_level"], time_window=series["window"],
            source_restrictions=series["source_restrictions"], estimate_or_bound="descriptive", test_id_and_status="no independent test",
            next_step="obtain matched profiles and uncertainty at the reported doses")
    for u in b["item31"]["upstream"]:
        rec(31, 3, "upstream occasion comparison", u.get("rows"), "see upstream record",
            [u["source"], u.get("first"), u.get("later")], evidence_kind="upstream occasion comparison",
            test_id_and_status=u["t9"], caveats=u.get("flags") or [], candidate_alternatives=b["item31"]["alternatives"])
    for p in b["reported"]:
        dose_context = p.get("dose_context") or {}
        refs = [p["dataset_id"], p.get("source_cell") or p["record_id"], *dose_context.get("source_refs", []), p.get("dispersion_ref")]
        regimen = {"repeat_regimen": p["repeat_regimen"]} if p.get("repeat_regimen") else {}
        if regimen:
            refs.append(p["repeat_regimen"]["source_ref"])
        if p["param"] == "AUC":
            unresolved = p["as_printed_only"] or p["unit"] == "unit unresolved"
            rec(31, 3, "source-reported AUC", p["value"], None if unresolved else p["unit"], refs + p["unit_source_refs"],
                analysis_unit="source-reported", matrix=p["matrix"], analyte=p["analyte"], route=p["route"],
                dose_mg_per_kg=p.get("dose"), dose_context=dose_context, **regimen,
                occasion=p["occasion"], raw=p["raw"], table_unit=p["table_unit"], text_units=p["text_units"],
                dispersion_type=p["dispersion_type"], n=p["n_note"], source_restrictions=p["source_restrictions"],
                evidence_kind="reported parameter", estimate_or_bound="as printed", as_printed_only=unresolved,
                caveats=[p["label_flag"]] + (["UNIT_CONFLICT"] if p["unit_conflict"] else []),
                next_step="Verify the AUC unit and integration window in the original study." if unresolved else "Verify the integration window before comparing occasions.")
            continue
        question = 5 if p["param"] in ("FE", "CLR", "CLNR") else 1
        qualifiers = {k: p[k] for k in ("half_life_phase", "phase_meaning", "cell_raw", "component_index", "review_source") if k in p}
        rec(33 if question == 5 else 29, question, p["name"], p["value"], p["unit"], refs + [p.get("review_source")],
            analysis_unit="source-reported", analyte=p["analyte"], matrix=p["matrix"], route=p["route"], dose_mg_per_kg=p["dose"],
            source_label=p["label"], parameter_code=p["param"], route_detail=p.get("route_detail"), n=p.get("n_note"),
            source_restrictions=p.get("source_restrictions", []), **qualifiers, **regimen,
            occasion=p["occasion"], evidence_kind="reported parameter", estimate_or_bound="as printed", raw=p["raw"],
            method=p["method"], dose_context=dose_context, dispersion_value=p.get("sd"), dispersion_type=p.get("dispersion_type"),
            caveats=[p["label_flag"]])

    for u in b["urine"]:
        if u.get("r_u") is None:
            continue
        contributors = u["intervals"] + u["printed_totals"]
        refs = [x.get("source_ref") or x["record_id"] for x in contributors]
        common = dict(analysis_unit=u["level"], group=u["group"], analyte=u["trace"], matrix="urine", route=u["route"],
                      dose_mg_per_kg=u["dose"], dose_basis=u["denominator"], occasion=u["occasion"], pairing=u["collection"]["pairing"],
            assay=u["assay"], assay_source=u["assay_note"], time_window=[0, u["collection_end_h"]] if u["window_label"].startswith("0–") else u["window_label"],
                      caveats=u["flags"])
        rec(33, 5, "cumulative urinary recovery", u["r_u"], "% of " + u["denominator"], refs, **common,
            estimate_or_bound="observed collected amount", evidence_kind="observed", missing=[u["fe_lower_reason"]] if u.get("fe_lower_reason") else [],
            next_step="check parent identity by specific assay" if u["analyte"] == "ACTIVE_MATERIAL" else "check collection completeness and duration")
        if u.get("recovery_lower") is not None:
            rec(33, 5, "lower limit on cumulative urinary recovery", u["recovery_lower"], "% of " + u["denominator"], refs, **common,
                estimate_or_bound=u["recovery_lower_kind"], limit_direction="lower", evidence_kind="statistical bound")
    urine_by_key = {u["key"]: u for u in b["urine"]}
    for c in b["clr"]:
        u = urine_by_key[c["urine_key"]]
        matched = [i for i in u["intervals"] if i["interval"] == c["urine_interval"]]
        t10_result = c.get("t10") or {"status": "CANNOT_ASSESS", "reason": c["text"]}
        rec(33, 5, "CLR", c.get("clr"), "L/h/kg", [c["sid"], *c.get("plasma_source_refs", []), c.get("urine_source_ref"),
            *[i.get("source_ref") or i["record_id"] for i in matched]],
            analysis_unit="ratio of means" if "RATIO_OF_MEANS" in c["caveats"] else c["plasma_level"], analyte="PARENT", matrix="urine / plasma",
            pairing=c["pairing"], urine_series_key=u["key"], dose_mg_per_kg=u["dose"], route=u["route"], dose_basis=u["denominator"],
            time_window={"urine": c["urine_interval"], "plasma": c["plasma_window"]},
            estimate_or_bound={"INTERVAL_ESTIMATE": "interval estimate", "WINDOW_PROXY": "partial-window proxy"}.get(c["kind"], c["kind"].lower()),
            evidence_kind="observed ratio" if c.get("clr") is not None else "withheld", test_id_and_status="T10 " + t10_result["status"],
            caveats=c["caveats"], missing=[t10_result["reason"]] if t10_result["status"] == "CANNOT_ASSESS" else [])

    for r in b["recovery"]:
        for obs in r["routes"] + r["source_totals"]:
            ref = obs.get("source_ref") or obs["record_id"]
            checks = [chk for chk in r.get("t12_checks", []) if chk["source_ref"] == ref]
            rec(34, 6, "reported total recovery" if obs in r["source_totals"] else "route recovery", obs["value"],
                "% of " + obs["denominator"], [r["dataset_id"], ref],
                analysis_unit=r["group"], animal=obs["animal"], occasion=r["occasion"], analyte=r["conserved_quantity"],
                matrix=ROUTE_WORD.get(obs["route"], str(obs["route"]).lower()), time_window=obs["interval"] or obs["interval_text"],
                dose_basis=obs["denominator"], estimate_or_bound="as printed", evidence_kind=obs.get("kind", "observed route"),
                test_id_and_status={"T12": checks}, caveats=r["caveats"], missing=r["notes"])

    for c in b["components"]:
        for component in c["components"]:
            roles = []
            if component == c["largest"]:
                roles.append("largest measured component")
            if component == c.get("largest_product"):
                roles.append("largest identified transformation product")
            rec(35, 7, "measured component share", component["share"], c["reported_basis"],
                [c["dataset_id"], component.get("source_ref") or component["record_id"]], analysis_unit=c["group"],
                analyte=component["component"], analyte_kind=component["kind"], roles=roles, matrix=c["excretum"].lower(),
                time_window=c["interval_text"], occasion=c["occasion"], estimate_or_bound="observed", evidence_kind="component profile",
                share_of_dose_pct=component["dose_share"], excretum_recovery_pct_dose=c["excretum_recovery_pct_dose"],
                caveats=list(dict.fromkeys(c["caveats"] + component["flags"])), missing=[c["conversion_blocked"]] if c["conversion_blocked"] else [])
    cards = {c["dataset_id"]: c for c in b["iv_cards"]}
    for row in b["in_vitro"]:
        if row["excluded_reason"] or row["value"] is None:
            continue
        card = cards[row["dataset_id"]]
        rec(35, 7, READOUT_WORD[row["readout"]], row["value"], row["unit"], [row["row_id"]],
            analysis_unit="in vitro assay", analyte=row["drug"], matrix=row["system"], time_window={"time_min": row["time_min"]} if row["time_min"] is not None else None,
            evidence_kind="observed in vitro readout", unit_basis=row.get("unit_basis"),
            assay_conditions={k: card[k] for k in ("start_concentration", "incubation", "normalization", "controls")},
            caveats=row["flags"], next_step="establish the relation to in vivo disposition before scaling")
    return recs


# ---------------------------------------------------------------- build

EXCRETA_ROLES = ("URINE_EXCRETION", "EXCRETION", "EXCRETA", "MASS_BALANCE", "RECOVERY")
IN_VITRO_ROLES = ("IN_VITRO_CLEARANCE", "IN_VITRO_METABOLISM", "IN_VITRO_STABILITY")


def species_summaries(rows, contrasts):
    out = {}
    for sp in sorted({r["species"] for r in rows}):
        rs = sorted((r for r in rows if r["species"] == sp), key=lambda r: r["study"])
        ur = [(r["study"], u) for r in rs for u in r["urinary_recovery"] if u["trace"] == "unchanged parent"]
        active = [(r["study"], u) for r in rs for u in r["urinary_recovery"] if u["trace"] == "active material (microbiological assay)"]
        assays = [(r["study"], x) for r in rs for x in r["in_vitro"] if x["eligible"]]
        cl = [(r["study"], c) for r in rs for c in r["window_cl"]]
        source_refs = []
        if ur:
            study, u = ur[0]
            source_refs = [u["dataset_id"]]
            obs = f"{study}, {u['group']}: {_f(u['value'])}% of {u['denominator']} collected as unchanged parent ({u['window']})."
            alt = "Later excretion or non-renal elimination of the rest; not apportioned."
            disc = f"{study} / {u['dataset_id']}: verify parent plasma exposure and urine completeness over {u['window']} before estimating interval renal clearance."
        elif active:
            study, u = active[0]
            source_refs = [u["dataset_id"]]
            obs = f"{study}: urinary antibacterial activity corresponds to {_f(u['value'])}% of {u['denominator']} ({u['window']})."
            alt = "The bioassay measures antimicrobial activity. The unchanged-parent contribution is unresolved."
            disc = f"{study} / {u['dataset_id']}: establish parent-specific urinary recovery over {u['window']} with a selective assay."
        elif cl:
            def time_flags(entry):
                return {f["operation"] for f in entry[1]["source_restrictions"]}
            study, c = min(cl, key=lambda e: ("TIME_AXIS_SELECTION" not in time_flags(e),
                                              "PK_MODELING" not in time_flags(e), e[0], e[1]["sid"]))
            source_refs = [c["sid"]]
            obs = c["description"]
            alt, disc = _plasma_priority(study, c)
        elif any(r["reported_cl"] for r in rs):
            study, p = next((r["study"], p) for r in rs for p in r["reported_cl"])
            source_refs = [p["dataset_id"]]
            obs = f"Source-reported clearance only ({p['as_printed']})."
            alt = "Method and window of the source value cannot be checked."
            disc = f"{study} / {p['dataset_id']}: verify the reported clearance definition against the underlying concentration profile."
        elif assays:
            study, x = assays[0]
            source_refs = [x["source_ref"]]
            obs = f"{study}: {x['system']}, {x['readout']} {_f(x['value'])} {x['unit']} (in vitro)."
            alt = "The contribution of this system to clearance in vivo is unresolved."
            disc = f"{study} / {x['dataset_id']}: check for matched in vivo parent exposure and recovery before using the {x['system']} result to explain clearance."
        else:
            study = rs[0]["study"]
            obs, alt = "No quantitative clearance estimate available for this species.", "—"
            disc = f"{study}: check the source for parent plasma after a documented dose or urinary amounts over defined intervals."
        if ur and active:
            other_study, u = active[0]
            obs += f" Separately, {other_study} reports urinary antibacterial activity of {_f(u['value'])}% of {u['denominator']} ({u['window']})."
        out[sp] = {"study": study, "observation": obs, "alternative": alt, "discriminator": disc, "source_refs": source_refs}
    return out


def upstream_dme_followup(distribution_board, board):
    """Keep upstream DME candidates attached to the observation that raised them."""
    followup = []
    binding = distribution_board.get("binding") or {}
    if "NONLINEAR_BINDING" in (binding.get("caveats") or []):
        followup.append({
            "candidate": "concentration-dependent binding", "source": "distribution item 27",
            "observation": "The upstream binding record reports concentration dependence.",
            "source_studies": binding["fu_studies"],
            "source_refs": sorted({x["record_id"] for x in binding["fu_table"] if x.get("record_id")}),
            "caveats": binding["caveats"], "status": "OPEN",
            "next_test": "Compare paired total and unbound concentrations in this study across the observed exposure range.",
        })
    records = distribution_board.get("item24", []) + distribution_board.get("dose_patterns", [])
    for record in records:
        for name in record.get("candidates") or []:
            if not any(term in name.lower() for term in ("binding", "elimination", "recycling", "time-depend")):
                continue
            followup.append({
                "candidate": name, "source": "distribution item 24",
                "source_refs": [record.get("sid") or record.get("key")],
                "observation": record.get("dose_pattern") or record.get("phases_visible"),
                "caveats": record.get("caveats") or [], "status": "OPEN",
                "next_test": ("Compare matched intact and bile-cannulated cohorts with a common input and collection window."
                              if "recycling" in name else board["item30"]["next_discriminator"]),
            })
    return followup




def build(root):
    root = Path(root)
    tables = dist._sorted_tables(root)
    source_tables = {table["dataset_id"]: table for table in tables}
    cfg = load_config(root)
    dcfg = dist.load_config(root)
    out = root / "elimination"
    out.mkdir(exist_ok=True)
    _SPECS.clear()
    previous = set()
    if (out / "plot_specs.json").is_file():
        previous = {f["file"] for f in json.loads((out / "plot_specs.json").read_text(encoding="utf-8")).get("figures", [])}
    previous |= {p.name for p in out.glob("species-*.html")}
    (out / "elimination_config.template.json").write_text(json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=1), encoding="utf-8")
    abs_data, abs_meta = load_upstream(root, "absorption")
    dist_data, dist_meta = load_upstream(root, "distribution")
    abs_idx, _ = absorption_index(abs_data)
    abs_param_ids = set((abs_data or {}).get("reported_parameter_ev_datasets") or [])
    series, ex_cards, obs, iv_cards, iv_rows, reported, scope, skipped = [], {}, [], [], [], [], [], []
    reported_auc = []
    parameter_context = dist.load_parameter_context(root)
    tissue_parameters = []
    for e in tables:
        role = e.get("role")
        try:
            if role == "PK_OBSERVATIONS":
                _, ss = dist.extract(e, dcfg)
                series += ss
            elif role in EXCRETA_ROLES:
                card, o = excreta_dataset(e, cfg)
                ex_cards[card["dataset_id"]] = card
                obs += o
                if not o:
                    skipped.append({"dataset_id": e["dataset_id"], "reason": card["layout_reason"]})
            elif role in IN_VITRO_ROLES:
                card, rows = in_vitro_dataset(e)
                iv_cards.append(card)
                iv_rows += rows
            elif role == "REPORTED_PARAMETERS":
                reviewed = dist.reviewed_parameters(e, parameter_context)
                r, sc = reported_dataset(e, abs_param_ids, reviewed)
                tissue_parameters.extend(x for x in reviewed if x["param"] == "THALF" and x["matrix"] in ("tissue fluid", "interstitial fluid"))
                reported += r
                scope += sc
                reported_auc.extend(_reported_auc_series(e))
        except Exception as exc:  # noqa: BLE001 - one unreadable table must not stop the section
            skipped.append({"dataset_id": e.get("dataset_id"), "reason": f"could not be read: {exc!r}"})
    plasma_all = [s for s in series if s["matrix_class"] in dist.REF_CLASSES]
    dist.write_tissue_parameter_supplement(root / "distribution", tissue_parameters)
    plasma = [s for s in plasma_all if s["analyte"] == "PARENT" and not s["unbound"]]
    dist_boards = {(b["study"], b["species"]): b for b in (dist_data or {}).get("boards", [])}
    d24 = {r["sid"]: r for b in dist_boards.values() for r in b.get("item24", [])}
    em7b = em7b_groups(iv_cards, iv_rows)
    keys = {(s["study"], s["species"]) for s in plasma if s["route_class"] in ("IV", "EV")} | {(o["study"], o["species"]) for o in obs} | \
           {(p["study"], p["species"]) for p in reported} | {(r["study"], r["species"]) for r in iv_rows if species_of(r["species"])}
    keys.update((s["study"], s["species"]) for s in reported_auc)
    keys = sorted(k for k in keys if k[0] and k[1])
    boards = []
    for st, sp in keys:
        db = dist_boards.get((st, sp)) or {}
        bp = [s for s in plasma if s["study"] == st and s["species"] == sp]
        bo = [o for o in obs if o["study"] == st and o["species"] == sp]
        br = [p for p in reported if p["study"] == st and p["species"] == sp]
        fu_cfg = (cfg.get("fu_p") or {}).get(f"{st}|{sp}")
        fu_rec = fu_cfg if fu_cfg and fu_cfg.get("low") is not None else None
        b = {"key": _slug(f"{st}-{sp}"), "study": st, "species": sp, "plasma": bp, "datasets": sorted({s["dataset_id"] for s in bp} | {o["dataset_id"] for o in bo} | {p["dataset_id"] for p in br} | {r["dataset_id"] for r in iv_rows if r["study"] == st and r["species"] == sp}),
             "reported": br, "figs": {}, "distribution_board": db.get("key"),
             "dist_panels": {k: _upfile("distribution", f) for k, f in (db.get("figs") or {}).items()}}
        b["item29"] = []
        for s in bp:
            if s["route_class"] not in ("IV", "EV") or s["occasion"] != "FIRST_DOSE":
                continue
            r = item29(s, abs_idx, abs_meta, d24.get(s["sid"]), db.get("binding"), reported, cfg,
                       source=source_tables[s["dataset_id"]])
            f = (db.get("figs") or {}).get(f"DIS1a|{s['sid']}")
            if s["route_class"] == "IV" and f:
                r["upstream_panel"] = {"section": "distribution", "panel": "DIS-1a", "file": _upfile("distribution", f)}
            elif s["route_class"] == "IV":
                r["upstream_mismatch"] = "no DIS-1a panel for this profile in the distribution record"
            b["item29"].append(r)
        clearance_contrasts = cfg.get("reported_iv_clearance_contrasts", [])
        b["item30"] = item30(b, bp, db, abs_data, reported, bo, reported_auc, clearance_contrasts)
        b["datasets"] = sorted(set(b["datasets"]) | {s["dataset_id"] for s in b["item30"]["reported_auc"]})
        pk_sources = [source_tables[ds] for ds in b["datasets"] if ds in source_tables and source_tables[ds].get("role") in
                      ("PK_OBSERVATIONS", "REPORTED_PARAMETERS", *EXCRETA_ROLES)]
        regimens = [design for entry in pk_sources if (design := _repeat_regimen(entry))]
        b["item31"] = item31(b, bp, dist_data, abs_data, reported, bo, regimens, clearance_contrasts)
        if any(r["study"] == st and r["species"] == sp for r in tissue_parameters):
            b["distribution_tissue_table"] = "../distribution/reported-tissue-half-lives.html"
            b["distribution_tissue_records"] = "../distribution/reported-tissue-half-lives.json"
        b["urine"] = urine_series(bo, ex_cards, cfg)
        b["clr"] = [row for u in b["urine"] for row in item33_clr(u, bp, ex_cards, cfg, fu_rec)]
        b["renal_filtration_comparison"] = renal_filtration_comparison(
            b, cfg.get("renal_filtration_comparison", {}).get(f"{st}|{sp}"))
        b["recovery"] = recovery_sets(bo, ex_cards, cfg)
        b["recovery_design_sources"] = sorted({o["dataset_id"] for o in bo if _is_recovery_observation(o)})
        b["components"] = component_profiles(bo, ex_cards)
        b["in_vitro"] = [r for r in iv_rows if r["study"] == st and (r["species"] == sp)]
        b["em7b"] = [g for g in em7b if g["study"] == st and any(r["species"] == sp for r in g["rows"] + [{"species": x["species"]} for x in g["left_out"]])]
        b["ex_cards"] = [ex_cards[d] for d in sorted({o["dataset_id"] for o in bo})]
        b["iv_cards"] = [c for c in iv_cards if c["dataset_id"] in {r["dataset_id"] for r in b["in_vitro"]}]
        # Display metadata only: source identifiers remain in datasets and all measurement records.
        b["inventory_sources"] = [{"dataset_id": d, "title": source_tables[d].get("title"),
                                     "role": source_tables[d].get("role")}
                                    for d in b["datasets"] if d in source_tables]
        boards.append(b)
    project_figures = figures(boards, out, em7b)
    sp_rows, contrasts = species_columns(boards, dist_data)
    for b in boards:
        b["questions"] = board_questions(b)
        b["hypothesis"] = board_hypothesis(b)
        b["hypothesis"]["upstream_dme_followup"] = upstream_dme_followup(
            dist_boards.get((b["study"], b["species"])) or {}, b)
        b["handoff"] = handoff_records(b)
    spt = {"species_rows": sp_rows, "contrast_rows": contrasts, "species_summaries": species_summaries(sp_rows, contrasts),
           "assay_comparisons": project_figures,
           "missing_by_species": {sp: sorted({m for b in boards if b["species"] == sp for q in b["questions"] if q["shown"] for m in q["missing"]})[:6]
                                  for sp in sorted({b["species"] for b in boards})},
           "dis6b": _upfile("distribution", ((dist_data or {}).get("species_table") or {}).get("figure"))}
    result = {"version": VERSION, "rule_specification": RULES["file"], "rules": RULES, "rule_amendments": [Q1_AMENDMENT, Q2_AMENDMENT, Q3_AMENDMENT, Q5_AMENDMENT, Q6_AMENDMENT, Q7_AMENDMENT, SPECIES_AMENDMENT, REPORTED_DOSE_AMENDMENT, REPORTED_CONTEXT_AMENDMENT],
              "generator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "source_tables_sha256": hashlib.sha256((root / "source_tables.json").read_bytes()).hexdigest(),
              "upstream": {"absorption": abs_meta, "distribution": dist_meta},
              "settings": {"late_increment_share": cfg.get("late_increment_share"), "recovery_review_tolerance_pp": cfg.get("recovery_review_tolerance_pp"),
                           "tolerance_rel": TOL, "gfr_sourced": sorted(k for k, v in (cfg.get("gfr") or {}).items() if v and (v.get("low") or v.get("gfr_ml_min_kg")))},
              "config_used": {k: v for k, v in cfg.items() if not k.startswith("_about")}, "reading_map": READING_MAP, "skipped": skipped,
              "excreta_cards": list(ex_cards.values()), "in_vitro_cards": iv_cards, "in_vitro_rows": iv_rows, "em7b_groups": em7b,
              "reported_parameters": reported, "item32_inventory": item32(plasma_all, scope),
              "boards": [_board_json(b) for b in boards], "species_table": spt,
               "modeling_index": [{"study": b["study"], "species": b["species"],
                                   "species_priority": "#/species_table/species_summaries/" + b["species"].replace("~", "~0").replace("/", "~1"),
                                   "urinary_evidence": f"#/boards/{i}/questions/{next(k for k, q in enumerate(b['questions']) if q['q'] == 5)}/evidence_levels",
                                   "hypothesis": f"#/boards/{i}/hypothesis", "quantities": f"#/boards/{i}/handoff"}
                                  for i, b in enumerate(boards)],
              "handoff": [r | {"study": b["study"], "species": b["species"]} for b in boards for r in b["handoff"]]}
    current = {f["file"] for f in _SPECS}
    render_all(out)
    result["render"] = dict(_RENDER)
    pages = render_pages(result, boards, spt, out)
    _eda_common().annotate_section("elimination", result, Path(root))
    (out / "elimination.json").write_text(json.dumps(result, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    for name, text in pages.items():
        (out / name).write_text(text, encoding="utf-8")
    for name in previous - current - set(pages):
        if Path(name).name == name and (name.startswith("EM") or name.startswith("species-")):
            (out / name).unlink(missing_ok=True)
    result["_boards"] = boards
    return result


def _board_json(b):
    o = {}
    for k, v in b.items():
        if k == "plasma":
            o[k] = [s["sid"] for s in v]
        elif k == "figs":
            o[k] = dict(v)
        else:
            o[k] = v
    return o


# ---------------------------------------------------------------- pages

def _shell(title, body):
    return dist._shell(title, body).replace(" · EDA review</title>", " · EDA review</title>", 1)


def _report_nav(out):
    report = '<a href="../report.html#elimination">← EDA report</a>' if out and (Path(out).parent / "report.html").is_file() else ""
    return f'<!--EM-NAV-->{report}<!--/EM-NAV-->'


def page_name(sp):
    return f"species-{_slug(sp)}.html"


def _table(head, rows, cls="res evt", caption=""):
    return (f'<div class="tw"><table class="{cls}">' + (f"<caption>{_e(caption)}</caption>" if caption else "") + "<tr>" + "".join(f"<th>{_e(x)}</th>" for x in head) + "</tr>"
            + "".join("<tr>" + "".join(f"<td>{_wb(v)}</td>" for v in r) + "</tr>" for r in rows) + "</table></div>")


def _card_html(b):
    rows = []
    for s in b["plasma"]:
        rows.append([s["dataset_id"], s["label"], "plasma (" + s["matrix_class"].lower() + ")", s["route_class"], f"{s['dose']:g} mg/kg" if s["dose"] else (dist._regimen_text(s) or "dose not found"),
                     _lvl(s["level"]), _assay_plasma(s).replace("_", " ").lower(), s["occasion"].replace("_", " ").lower()])
    for c in b["ex_cards"]:
        rows.append([c["dataset_id"], _short(c["title"], 60), c["excretum_default"].lower() + " (excreta)", c["route_class"], f"{c['dose']:g} mg/kg" if c["dose"] else "dose not found",
                     _lvl(c["level"]), c["assay"].replace("_", " ").lower(), "repeat" if c["repeat"] else "single"])
    for c in b["iv_cards"]:
        rows.append([c["dataset_id"], _short(c["title"], 60), "in vitro: " + _short(c["system"], 30), "—", c["start_concentration"], "—", "—", "—"])
    for d in sorted({p["dataset_id"] for p in b["reported"]}):
        p = next(p for p in b["reported"] if p["dataset_id"] == d)
        dose = f"{_f(p['table_dose'])} mg/kg" if p.get("table_dose") else _study_dose_text(p.get("dose_context", {})) or "see source rows"
        rows.append([d, _short(p["title"], 60), "reported parameters", _reported_routes(b["reported"], d), dose, "as reported", p["method"], "—"])
    if len(rows) > 16:
        rows = rows[:14] + [["…", f"{len(rows) - 14} more datasets", "", "", "", "", "", ""]]
    h = _table(["Dataset", "Series or table", "Matrix", "Route", "Dose", "Data", "Assay", "Occasion"], rows, "res evt card")
    coll = []
    for c in b["ex_cards"]:
        cc = c["collection"]
        coll.append([c["dataset_id"], c["assay"].replace("_", " ").lower() + (f" ({_short(c['assay_note'], 80)})" if c.get("assay_note") else ""), cc["bladder_emptying"],
                     cc["collection_complete"], cc["cagewash"].replace("_", " ").lower(), cc["animals"].replace("_", " ").lower(), cc["pairing"].replace("_", " ").lower(),
                     cc["stability"], c["dispersion"].replace("UNKNOWN", "type not identified")])
    if coll:
        h += ('<details class="evi"><summary>Excreta data card (E0.8 fields; "not reported" becomes a missing entry)</summary>'
              + _table(["Dataset", "Assay", "Bladder emptying", "Collection complete", "Cage wash", "Animals", "Plasma pairing", "Stability", "Dispersion"], coll) + '</details>')
    return h


def _chips(b, page=""):
    chips = [f'<a class="qchip" href="{_e(page)}#step-{_e(b["key"])}-{q["q"]}" title="{_e(q["text"])}">Q{q["q"]} {_e(q["label"])}'
             f'<span class="st {ab.ST_CLASS[q["status"]]}">{_e(ab.ST_SHORT[q["status"]])}</span></a>' for q in b["questions"] if q["shown"]]
    chips.append(f'<a class="qchip" href="{_e(page)}#h-{_e(b["key"])}">H Working hypothesis<span class="st st-hyp">Pending</span></a>')
    return "".join(chips)


def _qrow_html(q, key, base):
    html_ = dist._qrow_html(dict(q, display_number=q["q"], q=0 if q["q"] == 7 else q["q"]), key, base)
    html_ = html_.replace(f'id="q-{_e(key)}-0"', f'id="q-{_e(key)}-7"')
    if q["q"] in (1, 3, 6) and (q.get("primary") or {}).get("kind") == "row":
        html_ = html_.replace('class="qbody"', 'class="qbody noprim"', 1)
    if q.get("distribution_tissue_table"):
        html_ = html_.replace("</article>", f'<p><a href="{_e(q["distribution_tissue_table"])}">Reported tissue-fluid half-lives in Distribution →</a></p></article>', 1)
    if q["q"] == 7 and q.get("comparison_keys"):
        anchor = "assay-" + _slug(q["comparison_keys"][0])
        html_ = html_.replace("</article>", f'<p><a href="conditions-and-species.html#{_e(anchor)}">Compare this assay across species →</a></p></article>', 1)
    return html_


def _hrow_html(b):
    h = b["hypothesis"]
    miss = ('<p class="miss"><b>Missing:</b> ' + "; ".join(_e(m) for m in h["missing"]) + '</p>') if h["missing"] else ""
    chk = ('<p class="hstab warn"><b>Check first:</b> ' + "; ".join(_e(m) for m in h["check_first"]) + '</p>') if h["check_first"] else ""
    return (f'<article class="qrow hrow" id="h-{_e(b["key"])}"><div class="qhead"><span class="qn">H</span><h3>Working hypothesis</h3>'
            f'<span class="st st-hyp">Review pending</span><p class="q">Taken together, what should a model check next about elimination?</p></div>'
            f'<div class="qbody noprim"><div class="qtext"><p class="concl">{_e(h["observation"])} <span class="sub">'
            + (f'Alternative: {_e(h["alternative"])} ' if h["alternative"] else "") + f'Next: {_e(h["next_test"])} {_e(h["rests_on"])}</span></p>{miss}{chk}</div></div></article>')


def _points_html(b):
    h = []
    anchored = set()
    def anchor(dataset):
        if dataset in anchored:
            return ""
        anchored.add(dataset)
        return f' id="data-{_e(b["key"])}-{_e(dataset)}"'

    for s in b["plasma"]:
        h.append(f'<details class="pts"{anchor(s["dataset_id"])}><summary>{_e(s["dataset_id"])} · {_e(s["label"])}</summary>'
                 + _table(["Time (h)", "Value", "Status", "Record"], [[_f(p["t"], 4), _f(p["c"] if p["c"] is not None else p.get("lim"), 4), p["status"], p.get("record_id") or "—"]
                                                                       for p in s["points"]], caption=s["unit"]) + '</details>')
    for c in b["ex_cards"]:
        os_ = [u for u in b["urine"] if u["dataset_id"] == c["dataset_id"]]
        rows = [[u["group"], u["trace"], " – ".join(_f(x) for x in i["interval"]) if i["interval"] else "—", i["raw"], i["state"].lower(), i["record_id"]] for u in os_ for i in u["intervals"]]
        rows += [[u["group"], u["trace"], "printed total", t["raw"], "quantified", t["record_id"]] for u in os_ for t in u["printed_totals"]]
        h.append(f'<details class="pts"{anchor(c["dataset_id"])}><summary>{_e(c["dataset_id"])} · {_e(c["title"])}</summary>'
                 + (_table(["Group", "Trace", "Interval (h)", "As printed", "State", "Record"], rows) if rows else "<p>Recovery and component rows are in the evidence of Q6 and Q7.</p>")
                 + (f'<p class="ev notes">Layout: {_e(c["layout"])} ({_e(c["layout_reason"])}). Footnotes: {_e("; ".join(f"{k}) {v}" for k, v in c["footnotes"].items()) or "none")}.</p>')
                 + '</details>')
    for c in b["iv_cards"]:
        ds = c["dataset_id"]
        rows = [[r["drug"], READOUT_WORD.get(r["readout"], r["readout"]), r["raw"], r["unit"],
                 r["row_id"], r["excluded_reason"] or "—"] for r in b["in_vitro"] if r["dataset_id"] == ds]
        h.append(f'<details class="pts"{anchor(ds)}><summary>{_e(ds)} · {_e(c["system"])}</summary>'
                 + _table(["Drug", "Readout", "As printed", "Unit", "Source cell", "Exclusion"], rows) + '</details>')
    for ds in sorted({r["dataset_id"] for r in b["reported"]}):
        reported = [r for r in b["reported"] if r["dataset_id"] == ds]
        h.append(f'<details class="pts"{anchor(ds)}><summary>{_e(ds)} · Source-reported parameters</summary>'
                 + _table(REP_HEAD, _rep_rows(reported)) + '</details>')
    for s in b["item30"].get("reported_auc", []):
        ds = s["dataset_id"]
        h.append(f'<details class="pts"{anchor(ds)}><summary>{_e(s["key"])} · AUC by dose</summary>'
                 + _table(["Dose (mg/kg)", f"Reported AUC ({s['auc_unit']})", "Source cells"],
                          [[_f(r["dose"]), _f(r["auc"]), ", ".join(r["refs"])] for r in s["rows"]]) + '</details>')
    return ('<section class="panel" id="points-' + _e(b["key"]) + '"><h2>Source data points</h2>' + "".join(h) + '</section>') if h else ""


def _species_card(sp, boards):
    counts = Counter(q["status"] for b in boards for q in b["questions"] if q["shown"])
    files = list(dict.fromkeys(f for b in boards for f in b["figs"].values()))
    up = [r["upstream_panel"]["file"] for b in boards for r in b["item29"] if r.get("upstream_panel")]
    previews = (files + up)[:3]
    studies = [b["study"] for b in boards]
    info = {"species": sp, "page": page_name(sp), "studies": studies, "figures": len(files), "thumbnails": previews,
            "counts": {ST_CODE[s]: counts[s] for s in ab.ST_ORDER if counts[s]}}
    chips = " ".join(f'<span class="st {ab.ST_CLASS[s]}">{counts[s]} {_e(ab.ST_SHORT[s].lower())}</span>' for s in ab.ST_ORDER if counts[s])
    images = "".join(f'<img src="{_e(f)}" alt="Preview of {_e(f)}" loading="lazy">' for f in previews)
    card = (f'<a class="category" id="sp-{_e(_slug(sp))}" href="{_e(page_name(sp))}"><span class="badge">{len(studies)} {"study" if len(studies) == 1 else "studies"}</span>'
            f'<h3>{_e(sp)}</h3><p class="muted">{len(studies)} {"study" if len(studies) == 1 else "studies"} · {len(files)} new {"panel" if len(files) == 1 else "panels"}</p><p>{chips}</p>'
            + (f'<div class="thumbs">{images}</div>' if images else "") + '<span class="open">Open the questions →</span></a>')
    return info, card


def _emr_page(res, back):
    rep = res["reported_parameters"]
    rows = [[p["species"], p["study"]] + r for p, r in zip(rep, _rep_rows(rep))]
    scope = res["item32_inventory"]
    h = [back, '<section class="panel" id="em-r"><h1>EM-R · Source-reported parameters</h1>',
         '<p class="muted">Clearance, renal clearance, fe, rate constants and half-lives as printed, with their definition, units, method and source (E0.12). '
         'They are never substituted for the window value (EM-1a) or the urine series (EM-5a). Values already shown in absorption F are marked there and not repeated here.</p>',
         _table(["Species", "Study"] + REP_HEAD, [r for p, r in zip(rep, rows) if not p["shown_in_absorption_F"]]) if rep else "<p>No reported elimination parameters.</p>"]
    if scope:
        h.append('<details class="evi"><summary>Item 32 (reserved): metabolite and total-radioactivity entries, listed for scope review only</summary>'
                 + _table(["Dataset", "Series", "Study", "Species", "Analyte", "Matrix", "Flags"], [[x["dataset_id"], x["series"], x["study"], x["species"], x["analyte"], x["matrix"], _words(x["caveats"])] for x in scope]) + '</details>')
    h.append('</section>')
    return _shell("Reported parameters", "".join(h))


def _species_page(spt, back):
    h = [back, '<section class="panel" id="species"><h1>Q7 · Species and conditions (project level)</h1>',
         '<p class="muted">The elimination columns (EM-8a) are added to the project species table DIS-6b; no second table. Different quantities are never put on '
         'a common clearance axis, and missing cells stay visible.</p>']
    h.append('<nav><a href="#modeling-priorities">Modeling check by species</a>' +
             ('<a href="#common-windows">Measured windows</a>' if spt["contrast_rows"] else '') + '</nav>')
    if spt.get("dis6b"):
        h.append(f'<figure class="prim" style="max-width:760px"><a href="{_e(spt["dis6b"])}" target="_blank"><img src="{_e(spt["dis6b"])}" alt="DIS-6b"></a>'
                 '<figcaption><b>DIS-6b</b> · project species table from Distribution (linked, not redrawn)</figcaption></figure>')
    for g in spt.get("assay_comparisons", []):
        title = f"{g['system']} · {READOUT_WORD[g['readout']]}"
        if g["time_min"] is not None:
            title += f" at {_f(g['time_min'])} min"
        h.append(f'<figure class="prim" id="assay-{_e(_slug(g["key"]))}"><a href="{_e(g["file"])}">'
                 f'<img src="{_e(g["file"])}" loading="lazy" alt="{_e(title)}"></a><figcaption>'
                 f'<b>{_e(title)}</b> ({_e(g["unit"])}). {_e(g["study"])} / {_e(g["dataset_id"])} · {_e(g["drug"])}. '
                 f'{_e(g["direction"])}.</figcaption></figure>')
    rows = []
    for r in spt["species_rows"]:
        d = r["dis6b"] or {}
        rows.append([r["species"], r["study"], d.get("phases") or "—",
                     " ".join(c["description"] for c in r["window_cl"]) or "—",
                     "; ".join(p["as_printed"] + (f" @ {_f(p['dose'])} mg/kg" if p.get("dose") else " " + _study_dose_text(p.get("dose_context", {}))) for p in r["reported_cl"][:3]) or "—",
                     "; ".join(f"{_f(u['value'])} % by {_f(u['end_h'])} h ({u['trace']}{', ' + u['occasion'].replace('_', ' ').lower() if u['occasion'] != 'FIRST_DOSE' else ''})" for u in r["urinary_recovery"][:3]) or "—",
                     "; ".join(f"{_f(c['value'] * ML_MIN_KG_PER_L_H_KG)} mL/min/kg ({c['kind'].replace('_', ' ').lower()}, T10 {c['t10'].replace('_', ' ').lower()})" for c in r["clr"][:2]) or "—",
                     "; ".join(", ".join(f"{ROUTE_WORD.get(k, k.lower())} {', '.join(_f(x) for x in v)}" for k, v in x["routes"].items()) + (f"; total {', '.join(_f(t) for t in x['source_totals'])}" if x["source_totals"] else "") for x in r["recovery"][:2]) or "—",
                     "; ".join(f"{c['group']}: {c['component']} {_f(c['share'])} {c['basis']}" for c in r["largest_product"]) or "—",
                     "; ".join(f"{x['readout']} {_f(x['value'])} {x['unit']}" for x in r["in_vitro"] if x["eligible"]) or "—"])
    h.append(_table(["Species", "Study", "DIS-6b phases", "Dose / observed AUC (L/h/kg)", "Reported CL", "Urinary recovery", "CLR", "Recovery by route (%)", "Largest named product", "In vitro"],
                    rows, caption="EM-8a columns"))
    if spt["contrast_rows"]:
        h.append('<h2 id="common-windows">Observed windows across species</h2>')
    for c in spt["contrast_rows"]:
        if not c.get("windows"):
            continue
        profiles = c["profiles"]
        names = Counter(p["species"] for p in profiles)
        labels = [p["species"] if names[p["species"]] == 1 else f"{p['species']} ({p['group']})" for p in profiles]
        unit = "L/h/kg" if c["denominator"] == "L/h/kg" else f"% of {c['denominator']}"
        dose = f"{_f(c['dose'])} mg/kg" if c["dose"] is not None else "dose unknown"
        caption = f"{c['study']} / {c['dataset']} · {c['quantity']} ({unit}) · {dose} {c['route']} · {c['occasion'].replace('_', ' ').lower()}"
        h.append(_table(["Measured window (h)", *labels, "Use"], [
            [f"{_f(w['window_h'][0])}–{_f(w['window_h'][1])}",
             *[(_f(cell["value"], 4) + ("*" if "SOURCE_CONFLICT" in profile["flags"] else "")) if cell and cell["value"] is not None else "—"
               for cell, profile in zip(w["cells"], profiles)],
             "Descriptive comparison" if w["comparability"] == "descriptive_only" else "Separate observations"]
            for w in c["windows"]], caption=caption))
        notes = "A dash means no usable value for this window. Only matching windows support a descriptive comparison."
        if c["denominator"] != "L/h/kg":
            notes += " These recoveries cannot rank the ultimate fraction of unchanged drug excreted in urine."
        if any("SOURCE_CONFLICT" in p["flags"] for p in profiles):
            affected = ", ".join(label for label, p in zip(labels, profiles) if "SOURCE_CONFLICT" in p["flags"])
            notes += f" * {affected}: a source conflict remains open. The printed value is displayed separately."
        h.append(f'<p class="muted">{_e(notes)}</p>')
        if c["unmatched_pairs"]:
            pairs = ", ".join(" / ".join(pair) for pair in c["unmatched_pairs"])
            h.append(f'<details><summary>Species pairs without an eligible common window</summary><p>{_e(pairs)}. '
                     'Their usable measurements do not cover a common interval on this basis.</p></details>')
    blocked = [c for c in spt["contrast_rows"] if not c.get("windows")]
    if blocked:
        h.append(_table(["Species", "Quantity", "Reason"], [[" / ".join(c["pair"]), c["quantity"], c["reason"]] for c in blocked],
                        caption="Comparisons without a matched source and measurement basis"))
    h.append('<h2 id="modeling-priorities">One modeling check per species</h2>')
    h.append(_table(["Species", "Observation", "Principal unresolved alternative", "Discriminator"],
                    [[sp, v["observation"], v["alternative"], v["discriminator"]] for sp, v in spt["species_summaries"].items()], caption="Species summaries"))
    miss = "; ".join(f"{sp}: {', '.join(m)}" for sp, m in spt["missing_by_species"].items() if m)
    if miss:
        h.append(f'<p class="miss"><b>Missing by species:</b> {_e(miss)}</p>')
    h.append('</section>')
    return _shell("Species and conditions", "".join(h))


QSHORT = {1: "Window CL", 2: "Dose", 3: "Repeat dosing", 5: "Urine", 6: "Recovery", 7: "Products, species"}
LEGEND = ((ST_YES, "the data answer it under the stated assumptions"),
          (ST_PART, "a description, or a value with limits, answers part of it; the row says which part"),
          (ST_NO, "these data cannot answer it yet; the row says what is missing"),
          (ST_NA, "the question does not arise in this study"))


def _legend():
    return '<div class="legend">' + "".join(f'<span><span class="st {ab.ST_CLASS[s]}">{_e(ab.ST_SHORT[s])}</span>{_e(d)}</span>' for s, d in LEGEND) + '</div>'


def _engine(res):
    eng = res["render"]["engine"]
    return {"R_GGPLOT2": "Figures drawn with R (ggplot2)", "MATPLOTLIB_FALLBACK": "Figures drawn with matplotlib (R unavailable)",
            "none": "No new figures"}.get(eng, f"Figures: {eng}")


def _qtab(boards):
    head = "".join(f'<th title="{_e(QD[q][1])}">Q{q}<br><span class="muted">{_e(QSHORT[q])}</span></th>' for q in (1, 2, 3, 5, 6, 7))
    rows = []
    for b in boards:
        cells = []
        for q in b["questions"]:
            pg = page_name(b["species"])
            chip = f'<span class="st {ab.ST_CLASS[q["status"]]}">{_e(ab.ST_SHORT[q["status"]])}</span>'
            cells.append(f'<td><a href="{_e(pg)}#q-{_e(b["key"])}-{q["q"]}" title="{_e(q["text"])}">{chip}</a></td>' if q["shown"] else f'<td title="{_e(q["text"])}">{chip}</td>')
        rows.append(f'<tr><td><a href="{_e(page_name(b["species"]))}#study-{_e(b["key"])}">{_e(b["study"])}</a> · {_e(b["species"])}</td>' + "".join(cells)
                    + f'<td><a href="{_e(page_name(b["species"]))}#h-{_e(b["key"])}"><span class="st st-hyp">Pending</span></a></td></tr>')
    return ('<div class="tw"><table class="res qtab"><tr><th>Study</th>' + head + '<th title="Working hypothesis">H<br><span class="muted">Hypothesis</span></th></tr>'
            + "".join(rows) + '</table></div>')


def _datasets_rows(boards):
    seen, rows = set(), []
    for b in boards:
        for s in b["plasma"]:
            if (s["dataset_id"], b["species"]) in seen:
                continue
            seen.add((s["dataset_id"], b["species"]))
            used = "Q1 dose / observed AUC" if any(r["dataset_id"] == s["dataset_id"] and r["window_proxy"] for r in b["item29"]) else "context (not first-dose IV/EV parent)"
            rows.append([s["dataset_id"], b["species"], b["study"], (f"{s['dose']:g} mg/kg " if s["dose"] else (dist._regimen_text(s) or "dose not found") + " ") + s["route_class"],
                         "plasma" if s["matrix_class"] == "PLASMA" else s["matrix_class"].lower(), _lvl(s["level"]).capitalize() + (", digitized" if s.get("digitized") else ""), used])
        for c in b["ex_cards"]:
            if (c["dataset_id"], b["species"]) in seen:
                continue
            seen.add((c["dataset_id"], b["species"]))
            rows.append([c["dataset_id"], b["species"], b["study"], (f"{c['dose']:g} mg/kg " if c["dose"] else "dose not found ") + c["route_class"],
                         c["excretum_default"].lower() + " (excreta)", _lvl(c["level"]).capitalize(), "Q5 to Q7 excreta" + (f"; assay {c['assay'].lower().replace('_', ' ')}" if c["assay"] != "SPECIFIC" else "")])
        for c in b["iv_cards"]:
            if (c["dataset_id"], "iv") in seen:
                continue
            seen.add((c["dataset_id"], "iv"))
            rows.append([c["dataset_id"], "several", b["study"], c["start_concentration"], "in vitro: " + _short(c["system"], 40), "As reported", "Q7 in vitro"])
        for d in sorted({p["dataset_id"] for p in b["reported"]}):
            if (d, b["species"]) in seen:
                continue
            seen.add((d, b["species"]))
            p = next(p for p in b["reported"] if p["dataset_id"] == d)
            dose = f"{_f(p['table_dose'])} mg/kg" if p.get("table_dose") else _study_dose_text(p.get("dose_context", {}))
            rows.append([d, b["species"], b["study"], (dose + " " + _reported_routes(b["reported"], d)).strip(), "reported parameters", "As reported", "EM-R"])
    return sorted(rows, key=lambda r: (r[0], r[1]))


# ---------------------------------------------------------------- overview summary (the form of the absorption overview)

def _overview_paras(res, boards):
    """A short reading guide; calculations and study-specific provenance stay on the species pages."""
    if not boards:
        return []
    # Older saved boards predate display metadata; their source cards still identify the study design.
    display_boards = [dict(b, inventory_sources=b.get("inventory_sources") or
                          b.get("ex_cards", []) + b.get("iv_cards", []) + b.get("reported", []) +
                          [p for p in b.get("plasma", []) if isinstance(p, dict)]) for b in boards]
    name = dist._board_namer(display_boards)
    def animals(species):
        return {"Mouse": "mice", "Human": "humans"}.get(species, species.lower() + "s")

    def urine_is_oral(b, u):
        detail = next((c.get("route_detail") for c in b.get("ex_cards", []) if c.get("dataset_id") == u.get("dataset_id")), "")
        return u.get("route") == "EV" and (detail in ("PO", "ORAL") or bool(re.search(r"\b(?:PO|oral)\b", u.get("group", ""), re.I)))

    paras = []
    repeat = [(b, (b.get("item31") or {}).get("reported_accumulation") or {}) for b in boards]
    repeat = [(b, a) for b, a in repeat if a.get("rows")]
    for b, acc in repeat[:1]:
        rows = acc["rows"]
        readings = []
        for r in rows:
            if r.get("param") == "THALF" or "t1/2" in r["label"]:
                readings.append(f"terminal half-life {_f(r['first'])} → {_f(r['last'])} {r['unit']}")
            else:
                label = "peak concentration" if r["label"] == "Cmax" else r["label"]
                readings.append(f"{label} {r['ratio']:.2f}×")
        first, last = rows[0]["first_day"], rows[0]["last_day"]
        route_details = {p.get("route_detail") for p in b.get("reported", []) if p.get("dataset_id") in rows[0].get("datasets", [])}
        route = "oral" if route_details & {"PO", "ORAL"} else "IV" if rows[0].get("route") == "IV" else "extravascular" if rows[0].get("route") == "EV" else "repeated"
        interval = acc.get("interval_h")
        schedule = " daily" if interval == 24 else f" every {_f(interval)} h" if interval else " repeatedly"
        condition = (acc.get("condition") + " ") if acc.get("condition") in ("fasted", "nonfasted", "fed") else ""
        txt = f"In {condition}{animals(b['species'])} given {route} doses{schedule}, source-reported group summaries show " + "; ".join(readings)
        txt += f" on day {last} versus day {first}. These ratios have no uncertainty interval and do not establish a clearance change."
        if acc.get("dose_resolved") is False:
            txt += " The absolute dose conflicts between source passages; comparisons retain the same reported regimen without dose normalization."
        paras.append(("Repeated dosing", txt))
    ongoing = [(b, r["ongoing_input"]) for b in boards for r in b.get("item29", [])
               if r.get("ongoing_input") and r["ongoing_input"].get("sample_variation") == "WITHIN_BAND"]
    if ongoing:
        b, o = ongoing[0]
        paras.append(("Infusion", f"In {animals(b['species'])}, the IV infusion rate divided by the mean sampled plasma concentration was {o['value_l_per_h_kg']:.3g} L/h/kg "
                      f"over {_f(o['window_h'][0])}–{_f(o['window_h'][1])} h. It equals clearance only under constant IV input, "
                      "steady state and a parent-specific total-plasma assay; small sampled variation does not establish steady state."))
    urine = [(b, [u for u in b.get("urine", []) if u.get("r_u") is not None]) for b in boards]
    urine = [(b, us) for b, us in urine if us]
    active_urine = [(b, u) for b, us in urine for u in us if u["analyte"] == "ACTIVE_MATERIAL"]
    if active_urine and len(active_urine) == sum(len(us) for _, us in urine):
        oral_groups = {}
        for b, u in active_urine:
            if urine_is_oral(b, u):
                key = (u.get("dose"), u.get("collection_end_h"), u["denominator"], u.get("occasion", "FIRST_DOSE"))
                oral_groups.setdefault(key, []).append((b, u))
        sentences = []
        for (dose, end, denominator, occasion), group in list(oral_groups.items())[:2]:
            values = ab._hjoin(f"{_f(u['r_u'])}% in {animals(b['species'])}" for b, u in group)
            dose_text = f" {_f(dose)} mg/kg" if dose is not None else ""
            window = f" by {_f(end)} h" if end is not None else " over the reported window"
            timing = "" if occasion == "FIRST_DOSE" else " (" + occasion.lower().replace("_", " ") + ")"
            sentences.append(f"After oral{dose_text} doses, urine bioassay recovery{window} was {values} (percent of {denominator}){timing}.")
        for b, u in active_urine:
            if "SOURCE_CONFLICT" not in u.get("flags", []):
                continue
            other = (u.get("reconcile") or {}).get("sum_of_increments")
            window = f" over 0–{_f(u['collection_end_h'])} h" if u.get("collection_end_h") is not None else ""
            route = "IV" if u.get("route") == "IV" else "oral" if urine_is_oral(b, u) else "extravascular"
            sentences.append(f"The {route} result in {animals(b['species'])} has a source conflict: printed recovery {_f(u['r_u'])}% versus interval sum {_f(other)}%{window}."
                             if other is not None else f"The {route} result in {animals(b['species'])} has an unresolved source conflict.")
        if not sentences:
            b, u = active_urine[0]
            sentences.append(f"Urine bioassays measured {_f(u['r_u'])}% of {u['denominator']} as active material in {animals(b['species'])}; conditions are on the species page.")
        sentences.append("These are collected recoveries, not ultimate excretion fractions. The assay measures antimicrobial activity and cannot identify unchanged drug alone. Other routes and conditions are on the species pages.")
        paras.append(("Urine", " ".join(sentences)))
    elif urine:
        readings = []
        active = False
        board_limit, row_limit = (2, 1) if len(paras) > 1 else (4, 2)
        for b, us in urine[:board_limit]:
            parts = []
            for u in us[:row_limit]:
                active = active or u["analyte"] == "ACTIVE_MATERIAL"
                detail = next((c.get("route_detail") for c in b.get("ex_cards", []) if c.get("dataset_id") == u.get("dataset_id")), "")
                oral = detail in ("PO", "ORAL") or re.search(r"\b(?:PO|oral)\b", u.get("group", ""), re.I)
                route = "oral" if oral and u.get("route") == "EV" else {"IV": "IV", "EV": "extravascular"}.get(u.get("route"), "route unstated")
                dose = f" {_f(u['dose'])} mg/kg" if u.get("dose") is not None else ""
                occasion = u.get("occasion", "FIRST_DOSE")
                timing = "" if occasion == "FIRST_DOSE" else ", " + occasion.lower().replace("_", " ")
                window = f"by {_f(u['collection_end_h'])} h" if u.get("collection_end_h") is not None else (u.get("window_label") or "window unstated")
                label = "active material" if u["analyte"] == "ACTIVE_MATERIAL" else "unchanged parent"
                den = u["denominator"].removeprefix("the ")
                condition = re.search(r"\b(nonfasted|fasted|fed)\b", u.get("group", ""), re.I)
                condition_text = f", {condition.group(1).lower()}" if condition else ""
                part = f"{route}{dose}{condition_text}: {_f(u['r_u'])}% of {den} as {label} {window}{timing}"
                if "SOURCE_CONFLICT" in u.get("flags", []):
                    reconciliation = u.get("reconcile") or {}
                    other = reconciliation.get("sum_of_increments")
                    part += f" (source conflict: interval sum {_f(other)}%)" if other is not None else " (source conflict)"
                parts.append(part)
            if len(us) > row_limit:
                parts.append("additional conditions on the species page")
            readings.append(f"In {animals(b['species'])}, " + "; ".join(parts) + ".")
        txt = " ".join(readings)
        if len(urine) > board_limit:
            txt += " Further species are on their detail pages."
        txt += " These are collected recoveries, not ultimate excretion fractions."
        if active:
            txt += " The bioassay measures antimicrobial activity and cannot identify unchanged drug alone."
        paras.append(("Urine", txt))
    # Give other evidence a concise entry point when urine and repeat/infusion findings do not already fill the summary.
    if not paras:
        plasma_groups = {}
        for b in boards:
            for r in b.get("item29", []):
                if r.get("window_proxy") is None:
                    continue
                key = (b["key"], r.get("route"), r.get("route_detail"), r.get("dose_mg_per_kg"), r.get("matrix"),
                       r.get("measurement_basis"), r.get("assay"), r.get("analysis_unit"))
                plasma_groups.setdefault(key, []).append((b, r))
        if plasma_groups:
            readings = []
            differing_windows = False
            unreported_assay = []
            for (board_key, route, detail, dose, matrix, basis, assay, level), group in plasma_groups.items():
                b = group[0][0]
                values = [r["window_proxy"] for _, r in group]
                value = _f(min(values)) + (f"–{_f(max(values))}" if min(values) != max(values) else "")
                windows = sorted({tuple(r["auc_window_h"]) for _, r in group if r.get("auc_window_h")})
                route_text = {"PO": "oral", "ORAL": "oral", "SC": "subcutaneous", "IM": "intramuscular", "IV_BOLUS": "IV", "IV": "IV"}.get(detail, "IV" if route == "IV" else "extravascular")
                dose_text = f" {_f(dose)} mg/kg" if dose is not None else ""
                unit = "individual" if level == "INDIVIDUAL" else "group-mean" if level == "GROUP_MEAN" else "reported"
                if len(windows) == 1:
                    scope = f"{_f(windows[0][0])}–{_f(windows[0][1])} h"
                elif windows:
                    scope = "different sampling windows"
                    differing_windows = True
                else:
                    scope = "windows unstated"
                profile_word = "profile" if len(group) == 1 else "profiles"
                readings.append(f"After {route_text}{dose_text} dosing, {len(group)} {unit} {b['species'].lower()} {profile_word} gave dose / observed AUC "
                                f"of {value} L/h/kg ({scope}; {str(matrix or 'matrix unstated').lower()}).")
                if assay == "NOT_REPORTED" and animals(b["species"]) not in unreported_assay:
                    unreported_assay.append(animals(b["species"]))
            text = " ".join(readings)
            if differing_windows:
                text += " Each profile uses its own observed window; the ranges describe separate profiles, not matched-window comparisons."
            else:
                text += " Each value uses its own observed window."
            if unreported_assay:
                text += " The assay is unreported for " + ab._hjoin(unreported_assay) + "."
            text += " The unobserved tail is excluded, so these are not full-exposure clearance estimates."
            paras.append(("Observed plasma", text))
        recovery = [(b, r) for b in boards for r in b.get("recovery", [])]
        if recovery:
            readings = []
            for b, r in recovery[:2]:
                parts = [f"{ROUTE_WORD.get(x['route'], x['route'].lower())} {_f(x['value'])}% ({x.get('interval_text') or 'window unstated'})" for x in r.get("routes", [])[:2]]
                parts.extend(f"source-reported total {_f(x['value'])}% ({x.get('interval_text') or 'window unstated'})" for x in r.get("source_totals", [])[:1])
                animals = {"INTACT": "intact animals", "BILE_CANNULATED": "bile-cannulated animals"}.get(r.get("animals"), "surgical status unstated")
                txt = f"{name(b)}, {animals}: " + "; ".join(parts) + f" of {r['denominator']} ({r['conserved_quantity']})."
                if r.get("t12"):
                    txt += " A source discrepancy remains open."
                readings.append(txt)
            paras.append(("Recovery", " ".join(readings) + " Route subtotals are partial accounting, not proof of complete recovery; different cohorts and windows stay separate."))
        components = [(b, c) for b in boards for c in b.get("components", []) if c.get("largest")]
        if components and not recovery:
            b, c = components[0]
            x = c["largest"]
            value, basis = (x["dose_share"], "of dose") if x.get("dose_share") is not None else (x["share"], f"on the reported basis ({c['reported_basis']})")
            paras.append(("Measured components", f"{name(b)}: {x['component']} represents {_f(value)}% {basis} in {c['excretum'].lower()} "
                          f"({c.get('interval_text') or 'window unstated'}). It is largest within this source component set; different denominators are not ranked together."))
        if not paras:
            reported = [(b, p) for b in boards for p in b.get("reported", []) if p.get("value") is not None]
            assays = [(b, r) for b in boards for r in b.get("in_vitro", []) if r.get("value") is not None and not r.get("excluded_reason")]
            if reported:
                b, p = reported[0]
                paras.append(("Source report", f"{name(b)}: the source reports {p['name']} of {_reported_value_text(p)}. The underlying method and sampling window need review before modeling."))
            elif assays:
                b, r = assays[0]
                paras.append(("In vitro", f"{name(b)}: {r['system']} reports {READOUT_WORD[r['readout']]} of {r['raw']} {r['unit']}. Its contribution to clearance in vivo remains unresolved."))
            else:
                paras.append(("Available evidence", "The available records do not yet support a quantitative elimination summary. Missing measurements do not establish absence of an elimination pathway."))
    if urine:
        next_step = "Match parent-specific plasma and urine measurements over the same collection interval; resolve source discrepancies first."
    elif ongoing:
        next_step = "Check steady state or sample after the infusion stops before interpreting the ratio as clearance."
    else:
        next_step = "Review sampling coverage and measurement basis before choosing an elimination model."
    paras.append(("Next step", next_step + " Species pages retain every study, condition and source reference. Human review is pending."))
    return [(title, dist._reader_text(text, display_boards)) for title, text in paras]


def _overview_html(res, boards):
    paras = _overview_paras(res, boards)
    return ('<div class="hsumtext">' + "".join(f'<p><b>{_e(k)}.</b> {_e(v)}</p>' for k, v in paras) + '</div>') if paras else ""


def _overview_stats(res, boards):
    cnt = dist._hcount
    files = {f for b in boards for f in b["figs"].values()}
    plasma = len({s if isinstance(s, str) else s["sid"] for b in boards for s in b["plasma"]})
    return (f'<p class="muted">{cnt(len(files), "new panel")} · {len({b["species"] for b in boards})} species · '
            f'{cnt(len({b["study"] for b in boards}), "study", "studies")} · {cnt(plasma, "plasma profile")} read from upstream, '
            f'{cnt(len(res.get("excreta_cards") or []), "excreta dataset")}, {cnt(len(res.get("in_vitro_cards") or []), "in vitro dataset")} and '
            f'{cnt(len(res.get("reported_parameters") or []), "reported-parameter record")} · Computed by host code from observed points; {FIT_NOTE} · '
            f'{_e(dist._hengine(res))} · Human review pending</p>')


def render_pages(res, boards, spt, out=None):
    pages = {}
    sps = sorted({b["species"] for b in boards})
    report_nav = _report_nav(out)
    back = f'<nav><a href="index.html">← All species</a>{report_nav}</nav>'
    n_fig = len({f for b in boards for f in b["figs"].values()}) + len(spt.get("assay_comparisons", []))
    n_ds = len({r[0] for r in _datasets_rows(boards)})
    meta = (f'{n_fig} new panels · {len(sps)} species · {len(boards)} study–species groups · {n_ds} datasets · plasma panels linked from Absorption and Distribution · '
            f'Computed by host code from observed points; {FIT_NOTE} · {_engine(res)} · Human review pending')
    entries = [_species_card(sp, [b for b in boards if b["species"] == sp]) for sp in sps]
    entries.sort(key=lambda p: (-len(p[0]["studies"]), -p[0]["figures"], p[0]["species"]))
    h = [f'<nav>{report_nav}<a href="figure-guide.html">How to read the figures</a>'
         '<a href="conditions-and-species.html">Species and conditions</a><a href="reported-parameters.html">Reported parameters</a>'
         '<a href="datasets.html">Data and provenance</a></nav>',
         '<div class="eyebrow">EDA figure review</div><h1>Elimination and metabolism</h1>',
         '<p class="lead">What the measurements show about drug removal, and the next useful check. Open a species for the full evidence.</p>',
         '<section class="panel" id="hypotheses"><h2>What the data point to</h2>' + _overview_html(res, boards) + '</section>',
         '<div class="section-head" id="species"><h2>Review by species</h2><span class="muted">Observations, limits and sources for each study.</span></div>'
         '<div class="categories">' + "".join(c for _, c in entries) + '</div>']
    provenance = [back, '<section class="panel" id="questions"><h1>Questions by study</h1>' + _legend() + _qtab(boards) + '</section>',
         '<section class="panel" id="data"><h2>Datasets used</h2><p class="muted">Technical identifiers link each measurement to its source record.</p>'
         + _table(["Dataset", "Species", "Study", "Dose", "Matrix", "Data", "Used for"], _datasets_rows(boards), "res") + '</section>']
    up = res["upstream"]
    provenance.append('<details class="evi"><summary>Upstream records read</summary>' + _table(["Section", "File", "Version", "SHA-256"],
             [[k, v.get("file"), v.get("version") or ("missing" if not v.get("present") else "—"), (v.get("sha256") or "—")[:16] + "…"] for k, v in up.items()]) + '</details>')
    if res["skipped"]:
        provenance.append('<details class="evi"><summary>Not read</summary><ul class="ev">' + "".join(f'<li>{_e(x["dataset_id"])}: {_e(x["reason"])}</li>' for x in res["skipped"]) + '</ul></details>')
    st = res["settings"]
    provenance.append(f'<footer>Elimination and metabolism rules {RULES_VERSION} · Technical EDA. Each value records its evidence, window and limits. Settings: late increment share '
             f'{_f(st["late_increment_share"])}; recovery review tolerance '
             + (f'{_f(st["recovery_review_tolerance_pp"])} pp' if st["recovery_review_tolerance_pp"] is not None else "not set")
             + '; GFR sourced for ' + (_e(", ".join(st["gfr_sourced"])) or "no species") + '. Human review pending.'
             + (f' Renderer note: {_e(res["render"]["note"])}' if res["render"].get("note") else "") + '</footer>')
    pages["datasets.html"] = _shell("Elimination data and provenance", "".join(provenance))
    h.append('<footer>Descriptive EDA from measured points and source-reported values; no new model fitting. Human review pending.</footer>')
    pages["index.html"] = _shell("Elimination", "".join(h))
    pages["figure-guide.html"] = _shell("How to read the figures", back + '<div class="eyebrow">EDA figure review · Elimination</div><h1>How to read the figures</h1>'
                                        '<section class="panel" id="reading-map"><p class="muted">Each panel: what to look at, what can be read from it, and what it hands to '
                                        f'modeling (rules E0.11, {RULES_VERSION}).</p>' + _table(["Panel", "Look at", "Reading", "Hypothesis handed over"], READING_MAP, "res rmap") + '</section>')
    pages["conditions-and-species.html"] = _species_page(spt, back)
    pages["reported-parameters.html"] = _emr_page(res, back)
    for sp in sps:
        bs = [b for b in boards if b["species"] == sp]
        nf = len({f for b in bs for f in b["figs"].values()})
        studies = ", ".join(b["study"] for b in bs)
        body = [f'<nav><a href="index.html">← All species</a>{report_nav}'
                + "".join(f'<a href="#study-{_e(b["key"])}">{_e(b["study"])}</a>' for b in bs) + '</nav>',
                f'<div class="eyebrow">EDA figure review · Elimination</div><h1>{_e(sp)}</h1>',
                f'<p class="lead">Six questions on how the drug leaves the body, for {"study" if len(bs) == 1 else "studies"} {_e(studies)}. Each row gives the status, '
                'one conclusion, the evidence that explains it best, and what is missing.</p>',
                f'<p class="muted">{nf} new panels · plasma panels linked from Absorption and Distribution · Computed by host code from observed points; {FIT_NOTE} · '
                f'{_e(_engine(res))} · Human review pending</p>', _legend()]
        for b in bs:
            body.append(f'<section class="panel study" id="study-{_e(b["key"])}"><h2>{_e(b["study"])} · {_e(sp)}</h2><p class="muted">{_e(", ".join(b["datasets"]))}</p>'
                        + _card_html(b) + f'<div class="qchips">{_chips(b)}</div>' + "".join(_qrow_html(q, b["key"], out) for q in b["questions"] if q["shown"])
                        + _hrow_html(b) + '</section>')
            body.append(_points_html(b))
        pages[page_name(sp)] = _shell(f"Elimination · {sp}", "".join(body))
    res["presentation"] = {"species": [i for i, _ in entries], "figures": n_fig,
                           "thumbnails": list(dict.fromkeys(f for b in boards for f in b["figs"].values()))[:3]}
    return pages


# ---------------------------------------------------------------- report.html section, portal card, attach

def report_section(res, error=None):
    h = ['<section id="elimination"><h2>Elimination and metabolism: how does the drug leave?</h2>',
         '<p><b>Need to understand:</b> the dose-to-observed-AUC ratio in plasma, unchanged parent in urine and renal clearance, recovery by route, measured products and '
         f'what can be compared across species (rules {RULES_VERSION} items 29–36). Plasma panels are linked from absorption and distribution.</p>']
    if error is not None or not res:
        h.append(f'<p><b>Not generated:</b> {_e(error)}. The reason is recorded in elimination/error.json.</p></section>')
        return "".join(h)
    name = dist._board_namer(res["boards"])
    paragraphs = _overview_paras(res, res["boards"])
    if paragraphs:
        heading, observation = paragraphs[0]
        h.append(f'<p><b>{_e(heading)}.</b> {_e(observation)}</p>')
    h.append('<p><a href="elimination/index.html#hypotheses">Read the full findings</a></p><details><summary>Questions by experiment</summary><ul>')
    for b in res["boards"]:
        by = {}
        for q in b["questions"]:
            if q["shown"]:
                by.setdefault(q["status"], []).append(f'Q{q["q"]}')
        h.append(f'<li><a href="elimination/{page_name(b["species"])}#study-{_e(b["key"])}">{_e(name(b))}</a>: '
                 + "; ".join(f'{_e(s.lower())} {", ".join(by[s])}' for s in ab.ST_ORDER if by.get(s)) + '</li>')
    h.append('</ul></details><p><a href="elimination/index.html">Open the Elimination overview</a></p></section>')
    return "".join(h)


def add_to_portal(root):
    root = Path(root)
    try:
        if not (root / "elimination" / "index.html").exists():
            return False
        res = json.loads((root / "elimination" / "elimination.json").read_text(encoding="utf-8"))
        pres = res.get("presentation", {})
        n = pres.get("figures", 0)
        thumbs = "".join(f'<img src="elimination/{_e(s)}" alt="Preview of {_e(s)}" loading="lazy">' for s in pres.get("thumbnails", []))
        sp = ", ".join(f'{x["species"]} ({x["figures"]})' for x in pres.get("species", []))
        card = ('<!--ELIMINATION-CARD-START--><a class="category" id="ELIMINATION" href="elimination/index.html">'
                f'<span class="badge">{n} panels</span><h3>Elimination and metabolism</h3><p class="muted">Dose / observed AUC, urine and renal clearance, recovery, '
                f'products and in vitro. One page per species: {_e(sp)}.</p><div class="thumbs">{thumbs}</div><span class="open">View all {n} panels →</span></a><!--ELIMINATION-CARD-END-->')
        done = False
        for name in ("index.html", "human_review.html"):
            p = root / name
            if not p.exists():
                continue
            text = re.sub(r"<!--ELIMINATION-CARD-START-->.*?<!--ELIMINATION-CARD-END-->", "", p.read_text(encoding="utf-8"), flags=re.S)
            pos = ab._grid_end(text)
            if pos is None:
                continue
            p.write_text(text[:pos] + card + text[pos:], encoding="utf-8")
            done = True
        return done
    except Exception as exc:  # noqa: BLE001 - the portal must not fail because of this card
        try:
            (root / "elimination" / "portal_error.json").write_text(json.dumps({"error": repr(exc)}), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
        return False


def attach(root):
    """Build the Elimination category and add a short section to report.html. A failure never stops the EDA run."""
    root = Path(root)
    res, err = None, None
    try:
        res = build(root)
    except Exception as exc:  # noqa: BLE001 - recorded and shown
        err = exc
        (root / "elimination").mkdir(exist_ok=True)
        (root / "elimination" / "error.json").write_text(json.dumps({"error": repr(exc)}, ensure_ascii=False), encoding="utf-8")
    report = root / "report.html"
    body = report.read_text(encoding="utf-8") if report.exists() else '<html lang="en"><meta charset="utf-8"></html>'
    body = re.sub(r'<!--ELIMINATION-START-->.*?<!--ELIMINATION-END-->', '', body, flags=re.S)
    block = '<!--ELIMINATION-START-->' + report_section(res, err) + '<!--ELIMINATION-END-->'
    anchor = '<section><h2>Review issues</h2>'
    if anchor in body:
        body = body.replace(anchor, block + anchor, 1)
    elif '</html>' in body:
        body = body.replace('</html>', block + '</html>', 1)
    else:
        body += block
    report.write_text(body, encoding="utf-8")
    if res is not None:
        out = root / "elimination"
        for pg in out.glob("*.html"):
            s = pg.read_text(encoding="utf-8")
            updated = s.replace("<!--EM-NAV--><!--/EM-NAV-->", _report_nav(out))
            if updated != s:
                pg.write_text(updated, encoding="utf-8")
    add_to_portal(root)
    return root / "elimination"


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description=f"Build the elimination and metabolism EDA section (rules {RULES_VERSION})")
    parser.add_argument("root", type=Path)
    parser.add_argument("--attach", action="store_true", help="also add the section to report.html and the portal")
    args = parser.parse_args(argv)
    if args.attach:
        attach(args.root)
        res = json.loads((args.root / "elimination" / "elimination.json").read_text(encoding="utf-8"))
    else:
        res = build(args.root)
    print(json.dumps({"boards": len(res["boards"]), "figures": res.get("presentation", {}).get("figures"), "render": res["render"]["engine"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
