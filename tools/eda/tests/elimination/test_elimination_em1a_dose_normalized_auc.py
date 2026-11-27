"""EM-1a (George 2026-11-27): the Q1 clearance figure is dose-normalized AUC vs dose; with one dose it is the semi-log terminal
phase (EM-T). The window clearance dose / observed AUC is a value in the NCA table and is never plotted."""
import json

from test_elimination_renal_review import plasma, el


def _iv(dose, sid, scale=1.0, times=(0.5, 1, 2, 4, 8)):
    s = plasma(times)
    s.update(sid=sid, dataset_id=sid.split(":")[0], dose=dose, label=f"Rat {dose:g} mg/kg")
    for p in s["points"]:
        p["c"] = dose * scale * 12 / (p["t"] + 1)
    return s


def _board(series):
    b = {"key": "s1-rat", "study": "S1", "species": "Rat", "plasma": series, "reported": [], "figs": {},
         "urine": [], "clr": [], "recovery": [], "components": [], "em7b": [], "item30": {"upstream": []}}
    b["item29"] = [el.item29(s, {}, {}, None, None, [], {}) for s in series]
    return b


def _spec_texts():
    return json.dumps([x["panels"] for x in el._SPECS])


def test_two_iv_doses_draw_em1a_and_q1_uses_it():
    el._SPECS.clear()
    b = _board([_iv(5, "T1:c1"), _iv(20, "T2:c1", scale=1.6)])
    el.figures([b], None)
    g, = b["em1a"]
    assert g["route"] == "IV" and g["doses"] == [5, 20] and g["common_window_h"] == [0.5, 8]
    assert abs(g["ratio_high_low"] - 1.6) < 1e-9 and el._em1a_reading(g) == "rises with dose"
    assert g["file"] and b["figs"][f"EM1a|{g['key']}"] == g["file"]
    text = _spec_texts()
    assert "AUC / dose" in text and "L/h/kg" not in text and "clearance (" not in text.lower()
    q = el.q1_row(b)
    assert q["primary"]["kind"] == "panel" and q["primary"]["panels"] == ["EM-1a"] and q["primary"]["file"] == g["file"]
    assert "rises with dose" in q["primary"]["lines"][1]
    nca = q["evidence"][0]["tables"][0]
    assert nca["caption"].startswith("NCA table") and "Dose / observed AUC (L/h/kg)" in nca["head"]
    assert any(v["panel"] == "EM-T" for v in q["views"])


def test_one_dose_uses_the_terminal_phase_plot():
    el._SPECS.clear()
    b = _board([_iv(10, "T1:c1")])
    el.figures([b], None)
    assert b["em1a"] == []
    q = el.q1_row(b)
    assert q["primary"]["panels"] == ["EM-T"] and "terminal phase" in q["primary"]["lines"][1]


def test_extravascular_group_reuses_absorption_c2():
    el._SPECS.clear()
    ev = [dict(_iv(d, f"T{i}:c1"), route_class="EV", route_detail="PO", iv_mode=None) for i, d in enumerate((5, 10), 1)]
    b = _board(ev)
    comparable, = el.em1a_groups(b)
    exposure = {"window": comparable["common_window_h"], "rows": [
        {"dose": rated["dose"], "auc_per_dose": rated["auc_d"], "refs": [profile["sid"]]}
        for rated, profile in zip(comparable["by_dose"], ev)
    ]}
    b["item30"] = {"upstream": [{"route": "EV", "doses": [5.0, 10.0], "panel_id": "C2", "panel": "../absorption/C1_x.png",
                                 "c2_panel": "../absorption/C2_x.png", "exposure": exposure}]}
    el.figures([b], None)
    g, = b["em1a"]
    assert g["reused"]["file"] == "../absorption/C2_x.png" and g["file"] is None
    assert not any("EM1a" in x["file"] for x in el._SPECS)
    q = el.q1_row(b)
    assert q["primary"]["panels"] == ["C2"] and q["primary"]["file"] == "../absorption/C2_x.png"


def test_windows_not_shared_fall_back_to_own_window():
    el._SPECS.clear()
    b = _board([_iv(5, "T1:c1", times=(0.5, 1, 2, 4)), _iv(20, "T2:c1", times=(0.25, 1, 3, 6))])
    el.figures([b], None)
    g, = b["em1a"]
    assert g["common_window_h"] is None and "own observed window" in g["basis"]
    assert g["ratio_high_low"] is None
    assert "Different windows prevent a dose comparison" in _spec_texts()


def test_shared_window_uses_shared_sample_endpoints_inside_overlapping_profiles():
    el._SPECS.clear()
    b = _board([_iv(5, "T1:c1", times=(0.25, 1, 2, 4, 6)), _iv(20, "T2:c1", times=(0.5, 1, 2, 4, 8))])
    el.figures([b], None)
    g, = b["em1a"]
    assert g["common_window_h"] == [1, 4]
    assert abs(g["ratio_high_low"] - 1) < 1e-9


def test_equal_dose_levels_do_not_reuse_a_panel_from_other_profiles():
    el._SPECS.clear()
    ev = [dict(_iv(d, f"T{i}:c1"), route_class="EV", route_detail="PO", iv_mode=None) for i, d in enumerate((5, 10), 1)]
    b = _board(ev)
    b["item30"] = {"upstream": [{"route": "EV", "doses": [5, 10], "c2_panel": "../absorption/C2_other.png",
                                "exposure": {"window": [0.5, 8], "rows": [
                                    {"dose": 5, "auc_per_dose": 1, "refs": ["X1:c1"]},
                                    {"dose": 10, "auc_per_dose": 1, "refs": ["X2:c1"]}]}}]}
    el.figures([b], None)
    g, = b["em1a"]
    assert g["file"] and not g["reused"]
