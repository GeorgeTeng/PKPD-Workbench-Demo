import shutil
import uuid
from pathlib import Path
from .common import PipelineError, require_id, sha256, read_json, write_json

MAX_BYTES = 64 * 1024 * 1024
ALLOWED = {".csv", ".json", ".xlsx", ".pdf", ".txt", ".md", ".docx", ".zip"}


def store_upload(root, fileobj, filename):
    suffix = Path(filename or "").suffix.lower()
    if suffix not in ALLOWED:
        raise PipelineError("FILE_TYPE", "Supported attachments: CSV, JSON, XLSX, PDF, TXT, MD, DOCX, ZIP.")
    identifier = uuid.uuid4().hex
    folder = Path(root) / "uploads" / identifier
    folder.mkdir(parents=True)
    target = folder / ("file" + suffix)
    size = 0
    try:
        with target.open("wb") as output:
            while block := fileobj.read(1024 * 1024):
                size += len(block)
                if size > MAX_BYTES:
                    raise PipelineError("FILE_TOO_LARGE", "Maximum attachment size is 64 MiB.")
                output.write(block)
        value = {"upload_id": identifier, "filename": Path(filename).name, "stored_name": target.name,
                 "bytes": size, "sha256": sha256(target),
                 "readability_status": "PENDING_INTAKE", "qc_status": "NOT_RUN", "fit_ready": False}
        write_json(folder / "metadata.json", value)
        return value
    except Exception:
        target.unlink(missing_ok=True)
        raise


def uploaded_path(root, identifier):
    require_id(identifier)
    folder = Path(root) / "uploads" / identifier
    if not (folder / "metadata.json").is_file():
        raise PipelineError("UPLOAD_NOT_FOUND", "Upload ID is not registered.")
    info = read_json(folder / "metadata.json")
    path = folder / info["stored_name"]
    if not path.is_file():
        raise PipelineError("UPLOAD_NOT_FOUND", "Uploaded file is missing.")
    if sha256(path) != info["sha256"]:
        raise PipelineError("ATTACHMENT_CHANGED", "Uploaded attachment no longer matches its registered hash.")
    return path


def snapshot_attachments(items, destination, state, base, allow_paths=True):
    result = {}
    for item in items:
        identifier = require_id(item["id"])
        if identifier in result:
            raise PipelineError("DUPLICATE_ATTACHMENT", identifier)
        if "path" in item:
            if not allow_paths:
                raise PipelineError("LOCAL_PATH_FORBIDDEN", "HTTP requests must reference upload_id, not a server path.")
            path = Path(item["path"])
            if not path.is_absolute():
                path = Path(base) / path
            path = path.resolve(strict=True)
        else:
            path = uploaded_path(state, item["upload_id"])
        if not path.is_file() or path.suffix.lower() not in ALLOWED:
            raise PipelineError("FILE_TYPE", f"Unsupported attachment: {identifier}")
        if path.stat().st_size > MAX_BYTES:
            raise PipelineError("FILE_TOO_LARGE", identifier)
        target = Path(destination) / (identifier + path.suffix.lower())
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        digest = sha256(target)
        if item.get("sha256", digest).lower() != digest:
            raise PipelineError("HASH_MISMATCH", identifier)
        result[identifier] = {"id": identifier, "path": str(target), "role": item.get("role", "unspecified"),
                              "original_name": path.name, "sha256": digest, "bytes": target.stat().st_size}
    return result
