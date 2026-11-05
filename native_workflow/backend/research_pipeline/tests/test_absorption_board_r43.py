"""Reader-facing r4.3 regression cases use invented curves and source summaries."""
from research_pipeline import eda_absorption as ab
from research_pipeline.eda_absorption_board43 import boards


def dataset(cid="E", level="GROUP_MEAN", points=((0.25, 1), (1, 4), (2, 2), (3, 3), (6, 1))):
    source = {"dataset_id": cid, "study_source_ids": ["study"], "title": "Synthetic plasma: 1 mg/kg",
              "experimental_unit": "Group means", "notes": "",
              "metadata": {"species": "mouse", "route_class": "EV", "route_detail": "SC", "matrix": "plasma",
                           "matrix_category": "PLASMA_SERUM_BLOOD", "record_category": "GROUP_SUMMARY",
                           "dose_basis": "active", "dosing_regimen": "Single SC dose"},
              "columns": [{"id": "t", "meaning": "TIME", "unit": "h"},
                          {"id": "v", "meaning": "CONCENTRATION", "unit": "mg/L", "header": "Mean"}],
              "records": [{"record_id": f"{cid}_R{i}", "t": t, "v": c, "qc_status": "TECHNICALLY_RETAINED",
                           "value_status": {"t": "QUANTIFIED", "v": "QUANTIFIED"}} for i, (t, c) in enumerate(points)]}
    c, ss = ab.extract(source)
    c.update(record_level=level)
    s, = ss
    s["metrics"] = ab.curve_metrics(s["points"], level, c)
    s["t2"] = ab.t2_curve(s["points"], c, level)
    s.update(A1=f"A1_{cid}.png", B1=f"B1_{cid}.png", A2=f"A2_{cid}.png")
    return {"card": c, "series": ss}


def read(ds=(), doses=(), refs=(), pairs=(), ps=(), ivs=()):
    board, = boards(ds, doses, refs, pairs, ps, ivs)
    assert [q["q"] for q in board["questions"]] == list(range(1, 10))
    return {q["q"]: q for q in board["questions"]}


def test_group_shape_and_unverified_labels_have_separate_interpretations():
    g = dataset()
    q = read([g])
    assert "Group-mean description" in q[4]["text"] and "Within-animal T2 unavailable" in q[4]["text"]
    assert q[4]["primary"]["file"] == "B1_E.png"
    assert "Weibull" in str(q[3]["evidence"]) and "0 < β < 1" in str(q[3]["evidence"])
    assert q[5]["status_code"] == "NOT_ANSWERABLE_YET" and q[5]["primary"] is None
    assert q[7]["status_code"] == "NOT_ANSWERABLE_YET" and "NOT_ESTIMABLE" in q[7]["text"]
    g = dataset(level="INDIVIDUAL_IDENTITY_UNVERIFIED")
    g["card"].update(series_kind="INDIVIDUALS", identity_verified="no")
    g["series"][0]["label"] = "source animal A"
    g["A1ind"] = "source-label-points.png"
    q = read([g])
    assert q[5]["status_code"] == "PARTLY_ANSWERABLE"
    assert q[5]["primary"]["file"] == "source-label-points.png"
    assert "CONDITIONAL_ON_LABEL_IDENTITY" in q[5]["text"]
    assert "source animal A" in q[5]["text"]


def test_parameter_only_unknown_dose_and_definition_are_visible_without_curve_inference():
    c = dataset()["card"]
    c.update(data_form="REPORTED_PARAMETER", dose_mg_per_kg=None)
    ps = {"card": c, "analysis": {"reported_iv_references": [{"dataset_id": "IV_P", "params": [
        {"param": "THALF", "label": "model half-life", "value": 2.1, "unit": "h", "record_id": "ivr",
         "definition": "method not stated", "dose": None}]}]}, "params": []}
    for param, value, unit in (("TMAX", 1, "h"), ("THALF", 4, "h"), ("AUC", 12, "mg h/L"), ("CMAX", 5, "mg/L"), ("F", 112, "%")):
        ps["params"].append({"param": param, "value": value, "unit": unit, "dose": None, "label": param,
                             "record_id": "row_" + param, "definition": "not stated", "source": "Table 2",
                             "n": 9, "n_from": "source text"})
    q = read(ps=[ps])
    for n, param in ((2, "TMAX"), (6, "THALF"), (7, "F"), (8, "AUC")):
        assert q[n]["status_code"] == "PARTLY_ANSWERABLE"
        assert q[n]["primary"]["kind"] == "row" and param in q[n]["primary"]["rows"][0][1]
        details = str(q[n]["evidence"])
        assert "Table 2" in details and "not stated" in details and "['n for this parameter', 'not reported']" in details
    assert "IV_P" in str(q[6]["evidence"]) and "REPORTED_IV_PARAMETER" in str(q[6]["evidence"])
    assert "F_ABOVE_ONE" in q[7]["text"]
    assert "Dose assignment unresolved" in q[8]["text"] and "CMAX" not in q[8]["primary"]["rows"][0][1]
    assert q[1]["primary"] is None and q[3]["primary"] is None


def test_all_blq_is_visible_and_gated_measurements_cannot_answer_questions():
    d = dataset("BLQ")
    d["series"][0]["metrics"] = {"n_quantified": 0, "n_blq": 5, "not_assessable_reason": "all postdose samples BLQ"}
    gated = dataset("ELF")
    gated["card"].update(tests_allowed=False, gates=["NOT_CENTRAL_MATRIX"])
    gated["A1ind"] = "gated-labels.png"
    q = read([d, gated])
    for n in (1, 2, 3, 4, 6):
        assert "5 BLQ" in q[n]["text"] and "BLQ" in q[n]["dataset_ids"]
        assert q[n]["primary"] is None and q[n]["status_code"] == "NOT_ANSWERABLE_YET"
    for row in q.values():
        assert "NOT_CENTRAL_MATRIX" in str(row["evidence"])
        assert all("ELF" not in v["ids"] for v in row["views"])
        assert "ELF" not in row["dataset_ids"]


def test_condition_and_iv_primaries_select_relevant_pair_and_keep_withheld_reason():
    a, b = dataset("IT"), dataset("SC")
    a["card"]["route_detail"] = "IT"
    c = dataset("IV")["card"]
    common = {"iv": "IV", "dose_ev": 1, "dose_iv": 1, "t4_label": "CANNOT_ASSESS",
              "terminal_comparison": {"comparison_status": "DIFFERENT_WINDOWS", "flip_flop_reading": "UNRESOLVED",
                                     "pairs": [{"ev_window_h": [1,12], "iv_window_h": [1,6],
                                                "ratio": 2, "grade": "EV_SHALLOWER_MARKED", "same_window": False}]},
              "t4": {"formal_status": "CANNOT_ASSESS", "margin": 3, "missing_premises": ["IV mode unknown"]},
              "mt4": 3, "trigger_text": "EV apparent t½ 4 h, IV 2 h", "observed_window": {"start_h": .25, "end_h": 6},
              "absolute_f_status": "NOT_ESTIMABLE"}
    refs = [dict(common, ev="IT", f_status="NOT_ESTIMABLE", f_reason="dose basis differs", D1="IT-v-IV.png"),
            dict(common, ev="SC", f_window=1.53, f_status="INCOMPLETE_EXPOSURE_RATIO",
                 f_reason="IV early coverage unresolved", D1="SC-v-IV.png", D2="SC-IV-F.png")]
    intervals = [{"t": i+.03, "reference_t": i+.04, "delta_h": .01, "c": 1+i/10, "records": ["a","b"]}
                 for i in range(6)]
    pair = {"a": "IT", "b": "SC", "exact_pairs": 0, "intervals": intervals, "t5_label": "CANNOT_ASSESS",
            "rate_only_label": "CANNOT_ASSESS", "c_lower": .69, "c_upper": .38, "E1": "E1.png", "E2": "E2.png"}
    q = read([a, b], refs=refs, pairs=[pair], ivs=[{"card": c}])
    assert "Terminal-window comparison" in q[6]["text"] and "T4 CANNOT_ASSESS" in q[6]["text"]
    assert "DIFFERENT_WINDOWS" in q[6]["text"] and "EV windows end at 12 h, IV windows at 6 h" in q[6]["text"]
    assert q[7]["primary"]["file"] == "SC-IV-F.png" and "1.53" in q[7]["text"] and "dose basis differs" in q[7]["text"]
    assert q[9]["primary"]["file"] == "E2.png" and "6 near-time pairs and 0 exact pairs" in q[9]["text"]
    assert "T5 CANNOT_ASSESS" in q[9]["text"]


def test_formal_test_and_common_window_reach_their_own_questions():
    d = dataset()
    s = d["series"][0]
    s["metrics"]["t1"].update(formal_status="EXCLUDED_UNDER_STATED_ASSUMPTIONS", flags=[], positive_count=1)
    win = {"start_h": 0.5, "end_h": 4.0, "same_grid": False, "shared_grid_R": .91}
    dose = {"dataset_ids": ["E"], "label": "constructed dose series", "observed_window": win,
            "R_window": .94, "cmax_d_ratio": .42, "t3_label": "NOT_EXCLUDED", "t3_flags": [],
            "t3p": {"t3p_label": "CANNOT_ASSESS"}, "C1": "dose-overlay.png"}
    q = read([d], doses=[dose])
    assert q[3]["status_code"] == "ANSWERABLE" and q[3]["primary"]["file"] == "A2_E.png"
    assert "outside this guarantee" in str(q[3]["evidence"])
    assert q[8]["status_code"] == "ANSWERABLE" and q[8]["primary"]["file"] == "dose-overlay.png"
    assert "0.5–4 h" in q[8]["text"] and "0.94" in q[8]["text"] and "0.91" in str(q[8]["evidence"])

