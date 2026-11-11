"""Tests for the EDA re-review (ERR) and summary (ES) host checks. No model is called: answers are scripted."""
import json
import sys
import pytest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from eda.review import runner as R  # noqa: E402
from eda.review.contracts import classify, scope_problem

RULES = """# rules
## A. Rule text
### E0 | SHARED
#### E0.3 Exclusion
labels
#### E0.11 Status
status text
### 29 | PLASMA WINDOW CLEARANCE
item 29 text
### 33 | URINE
item 33 text
### Flag registry (items 29-36)
WINDOW_PROXY
## B. Changes
not a rule passage
"""


def _q(n, status, observed, fig=None, missing=None):
    return {"q": n, "label": f"L{n}", "question": f"Q{n}?", "status_code": status, "observed": observed, "basis": "b", "reach": "r",
            "missing": missing or [], "primary": {"kind": "panel", "file": fig, "panels": ["P"], "lines": ["cap"]} if fig else None,
            "views": [], "evidence": []}


def _fixture(tmp):
    (tmp / "elimination").mkdir()
    (tmp / "absorption").mkdir()
    (tmp / "elimination" / "EM5a_x.png").write_bytes(b"png")
    (tmp / "absorption" / "A1_x.png").write_bytes(b"png")
    el = {"version": "E", "boards": [
        {"key": "s01-dog", "study": "S01", "species": "Dog",
         "questions": [_q(1, "ANSWERABLE", "CL window 0.432 L/h/kg", "../absorption/A1_x.png"),
                       _q(5, "PARTLY_ANSWERABLE", "49.1 % of dose in urine by 8 h", "EM5a_x.png", ["GFR"]),
                       dict(_q(3, "NOT_APPLICABLE", "single dose"), shown=False)],
         "hypothesis": {"text": "49.1 % in urine", "rests_on": "EM-5a", "missing": ["late plasma"], "alternative": "non-renal"}},
        {"key": "s01-rat", "study": "S01", "species": "Rat",
         "questions": [_q(1, "PARTLY_ANSWERABLE", "CL/F 2.5 L/h/kg", None, ["IV dose"])]}]}
    ab = {"version": "A", "status_boards": [{"study": "S01", "species": "Dog", "questions": [_q(2, "ANSWERABLE", "peak 12.4 mg/L at 0.56 h", "A1_x.png")]}]}
    (tmp / "elimination" / "elimination.json").write_text(json.dumps(el), encoding="utf-8")
    (tmp / "absorption" / "absorption.json").write_text(json.dumps(ab), encoding="utf-8")
    (tmp / "rules.md").write_text(RULES, encoding="utf-8")
    return tmp


def _confirm_all(req):
    rows = []
    for r in req["payload"]["rows"]:
        figs = [f["file"] for f in r.get("figures", [])]
        rows.append({"row_id": r["row_id"], "verdict": "CONFIRMED", "checked_figures": figs, "checked_rules": [], "issues": []})
    return {"board": req["payload"]["board"], "rows": rows, "omissions": []}


def test_rule_passages_stop_at_other_headings():
    p = R.rule_passages(RULES)
    assert set(p) == {"E0", "E0.3", "E0.11", "29", "33", "FLAGS"}
    assert "not a rule passage" not in p["FLAGS"] and "Flag registry" not in p["33"]
    keep = R.passages_for("elimination", 5, p)
    assert {"33", "E0.3", "E0.11", "FLAGS"} <= set(keep) and "29" not in keep


@pytest.mark.parametrize("fix,expected", [(True, "PASSED"), (False, "PENDING")])
def test_keyword_rerun_rechecks_and_blocks_unresolved_rows(tmp_path, fix, expected):
    root = _fixture(tmp_path)
    board = {"study": "S01", "species": "Rat", "key": "s01-rat", "components": [], "in_vitro": [],
             "questions": [_q(7, "ANSWERABLE", "No component or assay measurements.")]}
    path = root / "elimination/elimination.json"
    path.write_text(json.dumps({"boards": [board]}), encoding="utf-8")
    (root / "source_tables.json").write_text(json.dumps([
        {"dataset_id": "T1", "study_source_ids": ["S01"], "metadata": {"species": "rat"},
         "title": "Plasma assay inventory", "records": [{"note": "No in vitro assay"}]}]), encoding="utf-8")
    calls = []
    def model(prompt, schema, images):
        p = json.loads(prompt.split("\nREQUEST\n")[1])
        if "feedback" in p:
            calls.append("write")
            assert p["source_matches"][0]["dataset_id"] == "T1" and "excreta" in p["keywords"]
            r = p["rows"][0]
            return {"rows": [{"row_id": r["row_id"], "status_code": "NOT_ANSWERABLE_YET" if fix else "ANSWERABLE",
                              "observed": "No component or assay measurements.", "basis": "", "reach": "", "missing": []}]}
        if "species" in schema["properties"]:
            calls.append("summary")
            revised = next(r for r in p["rows"] if r["q"] == 7)
            assert revised["status_code"] == "NOT_ANSWERABLE_YET"
            return _es_answer(p["species"], {})
        calls.append("recheck" if "previous_findings" in p else "check")
        return _confirm_all({"payload": p})
    result = R.run(root, model)
    assert result["self_review"] == expected and "recheck" in calls
    assert ("summary" in calls) == fix
    assert json.loads(path.read_bytes())["boards"][0]["questions"][0]["status_code"] == "ANSWERABLE"
    resumed = R.run(root, None, resume=True)
    assert resumed["self_review"] == expected


def test_study_and_arm_citations():
    board = {"study": "A", "arm": {"experiment_arm": "po"}}
    def item(did, study, arm):
        return classify({"dataset_id": did, "study_ids": study, "experiment_arm": arm}, board, {"foreign"})
    inventory = [item("local", ["A"], "po"), item("iv", ["A"], "iv"), item("foreign", ["B"], "po"),
                 item("unknown", [], "po"), item("unspecified", ["A"], None)]
    def check(did, scope):
        return scope_problem({"type": "OMITTED_EVIDENCE", "evidence": {"dataset_ids": [did]}},
                             {"claim_scope": scope}, inventory)
    assert not check("local", "arm") and not check("unspecified", "study")
    assert all(check(d, "arm") for d in ("iv", "foreign", "unknown", "unspecified"))
    assert not check("foreign", "project") and check("invented", "project")


def test_missing_fields_and_bounded_measurement_are_not_zero_evidence():
    for b in ({}, {"components": []}, {"components": [{"component": "parent"}], "in_vitro": []}):
        assert R.endpoint_limit("elimination", b, {"q": 7}, {}) is None


def test_collect_rows_paths_and_hypothesis(tmp_path):
    rows, meta = R.collect(_fixture(tmp_path))
    ids = {r["row_id"]: r for r in rows}
    assert meta["distribution"]["present"] is False
    assert "elimination:s01-dog:Q1" in ids and "elimination:s01-dog:H" in ids and "absorption:s01-dog:Q2" in ids
    assert ids["elimination:s01-dog:Q1"]["figures"][0]["path"] == str(Path("absorption/A1_x.png"))
    assert ids["elimination:s01-dog:Q5"]["figures"][0]["path"] == str(Path("elimination/EM5a_x.png"))
    assert ids["elimination:s01-dog:H"]["cites"] == ["elimination:s01-dog:Q1", "elimination:s01-dog:Q5"]
    assert ids["elimination:s01-dog:Q3"]["shown"] is False


def test_requests_review_hidden_rows_carry_inputs_and_split_by_images(tmp_path):
    root = _fixture(tmp_path)
    (root / "source_tables.json").write_text(json.dumps([
        {"dataset_id": "D_dog_rep", "title": "dog day 7 of 7", "role": "PK_PARAMETERS", "metadata": {"species": "dog", "dosing_regimen": "7 days"}},
        {"dataset_id": "D_rat", "title": "rat", "metadata": {"species": "rat"}}]), encoding="utf-8")
    rows, _ = R.collect(root)
    reqs = R.err_requests(root, rows, {"elimination": RULES})
    sent = [r for q in reqs for r in q["payload"]["rows"]]
    assert len(sent) == len({r["row_id"] for r in sent}) == 6
    assert next(r for r in sent if r["row_id"] == "elimination:s01-dog:Q3")["hidden_on_page"] is True
    dog0 = next(q for q in reqs if q["id"].startswith("ERR-elimination-s01-dog"))
    assert [x["dataset_id"] for x in dog0["payload"]["inputs_for_species"]] == ["D_dog_rep"]
    assert dog0["payload"]["inputs_for_species"][0]["used_by_this_board"] is False
    dog = next(q for q in reqs if q["id"].startswith("ERR-elimination-s01-dog"))
    assert set(dog["payload"]["rules"]) >= {"29", "33", "FLAGS"}
    assert sorted(Path(p).name for p in dog["images"]) == ["A1_x.png", "EM5a_x.png"]
    split = R.err_requests(root, rows, {}, max_images=1)
    assert sum(1 for q in split if q["id"].startswith("ERR-elimination-s01-dog")) >= 2
    assert all(len(q["images"]) <= 1 or len(q["payload"]["rows"]) == 1 for q in split)


def test_validate_err_accepts_clean_and_rejects_bad_answers(tmp_path):
    root = _fixture(tmp_path)
    rows, _ = R.collect(root)
    req = next(q for q in R.err_requests(root, rows, {"elimination": RULES}) if q["id"].startswith("ERR-elimination-s01-dog"))
    ok, probs = R.validate_err(_confirm_all(req), req)
    assert ok, probs
    bad = _confirm_all(req)
    bad["rows"].pop()                                                    # a row left out
    bad["rows"][0]["checked_figures"] = ["DIS1a_other.png"]              # a figure that was not sent
    bad["rows"][1].update(verdict="REVISE", issues=[{"type": "VALUE_ERROR", "what": "x", "evidence": {"figure": None, "rule": "99", "data": None},
                                                       "smallest_correction": ""}])
    bad["rows"].append(dict(bad["rows"][0], row_id="elimination:s01-dog:Q9"))
    ok, probs = R.validate_err(bad, req)
    text = " | ".join(probs)
    assert not ok
    for frag in ("answered 0 times", "not in the request", "that was not sent", "REVISE without a correction", "rule 99"):
        assert frag in text, frag
    conf = _confirm_all(req)
    conf["rows"][0]["checked_figures"] = []
    assert any("without checking" in p for p in R.validate_err(conf, req)[1])


def test_missing_figure_cannot_be_confirmed(tmp_path):
    root = _fixture(tmp_path)
    (root / "elimination" / "EM5a_x.png").unlink()
    rows, _ = R.collect(root)
    req = next(q for q in R.err_requests(root, rows, {}) if q["id"].startswith("ERR-elimination-s01-dog"))
    q5 = next(r for r in req["payload"]["rows"] if r["row_id"].endswith("Q5"))
    assert q5["figures_not_sent"] == ["EM5a_x.png"] and not q5["figures"]
    ok, probs = R.validate_err(_confirm_all(req), req)
    assert not ok and any("not sent (EM5a_x.png)" in p for p in probs)


def _es_answer(species, statements):
    return {"species": [{"species": s, "statements": statements.get(s, []), "handoff": []} for s in species], "project_open_items": []}


def test_validate_es_strength_numbers_words_and_coverage(tmp_path):
    root = _fixture(tmp_path)
    rows, _ = R.collect(root)
    verdicts = {"elimination:s01-dog:Q1": {"verdict": "CONFIRMED", "issues": []}, "elimination:s01-dog:Q5": {"verdict": "REVISE", "issues": []}}
    req = R.es_request(rows, verdicts)
    assert "elimination:s01-dog:Q3" not in {r["row_id"] for r in req["payload"]["rows"]}   # NOT_APPLICABLE and hidden
    good = _es_answer(["Dog", "Rat"], {"Dog": [{"kind": "FINDING", "text": "Window clearance 0.432 L/h/kg.", "cites": ["elimination:s01-dog:Q1"],
                                                 "strength": "ANSWERABLE"}],
                                       "Rat": [{"kind": "OPEN", "text": "An IV dose is missing.", "cites": ["elimination:s01-rat:Q1"],
                                                "strength": "PARTLY_ANSWERABLE"}]})
    ok, probs = R.validate_es(good, req, rows, verdicts)
    assert ok, probs
    bad = _es_answer(["Dog"], {"Dog": [
        {"kind": "FINDING", "text": "Urine 49.1 % of dose.", "cites": ["elimination:s01-dog:Q5"], "strength": "PARTLY_ANSWERABLE"},
        {"kind": "LINK", "text": "CL/F 2.5 and urine together.", "cites": ["elimination:s01-rat:Q1"], "strength": "ANSWERABLE"},
        {"kind": "FINDING", "text": "Clearance is 0.9 L/h/kg.", "cites": ["elimination:s01-dog:Q1"], "strength": "ANSWERABLE"},
        {"kind": "FINDING", "text": "This establishes renal elimination.", "cites": ["elimination:s01-dog:Q1"], "strength": "ANSWERABLE"},
        {"kind": "FINDING", "text": "No source.", "cites": [], "strength": "ANSWERABLE"},
        {"kind": "FINDING", "text": "Made up row.", "cites": ["elimination:s09-dog:Q1"], "strength": "ANSWERABLE"}]})
    ok, probs = R.validate_es(bad, req, rows, verdicts)
    text = " | ".join(probs)
    assert not ok
    for frag in ("species Rat missing", "above the cited rows (REVIEW_PENDING)", "above the cited rows (PARTLY_ANSWERABLE)",
                 "numbers not in the cited rows (0.9)", "wording beyond evidence", "without citations", "not in the request"):
        assert frag in text, frag


def test_injection_and_score_with_an_oracle(tmp_path):
    root = _fixture(tmp_path)
    rows, _ = R.collect(root)
    bad_rows, truth = R.inject_errors(rows, n=3, seed=1)
    assert truth and all(t in R.ISSUE_TYPES for t in truth.values())
    changed = [r for r in bad_rows if r["row_id"] in truth]
    orig = {r["row_id"]: r for r in rows}
    assert all(r != orig[r["row_id"]] for r in changed)
    verdicts = {r["row_id"]: ({"verdict": "REVISE", "issues": [{"type": truth[r["row_id"]]}]} if r["row_id"] in truth
                              else {"verdict": "CONFIRMED", "issues": []}) for r in bad_rows if r.get("shown", True)}
    s = R.score(truth, verdicts)
    assert s["catch_rate"] == 1 and s["caught_with_right_type"] == len(truth) and s["flagged_clean"] == 0


def test_run_end_to_end_with_scripted_answers(tmp_path):
    root = _fixture(tmp_path)

    def gen(prompt, schema, images):
        payload = json.loads(prompt.split("\nREQUEST\n", 1)[1])
        if "species" in schema["properties"]:
            return _es_answer(payload["species"], {})
        return _confirm_all({"payload": payload})

    rec = R.run(root, gen, {"elimination": str(root / "rules.md")})
    assert rec["counts"]["accepted"] == rec["counts"]["requests"] and rec["counts"]["confirmed"] == rec["counts"]["rows"] == 6
    assert rec["es"]["status"] == "ACCEPTED"
    assert (root / "review" / "review.json").is_file() and "Review summary" in (root / "review" / "index.html").read_text(encoding="utf-8")


def test_injection_run_scores_and_skips_summary(tmp_path):
    root = _fixture(tmp_path)

    def gen(prompt, schema, images):           # flags every row that carries the planted strong word, confirms the rest
        payload = json.loads(prompt.split("\nREQUEST\n", 1)[1])
        out = _confirm_all({"payload": payload})
        for x, r in zip(out["rows"], payload["rows"]):
            if "establishes" in (r.get("observed") or ""):
                x.update(verdict="REVISE", issues=[{"type": "WORDING_BEYOND_EVIDENCE", "what": "strong word", "smallest_correction": "drop it",
                                                    "evidence": {"figure": None, "rule": None, "data": None}}])
        return out

    rec = R.run(root, gen, {}, inject=4, seed=3)
    inj = rec["injection"]
    assert inj["truth"] and rec["es"]["status"] == "NOT_RUN"
    planted_words = sum(1 for t in inj["truth"].values() if t == "WORDING_BEYOND_EVIDENCE")
    assert inj["score"]["caught"] == planted_words and inj["score"]["flagged_clean"] == 0


def test_score_known_groups():
    bench = {"groups": [{"id": "E5", "rows": ["a:Q3"], "expected_types": ["STATUS_TOO_WEAK"]},
                        {"id": "D7", "rows": ["b:Q6", "c:Q6"], "expected_types": ["OMITTED_EVIDENCE"]},
                        {"id": "A3", "partial": True, "rows": ["d:H"], "expected_types": ["HYPOTHESIS_UNSUPPORTED"]}]}
    v = {"a:Q3": {"verdict": "REVISE", "issues": [{"type": "STATUS_TOO_WEAK"}]}, "b:Q6": {"verdict": "CONFIRMED", "issues": []},
         "c:Q6": {"verdict": "UNCERTAIN", "issues": []}, "d:H": {"verdict": "REVISE", "issues": [{"type": "DISPLAY"}]},
         "e:Q1": {"verdict": "REVISE", "issues": []}}
    s = R.score_known(bench, v)
    assert (s["caught"], s["known"], s["caught_partial"]) == (1, 2, 1)
    assert s["groups"][0]["caught_with_expected_type"] and s["groups"][1]["uncertain"] == ["c:Q6"]
    assert s["revise_outside_known"] == ["e:Q1"]


def test_coverage_retry_only_and_resume(tmp_path):
    root = _fixture(tmp_path)
    (root / "source_tables.json").write_text(json.dumps([
        {"dataset_id": "D_used", "title": "dog iv", "metadata": {"species": "dog"}},
        {"dataset_id": "D_dog_rep", "title": "dog day 7 of 7", "metadata": {"species": "dog", "dosing_regimen": "7 days"}}]), encoding="utf-8")
    el = json.loads((root / "elimination" / "elimination.json").read_text(encoding="utf-8"))
    el["boards"][0]["datasets"] = ["D_used"]
    (root / "elimination" / "elimination.json").write_text(json.dumps(el), encoding="utf-8")
    calls = []

    def gen(prompt, schema, images):
        calls.append(prompt)
        payload = json.loads(prompt.split("\nREQUEST\n", 1)[1].split("\n\nYOUR PREVIOUS ANSWER")[0])
        out = _confirm_all({"payload": payload})
        if "REJECTED BY THE HOST CHECKS" not in prompt:
            out["rows"].pop()                      # first attempt leaves a row out
        return out

    rec = R.run(root, gen, {}, only="elimination-s01-dog")
    assert [x["dataset_id"] for x in rec["coverage"]["unused"]] == ["D_dog_rep"] and rec["coverage"]["used_by"]["D_used"] == ["elimination:s01-dog"]
    assert len(rec["err"]) == 1 and rec["err"][0]["status"] == "ACCEPTED" and rec["err"][0]["attempts"] == 2 and len(calls) == 2
    assert rec["es"]["status"] == "NOT_RUN"
    assert "Input coverage" in (root / "review" / "index.html").read_text(encoding="utf-8")
    rec2 = R.run(root, None, {}, only="elimination-s01-dog", resume=True)       # no model: the saved answer is reused
    assert rec2["err"][0]["status"] == "ACCEPTED" and rec2["err"][0]["resumed"] and rec2["counts"]["confirmed"] == 4
