"""Thin routing after native EDA review; two ContextBuilder calls, no models."""
import argparse
import json
from pathlib import Path

from ctxcomp.io import digest
from . import context_builder as cb
from . import eda_review_handoff as gate
from .common import read_json, write_json


def _source(root, preview):
    p = gate.packet(root)
    gate.require(p["version"] == "EDA_QUESTION_HUMAN_PACKET_1",
                 "question-driven EDA packet required")
    assignments = (read_json(p["bindings"]["branch_drafts"]["path"]) if preview
                   else {b: gate.branch_input(root, b) for b in ("PK", "PD")})
    inputs = read_json(p["bindings"]["context"]["path"])
    source = {"inputs": inputs,
              "findings": read_json(p["bindings"]["findings"]["path"])}
    refs = {"review_packet": cb.file_ref(root / "human_review.json"),
            "router": cb.file_ref(__file__),
            "review_gate": cb.file_ref(gate.__file__)}
    if not preview:
        refs["approved_release"] = cb.file_ref(root / "approved_release.json")
    original = p["bindings"].get("input")
    source["normalized_files"] = (
        read_json(original["path"]).get("data_handoff", {}).get("files", [])
        if original else [])
    tables = read_json(p["bindings"]["source_tables"]["path"])
    table_ids = {t["dataset_id"] for t in tables}
    for branch, assignment in assignments.items():
        gate.require(assignment["branch"] == branch, "branch identity differs")
        gate.require(set(assignment["dataset_ids"]
                         + assignment["shared_context_dataset_ids"]) <= table_ids,
                     "branch references unknown datasets")
    cb.check_refs(p["bindings"])
    return p, assignments, source, refs


def build(root, out=None, *, preview=False):
    root = Path(root).resolve()
    out = Path(out).resolve() if out else root / (
        "task_assignment_draft" if preview else "task_assignment")
    p, assignments, source, refs = _source(root, preview)
    marker = out / "routing_plan.json"
    if marker.exists():
        previous = inspect(out)
        gate.require(previous["packet_sha256"] == p["content_sha256"]
                     and previous["preview"] == preview,
                     "assignment differs; use a new output directory")
        return previous
    # Prepare both in memory. A final marker is the only publish point.
    bundles = {b: cb.build_branch_handoff(source, assignments[b], input_bindings=refs)
               for b in ("PK", "PD")}
    out.mkdir(parents=True, exist_ok=True)
    outputs = {}
    for branch, bundle in bundles.items():
        path = out / (branch + ".context.json")
        write_json(path, bundle)
        outputs[branch] = cb.file_ref(path)
    gate.packet(root)
    cb.check_refs(refs)
    cb.check_refs(outputs)
    plan = {"version": "EDA_TASK_ASSIGNMENT_1", "root": str(root),
            "packet_sha256": p["content_sha256"], "preview": preview,
            "status": ("BLOCKED_PENDING_HUMAN_APPROVAL" if preview
                       else "READY_FOR_INPUT_QUALIFICATION"),
            "branches": outputs, "input_bindings": refs,
            "model_calls": 0, "fit_ready": False, "scientific_release": False}
    plan["content_sha256"] = digest(plan)
    write_json(marker, plan)
    return plan


def inspect(out):
    """Check transitive EDA bindings as well as generated branch files."""
    plan = read_json(Path(out) / "routing_plan.json")
    expected = plan.pop("content_sha256")
    gate.require(digest(plan) == expected, "routing plan changed")
    plan["content_sha256"] = expected
    cb.check_refs(plan["input_bindings"])
    cb.check_refs(plan["branches"])
    p = gate.packet(plan["root"])
    gate.require(p["content_sha256"] == plan["packet_sha256"], "packet differs")
    for branch, ref in plan["branches"].items():
        context = cb.verify_branch_handoff(read_json(ref["path"]))
        gate.require(context["branch"] == branch, "branch identity differs")
        if not plan["preview"]:
            gate.branch_input(plan["root"], branch)
    return plan


def consume(out, branch):
    """Downstream input qualification API; return exact selected source rows."""
    gate.require(branch in {"PK", "PD"}, "unknown branch")
    plan = inspect(out)
    gate.require(not plan["preview"], "human approval required; draft context")
    context = cb.verify_branch_handoff(read_json(plan["branches"][branch]["path"]))
    tables = read_json(context["source_tables_ref"]["path"])
    direct, shared = set(context["dataset_ids"]), set(context["shared_context_dataset_ids"])
    result = {"context": context,
              "source_tables": [t for t in tables if t["dataset_id"] in direct],
              "shared_context_tables": [t for t in tables if t["dataset_id"] in shared]}
    inspect(out)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True)
    parser.add_argument("--out")
    parser.add_argument("--preview", action="store_true")
    args = parser.parse_args()
    print(json.dumps(build(args.run, args.out, preview=args.preview), indent=2))


if __name__ == "__main__":
    main()
