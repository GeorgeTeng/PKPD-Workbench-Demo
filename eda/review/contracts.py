"""Necessary conditions for specific endpoints, separate from the model's opinion."""
import copy
import re


def endpoint_limit(section, board, q, project):
    """Return a ceiling only for known board layouts. Absent keys are not empty measurements."""
    n, obs = q.get("q"), q.get("observed") or ""
    if section == "elimination" and n == 7 and board.get("components") == [] and board.get("in_vitro") == []:
        return ("NOT_ANSWERABLE_YET", "EL_COMPONENT_OR_ASSAY",
                "This board has zero excreta component measurements and zero in vitro assay rows.")
    if section != "distribution":
        return None
    if n == 6 and obs.startswith("Unbound plasma exposure is unknown."):
        b = board.get("binding") or {}
        if (b.get("plasma_unbound_status") == "UNKNOWN" and b.get("unbound_points") == []
                and b.get("unbound_auc_window") == [] and not b.get("conditional_fu")):
            return ("PARTLY_ANSWERABLE", "DIST_UNBOUND_EXPOSURE",
                    "Binding can be described, but the board has neither unbound plasma points nor an unbound AUC.")
    if n == 5 and "A fixed tissue-to-blood ratio cannot be checked across times." in obs:
        pairs = board.get("tissue_pairs")
        if isinstance(pairs, list) and pairs and all(isinstance(p.get("n_common_times"), int)
                                                     and p["n_common_times"] < 2 for p in pairs):
            return ("PARTLY_ANSWERABLE", "DIST_PAIRED_TIMES",
                    "Every tissue/reference pair has fewer than two common times. Tissue observations remain reportable.")
    if n == 7 and q.get("scope") == "project" and re.fullmatch(
            r"Project level: \d+ species with an? (?:item 25|initial-volume) bound \([^)]*\)\.", obs):
        species = project.get("species_with_bound")
        if (isinstance(species, list) and len(set(species)) < 2 and project.get("comparable_definitions") == []
                and not board.get("conditions")):
            return ("PARTLY_ANSWERABLE", "DIST_CROSS_SPECIES",
                    "Fewer than two species have volume bounds and no comparable reported volume definition is present.")
    return None


RANK = {"NOT_APPLICABLE": -1, "NOT_ANSWERABLE_YET": 0, "PARTLY_ANSWERABLE": 1, "ANSWERABLE": 2}


def host_issue(row):
    cap = row.get("endpoint_limit")
    if not cap or RANK.get(row.get("status_code"), -1) <= RANK[cap[0]]:
        return None
    keywords = {"EL_COMPONENT_OR_ASSAY": ["excreta", "component", "in vitro", "assay"],
                "DIST_UNBOUND_EXPOSURE": ["unbound", "binding", "plasma"],
                "DIST_PAIRED_TIMES": ["tissue", "blood", "sampling time"],
                "DIST_CROSS_SPECIES": ["volume", "species"]}
    return {"type": "STATUS_TOO_STRONG", "what": cap[2], "source": "HOST", "check": cap[1], "keywords": keywords[cap[1]],
            "evidence": {"rule": None, "figure": None, "data": row["row_id"], "dataset_ids": []},
            "smallest_correction": f"Reassess the status; the supported ceiling for this endpoint is {cap[0]}. Keep any measured secondary findings."}


def effective_answer(answer, rows):
    """Preserve the raw opinion, and never let it override a reproducible contradiction."""
    result = copy.deepcopy(answer)
    findings = {r["row_id"]: host_issue(r) for r in rows}
    for item in result["rows"]:
        finding = findings.get(item["row_id"])
        if finding:
            item["model_verdict"] = item["verdict"]
            item["verdict"] = "REVISE"
            item["issues"].append(finding)
    return result


def species_key(value):
    text = str(value or "").strip().casefold()
    tokens = {"mouse": r"mice|mouse|murine", "rat": r"rats?|rattus", "dog": r"dogs?|canine|beagles?",
              "rabbit": r"rabbits?", "monkey": r"monkeys?|macaques?|cynomolgus|rhesus"}
    matches = [sp for sp, pattern in tokens.items() if re.search(r"\b(?:" + pattern + r")\b", text)]
    return matches[0] if len(matches) == 1 else text


def identity(value):
    if not isinstance(value, str) or value.strip().casefold() in {"", "not_found", "unknown", "not reported", "not_reported", "n/a"}:
        return None
    return value.strip().casefold()


def classify(dataset, board, used):
    studies = {identity(s) for s in dataset.get("study_ids", [])} - {None}
    study = identity(board.get("study"))
    if not studies or not study or (study in studies and len(studies) > 1):
        relation = "study_unresolved"
    elif study not in studies:
        relation = "other_study"
    else:
        board_arm = board.get("arm") or {}
        # Only explicit, like-for-like arm or cohort identifiers establish arm identity.
        comparisons = [(identity(board_arm.get(k)), identity(dataset.get(k))) for k in ("experiment_arm", "cohort")]
        matched = [a == b for a, b in comparisons if a and b]
        if False in matched:
            relation = "same_study_other_arm"
        elif matched and all(not a or b for a, b in comparisons):
            relation = "same_arm"
        else:
            relation = "same_study_arm_unverified"
    return dict(dataset, used_by_this_board=dataset.get("dataset_id") in used, scope_relation=relation)


def scope_problem(issue, sent, inventory):
    """A local upgrade based on another study/arm is not admissible; project inventory questions are distinct."""
    if issue.get("type") not in ("STATUS_TOO_WEAK", "OMITTED_EVIDENCE"):
        return None
    evidence = issue.get("evidence") or {}
    ids = evidence.get("dataset_ids")
    if not isinstance(ids, list) or not ids:
        return "cite the applicable dataset_ids for the proposed upgrade or omission"
    indexed = {x["dataset_id"]: x for x in inventory}
    if any(d not in indexed for d in ids):
        return "dataset_ids include a dataset outside the supplied inventory"
    if sent.get("claim_scope") == "project":
        return None
    permitted = {"same_arm"}
    if sent.get("claim_scope") == "study":
        permitted.add("same_study_arm_unverified")
    def applicable(d):
        relation = indexed[d]["scope_relation"]
        if relation in permitted:
            return True
        # An omission visible in the row's own cited figure does not require a new arm join.
        return (relation == "same_study_arm_unverified" and d in sent.get("row_sources", [])
                and evidence.get("figure") in {f["file"] for f in sent.get("figures", [])})
    if any(not applicable(d) for d in ids):
        return "a local upgrade or omission needs evidence of matching scope; cite external context separately"
    return None
