"""Checks structural integrity; semantic truth remains a separate review."""
from collections import deque
import re
from pathlib import PurePosixPath, PureWindowsPath
from .io import leaves, length_metrics
from .schemas import CONTEXT, PIPELINE, REVIEW, CONTEXT_REVIEW, validate_schema


def check_quote(source_id, quote, sources):
    source = next((s for s in sources if s["id"] == source_id), None)
    if not source or not quote or quote not in source["text"]:
        raise ValueError(f"Evidence quote not found verbatim in {source_id}")
    start = source["text"].index(quote)
    return {"source_id": source_id, "start_char": start, "end_char": start + len(quote),
            "line": source["text"][:start].count("\n") + 1}


def target_pointer(pointer, root, expected):
    """Resolve only exact target-relative paths or their one envelope prefix.

    Do not repair spelling, array indices, escapes, or repeated prefixes. Both
    accepted spellings must identify an actual expected field before use.
    """
    if pointer in expected:
        return pointer
    prefix = "/" + root
    if pointer.startswith(prefix + "/") and pointer[len(prefix):] in expected:
        return pointer[len(prefix):]
    raise ValueError(f"Unknown {root} evidence/review pointer: {pointer}")


def context_check(context, evidence, sources, budget):
    validate_schema(context, CONTEXT)
    leaf_map = dict(leaves(context))
    required = set(leaf_map) - {"/version"}
    seen = set()
    audit = []
    for item in evidence:
        pointer = target_pointer(item["path"], "context", required)
        if pointer in seen:
            raise ValueError(f"Repeated evidence pointer: {item['path']} resolves to {pointer}")
        seen.add(pointer)
        entry = dict(item)
        entry["path"] = pointer
        if pointer != item["path"]:
            entry["input_path"] = item["path"]
        if item["status"] == "EXPLICIT":
            entry["location"] = check_quote(item["source_id"], item["quote"], sources)
        elif item["status"] == "NOT_FOUND":
            if leaf_map[pointer] != "NOT_FOUND" or item["quote"] or item["source_id"]:
                raise ValueError("NOT_FOUND requires literal NOT_FOUND and no invented source quote")
        elif item["status"] == "PROPOSED":
            if not pointer.startswith(("/data/required/", "/checks/", "/uncertainties/")):
                raise ValueError(f"Suggestions must not be presented as project facts: {pointer}")
            if item["quote"]:
                entry["location"] = check_quote(item["source_id"], item["quote"], sources)
        audit.append(entry)
    if required != seen:
        raise ValueError(f"Missing evidence records: {sorted(required - seen)}")
    metrics = length_metrics(context, "\n".join(s["text"] for s in sources))
    for key in ("content_words", "compact_characters"):
        limit = budget[key]
        if limit is not None and metrics[key] > limit:
            raise ValueError(f"Context exceeds {key} budget: {metrics[key]} > {limit}; preserve meaning when revising")
    return audit, metrics


def review_check(review, target, sources, stage):
    validate_schema(review, CONTEXT_REVIEW if stage == "context_review" and "coverage" in review else REVIEW)
    if stage == "context_review":
        expected = set(dict(leaves(target))) - {"/version"}
    else:
        expected = {f"/blocks/{i}" for i in range(len(target["blocks"]))}
        expected |= {f"/data_files/{i}" for i in range(len(target["data_files"]))}
    root = "context" if stage == "context_review" else "pipeline"
    paths = [target_pointer(r["path"], root, expected) for r in review["claims"]]
    if len(paths) != len(set(paths)) or set(paths) != expected:
        raise ValueError("Review must cover every context leaf or every pipeline block/file exactly once")
    for item in review["retention"]:
        check_quote(item["source_id"], item["quote"], sources)
    bad = any(r["verdict"] != "PRESERVED" for r in review["claims"] + review["retention"])
    if review["decision"] == "PASS" and (bad or review["critical_errors"]):
        raise ValueError("PASS contradicts missing/altered/unresolved items or critical errors")
    return review["decision"]


def safe_future_path(value):
    if value == "NOT_FOUND":
        return
    if (PureWindowsPath(value).is_absolute() or PureWindowsPath(value).drive
            or PurePosixPath(value).is_absolute() or ".." in value.replace("\\", "/").split("/")):
        raise ValueError(f"Planned output path must be relative and stay within its task: {value}")


def pipeline_check(pipeline, policy, literature, inventory=(), sources=()):
    validate_schema(pipeline, PIPELINE)
    blocks = {b["id"]: b for b in pipeline["blocks"]}
    files = {f["id"]: f for f in pipeline["data_files"]}
    if len(blocks) != len(pipeline["blocks"]) or len(files) != len(pipeline["data_files"]):
        raise ValueError("Duplicate block or file ID")
    if any(not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", i) for i in list(blocks) + list(files)):
        raise ValueError("IDs must be simple ASCII identifiers")
    refs = {r["id"] for r in literature}
    inventory_ids = {d["id"] for d in inventory}
    source_ids = {s["id"] for s in sources}
    connections, producers, adjacency, warnings = [], {}, {b: set() for b in blocks}, []
    for block in blocks.values():
        if len(block["outputs"]) != len(set(block["outputs"])):
            raise ValueError("Repeated output in block")
        for fid in block["outputs"]:
            if fid not in files or fid in producers:
                raise ValueError(f"Unknown or multiply produced output: {fid}")
            producers[fid] = block["id"]
        if policy["exclude_pbpk"] and re.search(r"\bPBPK\b|physiologically.based", block["method"]["name"], re.I):
            raise ValueError("PBPK method conflicts with the project policy")
        if set(block["method"]["reference_ids"]) - refs:
            raise ValueError("Method references unknown literature IDs")
        if block["method"]["origin"] == "SUGGESTED" and not block["method"]["reference_ids"]:
            raise ValueError("Suggested method requires a traceable method reference")
    for fid, file in files.items():
        if file["producer"] == "EXTERNAL":
            if fid in producers or file["availability"] == "TO_GENERATE":
                raise ValueError("External file cannot be a generated output")
            if file["availability"] == "DECLARED" and fid not in inventory_ids:
                raise ValueError(f"Declared data must occur in the supplied descriptive inventory: {fid}")
            if file["availability"] == "LOCAL_DOCUMENT" and fid not in source_ids:
                raise ValueError(f"Local document must occur in ingested sources: {fid}")
        else:
            if producers.get(fid) != file["producer"] or file["availability"] != "TO_GENERATE":
                raise ValueError(f"Generated file lacks matching producer/output contract: {fid}")
            safe_future_path(file["path"])
    for block in blocks.values():
        seen = set()
        for inp in block["inputs"]:
            fid = inp["file_id"]
            if fid not in files or fid in seen:
                raise ValueError(f"Unknown/repeated input: {fid}")
            seen.add(fid)
            file = files[fid]
            if (policy["human_pk_validation_only"] and file["kind"] == "DATASET"
                    and file["role"] == "VALIDATION" and block["category"] != "VALIDATION"):
                raise ValueError("Validation observations cannot enter development or prediction blocks")
            for key, expected in inp["expects"].items():
                actual = file["attributes"][key]
                if expected not in {"ANY", "NOT_FOUND"}:
                    if actual == "NOT_FOUND":
                        warnings.append(f"{block['id']}:{fid} {key} is unresolved")
                    elif actual != expected:
                        raise ValueError(f"Incompatible {key}: {fid}={actual}, {block['id']} expects {expected}")
            if file["producer"] != "EXTERNAL":
                upstream = file["producer"]
                if upstream == block["id"]:
                    raise ValueError("Block cannot consume its own output")
                adjacency[upstream].add(block["id"])
                connections.append({"from": upstream, "to": block["id"], "file_id": fid,
                                    "required": inp["required"], "when": block["when"]})
    indegree = {bid: 0 for bid in blocks}
    for following in adjacency.values():
        for bid in following:
            indegree[bid] += 1
    queue = deque(bid for bid, degree in indegree.items() if not degree)
    order = []
    while queue:
        bid = queue.popleft()
        order.append(bid)
        for child in sorted(adjacency[bid]):
            indegree[child] -= 1
            if indegree[child] == 0:
                queue.append(child)
    if len(order) != len(blocks):
        raise ValueError("Pipeline contains a dependency cycle")
    states = {}
    flags = {"ALWAYS": True, "PD_REQUESTED": policy["pd_requested"],
             "CFR_REQUESTED": policy["cfr_requested"],
             "HUMAN_VALIDATION_AVAILABLE": policy["human_validation_available"]}
    for bid in order:
        block = blocks[bid]
        blockers, waiting, declarations = [], [], []
        if not flags[block["when"]]:
            states[bid] = {"status": "CONDITIONAL_PENDING", "reason": block["when"], "blocking_files": []}
            continue
        for inp in block["inputs"]:
            if not inp["required"]:
                continue
            file = files[inp["file_id"]]
            if file["availability"] == "MISSING":
                blockers.append(file["id"])
            elif file["producer"] != "EXTERNAL":
                up = states[file["producer"]]["status"]
                if up in {"BLOCKED_MISSING_INPUT", "BLOCKED_UPSTREAM", "CONDITIONAL_PENDING"}:
                    blockers.append(file["id"])
                else:
                    waiting.append(file["id"])
            elif file["availability"] == "DECLARED":
                declarations.append(file["id"])
        state = ("BLOCKED_MISSING_INPUT" if any(files[f]["availability"] == "MISSING" for f in blockers)
                 else "BLOCKED_UPSTREAM" if blockers else "WAITING_UPSTREAM" if waiting
                 else "NEEDS_DATA_QC" if declarations else "READY_TO_START")
        states[bid] = {"status": state, "blocking_files": blockers,
                       "waiting_for": waiting, "declared_not_qc_verified": declarations}
    return {"connections": connections, "execution_order": order, "readiness": states,
            "warnings": sorted(set(warnings)), "scientific_validity": "REQUIRES_SEMANTIC_REVIEW"}
