# Scientific extraction: A / B / C

## Runtime scope

Active for newly initialized compression runs under CC rules 1.16.0. Existing
runs retain their snapshotted rules. No historical approval is silently upgraded.
This changes compression and its handoff consumers, not scientific fitting,
human translation, target determination or PTA execution adapters.

The existing LangGraph → Prefect → Snakemake compression adapter continues to
call `ctxcomp.providers.run_model`. Each model call receives its own complete
request, scoped rules, sources and schema. There is no new classification call.

## A — Meaning before shortening

The existing retention inventory now uses version 1.1. Each source proposition
has a `science` object:

| Field | Meaning |
|---|---|
| `role` | FACT, RESULT, HYPOTHESIS, ASSUMPTION, METHOD, IMPLICATION, OBJECTIVE, REQUIREMENT, OTHER or UNRESOLVED |
| `evidence_status` | OBSERVED, ESTIMATED, PREDICTED, SOURCE_REPORTED, ASSUMED, NOT_APPLICABLE, NOT_FOUND or UNRESOLVED |
| `method_refs` | Explicit links to METHOD inventory items |
| `bindings` | Original attribute values with source component IDs |
| `adoption_relations` | Source-supported adoption/use, purpose, conditions and evidence |
| `relations` | Source-supported USES, TESTS, SUPPORTS, CONTRADICTS or INTERPRETS links |

For example, a human CL prediction is RESULT + PREDICTED, not an observed human
fact. Role is distinct from the legacy FACT/UNKNOWN inventory bookkeeping and
EXPLICIT/PROPOSED/NOT_FOUND attribution on compact-context fields.

Only source-explicit or source-adopted premises may be ASSUMPTION + ASSUMED.
Inferred premises stay in `potential_questions`, with MODEL_INFERENCE,
PENDING_CONFIRMATION, cited rationale, needed_at and impact. A correctly retained
pending question can pass compression; it has not become an approved assumption.
A REQUIREMENT discourse label does not publish a project rule. The separate
Project Rules Agent rereads original project materials and owns that publication.

## B — Review the exact deliverable

```text
Permitted proposal and supporting passages
→ proposition inventory with A/C metadata
→ independent source-to-inventory review
→ compact core context + deterministic scientific_context projection
→ faithfulness review || completeness review
→ global conflict review
→ main.json 3.2
```

The core model-generated context remains version 3.0. The host constructs the
additional scientific_context from the inventory, shows that exact object to
all final reviewers, and copies it unchanged into main.json 3.2 after PASS.
The compact scientific_context 2.0 keeps statements, role/status, method links,
semantic relationships, adoption conditions and pending questions. Quotes,
bindings, component IDs, original-source links and character offsets stay in
the inventory and audit/scientific_context.json. The audit records the reviewed
request hash and published main hash; it is not required downstream context.
Data-file references and the separately published project-rule reference remain
available for execution. Reviewers compare the actual compact output with the
inventory and originals. Critical meaning present only in a removed binding is
an omission and must fail review. No semantic rewriting occurs after review.

Faithfulness and completeness each return one `scientific_checks` verdict per
scientific item and inferred question. A missing item or contradictory PASS is
rejected. A failed branch cannot be overridden by global PASS. Global review
checks conflicts across both representations and the full original sources.
Historical main.json 3.0/3.1 remains readable; new runs require the 3.2 extension.

### Private binding extraction contract

`binding.value` is one continuous verbatim excerpt of the cited source of a
selected component of the same item (contract 1.1): a verified quotation, the rest
of its line or source unit, or for a spreadsheet row another cell of that row, the
sheet name or a column header above the cited cell. Values found outside the quote
are listed in `outside_quote` with their location so that reviews can check the
pairing. Compressed or combined meaning belongs
in `statement`. Separate independently located values into separate bindings;
preserve their relationships, conditions, units and negations. Do not repair by
fuzzy matching or automatically approving rewritten values.

`MODEL_BINDING_INVALID` reports all affected items, fields, JSON paths, submitted
values, source excerpts and correction instructions. Failed responses remain
immutable. New runs permit one fresh `binding_repair` invocation for exact-excerpt
or empty-value failures, before accepting the inventory. Only flagged bindings
may change, using the original field and selected source components; statements,
evidence, roles, statuses and unflagged bindings remain unchanged. Separate exact
excerpts can replace a combined value. The full repaired candidate is validated
and still requires inventory, faithfulness, completeness and conflict review.
Unresolvable meaning, invalid repair output or a second binding failure stops
the workflow; there is no retry loop. Requests, original/corrected responses and
diagnosis remain in `audit/binding_repairs`. Existing failed runs are not resumed
automatically. Error counts are not counts of proven scientific errors.

## C — PK knowledge supports binding, not inference

`rules/compression/pk_binding_knowledge.json` version 2.0.0 has eight English
groups, ordered by scientific task: dose input/absorption; concentration/exposure;
distribution/elimination; free/total/tissue exposure; model structure/estimation;
evaluation/uncertainty; animal-to-human translation; PK/PD handoff. The last three
are conditional extensions, not required analyses. There are 41 concept families;
related quantities are distinguished, with true aliases stored at one location.

Species and study descriptors occupy one short supporting metadata line, without
animal-name lists. Two data-qualifier notes preserve experimental units and assay
missingness. Role/status and general logic refer to their existing profiles.
See [PK terminology review](PK_TERMINOLOGY_REVIEW.md) for the full English tables,
deduplication decisions and literature reading scope. This reorganization does
not relax the 13 CC005 preservation categories or remove source-specific facts.
CC005 now maps these categories to its terminology appendix. See the integrated
[CC005 review](CC005_REVIEW.md) and [merged rule overview](COMPRESSION_RULES_REVIEW.md).

These are prompts for reading the evidence, not lookup rules assigning labels.
Review the complete study/analysis-specific tuple. A quotation containing all
words is insufficient when they belong to different doses, animals or analyses.
Unknown associations remain unresolved. Never normalize values, import parameter
values, impose biological thresholds or infer permissions from the glossary.
All 13 detailed CC005 preservation categories remain applicable.

## Handoff and downstream handling

- Compression still publishes one downstream JSON, main.json, with original files
  referenced in data.files. Scientific metadata does not grant fitting readiness.
- Formal rules remain in project_rules.json. The Rules Agent receives the typed
  compression evidence but rechecks original sources for authority.
- Adequacy receives complete scientific records. Its checklist covers each record
  once rather than treating provenance hashes/offsets as separate data needs.
- Routing carries records explicitly cited by reviewed tasks/requirements, plus
  their referenced methods and premises. It keeps a hash-bound source reference.
  Uncited records are not assigned by guessed keyword or filename relevance;
  routing review must inspect incomplete task evidence.
- References may propose append-only advice; they do not rewrite the reviewed
  scientific_context or silently convert questions into facts.

## Validation limits

Structural tests check schemas, source spans, reference integrity, missing review
items, failed-verdict gates, immutable publication and downstream compatibility.
Authored semantic defects test whether recorded failures block release. They do
not show that a real model detects every defect. The accepted standard remains
zero unblocked critical errors in an agreed acceptance set, not zero real-world
error. A full document benchmark remains deferred for insufficient labelled data.

No model-call timeout or output-length cap was added. Existing five-minute
local-process heartbeat, event logs and exact-input review caching remain.
Shorter output is preferred only when consequential meaning remains intact.
