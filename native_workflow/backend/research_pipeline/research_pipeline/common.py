import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

# Repository layout: <repo>/backend/research_pipeline/research_pipeline/common.py
PROJECT = Path(__file__).resolve().parents[3]  # repository root (pkpd_r/, outputs/ live here)
BACKEND = PROJECT / "backend"                   # Python packages: research_pipeline/, context_compression/
FRONTEND = PROJECT / "frontend"                 # workbench HTML/JS/CSS served at /assets
RULES = BACKEND / "rules"                       # every rule definition the agents load; see rules/README.md
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")


class PipelineError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def require_id(value):
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise PipelineError("INVALID_ID", "IDs must use 1-80 ASCII letters, digits, underscores or hyphens.")
    return value


def read_json(path):
    def reject_constant(value):
        raise PipelineError("INVALID_JSON", f"Non-finite JSON number: {value}")
    return json.loads(Path(path).read_text(encoding="utf-8-sig"), parse_constant=reject_constant)


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    temporary.replace(path)
    return path


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def state_root(path=None):
    return Path(path or os.getenv("RESEARCH_PIPELINE_STATE", PROJECT / "outputs" / "research_pipeline_state")).resolve()


def verify_context(value):
    from jsonschema import Draft202012Validator
    # Reuse the original compact-context schema; no renamed fields or inferred facts.
    required = {"version", "objective", "study", "data", "rules", "checks", "uncertainties"}
    context = value.get("context", value)
    if not isinstance(context, dict) or not required.issubset(context):
        raise PipelineError("INVALID_CONTEXT", "Missing original compact-context keys.")
    schema_path = BACKEND / "context_compression" / "schemas" / "context.schema.json"
    if schema_path.exists():
        schema = read_json(schema_path)
        # The original schema may describe a stage envelope rather than context.
        if required.issubset(schema.get("properties", {})):
            Draft202012Validator(schema).validate(context)
    return context
