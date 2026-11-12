"""Changes of 2026-11-12: whole shared rule passages, issue routing, number guard, re-review retry, species keys."""
import copy
import json
import sys
import pytest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from eda.review import runner as R  # noqa: E402
from eda.review.contracts import species_key  # noqa: E402
from eda.review.rerun import rerun  # noqa: E402

LONG = "x" * 9000 + " ANSWERABLE is defined here."
RULES = f"""# rules
## A. Rule text
### E0 | SHARED
#### E0.2 Gates
gate 3 text
#### E0.3 Exclusion
labels
#### E0.10 Tests
T10 text
#### E0.11 Status
{LONG}
### 33 | URINE
Run T10 (E0.10). Assay type (E0.2, gate 3).
### Flag registry (items 29-36)
WINDOW_PROXY
## B. Changes
"""


def test_shared_passages_are_whole_and_cited_definitions_travel():
    keep = R.passages_for("elimination", 5, R.rule_passages(RULES))
    assert keep["E0.11"].endswith("ANSWERABLE is defined here.")
    assert {"E0.2", "E0.10", "33", "E0.3", "FLAGS"} <= set(keep)


def test_species_keys_cover_every_module_group():
    assert species_key("Guinea pigs") == "guinea pig" and species_key("Landrace pigs") == "pig"
    assert species_key("koalas") == "koala" and species_key("Jennies") == "donkey" and species_key("beagle dogs") == "dog"
    assert species_key("ponies") == "horse" and species_key("murine") == "mouse"


ROW = {"row_id": "elimination:b:Q5", "kind": "question", "label": "Urine", "question": "How much?", "status_code": "ANSWERABLE",
       "observed": "49.1 % of the dose by 8 h.", "basis": "", "reach": "", "missing": [], "value_table": None, "evidence": []}


def _req(rows):
    payload = {"board": "b", "rows": rows, "figures": [], "inputs_for_species": [], "project_context": [], "context_rows": []}
    return {"id": "ERR-x", "payload": payload, "schema": {"type": "object"}}


def _answer(verdict, *issues):
    return {"board": "b", "omissions": [], "rows": [{"row_id": ROW["row_id"], "verdict": verdict, "checked_figures": [],
                                                     "checked_rules": [], "issues": list(issues)}]}


def _issue(kind, what="w", correction="c"):
    return {"type": kind, "what": what, "smallest_correction": correction, "keywords": ["urine"],
            "evidence": {"figure": None, "rule": None, "data": None, "dataset_ids": []}}


def _ok(raw, req):
    return True, []


def test_display_note_on_a_confirmed_row_does_not_start_a_rewrite(tmp_path):
    result, _ = rerun(_req([copy.deepcopy(ROW)]), _answer("CONFIRMED", _issue("DISPLAY")), None, _ok, "P", [], [], None, tmp_path, False)
    assert result["status"] == "PASSED" and result["display_notes"][ROW["row_id"]][0]["type"] == "DISPLAY" and not result["rounds"]


def test_value_error_needs_code_not_new_wording(tmp_path):
    calls = []
    result, _ = rerun(_req([copy.deepcopy(ROW)]), _answer("REVISE", _issue("VALUE_ERROR")),
                      lambda *a: calls.append(a), _ok, "P", [], [], None, tmp_path, False)
    assert result["status"] == "NEEDS_CODE_OR_DATA" and not calls and ROW["row_id"] in result["needs_code_or_data"]


@pytest.mark.parametrize("claim", ["7 % of the dose by 8 h.", "62.5 % of the dose by 8 h.",
    "8 % of the dose by 49.1 h.", "49.1 mg of the dose by 8 h.", "49.1 % of the dose by 8 h in 14 animals.",
    "Seven percent of the dose by 8 h.", "No data are available."])
def test_writer_cannot_replace_a_measurement_even_if_reviewer_confirms(tmp_path, claim):
    dispatch = []
    def writer(prompt, schema, images):
        packet = json.loads(prompt.split("\nREQUEST\n", 1)[1])
        if "previous_findings" in packet:
            dispatch.append("review")
            return _answer("CONFIRMED")
        dispatch.append("write")
        return {"rows": [{"row_id": ROW["row_id"], "status_code": "PARTLY_ANSWERABLE", "observed": claim,
                          "basis": "", "reach": "", "missing": []}]}
    result, _ = rerun(_req([copy.deepcopy(ROW)]), _answer("REVISE", _issue("STATUS_TOO_STRONG", "14 animals")),
                      writer, _ok, "P", [], [], None, tmp_path, False)
    assert result["status"] == "NEEDS_CODE_OR_DATA" and not result["updated_rows"] and dispatch == ["write"]


def test_writer_can_qualify_a_preserved_measurement_and_rereview_is_retried(tmp_path):
    seen = []
    def model(prompt, schema, images):
        if "REQUEST" in prompt and '"feedback"' in prompt:
            return {"rows": [{"row_id": ROW["row_id"], "status_code": "PARTLY_ANSWERABLE", "observed": ROW["observed"] + " Total recovery remains unknown.",
                              "basis": "", "reach": "", "missing": []}]}
        seen.append("REJECTED BY THE HOST CHECKS" in prompt)
        return _answer("CONFIRMED")
    checks = iter([(False, ["bad"]), (True, [])])
    result, _ = rerun(_req([copy.deepcopy(ROW)]), _answer("REVISE", _issue("FIGURE_TEXT_MISMATCH", "the figure shows 14 animals")),
                      model, lambda raw, req: next(checks), "P", [], [], None, tmp_path, False)
    assert result["status"] == "PASSED" and seen == [False, True]


def test_review_uses_the_rules_the_run_used(tmp_path):
    import hashlib
    import json
    run_rules = R.run_rules
    rules = tmp_path / "_engine" / "rules"
    rules.mkdir(parents=True)
    (rules / "dist.md").write_text("## 24\nrule text\n", encoding="utf-8")
    sha = hashlib.sha256((rules / "dist.md").read_bytes()).hexdigest()
    (rules / "rules_manifest.json").write_text(json.dumps({"sections": {"distribution": {"version": "r1.3", "file": "dist.md", "sha256": sha}}}), encoding="utf-8")
    (tmp_path / "run_record.json").write_text(json.dumps({"rules": {"distribution": {"version": "r1.3", "file": "dist.md", "sha256": sha}}}), encoding="utf-8")
    assert run_rules(tmp_path) == {"distribution": str(rules / "dist.md")}
    assert R.rule_problems(tmp_path, {"distribution"}, {"distribution": sha}) == []
    other = tmp_path / "old.md"
    other.write_text("## 24\nolder text\n", encoding="utf-8")
    assert R.rule_problems(tmp_path, {"distribution"}, {"distribution": hashlib.sha256(other.read_bytes()).hexdigest()})
