import copy
import hashlib
import json
from pathlib import Path

import pytest

from research_pipeline.context_reference_scope import ReferenceScopeError, project


ROOT = Path(__file__).resolve().parents[3]
REFERENCE = ROOT / "backend" / "rules" / "eda" / "eda_scientific_reference.txt"
CATALOG = ROOT / "backend" / "research_pipeline" / "research_pipeline" / "resources" / "context_builder" / "reference_catalogs" / "eda.20261013.json"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _payload():
    return {
        "scientific_reference": {
            "locator": str(REFERENCE),
            "text": REFERENCE.read_bytes().decode("utf-8"),
        },
        "project_rules": {"rule_count": 56, "G001-G008": ["authoritative governance"]},
        "governance": {"mandatory": ["G001", "G008"]},
        "evidence": {"source_rows": 148, "source_ids": ["T28", "T13", "T10"]},
        "other": {"must_remain": True},
    }


def _spec(catalog_path=CATALOG, selected=None):
    raw = Path(catalog_path).read_bytes()
    return [{
            "path": ["scientific_reference", "text"],
            "catalog": {"path": str(catalog_path), "sha256": _sha(raw)},
            "selected": list(selected if selected is not None else ["01", "02", "03", "06", "08", "11", "15"]),
        }]


def _clone_catalog(tmp_path, mutate):
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    catalog["source"]["path"] = str(REFERENCE)
    mutate(catalog)
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(catalog, ensure_ascii=False), encoding="utf-8")
    return path


def test_projection_keeps_exact_selected_sections_and_required_closure():
    payload = _payload()
    original = copy.deepcopy(payload)
    projected, audit, bindings = project(payload, _spec())
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    included = audit["fields"][0]["included"]
    included_ids = {item["id"] for item in included}

    assert {"01", "02", "03", "06", "08", "11", "15"} <= included_ids
    assert {"GLOBAL", "SOURCE_KEY"} <= included_ids
    assert {"B01", "B02", "B03", "B04", "B05", "B06", "B07", "B09", "B10"} <= included_ids
    # The selected guidance's literature citations are included as exact provenance sections.
    assert {"WEB02", "WEB03", "WEB04", "WEB05", "WEB08", "WEB09", "WEB11", "WEB12"} <= included_ids
    by_id = {section["id"]: section for section in catalog["sections"]}
    expected_text = "".join(
        payload["scientific_reference"]["text"][by_id[item["id"]]["start"] : by_id[item["id"]]["end"]]
        for item in catalog["sections"]
        if item["id"] in included_ids
    )
    assert projected["scientific_reference"]["text"] == expected_text
    assert projected["scientific_reference"]["locator"] == payload["scientific_reference"]["locator"]
    for key in ("project_rules", "governance", "evidence", "other"):
        assert projected[key] == payload[key]
    assert payload == original  # pure operation; full host reference remains untouched
    assert audit["fields"][0]["omitted_ids"]
    assert bindings["reference_scope.scientific_reference.text.source"]["sha256"] == _sha(REFERENCE.read_bytes())
    assert Path(bindings["reference_scope.scientific_reference.text.source"]["path"]).is_absolute()


def test_rejects_protected_or_non_allowlisted_fields():
    payload = _payload()
    allowed_catalog = _spec()[0]["catalog"]
    for path in (("project_rules",), ("governance",), ("evidence",), ("other", "must_remain")):
        with pytest.raises(ReferenceScopeError):
            project(payload, {path: {"catalog": allowed_catalog, "selected": ["01"]}})

    alternate = {"method_reference": {"text": payload["scientific_reference"]["text"]}}
    result, _, _ = project(
        alternate,
        [{"path": ["method_reference", "text"], "catalog": allowed_catalog, "selected": ["02"]}],
        allowed_paths=[["method_reference", "text"]],
    )
    assert "02 | INDIVIDUAL" in result["method_reference"]["text"]


def test_rejects_catalog_file_hash_mismatch():
    payload = _payload()
    bad = {("scientific_reference", "text"): {"catalog": {"path": str(CATALOG), "sha256": "0" * 64}, "selected": ["02"]}}
    with pytest.raises(ReferenceScopeError, match="catalog hash mismatch"):
        project(payload, bad)


def test_rejects_incomplete_partition_even_when_catalog_file_hash_is_current(tmp_path):
    payload = _payload()
    path = _clone_catalog(tmp_path, lambda c: c["sections"][1].update(start=c["sections"][1]["start"] + 1))
    with pytest.raises(ReferenceScopeError, match="partition is incomplete"):
        project(payload, _spec(path, ["02"]))


def test_rejects_unknown_selected_section_and_missing_dependency(tmp_path):
    with pytest.raises(ReferenceScopeError, match="unknown selected section"):
        project(_payload(), _spec(selected=["S02"]))

    def remove_dependency(catalog):
        catalog["sections"][0]["requires"] = ["NO_SUCH_SECTION"]

    path = _clone_catalog(tmp_path, remove_dependency)
    with pytest.raises(ReferenceScopeError, match="unknown dependency"):
        project(_payload(), _spec(path, ["02"]))


def test_global_dependency_closure_is_included(tmp_path):
    path = _clone_catalog(tmp_path, lambda c: c["sections"][0]["requires"].append("WEB01"))
    _, audit, _ = project(_payload(), _spec(path, ["02"]))
    assert "WEB01" in {item["id"] for item in audit["fields"][0]["included"]}


def test_rejects_source_hash_mismatch_and_unbound_payload_text(tmp_path):
    payload = _payload()
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    catalog["source"]["path"] = str(REFERENCE)
    catalog["source"]["sha256"] = "0" * 64
    path = tmp_path / "source_hash_mismatch.json"
    path.write_text(json.dumps(catalog), encoding="utf-8")
    with pytest.raises(ReferenceScopeError, match="source hash mismatch"):
        project(payload, _spec(path, ["02"]))

    payload["scientific_reference"]["text"] += "tampered"
    with pytest.raises(ReferenceScopeError, match="differs from the bound source"):
        project(payload, _spec())

