"""Select one figure-led modeling comparison per species from native EDA results."""
import argparse
from html import escape
import json
from pathlib import Path


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def question_figure(board, number):
    question = next((q for q in board["questions"] if q["q"] == number), {})
    return (question.get("primary") or {}).get("file")


def figures(stage, *names):
    return [f"{stage}/{name}" for name in dict.fromkeys(names) if name]


def finding(priority, board, supports, alternative, check, plots, ids):
    return priority, {"species": board["species"].capitalize(), "study": board["study"],
                      "supports": supports, "still_possible": alternative, "next_check": check,
                      "figures": plots, "source_ids": sorted(set(ids))}


def dose_pattern(board, series, datasets, route_pairs):
    rows = sorted(series.get("rows", []), key=lambda r: r["dose"])
    points = sorted((p for p in series.get("per_time", []) if p.get("ratio") is not None), key=lambda p: p["t"])
    if len(rows) < 2 or len(points) < 2 or rows[0].get("tmax") is None or series.get("R_window") is None:
        return
    peak = min(points, key=lambda p: abs(p["t"] - rows[0]["tmax"]))
    late = [p for p in points if p["t"] > max(r["tmax"] for r in rows if r.get("tmax") is not None)]
    if not late:
        return
    tail = late[-2] if len(late) >= 2 else late[-1]
    ratios = [p["ratio"] for p in points]
    if 0.8 <= series["R_window"] <= 1.25 and min(ratios) >= 0.8 and max(ratios) <= 1.25:
        return
    hi, lo = rows[-1]["dose"], rows[0]["dose"]
    cards = [datasets[k]["card"] for k in series["dataset_ids"]]
    routes = "/".join(sorted({str(c["route_detail"]) for c in cards}))
    condition = series.get("condition")
    description = " in the " + condition + " condition" if condition and condition != "not reported" else ""
    level = "group-mean " if all(c["record_level"] == "GROUP_MEAN" for c in cards) else ""
    observation = (f"At {hi:g} versus {lo:g} mg/kg {routes}{description}, the {level}AUC/dose ratio over 0–{series['window_end_h']:g} h was {series['R_window']:.2f}. "
                   f"The concentration/dose ratio was {peak['ratio']:.2f} at {peak['t']:g} h and {tail['ratio']:.2f} at {tail['t']:g} h.")
    coverage = series.get("dispersion_coverage") or {}
    if coverage.get("with_se", 0) and coverage["with_se"] < coverage["points"]:
        observation += f" SE was available at {coverage['with_se']}/{coverage['points']} concentration points."
    if series.get("e6_label") == "INCONCLUSIVE":
        observation += " The area ratio alone is inconclusive."
    iv_doses = {p["dose_iv"] for p in route_pairs if p["ev"] in series["dataset_ids"] and p.get("dose_iv")}
    next_check = "Test constant scaling by F first. Compare input rate with nonlinear disposition only if peak and late residuals diverge."
    if len(iv_doses) == 1:
        next_check += f" IV covers only {next(iter(iv_doses)):g} mg/kg. Check additional IV concentration ranges."
    return finding("dose_overlay", board, observation,
                   "F, input rate and clearance remain alternatives, including dose-proportional PK with sampling variation.",
                   next_check,
                   figures("absorption", series.get("C1"), series.get("C3d")), series["dataset_ids"])


def rebound(board, dataset):
    card, series = dataset["card"], dataset["series"]
    if card["record_level"] != "INDIVIDUAL":
        return
    hits = [s for s in series if (s.get("t2") or {}).get("valley")]
    if not hits:
        return
    stable = [s for s in hits if s["t2"].get("robust") and s["t2"]["t2_label"].startswith("EXCLUDED")]
    example = (stable or hits)[0]
    route = card["route_detail"]
    peaks = [s["metrics"]["tmax"] for s in series if s["metrics"].get("tmax") is not None]
    onset = f"Sampled peaks after {route} dosing occurred at {min(peaks):.3g}–{max(peaks):.3g} h. " if peaks else ""
    terminal = [s["metrics"].get("terminal_selected") for s in series]
    halves = [t["thalf"] for t in terminal if t and t.get("thalf")]
    if len(halves) == len(series):
        onset += f"The apparent terminal half-lives spanned {min(halves):.3g}–{max(halves):.3g} h. "
    elif not halves:
        onset += "No post-peak window qualified for a terminal half-life. "
    retained = f"{len(stable)} met the within-animal rebound criterion" if stable else "the rises were sensitive to deleting a sample"
    support = onset + f"{len(hits)}/{len(series)} profiles dipped then rose. " + retained.capitalize() + "."
    rival = ("A second input episode or recirculation could produce a reproducible rebound." if stable else
             "A second input episode remains possible; sampling variation around a single input could explain the dip.")
    check = ("Compare a single smooth input with a delayed second input using individual peak-region residuals and leave-one-animal-out fits."
             if stable else "Start with one input. Recheck individual measurements bracketing the dip before adding a delayed second input.")
    if not stable and route == "SC":
        rival = "Slow depot release and variation in late low concentrations remain plausible."
        check = "Check late concentrations against assay precision and dose times before comparing one depot with delayed additional input."
    sensitivity = card.get("modeling_evidence", {}).get("low_concentration_sensitivity")
    if sensitivity:
        checks = [s["t2"]["low_concentration_sensitivity"] for s in series if (s.get("t2") or {}).get("low_concentration_sensitivity")]
        assessable = [s for s in checks if s["evaluable"]]
        if assessable:
            support = (onset + f"{len(hits)}/{len(series)} profiles dipped then rose. Omitting values below "
                       f"{sensitivity['value']:g} {sensitivity['unit']} in a sensitivity check left "
                       f"{sum(s['has_valley'] for s in assessable)}/{len(assessable)} evaluable profiles with a dip.")
            if not stable and route == "SC":
                rival = "Slow depot release or slow systemic disposition can explain the long SC tail."
                check = "Keep the measured values in the primary fit. Use IV disposition or an independently characterized formulation to distinguish release from elimination."
    if card.get("analyte_role") == "ASSAY_EQUIVALENTS":
        support += " Concentrations are assay equivalents."
    return finding("replicated_individual_rebound" if len(stable) >= 2 else "individual_rebound" if stable else "unconfirmed_rebound", board, support, rival, check,
                   figures("absorption", dataset.get("A1ind"), example.get("T2")), [card["dataset_id"]])


def terminal_pattern(board, pair, datasets, references, iv_board):
    tail = pair.get("tail") or {}
    if not tail.get("test"):
        return
    ev = datasets[pair["ev"]]
    if len(ev["series"]) != 1 or pair["iv"] not in references:
        return
    em = ev["series"][0]["metrics"]["terminal_selected"]
    im = references[pair["iv"]]["metrics"]["terminal_selected"]
    ew, iw = tail["ev_window_h"], tail["iv_window_h"]
    support = (f"{ev['card']['route_detail']} and IV apparent half-lives were {em['thalf']:.3g} h ({ew[0]:g}–{ew[1]:g} h) "
               f"and {im['thalf']:.3g} h ({iw[0]:g}–{iw[1]:g} h).")
    activity = iv_board and any(v.get("analyte") == "ACTIVE_MATERIAL" and v["dataset_id"] == pair["iv"]
                                for v in iv_board.get("item24", []))
    if activity:
        support += " The assay measured antimicrobial activity."
    slower = tail["class"] in ("SLOWER", "SLOWER_NOT_SEPARATED")
    common = tail.get("common_tail") or {}
    if slower:
        comparable = bool(pair.get("dose_ev") and pair["dose_ev"] == pair.get("dose_iv") and common.get("corroborates_slower_ev"))
        priority = "separated_route_slopes" if comparable else "sensitive_shape"
        if common.get("window_h") and common["window_h"][0] == common["window_h"][-1]:
            support += f" The selected windows meet only at {common['window_h'][0]:g} h."
        elif common.get("ratio") and common.get("test"):
            support += f" On their overlap the half-life ratio was {common['ratio']:.2f} (nominal p={common['test']['p']:.2g})."
        rival = "Slow absorption (flip-flop) and an incompletely sampled disposition phase could both explain the slower extravascular decline."
        if comparable:
            check = "Compare shared IV/EV disposition with faster versus absorption-limited input; check whether both peak and late residuals improve."
        elif common.get("n_iv", 0) < 3 or common.get("n_ev", 0) < 3:
            check = "Seek quantifiable late samples for a common terminal interval before attributing the slope difference to slow input."
        elif common.get("test") and pair.get("dose_ev") == pair.get("dose_iv"):
            check = "The common-window result did not meet the slow-input criterion. Start with shared disposition and inspect peak and tail residuals."
        else:
            check = "Check dose-matched common late windows before fitting a slow-input alternative."
    else:
        priority = "route_reference"
        rival = "Disposition can explain the tail; earlier absorption or an unresolved distribution phase remains possible."
        check = "Use the IV profile to constrain disposition and compare early extravascular residuals before adding input complexity."
    if activity:
        check += " Verify parent specificity for parent PK."
    unit = ev["card"].get("experimental_unit", "").lower()
    if "terminal cohorts by sampling time" in unit:
        support += " Different animals contributed each time-point mean."
    elif "serially sampled cohort" in unit:
        support += " These are means from serially sampled animals."
    plots = figures("absorption", pair.get("D1") or question_figure(board, 5))
    if not pair.get("D1") and iv_board:
        plots += figures("distribution", question_figure(iv_board, 1))
    return finding(priority, board, support, rival, check, plots, [pair["ev"], pair["iv"]])


def iv_pattern(board, rebounds):
    rows = [r for r in board.get("item24", []) if r.get("curvature") == "FLATTENING"]
    if not rows:
        return
    robust = [r for r in rows if r.get("curvature_support") == "ROBUST"]
    sample = (robust or rows)[0]
    group = [r for r in board["item24"] if r["dataset_id"] == sample["dataset_id"]]
    stable = sum(r in robust for r in group)
    if sample.get("analysis_unit") == "INDIVIDUAL":
        observation = f"{stable}/{len(group)} individual IV profiles retained a steep early and slower late decline after endpoint deletion."
    else:
        observation = ("The mean IV curve declined steeply at first and more slowly later. "
                       + ("This bend survived endpoint deletion." if stable else "The bend depended on endpoint selection."))
        if sample.get("slope_ratio"):
            observation += f" The early/late slope magnitude ratio was {sample['slope_ratio']:.2g}."
    plots = figures("distribution", question_figure(board, 1), question_figure(board, 4))
    ids = [sample["dataset_id"]]
    rival = "One disposition compartment may suffice; a second can account for the slower late phase."
    check = "Compare one versus two compartments on the same IV points and inspect early and late residuals before fitting extravascular input."
    # Link an independent input observation only when the distribution board actually includes its source table.
    weak_input = next(((v, d) for (p, v), d in rebounds if p == "unconfirmed_rebound" and v["study"] == board["study"]
                       and v["species"] == board["species"].capitalize() and set(v["source_ids"]) <= set(board["datasets"])), None)
    if weak_input and stable >= 2:
        weak, dataset = weak_input
        curves = dataset["series"]
        seen = sum(bool((s.get("t2") or {}).get("valley")) for s in curves)
        observation += f" After {dataset['card']['route_detail']} dosing, {seen}/{len(curves)} profiles dipped then rose; none passed the deletion check."
        rival = "A single delayed input (lag or transit) and a second input remain open for the extravascular profiles."
        check += " Add a second input only for reproducible within-animal rebounds."
        plots += weak["figures"][-1:]
        ids += weak["source_ids"]
    elif not stable:
        check = "Refit the IV curve with and without the influential endpoints. Add a second compartment only if early and late residual patterns persist."
    return finding("replicated_iv_curvature" if stable >= 2 and sample.get("analysis_unit") == "INDIVIDUAL" else
                   "stable_iv_curvature" if stable else "sensitive_shape", board, observation, rival, check, plots, ids)


def renal_qualification(row, board, series):
    """A separate source-table lead, never an inferred plasma/urine pairing."""
    urine = board.get("urine", [])
    conflict = next((u for u in urine if "SOURCE_CONFLICT" in u.get("flags", []) and u.get("reconcile")), None)
    if conflict:
        rec = conflict["reconcile"]
        start, end = rec["interval"]
        note = (f"{conflict['route']} urine recovery at {start:g}–{end:g} h was printed as {rec['printed']:g}% "
                f"and sums to {rec['sum_of_increments']:g}% by interval. Resolve the discrepancy before using renal recovery.")
        ids = [conflict["dataset_id"]]
    elif series and series.get("condition") and series.get("occasion") in (None, "SINGLE_DOSE"):
        condition = series["condition"].lower()
        matched = [u for u in urine if u.get("analyte") == "PARENT" and u.get("route") == "EV"
                   and u.get("occasion") == "FIRST_DOSE" and u.get("dose") in series["doses"]
                   and condition in u.get("group", "").lower().split()]
        if sorted(u["dose"] for u in matched) != sorted(series["doses"]):
            return
        common = set.intersection(*[{tuple(p["interval"]) for p in u["printed_totals"]} for u in matched])
        windows = [w for w in common if w[0] == 0]
        if not windows:
            return
        window = min(windows, key=lambda w: abs(w[1] - series["window_end_h"]))
        ordered = sorted(matched, key=lambda u: u["dose"])
        values = [next(p["value"] for p in u["printed_totals"] if tuple(p["interval"]) == window) for u in ordered]
        note = (f"Urinary parent recovery at {window[1]:g} h was " + ", ".join(f"{v:g}%" for v in values)
                + " at " + ", ".join(f"{u['dose']:g}" for u in ordered)
                + " mg/kg, respectively. Verify cohort, collection and plasma window before estimating renal clearance.")
        ids = [u["dataset_id"] for u in ordered]
    else:
        return
    row["supporting_table"] = {"observation": note, "source_ids": ids,
                               "page": "elimination/species-" + board["species"].lower() + ".html#q-" + board["key"] + "-5"}


def evidence_for_case(root):
    rules = read(Path(__file__).with_name("eda_modeling_rules.json"))
    rank = {kind: i for i, kind in enumerate(rules["priority_order"])}
    ab, dist, elim = [read(root / module / (module + ".json")) for module in ("absorption", "distribution", "elimination")]
    datasets = {d["card"]["dataset_id"]: d for d in ab["datasets"]}
    refs = {r["card"]["dataset_id"]: r for r in ab["iv_references"]}
    options, rebounds = [], []
    for b in ab["status_boards"]:
        keys = set(b["datasets"])
        for d in (datasets[k] for k in sorted(keys & datasets.keys())):
            if not d["card"]["tests_allowed"]:
                continue
            r = rebound(b, d)
            if r:
                options.append(r)
                rebounds.append((r, d))
            s = next((s for s in d["series"] if s["metrics"].get("tmax") is not None), None)
            if s:
                m = s["metrics"]
                options.append(finding("sampled_peak", b, f"The {d['card']['route_detail']} profile for {s['label']} reached its sampled peak at {m['tmax']:g} h; the first quantified point was at {m['first_t']:g} h.",
                    "Immediate and delayed input can give similar sampled peaks.",
                    "Check the rise with earlier samples and compare residuals around the peak under shared disposition.",
                    figures("absorption", s.get("A1")), [d["card"]["dataset_id"]]))
        for x in ab["dose_series"]:
            if x.get("dataset_ids") and set(x["dataset_ids"]) <= keys and x.get("status") == "ASSESSED":
                options.append(dose_pattern(b, x, datasets, ab["ev_iv"]))
        for pair in ab["ev_iv"]:
            if pair["ev"] in keys and pair["ev"] in datasets:
                iv_board = next((db for db in dist["boards"] if db["study"] == b["study"]
                                 and db["species"].casefold() == b["species"].casefold()
                                 and any(v["dataset_id"] == pair["iv"] for v in db.get("item24", []))), None)
                options.append(terminal_pattern(b, pair, datasets, refs, iv_board))
    for b in dist["boards"]:
        options.append(iv_pattern(b, rebounds))
    boards = ab["status_boards"] + dist["boards"] + elim["boards"]
    species = sorted({b["species"].capitalize() for b in boards})
    result = []
    for sp in species:
        candidates = sorted((x for x in options if x and x[1]["species"] == sp),
                            key=lambda x: (rank[x[0]], x[1]["study"], x[1]["source_ids"]))
        if candidates:
            row = candidates[0][1]
            for key in row["source_ids"]:
                notes = datasets.get(key, {}).get("card", {}).get("modeling_evidence", {})
                if notes.get("comparator"):
                    row["paper_comparator"] = notes["comparator"]
                if notes.get("low_concentration_sensitivity"):
                    limit = notes["low_concentration_sensitivity"]
                    row["sensitivity_source"] = {k: limit[k] for k in ("source", "location")}
            series = next((s for s in ab["dose_series"] if s.get("dataset_ids")
                           and set(s["dataset_ids"]) == set(row["source_ids"])), None)
            eb = next((b for b in elim["boards"] if b["study"] == row["study"]
                       and b["species"].capitalize() == sp and set(row["source_ids"]) & set(b["datasets"])), None)
            if eb is None:
                # A conflicting tabulated total is relevant even when parent plasma was gated by assay.
                # Keep the table independent of the plasma profiles; it supplies no paired renal estimate.
                eb = next((b for b in elim["boards"] if b["study"] == row["study"] and b["species"].capitalize() == sp
                           and any("SOURCE_CONFLICT" in u.get("flags", []) for u in b.get("urine", []))), None)
            if eb:
                renal_qualification(row, eb, series)
        else:
            source = next(b for b in boards if b["species"].capitalize() == sp)
            row = finding(99, source, "No evaluable systemic time-course contrast was available in this scope.",
                          "Input and disposition remain unresolved.", "Obtain timed systemic concentrations and verify the dosing history.",
                          [], source.get("datasets", [])[:1])[1]
        result.append(row)
    drug = next((d["card"]["drug"] for d in datasets.values() if d["card"].get("drug")), root.name)
    return {"schema": rules["version"], "drug": str(drug).capitalize(), "species": result}


def write_handoff(root):
    context = evidence_for_case(root)
    for row in context["species"]:
        for plot in row["figures"]:
            if not (root / plot).is_file():
                raise FileNotFoundError(root / plot)
    (root / "modeling_context.json").write_text(json.dumps(context, indent=2, ensure_ascii=False), encoding="utf-8")
    return context


def collection_page(root):
    sections = []
    for path in sorted(root.glob("*/modeling_context.json")):
        context = read(path)
        prefix = path.parent.name + "/"
        sections.append(f'<h2>{escape(context["drug"])}</h2><p><a href="{escape(prefix)}index.html">Full EDA</a> · '
                        f'<a href="{escape(prefix)}modeling_context.json">Modeling context JSON</a></p>')
        for row in context["species"]:
            refs = " · ".join(f'<a href="{escape(prefix + path)}">Figure {i}</a>' for i, path in enumerate(row["figures"], 1))
            table = row.get("supporting_table")
            extra = (f'<p><a href="{escape(prefix + table["page"])}">Recovery table</a> · {escape(table["observation"])}</p>' if table else "")
            paper = row.get("paper_comparator") or row.get("sensitivity_source")
            if paper:
                extra += f'<p>{escape(paper.get("text", ""))} <a href="{escape(paper["source"])}">{escape(paper["location"])}</a></p>'
            sections.append(f'<section><h3>{escape(row["species"])}</h3><p>{escape(row["supports"])}</p>'
                            f'<p><b>Still possible.</b> {escape(row["still_possible"])}</p><p><b>Next check.</b> {escape(row["next_check"])}</p>'
                            f'{extra}<small>{escape(row["study"])} · {refs}</small></section>')
    if not sections:
        raise ValueError("No case modeling contexts found")
    (root / "index.html").write_text('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>Species modeling handoff</title><style>body{max-width:780px;margin:2em auto;padding:0 1em;font:17px/1.5 system-ui;color:#223843}'
        'section{padding:0 0 1em;border-bottom:1px solid #d2dada}p{margin:.45em 0}h2{margin-top:1.7em}a{color:#075e67}</style>'
        '<main><h1>Species modeling handoff</h1>' + "".join(sections) + '</main></html>', encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build a collection index from published modeling contexts")
    parser.add_argument("collection", type=Path)
    collection_page(parser.parse_args().collection)
