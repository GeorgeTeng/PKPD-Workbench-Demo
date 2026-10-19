"""Source inventory and exhaustive review contracts, not a semantic truth oracle."""
import re

from .io import digest, leaves
from .schemas import REQUIREMENTS, REQUIREMENTS_REVIEW, CONTEXT_REVIEW, validate_schema
from .validation import target_pointer

WORKFLOW_VERSION = "proposal-single-handoff-v3"


def source_units(sources):
    """Deterministic paragraph/bounded text units; retain every source character.

    These are audit units, never observation/table splits or content truncation.
    Adjacent units and the full source remain available for cross-unit rules.
    """
    units = []
    for source in sources:
        text = source["text"]
        boundaries = [0] + [m.end() for m in re.finditer(r"\n[ \t]*\n", text)]
        if boundaries[-1] != len(text):
            boundaries.append(len(text))
        index = 0
        for start, end in zip(boundaries, boundaries[1:]):
            while start < end:
                stop = min(start + 4000, end)
                if stop < end:
                    newline = text.rfind("\n", start, stop)
                    if newline > start:
                        stop = newline + 1
                index += 1
                fragment = text[start:stop]
                units.append({"id": f"{source['id']}_U{index:04d}",
                              "source_id": source["id"], "start_char": start,
                              "end_char": stop, "text": fragment,
                              "text_sha256": digest(fragment)})
                start = stop
    return units


def exact_ids(values, expected, label):
    if len(values) != len(set(values)) or set(values) != set(expected):
        raise ValueError(f"{label} must cover every expected ID exactly once")


def span_check(span, units):
    unit = next((u for u in units if u["id"] == span["unit_id"]), None)
    if (not unit or unit["source_id"] != span["source_id"]
            or not span["quote"].strip() or span["quote"] not in unit["text"]):
        raise ValueError("Source evidence must occur verbatim in the declared source unit")
    # Preserve all possible locations instead of silently choosing the first match.
    starts = [m.start() + unit["start_char"]
              for m in re.finditer(re.escape(span["quote"]), unit["text"])]
    return {**span, "matches": [{"start_char": s, "end_char": s + len(span["quote"])}
                               for s in starts]}


def requirements_check(requirements, units, options=None):
    """options: the run's binding checks (bindings.options); exact matching when None."""
    validate_schema(requirements, REQUIREMENTS)
    from .scientific import validate_inventory, STRICT
    validate_inventory(requirements, units, options or STRICT)
    ids = [r["id"] for r in requirements["items"]]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate requirement ID")
    audit = []
    for req in requirements["items"]:
        selection = req["selection"]
        if not selection["explicit"] or not selection["applicable"]:
            raise ValueError("Required source items must be explicit and applicable; report ambiguity in review")
        critical = selection["material"] and (req["kind"] != "RULE" or selection["technical"])
        if req["critical"] != critical:
            raise ValueError("Critical classification contradicts the recorded selection criteria")
        components = [c["id"] for c in req["components"]]
        if len(components) != len(set(components)):
            raise ValueError("Duplicate component ID within requirement")
        for component in req["components"]:
            audit.append({"requirement_id": req["id"], "component_id": component["id"],
                          "evidence": [span_check(s, units) for s in component["evidence"]]})
    return {"requirements_sha256": digest(requirements), "components": audit}


def reject_false_pass(review, bad):
    if review["decision"] == "PASS" and (bad or review["critical_errors"]):
        raise ValueError("PASS contradicts missing/altered/unresolved items or critical errors")


def source_unit_links(requirements, unit_ids):
    """For each reviewed unit, the inventory item and potential-question IDs whose evidence cites it."""
    linked = {unit_id: set() for unit_id in unit_ids}
    for req in requirements["items"]:
        for component in req["components"]:
            for span in component["evidence"]:
                if span["unit_id"] in linked:
                    linked[span["unit_id"]].add(req["id"])
    for question in requirements.get('potential_questions', []):
        for span in question['source_refs']:
            if span['unit_id'] in linked:
                linked[span['unit_id']].add(question['id'])
    return linked


def requirements_review_check(review, requirements, units, reviewed_unit_ids=None, options=None):
    """reviewed_unit_ids: units needing their own verdict (default all); other units are checked where cited."""
    validate_schema(review, REQUIREMENTS_REVIEW)
    requirements_check(requirements, units, options)
    from .scientific import item_ids
    ids = set(item_ids(requirements))
    exact_ids([r["requirement_id"] for r in review["items"]], ids, "Requirement review")
    reviewed = [u["id"] for u in units] if reviewed_unit_ids is None else list(reviewed_unit_ids)
    exact_ids([r["unit_id"] for r in review["source_units"]], reviewed, "Source-unit review")
    linked = source_unit_links(requirements, reviewed)
    for record in review["source_units"]:
        exact_ids(record["requirement_ids"], linked[record["unit_id"]], "Source-to-requirement links")
    bad = any(r["verdict"] != "PRESERVED" for r in review["items"] + review["source_units"])
    reject_false_pass(review, bad)
    return {"decision": review["decision"], "source_units_reviewed": len(reviewed),
            "requirements_reviewed": len(ids), "requirements_sha256": digest(requirements),
            "limitation": "Exhaustive unit records do not prove semantic extraction completeness."}


def context_coverage_check(review, requirements, context, evidence, units):
    validate_schema(review, CONTEXT_REVIEW)
    from .scientific import review_check as scientific_review_check
    scientific_review_check(review, requirements)
    values = {p: v for p, v in leaves(context) if p != "/version"}
    evidence_by_path = {target_pointer(e["path"], "context", values): e for e in evidence}
    exact_ids(list(evidence_by_path), values, "Context evidence")
    paths = set(values)
    req_by_id = {r["id"]: r for r in requirements["items"]}
    exact_ids([r["requirement_id"] for r in review["coverage"]], req_by_id, "Requirement coverage")
    bad = False
    for record in review["coverage"]:
        req = req_by_id[record["requirement_id"]]
        exact_ids([c["component_id"] for c in record["components"]],
                  [c["id"] for c in req["components"]], "Requirement component review")
        component_bad = False
        for component in record["components"]:
            component_bad |= component["verdict"] != "PRESERVED"
            if component["verdict"] == "PRESERVED" and not component["targets"]:
                raise ValueError("Preserved component requires actual context evidence")
            seen_targets = set()
            for target in component["targets"]:
                path = target_pointer(target["path"], "context", paths)
                if (path, target["quote"]) in seen_targets:
                    raise ValueError("Duplicate coverage target")
                seen_targets.add((path, target["quote"]))
                if target["quote"] not in values[path]:
                    raise ValueError("Coverage quote not found in context target")
                if component["verdict"] == "PRESERVED" and evidence_by_path[path]["status"] != "EXPLICIT":
                    raise ValueError("A source requirement cannot be preserved only as PROPOSED or NOT_FOUND")
        if record["verdict"] == "PRESERVED" and component_bad:
            raise ValueError("Preserved requirement contradicts component review")
        bad |= component_bad or record["verdict"] != "PRESERVED"

    atom_ids = [c["id"] for c in review["atomic_claims"]]
    if len(atom_ids) != len(set(atom_ids)):
        raise ValueError("Duplicate atomic claim ID")
    atoms_by_path = {p: set() for p in paths}
    for claim in review["atomic_claims"]:
        path = target_pointer(claim["path"], "context", paths)
        atoms_by_path[path].add(claim["id"])
        if claim["quote"] not in values[path]:
            raise ValueError("Atomic claim quote not found in context field")
        if claim["status"] != evidence_by_path[path]["status"]:
            raise ValueError("Atomic claim status contradicts extraction evidence")
        if claim["status"] == "EXPLICIT" and claim["verdict"] == "PRESERVED" and not claim["evidence"]:
            raise ValueError("Supported atomic fact requires source evidence")
        if claim["status"] == "NOT_FOUND" and claim["evidence"]:
            raise ValueError("NOT_FOUND must not invent supporting source evidence")
        for span in claim["evidence"]:
            span_check(span, units)
        bad |= claim["verdict"] != "PRESERVED"
    exact_ids([target_pointer(d["path"], "context", paths) for d in review["decomposition"]],
              paths, "Atomic decomposition review")
    for record in review["decomposition"]:
        path = target_pointer(record["path"], "context", paths)
        exact_ids(record["claim_ids"], atoms_by_path[path], "Field-to-claim mapping")
        bad |= record["verdict"] != "PRESERVED"
    reject_false_pass(review, bad)
    critical = [r for r in review["coverage"] if req_by_id[r["requirement_id"]]["critical"]]
    unresolved = any(r["verdict"] == "UNRESOLVED" or any(c["verdict"] == "UNRESOLVED"
                     for c in r["components"]) for r in critical)
    preserved = sum(r["verdict"] == "PRESERVED" for r in critical)
    return {"decision": review["decision"], "requirements_sha256": digest(requirements),
            "context_sha256": digest(context), "evidence_sha256": digest(evidence),
            "critical_count": len(critical), "critical_preserved": preserved,
            "critical_recall": preserved / len(critical) if critical and not unresolved else None,
            "coverage": review["coverage"], "atomic_claims": review["atomic_claims"],
            "decomposition": review["decomposition"],
            "independent_accuracy": None,
            "limitation": "Recall is relative to this reviewed inventory. Semantic judgments are not independently validated."}
