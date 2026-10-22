"""Lossless, source-bound normalized views for reviewed knowledge cards.

Purpose views are exact pointers into a canonical card. They support retrieval
organization only. Declared identifiers are recorded as declared links; prose
semantics are unknown and the only selectable unit is the full card.
"""
from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

VERSION = "SOURCE_BOUND_KNOWLEDGE_STRUCTURE_1"
VIEW_FIELDS = ("title", "claim", "method_keywords", "method_recipe", "plot_recipe")
CONSTRAINT_FIELDS = ("conditions", "limitations", "required_inputs", "required_branches")


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _escape(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _pointer_value(document: Any, pointer: str) -> Any:
    value = document
    if pointer == "":
        return value
    if not pointer.startswith("/"):
        raise ValueError("JSON pointer must be empty or begin with '/'")
    for part in pointer[1:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        value = value[int(part)] if isinstance(value, list) else value[part]
    return value


def _view_pointers(card: dict) -> list[str]:
    result = []
    for field in VIEW_FIELDS:
        if field not in card:
            continue
        value = card[field]
        if isinstance(value, dict):
            result.extend("/" + _escape(field) + "/" + _escape(str(key))
                          for key, child in value.items() if child not in (None, "", [], {}))
        elif isinstance(value, list):
            result.extend("/" + _escape(field) + "/" + str(index)
                          for index, child in enumerate(value) if child not in (None, "", [], {}))
        elif value not in (None, "", [], {}):
            result.append("/" + _escape(field))
    return result


def normalize_card(card: dict) -> dict:
    """Create a reversible normalized record without interpreting card prose."""
    if not isinstance(card, dict):
        raise TypeError("card must be a JSON object")
    original = copy.deepcopy(card)
    card_hash = _digest(original)
    constraints = ["/" + key for key in CONSTRAINT_FIELDS if key in original]
    views = []
    for pointer in _view_pointers(original):
        views.append({
            "source_pointer": pointer,
            "source_sha256": _digest(_pointer_value(original, pointer)),
            "card_sha256": card_hash,
            "constraint_pointers": constraints[:],
            "status": "EXACT_BOUND_RETRIEVAL_VIEW_NOT_APPLICABILITY_APPROVAL",
        })

    links = []
    supports = original.get("claim_support", [])
    if isinstance(supports, list):
        for index, support in enumerate(supports):
            if not isinstance(support, dict):
                continue
            links.append({
                "claim_pointer": "/claim_support/" + str(index),
                "claim_sha256": _digest(support),
                "evidence_chunk_ids": copy.deepcopy(support.get("evidence_chunk_ids", [])),
                "link_status": "DECLARED_CARD_LINK_NOT_ENTAILMENT_REVIEW",
            })

    return {
        "version": VERSION,
        "canonical_card": original,
        "card_sha256": card_hash,
        "source_binding": {
            "card_pointer": "",
            "card_sha256": card_hash,
            "field_pointers": {"/" + _escape(key): _digest(value) for key, value in original.items()},
            "source_ids": copy.deepcopy(original.get("source_ids", [])),
            "evidence_chunk_ids": copy.deepcopy(original.get("evidence_chunk_ids", [])),
        },
        "purpose_views": views,
        "shared_constraints": [
            {"source_pointer": "/" + key, "source_sha256": _digest(original[key]), "scope": "CARD_SHARED"}
            for key in CONSTRAINT_FIELDS if key in original
        ],
        "declared_claim_support": links,
        "semantic_dependency_status": "UNKNOWN",
        "evidence_units": [{
            "unit_id": "FULL_CARD:" + card_hash,
            "kind": "FULL_CARD_FALLBACK",
            "source_pointers": [""],
            "source_sha256": card_hash,
            "selection_status": "DEFAULT_REQUIRED_UNREVIEWED_SEMANTIC_CLOSURE",
        }],
        "selection_boundary": (
            "Only the full card is currently represented as a selectable evidence unit. "
            "Explicit pointer links do not establish semantic independence or authorize field deletion."
        ),
    }


def validate_normalized(record: dict, card: dict) -> bool:
    """Return true only when every normalized source binding still matches."""
    try:
        if not isinstance(record, dict) or not isinstance(card, dict):
            return False
        if record.get("version") != VERSION or record.get("canonical_card") != card:
            return False
        digest = _digest(card)
        if record.get("card_sha256") != digest:
            return False
        binding = record.get("source_binding", {})
        if binding.get("card_pointer") != "" or binding.get("card_sha256") != digest:
            return False
        if binding.get("field_pointers") != {"/" + _escape(k): _digest(v) for k, v in card.items()}:
            return False
        for view in record.get("purpose_views", []):
            if view.get("card_sha256") != digest:
                return False
            value = _pointer_value(card, view["source_pointer"])
            if view.get("source_sha256") != _digest(value):
                return False
        for constraint in record.get("shared_constraints", []):
            if constraint.get("source_sha256") != _digest(_pointer_value(card, constraint["source_pointer"])):
                return False
        expected = normalize_card(card)
        return record == expected
    except (KeyError, IndexError, TypeError, ValueError):
        return False
