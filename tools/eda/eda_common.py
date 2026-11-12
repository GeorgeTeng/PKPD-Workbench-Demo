"""Shared helpers for the three EDA modules and their runners.

* ``workspace()`` finds the project workspace independent of folder depth.
* ``design_of`` / ``board_design`` / ``board_id`` give every board one identity
  that is the same in absorption, distribution and elimination.
* ``hypothesis_v1`` builds the common hypothesis record.
* ``input_coverage`` lists which source tables each section's boards use.
* ``rules_entry`` / ``check_rules`` give the one rules version per section (rules/rules_manifest.json).
"""
import hashlib
import json
import os
import re
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_MARKERS = ("data", "deliverables", "outputs")


def workspace(start=None):
    """Return the project workspace: $EDA_WORKSPACE, else the nearest parent with data/, deliverables/ and outputs/."""
    env = os.environ.get("EDA_WORKSPACE")
    if env:
        return Path(env).resolve()
    here = Path(start or _HERE).resolve()
    for folder in (here, *here.parents):
        if all((folder / name).is_dir() for name in _MARKERS):
            return folder
    return _HERE.parents[1]


WORKSPACE = workspace()

# ---------------------------------------------------------------- rules version (one per section)
RULES_DIR = _HERE / "rules"
UNRECORDED = {"version": "unrecorded", "items": "", "file": None, "sha256": None}


# Page wording for EDA004. Slopes and the named dose and slope tests are log-linear regressions on observed points,
# so "no fitting" alone would be wrong; no PK model is fitted and nothing is extrapolated.
FIT_NOTE = "no PK model fitted; any slope or named test shown is a descriptive regression"


def rules_manifest(folder=None):
    path = Path(folder or RULES_DIR) / "rules_manifest.json"
    return json.loads(path.read_text(encoding="utf-8"))


def rules_entry(section, folder=None):
    """The rules version this code implements for a section. A copy without its rules folder reports 'unrecorded'."""
    try:
        return dict(rules_manifest(folder)["sections"][section])
    except (OSError, KeyError, ValueError):
        return dict(UNRECORDED)


def rules_label(section, folder=None):
    return "rules " + rules_entry(section, folder)["version"]


def check_rules(folder=None):
    """Problems with the rules folder: a missing file or a file whose SHA-256 differs from the manifest."""
    folder = Path(folder or RULES_DIR)
    try:
        sections = rules_manifest(folder)["sections"]
    except (OSError, KeyError, ValueError) as exc:
        return [f"rules manifest unreadable in {folder}: {exc}"]
    if not isinstance(sections, dict):
        return ["rules manifest sections must be an object"]
    problems = [f"{s}: section missing from rules manifest" for s in ("absorption", "distribution", "elimination") if s not in sections]
    for section, entry in sections.items():
        if not isinstance(entry, dict) or not isinstance(entry.get("file"), str) or not entry.get("sha256"):
            problems.append(f"{section}: incomplete rule binding")
            continue
        path = folder / entry["file"]
        if not path.is_file():
            problems.append(f"{section}: {entry['file']} is missing")
        elif hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
            problems.append(f"{section}: {entry['file']} differs from the manifest SHA-256")
    return problems

# ---------------------------------------------------------------- board identity
SINGLE = "SINGLE"
REPEAT = "REPEAT"
LOADING_PLUS_INFUSION = "LOADING_PLUS_INFUSION"
INFUSION = "INFUSION"
IN_VITRO = "IN_VITRO"
EXCRETA = "EXCRETA"
REPORTED = "REPORTED"
DESIGNS = (SINGLE, REPEAT, LOADING_PLUS_INFUSION, INFUSION, IN_VITRO, EXCRETA, REPORTED)
# Ordering used when a board mixes designs: the most specific design wins the board's label.
_PRECEDENCE = {LOADING_PLUS_INFUSION: 0, INFUSION: 1, REPEAT: 2, IN_VITRO: 3, EXCRETA: 4, SINGLE: 5, REPORTED: 6}
_EXCRETA_ROLES = {"URINE_EXCRETION", "FECES_EXCRETION", "BILE_EXCRETION", "MASS_BALANCE", "EXCRETION"}
_IN_VITRO_ROLES = {"BINDING", "IN_VITRO", "METABOLISM_IN_VITRO", "BLOOD_PLASMA_RATIO"}
_OCCASION = re.compile(r"\bday\s*(\d+)\s*of\s*(\d+)\b", re.I)


def _text(*values):
    return " ".join(str(v) for v in values if v not in (None, "")).lower()


def design_of(table):
    """Design of one source table from its role, route and dosing_regimen."""
    md = table.get("metadata") or {}
    role = str(table.get("role") or "").upper()
    if role in _EXCRETA_ROLES:
        return EXCRETA
    if role in _IN_VITRO_ROLES or str(md.get("origin") or "").upper() == "IN_VITRO":
        return IN_VITRO
    regimen = _text(md.get("dosing_regimen"), md.get("regimen"), md.get("route_detail"))
    route = _text(md.get("route"), md.get("route_class"), md.get("route_detail"))
    if "loading" in regimen and "infusion" in regimen:
        return LOADING_PLUS_INFUSION
    if ("continuous" in regimen and "infusion" in regimen) or "continuous infusion" in route:
        return INFUSION
    occasion = _OCCASION.search(regimen)
    if occasion and int(occasion.group(2)) > 1:
        return REPEAT
    if re.search(r"\b(daily|repeat(ed)?|multiple|q\d+h|b\.?i\.?d|t\.?i\.?d|for \d+ days|once a day|twice)\b", regimen):
        return REPEAT
    return SINGLE


def board_design(tables):
    """Design label of a board from the source tables it uses.

    One design → that design.  Several → the designs joined with "+" in a fixed
    order, so a repeat-dose or infusion table can never sit on a board that is
    labelled SINGLE.  Excreta and in-vitro tables label a board only when it has
    no in-vivo dosing design of its own (urine beside a single-dose plasma curve
    stays a SINGLE board).
    """
    designs = {design_of(t) for t in tables if t is not None}
    if designs - {EXCRETA, IN_VITRO}:
        designs -= {EXCRETA, IN_VITRO}
    designs = sorted(designs, key=_PRECEDENCE.get)
    if not designs:
        return SINGLE
    return "+".join(designs)


def _slug(value):
    return re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-") or "na"


def board_id(study, species_group, design, qualifier=None):
    """One identity for the same experiment in all three sections: study/species/design[/qualifier]."""
    parts = [_slug(study), _slug(species_group), _slug(design)]
    if qualifier:
        parts.append(_slug(qualifier))
    return "/".join(parts)


def species_group_of(value):
    text = str(value or "").strip()
    return text[:1].upper() + text[1:].lower() if text else ""


def annotate_board(board, tables_by_id, dataset_ids, study=None, species=None, qualifier=None):
    """Add board_id and design to a board in place; existing keys stay unchanged."""
    used = [tables_by_id[i] for i in dataset_ids if i in tables_by_id]
    design = board_design(used)
    group = species_group_of(board.get("species_group") or species or board.get("species"))
    board["design"] = design
    board["board_id"] = board_id(study or board.get("study"), group, design, qualifier)
    return board


def disambiguate(boards):
    """Give boards that still share a board_id a qualifier from their own scope labels."""
    seen = {}
    for b in boards:
        seen.setdefault(b["board_id"], []).append(b)
    for bid, same in seen.items():
        if len(same) < 2:
            continue
        for b in same:
            label = b.get("experiment_arm") or b.get("cohort") or b.get("regimen") or b.get("scope_key") or b.get("key")
            b["board_id"] = bid + "/" + _slug(label)
        # Still identical (no distinguishing label): number them in their output order.
        again = {}
        for b in same:
            again.setdefault(b["board_id"], []).append(b)
        for bid2, rest in again.items():
            if len(rest) > 1:
                for n, b in enumerate(rest, 1):
                    b["board_id"] = f"{bid2}/{n}"
    return boards


def table_index(tables):
    return {t.get("dataset_id"): t for t in tables or [] if isinstance(t, dict) and t.get("dataset_id")}


# --------------------------------------------------------------- hypothesis v1
HYPOTHESIS_V1_FIELDS = ("id", "section", "board_id", "text", "observation", "candidates", "alternatives",
                        "next_test", "rests_on", "missing", "checks", "state", "sha256")


def _strs(values):
    out = []
    for v in values or []:
        if v in (None, ""):
            continue
        if isinstance(v, dict):
            v = v.get("text") or v.get("label") or v.get("name") or json.dumps(v, ensure_ascii=False, sort_keys=True)
        out.append(str(v))
    return out


def hypothesis_v1(section, board_id_value, *, text, observation, candidates, alternatives, next_test,
                  question_numbers, missing, checks, state):
    """Common hypothesis record; sha256 covers every other field."""
    cands = []
    for c in candidates or []:
        if isinstance(c, dict):
            cands.append({"name": str(c.get("name") or ""),
                          "extra_parameters": [str(x) for x in (c.get("extra_parameters") or [])],
                          "must_show": str(c.get("must_show") or "")})
        else:
            cands.append({"name": str(c), "extra_parameters": [], "must_show": ""})
    record = {
        "id": f"{section}:{board_id_value}:H1",
        "section": section,
        "board_id": board_id_value,
        "text": str(text or ""),
        "observation": str(observation or ""),
        "candidates": cands,
        "alternatives": _strs(alternatives),
        "next_test": str(next_test or ""),
        "rests_on": [f"{section}:{board_id_value}:Q{n}" for n in question_numbers],
        "missing": _strs(missing),
        "checks": _strs(checks),
        "state": str(state or ""),
    }
    record["sha256"] = hashlib.sha256(json.dumps(record, sort_keys=True, ensure_ascii=False).encode("utf8")).hexdigest()
    return record


def question_number(question, index):
    """Q number of a board question: its own numeric id when it has one, else its position (1-based)."""
    for key in ("q", "number", "n", "qid", "id"):
        value = question.get(key) if isinstance(question, dict) else None
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            m = re.search(r"(\d+)", value)
            if m:
                return int(m.group(1))
    return index + 1


_ITEM = re.compile(r"\b(item\s?\d+[a-z]?|EM-\d+[a-z]?|DIS\d+[a-z]?)\b", re.I)


def rests_on_questions(questions, rests_text="", source_ids=(), explicit=None):
    """Q numbers a hypothesis rests on.

    Explicit numbers (absorption brief.qs) win; otherwise Qn written in the text, then
    the board rows whose evidence cites the same item codes or source table IDs.
    """
    numbers = [question_number(q, i) for i, q in enumerate(questions or [])]
    if explicit:
        return [int(n) for n in explicit]
    text = str(rests_text or "")
    direct = [int(n) for n in re.findall(r"\bQ(\d+)\b", text)]
    if direct:
        return list(dict.fromkeys(n for n in direct if n in numbers))
    codes = {re.sub(r"\s+", " ", c.lower()) for c in _ITEM.findall(text)}
    ids = {s for s in source_ids or [] if s}
    found = []
    for q, n in zip(questions or [], numbers):
        blob = json.dumps(q.get("evidence") or [], ensure_ascii=False)
        low = re.sub(r"\s+", " ", blob.lower())
        hit = any(re.search(r"\b" + re.escape(c) + r"\b", low) for c in codes)
        hit = hit or any(i in blob for i in ids)
        if hit:
            found.append(n)
    return found


def _ladder_candidates(rows, with_params):
    out = []
    for row in rows or []:
        row = [str(x) for x in row]
        if not row:
            continue
        name = f"{row[0]}: {row[1]}" if len(row) > 1 else row[0]
        if with_params:
            extra = [] if len(row) < 3 or row[2] in ("—", "-", "") else [row[2]]
            must = row[3] if len(row) > 3 else ""
        else:
            extra, must = [], row[2] if len(row) > 2 else ""
        out.append({"name": name, "extra_parameters": extra, "must_show": must})
    return out


def _alt_names(candidates):
    return [c["name"].split(": ", 1)[-1] for c in candidates if c["name"].startswith("Alt")]


def hypothesis_v1_for(section, board, bid):
    """Fill hypothesis_v1 from a section's own hypothesis fields (the old 'hypothesis' stays as an alias)."""
    h = board.get("hypothesis")
    if not isinstance(h, dict):
        return None
    questions = board.get("questions") or []
    if section == "absorption":
        primary = h.get("primary") or {}
        rows = primary.get("rows") if (primary.get("head") or [None])[0] == "Step" else []
        candidates = _ladder_candidates(rows, True)
        brief = h.get("brief") or {}
        alternatives = _alt_names(candidates) + _strs(h.get("alternatives"))
        alternatives += [" or ".join(map(str, pair)) for pair in brief.get("either") or [] if pair]
        alternatives += _strs(brief.get("deferred")) + _strs(brief.get("readings"))
        nxt = brief.get("next")
        next_test = (f"{nxt[0]}: {nxt[1]} ({nxt[2]})" if isinstance(nxt, list) and len(nxt) >= 3 else
                     " ".join(map(str, nxt)) if isinstance(nxt, list) else str(nxt or ""))
        if not next_test:
            steps = [c for c in candidates if not c["name"].startswith(("M0", "Alt"))]
            if steps:
                next_test = f"{steps[0]['name']}; the fit has to show {steps[0]['must_show']}"
            elif h.get("checks_before_modelling"):
                first = h["checks_before_modelling"][0]
                next_test = first.get("text") if isinstance(first, dict) else str(first)
        checks = [c.get("text") if isinstance(c, dict) else c for c in h.get("checks_before_modelling") or []]
        checks += [c.get("detail") or c.get("check") for c in h.get("checks") or []
                   if isinstance(c, dict) and c.get("result") not in (None, "PASS")]
        rests = rests_on_questions(questions, h.get("rests_on"), explicit=brief.get("qs"))
        observation = re.sub(r"^(This rests on|The observations remain descriptive:)\s*", "", str(h.get("rests_on") or ""))
        return hypothesis_v1(section, bid, text=h.get("text"), observation=observation, candidates=candidates,
                             alternatives=list(dict.fromkeys(a for a in alternatives if a)), next_test=next_test,
                             question_numbers=rests, missing=h.get("missing"), checks=checks, state=h.get("state"))
    if section == "distribution":
        candidates = _ladder_candidates(h.get("ladder"), False)
        steps = [c for c in candidates if not c["name"].startswith(("M0", "Alt"))]
        next_test = (h.get("check_first") or [None])[0] or (
            f"{steps[0]['name']}; the fit has to show {steps[0]['must_show']}" if steps else "")
        observation = " ".join(f"{l.get('label')}: {l.get('text')}" for l in h.get("lines") or [] if isinstance(l, dict))
        ids = board.get("datasets") or []
        rests = rests_on_questions(questions, h.get("rests_on"), source_ids=ids)
        return hypothesis_v1(section, bid, text=h.get("text"), observation=observation or h.get("text"),
                             candidates=candidates, alternatives=_alt_names(candidates), next_test=next_test,
                             question_numbers=rests, missing=h.get("missing"), checks=h.get("check_first"),
                             state=h.get("state"))
    # elimination
    kind = str(h.get("kind") or "")
    state = h.get("state") or ("PENDING" if "pending" in kind.lower() else kind.upper())
    rests = rests_on_questions(questions, h.get("rests_on"), source_ids=h.get("source_ids"))
    alternatives = [h["alternative"]] if h.get("alternative") else []
    return hypothesis_v1(section, bid, text=h.get("text"), observation=h.get("observation"), candidates=[],
                         alternatives=alternatives, next_test=h.get("next_test"), question_numbers=rests,
                         missing=h.get("missing"), checks=h.get("check_first"), state=state)


def annotate_section(section, result, root):
    """Add board_id, design and hypothesis_v1 to every board of one section result, in place."""
    tables = json.loads((Path(root) / "source_tables.json").read_text(encoding="utf-8-sig"))
    by_id = table_index(tables)
    boards = result.get(BOARD_LIST[section]) or []
    for b in boards:
        qualifier = (b.get("experiment_arm") or b.get("cohort")) if section == "absorption" else None
        annotate_board(b, by_id, b.get("datasets") or [], qualifier=qualifier)
    disambiguate(boards)
    for b in boards:
        v1 = hypothesis_v1_for(section, b, b["board_id"])
        if v1 is not None:
            b["hypothesis_v1"] = v1
    return boards


# --------------------------------------------------------------- input coverage
SECTIONS = ("absorption", "distribution", "elimination")
BOARD_LIST = {"absorption": "status_boards", "distribution": "boards", "elimination": "boards"}
# Roles each section has questions for.
SECTION_ROLES = {
    "absorption": {"PK_OBSERVATIONS", "REPORTED_PARAMETERS"},
    "distribution": {"PK_OBSERVATIONS", "REPORTED_PARAMETERS", "BINDING", "TISSUE_DISTRIBUTION"},
    "elimination": {"PK_OBSERVATIONS", "REPORTED_PARAMETERS", "URINE_EXCRETION", "FECES_EXCRETION",
                    "BILE_EXCRETION", "MASS_BALANCE", "EXCRETION", "METABOLISM_IN_VITRO", "IN_VITRO"},
}
REASONS = ("NOT_PK_ROLE", "NO_QUESTION_FOR_TYPE", "GATED_OUT", "DESIGN_NOT_SUPPORTED", "UNKNOWN")
STRUCTURAL_REASONS = ("NOT_PK_ROLE", "NO_QUESTION_FOR_TYPE")


def _skip_reason(result, dataset_id):
    """Gate named by a module's own 'skipped' list for this dataset, if any."""
    skipped = result.get("skipped") or []
    if isinstance(skipped, dict):
        skipped = [dict(v, dataset_id=k) if isinstance(v, dict) else {"dataset_id": k, "reason": v}
                   for k, v in skipped.items()]
    for row in skipped:
        if not isinstance(row, dict):
            continue
        ident = row.get("dataset_id") or row.get("id") or row.get("dataset")
        if ident == dataset_id:
            gate = row.get("gate") or row.get("reason") or row.get("code") or "SKIPPED"
            return _slug(gate).upper().replace("-", "_")[:60]
    return None


def _mentions(obj, ids, found):
    if isinstance(obj, dict):
        for v in obj.values():
            _mentions(v, ids, found)
    elif isinstance(obj, list):
        for v in obj:
            _mentions(v, ids, found)
    elif isinstance(obj, str) and obj in ids:
        found.add(obj)
    return found


def _type_supported(section, table):
    md = table.get("metadata") or {}
    route_class = str(md.get("route_class") or "").upper()
    category = str(md.get("matrix_category") or "").upper()
    matrix = str(md.get("matrix") or "").upper()
    if section == "absorption":
        # Absorption boards are extravascular inputs; IV curves serve only as module-level references.
        return route_class != "IV"
    if section == "elimination" and table.get("role") in ("PK_OBSERVATIONS", None):
        # Elimination reads systemic plasma/serum/blood; tissue and CSF concentrations have no elimination row.
        return category in ("", "PLASMA_SERUM_BLOOD") and "CSF" not in matrix
    return True


def _assay_gate(section, result, table):
    """Elimination reads parent drug; a non-specific assay (config or metadata) keeps a table off its boards."""
    if section != "elimination":
        return None
    md = table.get("metadata") or {}
    assay = str(md.get("assay") or "").upper()
    rule = ((result.get("config_used") or {}).get("assay_by_dataset") or {}).get(table.get("dataset_id"))
    if isinstance(rule, dict) and rule.get("assay"):
        assay = str(rule["assay"]).upper()
    role = str(md.get("analyte_role") or "").upper()
    if assay and assay not in ("SPECIFIC", "SELECTIVE", "LC-MS/MS", "HPLC"):
        return "ASSAY_" + _slug(assay).upper().replace("-", "_")
    if role and role not in ("PARENT",) and table.get("role") == "PK_OBSERVATIONS":
        return "ANALYTE_" + role
    return None


def _design_on_boards(section, result, table, by_id):
    """True when some board of the same study and species in this section already carries the table's design."""
    md = table.get("metadata") or {}
    studies = set(table.get("study_source_ids") or [])
    species = species_group_of(md.get("species")).lower()
    design = design_of(table)
    peers = [b for b in result.get(BOARD_LIST[section]) or []
             if species_group_of(b.get("species_group") or b.get("species")).lower() == species
             and (not studies or b.get("study") in studies)]
    if not peers:
        return True  # no board for this study/species at all: not a design question
    for b in peers:
        designs = {design_of(by_id[i]) for i in b.get("datasets") or [] if i in by_id}
        if design in designs:
            return True
    return False


def _section_unused_reason(section, result, table, by_id):
    role = str(table.get("role") or "").upper()
    if role not in SECTION_ROLES[section]:
        return "NOT_PK_ROLE"
    gate = _skip_reason(result, table.get("dataset_id"))
    if gate:
        return "GATED_OUT:" + gate
    if not _type_supported(section, table):
        return "NO_QUESTION_FOR_TYPE"
    gate = _assay_gate(section, result, table)
    if gate:
        return "GATED_OUT:" + gate
    design = design_of(table)
    if section == "absorption" and design in (LOADING_PLUS_INFUSION, INFUSION):
        return "DESIGN_NOT_SUPPORTED"
    if not _design_on_boards(section, result, table, by_id):
        return "DESIGN_NOT_SUPPORTED"
    return "UNKNOWN"


def input_coverage(tables, results):
    """coverage.json body: per dataset, the boards that use it in each section or an unused reason."""
    ids = [t.get("dataset_id") for t in tables if isinstance(t, dict) and t.get("dataset_id")]
    by_id = table_index(tables)
    datasets = []
    for dataset_id in ids:
        table = by_id[dataset_id]
        md = table.get("metadata") or {}
        entry = {"dataset_id": dataset_id, "role": table.get("role"), "design": design_of(table),
                 "species": md.get("species"), "route": md.get("route"),
                 "dosing_regimen": md.get("dosing_regimen"), "sections": {}}
        for section in SECTIONS:
            result = results.get(section)
            if result is None:
                entry["sections"][section] = {"status": "unused", "reason": "UNKNOWN", "detail": "section not run"}
                continue
            boards = [b for b in result.get(BOARD_LIST[section]) or [] if dataset_id in (b.get("datasets") or [])]
            if boards:
                entry["sections"][section] = {"status": "used",
                                              "boards": [b.get("board_id") or b.get("key") or b.get("study") for b in boards]}
                continue
            outside = bool(_mentions({k: v for k, v in result.items() if k != BOARD_LIST[section]}, {dataset_id}, set()))
            row = {"status": "unused", "reason": _section_unused_reason(section, result, table, by_id)}
            if outside:
                row["referenced_outside_boards"] = True
            entry["sections"][section] = row
        used_any = any(s["status"] == "used" for s in entry["sections"].values())
        entry["status"] = "used" if used_any else "unused"
        datasets.append(entry)
    summary = {
        "datasets": len(datasets),
        "used_any_section": sum(d["status"] == "used" for d in datasets),
        "unused_all_sections": [d["dataset_id"] for d in datasets if d["status"] == "unused"],
        "unused_by_section": {s: {d["dataset_id"]: d["sections"][s]["reason"] for d in datasets
                                  if d["sections"][s]["status"] == "unused"} for s in SECTIONS},
    }
    return {"version": "EDA_INPUT_COVERAGE_1", "reason_codes": list(REASONS), "summary": summary, "datasets": datasets}


def write_coverage(out):
    """Write <out>/coverage.json from the run's source tables and the three section JSON files."""
    out = Path(out)
    tables = json.loads((out / "source_tables.json").read_text(encoding="utf8"))
    results = {}
    for section in SECTIONS:
        path = out / section / (section + ".json")
        if path.is_file():
            results[section] = json.loads(path.read_text(encoding="utf8"))
    body = input_coverage(tables, results)
    (out / "coverage.json").write_text(json.dumps(body, indent=2, ensure_ascii=False), encoding="utf8")
    return body


def coverage_table_html(coverage):
    """Short 'Input coverage' table for the portal overview: unused datasets only."""
    from html import escape
    rows = []
    structural = 0
    for d in coverage["datasets"]:
        unused = [(s, d["sections"][s]["reason"]) for s in SECTIONS if d["sections"][s]["status"] == "unused"]
        if not unused:
            continue
        # A role or type a section has no question for is expected; list it only when no section uses the table.
        notable = [(s, r) for s, r in unused if r not in STRUCTURAL_REASONS]
        if d["status"] == "used" and not notable:
            structural += 1
            continue
        unused = unused if d["status"] == "unused" else notable
        used = [s for s in SECTIONS if d["sections"][s]["status"] == "used"]
        rows.append("<tr><td><code>{}</code></td><td>{}</td><td>{}</td><td>{}</td></tr>".format(
            escape(d["dataset_id"]), escape(str(d.get("role") or "")),
            escape(", ".join(used) or "none"),
            "<br>".join(escape(f"{s}: {r}") for s, r in unused)))
    summary = coverage["summary"]
    intro = (f'{summary["datasets"]} input tables, {summary["used_any_section"]} used by at least one board. '
             f'{structural} of them are left out of some sections only because that section has no question for their '
             'role or type (NOT_PK_ROLE, NO_QUESTION_FOR_TYPE); all reasons are in '
             '<a href="coverage.json">coverage.json</a>.')
    if not rows:
        body = "<p>No input table is unused for any other reason.</p>"
    else:
        body = ("<table class=\"coverage tbl\"><thead><tr><th>Dataset</th><th>Role</th><th>Used in</th>"
                "<th>Not used (reason)</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table>")
    return '<section id="input-coverage"><h2>Input coverage</h2><p>' + intro + "</p>" + body + "</section>"
