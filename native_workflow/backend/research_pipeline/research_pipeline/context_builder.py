"""Deterministic, lossless request assembly; no model, file search or stage launch.

Version 1 preserves stage-adapter decisions. It does not select scientific Rules
or prune evidence. Historical snapshots can be compared without granting reuse.
"""
import argparse
import copy
import json
from pathlib import Path

from ctxcomp import governance
from ctxcomp.io import digest
from jsonschema import Draft202012Validator
from .common import PipelineError, read_json, write_json, sha256

CONFIG = Path(__file__).parent / "resources/context_builder/routes.v2.json"
VERSION = "CONTEXT_BUILDER_2.1"


def fail(message):
    raise PipelineError("CONTEXT_BUILD_INVALID", message)


def file_ref(path):
    path = Path(path).resolve()
    return {"path": str(path), "sha256": sha256(path)}


def check_refs(refs):
    for name, ref in refs.items():
        if file_ref(ref["path"]) != ref:
            fail("Changed input: " + name)


def check_governance(value):
    if not isinstance(value, dict):
        fail("Missing governance object")
    rules = value.get("rules", [])
    if value.get("scope") != "ALL_WORKFLOW_STEPS" or [r.get("id") for r in rules] != [
            f"G{i:03}" for i in range(1, 9)]:
        fail("Expected canonical G001-G008 once")
    if any(not r.get("instruction") or not r.get("actions") for r in rules):
        fail("Governance IDs without complete rule text")


def build_context(stage, operation, payload, schema, *, input_bindings=None,
                  historical_snapshot=False):
    """Build one request; unknown fields fail rather than being dropped.

    Fresh builds bind current governance. Snapshot builds preserve recorded
    governance for offline comparison only and never authorize execution/reuse.
    Caller stage adapters remain responsible for permissions and scientific
    input validation. Only explicit file bindings are checked here.
    """
    config_ref = file_ref(CONFIG)
    config = read_json(CONFIG)
    route_id = stage + "." + operation
    route = config["routes"].get(route_id)
    if route is None:
        fail("Unsupported route: " + route_id)
    if not isinstance(payload, dict) or not isinstance(schema, dict):
        fail("Payload and output schema must be objects")
    refs = copy.deepcopy(input_bindings or {})
    carried = payload.get('context_task_bindings', {})
    if not isinstance(carried, dict):
        fail('Task bindings must be a host file-reference object')
    for name, ref in carried.items():
        if name in refs and refs[name] != ref:
            fail('Conflicting carried task binding: ' + name)
        refs[name] = copy.deepcopy(ref)
    if 'context_selection' in payload:
        from .context_task import validate_selection
        _, _, selection_refs = validate_selection(payload, route_id)
        for name, ref in selection_refs.items():
            if name in refs and refs[name] != ref:
                fail('Conflicting reference selection binding: ' + name)
        refs.update(selection_refs)
    if stage == 'eda':
        from .eda_context import validate_payload
        eda_refs = validate_payload(payload, operation, schema)
        for name, ref in eda_refs.items():
            if name in refs and refs[name] != ref:
                fail('Conflicting EDA binding: ' + name)
        refs.update(eda_refs)
    check_refs(refs)
    if 'context_support' in payload:
        from .context_handoff import validate_support
        validate_support(payload['context_support'], refs, route_id)
    wire = copy.deepcopy(payload)
    if not isinstance(wire.get("instructions"), str) or not wire["instructions"].strip():
        fail("An explicit operation prompt is required")
    if "schema" in wire and wire["schema"] != schema:
        fail("Conflicting response schemas")
    try:
        Draft202012Validator.check_schema(schema)
    except Exception as exc:
        fail("Invalid response schema: " + str(exc))
    wire["schema"] = copy.deepcopy(schema)
    for key, allowed in route["identity"].items():
        if wire.get(key) not in allowed:
            fail("Payload identity does not match route: " + key)
    missing = set(route["required"]) - wire.keys()
    if missing:
        fail("Missing required sections: " + ", ".join(sorted(missing)))
    allowed = set(config["common_fields"] + route["required"] + route["optional"])
    allowed.update(route["identity"])
    extra = wire.keys() - allowed
    if extra and not route.get('preserve_adapter_fields', False):
        fail("Unexpected sections for " + route_id + ": " + ", ".join(sorted(extra)))
    for key in route["required"]:
        if wire[key] is None:
            fail("Null required section: " + key)
    # Never rewrite a stored prompt or swap the governance version in a replay.
    if historical_snapshot:
        if "governance" not in wire:
            fail("Historical request must contain its governance snapshot")
        gov = copy.deepcopy(wire["governance"])
    else:
        gov = governance.load_governance()
        if "governance" in wire and wire["governance"] != gov:
            fail("Fresh request contains stale or conflicting governance")
    check_governance(gov)
    if "governance_sha256" in wire and wire["governance_sha256"] != digest(gov):
        fail("Governance hash mismatch")
    governance.attach_governance(wire, gov)
    request = {"request_sha256": digest(wire), "payload": wire}
    size = len(json.dumps(request, ensure_ascii=False))
    if size > config["max_request_chars"]:
        fail("Request exceeds capacity; no content was truncated")
    for key in route["rules"]:
        if key in wire and isinstance(wire[key], list):
            ids = [r.get("id") for r in wire[key] if isinstance(r, dict)]
            if len(ids) != len(wire[key]) or any(not i for i in ids) or len(set(ids)) != len(ids):
                fail("Ambiguous or duplicate rule IDs in " + key)
    sections = {}
    for key, value in wire.items():
        kind = ("instructions" if key == "instructions" else
                "output_schema" if key == "schema" else
                "rules" if key == "governance" or key in route["rules"] else
                "evidence" if key in route["evidence"] else "task_metadata")
        sections[key] = {"kind": kind, "sha256": digest(value),
                         "characters": len(json.dumps(value, ensure_ascii=False))}
    check_refs(refs)
    check_refs({"route_config": config_ref})
    manifest = {
        "version": VERSION, "route": route_id, "mode": config["mode"],
        "request_sha256": request["request_sha256"],
        "instructions_sha256": digest(wire["instructions"]),
        "schema_sha256": digest(schema), "governance_sha256": digest(gov),
        "builder": file_ref(__file__), "route_config": config_ref,
        "input_bindings": refs, "sections": sections, "request_characters": size,
        "size_note": "Serialized character counts, not model token counts.",
        "content_policy": route["boundary"], "dropped_fields": [],
        "rule_filtering": False, "evidence_pruning": False,
        "adapter_extra_fields_preserved": sorted(extra),
        "permissions_checked_by": "Existing stage adapter; builder does not grant source access.",
        "historical_snapshot_only": historical_snapshot,
        "model_calls": 0, "scientific_approval": False, "downstream_executed": False,
        "execution_authorized": False,
    }
    return {"request": request, "context_manifest": manifest}


def verify_bundle(bundle):
    """Reconstruct and compare before any caller consumes a prepared bundle."""
    manifest = bundle["context_manifest"]
    check_refs({"builder": manifest["builder"], "route_config": manifest["route_config"]})
    check_refs(manifest["input_bindings"])
    stage, operation = manifest["route"].split(".", 1)
    request = bundle["request"]
    if digest(request["payload"]) != request["request_sha256"]:
        fail("Request content/hash mismatch")
    rebuilt = build_context(stage, operation, request["payload"],
                            request["payload"]["schema"],
                            input_bindings=manifest["input_bindings"],
                            historical_snapshot=manifest["historical_snapshot_only"])
    if rebuilt != bundle:
        fail("Context bundle differs from its deterministic reconstruction")
    return bundle


def rebuild_snapshot(stage, operation, path):
    """Rebuild a stored request without executing or treating old bindings as current."""
    reference = file_ref(path)
    original = read_json(path)
    original = original.get("request", original)
    if original.get("request_sha256") != digest(original["payload"]):
        fail("Stored request hash mismatch")
    bundle = build_context(stage, operation, original["payload"],
                           original["payload"]["schema"],
                           input_bindings={"request_snapshot": reference},
                           historical_snapshot=True)
    if bundle["request"] != original:
        fail("Lossless rebuild changed the stored request")
    return bundle


def save_bundle(out, bundle):
    verify_bundle(bundle)
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=False)
    write_json(out / "request.json", bundle["request"])
    write_json(out / "context_manifest.json", bundle["context_manifest"])
    return out


def build_branch_handoff(source, assignment, *, input_bindings):
    """Assemble one native EDA intake context without a model request."""
    from . import eda_branch_context
    refs = copy.deepcopy(input_bindings)
    refs.update(context_builder=file_ref(__file__),
                branch_adapter=file_ref(eda_branch_context.__file__))
    check_refs(refs)
    context = eda_branch_context.project(source, assignment)
    for item in context["normalized_files"] + context["shared_normalized_files"]:
        for key, value in item.items():
            if isinstance(value, dict) and "path" in value and "sha256" in value:
                refs["dataset:" + item["id"] + ":" + key] = {
                    "path": value["path"], "sha256": value["sha256"]}
    bundle = {"context": context, "context_manifest": {
        "version": "EDA_BRANCH_CONTEXT_MANIFEST_1",
        "branch": assignment["branch"], "context_sha256": digest(context),
        "input_bindings": refs, "model_calls": 0,
    }}
    check_refs(refs)
    return bundle


def verify_branch_handoff(bundle):
    manifest = bundle["context_manifest"]
    if manifest.get("version") != "EDA_BRANCH_CONTEXT_MANIFEST_1":
        fail("Unknown EDA branch manifest")
    if (manifest["context_sha256"] != digest(bundle["context"])
            or manifest["branch"] != bundle["context"]["branch"]):
        fail("EDA branch context changed")
    check_refs(manifest["input_bindings"])
    return bundle["context"]


def main():
    parser = argparse.ArgumentParser(description="Offline lossless context assembly; no model calls.")
    parser.add_argument("--stage", required=True)
    parser.add_argument("--operation", required=True)
    parser.add_argument("--request", required=True, help="Stored request.json or prepared.json")
    parser.add_argument("--out", required=True, help="A new output directory")
    args = parser.parse_args()
    bundle = rebuild_snapshot(args.stage, args.operation, args.request)
    out = save_bundle(args.out, bundle)
    print(json.dumps({"out": str(out), "route": bundle["context_manifest"]["route"],
                      "identical_request": True, "model_calls": 0,
                      "snapshot_only": True}, indent=2))


if __name__ == "__main__":
    main()

