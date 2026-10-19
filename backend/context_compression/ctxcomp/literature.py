"""Explicit public-query search. Never derives a query from private project text."""
import json
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from .io import write_json


def search(query, output, page_size=10):
    if not query.strip() or len(query) > 1000:
        raise ValueError("Provide a short public literature query")
    if not 1 <= page_size <= 100:
        raise ValueError("page-size must be 1..100")
    url = "https://www.ebi.ac.uk/europepmc/webservices/rest/search?" + urllib.parse.urlencode(
        {"query": query, "format": "json", "resultType": "core", "pageSize": page_size})
    request = urllib.request.Request(url, headers={"User-Agent": "ResearchContextCompression/3.8"})
    with urllib.request.urlopen(request, timeout=40) as response:
        data = json.load(response)
    papers = []
    for item in data.get("resultList", {}).get("result", []):
        papers.append({"id": f"{item.get('source', 'MED')}_{item.get('id', '')}",
                       "title": item.get("title"), "doi": item.get("doi"),
                       "pmid": item.get("pmid"), "pmcid": item.get("pmcid"),
                       "year": item.get("pubYear"), "abstract": item.get("abstractText"),
                       "citation_count": item.get("citedByCount"), "citation_database": "Europe PMC",
                       "full_text_status": "NOT_FETCHED", "applicability": "NOT_REVIEWED",
                       "raw_data_available": "NOT_VERIFIED", "code_available": "NOT_VERIFIED"})
    result = {"searched_at": datetime.now(timezone.utc).isoformat(), "query": query, "url": url,
              "hit_count": data.get("hitCount"), "papers": papers,
              "note": "Search results are candidates, not approved method references. Citation count is not model quality"}
    write_json(output, result)
    return {"status": "SEARCHED", "returned": len(papers), "hit_count": data.get("hitCount")}
