"""Return flagged rows to the writer, then independently review the revised board."""
import copy
import hashlib
import json
from itertools import count
from pathlib import Path

from .contracts import CODE_OR_DATA_ISSUES, RANK, effective_answer, quantitative_clauses


EDITABLE = ("status_code", "observed", "basis", "reach", "missing")
TEXT = {"type": "string"}
STRINGS = {"type": "array", "items": TEXT}
PATCH = {"row_id": TEXT, "status_code": {"type": "string", "enum": list(RANK) + ["REVIEW_PENDING"]},
         "observed": TEXT, "basis": TEXT, "reach": TEXT, "missing": STRINGS}
WRITE_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["rows"], "properties": {
    "rows": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                       "required": list(PATCH), "properties": PATCH}}}}
WRITE_PROMPT = """Revise the flagged EDA conclusions using the review feedback, its search keywords,
the source matches, and the original evidence and figures. Return exactly the requested row IDs.
Keep the endpoint and any supported findings. Use a bounded answer when the endpoint lacks evidence.
Preserve the original status of a working hypothesis. Never change a numerical result or imply a plot
has been fixed without evidence. If an independent source or figure fix is needed, leave that issue open.
Copy quantitative sentences verbatim in their original fields. Add limitations in separate sentences.
If the underlying measurement needs correction or a new number is needed, return it for code or data review."""


def fingerprint(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def find_sources(tables, payload, keywords):
    """Bounded retrieval from the supplied tables. No match is not evidence of absence."""
    inventory = {x["dataset_id"]: x for x in payload["inputs_for_species"] + payload.get("project_context", [])}
    terms = [s.casefold() for s in keywords if isinstance(s, str) and s.strip()]
    hits = []
    for t in tables:
        did = t.get("dataset_id")
        if did not in inventory:
            continue
        header = " ".join(str(t.get(k, "")) for k in ("dataset_id", "title", "role", "columns")).casefold()
        matched = []
        score = sum(s in header for s in terms)
        for rec in t.get("records") or []:
            rank = sum(s in json.dumps(rec, ensure_ascii=False).casefold() for s in terms)
            if rank:
                matched.append((rank, rec))
        if score or matched:
            matched.sort(key=lambda pair: -pair[0])
            hits.append((score + (matched[0][0] if matched else 0), {
                "dataset_id": did, "scope": inventory[did].get("scope_relation", "project_context"),
                "columns": t.get("columns"), "records": [v for _, v in matched[:3]]}))
    hits.sort(key=lambda pair: -pair[0])
    return [v for _, v in hits[:5]]


def _split(issues):
    """Issues a writer can resolve, and issues that need a code or data change first."""
    code = [i for i in issues if i.get("type") in CODE_OR_DATA_ISSUES]
    return [i for i in issues if i.get("type") not in CODE_OR_DATA_ISSUES], code


def rerun(req, first, generate, validate, review_prompt, tables, images, max_rounds, cache, resume, retries=1):
    payload = copy.deepcopy(req["payload"])
    by_id = {r["row_id"]: r for r in payload["rows"]}
    original = copy.deepcopy(by_id)
    answer = first
    history, keywords, seen = [], [], set()
    result = {"status": "PENDING", "rounds": history, "updated_rows": {}, "needs_code_or_data": {}, "display_notes": {}}

    def note(store, rid, issues):
        kept = store.setdefault(rid, [])
        for issue in issues:
            if all((issue.get("type"), issue.get("what")) != (k.get("type"), k.get("what")) for k in kept):
                kept.append(issue)

    def call(prompt, schema):
        key = fingerprint([req["id"], prompt, schema, payload["figures"]])
        path = Path(cache) / (key + ".json")
        if resume and path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
        if generate is None:
            raise RuntimeError("No saved response for this revision. Resume with the generator.")
        value = generate(prompt, schema, images)
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        return value

    for turn in count():
        feedback = {}
        for v in answer["rows"]:
            writable, code = _split(v["issues"])
            if v["verdict"] == "CONFIRMED":
                # a confirmed row can carry display notes only (validate_err); they do not block the review
                if code:
                    note(result["display_notes"], v["row_id"], code)
                continue
            if code:
                note(result["needs_code_or_data"], v["row_id"], code)
            if writable or not code:
                feedback[v["row_id"]] = writable or [{"what": "Evidence could not be verified."}]
        for omission in answer.get("omissions", []):
            rid = omission.get("row_id")
            if rid not in by_id:
                result["reason"] = "An omission needs a conclusion row or a new source."
                return result, answer
            feedback.setdefault(rid, []).append(omission)
        if not feedback:
            if result["needs_code_or_data"]:
                result["status"] = "NEEDS_CODE_OR_DATA"
                result["reason"] = ("The wording passed review. A computed value or a figure was questioned; "
                                    "that needs a change in the EDA code or data and a new run, not a new sentence.")
            else:
                result["status"] = "PASSED"
            return result, answer
        result["open_rows"] = sorted(feedback)
        if turn == max_rounds or (generate is None and not resume):
            result["reason"] = "Review is still open. Resume with more rounds or additional evidence."
            return result, answer
        for rid, issues in feedback.items():
            for issue in issues:
                keywords.extend(issue.get("keywords") or [by_id[rid].get("label") or rid])
        keywords = list(dict.fromkeys(k for k in keywords if isinstance(k, str) and k.strip()))
        matches = find_sources(tables, payload, keywords)
        record = {"round": turn + 1, "feedback": feedback, "keywords": list(keywords),
                  "matched_datasets": [m["dataset_id"] for m in matches]}
        history.append(record)
        try:
            request = dict(payload, rows=[by_id[rid] for rid in feedback], feedback=feedback,
                           keywords=keywords, source_matches=matches)
            patch = call(WRITE_PROMPT + "\nREQUEST\n" + json.dumps(request, ensure_ascii=False), WRITE_SCHEMA)["rows"]
            if sorted(v["row_id"] for v in patch) != sorted(feedback):
                raise ValueError("Writer returned different row IDs.")
            for v in patch:
                r = by_id[v["row_id"]]
                allowed = ["REVIEW_PENDING"] if r["kind"] == "hypothesis" else RANK
                if (v["status_code"] not in allowed or not v["observed"].strip()
                        or not isinstance(v["missing"], list) or not all(isinstance(x, str) for x in v["missing"])
                        or not all(isinstance(v[k], str) for k in ("observed", "basis", "reach"))):
                    raise ValueError("Writer returned an invalid conclusion.")
                for field in ("observed", "basis", "reach", "missing"):
                    if quantitative_clauses(v[field]) != quantitative_clauses(original[v["row_id"]].get(field)):
                        result["status"] = "NEEDS_CODE_OR_DATA"
                        result["reason"] = f"{v['row_id']}.{field}: a rewrite changed a source-bound quantitative statement."
                        note(result["needs_code_or_data"], v["row_id"], [{"type": "VALUE_ERROR", "what": result["reason"],
                             "smallest_correction": "Verify the source and recompute the row if the measurement needs changing."}])
                        return result, answer
            for v in patch:
                r = by_id[v["row_id"]]
                r.update({k: v[k] for k in EDITABLE})
                result["updated_rows"][v["row_id"]] = {k: r[k] for k in EDITABLE}
            state = fingerprint([payload["rows"], matches])
            if state in seen:
                result["reason"] = "The same revision and keyword search already failed independent review."
                return result, answer
            seen.add(state)
            packet = dict(payload, previous_findings=feedback, search_keywords=keywords, source_matches=matches)
            prompt = (review_prompt + "\nVerify each earlier finding against the original evidence. A wording change cannot "
                      "resolve an unchanged figure or source defect. Report every unresolved finding. A documented absence "
                      "can support NOT_ANSWERABLE_YET.\nREQUEST\n" + json.dumps(packet, ensure_ascii=False))
            raw = call(prompt, req["schema"])
            ok, problems = validate(raw, dict(req, payload=packet))
            for _ in range(retries):
                if ok:
                    break
                # one more attempt with the host's reasons, as for the first review
                raw = call(prompt + "\n\nYOUR PREVIOUS ANSWER WAS REJECTED BY THE HOST CHECKS. Fix exactly these points and answer again:\n- "
                           + "\n- ".join(problems[:20]), req["schema"])
                ok, problems = validate(raw, dict(req, payload=packet))
            if not ok:
                raise ValueError("Invalid re-review: " + " | ".join(problems))
            answer = effective_answer(raw, payload["rows"])
            record["verdicts"] = {v["row_id"]: v["verdict"] for v in answer["rows"]}
            result.pop("open_rows", None)
        except (KeyError, TypeError, ValueError, RuntimeError, OSError) as exc:
            result["reason"] = str(exc)
            return result, answer
