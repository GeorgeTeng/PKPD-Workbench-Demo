"""EDA Absorption section: S02 (PMB retry_024) numbers must match the r4 trial
(eda-part/absorption_r4/trial_retry024/r4_trial_out.json, 2026-11-04)."""
import json

import pytest

from research_pipeline import eda_absorption as ab

S02 = {2: [(0.2487, 1.6719), (0.5181, 2.7502), (0.9948, 2.5882), (1.513, 1.4807), (2.0104, 0.8679), (2.9845, 0.3492), (4, 0.2228), (5.0155, 0.1665)],
       4: [(0.5181, 4.866), (0.9948, 5.4278), (1.513, 4.3623), (2.0104, 2.8178), (2.9845, 1.3114), (4, 0.9681), (5.0155, 0.8893), (6.0104, 0.3991)],
       8: [(0.5181, 8.0046), (0.9948, 10.0813), (2.0104, 5.9814), (2.9845, 3.7709), (4, 1.9816), (6.0104, 1.12), (8, 0.5957)],
       16: [(0.5181, 9.4875), (0.9948, 15.9907), (2.0104, 11.2452), (2.9845, 10.0813), (4, 7.4423), (6.0104, 2.6842), (8, 2.2924), (10.0104, 1.5734)],
       32: [(0.5181, 13.9917), (0.9948, 19.1846), (2.0104, 17.1989), (4, 13.0087), (6.0104, 8.7146), (8, 6.672), (10.0104, 4.866), (11.9793, 2.2924)]}
IDS = {2: "T0028", 4: "T0029", 8: "T0030", 16: "T0031", 32: "T0032"}

# trial values: (Tmax, Cmax/D, max M_T1, split ratio, selected window start, apparent t1/2, AUC0-4h/D)
TRIAL = {2: (0.5181, 1.37510, -0.026948, 0.338956, 0.9948, 1.0035, 2.257232),
         4: (0.9948, 1.35695, -0.085681, 0.541019, 1.513, 1.4541, 2.766),
         8: (0.9948, 1.26016, -0.125, 0.54, 2.0104, 1.8311, 2.732),
         16: (0.9948, 0.99942, -0.152, 0.64, 2.0104, 2.6047, 2.589),
         32: (0.9948, 0.59952, -0.329, 1.58, 2.0104, 3.6443, 1.870)}


def _entry(dose, pts):
    return {"dataset_id": IDS[dose], "title": f"S02 Figure 1: SC {dose} mg/kg plasma mean concentrations (digitized)",
            "study_source_ids": ["S02"], "role": "PK_OBSERVATIONS",
            "experimental_unit": "Observed mean symbols digitized from the published figure",
            "columns": [{"id": "c002_time_h", "meaning": "TIME", "unit": "h"},
                        {"id": "c003_mean", "meaning": "CONCENTRATION", "unit": "mg/L", "header": "Mean"}],
            "records": [{"record_id": f"R{i}", "time_h": t, "c002_time_h": t, "c003_mean": c, "qc_status": "TECHNICALLY_RETAINED",
                         "value_status": {"c002_time_h": "QUANTIFIED", "c003_mean": "QUANTIFIED"}} for i, (t, c) in enumerate(pts)],
            "notes": "Source states 3 or 4 mice/time",
            "metadata": {"species": "neutropenic thigh-infected mice", "matrix": "plasma", "drug": "PMB", "route_class": "EV",
                         "route_detail": "SC", "matrix_category": "PLASMA_SERUM_BLOOD", "record_category": "GROUP_SUMMARY",
                         "observation_source": "DIGITIZED_FROM_FIGURE", "dose_basis": "PMB sulphate", "dosing_regimen": "Single SC dose"}}


@pytest.fixture()
def run(tmp_path):
    (tmp_path / "source_tables.json").write_text(json.dumps([_entry(d, p) for d, p in S02.items()]), encoding="utf-8")
    (tmp_path / "report.html").write_text('<html lang="en"><meta charset="utf-8"><h1>EDA</h1></html>', encoding="utf-8")
    return tmp_path


def test_s02_matches_r4_trial(run):
    res = ab.build(run)
    by = {d["card"]["dataset_id"]: d["series"][0]["metrics"] for d in res["datasets"]}
    ds = res["dose_series"][0]
    assert ds["window_end_h"] == 4
    for dose, (tmax, cmax_d, mt1, split, start, thalf, aucw) in TRIAL.items():
        m = by[IDS[dose]]
        assert m["tmax"] == pytest.approx(tmax)
        assert m["cmax"] / dose == pytest.approx(cmax_d, rel=1e-4)
        assert m["mt1"] == pytest.approx(mt1, abs=2e-3)
        assert m["t1_label"] == "NOT_EXCLUDED" and "SENSITIVITY_ONLY" in m["t1_flags"]
        assert m["onset_status"] == "ONSET_NOT_OBSERVED"
        assert "KA_NOT_IDENTIFIABLE" in m["caveats"] and "LATE_FIRST_SAMPLE" in m["caveats"]
        assert m["split"]["ratio"] == pytest.approx(split, abs=6e-3)
        assert m["terminal_selected"]["start"] == pytest.approx(start, abs=1e-3)
        assert m["terminal_selected"]["thalf"] == pytest.approx(thalf, abs=1e-3)
        row = next(r for r in ds["rows"] if r["dose"] == dose)
        assert row["aucW_d"] == pytest.approx(aucw, abs=1e-3)
    assert by["T0032"]["split"]["class"] == "DECLINE_STEEPENS"
    assert ds["R_window"] == pytest.approx(0.829, abs=1e-3) and ds["e6_label"] == "NO_SIGN"
    assert ds["cmax_d_ratio"] == pytest.approx(0.436, abs=1e-3) and ds["cmax_label"] == "POINTS_TO_NONLINEARITY"
    assert ds["t3_label"] == "CANNOT_ASSESS"


def test_status_board_and_report(run):
    ab.attach(run)
    ab.attach(run)  # idempotent
    res = json.loads((run / "absorption" / "absorption.json").read_text(encoding="utf-8"))
    b = res["status_boards"][0]
    rows = b["rows"]
    # draft A0.11: Q4 and Q5 on group means are partly answerable as descriptions (dip search, terminal window, split halves)
    assert rows["4"][0] == ab.ST_PART and rows["5"][0] == ab.ST_PART and rows["6"][0] == ab.ST_NO
    assert rows["7"][0] == ab.ST_PART and rows["8"][0] == ab.ST_NA and rows["9"][0] == ab.ST_NO
    assert {k: v for k, v in b["status_codes"].items()} == {str(q["q"]): q["status_code"] for q in b["questions"]}
    html = (run / "report.html").read_text(encoding="utf-8")
    assert html.count('<section id="absorption"') == 1 and 'href="absorption/index.html"' in html
    assert 'href="absorption/species-mouse.html#study-s02"' in html and "not answerable yet Q6, Q9" in html
    # overview: one card per species, then the nine questions of every study
    pres = res["presentation"]
    assert [x["species"] for x in pres["species"]] == ["Mouse"] and pres["species"][0]["page"] == "species-mouse.html"
    overview = (run / "absorption" / "index.html").read_text(encoding="utf-8")
    assert overview.count('class="category"') == 1 and 'href="species-mouse.html"' in overview
    assert all(f'href="species-mouse.html#q-s02-{n}"' in overview for n in range(1, 10)) and "<figure" not in overview
    assert '<a href="../report.html#absorption">← EDA report</a>' in overview  # no portal yet
    # species page: species → study → data card → nine question rows
    page = (run / "absorption" / "species-mouse.html").read_text(encoding="utf-8")
    assert page.count('class="panel study"') == 1 and page.count('class="qrow"') == 9
    assert all(f'id="q-s02-{n}"' in page for n in range(1, 10)) and '<a href="index.html">← All species</a>' in page
    qs = {q["q"]: q for q in b["questions"]}
    assert [q["q"] for q in b["questions"]] == list(range(1, 10))
    for q in qs.values():  # three-part conclusion; the primary evidence only when the question can be answered at least in part
        assert q["observed"] and q["text"].startswith(q["observed"])
        if q["status"] in (ab.ST_NO, ab.ST_NA):
            assert not q["primary"] or q["primary"]["kind"] == "row"
    for n in (1, 2, 3, 4, 5, 7):
        pr = qs[n]["primary"]
        assert pr["kind"] == "panel" and (run / "absorption" / pr["file"]).exists() and pr["lines"][0].startswith(f"Answers Q{n}")
        assert "Group mean of different animals" in pr["level"] and f'src="{pr["file"]}"' in page
    assert qs[1]["observed"].startswith("Drug was already quantified at the first sample of all 5 curves")
    assert "0.249–0.518 h" in qs[1]["observed"] and qs[1]["missing"][:2] == ["a sample before 0.249 h", "a predose sample"]
    assert qs[3]["primary"]["panels"] == ["A2"] and qs[4]["primary"]["panels"] == ["B1"]
    assert "Cmax/D at 32 mg/kg is 0.44×" in qs[7]["observed"] and qs[7]["primary"]["panels"] == ["C1"]
    assert qs[9]["primary"]["kind"] == "row" and "different animals at each time" in str(qs[9]["primary"]["rows"])
    assert qs[6]["primary"] is None and "NOT_ESTIMABLE" in qs[6]["text"]
    # other panels open from the row by tier; every row keeps its evidence (rule, numbers, source points)
    assert {v["panel"] for v in qs[5]["views"]} >= {"B1", "B2"} and {v["tier"] for v in qs[5]["views"]} == {1, 3}
    ev = b["evidence"]
    assert sorted(ev, key=int) == [str(q) for q in range(1, 10)]
    assert all(p["rule"] and p["tables"] and p["data"] for parts in ev.values() for p in parts)
    q7 = {r[0]: r for t in ev["7"][0]["tables"] for r in t["rows"]}
    assert q7["E6 · AUC/D ratio over the window"][1:4:2] == ["0.829", "NO_SIGN"]
    q1 = next(r for r in ev["1"][0]["tables"][0]["rows"] if r[0] == "T0032")
    assert q1[2] == "0.518" and q1[6] == "ONSET_NOT_OBSERVED"
    assert page.count('<details class="evi">') == 9 and page.count('class="pts" id="data-T00') == 5
    assert page.count('href="#data-T0032"') >= 9 and page.count("<td>QUANTIFIED</td>") == sum(len(v) for v in S02.values())
    for fig in ("A1_T0032", "A1w_T0032", "A2_T0032", "B1_T0032", "B2_T0032", "C1_", "C2_", "C3d_", "Q1_S02", "Q4_S02"):
        assert any(p.name.startswith(fig) for p in (run / "absorption").iterdir()), fig
    assert not any(p.name.startswith(("fig", "T2_")) for p in (run / "absorption").iterdir())


def test_question_view_stacks_two_panels_and_wraps_small_multiples(tmp_path):
    ab._SPECS.clear()
    a, b = ab.Panel("a"), ab.Panel("b")
    ab._figure(tmp_path, "x.png", "", [a, b], 5.6, 7.4, ncol=1)
    ab._figure(tmp_path, "y.png", "", [ab.Panel(str(k)) for k in range(10)], 12, 7.7, ncol=4)
    x, y = ab._SPECS[-2:]
    assert x["ncol"] == 1 and x["widths"] == [1] and y["ncol"] == 4 and len(y["widths"]) == 4
    for s in (x, y):
        ab._render_mpl(s, tmp_path)
    assert (tmp_path / "x.png").exists() and (tmp_path / "y.png").exists()
    ab._SPECS.clear()


def test_individual_layer_small_multiples():
    card = {"dataset_id": "I1", "unit": "mg/L"}
    sl = [{"label": f"rat {k}", "points": [{"t": t, "c": c * (1 + k / 20), "status": "QUANTIFIED"} for t, c in ((0.5, 2), (1, 4), (2, 3), (4, 1))],
           "metrics": {"tmax": 1.0, "first_t": 0.5, "_t": [0.5, 1, 2, 4], "_c": [2, 4, 3, 1]}} for k in range(ab.IND_SMALL_MULTIPLES + 1)]
    assert isinstance(ab.pInd(card, sl, True), list) and len(ab.pInd(card, sl, True)) == len(sl)
    one = ab.pInd(card, sl[:3], False, early=True)
    assert not isinstance(one, list) and one.d["xlim"][1] == pytest.approx(2 * 1.06)
    assert not any(L["kind"] == "line" for L in one.d["layers"])  # identity not verified: points only


def test_group_mean_dip_is_a_described_second_rise(run):
    tables = json.loads((run / "source_tables.json").read_text(encoding="utf-8"))
    e = tables[0]
    e["records"] = [{"record_id": f"R{i}", "time_h": t, "c002_time_h": t, "c003_mean": c, "qc_status": "TECHNICALLY_RETAINED",
                     "value_status": {"c002_time_h": "QUANTIFIED", "c003_mean": "QUANTIFIED"}}
                    for i, (t, c) in enumerate(((0.25, 6), (0.5, 10), (1, 7), (2, 9), (3, 5), (5, 2)))]
    (run / "source_tables.json").write_text(json.dumps([e]), encoding="utf-8")
    res = ab.build(run)
    q4 = res["status_boards"][0]["questions"][3]
    assert q4["status"] == ab.ST_PART and q4["observed"].startswith("The group mean of T0028 dips at 1 h")
    assert q4["primary"]["panels"] == ["A1"] and "T2 does not apply to group means" in q4["primary"]["lines"][1]
    assert "averaging single-peaked curves can create a dip" in q4["reach"]


def test_species_group():
    assert ab.species_group("neutropenic thigh-infected mice") == "Mouse"
    assert ab.species_group("Female Sprague-Dawley rats") == "Rat"
    assert ab.species_group("Neonatal rabbit") == "Rabbit"
    assert ab.species_group("Guinea pigs") == "Guinea pig"
    assert ab.species_group("K. pneumoniae") == "Species not stated"


def test_portal_card(run):
    home = ('<main><h2>Review by category</h2><div class="categories"><a class="category" href="sections/Q_PK_SHAPE/index.html">'
            '<div class="thumbs"><img src="x.jpg"></div></a></div><section class="panel" id="review-notes"></section></main>')
    (run / "index.html").write_text(home, encoding="utf-8")
    ab.attach(run)
    ab.add_to_portal(run)  # idempotent
    text = (run / "index.html").read_text(encoding="utf-8")
    assert text.count('href="absorption/index.html"') == 1
    grid = text[text.index('<div class="categories">'):text.index('<section class="panel" id="review-notes">')]
    assert 'id="ABSORPTION"' in grid and grid.endswith("</a><!--ABSORPTION-CARD-END--></div>")
    assert "Mouse (" in grid
    for name in ("index.html", "species-mouse.html"):
        page = (run / "absorption" / name).read_text(encoding="utf-8")
        assert '<a href="../index.html#categories">← All categories</a>' in page


def test_non_central_matrix_only_overview(run):
    tables = json.loads((run / "source_tables.json").read_text(encoding="utf-8"))
    tables[0]["metadata"]["matrix_category"] = "INFECTION_SITE"
    (run / "source_tables.json").write_text(json.dumps(tables), encoding="utf-8")
    res = ab.build(run)
    card = next(d["card"] for d in res["datasets"] if d["card"]["dataset_id"] == "T0028")
    assert not card["tests_allowed"] and "NOT_CENTRAL_MATRIX" in card["gates"]
    assert not any(p.name.startswith(("A2_T0028", "A1_T0028")) for p in (run / "absorption").iterdir())
    assert any(p.name.startswith("A1w_T0028") for p in (run / "absorption").iterdir())


# ---------------------------------------------------------------- r4.1: T2, T3 (group SD, Bailer), T3p, A0.12

def test_t_quantile_and_holm():
    assert ab.t_ppf(0.975, 4) == pytest.approx(2.7764, abs=1e-3)
    assert ab.t_ppf(0.975, 30) == pytest.approx(2.0423, abs=1e-3)
    assert ab.holm([0.01, 0.04, 0.03]) == pytest.approx([0.03, 0.06, 0.06])


def test_t2_individual_valley_and_group_mean():
    pts = [{"t": t, "c": c, "status": "QUANTIFIED"} for t, c in ((0.5, 5), (1, 10), (2, 6), (3, 4), (4, 7), (6, 5), (8, 2))]
    r = ab.t2_curve(pts)
    assert r["valley"] is not None and r["t2_margin"] > 0
    assert ab.t2_label(r, "INDIVIDUAL")[0] == "EXCLUDED_UNDER_STATED_ASSUMPTIONS"
    lab, flags = ab.t2_label(r, "INDIVIDUAL_IDENTITY_UNVERIFIED")
    assert "CONDITIONAL_ON_LABEL_IDENTITY" in flags
    assert ab.t2_label(r, "GROUP_MEAN")[0] == "DESCRIPTIVE_ONLY"
    mono = [{"t": t, "c": c, "status": "QUANTIFIED"} for t, c in ((0.5, 5), (1, 10), (2, 6), (4, 3))]
    assert ab.t2_label(ab.t2_curve(mono), "INDIVIDUAL")[0] == "NOT_EXCLUDED"


def test_t3_group_sd_vori_s02():
    # Vori S02 (Andes 2003) legend: AUC 27.2 ± 12.2 (40 mg/kg), 0.72 ± 0.12 (10 mg/kg), 3 mice
    r = ab.t3_group_sd({"auc": 0.72, "sd": 0.12, "n": 3, "dose": 10}, {"auc": 27.2, "sd": 12.2, "n": 3, "dose": 40})
    assert r["R"] == pytest.approx(9.444, abs=1e-3)
    assert r["df"] == pytest.approx(2.54, abs=0.01)
    assert r["ci"][0] > 1 and r["t3_label"] == "EXCLUDED_UNDER_STATED_ASSUMPTIONS"


def test_bailer_matches_trapezoid():
    a, v = ab.bailer_auc([1, 2, 4], [2.0, 4.0, 2.0], [0.2, 0.4, 0.2], [3, 3, 3], 4)
    assert a == pytest.approx(0.5 * 1 * 2 + 0.5 * 1 * 6 + 0.5 * 2 * 6)
    assert v > 0


def _vori_s03(tmp_path):
    cols = [{"id": "t", "header": "Time (h)", "meaning": "TIME", "unit": "h"}]
    for d in (40, 80):
        cols += [{"id": f"m{d}", "header": f"{d} mg/kg mean (mg/L)", "meaning": "CONCENTRATION", "unit": "mg/L"},
                 {"id": f"u{d}", "header": f"{d} mg/kg upper bar end", "meaning": "ERROR_BAR_UPPER"},
                 {"id": f"l{d}", "header": f"{d} mg/kg lower bar end", "meaning": "ERROR_BAR_LOWER"}]
    rows = [[0.5, 9.41, 10.75, 8.16, 27.83, 30.92, 24.75], [1, 11.17, None, None, 33.83, 35.08, 32.5],
            [2, 11.83, None, None, 35.83, 42.17, 29.62], [4, 10.67, 11.5, 9.83, 25.92, 29.67, 22.17],
            [8, 1.38, None, None, 19.75, 25, 14.5], [12, 4.56, 7.49, 1.72, 23.08, 31.42, 14.71]]
    recs = [{"record_id": f"R{k}", "time_h": r[0], "qc_status": "TECHNICALLY_RETAINED",
             **{c["id"]: v for c, v in zip(cols, r)}, "value_status": {c["id"]: "QUANTIFIED" for c in cols}} for k, r in enumerate(rows)]
    e = {"dataset_id": "V1", "title": "S03 Fig. 2 oral voriconazole", "study_source_ids": ["S03"], "role": "PK_OBSERVATIONS",
         "experimental_unit": "Digitized group means", "columns": cols, "records": recs,
         "notes": "3 mice per time point. Each symbol is the geometric mean and standard deviation. PK on DAY 2 OF TREATMENT.",
         "metadata": {"species": "mice", "matrix": "plasma", "drug": "VRC", "route_class": "EV", "route_detail": "ORAL",
                      "matrix_category": "PLASMA_SERUM_BLOOD", "record_category": "GROUP_SUMMARY",
                      "observation_source": "DIGITIZED_FROM_FIGURE", "dosing_regimen": "Once daily; PK on day 2 of treatment"}}
    (tmp_path / "source_tables.json").write_text(json.dumps([e]), encoding="utf-8")
    return tmp_path


def test_t3p_from_digitized_error_bars(tmp_path):
    res = ab.build(_vori_s03(tmp_path))
    ds = res["dose_series"][0]
    p = ds["t3p"]
    assert p["t3p_dose_pair"] == [40, 80] and p["t3p_times"] == [0.5, 4.0, 12.0]
    assert p["t3p_ln_ratio_ci"][0]["ln_ratio"] == pytest.approx(0.3912, abs=1e-3)
    assert p["t3p_p_holm"][0] == pytest.approx(0.0604, abs=2e-3)
    assert p["t3p_label"] == "NOT_EXCLUDED" and "SENSITIVITY_ONLY" in p["t3p_flags"]
    assert {s["t"] for s in p["skipped"]} == {1.0, 2.0, 8.0}
    assert ds["t3_label"] == "CANNOT_ASSESS"          # Bailer needs SD at every window time
    assert ds.get("C3") and (tmp_path / "absorption" / ds["C3"]).exists()
    q7 = res["status_boards"][0]["questions"][6]
    assert q7["primary"]["file"] == ds["C3"] and q7["primary"]["panels"] == ["C3"]


def test_reported_parameters_wide_and_long():
    wide = {"dataset_id": "P1", "title": "S02 legend: single oral gavage", "study_source_ids": ["S02"], "role": "REPORTED_PARAMETERS",
            "columns": [{"id": "d", "header": "Dose (mg/kg)", "meaning": "DOSE"}, {"id": "a", "header": "AUC (mg·h/liter)", "meaning": "PARAMETER_VALUE"},
                        {"id": "x", "header": "Dose-normalized AUC", "meaning": "PARAMETER_VALUE"}],
            "records": [{"record_id": "1", "d": 40, "a": "27.2 ± 12.2", "x": 0.68}, {"record_id": "2", "d": 10, "a": "0,72 ± 0,12", "x": 0.072}],
            "notes": "3 mice per time", "metadata": {"route_class": "EV", "route_detail": "ORAL", "dosing_regimen": "Single oral gavage",
                                                    "matrix_category": "PLASMA_SERUM_BLOOD", "record_category": "GROUP_SUMMARY"}}
    card, ps = ab.reported_parameters(wide)
    assert card["data_form"] == "REPORTED_PARAMETER"
    assert [(p["param"], p["dose"], p["value"], p["dispersion"], p["n"]) for p in ps] == [("AUC", 40, 27.2, 12.2, 3), ("AUC", 10, 0.72, 0.12, 3)]
    a = ab.reported_analysis(card, ps)
    assert a["t3"]["t3_label"] == "EXCLUDED_UNDER_STATED_ASSUMPTIONS" and "SENSITIVITY_ONLY" in a["t3"]["t3_flags"]
    long = {"dataset_id": "P2", "title": "S08 oral 20 mg/kg (n = 6)", "study_source_ids": ["S08"], "role": "REPORTED_PARAMETERS",
            "columns": [{"id": "m", "header": "Measure", "meaning": "OTHER"}, {"id": "v", "header": "Value", "meaning": "PARAMETER_VALUE"}],
            "records": [{"record_id": "1", "m": "F (%)", "v": 106}, {"record_id": "2", "m": "Tmax (min)", "v": "263 ± 201"}],
            "notes": "means ± standard deviation (SD)", "metadata": {"route_class": "EV", "route_detail": "ORAL", "dosing_regimen": "Single oral 20 mg/kg"}}
    card, ps = ab.reported_parameters(long)
    tm = next(p for p in ps if p["param"] == "TMAX")
    assert tm["unit"] == "min" and tm["n"] == 6
    f = ab.reported_analysis(card, ps, [{"dataset_id": "IV1", "dose": 10, "dose_basis": "NOT_FOUND"}])["f"]
    assert f["f_status"] == "SOURCE_REPORTED" and f["value"] == pytest.approx(1.06)
    assert {"F_ABOVE_ONE", "DOSE_MISMATCH", "LINEARITY_UNTESTED"} <= set(f["flags"])


def _dose_report(run, status, execution=None, views=()):
    g = {"group_id": "PK_MOUSE_SC", "dataset_ids": [IDS[d] for d in S02], "status": status, "reason": "source signature missing.",
         "selected_view_ids": list(views)}
    if execution:
        g["execution_status"] = execution
    (run / "dose_normalization_assessment.json").write_text(json.dumps({"groups": [g]}), encoding="utf-8")


def test_dose_normalized_overlay_link(run):
    _dose_report(run, "READY", "RENDERED_AND_VERIFIED", ["PK_MOUSE_SC__DOSE_NORMALIZED"])
    (run / "EV").mkdir()
    (run / "EV" / "PK_MOUSE_SC__DOSE_NORMALIZED.png").write_bytes(b"\x89PNG")
    ab.attach(run)
    res = json.loads((run / "absorption" / "absorption.json").read_text(encoding="utf-8"))
    assert not [x for x in res["presentation"]["not_drawn"] if x["figure"].startswith("C1 · overlay")]
    page = (run / "absorption" / "species-mouse.html").read_text(encoding="utf-8")
    assert 'href="../EV/PK_MOUSE_SC__DOSE_NORMALIZED.png"' in page and "RENDERED_AND_VERIFIED" in page
    (run / "index.html").write_text('<div class="categories"><a class="category"></a></div>', encoding="utf-8")
    ab.add_to_portal(run)
    page = (run / "absorption" / "species-mouse.html").read_text(encoding="utf-8")
    assert 'href="../sections/Q_PK_SHAPE/index.html#figure-PK_MOUSE_SC__DOSE_NORMALIZED"' in page


def test_dose_normalized_overlay_blocked(run):
    _dose_report(run, "BLOCKED")
    res = ab.build(run)
    skips = [x for x in res["presentation"]["not_drawn"] if x["figure"].startswith("C1 · overlay")]
    assert len(skips) == 1 and "BLOCKED" in skips[0]["reason"] and "source signature missing" in skips[0]["reason"]


# ---------------------------------------------------------------- working hypothesis, hidden case space, review rounds

def _hyp(res, study="S02"):
    return next(b for b in res["status_boards"] if b["study"] == study)["hypothesis"]


def test_hypothesis_after_nine_questions_and_hidden_space(run):
    res = ab.build(run)
    h = _hyp(res)
    assert h["id"] == "S02-H-r1" and h["state"] == "PENDING"
    assert h["primary_parts"] == ["dose.saturable_rate"] and h["components"]["dose"] == "saturable_rate"
    assert h["text"].startswith("Suspected: an absorption rate that saturates as the dose rises")
    # the common window 0–4 h holds too little of the 32 mg/kg exposure to read AUC/D as extent: the falling peak carries the reading
    assert "Q7, Cmax/D 0.44× from 2 to 32 mg/kg (AUC window short)" in h["rests_on"]
    assert "a fraction absorbed that falls as the dose rises" in h["text"]
    assert all(c["result"] == "PASS" for c in h["checks"]), h["checks"]
    assert [r[0] for r in h["primary"]["rows"]][:2] == ["M0", "M1"]
    ctx = json.loads((run / "absorption" / "hypothesis_context.json").read_text(encoding="utf-8"))
    st = ctx["studies"][0]
    assert len(st["combinations"]["rows"]) == len(ab._hspace()) == 2112
    assert sum(v for k, v in st["combinations"]["counts"].items() if k != "WITH_UNTESTABLE_PART") == 2112
    assert set(ctx["catalog_crosswalk"]["entries"]) >= {"first_order", "weibull_eq1_lag", "nonlinear_elimination", "timing_sampling"}
    page = (run / "absorption" / "species-mouse.html").read_text(encoding="utf-8")
    assert page.index('id="q-s02-9"') < page.index('id="h-s02"') < page.index("</section>", page.index('id="h-s02"'))
    # the case and combination list stays in the context file; the page shows one hypothesis and its ladder
    assert "I-FO-1-D-LIN-0" not in page and "Single Weibull" not in page and "· open" not in page
    tpl = json.loads((run / "absorption" / "hypothesis_review.template.json").read_text(encoding="utf-8"))
    assert tpl["reviews"][0]["hypothesis_sha256"] == h["sha256"] and tpl["reviews"][0]["decision"] == "PENDING"
    idx = (run / "absorption" / "index.html").read_text(encoding="utf-8")
    assert 'href="species-mouse.html#h-s02"' in idx and "Review pending" in idx
    # overview: the hypotheses in short come first, for a first review; no dataset list
    assert idx.index('id="hypotheses"') < idx.index('id="species"') < idx.index('id="questions"') and "Datasets used" not in idx
    assert idx.count('class="res hsum"') == 1 and idx.count('<tr><td><a href="species-mouse.html#h-s02">S02</a>') == 1
    assert h["brief"]["qs"] == sorted({s["q"] for s in ctx["studies"][0]["findings"]["signals"] if s["id"] in h["signals_used"]})


def test_t1_exclusion_sets_immediate_input_aside(run):
    tables = json.loads((run / "source_tables.json").read_text(encoding="utf-8"))
    e = tables[0]
    e["records"] = [{"record_id": f"R{i}", "time_h": t, "c002_time_h": t, "c003_mean": c, "qc_status": "TECHNICALLY_RETAINED",
                     "value_status": {"c002_time_h": "QUANTIFIED", "c003_mean": "QUANTIFIED"}}
                    for i, (t, c) in enumerate(((0.25, 0.5), (0.5, 4), (1, 10), (2, 8), (4, 4), (8, 1)))]
    (run / "source_tables.json").write_text(json.dumps([e]), encoding="utf-8")
    res = ab.build(run)
    h = _hyp(res)
    assert h["components"]["onset"] == "fixed_lag" and "onset.fixed_lag" in h["primary_parts"]
    assert "T1" in h["primary"]["rows"][0][3] and "set aside by T1" in h["primary"]["rows"][0][3]
    ctx = json.loads((run / "absorption" / "hypothesis_context.json").read_text(encoding="utf-8"))
    rows = {r[0]: r for r in ctx["studies"][0]["combinations"]["rows"]}
    assert rows["I-FO-1-D-LIN-0"][1] == "DISFAVORED" and rows["I-FO-1-D-LIN-0"][4] == ["T1"]
    assert rows["I-W>1-1-D-LIN-0"][1] != "DISFAVORED" and rows["L-FO-1-D-LIN-0"][1] == "ACCOUNTS_FOR_ALL"
    assert all(c["result"] == "PASS" for c in h["checks"]), h["checks"]


def test_selection_follows_t2_and_condition_rules():
    F = {"signals": [ab._hsig("rerise_within_animal", 4, ab.SUG, "", "", [["second.two_inputs"], ["second.recirculation"]]),
                     ab._hsig("condition_changes_shape", 8, ab.SUG, "", "", [["condition.rate_shape"]], factor="condition")],
         "rules": [ab._hrule("T2", 4, "", {"shape": list(ab.LOGCONCAVE), "second": ["none"], "other": ["none", "multicompartment"]}),
                   ab._hrule("T5", 8, "", {"condition": ["same", "extent_only", "disposition_scaling"]}, factor="condition")],
         "untestable": {}, "cond": {"attr": "route"}}
    space = ab._hspace()
    ev = [ab._heval(c, F) for c in space]
    primary, chosen, added, not_added = ab._hselect(F, space, ev)
    assert chosen["second"] == "two_inputs" and chosen["shape"] == "first_order" and not added
    assert ab._hcond_select(F, ab._hcond_rows(F)) == "rate_shape"
    assert ab._heval(dict(ab.HYP_DEFAULT), F)["rules"] == ["T2"]


def test_hint_layer_drops_a_part_it_makes_redundant():
    # T1 points to a delay or a second input; a dip that only hints at a second input: the second input alone accounts for both,
    # so a fixed lag chosen first is dropped (cheaper and accounts for the same findings)
    t1 = [["onset.fixed_lag"], ["onset.transit"], ["onset.variable_lag"], ["shape.zero_then_first"], ["shape.weibull_sigmoid"],
          ["shape.inverse_gaussian"], ["second.two_inputs"], ["second.recirculation"]]
    F = {"signals": [ab._hsig("t1_excluded", 3, ab.SUG, "", "", t1),
                     ab._hsig("rerise_group_mean", 4, ab.HINT, "", "", [["second.two_inputs"], ["second.recirculation"], ["onset.variable_lag"]])],
         "rules": [ab._hrule("T1", 3, "", {"onset": ["immediate"], "shape": list(ab.NONINC), "second": ["none"], "other": ["none", "multicompartment"]})],
         "untestable": {"onset.variable_lag": "needs serial curves of single animals (Q9)"}, "cond": None}
    space = ab._hspace()
    ev = [ab._heval(c, F) for c in space]
    primary, chosen, added, not_added = ab._hselect(F, space, ev)
    assert primary["onset"] == "fixed_lag" and chosen["onset"] == "immediate" and chosen["second"] == "two_inputs"


def test_same_data_in_any_order_give_the_same_hypotheses(run, tmp_path_factory):
    tables = json.loads((run / "source_tables.json").read_text(encoding="utf-8"))
    other = tmp_path_factory.mktemp("reordered")
    (other / "source_tables.json").write_text(json.dumps(tables[::-1]), encoding="utf-8")
    (other / "report.html").write_text((run / "report.html").read_text(encoding="utf-8"), encoding="utf-8")
    a, b = ab.build(run), ab.build(other)
    key = lambda res: [(x["study"], x["hypothesis"]["sha256"], x["hypothesis"]["text"]) for x in res["status_boards"]]  # noqa: E731
    assert key(a) == key(b)
    pairs = [{"ev": "E2", "iv": "I1", "dose_ev": 8.0, "dose_iv": 4.0}, {"ev": "E1", "iv": "I1", "dose_ev": 4.0, "dose_iv": 4.0}]
    assert min(pairs, key=ab._hpair_key)["ev"] == "E1"  # the dose-matched EV/IV pair is read first


def test_short_auc_window_is_not_read_as_extent(run):
    # without the 4 h sample of the 2 mg/kg group the common window ends at 2 h: AUC/D 0.51× there, but the higher dose peaks later,
    # so the fall is a hint to slower absorption or lower extent, not a firm finding of lower extent
    tables = json.loads((run / "source_tables.json").read_text(encoding="utf-8"))
    tables[0]["records"] = [r for r in tables[0]["records"] if r["time_h"] != 4]
    (run / "source_tables.json").write_text(json.dumps(tables), encoding="utf-8")
    res = ab.build(run)
    h = _hyp(res)
    ctx = json.loads((run / "absorption" / "hypothesis_context.json").read_text(encoding="utf-8"))
    F = ctx["studies"][0]["findings"]
    sig = {s["id"]: s for s in F["signals"]}
    assert F["bounds"]["auc_window"]["short"] and F["bounds"]["auc_window"]["end_h"] < 4
    assert "exposure_falls" not in sig and sig["auc_short_window"]["strength"] == ab.HINT and sig["peak_falls"]["strength"] == ab.SUG
    assert h["primary_parts"] == ["dose.saturable_rate"] and all(c["result"] == "PASS" for c in h["checks"]), h["checks"]
    assert ctx["thresholds"]["auc_window_share_min"] == ab.SHARE_MIN
    # the hint offers the same swaps as the falling peak; they stay listed under the firm finding, so the forks stay on the page
    assert "Equally possible: a fraction absorbed that falls as the dose rises" in h["text"]
    assert "Equally possible: concentration-dependent binding" in h["text"]


def test_one_sample_left_out_is_checked_and_shown(run, monkeypatch):
    res = ab.build(run)
    st = _hyp(res)["stability"]
    assert st["checks"] == sum(len(p) for p in S02.values()) and not st["errors"] and len(st["changed"]) <= 2
    page = (run / "absorption" / "species-mouse.html").read_text(encoding="utf-8")
    idx = (run / "absorption" / "index.html").read_text(encoding="utf-8")
    assert "One sample left out:" in page and "<b>How firm it is.</b>" in idx
    # the overview summary is a few short paragraphs, not a list of facts
    assert 'class="hsumtext"' in idx and "hfacts" not in idx and "<b>What the data point to.</b> In S02 the findings point beyond" in idx
    assert ab._hstab_text({"checks": 3, "changed": [], "errors": []}) == ("unchanged when any one of 3 samples is left out.", False)
    monkeypatch.setenv("ABSORPTION_STABILITY", "0")
    res = ab.build(run)
    assert _hyp(res)["stability"] is None and "One sample left out:" not in (run / "absorption" / "species-mouse.html").read_text(encoding="utf-8")

def test_review_round_revises_and_binds_to_revision(run):
    res = ab.build(run)
    h = _hyp(res)
    rd = run / "absorption" / "reviews"
    rec = {"study": "S02", "hypothesis_id": h["id"], "hypothesis_sha256": h["sha256"], "decision": "REVISE",
           "opinion": "Flattening is more likely a second compartment.", "components": {"other": "multicompartment", "nonsense": "x"}}
    (rd / "a.json").write_text(json.dumps({"actor_type": "HUMAN", "reviewer": "George", "reviewed_at": "2026-11-06T09:00:00Z",
                                           "reviews": [rec]}), encoding="utf-8")
    (rd / "b.json").write_text(json.dumps({"actor_type": "AGENT", "reviewer": "x", "reviewed_at": "2026-11-06T09:00:00Z", "reviews": []}),
                               encoding="utf-8")
    res = ab.build(run)
    h2 = _hyp(res)
    assert h2["id"] == "S02-H-r2" and h2["state"] == "PENDING" and h2["components"]["other"] == "multicompartment"
    assert any(x.startswith("added: multi-compartment disposition") for x in h2["changes"])
    assert h2["history"][0]["review"]["opinion"].startswith("Flattening") and h2["history"][0]["state"] == "REVISED"
    log = json.loads((run / "absorption" / "hypothesis_context.json").read_text(encoding="utf-8"))["review_log"]
    assert {x["status"] for x in log} == {"APPLIED", "REJECTED_FILE"}
    # a second gate on revision 2; a review that names revision 1 again is stale
    (rd / "c.json").write_text(json.dumps({"actor_type": "HUMAN", "reviewer": "George", "reviewed_at": "2026-11-06T10:00:00Z",
                                           "reviews": [{"study": "S02", "hypothesis_id": h2["id"], "hypothesis_sha256": h2["sha256"],
                                                        "decision": "AGREE", "opinion": ""}, rec]}), encoding="utf-8")
    res = ab.build(run)
    h3 = _hyp(res)
    assert h3["id"] == "S02-H-r2" and h3["state"] == "AGREED"
    log = json.loads((run / "absorption" / "hypothesis_context.json").read_text(encoding="utf-8"))["review_log"]
    assert any(x["status"] == "STALE" for x in log)
    page = (run / "absorption" / "species-mouse.html").read_text(encoding="utf-8")
    assert "Flattening is more likely a second compartment." in page and ">Agreed<" in page
