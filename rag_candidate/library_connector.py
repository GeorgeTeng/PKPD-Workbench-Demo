"""Resolve latest ONCE at run start, validate, pin an immutable local binding.

No watcher, automation, model calls, or writes to the knowledge library. The
mutable pointer is deliberately absent from old packet/builder file bindings.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from dataclasses import dataclass
import json
from pathlib import Path
import re
import tarfile

from .rag_v1 import HERE, RagError, _card_chunks, _chunk, canonical, check_refs, digest, file_ref, open_library, read_json, source_path

VERSION = "PKPD_LIBRARY_BINDING_1.0"
STATUS = "DRAFT_STRUCTURAL_INTEGRITY_CHECKED_ONLY"
REQUIRED_TABLES = {
    "sources": {"id", "json"}, "cards": {"id", "json"},
    "chunks": {"id", "source_id", "locator", "text", "sha256"},
    "cards_fts": {"id", "topics", "title", "claim", "details"},
    "chunks_fts": {"id", "source_id", "text"},
}


def _anchor_manifest(archive, manifest_path):
    # Do not extract anything. A verified archive identity must actually anchor
    # the extracted manifest, rather than accepting coherent local rewrites.
    with tarfile.open(archive, "r:gz") as bundle:
        members = [m for m in bundle.getmembers() if m.name == "knowledge/result_manifest.json"]
        if len(members) != 1 or not members[0].isfile() or members[0].size > 10_000_000:
            raise RagError("Archive lacks one bounded knowledge/result_manifest.json")
        with bundle.extractfile(members[0]) as stream:
            if stream.read() != Path(manifest_path).read_bytes():
                raise RagError("Extracted result manifest differs from verified archive")


def _validate_manifest(root, manifest_path):
    manifest = read_json(manifest_path)
    if not isinstance(manifest, dict) or "knowledge.sqlite" not in manifest:
        raise RagError("Result manifest must bind knowledge.sqlite")
    refs = {}
    for relative, expected in manifest.items():
        if not isinstance(relative, str) or not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
            raise RagError("Invalid result-manifest entry")
        path = (root / relative).resolve(strict=True)
        if not path.is_relative_to(root) or path == root:
            raise RagError("Result manifest path escapes library")
        refs["manifest:" + relative] = {"path": str(path), "sha256": expected}
    check_refs(refs)
    return manifest, refs


def _validate_sqlite(root, manifest):
    with closing(open_library(root / "knowledge.sqlite")) as db:
        if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise RagError("SQLite integrity check failed")
        for table, columns in REQUIRED_TABLES.items():
            actual = {row[1] for row in db.execute("PRAGMA table_info(" + table + ")")}
            if actual != columns:
                raise RagError("Unsupported SQLite schema: " + table)
        known = set()
        for sid, encoded in db.execute("SELECT id,json FROM sources"):
            source = json.loads(encoded)
            if source.get("id") != sid or not all(k in source for k in
                    ("title", "local_path", "sha256", "topics", "document_type", "access_level", "source_status")):
                raise RagError("Incomplete source metadata: " + sid)
            if (not isinstance(source["topics"], list) or not source["topics"]
                    or any(not isinstance(t, str) or not t for t in source["topics"])
                    or any(not isinstance(source[k], str) or not source[k] for k in
                           ("title", "document_type", "source_status", "access_level"))):
                raise RagError("Missing source applicability metadata: " + sid)
            original = source_path(root, source)
            relative = original.relative_to(root).as_posix()
            if manifest.get(relative) != source["sha256"]:
                raise RagError("Original source is absent from anchored manifest: " + sid)
            if file_ref(original)["sha256"] != source["sha256"]:
                raise RagError("Original source hash mismatch: " + sid)
            known.add(sid)
        for cid, sid in db.execute("SELECT id,source_id FROM chunks"):
            if sid not in known:
                raise RagError("Chunk references unknown source: " + cid)
            _chunk(db, cid)
        for cid, encoded in db.execute("SELECT id,json FROM cards"):
            card = json.loads(encoded)
            required = {"id", "topics", "title", "claim", "conditions", "required_inputs", "limitations",
                        "downstream_use", "evidence_chunk_ids", "source_ids", "status", "kind", "origin_job"}
            if not required <= card.keys() or card["id"] != cid or not card["topics"] or not card["status"]:
                raise RagError("Incomplete card schema: " + cid)
            if not set(card["source_ids"]) <= known:
                raise RagError("Card references unknown source: " + cid)
            _card_chunks(db, card)
        # FTS integrity_check alone cannot detect stale indexed content.
        # Compare stored FTS projections with their authoritative records.
        if db.execute("SELECT count(*) FROM chunks_fts").fetchone()[0] != db.execute("SELECT count(*) FROM chunks").fetchone()[0]:
            raise RagError("Chunk FTS row count differs from original records")
        for cid, sid, text in db.execute("SELECT id,source_id,text FROM chunks_fts"):
            if db.execute("SELECT source_id,text FROM chunks WHERE id=?", (cid,)).fetchall() != [(sid, text)]:
                raise RagError("Stale chunk FTS content: " + cid)
        if db.execute("SELECT count(*) FROM cards_fts").fetchone()[0] != db.execute("SELECT count(*) FROM cards").fetchone()[0]:
            raise RagError("Card FTS row count differs from authoritative records")
        seen = set()
        for cid, topics, title, claim, details in db.execute("SELECT id,topics,title,claim,details FROM cards_fts"):
            row = db.execute("SELECT json FROM cards WHERE id=?", (cid,)).fetchone()
            if row is None or cid in seen:
                raise RagError("Unknown or duplicate card FTS identity: " + cid)
            seen.add(cid)
            card = json.loads(row[0])
            if ((topics, title, claim) != (" ".join(card["topics"]), card["title"], card["claim"])
                    or json.loads(details) != {k: card[k] for k in ("conditions", "required_inputs", "limitations", "downstream_use")}):
                raise RagError("Stale card FTS content: " + cid)


def _exclusions(connection, revision_sha256):
    if connection.get("version") != "PKPD_RAG_CONNECTION_1.0":
        raise RagError("Unsupported connection config version")
    mapping = connection.get("revision_excluded_card_ids")
    if not isinstance(mapping, dict):
        raise RagError("Revision exclusion mapping required")
    for key, ids in mapping.items():
        if (not re.fullmatch(r"[0-9a-f]{64}", key) or not isinstance(ids, list)
                or any(not isinstance(cid, str) or not cid for cid in ids)):
            raise RagError("Invalid revision-specific exclusion policy")
    return sorted(set(mapping.get(revision_sha256, [])))


@dataclass(frozen=True)
class LibraryRevision:
    _serialized: str
    _sha256: str
    binding_path: Path

    @property
    def root(self):
        return Path(self.to_dict()["library_root"])

    def to_dict(self):
        return json.loads(self._serialized)

    def verify(self):
        value = self.to_dict()
        if canonical(value) != self._serialized or digest(value) != self._sha256 or value.get("version") != VERSION:
            raise RagError("Library binding content/hash mismatch")
        check_refs(value["bindings"])
        refs = value["bindings"]
        if value["revision_sha256"] != refs["archive"]["sha256"]:
            raise RagError("Revision identity differs from bound archive")
        if (value.get("status") != STATUS or value.get("scientific_approval") is not False
                or value.get("production_dispatch_authorized") is not False):
            raise RagError("Pinned revision cannot claim approval or dispatch authorization")
        if value["excluded_card_ids"] != _exclusions(read_json(refs["connection_config"]["path"]), value["revision_sha256"]):
            raise RagError("Revision exclusions differ from bound connection policy")
        if read_json(refs["config"]["path"]).get("version") != "PKPD_RAG_CONFIG_1.0":
            raise RagError("Unsupported pinned retrieval config")
        if Path(value["bindings"]["library"]["path"]).resolve() != self.root / "knowledge.sqlite":
            raise RagError("Pinned database escaped versioned library root")
        if (Path(refs["result_manifest"]["path"]).resolve() != self.root / "result_manifest.json"
                or Path(refs["archive"]["path"]).resolve() != self.root.parent / "pkpd_knowledge_draft.tar.gz"):
            raise RagError("Pinned manifest/archive escaped versioned library layout")
        manifest, members = _validate_manifest(self.root, value["bindings"]["result_manifest"]["path"])
        if manifest["knowledge.sqlite"] != refs["library"]["sha256"]:
            raise RagError("Pinned database differs from anchored manifest")
        policy_path = self.root / "retrieval_policy.json"
        if policy_path.exists() != ("library_policy" in refs):
            raise RagError("Library policy must be explicitly bound when present")
        if "library_policy" in refs and (Path(refs["library_policy"]["path"]).resolve() != policy_path
                or manifest.get("retrieval_policy.json") != refs["library_policy"]["sha256"]):
            raise RagError("Pinned library policy differs from anchored manifest")
        _anchor_manifest(value["bindings"]["archive"]["path"], value["bindings"]["result_manifest"]["path"])
        check_refs(members)
        check_refs(value["bindings"])
        return self


def load_binding(path):
    ref = file_ref(path)
    value = read_json(path)
    if set(value) != {"binding_sha256", "binding"}:
        raise RagError("Invalid library binding envelope")
    result = LibraryRevision(canonical(value["binding"]), value["binding_sha256"], Path(path).resolve())
    result.verify()
    check_refs({"library_binding": ref})
    return result


def resolve_revision(pointer_path, run_dir, *, config_path=None, connection_config_path=None):
    """Pin current completed draft revision into a NEW local run directory.

    Archive + full result-manifest hashes and schema/citation integrity are
    checked. Scientific correctness of card claims is explicitly not inferred.
    A later pointer update cannot rebind an existing run.
    """
    pointer_path = Path(pointer_path).resolve(strict=True)
    pointer_ref = file_ref(pointer_path)
    pointer = read_json(pointer_path)
    if pointer.get("remote_status") != "COMPLETED_DRAFT" or not isinstance(pointer.get("sha256"), str) or len(pointer["sha256"]) != 64:
        raise RagError("Latest pointer is not a completed versioned draft")
    root = Path(pointer["path"]).resolve(strict=True)
    if not root.is_relative_to(pointer_path.parent) or root == pointer_path.parent:
        raise RagError("Latest pointer escapes its library directory")
    archive = root.parent / "pkpd_knowledge_draft.tar.gz"
    archive_ref = file_ref(archive)
    if archive_ref["sha256"] != pointer["sha256"]:
        raise RagError("Downloaded archive differs from latest pointer hash")
    manifest_path = root / "result_manifest.json"
    refs = {"library": file_ref(root / "knowledge.sqlite"), "archive": archive_ref,
            "result_manifest": file_ref(manifest_path),
            "config": file_ref(config_path or HERE / "rag_config.v1.json"),
            "connection_config": file_ref(connection_config_path or HERE / "connection_config.v1.json")}
    if (root / "retrieval_policy.json").exists():
        refs["library_policy"] = file_ref(root / "retrieval_policy.json")
    config = read_json(refs["config"]["path"])
    connection = read_json(refs["connection_config"]["path"])
    if config.get("version") != "PKPD_RAG_CONFIG_1.0" or connection.get("version") != "PKPD_RAG_CONNECTION_1.0":
        raise RagError("Unsupported connection or retrieval config version")
    manifest, members = _validate_manifest(root, manifest_path)
    _anchor_manifest(archive, manifest_path)
    _validate_sqlite(root, manifest)
    check_refs(members)
    check_refs(refs)
    # Check pointer only during resolution; it is not a persistent file binding.
    check_refs({"latest_pointer_during_resolution": pointer_ref})
    value = {"version": VERSION, "library_root": str(root), "revision_sha256": archive_ref["sha256"],
             "bindings": refs, "excluded_card_ids": _exclusions(connection, archive_ref["sha256"]),
             "status": STATUS, "scientific_approval": False,
             "production_dispatch_authorized": False}
    run_dir = Path(run_dir).resolve()
    if run_dir.is_relative_to(pointer_path.parent):
        raise RagError("Run bindings must be written outside the knowledge library")
    run_dir.mkdir(parents=True, exist_ok=False)
    # Mutable defaults select a NEW run only. Historical replay reads these
    # tiny exact-byte copies, so future exclusion/config updates cannot rebind it.
    config_sources = {name: refs[name] for name in ("config", "connection_config")}
    for name, source in config_sources.items():
        frozen_path = run_dir / (name + ".snapshot.json")
        with frozen_path.open("xb") as stream:
            stream.write(Path(source["path"]).read_bytes())
        frozen_ref = file_ref(frozen_path)
        if frozen_ref["sha256"] != source["sha256"]:
            raise RagError("Configuration changed while taking run snapshot: " + name)
        refs[name] = frozen_ref
    check_refs(config_sources)
    value["configuration_sources_at_resolution"] = config_sources
    path = run_dir / "library_binding.json"
    result = LibraryRevision(canonical(value), digest(value), path)
    path.write_text(canonical({"binding_sha256": result._sha256, "binding": value}), encoding="utf-8")
    result = load_binding(path)
    check_refs(config_sources)
    check_refs({"latest_pointer_during_resolution": pointer_ref})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest", required=True)
    parser.add_argument("--run-dir", required=True)
    args = parser.parse_args()
    revision = resolve_revision(args.latest, args.run_dir)
    print(canonical({"root": str(revision.root), "binding": str(revision.binding_path),
                     "revision_sha256": revision.to_dict()["revision_sha256"], "scientific_approval": False}))


if __name__ == "__main__":
    main()
