"""Bounded, source-bound on-demand reads of complete validated method units.

This module is an integration boundary only. It does not search or read files,
call a model, authorize itself, or infer scientific adequacy.
"""
import copy
import hashlib
import json

MAX_REQUEST_BYTES = 60000
MAX_RAW_CONTEXT_CHARS = 64000


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def sha256(value):
    raw = value if isinstance(value, bytes) else canonical(value).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _append_only(before, after):
    """True when every original value remains at the same path and order."""
    if isinstance(before, dict):
        return (isinstance(after, dict) and set(before) <= set(after) and
                all(_append_only(v, after[k]) for k, v in before.items()))
    if isinstance(before, list):
        return (isinstance(after, list) and len(after) >= len(before) and
                all(_append_only(v, after[i]) for i, v in enumerate(before)))
    return type(before) is type(after) and before == after


def _request_contains(request, target):
    """Find target structurally, including JSON objects encoded in strings."""
    if request == target:
        return True
    if isinstance(request, dict):
        if isinstance(request.get("context_support"), dict):
            try:
                from rag_vnext.delivery_codec import decode_support
                if decode_support(request["context_support"]) == target:
                    return True
            except (ImportError, ValueError, KeyError, TypeError):
                pass
        return any(_request_contains(v, target) for v in request.values())
    if isinstance(request, list):
        return any(_request_contains(v, target) for v in request)
    if isinstance(request, str):
        try:
            decoded = json.loads(request)
        except (TypeError, ValueError):
            return False
        return decoded != request and _request_contains(decoded, target)
    return False


def _model_messages_contain(request, target):
    """Verify exact content only in message bodies sent to the model."""
    if not isinstance(request, dict) or not isinstance(request.get("messages"), list):
        return False
    return any(isinstance(message, dict) and "content" in message and
               _request_contains(message["content"], target)
               for message in request["messages"])


def _scope_restriction(registry, read_request, authorized_unit_ids, allowed_source_ids,
                       allowed_branches, current_source_manifest_hashes):
    uid = read_request.get("unit_id") if isinstance(read_request, dict) else None
    need = read_request.get("need_id") if isinstance(read_request, dict) else None
    if not isinstance(uid, str) or uid not in registry.get("units", {}):
        return "UNKNOWN_UNIT", need
    if uid not in set(authorized_unit_ids):
        return "UNIT_OUTSIDE_AUTHORIZED_SCOPE", need
    row = registry["units"][uid]
    if need is not None and need != row["need_id"]:
        return "NEED_SCOPE_MISMATCH", need
    _assert_frozen_integrity(registry)
    if not set(row["source_hashes"]) <= set(allowed_source_ids):
        return "SOURCE_OUTSIDE_AUTHORIZED_SCOPE", need
    if not set(row["content"]["card"].get("required_branches", [])) <= set(allowed_branches):
        return "BRANCH_OUTSIDE_AUTHORIZED_SCOPE", need
    for sid, frozen_hash in row["source_hashes"].items():
        if current_source_manifest_hashes.get(sid) != frozen_hash:
            return "STALE_SOURCE_BINDING", need
    return None, need


def _whole_unit(card_row):
    """Return full card/evidence/source content; reject partial or invalid closure."""
    if card_row.get("problems"):
        raise ValueError("Only validated units can enter the background registry")
    closure = card_row.get("closure")
    if not isinstance(closure, dict) or not {"nodes", "missing", "cycles"} <= set(closure):
        raise ValueError("Declared closure record is incomplete")
    if closure.get("missing") or closure.get("cycles"):
        raise ValueError("Unit closure is not complete")
    root = card_row.get("root")
    if not root or root not in closure["nodes"]:
        raise ValueError("Declared closure does not include the complete card root")
    card = copy.deepcopy(card_row["card"])
    # Conditions and qualifiers are integral evidence and must stay present.
    for field in ("conditions", "limitations", "required_inputs"):
        if field not in card or card[field] in (None, "", [], {}):
            raise ValueError("Whole unit is missing required boundary: " + field)
    evidence = copy.deepcopy(card_row["evidence"])
    sources = copy.deepcopy(card_row["sources"])
    if not isinstance(evidence, list) or not isinstance(sources, dict):
        raise ValueError("Evidence and source records must be complete collections")
    by_id = {}
    for item in evidence:
        if not isinstance(item, dict) or not item.get("id") or item["id"] in by_id:
            raise ValueError("Evidence IDs must be present and unique")
        if not item.get("text") or not item.get("locator") or not item.get("source_id"):
            raise ValueError("Evidence text, locator, and source binding are required")
        by_id[item["id"]] = item
    required = list(dict.fromkeys(card.get("evidence_chunk_ids", []) +
                                  [eid for claim in card.get("claim_support", [])
                                   for eid in claim.get("evidence_chunk_ids", [])]))
    if not required or not set(required) <= set(by_id):
        raise ValueError("Whole card evidence closure is incomplete")
    required_sources = set(card.get("source_ids", [])) | {by_id[eid]["source_id"] for eid in required}
    if not required_sources <= set(sources):
        raise ValueError("Whole card source closure is incomplete")
    # Recompute the expected declared descendants that compile_units places in
    # its exact closure graph; a root-only closure must not masquerade as full.
    try:
        prefix = root.rsplit("/general_methods/", 1)[0]
        expected_nodes = {root}
        for key in card:
            field = root + "/" + str(key).replace("~", "~0").replace("/", "~1")
            expected_nodes.add(field)
            if key == "claim_support":
                expected_nodes.update(field + "/" + str(i) for i in range(len(card[key])))
        for sid in required_sources:
            esc_sid = str(sid).replace("~", "~0").replace("/", "~1")
            expected_nodes.add(prefix + "/applicability_and_examples/cited_originals/" + esc_sid)
        closure_nodes = closure["nodes"]
        if len(closure_nodes) != len(set(closure_nodes)):
            raise ValueError("Declared closure contains duplicate node pointers")
        evidence_prefix = prefix + "/applicability_and_examples/evidence/"
        evidence_nodes = {n for n in closure_nodes if n.startswith(evidence_prefix)}
        pointer_hashes = card_row.get("evidence_pointer_hashes")
        if not isinstance(pointer_hashes, dict) or set(pointer_hashes) != evidence_nodes:
            raise ValueError("Evidence pointer hashes must bind every exact closure evidence node")
        required_evidence_nodes = set()
        for item in evidence:
            if item["id"] not in set(required):
                continue
            evidence_hash = sha256(item)
            matches = [pointer for pointer in evidence_nodes
                       if pointer_hashes.get(pointer) == evidence_hash]
            if len(matches) != 1:
                raise ValueError("Required evidence must bind exactly one original closure pointer")
            required_evidence_nodes.add(matches[0])
        if not expected_nodes <= set(closure_nodes) or not required_evidence_nodes <= set(closure_nodes):
            raise ValueError("Declared closure omits card, required evidence, or source descendants")
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Declared closure cannot be verified") from exc
    return {"card": card, "evidence": evidence,
            "sources": sources,
            "applicability": copy.deepcopy(card_row["applicability"]),
            "closure": copy.deepcopy(closure)}


def build_registry(cards, source_manifest_hashes, *, max_reads=2,
                   max_cumulative_bytes=60000):
    """Freeze whole units into an immutable-by-convention registry.

    `cards` should be the complete validated cards returned by compile_units.
    Source hashes are bound to each full source record. Unknown declared closure
    must have been resolved to the full card before this function is called.
    """
    if not isinstance(max_reads, int) or isinstance(max_reads, bool) or max_reads < 0:
        raise ValueError("max_reads must be a nonnegative integer")
    if not isinstance(max_cumulative_bytes, int) or isinstance(max_cumulative_bytes, bool) or max_cumulative_bytes < 0:
        raise ValueError("max_cumulative_bytes must be a nonnegative integer")
    units = {}
    for row in cards:
        unit = _whole_unit(row)
        uid = row.get("unit_id") or row.get("root")
        if not isinstance(uid, str) or not uid or uid in units:
            raise ValueError("Each unit needs a unique stable unit_id or root")
        for sid, source in unit["sources"].items():
            expected = source_manifest_hashes.get(sid)
            if not expected or expected != sha256(source):
                raise ValueError("Source is absent from or differs from frozen manifest: " + sid)
        units[uid] = {"content": unit, "need_id": row.get("need_id"), "sha256": sha256(unit),
                      "source_hashes": {sid: source_manifest_hashes[sid]
                                        for sid in unit["sources"]}}
    return {"version": "BOUNDED_BACKGROUND_REGISTRY_1",
            "units": units, "source_manifest_hashes": copy.deepcopy(source_manifest_hashes),
            "limits": {"max_reads": max_reads,
                       "max_cumulative_bytes": max_cumulative_bytes},
            "semantics": {"available_or_indexed": "NOT_DELIVERED",
                          "delivered_or_read": "NOT_SEMANTICALLY_VERIFIED",
                          "automatic_authority": False}}


def _assert_frozen_integrity(registry):
    for uid, row in registry["units"].items():
        if sha256(row["content"]) != row["sha256"]:
            raise ValueError("Frozen background unit changed: " + uid)
        for sid, expected in row["source_hashes"].items():
            source = row["content"]["sources"].get(sid)
            if source is None or sha256(source) != expected:
                raise ValueError("Frozen source record changed: " + sid)


def lightweight_index(registry, authorized_unit_ids, *, allowed_source_ids,
                      allowed_branches):
    """Expose identifiers and brief labels only for explicitly scoped units."""
    _assert_frozen_integrity(registry)
    allowed = set(authorized_unit_ids)
    sources = set(allowed_source_ids)
    branches = set(allowed_branches)
    rows = []
    for uid, row in registry["units"].items():
        if uid not in allowed:
            continue
        row_sources = set(row["source_hashes"])
        row_branches = set(row["content"]["card"].get("required_branches", []))
        if not row_sources <= sources or not row_branches <= branches:
            continue
        card = row["content"]["card"]
        rows.append({"unit_id": uid, "method_id": card.get("id"),
                     "title": card.get("title"), "need_id": row["need_id"],
                     "unit_sha256": row["sha256"], "delivery": "AVAILABLE_NOT_READ"})
    return {"version": "BACKGROUND_INDEX_1", "units": rows,
            "authority_granted": False,
            "boundary": "An index entry is not delivered evidence and cannot support a claim."}


def fulfill_read(registry, read_request, *, authorized_unit_ids,
                 allowed_source_ids, allowed_branches,
                 current_request_bytes, current_raw_context_chars,
                 current_source_manifest_hashes,
                 prior_state=None):
    """Fulfill one deterministic read or return a scoped restriction.

    Request shape: {"unit_id": str, "need_id": str}. Authorization must come
    from the host. `current_request_bytes` is UTF-8 bytes for the complete
    prospective input after appending this unit. `current_raw_context_chars`
    covers the complete raw context and remains under 64,000. Production callers
    should use fulfill_read_from_context to compute both from the actual payload.
    """
    state = copy.deepcopy(prior_state if prior_state is not None else
                           {"read_count": 0, "cumulative_bytes": 0, "read_ids": []})
    uid = read_request.get("unit_id") if isinstance(read_request, dict) else None
    need = read_request.get("need_id") if isinstance(read_request, dict) else None

    def restricted(reason, scope=None):
        return {"status": "RESTRICTED", "reason": reason,
                "affected_need_id": scope or need,
                "authority_granted": False, "state": state}

    if not isinstance(state, dict) or set(state) != {"read_count", "cumulative_bytes", "read_ids"}:
        return restricted("INVALID_SESSION_STATE")
    if (any(not isinstance(state[k], int) or isinstance(state[k], bool) or state[k] < 0
            for k in ("read_count", "cumulative_bytes")) or
            not isinstance(state["read_ids"], list) or
            any(not isinstance(x, str) for x in state["read_ids"]) or
            len(set(state["read_ids"])) != len(state["read_ids"]) or
            state["read_count"] != len(state["read_ids"]) or
            any(x not in registry["units"] for x in state["read_ids"]) or
            state["read_count"] > registry["limits"]["max_reads"] or
            state["cumulative_bytes"] > registry["limits"]["max_cumulative_bytes"]):
        return restricted("INVALID_SESSION_STATE")
    if not isinstance(current_request_bytes, int) or isinstance(current_request_bytes, bool) or current_request_bytes < 0:
        return restricted("INVALID_CURRENT_REQUEST_SIZING")
    if current_request_bytes > MAX_REQUEST_BYTES:
        return restricted("EXISTING_REQUEST_LIMIT_EXCEEDED")
    if (not isinstance(current_raw_context_chars, int) or isinstance(current_raw_context_chars, bool)
            or current_raw_context_chars < 0 or current_raw_context_chars > MAX_RAW_CONTEXT_CHARS):
        return restricted("RAW_CONTEXT_LIMIT_EXCEEDED")
    if not isinstance(uid, str) or uid not in registry["units"]:
        return restricted("UNKNOWN_UNIT")
    if uid not in set(authorized_unit_ids):
        return restricted("UNIT_OUTSIDE_AUTHORIZED_SCOPE")
    unitrow = registry["units"][uid]
    if need is not None and need != unitrow["need_id"]:
        return restricted("NEED_SCOPE_MISMATCH")
    if uid in state["read_ids"]:
        return restricted("DUPLICATE_READ")
    _assert_frozen_integrity(registry)
    if not set(unitrow["source_hashes"]) <= set(allowed_source_ids):
        return restricted("SOURCE_OUTSIDE_AUTHORIZED_SCOPE")
    if not set(unitrow["content"]["card"].get("required_branches", [])) <= set(allowed_branches):
        return restricted("BRANCH_OUTSIDE_AUTHORIZED_SCOPE")
    for sid, frozen_hash in unitrow["source_hashes"].items():
        if current_source_manifest_hashes.get(sid) != frozen_hash:
            return restricted("STALE_SOURCE_BINDING")
    limits = registry["limits"]
    if state["read_count"] >= limits["max_reads"]:
        return restricted("READ_COUNT_BUDGET_EXCEEDED")
    payload = {"unit_id": uid, "unit_sha256": unitrow["sha256"],
               "source_hashes": copy.deepcopy(unitrow["source_hashes"]),
               "content": copy.deepcopy(unitrow["content"]),
               "semantic_status": "DELIVERED_NOT_SEMANTICALLY_VERIFIED",
               "authority_granted": False}
    size = len(canonical(payload).encode("utf-8"))
    if state["cumulative_bytes"] + size > limits["max_cumulative_bytes"]:
        return restricted("CUMULATIVE_BYTE_BUDGET_EXCEEDED")
    state["read_count"] += 1
    state["cumulative_bytes"] += size
    state["read_ids"].append(uid)
    return {"status": "DELIVERED", "payload": payload,
            "delivered_bytes": size, "state": state,
            "evidence_use": "READ_CONTENT_MAY_BE_REVIEWED; SEMANTIC_SUPPORT_NOT_ESTABLISHED"}


def fulfill_read_from_context(registry, read_request, *, authorized_unit_ids,
                              allowed_source_ids, allowed_branches,
                              current_context, append_whole_unit,
                              current_source_manifest_hashes,
                              prior_state=None):
    """Production helper that sizes the real prospective request itself.

    append_whole_unit(current_context, complete_unit) must return a mapping with
    `request` and `raw_context`. The complete original raw context is pinned by
    recursive value equality and list-prefix checks; it cannot be removed or
    altered while optional content is appended. The request must contain the
    resulting raw context, structurally or as JSON encoded in a message string.
    The existing reserve is the caller's responsibility and must already be
    accounted for in request construction.
    """
    uid = read_request.get("unit_id") if isinstance(read_request, dict) else None
    if uid not in registry.get("units", {}):
        return {"status": "RESTRICTED", "reason": "UNKNOWN_UNIT",
                "affected_need_id": read_request.get("need_id") if isinstance(read_request, dict) else None,
                "authority_granted": False,
                "state": copy.deepcopy(prior_state if prior_state is not None else
                                        {"read_count": 0, "cumulative_bytes": 0, "read_ids": []})}
    reason, need = _scope_restriction(registry, read_request, authorized_unit_ids,
                                      allowed_source_ids, allowed_branches,
                                      current_source_manifest_hashes)
    if reason:
        return {"status": "RESTRICTED", "reason": reason, "affected_need_id": need,
                "authority_granted": False,
                "state": copy.deepcopy(prior_state if prior_state is not None else
                                        {"read_count": 0, "cumulative_bytes": 0, "read_ids": []})}
    _assert_frozen_integrity(registry)
    unit = registry["units"][uid]["content"]
    prospective = append_whole_unit(copy.deepcopy(current_context), copy.deepcopy(unit))
    if not isinstance(prospective, dict) or not {"request", "raw_context"} <= set(prospective):
        raise ValueError("Append callback must return request and raw_context")
    if not _append_only(current_context, prospective["raw_context"]):
        raise ValueError("Optional read removed or changed existing raw context")
    if not _request_contains(prospective["raw_context"], unit):
        raise ValueError("Complete unit is absent from prospective raw context")
    if not _model_messages_contain(prospective["request"], prospective["raw_context"]):
        raise ValueError("Model-visible message content does not contain the sized raw context")
    request_bytes = len(canonical(prospective["request"]).encode("utf-8"))
    raw_chars = len(canonical(prospective["raw_context"]))
    outcome = fulfill_read(registry, read_request, authorized_unit_ids=authorized_unit_ids,
                        allowed_source_ids=allowed_source_ids, allowed_branches=allowed_branches,
                        current_request_bytes=request_bytes, current_raw_context_chars=raw_chars,
                        current_source_manifest_hashes=current_source_manifest_hashes,
                        prior_state=prior_state)
    if outcome["status"] == "DELIVERED":
        outcome["prospective_request"] = copy.deepcopy(prospective["request"])
        outcome["prospective_raw_context"] = copy.deepcopy(prospective["raw_context"])
        outcome["measured_request_bytes"] = request_bytes
        outcome["measured_raw_context_chars"] = raw_chars
    return outcome


def required_evidence_policy(required_inline_ids):
    """Make mandatory inline evidence non-evictable by optional reads."""
    return {"required_evidence_inline": list(dict.fromkeys(required_inline_ids)),
            "eviction_allowed": False,
            "optional_read_budget_effect": "RESTRICT_OPTIONAL_READ_ONLY",
            "unread_evidence_claim_use": "PROHIBITED"}
