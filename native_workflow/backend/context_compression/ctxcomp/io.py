"""Strict JSON, immutable run inputs, and document-only ingestion."""
import hashlib
import json
import os
import re
import tempfile
import time
from pathlib import Path


REPLACE_RETRY_DELAYS = (.01, .02, .05, .1, .2, .4, .8)


class AtomicReplaceError(PermissionError):
    """Windows refused publication; the previous destination was not removed."""
    code = 'LOCAL_FILE_REPLACE_BLOCKED'

    def __init__(self, path, error, attempts, waited):
        self.validation_details = {'operation': 'atomic_replace', 'path': str(Path(path).resolve()),
            'winerror': error.winerror, 'errno': error.errno, 'attempts': attempts,
            'retry_wait_seconds': round(waited, 3), 'occupying_process': 'NOT_IDENTIFIED',
            'previous_destination_preserved': True}
        super().__init__(error.errno, f'Windows refused to replace the local file after {attempts} attempts '
            f'({waited:.2f}s retry wait). The file may be open without replacement sharing, read-only, '
            'or access-restricted. No replacement was published.', str(path))


def _replace_with_retry(source, destination):
    waited = 0.0
    for attempt in range(len(REPLACE_RETRY_DELAYS) + 1):
        try:
            os.replace(source, destination)
            return
        except OSError as exc:
            # WinError 5 includes both transient handle contention and persistent ACL
            # failures. Retry it briefly, never assume it identifies an occupying process.
            if getattr(exc, 'winerror', None) not in {5, 32, 33}:
                raise
            if attempt == len(REPLACE_RETRY_DELAYS):
                raise AtomicReplaceError(destination, exc, attempt + 1, waited) from exc
            delay = REPLACE_RETRY_DELAYS[attempt]
            time.sleep(delay)
            waited += delay


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def loads(text):
    def invalid(value):
        raise ValueError(f"Non-finite JSON number: {value}")
    return json.loads(text.lstrip("\ufeff"), object_pairs_hook=_pairs, parse_constant=invalid)


def read_json(path):
    return loads(Path(path).read_text(encoding="utf-8-sig"))


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def atomic_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".writing-", dir=path.parent)
    failure = None
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
        _replace_with_retry(tmp, path)
    except BaseException as exc:
        failure = exc
        raise
    finally:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        except OSError as exc:
            if failure is None:
                raise
            failure.add_note(f'Temporary-file cleanup also failed: {tmp}: {exc}')


def write_json(path, value):
    atomic_text(path, json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def leaves(value, prefix=""):
    """JSON pointer -> nonempty scalar; empty containers carry no factual claim."""
    if isinstance(value, dict):
        for key, child in value.items():
            escaped = key.replace("~", "~0").replace("/", "~1")
            yield from leaves(child, prefix + "/" + escaped)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from leaves(child, prefix + "/" + str(index))
    else:
        yield prefix, value


def document(path, source_id, role):
    path = Path(path).resolve()
    suffix = path.suffix.lower()
    if suffix in {".md", ".txt"}:
        text = path.read_text(encoding="utf-8-sig")
    elif suffix == ".pdf":
        from pypdf import PdfReader
        pages = PdfReader(path).pages
        text = "\n".join(f"[PAGE {i+1}]\n{p.extract_text() or ''}" for i, p in enumerate(pages))
        if not any((p.extract_text() or "").strip() for p in pages):
            raise ValueError("PDF has no extractable text; provide a checked OCR text version.")
    elif suffix == ".docx":
        from docx import Document
        doc = Document(path)
        # iter_inner_content preserves table/paragraph order in current python-docx.
        from docx.table import Table
        chunks = []
        for node in doc.iter_inner_content():
            if isinstance(node, Table):
                chunks.extend(" | ".join(c.text for c in row.cells) for row in node.rows)
            else:
                chunks.append(node.text)
        text = "\n".join(chunks)
    else:
        raise ValueError("Input must be a proposal/description: .md, .txt, .pdf or .docx. Raw data are not ingested.")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if not text.strip():
        raise ValueError(f"Empty document: {path.name}")
    if len(text) > 200_000:
        raise ValueError("Document exceeds 200,000 characters; split into explicit documents. No silent truncation.")
    return {"id": source_id, "name": path.name, "role": role, "text": text,
            "original_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def length_metrics(context, source_text):
    # Historical budget measures content words and compact characters, never tokens.
    strings = [str(v) for p, v in leaves(context) if p != "/version"]
    compact = json.dumps(context, ensure_ascii=False, separators=(",", ":"))
    return {"content_words": len(re.findall(r"\S+", " ".join(strings))),
            "compact_characters": len(compact), "utf8_bytes": len(compact.encode("utf-8")),
            "source_characters": len(source_text),
            "character_retention_ratio": len(compact) / len(source_text) if source_text else None,
            "token_count": None, "tokenizer": "NOT_RUN"}

