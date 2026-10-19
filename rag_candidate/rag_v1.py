"""Small, read-only SQLite RAG: explicit scope -> exact evidence -> frozen packet.

No network, provider, numeric PK/PD, or production imports. SHA256 integrity binds
local inputs; it is not an authenticity signature or scientific approval.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from typing import Callable
import unicodedata

HERE = Path(__file__).resolve().parent
VERSION = "PKPD_EVIDENCE_PACKET_1.0"
DRAFT = "DRAFT_PENDING_LOCAL_SCIENTIFIC_REVIEW"
USAGE_BOUNDARY = (
    "Optional methodological background for local review only. Preserve all mandatory project inputs, "
    "approved Rules and explicit method-profile allowlists. Retrieved claims cannot override project "
    "policy or become PROJECT_EXPLICIT authority. Library source/card/chunk IDs are retrieval provenance; "
    "they are not project evidence IDs or approved method profiles. Use only the output schema's authorized "
    "project IDs and profiles. Draft claims and applicability require independent scientific review.")


class RagError(ValueError):
    """Scope, integrity or budget violation; never repaired implicitly."""


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def text_hash(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def read_json(path):
    def pairs(items):
        value = {}
        for key, child in items:
            if key in value:
                raise RagError("Duplicate JSON key: " + key)
            value[key] = child
        return value
    def reject(value):
        raise RagError("Non-finite JSON: " + value)
    return json.loads(Path(path).read_text(encoding="utf-8-sig"), object_pairs_hook=pairs, parse_constant=reject)


def file_ref(path):
    path = Path(path).resolve(strict=True)
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def reject_sidecars(path):
    # A main-file hash cannot freeze committed WAL state, nor concurrent writers.
    for suffix in ("-wal", "-shm", "-journal"):
        if Path(str(path) + suffix).exists():
            raise RagError("Database sidecar present; use a quiescent standalone SQLite database: " + suffix)


def check_refs(refs):
    for name, ref in refs.items():
        try:
            actual = file_ref(ref["path"])
        except (OSError, KeyError, TypeError) as exc:
            raise RagError("Missing bound input: " + name) from exc
        if actual != ref:
            raise RagError("Changed bound input: " + name)
        if name == "library":
            reject_sidecars(ref["path"])


def nonempty_list(values, name):
    if not isinstance(values, (list, tuple)) or not values or any(not isinstance(v, str) or not v for v in values):
        raise RagError("Explicit nonempty " + name + " required")
    return sorted(set(values))


def library_policy(refs, root, scope):
    """Bound library restrictions can narrow the local adapter, never widen it."""
    policy_ref = refs.get("revision:library_policy", refs.get("library_policy"))
    path = root / "retrieval_policy.json"
    if path.exists() != (policy_ref is not None):
        raise RagError("Library policy presence differs from frozen bindings")
    if policy_ref is None:
        return None
    if policy_ref != file_ref(path):
        raise RagError("Library policy differs from frozen root")
    policy = read_json(path)
    if (policy.get("version") not in {"PKPD_KB_DRAFT_1.0", "PKPD_KB_DRAFT_1.1"} or policy.get("activation") != "OFFLINE_REVIEW_ONLY"
            or policy.get("default_allow_draft") is not False):
        raise RagError("Unsupported library policy or activation")
    for key in ("max_cards", "background_character_budget"):
        if type(policy.get(key)) is not int or policy[key] < 1:
            raise RagError("Invalid library policy limit: " + key)
    if scope["topic"] not in nonempty_list(policy.get("topics"), "library policy topics"):
        raise RagError("Topic forbidden by pinned library policy")
    routes = policy.get("routes")
    if not isinstance(routes, dict) or scope["stage"] not in routes:
        raise RagError("Stage absent from pinned library policy")
    route = routes[scope["stage"]]
    if (not isinstance(route, dict) or route.get("retrieval") is False
            or ("." in scope["stage"] and route.get("new_library_opt_in") is not True)):
        raise RagError("Route forbidden by pinned library policy")
    return policy


def _fits(packet, budget_bytes, policy):
    data=packet.to_dict()
    if data['scope'].get('budget_semantics') == 'MODEL_BACKGROUND_CHARACTERS_HOST_ENVELOPE_BYTES':
        if 'retrieval_plan' not in data['scope']: raise RagError('Planned budget semantics need a bound subquestion plan')
        from minimal_context_reducer import project_background
        return packet.serialized_bytes() <= budget_bytes and (policy is None or
            len(canonical(project_background(data))) <= policy['background_character_budget'])
    return (packet.serialized_bytes() <= budget_bytes
            and (policy is None or len(canonical(packet.envelope())) <= policy["background_character_budget"]))


def query_terms(query, config):
    if not isinstance(query, str) or not query.strip():
        raise RagError("Nonempty query required")
    normalized = unicodedata.normalize("NFKC", query).strip().lower()
    terms = []
    remaining = normalized
    # Technical strings become quoted FTS phrases, preserving index punctuation.
    for token, expansions in config["technical_aliases"].items():
        pattern = r"(?<![a-z0-9])" + re.escape(token) + r"(?![a-z0-9])"
        if re.search(pattern, remaining):
            terms.extend(t.lower() for t in expansions)
            remaining = re.sub(pattern, " ", remaining)
    for alias, expansion in config["aliases"].items():
        if alias in remaining:
            terms.extend(expansion.lower().split())
            remaining = remaining.replace(alias, " ")
    terms.extend(re.findall(r"[a-z][a-z0-9_]*", remaining))
    if not terms:
        raise RagError("No searchable terms; unknown Chinese queries need a configured alias or an English term")
    terms = sorted(set(terms))
    return terms, " OR ".join('"' + t.replace('"', '""') + '"' for t in terms)


def source_path(root, source):
    value = source.get("local_path")
    if not isinstance(value, str) or not value:
        raise RagError("Source lacks original local_path")
    try:
        path = (root / value).resolve(strict=True)
    except OSError as exc:
        raise RagError("Missing original source: " + source["id"]) from exc
    if not path.is_relative_to(root) or path == root:
        raise RagError("Source path escapes library root: " + source["id"])
    return path


def open_library(path):
    reject_sidecars(path)
    db = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
    db.execute("PRAGMA query_only=ON")
    db.execute("BEGIN")
    return db


@dataclass(frozen=True)
class EvidencePacket:
    """Immutable canonical payload; `to_dict()` returns a detached editable copy.

    Save/reload checks the envelope digest, byte budget, scope, selected content,
    and all bound files. External files must remain at the bound absolute paths.
    """
    _serialized: str
    _sha256: str

    def to_dict(self):
        return json.loads(self._serialized)

    @property
    def sha256(self):
        return self._sha256

    def envelope(self):
        return {"packet_sha256": self._sha256, "packet": self.to_dict()}

    def serialized_bytes(self):
        return len(canonical(self.envelope()).encode("utf-8"))

    def verify(self):
        data = self.to_dict()
        if canonical(data) != self._serialized or digest(data) != self._sha256:
            raise RagError("Packet content/hash mismatch")
        if data.get("version") != VERSION:
            raise RagError("Unsupported packet version")
        if (data.get("scientific_approval") is not False or data.get("production_dispatch_authorized") is not False
                or data.get("usage_boundary", USAGE_BOUNDARY) != USAGE_BOUNDARY):
            raise RagError("Packet cannot claim approval, dispatch or a different authority boundary")
        if self.serialized_bytes() > data["scope"]["budget_bytes"]:
            raise RagError("Serialized packet exceeds byte budget")
        check_refs(data["bindings"])
        if "library_revision" in data["bindings"]:
            from .library_connector import load_binding
            revision = load_binding(data["bindings"]["library_revision"]["path"])
            pinned = revision.to_dict()
            expected_refs = {name if name in {"library", "config"} else "revision:" + name: ref
                             for name, ref in pinned["bindings"].items()}
            if (str(revision.root) != data["library_root"]
                    or not set(pinned["excluded_card_ids"]) <= set(data["scope"]["excluded_card_ids"])
                    or any(data["bindings"].get(name) != ref for name, ref in expected_refs.items())):
                raise RagError("Packet conflicts with pinned library revision or exclusions")
        _verify_selected(data)
        return self

    def save(self, path):
        self.verify()
        path = Path(path).resolve()
        # Canonical on-disk envelope has exactly the bytes that were budgeted.
        with path.open("x", encoding="utf-8", newline="") as stream:
            stream.write(canonical(self.envelope()))
        self.verify()
        return path

    @classmethod
    def load(cls, path):
        ref = file_ref(path)
        value = read_json(path)
        if set(value) != {"packet_sha256", "packet"}:
            raise RagError("Invalid packet envelope")
        packet = cls(canonical(value["packet"]), value["packet_sha256"])
        packet.verify()
        check_refs({"packet": ref})
        return packet


def _eligible_source(source, scope):
    return (scope["topic"] in source.get("topics", [])
            and source.get("source_status") in scope["source_statuses"]
            and source.get("access_level") in scope["access_levels"])


def _eligible_card(card, scope):
    return (scope["topic"] in card.get("topics", [])
            and card.get("status") in scope["card_statuses"]
            and card.get("id") not in scope.get("excluded_card_ids", [])
            and not scope.get("raw_only", False)
            and (scope["allow_draft"] or "DRAFT" not in card.get("status", "").upper()))


def _chunk(db, cid):
    row = db.execute("SELECT source_id,locator,text,sha256 FROM chunks WHERE id=?", (cid,)).fetchone()
    if row is None:
        raise RagError("Dangling citation: " + cid)
    source_id, locator, text, expected = row
    if not isinstance(locator, str) or not locator or not isinstance(text, str) or not text:
        raise RagError("Citation lacks locator or original text: " + cid)
    if text_hash(text) != expected:
        raise RagError("Corrupt cited chunk hash: " + cid)
    return {"id": cid, "source_id": source_id, "locator": locator, "text": text, "sha256": expected}


def _card_chunks(db, card):
    ids = nonempty_list(card.get("evidence_chunk_ids"), "card citations")
    claimed_sources = nonempty_list(card.get("source_ids"), "card sources")
    chunks = [_chunk(db, cid) for cid in ids]
    if sorted({c["source_id"] for c in chunks}) != claimed_sources:
        raise RagError("Card source_ids disagree with citations: " + card["id"])
    return chunks


def _verify_selected(data):
    if 'retrieval_plan' in data['scope']:
        from .retrieval_plan import verify_plan_selection
        verify_plan_selection(data)
    scope = data["scope"]
    if (type(scope["allow_draft"]) is not bool or type(scope["raw_only"]) is not bool
            or type(scope["limit"]) is not int or type(scope["budget_bytes"]) is not int):
        raise RagError("Frozen scope has invalid boolean or numeric types")
    for key in ("allowed_source_ids", "source_statuses", "card_statuses", "access_levels"):
        if scope[key] != nonempty_list(scope[key], key):
            raise RagError("Frozen scope must contain canonical explicit lists")
    exclusions = scope["excluded_card_ids"]
    if (not isinstance(exclusions, list) or any(not isinstance(v, str) or not v for v in exclusions)
            or exclusions != sorted(set(exclusions))):
        raise RagError("Invalid frozen card exclusions")
    if data["scope_sha256"] != digest(scope) or data["selection_sha256"] != digest(
            {k: data[k] for k in ("units", "cards", "chunks", "sources")}):
        raise RagError("Scope or selected evidence binding mismatch")
    if not scope["allowed_source_ids"]:
        raise RagError("Empty permitted source scope")
    dbpath = data["bindings"]["library"]["path"]
    root = Path(data["library_root"]).resolve(strict=True)
    if Path(dbpath).resolve() != root / "knowledge.sqlite":
        raise RagError("Library binding does not belong to frozen root")
    config = read_json(data["bindings"]["config"]["path"])
    policy = library_policy(data["bindings"], root, scope)
    if policy and (len(data["cards"]) > policy["max_cards"] or not _fits(_packet(data),scope['budget_bytes'],policy)):
        raise RagError("Packet exceeds pinned library policy limits")
    if config.get("version") != "PKPD_RAG_CONFIG_1.0" or scope["stage"] not in config["stage_topics"] or scope["topic"] not in config["stage_topics"][scope["stage"]]:
        raise RagError("Frozen scope violates configured stage/topic")
    if not 1 <= scope["limit"] <= config["max_units"] or not 1 <= scope["budget_bytes"] <= config["max_packet_bytes"]:
        raise RagError("Frozen scope exceeds configured bounds")
    if query_terms(data["query"], config)[0] != data["query_terms"]:
        raise RagError("Frozen query normalization mismatch")
    if not scope["allow_draft"] and any("DRAFT" in s.upper() for s in scope["card_statuses"] + scope["source_statuses"]):
        raise RagError("Frozen scope lacks draft opt-in")
    with closing(open_library(dbpath)) as db:
        seen_chunks = set()
        for sid, source in data["sources"].items():
            if sid not in scope["allowed_source_ids"] or source.get("id") != sid or not _eligible_source(source, scope):
                raise RagError("Selected source violates scope")
            row = db.execute("SELECT json FROM sources WHERE id=?", (sid,)).fetchone()
            if row is None or json.loads(row[0]) != source:
                raise RagError("Selected source metadata changed")
            ref = file_ref(source_path(root, source))
            if ref != data["bindings"]["source:" + sid] or ref["sha256"] != source["sha256"]:
                raise RagError("Original source/hash mismatch")
        for chunk in data["chunks"]:
            if chunk["id"] in seen_chunks or chunk != _chunk(db, chunk["id"]):
                raise RagError("Duplicate or altered original chunk")
            seen_chunks.add(chunk["id"])
            if chunk["source_id"] not in data["sources"]:
                raise RagError("Chunk source is not selected")
        card_ids = set()
        cited_chunks = set()
        for card in data["cards"]:
            if card["id"] in card_ids:
                raise RagError("Duplicate selected card")
            card_ids.add(card["id"])
            row = db.execute("SELECT json FROM cards WHERE id=?", (card["id"],)).fetchone()
            if row is None or json.loads(row[0]) != card or not _eligible_card(card, scope):
                raise RagError("Selected card changed or violates scope")
            if not set(card["source_ids"]) <= set(data["sources"]):
                raise RagError("Card source not selected")
            cited = {c["id"] for c in _card_chunks(db, card)}
            if not cited <= seen_chunks:
                raise RagError("Card citation omitted")
            cited_chunks.update(cited)
        unit_ids = set()
        unit_cards = set()
        raw_chunks = set()
        for rank, unit in enumerate(data["units"], 1):
            key = (unit["kind"], unit["id"])
            if unit["rank"] != rank or key in unit_ids:
                raise RagError("Invalid rank or duplicate evidence unit")
            unit_ids.add(key)
            if unit["kind"] == "card" and unit["id"] in card_ids:
                unit_cards.add(unit["id"])
            elif unit["kind"] == "chunk" and unit["id"] in seen_chunks:
                raw_chunks.add(unit["id"])
            else:
                raise RagError("Evidence unit has no selected content")
        if unit_cards != card_ids or raw_chunks | cited_chunks != seen_chunks:
            raise RagError("Unbound selected content outside evidence units")
        if set(data["sources"]) != {c["source_id"] for c in data["chunks"]}:
            raise RagError("Unreferenced selected source metadata")
        if len(data["units"]) > scope["limit"]:
            raise RagError("Selection exceeds requested limit")
    check_refs(data["bindings"])


def _packet(data):
    data["selection_sha256"] = digest({k: data[k] for k in ("units", "cards", "chunks", "sources")})
    return EvidencePacket(canonical(data), digest(data))


def retrieve(root, query, topic, stage, allowed_source_ids, *, source_statuses,
             card_statuses, access_levels, allow_draft=False, limit=6,
             budget_bytes=24000, config_path=None, excluded_card_ids=(), raw_only=False,
             library_binding_path=None, _checkpoint: Callable | None = None):
    """Recall cards AND original chunks independently; filter before rank/limit.

    `_checkpoint` is a test-only callback invoked after inputs freeze; no provider
    or network hook. Wider biological applicability metadata is deferred: cards'
    conditions/required_inputs/limitations are preserved for independent review.
    """
    root = Path(root).resolve(strict=True)
    revision = None
    binding_ref = None
    if library_binding_path is not None:
        from .library_connector import load_binding
        binding_ref = file_ref(library_binding_path)
        revision = load_binding(library_binding_path)
        if config_path is None:
            config_path = revision.to_dict()["bindings"]["config"]["path"]
    config_path = Path(config_path or HERE / "rag_config.v1.json").resolve(strict=True)
    dbpath = root / "knowledge.sqlite"
    refs = {"config": file_ref(config_path), "library": file_ref(dbpath)}
    revision_exclusions = []
    if revision is not None:
        if (revision.root != root or revision.to_dict()["bindings"]["config"] != refs["config"]
                or revision.to_dict()["bindings"]["library"] != refs["library"]):
            raise RagError("Pinned revision differs from requested library/config")
        revision_exclusions = revision.to_dict()["excluded_card_ids"]
        refs["library_revision"] = binding_ref
        for name, ref in revision.to_dict()["bindings"].items():
            if name not in {"library", "config"}:
                refs["revision:" + name] = ref
    elif (root / "retrieval_policy.json").exists():
        refs["library_policy"] = file_ref(root / "retrieval_policy.json")
    reject_sidecars(dbpath)
    config = read_json(config_path)
    if config.get("version") != "PKPD_RAG_CONFIG_1.0":
        raise RagError("Unsupported retrieval configuration")
    if stage not in config["stage_topics"] or topic not in config["stage_topics"][stage] or topic not in config["topics"]:
        raise RagError("Unsupported stage/topic scope")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= config["max_units"]:
        raise RagError("Limit outside configured bounds")
    if isinstance(budget_bytes, bool) or not isinstance(budget_bytes, int) or not 1 <= budget_bytes <= config["max_packet_bytes"]:
        raise RagError("Byte budget outside configured bounds")
    if not isinstance(allow_draft, bool):
        raise RagError("allow_draft must be an explicit boolean")
    if not isinstance(raw_only, bool) or not isinstance(excluded_card_ids, (list, tuple)) or any(not isinstance(v, str) or not v for v in excluded_card_ids):
        raise RagError("raw_only must be boolean and excluded_card_ids must contain nonempty IDs")
    scope = {"topic": topic, "stage": stage,
             "allowed_source_ids": nonempty_list(allowed_source_ids, "allowed source IDs"),
             "source_statuses": nonempty_list(source_statuses, "source statuses"),
             "card_statuses": nonempty_list(card_statuses, "card statuses"),
             "access_levels": nonempty_list(access_levels, "access levels"),
             "allow_draft": allow_draft, "limit": limit, "budget_bytes": budget_bytes,
             "excluded_card_ids": sorted(set(excluded_card_ids) | set(revision_exclusions)), "raw_only": raw_only}
    if not allow_draft and any("DRAFT" in s.upper() for s in scope["card_statuses"] + scope["source_statuses"]):
        raise RagError("Draft status allowance requires explicit allow_draft=True")
    policy = library_policy(refs, root, scope)
    terms, match = query_terms(query, config)
    with closing(open_library(dbpath)) as db:
        sources = {}
        for sid in scope["allowed_source_ids"]:
            row = db.execute("SELECT json FROM sources WHERE id=?", (sid,)).fetchone()
            if row is None:
                raise RagError("Unknown allowed source ID: " + sid)
            source = json.loads(row[0])
            if source.get("id") != sid:
                raise RagError("Source identity mismatch")
            ref = file_ref(source_path(root, source))
            if ref["sha256"] != source.get("sha256"):
                raise RagError("Original source hash mismatch: " + sid)
            refs["source:" + sid] = ref
            sources[sid] = source
        check_refs(refs)
        if _checkpoint is not None:
            _checkpoint()
        eligible = {sid for sid, source in sources.items() if _eligible_source(source, scope)}
        candidates = {}
        filtered = {"cards": 0, "chunks": 0}
        # No SQL LIMIT: denied high-ranked rows cannot hide permitted low ranks.
        card_rows = db.execute("SELECT c.id,c.json,bm25(cards_fts) FROM cards_fts f JOIN cards c ON c.id=f.id "
                               "WHERE cards_fts MATCH ? ORDER BY bm25(cards_fts),c.id", (match,)).fetchall()
        card_rank = 0
        for cid, encoded, _score in card_rows:
            card = json.loads(encoded)
            if card.get("id") != cid:
                raise RagError("Card identity mismatch")
            declared = card.get("source_ids")
            if not _eligible_card(card, scope) or not declared or not set(declared) <= eligible:
                filtered["cards"] += 1
                continue
            chunks = _card_chunks(db, card)
            if any(c["source_id"] not in eligible for c in chunks):
                raise RagError("Card citation violates permitted source scope")
            card_rank += 1
            candidates[("card", cid)] = {"kind": "card", "id": cid, "card": card, "chunks": chunks,
                                         "score": 1 / (60 + card_rank)}
        chunk_rows = db.execute("SELECT c.id,bm25(chunks_fts) FROM chunks_fts f JOIN chunks c ON c.id=f.id "
                                "WHERE chunks_fts MATCH ? ORDER BY bm25(chunks_fts),c.id", (match,)).fetchall()
        chunk_rank = 0
        for cid, _score in chunk_rows:
            row = db.execute("SELECT source_id FROM chunks WHERE id=?", (cid,)).fetchone()
            if row[0] not in eligible:
                filtered["chunks"] += 1
                continue
            chunk = _chunk(db, cid)
            chunk_rank += 1
            candidates[("chunk", cid)] = {"kind": "chunk", "id": cid, "chunks": [chunk],
                                          "score": 1 / (60 + chunk_rank)}
        ranked = sorted(candidates.values(), key=lambda item: (-item["score"], item["kind"] != "card", item["id"]))
        data = {"version": VERSION, "query": query, "query_terms": terms, "scope": scope,
                "scope_sha256": digest(scope), "library_root": str(root),
                "bindings": {k: ref for k, ref in refs.items() if not k.startswith("source:")},
                "units": [], "cards": [], "chunks": [], "sources": {},
                "omissions": {"budget_units": 0, "limit_units": 0, "duplicate_raw_units": 0,
                              "filtered_hits": filtered},
                "gaps": ["Applicability and scientific entailment require independent review."],
                "status": "NO_MATCH_NOT_EVIDENCE_OF_ABSENCE", "empty_reason": "NO_ELIGIBLE_LEXICAL_MATCH",
                "rank_note": config["rank_note"], "scientific_approval": False,
                "usage_boundary": USAGE_BOUNDARY,
                "production_dispatch_authorized": False}
        base = _packet(data)
        if not _fits(base, budget_bytes, policy):
            raise RagError("Mandatory packet provenance exceeds byte budget; no content truncated")
        # Each candidate is accepted with all citations/metadata or omitted whole.
        for item in ranked:
            existing = {c["id"] for c in data["chunks"]}
            if item["kind"] == "chunk" and item["id"] in existing:
                data["omissions"]["duplicate_raw_units"] += 1
                continue
            if (len(data["units"]) >= limit or
                    (policy and item["kind"] == "card" and len(data["cards"]) >= policy["max_cards"])):
                data["omissions"]["limit_units"] += 1
                continue
            trial = json.loads(canonical(data))
            trial["units"].append({"kind": item["kind"], "id": item["id"], "rank": len(trial["units"]) + 1})
            if item["kind"] == "card":
                trial["cards"].append(item["card"])
            trial["chunks"].extend(c for c in item["chunks"] if c["id"] not in existing)
            for chunk in item["chunks"]:
                trial["sources"][chunk["source_id"]] = sources[chunk["source_id"]]
                trial["bindings"]["source:" + chunk["source_id"]] = refs["source:" + chunk["source_id"]]
            trial["status"] = "OPTIONAL_BACKGROUND_FOR_LOCAL_REVIEW"
            trial["empty_reason"] = None
            if not _fits(_packet(trial), budget_bytes, policy):
                data["omissions"]["budget_units"] += 1
                continue
            data = trial
        if not data["units"] and ranked:
            data["empty_reason"] = "ALL_EVIDENCE_UNITS_EXCEED_BUDGET"
        packet = _packet(data)
        # Counters can add bytes at decimal boundaries; fail instead of trimming.
        if not _fits(packet, budget_bytes, policy):
            raise RagError("Packet provenance and omission counts exceed byte budget")
        check_refs(refs)
    return packet.verify()


def main():
    parser = argparse.ArgumentParser(description="Offline explicit-source RAG; no model calls")
    parser.add_argument("--root", required=True)
    parser.add_argument("--query", required=True)
    parser.add_argument("--topic", required=True)
    parser.add_argument("--stage", required=True)
    parser.add_argument("--source-id", action="append", required=True)
    parser.add_argument("--source-status", action="append", required=True)
    parser.add_argument("--card-status", action="append", required=True)
    parser.add_argument("--access-level", action="append", required=True)
    parser.add_argument("--allow-draft", action="store_true")
    parser.add_argument("--raw-only", action="store_true")
    parser.add_argument("--exclude-card-id", action="append", default=[])
    parser.add_argument("--library-binding", help="Immutable binding produced by library_connector.py")
    parser.add_argument("--limit", type=int, default=6)
    parser.add_argument("--budget-bytes", type=int, default=24000)
    parser.add_argument("--out", required=True, help="New packet file")
    args = parser.parse_args()
    packet = retrieve(args.root, args.query, args.topic, args.stage, args.source_id,
                      source_statuses=args.source_status, card_statuses=args.card_status,
                      access_levels=args.access_level, allow_draft=args.allow_draft,
                      limit=args.limit, budget_bytes=args.budget_bytes, raw_only=args.raw_only,
                      excluded_card_ids=args.exclude_card_id, library_binding_path=args.library_binding)
    packet.save(args.out)
    print(canonical({"out": str(Path(args.out).resolve()), "status": packet.to_dict()["status"],
                     "packet_sha256": packet.sha256, "serialized_bytes": packet.serialized_bytes(), "model_calls": 0}))


if __name__ == "__main__":
    main()
