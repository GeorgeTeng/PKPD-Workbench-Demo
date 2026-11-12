"""Bind figure-level readings to native image paths when publishing the EDA detail pages."""
import json
import posixpath
import re
from collections import defaultdict
from html import escape
from html.parser import HTMLParser
from urllib.parse import unquote, urlsplit

def fmt(value):
    return f"{value:.3g}" if isinstance(value, (int, float)) else "—"


def interval(values):
    return "–".join(fmt(v) for v in values) if values else "—"


def p_value(value, alpha=.05, *, missing="Not tested", underflow="below numerical precision"):
    if value is None:
        return missing
    if value == 0:
        return underflow
    shown = fmt(value)
    return str(value) if float(shown) == alpha and value != alpha else shown


def time_window(values, *, empty="No overlap", single="{:g} h only"):
    if not values:
        return empty
    if values[0] == values[-1]:
        return single.format(values[0])
    return f"{values[0]:g}–{values[-1]:g} h"


def table(labels, rows):
    head = "".join(f"<th>{escape(label)}</th>" for label in labels)
    body = "".join("<tr>" + "".join(f"<td>{escape(str(cell))}</td>" for cell in row) + "</tr>" for row in rows)
    return f'<div class="scroll"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def block(heading, method, finding, headers=(), rows=(), *, statistical=False):
    body = f"<b>{escape(heading)}</b><p>{escape(method)}</p>"
    if finding:
        body += f"<p>{escape(finding)}</p>"
    if rows:
        body += table(headers, rows)
    kind = "test" if statistical else "data"
    return f'<section class="fig-reading" data-reading="{kind}" lang="en">{body}</section>'


def tail_note(pair, route, group_mean):
    tail = pair.get("tail") or {}
    original = tail.get("test") or {}
    if original.get("p") is None:
        return ""
    common = tail.get("common_tail") or {}
    shared = common.get("test") or {}
    ev_label = "Oral" if str(route).upper() in ("PO", "ORAL") else "Extravascular"
    unit = " Each point is a group mean." if group_mean else ""
    rows = [["Route-specific windows", time_window(tail["ev_window_h"]), time_window(tail["iv_window_h"]),
             f"{original['n_ev']} / {original['n_iv']}", fmt(tail["ratio"]), original["df"], p_value(original["p"])]]
    if common:
        span = time_window(common.get("window_h"))
        rows.append(["Shared window", span, span, f"{common['n_ev']} / {common['n_iv']}", fmt(common.get("ratio")),
                     shared.get("df", "—"), p_value(shared.get("p"))])
    alpha = tail.get("alpha", .05)
    if shared.get("p") is None:
        finding = "The overlap contained too few usable points for two declining slopes. The shared-window comparison could not be assessed."
    elif shared["p"] < alpha:
        direction = "more slowly" if common["ratio"] > 1 else "faster"
        finding = f"In the shared window, concentrations declined {direction} after {ev_label.lower()} dosing than after IV dosing."
    elif original["p"] < alpha:
        finding = "The slopes differed in the route-specific windows. The shared-window fit gave insufficient evidence of a difference."
    else:
        finding = "Neither fit resolved a difference between the slopes. Similar decline rates remain possible."
    if pair["dose_ev"] != pair["dose_iv"]:
        finding += " The two routes used different doses."
    return block(f"Terminal slopes · {ev_label} {fmt(pair['dose_ev'])} vs IV {fmt(pair['dose_iv'])} mg/kg",
                 f"A two-sided t test compared the slopes of log concentration against time, first in each route’s selected terminal window "
                 f"and then using observations in the overlap.{unit} Degrees of freedom come from the fitted time points. "
                 "The nominal p values do not account for window selection or multiple comparisons.",
                 finding + f" A half-life ratio above 1 indicates a slower {ev_label.lower()} decline. Confirming absorption-limited kinetics requires independent evidence.",
                 ["Comparison", f"{ev_label} window", "IV window", f"Time points ({ev_label.lower()} / IV)", "Half-life ratio", "df", "Two-sided p"], rows,
                 statistical=True)


def auc_notes(result):
    notes = []
    power = result.get("t3_power")
    if power:
        verdict = ("The group means suggest a departure from dose proportionality." if power["p"] < .05 else
                   "These dose groups provide insufficient evidence of a departure from proportionality.")
        notes.append(block("Dose proportionality of exposure",
                           f"Each of the {power['n_doses']} dose groups contributed one AUC from its mean concentration curve over the common window. "
                           f"A two-sided test compared the slope of log AUC against log dose with 1 ({power['df']} residual df).",
                           f"Estimated slope {fmt(power['beta'])} (nominal 95% CI {interval(power['ci'])}), p = {p_value(power['p'])}. "
                           + verdict + " The interval reflects variation about the fitted dose-group means. Individual-animal variability remains unresolved.", statistical=True))
    animal = result.get("animal_auc") or {}
    if animal.get("status") == "ASSESSED":
        method = "A paired t test within animals" if animal["design"] == "PAIRED" else "Welch’s t test for independent animal groups"
        finding = (f"High-to-low dose geometric mean ratio {fmt(animal['R'])} (95% CI {interval(animal['ci'])}), "
                   f"{fmt(animal['df'])} df, two-sided p = {p_value(animal['p'])}.")
        eq = animal.get("equivalence") or {}
        if eq.get("ci90"):
            finding += f" The equivalence assessment compares the 90% CI ({interval(eq['ci90'])}) with the prespecified limits ({interval(eq['margin'])})."
        notes.append(block("Dose-normalized exposure in individual animals", method + " compared log(AUC/dose) at the highest and lowest doses. The null geometric mean ratio is 1.", finding, statistical=True))
    elif result.get("ci") and result.get("R") is not None:
        notes.append(block("Dose-normalized exposure", str(result.get("method") or result.get("t3_reason_en") or "The comparison uses AUC/dose at the highest and lowest doses."),
                           f"High-to-low dose ratio {fmt(result['R'])} (interval {interval(result['ci'])}).", statistical=True))
    return "".join(notes)


def pointwise_note(result):
    test = result.get("t3p") or {}
    rows = [[fmt(ci["t"]), fmt(ci["ln_ratio"]), interval(ci["ci95"]), p_value(ci["p_raw"]), p_value(adj)]
            for ci, adj in zip(test.get("t3p_ln_ratio_ci", []), test.get("t3p_p_holm", []))]
    if not rows:
        return ""
    return block("Dose effects at matched sampling times", "Welch’s approximation compares dose-normalized concentrations at each matched time. A log ratio of zero indicates equal exposure at that time. Holm adjustment accounts for testing multiple times.",
                 f"{sum(bool(s) for s in test.get('significant', []))} of {len(rows)} time points met the adjusted significance criterion.",
                 ["Time (h)", "Log ratio", "Pointwise 95% CI", "Raw p", "Holm-adjusted p"], rows, statistical=True)


def absorption_notes(data, add):
    datasets = {d["card"]["dataset_id"]: d for d in data.get("datasets", [])}
    for d in datasets.values():
        for s in d["series"]:
            m = s["metrics"]
            if s.get("A2") and m.get("mt1") is not None:
                excluded = m.get("t1_label") == "EXCLUDED_UNDER_STATED_ASSUMPTIONS"
                result = ("The curve excludes this input pattern under the stated assumptions." if excluded else
                          "The input pattern remains compatible with the observations after the tolerance and point-deletion checks.")
                add("absorption", s["A2"], block("Absorption input shape", "With linear disposition and a nonincreasing input rate, concentration divided by time should not rise. "
                    "The check compares earlier and later samples using the reading tolerance at each point.", result,
                    ["Times of maximum departure", "Largest difference after tolerance (concentration units/h)"],
                    [[time_window(m["mt1_witness"]), fmt(m["mt1"])]]))
            t2 = s.get("t2") or {}
            if s.get("T2") and t2.get("valley"):
                excluded = t2.get("t2_label") == "EXCLUDED_UNDER_STATED_ASSUMPTIONS"
                add("absorption", s["T2"], block("Single-peak check", "The concentrations bracketing the trough quantify the fall and subsequent rise. The check uses the reading tolerance and assesses sensitivity to removing a point.",
                    ("The observations exclude a single peak at the stated tolerance." if excluded else "A single peak remains compatible with the observations."),
                    ["Before / at / after trough (h)", "Fall margin", "Rise margin"],
                    [[" / ".join(f"{v:g}" for v in t2["valley"]), fmt(t2.get("m_drop")), fmt(t2.get("m_rise"))]]))
    by_pair = {}
    for pair in data.get("ev_iv", []):
        ev = datasets.get(pair["ev"])
        if ev is None:
            continue
        note = tail_note(pair, ev["card"].get("route_detail"), ev["card"].get("record_level") == "GROUP_MEAN")
        by_pair[pair["ev"], pair["iv"]] = note
        if pair.get("D1"):
            add("absorption", pair["D1"], note)
            if pair.get("q"):
                finding = ("The ratio fell beyond the allowed tolerance and contradicts this assumption." if pair.get("t4_label") == "EXCLUDED_UNDER_STATED_ASSUMPTIONS"
                           else "The observations do not rule out the assumption at this tolerance.")
                add("absorption", pair["D1"], block("Concentration ratios at matched times",
                    "With shared linear one-compartment disposition, the extravascular-to-IV concentration ratio should not fall. This shape check allows for the reading tolerance.",
                    finding, ["Matched time (h)", "Extravascular/IV concentration ratio"],
                    [[fmt(r["t"]), fmt(r["q"])] for r in pair["q"]]))
        elif len(ev["series"]) == 1:
            add("absorption", ev["series"][0].get("B1"), note)
        area = pair.get("window_auc_ratio")
        if pair.get("D2") and area is not None:
            src = pair.get("source_reported_absolute_f") or {}
            rows = [["Observed-window AUC ratio", time_window([pair["window_start_h"], pair["window_end_h"]]), f"{fmt(100 * area)}%"]]
            if src.get("fraction") is not None:
                span = src.get("source_window_h")
                rows.append(["Author-reported absolute bioavailability", time_window(span) if span else "See source method", f"{fmt(100 * src['fraction'])}%"])
            add("absorption", pair["D2"], block("Exposure by route", "Both curves were integrated over their shared observation window. Each AUC was divided by dose to obtain the extravascular-to-IV exposure ratio.",
                "The observed-window ratio is a descriptive estimate.", ["Measure", "Observation window", "Value"], rows))
            if not pair.get("D1"):
                add("absorption", pair["D2"], note)
    for series in data.get("dose_series", []):
        auc = auc_notes(series)
        points = pointwise_note(series)
        records = series.get("rows") or []
        values = ""
        if records:
            units = {datasets[r["dataset_id"]]["card"].get("unit") for r in records if r.get("dataset_id") in datasets}
            unit = str(next(iter(units))) if len(units) == 1 and None not in units else ""
            values = block("Observed exposure by dose", f"The AUC window ends at {fmt(series.get('window_end_h'))} h in all dose groups.", "",
                ["Dose (mg/kg)", "Observed peak time (h)", f"AUC/dose{f' ({unit}·h per mg/kg)' if unit else ''}"],
                [[fmt(r["dose"]), fmt(r.get("tmax")), fmt(r.get("aucW_d"))] for r in records])
        for key in ("C1", "C2", "C2T3"):
            add("absorption", series.get(key), auc + values)
        add("absorption", series.get("C3"), points)
        if points and not series.get("C3"):
            add("absorption", series.get("C1"), points)
        if series.get("C3d") and series.get("per_time"):
            add("absorption", series["C3d"], block("Observed concentration ratios by time",
                "At each matched time, the table compares dose-normalized concentrations at the highest and lowest doses.", "The results are descriptive. No time-point test was performed.",
                ["Time (h)", "High/low dose-normalized concentration ratio"], [[fmt(r["t"]), fmt(r["ratio"])] for r in series["per_time"]]))
    for dataset in data.get("reported_parameters", []):
        analysis = dataset.get("analysis") or {}
        note = auc_notes(dict(analysis.get("t3") or {}, animal_auc=analysis.get("animal_auc")))
        add("absorption", dataset.get("C2T3") or dataset.get("F"), note)
    # The native Q5 fallback draws the first eligible EV pair in this board's order.
    for board in data.get("status_boards", []):
        board_ids = set(board.get("datasets", []))
        pair = next((p for p in data.get("ev_iv", []) if p["ev"] in board_ids and (p["ev"], p["iv"]) in by_pair), None)
        primary = {q["q"]: q.get("primary") or {} for q in board.get("questions", [])}
        if pair and primary.get(5, {}).get("panels") == ["B1"]:
            add("absorption", primary[5].get("file"), by_pair[pair["ev"], pair["iv"]])
        individuals = [d for k, d in datasets.items() if k in board_ids and d["card"].get("record_level") == "INDIVIDUAL"
                       and len(d["series"]) > 1 and d.get("A1ind")]
        for d in individuals:
            rows = [[s["label"], fmt(m.get("n_quantified")), fmt(m.get("n_before_peak")), fmt(m.get("tmax")), fmt(m.get("cmax"))]
                    for s in d["series"] for m in [s["metrics"]] if m.get("tmax") is not None]
            note = block("Sampling and observed peaks by animal", "For each animal, peak time is the time of its highest measured concentration. Pre-peak counts use that animal’s sampling record.", "",
                         ["Animal", "Quantifiable samples", "Pre-peak samples", "Peak time (h)", f"Peak concentration ({d['card'].get('unit', '')})"], rows)
            for key in ("A1ind", "B1ind"):
                add("absorption", d.get(key), note)
            if len(individuals) == 1 and "A1ind" in primary.get(9, {}).get("panels", []):
                add("absorption", primary[9].get("file"), note)
    return by_pair


def distribution_notes(data, add, tails):
    owners = {s["sid"]: s["dataset_id"] for s in data.get("series", [])}
    for b in data.get("boards", []):
        figs = b.get("figs", {})
        for r in b.get("route_pairs", []):
            add("distribution", r.get("file"), tails.get((owners.get(r["ev"]), owners.get(r["iv"])), ""))
        for pair in b.get("tissue_pairs", []):
            file = figs.get("DIS4b|" + pair["tissue_sid"])
            if not file:
                continue
            reference = pair.get("ref_label") or "reference matrix"
            change = pair.get("dis4b") or {}
            finding = ""
            if change.get("fold_ci"):
                finding = (f"The ratio at {fmt(change['t_late'])} h was {fmt(change['fold'])} times the ratio at {fmt(change['t_early'])} h "
                           f"(conditional interval {interval(change['fold_ci'])}). This interval uses the variation of four group means and Welch degrees of freedom, assuming zero covariance across matrices and times.")
            rows = [[fmt(r["t"]), fmt(r.get("tissue")), fmt(r.get("ref")), fmt(r.get("ratio"))] for r in pair["rows"]]
            basis = " Concentrations reflect antimicrobial activity measured by bioassay." if pair.get("analyte") == "ACTIVE_MATERIAL" else ""
            add("distribution", file, block("Matched concentrations and ratios", f"At each time, the tissue or fluid concentration was divided by the concurrent {reference} concentration.{basis}", finding,
                ["Time (h)", f"{pair['tissue']} ({pair['unit']})", f"{reference} ({pair['ref_unit']})", f"Ratio ({pair['ratio_unit']})"], rows))
            for t in b.get("prespecified_ratio_tests", []):
                if t["status"] != "ASSESSED" or not any(o["tissue_sid"] == pair["tissue_sid"] and o["plasma_sid"] == pair["ref_sid"]
                                                        for o in t["observations"]):
                    continue
                method = "A paired t test within animals" if t["design"] == "LONGITUDINAL_PAIRED" else "Welch’s t test for independent animal groups"
                add("distribution", file, block("Prespecified change in the tissue/plasma ratio",
                    f"{method} compared log tissue/plasma ratios at two prespecified times. The full comparison included {t['n_early']} animals at the earlier time and {t['n_late']} at the later time.",
                    f"Late/early ratio {fmt(t['fold_change'])} (adjusted interval {interval(t['ci_fold'])}), raw p = {p_value(t['p_raw'])}, "
                    f"Bonferroni-adjusted p = {p_value(t['p_adjusted'])} across {t['family_size']} prespecified comparisons.", statistical=True))
        for d in b.get("dose_patterns", []):
            rows = [[fmt(r["t"]), fmt(r.get("ratio")), p_value(r["p"]), p_value(r["holm_p"])] for r in d.get("rows", []) if "holm_p" in r]
            if rows:
                add("distribution", figs.get("DIS2|" + d["key"]), block("IV dose comparison at matched times",
                    "At each time, Welch’s approximation compares high- and low-dose concentrations after dose normalization. Holm adjustment accounts for testing multiple times.", "",
                    ["Time (h)", "Dose-normalized concentration ratio", "Raw p", "Holm-adjusted p"], rows, statistical=True))


def elimination_notes(data, add):
    for b in data.get("boards", []):
        for u in b.get("urine", []):
            file = b["figs"].get("EM5a|" + u["dataset_id"])
            rows = [[fmt(c["t"]), fmt(c["value"])] for c in u["cumulative"]]
            if not file or not rows:
                continue
            description = f"For {u['group']}, each point gives cumulative urinary recovery through the end of collection as a percentage of the {u['denominator']}."
            finding = "The assay measures antimicrobial activity equivalents." if u["analyte"] == "ACTIVE_MATERIAL" else ""
            for rec in u.get("reconciliations", []):
                if "does not reconcile" in str(rec.get("status", "")):
                    finding += (f" Over {time_window(rec['interval'])}, the interval recoveries sum to {fmt(rec['sum_of_increments'])}%. "
                                f"The source table gives a total of {fmt(rec['printed'])}%.")
            add("elimination", file, block("Observed urinary recovery", description, finding.strip(), ["Collection end (h)", "Cumulative recovery (%)"], rows))
        test = b.get("renal_filtration_comparison") or {}
        if test.get("status") == "TESTED":
            add("elimination", b["figs"].get("EM5c|board"), block("Renal clearance relative to filtration",
                f"Over {time_window(test['interval_h'])}, each animal’s renal clearance was divided by its unbound fraction × glomerular filtration rate. A two-sided exact sign test compared the population median ratio with 1.",
                f"Median ratio {fmt(test['median_ratio'])} across {test['n_animals']} animals. Ratios above / below / equal to 1: "
                f"{test['above']} / {test['below']} / {test['ties']}, p = {p_value(test['p'])}.", statistical=True))


def figure_readings(root):
    notes = defaultdict(list)

    def add(stage, file, html):
        if file and html:
            key = posixpath.normpath(posixpath.join(stage, file))
            if html not in notes[key]:
                notes[key].append(html)

    results = {}
    for stage in ("absorption", "distribution", "elimination"):
        path = root / stage / (stage + ".json")
        if path.is_file():
            results[stage] = json.loads(path.read_text(encoding="utf-8-sig"))
    tails = absorption_notes(results["absorption"], add) if "absorption" in results else {}
    if "distribution" in results:
        distribution_notes(results["distribution"], add, tails)
    if "elimination" in results:
        elimination_notes(results["elimination"], add)
    return {k: "".join(v) for k, v in notes.items()}


# Insert around the native image link, preserving the original HTML and figure captions byte-for-byte.
_START, _END = "<!--eda-figure-reading-->", "<!--/eda-figure-reading-->"
_GENERATED = re.compile(re.escape(_START) + ".*?" + re.escape(_END), re.S)
_STYLE = """<style>.image-reading{min-width:0;max-width:100%}.fthumbs>.image-reading{flex:1 1 460px}
.fthumbs>.image-reading>a{width:min(100%,460px)}.fig-reading{font:inherit;font-size:14px;line-height:1.55;
color:#243b40;background:#f5f8f7;padding:8px 12px;border-left:3px solid #76978c;margin:6px 0}
.fig-reading p{margin:3px 0}.fig-reading .scroll{overflow-x:auto}.fig-reading table{border-collapse:collapse;
font-size:13px;width:100%}.fig-reading td,.fig-reading th{text-align:left;padding:4px 7px;border-bottom:1px solid #cfdbd6}
.fig-reading th{background:#e8efeb}.image-reading>details>summary{cursor:pointer;color:#075b64}</style>"""


class ImageLinks(HTMLParser):
    def __init__(self, source, folder, readings):
        super().__init__()
        self.starts = [0, *(m.end() for m in re.finditer("\n", source))]
        self.anchor = self.note = None
        self.edits = []
        self.folder, self.readings = folder, readings

    def char_index(self):
        line, col = self.getpos()
        return self.starts[line - 1] + col

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.anchor, self.note = self.char_index(), None
        elif tag == "img" and self.anchor is not None:
            url = urlsplit(dict(attrs).get("src", ""))
            if not (url.scheme or url.netloc):
                self.note = self.readings.get(posixpath.normpath(posixpath.join(self.folder, unquote(url.path))))

    def handle_endtag(self, tag):
        if tag == "a" and self.anchor is not None:
            if self.note:
                self.edits.append((self.anchor, self.char_index(), self.note))
            self.anchor = self.note = None


def annotate(source, folder, readings):
    source = _GENERATED.sub("", source)
    links = ImageLinks(source, folder, readings)
    links.feed(source)
    links.close()
    if not links.edits:
        return source
    pieces, previous = [], 0
    for start, close, note in links.edits:
        end = source.index(">", close) + 1
        if folder == "figures":
            note = '<details lang="en"><summary>Methods, results and data for this figure</summary>' + note + "</details>"
        pieces.extend([source[previous:start], _START + '<div class="image-reading">' + _END,
                       source[start:end], _START + note + "</div>" + _END])
        previous = end
    html = "".join(pieces) + source[previous:]
    return html.replace("</head>", _START + _STYLE + _END + "</head>", 1)


def publish(root):
    readings = figure_readings(root)
    pages = [p for stage in ("absorption", "distribution", "elimination") for p in (root / stage).glob("species-*.html")]
    gallery = root / "figures/index.html"
    if gallery.is_file():
        pages.append(gallery)
    for page in pages:
        old = page.read_text(encoding="utf8")
        new = annotate(old, page.parent.name, readings)
        if new != old:
            page.write_text(new, encoding="utf8")
    return len(readings)
