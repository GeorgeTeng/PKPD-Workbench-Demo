"""EDA review agents: re-review (ERR) and cross-section summary (ES). Host side only.

The three EDA modules compute the original conclusions and figures. This standalone reviewer reads a completed run.

* ERR  re-review. One call per study board and section. The model gets every conclusion row (status, observed,
       basis, reach, missing), the working hypothesis, the PNG files those rows cite, the rule text of the items behind
       each question, and the source points. For each row it returns CONFIRMED / REVISE / UNCERTAIN with typed issues.
       Flagged conclusions return to a writer with search terms. An independent review checks each new draft.
* ES   summary. One call per project. Input: the conclusion rows of all three sections plus the ERR verdicts. Output:
       per species, a short list of statements that each cite the row IDs they rest on, cross-section links and
       conflicts, and open items. The summary runs after all selected boards pass.

Everything that can be checked without a model is checked here: coverage (every row answered once), citations (every
cited figure, rule passage and row exists in the request), status discipline (a summary statement may not be stronger
than the rows it cites), and schema. A model output that fails is recorded with its reasons and is not shown as a review.

The model call itself is injected (``generate(prompt, schema, images) -> dict``) so the same code runs with
eda_questions_v6.call_once in the pipeline, with a recorded response in tests, or offline: ``--write-requests`` writes
each request (prompt, schema, image list) to disk for a manual run.

Error-injection harness (``inject_errors``): plants known errors in copies of the rows so that the catch rate and the
false-alarm rate of ERR can be measured on real boards before it is trusted.
"""
from __future__ import annotations

import copy
import hashlib
import json
import random
import re
import sys
from pathlib import Path
from .contracts import classify, effective_answer, endpoint_limit, host_issue, identity, scope_problem, species_key
from .rerun import rerun

VERSION = "EDA_REVIEW_AGENTS_R0_2"
SECTIONS = ("absorption", "distribution", "elimination")
STATUS_RANK = {"NOT_APPLICABLE": -1, "NOT_ANSWERABLE_YET": 0, "PARTLY_ANSWERABLE": 1, "ANSWERABLE": 2}
VERDICTS = ("CONFIRMED", "REVISE", "UNCERTAIN")
ISSUE_TYPES = ("FIGURE_TEXT_MISMATCH", "VALUE_ERROR", "STATUS_TOO_STRONG", "STATUS_TOO_WEAK", "RULE_MISAPPLIED",
               "FLAG_MISSING", "MISSING_INCOMPLETE", "OMITTED_EVIDENCE", "WORDING_BEYOND_EVIDENCE", "HYPOTHESIS_UNSUPPORTED",
               "DISPLAY")
STRONG_WORDS = r"\b(establish(?:ed|es)?|confirm(?:ed|s)?|demonstrat(?:ed|es)|prov(?:ed|en|es)|shows? that|clearly|definitive(?:ly)?|is (?:the )?mechanism)\b"
MAX_IMAGES = 12          # per ERR call; a board with more figures is split, every part carries its own images
MAX_POINTS = 60          # source points per series passed to ERR

# question -> rule items, used to cut the rule text each row is reviewed against (overridable per run)
ITEM_MAP = {
    # absorption question labels (r4.x): 1 onset, 2 rise and peak, 3 input/disposition models, 4 trough and second rise,
    # 5 individual trajectories, 6 terminal and flip-flop, 7 systemic F, 8 dose proportionality, 9 scaling across conditions
    "absorption": {1: [16, 21], 2: [17], 3: ["A0.10", 17, 18], 4: [20], 5: ["A0.11"], 6: [18], 7: [22, "A0.12"], 8: [19], 9: [23]},
    "distribution": {1: [24], 2: [25], 3: [24], 4: [24], 5: [26], 6: [27], 7: [28]},
    "elimination": {1: [29], 2: [30], 3: [31], 5: [33], 6: [34], 7: [35, 36]},
}
SHARED_SECTION = {"absorption": "A0", "distribution": "D0", "elimination": "E0"}


# ---------------------------------------------------------------- reading the three sections into one row list

def _load(root, section):
    p = Path(root) / section / f"{section}.json"
    if not p.is_file():
        return None, None
    raw = p.read_bytes()
    return json.loads(raw.decode("utf-8-sig")), hashlib.sha256(raw).hexdigest()


def _figs(q):
    out = []
    pr = q.get("primary") or {}
    if pr.get("kind") == "panel" and pr.get("file"):
        out.append({"role": "primary", "panel": ",".join(pr.get("panels") or []), "file": pr["file"], "caption": " · ".join(pr.get("lines") or [])})
    for v in q.get("views") or []:
        if v.get("file"):
            out.append({"role": f"tier {v.get('tier', 1)}", "panel": v.get("panel"), "file": v["file"], "caption": v.get("label") or ""})
    return out


def _row_table(q):
    pr = q.get("primary") or {}
    if pr.get("kind") == "row":
        return {"head": pr.get("head"), "rows": pr.get("rows")}
    return None


def _evidence_tables(q, limit=4):
    out = []
    for ev in (q.get("evidence") or [])[:limit]:
        for t in (ev.get("tables") or [])[:3]:
            out.append({"rule": ev.get("rule"), "caption": t.get("caption"), "head": t.get("head"), "rows": (t.get("rows") or [])[:25]})
    return out


def _row(section, board, q, key, project=None):
    qn = q.get("q")
    shown = q.get("shown", True)
    return {"row_id": f"{section}:{key}:Q{qn}", "kind": "question", "section": section, "board": key, "study": board.get("study"),
            "species": _species(board), "species_text": board.get("species_text") or board.get("species"), "q": qn, "label": q.get("label"), "question": q.get("question"), "status_code": q.get("status_code"),
            "observed": q.get("observed"), "basis": q.get("basis"), "reach": q.get("reach"), "missing": q.get("missing") or [],
            "figures": _figs(q), "value_table": _row_table(q), "evidence": _evidence_tables(q), "shown": shown,
            "datasets": q.get("dataset_ids", board.get("datasets") or []),
            "row_sources": sorted({s for ev in q.get("evidence") or [] for s in ev.get("data") or []
                                   if isinstance(ev.get("data"), list) and isinstance(s, str)}),
            "endpoint_limit": endpoint_limit(section, board, q, project or {}),
            **_scope(board, q)}


def _scope(board, q):
    arm = {k: board[k] for k in ("experiment_arm", "cohort", "regimen") if identity(board.get(k))}
    scope = "project" if q.get("scope") == "project" else ("arm" if arm or q.get("scope") == "arm" else "study")
    return {"claim_scope": scope, "arm": arm, "board_datasets": board.get("datasets") or []}


def _hrow(section, board, key):
    h = board.get("hypothesis")
    if not h:
        return None
    text = h.get("text") or ""
    return {"row_id": f"{section}:{key}:H", "kind": "hypothesis", "section": section, "board": key, "study": board.get("study"),
            "species": _species(board), "q": "H", "label": "Working hypothesis", "question": "What should a model check next?",
            "status_code": "REVIEW_PENDING", "observed": text, "basis": h.get("rests_on") or "; ".join(map(str, h.get("components") or [])),
            "reach": h.get("reach") or h.get("condition") or "", "missing": h.get("missing") or [],
            "figures": [], "value_table": None, "evidence": [], "shown": True,
            "alternatives": h.get("alternatives") or h.get("alternative"), "next_test": h.get("next_test"),
            "checks": h.get("check_first") or h.get("checks_before_modelling") or h.get("checks"), "source_ids": h.get("source_ids"),
            **_scope(board, {})}


def _species(b):
    """Species group used to join the three sections (absorption keeps the source text in 'species')."""
    return b.get("species_group") or b.get("species")


def board_key(section, b):
    return b.get("key") or re.sub(r"[^a-z0-9]+", "-", f"{b.get('study')}-{_species(b)}".lower()).strip("-")


def inventory(root):
    """The input datasets by species (source_tables.json), so the re-review can see data a row says is missing."""
    p = Path(root) / "source_tables.json"
    if not p.is_file():
        return {}
    try:
        tabs = json.loads(p.read_bytes().decode("utf-8-sig"))
    except ValueError:
        return {}
    tabs = tabs.get("datasets") or tabs.get("tables") or [] if isinstance(tabs, dict) else tabs
    out = {}
    for t in tabs or []:
        m = t.get("metadata") or {}
        sp = species_key(m.get("species"))
        study_ids = t.get("study_source_ids")
        if not isinstance(study_ids, list):
            study_ids = [study_ids] if isinstance(study_ids, str) else []
        recs = t.get("records")
        out.setdefault(sp, []).append({k: v for k, v in {
            "dataset_id": t.get("dataset_id"), "study_ids": study_ids, "species_text": m.get("species"),
            "experiment_arm": m.get("experiment_arm") or t.get("experiment_arm"), "cohort": m.get("cohort") or t.get("cohort"),
            "title": t.get("title"), "role": t.get("role"), "matrix": m.get("matrix"),
            "analyte": m.get("analyte"), "route": m.get("route"), "dosing_regimen": m.get("dosing_regimen"),
            "condition": m.get("condition"), "unit": t.get("experimental_unit"), "source": t.get("source_item_id"),
            "n_records": len(recs) if isinstance(recs, list) else None}.items() if v not in (None, "")})
    return out


def coverage(rows, inv):
    """Host check, no model: every input dataset of a species is either used by a board or listed here as unused."""
    used = {}
    for r in rows:
        for d in r.get("datasets") or []:
            used.setdefault(d, set()).add(f"{r['section']}:{r['board']}")
    out = {"datasets": 0, "unused": [], "used_by": {}}
    for sp, items in sorted((inv or {}).items()):
        for x in items:
            out["datasets"] += 1
            did = x.get("dataset_id")
            if did in used:
                out["used_by"][did] = sorted(used[did])
            else:
                out["unused"].append({k: x.get(k) for k in ("dataset_id", "title", "role", "matrix", "route", "dosing_regimen", "condition") if x.get(k)}
                                     | {"species": sp})
    return out


def collect(root):
    """All conclusion rows and hypotheses of the three sections, with the files they cite (paths relative to root)."""
    rows, meta = [], {}
    for sec in SECTIONS:
        d, sha = _load(root, sec)
        meta[sec] = {"present": d is not None, "version": (d or {}).get("version"), "sha256": sha}
        if not d:
            continue
        boards = d.get("status_boards") if sec == "absorption" else d.get("boards")
        seen = {}
        for b in boards or []:
            key = board_key(sec, b)
            seen[key] = seen.get(key, 0) + 1
            if seen[key] > 1:          # two boards of one study and species (e.g. separate dosing designs) keep separate ids
                key = f"{key}-{seen[key]}"
            for q in b.get("questions") or []:
                r = _row(sec, b, q, key, d.get("species_table"))
                for f in r["figures"]:
                    f["path"] = str(Path(sec) / f["file"]) if not f["file"].startswith("../") else str(Path(f["file"][3:]))
                rows.append(r)
            h = _hrow(sec, b, key)
            if h:
                h["cites"] = [r["row_id"] for r in rows if r["section"] == sec and r["board"] == key and r["kind"] == "question" and r.get("shown", True)]
                rows.append(h)
    return rows, meta


# ---------------------------------------------------------------- rule passages

def rule_passages(text):
    """Split a rules markdown file into passages keyed by item number ('29') or shared heading ('E0.6')."""
    out, cur, buf = {}, None, []
    for line in text.splitlines():
        m = re.match(r"^###\s+(\w+)\s*\|", line) or re.match(r"^####\s+([A-Z]\d+\.\d+)\b", line)
        end = re.match(r"^#{2,3}\s", line) and not m       # any other heading closes the passage (sections B, C ...)
        if m or end:
            if cur:
                out[cur] = "\n".join(buf).strip()
            cur, buf = (m.group(1), [line]) if m else (("FLAGS", [line]) if re.match(r"^###\s+Flag registry", line) else (None, []))
        elif cur:
            buf.append(line)
    if cur:
        out[cur] = "\n".join(buf).strip()
    return out


def passages_for(section, q, passages, item_map=None):
    items = (item_map or ITEM_MAP).get(section, {}).get(q, [])
    keep = {}
    for it in items:
        if str(it) in passages:
            keep[str(it)] = passages[str(it)]
    # the shared answer-status and figure rules always travel with a row
    for k, v in passages.items():
        if re.match(rf"^{SHARED_SECTION[section][0]}0\.(11|3|6)$", k) or k in (SHARED_SECTION[section], "FLAGS"):
            keep.setdefault(k, v[:8000])
    return keep


# ---------------------------------------------------------------- ERR: re-review requests

ERR_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["board", "rows", "omissions"],
    "properties": {
        "board": {"type": "string"},
        "rows": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                 "required": ["row_id", "verdict", "checked_figures", "checked_rules", "issues"],
                 "properties": {
                     "row_id": {"type": "string"}, "verdict": {"type": "string", "enum": list(VERDICTS)},
                     "checked_figures": {"type": "array", "items": {"type": "string"}},
                     "checked_rules": {"type": "array", "items": {"type": "string"}},
                     "issues": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                "required": ["type", "what", "evidence", "smallest_correction", "keywords"],
                                "properties": {"type": {"type": "string", "enum": list(ISSUE_TYPES)}, "what": {"type": "string"},
                                               "keywords": {"type": "array", "items": {"type": "string"}},
                                               "evidence": {"type": "object", "additionalProperties": False, "required": ["figure", "rule", "data", "dataset_ids"],
                                                            "properties": {"figure": {"type": ["string", "null"]}, "rule": {"type": ["string", "null"]},
                                                                           "data": {"type": ["string", "null"]}, "dataset_ids": {"type": "array", "items": {"type": "string"}}}},
                                               "smallest_correction": {"type": "string"}}}}}}},
        "omissions": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["row_id", "keywords", "what", "evidence", "rule"],
                      "properties": {"row_id": {"type": ["string", "null"]}, "keywords": {"type": "array", "items": {"type": "string"}},
                                     "what": {"type": "string"}, "evidence": {"type": "string"}, "rule": {"type": ["string", "null"]}}}},
    },
}

ERR_PROMPT = """You are the re-review step of a pharmacokinetic exploratory data analysis (EDA). Host code has already computed
every conclusion below from the source points, following the attached rules. Your job is to check them, not to rewrite them.

For EACH row (question conclusion or working hypothesis) do all of the following and record what you checked:
1. Look at every attached figure the row cites. Does the conclusion sentence (observed, basis, reach) match what the figure
   shows: values, times, number of series, which points are quantified or below the limit, labels and units?
2. Read the rule passages for the row. Is the status (ANSWERABLE, PARTLY_ANSWERABLE, NOT_ANSWERABLE_YET, NOT_APPLICABLE)
   allowed by the rules for this evidence? Are required flags and caveats present? Is anything the rules require missing
   from the 'missing' list?
3. Check numbers against the value table, evidence tables and source points.
4. For a working hypothesis: is each part supported by a cited row, is the alternative still consistent with the data,
   and is the next test feasible? Mark HYPOTHESIS_UNSUPPORTED otherwise.
5. Wording: flag any word stronger than the evidence (established, confirmed, shows that, mechanism) as WORDING_BEYOND_EVIDENCE.
6. Check the specific endpoint asked, and distinguish a measured, limited finding from an unmeasured mechanism.
   Use study IDs, scope_relation, arm/cohort, route, dose/regimen, matrix and occasion before proposing an upgrade.
   Being listed or used by a board does not mean the dataset matches the arm. Other studies and other arms are context,
   not replacements for locally missing evidence. Unknown correspondence is a question for the human reviewer.
   For STATUS_TOO_WEAK or OMITTED_EVIDENCE list the direct supporting dataset_ids; cite external leads separately.
   A project-scoped row may use project_context for a project-wide comparison; still check comparability.
   Return [] for dataset_ids when an issue does not rely on a dataset. Review hidden rows too.
   'context_rows' are the conclusions a hypothesis rests on when they were sent in another part: read them, do not answer them.
7. Scope: a conclusion or hypothesis must stay within the species, route, dose and condition of the data it rests on.
   A statement carried to other species or conditions, or one panel pooling several species, is RULE_MISAPPLIED or
   HYPOTHESIS_UNSUPPORTED.

Verdicts: CONFIRMED when nothing is wrong. REVISE when at least one issue is wrong as stated (give the smallest correction).
UNCERTAIN when you cannot check it (say why in an issue); a row with figures_not_sent is UNCERTAIN unless you find an error. Do not invent figures or rules: cite only file names and rule
keys that appear in this request. Use one exact file or rule ID per reference. For each issue or omission give two to
four specific search keywords (assay, analyte, endpoint or dataset ID). Attach an omission to the affected row,
or give a null row_id if no existing row covers it. Return JSON only.
"""


def err_requests(root, rows, rules_text_by_section, item_map=None, max_images=MAX_IMAGES, inv=None):
    """One or more requests per board; every part carries the images of its own rows."""
    if inv is None:
        inv = inventory(root)
    passages = {s: rule_passages(t) for s, t in (rules_text_by_section or {}).items() if t}
    by_board = {}
    for r in rows:
        # hidden rows (NOT_APPLICABLE) are reviewed too: "not applicable although the data are in the input" is a real error
        by_board.setdefault((r["section"], r["board"]), []).append(r)
    reqs = []
    for (sec, key), rs in by_board.items():
        parts, cur, imgs = [], [], []
        for r in rs:
            f = [x["path"] for x in r["figures"]]
            if cur and len(set(imgs + f)) > max_images:
                parts.append((cur, imgs)); cur, imgs = [], []
            cur.append(r); imgs = list(dict.fromkeys(imgs + f))
        if cur:
            parts.append((cur, imgs))
        for i, (prs, im) in enumerate(parts, 1):
            rules = {}
            for r in prs:
                if r["kind"] == "question":
                    # Earlier boards number the last five absorption endpoints differently.
                    legacy = {"Long tail and flip-flop": 6, "Extent of absorption (F)": 7, "Dose dependence": 8,
                              "Comparison across conditions": 9, "Individuals or averaging": 5}
                    question = legacy.get(r["label"], r["q"]) if sec == "absorption" and not item_map else r["q"]
                    rules.update(passages_for(sec, question, passages.get(sec, {}), item_map))
            exist = [p for p in im if (Path(root) / p).is_file()]
            here = {r["row_id"] for r in prs}
            by_id = {r["row_id"]: r for r in rs}
            # a hypothesis is reviewed with the rows it rests on: those that sit in another part travel as text only
            ctx = [{k: by_id[c].get(k) for k in ("row_id", "label", "status_code", "observed", "reach")}
                   for r in prs if r["kind"] == "hypothesis" for c in r.get("cites") or [] if c not in here and c in by_id]
            sp = species_key(rs[0].get("species"))
            used = set(rs[0].get("board_datasets") or []) | {v for row in rs for v in row.get("datasets") or []}
            inputs = [classify(x, rs[0], used) for x in (inv or {}).get(sp, [])]
            project_inputs = []
            if any(r.get("claim_scope") == "project" for r in prs):
                project_inputs = [{k: x.get(k) for k in ("dataset_id", "study_ids", "species_text", "role", "route", "matrix")}
                                  for sp2, bucket in (inv or {}).items() if sp2 != sp for x in bucket]
            payload = {"section": sec, "board": key, "part": f"{i}/{len(parts)}", "species": prs[0].get("species"),
                       "study": rs[0].get("study"), "arm": rs[0].get("arm"), "board_datasets": sorted(used),
                       "inputs_for_species": inputs, "project_context": project_inputs,
                       "rows": [_compact(r, set(exist)) for r in prs], "context_rows": ctx,
                       "rules": rules, "figures": [{"file": Path(p).name, "path": p, "sha256": hashlib.sha256((Path(root) / p).read_bytes()).hexdigest()} for p in exist],
                       "figures_not_found": [p for p in im if p not in exist]}
            reqs.append({"id": f"ERR-{sec}-{key}-{i}", "kind": "ERR", "prompt": ERR_PROMPT + "\nREQUEST\n" + json.dumps(payload, ensure_ascii=False),
                         "schema": ERR_SCHEMA, "images": exist, "payload": payload})
    return reqs


def _compact(r, sent=None):
    keep = ("row_id", "kind", "study", "species", "q", "label", "question", "status_code", "observed", "basis", "reach", "missing",
            "value_table", "evidence", "alternatives", "next_test", "checks", "source_ids", "cites", "claim_scope", "datasets", "row_sources", "endpoint_limit")
    out = {k: r.get(k) for k in keep if r.get(k) not in (None, [], "")}
    if not r.get("shown", True):
        out["hidden_on_page"] = True
    out["figures"] = [{"file": Path(f["path"]).name, "role": f["role"], "panel": f["panel"], "caption": f["caption"]}
                      for f in r["figures"] if sent is None or f["path"] in sent]
    lost = [Path(f["path"]).name for f in r["figures"] if sent is not None and f["path"] not in sent]
    if lost:
        out["figures_not_sent"] = lost      # cited by the row but the file is missing: the row cannot be CONFIRMED on them
    return out


def validate_err(out, req):
    """Host checks on one ERR answer. Returns (ok, problems)."""
    probs = []
    want = [r["row_id"] for r in req["payload"]["rows"]]
    if out.get("board") != req["payload"]["board"]:
        probs.append("answer belongs to a different board")
    got = [x.get("row_id") for x in out.get("rows", [])]
    for rid in want:
        n = got.count(rid)
        if n != 1:
            probs.append(f"{rid}: answered {n} times")
    for rid in set(got) - set(want):
        probs.append(f"{rid}: not in the request")
    files = {f["file"] for f in req["payload"]["figures"]}
    rules = set(req["payload"]["rules"])
    for x in out.get("rows", []):
        v = x.get("verdict")
        if v not in VERDICTS:
            probs.append(f"{x.get('row_id')}: verdict {v!r}")
        if v == "REVISE" and not any(i.get("smallest_correction") for i in x.get("issues", [])):
            probs.append(f"{x.get('row_id')}: REVISE without a correction")
        if v == "CONFIRMED" and any(i.get("type") != "DISPLAY" for i in x.get("issues", [])):
            probs.append(f"{x.get('row_id')}: CONFIRMED with a substantive issue")
        for f in x.get("checked_figures", []):
            if Path(f).name not in files:
                probs.append(f"{x.get('row_id')}: cites figure {f} that was not sent")
        for k in x.get("checked_rules", []):
            if str(k) not in rules:
                probs.append(f"{x.get('row_id')}: cites rule {k} that was not sent")
        for i in x.get("issues", []):
            if i.get("type") not in ISSUE_TYPES:
                probs.append(f"{x.get('row_id')}: issue type {i.get('type')!r}")
            ev = i.get("evidence") or {}
            if ev.get("figure") and Path(ev["figure"]).name not in files:
                probs.append(f"{x.get('row_id')}: issue cites figure {ev['figure']} that was not sent")
            if ev.get("rule") and str(ev["rule"]) not in rules:
                probs.append(f"{x.get('row_id')}: issue cites rule {ev['rule']} that was not sent")
        # a row with figures must have looked at at least one of them
        sent = next((r for r in req["payload"]["rows"] if r["row_id"] == x.get("row_id")), None)
        if sent and v == "REVISE":
            inv = req["payload"].get("inputs_for_species", [])
            if sent.get("claim_scope") == "project":
                inv = inv + req["payload"].get("project_context", [])
            for issue in x.get("issues", []):
                problem = scope_problem(issue, sent, inv)
                if problem:
                    probs.append(f"{sent['row_id']}: {problem}")
        if (sent and sent.get("figures") and v == "CONFIRMED" and not
                {Path(f).name for f in x.get("checked_figures", [])}.intersection(f["file"] for f in sent["figures"])):
            probs.append(f"{x.get('row_id')}: CONFIRMED without checking any of its figures")
        if sent and sent.get("figures_not_sent") and v == "CONFIRMED":
            probs.append(f"{x.get('row_id')}: CONFIRMED although cited figures were not sent ({', '.join(sent['figures_not_sent'][:3])})")
    return not probs, probs


# ---------------------------------------------------------------- ES: summary request

ES_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["species", "project_open_items"],
    "properties": {
        "species": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                    "required": ["species", "statements", "handoff"],
                    "properties": {
                        "species": {"type": "string"},
                        "statements": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                       "required": ["kind", "text", "cites", "strength"],
                                       "properties": {"kind": {"type": "string", "enum": ["FINDING", "LINK", "CONFLICT", "OPEN"]},
                                                      "text": {"type": "string"}, "cites": {"type": "array", "items": {"type": "string"}},
                                                      "strength": {"type": "string", "enum": ["ANSWERABLE", "PARTLY_ANSWERABLE", "NOT_ANSWERABLE_YET", "REVIEW_PENDING"]}}}},
                        "handoff": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                    "required": ["text", "cites"], "properties": {"text": {"type": "string"},
                                                                                  "cites": {"type": "array", "items": {"type": "string"}}}}}}}},
        "project_open_items": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["text", "cites"],
                               "properties": {"text": {"type": "string"}, "cites": {"type": "array", "items": {"type": "string"}}}}},
    },
}

ES_PROMPT = """You write the review summary of a pharmacokinetic EDA for a human reviewer. The three sections (absorption,
distribution, elimination) were computed by host code; each row below is one conclusion with its status, and each row
also carries the verdict of an independent re-review (CONFIRMED, REVISE, UNCERTAIN).

Per species, write at most 8 short statements:
- FINDING: the most important conclusions, at most one per section and question family.
- LINK: where two sections inform each other (for example absorption CL/F and the elimination window clearance; the
  distribution volume bound and the elimination window; dose readings in absorption and urine by dose).
- CONFLICT: where two rows disagree or cannot both hold.
- OPEN: the most useful missing measurement.
Then the hand-off items for modeling (the working hypotheses and what they rest on).

Hard rules: every statement cites the row_ids it rests on, only from this request. The 'strength' of a statement is the
lowest status among its cited rows; never write it stronger. A statement resting on a row whose re-review verdict is
REVISE or UNCERTAIN has strength REVIEW_PENDING and says so. Do not add numbers that are not in the cited rows. No new
interpretation, no mechanism, no prediction. Return JSON only.
"""


def es_request(rows, err_verdicts):
    items = []
    for r in rows:
        v = err_verdicts.get(r["row_id"], {"verdict": "NOT_REVIEWED"})
        if (not r.get("shown", True) or r["status_code"] == "NOT_APPLICABLE") and v.get("verdict") != "REVISE":
            continue      # a hidden row reaches the summary only when the re-review says its 'not applicable' is wrong
        items.append({"row_id": r["row_id"], "section": r["section"], "study": r["study"], "species": r["species"], "q": r["q"],
                      "label": r["label"], "status_code": r["status_code"], "observed": r["observed"], "reach": r.get("reach"),
                      "missing": r["missing"][:3], "rereview": v.get("verdict"), "rereview_issues": [i.get("what") for i in v.get("issues", [])][:3]})
    payload = {"rows": items, "species": sorted({r["species"] for r in items if r["species"]})}
    return {"id": "ES-project", "kind": "ES", "prompt": ES_PROMPT + "\nREQUEST\n" + json.dumps(payload, ensure_ascii=False),
            "schema": ES_SCHEMA, "images": [], "payload": payload}


def _strength_of(cites, rows_by_id, verdicts):
    ranks = []
    for c in cites:
        r = rows_by_id.get(c)
        if r is None:
            continue
        if verdicts.get(c, {}).get("verdict") in ("REVISE", "UNCERTAIN") or r["status_code"] == "REVIEW_PENDING":
            return "REVIEW_PENDING"
        ranks.append(STATUS_RANK.get(r["status_code"], 0))
    if not ranks:
        return None
    return {2: "ANSWERABLE", 1: "PARTLY_ANSWERABLE", 0: "NOT_ANSWERABLE_YET", -1: "NOT_ANSWERABLE_YET"}[min(ranks)]


def _numbers(text):
    return {re.sub(r"\.0+$", "", n) for n in re.findall(r"(?<![\w.])\d+(?:\.\d+)?", text or "")}


def validate_es(out, req, rows, verdicts):
    probs = []
    by_id = {r["row_id"]: r for r in rows}
    sent = {r["row_id"] for r in req["payload"]["rows"]}
    species_out = {s.get("species") for s in out.get("species", [])}
    for sp in req["payload"]["species"]:
        if sp not in species_out:
            probs.append(f"species {sp} missing from the summary")
    order = ["REVIEW_PENDING", "NOT_ANSWERABLE_YET", "PARTLY_ANSWERABLE", "ANSWERABLE"]
    for s in out.get("species", []):
        for st in s.get("statements", []) + s.get("handoff", []):
            cites = st.get("cites") or []
            if not cites:
                probs.append(f"{s.get('species')}: statement without citations: {st.get('text', '')[:60]}")
                continue
            bad = [c for c in cites if c not in sent]
            if bad:
                probs.append(f"{s.get('species')}: cites rows not in the request: {', '.join(bad)}")
            allowed = _strength_of(cites, by_id, verdicts)
            if "strength" in st and allowed and order.index(st["strength"]) > order.index(allowed):
                probs.append(f"{s.get('species')}: strength {st['strength']} above the cited rows ({allowed}): {st.get('text', '')[:60]}")
            if re.search(STRONG_WORDS, st.get("text", ""), re.I):
                probs.append(f"{s.get('species')}: wording beyond evidence: {st.get('text', '')[:60]}")
            src = set().union(*[_numbers(" ".join(str(by_id[c].get(k) or "") for k in ("observed", "basis", "reach")) + " " + json.dumps(by_id[c].get("value_table") or ""))
                                for c in cites if c in by_id]) if any(c in by_id for c in cites) else set()
            extra = {n for n in _numbers(st.get("text", "")) - src if len(n) > 1 or "." in n}
            if extra:
                probs.append(f"{s.get('species')}: numbers not in the cited rows ({', '.join(sorted(extra)[:5])}): {st.get('text', '')[:60]}")
    return not probs, probs


# ---------------------------------------------------------------- running

def run(root, generate=None, rules_paths=None, out_dir=None, write_requests=False, item_map=None, inject=0, seed=7,
        only=None, retries=1, summary=True, resume=False, max_rounds=None):
    """Build requests, call the model (if a generator is given), validate, and write review/review.json and review/index.html."""
    root = Path(root)
    out = Path(out_dir or root / "review")
    out.mkdir(parents=True, exist_ok=True)
    rows, meta = collect(root)
    truth = None
    if inject:      # measurement run: planted errors, the summary is skipped and the page says so
        rows, truth = inject_errors(rows, n=inject, seed=seed)
    rules = {s: Path(p).read_text(encoding="utf-8-sig") for s, p in (rules_paths or {}).items() if p and Path(p).is_file()}
    inv = inventory(root)
    reqs = err_requests(root, rows, rules, item_map, inv=inv)
    if only and str(only).startswith("@"):      # a file with one request id per line
        ids = [x.strip() for x in Path(str(only)[1:]).read_text(encoding="utf-8").splitlines() if x.strip()]
        only = "^(" + "|".join(re.escape(x) for x in ids) + ")$"
    if only:        # partial run (pilot): only the requests whose id matches; the summary is skipped
        reqs = [q for q in reqs if re.search(only, q["id"])]
        summary = False
    ans_dir = out / "answers"
    ans_dir.mkdir(exist_ok=True)
    record = {"version": VERSION, "sections": meta, "rules": {s: {"file": Path(p).name, "sha256": hashlib.sha256(Path(p).read_bytes()).hexdigest()}
                                                            for s, p in (rules_paths or {}).items() if p and Path(p).is_file()},
              "rows": len(rows), "coverage": coverage(rows, inv), "only": only, "err": [], "es": None}
    verdicts = {}
    current_rows = {r["row_id"]: r for r in rows}
    tables_path = root / "source_tables.json"
    tables = json.loads(tables_path.read_bytes()) if tables_path.is_file() else []
    if isinstance(tables, dict):
        tables = tables.get("datasets") or tables.get("tables") or []
    if write_requests:
        rq = out / "requests"
        rq.mkdir(exist_ok=True)
    for req in reqs:
        if req["payload"]["context_rows"]:
            for ctx in req["payload"]["context_rows"]:
                ctx.update({k: current_rows[ctx["row_id"]].get(k) for k in ctx})
            req["prompt"] = ERR_PROMPT + "\nREQUEST\n" + json.dumps(req["payload"], ensure_ascii=False)
        entry = {"id": req["id"], "rows": [r["row_id"] for r in req["payload"]["rows"]], "images": req["images"],
                 "figures_not_found": req["payload"]["figures_not_found"], "status": "NOT_RUN"}
        entry["host_findings"] = {r["row_id"]: issue for r in req["payload"]["rows"] if (issue := host_issue(r))}
        if write_requests:
            (rq / f"{req['id']}.prompt.txt").write_text(req["prompt"], encoding="utf-8")
            (rq / f"{req['id']}.schema.json").write_text(json.dumps(req["schema"], indent=1), encoding="utf-8")
            (rq / f"{req['id']}.images.json").write_text(json.dumps(req["images"], indent=1), encoding="utf-8")
        digest = hashlib.sha256(json.dumps([VERSION, req["prompt"], req["schema"]], ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        entry["request_sha256"] = digest
        saved = ans_dir / f"{req['id']}.{digest}.json"
        if generate or (resume and saved.is_file()):
            try:
                imgs = [str(root / p) for p in req["images"]]
                tries, prompt = 0, req["prompt"]
                while True:
                    if resume and saved.is_file() and tries == 0:
                        ans = json.loads(saved.read_text(encoding="utf-8"))
                        entry["resumed"] = True
                    else:
                        ans = generate(prompt, req["schema"], imgs)
                    tries += 1
                    ok, probs = validate_err(ans, req)
                    if ok or tries > retries or not generate:
                        break
                    # one more attempt with the reasons the host checks gave; the conclusions themselves are not changed
                    prompt = (req["prompt"] + "\n\nYOUR PREVIOUS ANSWER WAS REJECTED BY THE HOST CHECKS. Fix exactly these points and answer again:\n- "
                              + "\n- ".join(probs[:20]))
                effective = effective_answer(ans, req["payload"]["rows"]) if ok else ans
                entry.update(status="ACCEPTED" if ok else "REJECTED", problems=probs, answer=effective, attempts=tries,
                             raw_answer_file=str(saved.relative_to(out)))
                saved.write_text(json.dumps(ans, ensure_ascii=False, indent=1), encoding="utf-8")   # kept so a paid call is never lost
                if ok:
                    if truth is None:
                        loop, effective = rerun(req, effective, generate, validate_err, ERR_PROMPT, tables,
                                                imgs, max_rounds, ans_dir, resume)
                        entry.update(self_review=loop, answer=effective)
                        if loop["status"] == "PASSED":
                            for rid, changes in loop["updated_rows"].items():
                                current_rows[rid].update(changes)
                    for x in effective["rows"]:
                        verdicts[x["row_id"]] = x
            except Exception as exc:  # noqa: BLE001 - recorded
                entry.update(status="ERROR", problems=[repr(exc)])
        record["err"].append(entry)
    es = es_request(rows, verdicts)
    record["es"] = {"id": es["id"], "status": "NOT_RUN"}
    if write_requests:
        (out / "requests" / "ES-project.prompt.txt").write_text(es["prompt"], encoding="utf-8")
        (out / "requests" / "ES-project.schema.json").write_text(json.dumps(es["schema"], indent=1), encoding="utf-8")
    record["self_review"] = ("BENCHMARK" if truth is not None else "PASSED" if reqs and all(
        e.get("self_review", {}).get("status") == "PASSED" for e in record["err"]) else "PENDING")
    if generate and truth is None and summary and record["self_review"] == "PASSED":
        try:
            ans = generate(es["prompt"], es["schema"], [])
            ok, probs = validate_es(ans, es, rows, verdicts)
            record["es"].update(status="ACCEPTED" if ok else "REJECTED", problems=probs, answer=ans)
        except Exception as exc:  # noqa: BLE001
            record["es"].update(status="ERROR", problems=[repr(exc)])
    record["counts"] = _counts(record, rows, verdicts)
    if truth is not None:
        sent = {rid for e in record["err"] for rid in e["rows"]}
        truth_sent = {k: v for k, v in truth.items() if k in sent}
        record["injection"] = {"seed": seed, "truth": truth_sent, "score": score(truth_sent, verdicts) if (generate or resume) else None}
    (out / "review.json").write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "index.html").write_text(render_html(record, rows, verdicts), encoding="utf-8")
    return record


def _counts(record, rows, verdicts):
    sent = {rid for e in record["err"] for rid in e["rows"]}
    shown = [r for r in rows if r["row_id"] in sent]      # hidden NOT_APPLICABLE rows are reviewed as well; a pilot counts its own rows
    c = {"rows": len(shown), "requests": len(record["err"]), "accepted": sum(e["status"] == "ACCEPTED" for e in record["err"]),
         "rejected": sum(e["status"] == "REJECTED" for e in record["err"])}
    for v in VERDICTS:
        c[v.lower()] = sum(1 for x in verdicts.values() if x["verdict"] == v)
    c["not_reviewed"] = len(shown) - len(verdicts)
    return c


# ---------------------------------------------------------------- page

def _e(x):
    import html
    return html.escape(str(x if x is not None else ""))


def render_html(record, rows, verdicts):
    by_id = {r["row_id"]: r for r in rows}
    c = record["counts"]
    h = ['<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">',
         '<title>EDA review summary</title><style>body{font:15px/1.5 system-ui,sans-serif;margin:24px auto;max-width:1100px;padding:0 16px;color:#17364b;background:#f6f8fa}'
         'table{border-collapse:collapse;width:100%;font-size:13.5px}td,th{border-bottom:1px solid #e4eaf0;padding:6px;text-align:left;vertical-align:top}'
         '.panel{background:#fff;border:1px solid #e4eaf0;border-radius:12px;padding:16px 20px;margin:16px 0}.muted{color:#5b7083}'
         '.st{display:inline-block;padding:1px 8px;border-radius:9px;font-size:12px}.CONFIRMED{background:#dff3ea}.REVISE{background:#fde2e2}.UNCERTAIN{background:#fff1cc}'
         '.REVIEW_PENDING{background:#e8eef9}</style></head><body><main>',
         '<nav><a href="../report.html">← EDA report</a></nav><p class="muted">EDA review</p><h1>Review summary</h1>',
         f'<p class="muted">{c["rows"]} conclusions and hypotheses across absorption, distribution and elimination · {c["requests"]} review requests '
         f'({c["accepted"]} accepted, {c["rejected"]} rejected by the host checks) · {c.get("confirmed", 0)} confirmed, {c.get("revise", 0)} to revise, '
         f'{c.get("uncertain", 0)} uncertain, {c["not_reviewed"]} not reviewed · Human review pending</p>']
    h.append(f'<p>Self-review of the selected requests: <b>{_e(record["self_review"])}</b></p>')
    es = (record.get("es") or {})
    for entry in record["err"]:
        loop = entry.get("self_review", {})
        if loop.get("rounds") or loop.get("reason"):
            h.append(f'<details><summary>{_e(entry["id"])} · {_e(loop["status"])} · {len(loop["rounds"])} correction rounds</summary>')
            if loop.get("reason"):
                h.append(f'<p>{_e(loop["reason"])}</p>')
            for rid, updated in loop.get("updated_rows", {}).items():
                h.append(f'<p>{_e(rid)} · {_e(updated["status_code"])} · {_e(updated["observed"])}</p>')
            h.append('</details>')
    contradictions = [(rid, issue) for e in record["err"] if e.get("self_review", {}).get("status") != "PASSED"
                      for rid, issue in e.get("host_findings", {}).items()]
    if contradictions:
        h.append('<section class="panel"><h2>Deterministic status checks · human review required</h2><ul>' +
                 "".join(f'<li>{_e(rid)}: {_e(issue["what"])} {_e(issue["smallest_correction"])}</li>' for rid, issue in contradictions) +
                 '</ul></section>')
    if es.get("status") == "ACCEPTED":
        for s in es["answer"]["species"]:
            h.append(f'<section class="panel"><h2>{_e(s["species"])}</h2><table><tr><th>Kind</th><th>Statement</th><th>Strength</th><th>Rests on</th></tr>')
            for st in s["statements"]:
                h.append(f'<tr><td>{_e(st["kind"].lower())}</td><td>{_e(st["text"])}</td><td><span class="st {_e(st["strength"])}">{_e(st["strength"].replace("_", " ").lower())}</span></td>'
                         f'<td>{"<br>".join(_e(c) for c in st["cites"])}</td></tr>')
            h.append('</table>')
            if s["handoff"]:
                h.append('<h3>Hand-off to modeling</h3><ul>' + "".join(f'<li>{_e(x["text"])} <span class="muted">({_e(", ".join(x["cites"]))})</span></li>' for x in s["handoff"]) + '</ul>')
            h.append('</section>')
    else:
        h.append(f'<section class="panel"><h2>Summary</h2><p>Summary not available: {_e(es.get("status"))}. '
                 + _e("; ".join((es.get("problems") or [])[:5])) + '</p></section>')
    flagged = [(rid, v) for rid, v in verdicts.items() if v["verdict"] != "CONFIRMED"]
    h.append('<section class="panel"><h2>Re-review findings</h2>' + ('<table><tr><th>Row</th><th>Status</th><th>Verdict</th><th>Issue</th><th>Smallest correction</th></tr>' + "".join(
        f'<tr><td>{_e(rid)}</td><td>{_e(by_id.get(rid, {}).get("status_code"))}</td><td><span class="st {_e(v["verdict"])}">{_e(v["verdict"].lower())}</span></td>'
        f'<td>{"<br>".join(_e(i["type"].replace("_", " ").lower() + ": " + i["what"]) for i in v["issues"])}</td>'
        f'<td>{"<br>".join(_e(i["smallest_correction"]) for i in v["issues"])}</td></tr>' for rid, v in flagged) + '</table>' if flagged else
        '<p>No findings, or the re-review has not run.</p>') + '</section>')
    cov = record.get("coverage") or {}
    if cov.get("datasets"):
        un = cov.get("unused") or []
        h.append(f'<section class="panel"><h2>Input coverage</h2><p class="muted">{cov["datasets"]} input datasets · {len(un)} not used by any board</p>'
                 + ('<table><tr><th>Dataset</th><th>Species</th><th>Title</th><th>Regimen / condition</th></tr>' + "".join(
                     f'<tr><td>{_e(x.get("dataset_id"))}</td><td>{_e(x.get("species"))}</td><td>{_e(x.get("title"))}</td>'
                     f'<td>{_e(" · ".join(str(x[k]) for k in ("route", "dosing_regimen", "condition") if x.get(k)))}</td></tr>' for x in un) + '</table>'
                    if un else '<p>Every input dataset is used by at least one board.</p>') + '</section>')
    rej = [e for e in record["err"] if e["status"] in ("REJECTED", "ERROR")]
    if rej:
        h.append('<details class="panel"><summary>Re-review answers not accepted</summary><ul>' + "".join(
            f'<li>{_e(e["id"])}: {_e("; ".join(e.get("problems", [])[:4]))}</li>' for e in rej) + '</ul></details>')
    h.append(f'<footer class="muted">{_e(VERSION)} · revisions and review decisions are recorded in review.json.</footer></main></body></html>')
    return "".join(h)


# ---------------------------------------------------------------- error-injection harness (measuring ERR)

def inject_errors(rows, n=30, seed=7):
    """Copies of the rows with n planted errors of known type. Returns (rows, truth) where truth maps row_id -> type."""
    rng = random.Random(seed)
    rows = copy.deepcopy(rows)
    cands = [r for r in rows if r["kind"] == "question" and r.get("shown", True)]
    rng.shuffle(cands)
    truth = {}

    def bump_number(r):
        nums = re.findall(r"\d+\.\d+|\d{2,}", r["observed"] or "")
        if not nums:
            return False
        x = rng.choice(nums)
        new = f"{float(x) * rng.choice([2.0, 0.5, 10.0]):g}"
        r["observed"] = r["observed"].replace(x, new, 1)
        return True

    def raise_status(r):
        if r["status_code"] in ("PARTLY_ANSWERABLE", "NOT_ANSWERABLE_YET"):
            r["status_code"] = "ANSWERABLE"
            return True
        return False

    def drop_missing(r):
        if r["missing"]:
            r["missing"] = []
            return True
        return False

    def strong_word(r):
        r["observed"] = (r["observed"] or "").rstrip(".") + "; this establishes the mechanism."
        return True

    def swap_figure(r):
        others = [x for x in rows if x is not r and x["figures"] and x["section"] == r["section"] and x["board"] != r["board"]]
        if not r["figures"] or not others:
            return False
        r["figures"][0] = dict(r["figures"][0], path=rng.choice(others)["figures"][0]["path"])
        return True

    kinds = [("VALUE_ERROR", bump_number), ("STATUS_TOO_STRONG", raise_status), ("MISSING_INCOMPLETE", drop_missing),
             ("WORDING_BEYOND_EVIDENCE", strong_word), ("FIGURE_TEXT_MISMATCH", swap_figure)]
    i = 0
    for r in cands:
        if len(truth) >= n:
            break
        name, fn = kinds[i % len(kinds)]
        if fn(r):
            truth[r["row_id"]] = name
            i += 1
    return rows, truth


def score(truth, verdicts):
    """Catch rate on planted rows and flag rate on untouched rows."""
    hit = sum(1 for rid, t in truth.items() if verdicts.get(rid, {}).get("verdict") == "REVISE")
    typed = sum(1 for rid, t in truth.items() if any(i["type"] == t for i in verdicts.get(rid, {}).get("issues", [])))
    clean = [rid for rid in verdicts if rid not in truth]
    fa = sum(1 for rid in clean if verdicts[rid]["verdict"] == "REVISE")
    return {"planted": len(truth), "caught": hit, "caught_with_right_type": typed, "catch_rate": hit / len(truth) if truth else None,
            "clean_rows": len(clean), "flagged_clean": fa, "flag_rate_clean": fa / len(clean) if clean else None}


def score_known(benchmark, verdicts):
    """Score against known real errors (e.g. from a paper comparison). A group is caught when any of its rows gets REVISE.
    REVISE outside every group is listed for a human check: the comparison did not cover every row."""
    groups = benchmark["groups"]
    res, inside = [], set()
    for g in groups:
        inside.update(g["rows"])
        vs = {rid: verdicts.get(rid, {}) for rid in g["rows"]}
        rev = [rid for rid, v in vs.items() if v.get("verdict") == "REVISE"]
        typed = [rid for rid in rev if any(i.get("type") in g.get("expected_types", []) for i in vs[rid].get("issues", []))]
        res.append({"id": g["id"], "partial": bool(g.get("partial")), "caught": bool(rev), "caught_with_expected_type": bool(typed),
                    "uncertain": [rid for rid, v in vs.items() if v.get("verdict") == "UNCERTAIN"],
                    "not_reviewed": [rid for rid, v in vs.items() if not v]})
    full = [r for r in res if not r["partial"]]
    outside = sorted(rid for rid, v in verdicts.items() if rid not in inside and v.get("verdict") == "REVISE")
    return {"groups": res, "caught": sum(r["caught"] for r in full), "known": len(full),
            "caught_partial": sum(r["caught"] for r in res if r["partial"]), "revise_outside_known": outside,
            "reviewed_rows": len(verdicts)}


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="EDA re-review and summary requests (host side)")
    ap.add_argument("root", type=Path)
    ap.add_argument("--rules", nargs="*", default=[], help="section=path pairs, e.g. elimination=rules/EDA_elimination_...md")
    ap.add_argument("--write-requests", action="store_true")
    ap.add_argument("--inject", type=int, default=0, help="plant N known errors (measurement run; not a review)")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--only", default=None, help="regex on request ids (pilot run); skips the summary")
    ap.add_argument("--generate", default=None, help="module:function with signature (prompt, schema, image_paths) -> dict")
    ap.add_argument("--resume", action="store_true", help="reuse answers already saved under <out>/answers")
    ap.add_argument("--retries", type=int, default=1)
    ap.add_argument("--max-rounds", type=int, help="optional limit on correction rounds per request")
    ap.add_argument("--known", type=Path, default=None, help="known-error benchmark JSON; scores an existing review/review.json")
    a = ap.parse_args(argv)
    if a.max_rounds is not None and a.max_rounds < 0:
        ap.error("--max-rounds must be nonnegative")
    rules = dict(x.split("=", 1) for x in a.rules)
    if a.generate:
        for section, path in rules.items():
            if section not in SECTIONS or not Path(path).is_file():
                ap.error(f"unknown section or missing rule file: {section}={path}")
        if not rules:
            ap.error("supply the section's EDA rule files using --rules")
    if a.known:
        rv = json.loads((Path(a.out or a.root / "review") / "review.json").read_text(encoding="utf-8"))
        verdicts = {x["row_id"]: x for e in rv["err"] if e["status"] == "ACCEPTED" for x in e["answer"]["rows"]}
        print(json.dumps(score_known(json.loads(a.known.read_text(encoding="utf-8")), verdicts), ensure_ascii=False, indent=1))
        return
    gen = None
    if a.generate:
        import importlib
        mod, fn = a.generate.split(":", 1)
        gen = getattr(importlib.import_module(mod), fn)
    rec = run(a.root, gen, rules, out_dir=a.out, write_requests=a.write_requests, inject=a.inject, seed=a.seed, only=a.only,
              retries=a.retries, resume=a.resume, max_rounds=a.max_rounds)
    print(json.dumps(dict(rec["counts"], self_review=rec["self_review"])))
    if a.generate and rec["self_review"] == "PENDING":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
