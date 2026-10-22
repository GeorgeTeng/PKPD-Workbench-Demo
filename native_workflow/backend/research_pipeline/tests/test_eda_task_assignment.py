"""Offline native EDA routing tests. Synthetic decisions never approve real data."""
import pytest
from research_pipeline import context_builder as cb
from research_pipeline import eda_review_handoff as gate
from research_pipeline import eda_task_assignment as routing
from research_pipeline import eda_workflow as workflow
from research_pipeline.common import read_json, write_json


@pytest.fixture
def package(tmp_path):
    tables = tmp_path / "tables.json"
    write_json(tables, [
        {"dataset_id": "PK1", "columns": [], "records": [{"value": "<0.2", "status": "BLQ"}]},
        {"dataset_id": "PD1", "columns": [], "records": [{"cfu": None, "status": "MISSING"}]},
        {"dataset_id": "SHARED", "columns": [], "records": [{"note": "support only"}]},
    ])
    source = tmp_path / "observations.json"
    write_json(source, {"raw": "unchanged"})
    original = tmp_path / "original.json"
    write_json(original, {"data_handoff": {"files": [{
        "id": "PK1", "role": "PK_OBSERVATIONS", "data": cb.file_ref(source)}]}})
    inputs = {
        "task_context": {"objective": "fixture", "project_rules": [
            {"id": "PK", "text": "PK rule with exception", "used_in": ["animal_pk"]},
            {"id": "PD", "text": "PD rule", "used_in": ["index"]},
            {"id": "ALL", "text": "Shared clause", "used_in": ["dispatch"]},
            {"id": "UNKNOWN", "text": "Unresolved scope stays visible"}]},
        "data_handoff": {"operation_policy": {"PK_MODELING": "RESTRICTED"},
                         "dataset_action_readiness": [
                             {"dataset_id": x, "actions": ["DESCRIPTIVE_ONLY"]}
                             for x in ["PK1", "PD1", "SHARED"]]},
        "eda_plan": {"analyses": [
            {"analysis_id": "Q_PK_SHAPE", "dataset_ids": ["PK1"]},
            {"analysis_id": "Q_PD_EFFECT", "dataset_ids": ["PD1"]}]},
        "figure_bundle": {"tables": {"host_file": cb.file_ref(tables)}, "figures": []},
    }
    inputs["eda_plan"]["dataset_dispositions"] = [
        {"dataset_id": did, "handoff": {"destinations": dest, "role": role,
         "purpose": "Synthetic routing fixture", "pending_checks": ["Fixture qualification"]}}
        for did, dest, role in [("PK1", ["PK"], "OBSERVATIONS"),
                                ("PD1", ["PD"], "OBSERVATIONS"),
                                ("SHARED", ["PK", "PD"], "CONTEXT")]]
    findings = {"version": "QUESTION_FINDINGS_3", "findings": [],
                "open_items": ["fixture issue"], "limitations": ["fixture limitation"]}
    root = tmp_path / "run"
    root.mkdir()
    p = gate.build(root, inputs, findings,
                   {"decision": "PASS", "issues": [], "unreviewed_items": []},
                   {"input": cb.file_ref(original)})
    decision = root / "fixture_decision.json"
    write_json(decision, {
        "actor_type": "HUMAN", "reviewer": "OFFLINE FIXTURE",
        "reviewed_at": "2026-10-20T00:00:00Z", "packet_sha256": p["content_sha256"],
        "decision": "APPROVE_DESCRIPTIVE_EDA", "images_inspected": True,
        "limitations_acknowledged": True, "accepted_open_items": ["fixture issue"],
        "accepted_unreviewed_items": [],
    })
    return root, decision, source, inputs


def test_preview_builds_two_distinct_contexts_but_cannot_release(package, monkeypatch):
    root, _, _, inputs = package
    calls = []
    build = cb.build_branch_handoff
    def counted(source, assignment, **kwargs):
        calls.append(assignment["branch"])
        return build(source, assignment, **kwargs)
    monkeypatch.setattr(cb, "build_branch_handoff", counted)
    plan = routing.build(root, preview=True)
    assert calls == ["PK", "PD"]
    contexts = {b: read_json(ref["path"])["context"] for b, ref in plan["branches"].items()}
    assert contexts["PK"]["dataset_ids"] == ["PK1"]
    assert contexts["PD"]["dataset_ids"] == ["PD1"]
    assert contexts["PK"]["shared_context_dataset_ids"] == ["SHARED"]
    assert [r["id"] for r in contexts["PK"]["project_rules"]] == ["PK", "ALL", "UNKNOWN"]
    assert [r["id"] for r in contexts["PD"]["project_rules"]] == ["PD", "ALL", "UNKNOWN"]
    assert contexts["PK"]["project_rules"][0] == inputs["task_context"]["project_rules"][0]
    assert contexts["PD"]["dependencies"][0]["status"] == "UNRESOLVED"
    assert contexts["PK"]["data_policy"]["operation_policy"]["PK_MODELING"] == "RESTRICTED"
    assert contexts["PD"]["missing_normalized_dataset_ids"] == ["PD1"]
    assert plan["model_calls"] == 0
    for c in contexts.values():
        assert not c["fit_ready"] and not c["model_execution_started"]
    with pytest.raises(ValueError, match="human approval required"):
        routing.consume(root / "task_assignment_draft", "PK")
    assert not (root / "approved_release.json").exists()


def test_confirmation_connects_native_gate_and_preserves_exact_rows(package):
    root, decision, _, _ = package
    workflow.confirm(root, decision)
    out = root / "task_assignment"
    pk = routing.consume(out, "PK")
    pd = routing.consume(out, "PD")
    assert pk["source_tables"] == [{"dataset_id": "PK1", "columns": [], "records": [{"value": "<0.2", "status": "BLQ"}]}]
    assert pd["source_tables"] == [{"dataset_id": "PD1", "columns": [], "records": [{"cfu": None, "status": "MISSING"}]}]
    assert pk["shared_context_tables"] == pd["shared_context_tables"]
    assert pk["context"]["status"] == "READY_FOR_INPUT_QUALIFICATION"
    before = cb.file_ref(out / "routing_plan.json")
    routing.build(root)
    assert cb.file_ref(out / "routing_plan.json") == before


@pytest.mark.parametrize("target", ["decision", "source", "context", "tables", "plan"])
def test_changed_binding_blocks_consumption(package, target):
    root, decision, source, _ = package
    gate.confirm(root, decision)
    out = root / "task_assignment"
    path = {"decision": decision, "source": source, "context": out / "PK.context.json",
            "tables": root.parent / "tables.json", "plan": out / "routing_plan.json"}[target]
    value = read_json(path)
    if isinstance(value, list):
        value[0]["records"][0]["value"] = "999"
    else:
        value["tampered"] = True
    write_json(path, value)
    with pytest.raises(Exception, match="Changed input|routing plan changed"):
        routing.consume(out, "PK")


def test_partial_assignment_retry_keeps_original_approval(package, monkeypatch):
    root, decision, _, _ = package
    original = cb.build_branch_handoff
    def fail(*args, **kwargs):
        raise RuntimeError("fixture assembly failure")
    monkeypatch.setattr(cb, "build_branch_handoff", fail)
    with pytest.raises(RuntimeError, match="fixture assembly failure"):
        gate.confirm(root, decision)
    release = cb.file_ref(root / "approved_release.json")
    assert not (root / "task_assignment/routing_plan.json").exists()
    monkeypatch.setattr(cb, "build_branch_handoff", original)
    routing.build(root)
    assert cb.file_ref(root / "approved_release.json") == release
    assert routing.consume(root / "task_assignment", "PD")["context"]["branch"] == "PD"


def test_unapproved_routing_rejected(package):
    root, *_ = package
    with pytest.raises(ValueError, match="human approval required"):
        routing.build(root)


def test_existing_draft_cannot_be_promoted_in_place(package):
    root, decision, *_ = package
    routing.build(root, preview=True)
    gate.confirm(root, decision)
    with pytest.raises(ValueError, match="assignment differs"):
        routing.build(root, root / "task_assignment_draft")


def test_explicit_routing_survives_qualification_handoff(package):
    root, decision, _, _ = package
    before = read_json(root / "dataset_routing.json")
    assert len(before["datasets"]) == 3
    assert all(r["packaging_status"] == "WAITING_FOR_NEXT_STAGE_PACKAGING" for r in before["datasets"])
    gate.confirm(root, decision)
    context = routing.consume(root / "task_assignment", "PK")["context"]
    assert {r["dataset_id"] for r in context["dataset_routing"]} == {"PK1", "SHARED"}
    assert all(r["packaging_status"] == "PACKAGED_FOR_INPUT_QUALIFICATION" and not r["fit_ready"] for r in context["dataset_routing"])


def test_missing_assignment_is_not_shared_by_default(package):
    from research_pipeline import eda_dataset_routes
    _, _, _, inputs = package
    tables = read_json(inputs["figure_bundle"]["tables"]["host_file"]["path"])
    with pytest.raises(ValueError, match="exactly once"):
        eda_dataset_routes.build(tables, inputs["eda_plan"]["dataset_dispositions"][:-1])


def test_global_image_checkbox_cannot_replace_each_figure_review():
    from research_pipeline import eda_dataset_routes
    with pytest.raises(ValueError, match="every current figure"):
        eda_dataset_routes.validate_figure_review(["F1", "F2"], {"images_inspected": True,
            "figure_reviews": [{"figure_id": "F1", "decision": "ACCEPT"}]})
