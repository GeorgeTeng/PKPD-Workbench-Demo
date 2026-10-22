"""Fixed-location, hash-pinned storage for background registries.

The API accepts a trusted per-run directory, never a caller-supplied file path.
It creates one append-only `background_info.json` and rejects symlinks, stale
hashes, path escape, overwrite, or content drift.
"""
from pathlib import Path
import json
import os

import background_info

STORE_NAME = "background_info.json"


def _fixed_path(trusted_root, *, must_exist=False):
    root = Path(trusted_root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Trusted root must be a directory")
    path = root / STORE_NAME
    if path.parent != root:
        raise ValueError("Store path escaped trusted root")
    if path.is_symlink():
        raise ValueError("Store symlink is forbidden")
    if must_exist and not path.exists():
        raise FileNotFoundError(STORE_NAME)
    if path.exists() and path.resolve(strict=True).parent != root:
        raise ValueError("Resolved store path escaped trusted root")
    return root, path


def save_registry(trusted_root, registry):
    """Create the fixed registry file once; return its relative path and hash."""
    root, path = _fixed_path(trusted_root)
    data = (background_info.canonical(registry) + "\n").encode("utf-8")
    digest = background_info.sha256(registry)
    # Exclusive creation prevents replacing a frozen registry from a later run.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        try:
            path.unlink()
        except OSError:
            pass
        raise
    return {"relative_path": STORE_NAME, "sha256": digest,
            "source_manifest_hashes": registry["source_manifest_hashes"]}


def load_registry(trusted_root, expected_sha256):
    """Load only the fixed file and require the exact caller-pinned digest."""
    if not isinstance(expected_sha256, str) or len(expected_sha256) != 64:
        raise ValueError("Expected registry SHA-256 is required")
    root, path = _fixed_path(trusted_root, must_exist=True)
    value = json.loads(path.read_text(encoding="utf-8"))
    actual = background_info.sha256(value)
    if actual != expected_sha256:
        raise ValueError("Background registry hash mismatch")
    # Recheck after reading to narrow replacement/symlink races.
    _, final_path = _fixed_path(root, must_exist=True)
    if final_path != path or final_path.is_symlink():
        raise ValueError("Background registry path changed during read")
    return value
