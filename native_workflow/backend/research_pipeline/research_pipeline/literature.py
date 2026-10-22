import hashlib
import html
import json
import re
import sqlite3
import urllib.parse
import urllib.request
from pathlib import Path
from .common import PipelineError, read_json, sha256, utcnow
from .references import ALIASES, canonical_drug, drug_mentions


class SearchProvider:
    def search(self, query, limit=10, drug=None):
        raise NotImplementedError


def candidate_screen(title, abstract, drug):
    mentions = drug_mentions(title + " " + abstract)
    target = canonical_drug(drug) if drug else None
    if drug and target not in ALIASES and re.search(r"(?<!\w)"+re.escape(drug)+r"(?!\w)", title+" "+abstract, re.I):
        mentions.append(target)
    return {"drug_mentions": mentions,
      "same_drug_status": "MENTIONED_NOT_MODEL_VERIFIED" if target in mentions else "NOT_ESTABLISHED",
      "model_status": "NOT_VERIFIED", "reliability": "NOT_REVIEWED",
      "note": "Mentioning the drug, including as comparator, does not prove that its PK model was developed or validated."}


class EuropePMC(SearchProvider):
    def search(self, query, limit=10, drug=None):
        if not query.strip() or len(query) > 1000 or not 1 <= limit <= 50:
            raise PipelineError("INVALID_QUERY", "Provide 1-1000 characters and limit 1-50.")
        if not drug:
            raise PipelineError("DRUG_REQUIRED", "Specify the same-drug retrieval target.")
        aliases = ALIASES.get(canonical_drug(drug), [drug])
        drug_query = " OR ".join('TITLE_ABS:"' + alias.replace('"', '') + '"' for alias in aliases)
        effective_query = f"({query}) AND ({drug_query})"
        url = "https://www.ebi.ac.uk/europepmc/webservices/rest/search?" + urllib.parse.urlencode(
            {"query": effective_query, "format": "json", "resultType": "core", "pageSize": limit})
        request = urllib.request.Request(url, headers={"User-Agent": "PKPDResearchPipeline/0.1"})
        try:
            with urllib.request.urlopen(request, timeout=25) as response:
                data = json.load(response)
        except Exception as exc:
            raise PipelineError("ONLINE_SEARCH_FAILED", str(exc)) from exc
        records = []
        for item in data.get("resultList", {}).get("result", []):
            abstract = html.unescape(re.sub(r"<[^>]+>", " ", item.get("abstractText", "")))
            title = item.get("title", "NOT_FOUND")
            records.append({"id": f"{item.get('source','MED')}_{item.get('id','')}", "title": title,
                "doi": item.get("doi", "NOT_FOUND"), "pmid": item.get("pmid", "NOT_FOUND"),
                "year": item.get("pubYear", "NOT_FOUND"), "abstract": abstract or "NOT_FOUND",
                "citation_count": item.get("citedByCount"), "citation_database": "Europe PMC",
                "citation_count_observed_at": utcnow(), "full_text_status": "NOT_FETCHED",
                "data_availability": "NOT_VERIFIED", "code_availability": "NOT_VERIFIED",
                "screening": candidate_screen(title, abstract, drug)})
        return {"schema_version": "1.0", "provider": "online", "query": query, "searched_at": utcnow(),
                "source_url": url, "effective_query":effective_query, "target_drug":canonical_drug(drug), "hit_count": data.get("hitCount"), "results": records,
                "status": "SUCCEEDED", "transmitted": "Only the explicit query and drug aliases; no attachments or project context."}


class LocalLibrary(SearchProvider):
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS documents(id TEXT PRIMARY KEY, title TEXT, path TEXT, sha256 TEXT, metadata TEXT, indexed_at TEXT);
                CREATE VIRTUAL TABLE IF NOT EXISTS chunks USING fts5(document_id UNINDEXED, locator UNINDEXED, title, body, tokenize='unicode61');
            """)

    def connect(self):
        db = sqlite3.connect(self.path, timeout=20)
        db.row_factory = sqlite3.Row
        return db

    def index_file(self, path):
        path = Path(path).resolve(strict=True)
        if path.stat().st_size > 64*1024*1024:
            raise PipelineError("FILE_TOO_LARGE", path.name)
        digest = sha256(path)
        identifier = "doc_" + hashlib.sha256(str(path).encode()).hexdigest()[:20]
        metadata = {"title": path.stem, "record_type": "local_document", "reliability": "NOT_REVIEWED"}
        if path.suffix.lower() == ".pdf":
            from pypdf import PdfReader
            pages = [(f"page:{i+1}", page.extract_text() or "") for i, page in enumerate(PdfReader(path).pages)]
        elif path.suffix.lower() == ".json":
            card = read_json(path)
            if not isinstance(card, dict):
                raise PipelineError("LIBRARY_CARD_TYPE", "A model card must be a JSON object.")
            metadata.update(card)
            pages = [("json", json.dumps(metadata, ensure_ascii=False))]
        elif path.suffix.lower() in (".txt", ".md"):
            pages = [("text", path.read_text(encoding="utf-8-sig"))]
        else:
            raise PipelineError("LIBRARY_FILE_TYPE", "Local literature supports PDF, TXT, MD and JSON model cards.")
        chunks = []
        for locator, text in pages:
            for start in range(0, len(text), 3000):
                body = text[start:start+3000]
                if body.strip():
                    chunks.append((identifier, f"{locator}:chars:{start}-{start+len(body)}", metadata["title"], body))
        if not chunks:
            raise PipelineError("NO_EXTRACTABLE_TEXT", "No searchable text; provide verified OCR text separately.")
        with self.connect() as db:
            db.execute("DELETE FROM chunks WHERE document_id=?", (identifier,))
            db.execute("INSERT OR REPLACE INTO documents VALUES (?,?,?,?,?,?)",
                (identifier, metadata["title"], str(path), digest, json.dumps(metadata, ensure_ascii=False), utcnow()))
            db.executemany("INSERT INTO chunks(document_id,locator,title,body) VALUES (?,?,?,?)", chunks)
        return {"document_id": identifier, "sha256": digest, "chunks": len(chunks), "status": "INDEXED",
                "record_type": metadata["record_type"], "scientific_review": "NOT_GRANTED_BY_INDEXING"}

    def search(self, query, limit=10, drug=None):
        tokens = re.findall(r"[\w-]+", query, flags=re.UNICODE)
        if not tokens or len(query) > 1000 or not 1 <= limit <= 50:
            raise PipelineError("INVALID_QUERY", "Invalid local query or limit.")
        match = " OR ".join('"' + token.replace('"', '""') + '"' for token in tokens)
        with self.connect() as db:
            # Retrieve additional chunks before deduplicating documents.
            rows = db.execute("""SELECT c.document_id,c.locator,c.body,d.title,d.path,d.sha256,d.metadata,
              bm25(chunks,0,0,4,1) AS rank FROM chunks c JOIN documents d ON c.document_id=d.id
              WHERE chunks MATCH ? ORDER BY rank LIMIT ?""", (match, limit*10)).fetchall()
            if not rows:  # Literal substring fallback supports unsegmented Chinese phrases.
                rows = db.execute("""SELECT c.document_id,c.locator,c.body,d.title,d.path,d.sha256,d.metadata,
                  0 AS rank FROM chunks c JOIN documents d ON c.document_id=d.id
                  WHERE instr(lower(c.body),lower(?))>0 LIMIT ?""", (query, limit*10)).fetchall()
        results, seen = [], set()
        for row in rows:
            if row["document_id"] in seen:
                continue
            metadata = json.loads(row["metadata"])
            declared = metadata.get("drug_id")
            if drug and declared and canonical_drug(declared) != canonical_drug(drug):
                continue
            body = row["body"]
            if drug and not declared and candidate_screen(row["title"], body, drug)["same_drug_status"] == "NOT_ESTABLISHED":
                continue
            seen.add(row["document_id"])
            offsets = [body.casefold().find(t.casefold()) for t in tokens]
            first = min((x for x in offsets if x >= 0), default=0)
            snippet = body[max(0, first-80):first+420]
            results.append({"id": row["document_id"], "title": row["title"], "source_path": row["path"],
                "source_sha256": row["sha256"], "locator": row["locator"], "snippet": snippet,
                "document_changed_since_index": not Path(row["path"]).exists() or sha256(row["path"]) != row["sha256"],
                "ranking_method": "FTS5 BM25 or literal fallback", "metadata": metadata,
                "screening": candidate_screen(row["title"], body, drug)})
            if len(results) == limit:
                break
        return {"schema_version": "1.0", "provider": "local", "query": query, "searched_at": utcnow(),
                "results": results, "status": "SUCCEEDED", "network_used": False,
                "note": "Local lexical full-text search; not embedding retrieval or automatic model validation."}

    def status(self):
        with self.connect() as db:
            return {"documents": db.execute("SELECT count(*) FROM documents").fetchone()[0],
                    "chunks": db.execute("SELECT count(*) FROM chunks").fetchone()[0]}


def search(provider, query, state, limit=10, drug=None):
    if provider == "online":
        return EuropePMC().search(query, limit, drug)
    if provider == "local":
        return LocalLibrary(Path(state)/"library.sqlite3").search(query, limit, drug)
    raise PipelineError("UNKNOWN_PROVIDER", provider)
