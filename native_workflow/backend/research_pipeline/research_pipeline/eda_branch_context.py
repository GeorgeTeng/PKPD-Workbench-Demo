"""Lossless branch selection from the question-driven EDA handoff."""
import copy

QUESTIONS = {
    "PK": {"Q_PK_SHAPE", "Q_PK_VARIABILITY"},
    "PD": {"Q_PD_EFFECT", "Q_INDEX", "Q_TIMEKILL"},
}


def project(source, assignment):
    """Select by explicit EDA IDs; shared evidence never becomes observations."""
    branch = assignment["branch"]
    if branch not in QUESTIONS:
        raise ValueError("Unknown EDA branch: " + branch)
    ids = set(assignment["dataset_ids"])
    shared = set(assignment["shared_context_dataset_ids"])
    inputs = source["inputs"]
    task = inputs["task_context"]
    data = inputs.get("data_handoff", {})
    stage = "animal_pk" if branch == "PK" else "index"
    rules, excluded, unresolved = [], [], []
    for rule in task.get("project_rules", []):
        scope = rule.get("used_in")
        if not scope:
            rules.append(copy.deepcopy(rule))
            unresolved.append(rule.get("id"))
        elif stage in scope or "dispatch" in scope:
            rules.append(copy.deepcopy(rule))
        else:
            excluded.append(rule.get("id"))
    normalized = source.get("normalized_files", [])

    def files(selected):
        return [copy.deepcopy(f) for f in normalized if f["id"] in selected]

    figures = {f["figure_id"]: f for f in inputs["figure_bundle"]["figures"]}
    findings = {f["finding_id"]: f for f in source["findings"]["findings"]}
    context = {
        "version": "EDA_BRANCH_CONTEXT_1",
        "branch": branch, "module": "pk" if branch == "PK" else "index",
        "status": assignment["status"],
        "next_step": "INPUT_QUALIFICATION",
        "objective": task.get("objective"),
        "study": copy.deepcopy(task.get("study", {})),
        "shared_context_ref": assignment["context_ref"],
        "dataset_ids": sorted(ids),
        "shared_context_dataset_ids": sorted(shared),
        "source_tables_ref": assignment["source_tables_ref"],
        "dataset_routing": copy.deepcopy(assignment.get("dataset_routing", [])),
        "dataset_routing_ref": copy.deepcopy(assignment.get("dataset_routing_ref")),
        "normalized_files": files(ids),
        "shared_normalized_files": files(shared),
        "missing_normalized_dataset_ids": sorted(ids - {f["id"] for f in normalized}),
        "project_rules": rules,
        "rule_selection": {
            "stage": stage, "excluded_rule_ids": excluded,
            "unresolved_scope_rule_ids": unresolved,
            "all_rules_ref": assignment["context_ref"],
        },
        "analyses": [copy.deepcopy(a) for a in inputs["eda_plan"]["analyses"]
                     if a["analysis_id"] in QUESTIONS[branch] | {"Q_CONTEXT"}],
        "figures": [copy.deepcopy(figures[f]) for f in assignment["figure_ids"]],
        "findings": [copy.deepcopy(findings[f]) for f in assignment["finding_ids"]],
        "data_policy": {k: copy.deepcopy(v) for k, v in data.items()
                        if k not in {"admitted_evidence", "dataset_action_readiness"}},
        "dataset_action_readiness": [
            copy.deepcopy(r) for r in data.get("dataset_action_readiness", [])
            if r["dataset_id"] in ids | shared],
        "open_items": copy.deepcopy(assignment["open_items"]),
        "limitations": copy.deepcopy(assignment["limitations"]),
        "excluded_sources": copy.deepcopy(assignment["excluded_sources"]),
        "dependencies": ([] if branch == "PK" else [{
            "kind": "PK_EXPOSURE", "status": "UNRESOLVED",
            "required_before": "EXPOSURE_DEPENDENT_ANALYSIS",
            "input_qualification_may_proceed": True,
        }]),
        "model_selected": False, "fit_ready": False,
        "model_execution_started": False, "scientific_release": False,
    }
    return context
