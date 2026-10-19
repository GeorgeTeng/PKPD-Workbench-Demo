"""Replay authored fixtures through the workflow; not a model evaluation."""
import argparse
from pathlib import Path
from ctxcomp.engine import STAGES, init_run, prepare, accept, verify
from ctxcomp.io import read_json, write_json, leaves

ROOT = Path(__file__).parent / "current_research"


def spans_for_quote(quote, units, source_id="S1"):
    """Map an authored fixture quote across original audit-unit boundaries."""
    source_units = [u for u in units if u["source_id"] == source_id]
    text = "".join(u["text"] for u in source_units)
    start = text.index(quote)
    end = start + len(quote)
    spans = []
    for unit in source_units:
        left, right = max(start, unit["start_char"]), min(end, unit["end_char"])
        if left < right and text[left:right].strip():
            spans.append({"source_id": source_id, "unit_id": unit["id"], "quote": text[left:right]})
    return spans


def fixture_requirements(quotes, units, source_id='S1'):
    return {"version": "1.1", "potential_questions": [], "items": [
        {"id": f"R{i:03d}", "kind": "FACT",
         "statement": quote, "critical": True,
         "rationale": "Authored demonstration requirement; not an independent reference standard.",
         "downstream_effect": "Retain the stated research scope and limitations.",
         "selection": {"explicit": True, "applicable": True, "technical": True, "material": True},
         "science": {"role": "OTHER", "evidence_status": "SOURCE_REPORTED", "method_refs": [],
                     "bindings": [], "adoption_relations": [], "relations": []},
         "components": [{"id": "C1", "role": "ACTION" if path.startswith("/rules/") else "FACT",
                         "text": quote, "evidence": spans_for_quote(quote, units, source_id)}]}
        for i, (path, quote) in enumerate(quotes.items(), 1)]}


def fixture_requirements_review(requirements, units):
    return {"decision": "PASS", "reviewer": "Authored demonstration fixture",
            "review_type": "ASSISTANT_INTERNAL_REVIEW",
            "items": [{"requirement_id": r["id"], "verdict": "PRESERVED", "reason": "Fixture judgment only."}
                      for r in requirements["items"]],
            "source_units": [{"unit_id": u["id"], "requirement_ids": [r["id"] for r in requirements["items"]
                              if any(s["unit_id"] == u["id"] for c in r["components"] for s in c["evidence"])],
                              "verdict": "PRESERVED", "reason": "Authored fixture coverage; no independent completeness claim."}
                             for u in units],
            "critical_errors": [], "limitations": ["Authored test labels, not model or expert evaluation."]}


def fixture_coverage(requirements, paths, context):
    values = dict(leaves(context))
    return [{"requirement_id": r["id"], "verdict": "PRESERVED", "reason": "Authored fixture judgment.",
             "components": [{"component_id": c["id"], "verdict": "PRESERVED",
                             "targets": [{"path": path, "quote": values[path]}],
                             "reason": "Fixture maps the requirement to this field."} for c in r["components"]]}
            for r, path in zip(requirements["items"], paths)]


def fixture_atoms(context, evidence, units):
    # Mechanically constructed test records exercise contracts only, not atomization accuracy.
    atoms, decomposition = [], []
    values = dict(leaves(context))
    for i, item in enumerate(evidence):
        path = item["path"].removeprefix("/context")
        identifier = f"A{i:03d}"
        atoms.append({"id": identifier, "path": path, "quote": values[path], "statement": values[path],
                      "status": item["status"], "evidence": spans_for_quote(item["quote"], units, item["source_id"])
                      if item["quote"] else [], "verdict": "PRESERVED", "reason": "Fixture judgment only."})
        decomposition.append({"path": path, "claim_ids": [identifier], "verdict": "PRESERVED",
                              "reason": "Coarse authored fixture, not a validated atomic decomposition."})
    return atoms, decomposition


def replay(out):
    init_run(out, ROOT / "proposal.md", inventory_path=ROOT / "inventory.json",
             policy=read_json(ROOT / "policy.json"), context_review_mode='legacy')
    context = read_json(ROOT / "context.json")
    quotes = read_json(ROOT / "evidence_quotes.json")
    evidence = []
    for path, value in leaves(context):
        if path == "/version":
            continue
        status = "NOT_FOUND" if value == "NOT_FOUND" else "EXPLICIT" if path in quotes else "PROPOSED"
        evidence.append({"path": path, "status": status,
                         "source_id": "S1" if path in quotes else "", "quote": quotes.get(path, ""),
                         "reason": "Assistant-authored demonstration mapping; explicit source span, stated absence, or proposed data preparation requirement as labelled."})
    responses = {}
    for stage in STAGES:
        req = prepare(out, stage)
        response = {"request_sha256": req["request_sha256"]}
        if stage == "attachment_plan":
            # Authored fixture only; this is not a live search-quality result.
            response['questions'] = []
        elif stage == "attachment_evidence":
            response['answers'] = []
        elif stage == "requirements":
            response["requirements"] = fixture_requirements(quotes, req["payload"]["source_units"])
        elif stage == "requirements_review":
            response["review"] = fixture_requirements_review(req["payload"]["requirements"], req["payload"]["source_units"])
        elif stage == "context":
            response.update(context=context, evidence=evidence)
        elif stage == "pipeline":
            response["pipeline"] = read_json(ROOT / "pipeline.json")
        else:
            target = context if stage == "context_review" else responses["pipeline"]["pipeline"]
            if stage == "context_review":
                claims = [{"path": p, "verdict": "PRESERVED", "reason": next(e["reason"] for e in evidence if e["path"] == p)}
                          for p, _ in leaves(target) if p != "/version"]
            else:
                claims = [{"path": f"/blocks/{i}", "verdict": "PRESERVED",
                           "reason": f"Suggested step serves '{b['purpose']}' with explicit inputs, outputs and conditional scope; no numerical execution claimed."}
                          for i, b in enumerate(target["blocks"])]
                claims += [{"path": f"/data_files/{i}", "verdict": "PRESERVED",
                            "reason": f"{f['id']} is correctly treated as {f['availability']}; attributes remain unknown where the brief is silent."}
                           for i, f in enumerate(target["data_files"])]
            response["review"] = {
                "decision": "PASS", "reviewer": "Assistant compiling this demonstration",
                "review_type": "ASSISTANT_INTERNAL_REVIEW", "claims": claims,
                "retention": [{"source_id": "S1", "quote": q, "verdict": "PRESERVED", "critical": True,
                               "reason": "Constraint retained in the compact context and applicable proposed workflow."}
                              for q in quotes.values()],
                "critical_errors": [], "limitations": ["Same-assistant example generation and internal review; no independent semantic accuracy estimate.",
                                                          "Workflow is a proposal, not executed PK/PD analysis. Original Mac sources were not recovered."]}
            if stage == "context_review":
                atoms, decomposition = fixture_atoms(context, evidence, req["payload"]["source_units"])
                response["review"]["scientific_checks"] = [
                    {"id": r["id"], "faithfulness": "PRESERVED", "completeness": "PRESERVED",
                     "reason": "Authored structural fixture, not a scientific classification accuracy test."}
                    for r in req["payload"]["requirements"]["items"]]
                response["review"].update(atomic_claims=atoms, decomposition=decomposition,
                    coverage=fixture_coverage(req["payload"]["requirements"], quotes, context))
                response["review"]["limitations"].append("Coarse mechanically constructed fixture claims test contracts, not atomic-decomposition quality.")
        write_json(Path(out) / "saved_responses" / f"{stage}.json", response)
        accept(out, stage, response, provider="assistant_authored_example_replay")
        responses[stage] = response
    write_json(Path(out) / "demo_provenance.json", {
        "generation": "Assistant-authored demonstration based on current conversation constraints",
        "runtime": "Saved-response replay through installed program; no model backend invoked",
        "semantic_evaluation": "Internal review only; independent scores intentionally null",
        "clinical_or_animal_data_used": False})
    return verify(out)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    print(replay(args.out))
