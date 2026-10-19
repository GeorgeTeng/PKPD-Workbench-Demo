"""Exact, provenance-bound projection of selected reference sections.

This module does not interpret reference content. A catalog is a complete,
hash-checked partition of one UTF-8 source file. Projection copies the exact
selected source slices (including all mandatory GLOBAL sections) and records
omissions only in the host-side audit.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


class ReferenceScopeError(ValueError):
    """Raised when a reference catalog or projection request is unsafe."""


# The first integration is intentionally restricted to the EDA scientific
# reference text. Expand this allowlist only when another reference field has
# its own reviewed catalog and tests. Rules, governance, and evidence are never
# reference-selectable fields.
REFERENCE_PATH_ALLOWLIST = frozenset({("scientific_reference", "text")})
_NEVER_SELECT_SEGMENTS = frozenset({
    "rules", "project_rules", "governance", "evidence", "evidence_packet",
    "source", "handoff", "result", "results",
})


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _path_parts(value: Any) -> tuple[str, ...]:
    if isinstance(value, (tuple, list)) and value and all(isinstance(x, str) and x for x in value):
        return tuple(value)
    if isinstance(value, str) and value:
        return tuple(value.split("."))
    raise ReferenceScopeError("reference field path must be a non-empty string or tuple of strings")


def _file_ref(value: Any, *, label: str) -> tuple[Path, str]:
    if not isinstance(value, Mapping):
        raise ReferenceScopeError(f"{label} must be a file reference with path and sha256")
    raw_path = value.get("path")
    digest = value.get("sha256")
    if not isinstance(raw_path, str) or not raw_path or not isinstance(digest, str):
        raise ReferenceScopeError(f"{label} must contain string path and sha256")
    if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest.lower()):
        raise ReferenceScopeError(f"{label} sha256 is malformed")
    return Path(raw_path), digest.lower()


def _read_verified(ref: Any, *, label: str, base: Path | None = None) -> tuple[Path, bytes]:
    path, expected = _file_ref(ref, label=label)
    if not path.is_absolute():
        path = ((base / path) if base is not None else path).resolve()
    else:
        path = path.resolve()
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ReferenceScopeError(f"cannot read {label}: {path}") from exc
    if sha256_bytes(data) != expected:
        raise ReferenceScopeError(f"{label} hash mismatch: {path}")
    return path, data


def _get_path(root: Any, parts: tuple[str, ...]) -> Any:
    current = root
    for part in parts:
        if not isinstance(current, Mapping) or part not in current:
            raise ReferenceScopeError(f"reference field path does not exist: {'.'.join(parts)}")
        current = current[part]
    return current


def _set_path(root: dict[str, Any], parts: tuple[str, ...], value: Any) -> None:
    current: Any = root
    for part in parts[:-1]:
        if not isinstance(current, dict) or part not in current:
            raise ReferenceScopeError(f"reference field path is not mutable mapping: {'.'.join(parts)}")
        current = current[part]
    if not isinstance(current, dict):
        raise ReferenceScopeError(f"reference field path is not mutable mapping: {'.'.join(parts)}")
    current[parts[-1]] = value


def _validate_catalog(catalog: Mapping[str, Any], source_text: str) -> dict[str, dict[str, Any]]:
    if catalog.get("offset_unit") != "unicode_codepoints":
        raise ReferenceScopeError("catalog offset_unit must be unicode_codepoints")
    if catalog.get("text_sha256") != sha256_bytes(source_text.encode("utf-8")):
        raise ReferenceScopeError("catalog source text hash does not match bound source")
    if catalog.get("text_length") != len(source_text):
        raise ReferenceScopeError("catalog source text length does not match bound source")
    sections = catalog.get("sections")
    if not isinstance(sections, list) or not sections:
        raise ReferenceScopeError("catalog sections must be a non-empty list")
    by_id: dict[str, dict[str, Any]] = {}
    cursor = 0
    for item in sections:
        if not isinstance(item, Mapping):
            raise ReferenceScopeError("catalog section must be an object")
        section_id = item.get("id")
        start, end = item.get("start"), item.get("end")
        role = item.get("role")
        if not isinstance(section_id, str) or not section_id or section_id in by_id:
            raise ReferenceScopeError("catalog section IDs must be unique non-empty strings")
        if role not in {"GLOBAL", "GUIDANCE", "PROVENANCE"}:
            raise ReferenceScopeError(f"invalid role for section {section_id}")
        if not isinstance(start, int) or not isinstance(end, int) or start != cursor or end <= start or end > len(source_text):
            raise ReferenceScopeError(f"catalog partition is incomplete or non-contiguous at {section_id}")
        exact = source_text[start:end]
        if item.get("text_sha256") != sha256_bytes(exact.encode("utf-8")):
            raise ReferenceScopeError(f"section hash mismatch: {section_id}")
        requires = item.get("requires", [])
        if not isinstance(requires, list) or any(not isinstance(x, str) for x in requires):
            raise ReferenceScopeError(f"invalid requires list for {section_id}")
        by_id[section_id] = dict(item)
        cursor = end
    if cursor != len(source_text):
        raise ReferenceScopeError("catalog does not partition the complete source text")
    if not any(s["role"] == "GLOBAL" for s in by_id.values()):
        raise ReferenceScopeError("catalog must contain at least one GLOBAL section")
    for section_id, section in by_id.items():
        missing = [dep for dep in section.get("requires", []) if dep not in by_id]
        if missing:
            raise ReferenceScopeError(f"unknown dependency for {section_id}: {missing}")
    return by_id


def project(
    payload: Mapping[str, Any],
    spec: Any,
    *,
    allowed_paths: Any = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Return a copy with exact selected reference sections, audit, and bindings.

    ``spec`` may be a list of ``{"path": [field, ...], "catalog": file_ref,
    "selected": [section_id, ...]}`` entries, or a mapping from tuple/dotted
    field paths to those field specs. A file_ref is ``{"path": ..., 
    "sha256": ...}``. ``allowed_paths`` is the caller's route allowlist;
    absent it, only the EDA scientific-reference field is allowed. Direct selection is limited to GUIDANCE sections;
    GLOBAL sections are always included and PROVENANCE sections enter only
    through a declared dependency.
    """
    if not isinstance(payload, Mapping):
        raise ReferenceScopeError("payload must be a mapping")
    if isinstance(spec, list):
        entries = []
        for entry in spec:
            if not isinstance(entry, Mapping) or "path" not in entry:
                raise ReferenceScopeError("each reference spec entry must contain a path")
            entries.append((entry["path"], entry))
    elif isinstance(spec, Mapping):
        entries = list(spec.items())
    else:
        raise ReferenceScopeError("projection spec must be a mapping or list of entries")
    if not entries:
        raise ReferenceScopeError("projection spec must not be empty")
    if allowed_paths is None:
        allowed = REFERENCE_PATH_ALLOWLIST
    else:
        if not isinstance(allowed_paths, (list, tuple, set, frozenset)):
            raise ReferenceScopeError("allowed_paths must be a sequence or set of paths")
        allowed = frozenset(_path_parts(path) for path in allowed_paths)
    result = copy.deepcopy(dict(payload))
    audit: dict[str, Any] = {"version": "REFERENCE_SCOPE_AUDIT_1.0", "fields": []}
    bindings: dict[str, Any] = {}
    seen_paths: set[tuple[str, ...]] = set()
    for raw_path, field_spec in entries:
        parts = _path_parts(raw_path)
        if parts in seen_paths:
            raise ReferenceScopeError(f"duplicate reference field path: {'.'.join(parts)}")
        seen_paths.add(parts)
        if any(part.lower() in _NEVER_SELECT_SEGMENTS for part in parts):
            raise ReferenceScopeError(f"protected field cannot be projected: {'.'.join(parts)}")
        if parts not in allowed:
            raise ReferenceScopeError(f"reference field path is not allowlisted: {'.'.join(parts)}")
        if not isinstance(field_spec, Mapping):
            raise ReferenceScopeError(f"spec for {'.'.join(parts)} must be an object")
        original = _get_path(payload, parts)
        if not isinstance(original, str):
            raise ReferenceScopeError(f"reference field must contain exact text: {'.'.join(parts)}")
        catalog_path, catalog_bytes = _read_verified(field_spec.get("catalog"), label="catalog")
        try:
            catalog = json.loads(catalog_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ReferenceScopeError("catalog is not valid UTF-8 JSON") from exc
        if not isinstance(catalog, Mapping):
            raise ReferenceScopeError("catalog root must be an object")
        source_path, source_bytes = _read_verified(
            catalog.get("source"), label="source", base=catalog_path.parent
        )
        try:
            bound_text = source_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ReferenceScopeError("bound source is not UTF-8") from exc
        if original != bound_text:
            raise ReferenceScopeError("payload reference text differs from the bound source")
        by_id = _validate_catalog(catalog, bound_text)
        selected = field_spec.get("selected")
        if not isinstance(selected, list) or any(not isinstance(x, str) for x in selected):
            raise ReferenceScopeError("selected must be a list of section IDs")
        if len(set(selected)) != len(selected):
            raise ReferenceScopeError("selected section IDs must be unique")
        unknown = [sid for sid in selected if sid not in by_id]
        if unknown:
            raise ReferenceScopeError(f"unknown selected section IDs: {unknown}")
        for sid in selected:
            if by_id[sid]["role"] != "GUIDANCE":
                raise ReferenceScopeError(f"only GUIDANCE sections may be selected directly: {sid}")
        included: set[str] = set()
        completed: set[str] = set()
        visiting: set[str] = set()

        def include(sid: str) -> None:
            if sid in completed:
                return
            if sid in visiting:
                raise ReferenceScopeError(f"catalog dependency cycle at {sid}")
            visiting.add(sid)
            for dependency in by_id[sid].get("requires", []):
                include(dependency)
            visiting.remove(sid)
            included.add(sid)
            completed.add(sid)

        for sid, section in by_id.items():
            if section["role"] == "GLOBAL":
                include(sid)
        for sid in selected:
            include(sid)
        ordered = [dict(section) for section in catalog["sections"] if section["id"] in included]
        projected_text = "".join(bound_text[s["start"] : s["end"]] for s in ordered)
        _set_path(result, parts, projected_text)
        # Re-read all bound files after projection to catch concurrent changes.
        if sha256_bytes(catalog_path.read_bytes()) != _file_ref(field_spec.get("catalog"), label="catalog")[1]:
            raise ReferenceScopeError("catalog changed during projection")
        if sha256_bytes(source_path.read_bytes()) != _file_ref(catalog.get("source"), label="source")[1]:
            raise ReferenceScopeError("source changed during projection")
        field_key = ".".join(parts)
        audit["fields"].append({
            "path": list(parts),
            "source_sha256": sha256_bytes(source_bytes),
            "catalog_sha256": sha256_bytes(catalog_bytes),
            "selected": selected,
            "included": [{"id": s["id"], "role": s["role"], "locator": s.get("locator"),
                          "start": s["start"], "end": s["end"], "text_sha256": s["text_sha256"]} for s in ordered],
            "omitted_ids": [s["id"] for s in catalog["sections"] if s["id"] not in included],
            "original_chars": len(bound_text),
            "projected_chars": len(projected_text),
            "projected_sha256": sha256_bytes(projected_text.encode("utf-8")),
        })
        bindings[f"reference_scope.{field_key}.source"] = {"path": str(source_path), "sha256": sha256_bytes(source_bytes)}
        bindings[f"reference_scope.{field_key}.catalog"] = {"path": str(catalog_path), "sha256": sha256_bytes(catalog_bytes)}
    return result, audit, bindings

