"""EDA Distribution section (items 24-28; rules version in rules/rules_manifest.json), host code only.

Reads an EDA run root (``source_tables.json``; optional ``distribution_config.json``) and writes ``<root>/distribution/``:

* ``distribution.json``   every computed value, label, reason and panel path;
* ``DIS*_*.png``          panels of guide figures 1a-5 (labels DIS-1a ... DIS-5, r1.5b numbering) and DIS-R; file names keep
                          the earlier panel keys (DIS1a = figures 1a/1b/1c, DIS4* = figure 3, DIS5* = figure 4, DIS6* = 2a/5);
* ``index.html``, ``species-*.html``  the Distribution category of the EDA review;
* ``distribution_config.template.json``  the run-configuration fields of rules section B.6 (physiology, organ weights,
  residual blood, B:P, IV mode overrides, target-binding declarations), plus optional prespecified animal-level
  organ/plasma ratio contrasts at two times. Nothing physiological is assumed by default.

Page structure follows the absorption pages: species -> study -> data card -> question rows Q1-Q7 -> working hypothesis.
Each question row has a status, one conclusion (what was seen; what it rests on; how far it reaches), the panel that
explains it best, and what is missing. The reading map of rules D0.11 is the figure -> look at -> reading ->
hypothesis chain; it is stored in READING_MAP and printed on the figure guide.

No PK model fitting, smoothing, back-extrapolation, AUMC, MRT, Vss or Kp at infinity (EDA004, rules D0.7). Formal exclusions come
only from T6, T7, T8, T9 and the reused T3p and T5, each with its premises. Descriptive readings never exclude.
The separate two-time animal-level t tests estimate a measured ratio change; they do not exclude a biological mechanism.
"""
from __future__ import annotations

import html
import itertools
import json
import math
import re
import sys
import statistics
from collections import Counter
from pathlib import Path
from statistics import mean, stdev, variance

try:  # inside the pipeline package
    from . import eda_absorption as ab
except Exception:  # noqa: BLE001 - standalone use next to eda_absorption.py
    import eda_absorption as ab  # type: ignore


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


RULES = _eda_common().rules_entry("distribution")  # the one rules version for this section: rules/rules_manifest.json
RULES_VERSION = RULES["version"]
FIT_NOTE = _eda_common().FIT_NOTE
COMMON = _eda_common()

VERSION = RULES.get("output_version") or "unrecorded"   # M3/L7: one version source, rules/rules_manifest.json (r1.6: EDA_DISTRIBUTION_R1_6_20261124)
RULES_R15 = "Distribution EDA rules r1.5 (deliverables/Distribution_EDA_20261121/EDA_distribution_rules_r1.5_rules_only_20261121.md)"

# ---------------------------------------------------------------- project settings (labelled as such on the pages)
TOL = 0.05                 # A0.4 project-set relative error for tabulated / digitized values without a reported error
SIGMA_IND = 0.15           # item 24 rule 3: per-point noise on ln C for individual data
SIGMA_GROUP_DEFAULT = 0.158  # item 24 rule 3: group means without SD and n
DIGIT_TERM = 0.05          # item 24 rule 3: digitization term for group means
SPLIT_R = 1.5              # item 24 rule 3: R >= 1.5 and z >= 2 -> FLATTENING
SPLIT_Z = 2.0
GM_R_CAUTION = 1.6         # GROUP_MEAN_CURVATURE_POSSIBLE below this R
MIN_SPLIT_POINTS = 5
NONLINEAR_CANDIDATE = "nonlinear elimination or binding"     # YAML candidates name (finding D2)
MIN_TEST_TIMES = 3          # T6 and T7, also after a removal (rule decision R2, 2026-11-24)
FAMILY_ALPHA = 0.05         # two-sided family-wise alpha (rule decision R4, 2026-11-24)
# r1.5b (2026-11-24): the flip-flop flag and its threshold moved to Absorption (EV/IV half-life ratio grades 0.80/1.25/2.0);
# Distribution passes only the IV reference window.
BORDERLINE_Z = 0.5         # r1.5 section 2.2: odd n and |z| within this of the threshold -> borderline
# M1: the screen constants live with the shared IV-window function; these names stay for the pages and must agree
assert (SPLIT_R, SPLIT_Z, MIN_SPLIT_POINTS, BORDERLINE_Z, SIGMA_IND, SIGMA_GROUP_DEFAULT, DIGIT_TERM) == (
    COMMON.WIN_SPLIT_R, COMMON.WIN_SPLIT_Z, COMMON.WIN_MIN_POINTS, COMMON.WIN_BORDERLINE_Z, COMMON.WIN_SIGMA_IND,
    COMMON.WIN_SIGMA_GROUP_DEFAULT, COMMON.WIN_DIGIT_TERM)
EARLY_MIX_H = 5 / 60       # EARLY_MIXING_POSSIBLE: a sample within 5 min of the end of dosing


def early_mixing(dt_after_end_h):
    """L6 (2026-11-24): the mixing caution is bounded exactly as "within 5 minutes after the end of dosing", inclusive of 5 min;
    the tolerance absorbs floating-point error from converting minutes and subtracting the infusion duration."""
    return dt_after_end_h is not None and dt_after_end_h <= EARLY_MIX_H + 1e-9
LLOQ_PROX = 3.0            # LLOQ_PROXIMAL: last point below 3 x LLOQ
BAND = (0.80, 1.25)        # dimensionless fold band
BAND_DIGITIZED = (0.72, 1.38)
KPUU_BAND = (0.5, 2.0)
T_QUANTILE = 0.977         # item 26 step 10: t quantile for z_crit with Welch-Satterthwaite df
NOISE_GATE_SIGMAS = 1.0    # description only: does a numerical T6/T7 contradiction found at ±TOL remain when every point
                           # is widened to ± this many item 24 sigmas on ln C (A0.3 BORDERLINE reading; labels are unchanged)
EARLY_SPREAD_FOLD = 3.0    # check first: per-animal Vc bounds taken at the same time differ by more than this fold
MATCH_REL, MATCH_ABS = 0.05, 0.02  # matched times across series (relative, hours)

ST_YES, ST_PART, ST_NO, ST_NA = COMMON.ST_YES, COMMON.ST_PART, COMMON.ST_NO, COMMON.ST_NA
ST_CODE = COMMON.ST_CODE
INK, INK2, MUTED, GRID, SURF = ab.INK, ab.INK2, ab.MUTED, ab.GRID, ab.SURF
BLUE, ORANGE, GREEN, PURPLE = ab.BLUE, ab.ORANGE, ab.GREEN, ab.PURPLE
RAMP = ab.RAMP
GRAY = "#8a9aa6"
_e, _f, _slug, _wb = COMMON._e, COMMON._f, COMMON.page_slug, COMMON._wb
species_group = ab.species_group

# ---------------------------------------------------------------- reader wording (distribution.json keeps the codes)
_WORDS = {
    "FLATTENING": "flattens", "STEEPENING": "steepens", "NONE_DETECTED": "no bend seen", "NOT_ASSESSABLE": "not assessable",
    "ROBUST": "holds without the first or the last point",
    "TWO_OR_MORE": "two or more phases", "TWO_OR_MORE_TENTATIVE": "a second phase that rests on one point", "ONE_APPARENT": "one phase",
    "NOT_LOG_CONVEX_DESCRIPTIVE": "a decline that steepens",
    "EXCLUDED_UNDER_STATED_ASSUMPTIONS": "contradicted", "NOT_EXCLUDED": "not contradicted", "CANNOT_ASSESS": "not assessable",
    "INDIVIDUAL": "one animal", "GEOMETRIC_MEAN_PROFILE": "geometric-mean profile", "HARMONIC_MEAN": "harmonic mean of the animals",
    "PASS": "passes", "VOLUME_BELOW_PLASMA": "below plasma volume", "DATA_ISSUE": "data issue",
    "SENSITIVITY_ONLY": "sensitivity result only", "BORDERLINE": "within noise", "SINGLE_POINT_SUPPORT": "rests on one point",
    "SAMPLING_SITE_EARLY": "early sample with the sampling site not arterial or not reported",
    "EARLY_MIXING_POSSIBLE": "sample within 5 min of the end of dosing (mixing may be incomplete)",
    "RESIDUE_UNRESOLVED": "predose residue unresolved; the Vc limit is kept as a sensitivity result",
    "LOOSE_BOUND": "loose bound (first sample late)", "WHOLE_BLOOD_BASIS": "whole-blood basis", "DIGITIZED": "digitized",
    "GROUP_MEAN": "group mean", "GROUP_MEAN_CURVATURE_POSSIBLE": "bend may come from averaging animals",
    "LLOQ_PROXIMAL": "last point close to the LLOQ", "DESTRUCTIVE_SAMPLING": "different animals at each time",
    "ACTIVE_MATERIAL": "antimicrobial activity; parent specificity not established", "ONGOING_INPUT": "ongoing IV input", "INFUSION_TIMING_UNKNOWN": "infusion end not reported", "TOTAL_RADIOACTIVITY": "total radioactivity", "SOURCE_CONFLICT": "source conflict noted upstream",
    "FU_OTHER_STUDY": "fu,p comes from another study", "FU_OTHER_SPECIES": "fu,p comes from another species",
    "NONLINEAR_BINDING": "fu,p changes with concentration", "FU_RANGE_NOT_COVERED": "the binding records do not span the whole PK concentration range",
    "RATIO_WITHIN_BAND": "the high/low ratio of dose-normalised concentrations stays within the band at every shared time",
    "RATIO_RISES_LATE_ABOVE_BAND": "the high/low ratio of dose-normalised concentrations rises above the band in the late part",
    "RATIO_BELOW_BAND": "the high/low ratio of dose-normalised concentrations is below the band at every shared time",
    "RATIO_CONSTANT_OUTSIDE_BAND": "the high/low ratio of dose-normalised concentrations is a near-constant fold outside the band",
    "RATIO_ABOVE_BAND_EARLY_THEN_FALLS": "the high/low ratio of dose-normalised concentrations is above the band early and then falls",
    "RATIO_MIXED": "the high/low ratio of dose-normalised concentrations shows no single shape",
    "DESCRIPTIVE_CONFOUNDED": "dose contrast between different animals or studies (ratios shown, no pattern label)",
    "NO_DIFFERENCE_SEEN": "no difference seen", "VARIABLE_WITHIN_WINDOW": "variable within the window", "TISSUE_NOT_FALLING": "tissue not falling",
    "SERIAL": "same animals", "DESTRUCTIVE": "different animals at each time", "RATIO_OF_MEANS": "ratio of means",
    "CONDITIONAL_ON_LABEL_IDENTITY": "holds if the animal labels are right", "CONDITIONAL_ON_FIXED_COHORT": "holds if the cohort is the same at every time",
    "INDIVIDUAL_IDENTITY_UNVERIFIED": "individual, identity not verified", "LOCAL_ROUTE": "dose given into this space",
    "MIXED": "no single pattern", "EXCLUDED": "contradicted", "UNKNOWN": "unknown", "MEASURED": "measured", "DERIVED": "derived", "QUANTIFIED": "quantified",
    "NOT_APPLICABLE": "not applicable", "NOT_DETERMINED": "not determined",
    "UNDEFINED": "no ratio", "NOT_FOUND": "not found", "NOT_REPORTED": "not reported", "NOT_STATED": "not stated",
    "IV_MODE_UNKNOWN": "not reported", "BOLUS": "bolus", "INFUSION": "infusion", "CONFOUNDED": "more than one thing differs",
    "CONDITION_NOT_IDENTIFIED": "condition not identified", "DIFFERENT_STUDIES": "different studies", "DOSE_BASIS_MISMATCH": "dose basis differs",
    "REPORTED_PARAMETERS": "reported parameters", "PK_OBSERVATIONS": "PK observations", "TISSUE_ACCUMULATES_MORE": "tissue accumulates more",
    "BLQ": "below the LLOQ", "ALQ": "above the upper limit",
}


def say(code):
    """Reader wording for a stored code; unknown codes are shown in lower case with spaces."""
    if code is None:
        return "—"
    c = str(code)
    if c in _WORDS:
        return _WORDS[c]
    if c.startswith("DEPENDS_ON_"):
        return "rests on the " + c[len("DEPENDS_ON_"):].replace("_AND_", " and the ").replace("_", " ").lower()
    return c.replace("_", " ").lower() if c.isupper() or "_" in c else c


def yes_no(words):
    """Species-page table (George 2026-11-25): the single-exponential and only-slows checks as a plain answer."""
    w = str(words or "")
    if w.startswith("contradicted"):
        if "noise setting" in w:
            return "No (beyond ±5 % and beyond assay noise)"
        if w.endswith("only"):
            return "Not clearly (beyond ±5 % only, within assay noise)"
        return "No (beyond ±5 %)"
    if w == "rests on one point":
        return "Not decided (one point)"
    if w.startswith("no contradiction"):
        return "Yes"
    if w in ("not run", "—", ""):
        return "Not checked"
    return w


def check_words(r, k):
    """T6 / T7 result of one profile in words. k is 't6' or 't7'. A result that rests on project tolerances alone is a numerical
    check, not a formal test: its label stays CANNOT_ASSESS and the numerical finding is described."""
    lab, fl = r.get(k + "_label"), r.get(k + "_flags") or []
    sens = r.get(k + "_sensitivity_label")
    if sens is not None:
        if sens == "EXCLUDED_UNDER_STATED_ASSUMPTIONS":
            if r.get(k + "_at_noise") is None:
                return f"contradicted at ±{100 * TOL:g} %"
            return f"contradicted at ±{100 * TOL:g} % " + ("and at the noise setting" if r[k + "_at_noise"] else "only")
        if "SINGLE_POINT_SUPPORT" in fl:
            return "rests on one point"
        return f"no contradiction at ±{100 * TOL:g} %"
    if lab in (None, "CANNOT_ASSESS"):
        return "not run"
    if lab == "EXCLUDED_UNDER_STATED_ASSUMPTIONS":
        return "contradicted"
    if "SINGLE_POINT_SUPPORT" in fl:
        return "rests on one point"
    return "no contradiction"


_CODE = re.compile(r"\b[A-Z]{2,}(?:_[A-Z]+)+\b|\b(?:FLATTENING|STEEPENING|ROBUST|PASS|RISING|FALLING|INSIDE|ABOVE|BELOW|UNRESOLVED|STABLE|CHANGING|"
                   r"MIXED|EXCLUDED|MEASURED|DERIVED|UNKNOWN|QUANTIFIED|UNDEFINED|SERIAL|DESTRUCTIVE)\b")


def say_codes(text):
    """Stored codes inside a sentence or a table cell, in reader wording (the page; distribution.json keeps the codes)."""
    return _CODE.sub(lambda m: say(m.group(0)), text) if isinstance(text, str) else text


def _join_and(xs):
    xs = list(xs)
    return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " and " + xs[-1]


def _count_of(n, total, what="profile"):
    return f"{n} of {total} {what}{'s' if total != 1 else ''}"


def _dur(h):
    return f"{_f(h * 60)} min" if h < 1 else f"{_f(h)} h"


def clock_text(t_after_end, ends=None):
    """S13 one clock in text (George 2026-11-25): a time computed after the end of the input is reported after the START of
    dosing, with the time after the end of infusion in brackets. ends: the input lengths of the profiles concerned (None =
    unknown). Bolus: the two clocks agree. Several lengths: the after-end time, then the range of start-of-dosing times."""
    if t_after_end is None:
        return "—"
    hs = sorted({round(float(e), 6) for e in (ends or []) if e is not None})
    if not hs or hs == [0.0]:
        return f"{_f(t_after_end)} h"
    if len(hs) == 1:
        return f"{_f(t_after_end + hs[0])} h (end of infusion + {_dur(t_after_end)})"
    return f"end of infusion + {_dur(t_after_end)} ({_f(t_after_end + hs[0])}–{_f(t_after_end + hs[-1])} h after the start of dosing)"


def _board_ends(b, sids=None):
    return [x.get("input_end_h") for x in b.get("item25", []) if sids is None or x["sid"] in sids]


def _same_time_text(vs, ends=None):
    """'0.0167 h', or '0.0083–0.0334 h' when the animals grouped within the time-match tolerance were sampled at different times."""
    rng = vs.get("same_time_range_h") or [vs["same_time_h"]] * 2
    if rng[1] - rng[0] > 1e-9:
        return f"{clock_text(rng[0], ends)} to {clock_text(rng[1], ends)}" if ends and any(ends) else f"{_f(rng[0])}–{_f(rng[1])} h"
    return clock_text(vs["same_time_h"], ends)


def vc_summary(okb):
    """Item 25 bounds of one board. With three or more animals each bound applies to its own animal, so the board reports the
    median and the range instead of the smallest value (every animal lies below its own bound, hence the median animal lies at
    or below the median bound)."""
    if not okb:
        return None
    vals = sorted(okb, key=lambda x: x["vc_upper_bound_l_per_kg"])
    m = vals[0]
    out = {"kind": "SINGLE", "n": len(okb), "min": m["vc_upper_bound_l_per_kg"], "max": vals[-1]["vc_upper_bound_l_per_kg"],
           "min_label": m["label"], "min_time_h": m["sample_time_h"]}
    if len(okb) >= 3 and all(x.get("population_meaning") == "INDIVIDUAL" for x in okb):
        v = [x["vc_upper_bound_l_per_kg"] for x in vals]
        k = len(v)
        med = v[k // 2] if k % 2 else (v[k // 2 - 1] + v[k // 2]) / 2
        groups = []
        for x in okb:
            g = next((g for g in groups if _match(g[0]["sample_time_h"], x["sample_time_h"])), None)
            (g.append(x) if g else groups.append([x]))
        big = max(groups, key=len)
        bv = [x["vc_upper_bound_l_per_kg"] for x in big]
        # round 3: times grouped within the match tolerance are reported as their range, not as the first animal's time
        bt = [x["sample_time_h"] for x in big]
        out.update(kind="PER_ANIMAL", median=med, same_time_h=big[0]["sample_time_h"], same_time_n=len(big),
                   same_time_range_h=[min(bt), max(bt)],
                   same_time_fold=(max(bv) / min(bv)) if len(big) >= 3 else None,
                   other_times=[{"label": x["label"], "t": x["sample_time_h"]} for x in okb if x not in big])
    return out

def animal_spread(refs):
    """Between-animal spread in individual IV profiles given the same dose: the fold range of the concentrations at the first time
    shared by three or more animals and at the last time shared by all, and of the trapezoid area between the times every animal
    was sampled at. A description for placing between-animal variability; nothing is fitted."""
    ss = [s for s in refs if s["level"] == "INDIVIDUAL" and s["analyte"] == "PARENT" and s.get("dose") and s.get("uf") and not s["unbound"]]
    if len(ss) < 3 or len({(s["dose"], s["matrix_class"], s["iv_mode"], COMMON.input_nominal(s)) for s in ss}) != 1:
        return None
    # one common clock for the descriptive grid (round 3): the table-level input, so animals keep their shared sampling times
    lag = (COMMON.input_nominal(ss[0]) or 0) if ss[0]["iv_mode"] == "INFUSION" else 0   # times after the end of dosing, as in items 24 and 25
    prof = [[(p["t"] - lag, p["c"] * s["uf"]) for p in _q(s["points"]) if p["t"] - lag > 0] for s in ss]
    times = []
    for pts in prof:
        for t, _ in pts:
            if not any(_match(t, u) for u in times):
                times.append(t)
    at = lambda pts, t: next((c for u, c in pts if _match(u, t)), None)  # noqa: E731
    rows = []
    for t in sorted(times):
        cs = [c for c in (at(pts, t) for pts in prof) if c]
        if len(cs) >= 3:
            rows.append({"t": t, "n": len(cs), "fold": max(cs) / min(cs)})
    if len(rows) < 2:
        return None
    common = [r for r in rows if r["n"] == len(ss)]
    out = {"n": len(ss), "first": rows[0], "late": common[-1] if common and common[-1]["t"] > rows[0]["t"] else rows[-1], "auc": None}
    if len(common) >= 3:
        a, z = common[0]["t"], common[-1]["t"]
        aucs = []
        for pts in prof:
            w = [(t, c) for t, c in pts if (t >= a or _match(t, a)) and (t <= z or _match(t, z))]
            aucs.append(sum((t2 - t1) * (c1 + c2) / 2 for (t1, c1), (t2, c2) in zip(w, w[1:])))
        ln = [math.log(x) for x in aucs]
        m = sum(ln) / len(ln)
        var = sum((x - m) ** 2 for x in ln) / (len(ln) - 1)
        out["auc"] = {"from_h": a, "to_h": z, "fold": max(aucs) / min(aucs), "cv_pct": 100 * math.sqrt(math.exp(var) - 1)}
    return out


def _species_iv_words(xs):
    return _join_and([f"{x['study']} ({x['n']} IV profile{'s' if x['n'] != 1 else ''}"
                      + (f", {', '.join(_f(d) for d in x['doses'])} mg/kg" if x["doses"] else "") + f", {x['level']})" for x in xs])


def _dur(h):
    """A duration in words: minutes below one hour, hours otherwise."""
    return f"{_f(h * 60)} min" if h < 1 else f"{_f(h)} h"


def _cap(text):
    """Capital first letter, except for symbols that are written in lower case (fu,p)."""
    return text if text.startswith(("fu,", "ka ", "tlag")) else text[0].upper() + text[1:]


def _names_of(rs, k=3):
    labs = [r["label"] for r in rs]
    return _join_and(labs) if len(labs) <= k else ", ".join(labs[:k]) + f" and {len(labs) - k} more"


_CHECK_OPEN = ("not reported", "different animals", "total radioactivity", "metabolite or mixed", "predose sample present", "requires review")


def _check_open(v):
    """A check is open when its finding leaves an alternative reading of the bend standing."""
    return any(w in str(v).lower() for w in _CHECK_OPEN)


def _open_words(k, v):
    """One open check in words: the part of the finding that is open, named by its check when the part alone does not say what it is about."""
    frag = next((p for p in str(v).split("; ") if _check_open(p)), str(v))
    return f"{k} {frag}" if frag.startswith("not ") else frag if k.startswith("early mixing") else f"{k}: {frag}"



DEFAULT_CONFIG = {
    "_about": (f"Run configuration for the Distribution section (rules {RULES_VERSION}, section B.6). Every value needs a source. "
               "Leave a field empty when no sourced value exists: the dependent check is then reported as not assessable."),
    "reference_volumes_l_per_kg": {
        "_example_Rat": {"plasma": None, "plasma_lower": None, "extracellular": None, "total_water": None, "source": ""}},
    "organ_weights_g_per_kg": {
        "_example_Rat": {"Kidney": None, "Liver": None, "source": "", "matched_on": "species, strain, age, body weight / not matched",
                         "same_study": False}},
    "residual_blood": {"V_r": {}, "hct": {}, "bp_upper": None, "bp": {}, "source": ""},
    "iv_mode": {"_example_T0001": {"mode": "BOLUS or INFUSION", "infusion_h": None, "source": ""}},
    "target_binding_declared": {"_example_DrugName": {"declared": "YES", "source_quote": ""}},
    "evidence_by_dataset": {"_example_T0001": {"source": "source record or quotation", "metadata": {}}},
    "perfused": {"_example_T0001": {"perfused": "YES or NO", "source": ""}},
    "tissue_ratio_comparisons": {
        "_example_kidney_change": {"study": "STUDY_ID", "species": "Rat", "organ": "Kidney", "times_h": [1, 4],
            "tissue_series": ["kidney_animal1:conc", "kidney_animal2:conc"],
            "plasma_series": ["plasma_animal1:conc", "plasma_animal2:conc"],
            "design": "LONGITUDINAL_PAIRED or INDEPENDENT_COHORTS", "prespecified": False,
            "within_animal_matrix_pairing_verified": False, "time_design_verified": False,
            "source": "source evidence for animal/matrix/time design", "prespecification_source": "dated analysis plan and selected organ/times"}},
    "tissue_ratio_test_alpha": 0.05,
    "optional_figures": {"_about": "r1.5: the Vc bound is reported in Table 3; set true to also draw it (panel key DIS3)", "DIS3": False},
}


def _num(v):
    return COMMON.to_float(v)   # round 3 (2026-11-24): the one number reader, after the shared ingress normalisation


def load_config(root):
    return COMMON.load_section_config(root, "distribution_config.json", DEFAULT_CONFIG)


# ---------------------------------------------------------------- parsing helpers

# 2026-11-24 review (parser): the dispersion is a whole number, exponent included (shared NUMBER pattern)
_PM = re.compile(rf"^\s*({COMMON.NUMBER})\s*(?:±|\+/-|\+-)\s*({COMMON.NUMBER})(?![\d.eE])\s*(?:\((\d+)\))?\s*$")
_N_SUFFIX = re.compile(rf"^\s*({COMMON.NUMBER})\s*\((\d+)\)\s*$")
_BLQ_TXT = re.compile(r"<\s*ll?oq|\bblq\b|below (?:the )?(?:limit of quantification|lloq)|^<\s*\d", re.I)


def parse_value(raw, status=None):
    """Return (value, sd, n, status) from a cell: numbers, 'mean ± SD', 'mean±SD(n)', '<LLOQ'. Missing -> None.
    L1 (2026-11-24): a cell the source marks REPORTED_ZERO_PREDOSE keeps that status (value 0), as in Absorption."""
    if str(status or "").strip().upper() == COMMON.PREDOSE_ZERO:
        x = _num(raw)
        return (0.0, None, None, COMMON.PREDOSE_ZERO) if x == 0 else (None, None, None, "MISSING")
    st = COMMON.assay_qualifier(status, raw)
    if st and st != "BLQ":
        return None, None, None, st
    if st == "BLQ" or (isinstance(raw, str) and _BLQ_TXT.search(raw.strip())):
        bound = COMMON.printed_assay_bound(raw)
        lim = (bound["threshold"] if bound and bound["relation"] in ("<", "<=", "≤") and
               not bound["unit_as_printed"] else None)
        return lim, None, None, "BLQ"
    x = _num(raw)
    if x is not None:
        return x, None, None, "QUANTIFIED"
    if isinstance(raw, str):
        s = COMMON.normalize_numeric_text(raw).strip()
        pm = COMMON.mean_dispersion(s)          # round 3: the shared 'mean ± dispersion' reader, powers of ten included
        if pm and (not pm[2] or re.fullmatch(r"\((\d+)\)", pm[2])):
            n_tail = re.fullmatch(r"\((\d+)\)", pm[2]) if pm[2] else None
            return pm[0], pm[1], (int(n_tail.group(1)) if n_tail else None), "QUANTIFIED"
        m = _PM.match(s)
        if m:
            return float(m.group(1)), float(m.group(2)), (int(m.group(3)) if m.group(3) else None), "QUANTIFIED"
        m = _N_SUFFIX.match(s)
        if m:
            return float(m.group(1)), None, int(m.group(2)), "QUANTIFIED"
        nums = re.findall(r"(?<![\w.])(\d+(?:\.\d+)?)(?![\w.])", s.split("(")[0])
        # 2026-11-24 review: a list of individual values never carries a dispersion sign ('1,250 ± 30' is not 1, 250 and 30)
        if len(nums) >= 2 and "," in s and not re.search(r"[a-zA-Z±]|\+/-|\+-", s.split("(")[0]):
            vals = [float(v) for v in nums]
            m2 = re.search(r"\((\d+)\)\s*$", s)
            return sum(vals) / len(vals), None, int(m2.group(1)) if m2 else len(vals), "QUANTIFIED"
    return None, None, None, "MISSING"


def time_from_header(text):
    """'5 min' -> 0.0833; '45 min' -> 0.75; '6 h' -> 6; '24 hr' -> 24; else None."""
    s = str(text or "").lower()
    m = re.search(r"(\d+(?:\.\d+)?)\s*(min|minutes?|h|hr|hrs|hours?|d|days?)\b", s)
    if not m:
        return None
    v, u = float(m.group(1)), m.group(2)
    return v / 60 if u.startswith("min") else v * 24 if u.startswith("d") else v


_UNIT = {"mg/l": 1.0, "µg/ml": 1.0, "ug/ml": 1.0, "μg/ml": 1.0, "mcg/ml": 1.0, "mg/liter": 1.0, "µg/l": 1e-3, "ug/l": 1e-3,
         "ng/ml": 1e-3, "ng/l": 1e-6, "mg/ml": 1e3, "µg/g": 1.0, "ug/g": 1.0, "μg/g": 1.0, "mg/kg": 1.0, "ng/g": 1e-3,
         "µg eq/g": 1.0, "µg eq/ml": 1.0, "µg/organ": None}


def unit_factor(unit):
    """Factor to mg/L (mg/kg for tissue; 1 g taken as 1 mL, rules D0.8). None when not convertible."""
    u = str(unit or "").strip().lower().replace(" ", "").replace("μ", "µ").replace("liter", "l")
    u = re.sub(r"^ug", "µg", u)
    for k, v in _UNIT.items():
        if u == k.replace(" ", ""):
            return v
    return None


_SP_HEAD = COMMON.SPECIES          # L4: the shared registry (same list object as Absorption's)


def species_in(text):
    t = str(text or "").lower()
    for name, pat in _SP_HEAD:
        if re.search(pat, t):
            return name
    return None


# ---------------------------------------------------------------- matrix classification (rules D0.8)

REF_CLASSES = ("PLASMA", "SERUM", "WHOLE_BLOOD")
_ORGANS = ["gall bladder", "bone marrow", "lymph node", "caecum", "cecum", "colon", "rectum", "duodenum", "jejunum", "ileum",
           "oesophagus", "esophagus", "salivary gland", "skeletal muscle", "kidney", "liver", "lung", "heart", "spleen", "brain", "muscle", "thigh", "skin", "fat", "adipose", "bone", "intestine",
           "stomach", "lymph node", "testis", "ovary", "uterus", "pancreas", "adrenal", "thyroid", "eye", "thymus", "prostate",
           "bladder", "placenta", "bone marrow", "diaphragm", "aorta", "epididymis", "pituitary", "tongue", "trachea", "cartilage"]


def classify_matrix(text):
    """Return (matrix_class, organ, notes). Classes of D0.8 plus EXCRETA (urine, faeces, bile, cagewash) and OTHER_FLUID."""
    t = str(text or "").lower().replace("tyroid", "thyroid").replace("mesentric", "mesenteric")
    if not t or t in ("not_found", "mixed"):
        return "UNKNOWN", None, []
    if re.search(r"fetal|foetal|amniotic", t):
        return "OTHER_FLUID", "fetal/amniotic", []
    if re.search(r"urine|cagewash|faec|fece|feces|carcass|expired", t):
        return "EXCRETA", None, []
    if re.search(r"\bbile\b", t):
        return "EXCRETA", "bile", []
    if re.search(r"microdialys|dialysate|interstitial", t):
        return "ISF_MICRODIALYSIS", None, []
    if re.search(r"\belf\b|epithelial lining|lining fluid|\bbal\b", t):
        return "ELF", "ELF", (["UREA"] if "urea" in t else [])
    if re.search(r"\bcsf\b|cerebrospinal", t):
        return "CSF", "CSF", []
    if re.search(r"macrophage|\bcells?\b|leukocyte|neutrophil", t):
        return "CELLS", "cells", []
    for o in _ORGANS:
        if re.search(r"\b" + o + r"s?\b", t):
            return "TISSUE_HOMOGENATE", o.capitalize(), []
    if re.search(r"homogenate|tissue", t):
        return "TISSUE_HOMOGENATE", None, []
    if re.search(r"whole blood|\bblood\b", t) and "plasma" not in t:
        return "WHOLE_BLOOD", None, []
    if "serum" in t:
        return "SERUM", None, []
    if "plasma" in t:
        return "PLASMA", None, []
    if re.search(r"aqueous|vitreous|synovial|pleural|peritoneal|exudate|tissue fluid|blister", t):
        return "OTHER_FLUID", None, []
    return "UNKNOWN", None, []


def analyte_of(text):
    t = str(text or "").lower()
    if re.search(r"radioactiv|\b14c\b|\[14c\]|µg ?eq|ug ?eq|dpm", t):
        return "TOTAL_RADIOACTIVITY"
    if re.search(r"\b(?:free target|total target|target protein|drug.target complex|ligand.target complex)\b", t):
        return "TARGET_OR_COMPLEX"
    if re.search(r"antimicrobial activity|antibacterial activity|active material|bioassay|microbiolog", t):
        return "ACTIVE_MATERIAL"
    if re.search(r"metabolite|h-\d{3,}", t):
        return "METABOLITE_OR_MIXED"
    return "PARENT"


# ---------------------------------------------------------------- data card fields

def _dose(entry):
    meta = entry.get("metadata", {})
    factors = {"mg/kg": 1, "ug/kg": .001, "µg/kg": .001, "ng/kg": 1e-6, "g/kg": 1000}
    if _ongoing_input(entry):
        return None, "compound or ongoing input; no single total dose"
    d = meta.get("dose")
    if isinstance(d, dict) and d.get("status") == "SOURCE_STATED":
        factor = factors.get(str(d.get("unit", "")).lower().replace("μ", "µ").replace(" ", ""))
        x = _num(d.get("value"))
        if factor and x is not None and x > 0:
            return x * factor, "metadata.dose"
        return None, "nonpositive or incompatible source-stated dose"
    for key in ("dose_mg_kg", "dose_mg_per_kg"):        # round 3: the structured table-level dose before any prose
        x = _num(meta.get(key))
        if x is not None and x > 0:
            return x, "metadata." + key
    for field, value in (("title", entry.get("title")), ("dosing_regimen", meta.get("dosing_regimen")), ("notes", entry.get("notes"))):
        matches = re.findall(r"(?<![\w.-])(\d+(?:\.\d+)?)\s*(mg|[uµμ]g|ng|g)/kg\b(?!\s*/\s*(?:day|h(?:r|our)?))", str(value or ""), re.I)
        doses = {float(v) * factors[u.lower().replace("μ", "µ") + "/kg"] for v, u in matches if float(v) > 0}
        if len(doses) == 1:
            return doses.pop(), field
        if len(doses) > 1:
            return None, "multiple doses in source text"
    return None, "NOT_FOUND"


_text = COMMON.entry_text


def _ongoing_input(entry):
    return COMMON.ongoing_input(entry)          # M1: one parser for both modules

def _regimen(entry):
    """Source regimen identity; loading dose and rate are never collapsed into one dose."""
    meta = entry.get("metadata", {})
    text = _text(entry)
    loading = _num(meta.get("loading_dose_mg_kg"))
    rate = _num(meta.get("infusion_rate_mg_kg_h"))
    if loading is None:
        m = re.search(r"([\d.]+)\s*mg/kg\s*(?:loading|(?:iv )?bolus)", text, re.I)
        loading = float(m.group(1)) if m else None
    if rate is None:
        m = re.search(r"([\d.]+)\s*mg/kg/(?:h|hr|hour)\b", text, re.I)
        rate = float(m.group(1)) if m else None
    return {"source_text": meta.get("dosing_regimen", ""), "loading_dose_mg_kg": loading,
            "infusion_rate_mg_kg_h": rate, "infusion_start_h": _num(meta.get("infusion_start_h")), "administration_method": meta.get("administration_method"), "ongoing_input": _ongoing_input(entry)}


def _sample_size(text):
    """Preserve an n range; never assign its lower bound to every time. L2 (2026-11-24): the shared reader in eda_common."""
    n, rng, _ = COMMON.sample_size(text)
    return n, rng


def iv_mode(entry, cfg):
    """Return (mode, infusion_h, source). Modes: BOLUS, INFUSION (with end), ONGOING_INPUT, INFUSION_TIMING_UNKNOWN, IV_MODE_UNKNOWN.
    M1 (2026-11-24): the shared dosing clock in eda_common, also used by Absorption."""
    return COMMON.iv_dosing(entry, cfg)


def iv_mode_column(entry, cfg, column):
    """Round 3: the dosing clock of one concentration column (its own input duration when the input gives one)."""
    return COMMON.iv_dosing(entry, cfg, column)


def _local_route(entry):
    """Intratracheal / inhaled / intrathecal dosing (rules D0.2 LOCAL_ROUTE when the dosed site is sampled)."""
    t = (_text(entry) + " " + str(entry.get("metadata", {}).get("route_detail", ""))).lower()
    if re.search(r"\bit\b|intratrache|inhal|aerosol|nebuli|intrapulmon", t):
        return "LUNG"
    if re.search(r"intrathecal|intraventricular|\bicv\b", t):
        return "CNS"
    return None


def _design(text, level):
    t = str(text or "").lower()
    if re.search(r"terminal sampling|terminal cohorts|destructively sampled|killed|sacrific|euthan|different (?:group|animals)|one \w+ per time|each time point (?:is )?a different", t):
        return "DESTRUCTIVE"
    if level == "INDIVIDUAL" or re.search(r"serial|same animals?|cannula", t):
        return "SERIAL"
    return "UNKNOWN"


def _n_by_time(text):
    """'n=3 at 3 h, n=6 at 6 h' -> {3: 3, 6: 6}."""
    out = {}
    for m in re.finditer(r"n\s*=\s*(\d+)\s*at\s*(\d+(?:\.\d+)?)\s*(h|min)", str(text or "").lower()):
        out[round(float(m.group(2)) / (60 if m.group(3) == "min" else 1), 6)] = int(m.group(1))
    return out


def _one_per_time(text):
    return bool(re.search(r"one (?:\w+ )?(?:animal|dog|rat|mouse|monkey|rabbit) per time", str(text or "").lower()))


def _mean_type(text):
    s = str(text or "").lower()
    g, a = "geometric mean" in s, "arithmetic mean" in s
    return "UNKNOWN" if g and a else "GEOMETRIC" if g else "ARITHMETIC" if a else "NOT_REPORTED"


def _target_declared(entry, cfg):
    drug = str(entry.get("metadata", {}).get("drug", "") or "")
    for k, v in (cfg.get("target_binding_declared") or {}).items():
        if k and (k.lower() in drug.lower() or k == entry.get("dataset_id")) and str(v.get("declared", "")).upper() == "YES":
            return "YES", v.get("source_quote", "")
    return "NOT_STATED", ""


def _occasion(text):
    t = str(text or "").lower()
    m = re.search(r"\bday\s*(\d+)\b", t)
    if re.search(r"steady[- ]state|last dose|after (?:the )?(?:second|third|fourth|final|last|\d+(?:nd|rd|th)) dose|repeated[- ]dos|repeat dos|multiple dos|q\d+h|daily for", t):
        return ("LATER_DOSE", int(m.group(1)) if m else None)
    if m and int(m.group(1)) > 1:
        return ("LATER_DOSE", int(m.group(1)))
    return ("FIRST_DOSE", 1)


# ---------------------------------------------------------------- extraction: one series per matrix, animal, dose or species

def _level(entry, text):
    return COMMON.series_level(entry)           # M1: one record-level rule for the IV window in both modules

def _card_base(entry, cfg):
    meta = entry.get("metadata", {})
    text = _text(entry)
    dose, dose_from = _dose(entry)
    rc = meta.get("route_class", "NOT_FOUND")
    mode, inf_h, mode_src = iv_mode(entry, cfg) if rc == "IV" else ("NOT_IV", None, "")
    level = _level(entry, text)
    occ, day = _occasion(text)
    tb, tbq = _target_declared(entry, cfg)
    perf = (cfg.get("perfused") or {}).get(entry["dataset_id"], {}).get("perfused")
    if not perf:
        perf = "YES" if re.search(r"(?<!not )perfused", text.lower()) else "NOT_REPORTED"
    return {
        "dataset_id": entry["dataset_id"], "title": entry.get("title", ""), "study": ",".join(entry.get("study_source_ids", [])) or "NOT_FOUND",
        "study_display_name": meta.get("study_display_name") or entry.get("study_display_name"),
        "species_text": meta.get("species", "NOT_FOUND"), "drug": meta.get("drug", "NOT_FOUND"),
        "route_class": rc, "route_detail": meta.get("route_detail", "NOT_FOUND"), "route_source": meta.get("route"), "iv_mode": mode, "infusion_h": inf_h,
        "time_origin_source": COMMON.time_origin(entry), "time_origin_basis": COMMON.time_origin_record(entry)[1],
        "input_contract_issues": COMMON.input_contract(entry)["issues"],
        "iv_mode_source": mode_src, "regimen": _regimen(entry), "n_range": meta.get("n_range") or _sample_size(text)[1], "assay": meta.get("assay", ""), "assay_method": meta.get("assay_method", ""), "analyte_role": meta.get("analyte_role", ""), "source_refs": entry.get("source_refs", []), "source_item_id": entry.get("source_item_id"), "local": _local_route(entry), "dose": dose, "dose_from": dose_from,
        "dose_basis": meta.get("dose_basis", "NOT_FOUND"), "level": level, "design": _design(text, level),
        # M6: a supported upper limit on the delivered dose (mg/kg), when the source gives one
        "dose_upper_mg_per_kg": _num(meta.get("dose_upper_mg_per_kg") or meta.get("dose_upper_mg_kg")),
        "mean_type": _mean_type(text) if level == "GROUP_MEAN" else "n/a",
        # 2026-11-24 (rule decision R1): scale of a reported SD or SE; "LN" only when the source gives it on the ln C scale
        "dispersion_scale": "LN" if str(meta.get("dispersion_scale") or "").strip().upper() in ("LN", "LOG", "LN_C", "NATURAL_LOG") else "CONCENTRATION",
        "digitized": meta.get("observation_source") == "DIGITIZED_FROM_FIGURE" or "digitiz" in text.lower(),
        "occasion": occ, "occasion_day": day, "target_binding": tb, "target_binding_quote": tbq, "perfused": perf,
        # rule decision R10 (2026-11-24): a quantified predose value. T7 stays assessable only when the source attributes the residue
        # to completed input into the central compartment of the same linear system; T6 keeps a sensitivity reading only under a
        # stated residue assumption
        "predose_residue_central_completed": (meta.get("predose_residue_central_input_completed") is True
                                              and bool(str(meta.get("predose_residue_source") or "").strip())),
        "predose_residue_assumption": str(meta.get("predose_residue_assumption") or "").strip() or None,
        "endogenous": (meta.get("endogenous") is True or bool(re.search(r"(?<!not )(?<!non-)\bendogenous\b", text + " " + str(meta.get("analyte", "")), re.I))),
        "interval_h": _num(meta.get("dosing_interval_h")),
        "equilibrated": meta.get("equilibrated") is True,
        "regimen_comparable": meta.get("regimen_comparable") is True,
        "steady_state": meta.get("steady_state") is True or bool(re.search(r"(?<!not at )(?<!not )\bsteady[- ]state\b", text, re.I)),
        "tissue_fu": meta.get("tissue_fu") or {},
        "sampling_dependence": meta.get("sampling_dependence"),
        # R7 item 6: the T3p reuse needs independent dose groups at one time point (or a valid paired method)
        "dose_group_dependence": meta.get("dose_group_dependence"),
        "exchange_premises": meta.get("exchange_premises") or {},
        "sampling_site": meta.get("sampling_site", "NOT_REPORTED"),
        "condition": meta.get("condition") or meta.get("treatment_group"),
        "concentration_basis": meta.get("concentration_basis", ""),
        "matrix_text": meta.get("matrix", "NOT_FOUND"), "matrix_category": meta.get("matrix_category", "NOT_FOUND"),
        "notes": html.unescape(str(entry.get("notes") or "")).strip(), "analyte_text": meta.get("analyte", ""),
        "restrictions": [o.get("operation") for o in entry.get("operation_restrictions") or []],
        "source_conflicts": _conflicts(entry),
        "matching_identity": {k: meta.get(k, entry.get(k)) for k in (
            "cohort", "cohort_id", "arm", "arm_id", "experiment_arm", "experiment_arm_id",
            "group", "group_id", "animal_id", "subject_id", "individual_id")
            if meta.get(k, entry.get(k)) not in (None, "", "NOT_FOUND", "NOT_REPORTED")},
    }


_CONFLICT_OPS = ("PK_MODELING", "NCA", "TIME_AXIS_SELECTION", "CROSS_MATRIX_CONVERSION", "LONGITUDINAL_JOIN", "CROSS_TABLE_LINKAGE")


def _conflicts(entry):
    """Source conflicts recorded upstream that touch concentration-time reading (shown as a caveat, never an exclusion)."""
    out = []
    for o in entry.get("operation_restrictions") or []:
        if o.get("operation") not in _CONFLICT_OPS:
            continue
        for r in o.get("reasons") or []:
            r = str(r)
            if re.match(r"[A-Z0-9_]*CONFLICT", r) and r not in out:
                out.append(r)
    return out


def _new_series(base, sid, label, matrix_text, species_txt, unit, dose=None, animal=None):
    mclass, organ, mnotes = classify_matrix(matrix_text)
    s = dict(base)
    sp = species_in(species_txt) or species_group(base["species_text"])
    s.update({"sid": sid, "label": label, "matrix_label": str(matrix_text), "matrix_class": mclass, "organ": organ or (
        mclass.replace("_", " ").title() if mclass not in REF_CLASSES else mclass.title()), "species": sp, "unit": unit,
        "uf": unit_factor(unit), "animal": animal, "points": [], "scheduled_times": [], "flags": []})
    if dose is not None:
        s["dose"] = dose
    s["analyte"] = analyte_of(" ".join([str(unit), str(label), str(base.get("analyte_text", ""))]))
    if s["analyte"] == "PARENT" and not re.search(r"\bparent\b", str(label), re.I):
        s["analyte"] = analyte_of(base.get("title", ""))
    if str(base.get("analyte_role", "")).upper() == "ACTIVE_MATERIAL" or re.search(r"microbiolog|bioassay", str(base.get("assay", "")), re.I):
        s["analyte"] = "ACTIVE_MATERIAL"
        s["flags"].append("ACTIVE_MATERIAL")
    s["elf_correction"] = ("UREA" if ("UREA" in mnotes or re.search(r"urea", base["notes"].lower() + base["title"].lower())) else "NOT_REPORTED") \
        if mclass == "ELF" else "n/a"
    basis = " ".join(str(x or "") for x in (label, matrix_text, base.get("concentration_basis"), base.get("analyte_text")))
    s["unbound"] = bool(re.search(r"\bunbound\b|\bfree (?:drug|plasma|concentration)\b", basis, re.I))
    s["recovery_calibrated"] = "n/a"
    if mclass == "ISF_MICRODIALYSIS":
        recovery = " ".join((str(matrix_text), base["notes"]))
        corrected = re.search(r"\brecovery[- ]corrected\b|\bcorrected for (?:probe |in vivo )?recovery\b", recovery, re.I)
        negated = re.search(r"\b(?:not|never|without)\s+(?:recovery[- ]correct|correct|calibrat)|\buncorrected\b", recovery, re.I)
        s["recovery_calibrated"] = "YES" if corrected and not negated else "NO"
    if mclass == "UNKNOWN":
        s["flags"].append("MATRIX_UNKNOWN")
    if s["uf"] is None:
        s["flags"].append("UNIT_NOT_CONVERTIBLE")
    if s["analyte"] == "TOTAL_RADIOACTIVITY":
        s["flags"].append("TOTAL_RADIOACTIVITY")
    if mclass == "ELF" and s["elf_correction"] != "UREA":
        s["flags"].append("ELF_DILUTION_UNCORRECTED")
    if mclass == "ISF_MICRODIALYSIS" and s["recovery_calibrated"] != "YES":
        s["flags"].append("MICRODIALYSIS_UNCALIBRATED")
    return s


def _cell(r, cid):
    printed = (r.get("source_raw_values") or {}).get(cid)
    status = COMMON.cell_status(r, cid)
    if printed is not None and (COMMON.assay_qualifier(status, printed) or
                                isinstance(printed, str) and _BLQ_TXT.search(printed)):
        return printed, status
    raw = r.get(cid, printed)
    if isinstance(raw, str) is False and raw is None:
        raw = (r.get("source_raw_values") or {}).get(cid)
    return raw, status


def _n_for(series_n, t, n_map, n_note, one):
    if series_n:
        return series_n
    for k, v in n_map.items():
        if abs(k - t) <= max(1e-6, 0.02 * k):
            return v
    return 1 if one else n_note


def extract(entry, cfg):
    """Every concentration series of one PK_OBSERVATIONS table. M1 (2026-11-24): a source whose times already start at the end of
    the infusion is moved once onto the module clock (time after the start of dosing), so every later step subtracts the
    infusion duration exactly once and no second shift is applied."""
    base, out = _extract_raw(entry, cfg)
    if base.get("time_origin_source") != "END_OF_INFUSION" or base.get("route_class") != "IV":
        return base, out
    for s in out:
        h = s.get("infusion_h") or 0     # round 3: each animal's own input duration when the input gives one
        if h > 0:
            for p in s["points"]:
                if p.get("t") is not None:
                    p["t"] += h
            s["scheduled_times"] = [t + h for t in s.get("scheduled_times") or []]
            s["time_converted_from_end_of_infusion_h"] = h
    return base, out


def _extract_raw(entry, cfg):
    """Every concentration series of one PK_OBSERVATIONS table, in long form (rules D0.8 fields on each)."""
    base = _card_base(entry, cfg)
    cols = entry.get("columns", [])
    text = _text(entry)
    n_map, n_note, one = _n_by_time(text), _num(entry.get("metadata", {}).get("n") or entry.get("metadata", {}).get("n_animals")) or _sample_size(text)[0], _one_per_time(text)
    conc = [c for c in cols if c.get("meaning") == "CONCENTRATION"]
    times = [c for c in cols if c.get("meaning") == "TIME" and "pixel" not in str(c.get("header", "")).lower()]
    recs = [r for r in entry.get("records", []) if r.get("qc_status") in (None, "TECHNICALLY_RETAINED")]
    out = []
    if not times and conc and all(time_from_header(c.get("header")) is not None for c in conc):
        # wide by time: one row per tissue (and group), one column per time
        lab_col = next((c for c in cols if c.get("meaning") in ("COVARIATE", "OTHER") and re.search(r"tissue|organ|matrix|sample", str(c.get("header", "")).lower())), None) \
            or next((c for c in cols if c.get("meaning") in ("COVARIATE", "OTHER")), None)
        grp_col = next((c for c in cols if c.get("meaning") == "GROUP_OR_TREATMENT"), None)
        group = None
        for r in recs:
            g = r.get(grp_col["id"]) if grp_col else None
            if g not in (None, ""):
                group = str(g)
            lab = str(r.get(lab_col["id"]) if lab_col else r.get("record_id"))
            gn = re.search(r"\((\d+)\)\s*$", group or "")
            unit = conc[0].get("unit", "NOT_FOUND")
            s = _new_series(base, f"{entry['dataset_id']}:{r.get('record_id')}", (f"{group} · " if group else "") + lab, lab,
                            group or base["species_text"], unit)
            for c in conc:
                t = time_from_header(c.get("header"))
                s["scheduled_times"].append(t)
                raw, st = _cell(r, c["id"])
                v, sd, n, status = parse_value(raw, st)
                if status == "MISSING" or (status == COMMON.PREDOSE_ZERO and not (t is not None and t <= 0)):
                    continue
                s["points"].append({"t": t, "c": v if status in ("QUANTIFIED", COMMON.PREDOSE_ZERO) else None, "lim": v if status == "BLQ" else None,
                                    "status": status, "sd": sd, "n": n or _n_for(int(gn.group(1)) if gn else None, t, n_map, n_note, one),
                                    "record_id": r.get("record_id")})
                if status in COMMON.ASSAY_LABELS and (bound := COMMON.printed_assay_bound(raw)):
                    s["points"][-1]["censoring"] = bound
            if s["points"]:
                out.append(s)
        return base, out
    if not times or not conc:
        return base, []
    tcol = times[0]
    disp = COMMON._dispersion_columns(cols, conc)
    n_col = next((c["id"] for c in cols if c.get("meaning") in ("N", "N_ANIMALS")), None)
    multi_species = len({species_in(c.get("header")) for c in conc} - {None}) > 1
    for c in conc:
        head = str(c.get("header", c["id"]))
        mclass_h, _, _ = classify_matrix(re.sub(r"\(.*?\)", "", head))
        matrix_text = head if mclass_h != "UNKNOWN" else base["matrix_text"]
        sp_txt = head if (multi_species or species_in(head)) and species_in(head) else base["species_text"]
        m = re.search(r"(\d+(?:\.\d+)?)\s*mg/kg", head)
        animal = head if (base["level"].startswith("INDIVIDUAL") and len(conc) > 1 and mclass_h == "UNKNOWN" and not multi_species and not m) else None
        if base["level"].startswith("INDIVIDUAL"):
            # E8 boundary case: a one-animal table keeps its animal identifier (stated subject, metadata, or an
            # identifier-like header), so a one-animal study can still form a same-animal comparison
            meta0 = entry.get("metadata", {})
            stated = COMMON.column_subject(c) or (str(meta0.get("animal_id") or meta0.get("subject_id") or "").strip() if len(conc) == 1 else "")
            if stated and stated.lower() not in ("not_found", "not_reported", "unknown", "none"):
                animal = stated
            elif (animal is None and len(conc) == 1 and mclass_h == "UNKNOWN" and not m and not multi_species
                  and not re.search(r"conc|level|mean|median|value|plasma|serum|blood|\bc\b", head, re.I)):
                animal = head
        subj = COMMON.subject_dosing(entry, c)
        # round 3: a column without a subject that prints dose_mg_kg names a dose level; a subject column's dose is its own
        level = float(m.group(1)) if m else (subj["dose_level_mg_kg"] or (_num(c.get("dose_mg_kg")) if not subj["subject_id"] else None))
        s = _new_series(base, f"{entry['dataset_id']}:{c['id']}", head, matrix_text, sp_txt, c.get("unit", "NOT_FOUND"),
                        level, animal)
        meta = entry.get("metadata", {})
        s["dose_given"] = subj["dose_mg_kg"] if subj["dose_mg_kg"] is not None else s.get("dose")
        s["dose_given_from"] = "column" if subj["dose_mg_kg"] is not None else s.get("dose_from")
        s["infusion_h_nominal"] = base.get("infusion_h")
        if base.get("route_class") == "IV" and subj["infusion_h"] is not None:
            s["iv_mode"], s["infusion_h"], s["iv_mode_source"] = iv_mode_column(entry, cfg, c)
        s["subject_id"] = COMMON.column_subject(c)                      # r1.5 section 2.1: animal x occasion linkage
        s["source_occasion"] = str(c.get("occasion") or meta.get("occasion") or "").strip() or None
        s["washout_verified"] = c.get("washout_verified", meta.get("washout_verified")) is True
        s["cross_route_identity_verified"] = c.get("cross_route_identity_verified", meta.get("cross_route_identity_verified")) is True
        s["lloq_meta"] = _num(meta.get("lloq_ug_mL") or meta.get("lloq_mg_L"))      # mg/L
        s["noise_source"] = {k: meta.get(k) for k in COMMON.PRECISION_SOURCE_KEYS if meta.get(k) not in (None, "")}   # R8 fields
        dc = disp.get(c["id"], {})
        for r in recs:
            t = COMMON.observation_time_h(r, tcol)
            if t is None:
                continue
            s["scheduled_times"].append(t)
            raw, st = _cell(r, c["id"])
            v, sd, n, status = parse_value(raw, st)
            if status == "MISSING" or (status == COMMON.PREDOSE_ZERO and t > 0):
                continue
            if sd is None and status == "QUANTIFIED" and dc:
                sd, _ = COMMON._point_sd(r, dc, v)
            nn = _num(r.get(n_col)) if n_col else None
            nn = int(nn) if nn else (n or _n_for(None, t, n_map, n_note, one))
            se = _num(r.get(dc.get("se"))) if dc.get("se") else None
            if sd is None and se is not None and nn and nn > 1:
                sd = se * math.sqrt(nn)
            s["points"].append({"t": t, "c": v if status in ("QUANTIFIED", COMMON.PREDOSE_ZERO) else None, "lim": v if status == "BLQ" else None,
                                "status": status, "sd": sd, "se": se, "n": nn, "n_range": base.get("n_range"), "dispersion_kind": "SE" if se is not None else ("SD" if sd is not None else None),
                                "record_id": r.get("record_id")})
            if status in COMMON.ASSAY_LABELS and (bound := COMMON.printed_assay_bound(raw)):
                s["points"][-1]["censoring"] = bound
        s["points"].sort(key=lambda p: p["t"])
        if s["points"]:
            out.append(s)
    return base, out


def _q(points):
    return sorted((p for p in points if p["status"] == "QUANTIFIED" and p["c"] is not None and p["c"] > 0), key=lambda p: p["t"])


def _adjacent_chords(s, after=None, shift=0.0):
    """Rates between adjacent quantified samples, as in figure DIS-1c (2026-11-24, finding D12): a missing or below-limit
    sample between two quantified ones breaks the chain, so no rate is drawn across it."""
    pts = sorted((p for p in s["points"] if p.get("t") is not None and (after is None or p["t"] > after + 1e-12)), key=lambda p: p["t"])
    return [{"from_h": a["t"] - shift, "to_h": b["t"] - shift, "slope_per_h": (math.log(b["c"]) - math.log(a["c"])) / (b["t"] - a["t"])}
            for a, b in zip(pts, pts[1:])
            if a["status"] == b["status"] == "QUANTIFIED" and (a.get("c") or 0) > 0 and (b.get("c") or 0) > 0 and b["t"] > a["t"]]


def _match(t1, t2):
    return abs(t1 - t2) <= max(MATCH_ABS, MATCH_REL * max(abs(t1), abs(t2)))


# ---------------------------------------------------------------- statistics helpers (no scipy)

def welch_df(vs, ns):
    """Welch-Satterthwaite df for a sum of variance components v_i with n_i - 1 df each."""
    num = sum(vs) ** 2
    den = sum(v * v / (n - 1) for v, n in zip(vs, ns) if n and n > 1)
    return num / den if den > 0 else None


def z_crit(df):
    return 2.0 if df is None else COMMON.t_ppf(T_QUANTILE, df)


def log_interval(p, level, tol=TOL, family_size=1, source_sigma=None, mean_type=None, dispersion_scale=None, admission=None):
    """[ln L, ln U] for one quantified point (rules D0.4). Group means with SD and n add the sampling error of the mean.
    Returns (lo, hi, basis).

    With mean_type given (T6/T7, rule decision R1 of 2026-11-24) the interval must match the mean type:
    an arithmetic mean gets the t interval of the mean on the concentration scale, then the log of its ends (basis SAMPLING_ERROR);
    a geometric mean gets a formal interval only from an SD or SE on the ln C scale (basis SAMPLING_ERROR); any other mean with an
    SD on the concentration scale keeps the delta approximation as a sensitivity reading only (basis SAMPLING_ERROR_DELTA).
    Without mean_type the earlier delta-method interval is returned (other callers).

    With an R8 admission record (T6/T7, 2026-11-24) the ±5 % point tolerance is no longer a generic widening (R3): the figure-reading
    component enters only for digitized data (a bounded range from the figure, or the project default, which keeps the result a
    sensitivity reading), and a source precision uses its degrees of freedom and the standard error that matches the value."""
    c = p["c"]
    w = math.log(1 + tol)
    if admission is not None:
        rp = admission.get("reading_pct")
        w = math.log(1 + rp / 100) if rp is not None else 0.0
    if level == "GROUP_MEAN" and p.get("sd") and p.get("n") and p["n"] > 1:
        q = COMMON.t_ppf(1 - 0.025 / family_size, p["n"] - 1)
        if mean_type == "ARITHMETIC":
            half = q * p["sd"] / math.sqrt(p["n"])
            lo = math.log(c - half) if c - half > 0 else math.log(1e-12)
            return lo - w, math.log(c + half) + w, "SAMPLING_ERROR"
        if mean_type == "GEOMETRIC" and dispersion_scale == "LN":
            w += q * p["sd"] / math.sqrt(p["n"])
            return math.log(c) - w, math.log(c) + w, "SAMPLING_ERROR"
        cv = p["sd"] / c
        w += q * cv / math.sqrt(p["n"])
        return math.log(c) - w, math.log(c) + w, ("SAMPLING_ERROR" if mean_type is None else "SAMPLING_ERROR_DELTA")
    if source_sigma and level != "GROUP_MEAN":
        # r1.5 section 2.8 tiers 1-2: source assay precision or replicate scatter, simultaneous over the points of the profile
        if admission is not None:
            w += COMMON.t_ppf(1 - 0.025 / family_size, admission.get("df") or 1000) * (admission.get("se_target") or source_sigma)
        else:
            w = COMMON.t_ppf(1 - 0.025 / family_size, 1000) * source_sigma
        return math.log(c) - w, math.log(c) + w, "SOURCE_PRECISION"
    w = math.log(1 + tol)
    return math.log(c) - w, math.log(c) + w, "PROJECT_TOLERANCE"


# ---------------------------------------------------------------- item 24: decline phases after IV dosing

_slope = COMMON.win_slope


def sigma_for(s, pts):
    """Item 24 rule 3: sigma on ln C (shared with Absorption, M1). Returns (sigma, basis)."""
    return COMMON.window_sigma(s["level"], s["digitized"], pts)


def noise_setting(s, pts, cfg=None):
    """r1.5 section 2.8: sigma on ln C for this dataset, set before any test. Tier 1 source assay precision, tier 2 source
    replicates, tier 3 the r1.3 project default. Returns dict(sigma, tier, basis, source, source_sigma)."""
    override = ((cfg or {}).get("noise_by_dataset") or {}).get(s["dataset_id"]) or {}
    src = dict(s.get("noise_source") or {}, **override)
    # rule decision R8: one admission rule decides whether the precision may carry a formal interval
    adm = COMMON.precision_admission(src, analyte=s.get("analyte", "PARENT"), matrix=s.get("matrix_class"), digitized=bool(s.get("digitized")),
                                     level=s["level"], group_sd_n=bool(pts) and all(p.get("sd") and p.get("n") for p in pts))
    # M1: the tiers come from the shared rule that Absorption uses for the IV window (zero, negative or non-finite values are not
    # a precision)
    return dict(COMMON.window_noise(s["level"], s["digitized"], pts, src), admission=adm)


def split_half(pts, sigma):
    """Item 24 rule 3 split-half screen; M1 (2026-11-24): the shared implementation in eda_common, also used by Absorption."""
    return COMMON.win_split_half(pts, sigma)


def _baseline(s):
    values = [p["c"] for p in s["points"] if p["t"] <= 0 and p["status"] in ("QUANTIFIED", COMMON.PREDOSE_ZERO) and p["c"] is not None]
    bounds = [min(values), max(values)] if values else None
    return bool(s.get("endogenous") or any(v > 0 for v in values)), bounds


def item24_profile(s, cfg=None, prior_unwashed=False, prior_routes=None):
    """Rules item 24 steps 1-8 on one IV reference series (plasma, serum or whole blood)."""
    q, end = COMMON.iv_window_samples(s["points"], s.get("infusion_h"), "START_OF_DOSING")   # M1: the shared normalised samples
    res = {"sid": s["sid"], "label": s["label"], "dataset_id": s["dataset_id"], "time_basis": "time after the end of dosing",
           "n_points": len(q), "earliest_sample_h": q[0]["t"] if q else None, "caveats": [], "checks_done": {}}
    # round 3 addendum: quantified samples taken during the input or at its end (time after the end <= 0). They are not used for
    # the decline shape (a sample at the nominal end may fall inside the input), but they exist and are not "missing".
    res["input_samples_h"] = sorted(round(p["t"] - end, 6) for p in s["points"] if p.get("status") == "QUANTIFIED" and p.get("c") is not None
                                    and p["c"] > 0 and p.get("t") is not None and 0 < p["t"] <= end + 1e-12) if end else []
    if s["level"] == "GROUP_MEAN":
        res["caveats"].append("GROUP_MEAN")
    if s["digitized"]:
        res["caveats"].append("DIGITIZED")
    if s["design"] == "DESTRUCTIVE":
        res["caveats"].append("DESTRUCTIVE_SAMPLING")
    if s["iv_mode"] in ("INFUSION_TIMING_UNKNOWN", "IV_MODE_UNKNOWN"):
        res["caveats"].append("INFUSION_TIMING_UNKNOWN")
    if "TOTAL_RADIOACTIVITY" in s["flags"]:
        res["caveats"].append("TOTAL_RADIOACTIVITY")
    if s.get("source_conflicts"):
        res["caveats"].append("SOURCE_CONFLICT")
        res["source_conflicts"] = s["source_conflicts"]
    res["analyte"] = s["analyte"]
    res["assay"] = s.get("assay")
    res["checks_done"]["parent and metabolite"] = say(s["analyte"])
    if s["iv_mode"] == "ONGOING_INPUT" or s["analyte"] == "ACTIVE_MATERIAL":
        reason = ("ongoing IV input: observations are not a post-stop decline" if s["iv_mode"] == "ONGOING_INPUT"
                  else "active-material assay: parent-specific disposition is not established")
        res["caveats"].append("ONGOING_INPUT" if s["iv_mode"] == "ONGOING_INPUT" else "ACTIVE_MATERIAL")
        return res | {"curvature": "NOT_ASSESSABLE", "phases_visible": "NOT_ASSESSABLE", "not_assessable_reason": reason,
                      "time_basis": "reported time during ongoing input" if s["iv_mode"] == "ONGOING_INPUT" else "reported time after dose",
                      "t6_label": "CANNOT_ASSESS", "t7_label": "CANNOT_ASSESS"}
    res["sampling_site"] = s.get("sampling_site", "NOT_REPORTED")
    if len({p["t"] for p in q}) != len(q):
        return res | {"curvature": "NOT_ASSESSABLE", "phases_visible": "NOT_ASSESSABLE", "not_assessable_reason": "duplicate times in a single series", "t6_label": "CANNOT_ASSESS", "t7_label": "CANNOT_ASSESS"}
    if not q:
        return res | {"curvature": "NOT_ASSESSABLE", "not_assessable_reason": "NO_QUANTIFIED_POINTS", "phases_visible": "NOT_ASSESSABLE",
                      "t6_label": "CANNOT_ASSESS", "t7_label": "CANNOT_ASSESS", "t6_reason": "no quantified points", "t7_reason": "no quantified points"}
    review, res["baseline_range"] = _baseline(s)
    # R10: a quantified predose value whose residue the source explains (completed central input, or a stated residue
    # assumption) does not stop the profile; T6 and T7 then apply their own premises in item24_tests
    explained = (not s.get("endogenous") and (s.get("predose_residue_central_completed") or s.get("predose_residue_assumption")))
    if review and explained:
        res["caveats"].append("PREDOSE_QUANTIFIED")
        res["predose_residue"] = {"central_input_completed": bool(s.get("predose_residue_central_completed")),
                                  "assumption": s.get("predose_residue_assumption")}
    elif review:
        res["caveats"].append("ENDOGENOUS_REVIEW_REQUIRED")
        return res | {"curvature": "NOT_ASSESSABLE", "phases_visible": "NOT_ASSESSABLE",
                      "not_assessable_reason": "baseline review required before assigning decline phases",
                      "t6_label": "CANNOT_ASSESS", "t7_label": "CANNOT_ASSESS",
                      "t6_reason": ("endogenous baseline" if s.get("endogenous") else "predose concentration quantified and unexplained")
                                   + ": zero baseline not established",
                      "t7_reason": ("endogenous baseline (ongoing input)" if s.get("endogenous") else
                                    "predose concentration quantified; the source does not attribute the residue to completed central input")
                                   + ": zero baseline not established"}
    noise = noise_setting(s, q, cfg)
    sigma, sbasis = noise["sigma"], noise["basis"]
    res["noise"] = {k: v for k, v in noise.items()}
    res["prior_dose_residue_possible"] = bool(prior_unwashed)
    base = split_half(q, sigma)
    if base.get("borderline_shared_point"):
        res["caveats"].append("BORDERLINE_SHARED_POINT")
    res.update({"curvature": base["curvature"], "slope_ratio": base.get("R"), "z": base.get("z"), "sigma_used": sigma,
                "sigma_basis": sbasis, "split": {k: v for k, v in base.items() if k not in ("curvature",)},
                "not_assessable_reason": base.get("reason"),
                "chord_slopes": _adjacent_chords(s, after=end, shift=end)})
    rows, deps = [], []
    for name, sub in (("without first point", q[1:]), ("without last point", q[:-1]),
                      ("without low-confidence points", [p for p in q if not p.get("low_conf")])):
        if name.endswith("low-confidence points") and len(sub) == len(q):
            rows.append({"repeat": name, "reading": "no low-confidence points", "n": len(sub)}); continue
        if len(sub) < MIN_SPLIT_POINTS:
            rows.append({"repeat": name, "reading": "fewer than 5 points; not repeated", "n": len(sub)}); continue
        r2 = split_half(sub, sigma)
        rows.append({"repeat": name, "reading": r2["curvature"], "R": r2.get("R"), "z": r2.get("z"), "n": len(sub)})
        if r2["curvature"] not in ("NOT_ASSESSABLE", base["curvature"]):
            deps.append({"without first point": "FIRST_POINT", "without last point": "LAST_POINT"}.get(name, "LOW_CONFIDENCE_POINTS"))
    res["robustness_rows"] = rows
    incomplete = base["curvature"] == "NOT_ASSESSABLE" or any(row["n"] < MIN_SPLIT_POINTS or row["reading"] == "NOT_ASSESSABLE" for row in rows)
    res["curvature_support"] = "DEPENDS_ON_" + "_AND_".join(deps) if deps else "NOT_ASSESSABLE" if incomplete else "ROBUST"
    cur = base["curvature"]
    pv = {"NOT_ASSESSABLE": "NOT_ASSESSABLE", "STEEPENING": "NOT_LOG_CONVEX_DESCRIPTIVE", "NONE_DETECTED": "ONE_APPARENT"}.get(cur)
    if cur == "FLATTENING":
        pv = "TWO_OR_MORE" if res["curvature_support"] == "ROBUST" else "TWO_OR_MORE_TENTATIVE"
        if s["level"] == "GROUP_MEAN" and base["R"] < GM_R_CAUTION:
            res["caveats"].append("GROUP_MEAN_CURVATURE_POSSIBLE")
        if "LAST_POINT" in deps:
            res["caveats"].append("LLOQ_PROXIMAL")
        if "FIRST_POINT" in deps and early_mixing(q[0]["t"]):
            res["caveats"].append("EARLY_MIXING_POSSIBLE")
        if "FIRST_POINT" in deps and s.get("sampling_site", "NOT_REPORTED") in ("NOT_REPORTED", "VENOUS", "MIXED"):
            res["caveats"].append("SAMPLING_SITE_EARLY")
    res["phases_visible"] = pv
    # step 7 (r1.5 section 2.5): start of the post-distribution part; a suffix counts only when the screen had the power.
    # M1 (2026-11-24): the shared IV-window function writes the record that Absorption also computes (same name, same samples)
    win = COMMON.iv_window(q, sigma, sbasis, shift=end, base=base)
    res["iv_window"] = {k: v for k, v in win.items() if k != "suffix_screen"}
    res["post_distribution_from_h"] = win["start_h"] if win["status"] == "DETERMINED" else "NOT_DETERMINED"
    if win["status"] != "DETERMINED":
        res["post_distribution_reason"] = win["reason"]          # finding D12 reasons, unchanged
    trail = win["suffix_screen"]
    res["window_start_screen"] = trail
    res["split_power_ok"] = base.get("power_ok")
    res["late_area_share"] = late_area_share(q, pv, res["post_distribution_from_h"])
    lloq = next((p.get("lim") for p in s["points"] if p["status"] == "BLQ" and p.get("lim")), None)
    res["last_quantified_over_lloq"] = (q[-1]["c"] / lloq) if lloq else None
    res["lloq"] = lloq
    # step 6: formal tests
    res.update(item24_tests(s, q, sigma, noise=noise, prior_unwashed=prior_unwashed, prior_routes=prior_routes))
    if cur == "FLATTENING":
        res["slowing_alternatives"] = slowing_alternatives(s, q, res)
    res["checks_done"] = {
        "early mixing and sampling site": "first sample %s h after the end of dosing; sampling site %s" % (_f(q[0]["t"]), res["sampling_site"].lower().replace("_", " ")),
        "cohort composition across times": {"DESTRUCTIVE": "different animals at each time", "SERIAL": "same animals", "UNKNOWN": "not reported"}[s["design"]],
        "predose signal and prior dose": "no predose sample" if not any(p["t"] <= 0 for p in s["points"]) else "predose sample present",
        "endogenous baseline": "measured zero at or before dosing" if res["baseline_range"] else "no predose concentration or endogenous signal reported",
        "parent and metabolite": {"PARENT": "parent", "TOTAL_RADIOACTIVITY": "total radioactivity: not read as parent",
                                  "METABOLITE_OR_MIXED": "metabolite or mixed", "TARGET_OR_COMPLEX": "target or complex"}[s["analyte"]],
        "target binding": ("declared: " + s["target_binding_quote"]) if s["target_binding"] == "YES" else f"not stated by the source; not considered (rules {RULES_VERSION})",
    }
    return res


def _triples(n):
    return itertools.combinations(range(n), 3)


def t7_scan(ts, lo, hi, keep=None):
    """T7 log-convexity: M = ln L_b - [w ln U_a + (1-w) ln U_c] over ordered triples; returns (max M, witness)."""
    idx = list(range(len(ts))) if keep is None else keep
    best = None
    for a, b, c in itertools.combinations(idx, 3):
        if not (ts[a] < ts[b] < ts[c]):
            continue
        w = (ts[c] - ts[b]) / (ts[c] - ts[a])
        m = lo[b] - (w * hi[a] + (1 - w) * hi[c])
        if best is None or m > best[0]:
            best = (m, (a, b, c))
    return best


def t6_margin(ts, lo, hi, keep=None):
    """T6 single-line feasibility: smallest common widening delta (log scale) so that one line a - lambda t, lambda >= 0,
    passes every [ln L_i, ln U_i]. delta(lambda) = [max(ln L_i + lambda t_i) - min(ln U_j + lambda t_j)]/2 is convex and
    piecewise linear, so its minimum lies at lambda = 0 or at a breakpoint. Returns (delta, lambda, witness indices)."""
    idx = list(range(len(ts))) if keep is None else keep
    cands = {0.0}
    for fam in (lo, hi):
        for i, j in itertools.combinations(idx, 2):
            if ts[i] != ts[j]:
                lam = (fam[j] - fam[i]) / (ts[i] - ts[j])
                if lam > 0:
                    cands.add(lam)
    best = None
    for lam in sorted(cands):
        up = [(lo[i] + lam * ts[i], i) for i in idx]
        dn = [(hi[i] + lam * ts[i], i) for i in idx]
        mx, mn = max(up), min(dn)
        d = (mx[0] - mn[0]) / 2
        if best is None or d < best[0] - 1e-15:
            best = (d, lam, (mx[1], mn[1]))
    return best


def _loo(fn, n, ts, lo, hi, eps=0.0):
    """A0.3 leave-one-out, every point in turn (rule decision R2, 2026-11-24). Every rerun keeps the original intervals and
    needs MIN_TEST_TIMES distinct times; a rerun below that minimum cannot be assessed. Returns a dict:
    lost (indices whose removal leaves an assessable test without contradiction: SINGLE_POINT_SUPPORT),
    not_assessable (indices whose removal leaves too few data: LOO_NOT_ASSESSABLE), worst (smallest margin over the
    assessable reruns), reruns (number of assessable reruns) and robust (every rerun assessable and contradicting).
    Both facts are kept when both occur. The same margin threshold eps decides the full test and each rerun."""
    worst, lost, na = None, [], []
    for d in range(n):
        keep = [i for i in range(n) if i != d]
        r = fn(ts, lo, hi, keep) if len({ts[i] for i in keep}) >= MIN_TEST_TIMES else None
        if r is None:
            na.append(d)
            continue
        if r[0] <= eps:
            lost.append(d)
        worst = r[0] if worst is None else min(worst, r[0])
    return {"robust": not lost and not na and n > 0, "worst": worst, "lost": lost, "not_assessable": na,
            "reruns": n - len(na), "required": n}


def _loo_apply(test, loo, ts, out, fl):
    """Write the removal outcome of T6 or T7 (rule decision R2): NOT_EXCLUDED with SINGLE_POINT_SUPPORT and/or
    LOO_NOT_ASSESSABLE unless every required rerun was assessable and kept the contradiction."""
    out[test + "_removal"] = {"unit": "one concentration point at a time", "required_reruns": loo["required"],
                              "assessable_reruns": loo["reruns"], "contradiction_lost_without_h": [ts[i] for i in loo["lost"]],
                              "not_assessable_without_h": [ts[i] for i in loo["not_assessable"]]}
    if loo["lost"]:
        fl.append("SINGLE_POINT_SUPPORT")
        out[test + "_loo_drop_h"] = ts[loo["lost"][0]]
    if loo["not_assessable"]:
        fl.append("LOO_NOT_ASSESSABLE")
        out[test + "_reason"] = ("exclusion deferred: removing a point leaves fewer than %d distinct times, so removal robustness "
                                 "is unknown (contradiction in the full data kept as a sensitivity reading)" % MIN_TEST_TIMES)
    return "EXCLUDED_UNDER_STATED_ASSUMPTIONS" if loo["robust"] else "NOT_EXCLUDED"


def item24_tests(s, q, sigma=None, noise=None, prior_unwashed=False, prior_routes=None):
    out = {}
    if len(q) < 3:
        return {"t6_label": "CANNOT_ASSESS", "t6_reason": "fewer than 3 quantified points", "t7_label": "CANNOT_ASSESS",
                "t7_reason": "fewer than 3 quantified points", "analysis_unit": None}
    unit = ("INDIVIDUAL" if s["level"].startswith("INDIVIDUAL") and s["design"] != "DESTRUCTIVE" else
            "DESTRUCTIVE" if s["design"] == "DESTRUCTIVE" else
            "GEOMETRIC_MEAN_FIXED" if s["mean_type"] == "GEOMETRIC" else "ARITHMETIC_MEAN_FIXED")
    out["analysis_unit"] = unit
    prem = []
    prem6, prem7 = [], []
    predose = _baseline(s)[0] and not s.get("endogenous")
    if s.get("source_conflicts"):
        prem.append("source conflict requires review")
    if s.get("endogenous"):
        prem.append("endogenous baseline (ongoing input) requires review")
    if predose and not s.get("predose_residue_assumption"):
        prem6.append("predose concentration quantified and unexplained")
    if predose and not s.get("predose_residue_central_completed"):
        # R10: "input has stopped" is not enough; only residue from completed central input of the same linear system keeps T7
        prem7.append("predose concentration quantified; the residue is not confirmed as completed input into the central compartment "
                     "of the same linear system")
    if prior_unwashed and prior_routes and not set(prior_routes) <= {"IV"}:
        prem7.append("earlier extravascular or unknown-route dose without documented washout; input may continue")
    if s["iv_mode"] in ("INFUSION_TIMING_UNKNOWN", "IV_MODE_UNKNOWN"):
        prem.append("IV mode or infusion end not reported (INFUSION_TIMING_UNKNOWN)")
    if s["analyte"] != "PARENT":
        prem.append("analyte is not the parent drug")
    group_mean = s["level"] == "GROUP_MEAN"
    adm = (noise or {}).get("admission")
    ivs = [log_interval(p, s["level"], family_size=len(q), source_sigma=(noise or {}).get("source_sigma"),
                        mean_type=(s.get("mean_type") if group_mean else None), dispersion_scale=s.get("dispersion_scale"),
                        admission=adm) for p in q]
    if unit == "DESTRUCTIVE" and not all(b.startswith("SAMPLING_ERROR") for _, _, b in ivs):
        prem.append("destructive cohorts without SD and n: intervals cannot cover sampling error")
    ts = [p["t"] for p in q]
    lo = [a for a, _, _ in ivs]
    hi = [b for _, b, _ in ivs]
    flags = []
    # rule decisions R1/R4 (2026-11-24): a result resting on the project tolerance (tier 3) or on a concentration-scale SD
    # beside a mean that is not arithmetic is a sensitivity reading; the formal basis is recorded apart from the noise tier
    if any(b in ("PROJECT_TOLERANCE", "SAMPLING_ERROR_DELTA") for _, _, b in ivs):
        flags.append("SENSITIVITY_ONLY")
    if adm is not None:
        # R8: the machine result keeps the precision source, matched scope, df or coverage and the components of the joint interval
        out["precision"] = {k: adm.get(k) for k in ("kind", "source", "scope_match", "df", "coverage", "components", "formal_ok", "missing",
                                                     "short_label")}
        if not adm["formal_ok"] and "SENSITIVITY_ONLY" not in flags:
            flags.append("SENSITIVITY_ONLY")
    if s["level"] == "INDIVIDUAL_IDENTITY_UNVERIFIED":
        flags.append("CONDITIONAL_ON_LABEL_IDENTITY")
    if group_mean and s["design"] == "UNKNOWN":
        flags.append("CONDITIONAL_ON_FIXED_COHORT")
    out["interval_basis"] = sorted({b for _, _, b in ivs})
    formal_basis = sorted({b for _, _, b in ivs}) if "SENSITIVITY_ONLY" not in flags else []
    out["formal_interval_basis"] = formal_basis[0] if len(formal_basis) == 1 else (formal_basis or None)
    family = ({"scope": "this profile and its sampled window", "analysis_unit": unit, "members": f"{len(q)} concentration intervals",
               "m": len(q), "method": "Bonferroni joint intervals, two-sided", "family_alpha": FAMILY_ALPHA} if formal_basis else None)
    need = None
    if "SENSITIVITY_ONLY" in flags and sigma:
        need = max(0.0, NOISE_GATE_SIGMAS * sigma - math.log(1 + TOL))
        out["noise_gate"] = {"sigma": sigma, "sigmas": NOISE_GATE_SIGMAS, "half_width_pct": 100 * (math.exp(NOISE_GATE_SIGMAS * sigma) - 1),
                             "extra_log_widening_needed": need}
    # T7
    if prem or prem7:
        out.update(t7_label="CANNOT_ASSESS", t7_reason="; ".join(prem + prem7))
    else:
        best = t7_scan(ts, lo, hi)
        m, (a, b, c) = best
        n_tri = sum(1 for _ in _triples(len(ts)))
        lab, fl = "NOT_EXCLUDED", list(flags)
        if m > 0:
            loo = _loo(t7_scan, len(ts), ts, lo, hi)
            lab = _loo_apply("t7", loo, ts, out, fl)
            if loo["robust"]:
                # widening every interval by e lowers M by 2e, so the contradiction survives a further +/- (exp(M/2) - 1)
                out["t7_extra_tolerance_pct"] = 100 * (math.exp(min(m, loo["worst"]) / 2) - 1)
                if need is not None:
                    out["t7_at_noise"] = bool(min(m, loo["worst"]) / 2 > need)
        if need is not None:
            out["t7_at_tolerance"] = lab == "EXCLUDED_UNDER_STATED_ASSUMPTIONS"
        out.update(t7_label=lab, t7_flags=fl, t7_margin=m, t7_points=[ts[a], ts[b], ts[c]], t7_triples=n_tri, t7_family=family,
                   t7_window=[ts[0], ts[-1]], t7_combination="linear reversible mammillary disposition + completed central input + zero baseline + central observation")
    # T6
    if prem or prem6:
        out.update(t6_label="CANNOT_ASSESS", t6_reason="; ".join(prem + prem6))
    elif group_mean and s.get("mean_type") != "GEOMETRIC":
        # rule decision R1: no single-line exclusion from arithmetic (or unstated) means, fixed or destructive cohorts alike
        out.update(t6_label="CANNOT_ASSESS", t6_reason="T6 not applicable to arithmetic means (mean type %s)" % s["mean_type"].lower().replace("_", " "))
    else:
        d, lam, (i, j) = t6_margin(ts, lo, hi)
        lab, fl = "NOT_EXCLUDED", list(flags)
        if d > 1e-12:
            loo = _loo(t6_margin, len(ts), ts, lo, hi, eps=1e-12)
            lab = _loo_apply("t6", loo, ts, out, fl)
            if loo["robust"]:
                # the minimax margin is the common log widening needed for one line to fit
                out["t6_extra_tolerance_pct"] = 100 * (math.exp(min(d, loo["worst"])) - 1)
                if need is not None:
                    out["t6_at_noise"] = bool(min(d, loo["worst"]) > need)
        if need is not None:
            out["t6_at_tolerance"] = lab == "EXCLUDED_UNDER_STATED_ASSUMPTIONS"
        out.update(t6_label=lab, t6_flags=fl, t6_margin=d, t6_lambda=lam, t6_points=sorted({ts[i], ts[j]}), t6_family=family,
                   t6_combination="linear one-compartment + completed central input + zero baseline + central observation")
    if predose and out.get("t6_label") not in (None, "CANNOT_ASSESS"):
        # R10: T6 tests the decline after this dose; with a quantified predose value the formal result is CANNOT_ASSESS and the
        # reading is kept only under the stated residue assumption
        out.setdefault("t6_flags", []).append("SENSITIVITY_ONLY")
        out["t6_residue_note"] = "predose concentration quantified; reading under the stated residue assumption: " + s["predose_residue_assumption"]
    elif prior_unwashed and out.get("t6_label") == "EXCLUDED_UNDER_STATED_ASSUMPTIONS":
        # r1.5 section 2.1: residue from an earlier dose adds a slow component that T6 reads as exchange; T7 is kept only when
        # the earlier input was IV (completed central input, R10)
        out.setdefault("t6_flags", []).append("SENSITIVITY_ONLY")
        out["t6_residue_note"] = "earlier dose without documented washout; residue not accounted for"
    for test in ("t6", "t7"):
        if "SENSITIVITY_ONLY" in out.get(test + "_flags", []):
            out[test + "_sensitivity_label"] = out[test + "_label"]
            out[test + "_label"] = "CANNOT_ASSESS"
            out[test + "_reason"] = (out[test + "_residue_note"] if out.get(test + "_residue_note")
                                     else "group-mean SD on the concentration scale; no ln C-scale uncertainty for this mean type "
                                          "(delta approximation, sensitivity only)" if "SAMPLING_ERROR_DELTA" in out.get("interval_basis", [])
                                     else (out.get("precision") or {}).get("short_label")
                                     or "only project-set point tolerances are available (noise tier 3, DEFAULT)")
            out[test + "_family"] = None
    out["noise_tier"] = (noise or {}).get("tier")
    return out


def slowing_alternatives(s, q, res):
    """r1.5 section 2.3: causes of a late slowing other than peripheral exchange, each with what the data show."""
    rows = []
    base_note = "predose value quantified" if _baseline(s)[0] else ("earlier dose without documented washout" if res.get("prior_dose_residue_possible") else "no predose signal; no unwashed earlier dose")
    rows.append({"cause": "residue or endogenous baseline", "status": "POSSIBLE" if (_baseline(s)[0] or res.get("prior_dose_residue_possible")) else "NOT_INDICATED", "note": base_note})
    ratio = res.get("last_quantified_over_lloq")
    if ratio is None and s.get("lloq_meta") and s.get("uf"):
        ratio = q[-1]["c"] * s["uf"] / s["lloq_meta"]
    rows.append({"cause": "assay bias or selective censoring near the LLOQ",
                 "status": "NOT_CHECKABLE" if ratio is None else "POSSIBLE" if ratio < LLOQ_PROX else "NOT_INDICATED",
                 "note": "LLOQ not reported" if ratio is None else f"last quantified value {ratio:.3g} x LLOQ"})
    chords = res.get("chord_slopes") or []
    early_t = q[min(2, len(q) - 1)]["t"]                 # the first three samples: a rise there reads as mixing, not recirculation
    rises = [c for c in chords if c["slope_per_h"] > 0 and c["from_h"] >= early_t]
    early_rises = [c for c in chords if c["slope_per_h"] > 0 and c["from_h"] < early_t]
    rows.append({"cause": "enterohepatic recirculation or secondary peak", "status": "POSSIBLE" if rises else "NOT_INDICATED",
                 "note": (f"{len(rises)} rising interval(s), first {_f(rises[0]['from_h'])}-{_f(rises[0]['to_h'])} h") if rises else "no rising interval after the first three samples"})
    if early_rises:
        rows.append({"cause": "incomplete mixing or sample timing at the first samples", "status": "POSSIBLE",
                     "note": f"concentration rises {_f(early_rises[0]['from_h'])}-{_f(early_rises[0]['to_h'])} h after the bolus"})
    specific = s["analyte"] == "PARENT" and COMMON.assay_class(s.get("assay")) == "SPECIFIC"   # round 3 addendum: shared reader
    rows.append({"cause": "metabolite or nonspecific assay signal", "status": "NOT_INDICATED" if specific else "POSSIBLE" if s["analyte"] != "PARENT" else "NOT_CHECKABLE",
                 "note": s.get("assay") or "assay not reported"})
    rows.append({"cause": "late change of matrix or sampling site", "status": "NOT_INDICATED" if s.get("matrix_text") and s.get("sampling_site") != "MIXED" else "NOT_CHECKABLE",
                 "note": f"one matrix ({s.get('matrix_text')}); sampling site {str(s.get('sampling_site', 'NOT_REPORTED')).lower().replace('_', ' ')}"})
    return rows


def item24_candidates(r, declared):
    c = []
    if r.get("t7_label") == "EXCLUDED_UNDER_STATED_ASSUMPTIONS" or r.get("phases_visible") == "NOT_LOG_CONVEX_DESCRIPTIVE":
        c = ["saturable elimination", "nonlinear binding", "enterohepatic recycling (with a rebound)", "mistimed infusion end",
             "unrecorded input", "data issue"]
        if declared == "YES":
            c.insert(1, "target-mediated disposition")
    return c


# ---------------------------------------------------------------- r1.5 additions: occasions, EV profiles, APOD ordering

def _occ_key(s):
    """Order of an occasion label: the number itself, or the one number inside a label such as "Period 2" or "Day 7";
    math.inf when the label gives no order (for example "IV" or "PO")."""
    o = s.get("source_occasion")
    try:
        return float(o)
    except (TypeError, ValueError):
        nums = re.findall(r"\d+(?:\.\d+)?", str(o or ""))
        return float(nums[0]) if len(nums) == 1 else math.inf


def prior_unwashed(s, series):
    """r1.5 section 2.1: an earlier occasion of the same animal and no documented washout before this one.
    2026-11-24 (finding D4): when the same animal has another occasion with a different label and the labels give no order,
    the order cannot be established, so either may be the later one and washout counts as unverified."""
    if not s.get("subject_id"):
        return False
    others = [o for o in series if o is not s and o.get("subject_id") == s["subject_id"] and o.get("study") == s.get("study")]
    earlier = [o for o in others if _occ_key(o) < _occ_key(s)]
    unordered = [o for o in others if o.get("source_occasion") != s.get("source_occasion")
                 and math.inf in (_occ_key(o), _occ_key(s))]
    return bool(earlier or unordered) and not s.get("washout_verified")


def prior_unwashed_routes(s, series):
    """R10: route classes of the earlier (or unordered) occasions of the same animal that lack a documented washout."""
    if not prior_unwashed(s, series):
        return set()
    others = [o for o in series if o is not s and o.get("subject_id") == s["subject_id"] and o.get("study") == s.get("study")]
    return {o.get("route_class") or "UNKNOWN" for o in others
            if _occ_key(o) < _occ_key(s) or (o.get("source_occasion") != s.get("source_occasion") and math.inf in (_occ_key(o), _occ_key(s)))}


def _iv_reference_for(ev, ivr, item24):
    """2026-11-24 (finding D9): the IV unit of the same animal by an explicit rule, independent of table order: same matrix
    class first, then the nearest occasion by label; a tie that the rule cannot break passes no window (reason recorded)."""
    subj = ev.get("subject_id")
    cands = [s for s in ivr if subj and s.get("subject_id") == subj and s["sid"] in item24]
    if not cands:
        return None, None
    same = [s for s in cands if s.get("matrix_class") == ev.get("matrix_class")] or cands
    dist = lambda s: abs(_occ_key(s) - _occ_key(ev)) if math.inf not in (_occ_key(s), _occ_key(ev)) else math.inf
    best = min(dist(s) for s in same)
    pick = sorted((s for s in same if dist(s) == best), key=lambda s: s["sid"])
    if len(pick) > 1:
        return None, ("more than one IV unit of this animal (" + ", ".join(s["sid"] for s in pick)
                      + ") with the same matrix and equally near or unordered occasions; no IV window passed")
    return item24[pick[0]["sid"]], None


def item24_ev(s, cfg=None, iv_r24=None, prior=False, iv_reason=None):
    """r1.5 section 2.6: post-peak description of one EV profile. T6/T7 are not assessable (input continues);
    the split-half uses the A0.7 EV cut-offs; Vc/F <= D/C(t). r1.5b: no flip-flop flag here; the same animal's IV
    reference window is passed to Absorption, which owns the paired-route comparison and its thresholds."""
    q = _q(s["points"])
    res = {"sid": s["sid"], "label": s["label"], "dataset_id": s["dataset_id"], "route": "EV", "subject_id": s.get("subject_id"),
           "occasion": s.get("source_occasion"), "n_points": len(q), "caveats": [],
           "t6_label": "CANNOT_ASSESS", "t7_label": "CANNOT_ASSESS", "t6_reason": "EV input continues; completed-input premise not met",
           "t7_reason": "EV input continues; completed-input premise not met",
           "separability": "ABSORPTION_AND_DISTRIBUTION_NOT_SEPARABLE", "prior_dose_residue_possible": bool(prior)}
    if not q:
        return res | {"curvature": "NOT_ASSESSABLE", "not_assessable_reason": "NO_QUANTIFIED_POINTS"}
    peak = max(q, key=lambda p: p["c"])
    post = [p for p in q if p["t"] > peak["t"]]
    res.update(tmax_h=peak["t"], cmax=peak["c"], n_post_peak=len(post))
    noise = noise_setting(s, post or q, cfg)
    res["noise"] = noise
    # L5 (2026-11-24): the EV post-peak description is Absorption's A0.7 split, written once in eda_common and reused here, so one
    # curve carries one shape label in both sections; no z gate (the IV task's z threshold does not apply to this description)
    sp = COMMON.ev_post_peak_split(post, s["level"])
    if sp:
        cur = {"DECLINE_FLATTENS": "FLATTENING", "DECLINE_STEEPENS": "STEEPENING", "NEITHER": "NONE_DETECTED"}.get(sp["class"], "NOT_ASSESSABLE")
        res.update(curvature=cur, ev_split=sp, slope_ratio=(1 / sp["ratio"]) if sp["ratio"] else None, z=None,
                   b_early=-sp["early_slope"], b_late=-sp["late_slope"], description_only=True)
        if cur == "NOT_ASSESSABLE":
            res["not_assessable_reason"] = sp["reason"]
    else:
        res.update(curvature="NOT_ASSESSABLE", not_assessable_reason=f"fewer than {COMMON.EV_SPLIT_MIN_POINTS} post-peak points")
        if len(post) >= 2:
            sl, _ = _slope([p["t"] for p in post], [math.log(p["c"]) for p in post])
            res["b_late"] = -sl
    res["chord_slopes"] = _adjacent_chords(s)
    # r1.5b: hand the same animal's IV reference window to Absorption (no flip-flop reading here)
    if iv_r24:
        # M1 (2026-11-24): the shared window record; the rate is refitted on the samples the record lists (no longer the slope of
        # the whole later half of the curve)
        win = iv_r24.get("iv_window") or {}
        start = iv_r24.get("post_distribution_from_h")
        res["iv_reference_window"] = {"iv_sid": iv_r24.get("sid"), "name": win.get("name", COMMON.IV_WINDOW_NAME), "from_h": start,
                                      "to_h": win.get("end_h"), "sample_ids": win.get("sample_ids", []), "b_late_iv_per_h": win.get("rate_per_h"),
                                      "consumer": "Absorption Q5 (paired-route terminal comparison and flip-flop); Absorption computes the same record"}
        if not isinstance(start, (int, float)):
            # 2026-11-24 (finding D9): no window start, so no rate is passed with it
            res["iv_reference_window"].update(b_late_iv_per_h=None, rate_withheld="IV window start not determined "
                                              f"({iv_r24.get('post_distribution_reason') or 'NOT_DETERMINED'})")
    else:
        res["iv_reference_window"] = None
        if iv_reason:
            res["iv_reference_reason"] = iv_reason
    # Vc/F bound
    if s["dose"] and s["uf"] and s["analyte"] == "PARENT" and not s.get("unbound"):
        c = peak["c"] * s["uf"]
        res["vc_over_f_upper_bound_l_per_kg"] = COMMON.dose_given(s) / c
        res["vc_over_f_basis"] = f"D/C at the highest quantified concentration ({_f(peak['t'])} h); amount in the central compartment <= F*D"
        if prior or _baseline(s)[0]:
            res["vc_over_f_label"] = "SENSITIVITY_ONLY"
    res["next"] = "Absorption Q5 (paired-route terminal comparison and flip-flop; thresholds owned by Absorption)"
    return res


def animal_occasions(b):
    """r1.5 section 2.1: draw and test each animal x occasion; read the occasions of one animal together."""
    by = {}
    for r in b["item24"] + b.get("item24_ev", []):
        sid = r["sid"]
        s = next((x for x in b["source_series"] if x["sid"] == sid), None)
        if not s or not s.get("subject_id"):
            continue
        by.setdefault(s["subject_id"], []).append((s, r))
    rows = []
    for subj, items in sorted(by.items()):
        if len(items) < 2:
            continue
        items.sort(key=lambda sr: _occ_key(sr[0]))
        occ = []
        for s, r in items:
            vc = next((x for x in b["item25"] if x["sid"] == s["sid"]), {})
            occ.append({"sid": s["sid"], "label": s["label"], "occasion": s.get("source_occasion"), "route": s["route_class"], "dose": s.get("dose"),
                        "reading": r.get("phases_visible") or r.get("curvature"), "R": r.get("slope_ratio"), "z": r.get("z"),
                        "late_rate_per_h": (r.get("split") or {}).get("b_late") if s["route_class"] == "IV" else r.get("b_late"),
                        "t6": r.get("t6_label"), "t6_sensitivity": r.get("t6_sensitivity_label"),
                        "t7": r.get("t7_label"), "t7_sensitivity": r.get("t7_sensitivity_label"),
                        "vc_bound_l_per_kg": vc.get("vc_upper_bound_l_per_kg"), "vc_over_f_bound_l_per_kg": r.get("vc_over_f_upper_bound_l_per_kg"),
                        "washout_verified": s.get("washout_verified")})
        routes = {o["route"] for o in occ}
        agree = None
        # 2026-11-24 (finding D8): the two rates and their ratio only, without a grade; the paired-route reading and its
        # thresholds belong to Absorption (decision B). The pair is the first IV and the first EV occasion that have a rate.
        rated = [o for o in occ if o["late_rate_per_h"]]
        iv_o = next((o for o in rated if o["route"] == "IV"), None)
        ev_o = next((o for o in rated if o["route"] == "EV"), None)
        if routes == {"IV", "EV"} and iv_o and ev_o:
            known = math.inf not in (_occ_key({"source_occasion": iv_o["occasion"]}), _occ_key({"source_occasion": ev_o["occasion"]}))
            if known:
                first, second = sorted((iv_o, ev_o), key=occ.index)
                agree = {"compared": "late decline rate, later / earlier occasion",
                         "earlier": {"sid": first["sid"], "route": first["route"], "late_rate_per_h": first["late_rate_per_h"]},
                         "later": {"sid": second["sid"], "route": second["route"], "late_rate_per_h": second["late_rate_per_h"]},
                         "ratio": second["late_rate_per_h"] / first["late_rate_per_h"],
                         "follows": f"route ({first['route']} then {second['route']}); occasion order and route are confounded in this design"}
            else:
                agree = {"compared": "late decline rate, EV / IV (occasion order not stated)",
                         "iv": {"sid": iv_o["sid"], "route": "IV", "late_rate_per_h": iv_o["late_rate_per_h"]},
                         "ev": {"sid": ev_o["sid"], "route": "EV", "late_rate_per_h": ev_o["late_rate_per_h"]},
                         "ratio": ev_o["late_rate_per_h"] / iv_o["late_rate_per_h"],
                         "follows": "route; the occasion order is not stated"}
            agree.update(reading="NOT_GRADED_HERE", next="Absorption Q5 (paired-route terminal comparison and its thresholds)")
        rows.append({"subject_id": subj, "occasions": occ, "agreement": agree,
                     "linkage_verified": all(s.get("cross_route_identity_verified") for s, _ in items)})
    return rows


RANK_GROUPS = ("REFERENCE", "SUPPORTED", "INDIRECT_SUPPORT", "UNTESTED", "CONTRARY_EVIDENCE")   # rule decision R5, shared terms
_SIMPLICITY = {"one-compartment": 0, "two-compartment": 1, "three-compartment": 2, NONLINEAR_CANDIDATE: 3}
_LINEAR = ("one-compartment", "two-compartment", "three-compartment")
_EXCL = "EXCLUDED_UNDER_STATED_ASSUMPTIONS"


def _unit_id(r):
    return r.get("sid") or r.get("label")


def _contradiction(units, test, candidate):
    """R5: one check against one candidate over the required units fixed before the results (every IV first-dose profile on
    the board); a unit that cannot be assessed stays in the denominator."""
    formal = [r for r in units if r.get(test + "_label") == _EXCL]
    sens = [r for r in units if r.get(test + "_label") != _EXCL and (
        r.get(test + "_sensitivity_label") == _EXCL
        or {"SINGLE_POINT_SUPPORT", "LOO_NOT_ASSESSABLE"} & (set(r.get(test + "_flags") or []) | set(r.get(test + "_sensitivity_flags") or [])))]
    assessable = [r for r in units if r.get(test + "_label") in (_EXCL, "NOT_EXCLUDED")]
    if test == "t6":
        direction = lambda r: {"FLATTENING": "slowing", "STEEPENING": "steepening"}.get(r.get("curvature"), "one line excluded")  # noqa: E731
    else:
        direction = lambda r: "late steepening"  # noqa: E731
    dirs = sorted({direction(r) for r in formal})
    n, k = len(units), len(formal)
    level = ("BOARD" if n and k == n and len(dirs) == 1 else "FORMAL_UNIT" if k else "SENSITIVITY" if sens else None)
    if level is None:
        return None
    return {"candidate": candidate, "test": test.upper(), "level": level, "required_n": n, "assessable_m": len(assessable),
            "formal_k": k, "sensitivity_only": len(sens), "directions": dirs or sorted({direction(r) for r in sens}),
            "formal_units": [_unit_id(r) for r in formal], "sensitivity_units": [_unit_id(r) for r in sens],
            "correction": "per-unit Bonferroni joint intervals over the concentration intervals of that unit (see each unit's family)",
            "combination_rule": "board-level exclusion only when every required unit is formally excluded in the same direction "
                                "(intersection-union, rule decisions R4 and R5)"}


def apod_ordering(b):
    """r1.5 section 2.7 under rule decision R5 (2026-11-24): every candidate is a complete model combination placed in one group
    (SUPPORTED, INDIRECT_SUPPORT, UNTESTED, CONTRARY_EVIDENCE). The required units are fixed before the results (every IV first-dose
    profile on the board). A formal unit-level contradiction puts the combination in CONTRARY_EVIDENCE with n, m, k and direction;
    only a formal exclusion in every required unit, in one direction, excludes it at board level. A sensitivity-only contradiction
    is marked and moves a candidate only below another candidate of its group that the same observation supports. A T6 failure
    alone does not put two compartments ahead of one; late steepening (T7) challenges every linear candidate."""
    units = list(b["item24"])
    n = len(units)
    tested = lambda r: any(r.get(k) in (_EXCL, "NOT_EXCLUDED")  # noqa: E731
                           for k in ("t6_label", "t7_label", "t6_sensitivity_label", "t7_sensitivity_label"))
    iv = [r for r in units if r.get("curvature") not in (None, "NOT_ASSESSABLE") or tested(r)]
    flat = [r for r in iv if r.get("phases_visible") == "TWO_OR_MORE"]
    flat_t = [r for r in iv if r.get("phases_visible") == "TWO_OR_MORE_TENTATIVE"]
    one = [r for r in iv if r.get("phases_visible") == "ONE_APPARENT"]
    c6 = _contradiction(units, "t6", "one-compartment")
    c7 = {c: _contradiction(units, "t7", c) for c in _LINEAR}
    t7_units = (c7["one-compartment"] or {}).get("formal_units", []) + (c7["one-compartment"] or {}).get("sensitivity_units", [])
    t7_formal = (c7["one-compartment"] or {}).get("formal_units", [])
    cands = {
        "one-compartment": {"supported_by": [_unit_id(r) for r in one], "indirect": [], "sensitivity_support": []},
        "two-compartment": {"supported_by": [_unit_id(r) for r in flat], "indirect": [_unit_id(r) for r in flat_t], "sensitivity_support": []},
    }
    if flat or flat_t:
        cands["three-compartment"] = {"supported_by": [], "indirect": [], "sensitivity_support": []}
    if not iv:
        cands = {}          # no IV profile could be screened or tested: no order is proposed (the limitation says why)
    if t7_units:
        # the same late-steepening observation that challenges the linear candidates supports the nonlinear alternative; a
        # sensitivity-level steepening does not lift it into another group (R5), it only counts for an order change inside a group
        cands[NONLINEAR_CANDIDATE] = {"supported_by": list(t7_formal), "indirect": [],
                                      "sensitivity_support": [u for u in t7_units if u not in t7_formal]}
    rows, board_exclusions, unit_level = [], [], []
    for name, ev in cands.items():
        contra = [c for c in ([c6] if name == "one-compartment" else []) + [c7.get(name)] if c]
        group = "SUPPORTED" if ev["supported_by"] else "INDIRECT_SUPPORT" if ev["indirect"] else "UNTESTED"
        if any(c["level"] in ("FORMAL_UNIT", "BOARD") for c in contra):
            group = "CONTRARY_EVIDENCE"
        for c in contra:
            if c["level"] == "BOARD":
                board_exclusions.append({"candidate": name, "test": c["test"], "direction": c["directions"][0], "units": c["formal_units"],
                                         "required_n": c["required_n"], "rule": c["combination_rule"],
                                         "note": "excluded at board level within the declared conditions and windows; may still be fitted as a comparator"})
            if c["level"] in ("FORMAL_UNIT", "BOARD"):
                unit_level += [{"candidate": name, "test": c["test"], "unit": u} for u in c["formal_units"]]
        rows.append({"candidate": name, "group": group, "supported_by": ev["supported_by"], "indirect": ev["indirect"],
                     "sensitivity_support": ev["sensitivity_support"],
                     "untested_state": (None if group != "UNTESTED" else "assessed but undecided" if ev["sensitivity_support"] or contra
                                        else "not assessed"),
                     "independent_sources": len(set(ev["supported_by"]) | set(ev["indirect"])), "contradictions": contra,
                     "sensitivity_contradiction": [c for c in contra if c["level"] == "SENSITIVITY"],
                     "board_excluded": any(c["level"] == "BOARD" for c in contra), "simplicity": _SIMPLICITY[name]})
    order_idx = {g: i for i, g in enumerate(RANK_GROUPS)}
    rows.sort(key=lambda r: (order_idx[r["group"]], -len(set(r["supported_by"])), -r["independent_sources"], r["simplicity"]))
    # a sensitivity-only contradiction moves a candidate below another candidate of the same group only when the observation that
    # contradicts it supports that other candidate
    sup = lambda r: set(r["supported_by"]) | set(r["indirect"]) | set(r["sensitivity_support"])  # noqa: E731
    base = {r["candidate"]: i for i, r in enumerate(rows)}
    target = {}
    for i, a in enumerate(rows):
        against = {u for x in a["sensitivity_contradiction"] for u in x["sensitivity_units"]}
        hits = [k for k in range(i + 1, len(rows)) if rows[k]["group"] == a["group"] and against & sup(rows[k])]
        if hits:
            target[a["candidate"]] = (rows[hits[-1]]["candidate"], sorted(against & sup(rows[hits[-1]])))

    def key(name):      # directly below the last same-group candidate that the observation supports; moved ones keep their order
        return key(target[name][0]) + (1, base[name]) if name in target else (base[name],)
    rows.sort(key=lambda r: key(r["candidate"]))
    moved = []
    for i, r in enumerate(rows):
        if r["candidate"] in target:
            r["moved_below"], units_ = target[r["candidate"]]
            moved.append({"candidate": r["candidate"], "below": r["moved_below"], "positions": i - base[r["candidate"]], "group": r["group"],
                          "units": units_, "reason": "sensitivity-only contradiction; the same observation supports the candidate above"})
    for i, r in enumerate(rows):
        r["position"] = i + 1
        r["tie"] = f'{r["group"]}:{r["independent_sources"]}'
    final = [r["candidate"] for r in rows if not r["board_excluded"]]
    why = []
    if iv:
        why.append(f"early-to-late slowing in {len(flat)} robust + {len(flat_t)} tentative of {n} IV profiles"
                   + (f"; a single apparent phase in {len(one)}" if one else ""))
    bend = None
    indiv = [r for r in iv if r.get("analysis_unit") == "INDIVIDUAL" and r.get("phases_visible") is not None]
    if indiv:
        bend = {"shown": sum(r.get("phases_visible") in ("TWO_OR_MORE", "TWO_OR_MORE_TENTATIVE") for r in indiv), "sampled_both_sides": len(indiv)}
    if bend and any(str(r.get("analysis_unit", "")).endswith("MEAN_FIXED") and r.get("phases_visible") in ("TWO_OR_MORE", "TWO_OR_MORE_TENTATIVE") for r in iv):
        why.append(f"the group mean bends; {bend['shown']} of {bend['sampled_both_sides']} individually sampled animals show the bend")
    for c in [c6] + [c7["one-compartment"]]:
        if not c:
            continue
        what = "one line (T6)" if c["test"] == "T6" else "a log-convex decline (T7, every linear candidate)"
        if c["level"] == "SENSITIVITY":
            why.append(f"{what} contradicted at sensitivity level only in {c['sensitivity_only']} of {c['required_n']} required IV profiles; "
                       "the candidates stay in their groups" + ("; a T6 failure alone does not put two compartments ahead of one" if c["test"] == "T6" else ""))
        else:
            why.append(f"{what} formally contradicted in {c['formal_k']} of {c['required_n']} required IV profiles ({c['assessable_m']} assessable; "
                       f"direction {', '.join(c['directions'])})" + ("; excluded at board level" if c["level"] == "BOARD" else "; kept as contrary evidence"))
    limits = []
    if iv and all(r.get("noise_tier") == 3 for r in iv):
        fr = [r for r in iv if r.get("t6_label") in (_EXCL, "NOT_EXCLUDED") or r.get("t7_label") in (_EXCL, "NOT_EXCLUDED")]
        if not fr:
            limits.append("no source assay precision or replicates (noise tier DEFAULT), so T6/T7 give sensitivity results only")
        else:
            bases = sorted({x for r in fr for x in r.get("interval_basis") or []})
            limits.append(f"no source assay precision (noise tier DEFAULT): formal T6/T7 results in {len(fr)} of {n} IV profiles rest on "
                          f"{', '.join(bases) or 'the stated interval basis'} only; the other results are sensitivity results")
    near = sum(any(a.get("cause") == "assay bias or selective censoring near the LLOQ" and a.get("status") == "POSSIBLE" for a in r.get("slowing_alternatives") or []) for r in iv)
    if near:
        limits.append(f"late slowing may reflect concentrations near the LLOQ in {near} of {n} IV profiles")
    if iv and all(str(r.get("analysis_unit", "")).endswith("MEAN_FIXED") for r in iv):
        limits.append("group means only: one-compartment disposition may still hold in individual animals")
    if not iv and b["item24"]:
        limits.append("no IV profile could be screened or tested (see the item 24 reasons): the compartment question is open")
    elif not iv:
        limits.append("no eligible IV profile: the compartment question cannot be answered from post-peak EV data")
    conclusion = {"simplest_plausible_model": final[0] if final else None, "motivating_observations": why[:2],
                  "main_limitation": limits[0] if limits else None, "other_limitations": limits[1:]}
    return {"order": final, "candidates": rows, "groups": list(RANK_GROUPS), "board_exclusions": board_exclusions,
            "removed": unit_level, "removed_for_all_units": sorted({x["candidate"] for x in board_exclusions}),
            "required_units": [_unit_id(r) for r in units], "demoted": moved, "bend_count": bend,
            "basis": why, "q1_conclusion": conclusion,
            "rule": ("rule decision R5: groups SUPPORTED, INDIRECT_SUPPORT, UNTESTED, CONTRARY_EVIDENCE; required units fixed before the "
                     "results; board-level exclusion only when every required unit is formally excluded in one direction; a sensitivity-only "
                     "contradiction is marked and changes the order only against a candidate of the same group that the same observation supports")}


def _handoff_order_line(o):
    """R5 hand-off wording: each candidate with its group; contrary evidence with n, m, k and direction; board-level exclusions
    named separately from unit-level contrary evidence; sensitivity-only contradictions marked."""
    rows = {r["candidate"]: r for r in o.get("candidates") or []}

    def tag(name):
        r = rows.get(name)
        if not r:
            return name
        bits = [r["group"]]
        for c in r.get("contradictions") or []:
            if c["level"] == "SENSITIVITY":
                bits.append(f"{c['test']} contradiction at sensitivity level only in {c['sensitivity_only']} of {c['required_n']} required units")
            elif c["level"] == "FORMAL_UNIT":
                bits.append(f"{c['test']} formal contradiction in {c['formal_k']} of {c['required_n']} required units "
                            f"({c['assessable_m']} assessable; {', '.join(c['directions'])})")
        if r.get("moved_below"):
            bits.append(f"placed below {r['moved_below']}, which the same observation supports")
        return f"{name} [{'; '.join(bits)}]"
    if not rows:            # output written before rule decision R5
        return ("candidate order: " + " > ".join(o.get("order") or []) + ". "
                + ("Removed (formal, unit-level joint intervals): " + "; ".join(f"{x['candidate']} by {x['test']} in {x['unit']}" for x in o["removed"])
                   if o.get("removed") else "Nothing removed: no formal T6/T7 result."))
    line = "candidate order (groups SUPPORTED > INDIRECT_SUPPORT > UNTESTED > CONTRARY_EVIDENCE): " + " > ".join(tag(n) for n in o.get("order") or []) + ". "
    bx = o.get("board_exclusions") or []
    if bx:
        line += ("Excluded at board level (formal exclusion in every required unit, one direction): "
                 + "; ".join(f"{x['candidate']} by {x['test']} in {len(x['units'])} of {x['required_n']} ({x['direction']})" for x in bx) + ".")
    else:
        line += "No board-level exclusion (it needs a formal exclusion in every required unit in one direction)."
    return line


def pDIS1animal(b):
    """r1.5 section 2.1: one panel per animal, every occasion drawn separately and read together (dose-normalized, semilog)."""
    rows = b.get("animal_occasions") or []
    panels = []
    for row in rows:
        occ = [x for x in b["source_series"] if x["sid"] in {o["sid"] for o in row["occasions"]}]
        routes = " and ".join(dict.fromkeys("IV" if x.get("route_class") == "IV" else (x.get("route_detail") or x.get("route_class")) for x in occ))
        p = Panel(COMMON.std_title(occ[0].get("species") if occ else None, routes, f"animal {row['subject_id']}", None, "",
                                   "concentration divided by dose", "semi-log", (occ[0].get("matrix_label") if occ else None)),
                  TIME_AXIS, "Concentration / dose (per mg/kg)", ylog=True)
        p.set(subtitle=D_SUB["ANIMAL"])
        _band(p, occ)
        for i, o in enumerate(row["occasions"]):
            s = next(x for x in b["source_series"] if x["sid"] == o["sid"])
            pts = _q(s["points"])
            if not pts or not s.get("dose"):
                continue
            tt, cc = [x["t"] for x in pts], [x["c"] / COMMON.dose_given(s) for x in pts]
            color = BLUE if o["route"] == "IV" else ORANGE
            p.line(tt, cc, color=color, lw=0.55)
            p.points(tt, cc, color=color, size=1.6, label=f"{'IV' if s.get('route_class') == 'IV' else s.get('route_detail') or o['route']} "
                     f"{_f(COMMON.dose_given(s))} mg/kg")
        panels.append(p)
    return panels


# ---------------------------------------------------------------- DIS-2a/2b: two or more IV doses

def dose_pattern(members, declared="NOT_STATED"):
    """Rules item 24 steps 9-11 on IV reference series of one study, species, matrix and record level."""
    members = sorted(members, key=lambda s: s["dose"])
    lo_s, hi_s = members[0], members[-1]
    incompatible = (any(not m["uf"] or not m["dose"] or m["dose"] <= 0 for m in members)
                    or len({(m["dose_basis"], m["iv_mode"], COMMON.input_nominal(m)) for m in members}) != 1)
    digit = any(m["digitized"] for m in members)
    band = BAND_DIGITIZED if digit else BAND
    end_lo, end_hi = lo_s.get("infusion_h") or 0, hi_s.get("infusion_h") or 0
    pl = [dict(p, t=p["t"] - end_lo) for p in _q(lo_s["points"]) if p["t"] > end_lo]
    ph = [dict(p, t=p["t"] - end_hi) for p in _q(hi_s["points"]) if p["t"] > end_hi]
    rows = []
    for a in pl if not incompatible else []:
        matches = [x for x in ph if x["t"] == a["t"]] or [x for x in ph if _match(a["t"], x["t"])]
        if len(matches) == 1:
            b = matches[0]
            r = (b["c"] * hi_s["uf"] / COMMON.dose_given(hi_s)) / (a["c"] * lo_s["uf"] / COMMON.dose_given(lo_s))
            row = {"t": a["t"], "c_lo": a["c"], "c_hi": b["c"], "ratio": r}
            rows.append(row)
    out = {"doses": [m["dose"] for m in members], "pair": [lo_s["dose"], hi_s["dose"]], "band": list(band), "rows": rows,
           "series": [m["sid"] for m in members], "confounded": len({m["study"] for m in members}) > 1 or (any(m["level"].startswith("INDIVIDUAL") for m in members) and not (all(m.get("animal") for m in members) and len({m["animal"] for m in members}) == 1))}
    if incompatible or len(rows) < 2:
        reason = "incompatible units, dose basis or input timing" if incompatible else "fewer than 2 common sampling times"
        return out | {"dose_pattern": "NOT_APPLICABLE", "reason": reason}
    rs = [r["ratio"] for r in rows]
    inb = [band[0] <= r <= band[1] for r in rs]
    above = [r > band[1] for r in rs]
    below = [r < band[0] for r in rs]
    # R7 item 4: the label names the observable shape of the high/low ratio of dose-normalised concentrations; no mechanism is
    # read from it and no candidate is generated (an inference needs a registered rule)
    if all(inb):
        pat = "RATIO_WITHIN_BAND"
    elif (all(above) or all(below)) and max(rs) / min(rs) <= 1.25:
        pat = "RATIO_CONSTANT_OUTSIDE_BAND"
    elif rs[-1] > rs[0] and above[-1] and not any(below):
        pat = "RATIO_RISES_LATE_ABOVE_BAND"
    elif all(below):
        pat = "RATIO_BELOW_BAND"
    elif above[0] and rs[-1] < rs[0]:
        pat = "RATIO_ABOVE_BAND_EARLY_THEN_FALLS"
    else:
        pat = "RATIO_MIXED"
    out["declared_target_binding"] = declared
    out["candidates"] = []
    out["shape_rule"] = ("high/low ratio of dose-normalised concentrations at shared post-input times against the band "
                         f"{band[0]:g}-{band[1]:g}; observable shape only (rule decision R7 item 4)")
    if out["confounded"]:
        # 2026-11-24 (finding D11, R7 item 4): doses given to different animals or studies: the contrast and the reason only
        out.update(dose_pattern="DESCRIPTIVE_CONFOUNDED",
                   reason="dose groups differ in animals or study, so the dose contrast is confounded; the ratios are shown without a pattern label")
    else:
        out.update(dose_pattern=pat)
    # Use absorption's T3p once on the same exact post-input times and harmonised units.
    low_times = Counter(p["t"] for p in pl)
    high_times = Counter(p["t"] for p in ph)
    exact = sorted(t for t in low_times if low_times[t] == high_times[t] == 1)
    if exact and lo_s["level"] == hi_s["level"] == "GROUP_MEAN" and not out["confounded"]:
        records = []
        for s, points in ((lo_s, pl), (hi_s, ph)):
            records.append({p["t"]: dict(p, c=p["c"] * s["uf"], sd=p["sd"] * s["uf"] if (p.get("sd") or 0) > 0 else None)
                            for p in points if p["t"] in exact})
        # round 3 (S12): each group keeps its own summary type; the shared gate compares them. Units are harmonised above.
        card = dict(lo_s, digitized=digit, units_harmonised=True)
        test = COMMON.t3p_series([(card,), (dict(hi_s, units_harmonised=True),)], [{"dose": lo_s["dose"]}, {"dose": hi_s["dose"]}], exact, records)
        flags = test.get("t3p_flags", [])
        label = "CANNOT_ASSESS" if "SENSITIVITY_ONLY" in flags else test["t3p_label"]
        if "BORDERLINE" in flags and label == "EXCLUDED_UNDER_STATED_ASSUMPTIONS":
            label = "NOT_EXCLUDED"
        # R7 item 6: one shared result (registered reuse of the absorption T3p) with dose pair, matched times, family, status
        # and limits; the conclusion is limited to dose-normalised concentration at the matched times
        out["t3p"] = {"label": label, "times": test["t3p_times"], "flags": flags, "reason": test.get("reason"),
                      "source": "absorption.t3p_series", "reuse": "registered reuse of absorption T3p on IV group means (R7 item 6)",
                      "dose_pair": test.get("t3p_dose_pair"), "family": test.get("t3p_family"),
                      "sensitivity_label": test.get("t3p_sensitivity_label"), "removal": test.get("t3p_removal"),
                      "margin": test.get("t3p_margin"),
                      "dose_group_dependence": lo_s.get("dose_group_dependence"),
                      "conclusion_scope": "dose-normalised concentration at the matched post-input times only"}
        by_time = {row["t"]: row for row in rows}
        for ci, adj in zip(test["t3p_ln_ratio_ci"], test["t3p_p_holm"]):
            row = by_time[ci["t"]]
            row.update(ci=[math.exp(x) for x in ci["ci95"]], se=ci["se"], df=ci["df"], p=ci["p_raw"],
                       holm_p=adj, holm_reject=adj < .05)
    else:
        out["t3p"] = {"label": "CANNOT_ASSESS", "reason": "no comparable group summaries at exact matched post-input times"}
    return out


# ---------------------------------------------------------------- item 25: initial central-volume bound

def _regimen_text(s):
    """Loading dose and infusion rate of an ongoing-input series, as recorded in the source table; '' when neither is given."""
    r = s.get("regimen") or {}
    bits = []
    if isinstance(r.get("loading_dose_mg_kg"), (int, float)):
        bits.append(f"loading dose {r['loading_dose_mg_kg']:g} mg/kg")
    if isinstance(r.get("infusion_rate_mg_kg_h"), (int, float)):
        bits.append(f"infusion {r['infusion_rate_mg_kg_h']:g} mg/kg/h")
    return " and ".join(bits)


def _vc_missing(bounds):
    why = " ".join(x.get("not_assessable_reason", "") for x in bounds)
    if "ongoing" in why and "dose per kg not found" not in why and "mode" not in why:
        return ["a bolus dose, or samples after the input stops"]
    return ["the IV mode (bolus, or infusion with its end)", "dose per kg"] if "mode" in why else ["dose per kg"]


def item25_bound(s, r24, cfg):
    out = {"sid": s["sid"], "label": s["label"], "caveats": [],
           "input_end_h": (s.get("infusion_h") or 0.0) if s["iv_mode"] in ("INFUSION", "BOLUS") else None}
    why = []
    if s.get("source_conflicts"):
        why.append("source conflict affects the concentration or dose basis")
    if s["iv_mode"] == "ONGOING_INPUT":
        why.append("ongoing or compound IV input; no bolus Vc bound")
    if s["iv_mode"] in ("INFUSION_TIMING_UNKNOWN", "IV_MODE_UNKNOWN"):
        why.append("IV mode or infusion end not reported")
    if not s["dose"] and not (s["iv_mode"] == "ONGOING_INPUT" and _regimen_text(s)):
        why.append("dose per kg not found")
    if s["iv_mode"] == "ONGOING_INPUT" and _regimen_text(s):
        why.append("regimen recorded as " + _regimen_text(s))
    if s["uf"] is None:
        why.append("concentration unit not convertible to mg/L")
    if s.get("unbound"):
        why.append("unbound rather than total parent concentration")
    if s["analyte"] != "PARENT":
        why.append("analyte is not the parent drug; active-material concentration cannot constrain parent Vc without assay-specific evidence")
    if s.get("endogenous"):
        why.append("endogenous compound: the measured concentration is not attributable to the dose")
    # M6: predose residue does not withhold the bound; the limit is kept and stays a sensitivity result (below)
    residue = _baseline(s)[0] and not s.get("endogenous")
    end = s.get("infusion_h") or 0.0
    q = [p for p in _q(s["points"]) if p["t"] > end or (s["iv_mode"] == "INFUSION" and p["t"] == end)]
    if not q:
        why.append("no quantified sample after the end of dosing")
    if why:
        return out | {"data_check": "NOT_ASSESSABLE", "not_assessable_reason": "; ".join(why)}
    # M6 (2026-11-24): every quantified sample after input ends bounds Vc, because the central amount never exceeds the
    # delivered dose; the point bound uses the highest of them (the earliest sample is not always the highest).
    first = min(q, key=lambda x: x["t"])
    p = max(q, key=lambda x: (x["c"], -x["t"]))
    c = p["c"] * s["uf"]
    if p is not first:
        out["earliest_sample_bound_l_per_kg"] = COMMON.dose_given(s) / (first["c"] * s["uf"])
        out["earliest_sample_time_h"] = first["t"] - end
    # Modeling constraint: lower concentration limits that cover every candidate sample together (R4: family m = number of
    # candidates, because the highest is chosen after seeing them) with the precision admitted by R8, and the supported upper dose.
    noise = (r24 or {}).get("noise") or noise_setting(s, q, cfg)   # the noise setting item 24 used, else the same rule here
    adm = noise.get("admission") or COMMON.precision_admission(s.get("noise_source") or {}, analyte=s.get("analyte", "PARENT"),
                                                              matrix=s.get("matrix_class"), digitized=bool(s.get("digitized")), level=s["level"],
                                                              group_sd_n=all(x.get("sd") and x.get("n") for x in q))
    m = len(q)
    lows = []
    for x in q:
        lnl, _, basis = log_interval(x, s["level"], family_size=m, source_sigma=noise.get("source_sigma"),
                                     mean_type=s.get("mean_type") if s["level"] == "GROUP_MEAN" else None, admission=adm)
        lows.append((math.exp(lnl) * s["uf"], x, basis))
    lo, plo, lo_basis = max(lows, key=lambda z: z[0])
    lo = max(lo, 1e-12)
    dose_used = COMMON.dose_given(s)   # round 3: the animal's administered dose when the input states it
    d_up = s.get("dose_upper_mg_per_kg") if (s.get("dose_upper_mg_per_kg") or 0) >= dose_used else None
    reasons = []
    if lo_basis == "PROJECT_TOLERANCE" or not adm.get("formal_ok"):
        reasons.append(adm.get("short_label") or "no source precision for the lower concentration limit")
    if d_up is None:
        reasons.append("no supported upper limit on the delivered dose; the " + ("recorded per-animal" if s.get("dose_given_from") == "column" else "nominal") + " dose is used")
    if residue:
        reasons.append("predose residue unresolved")
        out["caveats"].append("RESIDUE_UNRESOLVED")
    if end > 0 and s.get("time_origin_basis") in ("not stated", "conflict"):
        # round 3: with an input of known length, the clock of the source times decides which samples follow the end of input
        reasons.append("the source does not state whether times start at the start or the end of input")
        out["caveats"].append("TIME_ORIGIN_NOT_STATED")
    if early_mixing(plo["t"] - end):
        reasons.append("the limiting sample is within 5 minutes of the end of input (mixing unresolved)")
    out["lower_bound_basis"] = "SENSITIVITY_ONLY" if reasons else lo_basis
    out["modeling_constraint"] = {
        "vc_upper_l_per_kg": (d_up or dose_used) / lo, "status": "SENSITIVITY_ONLY" if reasons else "FORMAL", "reasons": reasons,
        "dose_mg_per_kg": d_up or dose_used, "dose_basis": "supported upper limit" if d_up else ("recorded per-animal dose" if s.get("dose_given_from") == "column" else "nominal"),
        "c_lower_mg_per_l": lo, "sample_time_h": plo["t"] - end, "interval_basis": lo_basis, "family_m": m,
        "coverage": "family-wise two-sided 95 %, Bonferroni over the candidate samples", "precision": adm.get("kind"),
        "rule": "Vc <= D_upper / max_i L_i over all quantified samples after input ends (M6)"}
    out.update(vc_upper_bound_l_per_kg=dose_used / c, conservative_l_per_kg=(d_up or dose_used) / lo, sample_time_h=p["t"] - end,
               sample_time_after_start_h=p["t"], c_at_sample_mg_per_l=c, dose_used_mg_per_kg=dose_used,
               bound_rule="highest eligible concentration after input ends", n_candidates=m,
               bound_basis="POINT", population_meaning=("INDIVIDUAL" if s["level"].startswith("INDIVIDUAL") else
                                                        "GEOMETRIC_MEAN_PROFILE" if s["mean_type"] == "GEOMETRIC" else "HARMONIC_MEAN"),
               label_time=("end of infusion" if p["t"] == end else "after infusion") if s["iv_mode"] == "INFUSION" else "after bolus")
    if early_mixing(p["t"] - end):
        out["caveats"].append("EARLY_MIXING_POSSIBLE")   # M6: the limit is kept; mixing stays a caveat
    if s["matrix_class"] == "WHOLE_BLOOD":
        out["caveats"].append("WHOLE_BLOOD_BASIS")
    if s["digitized"]:
        out["caveats"].append("DIGITIZED")
    if s["level"] == "GROUP_MEAN":
        out["caveats"].append("GROUP_MEAN")
    if s.get("sampling_site", "NOT_REPORTED") != "ARTERIAL" and p["t"] - end <= 0.25:
        out["caveats"].append("SAMPLING_SITE_EARLY")
    ch = (r24 or {}).get("chord_slopes") or []
    if (r24 or {}).get("phases_visible") == "ONE_APPARENT" and ch and ch[0]["slope_per_h"] < 0:
        t_half1 = math.log(2) / -ch[0]["slope_per_h"]
        if q[0]["t"] - end > t_half1:
            out["caveats"].append("LOOSE_BOUND")
            out["loose_reason"] = f"first sample {_f(q[0]['t'] - end)} h is later than the first chord half-life {_f(t_half1)} h (project setting)"
    ref = (cfg.get("reference_volumes_l_per_kg") or {}).get(s["species"]) or {}
    out["reference_volumes"] = {k: ref.get(k) for k in ("plasma", "plasma_lower", "extracellular", "total_water") if ref.get(k)}
    out["reference_source"] = ref.get("source") or ""
    pl = ref.get("plasma_lower") or (ref.get("plasma") if ref.get("source") else None)
    if s["matrix_class"] == "WHOLE_BLOOD":
        pl = ref.get("blood_lower") or None
    if pl and ref.get("source"):
        out["data_check"] = "VOLUME_BELOW_PLASMA" if out["conservative_l_per_kg"] < pl else "PASS"
        out["plasma_lower_l_per_kg"] = pl
    else:
        out["data_check"] = "NOT_ASSESSABLE"
        out["data_check_reason"] = f"no sourced plasma-volume value for {s['species']} in the run configuration"
    if out["reference_volumes"]:
        near = min(out["reference_volumes"].items(), key=lambda kv: abs(math.log(out["vc_upper_bound_l_per_kg"] / kv[1])))
        out["nearest_reference"] = near[0]
    return out


# ---------------------------------------------------------------- item 26: tissue, tissue/reference ratio, repeat dosing

def _group_prefix(s):
    return s["label"].split(" · ")[0] if " · " in s["label"] else ""


def _same_regimen(t, r):
    a, b = t.get("regimen") or {}, r.get("regimen") or {}
    # Matching generic prose ("single dose") is not an arm identifier. Only the
    # explicit compound ongoing schedule can substitute for a scalar total dose.
    if not all(x.get("ongoing_input") is True for x in (a, b)):
        return False
    if not all(_num(x.get(k)) is not None and _num(x[k]) > 0 for x in (a, b)
               for k in ("loading_dose_mg_kg", "infusion_rate_mg_kg_h")):
        return False
    return all(a.get(k) == b.get(k) for k in ("loading_dose_mg_kg", "infusion_rate_mg_kg_h", "infusion_start_h", "administration_method", "ongoing_input"))


def _identity_values(s, keys):
    identity = s.get("matching_identity") or {}
    return {str(s.get(k) or identity.get(k)).strip().lower() for k in keys
            if s.get(k) or identity.get(k)}


def _identity_compatible(t, r):
    a_group, b_group = _group_prefix(t), _group_prefix(r)
    if a_group and b_group and a_group != b_group:
        return False
    for keys in (("cohort", "cohort_id"), ("arm", "arm_id", "experiment_arm", "experiment_arm_id"), ("group", "group_id")):
        a, b = _identity_values(t, keys), _identity_values(r, keys)
        if a and b and a.isdisjoint(b):
            return False
    keys = ("animal", "animal_id", "subject_id", "individual_id")
    a, b = _identity_values(t, keys), _identity_values(r, keys)
    individual = any(str(s.get("level", "")).startswith("INDIVIDUAL") for s in (t, r))
    if a or b or individual:
        return bool(a and b and not a.isdisjoint(b))
    return True


def _shared_arm(t, r):
    if t["dataset_id"] == r["dataset_id"] and _group_prefix(t) == _group_prefix(r):
        return True
    # A source table is positive grouping evidence; a common paper alone is not.
    item = t.get("source_item_id")
    if item and item == r.get("source_item_id"):
        return True
    if t.get("dose") is not None and r.get("dose") == t["dose"]:
        def table_locations(s):
            keys = set()
            for ref in s.get("source_refs", []):
                match = re.search(r"\bp\.?\s*\d+\s+table\s*\d+(?:\s*\([^)]+\))?", str(ref.get("location", "")), re.I)
                if ref.get("sha256") and match:
                    keys.add((ref["sha256"], re.sub(r"\s+", "", match.group()).lower()))
            return keys
        if table_locations(t) & table_locations(r):
            return True
    for keys in (("cohort", "cohort_id"), ("arm", "arm_id", "experiment_arm", "experiment_arm_id"), ("group", "group_id")):
        if _identity_values(t, keys) & _identity_values(r, keys):
            return True
    return False


def find_reference(t, refs):
    """Reference (plasma, serum or whole blood) for a tissue series: same study, species, route, dose, occasion and analyte;
    the same table and group first; plasma or serum before whole blood. Several animal series and no group mean: none."""
    cands = [r for r in refs if r["study"] == t["study"] and r["species"] == t["species"] and r["route_class"] == t["route_class"]
             and r["route_detail"] == t["route_detail"] and r["dose"] == t["dose"] and r["occasion"] == t["occasion"]
             and r["analyte"] == t["analyte"] and r["occasion_day"] == t["occasion_day"] and r.get("condition") == t.get("condition")
             and r.get("drug") == t.get("drug") and r.get("dose_basis") == t.get("dose_basis") and not r.get("unbound")
             and r.get("iv_mode") == t.get("iv_mode") and COMMON.input_nominal(r) == COMMON.input_nominal(t)
             and r.get("concentration_basis") == t.get("concentration_basis") and r.get("assay") == t.get("assay")
             and _identity_compatible(t, r)
             and (t.get("iv_mode") != "ONGOING_INPUT" or (_same_regimen(t, r) and t.get("uf") and r.get("uf")
                  and any(p.get("status") == q.get("status") == "QUANTIFIED" and _match(p["t"], q["t"])
                          for p in t["points"] for q in r["points"])))]
    if not cands:
        return None, "no plasma, serum or blood series with the same study, species, route, dose, occasion and analyte"
    same = [r for r in cands if _shared_arm(t, r)]
    pool = same or cands
    matched_regimen = [r for r in pool if _same_regimen(t, r) and t.get("uf") and r.get("uf")
                       and t.get("iv_mode") == r.get("iv_mode") == "ONGOING_INPUT"
                       and any(p.get("status") == q.get("status") == "QUANTIFIED" and _match(p["t"], q["t"])
                               for p in t["points"] for q in r["points"])]
    if matched_regimen:
        pool = matched_regimen
    if not same and not matched_regimen:
        return None, "no shared table/arm identifier or compatible explicit ongoing compound regimen"
    if t.get("animal"):
        hit = [r for r in pool if r.get("animal") == t["animal"]]
        if hit:
            return hit[0], None
    groups = [r for r in pool if not r.get("animal")]
    pool = groups or pool
    if len({r["sid"] for r in pool}) > 1 and all(r.get("animal") for r in pool):
        return None, "several animal series and no group mean (no pooling in EDA)"
    for matrix in ("PLASMA", "SERUM", "WHOLE_BLOOD"):
        chosen = [s for s in pool if s["matrix_class"] == matrix]
        if chosen:
            return (chosen[0], None) if len(chosen) == 1 else (None, "ambiguous reference arm")
    return None, "no comparable reference"


def _pairing(t, r):
    if t["level"] == r["level"] == "INDIVIDUAL" and _shared_arm(t, r):
        subject_fields = ("animal_id", "subject_id", "individual_id")
        if _identity_values(t, subject_fields) & _identity_values(r, subject_fields):
            return "SAME_ANIMAL"
    if (t.get("animal") and t.get("animal") == r.get("animal") and t["dataset_id"] == r["dataset_id"]
            and t["level"] == r["level"] == "INDIVIDUAL"):
        return "SAME_ANIMAL"
    if t.get("animal") and r.get("animal") and t["dataset_id"] == r["dataset_id"] and t["level"] == r["level"] == "INDIVIDUAL":
        return "DIFFERENT_ANIMALS"
    return "NOT_REPORTED"


def ratio_rows(t, r):
    rows = []
    for p in t["points"]:
        matches = [x for x in r["points"] if _match(p["t"], x["t"])] if r else []
        exact = [x for x in matches if x["t"] == p["t"]]
        chosen = exact or matches
        m = chosen[0] if len(chosen) == 1 else None
        row = {"t": p["t"], "tissue": p["c"], "tissue_status": p["status"], "tissue_sd": p.get("sd"), "tissue_se": p.get("se"), "tissue_n": p.get("n"), "tissue_n_range": p.get("n_range") or t.get("n_range"),
               "ref": m["c"] if m else None, "ref_status": m["status"] if m else "NOT_SAMPLED", "ref_sd": m.get("sd") if m else None,
               "ref_se": m.get("se") if m else None, "ref_n": m.get("n") if m else None, "ref_n_range": (m.get("n_range") or r.get("n_range")) if m else None, "ratio": None, "record_ids": [p.get("record_id")] + ([m.get("record_id")] if m else [])}
        if p["status"] == "QUANTIFIED" and m and m["status"] == "QUANTIFIED" and m["c"] is not None and m["c"] > 0 and p["c"] is not None and p["c"] >= 0 and t["uf"] and r["uf"]:
            row["ratio"] = (p["c"] * t["uf"]) / (m["c"] * r["uf"])
        elif p["status"] == "QUANTIFIED":
            row["ratio_status"] = "UNDEFINED"
        rows.append(row)
    return sorted(rows, key=lambda row: row["t"])


def _cv2n(c, sd, n):
    return (sd / c) ** 2 / n if (c and sd and n and n > 1) else None


def ratio_change(a, b, digit, local, comparisons=1):
    """DIS-3b / DIS-3c: d = ln(late) - ln(early) of a ratio, SE from the four CVs, Welch df, z_crit (rules item 26 step 10)."""
    band = BAND_DIGITIZED if digit else BAND
    d = math.log(b["ratio"]) - math.log(a["ratio"])
    comps = [(_cv2n(x[k], x[k + "_sd"], x[k + "_n"]), x[k + "_n"]) for x in (a, b) for k in ("tissue", "ref")]
    out = {"t_early": a["t"], "t_late": b["t"], "d": d, "fold": math.exp(d), "band_used": list(band)}
    if all(v is not None for v, _ in comps):
        vs, ns = [v for v, _ in comps], [n for _, n in comps]
        se = math.sqrt(sum(vs))
        df = welch_df(vs, ns)
        zc = COMMON.t_ppf(1 - (1 - T_QUANTILE) / comparisons, df) if df else 2.0
        out["fold_ci"] = [math.exp(d - zc * se), math.exp(d + zc * se)]
        out.update(se_d=se, df=df, z=d / se, z_crit=zc, se_basis="four group CVs, zero covariance (pairing correlation not reported)")
        out.update(fold_ci_kind="CONDITIONAL_ZERO_COVARIANCE_INTERVAL",
                   inference_note="This interval assumes zero covariance between matrices and times; it is a conditional sensitivity interval, not a paired-animal test.")
        sig = abs(d / se) >= zc
    else:
        out.update(se_d=None, df=None, z=None, z_crit=None, se_basis="exact per-time SD and n not jointly available at all four points; native SE and n ranges retained: descriptive only")
        sig = None
    outside = not (band[0] <= out["fold"] <= band[1])
    out["outside_band"] = outside
    out["significant"] = sig
    return out


def prespecified_ratio_tests(series, cfg):
    """Two-time tests on actual within-animal tissue/plasma ratios, never selected by observed p.

    The native series IDs, source animal IDs and source record IDs are retained.
    A longitudinal comparison uses paired log-ratio changes; destructive/parallel
    time cohorts use Welch's test on individual log ratios, not ratios of means.
    All requested comparisons, including ineligible ones, belong to one Bonferroni family.
    This is a two-time contrast, not the three-time T8 constant-ratio exclusion.
    """
    requests = cfg.get("tissue_ratio_comparisons") or {}
    if not isinstance(requests, dict):
        return [{"id": "invalid_configuration", "status": "CANNOT_ASSESS", "exclusion_reasons": ["tissue_ratio_comparisons must be an object keyed by prespecified comparison ID"]}]
    requests = {k:v for k,v in requests.items() if not str(k).startswith("_example")}
    family = len(requests)
    alpha = _num(cfg.get("tissue_ratio_test_alpha", .05))
    by_sid = {}
    for s in series:
        by_sid.setdefault(s["sid"], []).append(s)
    results = []
    for identifier, request in requests.items():
        spec = request if isinstance(request, dict) else {}
        out = {"id": str(identifier), "study": spec.get("study"), "species": spec.get("species"), "organ": spec.get("organ"),
               "design": spec.get("design"), "times_h": spec.get("times_h"), "status": "CANNOT_ASSESS", "exclusion_reasons": [],
               "source": spec.get("source"), "prespecification_source": spec.get("prespecification_source"),
               "configured_series": {"tissue": spec.get("tissue_series"), "plasma": spec.get("plasma_series")},
               "family": "all configured tissue_ratio_comparisons", "family_size": family, "multiplicity": "BONFERRONI",
               "alpha_family": alpha, "analysis_unit": "animal", "observations": [],
               "estimand": "geometric-mean late/early fold change of within-animal tissue/plasma concentration ratios",
               "scope": "Two prespecified sampled times and the measured analyte; no equilibrium, transport or compartment mechanism is established.",
               "uncertainty_scope": "Animal sampling variability conditional on the supplied measurements; graph readout and unreported assay errors are not estimated. Failure to detect change is not equivalence.",
               "assumptions": ["independent experimental animals", "approximately normal animal log-ratio changes (paired) or log ratios (independent cohorts)"]}
        reasons = out["exclusion_reasons"]
        if not isinstance(request, dict):reasons.append("comparison configuration must be an object")
        for field in ("prespecified", "within_animal_matrix_pairing_verified", "time_design_verified"):
            if spec.get(field) is not True:reasons.append(field + " must be explicitly verified")
        for field in ("study", "species", "organ", "source", "prespecification_source"):
            if not isinstance(spec.get(field), str) or not spec[field].strip():reasons.append(field + " is required")
        if alpha is None or not 0 < alpha < 1:reasons.append("family alpha must be between 0 and 1")
        design = spec.get("design")
        if design not in ("LONGITUDINAL_PAIRED", "INDEPENDENT_COHORTS"):reasons.append("time design must be LONGITUDINAL_PAIRED or INDEPENDENT_COHORTS")
        raw_times = spec.get("times_h")
        times = [_num(x) for x in raw_times] if isinstance(raw_times, list) and len(raw_times)==2 else []
        if len(times)!=2 or any(t is None or t < 0 for t in times) or times[0]>=times[1]:
            reasons.append("two finite nonnegative prespecified times in increasing order are required")
        selected = {}
        for role,key in (("tissue","tissue_series"),("plasma","plasma_series")):
            ids = spec.get(key)
            selected[role] = []
            if not isinstance(ids,list) or not ids or any(not isinstance(x,str) for x in ids):
                reasons.append(key + " must explicitly list native series IDs");continue
            if len(ids)!=len(set(ids)):reasons.append(key + " contains duplicate series IDs")
            for sid in ids:
                found = by_sid.get(sid,[])
                if len(found)!=1:reasons.append(sid + ": missing or ambiguous native series ID")
                else:selected[role].append(found[0])
        if reasons:results.append(out);continue
        maps = {role:{t:{} for t in times} for role in selected}
        all_selected = selected["tissue"] + selected["plasma"]
        context_fields = ("drug", "route_class", "route_detail", "dose", "dose_basis", "condition", "occasion", "analyte", "unbound", "concentration_basis", "iv_mode", "infusion_h", "regimen")
        context = [tuple(s.get(k) for k in context_fields) for s in all_selected]
        if context and any(x!=context[0] for x in context):reasons.append("selected series differ in analyte, drug, route, dose, condition, occasion or concentration basis")
        ratio_units = set()
        for role,ss in selected.items():
            methods = {(str(s.get("assay") or "").strip(),str(s.get("assay_method") or "").strip()) for s in ss}
            if len(methods)>1:reasons.append(role + ": assay or assay method changes across animals/times")
            for s in ss:
                prefix = s["sid"] + ": "
                identity = s.get("matching_identity") or {}
                animal_values = {str(v).strip() for v in [identity.get(k) for k in ("animal_id","subject_id","individual_id")] + [s.get("animal")] if v not in (None,"")}
                if len(animal_values)!=1:
                    reasons.append(prefix + "one unambiguous source animal ID is required");continue
                animal = next(iter(animal_values))
                if s.get("level") != "INDIVIDUAL":reasons.append(prefix + "verified individual measurements are required")
                if str(s.get("concentration_basis") or "").strip().upper() in ("", "UNKNOWN", "NOT_REPORTED", "NOT_FOUND"):
                    reasons.append(prefix + "concentration basis must be declared")
                if str(s.get("assay") or "").strip().upper() in ("", "UNKNOWN", "NOT_REPORTED", "NOT_FOUND"):
                    reasons.append(prefix + "assay identity must be declared")
                sources = s.get("source_refs") or []
                if not any(isinstance(src,dict) and src.get("location") and
                           (src.get("url") or (src.get("path") and re.fullmatch(r"[0-9a-fA-F]{64}",str(src.get("sha256") or "")))) for src in sources):
                    reasons.append(prefix + "an auditable source reference with location and URL or local path/SHA256 is required")
                if s.get("study")!=spec["study"] or str(s.get("species","")).lower()!=spec["species"].lower():reasons.append(prefix + "study/species does not match the prespecified comparison")
                if s.get("source_conflicts") or _baseline(s)[0]:reasons.append(prefix + "source conflict or unresolved endogenous baseline")
                if not s.get("uf"):reasons.append(prefix + "concentration unit is not convertible")
                if role=="plasma" and s.get("matrix_class")!="PLASMA":reasons.append(prefix + "reference must be plasma")
                if role=="tissue":
                    if design=="LONGITUDINAL_PAIRED" and s.get("design")=="DESTRUCTIVE":reasons.append(prefix + "native destructive tissue collection cannot be a longitudinal paired design")
                    if str(s.get("organ","")).lower()!=spec["organ"].lower() or s.get("matrix_class") in REF_CLASSES:reasons.append(prefix + "organ does not match the prespecified tissue")
                    ratio_units.add("mL/g" if s.get("matrix_class")=="TISSUE_HOMOGENATE" and re.search(r"/(?:g|kg)\b",str(s.get("unit")),re.I) else "dimensionless")
                    if any(flag in s.get("flags",[]) for flag in ("MATRIX_UNKNOWN","ELF_DILUTION_UNCORRECTED","MICRODIALYSIS_UNCALIBRATED")):reasons.append(prefix + "matrix measurement requires calibration/correction")
                has_time = False
                for t in times:
                    points = [p for p in s["points"] if p["t"]==t]
                    if not points:continue
                    has_time = True
                    if len(points)!=1:reasons.append(prefix + "duplicate observations at the requested time");continue
                    p = points[0];value = _num(p.get("c"))
                    if p.get("status")!="QUANTIFIED" or value is None or value<=0:
                        reasons.append(prefix + f"{t:g} h is missing, censored or nonpositive; no substitution or complete-case selection is made");continue
                    if not p.get("record_id"):reasons.append(prefix + "source record ID is required")
                    if animal in maps[role][t]:reasons.append(prefix + f"duplicate animal/matrix measurement at {t:g} h")
                    maps[role][t][animal] = (s,p)
                if not has_time:reasons.append(prefix + "no observation at either requested time")
        if len(ratio_units)!=1:reasons.append("selected tissue ratios do not have one common unit")
        if reasons:results.append(out);continue
        groups=[]
        for t in times:
            tissue,plasma=maps["tissue"][t],maps["plasma"][t]
            if set(tissue)!=set(plasma):reasons.append(f"{t:g} h tissue/plasma animal IDs differ; matrix pairing cannot be reconstructed")
            ratios={}
            for animal in sorted(set(tissue)&set(plasma)):
                ts,tp=tissue[animal];ps,pp=plasma[animal]
                if not _identity_compatible(ts,ps):reasons.append(animal + ": conflicting matrix arm/cohort identity")
                log_ratio=math.log(tp["c"])+math.log(ts["uf"])-math.log(pp["c"])-math.log(ps["uf"])
                ratios[animal]=log_ratio
                out["observations"].append({"animal_id":animal,"time_h":t,"ratio":_ratio_exp(log_ratio),"log_ratio":log_ratio,
                    "tissue_sid":ts["sid"],"plasma_sid":ps["sid"],"tissue_record_id":tp["record_id"],"plasma_record_id":pp["record_id"],
                    "tissue_value":tp["c"],"tissue_unit":ts["unit"],"plasma_value":pp["c"],"plasma_unit":ps["unit"],
                    "tissue_assay":ts.get("assay"),"tissue_assay_method":ts.get("assay_method"),
                    "plasma_assay":ps.get("assay"),"plasma_assay_method":ps.get("assay_method"),"concentration_basis":ts.get("concentration_basis"),
                    "tissue_source_refs":ts.get("source_refs",[]),"plasma_source_refs":ps.get("source_refs",[])})
            groups.append(ratios)
        out.update(ratio_unit=next(iter(ratio_units)) if len(ratio_units)==1 else None, analyte=all_selected[0].get("analyte") if all_selected else None)
        early,late=groups
        if min(len(early),len(late))<2:reasons.append("at least two independent animals per time/paired comparison are required")
        if design=="LONGITUDINAL_PAIRED" and set(early)!=set(late):reasons.append("longitudinal comparison requires the same complete animal IDs at both times")
        if design=="LONGITUDINAL_PAIRED":
            for animal in set(early)&set(late):
                if not _identity_compatible(maps["tissue"][times[0]][animal][0],maps["tissue"][times[1]][animal][0]):
                    reasons.append(animal + ": longitudinal arm/cohort identity changes across times")
        if design=="INDEPENDENT_COHORTS" and set(early)&set(late):reasons.append("independent time cohorts must have distinct animal IDs; repeated animals require the paired design")
        if reasons:results.append(out);continue
        out["n_early"],out["n_late"]=len(early),len(late)
        if design=="LONGITUDINAL_PAIRED":
            changes=[late[k]-early[k] for k in sorted(early)]
            estimate=mean(changes);se=stdev(changes)/math.sqrt(len(changes));df=len(changes)-1
            out.update(method="paired t test of within-animal log-ratio changes", animal_log_changes=dict(zip(sorted(early),changes)))
        else:
            a,b=list(early.values()),list(late.values())
            va,vb=variance(a)/len(a),variance(b)/len(b)
            estimate=mean(b)-mean(a);se=math.sqrt(va+vb)
            denom=va**2/(len(a)-1)+vb**2/(len(b)-1)
            df=(va+vb)**2/denom if denom else None
            out["method"]="Welch t test of individual log ratios in independent time cohorts"
        if se<=1e-12 or df is None:
            reasons.append("zero or numerically degenerate between-animal variance; a t-based sampling interval is not estimable")
            results.append(out);continue
        statistic=estimate/se;p=1. if abs(statistic)<1e-12 else min(1.,max(0.,2*(1-COMMON._t_cdf(abs(statistic),df))))
        critical=COMMON.t_ppf(1-alpha/(2*family),df)
        ci=[estimate-critical*se,estimate+critical*se]
        out.update(status="ASSESSED",log_fold_change=estimate,fold_change=_ratio_exp(estimate),se_log_fold=se,df=df,t=statistic,
                   p_raw=p,p_adjusted=min(1.,p*family),ci_log_fold=ci,ci_fold=[_ratio_exp(x) for x in ci],
                   ci_family_coverage=1-alpha,different_at_family_alpha=(p*family<alpha),
                   reading="CHANGE_DETECTED" if p*family<alpha else "CHANGE_NOT_DETECTED")
        results.append(out)
    return results


def _ratio_exp(value):
    """Keep log-scale inference usable when a fold exceeds floating-point range."""
    try:return math.exp(value)
    except OverflowError:return None


def _ratio_test_evidence(tests):
    return {"rule": "Prespecified two-time contrasts use paired tissue/plasma measurements within each animal. Longitudinal changes use paired t; independent time cohorts use Welch t. All configured comparisons share Bonferroni correction; this is not T8 or a mechanism test.",
            "data": [], "tables": [{"caption": "Prespecified organ ratio changes", "head": ["Comparison", "Organ / times (h)", "Design / animals", "Late/early fold", "Family-adjusted interval", "Adjusted p", "Result / exclusion reason", "Source / prespecification"],
                "rows": [[x["id"],str(x.get("organ"))+" / "+str(x.get("times_h")),str(x.get("design"))+" / "+str([x.get("n_early"),x.get("n_late")]),
                    _f(x.get("fold_change")), "–".join(_f(v) for v in x["ci_fold"]) if x.get("ci_fold") else "not estimable", _f(x.get("p_adjusted"),4),
                    x["reading"].lower().replace("_"," ") if x.get("reading") else "; ".join(x.get("exclusion_reasons",[])),str(x.get("source"))+" / "+str(x.get("prespecification_source"))] for x in tests]}]}


def _route_word(rc):
    rc = str(rc)
    if not re.fullmatch(r"[A-Z_]+", rc):
        return rc
    return {"OTHER_EV": "other extravascular", "EV": "extravascular", "IV": "IV", "SC": "SC", "IM": "IM", "PO": "PO", "IP": "IP", "IT": "IT"}.get(rc, rc.replace("_", " ").lower())


def _route_name(s):
    """Route in the reader's words. A source route such as IT or IP is used when the route detail is only a class (OTHER_EV)."""
    rd = str(s.get("route_detail") or "NOT_FOUND")
    own = str(s.get("route_source") or "").strip()
    if rd in ("NOT_FOUND", "OTHER_EV", "EV", "") and re.fullmatch(r"[A-Za-z][A-Za-z .-]{0,24}", own) and own.upper() not in ("NOT_FOUND", "EV", "OTHER_EV"):
        return own
    return _route_word(rd if rd != "NOT_FOUND" else s["route_class"])


def _names(ps, k=6):
    """Tissue names with repeats counted (same label from one table), at most k shown."""
    cnt = {}
    for p in ps:
        cnt[p["tissue"]] = cnt.get(p["tissue"], 0) + 1
    xs = [n + (f" ×{c}" if c > 1 else "") for n, c in cnt.items()]
    return ", ".join(xs[:k]) + (f" and {len(xs) - k} more" if len(xs) > k else "")


def _route_cell(s):
    """Route for a data card: class, detail when reported, IV mode in words."""
    bits = [s["route_class"]]
    rd = str(s.get("route_detail") or "NOT_FOUND")
    if rd != "NOT_FOUND" and rd.upper() not in ("IV_BOLUS", "IV_INFUSION", s["route_class"]):
        bits.append(_route_name(s))
    if s["route_class"] == "IV":
        bits.append({"BOLUS": "bolus", "INFUSION": f"infusion {_dur(s.get('infusion_h'))}" if s.get("infusion_h") else "infusion",
                     "INFUSION_TIMING_UNKNOWN": "infusion, end not reported", "IV_MODE_UNKNOWN": "IV mode not reported", "ONGOING_INPUT": "loading dose plus ongoing infusion"}.get(s["iv_mode"], s["iv_mode"]))
    return " · ".join(bits)


def _species_words(b):
    """Only the parts of the source species text that name this board's species (multi-species tables list all of them)."""
    out = []
    for t in b["species_text"]:
        for part in re.split(r";\s*", str(t)):
            if part and species_in(part) == b["species"] and part not in out:
                out.append(part)
    return "; ".join(out) if out else "; ".join(b["species_text"])


def _unique_tissue_labels(pairs):
    """Append dose and route (then dataset) when one study and species shows the same tissue name twice."""
    def key(p):
        return (p["study"], p["species"], p["tissue"])
    def dose_tag(t):
        r = _route_name(t)
        return f" ({_f(t['dose'])} mg/kg {r})" if t.get("dose") else f" ({r})"
    for tag in (dose_tag, lambda t: f" [{t['dataset_id']}]"):
        groups = {}
        for p in pairs:
            groups.setdefault(key(p), []).append(p)
        for ps in groups.values():
            # add a tag only when it separates the repeated name; identical repeats are counted later (×n)
            if len(ps) > 1 and len({tag(p["_t"]) for p in ps}) > 1:
                for p in ps:
                    p["tissue"] += tag(p["_t"])


def _auc_ratio_uncertainty(ts, rs, t, r):
    """Fieller interval with a delta-method AUC variance for independent destructive cohorts."""
    if not all(s["design"] == "DESTRUCTIVE" and s.get("sampling_dependence") == "INDEPENDENT_GROUPS_ACROSS_MATRICES_AND_TIMES" for s in (t, r)):
        return None, "covariance across times and matrices unknown; descriptive window AUC ratio"
    stats = []
    for points, series in ((ts, t), (rs, r)):
        if any(not p.get("sd") or not p.get("n") or p["n"] < 2 for p in points):
            return None, "sampling variance unavailable"
        time = [p["t"] for p in points]
        c = [p["c"] * series["uf"] for p in points]
        area = COMMON.auc(time, c)
        var = 0.0
        for i, p in enumerate(points):
            # Differentiate the same linear-up/log-down quadrature used for the estimate.
            step = c[i] * 1e-5
            plus, minus = c.copy(), c.copy()
            plus[i] += step
            minus[i] -= step
            gradient = (COMMON.auc(time, plus) - COMMON.auc(time, minus)) / (2 * step)
            var += (gradient * p["sd"] * series["uf"]) ** 2 / p["n"]
        stats.append((area, var))
    (num, vn), (den, vd) = stats
    critical = COMMON.t_ppf(.975, min(p["n"] - 1 for p in ts + rs))
    a = den*den - critical**2 * vd
    c = num*num - critical**2 * vn
    cross = num * den
    discriminant = cross**2 - a*c
    if a <= 0 or discriminant < 0:
        return None, "unbounded Fieller interval"
    delta = math.sqrt(discriminant)
    return [max(0, (cross-delta)/a), (cross+delta)/a], "approximate 95% Fieller interval, independent destructive cohorts"


def item26_pair(t, r, why_ref, dose_known_upper, cfg, r24_by_sid):
    rows = ratio_rows(t, r)
    q = _q(t["points"])
    disp = re.sub(r"\s*\((?:[µuμmn]g|%|dpm)[^)]*\)\s*$", "", str(t.get("matrix_label") or "").strip())
    res = {"tissue_sid": t["sid"], "tissue": disp if disp and disp.upper() not in ("NOT_FOUND", "MIXED") else (t["organ"] or "tissue"), "matrix_class": t["matrix_class"], "unit": t["unit"],
           "ref_sid": r["sid"] if r else None, "ref_label": (r["organ"] if r else None), "ref_unit": r["unit"] if r else None,
           "ratio_unit": ("mL/g" if t["matrix_class"] == "TISSUE_HOMOGENATE" and re.search(r"/(?:g|kg)\b", str(t["unit"]), re.I) else "dimensionless") if r else None, "rows": rows, "caveats": [], "candidates": [],
           "sampled_peak_h": max(q, key=lambda p: p["c"])["t"] if q else None, "last_quantified_h": q[-1]["t"] if q else None,
           "analyte": t["analyte"], "assay": t.get("assay"), "regimen": t.get("regimen"), "reference_reason": why_ref, "pairing": _pairing(t, r) if r else None}
    cav = res["caveats"]
    for f in t["flags"]:
        if f in ("MATRIX_UNKNOWN", "ELF_DILUTION_UNCORRECTED", "MICRODIALYSIS_UNCALIBRATED", "TOTAL_RADIOACTIVITY", "ACTIVE_MATERIAL"):
            cav.append(f)
    if t["digitized"]:
        cav.append("DIGITIZED")
    if t["design"] == "DESTRUCTIVE":
        cav.append("DESTRUCTIVE_SAMPLING")
    local = t.get("local") and ((t["local"] == "LUNG" and (t["matrix_class"] == "ELF" or (t["organ"] or "").lower() in ("lung", "elf")))
                                or (t["local"] == "CNS" and t["matrix_class"] == "CSF"))
    if local:
        cav.append("LOCAL_ROUTE")
    if t["matrix_class"] == "TISSUE_HOMOGENATE" and t["perfused"] != "YES":
        cav.append("RESIDUAL_BLOOD_UNCORRECTED")
    if t["matrix_class"] == "CSF":
        cav.append("CSF_NOT_BRAIN_ISF")
    if r:
        if res["pairing"] == "SAME_ANIMAL":
            res["ratio_estimator"] = "INDIVIDUAL_PAIR"
            cav.append("SAME_ANIMAL_PAIR")
        elif t["level"] == r["level"] == "GROUP_MEAN":
            res["ratio_estimator"] = "RATIO_OF_MEANS"
            cav.append("RATIO_OF_MEANS")
        else:
            res["ratio_estimator"] = "RECORD_PAIRING_UNVERIFIED"
            cav.append("RECORD_PAIRING_UNVERIFIED")
        if t["uf"] and r["uf"] and "g" in str(t["unit"]).lower() and "ml" in str(r["unit"]).lower():
            res["density_note"] = "µg/g over µg/mL has units mL/g; read as dimensionless only with a tissue density of 1 g/mL"
    usable = [x for x in rows if x["ratio"]]
    res["n_common_times"] = len(usable)
    blocked = [c for c in cav if c in ("MATRIX_UNKNOWN", "ELF_DILUTION_UNCORRECTED", "MICRODIALYSIS_UNCALIBRATED", "LOCAL_ROUTE")]
    _grp = {"LOCAL_ROUTE": "local route, dose given into this space", "ELF_DILUTION_UNCORRECTED": "ELF urea correction not reported",
            "MATRIX_UNKNOWN": "matrix not identified", "MICRODIALYSIS_UNCALIBRATED": "microdialysis recovery not calibrated"}
    if _baseline(t)[0] or (r and _baseline(r)[0]):
        blocked.append("ENDOGENOUS_REVIEW_REQUIRED")
        _grp["ENDOGENOUS_REVIEW_REQUIRED"] = "baseline review required"
    scheduled = sorted(set(t.get("scheduled_times", []) + [p["t"] for p in t["points"]]))
    ref_times = set(r.get("scheduled_times", []) + [p["t"] for p in r["points"]]) if r else set()
    window = [time for time in scheduled if any(_match(time, rt) for rt in ref_times)][-3:]
    res["scheduled_window_h"] = window
    res["unavailable_ratio_times_h"] = [row["t"] for row in rows if row["ratio"] is None]
    res["readable_window_h"] = [usable[0]["t"], usable[-1]["t"]] if usable else None
    window_rows = usable[-3:]
    window = [row["t"] for row in window_rows]
    res["assessed_window_h"] = window
    if not r:
        res.update(ratio_reading="NOT_ASSESSABLE", not_assessable_reason=why_ref, na_group="no reference profile")
    elif blocked:
        res.update(ratio_reading="NOT_ASSESSABLE", not_assessable_reason=", ".join(blocked) + ": no ratio reading (rules D0.2, D0.8)",
                   na_group=_grp[blocked[0]])
    elif len(usable) < 3:
        res["na_group"] = "fewer than 3 common times"
        undefined = [x["t"] for x in rows if x.get("ratio_status") == "UNDEFINED"]
        res.update(ratio_reading="NOT_ASSESSABLE", not_assessable_reason=f"{len(usable)} common quantified time{'s' if len(usable) != 1 else ''} with a usable reference; 3 are needed"
                   + (f" (reference BLQ or missing at {', '.join(_f(x) + ' h' for x in undefined)})" if undefined else ""))
    elif len(window_rows) != 3:
        res.update(ratio_reading="NOT_ASSESSABLE", not_assessable_reason="a scheduled late ratio is missing or censored",
                   na_group="incomplete scheduled window")
    else:
        a, mid, b = window_rows
        ch = ratio_change(a, b, t["digitized"] or r["digitized"], local)
        res["dis4b"] = ch
        rd = "NO_DIFFERENCE_SEEN"
        if ch["outside_band"]:
            rd = ("TISSUE_NOT_FALLING" if b["tissue"] >= a["tissue"] else "RISING") if ch["d"] > 0 else "FALLING"
        low, high = ch["band_used"]
        if rd == "NO_DIFFERENCE_SEEN" and not low <= mid["ratio"] / a["ratio"] <= high:
            rd = "VARIABLE_WITHIN_WINDOW"
        res["ratio_reading"] = rd
        independent = all(s.get("sampling_dependence") == "INDEPENDENT_GROUPS_ACROSS_MATRICES_AND_TIMES" for s in (t, r)) and not any(a["t"] <= missing <= b["t"] for missing in res["unavailable_ratio_times_h"])
        res["t8_label"] = "CANNOT_ASSESS"
        res["t8_reason"] = "the sample covariance or a suitable joint uncertainty bound was not reported"
        res["ratio_reading_flags"] = ["SENSITIVITY_ONLY"]
        if independent and ch.get("fold_ci") and t["route_class"] == "IV" and t["iv_mode"] in ("BOLUS", "INFUSION") and a["t"] > (t.get("infusion_h") or 0):
            # A three-occasion constant-ratio exclusion must survive removing any one occasion.
            contrasts = [ratio_change(x, y, t["digitized"] or r["digitized"], local, comparisons=3)
                         for x, y in itertools.combinations(window_rows, 2)]
            cis = [x.get("fold_ci") for x in contrasts]
            if all(cis):
                robust = all(lo > high for lo, hi in cis) or all(hi < low for lo, hi in cis)
                res.update(t8_label="EXCLUDED_UNDER_STATED_ASSUMPTIONS" if robust else "NOT_EXCLUDED",
                           t8_intervals=cis, ratio_reading_flags=[],
                           t8_reason="three scheduled contrasts with simultaneous limits and leave-one-occasion support")
        res["candidates"] = {"RISING": ["slow tissue compartment", "specific binding", "active uptake"],
                             "TISSUE_NOT_FALLING": ["active uptake", "specific binding", "accumulation"],
                             "FALLING": ["elimination in the tissue", "efflux", "redistribution"]}.get(rd, [])
        # observed-window AUC ratio (rules D0.6)
        t0, t1 = usable[0]["t"], usable[-1]["t"]
        tq = [p for p in _q(t["points"]) if t0 - 1e-9 <= p["t"] <= t1 + 1e-9]
        rq = [p for p in _q(r["points"]) if t0 - 1e-9 <= p["t"] <= t1 + 1e-9]
        continuous = all(all(any(math.isclose(x["t"], time, abs_tol=1e-9) for x in pts)
                             for time in s.get("scheduled_times", []) if t0 <= time <= t1) for s, pts in ((t, tq), (r, rq)))
        if continuous and len(tq) >= 2 and len(rq) >= 2 and tq[0]["t"] == rq[0]["t"] and tq[-1]["t"] == rq[-1]["t"]:
            at = COMMON.auc([p["t"] for p in tq], [p["c"] * t["uf"] for p in tq])
            ar = COMMON.auc([p["t"] for p in rq], [p["c"] * r["uf"] for p in rq])
            if ar > 0:
                ci, note = _auc_ratio_uncertainty(tq, rq, t, r)
                res["window_auc_ratio"] = {"window_h": [t0, t1], "ratio": at / ar, "ci": ci, "ci_note": note,
                                           "label": "homogenate, total" if t["matrix_class"] == "TISSUE_HOMOGENATE" else "total"}
        # An observed stable ratio becomes a Kp bound only under separately documented exchange assumptions.
        if independent and res.get("t8_intervals") and all(low <= lo <= hi <= high for lo, hi in res["t8_intervals"]):
            res["window_stability"] = "WITHIN_BAND_AT_ALL_THREE_TIMES"
            premises = t.get("exchange_premises") or {}
            if (premises.get("source") and all(premises.get(k) is True for k in ("linear_exchange", "non_eliminating_tissue", "terminal_plateau"))
                    and r["occasion"] == "FIRST_DOSE" and rd == "NO_DIFFERENCE_SEEN"):
                res["plateau_ratio"] = b["ratio"]
                res["plateau_statement"] = "Conditional steady-state Kp upper bound under the documented terminal plateau assumptions."
                auc = res.get("window_auc_ratio")
                if auc and (t0 == 0 or tq[-1]["c"] >= tq[0]["c"]) and auc["ratio"] <= b["ratio"]:
                    res["kp_bracket"] = {"lower": auc["ratio"], "upper": b["ratio"], "source": premises["source"]}
        # residual-blood sensitivity (step 12)
        res["residual_blood_sensitivity"] = residual_blood(t, r, a, b, rd, cfg)
        if res["residual_blood_sensitivity"].get("changes_reading"):
            res["ratio_reading_flags"] = ["SENSITIVITY_ONLY"]
            res["t8_label"] = "CANNOT_ASSESS"
            res["t8_reason"] = "the reading changes under residual-blood correction"
            for key in ("plateau_ratio", "plateau_statement", "kp_bracket", "window_stability"):
                res.pop(key, None)
    if r and not blocked and len(usable) >= 3:
        res["phase_loop"] = _phase_direction(usable)
    return res


def _phase_direction(rows):
    """Compare outbound and return branches only across their observed common reference range."""
    xy = [(math.log(p["ref"]), math.log(p["tissue"])) for p in rows]
    dx = [b[0] - a[0] for a, b in zip(xy, xy[1:])]
    turns = [i for i in range(1, len(dx)) if dx[i] * dx[i - 1] < 0]
    if len(turns) != 1 or any(d == 0 for d in dx):
        return "OPEN_TRAJECTORY"
    k = turns[0]
    first, second = sorted(xy[:k + 1]), sorted(xy[k:])
    lo, hi = max(first[0][0], second[0][0]), min(first[-1][0], second[-1][0])
    if lo >= hi:
        return "OPEN_TRAJECTORY"

    def ordinate(branch, x):
        for (x0, y0), (x1, y1) in zip(branch, branch[1:]):
            if x0 <= x <= x1:
                return y0 + (x - x0) * (y1 - y0) / (x1 - x0)

    knots = sorted({x for x, _ in xy if lo <= x <= hi})
    gaps = [(ordinate(second, x) - ordinate(first, x)) * (1 if dx[0] > 0 else -1) for x in knots]
    if max(abs(d) for d in gaps) < 1e-9:
        return "NONE"
    if min(gaps) >= -1e-9:
        return "COUNTER_CLOCKWISE"
    if max(gaps) <= 1e-9:
        return "CLOCKWISE"
    return "OPEN_TRAJECTORY"


def residual_blood(t, r, a, b, reading, cfg):
    if t["matrix_class"] != "TISSUE_HOMOGENATE":
        return {"status": "not applicable (not a homogenate)"}
    if t["perfused"] == "YES":
        return {"status": "not applicable (perfused tissue)"}
    rb = cfg.get("residual_blood") or {}
    vr = (rb.get("V_r") or {}).get(t["organ"] or "")
    hct = (rb.get("hct") or {}).get(t["species"])
    bp = (rb.get("bp") or {}).get(t["species"])
    if vr is None:
        return {"status": "not run: no sourced V_r for %s in the run configuration" % (t["organ"] or "this tissue"),
                "caveat": "RESIDUAL_BLOOD_UNCORRECTED"}
    bps = [bp] if bp else [x for x in ((1 - hct) if hct else None, rb.get("bp_upper")) if x]
    if not bps:
        return {"status": "not run: neither B:P nor haematocrit in the run configuration", "caveat": "RESIDUAL_BLOOD_UNCORRECTED"}
    out = {"V_r": vr, "bp_values": bps, "source": rb.get("source", ""), "rows": []}
    changes = False
    for bpv in bps:
        def corr(x):
            ct = x["tissue"] * t["uf"]
            cp = x["ref"] * r["uf"]
            return max((ct - vr * bpv * cp) / (1 - vr), 1e-12) / cp
        ra, rbb = corr(a), corr(b)
        fold = rbb / ra
        band = BAND_DIGITIZED if t["digitized"] else BAND
        same = (band[0] <= fold <= band[1]) == (reading == "NO_DIFFERENCE_SEEN")
        out["rows"].append({"bp": bpv, "ratio_early": ra, "ratio_late": rbb, "fold": fold, "reading_unchanged": same})
        changes = changes or not same
    out["changes_reading"] = changes
    out["status"] = "SENSITIVITY_ONLY" if changes else "unchanged"
    return out


def d3_check(dataset_series, dose, cfg):
    """D3 mass-balance pre-check on one tissue table (rules item 26 steps 1-5)."""
    tis = [s for s in dataset_series if s["matrix_class"] == "TISSUE_HOMOGENATE" and s["analyte"] == "PARENT" and s["uf"] and not _baseline(s)[0]]
    if not tis:
        return {"d3_status": "NOT_APPLICABLE", "reason": "no tissue homogenate"}
    if not dose:
        return {"d3_status": "NOT_ASSESSABLE", "reason": "dose per kg not found"}
    sp = tis[0]["species"]
    ow = (cfg.get("organ_weights_g_per_kg") or {}).get(sp) or {}
    times = sorted({p["t"] for s in tis for p in _q(s["points"])})
    equiv = []
    for s in tis:
        for p in _q(s["points"]):
            L = p["c"] * (s["uf"] or 1) * (1 - TOL)
            equiv.append({"tissue": s["organ"], "t": p["t"], "dose_equivalent_g_per_kg": dose * 1000 / L if L > 0 else None})
    out = {"dose_mg_per_kg": dose, "dose_equivalent_mass": equiv, "species": sp}
    weights = {s["organ"]: _num(ow.get(s["organ"])) for s in tis}
    if not ow or not any(weights.values()):
        return out | {"d3_status": "NOT_ASSESSABLE", "reason": f"no organ weights for {sp} in the run configuration; the dose-equivalent mass "
                      "(tissue weight per kg body weight that would hold the whole dose at the measured lower concentration) is listed instead"}
    matched = ow.get("same_study") is True or str(ow.get("matched_on", "")).lower().startswith("species, strain, age, body weight")
    formal = bool(ow.get("source") and matched and ow.get("lower_fraction") and 0 < ow["lower_fraction"] <= 1
                  and ow.get("dose_upper_mg_per_kg") and ow["dose_upper_mg_per_kg"] >= dose and ow.get("disjoint_whole_organs") is True
                  and all(s["occasion"] == "FIRST_DOSE" for s in tis) and len(weights) == len(tis))
    rows = []
    for t in times:
        parts = []
        for s in tis:
            p = next((x for x in _q(s["points"]) if x["t"] == t), None)
            w = weights.get(s["organ"])
            if p and w and w > 0:
                L = p["c"] * s["uf"] * (ow["lower_fraction"] if formal else 1 - TOL)
                parts.append({"tissue": s["organ"], "amount_ug_per_kg": L * w, "pct_dose": 100 * L * w / ((ow["dose_upper_mg_per_kg"] if formal else dose) * 1000)})
        tot = sum(x["pct_dose"] for x in parts)
        rows.append({"t": t, "parts": parts, "sum_pct_dose_lower": tot})
    worst = max(rows, key=lambda x: x["sum_pct_dose_lower"]) if rows else None
    over = worst and worst["sum_pct_dose_lower"] > 100
    status = ("DATA_ISSUE" if over else "PASS") if formal else ("SENSITIVITY_ONLY" if over else "PASS")
    return out | {"d3_status": status, "formal": formal, "rows": rows, "d3_sum_pct_dose_lower": worst["sum_pct_dose_lower"] if worst else None,
                  "organ_weight_source": ow.get("source", ""), "missing_weights": [k for k, v in weights.items() if not v],
                  "note": None if formal else "organ weights not same-study or not matched on species, strain, age and body weight: SENSITIVITY_ONLY, cannot set DATA_ISSUE"}


def repeat_dose(series):
    """Within-arm accumulation at matched times; retain the first and later reference sources."""
    groups = {}
    for s in series:
        if s["uf"] and not s.get("endogenous") and s["dose"] and s["dose"] > 0:
            key = (s["study"], s["species"], s["drug"], s["route_detail"], s["iv_mode"], COMMON.input_nominal(s), s["analyte"],
                   s["dose_basis"], s["level"], s["matrix_label"].lower(), s["dose"], s.get("condition"), s.get("animal"))
            groups.setdefault(key, []).append(s)
    out = []
    for ss in groups.values():
        first = [s for s in ss if s["occasion"] == "FIRST_DOSE" and not _baseline(s)[0]]
        if len(first) != 1:
            continue
        f = first[0]
        for later in (s for s in ss if s["occasion"] == "LATER_DOSE"):
            rows = []
            for p in _q(f["points"]):
                hits = [x for x in _q(later["points"]) if _match(x["t"], p["t"])]
                if len(hits) != 1 or p["t"] < 0:
                    continue
                m = hits[0]
                cf, cl = p["c"] * f["uf"], m["c"] * later["uf"]
                size = len(f["points"]) + len(later["points"])
                lf, _, uf = log_interval(p, f["level"], family_size=size)
                _, hl, ul = log_interval(m, later["level"], family_size=size)
                rows.append({"t": p["t"], "first": cf, "later": cl, "AR": cl / cf,
                             "supported": uf == ul == "SAMPLING_ERROR", "M_T9": math.exp(lf) * f["uf"] - math.exp(hl) * later["uf"]})
            if rows:
                supported = (all(r["supported"] for r in rows) and f["level"] == later["level"] == "GROUP_MEAN"
                             and f["dose_basis"] not in (None, "", "NOT_FOUND") and f.get("regimen_comparable") and later.get("regimen_comparable"))
                robust = sum(r["M_T9"] > 0 for r in rows) >= 2
                out.append({"matrix": f["matrix_label"], "matrix_class": f["matrix_class"], "first_sid": f["sid"],
                            "later_sid": later["sid"], "rows": rows, "t9_label": ("EXCLUDED_UNDER_STATED_ASSUMPTIONS" if robust else "NOT_EXCLUDED") if supported else "CANNOT_ASSESS",
                            "t9_flags": [] if supported else ["SENSITIVITY_ONLY"], "t9_reason": "matched regimen and simultaneous bounds" if supported else "regimen comparability or source uncertainty unresolved"})
    by_sid = {s["sid"]: s for s in series}
    refs = [s for s in series if s["matrix_class"] in REF_CLASSES and not s["unbound"]]
    by_pair = {(d["first_sid"], d["later_sid"]): d for d in out}
    for d in out:
        if d["matrix_class"] not in TISSUE_CLASSES:
            continue
        a, b = by_sid[d["first_sid"]], by_sid[d["later_sid"]]
        rf, _ = find_reference(a, refs)
        rl, _ = find_reference(b, refs)
        ref = by_pair.get((rf["sid"], rl["sid"])) if rf and rl else None
        d["relative_rows"] = []
        if ref and rl["occasion_day"] == b["occasion_day"] and not (_baseline(a)[0] or a.get("local")):
            d["reference_series"] = [rf["sid"], rl["sid"]]
            for row in d["rows"]:
                hits = [x for x in ref["rows"] if _match(x["t"], row["t"])]
                if len(hits) == 1:
                    ar = hits[0]["AR"]
                    d["relative_rows"].append({"t": row["t"], "ar_tissue": row["AR"], "ar_reference": ar,
                                               "relative_accumulation": row["AR"] / ar})
    return out


def _fu_from(measure, header, v):
    s = (str(measure or "") + " " + str(header or "")).lower()
    if "unbound" in s or "free" in s or re.search(r"\bfu\b", s):
        return v / 100 if "%" in s or "percent" in s or v > 1 else v
    return 1 - v / 100


def binding_records(entry):
    meta = entry.get("metadata", {})
    cols = entry.get("columns", [])
    bcols = [c for c in cols if c.get("meaning") == "BINDING" and str(c.get("unit", "")).strip() in ("%", "NOT_FOUND", "")]
    measure_col = next((c for c in cols if c.get("meaning") == "BINDING" and "measure" in str(c.get("header", "")).lower()), None)
    vcols = [c for c in bcols if c is not measure_col]
    conc_col = next((c for c in cols if c.get("meaning") == "CONCENTRATION"), None)
    meth_col = next((c for c in cols if re.search(r"method", str(c.get("header", "")).lower())), None)
    sp_col = next((c for c in cols if re.search(r"species|serum|plasma material", str(c.get("header", "")).lower())
                   and c.get("meaning") in ("COVARIATE", "GROUP_OR_TREATMENT")), None)
    study_col = next((c for c in cols if str(c.get("header", "")).lower() == "study"), None)
    sd_col = next((c for c in cols if c.get("meaning") == "SUMMARY_STATISTIC"), None)
    time_col = next((c for c in cols if c.get("meaning") == "TIME"), None)
    bound_se_col = next((c for c in cols if c.get("meaning") == "SE" and re.search(r"bound|binding", str(c.get("header", "")), re.I)), None)
    conc_se_col = next((c for c in cols if c.get("meaning") == "SE" and re.search(r"concentration", str(c.get("header", "")), re.I)), None)
    out = []
    for r in entry.get("records", []):
        for c in vcols:
            raw, status = _cell(r, c["id"])
            v, sd, n, st = parse_value(raw, status)
            if st != "QUANTIFIED" or v is None:
                continue
            if sd is None and sd_col:
                sd = _num(r.get(sd_col["id"]))
            head = c.get("header", "")
            meas = r.get(measure_col["id"]) if measure_col else ""
            sp = species_in(head) or species_in(r.get(sp_col["id"]) if sp_col else "") or species_group(meta.get("species", ""))
            meth = (r.get(meth_col["id"]) if meth_col else None) or ("equilibrium dialysis" if re.search(r"\bED\b", head) else
                                                                   "ultrafiltration" if re.search(r"\bUF\b", head) else
                                                                   meta.get("binding_method") or "not reported")
            fu = _fu_from(meas, head + " " + str(c.get("unit", "")), v)
            out.append({"dataset_id": entry["dataset_id"], "study": (str(r.get(study_col["id"])) if study_col and r.get(study_col["id"])
                                                                    else ",".join(entry.get("study_source_ids", []))),
                        "table_study": ",".join(entry.get("study_source_ids", [])), "drug": meta.get("drug"), "species": sp, "matrix": meta.get("matrix", ""),
                        "method": str(meth), "conc": _num(r.get(conc_col["id"])) if conc_col else None,
                        "conc_unit": conc_col.get("unit") if conc_col else None, "fu": fu, "reported": f"{v:g}% {'unbound' if fu * 100 == v or abs(fu - v / 100) < 1e-9 else 'bound'}",
                        "sd_pct": sd, "se_pct": _num(r.get(bound_se_col["id"])) if bound_se_col else None,
                        "conc_se": _num(r.get(conc_se_col["id"])) if conc_se_col else None,
                        "conc_se_unit": conc_se_col.get("unit") if conc_se_col else None,
                        "n": _num(r.get("n")) or n or meta.get("n_animals") or meta.get("n_samples"),
                        "n_basis": r.get("n_basis") or meta.get("experimental_unit") or ("animals" if meta.get("n_animals") else "samples" if meta.get("n_samples") else None),
                        "record_id": r.get("record_id"), "source_pointer": r.get("source_pointer"),
                        "source_refs": entry.get("source_refs") or [],
                        "basis": str(meta.get("binding_basis") or "").upper() or None, "analyte": meta.get("analyte"),
                        "analyte_role": meta.get("analyte_role"),
                        "time_h": COMMON.observation_time_h(r, time_col or {}),
                        "condition": meta.get("condition"), "source_conflicts": entry.get("source_conflicts") or meta.get("source_conflicts") or []})
    return out


def _site_unbound(binding, tissues, refs):
    """Observed site/plasma ratios, with no band classification of isolated points."""
    plasma = {s["sid"]: s for s in refs}
    by_sid = {}
    for p in binding["unbound_points"]:
        by_sid.setdefault(p["sid"], []).append(p)
    sites = []
    for t in tissues:
        if not t["uf"] or t.get("local") or t["analyte"] != "PARENT" or _baseline(t)[0]:
            continue
        factor = 1.0
        if t["matrix_class"] == "ISF_MICRODIALYSIS" and t["recovery_calibrated"] == "YES":
            basis = "recovery-corrected microdialysate"
        elif t["matrix_class"] == "TISSUE_HOMOGENATE":
            method = t.get("tissue_fu") or {}
            fraction = _num(method.get("value"))
            if (not fraction or not 0 < fraction <= 1 or not method.get("source") or not method.get("method")
                    or method.get("organ") != t["organ"] or not method.get("dilution_corrected")
                    or not (method.get("residual_blood_corrected") or t["perfused"] == "YES")
                    or not _num(method.get("density_g_per_ml")) or float(method["density_g_per_ml"]) <= 0):
                continue
            factor = fraction * float(method["density_g_per_ml"])
            basis = "corrected homogenate with sourced tissue fu and density"
        else:
            continue
        # Prefer direct unbound observations and a shared table/group. Refuse an ambiguous arm.
        candidates = [s for sid, s in plasma.items() if sid in by_sid and all(s.get(k) == t.get(k) for k in
                      ("study","species","drug","dose","dose_basis","route_detail","occasion","occasion_day","condition","animal"))
                      and s["dose"] and _group_prefix(s) == _group_prefix(t)]
        candidates.sort(key=lambda s: (not s["unbound"], s["dataset_id"] != t["dataset_id"]))
        if not candidates:
            continue
        r = candidates[0]
        if sum((s["unbound"], s["dataset_id"] == t["dataset_id"]) == (r["unbound"], r["dataset_id"] == t["dataset_id"]) for s in candidates) != 1:
            continue
        rows = []
        for point in _q(t["points"]):
            hits = [p for p in by_sid[r["sid"]] if _match(p["t"], point["t"])]
            if len(hits) == 1:
                cu = point["c"] * t["uf"] * factor
                rows.append({"t": point["t"], "cu_site": cu, "cu_plasma": hits[0]["cu_mg_l"],
                             "ratio": cu / hits[0]["cu_mg_l"], "records": [point["record_id"], hits[0]["record_id"]],
                             "site_sd": point["sd"] * t["uf"] if t["matrix_class"] == "ISF_MICRODIALYSIS" and t["level"] == "GROUP_MEAN" and point.get("sd") else None,
                             "site_n": point.get("n"), "plasma_sd": hits[0].get("sd_mg_l"), "plasma_n": hits[0].get("n")})
        if not rows:
            continue
        site = {"tissue_sid": t["sid"], "ref_sid": r["sid"], "site": t["matrix_label"], "basis": basis, "rows": rows,
                "estimator": "KPUU_APPARENT", "position": "UNRESOLVED"}
        times = [x["t"] for x in rows]
        full_interval = (t["interval_h"] and t["interval_h"] == r["interval_h"] and math.isclose(times[-1] - times[0], t["interval_h"], rel_tol=1e-6))
        if ((t["equilibrated"] and r["equilibrated"] or t["steady_state"] and r["steady_state"] and full_interval) and len(rows) >= 2 and len(rows) == len(t["points"]) == len(r["points"])
                and all(a < b for a, b in zip(times, times[1:]))):
            site.update(estimator="unbound AUC ratio over a supported equilibrium window or complete steady-state interval", window_h=[times[0], times[-1]],
                        auc_ratio=COMMON.auc(times, [x["cu_site"] for x in rows]) / COMMON.auc(times, [x["cu_plasma"] for x in rows]))
            if all(x.get(k + "_sd") and (x.get(k + "_n") or 0) > 1 for x in rows for k in ("site", "plasma")):
                # Simultaneous marginal bands bound both AUCs without assuming independence of paired matrices.
                bounds = {}
                for k in ("site", "plasma"):
                    intervals = [log_interval({"c": x["cu_" + k], "sd": x[k + "_sd"], "n": x[k + "_n"]},
                                              "GROUP_MEAN", tol=0, family_size=2 * len(rows)) for x in rows]
                    bounds[k] = [COMMON.auc(times, [math.exp(v[j]) for v in intervals]) for j in (0, 1)]
                lo, hi = bounds["site"][0]/bounds["plasma"][1], bounds["site"][1]/bounds["plasma"][0]
                site["interval"] = [lo, hi]
                site["position"] = "ABOVE" if lo > KPUU_BAND[1] else "BELOW" if hi < KPUU_BAND[0] else "INSIDE" if KPUU_BAND[0] <= lo <= hi <= KPUU_BAND[1] else "UNRESOLVED"
                site["interval_basis"] = "simultaneous 95% group-mean bands; conditional on the reported recovery correction"
        sites.append(site)
    binding["kpuu"] = {"position": sites[0]["position"] if sites and len({s["position"] for s in sites}) == 1 else "SITE_SPECIFIC" if sites else "NOT_ASSESSABLE", "sites": sites,
                        "reason": "point ratios or window estimate without supported interval" if sites else "no eligible matched unbound site and plasma profiles"}


def item27(study, species, binding, ref_series):
    candidates = [b for b in binding if b["species"] == species and 0 < b["fu"] <= 1
                  and classify_matrix(b.get("matrix", ""))[0] in ("PLASMA", "SERUM")]
    ex_vivo = [b for b in candidates if b.get("basis") == "EX_VIVO_AFTER_DOSING"]
    # Unknown or mixed signals cannot supply parent fu, including a radiolabel mixture.
    candidates = [b for b in candidates if b.get("basis") != "EX_VIVO_AFTER_DOSING"
                  and (b.get("analyte_role") == "PARENT" or
                       (not b.get("analyte_role") and b.get("analyte") and analyte_of(b["analyte"]) == "PARENT"
                        and (re.search(r"\bparent\b|\bunchanged\b|\bintact\b", str(b["analyte"]), re.I)
                             or (b.get("drug") and str(b["analyte"]).lower().strip() == str(b["drug"]).lower().strip()))))
                  and not b.get("source_conflicts")]
    ex_vivo = [b for b in ex_vivo if not b.get("source_conflicts")]
    same = [b for b in candidates if b["study"] == study]
    recs = same or candidates
    out = {"fu_table": recs, "fu_studies": sorted({b["study"] for b in recs}), "unbound_points": [],
           "plasma_unbound_status": "UNKNOWN", "caveats": ["FU_OTHER_STUDY"] if recs and not same else [],
           "unbound_auc_window": [], "constant_fu_sources": [], "fu_concentration_dependence": []}
    assays = {}
    for b in recs:
        factor = unit_factor(b.get("conc_unit"))
        # Binding brackets need concentration per volume; mass/mass is not a plasma mg/L bracket.
        unit = str(b.get("conc_unit") or "").lower().replace(" ", "")
        if factor and not re.search(r"/(?:g|kg)$", unit) and b.get("conc") is not None and b["conc"] > 0:
            key = (b["study"], b["method"], b["dataset_id"], classify_matrix(b["matrix"])[0], b.get("drug"))
            assays.setdefault(key, []).append((b["conc"] * factor, b))
    # Conflicting replicates at the same concentration are not a stable assay bracket.
    assays = {key: ms for key, ms in assays.items()
              if all(len({b["fu"] for cc, b in ms if cc == c}) == 1 for c, _ in ms)}
    for key, measurements in assays.items():
        cs = sorted({c for c, _ in measurements})
        if len(cs) < 2:
            continue
        fus = [b["fu"] for _, b in measurements]
        fold = max(fus) / min(fus)
        dep = {"study": key[0], "method": key[1], "dataset_id": key[2], "matrix": key[3],
               "conc_range": [cs[0], cs[-1]], "conc_unit": "mg/L", "fu_range": [min(fus), max(fus)],
               "fold": fold, "reading": "CHANGING" if fold > BAND[1] else "STABLE"}
        out["fu_concentration_dependence"].append(dep)
        if dep["reading"] == "CHANGING" and "NONLINEAR_BINDING" not in out["caveats"]:
            out["caveats"].append("NONLINEAR_BINDING")
    plasma = [s for s in ref_series if s["matrix_class"] == "PLASMA" and s["analyte"] == "PARENT" and s["uf"] and not s.get("source_conflicts")]
    all_pk = []
    for s in plasma:
        pts = _q(s["points"])
        pk = [p["c"] * s["uf"] for p in pts]
        if not pk:
            continue
        compatible = [(key, ms) for key, ms in assays.items() if key[0] == study and key[3] == "PLASMA"
                      and key[1] and key[1].lower() not in ("not reported", "not_found", "unknown")
                      and key[4] == s.get("drug") and key[4] not in (None, "", "NOT_FOUND")
                      and all(b.get("condition") == s.get("condition") for _, b in ms)]
        if not s["unbound"]:
            all_pk.extend(pk)
            for key, ms in compatible:
                cs = [c for c, _ in ms]
                fus = [b["fu"] for _, b in ms]
                if len(set(cs)) >= 2 and min(cs) <= min(pk) <= max(pk) <= max(cs) and max(fus)/min(fus) <= BAND[1]:
                    out["constant_fu_sources"].append({"dataset_id": key[2], "method": key[1], "series": s["sid"],
                                                       "fu_range": [min(fus), max(fus)], "drug": key[4], "condition": s.get("condition")})
        series_points = []
        for p, c in zip(pts, pk):
            point = {"sid": s["sid"], "record_id": p.get("record_id"), "t": p["t"]}
            if s["unbound"] and s["level"] == "GROUP_MEAN" and p.get("sd") and p.get("n") and p["n"] > 1:
                point.update(sd_mg_l=p["sd"] * s["uf"], n=p["n"])
            if s["unbound"]:
                point.update(cu_mg_l=c, basis="MEASURED")
            else:
                matches = []
                for key, ms in compatible:
                    exact = [b for cc, b in ms if math.isclose(c, cc, rel_tol=1e-8)]
                    # A single assay can transfer at its measured concentration. Across concentrations use
                    # only an unambiguous constant fraction spanning this point; never average different assays.
                    fus = {b["fu"] for _, b in ms}
                    cs = [cc for cc, _ in ms]
                    used = exact or ([b for _, b in ms] if len(fus) == 1 and min(cs) <= c <= max(cs) else [])
                    # With small measured variation across a bracket, report the interpolation explicitly.
                    if not used and len(cs) == len(set(cs)) and min(cs) < c < max(cs) and max(fus)/min(fus) <= BAND[1]:
                        lower, upper = max((v for v in ms if v[0] < c), key=lambda v: v[0]), min((v for v in ms if v[0] > c), key=lambda v: v[0])
                        weight = (c-lower[0])/(upper[0]-lower[0])
                        fv = lower[1]["fu"] + weight*(upper[1]["fu"]-lower[1]["fu"])
                        matches.append((fv, key, [lower[1].get("record_id"), upper[1].get("record_id")], "interpolated between stable measured fractions"))
                    if used and len({b["fu"] for b in used}) == 1:
                        matches.append((used[0]["fu"], key, [b.get("record_id") for b in used], "matched measured fraction" if exact else "constant measured fraction over bracket"))
                if len(matches) != 1:
                    continue
                fu, key, ids, conversion = matches[0]
                point.update(cu_mg_l=c * fu, total_mg_l=c, basis="DERIVED", fu=fu, conversion=conversion, binding_dataset=key[2],
                             method=key[1], binding_records=ids)
            series_points.append(point)
        out["unbound_points"].extend(series_points)
        if len(series_points) >= 2 and len(series_points) == len(pts) and all(p["status"] == "QUANTIFIED" or COMMON.is_predose_zero(p) for p in s["points"]):
            times = [p["t"] for p in series_points]
            if all(b > a for a, b in zip(times, times[1:])):
                out["unbound_auc_window"].append({"sid": s["sid"], "window_h": [times[0], times[-1]],
                                                 "auc_mg_h_l": COMMON.auc(times, [p["cu_mg_l"] for p in series_points])})
    if all_pk:
        out["pk_range"] = [min(all_pk), max(all_pk)]
        out["pk_range_covered"] = bool(out["constant_fu_sources"]) if len(plasma) == 1 else None
    if out["unbound_points"]:
        out["plasma_unbound_status"] = "MEASURED" if any(p["basis"] == "MEASURED" for p in out["unbound_points"]) else "DERIVED"
    out["kpuu"] = {"position": "NOT_ASSESSABLE", "reason": "matched unbound tissue and plasma exposure unavailable"}
    out["ex_vivo_binding"] = [dict(b, bound_pct=100 * (1 - b["fu"])) for b in sorted(ex_vivo, key=lambda b: (b["dataset_id"], b.get("time_h") or 0))]
    out["conditional_fu"] = None
    if out["plasma_unbound_status"] == "UNKNOWN" and all_pk:
        drugs = {s.get("drug") for s in plasma if not s["unbound"]}
        opts = []
        for key, ms in assays.items():
            cs, fus = [c for c, _ in ms], [b["fu"] for _, b in ms]
            if (key[3] != "PLASMA" or len(set(cs)) < 2 or max(fus) / min(fus) > BAND[1]
                    or key[4] not in drugs or key[4] in (None, "", "NOT_FOUND")
                    or key[1].lower() in ("not reported", "not_found", "unknown", "")
                    or any(b.get("condition") and any(b["condition"] != s.get("condition") for s in plasma if not s["unbound"]) for _, b in ms)) :
                continue
            inside = sum(min(cs) <= c <= max(cs) for c in all_pk)
            if inside:
                opts.append((-inside, key[0] != study, key[2], key, cs, fus, inside))
        # Multiple assays require agreement; selecting the most convenient assay hides contradictions.
        if opts and max(max(o[5]) for o in opts) / min(min(o[5]) for o in opts) <= BAND[1]:
            _, other, _, key, cs, fus, inside = min(opts, key=lambda o: o[:3])
            support = None
            matching_ex_vivo = [b for b in out["ex_vivo_binding"] if b.get("drug") == key[4]]
            if matching_ex_vivo:
                efu = [b["fu"] for b in matching_ex_vivo]
                ets = [b["time_h"] for b in matching_ex_vivo if b.get("time_h") is not None]
                support = {"datasets": sorted({b["dataset_id"] for b in matching_ex_vivo}), "fu_range": [min(efu), max(efu)],
                           "bound_pct_range": [100 * (1 - max(efu)), 100 * (1 - min(efu))], "times_h": [min(ets), max(ets)] if ets else None,
                           "n_values": len(efu), "ratio_to_in_vitro": [min(efu) / max(fus), max(efu) / min(fus)],
                           "within_band": bool(min(efu) / max(fus) >= BAND[0] and max(efu) / min(fus) <= BAND[1]),
                           "stable_over_time": bool(max(efu) / min(efu) <= BAND[1]),
                           "analyte": "; ".join(sorted({b.get("analyte") or "analyte not reported" for b in matching_ex_vivo})),
                           "role": "contextual comparison only; no parent fu transfer validation"}
            out["conditional_fu"] = {"dataset_id": key[2], "study": key[0], "method": key[1], "same_study": not other,
                                     "fu_range": [min(fus), max(fus)], "fold": max(fus) / min(fus), "assay_range_mg_l": [min(cs), max(cs)],
                                     "pk_range_mg_l": [min(all_pk), max(all_pk)], "points_inside": inside, "points_total": len(all_pk),
                                     "label": "CONDITIONAL_CROSS_STUDY" if other else "CONDITIONAL_CONCENTRATION_RANGE",
                                     "conditions": ["apply only inside the measured binding concentration range; do not extrapolate to uncovered samples",
                                                    "fu range describes measured variation, not a confidence interval"]
                                     + (["binding in this study's animals and conditions equals that of the binding study (same species and matrix)"] if other else [])
                                     + (["binding method not reported"] if key[1].lower() in ("not reported", "not_found", "unknown") else [])
                                     + ([f"{len(all_pk) - inside} of {len(all_pk)} total concentrations lie outside the assayed range"] if inside < len(all_pk) else []),
                                     "scope": "covered sampled parent concentrations only; sensitivity range, not unbound exposure or volume",
                                     "ex_vivo_support": support}
    return out


def _own_ex_vivo(b):
    """Only this board's post-dose binding samples; retain native concentration units."""
    return [x for x in b["binding"].get("ex_vivo_binding") or [] if x["study"] == b["study"]]


def _ex_vivo_only(b):
    return bool(_own_ex_vivo(b)) and not (b["iv_refs"] or b["ev_refs"] or b["tissues"])


def _ex_vivo_summary(rows):
    """Reader statement about observed binding; it makes no parent or unbound-exposure transfer."""
    times = [x["time_h"] for x in rows if x.get("time_h") is not None]
    matrices = ", ".join(sorted({x["matrix"] for x in rows}))
    methods = ", ".join(sorted({x["method"] for x in rows}))
    analytes = ", ".join(sorted({x.get("analyte") or "analyte not reported" for x in rows}))
    ranges = []
    for unit in dict.fromkeys(x.get("conc_unit") or "unit not reported" for x in rows):
        cs = [x["conc"] for x in rows if (x.get("conc_unit") or "unit not reported") == unit and x.get("conc") is not None]
        if cs:
            ranges.append(f"{_f(min(cs))}–{_f(max(cs))} {unit}")
    return (f"post-dose {matrices} binding measured by {methods}: {_f(min(x['bound_pct'] for x in rows))}–{_f(max(x['bound_pct'] for x in rows))} % bound"
            + (f" over {_f(min(times))}–{_f(max(times))} h" if times else " (sampling times not reported)")
            + f" ({len(rows)} reported binding values; {analytes}"
            + (f"; native concentrations {', '.join(ranges)}" if ranges else "")
            + "); this is post-dose binding context, not parent-specific fu or unbound parent exposure")


# ---------------------------------------------------------------- reported parameters (rules D0.12)

_VOL = [("Vss", r"\bv\s*ss\b|steady[- ]state volume"), ("Vz", r"\bv\s*z\b|v\s*β|vbeta|v\s*beta|\bvarea\b"),
        ("Vc/F", r"\bvc\s*/\s*f\b|v1\s*/\s*f"), ("V/F", r"\bv\s*/\s*f\b|vd\s*/\s*f"), ("Vc", r"\bvc\b|\bv1\b|central volume"),
        ("Vp", r"\bvp\b|\bv2\b|peripheral volume"), ("Vd (definition not stated)", r"\bvd\b|volume of distribution|\bvol\b|\bv\b(?!\s*/)"),
        ("Q", r"\bq\b|intercompartmental"), ("K12", r"\bk12\b"), ("K21", r"\bk21\b"), ("Kp", r"\bkp\b|partition coefficient")]


def _param_name(text):
    t = str(text or "").lower()
    apparent = re.search(r"\b(vss|vz|v1|vc|vd|v)\s*/\s*f\b", t)
    if apparent:
        return {"vss": "Vss/F", "vz": "Vz/F", "v1": "Vc/F", "vc": "Vc/F", "vd": "V/F", "v": "V/F"}[apparent.group(1)]
    for name, pat in _VOL:
        if re.search(pat, t):
            return name
    return None


def _to_l_per_kg(v, unit):
    u = str(unit or "").lower().replace(" ", "")
    if "ml/kg" in u:
        return v / 1000, "L/kg"
    if "l/kg" in u:
        return v, "L/kg"
    return None, unit


def load_parameter_context(root):
    path = Path(root) / "reported_parameter_context.json"
    return json.loads(path.read_text(encoding="utf-8-sig")) if path.is_file() else {}


def reviewed_parameters(entry, context):
    """Resolve a reviewed cell's ordered measurements against the bound source table."""
    spec = context.get(entry["dataset_id"])
    if not spec:
        return []
    if spec["source_item_id"] != entry.get("source_item_id") or spec["study"] not in entry.get("study_source_ids", []):
        raise ValueError(f"Reviewed parameter context does not match {entry['dataset_id']}")
    records = {r["record_id"]: r for r in entry["records"]}
    out = []
    column = spec["value_column"]
    for ref, definition in spec["records"].items():
        record = records[ref]
        cells = record.get("source_raw_values") or record
        label = cells[spec["label_column"]]
        if record.get("source_sha256") != spec["source_sha256"] or label != definition["label"]:
            raise ValueError(f"Reviewed parameter source changed for {ref}")
        status = (record.get("value_status") or {}).get(column)
        if status not in (None, "QUANTIFIED", "SOURCE_TEXT_REQUIRES_REVIEW"):
            continue
        raw = str(cells[column])
        parts = [s.strip() for s in raw.split(";")]
        if len(parts) != len(definition["matrices"]):
            raise ValueError(f"Matrix and measurement counts differ for {ref}")
        for i, (part, matrix) in enumerate(zip(parts, definition["matrices"])):
            m = re.fullmatch(rf"({COMMON.NUMBER})\s*(?:±|\+/-)\s*({COMMON.NUMBER})(?![\d.eE])(?:\s+(.+))?", part)
            if not m or m[3] and m[3] != definition["unit"]:
                raise ValueError(f"Reviewed value or unit changed for {ref}")
            route = definition["route"]
            if route not in ("IV", "SC"):
                raise ValueError(f"Unrecognized reviewed route for {ref}")
            out.append({"dataset_id": entry["dataset_id"], "study": spec["study"], "species": species_in(entry["metadata"]["species"]),
                        "label": label, "record_id": ref, "source_col": column, "cell_raw": raw, "raw": part, "component_index": i,
                        "source_cell": f"{entry['dataset_id']}:{ref}:{column}", "review_source": spec["source"],
                        "param": definition["param"], "route_detail": route, "route": "IV" if route == "IV" else "EV",
                        "matrix": matrix, "unit": definition["unit"], "value": float(m[1]), "sd": float(m[2]),
                        "dispersion_type": spec["dispersion_type"], "n": spec["n"], "phase_meaning": definition.get("phase_meaning")})
    return out


def tissue_parameter_table(rows):
    head = ["Study", "Species", "Route", "Matrix", "Parameter", "As reported", "Unit", "Source cell"]
    cells = [[r["study"], r["species"], r["route_detail"], r["matrix"], r["label"].split(" (")[0],
              f"{r['value']:g} ± {r['sd']:g} ({r['dispersion_type']}, n = {r['n']})", r["unit"], r["source_cell"]] for r in rows]
    return ('<div class="tw"><table class="res"><tr>' + "".join(f"<th>{_e(x)}</th>" for x in head) + "</tr>"
            + "".join("<tr>" + "".join(f"<td>{_e(v)}</td>" for v in row) + "</tr>" for row in cells) + "</table></div>")


def write_tissue_parameter_supplement(folder, rows):
    """Emit the same portable distribution evidence from a full build or a frozen upstream run."""
    page = folder / "reported-tissue-half-lives.html"
    data = page.with_suffix(".json")
    if not rows:
        for path in (page, data):
            path.unlink(missing_ok=True)
        return
    folder.mkdir(exist_ok=True)
    refs = list(dict.fromkeys(r["review_source"] for r in rows))
    sources = " · ".join(f'<a href="{_e(url)}">Original study</a>' for url in refs)
    page.write_text(_shell("Reported tissue-fluid half-lives",
        '<section class="panel"><h1>Distribution · Reported tissue-fluid half-lives</h1>'
        + tissue_parameter_table(rows) + f'<p>{sources} · <a href="{data.name}">Source-linked records (JSON)</a></p></section>'),
        encoding="utf-8")
    data.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")



def reported_volumes(entry):
    cols = entry.get("columns", [])
    meta = entry.get("metadata", {})
    label_col = next((c for c in cols if c.get("meaning") in ("OTHER",) and re.search(r"param|quantity|measure", str(c.get("header", "")).lower())), None)
    grp_col = next((c for c in cols if c.get("meaning") == "GROUP_OR_TREATMENT"), None)
    vcols = [c for c in cols if c.get("meaning") == "PARAMETER_VALUE"]
    out, group = [], None
    for r in entry.get("records", []):
        g = r.get(grp_col["id"]) if grp_col else None
        if g not in (None, ""):
            group = str(g)
        for c in vcols:
            head = str(c.get("header", ""))
            if re.search(r"\b(median|sd|s\.d\.|min|max|minimum|maximum|range|cv|%cv|se|sem|iqr|percentile|ci)\b", head.lower()):
                continue
            lab = str(r.get(label_col["id"])) if label_col else head
            name = _param_name(head) if not label_col else _param_name(lab)
            if not name:
                continue
            raw = r.get(c["id"], (r.get("source_raw_values") or {}).get(c["id"]))
            v, sd, n, st = parse_value(raw)
            unit = c.get("unit") if c.get("unit") not in (None, "NOT_FOUND") else (re.search(r"\(([^)]*)\)", lab).group(1) if re.search(r"\(([^)]*)\)", lab) else None)
            if v is None and isinstance(raw, str):
                # 2026-11-24 review: whole numbers only (an exponent's digits are never read as a value); mean ± dispersion first
                pm = COMMON.mean_dispersion(raw)
                um = re.match(r"(l/kg|ml/kg|l\b|ml\b)", pm[2].lower()) if pm else None
                m = None if um else re.search(rf"(?<![\w.+\-])({COMMON.NUMBER})(?![\d.])\s*(?:(?:\+/-|±)\s*({COMMON.NUMBER})(?![\d.]))?\s*(l/kg|ml/kg|l\b|ml\b)", raw.lower())
                if um:
                    v, sd, unit = pm[0], pm[1], um.group(1)
                elif m:
                    v, sd, unit = float(m.group(1)), (float(m.group(2)) if m.group(2) else None), m.group(3)
            if v is None:
                continue
            lkg, u2 = _to_l_per_kg(v, unit)
            sp = species_in(group) or species_in(head) or species_group(meta.get("species", ""))
            out.append({"dataset_id": entry["dataset_id"], "study": ",".join(entry.get("study_source_ids", [])), "species": sp, "parameter": name,
                        "label": lab if label_col else head, "drug": meta.get("drug"), "condition": meta.get("condition"),
                        "method": meta.get("estimation_method") or meta.get("method") or "not reported", "value": v, "unit": unit, "value_l_per_kg": lkg, "sd": sd,
                        "group": group, "route": meta.get("route_class"), "route_detail": meta.get("route_detail"),
                        "column": head, "record_id": r.get("record_id"), "label_flag": "REPORTED_PARAMETER"})
    return out


# ---------------------------------------------------------------- item 28: conditions (T5) and the species table

def t5_pair(a, b):
    """T5: one positive scale factor carries dose-normalized profile a onto b at matched times (interval intersection)."""
    rows = []
    end_a, end_b = a.get("infusion_h") or 0, b.get("infusion_h") or 0
    for p in _q(a["points"]):
        if p["t"] <= end_a:
            continue
        m = next((x for x in _q(b["points"]) if x["t"] > end_b and _match(p["t"] - end_a, x["t"] - end_b)), None)
        if m and a["dose"] and b["dose"] and a["uf"] and b["uf"]:
            n_family = len(a["points"]) + len(b["points"])
            la, ha, ua = log_interval(p, a["level"], family_size=n_family)
            lb, hb, ub = log_interval(m, b["level"], family_size=n_family)
            off = math.log(COMMON.dose_given(a) / a["uf"]) - math.log(COMMON.dose_given(b) / b["uf"])
            rows.append({"t": p["t"] - end_a, "supported": ua == ub == "SAMPLING_ERROR", "lo": la - hb - off, "hi": ha - lb - off})
    if len(rows) < 3:
        return {"t5_label": "CANNOT_ASSESS", "reason": "fewer than 3 matched times", "rows": rows}

    def margin(keep):
        rs = [rows[i] for i in keep]
        return max(r["lo"] for r in rs) - min(r["hi"] for r in rs)
    m = margin(range(len(rows)))
    supported = all(row["supported"] for row in rows) and len(rows) >= 4
    comparable = (a.get("condition") and b.get("condition") and a["condition"] != b["condition"]
                  and a["iv_mode"] in ("BOLUS", "INFUSION") and a["dose_basis"] not in (None, "NOT_FOUND")
                  and all(a.get(k) == b.get(k) for k in ("study","drug","species","dose_basis","dose","route_detail","iv_mode","matrix_class","level","design","analyte"))
                  and COMMON.input_nominal(a) == COMMON.input_nominal(b)
                  and not (_baseline(a)[0] or _baseline(b)[0]))
    lab, flags = "NOT_EXCLUDED", [] if supported and comparable else ["SENSITIVITY_ONLY"]
    if m > 0:
        robust = all(margin([i for i in range(len(rows)) if i != d]) > 0 for d in range(len(rows)))
        lab = "EXCLUDED_UNDER_STATED_ASSUMPTIONS" if robust else "NOT_EXCLUDED"
        if not robust:
            flags.append("SINGLE_POINT_SUPPORT")
    c_lo, c_hi = max(r["lo"] for r in rows), min(r["hi"] for r in rows)
    return {"t5_label": lab if supported and comparable else "CANNOT_ASSESS", "t5_sensitivity_label": lab, "t5_flags": flags, "t5_margin": m, "rows": rows,
            "c_interval": [math.exp(c_lo), math.exp(c_hi)] if c_lo <= c_hi else None,
            "affected_window": [rows[0]["t"], rows[-1]["t"]]}


_ATTRS = ("study", "species_text", "route_detail", "iv_mode", "dose_basis", "matrix_class", "level", "design", "analyte", "condition")


def conditions(refs):
    out = []
    iv = [s for s in refs if s["route_class"] == "IV" and len(_q(s["points"])) >= 3 and not s.get("animal")]
    for a, b in itertools.combinations(iv, 2):
        if a["species"] != b["species"] or a["matrix_class"] != b["matrix_class"] or a["dataset_id"] == b["dataset_id"] and a["dose"] != b["dose"]:
            continue
        if a["dataset_id"] == b["dataset_id"]:
            continue
        diff = [k for k in _ATTRS if a.get(k) != b.get(k)]
        if not diff:
            continue
        res = t5_pair(a, b)
        cav = []
        if not (a.get("condition") and b.get("condition") and a["condition"] != b["condition"]):
            cav.append("CONDITION_NOT_IDENTIFIED")
        if "study" in diff:
            cav.append("DIFFERENT_STUDIES")
        if len([d for d in diff if d != "species_text"]) > 1 or ("study" in diff and "species_text" in diff):
            cav.append("CONFOUNDED")
        if "dose_basis" in diff:
            cav.append("DOSE_BASIS_MISMATCH")
        out.append(res | {"a": a["sid"], "b": b["sid"], "a_label": f"{a['study']} {a['label']}", "b_label": f"{b['study']} {b['label']}",
                          "species": a["species"], "differing_attributes": diff, "caveats": cav,
                          "reading": "description only (different studies)" if "DIFFERENT_STUDIES" in cav else "descriptive comparison" if cav else "within-study comparison"})
    return out


# ---------------------------------------------------------------- guide figures 1a-5 (renderer-neutral specs, drawn by R or matplotlib)
# Labels follow the r1.5b guide: 1a linear, 1b semilog (T6/T7 decisive samples), 1c adjacent-interval decline rates, 2a/2b dose or
# condition contrasts, 3a-3c tissue, 4a/4b binding, 5 reported parameters; Table 2 support and Table 3 Vc bound; organ recovery optional.

Panel = ab.Panel
TIME_AXIS = ab.TIME_AXIS


def _band(p, series):
    """Plot rule P1: shade the IV input of the profiles drawn in the panel (start of dosing to its end)."""
    return ab.input_band(p, [x.get("infusion_h") for x in series if x.get("route_class", "IV") == "IV" and x.get("iv_mode") == "INFUSION"])
CAT = [BLUE, ORANGE, GREEN, PURPLE, "#E69F00", "#56B4E9", "#9a7d0a", "#4b6273"]  # categorical, fixed order (Okabe-Ito based)
_SPECS = []
_RENDER = {"engine": None, "note": ""}


def _figure(name, panels, width, height, ncol=None, title=""):
    ncol = min(ncol or len(panels), len(panels))
    _SPECS.append({"file": name, "title": title, "width": width, "height": height, "dpi": ab.RENDER_DPI, "ncol": ncol,
                   "widths": [1] * ncol, "panels": [p.d for p in panels]})
    return name


def _one(name, panel, w=5.8, h=3.8):
    return _figure(name, [panel], w, h)


def _r_script():
    import os
    if os.environ.get("DISTRIBUTION_R_SCRIPT"):
        return Path(os.environ["DISTRIBUTION_R_SCRIPT"])
    here = Path(__file__).resolve()
    for base in here.parents:
        cand = base / "pkpd_r" / "eda" / "distribution_figures.R"
        if cand.is_file():
            return cand
    return here.parent / "distribution_figures.R"


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
            done = subprocess.run([rs, "--vanilla", str(script), str(path), str(out)], capture_output=True, text=True,
                                  encoding="utf-8", timeout=600)
            (out / "r_stderr.txt").write_text(done.stderr or "", encoding="utf-8")
            if done.returncode == 0 and all((out / s["file"]).is_file() for s in specs):
                _RENDER.update(engine="R_GGPLOT2", note=done.stdout.strip()); return
            reason = f"R renderer failed (exit {done.returncode}); see distribution/r_stderr.txt"
        except Exception as exc:  # noqa: BLE001 - reported on the page
            reason = f"R renderer could not run: {exc!r}"
    else:
        reason = "Rscript not found (set PKPD_RSCRIPT)" if not rs else f"R script missing: {script}"
    with _plain_log_minor_labels():
        for s in specs:
            s2 = json.loads(json.dumps(s))
            for p in s2["panels"]:
                for L in p["layers"]:
                    if L["kind"] == "path":  # matplotlib draws lines in the given order already
                        L["kind"] = "line"
            ab._render_mpl(s2, out)
    _RENDER.update(engine="MATPLOTLIB_FALLBACK", note=reason)


class _plain_log_minor_labels:
    """Fallback only: log-axis minor labels as plain numbers at 2 and 5 (matplotlib's default prints 2×10^0 on short ranges)."""
    def __enter__(self):
        from matplotlib.axes import Axes
        from matplotlib.ticker import FuncFormatter
        self.A, self.ox, self.oy = Axes, Axes.set_xscale, Axes.set_yscale

        def lab(v, _):
            if v <= 0:
                return ""
            m = v / 10 ** math.floor(math.log10(v) + 1e-9)
            return f"{v:g}" if round(m, 6) in (2.0, 5.0) else ""

        def wrap(orig, axis):
            def f(ax, *a, **k):
                r = orig(ax, *a, **k)
                if (a[0] if a else k.get("value")) == "log" and k.get("base", 10) == 10:
                    getattr(ax, axis).set_minor_formatter(FuncFormatter(lab))
                return r
            return f
        Axes.set_xscale, Axes.set_yscale = wrap(self.ox, "xaxis"), wrap(self.oy, "yaxis")
        return self

    def __exit__(self, *exc):
        self.A.set_xscale, self.A.set_yscale = self.ox, self.oy
        return False


def _lvl_txt(s):
    lv = {"GROUP_MEAN": "group mean", "INDIVIDUAL": "individual", "INDIVIDUAL_IDENTITY_UNVERIFIED": "individual, identity not verified"}[s["level"]]
    return lv + (", destructive" if s["design"] == "DESTRUCTIVE" else "") + (", digitized" if s["digitized"] else "")


def _input_word(s):
    mode = s.get("iv_mode")
    if s.get("route_class") != "IV":
        return ""
    if mode == "IV_MODE_UNKNOWN":
        return "input mode not reported"
    if mode == "ONGOING_INPUT":
        return "ongoing input"
    return COMMON.input_text("INFUSION_TIMING_UNKNOWN" if mode == "INFUSION_TIMING_UNKNOWN" else mode, s.get("infusion_h"))


def _dstd(s, scale=None, what="concentration", who=None, part=None, vs="time", group=None):
    """S13 rule 9: the standard title of a Distribution figure (which data, what is plotted)."""
    if group:
        s = group[0]
        doses = sorted({round(COMMON.dose_given(x) or x.get("dose") or 0, 6) for x in group} - {0})
        dose = (doses[0] if len(doses) == 1 else f"{doses[0]:.4g}–{doses[-1]:.4g} mg/kg") if doses else None
        who = who or f"{len(group)} animal{'s' if len(group) != 1 else ''}"
        hs = sorted({x.get("infusion_h") for x in group if x.get("infusion_h")})
        inp = (f"{hs[0] * 60:.2g}–{hs[-1] * 60:.2g}-min infusion" if len(hs) > 1 and hs[-1] < 1 else _input_word(s))
    else:
        dose = COMMON.dose_given(s) or s.get("dose")
        who = s.get("label") if who is None else who
        inp = _input_word(s)
    route = "IV" if s.get("route_class") == "IV" else (s.get("route_detail") or s.get("route_class"))
    return COMMON.std_title(s.get("species"), route, who, dose, inp, what, scale, s.get("matrix_label") or s.get("matrix_text"), vs, part)


D_SUB = {   # S13 rule 9: the subtitle is the question the figure answers
    "FULL": "What is the whole concentration–time course?",
    "SEMI": "Does one exponential describe the decline?",
    "EARLY": "How fast does concentration fall right after the input?",
    "IND": "How do the individual animals compare?",
    "RATE": "Does the decline rate change over time?",
    "DOSE": "Does concentration rise in proportion to dose?",
    "ANIMAL": "Do the occasions of one animal agree once divided by dose?",
    "VC": "How large can the initial (central) volume be at most?",
    "TISSUE": "How does the tissue concentration compare with the reference matrix?",
    "BIND": "What fraction is unbound in plasma?",
    "VSS": "How do the reported volumes compare?",
    "EVIV": "How do the IV and EV profiles compare?",
}


def _blq(p, s, x_shift=0.0, color=GRAY):
    b = [x for x in s["points"] if x["status"] == "BLQ" and x.get("lim")]
    if b:
        p.points([x["t"] - x_shift for x in b], [x["lim"] for x in b], color=color, shape="open", size=2.4, label="BLQ (at LLOQ)")


def pDIS1a(s, r):
    """DIS-1a/1b on the time after the start of dosing (plot rules P1-P6). The shape reading works on the time after the end of
    the input (item 24); its samples are drawn at their own times, the IV input is a shaded band, and every observation is
    drawn: samples during the input and a sample at its end, which the shape reading does not use, are open grey circles."""
    end = s.get("infusion_h") or 0.0
    q = [dict(p, t=p["t"] - end) for p in _q(s["points"]) if p["t"] > end or (s["iv_mode"] == "INFUSION" and p["t"] == end)]
    unit = s["unit"]
    sp = r.get("split") or {}
    a = Panel(_dstd(s, "semi-log"), TIME_AXIS, f"Concentration ({unit})", ylog=True)
    a.set(subtitle=D_SUB["SEMI"])
    _band(a, [s])
    ser = s["design"] != "DESTRUCTIVE" and s["level"] != "INDIVIDUAL_IDENTITY_UNVERIFIED"
    positive = _q(s["points"])
    if ser:
        a.line([p["t"] for p in positive], [p["c"] for p in positive], color=MUTED, lw=0.5)
    # S13 (George 2026-11-25): every observation drawn alike; no early/late colouring (a count split for the screen, not PK
    # phases) and no used/unused marking (the input band shows which samples fall inside the input). The reading is in the corner.
    a.points([p["t"] for p in positive], [p["c"] for p in positive], color=BLUE)
    _blq(a, s)
    for value in sorted(set(r.get("baseline_range") or [])):
        if value > 0:
            a.hline(value, color=PURPLE, lty="dashed", label="observed predose concentration")
    a.set(legend="bottom_left", caption=shape_caption(s, r))
    k = max(3, math.ceil(len(q) / 2))
    cut = q[min(k, len(q)) - 1]["t"] if q else 1
    b = Panel(_dstd(s, "linear", part=f"0–{_f(cut + end)} h"), TIME_AXIS, f"Concentration ({unit})")
    b.set(subtitle=D_SUB["EARLY"])
    _band(b, [s])
    early_all = [p for p in positive if p["t"] - end <= cut * 1.05]
    if ser:
        b.line([p["t"] for p in early_all], [p["c"] for p in early_all], color=MUTED, lw=0.5)
    b.points([p["t"] for p in early_all], [p["c"] for p in early_all], color=BLUE)
    first_after = next((p for p in q if p["t"] > 0), None)
    if first_after:
        gap = first_after["t"]
        gap_txt = f"{_f(gap * 60)} min" if gap < 1 else f"{_f(gap)} h"
        b.set(caption=(f"First sample after the infusion: {_f(gap + end)} h (end of infusion + {gap_txt})."
                       if s["iv_mode"] == "INFUSION" and end > 0 else f"First sample: {_f(gap + end)} h."))
    b.set(xlim=[min([0.0] + [p["t"] for p in early_all]) - 0.03 * (cut + end), (cut + end) * 1.08], legend="bottom_left")
    full = Panel(_dstd(s, "linear"), TIME_AXIS, f"Concentration ({unit})")
    full.set(subtitle=D_SUB["FULL"])
    _band(full, [s])
    measured = sorted((p for p in s["points"] if p["status"] in ("QUANTIFIED", COMMON.PREDOSE_ZERO) and p["c"] is not None), key=lambda x: x["t"])
    full.points([p["t"] for p in measured], [p["c"] for p in measured], color=BLUE, label="quantified")
    if ser:
        full.line([p["t"] for p in measured], [p["c"] for p in measured], color=MUTED, lw=0.5)
    _blq(full, s)
    spread = [p for p in measured if s["level"] == "GROUP_MEAN" and (p.get("sd") or 0) > 0]
    for panel in (full, a):
        valid = [p for p in spread if panel is full or p["c"] > p["sd"]]
        if valid:
            t = [p["t"] for p in valid]
            panel.segments(t, [p["c"] - p["sd"] for p in valid], t, [p["c"] + p["sd"] for p in valid],
                           color=MUTED, lw=0.65, label="reported SD")
    if measured and min(p["c"] - (p.get("sd") or 0) for p in measured) >= 0:
        ymax = max([p["c"] + (p.get("sd") or 0) for p in measured] + [p["lim"] for p in s["points"] if p.get("lim")])
        if ymax > 0:
            full.set(ylim=[0, ymax * 1.1])
    if measured:
        # S13: marked on the data, not in a corner. The last quantified sample is ringed and labelled at its own time; a later
        # sample that is not quantified (BLQ or another assay status) is labelled at its own time too.
        last = measured[-1]
        full.points([last["t"]], [last["c"]], color=ORANGE, shape="ring", size=4.6, stroke=1.2)
        full.text(last["t"], last["c"], f"last quantified\n{_f(last['t'])} h", hjust=1, vjust=0, size=2.6, repel=True)
        after = [p for p in s["points"] if p.get("t") is not None and p["t"] > last["t"]]
        if after:
            fin = max(after, key=lambda p: p["t"])
            word = "BLQ" if fin["status"] == "BLQ" else COMMON.ASSAY_LABELS.get(fin["status"], fin["status"].lower().replace("_", " "))
            full.text(fin["t"], fin.get("lim") or 0, f"last sample\n{_f(fin['t'])} h ({word})", hjust=1, vjust=0, size=2.6, repel=True)
    if s["iv_mode"] in ("IV_MODE_UNKNOWN", "INFUSION_TIMING_UNKNOWN", "ONGOING_INPUT"):
        for panel in (a, full, b):
            panel.d["xlab"] = "Reported time during ongoing IV input (h)" if s["iv_mode"] == "ONGOING_INPUT" else "Reported time (h), input end unknown"
    times = [x["t"] for x in s["points"] if x["status"] == "QUANTIFIED" or x["status"] in COMMON.ASSAY_LABELS]
    if times and max(times) > min(times):
        start = min(0.0, min(times))
        for panel in (full, a):
            panel.set(xlim=[start - (max(times) - start) * .02, max(times) + (max(times) - start) * .04])
    notes = []
    for status, label in COMMON.ASSAY_LABELS.items():
        times = [p["t"] for p in s["points"] if p["status"] == status and not p.get("lim")]
        if times:
            notes.append(label.capitalize() + " at " + ", ".join(_f(t) for t in times) + " h")
    if notes:
        full.set(caption="; ".join(notes) + ".")
    return [full, a, b]


def shape_caption(s, r):
    """S13 rule 9: the shape reading of one IV profile in at most two plain sentences (the phase screen, then the
    single-exponential check; the speeding-up check only when it found something)."""
    end = s.get("infusion_h") or 0.0
    pd = r.get("post_distribution_from_h")
    cur = r.get("curvature")
    if cur == "FLATTENING":
        one = ("The decline is not a single exponential: it slows" + (f" from about {_f(pd + end)} h" if isinstance(pd, (int, float)) else "")
               + (f" (early rate {_f(r.get('slope_ratio'))} times the late rate; biphasic)." if r.get("slope_ratio") else " (biphasic)."))
    elif cur == "STEEPENING":
        one = "The decline becomes steeper over time."
    elif cur == "NONE_DETECTED":
        one = "No second phase is seen; one exponential describes the decline."
    else:
        one = "The number of phases cannot be judged from these samples."
    more = []
    if any(r.get(k) is not None for k in ("t6_label", "t6_sensitivity_label", "t7_label", "t7_sensitivity_label")):
        t7 = plain_check(r, "t7", _t7_where(r, end))
        if t7.startswith("Decline rate speeds up"):
            more.append(t7 + ".")
        t6 = plain_check(r, "t6")
        if cur != "FLATTENING" or not t6.startswith("A single exponential does not fit"):
            more.append(t6 + ".")
    return " ".join([one] + more[:1])


def _t7_where(r, end):
    tp = r.get("t7_points")
    if tp and r.get("t7_margin") is not None and r["t7_margin"] > 0:
        return f" between {_f(tp[0] + end)} and {_f(tp[-1] + end)} h"
    return ""


def pDIS1ind(ss, rs=None):
    """Display the actual individual observations on both scales, with no pooling. With item 24 results the profiles are coloured
    by their reading, so the two panels show how many animals carry each shape."""
    end_known = all(s["iv_mode"] not in ("IV_MODE_UNKNOWN", "INFUSION_TIMING_UNKNOWN", "ONGOING_INPUT") for s in ss)
    xlabel = TIME_AXIS if end_known else "Reported time (h), input end unknown"
    by = {r["sid"]: r for r in (rs or [])}
    groups = (("TWO_OR_MORE", BLUE, "early decline, then slower"), ("TWO_OR_MORE_TENTATIVE", ORANGE, "slowing that rests on one point"),
              ("ONE_APPARENT", GRAY, "one apparent decline"), ("NOT_LOG_CONVEX_DESCRIPTIVE", PURPLE, "steepening decline"))
    read = {s["sid"]: (by.get(s["sid"]) or {}).get("phases_visible") for s in ss}
    # S13 rule 9: no colouring by a screening reading; the reading is one caption sentence
    use_groups = False
    counts = Counter(read.values())
    cap = "; ".join(f"{n} of {len(ss)} animals: {w}" for code, _, w in groups for n in [counts.get(code, 0)] if n)
    panels = []
    for log in (False, True):
        p = Panel(_dstd(None, "semi-log" if log else "linear", group=ss), xlabel, f"Concentration ({ss[0]['unit']})", ylog=log)
        p.set(subtitle=D_SUB["IND"])
        if log and cap:
            p.set(caption=cap[:1].upper() + cap[1:] + ".")
        _band(p, ss)
        seen = set()
        for i, s in enumerate(ss):
            pts = sorted((x for x in s["points"] if x["status"] in ("QUANTIFIED", COMMON.PREDOSE_ZERO) and x["c"] is not None
                          and (not log or x["c"] > 0)), key=lambda x: x["t"])
            times, conc = [x["t"] for x in pts], [x["c"] for x in pts]
            color, label = CAT[i % len(CAT)], None
            if use_groups:
                code, color, words = next(g for g in groups if g[0] == read[s["sid"]])
                if log and code not in seen:
                    label = f"{words} ({sum(v == code for v in read.values())})"
                    seen.add(code)
            if s["level"] == "INDIVIDUAL" and s["design"] != "DESTRUCTIVE" and len(pts) > 1:
                p.line(times, conc, color=color, lw=0.55)
            if pts:
                p.points(times, conc, color=color, size=1.8, label=label)
            _blq(p, s, 0.0, color)
        if use_groups and log:
            p.set(legend="bottom_left")
        panels.append(p)
    return panels


def _late_share_text(share):
    if not share:
        return "—"
    return f"{_f(share['percent'])} % of {_f(share['window_h'][0])}–{_f(share['window_h'][1])} h"


def late_area_share(q, phases_visible, cut):
    """Item 24 step 7 (r1.3): observed AUC(cut, b) / AUC(a, b) in percent on the same quantified points (D0.6).

    Reported only for TWO_OR_MORE or TWO_OR_MORE_TENTATIVE with a determined cut; with one apparent phase the cut is the
    first sample and the share is 100 % by construction. A value row in Table 2: no plot, no threshold."""
    if phases_visible not in ("TWO_OR_MORE", "TWO_OR_MORE_TENTATIVE") or not isinstance(cut, (int, float)):
        return None
    ts, cs = [p["t"] for p in q], [p["c"] for p in q]
    whole = COMMON.auc(ts, cs)
    tail = [(t, c) for t, c in zip(ts, cs) if t >= cut]
    if whole <= 0 or len(tail) < 2:
        return None
    late = COMMON.auc([t for t, _ in tail], [c for _, c in tail])
    return {"percent": 100.0 * late / whole, "window_h": [ts[0], ts[-1]], "cut_h": cut, "n_points": len(ts),
            "method": "observed quantified points only; linear-up/log-down (D0.6); no extrapolation"}


def pDIS1rate(s, r):
    """Guide figure 1c (r1.5b): decline rate between adjacent quantified samples, one horizontal segment per eligible interval.
    Eligible: positive quantified samples at distinct times, adjacent in the same profile (no missing or below-limit sample
    between them), after IV input ends. Rate = [ln C(t1) - ln C(t2)] / (t2 - t1) in 1/h; zero marked."""
    end = s.get("infusion_h") or 0.0
    pts = sorted((p for p in s["points"] if p.get("t") is not None and p["t"] >= end), key=lambda p: p["t"])
    xs, ys, xe = [], [], []
    for a, b in zip(pts, pts[1:]):
        if (a["status"] == b["status"] == "QUANTIFIED" and (a.get("c") or 0) > 0 and (b.get("c") or 0) > 0 and b["t"] > a["t"]):
            xs.append(a["t"]); xe.append(b["t"])
            ys.append((math.log(a["c"]) - math.log(b["c"])) / (b["t"] - a["t"]))
    p = Panel(_dstd(s, what="decline rate between successive samples"), TIME_AXIS, "Decline rate (1/h)")
    p.set(subtitle=D_SUB["RATE"], caption="Decline rate = fall in ln(concentration) per hour between two successive quantified samples.")
    if s.get("iv_mode") in ("IV_MODE_UNKNOWN", "INFUSION_TIMING_UNKNOWN", "ONGOING_INPUT"):   # S13 rule 1: one axis name per figure
        p.d["xlab"] = "Reported time during ongoing IV input (h)" if s["iv_mode"] == "ONGOING_INPUT" else "Reported time (h), input end unknown"
    _band(p, [s])
    p.hline(0, color=MUTED, lty="dashed", label="no decline")
    if xs:
        p.segments(xs, ys, xe, ys, color=BLUE, lw=1.6, label="rate over each sampling interval")
        p.set(legend="top_right")
    else:
        why = ("ongoing or unknown IV input" if s.get("iv_mode") in ("IV_MODE_UNKNOWN", "INFUSION_TIMING_UNKNOWN", "ONGOING_INPUT")
               else "fewer than two adjacent positive quantified samples after input")
        p.text(0.5, 0.5, "No eligible interval: " + why, hjust=0.5, vjust=0.5, size=2.8, npc=True)
    return p


def plain_check(r, k, where=""):
    """S13 rule 8 (George 2026-11-25): the single-exponential (T6) and speeding-up (T7) checks in PK words for figure text."""
    w = check_words(r, k)
    tol = f"±{100 * TOL:g} %"
    if k == "t6":
        head = {"rests on one point": "Single-exponential misfit rests on one point", "not run": "Single-exponential check not run"}
        if w.startswith("contradicted"):
            return "A single exponential does not fit (" + (f"beyond {tol} and beyond assay noise" if "noise" in w else
                                                             f"beyond {tol} only, not beyond assay noise" if w.endswith("only") else f"beyond {tol}") + ")"
        return head.get(w, f"A single exponential is not ruled out ({tol})")
    if w.startswith("contradicted"):
        return f"Decline rate speeds up{where} (" + (f"beyond {tol} and beyond assay noise" if "noise" in w else
                                                     f"beyond {tol} only, not beyond assay noise" if w.endswith("only") else f"beyond {tol}") + ")"
    return {"rests on one point": "Speeding-up of the decline rests on one point", "not run": "Speeding-up check not run"}.get(
        w, f"No point where the decline speeds up ({tol})")


def pDIS2(res, members):
    members = sorted(members, key=lambda s: s["dose"])
    a = Panel(_dstd(None, "semi-log", what="concentration divided by dose", group=members, who=f"{len(members)} doses"), TIME_AXIS,
              "Concentration / dose (mg/L per mg/kg)", ylog=True)
    a.set(subtitle=D_SUB["DOSE"])
    _band(a, members)
    ramp = RAMP[1:] if len(members) <= len(RAMP) - 1 else RAMP
    for i, s in enumerate(members):
        q = _q(s["points"])                       # P4: every observation, the input band shows which fall inside it
        col = ramp[min(i * max(1, (len(ramp) - 1) // max(1, len(members) - 1)), len(ramp) - 1)]
        if s["design"] != "DESTRUCTIVE":
            a.line([p["t"] for p in q], [p["c"] * s["uf"] / COMMON.dose_given(s) for p in q], color=col, lw=0.6)
        a.points([p["t"] for p in q], [p["c"] * s["uf"] / COMMON.dose_given(s) for p in q], color=col, label=f"{s['dose']:g} mg/kg")
    a.set(legend="bottom_left")
    b = Panel(_dstd(None, what=f"ratio of concentration/dose, {res['pair'][1]:g} over {res['pair'][0]:g} mg/kg", group=members,
                    who=f"{len(members)} doses"), TIME_AXIS, f"Ratio of C/dose ({res['pair'][1]:g} / {res['pair'][0]:g} mg/kg)", ylog=True)
    b.set(subtitle=D_SUB["DOSE"])
    _band(b, members)
    shift = members[0].get("infusion_h") or 0.0          # rows are matched on the time after the end of the (common) input
    rows = [dict(r, t=r["t"] + shift) for r in res["rows"]]
    b.hline(1.0, color=MUTED)
    b.hline(res["band"][0], color=MUTED, lty="dashed")
    b.hline(res["band"][1], color=MUTED, lty="dashed", label=f"band {res['band'][0]:.2f}–{res['band'][1]:.2f}")
    ci = [r for r in rows if r.get("ci")]
    if ci:
        b.segments([r["t"] for r in ci], [r["ci"][0] for r in ci], [r["t"] for r in ci], [r["ci"][1] for r in ci], color=MUTED, lw=1.2)
    b.points([r["t"] for r in rows], [r["ratio"] for r in rows], color=BLUE)
    b.set(caption=say(res["dose_pattern"]).rstrip(".") + "." + (" Per-time test: " + say(res["t3p"]["label"]).rstrip(".") + "." if res.get("t3p") else ""))
    b.set(legend="bottom_left")
    native = Panel(_dstd(None, "semi-log", group=members, who=f"{len(members)} doses"), TIME_AXIS, "Concentration (mg/L)", ylog=True)
    native.set(subtitle=D_SUB["DOSE"])
    _band(native, members)
    for i, s in enumerate(members):
        pts = _q(s["points"])
        native.points([x["t"] for x in pts], [x["c"] * s["uf"] for x in pts], color=CAT[i % len(CAT)], label=f"{s['dose']:g} mg/kg")
    return [native, a, b]


VC_TABLE_HEAD = ("Species", "Study", "Animal / profile", "Dose (mg/kg)", "Sample time (h after start of dosing)",
                 "C at that time (mg/L)", "Vc ≤ D/C (L/kg)")


def vc_bound_table(rows, boards):
    """Table 3 (item 25): one row per profile with a point bound, then one median/range row per study (board)."""
    by_key = {b["key"]: b for b in boards}
    out = []
    for key in dict.fromkeys(x["board"] for x in rows):
        b = by_key[key]
        grp = [x for x in rows if x["board"] == key]
        for x in grp:
            out.append({"board": key, "kind": "profile", "cells": [
                b["species"], b["study"], x["label"].split(" · ")[-1], _f(x.get("dose_used_mg_per_kg")),
                _f(x.get("sample_time_after_start_h")), _f(x.get("c_at_sample_mg_per_l")), _f(x["vc_upper_bound_l_per_kg"])]})
        if len(grp) > 1:
            v = sorted(x["vc_upper_bound_l_per_kg"] for x in grp)
            t = sorted(x["sample_time_after_start_h"] for x in grp if x.get("sample_time_after_start_h") is not None)
            rng = lambda a: (f"{_f(statistics.median(a))} ({_f(a[0])}–{_f(a[-1])})" if a else "—")
            out.append({"board": key, "kind": "summary", "cells": [
                b["species"], b["study"], f"median (range), n = {len(grp)}", rng(sorted(x.get("dose_used_mg_per_kg") for x in grp if x.get("dose_used_mg_per_kg") is not None)),
                rng(t), rng(sorted(x["c_at_sample_mg_per_l"] for x in grp if x.get("c_at_sample_mg_per_l") is not None)), rng(v)]})
    return out


def vc_table_html(table, board=None):
    rows = [r for r in table if board is None or r["board"] == board]
    if not rows:
        return ""
    return ('<div class="tw"><table class="res evt"><tr>' + "".join(f"<th>{_e(h)}</th>" for h in VC_TABLE_HEAD) + "</tr>" + "".join(
        "<tr" + (' class="sum"' if r["kind"] == "summary" else "") + ">" + "".join(
            f"<td>{'<b>' if r['kind'] == 'summary' else ''}{_e(c)}{'</b>' if r['kind'] == 'summary' else ''}</td>" for c in r["cells"]) + "</tr>"
        for r in rows) + "</table></div>")


def pDIS3(rows, title="Upper bound on the central volume (Vc) from the first sample after the input, by profile", summary=None):
    """Upper bounds on Vc. Each bound is a cap with an arrow pointing down: values below the cap are allowed, values above are not.
    (The arrow is drawn by the R renderer; the fallback draws a plain stem.)"""
    p = Panel(title, "", "Volume (L/kg)", ylog=True)
    p.set(subtitle=D_SUB["VC"])
    xs = list(range(1, len(rows) + 1))
    ok = [(x, r) for x, r in zip(xs, rows) if r.get("vc_upper_bound_l_per_kg")]
    per_animal = bool(summary and summary.get("kind") == "PER_ANIMAL")
    stem = 1.6
    med = summary["median"] if per_animal else None
    if per_animal:
        p.hline(med, color=ORANGE, lty="dashed", label=f"median bound {_f(med)} L/kg")
    common = None
    if len(ok) >= 3:
        # a sample time shared by most bounds is stated once, not on every label
        groups = []
        for _, r in ok:
            g = next((g for g in groups if _match(g[0], r["sample_time_h"])), None)
            (g.append(r["sample_time_h"]) if g else groups.append([r["sample_time_h"]]))
        big = max(groups, key=len)
        if 2 * len(big) > len(ok):
            common = big[0]
    if ok:
        for x, r in ok:
            v = r["vc_upper_bound_l_per_kg"]
            p.add("path", x=[float(x), float(x)], y=[float(v), float(v / stem)], color=BLUE, lty="solid", lw=0.9, label=None, alpha=1.0)
        p.points([x for x, _ in ok], [r["vc_upper_bound_l_per_kg"] for _, r in ok], color=BLUE, shape="dash", size=4, label="upper bound on Vc (allowed values lie below)")
        for x, r in ok:
            v = r["vc_upper_bound_l_per_kg"]
            same = common is not None and _match(common, r["sample_time_h"])
            ylab = med * 1.06 if (med and v * 1.02 <= med <= v * 1.32) else v * 1.07   # a label the median line would cross sits just above the line
            p.text(x, ylab, _f(v) + ("" if same else f" @ {_f(r['sample_time_h'])} h"), hjust=0.5, vjust=0, size=2.6)
    if common is not None:
        p.text(0.98, 0.98, f"D/C(t) at {_f(common)} h unless labelled", hjust=1, vjust=1, size=2.8, npc=True)
    rep = [(x, v) for x, r in zip(xs, rows) for v in r.get("reported", []) if v.get("value_l_per_kg")]
    if rep:
        p.points([x + 0.15 for x, _ in rep], [v["value_l_per_kg"] for _, v in rep], color=ORANGE, shape="diamond_open", size=3.0, label="source-reported volume")
    refs = {}
    for r in rows:
        for k, v in (r.get("reference_volumes") or {}).items():
            refs.setdefault(k, v)
    for k, v in refs.items():
        p.hline(v, color=GREEN if k.startswith("plasma") else MUTED, lty="dashed", label=f"{k.replace('_', ' ')} {v:g} L/kg (sourced)")
    ys = [r["vc_upper_bound_l_per_kg"] for _, r in ok] + [r["vc_upper_bound_l_per_kg"] / stem for _, r in ok] + [v["value_l_per_kg"] for _, v in rep] + list(refs.values())
    if ys:
        lo, hi = min(ys), max(ys)
        span = max(hi / lo, 10)
        p.set(ylim=[lo / span ** 0.45, hi * span ** 0.22])  # at least a decade; room under the arrows for the legend and above for labels
    # labels that share a leading part (species and study on the project figure) show only what differs
    labs = [str(r["label"]) for r in rows]
    parts = [x.split(" · ") for x in labs]
    while len(labs) > 1 and all(len(x) > 1 for x in parts) and len({x[0] for x in parts}) == 1:
        parts = [x[1:] for x in parts]
    shown = [" · ".join(x) for x in parts]
    p.set(xbreaks=xs, xlabels=[_wrap_lab(x) for x in shown], xlim=[0.5, len(rows) + 0.5], legend="bottom_left")
    if shown != labs:
        p.text(0.02, 0.98, labs[0][:len(labs[0]) - len(shown[0])].rstrip(" ·"), hjust=0, vjust=1, size=2.8, npc=True)
    return p


def _wrap_lab(x, n=16):
    x = str(x)
    if len(x) > n and " · " in x:
        return "\n".join(_wrap_lab(part, min(n, 13)) for part in x.split(" · ")[:3])
    if len(x) <= n:
        return x
    import textwrap
    return "\n".join(textwrap.wrap(x, width=n, break_long_words=True)[:3])


def _disp_matrix(s):
    d = re.sub(r"\s*\((?:[µuμmn]g|%|dpm)[^)]*\)\s*$", "", str(s.get("matrix_label") or "").strip())
    return d if d and d.upper() not in ("NOT_FOUND", "MIXED") else (s.get("organ") or "tissue")


def pDIS4a(ref, tissues, title):
    p = Panel(title, TIME_AXIS, "Concentration (native units)", ylog=True)
    p.set(subtitle=D_SUB["TISSUE"])
    allser = ([ref] if ref else []) + tissues
    _band(p, allser)
    for i, s in enumerate(allser):
        q = _q(s["points"])
        col = INK if s is ref else CAT[i - (1 if ref else 0)]  # callers pass at most len(CAT) - 1 tissues
        if s["design"] != "DESTRUCTIVE" and s["level"] != "INDIVIDUAL_IDENTITY_UNVERIFIED" and len(q) > 1:
            p.line([x["t"] for x in q], [x["c"] for x in q], color=col, lw=0.6 if s is not ref else 0.9)
        sd = [x for x in q if x.get("se") is not None or x.get("sd") is not None]
        if sd:
            err = lambda x: x["se"] if x.get("se") is not None else x["sd"]
            p.segments([x["t"] for x in sd], [max(x["c"] - err(x), x["c"] * 0.05) for x in sd], [x["t"] for x in sd], [x["c"] + err(x) for x in sd], color=col, lw=0.6, label="SE" if any(x.get("se") is not None for x in sd) else "SD")
        p.points([x["t"] for x in q], [x["c"] for x in q], color=col, shape="square" if s is ref else "circle", size=2.4,
                 label=f"{_disp_matrix(s)} ({s['unit']})"[:34])
        b = [x for x in s["points"] if x["status"] in COMMON.ASSAY_LABELS]
        if b and q:
            p.text(b[-1]["t"], min(x["c"] for x in q), COMMON.ASSAY_LABELS[b[-1]["status"]], hjust=0.5, vjust=1, size=2.5, color=col)
    tmax = max((x["t"] for s in allser for x in s["points"] if x["t"] is not None), default=1)
    if any(s.get("iv_mode") == "ONGOING_INPUT" for s in allser):
        p.d["xlab"] = "Reported time during ongoing IV input (h)"
    p.set(legend="top_right", xlim=[-0.03 * tmax, tmax * 1.5])  # right third kept free for the legend
    return p


def pDIS4b(res, t, r):
    rows = [x for x in res["rows"] if x["ratio"]]
    p = Panel(_dstd(t, "semi-log", what=f"{res['tissue']}/{res['ref_label']} concentration ratio", who=""), TIME_AXIS,
              f"Ratio ({res['ratio_unit']})", ylog=True)
    p.set(subtitle=D_SUB["TISSUE"])
    if t["design"] != "DESTRUCTIVE" and len(rows) > 1:
        p.line([x["t"] for x in rows], [x["ratio"] for x in rows], color=MUTED, lw=0.5)
    p.points([x["t"] for x in rows], [x["ratio"] for x in rows], color=BLUE, size=2.2)
    ch = res.get("dis4b")
    if ch:
        last3 = rows[-3:]
        p.points([x["t"] for x in last3], [x["ratio"] for x in last3], color=BLUE, size=3.4, label="last three common times")
        r3 = rows[-3]["ratio"]
        p.hline(r3 * ch["band_used"][0], color=MUTED, lty="dashed")
        p.hline(r3 * ch["band_used"][1], color=MUTED, lty="dashed", label="band around the third-last ratio")
        txt = (f"{say(res['ratio_reading'])}\nfold {_f(ch['fold'])}, d = {_f(ch['d'])}" + (f", SE {_f(ch['se_d'])}\ndf {_f(ch['df'])}, z = {_f(ch['z'])}, z_crit {_f(ch['z_crit'])}" if ch.get("se_d") else "\nexact per-time SD/n unresolved: description"))
    else:
        txt = res.get("not_assessable_reason", "")
    if "SENSITIVITY_ONLY" in res.get("ratio_reading_flags", []):
        txt += "\nCovariance between times unknown: description only"
    if t["analyte"] == "ACTIVE_MATERIAL":
        txt += "\nAntimicrobial activity, not parent-specific"
    if t.get("iv_mode") == "ONGOING_INPUT":
        p.d["xlab"] = "Reported time during ongoing IV input (h)"
    und = [x for x in res["rows"] if x.get("ratio_status") == "UNDEFINED"]
    if und and ch:
        txt += f"\nundefined (reference BLQ) at {', '.join(_f(x['t']) for x in und)} h"
    p.text(0.02, 0.02, _wrap(txt, 46), hjust=0, vjust=0, size=2.7, npc=True)
    ys = [x["ratio"] for x in rows] + ([rows[-3]["ratio"] * ch["band_used"][0], rows[-3]["ratio"] * ch["band_used"][1]] if ch else [])
    if ys:
        lo, hi = min(ys), max(ys)
        span = max(hi / lo, 10)  # at least one decade, so log ticks stay readable
        p.set(ylim=[lo / span ** 0.6, hi * span ** 0.25])  # room under the points for the result text
    p.set(legend="top_right")
    return p


def _wrap(t, n):
    out = []
    for line in str(t).split("\n"):
        out.extend(COMMON._wrap(line, n) if len(line) > n else [line])
    return "\n".join(out)


def pDIS4d(d3):
    p = Panel("Parent drug recovered in each organ, as % of dose (lower bound), by sampling time", "Time after start of dosing (h)",
              "% of dose (lower bound)")
    p.set(subtitle="Where is the recovered drug at each time?")
    tissues = sorted({q["tissue"] for row in d3["rows"] for q in row["parts"]})
    for row in d3["rows"]:
        bottom = 0
        for part in row["parts"]:
            top = bottom + part["pct_dose"]
            p.segments([row["t"]], [bottom], [row["t"]], [top], color=CAT[tissues.index(part["tissue"]) % len(CAT)],
                       lw=4, label=part["tissue"])
            bottom = top
    p.hline(100, color=ORANGE, lty="dashed", label="administered dose")
    p.set(legend="top_right")
    return p


def pDIS4e(res, t, r):
    rows = [x for x in res["rows"] if x["ratio"]]
    p = Panel(_dstd(t, what=f"{res['tissue']} vs {res['ref_label']} concentration, in time order", who="", vs=None),
              f"Reference ({r['unit']})", f"Tissue ({t['unit']})", ylog=True)
    p.set(subtitle="Does the tissue lag behind the reference (a loop)?")
    p.set(xlog=True)
    p.add("path", x=COMMON._l([x["ref"] for x in rows]), y=COMMON._l([x["tissue"] for x in rows]), color=MUTED, lty="solid", lw=0.6, label=None, alpha=1.0)
    p.points([x["ref"] for x in rows], [x["tissue"] for x in rows], color=BLUE, size=2.4)
    for i, x in enumerate(rows):
        p.text(x["ref"], x["tissue"], f" {_f(x['t'])} h", hjust=0, vjust=0, size=2.5)
    p.text(0.02, 0.98, f"{res.get('phase_loop', '—').lower().replace('_', ' ')} (time-ordered observations)", hjust=0, vjust=1, size=2.8, npc=True)
    return p


def pDIS5a(rows, recs, pk_range):
    p = Panel("Fraction unbound vs total concentration tested, by assay matrix and method", "Total concentration tested (mg/L)",
              "Fraction unbound", ylog=False)
    p.set(subtitle="Does the unbound fraction depend on concentration?")
    p.set(xlog=True)
    if pk_range:
        p.band(pk_range[0], pk_range[1], color=GREEN, alpha=0.10)
    for i, d in enumerate(rows):
        bs = sorted([b for b in recs if b["dataset_id"] == d["dataset_id"] and b["study"] == d["study"] and b["method"] == d["method"] and b["conc"] and unit_factor(b["conc_unit"])], key=lambda b: b["conc"] * unit_factor(b["conc_unit"]))
        col = CAT[i % len(CAT)]
        p.line([b["conc"] * unit_factor(b["conc_unit"]) for b in bs], [b["fu"] for b in bs], color=col, lw=0.6)
        p.points([b["conc"] * unit_factor(b["conc_unit"]) for b in bs], [b["fu"] for b in bs], color=col, label=f"{d['study']} · {d['matrix'].lower()} · {d['method']}"[:65])
    pts = [(math.log10(b["conc"] * unit_factor(b["conc_unit"])), b["fu"]) for b in recs if b.get("conc") and unit_factor(b.get("conc_unit")) and b.get("fu") is not None
           and any(b["dataset_id"] == d["dataset_id"] and b["study"] == d["study"] and b["method"] == d["method"] for d in rows)]
    lx = [x for x, _ in pts] + [math.log10(v) for v in (pk_range or []) if v and v > 0]
    corner, note = "top_right", "top_left"
    if pts and lx:
        x0, y0 = min(lx), min(y for _, y in pts)
        nx, ny = [x - x0 for x in lx[:len(pts)]] + [max(lx) - x0], [y - y0 for _, y in pts] + [0.0]
        corner = ab._free_corner(nx, ny)
        note = ab._free_corner(nx, ny, order=tuple(k for k in ("top_left", "bottom_left", "bottom_right", "top_right") if k != corner))
    p.text(0.98 if note.endswith("right") else 0.02, 0.98 if note.startswith("top") else 0.02, "shaded: observed PK range" if pk_range else "",
           hjust=1 if note.endswith("right") else 0, vjust=1 if note.startswith("top") else 0, size=2.8, npc=True)
    p.set(legend=corner)
    return p


def pDIS6a(c, a, b):
    p = Panel(_dstd(None, "semi-log", what="concentration divided by dose", group=[a, b], who="two conditions"), TIME_AXIS,
              "Concentration / dose (mg/L per mg/kg)", ylog=True)
    p.set(subtitle="Do the two conditions give the same profile once divided by dose?")
    _band(p, [a, b])
    for s, col in ((a, BLUE), (b, ORANGE)):
        q = _q(s["points"])
        if s["design"] != "DESTRUCTIVE":
            p.line([x["t"] for x in q], [x["c"] * s["uf"] / COMMON.dose_given(s) for x in q], color=col, lw=0.6)
        p.points([x["t"] for x in q], [x["c"] * s["uf"] / COMMON.dose_given(s) for x in q], color=col, label=f"{s['study']} · {s['species_text']}"[:44])
    p.text(0.98, 0.98, f"same shape after scaling (T5): {say(c['t5_label'])}\ndiffering: {', '.join(say(x) for x in c['differing_attributes'])}"[:140], hjust=1, vjust=1, size=2.7, npc=True)
    p.set(legend="bottom_left")
    return p


# ---------------------------------------------------------------- reading map (rules D0.11) and question specs

READING_MAP = [
    ("DIS-1a, DIS-1b", "Does the semilog decline flatten, stay straight or steepen; time of the first sample; last point against LLOQ",
     "FLATTENING / NONE_DETECTED / STEEPENING",
     "Two or more phases (multi-compartment candidate); one phase after the first sample (earlier sampling decides); nonlinear elimination or recycling candidate (only after T7)"),
    ("DIS-1c, Table 2", "Interval decline rates; R, z and whether the reading survives dropping the first, last or low-confidence points",
     "ROBUST, point-dependent or repeat not assessable; candidate terminal window; the late-area share of the window",
     "Where item 18's IV terminal window may start; whether a compartment rests on one point; how the window area divides between the parts before and after the cut"),
    ("DIS-1b (T6/T7)", "Decisive triple: middle point above every admissible line (T6) or above the chord (T7)",
     "EXCLUDED_UNDER_STATED_ASSUMPTIONS / NOT_EXCLUDED / CANNOT_ASSESS", "One compartment excluded; linear mammillary disposition with completed input excluded"),
    ("DIS-2a, DIS-2b", "Do dose-normalized curves superimpose; how the higher/lower ratio moves with time",
     "RATIO_WITHIN_BAND / RATIO_RISES_LATE_ABOVE_BAND / RATIO_BELOW_BAND / RATIO_CONSTANT_OUTSIDE_BAND / RATIO_ABOVE_BAND_EARLY_THEN_FALLS / RATIO_MIXED",
     "Observable shapes only (R7 item 4); a mechanism needs a registered check, and a confounded contrast shows the ratios and the reason only"),
    ("Table 3", "Arrow D/C(t) against plasma, extracellular and total-water lines", "Vc ≤ X; VOLUME_BELOW_PLASMA; LOOSE_BOUND",
     "Upper limit for the initial Vc; initial confinement hint; dose, unit or timing error"),
    ("DIS-3a", "Tissue peak later than plasma; late declines parallel", "Sampled peak, persistence", "Slow equilibration; tissue moving with plasma"),
    ("DIS-3b", "Ratio flat, rising or falling over the last three common times", "NO_DIFFERENCE_SEEN / VARIABLE_WITHIN_WINDOW / RISING / TISSUE_NOT_FALLING / FALLING",
     "Window-specific tissue persistence, uptake or loss; an equilibrium Kp needs independent evidence of equilibration"),
    ("DIS-3c", "Tissue accumulation ratio against plasma at the same post-dose time", "TISSUE_ACCUMULATES_MORE / NO_DIFFERENCE_SEEN / less; T9",
     "Slow tissue; time dependence in plasma (absorption item 23) or tissue"),
    ("Optional organ contributions", "Lower-bound tissue amounts against the dose", "PASS / DATA_ISSUE / SENSITIVITY_ONLY", "Dilution, value basis, units or dose basis error"),
    ("DIS-3a inset", "Loop direction when tissue is plotted against plasma in time order", "Open trajectory / clockwise / counter-clockwise / overlapping branches", "Delayed tissue equilibration (description)"),
    ("DIS-4a", "fu,p across total concentration, by method", "STABLE / CHANGING / NOT_ASSESSABLE", "Constant-fraction unbound conversion; nonlinear binding"),
    ("DIS-4b", "Unbound ratio against [0.5, 2]", "INSIDE / ABOVE / BELOW / UNRESOLVED",
     "Passive equilibrium; uptake (or pH partitioning, lysosomal trapping); efflux or tissue elimination"),
    ("DIS-2a (conditions)", "Can one scale factor carry one condition onto the other (T5)", "NOT_EXCLUDED / EXCLUDED", "Shape change with the condition: covariate candidate"),
    ("Table 3, DIS-5", "Vc bounds, comparable Vss and source-matched Vss/fu,p across species", "Contrast shrinks / remains", "Plasma binding explains the contrast; tissue binding or transport hypothesis"),
]

QD = {
    1: ("Systemic disposition", "Do the measured systemic concentrations support a parent-disposition test?",
        "which observations support a change in decline rate", "a unique compartment count or exchange rate"),
    2: ("Central volume", "How tightly can early IV observations bound the initial central volume?",
        "the observation, time and assumptions behind an upper bound on Vc", "a measured Vc or an estimate of Vss"),
    3: ("Shared IV and EV disposition", "Could shared disposition and a different input explain the route profiles?",
        "the IV decline and the comparable EV post-peak window", "separate input and exchange rates from EV data alone"),
    4: ("Evidence for the systemic shape", "Does the shape survive checks on sampling, baseline and influential points?",
        "the observations that carry the systemic interpretation", "a mechanism from curvature alone"),
    5: ("Tissue exposure", "Can concurrent blood concentrations predict exposure in the sampled tissue?",
        "the measured concentrations and departures from a fixed tissue-to-reference ratio", "a unique transport mechanism"),
    6: ("Unbound plasma exposure", "Can the model use measured unbound plasma or a supported conversion from total plasma?",
        "the basis, assay and concentrations supporting unbound exposure", "target-site exposure from total plasma alone"),
    7: ("Cross-species transfer", "Which distribution assumptions can be tested across species, and which parameters need species-specific evidence?",
        "comparable observations, volume definitions and sampling windows", "a validated cross-species prediction"),
}


READER_ORDER = (1, 4, 6, 2, 3, 5, 7)
READER_NUMBER = {qid: i for i, qid in enumerate(READER_ORDER, 1)}


def _qrow(qn, status, observed, basis="", reach="", missing=(), primary=None, views=(), evidence=()):
    # M5: display_number is the guide question number (None for a row the guide does not number); `q` stays the engine id;
    # legacy_q is the engine row and legacy_display_number the page number used before (READER_NUMBER)
    return {"q": qn, "label": QD[qn][0], "question": QD[qn][1], "status": status, "status_code": ST_CODE[status],
            "observed": observed, "basis": basis, "reach": reach, "text": " ".join(x for x in (observed, basis, reach) if x),
            "missing": [m for m in dict.fromkeys(missing) if m], "primary": primary, "views": list(views), "evidence": list(evidence),
            **COMMON.guide_fields("distribution", qn), "legacy_q": [qn], "legacy_display_number": READER_NUMBER[qn]}


def _ref(qn):
    """What the page prints for one engine row (M5): the guide number, or the row name when the guide gives none."""
    return COMMON.display_ref("distribution", qn)


def _qref(q):
    """Printed reference of a question row: its own display_ref (Elimination rows pass theirs), else the Distribution one."""
    return q.get("display_ref") or (f'Q{q["display_number"]}' if q.get("display_number") else _ref(q["q"]))


def _anchor(q):
    """Page anchor of a question row: the guide number, or the stable id for a row the guide does not number."""
    return q.get("display_number") or q.get("qid") or q["q"]


def _prim(file, panel, qn, label_line, level):
    if not file:
        return None
    return {"kind": "panel", "file": file, "panels": [panel],
            "lines": [f"{_ref(qn)} · {QD[qn][0]}", label_line, "Shows " + QD[qn][2], "Cannot show: " + QD[qn][3]], "level": level}


def _rowprim(qn, head, rows, label_line, level):
    return {"kind": "row", "head": list(head), "rows": [list(r) for r in rows],
            "lines": [f"{_ref(qn)} · {QD[qn][0]}", label_line, "Shows " + QD[qn][2], "Cannot show: " + QD[qn][3]], "level": level}


_view = COMMON.panel_view


def _lvl_page(ss):
    lv = sorted({_lvl_txt(s) for s in ss})
    return "; ".join(lv) if lv else "—"


# ---------------------------------------------------------------- question rows per study board

def systemic_iv_coverage(series):
    """Describe the source series before any analyte, occasion or phase-analysis gate."""
    records = []
    for s in series:
        if not isinstance(s, dict) or s.get("route_class") != "IV" or s.get("matrix_class") not in REF_CLASSES:
            continue
        records.append({"dataset_id": s["dataset_id"], "series_id": s["sid"], "matrix": s["matrix_class"].lower(),
                        "occasion": s.get("occasion"), "reported_times": len({p["t"] for p in s["points"]
                        if p.get("t") is not None and (p.get("status") in ("QUANTIFIED", "ZERO", COMMON.PREDOSE_ZERO) or p.get("status") in COMMON.ASSAY_LABELS)})})
    return records


def _dq_systemic_shape(b, iv24, ivr, level, qs):
    """Question 1: systemic IV decline shape and phase count. Part of board_questions (split 2026-11-26 without change)."""
    usable = [r for r in iv24 if r.get("curvature") not in (None, "NOT_ASSESSABLE")]
    iv_coverage = systemic_iv_coverage(b.get("source_series", []))
    b["systemic_iv_coverage"] = iv_coverage
    if not ivr and iv_coverage:
        counts = [r["reported_times"] for r in iv_coverage]
        n_times = str(min(counts)) if min(counts) == max(counts) else f"{min(counts)}–{max(counts)}"
        matrices = "/".join(sorted({r["matrix"].replace("_", " ") for r in iv_coverage}))
        ids = sorted({r["dataset_id"] for r in iv_coverage})
        finding = (f"The study includes IV {matrices} data in {len(ids)} dataset{'s' if len(ids) != 1 else ''}, "
                   f"with {n_times} reported time point{'s' if n_times != '1' else ''} per profile.")
        qs.append(_qrow(1, ST_NO, finding, "Source datasets: " + ", ".join(ids) + ".",
                        "The available profiles do not establish early and late IV decline phases.",
                        ["an eligible first-dose IV profile with sufficient quantified post-input samples"],
                        evidence=[{"rule": "Observed IV coverage before the phase-analysis gates.", "data": ids,
                                   "tables": [{"caption": "Systemic IV observations", "head": ["Dataset", "Profile", "Matrix", "Occasion", "Reported times"],
                                               "rows": [[r[k] for k in ("dataset_id","series_id","matrix","occasion","reported_times")] for r in iv_coverage]}]}]))
    elif not ivr and b["ev_refs"]:
        profiles = [(s, _q(s["points"])) for s in b["ev_refs"] if s["analyte"] == "PARENT" and not s["unbound"]]
        observed = []
        for s, pts in profiles:
            if len(pts) < 2:
                continue
            peak = max(pts, key=lambda p: p["c"])
            later = [p for p in pts if p["t"] > peak["t"]]
            if later:
                same = sum(x["label"] == s["label"] for x, _ in profiles) > 1 and s.get("dose")
                twice = sum((x["label"], x.get("dose")) == (s["label"], s.get("dose")) for x, _ in profiles) > 1
                name = s["label"] + (f" at {_f(s['dose'])} mg/kg" if same else "") + (f" {_route_name(s)}" if twice else "")
                observed.append(f"{name}: sampled peak at {_f(peak['t'])} h, {len(later)} quantified observations through {_f(later[-1]['t'])} h")
        qs.append(_qrow(1, ST_PART if observed else ST_NO, (". ".join(observed) + ".") if observed else "No quantified post-peak window.",
                        "EV input may continue after the observed peak. An IV fast phase cannot be assigned from this profile.", "", ["matched IV parent observations"],
                        views=[_view("EV parent", f, sid) for (kind, sid), f in b["figs"].items() if kind == "EV parent"]))
    elif not ivr:
        qs.append(_qrow(1, ST_NO, "No systemic IV concentration series was identified on this board.", "With EV data the post-peak decline is described in absorption item 18.",
                        "", ["an IV profile with ≥ 5 quantified points after the end of dosing"]))
    elif not usable:
        r0 = max(iv24, key=lambda r: r["n_points"])
        qs.append(_qrow(1, ST_NO, f"IV profile{'s' if len(iv24) > 1 else ''} present, but the decline could not be read: "
                        + ", ".join(sorted({str(r.get('not_assessable_reason')) for r in iv24})).lower().replace("_", " ") + ".",
                        f"{r0['n_points']} quantified point{'s' if r0['n_points'] != 1 else ''} on the reported time axis in {r0['label']}.", "",
                        (["parent-specific assay evidence"] if "ACTIVE_MATERIAL" in r0["caveats"] else ["a separate post-stop sampling window"] if "ONGOING_INPUT" in r0["caveats"] else ["≥ 5 quantified points after the end of dosing"]) + (["the IV mode and infusion end"] if "INFUSION_TIMING_UNKNOWN" in r0["caveats"] else []),
                        _prim(b["figs"].get(("DIS1a", r0["sid"])), "DIS-1a/1b", 1, r0["label"], level) if b["figs"].get(("DIS1a", r0["sid"])) else None))
    else:
        main = max(usable, key=lambda r: ({"TWO_OR_MORE": 4, "NOT_LOG_CONVEX_DESCRIPTIVE": 5, "TWO_OR_MORE_TENTATIVE": 3, "ONE_APPARENT": 2}.get(r["phases_visible"], 0), r["n_points"]))
        cnt = {}
        for r in usable:
            cnt[r["phases_visible"]] = cnt.get(r["phases_visible"], 0) + 1
        readings = {"TWO_OR_MORE": "early decline followed by a slower decline", "TWO_OR_MORE_TENTATIVE": "possible early-to-late slowing sensitive to sampling",
                    "ONE_APPARENT": "one apparent decline over the sampled window", "NOT_LOG_CONVEX_DESCRIPTIVE": "a steepening semilog decline"}
        obs = "; ".join(f"{readings.get(k, k)} in {v} of {len(usable)} profile{'s' if len(usable) > 1 else ''}" for k, v in cnt.items())
        t7 = [r for r in usable if r.get("t7_label") not in (None, "CANNOT_ASSESS")]
        ex6 = [r for r in usable if r.get("t6_label") == "EXCLUDED_UNDER_STATED_ASSUMPTIONS"]
        ex7 = [r for r in usable if r.get("t7_label") == "EXCLUDED_UNDER_STATED_ASSUMPTIONS"]
        timing = "on the reported time axis (input end unknown)" if "INFUSION_TIMING_UNKNOWN" in main["caveats"] else "after input ended"
        basis = (f"Main view {main['label']}: R = {_f(main.get('slope_ratio'))}, z = {_f(main.get('z'))}, the reading {say(main['curvature_support'])}; "
                 f"first sample {_f(main['earliest_sample_h'])} h {timing}.")
        if ex6:
            basis += f" T6 excluded one compartment in {len(ex6)} profile{'s' if len(ex6) > 1 else ''}."
        if ex7:
            basis += f" T7 excluded linear mammillary disposition with completed input in {len(ex7)}."
        if t7 and not ex7:
            basis += " T7 found no contradiction of log-convexity."
        gate = next((r["noise_gate"] for r in usable if r.get("noise_gate")), None)
        nu_ = len(usable)
        tol6, tol7 = [r for r in usable if r.get("t6_at_tolerance")], [r for r in usable if r.get("t7_at_tolerance")]
        if gate and (tol6 or tol7):
            # a numerical finding at project tolerances, graded by the noise setting; the formal labels stay "not assessable"
            n6, n7 = [r for r in tol6 if r.get("t6_at_noise")], [r for r in tol7 if r.get("t7_at_noise")]
            pct = f"±{_f(gate['half_width_pct'], 2)} %"
            bits = []
            if tol6:
                bits.append(f"one straight line is contradicted in {_count_of(len(tol6), nu_)} at the ±{TOL * 100:g} % reading tolerance and in {len(n6)} "
                            f"once every point is widened to the noise setting ({pct})")
            if tol7:
                bits.append(f"the decline steepens somewhere in {_count_of(len(tol7), nu_)} at ±{TOL * 100:g} % and in {len(n7)} at the noise setting"
                            + (f" ({_names_of(n7)})" if n7 and nu_ > 1 else ""))
            basis += " Numerical check, not a formal test (no sourced error range): " + "; ".join(bits) + "."
        grp = all(s["level"] == "GROUP_MEAN" for s in ivr)
        st = ST_PART if (grp and not t7) or "TWO_OR_MORE_TENTATIVE" in cnt or any(r.get("curvature_support") != "ROBUST" for r in usable) else ST_YES
        reach = ("Group means: an apparent flattening can come from averaging animals with different single-phase declines." if grp else
                 "Individual profiles.") + (" One apparent decline means one phase after the first sample, not one compartment." if cnt.get("ONE_APPARENT") else "")
        miss = []
        if cnt.get("ONE_APPARENT"):
            # a sample at the end of input exists but is left out of the shape reading: it is not missing (same wording as the hypothesis)
            at_end_q = any(abs(x) <= 1e-9 for x in main.get("input_samples_h") or [])
            miss.append(f"IV samples between the end of input and {_f(main['earliest_sample_h'])} h" if at_end_q
                        else f"samples earlier than {_f(main['earliest_sample_h'])} h")
        if cnt.get("TWO_OR_MORE") and not ex7:
            reach += " Compare one compartment with reversible peripheral exchange against the early and late observations."
        elif cnt.get("TWO_OR_MORE_TENTATIVE"):
            reach += " Retain one and two compartments as candidates. Earlier replicated IV measurements could distinguish them."
        elif cnt.get("ONE_APPARENT"):
            reach += " Start with one compartment over the observed window and check coverage before sharing this structure."
        if grp:
            miss.append("individual profiles")
        if any("INFUSION_TIMING_UNKNOWN" in r["caveats"] for r in usable):
            miss.append("the IV mode and infusion end (T6, T7 not run)")
        views = [_view("Analytes", file, sid) for (kind, sid), file in b["figs"].items() if kind == "Analytes"]
        prim = None
        ev = [{"rule": ("Item 24 steps 2-7: split-half slopes of ln C (a bend is read at R ≥ 1.5 and z ≥ 2), repeats without the first and the last point, "
                        "and the checks T6 (one straight line) and T7 (the decline never steepens) of D0.10. Without a sourced error range T6 and T7 are numerical "
                        f"checks at the ±{TOL * 100:g} % reading tolerance, not formal tests; the table also says whether a contradiction remains with every point "
                        f"widened to ± {NOISE_GATE_SIGMAS:g} σ (A0.3)."),
               "tables": [{"caption": "Item 24 per profile", "head": ["Profile", "Points", "First (h)", "R", "z", "σ", "Reading", "Support", "Phases", "Single decline phase", "Progressive slowing", "Later part from (h)", "Window area after that time"],
                           "rows": [[r["label"], r["n_points"], _f(r["earliest_sample_h"]), _f(r.get("slope_ratio")), _f(r.get("z")), _f(r.get("sigma_used")),
                                     say(r.get("curvature")), say(r["curvature_support"]) if r.get("curvature_support") else "—", say(r.get("phases_visible")),
                                     check_words(r, "t6"), check_words(r, "t7"),
                                     _f(r["post_distribution_from_h"]) if isinstance(r.get("post_distribution_from_h"), (int, float)) else say(r.get("post_distribution_from_h")),
                                     _late_share_text(r.get("late_area_share"))]
                                    for r in iv24]}],
               "data": sorted({r["dataset_id"] for r in iv24})}]
        ev[0]["tables"].append({"caption": "Adjacent observed semilog slopes", "head": ["Profile", "From (h)", "To (h)", "Slope (1/h)"],
                                "rows": [[r["label"], _f(x["from_h"]), _f(x["to_h"]), _f(x["slope_per_h"])] for r in iv24 for x in r.get("chord_slopes", [])]})
        qs.append(_qrow(1, st, obs[0].upper() + obs[1:] + ".", basis, reach, miss, prim, views, ev))
    # A real profile is primary even when its sampling cannot resolve the phase count.
    q1 = qs[-1]
    preferred = (main if usable else r0) if ivr else None
    primary_key = None
    if preferred:
        for key in (("DIS1ind", preferred["dataset_id"]), ("DIS1a", preferred["sid"])):
            if key in b["figs"]:
                primary_key = key
                break
    curves = [(key, file) for key, file in b["figs"].items() if key[0] in ("DIS1ind", "DIS1a", "EV parent")]
    if primary_key is None and curves:
        primary_key = curves[0][0]
    if primary_key:
        file = b["figs"][primary_key]
        linked = str(file).startswith("../absorption/")
        q1["primary"] = _prim(file, "DIS-1a/1b", 1, f"{primary_key[1]} · " + ("semilog concentrations (absorption figure B1, not redrawn)" if linked
                                                                           else "linear and semilog concentrations"), level)
        q1["views"] = [v for v in q1["views"] if v["panel"] != "EV parent"]
        q1["views"].extend(_view("DIS-1a/1b", f, k[1]) for k, f in curves if k != primary_key)
        q1["views"].extend(_view("Linear profile (absorption A1w)", f, k[1]) for k, f in b["figs"].items() if k[0] == "EV linear")
        q1["views"].extend(_view("Early window", f, k[1]) for k, f in b["figs"].items() if k[0] == "Early")
    return iv_coverage, usable


def _dq_initial_volume(b, iv_coverage, ivr, level, qs):
    """Question 2: initial-volume (Vc) upper bound. Part of board_questions (split 2026-11-26 without change)."""
    bounds = b["item25"]
    okb = [x for x in bounds if x.get("vc_upper_bound_l_per_kg")]
    if not ivr and iv_coverage:
        qs.append(_qrow(2, ST_NO, "Systemic IV data are present. No eligible first-dose profile supports the initial-volume bound."))
    elif not ivr:
        if b["ev_refs"]:
            qs.append(_qrow(2, ST_NA, "EV data only: item 25 does not apply; EV data give V/F only, as a reported parameter."))
        else:
            qs.append(_qrow(2, ST_NA, "This study has no systemic concentration profile for an initial-volume bound."))
    elif not okb:
        qs.append(_qrow(2, ST_NO, "The initial-volume bound was not computed: " + "; ".join(sorted({x.get("not_assessable_reason", "") for x in bounds})) + ".",
                        "", "", _vc_missing(bounds)))
    else:
        m = min(okb, key=lambda x: x["vc_upper_bound_l_per_kg"])
        vs = b.get("vc_summary") or vc_summary(okb)
        cav = sorted({c for x in okb for c in x["caveats"]})
        st = ST_PART if ("LOOSE_BOUND" in cav or any(x["data_check"] == "VOLUME_BELOW_PLASMA" for x in okb)) else ST_YES
        chk = f"Plasma-volume check: {say(m['data_check'])}."
        if vs["kind"] == "PER_ANIMAL":
            # one bound per animal: each holds for its own animal, so the board reports the median and the range, not the smallest
            ends = _board_ends(b)
            endmap = {x["label"]: x.get("input_end_h") for x in b.get("item25", [])}
            at = _same_time_text(vs, ends)
            when = (f"all at {at}" if not vs["other_times"] else
                    f"{vs['same_time_n']} at {at}, " + ", ".join(f"{o['label']} at {clock_text(o['t'], [endmap.get(o['label'])])}" for o in vs["other_times"][:3]))
            obs = (f"Upper bounds on Vc, one per animal: median {_f(vs['median'])} L/kg, range {_f(vs['min'])}–{_f(vs['max'])} L/kg "
                   f"({vs['n']} animals, {when}).")
            basis = ("Each bound is D/C(t) at that animal's highest quantified sample at or after input end and holds for that animal only. Every animal lies below "
                     f"its own bound, so the median animal's Vc is at or below the median bound; the smallest bound ({_f(vs['min'])} L/kg, {vs['min_label']}) does not limit the others."
                     + (f" At {_same_time_text(vs, ends)} the bounds differ {_f(vs['same_time_fold'], 2)}-fold between animals given the same dose." if vs.get("same_time_fold") else "")
                     + " " + chk)
            plabel = f"{vs['n']} animals"
            use = " Use the median bound to check a typical fitted Vc and each animal's bound for its own estimate."
        else:
            obs = f"Vc ≤ {_f(m['vc_upper_bound_l_per_kg'])} L/kg at {clock_text(m['sample_time_h'], [m.get('input_end_h')])} ({m['label']})" + (
                f"; {len(okb)} bounds from {_f(min(x['vc_upper_bound_l_per_kg'] for x in okb))} to {_f(max(x['vc_upper_bound_l_per_kg'] for x in okb))} L/kg" if len(okb) > 1 else "") + "."
            basis = f"D/C(t) at the highest quantified sample at or after input end; the bound describes the {say(m['population_meaning'])}. " + chk
            plabel = m["label"]
            use = " Use this bound to check fitted Vc."
        reach = ("Keep in mind: " + "; ".join(say(c) for c in cav) + ".") if cav else ""
        # M6: the constraint for Modeling covers every candidate sample together and uses the supported upper dose
        mcs = [x["modeling_constraint"] for x in okb if x.get("modeling_constraint")]
        if mcs:
            formal = [x for x in mcs if x["status"] == "FORMAL"]
            reach += (f" As a fit constraint: {len(formal)} of {len(mcs)} bounds are formal (joint lower concentration limits over the candidate samples)"
                      + ("" if len(formal) == len(mcs) else "; the others are sensitivity results: " + "; ".join(sorted({r for x in mcs for r in x["reasons"]})))
                      + ".")
        miss = ([m.get("data_check_reason")] if m["data_check"] == "NOT_ASSESSABLE" else []) + (["an earlier first sample"] if "LOOSE_BOUND" in cav else [])
        ev = [{"rule": "Item 25 (M6): Vc ≤ D/C(t) at the highest quantified sample after input ends; the fit constraint is D_upper / L, with L the largest joint "
                       "lower concentration limit over all candidate samples (Bonferroni over the candidates, precision per R8); plasma-volume check when a sourced value exists.",
               "tables": [{"caption": "Item 25 per IV series", "head": ["Series", "t (h)", "Vc ≤ (L/kg)", "Fit constraint (L/kg)", "Constraint status", "Describes", "Plasma-volume check", "Keep in mind"],
                           "rows": [[x["label"], _f(x.get("sample_time_h")), _f(x.get("vc_upper_bound_l_per_kg")), _f(x.get("conservative_l_per_kg")),
                                     say((x.get("modeling_constraint") or {}).get("status")) if x.get("modeling_constraint") else "—",
                                     say(x["population_meaning"]) if x.get("population_meaning") else "—", say(x.get("data_check")), "; ".join(say(c) for c in x["caveats"]) or "—"] for x in bounds]}],
               "data": sorted({s["dataset_id"] for s in ivr})}]
        reach += use + " Q and peripheral volume require information on exchange over time."
        qs.append(_qrow(2, st, obs, basis, reach.strip(), miss, _prim(b["figs"].get(("DIS3", "board")), "Table 3", 2, plabel, level) if b["figs"].get(("DIS3", "board")) else None, (), ev))


def _dq_route_comparison(b, iv_coverage, ivr, level, qs):
    """Question 3: IV and EV route comparison of the early window. Part of board_questions (split 2026-11-26 without change)."""
    if b["ev_refs"] and ivr:
        pairs3 = b.get("route_pairs", [])
        possible = [p for p in pairs3 if p["masking_candidate"]]
        obs = ("A faster initial IV decline is visible over a window in which the matched EV post-peak profile appears single-phase. Ongoing input could mask the IV fast phase."
               if possible else "The available IV and EV observations do not resolve masking of a fast phase.")
        ranked = sorted(pairs3, key=lambda p: not p["masking_candidate"])
        primary = _prim(ranked[0]["file"], "IV/EV", 3, ranked[0]["iv"] + " / " + ranked[0]["ev"], level) if ranked else None
        views = [_view("IV/EV", p["file"], p["iv"] + " / " + p["ev"]) for p in ranked[1:]]
        basis3, ev3 = "", []
        made = b.get("absorption_route_pairs", [])
        if made and not pairs3:
            # absorption has already compared these routes: its figure and result are shown here, nothing is drawn again
            words = {"NOT_EXCLUDED": "is not contradicted", "EXCLUDED_UNDER_STATED_ASSUMPTIONS": "is contradicted"}
            parts = []
            for m in made:
                res = words.get(m["t4"], "could not be checked")
                parts.append(f"{m['ev']} against {m['iv']} ({_f(m['dose_ev'])} and {_f(m['dose_iv'])} mg/kg): {say_codes(m['summary'])}; shared one-compartment "
                             f"disposition with a different input {res}" + (" (numerical check)" if m["numerical_only"] and m["t4"] in words else ""))
            ivm = {s["dataset_id"]: s for s in ivr}
            why = (["the IV mode is not reported"] if any(ivm.get(m["iv"], {}).get("iv_mode") not in ("BOLUS", "INFUSION") for m in made) else [])
            other = [m["ev"] for m in made if m["dose_ev"] != m["dose_iv"]]
            if other:
                why.append(f"the dose of {_join_and(other)} differs from the IV dose")
            basis3 = ("Absorption has already compared these routes (its check T4): " + ". ".join(parts) + ". The absorption figure is shown here and not "
                      "drawn again. The comparison is not rated in this section because "
                      + (" and ".join(why) if why else "the pair does not meet its matching conditions (same dose, record level and matrix, a reported IV mode)") + ".")
            primary = _prim(made[0]["file"], "IV/EV", 3, f"{made[0]['iv']} / {made[0]['ev']} · absorption figure D1, not redrawn", level)
            views = [_view("IV/EV (absorption D1)", m["file"], m["iv"] + " / " + m["ev"]) for m in made[1:]]
            ev3 = [{"rule": "Absorption check T4: with shared one-compartment disposition the ratio C_EV / C_IV must not decrease.", "data": sorted({x for m in made for x in (m["ev"], m["iv"])}),
                    "tables": [{"caption": "Route comparisons made in absorption", "head": ["EV", "IV", "EV dose (mg/kg)", "IV dose (mg/kg)", "Shared disposition (T4)", "Absorption note"],
                                "rows": [[m["ev"], m["iv"], _f(m["dose_ev"]), _f(m["dose_iv"]), words.get(m["t4"], "could not be checked").replace("is ", ""), say_codes(m["summary"])] for m in made]}]}]
        qs.append(_qrow(3, ST_PART if pairs3 else ST_NO, obs, basis3, "", [] if possible else ["comparable route profiles resolving the same early window"], primary, views, ev3))
    elif b["ev_refs"] and iv_coverage:
        qs.append(_qrow(3, ST_NO, "Both IV and EV observations are present. No eligible IV profile supports a shared-disposition comparison.",
                        missing=["comparable IV and EV profiles resolving the same early window"]))
    elif b["ev_refs"]:
        siv = b.get("species_iv") or []
        qs.append(_qrow(3, ST_NO, "EV data only: the fast phase and Vc cannot be assessed from these profiles.", "The post-peak decline is described in absorption item 18."
                        + (f" {b['species']} has IV data in another study: {_species_iv_words(siv)}. A comparison across studies is not rated here, because animals, "
                           "condition and assay may differ." if siv else ""), "",
                        ["an IV profile in the same study"] if siv else ["an IV profile in the same species"]))
    else:
        qs.append(_qrow(3, ST_NA, "The study does not include an EV systemic profile for comparison with IV."))


def _dq_shape_support(b, qs, usable):
    """Question 4: support for the systemic shape under single-point deletion. Part of board_questions (split 2026-11-26 without change)."""
    rows = [[r["label"]] + [say(x["reading"]) for x in r.get("robustness_rows", [])] for r in usable]
    supported = sum(r.get("curvature_support") == "ROBUST" for r in usable)
    obs = (f"The observed shape survives the available deletion checks in {supported} of {len(usable)} profiles."
           if usable else "The available observations do not support a deletion check.")
    evidence = []
    views = []
    for q8 in b["q8_evidence"]:
        evidence.append({"rule": f"Absorption dose-proportionality assessment ({q8['version']}, {q8['key']}). {q8['interpretation']}"
                                 + (" Source limitations: " + ", ".join(q8["caveats"]) + "." if q8["caveats"] else ""),
                         "data": q8["datasets"], "tables": [{"caption": "Existing dose comparison", "head": ["Series", "Dose (mg/kg)", "Window (h)", "AUC/D ratio", "T3", "T3p"],
                         "rows": [[s, _f(d), q8["window"], _f(q8["auc_ratio"]), q8["t3"], q8["t3p"]] for s, d in zip(q8["series"], q8["doses"])]}]})
        if q8["figure"]:
            views.append(_view("Absorption dose comparison", q8["figure"], q8["route"] + " · " + q8["key"]))
    for d in b["dose_patterns"]:
        evidence.append({"rule": "Additional IV doses use the shared absorption pointwise comparison. Interpret the contrast in its sampled window.",
                         "data": list(dict.fromkeys(s.split(":")[0] for s in d["series"])),
                         "tables": [{"caption": "IV dose series", "head": ["Doses (mg/kg)", "Observed pattern", "Pointwise test", "Limitation"],
                                    "rows": [[", ".join(_f(x) for x in d["doses"]), d["dose_pattern"],
                                              d.get("t3p", {}).get("label", "CANNOT_ASSESS"), "subject or study confounding" if d["confounded"] else d.get("reason", "—")]]}]})
        if b["figs"].get(("DIS2", d["key"])):
            views.append(_view("DIS-2a/2b", b["figs"][("DIS2", d["key"])], "Additional IV dose series"))
    basis = ""
    if usable:
        # the checks of item 24 step 8: open ones in the text, the full list under evidence
        cd = usable[0]["checks_done"]
        open_ = [_open_words(k, v) for k, v in cd.items() if _check_open(v)]
        basis = (f"{len(cd)} checks were made before reading a bend as distribution (listed under “More for {_ref(4)}”); "
                 + ("open: " + "; ".join(open_) + "." if open_ else "none is open."))
        evidence.append({"rule": "Item 24 step 8: what is checked before a bend is read as distribution.",
                         "data": sorted({r["dataset_id"] for r in usable}),
                         "tables": [{"caption": "Checks before reading a bend as distribution", "head": ["Check", "Finding", "Open"],
                                     "rows": [[_cap(k), v, "yes" if _check_open(v) else "—"] for k, v in cd.items()]}]})
    # George 2026-11-25: no single-point removal table on the page; the reading is one plain sentence (rule 10), the per-profile
    # results stay in the JSON (item24[*].robustness_rows, curvature_support) and in depends_on_one_point below.
    prim = None
    views.extend(_view("DIS-1b (T6/T7)", f, k[1], 2) for k, f in b["figs"].items() if k[0] == "DIS1c")
    qs.append(_qrow(4, ST_YES if usable and supported == len(usable) else ST_PART if usable or evidence else ST_NO,
                    obs, basis, "", [], prim, views, evidence))
    qs[-1]["robust_profiles"] = [r["label"] for r in usable if r.get("curvature_support") == "ROBUST"]
    qs[-1]["depends_on_one_point"] = [r["label"] for r in usable if r.get("curvature_support") != "ROBUST"]


def _dq_tissues(b, qs):
    """Question 5: tissue observations and the proxy question. Part of board_questions (split 2026-11-26 without change)."""
    pairs = b["tissue_pairs"]
    bd = b["binding"]
    if b["tissues"]:
        tissues = b["tissues"]
        level_t = _lvl_page(tissues)
        tables = [{"caption": "Sampled tissue", "head": ["Series", "Unit", "Times (h)", "Flags"],
                   "rows": [[s["label"], s["unit"], ", ".join(_f(p["t"]) for p in s["points"]), ", ".join(s["flags"]) or "—"] for s in tissues]}]
        proxy, point_rows, checks = [], [], []
        for pair in pairs:
            rr = [x for x in pair["rows"] if x["ratio"] is not None and x["ratio"] > 0]
            for x in pair["rows"]:
                point_rows.append([pair["tissue"], pair["ref_label"], _f(x["t"]), _observed_cell(x, "tissue", pair["unit"]), _observed_cell(x, "ref", pair.get("ref_unit")),
                                   _f(x["ratio"]), pair.get("ratio_unit") or "—", x.get("ratio_status") or x["ref_status"]])
            # A two-point illustration is useful even when a formal time trend is unavailable.
            if len(rr) >= 2 and (pair["ratio_reading"] != "NOT_ASSESSABLE" or pair.get("na_group") in ("fewer than 3 common times", "incomplete scheduled window")):
                a, z = rr[0], rr[-1]
                expected = a["tissue"] * z["ref"] / a["ref"]
                checks.append({"tissue_sid": pair["tissue_sid"], "reference_sid": pair["_r"]["sid"], "unit": pair["_t"]["unit"],
                               "calibration_time_h": a["t"], "check_time_h": z["t"], "predicted": expected, "observed": z["tissue"],
                               "ratio_reading": pair["ratio_reading"], "basis": "descriptive fixed-ratio prediction"})
                proxy.append([pair["tissue"], pair["ref_label"], _f(a["t"]), _f(z["t"]), _f(expected, 4), _f(z["tissue"], 4),
                              pair["_t"]["unit"], pair["ratio_reading"]])
        if proxy:
            tables.append({"caption": "Later tissue concentration predicted from the first observed ratio", "head":
                           ["Tissue", "Reference", "First (h)", "Later (h)", "Fixed-ratio prediction", "Observed", "Unit", "Window reading"], "rows": proxy})
        if point_rows:
            tables.append({"caption": "Concurrent tissue and blood observations", "head": ["Tissue", "Reference", "Time (h)", "Tissue value / native error / n", "Reference value / native error / n", "Ratio", "Ratio unit", "Status"], "rows": point_rows})
        for d in b["repeat"]:
            if d.get("relative_rows"):
                tables.append({"caption": d["matrix"] + " · observed accumulation at matched occasions", "head": ["Time (h)", "Tissue AR", "Reference AR", "Ratio of ARs"],
                               "rows": [[_f(x[k]) for k in ("t","ar_tissue","ar_reference","relative_accumulation")] for x in d["relative_rows"]]})
        for site in bd["kpuu"]["sites"]:
            tables.append({"caption": site["site"] + " · " + site["estimator"] + " · " + site["position"],
                           "head": ["Time (h)", "Unbound site (mg/L)", "Unbound plasma (mg/L)", "Point ratio"],
                           "rows": [[_f(x[k]) for k in ("t","cu_site","cu_plasma","ratio")] for x in site["rows"]]})
        ds = sorted({s["dataset_id"] for s in tissues} | {p["_r"]["dataset_id"] for p in pairs if p.get("_r")}
                    | {site["ref_sid"].split(":")[0] for site in bd["kpuu"]["sites"]})
        ev = [{"rule": "Apply the first quantified tissue/reference ratio to the later reference in the same series. Report the observed and predicted values with native tissue units.", "data": ds, "tables": tables}]
        panels = [(k, f) for k, f in b["figs"].items() if k[0] in ("DIS4a","DIS4b","DIS4c","DIS4d","DIS4e","DIS5b")]
        prim = _prim(panels[0][1], panels[0][0][0], 5, "Sampled tissue and reference", level_t) if panels else None
        views = [_view(k[0], f, k[1], 3 if k[0] == "DIS4e" else 1) for k, f in panels[1:]]
        ranked = [pair for pair in pairs if pair.get("readable_window_h") and not any(c in pair["caveats"] for c in ("LOCAL_ROUTE", "MATRIX_UNKNOWN", "ELF_DILUTION_UNCORRECTED", "MICRODIALYSIS_UNCALIBRATED", "ENDOGENOUS_REVIEW_REQUIRED", "RECORD_PAIRING_UNVERIFIED"))]
        if ranked:
            main = ranked[0]
            values = [x["ratio"] for x in main["rows"] if x.get("ratio") is not None]
            times = main["readable_window_h"]
            obs = f"{main['tissue']}/{main['ref_label']}: observed concurrent ratios {_f(min(values))}–{_f(max(values))} {main['ratio_unit']} over {_f(times[0])}–{_f(times[1])} h."
            basis = ("Concurrent measurements from the same identified animal. " if main.get("ratio_estimator") == "INDIVIDUAL_PAIR"
                     else "Ratios of group means; covariance across matrices and times is unknown. ")
            basis += "The evidence table preserves the reported uncertainty. Equilibrium, Kp,uu and transport mechanisms require additional evidence."
            if main.get("analyte") == "ACTIVE_MATERIAL":
                basis += " The assay measures antimicrobial activity, with parent specificity unestablished."
            if "RESIDUAL_BLOOD_UNCORRECTED" in main["caveats"]:
                basis += " Tissue homogenates are uncorrected for residual blood."
            if main.get("unavailable_ratio_times_h"):
                basis += " Missing/censored ratios at " + ", ".join(_f(t) for t in main["unavailable_ratio_times_h"]) + " h do not extend the readable window."
            reach = "Use concurrent observations in their sampled window; fixed-ratio predictions remain descriptive."
            missing = ["sample covariance or individual pairs for inferential tissue/reference comparisons"]
            desired = b["figs"].get(("DIS4b", main["tissue_sid"]))
            if desired:
                prim = _prim(desired, "DIS-3b", 5, main["tissue"] + " / " + main["ref_label"], level_t)
        elif proxy:
            tissue, ref, t0, t1, pred, observed, unit, _ = proxy[0]
            obs = f"For {tissue}, carrying the {t0} h tissue/{ref} ratio forward predicts {pred} {unit} at {t1} h. The observed concentration was {observed} {unit}."
            basis = "This comparison uses sampled concentrations and retains the pairing and censoring limits of the source."
            reach = "Compare a fixed tissue-to-blood ratio with delayed tissue exchange against the later measurements."
            missing = ["additional concurrent tissue and blood samples to evaluate the time course"] if not any(p["ratio_reading"] != "NOT_ASSESSABLE" for p in pairs) else []
        else:
            names = ", ".join(sorted({_disp_matrix(s) for s in tissues}))
            obs = f"Observed tissue concentrations are available for {names}. A fixed tissue-to-blood ratio cannot be checked across times."
            basis, reach, missing = "", "Use the measured tissue values within their sampling window.", ["at least two eligible concurrent tissue and blood observations"]
        d3 = [d for d in b["d3"] if d.get("d3_status") in ("DATA_ISSUE", "SENSITIVITY_ONLY")]
        if d3:
            basis += " Partial organ recovery needs review: " + ", ".join(d["d3_status"] for d in d3) + "."
        if bd["kpuu"]["sites"]:
            reach += " Site-specific unbound measurements are listed with their estimator."
        views = [_view(k[0], f, k[1], 3 if k[0] == "DIS4e" else 1) for k, f in panels if not prim or f != prim.get("file")]
        q5 = _qrow(5, ST_PART if checks or bd["kpuu"]["sites"] else ST_NO, obs, basis, reach, missing, prim, views, ev)
        if prim and not q5["primary"]:
            q5["views"].insert(0, _view("DIS-3a", prim["file"], "Measured tissue concentrations"))
        q5["fixed_ratio_checks"] = checks
        q5["strongest_concurrent_ratio"] = {k: main[k] for k in ("tissue_sid", "tissue", "ref_label", "ratio_unit", "readable_window_h", "analyte")} if ranked else None
        qs.append(q5)
    else:
        qs.append(_qrow(5, ST_NA, "This study has no tissue concentration observations."))
    q5 = next(q for q in qs if q["q"] == 5)
    conditional = [p.get("dis4b") for p in pairs if (p.get("dis4b") or {}).get("fold_ci_kind") == "CONDITIONAL_ZERO_COVARIANCE_INTERVAL"]
    if conditional:
        q5["basis"] += " Any interval formed from four group CVs assumes zero covariance between matrices and times; it is a conditional sensitivity interval, not a paired-animal test."
        q5["conditional_interval_assumption"] = "zero covariance between matrices and times"
    tests = b.get("prespecified_ratio_tests") or []
    if tests:
        q5["prespecified_ratio_tests"] = tests
        summaries = []
        for test in tests:
            if test["status"] == "ASSESSED":
                summaries.append(f"{test['id']}: {test['organ']} late/early geometric-mean ratio change {_f(test['fold_change'])}×; "
                                 f"Bonferroni-adjusted p {_f(test['p_adjusted'],4)} ({test['reading'].lower().replace('_',' ')}).")
            else:
                summaries.append(test["id"] + ": not assessable: " + "; ".join(test["exclusion_reasons"]) + ".")
        q5["observed"] += " Prespecified animal-level comparisons: " + " ".join(summaries)
        q5["basis"] += " Longitudinal animals contribute paired log-ratio changes; independent time cohorts contribute individual log ratios to Welch's t test. The configured family uses Bonferroni adjustment."
        q5["reach"] += " This two-time contrast does not establish equilibrium or a transport mechanism and does not replace the three-time T8 check."
        q5["evidence"].append(_ratio_test_evidence(tests))
        if any(x["status"] == "ASSESSED" for x in tests):
            q5.update(status=ST_PART,status_code=ST_CODE[ST_PART])
    q5["text"] = " ".join(q5[k] for k in ("observed","basis","reach") if q5[k])
    return bd


def _dq_unbound_plasma(b, bd, qs):
    """Question 6: unbound plasma exposure; returns qs. Part of board_questions (split 2026-11-26 without change)."""
    status = bd["plasma_unbound_status"]
    points = bd["unbound_points"]
    fus = bd["fu_table"]
    views, ev, prim = [], [], None
    f5 = b["figs"].get(("DIS5a", "board"))
    if fus:
        rows = [[x["study"], x["matrix"], x["method"], f"{_f(x['conc'])} {x.get('conc_unit') or ''}", _f(x["fu"])] for x in fus]
        ev.append({"rule": "Match species, study, matrix, method and concentration range before converting total plasma.",
                   "tables": [{"caption": "Binding measurements", "head": ["Study", "Matrix", "Method", "Test concentration", "fu"], "rows": rows}],
                   "data": sorted({x["dataset_id"] for x in fus})})
        prim = _rowprim(6, ["Study", "Matrix", "Method", "Test concentration", "fu"], rows[:6], "Binding measurements", "binding records")
    if f5:
        prim = _prim(f5, "DIS-4a", 6, "Fraction unbound by concentration", "binding records")
    if points:
        rows = [[p["sid"], _f(p["t"]), _f(p["cu_mg_l"]), p["basis"], p.get("binding_dataset", p["record_id"])] for p in points]
        head = ["Profile", "Time (h)", "Cu,p (mg/L)", "Basis", "Source"]
        ev.append({"rule": "Retain the measured or derived basis of each unbound observation.", "data": sorted({p["sid"].split(":")[0] for p in points}),
                   "tables": [{"caption": "Unbound plasma concentrations", "head": head, "rows": rows}]})
        prim = _rowprim(6, head, rows[:5], "Unbound plasma exposure", "concentration records")
        if b["figs"].get(("Unbound plasma", "board")):
            prim = _prim(b["figs"][("Unbound plasma", "board")], "Table 4", 6, "Unbound concentrations at observed times", "measured or derived")
        if f5:
            views.append(_view("DIS-4a", f5, "Binding measurements"))
    obs = {"MEASURED": "Use the measured unbound plasma concentrations at their sampled times.",
           "DERIVED": "Unbound plasma concentrations can be derived at the matched observations.",
           "UNKNOWN": "Unbound plasma exposure is unknown."}[status]
    cf = bd.get("conditional_fu")
    xv = bd.get("ex_vivo_binding") or []
    if xv:
        ev.append({"rule": "Binding measured in plasma taken after dosing is listed with its analyte and sampling time; total radioactivity is not parent drug.",
                   "data": sorted({x["dataset_id"] for x in xv}),
                   "tables": [{"caption": "Binding in plasma taken after dosing (ex vivo)", "head": ["Study", "Analyte", "Time (h)", "Concentration", "Bound (%)", "fu"],
                               "rows": [[x["study"], x.get("analyte") or "not reported", _f(x.get("time_h")), f"{_f(x['conc'])} {x.get('conc_unit') or ''}".strip(),
                                         _f(x["bound_pct"]), _f(x["fu"])] for x in xv]}]})
    reach = ""
    if status == "UNKNOWN" and cf:
        lo, hi = cf["fu_range"]
        a0, a1 = cf["assay_range_mg_l"]
        p0, p1 = cf["pk_range_mg_l"]
        obs = (f"Unbound plasma was not measured in this study. A conditional sensitivity conversion is available: fu,p {_f(lo)}–{_f(hi)} "
               f"({cf['method']}, {cf['study']}, same species), {cf['fold']:.2f}-fold across {_f(a0)}–{_f(a1)} mg/L; "
               f"{cf['points_inside']} of {cf['points_total']} quantified total concentrations of this study ({_f(p0)}–{_f(p1)} mg/L) lie inside that range.")
        sup = cf.get("ex_vivo_support")
        if sup:
            b0, b1 = sup["bound_pct_range"]
            obs += (f" Plasma taken {_f(sup['times_h'][0])}–{_f(sup['times_h'][1])} h after dosing" if sup.get("times_h") else " Plasma taken after dosing")
            obs += (f" was {_f(b0)}–{_f(b1)} % bound (fu {_f(sup['fu_range'][0])}–{_f(sup['fu_range'][1])}, {sup['n_values']} values; "
                    + ("total radioactivity, not parent" if re.search(r"radioact|14\s*c", str(sup.get("analyte") or ""), re.I) else str(sup.get("analyte") or "analyte not reported")) + "): "
                    + f"{sup['ratio_to_in_vitro'][0]:.2f}–{sup['ratio_to_in_vitro'][1]:.2f} of the in vitro fu, "
                    + ("within" if sup["within_band"] else "outside") + " the 0.80–1.25 band,"
                    + (" and has a small observed range over time." if sup["stable_over_time"] else " and varies over time.") + " This mixed radiolabel comparison is contextual only; parent binding concordance remains unverified.")
        reach = ("Cu,p = total × fu holds under these conditions: " + "; ".join(cf["conditions"]) + "." if cf["conditions"] else
                 "Cu,p = total × fu within the assayed range.") + " This is a sensitivity range for covered samples only, not measured unbound exposure, a confidence interval or a volume estimate. Ex vivo total radioactivity cannot validate transfer of parent fu."
        ev.append({"rule": "A fraction unbound that is stable across an assayed range covering the plasma concentrations gives a conditional conversion; "
                           "a cross-study transfer is stated as a condition (item 27).", "data": [cf["dataset_id"]],
                   "tables": [{"caption": "Conditional conversion of total plasma", "head": ["fu,p", "Assayed range (mg/L)", "This study's total plasma (mg/L)", "Inside range", "Label"],
                               "rows": [[f"{_f(lo)}–{_f(hi)}", f"{_f(a0)}–{_f(a1)}", f"{_f(p0)}–{_f(p1)}", f"{cf['points_inside']} of {cf['points_total']}", cf["label"]]]}]})
        miss = ["unbound plasma measured in this study's animals"]
        qs.append(_qrow(6, ST_PART, obs, ("Keep in mind: " + "; ".join(say(c) for c in bd["caveats"]) + ".") if bd["caveats"] else "", reach, miss, prim, views, ev))
        return qs
    own = [x for x in xv if x["study"] == b["study"]]
    if status == "UNKNOWN" and own and not bd.get("pk_range"):
        obs = _cap(_ex_vivo_summary(own)) + ". This study has no total parent plasma profile to convert."
        head = ["Time (h)", "Native concentration", "Concentration SE", "Bound (%)", "Bound SE (%)", "n", "Experimental unit"]
        rows = [[_f(x.get("time_h")), f"{_f(x.get('conc'))} {x.get('conc_unit') or 'unit not reported'}",
                 f"{_f(x['conc_se'])} {x.get('conc_se_unit') or x.get('conc_unit') or ''}" if x.get("conc_se") is not None else "not reported",
                 _f(x["bound_pct"]), _f(x.get("se_pct")) if x.get("se_pct") is not None else "not reported",
                 _f(x.get("n")), x.get("n_basis") or "not reported"] for x in own]
        prim = _rowprim(6, head, rows, "This study: post-dose plasma binding in native units", "post-dose binding samples")
        # Own data first. Borrowed in-vitro parent binding remains explicitly external context.
        ev = [{"rule": "These are this study's post-dose binding measurements, with the original analyte and units; do not interpret total radioactivity as parent-specific fu.",
               "data": sorted({x["dataset_id"] for x in own}),
               "records": [{k: x.get(k) for k in ("dataset_id", "record_id", "source_pointer", "source_refs")} for x in own],
               "tables": [{"caption": "This study: post-dose binding", "head": head, "rows": rows}]}] + [
                   dict(item, rule="External binding context only. " + item["rule"]) for item in ev if item.get("data") != sorted({x["dataset_id"] for x in xv})]
        views = []
        qs.append(_qrow(6, ST_NO, obs, ("Keep in mind: " + "; ".join(say(c) for c in bd["caveats"]) + ".") if bd["caveats"] else "", "",
                        ["a total parent plasma profile in this study"], prim, views, ev))
        return qs
    if status == "UNKNOWN" and fus:
        obs += " Binding measurements are available, but they do not support a conversion of this plasma profile."
    miss = ["measured unbound plasma, or total plasma with a matched fraction unbound"] if status == "UNKNOWN" else []
    qs.append(_qrow(6, {"MEASURED":ST_YES, "DERIVED":ST_PART, "UNKNOWN":ST_NO}[status], obs,
                    ("Keep in mind: " + "; ".join(say(c) for c in bd["caveats"]) + ".") if bd["caveats"] else "", "", miss, prim, views, ev))
    return qs


def board_questions(b):
    qs = []
    ivr, iv24 = b["iv_refs"], b["item24"]
    level = _lvl_page(ivr) if ivr else _lvl_page(b["tissues"] + b["ev_refs"])
    # Q1
    iv_coverage, usable = _dq_systemic_shape(b, iv24, ivr, level, qs)
    # Q2
    _dq_initial_volume(b, iv_coverage, ivr, level, qs)
    # Q3
    _dq_route_comparison(b, iv_coverage, ivr, level, qs)
    # Source question 4 evaluates the support for the systemic shape.
    _dq_shape_support(b, qs, usable)
    # Tissue observations answer the proxy question. All comparisons retain their own measured matrix.
    bd = _dq_tissues(b, qs)
    # Unbound plasma is required even for studies with no tissue data.
    return _dq_unbound_plasma(b, bd, qs)


# ---------------------------------------------------------------- working hypothesis per study (H row)

def board_hypothesis(b):
    """One working hypothesis per study board. `lines` holds the labelled parts shown on the page, `text` the same content as
    one sentence (overview table, sha256), `ladder` the model steps a fit should try with what each must show."""
    parts, lines, rests, miss, check, ladder = [], [], [], [], [], []
    shape = None      # SUPPORTED / TENTATIVE / ONE_PHASE / NONLINEAR_FIRST / STEEPENS
    ev_only = None    # EV profiles without IV in the study: READ when the species has a readable IV profile elsewhere, NONE otherwise
    slow_tissue = dose_nonlinear = False

    def add(label, text):
        parts.append(text)
        lines.append({"label": label, "text": _cap(text) + "."})

    usable = [r for r in b["item24"] if r.get("curvature") not in (None, "NOT_ASSESSABLE")]
    if usable:
        pv = sorted({r["phases_visible"] for r in usable})
        nu = len(usable)
        nlc = [r for r in usable if r.get("t7_label") == "EXCLUDED_UNDER_STATED_ASSUMPTIONS"]
        t6x = [r for r in usable if r.get("t6_label") == "EXCLUDED_UNDER_STATED_ASSUMPTIONS"]
        sens = lambda rs: all("SENSITIVITY_ONLY" in (r.get("t7_flags", []) + r.get("t6_flags", [])) for r in rs)
        tol = lambda rs, k: min((r[k] for r in rs if r.get(k) is not None), default=None)
        n2 = sum(r["phases_visible"] == "TWO_OR_MORE" for r in usable)
        nt = sum(r["phases_visible"] == "TWO_OR_MORE_TENTATIVE" for r in usable)
        gate = next((r["noise_gate"] for r in usable if r.get("noise_gate")), None)
        num6 = [r for r in usable if r.get("t6_at_tolerance")]
        num6n = [r for r in num6 if r.get("t6_at_noise")]
        num7n = [r for r in usable if r.get("t7_at_tolerance") and r.get("t7_at_noise")]
        t6_clause = ""
        if gate and num6 and nu > 1:
            t6_clause = (f"; numerically, one straight line is contradicted in {len(num6n)} of {nu} at the noise setting"
                         + (f" and in {len(num6) - len(num6n)} more only at the ±{TOL * 100:g} % reading tolerance" if len(num6) > len(num6n) else "")
                         + " (not a formal test)")
        if num7n and 2 * len(num7n) <= nu and not nlc:
            check.append(f"{_names_of(num7n)} steepen{'s' if len(num7n) == 1 else ''} numerically at the noise setting ({len(num7n)} of {nu} IV profiles): timing, infusion end, analyte")
        if nlc and 2 * len(nlc) > nu:
            x = tol(nlc, "t7_extra_tolerance_pct")
            shape = "NONLINEAR_FIRST"
            add("Decline shape", f"the IV decline is not log-convex in {len(nlc)} of {nu} profiles, so a nonlinear or recycling candidate comes first (pending DME)"
                         + (f"; the contradiction holds up to a further ±{_f(x)} % on every point" if x is not None else "")
                         + (" (project tolerance, no SD)" if sens(nlc) else ""))
        elif nlc:
            check.append(f"the {len(nlc)} of {nu} IV profiles that are not log-convex ({', '.join(r['label'] for r in nlc[:3])}{'…' if len(nlc) > 3 else ''}): timing, infusion end, analyte")
        if nlc and 2 * len(nlc) > nu:
            pass
        elif nu > 1 and (n2 + nt) and "NOT_LOG_CONVEX_DESCRIPTIVE" not in pv:
            # several profiles: say how many carry the bend instead of letting one profile speak for all
            flat = n2 + nt
            detail = (f" ({n2} hold without the first or the last point, {nt} are sensitive to sampling)" if n2 and nt else
                      " (each holds without the first or the last point)" if n2 else " (each is sensitive to sampling)")
            if n2 and 2 * flat > nu:
                add("Decline shape", f"the IV decline slows in {flat} of {nu} profiles{detail}, so at least two compartments are supported" + t6_clause)
                shape = "SUPPORTED"
            elif n2:
                add("Decline shape", f"the IV decline slows in {flat} of {nu} profiles{detail}: a second compartment is a candidate, not yet seen in most profiles" + t6_clause)
                shape = "TENTATIVE"
            else:
                add("Decline shape", f"the IV decline slows in {flat} of {nu} profiles{detail}; retain one and two compartments as candidates" + t6_clause)
                shape = "TENTATIVE"
        elif t6x and 2 * len(t6x) > nu and "TWO_OR_MORE" not in pv:
            x = tol(t6x, "t6_extra_tolerance_pct")
            shape = "SUPPORTED"
            add("Decline shape", f"a single exponential is excluded (T6) in {len(t6x)} of {nu} IV profiles, so a multi-compartment candidate is supported"
                         + (f"; this holds up to a further ±{_f(x)} % on every point" if x is not None else "")
                         + (" (project tolerance, no SD)" if sens(t6x) else ""))
        elif "NOT_LOG_CONVEX_DESCRIPTIVE" in pv:
            add("Decline shape", "the observed IV semilog decline steepens; its cause remains unresolved")
            shape = "STEEPENS"
        elif "TWO_OR_MORE" in pv:
            add("Decline shape", "plasma shows two or more decline phases after IV dosing, so a multi-compartment candidate is supported")
            shape = "SUPPORTED"
        elif "TWO_OR_MORE_TENTATIVE" in pv:
            add("Decline shape", "plasma may show a second phase; deleting a point changes the reading or leaves too few samples to repeat it")
            shape = "TENTATIVE"
        else:
            e = min(r["earliest_sample_h"] for r in usable)
            at_end = any(abs(x) <= 1e-9 for r in usable for x in r.get("input_samples_h") or [])
            low_power = [r for r in usable if (r.get("split") or {}).get("power_ok") is False]
            if low_power and len(low_power) == len(usable):
                # Same candidate grouping as ONE_PHASE (parsimony); only the sentence stops reading a low-power screen as a finding.
                def span(xs):
                    xs = sorted(xs)
                    return _f(xs[0]) if len(xs) == 1 or _f(xs[0]) == _f(xs[-1]) else f"{_f(xs[0])}–{_f(xs[-1])}"
                ratios = [r["split"]["R"] for r in low_power if r["split"].get("R")]
                mdd = [r["split"]["min_detectable_rate_difference"] for r in low_power if r["split"].get("min_detectable_rate_difference")]
                detail = "; ".join(([f"early/late slope ratio {span(ratios)}"] if ratios else [])
                                   + ([f"smallest detectable rate difference {span(mdd)} per h"] if mdd else []))
                add("Decline shape", f"no slowing of the decline after {_f(e)} h is detected, but the screen has low power at the noise setting"
                    + (f" ({detail})" if detail else "") + ": a second phase is neither shown nor excluded" + t6_clause)
                shape = "ONE_PHASE"
            else:
                add("Decline shape", f"one decline phase is seen after {_f(e)} h; earlier samples would show whether a distribution phase was missed" + t6_clause)
                shape = "ONE_PHASE"
            if at_end:
                add("Decline shape", "a sample at the end of input exists but is not used for the shape, because a sample at the nominal end may "
                                     "still fall inside the input")
                miss.append(f"IV samples between the end of input and {_f(e)} h")
            else:
                miss.append(f"IV samples earlier than {_f(e)} h")
        rests.append("item 24 split-half reading" + (", T6" if any(r.get("t6_label") == "EXCLUDED_UNDER_STATED_ASSUMPTIONS" for r in usable) else "")
                     + (", T7" if any(r.get("t7_label") not in (None, "CANNOT_ASSESS") for r in usable) else ""))
        pd = [r["post_distribution_from_h"] for r in usable if r["curvature"] == "FLATTENING" and isinstance(r.get("post_distribution_from_h"), (int, float))]
        if pd:
            if len(set(pd)) > 1:
                add("Terminal window", f"the later, slower part starts between {_f(min(pd))} and {_f(max(pd))} h in the profiles that slow; "
                    "confirm an IV terminal window against each profile (item 18)")
            else:
                add("Terminal window", f"a candidate start for an IV terminal window is {_f(pd[0])} h; confirm against the profile (item 18)")
    elif b["iv_refs"]:
        if any("ONGOING_INPUT" in r["caveats"] for r in b["item24"]):
            add("Input design", "systemic and tissue observations were collected during ongoing IV input; no post-stop half-life, decline phase or bolus Vc is assigned")
            miss.append("a separate documented post-stop sampling window for a disposition-shape assessment")
        elif any("ACTIVE_MATERIAL" in r["caveats"] for r in b["item24"]):
            add("Assay scope", "the source measures antimicrobial activity; parent-specific decline structure and Vc are not established")
            miss.append("parent-specific assay evidence before assigning parent disposition or Vc")
        else:
            add("Decline shape", "the IV decline cannot be read yet")
            miss.append("predose range and baseline review" if any("ENDOGENOUS_REVIEW_REQUIRED" in r["caveats"] for r in b["item24"]) else "≥ 5 quantified IV points after the end of dosing, with the IV mode")
    else:
        siv = b.get("species_iv") or []
        read = [x for x in siv if x["readable"]]
        if b.get("systemic_iv_coverage"):
            add("Disposition", "systemic IV measurements are present, but the available profiles do not resolve IV decline phases")
            miss.append("a first-dose IV profile with sufficient quantified post-input observations")
        else:
            miss.append("an IV profile in the same study" if siv and (b["ev_refs"] or b["tissues"]) else "an IV profile")
        if b["ev_refs"] and not b.get("systemic_iv_coverage"):
            ev_only = "READ" if read else "NONE"
            if read:
                add("Disposition", f"no IV profile in this study, so these profiles give apparent values only (CL/F, V/F); the IV disposition for {b['species']} comes from "
                    f"{_species_iv_words(read)}: carrying its structure over is an assumption, because animals, condition and assay may differ")
            else:
                add("Disposition", f"no readable IV profile for {b['species']} in this project, so only apparent values (CL/F, V/F) can be estimated and a fast "
                    "distribution phase cannot be told from ongoing input")
    okb = [x for x in b["item25"] if x.get("vc_upper_bound_l_per_kg")]
    vs = b.get("vc_summary") or vc_summary(okb)
    if okb:
        m = min(okb, key=lambda x: x["vc_upper_bound_l_per_kg"])
        if vs["kind"] == "PER_ANIMAL":
            add("Initial volume", f"a typical initial Vc should start at or below about {_f(vs['median'])} L/kg (median of {vs['n']} per-animal bounds, "
                f"range {_f(vs['min'])}–{_f(vs['max'])} L/kg)")
            if vs.get("same_time_fold") and vs["same_time_fold"] > EARLY_SPREAD_FOLD:
                check.append(f"concentrations at {_same_time_text(vs, _board_ends(b))} differ {_f(vs['same_time_fold'], 2)}-fold between animals given the same dose: "
                             "dose per animal, animal identity in the source, timing of the first sample")
        else:
            add("Initial volume", f"an initial Vc estimate should not exceed {_f(m['vc_upper_bound_l_per_kg'])} L/kg (sample at {clock_text(m['sample_time_h'], [m.get('input_end_h')])})")
        rests.append("item 25 bound")
        if any(x["data_check"] == "VOLUME_BELOW_PLASMA" for x in okb):
            check.append("dose, units, timing and sampling site (bound below plasma volume)")
    sp = b.get("animal_spread")
    if sp:
        au = sp.get("auc")
        early_heavy = bool(au and sp["first"]["fold"] >= 1.5 * au["fold"])
        ends = _board_ends(b)
        add("Between animals", f"at the same dose, concentrations differ {_f(sp['first']['fold'], 2)}-fold at {clock_text(sp['first']['t'], ends)} ({sp['first']['n']} animals) and "
            f"{_f(sp['late']['fold'], 2)}-fold at {clock_text(sp['late']['t'], ends)} ({sp['late']['n']} animals)"
            + (f"; the area from {clock_text(au['from_h'], ends)} to {clock_text(au['to_h'], ends)} differs {_f(au['fold'], 2)}-fold (CV {_f(au['cv_pct'], 2)} %)" if au else "")
            + ("; the early spread is larger than the spread in exposure, so allow between-animal variability on the initial volume as well as on clearance"
               if early_heavy else "; allow between-animal variability on clearance and on the initial volume and let the fit show which is needed"))
        rests.append("observed concentrations at shared times")
    for item in b["q8_evidence"]:
        rests.append(f"absorption dose proportionality ({item['route']}, {item['key']})")
        pd_ = [r for r in item.get("per_dose") or [] if isinstance(r.get("thalf"), (int, float)) and r["thalf"] > 0]
        if item["route"] == "EV" and len(item["doses"]) >= 2:
            num = lambda k: item.get(k) if isinstance(item.get(k), (int, float)) else None  # noqa: E731
            cx, aw, al = num("cmax_d_ratio"), num("auc_ratio"), num("auc_last_ratio")
            bits = [f"Cmax/D changes {_f(cx, 2)}-fold"] if cx else []
            if aw and al and abs(math.log(aw / al)) > 0.05:
                bits.append(f"AUC/D changes {_f(aw, 2)}-fold over the window all doses share ({item['window']} h) but {_f(al, 2)}-fold to each profile's own last sample")
            elif aw or al:
                bits.append(f"AUC/D changes {_f(aw or al, 2)}-fold")
            if len(pd_) >= 2:
                bits.append(f"the post-peak half-life goes from {_f(pd_[0]['thalf'], 2)} to {_f(pd_[-1]['thalf'], 2)} h")
                if len(bits) > 1:
                    bits[-1] = "and " + bits[-1]
            if bits:
                outside = lambda x: x is not None and not BAND[0] <= x <= BAND[1]  # noqa: E731
                moved = len(pd_) >= 2 and outside(pd_[-1]["thalf"] / pd_[0]["thalf"])
                off = outside(aw) or outside(al) or outside(cx)
                dose_nonlinear = dose_nonlinear or moved or off
                add("Dose", f"from {_f(min(item['doses']))} to {_f(max(item['doses']))} mg/kg ({item.get('route_name') or 'EV'}), absorption finds that "
                    + ", ".join(bits) + (" (its figure C1)" if item.get("figure") else "")
                    + (". A post-peak slope that changes with dose is not one elimination rate, so do not carry disposition values from one dose to another unchecked"
                       if moved else ". Exposure does not scale with dose while the post-peak slope stays similar: F changing with dose and saturable elimination "
                       "are both candidates, and an IV profile at a second dose would separate them" if off else
                       ". Exposure and the post-peak slope scale with dose over this range"))
    made = b.get("absorption_route_pairs") or []
    if made:
        add("Routes", "absorption compared the routes of this study: " + "; ".join(f"{m['ev']} against {m['iv']}, {say_codes(m['summary'])}" for m in made)
            + ". Take the disposition from the IV profile; the EV tail can be set by input")
        rests.append("absorption route comparison (T4)")
    for d in b["dose_patterns"]:
        if d["dose_pattern"] not in ("NOT_APPLICABLE",):
            # R7 item 4: observable shape only; dose_nonlinear and mechanism candidates are not set from this field
            rr = [r["ratio"] for r in d.get("rows") or []]
            span = f" (high/low ratio {_f(min(rr), 2)}–{_f(max(rr), 2)})" if rr else ""
            if d["confounded"]:
                add("Dose", f"the IV dose contrast{span} compares different animals or studies, so dose and subject or study effects cannot be separated")
            else:
                add("Dose", say(d["dose_pattern"]) + span)
            rests.append("DIS-2a/2b dose pattern")
    # DIS-3b readings, tissues with the same reading, evidence basis and window grouped in one clause
    _say = {"RISING": "{who} rise relative to {ref}: a slow tissue compartment candidate, and a terminal slope from {ref} in this window may overestimate the true terminal rate",
            "TISSUE_NOT_FALLING": "{who} do not fall while {ref} falls: an uptake or binding candidate",
            "FALLING": "{who} fall faster than {ref}: a tissue elimination or efflux candidate"}
    grp = {}
    for p in b["tissue_pairs"]:
        rows_ = [x for x in p.get("rows", []) if isinstance(x.get("ratio"), (int, float))
                 and all(isinstance(x.get(k), (int, float)) and math.isfinite(x[k]) and x[k] > 0 for k in ("ratio", "ref", "tissue"))]
        if (p.get("regimen") or {}).get("ongoing_input") and len(rows_) >= 2:
            rs_, ts_ = [x["ratio"] for x in rows_], [x["t"] for x in rows_]
            fold = lambda k: max(x[k] for x in rows_) / min(x[k] for x in rows_)   # noqa: E731
            war = (p.get("window_auc_ratio") or {}).get("ratio")
            unit = "" if p.get("ratio_unit") == "dimensionless" else f" {p.get('ratio_unit')}"
            add("Tissue", f"{p['tissue']}/{p['ref_label'].lower()} concurrent ratio {_f(min(rs_))}–{_f(max(rs_))}{unit} at {len(rows_)} times over {_f(min(ts_))}–{_f(max(ts_))} h during ongoing IV input"
                + (f" (window AUC ratio {_f(war)})" if isinstance(war, (int, float)) else "")
                + f"; over that window {p['ref_label'].lower()} varies {fold('ref'):.2f}-fold and {p['tissue']} {fold('tissue'):.2f}-fold, this describes concurrent total concentrations during input; a plateau or equilibrium is not established by these ratios; Kp,uu and transport are not assigned")
            rests.append("DIS-3a concurrent ratios during ongoing input")
        rd = p.get("ratio_reading")
        if not rd or rd == "NOT_ASSESSABLE":
            continue
        ch = p.get("dis4b") or {}
        basis = "description" if p.get("t8_label") in (None, "CANNOT_ASSESS") else "T8"
        win = f"{_f(ch['t_early'])}–{_f(ch['t_late'])} h" if ch.get("t_early") is not None else ""
        extra = "total radioactivity" if "TOTAL_RADIOACTIVITY" in p["caveats"] else ""
        grp.setdefault((rd, p["ref_label"].lower(), basis, win, extra), []).append(p)
        rests.append("DIS-3b" + (" (T8)" if basis == "T8" else " (description)"))
    for (rd, ref, basis, win, extra), ps in grp.items():
        who = _names(ps)
        qual = " (" + ", ".join(x for x in (basis, win, extra) if x) + ")"
        if basis == "description" and rd in ("RISING", "FALLING", "TISSUE_NOT_FALLING"):
            add("Tissue", f"{who}{qual}: the endpoint ratio to {ref} " + ("is lower" if rd == "FALLING" else "is higher") + "; uncertainty limits interpretation")
        elif rd == "NO_DIFFERENCE_SEEN":
            add("Tissue", f"{who}{qual}: no endpoint ratio difference detected; equilibrium is unresolved")
        elif rd == "VARIABLE_WITHIN_WINDOW":
            add("Tissue", f"{who}{qual}: similar endpoint ratios with an intervening excursion")
        else:
            if len(ps) == 1:
                txt = _say[rd].replace("{who} rise", "{who} rises").replace("{who} do not", "{who} does not").replace("{who} fall ", "{who} falls ")
            else:
                txt = _say[rd]
            add("Tissue", txt.format(who=who + qual, ref=ref))
            slow_tissue = slow_tissue or rd == "RISING"
    np_ = [p for p in b["tissue_pairs"] if p.get("ratio_reading") == "NOT_ASSESSABLE"]
    if np_:
        groups = {}
        for p in np_:
            groups.setdefault(p.get("na_group") or "not assessable", []).append(p)
        segs = []
        for g, ps in groups.items():
            seg = f"{_names(ps, 5)} ({g})"
            rr = [p for p in ps if [x for x in p["rows"] if x["ratio"]]]
            if g == "fewer than 3 common times" and rr:
                ex = rr[0]
                vals = [x for x in ex["rows"] if x["ratio"]]
                seg += f", e.g. {ex['tissue']} {' → '.join(_f(x['ratio']) for x in vals[:3])} {ex['ratio_unit']} at {', '.join(_f(x['t']) for x in vals[:3])} h"
            segs.append(seg)
        add("Tissue", "tissue/reference trend not readable for " + "; ".join(segs))
        site = groups.get("local route, dose given into this space")
        if site:
            add("Dosing site", f"{_names(site, 5)}: sampled where the dose was given, so describe that space as the dosing depot and not with a tissue-to-plasma ratio")
        if "fewer than 3 common times" in groups:
            miss.append("≥ 3 common quantified tissue and reference times")
        if "ELF urea correction not reported" in groups:
            miss.append("ELF urea dilution correction")
    bd = b["binding"]
    own_binding_only = _ex_vivo_only(b)
    if own_binding_only:
        add("Post-dose binding", _ex_vivo_summary(_own_ex_vivo(b)))
        rests.append("this study's post-dose binding samples (native units)")
    if bd["plasma_unbound_status"] == "UNKNOWN" and bd.get("conditional_fu"):
        miss.append("unbound plasma measured in this study's animals (the fu,p conversion is conditional)")
    elif bd["plasma_unbound_status"] == "UNKNOWN":
        miss.append("matched total plasma and applicable fu,p, or measured unbound plasma")
    if bd["fu_table"]:
        fus = [x["fu"] for x in bd["fu_table"]]
        add("External binding context" if own_binding_only else "Binding", ("external in-vitro context only: " if own_binding_only else "") + f"reported fraction unbound ({', '.join(sorted({x['matrix'] for x in bd['fu_table']}))}) {_f(min(fus))}" + (f"–{_f(max(fus))}" if max(fus) > min(fus) else "") + (" and changing with concentration (nonlinear binding candidate)" if "NONLINEAR_BINDING" in bd["caveats"] else "")
                     + (f" from other studies ({', '.join(bd.get('fu_studies', []))})" if "FU_OTHER_STUDY" in bd["caveats"] else "")
                     + ((f"; stable across {_f(bd['conditional_fu']['assay_range_mg_l'][0])}–{_f(bd['conditional_fu']['assay_range_mg_l'][1])} mg/L, allowing a sensitivity conversion only for covered samples; unbound exposure and volumes remain unresolved"
                         + (" (ex vivo total-radioactivity fu is numerically within 0.80–1.25; this does not validate parent fu transfer)" if (bd["conditional_fu"].get("ex_vivo_support") or {}).get("within_band") else ""))
                        if bd.get("conditional_fu") else ""))
        rests.append("item 27 records")
    sc = sorted({c for s_ in b["iv_refs"] + b["tissues"] for c in s_.get("source_conflicts", [])})
    if sc:
        check.append("source conflict noted upstream: " + sc[0].split(":", 1)[-1].strip() + (f" (+{len(sc) - 1} more)" if len(sc) > 1 else ""))
    for d in b["d3"]:
        if d.get("d3_status") == "DATA_ISSUE":
            check.append("homogenate dilution, value basis and units (D3 sum above the dose)")
    if b.get("reported_parameters") and not b["item24"]:
        names = ", ".join(sorted({x["parameter"] for x in b["reported_parameters"]}))
        add("Reported", f"the source reports {names}; its parameter records can be reviewed with their definitions and units")
        rests.append("source-reported parameter records")
    if not parts:
        add("Reading", "no distribution reading is possible from these data yet")
    # model steps: what a fit should try, in order, and what each step must show
    nonlinear_binding = "NONLINEAR_BINDING" in bd["caveats"]
    if ev_only:
        ladder.append(["M0", "One-compartment disposition in apparent terms (CL/F, V/F); the input model comes from absorption", "—"])
        if ev_only == "READ":
            ladder.append(["M1", f"Disposition structure taken from the IV study of this species ({', '.join(x['study'] for x in b['species_iv'] if x['readable'])})",
                           "the EV profiles fitted with the IV disposition held, only F and the input differing"])
        if dose_nonlinear:
            ladder.append(["Alt", "Dose-dependent input or elimination instead of one linear model for all doses", "an IV profile at two or more doses, to tell input from elimination"])
        if nonlinear_binding:
            ladder.append(["Alt", "Concentration-dependent plasma binding", "unbound concentrations, or fu,p measured over the PK concentration range"])
    if shape:
        vc_txt = ""
        if okb:
            vc_txt = (f"Vc at or below about {_f(vs['median'])} L/kg for the typical animal" if vs["kind"] == "PER_ANIMAL" else
                      f"Vc at or below {_f(vs['min'])} L/kg")
        ladder.append(["M0", "One compartment, linear, IV input as dosed", vc_txt or "—"])
        if shape == "SUPPORTED":
            ladder.append(["M1", "M0 + reversible peripheral exchange (two compartments)", "both phases estimable, with the early phase carried by more than the first sample"])
            if COMMON.three_phase_reading(b.get("item24"))["candidate"]:   # George 2026-11-25: at least two, three only as a candidate
                ladder.append(["M2", "M1 + a second peripheral compartment (three compartments)",
                               "a second bend that remains in the profiles where the decline still slows after the early points"])
        elif shape == "TENTATIVE":
            ladder.append(["M1", "M0 + reversible peripheral exchange, tentative", "an improvement over M0 that remains when the first sample is left out"])
        elif shape == "ONE_PHASE":
            ladder.append(["M1", "M0 + reversible peripheral exchange, only with earlier samples", "a fast phase in samples earlier than the present first sample"])
        if shape in ("NONLINEAR_FIRST", "STEEPENS") or dose_nonlinear:
            ladder.append(["Alt", "Nonlinear elimination or binding instead of a further compartment", "dose-normalized IV profiles at two or more doses that do not superimpose"])
        if slow_tissue:
            ladder.append(["Alt", "A slow tissue compartment behind the plasma terminal phase", "a tissue/plasma ratio that still rises at the last common times, with SD and n"])
        if nonlinear_binding:
            ladder.append(["Alt", "Concentration-dependent plasma binding", "unbound concentrations, or fu,p measured over the PK concentration range"])
    # what the questions of this board list as missing belongs in the same place
    themes = ("IV mode", "plasma-volume", "second IV dose", "earlier", "individual profiles", "dose per kg", "quantified")
    for q in (b.get("questions") or []) if shape else []:
        if q["q"] in (1, 2, 4):
            for m_ in q["missing"]:
                th = next((k for k in themes if k in m_), m_)
                if m_ and not any(th in x for x in miss):
                    miss.append(m_)
    text = _cap("; ".join(parts)) + "."
    lv = _lvl_page(b["iv_refs"] + b["tissues"] + b["ev_refs"])
    h = {"id": f"H-{_slug(b['study'])}-{_slug(b['species'])}-r1", "text": text, "lines": lines, "ladder": ladder, "rests_on": ("Rests on: " + ", ".join(dict.fromkeys(rests)) + ".") if rests else "",
         "reach": f"Record level: {lv}.", "missing": list(dict.fromkeys(miss)), "check_first": list(dict.fromkeys(check)),
         "state": "PENDING", "target_binding": b["target_binding"]}
    import hashlib
    h["sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
    # what the overview summary is written from (codes and numbers only; the wording is in _overview_paras)
    fus_all = [x["fu"] for x in bd["fu_table"]] if bd["fu_table"] else []
    h["brief"] = {
        "shape": shape or ("ONGOING_INPUT" if any("ONGOING_INPUT" in r["caveats"] for r in b["item24"]) else
                           "ACTIVE_MATERIAL" if any("ACTIVE_MATERIAL" in r["caveats"] for r in b["item24"]) else
                           "UNREAD" if b["iv_refs"] else "REPORTED_ONLY" if b.get("reported_parameters") else
                           "UNREAD" if any(s.get("route_class") == "IV" and s.get("matrix_class") in REF_CLASSES for s in b.get("source_series", [])) else
                           "BINDING_ONLY" if not b["ev_refs"] and not b["tissues"] and not b.get("source_series") and (bd["fu_table"] or bd.get("ex_vivo_binding")) else "NO_IV"),
        "profiles": {"usable": len(usable), "robust": sum(r.get("phases_visible") == "TWO_OR_MORE" for r in usable),
                     "tentative": sum(r.get("phases_visible") == "TWO_OR_MORE_TENTATIVE" for r in usable),
                     "tested": sum(any(r.get(k) not in (None, "CANNOT_ASSESS") for k in ("t6_label", "t7_label")) for r in usable)},
        "vc": ({"value": vs["median"] if vs["kind"] == "PER_ANIMAL" else m["vc_upper_bound_l_per_kg"], "kind": vs["kind"], "min": vs["min"], "max": vs["max"], "n": vs["n"]} if okb else None),
        "tissue": {"series": len(b["tissue_pairs"]), "unread": len(np_),
                   "read": [{"reading": rd, "ref": ref, "basis": basis, "names": _names(ps), "n": len(ps), "window": win,
                             "analyte_scope": extra or ("antimicrobial activity; parent specificity unresolved" if any(p.get("analyte") == "ACTIVE_MATERIAL" for p in ps) else "parent")}
                            for (rd, ref, basis, win, extra), ps in grp.items()]},
        "fu": [min(fus_all), max(fus_all)] if fus_all else None,
        "nonlinear_binding": nonlinear_binding, "dose_nonlinear": dose_nonlinear,
        "fu_other_study": "FU_OTHER_STUDY" in bd["caveats"],
        "fu_conditional": bool(bd.get("conditional_fu")),
        "ongoing_tissue": [x["text"] for x in lines if x["label"] == "Tissue" and "during ongoing IV input" in x["text"]],
        "own_ex_vivo": _ex_vivo_summary(_own_ex_vivo(b)) if own_binding_only else None,
    }
    return h


# ---------------------------------------------------------------- build

TISSUE_CLASSES = ("TISSUE_HOMOGENATE", "ELF", "CSF", "CELLS", "ISF_MICRODIALYSIS", "OTHER_FLUID", "UNKNOWN")


def _sorted_tables(root):
    tables = json.loads((root / "source_tables.json").read_text(encoding="utf-8-sig"))
    tables = sorted(tables, key=lambda e: str(e.get("dataset_id", "")))
    for e in tables:
        rs = e.get("records")
        if isinstance(rs, list) and rs and all(isinstance(r.get("source_row"), (int, float)) for r in rs):
            e["records"] = sorted(rs, key=lambda r: r["source_row"])
    return tables


def species_table(boards, reported):
    rows = []
    for b in boards:
        for r in b["item24"] or [None]:
            bd = next((x for x in b["item25"] if r and x["sid"] == r["sid"]), None)
            rows.append({"species": b["species"], "study": b["study"], "series": r["label"] if r else "—",
                         "phases": r.get("phases_visible") if r else "—", "t6": r.get("t6_label") if r else "—", "t7": r.get("t7_label") if r else "—",
                         "t6_reading": check_words(r, "t6") if r else "—", "t7_reading": check_words(r, "t7") if r else "—",
                         "vc_bound": bd.get("vc_upper_bound_l_per_kg") if bd else None, "vc_t": bd.get("sample_time_after_start_h", bd.get("sample_time_h")) if bd else None,
                         "fu": [x["fu"] for x in b["binding"]["fu_table"] if x["study"] == b["study"] and classify_matrix(x["matrix"])[0] == "PLASMA"], "board": b["key"]})
    rep = [v for v in reported if v["parameter"] in ("Vss", "Vc", "Vz", "Vd (definition not stated)", "V/F", "Vc/F", "Vss/F", "Vz/F")]
    by_def = {}
    for v in rep:
        if v["parameter"] != "Vd (definition not stated)" and (v.get("value_l_per_kg") or 0) > 0 and v["species"] != "Species not stated":
            if v.get("route") not in (None, "NOT_FOUND"):
                by_def.setdefault((v["parameter"], v["route"], v.get("drug"), v.get("method")), set()).add(v["species"])
    comparable = sorted({k[0] for k, species in by_def.items() if len(species) >= 2 and k[2] and k[3] not in (None, "not reported")})
    bound_sp = sorted({r["species"] for r in rows if r["vc_bound"]})
    vss_fu = []
    for v in rep:
        if v["parameter"] == "Vss" and v.get("value_l_per_kg"):
            sources = [s for b in boards if b["species"] == v["species"] and b["study"] == v["study"]
                       for s in b["binding"].get("constant_fu_sources", []) if s["drug"] == v.get("drug") and v.get("route") == "IV" and v.get("condition") == s.get("condition")]
            distinct = {(s["dataset_id"], s["method"], tuple(s["fu_range"])) for s in sources}
            if len(distinct) == 1:
                dataset, method, (lo, hi) = distinct.pop()
                vss = v["value_l_per_kg"]
                vss_fu.append({"species": v["species"], "study": v["study"], "vss": vss, "fu_range": [lo, hi],
                               "vss_over_fu_range": [vss / hi, vss / lo], "vss_over_fu": vss / lo if lo == hi else None,
                               "binding_dataset": dataset, "volume_dataset": v["dataset_id"], "method": method})
    status = ST_PART if (len(bound_sp) >= 2 or comparable) else ST_NO
    missing = {}
    for sp in sorted({b["species"] for b in boards}):
        m = []
        if not any(r["species"] == sp and r["vc_bound"] for r in rows):
            m.append("an upper bound on the central volume (no usable first sample after the input)")
        if not any(r["species"] == sp and r["fu"] for r in rows):
            m.append("plasma unbound fraction (fu,p)")
        if not any(v["species"] == sp and v["parameter"] == "Vss" and (v.get("value_l_per_kg") or 0) > 0 for v in rep):
            m.append("Vss reported by the source authors")
        if not any((x.get("reference_volumes") or {}).get("plasma") or (x.get("reference_volumes") or {}).get("plasma_lower")
                   for b in boards if b["species"] == sp for x in b.get("item25", [])):
            m.append(f"reference plasma volume for {sp.lower()}")
        missing[sp] = m
    return {"species_rows": rows, "reported_volumes": rep, "comparable_definitions": comparable, "species_with_bound": bound_sp,
            "vss_fu_rows": vss_fu, "status": status, "missing_by_species": missing, "model_derived_rows": [],
            "transferred_hypotheses": []}


def _absorption_figures(root):
    """Figures absorption has already drawn in this run: whole profiles by series and IV-against-EV comparisons by dataset pair.
    Distribution links them and does not draw them again."""
    path = Path(root) / "absorption" / "absorption.json"
    if not path.is_file():
        return {}, []
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except ValueError:
        return {}, []
    there = lambda f: isinstance(f, str) and Path(f).name == f and (path.parent / f).is_file()
    profiles = {}
    for d in data.get("datasets", []):
        ds = (d.get("card") or {}).get("dataset_id")
        for x in d.get("series") or []:
            got = {k: x[k] for k in ("B1", "A1w") if there(x.get(k))}
            if ds and "B1" in got:
                profiles[f"{ds}:{x.get('series_id')}"] = got
    pairs = [e for e in data.get("ev_iv", []) if there(e.get("D1"))]
    return profiles, pairs


def _absorption_dose_evidence(root, series, absorption_run):
    """Read dose results for the same source snapshot, route, profiles and doses."""
    source = Path(absorption_run) if absorption_run else root
    path = source / "absorption" / "absorption.json"
    if not path.is_file():
        if absorption_run:
            raise FileNotFoundError(path)
        return []
    linked = source.resolve() == root.resolve()
    if not linked and (source / "source_tables.json").read_bytes() != (root / "source_tables.json").read_bytes():
        raise ValueError("Absorption and distribution use different source tables")
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    by_id = {s["sid"]: s for s in series if s["matrix_class"] in REF_CLASSES and s["analyte"] == "PARENT"
             and not s["unbound"] and s["occasion"] == "FIRST_DOSE"}
    cards = {x["card"]["dataset_id"]: x["card"] for x in data.get("datasets", []) + data.get("iv_references", []) if x.get("card")}
    results = []
    for d in data.get("dose_series", []):
        rows = d.get("rows") or []
        ids = [f"{r.get('dataset_id')}:{r.get('series_id')}" for r in rows]
        if len(set(ids)) != len(ids) or len(ids) < 2 or any(sid not in by_id for sid in ids):
            continue
        ss = [by_id[sid] for sid in ids]
        if any(s["dose"] != _num(r.get("dose")) or cards.get(s["dataset_id"], {}).get("route_class") != s["route_class"] for s, r in zip(ss, rows)):
            continue
        if len({(s["study"], s["species"], s["route_class"], s["route_detail"], s["matrix_class"], s.get("condition")) for s in ss}) != 1:
            continue
        route = ss[0]["route_class"]
        win = d.get("observed_window") or {}
        panel = d.get("C1") or d.get("C2")
        figure = "../absorption/" + panel if linked and isinstance(panel, str) and Path(panel).name == panel and (path.parent / panel).is_file() else None
        results.append({"study": ss[0]["study"], "species": ss[0]["species"], "route": route, "series": ids, "doses": [s["dose"] for s in ss],
                        "datasets": [s["dataset_id"] for s in ss], "source_status": d.get("status"),
                        "caveats": list(map(str, (d.get("t3_flags") or []) + (d.get("unverified_comparison_fields") or [])))
                                   + (["dose basis varies as reported"] if len({s["dose_basis"] for s in ss}) > 1 else []), "key": d.get("key") or ", ".join(ids), "version": data.get("version"),
                        "window": (f"{_f(win.get('start_h'))} to {_f(win.get('end_h'))}" if win else
                                   f"0 to {_f(d['window_end_h'])}" if isinstance(d.get("window_end_h"), (int, float)) else "not reported"),
                        "auc_ratio": d.get("R_window"), "auc_last_ratio": d.get("R_own_tlast"), "cmax_d_ratio": d.get("cmax_d_ratio"),
                        "route_name": _route_name(ss[0]),
                        "per_dose": [{"dose": _num(r.get("dose")), "thalf": r.get("thalf"), "tmax": r.get("tmax"), "cmax_d": r.get("cmax_d")} for r in rows],
                        "t3": d.get("t3_label") or "CANNOT_ASSESS", "t3p": (d.get("t3p") or {}).get("t3p_label") or "CANNOT_ASSESS",
                        "figure": figure, "interpretation": "EV evidence includes input and disposition." if route == "EV" else "IV evidence concerns systemic disposition over the tested doses."})
    return results




def build(root, absorption_run=None):
    root = Path(root)
    tables = _sorted_tables(root)
    cfg = load_config(root)
    parameter_context = load_parameter_context(root)
    tissue_parameters = []
    out = root / "distribution"
    out.mkdir(exist_ok=True)
    _SPECS.clear()
    manifest = out / "plot_specs.json"
    previous_files = set()
    if manifest.is_file():
        previous = json.loads(manifest.read_text(encoding="utf-8"))
        previous_files = {row["file"] for row in previous.get("figures", []) if re.fullmatch(r"DIS[\w.-]+\.png", row.get("file", ""))}
    previous_species = set()
    last_result = out / "distribution.json"
    if last_result.is_file():
        old = json.loads(last_result.read_text(encoding="utf-8"))
        previous_species = {page_name(sp) for sp in old.get("species_table", {}).get("missing_by_species", {})}
    (out / "distribution_config.template.json").write_text(json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=1), encoding="utf-8")
    series, cards, binding, reported, skipped = [], [], [], [], []
    for e in tables:
        evidence = (cfg.get("evidence_by_dataset") or {}).get(e["dataset_id"]) or {}
        if evidence.get("source") and isinstance(evidence.get("metadata"), dict):
            # Fill gaps only; the original source metadata and the cited override are retained in the audit output.
            e = dict(e, metadata={**evidence["metadata"], **e.get("metadata", {})})
        role = e.get("role")
        if role == "PK_OBSERVATIONS":
            base, ss = extract(e, cfg)
            cards.append(base)
            if base["route_class"] not in ("IV", "EV"):
                skipped.append({"dataset_id": e["dataset_id"], "reason": "ROUTE_UNKNOWN: values are background only"})
                continue
            if not ss:
                skipped.append({"dataset_id": e["dataset_id"], "reason": "no concentration series could be read"})
            series += ss
        elif role == "BINDING":
            binding += binding_records(e)
        elif role == "REPORTED_PARAMETERS":
            reviewed = reviewed_parameters(e, parameter_context)
            tissue_parameters.extend(r for r in reviewed if r["param"] == "THALF" and r["matrix"] in ("tissue fluid", "interstitial fluid"))
            reported += reported_volumes(e)
    refs = [s for s in series if s["matrix_class"] in REF_CLASSES and s["analyte"] in ("PARENT", "TOTAL_RADIOACTIVITY", "ACTIVE_MATERIAL") and not s["unbound"]]
    tissues = [s for s in series if s["matrix_class"] in TISSUE_CLASSES and s["analyte"] != "TARGET_OR_COMPLEX"]
    # item 24, per IV reference series (first dose)
    item24 = {}
    for s in refs:
        if s["route_class"] == "IV" and s["occasion"] == "FIRST_DOSE":
            r = item24_profile(s, cfg, prior_unwashed(s, series), prior_unwashed_routes(s, series))
            r["candidates"] = item24_candidates(r, s["target_binding"])
            item24[s["sid"]] = r
    # Reuse prior item 19 results for the identical IV series. EV results remain route-labelled context.
    q8 = _absorption_dose_evidence(root, refs, absorption_run)
    assessed_iv = {frozenset(item["series"]) for item in q8 if item["route"] == "IV"}
    groups = {}
    for s in refs:
        if s["sid"] in item24 and s["dose"] and not _baseline(s)[0] and not s.get("source_conflicts") and s["analyte"] == "PARENT":
            groups.setdefault((s["study"], s["species"], s["matrix_class"], s["level"], s["design"], s["iv_mode"], s["analyte"], s["drug"], s["dose_basis"], COMMON.input_nominal(s), s.get("condition")), []).append(s)
    dose_res = []
    for k, ms in groups.items():
        doses = {}
        for m in ms:
            doses.setdefault(m["dose"], m)
        if len(doses) >= 2 and len(doses) == len(ms) and frozenset(m["sid"] for m in ms) not in assessed_iv:
            d = dose_pattern(list(doses.values()), ms[0]["target_binding"])
            d["key"] = _slug(f"{k[0]}-{k[1]}-{k[2]}")
            d["study"], d["species"] = k[0], k[1]
            dose_res.append(d)
    # item 25
    item25 = {s["sid"]: item25_bound(s, item24.get(s["sid"]), cfg) for s in refs if s["sid"] in item24}
    # item 26
    pairs, d3 = [], []
    for t in tissues:
        if t["route_class"] not in ("IV", "EV"):
            continue
        r, why = find_reference(t, refs)
        pairs.append(item26_pair(t, r, why, None, cfg, item24) | {"study": t["study"], "species": t["species"], "_t": t, "_r": r})
    ratio_tests = prespecified_ratio_tests(series, cfg)
    def strength(pair):
        values = sorted(x["ratio"] for x in pair["rows"] if x.get("ratio") is not None)
        return values[len(values) // 2] if values else -1
    pairs.sort(key=strength, reverse=True)
    _unique_tissue_labels(pairs)
    by_tab = {}
    for t in tissues:
        by_tab.setdefault((t["dataset_id"], _group_prefix(t)), []).append(t)
    for (dsid, grp), ss in by_tab.items():
        d = d3_check(ss, ss[0]["dose"], cfg)
        d.update(dataset_id=dsid, group=grp, study=ss[0]["study"], species=ss[0]["species"])
        d3.append(d)
    rep_dose = repeat_dose(refs + tissues)
    conds = conditions(refs)
    # study boards (study x species)
    inventory = {(s["study"], s["species"]) for s in series} | {(v["study"], v["species"]) for v in reported + binding if v["study"] and v["species"]}
    inventory_sources = {}
    for e in tables:
        if e.get("role") not in ("PK_OBSERVATIONS", "BINDING", "REPORTED_PARAMETERS"):
            continue
        st = ",".join(e.get("study_source_ids") or [])
        if not st:
            continue
        source_species = str(e.get("metadata", {}).get("species") or "")
        remaining = source_species
        for sp, pattern in _SP_HEAD:
            if re.search(pattern, remaining, re.I):
                inventory.add((st, sp))
                inventory_sources.setdefault((st, sp), []).append({"dataset_id": e["dataset_id"], "role": e.get("role"), "title": e.get("title"),
                    "route_class": e.get("metadata", {}).get("route_class"),
                    "route_detail": e.get("metadata", {}).get("route_detail"), "route_source": e.get("metadata", {}).get("route"),
                    "dose": _dose(e)[0],
                    "study_display_name": e.get("metadata", {}).get("study_display_name") or e.get("study_display_name")})
                remaining = re.sub(pattern, " ", remaining, flags=re.I)
    keys = sorted(inventory)
    boards = []
    for st, sp in keys:
        bs = [s for s in series if s["study"] == st and s["species"] == sp]
        ivr = [s for s in bs if s["sid"] in item24]
        b = {"key": _slug(f"{st}-{sp}"), "study": st, "species": sp, "species_text": sorted({s["species_text"] for s in bs}) or [sp],
             "q8_evidence": [item for item in q8 if item["study"] == st and item["species"] == sp],
             "source_series": bs, "inventory_sources": inventory_sources.get((st, sp), []),
             "reported_parameters": [v for v in reported if v["study"] == st and v["species"] == sp],
             "reported_tissue_half_lives": [v for v in tissue_parameters if v["study"] == st and v["species"] == sp],
             "datasets": sorted({s["dataset_id"] for s in bs} | {v["dataset_id"] for v in inventory_sources.get((st, sp), [])} | {v["dataset_id"] for v in reported + binding if v["study"] == st and v["species"] == sp}), "iv_refs": ivr,
             "ev_refs": [s for s in refs if s["study"] == st and s["species"] == sp and s["route_class"] == "EV"],
             "tissues": [p["_t"] for p in pairs if p["study"] == st and p["species"] == sp], "item24": [item24[s["sid"]] for s in ivr],
             "item25": [item25[s["sid"]] for s in ivr], "dose_patterns": [d for d in dose_res if d["study"] == st and d["species"] == sp],
             "tissue_pairs": [p for p in pairs if p["study"] == st and p["species"] == sp], "d3": [d for d in d3 if d["study"] == st and d["species"] == sp],
             "prespecified_ratio_tests": [x for x in ratio_tests if x.get("study") == st and str(x.get("species","")).lower() == sp.lower()],
             "repeat": [x for x in rep_dose if x["first_sid"] in {s["sid"] for s in bs}],
             "binding": item27(st, sp, binding, [s for s in bs if s["matrix_class"] in REF_CLASSES]),
             "conditions": [c for c in conds if c["species"] == sp and {c["a"], c["b"]}.intersection(s["sid"] for s in bs)],
             "target_binding": "YES" if any(s["target_binding"] == "YES" for s in bs) else "NOT_STATED", "figs": {}}
        _site_unbound(b["binding"], b["tissues"], [s for s in bs if s["matrix_class"] == "PLASMA"])
        # r1.5 section 2.6: EV profiles are read as post-peak descriptions; section 2.1 animal x occasion; section 2.7 APOD ordering
        b["item24_ev"] = [item24_ev(s, cfg, *_iv_reference_for(s, ivr, item24)[:1], prior_unwashed(s, series),
                                    iv_reason=_iv_reference_for(s, ivr, item24)[1])
                          for s in b["ev_refs"] if s["analyte"] == "PARENT" and not s["unbound"]]
        b["animal_occasions"] = animal_occasions(b)
        b["apod_ordering"] = apod_ordering(b)
        b["optional_figures"] = {k: bool(v) for k, v in (cfg.get("optional_figures") or {}).items() if not k.startswith("_")}
        for x in b["item25"]:
            x["reported"] = [v for v in reported if v["study"] == st and v["species"] == sp and v.get("value_l_per_kg")]
        b["vc_summary"] = vc_summary([x for x in b["item25"] if x.get("vc_upper_bound_l_per_kg")])
        boards.append(b)
    for b in boards:
        # an EV-only study is read against the IV study of the same species, when the project has one
        b["species_iv"] = [{"study": o["study"], "key": o["key"], "n": len(o["iv_refs"]), "doses": sorted({s["dose"] for s in o["iv_refs"] if s.get("dose")}),
                            "level": _lvl_page(o["iv_refs"]), "readable": any(r.get("curvature") not in (None, "NOT_ASSESSABLE") for r in o["item24"]),
                            "bound": bool(o["vc_summary"])}
                           for o in boards if o["species"] == b["species"] and o["key"] != b["key"] and o["iv_refs"]]
        b["animal_spread"] = animal_spread(b["iv_refs"])
    sp_table = species_table(boards, reported)
    figures(boards, out, sp_table, conds, series, binding)
    for b in boards:
        b["questions"] = board_questions(b)
        b["questions"].append(_q7_row(b, sp_table))
        b["questions"].sort(key=lambda q: COMMON.guide_order("distribution", q))
        for question in b["questions"]:
            question["scope"] = "project" if question["q"] == 7 else "study"
            if question["q"] in (3, 4):
                question["supports_question"] = 1
        b["hypothesis"] = board_hypothesis(b)
        pl = COMMON.plain_distribution(b, sp_table.get("species_with_bound") or ())  # shared rule 10
        for question in b["questions"]:
            question["plain"] = pl.get(question["q"])
        if b["hypothesis"] and pl.get("H"):
            b["hypothesis"]["plain"] = pl["H"]
        b["plain_check"] = COMMON.plain_gate("distribution", b)   # translation gate; problems are listed on the main page
    result = {"version": VERSION, "rules": RULES, "rules_r15": RULES_R15, "settings": {"tolerance_rel": TOL, "noise_gate_sigmas": NOISE_GATE_SIGMAS, "early_spread_fold": EARLY_SPREAD_FOLD, "sigma_individual": SIGMA_IND, "sigma_group_default": SIGMA_GROUP_DEFAULT,
                                               "split_R": SPLIT_R, "split_z": SPLIT_Z, "band": BAND, "band_digitized": BAND_DIGITIZED,
                                               "kpuu_band": KPUU_BAND, "z_crit_rule": "t(0.977), Welch-Satterthwaite df; 2 for individual data"},
              "config_used": {k: v for k, v in cfg.items() if not k.startswith("_about")}, "reading_map": READING_MAP,
              "skipped": skipped, "series": [_series_json(s) for s in series], "boards": [_board_json(b) for b in boards], "species_table": sp_table,
              "conditions": [{k: v for k, v in c.items()} for c in conds], "binding_records": binding, "reported_volumes": reported,
              "repeat_dosing": rep_dose, "reported_tissue_half_lives": tissue_parameters}
    result["prespecified_ratio_tests"] = ratio_tests
    current_files = {figure["file"] for figure in _SPECS}
    render_all(out)
    write_tissue_parameter_supplement(out, tissue_parameters)
    result["render"] = dict(_RENDER)
    pages = render_pages(result, boards, series, sp_table, conds, out)
    if ratio_tests:
        block = '<section class="panel" id="prespecified-ratio-tests"><h2>Prespecified organ ratio changes</h2><p>Only organs and times supplied in the analysis configuration are tested. All requested comparisons share Bonferroni correction; missing or ineligible measurements are listed explicitly.</p>' + ab._evidence_html([_ratio_test_evidence(ratio_tests)]) + '</section>'
        pages["index.html"] = pages["index.html"].replace("<footer>", block + "<footer>", 1)
    _eda_common().annotate_section("distribution", result, Path(root))
    _eda_common().separate_sensitivity_flags(result)   # R10: formal CANNOT_ASSESS keeps only its own reason
    (out / "distribution.json").write_text(json.dumps(result, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    for name, text in pages.items():
        (out / name).write_text(COMMON.reader_text(text), encoding="utf-8")
    (out / "model_context.txt").write_text(model_context(result, boards), encoding="utf-8")  # compact context for a downstream model
    for name in (previous_files - current_files) | (previous_species - set(pages)):
        if Path(name).name == name:
            (out / name).unlink(missing_ok=True)
    result["_boards"] = boards
    return result


MC_STATUS = {"ANSWERABLE": "Y", "PARTLY_ANSWERABLE": "P", "NOT_ANSWERABLE_YET": "N", "NOT_APPLICABLE": "-"}


def _mc_board(b):
    """One study and species: what was dosed and measured, the seven statuses, the hypothesis parts, the model steps, what is missing."""
    h = b["hypothesis"]
    ss = b["iv_refs"] + b["ev_refs"] + b["tissues"]
    arms = {}
    for s in ss:
        if s["route_class"] == "IV":
            route = "IV (" + {"BOLUS": "bolus", "INFUSION": f"infusion {_dur(s.get('infusion_h'))}" if s.get("infusion_h") else "infusion",
                              "INFUSION_TIMING_UNKNOWN": "infusion, end not reported", "IV_MODE_UNKNOWN": "mode not reported", "ONGOING_INPUT": "loading dose plus ongoing infusion"}.get(s["iv_mode"], str(s["iv_mode"]).lower()) + ")"
        else:
            route = _route_name(s)
        arms.setdefault((route, s.get("dose")), []).append(s)
    by_route = {}
    for (route, dose), xs in arms.items():
        only = "" if any(s["matrix_class"] in REF_CLASSES for s in xs) else f" ({', '.join(sorted({s['organ'] for s in xs}))} only, no plasma)"
        by_route.setdefault((route, only), []).append(dose)
    dosed = "; ".join(f"{r} {', '.join(_f(d) for d in sorted(x for x in ds if x)) + ' mg/kg' if any(ds) else 'dose not reported'}{only}" for (r, only), ds in by_route.items())
    kinds = []
    for label, xs in (("IV", b["iv_refs"]), ("EV", b["ev_refs"])):
        if xs:
            kinds.append(f"{len(xs)} {label} {'profile' if len(xs) == 1 else 'profiles'} ({_lvl_page(xs)})")
    if b["tissues"]:
        kinds.append(f"{len(b['tissues'])} tissue or site series ({', '.join(sorted({s['organ'] for s in b['tissues']})[:6])})")
    drugs = "/".join(sorted({str(s["drug"]) for s in ss if s.get("drug") and s["drug"] != "NOT_FOUND"}))
    out = [" | ".join(x for x in (b["study"], b["species"], (drugs + " " + dosed).strip() if ss else "no concentration profile",
                                  "; ".join(kinds), ", ".join(b["datasets"])) if x),
           "questions: " + ", ".join(f"{_qref(q)} {MC_STATUS.get(q['status_code'], '?')}" for q in b["questions"])]
    out += ab._mc_plain(b, _qref)  # shared rule 10
    out += ["  input regimen: " + "; ".join(sorted({_regimen_words(s) for s in ss if _regimen_words(s)}))] if any(_regimen_words(s) for s in ss) else []
    out += ["  measured basis: " + "; ".join(sorted({str(s["analyte"]) + " / " + str(s.get("assay") or "assay not stated") for s in ss}))]
    for pair in b["tissue_pairs"][:3]:
        vals = [x["ratio"] for x in pair["rows"] if x.get("ratio") is not None]
        if vals:
            out.append(f"  observed {pair['tissue']}/{pair['ref_label']}: {_f(min(vals))}–{_f(max(vals))} {pair['ratio_unit']}; ratios of means unless individual pairing documented")
    out += [f"  {x['label'].lower()}: {say_codes(x['text'])}" for x in h.get("lines") or []]
    out += [f"  {step}: {model}" + ("" if show in ("", "—") else f" | must show: {show}") for step, model, show in h.get("ladder") or []]
    if h["missing"]:
        out.append("  missing: " + "; ".join(h["missing"]))
    if h["check_first"]:
        out.append("  check first: " + "; ".join(h["check_first"]))
    return "\n".join(out)


def model_context(result, boards):
    """Compact text for a downstream model: thresholds once at the top, one block per species, one entry per study in it."""
    st = result["settings"]
    head = [f"DISTRIBUTION CONTEXT · EDA {result['version']}",
            "Question status Y answerable, P partly, N not yet, - not applicable. Numbers are the review guide's; rows the guide does not number go by name. "
            + "; ".join((f"{_ref(q)} " if _ref(q).startswith("Q") else f"{_ref(q)}: ") + QD[q][0][0].lower() + QD[q][0][1:]
                        for q in sorted(QD, key=lambda q: COMMON.guide_order("distribution", q))) + ".",
            f"No PK model was fitted; any slope or named test shown is a descriptive regression. Reading tolerance ±{st['tolerance_rel']:.0%} per point; noise setting {st['noise_gate_sigmas']:g} σ "
            f"(σ on ln C {st['sigma_individual']:g} for individual data, {st['sigma_group_default']:g} for group means without SD). "
            "A parent Vc bound requires parent-specific total concentrations and completed IV input. Active-material assays and ongoing input do not supply a parent Vc bound.",
            "A hypothesis is a suspicion for a model to evaluate; observations do not establish a mechanism. The input side is in absorption/model_context.txt; "
            "full detail in distribution/distribution.json."]
    blocks = []
    for sp in sorted({b["species"] for b in boards}):
        bs = [b for b in boards if b["species"] == sp]
        iv = [b for b in bs if any(r.get("curvature") not in (None, "NOT_ASSESSABLE") for r in b["item24"])]
        weak = [b for b in bs if b["iv_refs"] and b not in iv]
        fu = [b for b in bs if any(x["study"] == b["study"] for x in b["binding"]["fu_table"])]
        facts = [("IV disposition from " + ", ".join(f"{b['study']} ({len(b['iv_refs'])} {'profile' if len(b['iv_refs']) == 1 else 'profiles'}, {_lvl_page(b['iv_refs'])})" for b in iv))
                 if iv else "no eligible parent post-input decline in this project; observed profiles retain their assay and input-design limits"]
        if weak:
            facts.append("IV decline not eligible or too sparse in " + ", ".join(b["study"] for b in weak))
        vb = [b for b in bs if b.get("vc_summary")]
        facts.append("Vc bound from " + ", ".join(b["study"] for b in vb) if vb else "no Vc bound")
        ts = [b for b in bs if b["tissues"]]
        facts.append("tissue or site data in " + ", ".join(b["study"] for b in ts) if ts else "no tissue data")
        facts.append("fraction unbound measured in " + ", ".join(b["study"] for b in fu) if fu else "no fraction unbound")
        blocks.append(f"== {sp} ==\n" + "; ".join(facts) + ".\n\n" + "\n\n".join(_mc_board(b) for b in bs))
    r15 = []
    for b in boards:
        o = b.get("apod_ordering") or {}
        if o.get("order") or o.get("removed"):
            r15.append(f"[{b['study']} / {b['species']}] " + _handoff_order_line(o)
                       + (" Basis: " + "; ".join(o.get("basis") or []) + "." if o.get("basis") else ""))
        c = o.get("q1_conclusion") or {}
        if c.get("simplest_plausible_model"):
            r15.append(f"[{b['study']} / {b['species']}] Q1: simplest plausible model {c['simplest_plausible_model']}; motivated by "
                       + "; ".join(c.get("motivating_observations") or ["-"]) + (f". Main limitation: {c['main_limitation']}." if c.get("main_limitation") else "."))
        elif c.get("main_limitation"):
            r15.append(f"[{b['study']} / {b['species']}] Q1: no candidate order; {c['main_limitation']}.")
        vcs = [x["vc_upper_bound_l_per_kg"] for x in b.get("item25") or [] if x.get("vc_upper_bound_l_per_kg")]
        if vcs:
            r15.append(f"[{b['study']} / {b['species']}] upper limit on fitted Vc: {min(vcs):.3g}-{max(vcs):.3g} L/kg (D/C(t), each bound for its own unit).")
        ev = b.get("item24_ev") or []
        if ev:
            vb = [r["vc_over_f_upper_bound_l_per_kg"] for r in ev if r.get("vc_over_f_upper_bound_l_per_kg")]
            nref = sum(bool(r.get("iv_reference_window")) for r in ev)
            r15.append(f"[{b['study']} / {b['species']}] EV post-peak shape is a description only (absorption and distribution not separable); "
                       f"IV reference window passed to Absorption for {nref} of {len(ev)} EV profiles (flip-flop is assessed there)"
                       + (f"; Vc/F upper bound {min(vb):.3g}-{max(vb):.3g} L/kg" if vb else "") + ".")
        tiers = sorted({(r.get("noise") or {}).get("tier") for r in b["item24"] if r.get("noise")} - {None})
        if tiers:
            r15.append(f"[{b['study']} / {b['species']}] noise tier {', '.join(map(str, tiers))} (3 = DEFAULT, results that depend on it are SENSITIVITY_ONLY).")
    tail = ("\n\nR1.5 HAND-OFF\n" + "\n".join(r15)) if r15 else ""
    return "\n".join(head) + "\n\n" + "\n\n".join(blocks) + tail + "\n"


def _series_json(s):
    return {k: v for k, v in s.items() if k not in ("notes",)}


def _board_json(b):
    out = {}
    for k, v in b.items():
        if k in ("iv_refs", "ev_refs", "tissues", "source_series"):
            out[k] = [s["sid"] for s in v]
        elif k == "tissue_pairs":
            out[k] = [{kk: vv for kk, vv in p.items() if not kk.startswith("_")} for p in v]
        elif k == "figs":
            out[k] = {f"{a}|{c}": f for (a, c), f in v.items()}
        else:
            out[k] = v
    return out


def _q7_row(b, spt):
    rows = [r for r in spt["species_rows"] if r["species"] == b["species"]]
    obs = (f"Project level: {len(spt['species_with_bound'])} species with an initial-volume bound ({', '.join(spt['species_with_bound']) or 'none'})"
           + (f"; reported volumes comparable by definition across species: {', '.join(spt['comparable_definitions'])}" if spt["comparable_definitions"] else "") + ".")
    conds = b["conditions"]
    if conds:
        obs += " Within " + b["species"] + ": " + "; ".join(f"{c['a_label']} vs {c['b_label']}: the same shape after scaling (T5) is {say(c['t5_label'])} ({', '.join(say(x) for x in c['caveats']) or 'no confounder listed'})" for c in conds[:3]) + "."
    miss = [f"{sp}: {', '.join(m)}" for sp, m in spt["missing_by_species"].items() if m and sp == b["species"]]
    prim = _prim(b["figs"].get(("DIS6a", "board")), "DIS-2a", 7, "Condition overlay", _lvl_page(b["iv_refs"]))
    vct = [r for r in spt.get("vc_bound_table", []) if r["board"] == b["key"]]
    if not prim and vct:
        prim = _rowprim(7, VC_TABLE_HEAD, [r["cells"] for r in vct], "Upper bound on central volume (Vc) from the first post-infusion sample", "project comparison")
    if not prim and b["reported_parameters"]:
        head = ["Parameter", "Value", "Unit", "Source"]
        prim = _rowprim(7, head, [[p["label"], _f(p["value"]), p["unit"] or "—", p["dataset_id"]] for p in b["reported_parameters"][:5]],
                        "Reported parameters for this study", "source records")
    if not prim and rows:
        row = next((r for r in rows if r["board"] == b["key"]), None)
        if row:
            prim = _rowprim(7, ["Species", "Study", "IV phases", "Missing for comparison"],
                            [[row["species"], row["study"], row["phases"], ", ".join(spt["missing_by_species"].get(b["species"], [])) or "—"]],
                            "This study in the project comparison", "study inventory")
    views = [_view("DIS-2a", f, key, 1) for (kind, key), f in b["figs"].items() if kind == "DIS6a" and key != "board"]
    evidence = []
    if b["reported_parameters"]:
        evidence.append({"rule": "DIS-R: source-reported parameters retain their definitions, methods and study arms.",
                         "tables": [{"caption": "Reported parameters", "head": ["Parameter", "Value", "Unit", "SD", "n", "Method", "Record"],
                                     "rows": [[v["label"], _f(v["value"]), v["unit"] or "—", _f(v.get("sd")), _f(v.get("n")), v["method"], v["record_id"]] for v in b["reported_parameters"]]}],
                         "data": sorted({v["dataset_id"] for v in b["reported_parameters"]})})
    return _qrow(7, spt["status"], obs, "", "No allometric scaling or prediction in EDA.", miss, prim, views, evidence)


# ---------------------------------------------------------------- figures for every board

def figures(boards, out, spt, conds, series, binding):
    abs_profiles, abs_pairs = _absorption_figures(out.parent)
    for b in boards:
        F = b["figs"]
        if b.get("animal_occasions"):
            n = len(b["animal_occasions"])
            F[("DIS1animal", b["key"])] = _figure(f"DIS1animal_{_slug(b['key'])}.png", pDIS1animal(b), 2.6 * min(4, n), 2.4 * math.ceil(n / 4), ncol=min(4, n),
                                                 title="")
        if not b["iv_refs"]:
            for ev in b["ev_refs"]:
                pts = _q(ev["points"])
                if not pts or ev["analyte"] != "PARENT" or ev["unbound"]:
                    continue
                drawn = abs_profiles.get(ev["sid"])
                if drawn:                                  # absorption drew this profile: link it, do not draw it again
                    F[("EV parent", ev["sid"])] = "../absorption/" + drawn["B1"]
                    if drawn.get("A1w"):
                        F[("EV linear", ev["sid"])] = "../absorption/" + drawn["A1w"]
                    continue
                panels = []
                for log in (False, True):
                    p = Panel(_dstd(ev, "semi-log" if log else "linear"), TIME_AXIS, f"Concentration ({ev['unit']})", ylog=log)
                    p.points([x["t"] for x in pts], [x["c"] for x in pts], color=BLUE)
                    _blq(p, ev)
                    panels.append(p)
                F[("EV parent", ev["sid"])] = _figure("DIS1_ev_" + _slug(ev["sid"]) + ".png", panels, 10.5, 3.8)
        b["route_pairs"] = []
        evs, ivs = {s["dataset_id"] for s in b["ev_refs"]}, {s["dataset_id"] for s in b["iv_refs"]}
        b["absorption_route_pairs"] = [
            {"ev": e["ev"], "iv": e["iv"], "key": e.get("key") or f"{e['ev']}_vs_{e['iv']}", "file": "../absorption/" + e["D1"],
             "t4": e.get("t4_label") or "CANNOT_ASSESS", "numerical_only": "SENSITIVITY_ONLY" in (e.get("t4_flags") or []),
             "summary": (e.get("trigger_text") or "").replace("EV decline DECLINE_FLATTENS", "the EV decline flattens")
                        .replace("EV decline DECLINE_STEEPENS", "the EV decline steepens").replace("EV decline NEITHER", "the EV decline neither flattens nor steepens"),
             "dose_ev": e.get("dose_ev"), "dose_iv": e.get("dose_iv")}
            for e in abs_pairs if e.get("ev") in evs and e.get("iv") in ivs]
        for parent in b["iv_refs"]:
            others = [s for s in b["source_series"] if s["dataset_id"] == parent["dataset_id"] and s["matrix_class"] == parent["matrix_class"]
                      and s["dose"] == parent["dose"] and s["analyte"] in ("METABOLITE_OR_MIXED", "TARGET_OR_COMPLEX")
                      and (s["analyte"] != "TARGET_OR_COMPLEX" or parent["target_binding"] == "YES")]
            if parent["analyte"] == "PARENT" and others:
                panels = []
                for s in [parent] + others:
                    pts = _q(s["points"])
                    p = Panel(_dstd(s, "semi-log", what=f"{s.get('analyte_text') or 'analyte'} concentration"), TIME_AXIS,
                              f"Concentration ({s['unit']})", ylog=True)
                    _band(p, [s])
                    p.points([x["t"] for x in pts], [x["c"] for x in pts], color=BLUE)
                    panels.append(p)
                F[("Analytes", parent["sid"])] = _figure("DIS_analytes_" + _slug(parent["sid"]) + ".png", panels, 10.5, 3.8 * math.ceil(len(panels)/2), ncol=2)
        for iv, ev in itertools.product(b["iv_refs"], b["ev_refs"]):
            if (not iv["uf"] or not ev["uf"] or not iv["dose"] or iv["iv_mode"] not in ("BOLUS", "INFUSION") or ev["unbound"]
                    or iv["analyte"] != "PARENT" or any(iv.get(k) != ev.get(k) for k in
                       ("drug","dose","dose_basis","species","condition","matrix_class","analyte","level","occasion","occasion_day"))
                    or _baseline(iv)[0] or _baseline(ev)[0] or iv.get("source_conflicts") or ev.get("source_conflicts")):
                continue
            eq = _q(ev["points"])
            if len(eq) < 3:
                continue
            peak = max(eq, key=lambda x: x["c"])
            tail = [x for x in eq if x["t"] >= peak["t"]]
            shape = next(x for x in b["item24"] if x["sid"] == iv["sid"])
            early = shape.get("split", {}).get("early_times") or []
            mask = (shape.get("phases_visible") == "TWO_OR_MORE" and peak["t"] > eq[0]["t"] and len(tail) >= MIN_SPLIT_POINTS and early
                    and tail[0]["t"] <= early[-1] + (iv["infusion_h"] or 0) <= tail[-1]["t"]
                    and split_half(tail, sigma_for(ev, tail)[0])["curvature"] == "NONE_DETECTED")
            tag = _slug(ev["sid"] + "-vs-" + iv["sid"])
            original = out.parent / "absorption" / f"D1_{ev['dataset_id']}_vs_{iv['dataset_id']}.png"
            if original.is_file():
                file = "../absorption/" + original.name
            else:
                p = Panel(_dstd(iv, "semi-log", who=f"IV {iv.get('label')} and {ev.get('route_detail')} {ev.get('label')}"), TIME_AXIS,
                          "Concentration (mg/L)", ylog=True)
                p.set(subtitle=D_SUB["EVIV"])
                _band(p, [iv])
                for s, color in ((iv, BLUE), (ev, ORANGE)):
                    points = _q(s["points"])
                    p.points([x["t"] for x in points], [x["c"] * s["uf"] for x in points], color=color, label=s["route_detail"])
                file = _one("DIS_route_" + tag + ".png", p)
            F[("IV/EV", tag)] = file
            b["route_pairs"].append({"iv": iv["sid"], "ev": ev["sid"], "file": file, "masking_candidate": bool(mask)})
        for s, r in zip(b["iv_refs"], b["item24"]):
            if not _q(s["points"]):
                continue
            tag = _slug(s["sid"])
            linear, log, early = pDIS1a(s, r)
            F[("DIS1a", s["sid"])] = _figure(f"DIS1a_{tag}.png", [linear, log, pDIS1rate(s, r)], 15, 4)   # guide 1a, 1b, 1c
            if r.get("n_points", 0) >= MIN_SPLIT_POINTS:
                F[("Early", s["sid"])] = _one(f"DIS1early_{tag}.png", early)
            # S13 rule 9 (George 2026-11-25): no single-exponential check figure; its reading is in the semi-log caption
        animals = {}
        for s in b["iv_refs"]:
            if s.get("animal"):
                animals.setdefault(s["dataset_id"], []).append(s)
        for dsid, ss in animals.items():
            if len(ss) > 1 and len({(s["unit"], s["dose"], s["matrix_class"], s["analyte"], s["iv_mode"], COMMON.input_nominal(s)) for s in ss}) == 1:
                F[("DIS1ind", dsid)] = _figure(f"DIS1ind_{_slug(dsid)}.png", pDIS1ind(ss, b["item24"]), 10, 4)
        # George 2026-11-25: the board figure "Table 2 support · sensitivity to sampling" is dropped; the deletion checks stay a
        # table (Q4 evidence) and numbers in distribution.json
        for d in b["dose_patterns"]:
            ms = [s for s in b["iv_refs"] if s["sid"] in d["series"]]
            if d["rows"]:
                F[("DIS2", d["key"])] = _figure(f"DIS2_{d['key']}.png", pDIS2(d, ms), 14, 3.8)
        okb = [x for x in b["item25"] if x.get("vc_upper_bound_l_per_kg")]
        if okb and b.get("optional_figures", {}).get("DIS3"):
            F[("DIS3", "board")] = _one(f"DIS3_{b['key']}.png", pDIS3(okb[:12], summary=b.get("vc_summary")), max(5.6, 1.0 + 0.9 * min(len(okb), 12)), 4.0)
        by_tab = {}
        for t in b["tissues"]:
            by_tab.setdefault((t["dataset_id"], _group_prefix(t)), []).append(t)
        for (dsid, grp), ts in by_tab.items():
            ref = next((p["_r"] for p in b["tissue_pairs"] if p["_t"] in ts and p.get("_r")), None)
            title = _dstd(None, "semi-log", what="tissue and reference concentrations", group=ts, who=grp or None)
            # small multiples of 7 tissues (+ the reference) so colours never repeat within a panel
            units = {}
            for s in ([ref] if ref else []) + ts:
                units.setdefault(s["unit"], []).append(s)
            panels = []
            for unit, group in units.items():
                ref_in_unit = ref if ref and ref["unit"] == unit else None
                tissue_group = [s for s in group if s is not ref_in_unit]
                chunks = [tissue_group[i:i + 7] for i in range(0, len(tissue_group), 7)] or [[]]
                for chunk in chunks:
                    panel = pDIS4a(ref_in_unit, chunk, title)
                    panel.d["ylab"] = f"Concentration ({unit})"
                    panels.append(panel)
            if len(panels) == 1:
                F[("DIS4a", f"{dsid}{grp}")] = _one(f"DIS4a_{_slug(dsid + grp)}.png", panels[0], 7.0, 4.4)
            else:
                nc = 2
                F[("DIS4a", f"{dsid}{grp}")] = _figure(f"DIS4a_{_slug(dsid + grp)}.png", panels, 12.0, 4.4 * math.ceil(len(panels) / nc), ncol=nc)
        for p in b["tissue_pairs"]:
            if p.get("_r") and [x for x in p["rows"] if x["ratio"]]:
                F[("DIS4b", p["tissue_sid"])] = _one(f"DIS4b_{_slug(p['tissue_sid'])}.png", pDIS4b(p, p["_t"], p["_r"]), 6.2, 4.0)
            if p.get("phase_loop"):
                F[("DIS4e", p["tissue_sid"])] = _one(f"DIS4e_{_slug(p['tissue_sid'])}.png", pDIS4e(p, p["_t"], p["_r"]), 6.0, 4.0)
        for d in b["repeat"]:
            rows = d.get("relative_rows") or []
            if rows:
                tag = _slug(d["first_sid"] + "-" + d["later_sid"])
                p = Panel(f"{d['matrix']}: tissue/reference accumulation ratio vs matched time after dosing", "Matched time after dosing (h)",
                          "Tissue / reference accumulation ratio")
                p.set(subtitle="Does the tissue accumulate more than the reference on repeated dosing?")
                p.hline(1, color=MUTED, lty="dashed")
                p.points([x["t"] for x in rows], [x["relative_accumulation"] for x in rows], color=BLUE)
                F[("DIS4c", tag)] = _one("DIS4c_" + tag + ".png", p)
        for site in b["binding"]["kpuu"]["sites"]:
            p = Panel(f"{site['site']}: unbound site/plasma ratio vs matched time after dosing", "Matched time after dosing (h)",
                      "Apparent unbound site / plasma ratio")
            p.set(subtitle="How does the unbound concentration at the site compare with plasma?")
            p.points([x["t"] for x in site["rows"]], [x["ratio"] for x in site["rows"]], color=BLUE)
            if site.get("auc_ratio") is not None:
                p.set(caption=f"Unbound AUC ratio over the observed window: {_f(site['auc_ratio'])} ({site['position'].lower()}).")
            panels = [p]
            if site.get("auc_ratio") is not None:
                band = Panel(f"{site['site']}: unbound AUC ratio, site/plasma, over the observed window", "", "Site / plasma", ylog=True)
                band.hline(KPUU_BAND[0], color=MUTED, lty="dashed")
                band.hline(KPUU_BAND[1], color=MUTED, lty="dashed")
                if site.get("interval"):
                    lo, hi = site["interval"]
                    band.segments([1], [lo], [1], [hi], color=BLUE)
                band.points([1], [site["auc_ratio"]], color=BLUE, label=site["position"])
                band.set(xbreaks=[1], xlabels=["observed window"])
                panels.append(band)
            F[("DIS5b", site["tissue_sid"])] = _figure("DIS5b_" + _slug(site["tissue_sid"]) + ".png", panels, 5.8*len(panels), 3.8)
        for d in b["d3"]:
            if d.get("rows"):
                F[("DIS4d", d["dataset_id"] + d["group"])] = _one(f"DIS4d_{_slug(d['dataset_id'] + d['group'])}.png", pDIS4d(d), 6.0, 3.8)
        bd = b["binding"]
        unbound_series = {}
        for point in bd["unbound_points"]:
            unbound_series.setdefault((point["sid"], point["basis"]), []).append(point)
        if any(len({x["t"] for x in pts}) >= 2 for pts in unbound_series.values()):
            p = Panel(f"{b['species']} — unbound plasma concentration vs time, linear", TIME_AXIS, "Unbound plasma concentration (mg/L)")
            for i, ((sid, basis), pts) in enumerate(unbound_series.items()):
                p.points([x["t"] for x in pts], [x["cu_mg_l"] for x in pts], color=CAT[i % len(CAT)], label=f"{sid} · {basis.lower()}")
            p.set(legend="top_right")
            F[("Unbound plasma", "board")] = _one("DIS5u_" + b["key"] + ".png", p, 6.7, 4)
        if bd["fu_concentration_dependence"] and not _ex_vivo_only(b):
            pk_range = bd.get("pk_range") if all(d["matrix"] == "PLASMA" and d["study"] == b["study"] for d in bd["fu_concentration_dependence"]) else None
            F[("DIS5a", "board")] = _one(f"DIS5a_{b['key']}.png", pDIS5a(bd["fu_concentration_dependence"], bd["fu_table"], pk_range), 6.4, 4.0)
        for idx, c in enumerate(pair for pair in b["conditions"] if pair["rows"]):
            a = next(s for s in series if s["sid"] == c["a"])
            bb = next(s for s in series if s["sid"] == c["b"])
            tag = "board" if idx == 0 else _slug(c["a"] + "-" + c["b"])
            name = "DIS6a_" + b["key"] + ("" if idx == 0 else "_" + tag) + ".png"
            F[("DIS6a", tag)] = _one(name, pDIS6a(c, a, bb), 6.6, 4.0)
    rows = [dict(x, board=b["key"], label=f"{b['species']} · {b['study']} · {x['label']}") for b in boards for x in b["item25"] if x.get("vc_upper_bound_l_per_kg")]
    spt["figures"] = []
    # George 2026-11-25: the Vc bounds are a table (species, study, profile, dose, sample time, C, D/C), not a figure
    spt["vc_bound_table"] = vc_bound_table(rows, boards)
    spt["figure"] = next(iter(spt["figures"]), None)
    if spt["vss_fu_rows"]:
        p = Panel("Reported Vss and Vss/fu by species and study", "Species and study", "Volume (L/kg)", ylog=True)
        p.set(subtitle=D_SUB["VSS"])
        for i, r in enumerate(spt["vss_fu_rows"], 1):
            p.points([i], [r["vss"]], color=BLUE, label="Vss")
            lo, hi = r["vss_over_fu_range"]
            p.segments([i], [lo], [i], [hi], color=ORANGE, label="Vss/fu range")
            p.points([i], [lo], color=ORANGE)
        p.set(xbreaks=list(range(1, len(spt["vss_fu_rows"])+1)), xlabels=[r["species"]+" · "+r["study"] for r in spt["vss_fu_rows"]])
        spt["figures"].append(_one("DIS6b_unbound_volume.png", p, 7.2, 4.2))


# ---------------------------------------------------------------- HTML pages

def _views_html(views):
    by = {}
    for v in views:
        by.setdefault(v["panel"], []).append(v)
    h = []
    for pid, vs in by.items():
        read = next((r for r in READING_MAP if pid.split(" ")[0] in r[0]), None)
        th = "".join(f'<a href="{_e(v["file"])}" target="_blank" rel="noopener"><img loading="lazy" src="{_e(v["file"])}" alt="{_e(pid + " · " + v["label"])}">'
                     f'<span>{_e(v["label"])}</span></a>' for v in vs)
        h.append(f'<div class="pgrp"><p><b>{_e(pid)}</b>' + (f' · look at: {_e(read[1])}' if read else "") + f'</p><div class="fthumbs">{th}</div></div>')
    return "".join(h)


def _in_words(x):
    """A copy of a primary row table or an evidence list with stored codes in reader wording."""
    if isinstance(x, str):
        return say_codes(x)
    if isinstance(x, list):
        return [_in_words(v) for v in x]
    if isinstance(x, dict):
        return {k: (v if k in ("file", "data", "panels", "kind") else _in_words(v)) for k, v in x.items()}
    return x


def _qrow_html(q, key, base, source_owners=None):
    st = q["status"]
    prim = ab._primary_html(_in_words(q["primary"]) if q.get("primary") else q["primary"])
    sub = say_codes(" ".join(x for x in (q["basis"], q["reach"]) if x))
    miss = ('<p class="miss"><b>Missing:</b> ' + "; ".join(_e(m) for m in q["missing"]) + '</p>') if q["missing"] else ""
    pr = q.get("primary") or {}
    ratio = ab._png_ratio(Path(base) / pr["file"]) if pr.get("kind") == "panel" and base is not None else None
    if ratio:
        prim = prim.replace("<img ", f'<img style="aspect-ratio:{ratio:.6f}" ', 1)
    wide = bool(ratio and ratio > 2.2)
    number = _qref(q)
    h = [f'<article class="qrow" id="step-{_e(key)}-{_e(_anchor(q))}"><span id="q-{_e(key)}-{q["q"]}" aria-hidden="true"></span><div class="qhead"><span class="qn">{_e(number)}</span><h3>{_e(q["label"])}</h3>'
         f'<span class="st {COMMON.ST_CLASS[st]}">{_e(st)}</span><p class="q">{_e(q["question"])}</p></div>'
         f'<div class="qbody{"" if prim and not wide else " noprim"}"><div class="qtext">'
         + (ab._plain_html(q["plain"], [say_codes(q["observed"]), sub]) if q.get("plain") else f'<p class="concl">{_e(say_codes(q["observed"]))}'
            + (f' <span class="sub">{_e(sub)}</span>' if sub else "") + '</p>') + f'{miss}</div>{prim}</div>']
    if q["q"] == 7:
        h.append('<p><a href="conditions-and-species.html">View the project-level conditions and species comparison →</a></p>')
    if q["views"] or q["evidence"]:
        t = {k: [v for v in q["views"] if v["tier"] == k] for k in (1, 2, 3)}
        bits = ([f"{len(q['views'])} more panel{'s' if len(q['views']) != 1 else ''}"] if q["views"] else []) + (["evidence"] if q["evidence"] else [])
        evidence = ab._evidence_html(_in_words(q["evidence"]))
        owners = source_owners or {}
        evidence = re.sub(r'href="#data-([^"]+)"',
                          lambda m: f'href="#data-{_e(owners.get(m[1], key))}-{m[1]}"', evidence)
        h.append(f'<details class="more"><summary>More for {_e(number)}: {" · ".join(bits)}</summary>' + _views_html(t[1])
                 + (f'<details class="tier"><summary>Tier 2 · tests ({len(t[2])})</summary>{_views_html(t[2])}</details>' if t[2] else "")
                 + (f'<details class="tier"><summary>Tier 3 · supplements ({len(t[3])})</summary>{_views_html(t[3])}</details>' if t[3] else "")
                 + evidence + '</details>')
    h.append('</article>')
    return "".join(h)


def _model_steps_html(h):
    rows = [r for r in h.get("ladder") or [] if len(r) >= 2]
    if not rows:
        return ""
    sug = ((h.get("plain") or {}).get("suggests") or "").lower()
    two = "two-compartment" in sug and "start with a one" not in sug
    pick = next((r for r in rows if two and re.search(r"two compartments|two-compartment|peripheral", str(r[1]), re.I)), None) or rows[0]
    base = rows[0] if pick is not rows[0] else None
    name = lambda r: re.sub(r"^M\d+\s*\+\s*", "", str(r[1])).strip().rstrip(".")  # noqa: E731
    txt = ("Recommended model: at least two compartments; start with two (central + one peripheral)." if two and pick is not rows[0]
           else f"Recommended model: {name(pick)[:1].lower() + name(pick)[1:]}.")
    if base:
        txt += f" The simpler model ({name(base)[:1].lower() + name(base)[1:]}) is fitted only as a baseline, to confirm that the recommended model fits better."
    if two and any(re.search(r"three compartments", str(r[1])) for r in rows):
        txt += " A three-compartment model is a candidate where the decline still bends after the early points; test it against two."
    return f'<p class="concl"><b>{_e(txt)}</b></p>'


def _hrow_html(b):
    h = b["hypothesis"]
    parts = '<dl class="hparts">' + "".join(f'<dt>{_e(x["label"])}</dt><dd>{_e(say_codes(x["text"]))}</dd>' for x in h.get("lines") or []) + '</dl>'
    if not h.get("lines"):
        parts = f'<p class="concl">{_e(say_codes(h["text"]))}</p>'
    if h.get("plain"):  # shared rule 10: plain sentences first, the detailed lines collapsed
        parts = ab._plain_html(h["plain"], [f'{x["label"]}: {say_codes(x["text"])}' for x in h.get("lines") or []] or [say_codes(h["text"])])
    lad = ""
    if h.get("ladder"):   # George 2026-11-25: lead with the recommended model; the simpler one is only the comparison baseline
        parts += _model_steps_html(h)
    miss = ('<p class="miss"><b>Missing:</b> ' + "; ".join(_e(m) for m in h["missing"]) + '</p>') if h["missing"] else ""
    chk = ('<p class="hstab warn"><b>Check first:</b> ' + "; ".join(_e(m) for m in h["check_first"]) + '</p>') if h["check_first"] else ""
    tb = ('<details class="nums"><summary>What this rests on</summary><p class="ev">' + _e(h["rests_on"]) + ("" if lad else " " + _e(h["reach"])) + ' Target binding: ' + (
        "declared by the source; target-mediated disposition is listed where the rules allow it."
        if h["target_binding"] == "YES" else "not stated by the source, so target-mediated disposition is not considered.") + '</p></details>')
    return (f'<article class="qrow hrow" id="h-{_e(b["key"])}"><div class="qhead"><span class="qn">H</span><h3>Working hypothesis</h3>'
            f'<span class="st st-hyp">Review pending</span><p class="q">Taken together, what should a model check next about distribution?</p></div>'
            f'<div class="qbody{"" if lad else " noprim"}"><div class="qtext">{parts}{miss}{chk}{tb}</div>{lad}</div></article>')


def _regimen_words(s):
    r = s.get("regimen") or {}
    bits = []
    if r.get("loading_dose_mg_kg") is not None:
        bits.append(f"loading {r['loading_dose_mg_kg']:g} mg/kg")
    if r.get("infusion_rate_mg_kg_h") is not None:
        bits.append(f"infusion {r['infusion_rate_mg_kg_h']:g} mg/kg/h")
    return "; ".join(bits)


def _observed_cell(row, prefix, unit):
    text = _f(row.get(prefix)) + " " + str(unit or "")
    if row.get(prefix + "_se") is not None:
        text += " ± " + _f(row[prefix + "_se"]) + " SE"
    elif row.get(prefix + "_sd") is not None:
        text += " ± " + _f(row[prefix + "_sd"]) + " SD"
    nn, nr = row.get(prefix + "_n"), row.get(prefix + "_n_range")
    text += "; n=" + (str(nn) if nn is not None else "–".join(str(x) for x in nr) + " (per-time n unresolved)" if nr else "not reported")
    return text


def _card_html(b):
    rows = []
    for s in b["source_series"]:
        gate = []
        if s["route_class"] == "IV" and s["iv_mode"] in ("INFUSION_TIMING_UNKNOWN", "IV_MODE_UNKNOWN"):
            gate.append("INFUSION_TIMING_UNKNOWN")
        gate += [f for f in s["flags"]]
        if s.get("local") and s["matrix_class"] in ("ELF", "TISSUE_HOMOGENATE", "CSF"):
            gate.append("LOCAL_ROUTE" if (s["local"] == "LUNG" and (s["matrix_class"] == "ELF" or (s["organ"] or "").lower() == "lung")) or (s["local"] == "CNS" and s["matrix_class"] == "CSF") else "")
        ns = sorted({p.get("n") for p in s["points"] if p.get("n")})
        npt = ", ".join(str(n) for n in ns) or ("–".join(str(n) for n in s.get("n_range", [])) + " (per-time n unresolved)" if s.get("n_range") else "") or ("1 (one animal per series)" if s["level"].startswith("INDIVIDUAL") and s.get("animal") else "not reported")
        rows.append([s.get("title") or "Concentration data", s["label"], s["matrix_class"].replace("_", " ").lower(),
                     _route_cell(s),
                     (COMMON.dose_text(s) if s["dose"] else (_regimen_words(s) or "dose not found")), _lvl_txt(s), npt,
                     s["unit"], "; ".join(say(g) for g in gate if g) or "—"])
    head = ["Measurements", "Series", "Matrix", "Route", "Dose", "Data", "n per time", "Unit", "Interpretation limits"]
    # series that differ only in their name (animals of one dataset) share one row
    merged = []
    for r in rows:
        key = r[:1] + r[2:]
        if merged and merged[-1]["key"] == key:
            merged[-1]["labels"].append(r[1])
        else:
            merged.append({"key": key, "labels": [r[1]], "row": r})
    rows = []
    for m in merged:
        r = list(m["row"])
        if len(m["labels"]) >= 3:
            r[1] = f"{m['labels'][0]} to {m['labels'][-1]} ({len(m['labels'])} series)"
            rows.append(r)
        else:
            rows += [[r[0], lab] + r[2:] for lab in m["labels"]]
    if len(rows) > 14:
        extra = len(rows) - 12
        rows = rows[:12] + [["…", f"{extra} more series (see source data points)", "", "", "", "", "", "", ""]]
    sources = []
    for s in b["source_series"]:
        for src in s.get("source_refs", []):
            if src.get("url"):
                link = '<a href="' + _e(src["url"]) + '" target="_blank" rel="noopener">' + _e(src.get("location") or s.get("source_item_id") or "Source") + '</a>'
                if link not in sources:
                    sources.append(link)
    source_html = '<p class="muted">Source: ' + '; '.join(sources) + '</p>' if sources else ''
    return (source_html + '<div class="tw"><table class="res evt card"><tr>'  + "".join(f"<th>{_e(x)}</th>" for x in head) + "</tr>"
            + "".join("<tr>" + "".join(f"<td>{_wb(v)}</td>" for v in r) + "</tr>" for r in rows) + "</table></div>")


def _gap_html(section, b):
    """M5 coverage stays internal (George 2026-11-25: the 'Guide questions without a row of their own' paragraph is not for readers).
    The coverage of each board is kept in the JSON (guide_coverage) and checked by the tests; the page shows nothing."""
    return ""


def _chips(b, page=""):
    chips = [f'<a class="qchip" href="{_e(page)}#step-{_e(b["key"])}-{_anchor(q)}" title="{_e(q["text"])}">'
             f'{_e(_qref(q))} {_e(q["label"])}<span class="st {COMMON.ST_CLASS[q["status"]]}">{_e(COMMON.ST_SHORT[q["status"]])}</span></a>'
             for q in b["questions"]]
    chips.append(f'<a class="qchip" href="{_e(page)}#h-{_e(b["key"])}">H Working hypothesis<span class="st st-hyp">Pending</span></a>')
    return "".join(chips)


def _points_html(b):
    h = []
    ids = set(b["datasets"]) | {r["dataset_id"] for r in b["binding"]["fu_table"] + _own_ex_vivo(b)}
    for dsid in sorted(ids):
        ss = [s for s in b["source_series"] if s["dataset_id"] == dsid]
        if not ss:
            rows = [r for r in b["binding"]["fu_table"] + _own_ex_vivo(b) + b["reported_parameters"] if r["dataset_id"] == dsid]
            if not rows:
                source = next((v for v in b["inventory_sources"] if v["dataset_id"] == dsid), {})
                h.append(f'<details class="pts" id="data-{_e(b["key"])}-{_e(dsid)}"><summary>{_e(dsid)} · Source inventory</summary>'
                         f'<p>{_e(source.get("title"))} · {_e(say(source.get("role")))}. No usable distribution series or parameter extracted for this study and species.</p></details>')
                continue
            h.append(f'<details class="pts" id="data-{_e(b["key"])}-{_e(dsid)}"><summary>{_e(dsid)} · Source records</summary><ul>'
                     + "".join(f'<li>{_e(r.get("record_id"))} · {_e(r.get("label") or r.get("method"))} · '
                               f'{_e(r.get("reported") or str(r.get("value")) + " " + str(r.get("unit")))}</li>' for r in rows) + '</ul></details>')
            continue
        s0 = ss[0]
        facts = [("Source", s0["title"]), ("Study", s0["study"]), ("Species as written", s0["species_text"]), ("Route", _route_cell(s0)),
                 ("IV mode", ("not reported" if s0["iv_mode"] == "IV_MODE_UNKNOWN" else f"{say(s0['iv_mode'])} ({say(s0['iv_mode_source'])})") if s0["route_class"] == "IV" else None), ("Dose", COMMON.dose_range_text(ss) if s0["dose"] else "not found"),
                 ("Dose basis", say(s0["dose_basis"])), ("Matrix as written", s0["matrix_text"]), ("Design", say(s0["design"])), ("Perfused", say(s0["perfused"])),
                 ("Target binding", say(s0["target_binding"]))]
        h.append(f'<details class="pts" id="data-{_e(b["key"])}-{_e(dsid)}"><summary>{_e(dsid)} · {_e(s0["title"])}</summary><dl class="facts">'
                 + "".join(f"<dt>{_e(k)}</dt><dd>{_e(v)}</dd>" for k, v in facts if v not in (None, "")) + '</dl>')
        for s in ss[:16]:
            h.append('<div class="tw"><table class="res evt"><caption>' + _e(s["label"]) + f' · {_e(s["unit"])}</caption><tr><th>Time (h)</th><th>Value</th>'
                     '<th>Status</th><th>SD</th><th>n</th><th>Record</th></tr>' + "".join(
                         f'<tr><td>{_f(p["t"], 4)}</td><td>{_f(p["c"] if p["c"] is not None else p.get("lim"), 4)}</td><td>{_e(say(p["status"]))}</td><td>{_f(p.get("sd"))}</td>'
                         f'<td>{_e(p.get("n") or "—")}</td><td>{_e(p.get("record_id") or "—")}</td></tr>' for p in s["points"]) + '</table></div>')
        if s0["notes"]:
            h.append(f'<p class="ev notes">{_e(s0["notes"][:1500])}</p>')
        h.append('</details>')
    return ('<section class="panel" id="points-' + _e(b["key"]) + '"><h2>Source data points</h2>' + "".join(h) + '</section>') if h else ""


def _shell(title, body):
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{_e(title)} · EDA review</title><style>' + ab._portal_css() + ab.ABS_CSS + ab.HYP_CSS + DIS_CSS + '</style></head><body><main id="main">'
            + body + '</main>' + ab._HASH_JS + '</body></html>')


DIS_CSS = ('.evi .rule,.fthumbs span{overflow-wrap:anywhere}'
           '.hrow .ev,.hrow .miss,.hparts dd{overflow-wrap:anywhere}'
           '.hparts{display:grid;grid-template-columns:max-content minmax(0,1fr);gap:6px 14px;margin:0 0 10px}.hparts dt{font-weight:650}'
           '.hparts dd{margin:0;line-height:1.5}@media(max-width:760px){.hparts{grid-template-columns:1fr;gap:2px 0}.hparts dd{margin-bottom:8px}}'
           '.res.hsum td:last-child{white-space:normal;min-width:200px}'
           '.hsum td:nth-child(2){width:52%}.hsum td:nth-child(3){width:18%}.hsum td{font-size:13.5px}.hsum td:first-child{white-space:nowrap}'
           '.rmap td:first-child{white-space:nowrap}.rmap td{font-size:13.5px}.rmap td:nth-child(2){min-width:220px}'
           '.rmap td:nth-child(4){min-width:240px}@media(max-width:760px){.rmap,.rmap tbody,.rmap tr,.rmap td{display:block}'
           '.rmap tr:first-child{display:none}.rmap tr{border-top:1px solid var(--line);padding:8px 0}.rmap td{border:0;padding:2px 0;min-width:0!important;white-space:normal!important}'
           '.rmap td[data-l]::before{content:attr(data-l);display:block;font-size:12px;color:var(--muted)}'
           '.hsum,.hsum tbody,.hsum tr,.hsum td{display:block}.hsum tr:first-child{display:none}.hsum tr{border-top:1px solid var(--line);padding:8px 0}'
           '.hsum td{border:0;padding:2px 0;width:auto!important;white-space:normal!important}'
           '.hsum td[data-l]::before{content:attr(data-l);display:block;font-size:12px;color:var(--muted)}}')


def _nav(overview, out):
    first = "" if overview else '<a href="index.html">← All species</a>'
    report = '<a href="../report.html#distribution">← EDA report</a>' if out and (Path(out).parent / "report.html").is_file() else ""
    return f'<nav>{first}<!--DIS-NAV-->{report}<!--/DIS-NAV--></nav>'


def page_name(sp):
    return f"species-{_slug(sp)}.html"


def _species_card(sp, boards):
    """Summarize the same study question rows and local panels the species page uses."""
    counts = Counter(q["status"] for b in boards for q in b["questions"])
    files = list(dict.fromkeys(f for b in boards for f in b["figs"].values()))
    # Prefer different panel types; fill remaining slots from the available studies.
    by_panel = {}
    for b in boards:
        for (panel, _), file in b["figs"].items():
            by_panel.setdefault(panel, file)
    previews = list(dict.fromkeys([*by_panel.values(), *files]))[:3]
    studies = [b["study"] for b in boards]
    study_labels = list(dict.fromkeys(_study_display_name(b) for b in boards))
    page = page_name(sp)
    info = {"species": sp, "page": page, "studies": studies, "figures": len(files),
            "thumbnails": previews, "counts": {ST_CODE[s]: counts[s] for s in COMMON.ST_ORDER if counts[s]}}
    chips = " ".join(f'<span class="st {COMMON.ST_CLASS[s]}">{counts[s]} {_e(COMMON.ST_SHORT[s].lower())}</span>'
                     for s in COMMON.ST_ORDER if counts[s])
    images = "".join(f'<img src="{_e(f)}" alt="Preview of {_e(f)}" loading="lazy">' for f in previews)
    observations = []
    for board in boards:
        for q in board["questions"]:
            marker = q.get("strongest_concurrent_ratio")
            if marker:
                assay = " Antimicrobial activity." if marker.get("analyte") == "ACTIVE_MATERIAL" else ""
                observations.append(f'<p>{_e(_ratio_reader_words(q["observed"]) + assay)}</p>')
    card = (f'<a class="category" id="sp-{_e(_slug(sp))}" href="{_e(page)}">'
            f'<span class="badge">{len(studies)} {"study" if len(studies) == 1 else "studies"}</span>'
            f'<h3>{_e(sp)}</h3><p class="muted">{_e("; ".join(study_labels))} · {len(files)} '
            f'{"panel" if len(files) == 1 else "panels"}</p>' + "".join(observations) + f'<p>{chips}</p>'
            + (f'<div class="thumbs">{images}</div>' if images else "")
            + '<span class="open">Open the seven questions →</span></a>')
    return info, card


# ---------------------------------------------------------------- overview summary (the form of the absorption overview)

_SHAPE_SAY = [("SUPPORTED", "the IV decline supports a multi-compartment candidate in {who}"),
              ("TENTATIVE", "a second phase is possible in {who} but is not firm"),
              ("ONE_PHASE", "one decline phase is seen in {who}"),
              ("NONLINEAR_FIRST", "the IV decline is not log-convex in {who}, so a nonlinear or recycling candidate comes first"),
              ("STEEPENS", "the IV decline steepens in {who}, with the cause unresolved"),
              ("ONGOING_INPUT", "observations are during ongoing IV input in {who}; no post-stop decline or bolus Vc is assigned"),
              ("ACTIVE_MATERIAL", "antimicrobial activity is measured in {who}; parent-specific decline structure and Vc are not established"),
              ("REPORTED_ONLY", "source-reported parameters, without an observed IV profile, are available in {who}"),
              ("BINDING_ONLY", "binding measurements, without a systemic concentration profile, are available in {who}"),
              ("UNREAD", "the IV decline cannot be read yet in {who}"),
              ("NO_IV", "there is no IV profile in {who}")]
_TISSUE_SAY = {"RISING": "the ratio to {ref} ends higher for {names}", "FALLING": "the ratio to {ref} ends lower for {names}",
               "TISSUE_NOT_FALLING": "the endpoint ratio to {ref} is higher for {names}",
               "NO_DIFFERENCE_SEEN": "no endpoint ratio difference to {ref} is detected for {names}; equilibrium remains unresolved",
               "VARIABLE_WITHIN_WINDOW": "the ratio to {ref} moves within the window for {names}"}
_TISSUE_COUNT = {"RISING": "the ratio ends higher in {n}", "FALLING": "the ratio ends lower in {n}",
                 "NO_DIFFERENCE_SEEN": "no endpoint ratio difference is detected in {n} (equilibrium unresolved)", "TISSUE_NOT_FALLING": "the endpoint ratio is higher in {n}",
                 "VARIABLE_WITHIN_WINDOW": "the ratio moves within the window in {n}"}
_FORK_SAY = {"TENTATIVE": "one or two compartments", "ONE_PHASE": "one compartment, or a fast phase before the first sample"}
_ALT_SAY = {"Nonlinear elimination or binding instead of a further compartment": "a further compartment, or nonlinear elimination or binding",
            "A slow tissue compartment behind the plasma terminal phase": "a plasma terminal phase that is the true one, or a slow tissue compartment behind it",
            "Concentration-dependent plasma binding": "constant or concentration-dependent plasma binding"}
OVERVIEW_NAMES = 4     # more boards than this are counted, with the first three named
OVERVIEW_ITEMS = 3     # most frequent missing items, checks and per-board details written out


def _study_routes(b):
    """Actual dosing routes, including nonoral EV routes; IDs never supply a route."""
    sources = [s for s in b.get("source_series", []) if isinstance(s, dict)] + list(b.get("inventory_sources") or [])
    routes = set()
    for s in sources:
        detail = str(s.get("route_detail") or s.get("route_source") or "").upper()
        if detail in ("NOT_FOUND", "OTHER_EV", "EV"):
            detail = str(s.get("route_source") or "").upper()
        title = str(s.get("title") or "")
        for code, pattern in (("IV", r"\bIV\b|intravenous"), ("oral", r"\bPO\b|\boral\b"),
                              ("SC", r"\bSC\b|subcutaneous"), ("IM", r"\bIM\b|intramuscular"),
                              ("IP", r"\bIP\b|intraperitoneal"), ("IT", r"\bIT\b|intrathecal")):
            if re.search(pattern, detail, re.I) or (not detail and re.search(pattern, title, re.I)):
                routes.add(code)
        if s.get("route_class") == "IV":
            routes.add("IV")
    if not routes and any(s.get("route_class") == "EV" for s in sources):
        routes.add("extravascular")
    return sorted(routes, key=lambda r: (r != "IV", r))


def _study_display_name(b):
    """Describe the study design using source metadata, without decoding an internal ID.

    Producers may supply study_display_name when a design alone is insufficient.
    The identifier remains in JSON and in source-data disclosures.
    """
    sources = [s for s in b.get("source_series", []) if isinstance(s, dict)] + list(b.get("inventory_sources") or [])
    explicit = b.get("study_display_name") or next((s.get("study_display_name") for s in sources if s.get("study_display_name")), None)
    if explicit:
        return str(explicit)
    text = " ".join(str(s.get("title") or "") for s in sources).lower()
    if "ongoing input" in text or any(s.get("iv_mode") == "ONGOING_INPUT" for s in sources):
        return "IV loading dose plus infusion"
    if "post-dose" in text and "binding" in text:
        return "post-dose plasma binding"
    if "in vitro" in text and "binding" in text:
        return "in-vitro plasma binding"
    if "recovery" in text or "excretion" in text:
        return "excretion study"
    route = COMMON._hjoin(_study_routes(b))
    tissue = bool(b.get("tissues")) or bool(re.search(r"\btissue\b|kidney|liver|spleen|heart|lung|\bcsf\b", text))
    if route or tissue:
        day = re.search(r"\bday\s+(\d+)\b", text)
        design = "tissue concentrations" if tissue else "concentration profiles"
        return (f"day {day.group(1)} " if day else "") + (route + " " if route else "") + design
    if b.get("reported_parameters"):
        return "reported PK parameters"
    if b.get("binding", {}).get("fu_table") or b.get("binding", {}).get("ex_vivo_binding"):
        return "plasma binding"
    return "concentration study"


def _board_namer(boards):
    """A stable reader label, with an ordinal only for otherwise identical designs."""
    labels, groups = {}, {}
    for b in boards:
        label = f'{b["species"]} · {_study_display_name(b)}'
        groups.setdefault(label, []).append(b)
    for label, same in groups.items():
        for i, b in enumerate(same, 1):
            labels[b["key"]] = label + (f" (study {i})" if len(same) > 1 else "")
    return lambda b: labels.get(b.get("key"), f'{b["species"]} · {_study_display_name(b)}')


def _reader_text(text, boards):
    """Replace identifiers in reader prose; never apply this to anchors or provenance."""
    names = _board_namer(boards)
    replacements = {}
    for b in boards:
        replacements.setdefault(b["study"], _study_display_name(b))
        for s in b.get("source_series", []):
            if isinstance(s, dict):
                replacements[s.get("dataset_id", "")] = s.get("title") or names(b)
                replacements[s.get("sid", "")] = s.get("label") or s.get("title") or names(b)
        for s in b.get("inventory_sources", []):
            replacements.setdefault(s.get("dataset_id", ""), s.get("title") or names(b))
    value = str(text or "")
    for code in sorted((k for k in replacements if k), key=len, reverse=True):
        value = re.sub(r"(?<![\w])" + re.escape(code) + r"(?![\w])", lambda _: replacements[code], value)
    value = re.sub(r"\bT6\s*(?:/|or|,)\s*T7\b", "decline-shape checks", value)
    value = re.sub(r"\bT6\b", "single-phase check", value)
    value = re.sub(r"\bT7\b", "decline-shape check", value)
    value = re.sub(r"\bT8\b", "tissue-ratio check", value)
    return say_codes(value)


def _hwho(names, total, inner=False):
    """Board names for a sentence: all of them, the names, or a count with the first three when the list is long.
    `inner` is the form for use inside parentheses."""
    names = list(dict.fromkeys(names))
    if total > 2 and len(names) == total:
        return f"all {COMMON._hnum(total)}"
    if len(names) > OVERVIEW_NAMES:
        return (f"{len(names)} of {total}, among them {COMMON._hjoin(names[:3])}" if inner else
                f"{len(names)} of {total} ({', '.join(names[:3])} and {len(names) - 3} more)")
    return COMMON._hjoin(names)


def _hmore(n, what="on the species pages"):
    return f" ({n} more {what})" if n > 0 else ""


def _hstate(hs):
    lab = {"PENDING": "waiting for review", "AGREED": "agreed", "REJECTED": "rejected"}
    if not hs:
        return "No hypotheses are available for review."
    cnt = Counter(lab.get(h.get("state") or "PENDING", "review status unknown") for _, h in hs)
    return (f"{'It is' if len(hs) == 1 else 'All ' + COMMON._hnum(len(hs)) + ' are'} {next(iter(cnt))}." if len(cnt) == 1 else
            COMMON._hcap(COMMON._hjoin(f"{COMMON._hnum(v)} {k}" for k, v in cnt.items())) + ".")


def _hmissing_text(miss, chk, total):
    """'What is missing': the most frequent lacks, then what to check before modelling."""
    ms = sorted(miss.items(), key=lambda kv: (-len(kv[1]), kv[0]))[:OVERVIEW_ITEMS]
    cs = list(chk.items())
    txt = (f"The data most often lack {COMMON._hjoin(f'{k} ({_hwho(v, total, True)})' for k, v in ms)}." if ms else "")
    if len(miss) > OVERVIEW_ITEMS:
        txt += f" {len(miss) - OVERVIEW_ITEMS} additional missing-data themes are listed on the species pages."
    if cs:
        txt += (" Before modelling, check " + COMMON._hjoin(("the " if k.startswith("source") else "") + f"{k} ({_hwho(v, total, True)})" for k, v in cs[:OVERVIEW_ITEMS])
                + _hmore(len(cs) - OVERVIEW_ITEMS) + ".")
    return txt.strip()


def _ratio_reader_words(text):
    text = str(text)
    for source in ("Kidney homogenate parent/Plasma", "Mean kidney concentration/Plasma"):
        text = text.replace(source + ": observed concurrent ratios", "Kidney-to-plasma concentration ratios were")
    return text


def _species_in_prose(species):
    plurals = {"dog":"dogs", "mouse":"mice", "rat":"rats", "rabbit":"rabbits",
               "pig":"pigs", "monkey":"monkeys", "koala":"koalas", "donkey":"donkeys",
               "cat":"cats", "human":"humans", "horse":"horses", "sheep":"sheep"}
    return plurals.get(species.lower(), "the " + species.lower() + " cohort")


def _overview_paras(boards, plain=False):
    """A small set of high-value findings; study-level detail stays below the summary. With plain=True (pages, shared rule 10) the IV
    paragraph is the plain reading and the numbers behind it come as a third element."""
    hs = [(b, b["hypothesis"]) for b in boards if b.get("hypothesis")]
    if not hs:
        return []
    brief = lambda h: h.get("brief") or {}
    species = lambda group: COMMON._hjoin(sorted({_species_in_prose(b["species"]) for b, _ in group}))
    paras, tissue_bits = [], []
    for b, h in sorted(hs, key=lambda bh: not bool(brief(bh[1]).get("ongoing_tissue"))):
        br = brief(h)
        ongoing = br.get("ongoing_tissue") or []
        if ongoing:
            observation = ongoing[0].split(";", 1)[0]
            observation = observation.replace("CSF parent/plasma concurrent ratio", "CSF-to-plasma concentration ratio was")
            tissue_bits.append(f"In {_species_in_prose(b['species'])}, the {observation}.")
        else:
            marker = next((q for q in b.get("questions", []) if q.get("strongest_concurrent_ratio")), None)
            if marker:
                sid = marker["strongest_concurrent_ratio"].get("tissue_sid", "")
                sources = [s for s in b.get("source_series", []) if isinstance(s, dict)] + list(b.get("inventory_sources") or [])
                source = next((s for s in sources if s.get("sid") == sid or s.get("dataset_id") == sid.split(":")[0]), {})
                dose = source.get("dose")
                routes = _study_routes({"source_series": [source]}) if source else []
                context = f" ({_f(dose)} mg/kg {COMMON._hjoin(routes)})" if dose and routes else ""
                observation = _ratio_reader_words(marker["observed"])
                tissue_bits.append(f"In {_species_in_prose(b['species'])}{context}, " + observation[:1].lower() + observation[1:])
    if tissue_bits:
        if any(brief(h).get("ongoing_tissue") for _, h in hs):
            tissue_bits.append("No post-stop decline or bolus Vc is assigned to the infusion experiment; these ratios do not establish a plateau, equilibrium or unbound penetration.")
        tissue_bits.append("Tissue-ratio trends remain descriptive where uncertainty limits interpretation; similar endpoint ratios leave equilibrium unresolved.")
        paras.append(("Tissue observations", " ".join(tissue_bits)))
    activity = [(b, h) for b, h in hs if brief(h).get("shape") == "ACTIVE_MATERIAL"]
    if activity:
        paras.append(("Assay scope", "The source measures antimicrobial activity; parent-specific decline structure and Vc are not established."))
    shape_bits = []
    supported = [(b, h) for b, h in hs if brief(h).get("shape") == "SUPPORTED"]
    many = [(b, h) for b, h in supported if brief(h).get("profiles", {}).get("usable", 0) > 1]
    if many:
        for b, h in many[:1]:
            pf = brief(h)["profiles"]
            shape_bits.append(f"In {_species_in_prose(b['species'])}, concentrations still declined more slowly at late times in {pf['robust']} of {pf['usable']} IV profiles after dropping the first or last point"
                              + (f". In {pf['tentative']} profiles the finding depended on a single sample" if pf.get("tentative") else "") + ". Compare one and two compartments.")
    few = [(b, h) for b, h in supported if (b, h) not in many]
    if few:
        shape_bits.append(f"IV declines support two-compartment candidates in {species(few)}.")
    for code, template in (("TENTATIVE", "A second phase is tentative in {who}."),
                           ("ONE_PHASE", "One visible phase in {who} does not exclude an earlier distribution phase."),
                           ("NONLINEAR_FIRST", "The decline in {who} steepens; nonlinear elimination or recycling needs consideration."),
                           ("STEEPENS", "The decline in {who} steepens, with the cause unresolved.")):
        group = [(b, h) for b, h in hs if brief(h).get("shape") == code]
        if group:
            shape_bits.append(template.format(who=species(group)))
    unread = [(b, h) for b, h in hs if brief(h).get("shape") == "UNREAD"]
    if unread:
        for b, _ in unread[:1]:
            design = _study_display_name(b).replace("concentration profiles", "study")
            shape_bits.append(f"The separate {design} in {_species_in_prose(b['species'])} sampled too infrequently to distinguish decline phases.")
    # Keep exceptional bounds scoped to their own animals, rather than pooling unlike experiments.
    per_animal = [(b, brief(h)["vc"]) for b, h in hs if (brief(h).get("vc") or {}).get("kind") == "PER_ANIMAL"]
    for b, vc in per_animal[:1]:
        shape_bits.append(f"The median of {vc['n']} per-animal initial Vc bounds in {_species_in_prose(b['species'])} is {_f(vc['value'])} L/kg (range {_f(vc['min'])}–{_f(vc['max'])}); this is not a bound for every animal.")
    has_iv = {b["species"] for b, h in hs if brief(h).get("shape") in ("SUPPORTED", "ONE_PHASE", "TENTATIVE", "UNREAD")}
    no_iv = [(b, h) for b, h in hs if brief(h).get("shape") == "NO_IV" and not b.get("tissues") and b["species"] not in has_iv]
    if no_iv:
        descriptions = [f"{_species_in_prose(b['species'])} ({COMMON._hjoin(_study_routes(b)) or 'extravascular dosing'})" for b, _ in no_iv]
        shape_bits.append(f"{COMMON._hcap(COMMON._hjoin(descriptions))} {'has' if len(descriptions) == 1 else 'have'} no IV profile in these studies; continuing absorption can shape {'its' if len(descriptions) == 1 else 'their'} decline.")
    want_plain = plain
    plain = list(dict.fromkeys(f'{h["plain"]["shows"]} {h["plain"]["suggests"]}' for b, h in hs if h.get("plain") and b.get("iv_refs")))
    if plain and want_plain:  # shared rule 10: the plain reading leads; the numbers behind it are collapsed under it
        paras.append(("IV disposition", " ".join(plain), " ".join(shape_bits)))
    elif shape_bits:
        paras.append(("IV disposition", " ".join(shape_bits)))
    binding_bits = []
    own_binding = [(b, brief(h)) for b, h in hs if brief(h).get("shape") == "BINDING_ONLY" and not brief(h).get("fu_other_study") and brief(h).get("fu")]
    if own_binding:
        values = [f"{_f(br['fu'][0])}–{_f(br['fu'][1])} in {_species_in_prose(b['species'])}" for b, br in own_binding]
        binding_bits.append("In-vitro parent fraction unbound was " + COMMON._hjoin(values) + ".")
    ex_vivo = []
    for b, h in hs:
        record = brief(h).get("own_ex_vivo") or ""
        found = re.search(r"([\d.]+(?:–[\d.]+)?) % bound over ([^(]+)", record)
        if found:
            ex_vivo.append(f"{found[1]}% in {_species_in_prose(b['species'])} ({found[2].strip()})")
    if ex_vivo:
        binding_bits.append("Post-dose total-radioactivity binding was " + COMMON._hjoin(ex_vivo) + ".")
    if any(brief(h).get("fu_other_study") for _, h in hs):
        binding_bits.append("The binding measurements come from other studies. Using them to estimate unbound drug in these animals requires comparable assay conditions.")
    if binding_bits:
        paras.append(("Plasma binding", " ".join(binding_bits)))
    if not paras:
        paras.append(("Available evidence", "Source-reported parameters and study-specific missing evidence are available in the study details."))
    paras.append(("Review status", _hstate(hs)))
    return [(p[0], _reader_text(p[1], boards)) + ((_reader_text(p[2], boards),) if len(p) > 2 and p[2] else ()) for p in paras]


def _overview_html(boards):
    paras = _overview_paras(boards, plain=True)
    return ('<p class="muted">One working hypothesis per study and species, drawn from its seven questions. Each is a working interpretation for a model '
            'to evaluate; observations do not establish a mechanism.</p><div class="hsumtext">' + "".join(
                f'<p><b>{_e(p[0])}.</b> {_e(p[1])}</p>' for p in paras) + '</div>'
            + "".join(f'<details class="nums"><summary>Numbers behind this</summary><p class="ev">{_e(p[2])}</p></details>' for p in paras if len(p) > 2)) if paras else ""


def _hcount(n, one, many=None):
    return f"{n} {one if n == 1 else (many or one + 's')}"


def _hengine(res):
    eng = (res.get("render") or {}).get("engine")
    return ("No figures drawn" if eng in (None, "none") else
            "Figures drawn with " + {"R_GGPLOT2": "R (ggplot2)", "MATPLOTLIB_FALLBACK": "matplotlib (R unavailable)"}.get(eng, eng))


def _overview_stats(res, boards):
    files = {f for b in boards for f in b["figs"].values()}
    data = [_hcount(sum(len(b["iv_refs"]) for b in boards), "IV profile"), _hcount(sum(len(b["ev_refs"]) for b in boards), "extravascular profile"),
            _hcount(sum(len(b["tissues"]) for b in boards), "tissue series", "tissue series")]
    return (f'<p class="muted">{_hcount(len(files), "panel")} · {len({b["species"] for b in boards})} species · '
            f'{_hcount(len({b["study"] for b in boards}), "study", "studies")} · {", ".join(data)} and '
            f'{_hcount(len(res.get("binding_records") or []), "binding record")} · Computed by host code from observed points; {FIT_NOTE} · '
            f'{_e(_hengine(res))} · Human review pending</p>')


def render_pages(res, boards, series, spt, conds, out=None):
    pages = {}
    name = _board_namer(boards)
    reader = lambda value: _reader_text(value, boards)
    sps = sorted({b["species"] for b in boards})
    # overview
    h = [_nav(True, out), '<p class="eyebrow">EDA review · Distribution</p><h1>Distribution</h1>',
         '<p class="lead">Where the drug goes after it reaches the circulation: decline phases after IV dosing, the initial-volume bound, tissue '
         f'concentrations and their ratio to plasma, unbound exposure, and what can be compared across conditions and species (rules {RULES_VERSION}, items 24–28). '
         f'Host-computed from observed points; {FIT_NOTE}; no extrapolation.</p>']
    species_entries = [_species_card(sp, [b for b in boards if b["species"] == sp]) for sp in sps]
    species_entries.sort(key=lambda pair: (pair[0]["species"] == "Species not stated", -pair[0]["figures"], pair[0]["species"]))
    h.append('<section id="species-pages"><div class="section-head"><h2>Review by species</h2>'
             '<span class="muted">Open a species for its studies and their distribution questions.</span></div>'
             '<div class="categories">' + "".join(card for _, card in species_entries) + '</div></section>')
    h.append('<nav aria-label="Distribution details"><a id="reading-map" href="figure-guide.html">How to read the figures</a>'
             '<a id="species" href="conditions-and-species.html">Q7 · Conditions and species</a></nav>')
    # the statistics line and the hypotheses come first, as on the absorption overview
    h.insert(3, _overview_stats(res, boards))
    h.insert(4, '<section class="panel" id="hypotheses"><h2>Working hypotheses: first review</h2>' + _overview_html(boards)
             + '<details class="evi"><summary>Study hypotheses and missing evidence</summary><div class="tw"><table class="res hsum"><tr><th>Study</th>'
             '<th>Working hypothesis</th><th>Rests on</th><th>Missing</th></tr>' + "".join(
                 f'<tr><td data-l="Study"><a href="{page_name(b["species"])}#h-{_e(b["key"])}">{_e(name(b))}</a></td>'
                 f'<td data-l="Working hypothesis">{"<br>".join("<b>" + _e(x["label"]) + ".</b> " + _e(reader(x["text"])) for x in b["hypothesis"].get("lines") or []) or _e(reader(b["hypothesis"]["text"]))}</td><td data-l="Rests on">{_e(reader(b["hypothesis"]["rests_on"].replace("Rests on: ", ""))) or "—"}</td>'
                 f'<td data-l="Missing">{_e(reader("; ".join(b["hypothesis"]["missing"]))) or "—"}</td></tr>' for b in boards) + '</table></div></details></section>')
    back = '<nav><a href="index.html">← Distribution overview</a></nav>'
    pages["figure-guide.html"] = _shell("How to read the figures", back + '<section class="panel" id="reading-map"><h1>How to read the figures</h1><p class="muted">Each panel: what to look at, what can be read from it, '
             f'and the hypothesis it hands to modeling (rules D0.11, {RULES_VERSION}). A reading without a test stays a description.</p><div class="tw"><table class="res rmap">'
             '<tr><th>Panel</th><th>Look at</th><th>Reading</th><th>Hypothesis handed over</th></tr>' + "".join(
                 f'<tr><td data-l="Panel">{_e(a)}</td><td data-l="Look at">{_e(b_)}</td><td data-l="Reading">{_wb(say_codes(c))}</td><td data-l="Hypothesis">{_e(d)}</td></tr>'
                 for a, b_, c, d in READING_MAP) + '</table></div></section>')
    q7 = [back, '<section class="panel" id="species"><h1>Q7 · Conditions and species (project level)</h1>',
          f'<p><span class="st {COMMON.ST_CLASS[spt["status"]]}">{_e(spt["status"])}</span> '
          + _e(f"{len(spt['species_with_bound'])} species with an initial-volume bound (item 25); reported volumes comparable by definition: {', '.join(spt['comparable_definitions']) or 'none'}.") + '</p>']
    q7.append("<p>Compare early sampling coverage and supported decline shapes before testing a shared compartment structure. Compare Vc bounds at their sampling times and Vss under matched definitions. Assess species-specific parameters only in comparable subsets.</p>")
    supported_species = sorted({r["species"] for r in spt["species_rows"] if r["phases"] == "TWO_OR_MORE"})
    if supported_species:
        q7.append("<p>Early-to-late slowing survives deletion checks in " + _e(", ".join(supported_species)) +
                  ". Compare one and two compartments in those source profiles. In each additional species, first check whether its sampling window could resolve the same feature.</p>")
    if spt.get("vc_bound_table"):
        q7.append("<h2>Upper bound on central volume (Vc) from the first post-infusion sample</h2><p class=\"muted\">Vc ≤ D/C at the highest "
                  "quantified concentration after the input ends (usually the first sample). Times are after the start of dosing, as in the figures.</p>"
                  + vc_table_html(spt["vc_bound_table"]))
    for file in spt.get("figures", []):
        caption = "Source-matched Vss and Vss/fu."
        q7.append(f'<figure class="prim" style="max-width:760px"><a href="{_e(file)}" target="_blank"><img src="{_e(file)}" alt="{_e(caption)}"></a>'
                  f'<figcaption><b>DIS-5</b> · {_e(caption)}</figcaption></figure>')
    rows = [[r["species"], reader(r["study"]), r["series"], say(r["phases"]) if r["phases"] != "—" else "—", yes_no(r.get("t6_reading", say(r["t6"]))),
             yes_no(r.get("t7_reading", say(r["t7"]))), _f(r["vc_bound"]) + (f" @ {_f(r['vc_t'])} h" if r["vc_t"] is not None else ""),
             (f"{_f(min(r['fu']))}–{_f(max(r['fu']))}" if r["fu"] else "—")] for r in spt["species_rows"]]
    q7.append('<div class="tw"><table class="res evt"><tr>' + "".join(f"<th>{x}</th>" for x in ("Species", "Study", "IV series", "Phases", "One exponential fits?", "Decline only slows?", "Vc ≤ (L/kg)", "fu,p"))
              + "</tr>" + "".join("<tr>" + "".join(f"<td>{_wb(v)}</td>" for v in r) + "</tr>" for r in rows) + "</table></div>")
    gates = sorted({_f(x["noise_gate"]["half_width_pct"], 2) for b in boards for x in b.get("item24", []) if x.get("noise_gate")})
    if gates:
        q7.append(f'<p class="muted">Assay noise assumed ±{" to ±".join([gates[0], gates[-1]] if len(gates) > 1 else gates)} % '
                  "(no source precision). Checks use ±5 % per point and, separately, this assay noise.</p>")
    if spt["reported_volumes"]:
        q7.append('<details class="evi"><summary>Source-reported volumes (never pooled across definitions)</summary><div class="tw"><table class="res evt"><tr>'
                  '<th>Species</th><th>Study</th><th>Parameter</th><th>As reported</th><th>L/kg</th><th>Method</th><th>SD / n</th><th>Dataset / record</th></tr>' + "".join(
                      f'<tr><td>{_e(v["species"])}</td><td>{_e(v["study"])}</td><td>{_e(v["parameter"])}</td><td>{_e(v["value"])} {_e(v["unit"] or "")}</td>'
                      f'<td>{_f(v.get("value_l_per_kg"))}</td><td>{_e(v["method"])}</td><td>{_f(v.get("sd"))} / {_f(v.get("n"))}</td><td>{_e(v["dataset_id"])} · {_e(v.get("record_id"))}</td></tr>' for v in spt["reported_volumes"]) + '</table></div></details>')
    if spt["vss_fu_rows"]:
        q7.append(ab._evidence_html([{"rule": "Matched source-reported Vss and stable fu,p.", "data": [], "tables": [{"caption": "Vss referred to unbound plasma", "head": ["Species", "Study", "Vss/fu range (L/kg)", "Binding dataset"],
                              "rows": [[x["species"], x["study"], " – ".join(_f(v) for v in x["vss_over_fu_range"]), x["binding_dataset"]] for x in spt["vss_fu_rows"]]}]}]))
    if conds:
        q7.append('<details class="evi"><summary>Condition pairs within a species (T5)</summary><div class="tw"><table class="res evt"><tr><th>Species</th><th>A</th><th>B</th>'
                  '<th>Differing</th><th>T5</th><th>Caveats</th></tr>' + "".join(
                      f'<tr><td>{_e(c["species"])}</td><td>{_e(reader(c["a_label"]))}</td><td>{_e(reader(c["b_label"]))}</td><td>{_e(", ".join(a.replace("_", " ") for a in c["differing_attributes"]))}</td>'
                      f'<td>{_e(say(c["t5_label"]))}</td><td>{_e(", ".join(say(x) for x in c["caveats"]) or "—")}</td></tr>' for c in conds) + '</table></div></details>')
    miss = "; ".join((f"{sp}: " if len(spt["missing_by_species"]) > 1 else "") + "; ".join(m) for sp, m in spt["missing_by_species"].items() if m)
    if miss:
        q7.append(f'<p class="miss"><b>Not supplied in this package:</b> {_e(miss)}. Missing inputs are not tool errors.</p>')
    q7.append('</section>')
    pages["conditions-and-species.html"] = _shell("Conditions and species", "".join(q7))
    h.append('<section class="panel" id="questions"><h2>Questions by study</h2>' + "".join(
        f'<div class="pgrp"><p><b>{_e(name(b))}</b></p><div class="qchips">{_chips(b, page_name(b["species"]))}</div></div>' for b in boards) + '</section>')
    if res["skipped"]:
        h.append('<details class="evi"><summary>Not drawn</summary><ul class="ev">' + "".join(f'<li>{_e(x["dataset_id"])}: {_e(x["reason"])}</li>' for x in res["skipped"]) + '</ul></details>')
    h.append(f'<footer>{_e(VERSION)} · figures drawn by {_e(res["render"]["engine"])}' + (f' ({_e(res["render"]["note"])})' if res["render"].get("note") else "")
             + ' · project settings: tolerance ±5 %, σ 0.15 / 0.158, R ≥ 1.5 and z ≥ 2, bands 0.80–1.25 / 0.72–1.38, Kpuu 0.5–2.</footer>')
    pages["index.html"] = _shell("Distribution", "".join(h))
    base = out
    for sp in sps:
        bs = [b for b in boards if b["species"] == sp]
        body = [_nav(False, out), '<nav aria-label="Studies">' + "".join(f'<a href="#study-{_e(b["key"])}">{_e(_study_display_name(b))}</a>' for b in bs) + '</nav>',
                f'<p class="eyebrow">EDA figure review · Distribution</p><h1>{_e(sp)}</h1>'
                '<p class="lead">Seven questions for each study. Read the concentration profiles first, then review the evidence for the study hypothesis.</p>',
                '<div class="legend">' + "".join(f'<span><span class="st {COMMON.ST_CLASS[st]}">{_e(COMMON.ST_SHORT[st])}</span>{desc}</span>' for st, desc in (
                    (ST_YES, "supported under the stated assumptions"), (ST_PART, "some evidence is available"),
                    (ST_NO, "more evidence is needed"), (ST_NA, "outside this study design"))) + '</div>']
        source_owners = {_e(ds): owner["key"] for owner in bs for ds in owner["datasets"]}
        for b in bs:
            local_ids = set(b["datasets"]) | {v["dataset_id"] for v in b["binding"]["fu_table"]}
            destinations = {**source_owners, **{_e(ds): b["key"] for ds in local_ids}}
            body.append(f'<section class="panel study" id="study-{_e(b["key"])}"><h2>{_e(name(b))}</h2><p class="muted">{_e(_species_words(b))}</p>'
                        + _card_html(b) + f'<div class="qchips">{_chips(b)}</div>' + _gap_html("distribution", b) + "".join(_qrow_html(q, b["key"], base, destinations) for q in b["questions"]) + _hrow_html(b) + '</section>')
            body.append(_points_html(b))
        pages[page_name(sp)] = _shell(f"Distribution · {sp}", "".join(body))
    res["presentation"] = {"species": [info for info, _ in species_entries],
                           "figures": sum(len(b["figs"]) for b in boards),
                           "thumbnails": [f for b in boards for f in b["figs"].values()][:3]}
    return pages


# ---------------------------------------------------------------- report.html section, portal card, attach

def report_section(res, error=None):
    h = ['<section id="distribution"><h2>Distribution: where does the drug go?</h2>',
         '<p>Where the drug goes after it reaches the blood: how many decline phases the IV data show, the size of the central volume, '
         'tissue levels and protein binding.</p>']
    if error is not None or not res:
        h.append(f'<p><b>Not generated:</b> {_e(error)}. The reason is recorded in distribution/error.json.</p></section>')
        return "".join(h)
    paragraphs = _overview_paras(res["boards"], plain=True)
    if paragraphs:
        heading, observation = paragraphs[0][:2]
        h.append(f'<p><b>{_e(heading)}.</b> {_e(observation)}</p>')
    h.append('<p><a href="distribution/index.html#hypotheses">Read the full findings</a></p><details><summary>Questions by experiment</summary><ul>')
    name = _board_namer(res["boards"])
    for b in res["boards"]:
        by = {}
        for q in b["questions"]:
            by.setdefault(q["status"], []).append(_qref(q))
        h.append(f'<li><a href="distribution/{page_name(b["species"])}#study-{_e(b["key"])}">{_e(name(b))}</a>: '
                 + "; ".join(f'{_e(s.lower())} {", ".join(by[s])}' for s in COMMON.ST_ORDER if by.get(s)) + '</li>')
    h.append('</ul></details><p><a href="distribution/index.html">Open the Distribution overview</a></p></section>')
    return "".join(h)


def add_to_portal(root):
    root = Path(root)
    try:
        page = root / "distribution" / "index.html"
        if not page.exists():
            return False
        res = json.loads((root / "distribution" / "distribution.json").read_text(encoding="utf-8"))
        pres = res.get("presentation", {})
        n = pres.get("figures", 0)
        card = ab.section_card("DISTRIBUTION", "Distribution", "distribution", "Where the drug goes after it reaches the blood: how many decline "
                               "phases IV data show, the size of the central volume, tissue levels and protein binding.", n, pres.get("thumbnails", []),
                               pres.get("species", []), "No distribution figures: this package has no IV or tissue profiles to draw.")
        done = False
        for name in ("index.html", "human_review.html"):
            p = root / name
            if not p.exists():
                continue
            text = re.sub(r"<!--DISTRIBUTION-CARD-START-->.*?<!--DISTRIBUTION-CARD-END-->", "", p.read_text(encoding="utf-8"), flags=re.S)
            pos = ab._grid_end(text)
            if pos is None:
                continue
            p.write_text(text[:pos] + card + text[pos:], encoding="utf-8")
            done = True
        if done:
            for pg in [page] + sorted((root / "distribution").glob("species-*.html")):
                s = re.sub(r"<!--DIS-NAV-->.*?<!--/DIS-NAV-->", '<!--DIS-NAV--><a href="../index.html#categories">← All categories</a>'
                           '<a href="../report.html#distribution">Question report</a><!--/DIS-NAV-->', pg.read_text(encoding="utf-8"), flags=re.S)
                pg.write_text(s, encoding="utf-8")
        return done
    except Exception as exc:  # noqa: BLE001 - the portal must not fail because of this card
        try:
            (root / "distribution" / "portal_error.json").write_text(json.dumps({"error": repr(exc)}), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
        return False


def attach(root, absorption_run=None):
    """Build the Distribution category and add a short section to report.html. A failure never stops the EDA run."""
    root = Path(root)
    res, err = None, None
    try:
        res = build(root, absorption_run)
    except Exception as exc:  # noqa: BLE001 - recorded and shown
        err = exc
        (root / "distribution").mkdir(exist_ok=True)
        (root / "distribution" / "error.json").write_text(json.dumps({"error": repr(exc)}, ensure_ascii=False), encoding="utf-8")
    report = root / "report.html"
    body = report.read_text(encoding="utf-8") if report.exists() else '<html lang="en"><meta charset="utf-8"></html>'
    body = re.sub(r'<!--DISTRIBUTION-START-->.*?<!--DISTRIBUTION-END-->', '', body, flags=re.S)
    block = '<!--DISTRIBUTION-START-->' + COMMON.reader_text(report_section(res, err)) + '<!--DISTRIBUTION-END-->'
    anchor = '<section><h2>Review issues</h2>'
    if anchor in body:
        body = body.replace(anchor, block + anchor, 1)
    elif '</html>' in body:
        body = body.replace('</html>', block + '</html>', 1)
    else:
        body += block
    report.write_text(body, encoding="utf-8")
    add_to_portal(root)
    return root / "distribution"


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description="Build the distribution EDA report")
    parser.add_argument("root", type=Path)
    parser.add_argument("--attach", action="store_true")
    parser.add_argument("--absorption-run", type=Path, help="Read dose evidence from a run with identical source tables")
    args = parser.parse_args(argv)
    root = args.root
    if args.attach:
        attach(root, args.absorption_run)
        res = json.loads((root / "distribution" / "distribution.json").read_text(encoding="utf-8"))
    else:
        res = build(root, args.absorption_run)
    print(json.dumps({"boards": len(res["boards"]), "species": len(res["species_table"]["missing_by_species"]),
                      "figures": res.get("presentation", {}).get("figures")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
