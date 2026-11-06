"""Exercise the published report on invented observations; no study fixture is distributed."""
import json
from html import unescape

from research_pipeline import eda_absorption as absorption


def test_group_means_with_no_iv_reference(tmp_path):
    dataset = {
        "dataset_id": "T0901", "study_source_ids": ["S91"], "role": "PK_OBSERVATIONS",
        "title": "Synthetic SC mouse plasma profile, 1 mg/kg",
        "experimental_unit": "Group means", "notes": "Constructed example",
        "metadata": {"species": "mouse", "route_class": "EV", "route_detail": "SC",
                     "matrix": "plasma", "matrix_category": "PLASMA_SERUM_BLOOD",
                     "record_category": "GROUP_SUMMARY", "observation_source": "REPORTED",
                     "dose_basis": "active", "dosing_regimen": "Single SC dose"},
        "columns": [{"id": "time_h", "meaning": "TIME", "unit": "h"},
                    {"id": "mean", "meaning": "CONCENTRATION", "unit": "mg/L", "header": "Mean"}],
        "records": [{"record_id": f"R{i}", "time_h": t, "mean": c, "qc_status": "TECHNICALLY_RETAINED",
                     "value_status": {"time_h": "QUANTIFIED", "mean": "QUANTIFIED"}}
                    for i, (t, c) in enumerate([(0.5, 2), (1, 6), (2, 3), (3, 2), (5, 1)])],
    }
    (tmp_path / "source_tables.json").write_text(json.dumps([dataset]), encoding="utf-8")
    (tmp_path / "report.html").write_text('<html lang="en"></html>', encoding="utf-8")
    folder = absorption.attach(tmp_path)
    assert not (folder / "error.json").exists()
    result = json.loads((folder / "absorption.json").read_text(encoding="utf-8"))
    board, = result["status_boards"]
    questions = {q["q"]: q for q in board["questions"]}
    assert set(questions) == set(range(1, 10))
    assert questions[7]["status_code"] == "NOT_ANSWERABLE_YET" and "bioavailability" in questions[7]["label"].lower()
    assert questions[5]["status_code"] == "NOT_ANSWERABLE_YET"
    assert result["version"] == "EDA_ABSORPTION_R4_3"
    assert result["rule_specification"]["version"] == "r4.3"
    assert result["render"]["engine"] in {"R_GGPLOT2", "MATPLOTLIB_FALLBACK"}
    species, = result["presentation"]["species"]
    page = (folder / species["page"]).read_text(encoding="utf-8")
    assert all(f'id="q-s91-{i}"' in page for i in questions)
    assert f'href="{species["page"]}"' in (folder / "index.html").read_text(encoding="utf-8")
    specs = json.loads((folder / "plot_specs.json").read_text(encoding="utf-8"))
    assert specs["figures"] and all((folder / s["file"]).is_file() for s in specs["figures"])
    assert 'href="absorption/index.html"' in (tmp_path / "report.html").read_text(encoding="utf-8")
    ledger = json.loads((folder / "mechanism_candidates.json").read_bytes())
    study, = ledger["studies"]
    assert study["study_id"] == "S91"
    assert len(study["questions"]) == 9
    assert [r["id"] for r in study["candidate_assessments"]] == [c["id"] for c in ledger["catalog"]]
    assert 'href="mechanism_assessment.html"' in (folder / "index.html").read_text(encoding="utf-8")
    for name in ("mechanism_assessment.html", "mechanism_assessment.md"):
        handoff = (folder / name).read_text(encoding="utf-8")
        assert "Single Weibull, 0 < β < 1, fixed positive lag" in handoff.replace("&lt;", "<")
        assert "species-mouse.html#q-s91-8" in handoff
    html = unescape((folder / "mechanism_assessment.html").read_text(encoding="utf-8"))
    # Landing view is a brief. All candidate rows must start inside the closed study context.
    overview, context = html.split('<details class="study-context" id="context-1">', 1)
    assert '<details class="candidate"' not in overview and '<details class="technical">' not in overview
    assert study["reader_brief"] and len(study["reader_brief"]) < len(study["candidate_assessments"])
    for finding in study["reader_brief"]:
        assert finding["observation"] in overview and finding["check"] in overview
        for key in finding["candidate_ids"]:
            assert f'id="study-1-{key}"' in context
    assert 'href="#study-1-' in overview
    blocks = html.split('<details class="candidate"')[1:]
    assert len(blocks) == len(ledger["catalog"])
    for block in blocks:
        # Presentation groups candidates by family, independently of the JSON order.
        key = block.split('data-candidate="', 1)[1].split('"', 1)[0]
        record = next(r for r in study["candidate_assessments"] if r["id"] == key)
        lead, evidence = block.split('<details class="technical">', 1)
        narrative = record["reader_explanation"]
        assert all(narrative.values())
        assert lead.index(narrative["support"]) < lead.index(narrative["alternatives"]) < lead.index(narrative["modeling_check"])
        assert "CANNOT_ASSESS" not in lead and "maximum margin" not in lead.lower()
        assert evidence.startswith("<summary>Technical details and source evidence</summary>")
