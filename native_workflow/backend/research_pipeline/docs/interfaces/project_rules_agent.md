# Project rules agent after compression

## Current default — lightweight policy 1.6.0, compact output 1.3

Fresh preparation freezes `extraction_policy.1.6.json` and the twelve-module
workflow reference `1.1.0`. Execution returns to the earlier compact path:
one extraction call, one independent source review, then local publication if
the exact reviewed collection passes. A REVISE is retained and stops publication;
this default has no inventory/consolidation calls, automatic repair or re-review.

Rules capture **drug/project-specific constraints, exceptions and cautions**.
They explain what a downstream module must handle differently for this project,
not how to perform its normal workflow. Both extraction and review use this same
criterion. Routine QC, modeling, documentation and reporting instructions stay
outside the rule collection unless they contain an adopted project-specific
restriction. A mandatory verb or drug name alone does not make a task special.
Keep concrete species eligibility, conflicting data handling, source-use limits,
holdout/freeze conditions and other supported exceptions. Drug facts alone do
not authorize invented restrictions or model choices.

Published records still contain only `id`, `text`, `used_in`, `evidence`.
Exact quotations, source permissions, source coverage, inherited-rule mapping,
review findings and hash-bound history remain. Module descriptions are routing
context, never project authority. PK translation retains `pk_translation`.

The ledger experiment below is **deferred until the downstream framework is
built**. Existing frozen runs retain their own policy and remain replayable;
resuming an old input does not silently migrate it. Start fresh preparation to
use the lightweight default. Historical 1.3-1.5 policy files are unchanged.
Contract tests establish execution and evidence checks, not perfect semantic
recall or stable model judgments across independent runs.

## Deferred experiment — obligation ledger policy 1.5.0

Historical ledger preparation froze `extraction_policy.1.5.json` and workflow reference
`1.2.0`. Normal execution uses three independent calls:

1. Inventory every authority-source segment and its complete obligations. Exact
   quotations remain attached; surrounding source text is available. Supporting
   evidence does not gain project authority. Context-only and unresolved segments
   receive explicit dispositions. Each source obligation owns its governed
   operation classifications; the host derives its destination set here.
2. Consolidate equivalent obligations. Every obligation is assigned exactly once
   to a rule or explicit exclusion. Code rejects unaccounted obligations and
   identical rule text regardless of routing. Semantic duplicates and scope
   compatibility still require independent review. Consolidation cannot change
   operation classifications or merge different destination sets. This prevents
   an obligation from inheriting extra destinations solely through grouping.
3. Independently review original source segments, obligations, final rules and
   the twelve module deliveries. This checks omissions *from the inventory* as
   well as omissions during consolidation. PASS requires all required checks.

Policy 1.4.1 additionally builds a deterministic shortlist of potentially repeated
rules from lexical overlap (independent of routing). Review must check each pair
and each rule's operation classifications. Similarity never merges or removes a
rule; different species, conditions or phases can correctly remain distinct.
Historical 1.4.0 requests retain their exact original schema and hashes.

On a localized REVISE, the workflow allows one bounded repair and a fresh full
review (normally at most five calls). A rejected patch that mixes differently
routed obligations gets at most one structural correction, bringing that case
to six calls; its rejected response, exact error and unchanged patch scope are
hash-bound in the repair lineage. No other model/provider failure is blindly
retried. Only named source segments/rules and their direct
obligation dependencies can change. Unaffected rules, evidence and IDs remain
identical. All original responses and reviews are retained. Further failure
stops publication; it never causes automatic full regeneration or a forced PASS.
`project_rule_pipeline.review_with_repair` returns explicit candidate/review
references; the workflow publishes that selection. `agent.review` remains one
independent call for callers that manage repair themselves.

Allowed rule IDs bound edits; omission from a patch never deletes a rule. Only
explicit removal IDs delete rows. Byte-identical neighbouring rule echoes are
ignored. A neighbouring source segment with identical obligations/disposition
but a paraphrased audit reason is also ignored, preserving the original reason.
Substantive out-of-scope edits remain errors. These normalizations do not rewrite
source requirements, evidence or routes, and the raw response remains retained.

An explicit diagnostic branch can combine the original failed review with the
recorded failed review of its first bounded repair, then apply one patch from the
original candidate. Both reviews, candidate hashes and the expanded local scope
are replay-validated. This is not an automatic loop, cannot use another project
or recursively chain diagnostic branches, and still needs a fresh full review.

Published rules still contain exactly `id`, `text`, `used_in`, `evidence`.
Inventory, exclusion/merge accounting, operation classifications, module views
and repair lineage live in audit artifacts. Published IDs survive local repairs.
Replays validate the frozen policy, every source quote, accounting, derived
routing, repair boundaries and review hashes.

New publications use the same module delivery function for review and consumption:
`pk` selects animal PK; `translation` selects PK translation and human validation;
`index`/`targets` share index, and `results`/`clinical` share clinical. Explicit tags
and the historical lookup name `human_pk` remain supported. This does not enable
planned/disabled modules. Historical publications retain their old coarse aliases.

Deterministic routing is stable for the same operation classification, including
input-order changes. The classification and source interpretation remain model
judgments: these contracts do not prove perfect recall, semantic equivalence,
scientific adequacy or stability across independent model runs. Real proposal
evaluations and source-based regression cases are required in addition to tests.

## Historical compact policy 1.3.4

Historical policy 1.3.4 uses `backend/rules/project_rules/extraction_policy.1.3.4.json`.
Extraction and independent review remain separate calls. Every extracted and
published rule has exactly four fields:

| Field | Purpose |
| --- | --- |
| `id` | Stable identifier within this immutable publication |
| `text` | Complete obligation, including conditions, exceptions, biological scope and timing |
| `used_in` | Smallest set of downstream steps whose actions or decisions must obey the rule |
| `evidence` | Exact original quotations with `source_id` and `unit_id`, retained once per rule |

No separate action/target slots, field-level evidence connections, authority
evidence copies, classification reasons or usage descriptions are published on
each rule. Source roles remain trusted input metadata; at least one permitted
project-authority citation is required in the single evidence list. Both model
calls receive original source units once, and the reviewer receives the exact
final collection without a duplicate candidate body.

Keep adopted constraints and consequential mandatory deliverables. Exclude
background, optional suggestions and task narrative already retained in context.
Do not turn a future-stage obligation into an immediate data prerequisite or
discard it merely because its consuming step occurs later. Complete conditions
must survive deduplication; semantically different duties remain separate.

`used_in` supports adequacy, prepare, eda, dispatch, animal_pk, pk_translation, index,
human_validation, pta and clinical. The last two specific analysis destinations
separate validation and attainment requirements from general interpretation.
The historical coarse `clinical` consumer receives all three clinical-related
destinations; callers may request `human_validation` or `pta` independently.
This catalog does not enable any workflow or authorize scientific execution.
Scope and timing remain in complete text for the consuming agent to obey;
compact projection filters steps, not individual species or task IDs.

Quote-location checks do not prove meaning. The independent reviewer checks
every final rule and source unit for necessity, support, omissions, routing,
duplicates and conflicts. Hashes bind review to the exact evidence and final
collection. Unresolved requirements or failed checks cannot publish as PASS.
Coverage/exclusion reasons and publication mappings stay in the audit record,
outside downstream rule bodies. After REVISE, correct the cause and run a fresh
extraction/review in new output directories; legacy field-repair operations
apply only to the historical contract.

Existing 1.0–1.2 snapshots, published IDs and reviews remain verifiable under
their frozen contracts. They are not silently migrated or rewritten. Preparing
a fresh rule input from verified compression adopts 1.3 without recompressing.

### Policy 1.3.3: decision order and rule boundaries

The output schema remains 1.3. PRC001-PRC007 now state the decision order:
source authority -> downstream necessity -> one complete obligation -> faithful
text and evidence -> consumer routing -> deduplication and coverage -> independent
review. Both stage prompts and seven boundary examples are frozen in the policy.
They are processing guidance, not project requirements or citable source evidence.

Independent operations must not be bundled merely because they share a paragraph,
source unit or consumer tag. Conditions, exceptions and coupled safeguards stay
with the operation they govern. Several species, metadata fields or consumers
alone do not imply a split. Documentation and failure outcomes stay with the
operation they qualify; differing consumer subsets alone are not a splitting
reason. Consolidate redundant general/specific restatements without dropping
qualifiers. Coverage links must agree with actual citations in both directions. The reviewer uses the existing per-rule verdict and
`COMBINED_DISTINCT_DUTIES` finding to explain the concrete applicability/routing
problem, and also checks over-splitting. No clause-level fields, extra calls,
keyword splitting or changes to the deterministic exact-duplicate assembler are
introduced.

Policy 1.3.0, 1.3.1 and 1.3.2 snapshots still reconstruct their original prompts, request hashes
and audit versions, with or without the workflow reference. Policy 1.3.3 introduced
these prompts; the current naming update is described below. Old candidates and
reviews cannot be reused against a changed request.

Policy 1.3.3 also preserves unqualified source scope (for example, human review
before fitting must not silently become animal-PK-only review). Consumer routing
checks both production and use of results, and earlier preparation when its
actions must obey a restriction. Independent target-use restrictions may be
separated from model-comparison work so PTA receives the restriction without
instructions to refit index models. The same independent review call also
checks each module view for missing or irrelevant restrictions, reporting
defects in existing checks/findings. No output fields or calls are added.

### Module naming and routing (policy 1.3.4)

The frontend and workflow reference use **PK translation**. Fresh rule records
use `pk_translation`; the former `human_pk` tag remains a lookup alias for
historical publications. Selection accepts either name without rewriting
stored text, tags, evidence or hashes. Human PK data/access fields keep their
meaning, and `human_validation` remains distinct.

| Frontend module | Current used_in mapping |
| --- | --- |
| File intake | Upstream; no separate rule consumer tag |
| Context & Project Rules | Upstream extraction/review; no separate tag |
| Data Assessment & Preparation | adequacy, prepare |
| EDA | eda |
| Task assignment | dispatch |
| Animal PK modeling | animal_pk |
| PK translation | pk_translation; human_validation for permitted human validation |
| PK/PD index screening | index |
| PD target estimation | index |
| PTA | pta |
| Results & review | clinical |
| Clinical interpretation | clinical |

This is a module-to-consumer mapping, not a one-to-one module enumeration.
Each rule still receives only tags for actions it governs. Policy 1.3.4 pins
workflow reference 1.1.0; previous policies retain reference 1.0.0 and their
original request hashes. No previously planned module is enabled by renaming.

### Workflow reference context

New compact inputs also freeze `workflow_reference.1.1.json` and its digest.
Both extraction and independent review receive this same reference once. It
describes all twelve frontend modules, their duties, internal steps, dependencies
and conditional mappings to the existing `used_in` tags. It is visible under
Project Rules in the workbench reference-file catalog.

This reference is not project authority, admitted source text or rule evidence.
It creates no project requirements and does not enable planned/disabled stages.
If removing a proposed rule changes no module action, choice, check, acceptance
decision or deliverable, exclude it and retain the reason in source coverage.
Do not invent a consumer to retain a rule; real future uses still count and
uncertain applicability requires review rather than an assumed exclusion.
For compatibility, PD target estimation uses the existing `index` tag and final
integrated reporting uses `clinical`; no frontend IDs are added to the enum.
The four-field output, policy, publication gates and runtime aliases are unchanged.
Historical compact inputs without this optional snapshot keep their original
request payloads and hashes. To adopt this reference, prepare a new input and
perform fresh extraction/review; old candidates and reviews are not rewritten.

## Historical extraction methods — contract 1.2

Historical 1.2 inputs use the versioned policy in
`backend/rules/project_rules/extraction_policy.1.2.1.json`. Inputs prepared
under policy 1.2.0 keep `extraction_policy.1.2.json`; its PRC007, PRC008 and
PRC011 became PRC005, PRC006 and PRC007 in 1.2.1 with unchanged meaning.
The two fresh calls remain extraction and independent review; publication is
deterministic and the LangGraph → Prefect → Snakemake path is unchanged.

| PRC | Focus | Method added |
| --- | --- | --- |
| PRC001 | Effective project requirements | Original project materials and adopted decisions; approved wording retained |
| PRC002 | Requirement identification | GoLLIE-style definitions and boundary examples; distinguish requirements, options, facts and unresolved clauses |
| PRC003 | Complete requirement fields | Detection followed by slot filling, adapted from EMNLP 2025; preserve force, action, actor/target and timing |
| PRC004 | Source grounding | XTRAREG-inspired bounded source context; exact field evidence and bidirectional coverage |
| PRC005 | When and where to use a rule | Workflow phase, deadline and frequency remain separate from observation windows |
| PRC006 | Requirement-specific gaps | Ask only questions that affect requirement meaning, adoption or applicability |
| PRC007 | Final collection review | Review the assembled records, exclusions and mappings; bind PASS to their exact hash |

The shared G001–G008 instructions are inherited once per call. Bibliographic
digests remain in the review documents. The other three references in that
digest are background only. This integration does not fine-tune GoLLIE, add a
retrieval service, or establish the cited papers' performance on project data.

Each candidate carries `classification_reason`; requirements additionally carry
`requirement.forms`, `actor`, `action`, `target`, `source_modality`,
`workflow_phase`, `deadline` and `frequency`. Missing scalar values remain
`NOT_SPECIFIED`. Existing conditions, exceptions and scientific scope are
retained. `field_evidence` binds each populated source-derived field to admitted
original spans. Routing stages use `routing_reason` because they are workflow
assignments, not necessarily words in the source.

The host validates fields and source mappings before invoking the reviewer.
The reviewer sees `publication_candidate`, including the final rule text and
publication map, and returns `final_rule_checks` and `final_rules_sha256`.
The same records are published unchanged. A syntactically valid quotation does
not establish that it supports the meaning: semantic grounding and omissions
still require the independent review.

Existing 1.0/1.1 inputs retain their earlier schemas and processing rules.
No saved input or live flow is migrated automatically. Previously prepared
inputs retain their original 1.2 policy. The runtime resource is
packaged and included in Snakemake plan dependency hashes. Its definitions,
scientific preservation profiles and shared governance are snapshotted for
new inputs.

The three methods are adopted and their integration is authorized. This does
not mark every updated PRC wording as human-approved. PRC001 approval is retained;
the remaining wording is presented for sequential review. Offline tests verify
contract behavior; a real-model blind qualification has not been completed.

## Scope

This stage receives an already reviewed compression run. It extracts and
independently reviews explicit project obligations before deterministic
publication. It does not fit models, clean data, approve scientific results or
modify the original compression handoff.

The project-wide scientific question remains in `main.json.objective`. Project
requirements are published only in `project_rules.json`. Compression preserves
source meaning (including original requirements) in evidenced context fields,
but does not classify or publish a formal rule list. Its reserved `rules` field
is empty. The effective `main.json` adds `project_rules_ref` (path and SHA-256).
Source identities, locations, exact
quotations, conditions, applicability and classification decisions belong to the
associated rule audit. A paper's use of a two-compartment model is a literature
fact or candidate method unless the project explicitly adopts it as a requirement.

Workflow processing rules and unapproved scientific rule libraries do not become
project requirements. Permission to read a material is not permission to import
its methods, parameter estimates or thresholds. Protected validation content
remains outside extraction. Missing or ambiguous authority is a review issue,
not permission for the agent to choose a project policy.

## Source designation and usage annotations (contract 1.1)

The original proposal is always rechecked. Additional registered documents may
be designated `PROTOCOL`, `PROJECT_SUPPLEMENT`, `CLARIFICATION`, or
`PROJECT_APPROVAL`. The last role includes review decisions. Each designation
contains `file_id`, `role`, and `designation_reason`. Direct clarification inputs
retain their explicit role. Ordinary literature stays `SUPPORTING_EVIDENCE`;
neither its filename nor its body can give it project authority.

Allowed registered documents and explicitly designated JSON statements/decisions
are read. JSON validation preserves the original text for quotations. Protected validation files are
rejected even if a declaration attempts to label them as an approval. A changed
source invalidates the prepared input and review. Contradictory source statements
still require resolution; importing an approval does not automatically override
all earlier requirements.

The declarations are accepted by `prepare(..., project_materials=[...])`, the
CLI `prepare --project-materials declarations.json`, fresh job requests, and
`POST /ui-api/workflow/sessions/{id}/files` alongside `upload_ids`. Use registered
IDs, not guessed filenames. The UI does not yet have a dedicated role-selection
editor; the API and CLI provide this interface.

Verified `LEAN_1.0` compression runs are also accepted. Preparation uses their
already admitted original sources after `verify_context`, without requesting
legacy attachment-plan or attachment-evidence stages. Only the host-selected
proposal receives `PROPOSAL` authority.

A readable registered document may instead be explicitly designated
`SUPPORTING_EVIDENCE`, for example a copied workbook regimen excerpt:

```json
{"file_id": "<registered ID>", "role": "SUPPORTING_EVIDENCE", "designation_reason": "Non-normative original data cells; curator advice is not adopted."}
```

This sets `may_supply_project_authority` to `false`. When the document is already
an admitted clarification, preparation retains its existing source IDs and text
once and applies the designation to every admitted fragment. It does not keep
an additional authority-bearing copy. Unspecified explicit clarifications retain
their existing `CLARIFICATION` behavior; reading a non-normative excerpt therefore
requires the explicit supporting-evidence designation. Protected files remain
forbidden under either designation. Historical prepared inputs are unchanged.

Each published rule includes its full text, evidence, conditions, exceptions,
scope and a `usage` annotation:

```json
{
  "used_in": ["animal_pk"],
  "check_at": ["STAGE_ENTRY_APPLICABILITY", "BEFORE_STAGE_HANDOFF_COMPLIANCE"],
  "applies_when": [],
  "except_when": [],
  "source_window": "NOT_SPECIFIED",
  "timing_policy": "Evaluate conditions at the assigned stage; do not require deferred data early. Unspecified source timing remains NOT_SPECIFIED."
}
```

This is an illustrative shape, not an active scientific rule. The extractor and
reviewer determine source-supported stages and conditions. The host derives
`usage` without changing them. `check_at` describes workflow checkpoints; it
does not invent a scientific deadline or prove that a downstream agent checked
compliance. Biological applicability remains for the consuming task to assess.

The rule pack has a relative `main_file` name. Main hashes the rule pack; the
report hashes both. Verification reconstructs the expected effective main from
the reviewed artifacts, avoiding circular file hashes. On-disk main contains no
duplicate formal rule text. Fresh downstream requests receive the applicable
full rule records, with stable published IDs and the original artifact reference.

## Python execution example

```python
from pathlib import Path
from research_pipeline.project_rule_agent import prepare
from research_pipeline.adequacy import file_ref
from research_pipeline.common import write_json, utcnow
from research_pipeline.graph_execution import run_controlled

# Use new, distinct folders. compression_run must already pass its own review.
job = Path("C:/research/jobs/project_rules_001")
run = Path("C:/research/outputs/project_rules_001")
input_path = job / "project_rules_input.json"
prepare(Path("C:/research/completed/context_work"), input_path, project_materials=[
    {"file_id": "F0002", "role": "PROTOCOL", "designation_reason": "User-selected project protocol"}
])

request = {
    "id": "project_rules_001",
    "created_at": utcnow(),
    "mode": "project_rules",
    "stop_after": "project_rules",
    "job_dir": str(job),
    "out": str(run),
    "project_rules_input": file_ref(input_path),
    "model": None,
}
request_path = write_json(job / "request.json", request)
status = run_controlled(str(request_path), target="project_rules")
```

New upload jobs build the whole dependency chain at initial planning, including
when the first target is `intake`. Their `context` target finishes publication;
`compression` is an explicit compression-only target. `project_rules` can also
be called as a separate job from a verified historical compression run:

```text
intake -> compress -> project_rules_prepare -> extract -> review -> publish
```

`project_rules_prepare` calls `prepare(context_work, project_rules/input.json)`
only after compression succeeds. The generated input reference is hashed at
execution and covered by its receipt; that input carries verified base-main and
source references. An existing saved plan is never expanded or migrated by
selecting a new target; use a new job to adopt this contract.

The example paths are placeholders. The input is produced by `prepare`, not by
manually marking files approved. `validate_input` verifies the prepared input,
base main reference and source references before scheduling. Input, code and
contract hashes are retained in the plan; changes require a new job.

## Execution layers

```text
LangGraph: validate input references and resolve the project goal
  -> Prefect: execute and track this job
    -> Snakemake: project_rules_extract
                 -> project_rules_review
                 -> project_rules_publish
  -> LangGraph: interpret the publication report
```

Extraction and independent review use separate model calls. Each receives the
explicit request for its role, including the actual applicable instructions and
permitted evidence. Publication is deterministic. It must reject invalid source
references, stale review/input identities and unresolved publication blockers.

Each stage writes an execution receipt. A completed extraction receipt only
means extraction returned its required artifact; it is not rule publication.

## Files

Paths below are relative to the new run's output directory:

| File | Purpose |
| --- | --- |
| `project_rules/extraction/candidate.json` | Candidate classifications and project requirements |
| `project_rules/review/review.json` | Independent review of the exact candidate and evidence |
| `project_rules/published/report.json` | Always emitted when publication can evaluate the review |
| `project_rules/published/main.json` | New downstream main, published only on a clean pass |
| `project_rules/published/project_rules.json` | Published project-rule collection, only on a clean pass |
| `project_rules/published/rule_audit.json` | Evidence, scope and publication trace |
| `project_rules/stopped.json` | Structured execution failure and next action, if execution fails |

The output folders also retain per-call audit artifacts created by the agent.
The original compression run and its approvals remain immutable. A published
rule collection is a new versioned artifact; an old approval does not transfer
to changed rules. Scoped downstream subsets preserve inherited rule identities
and carry actual rule text and provenance references, not IDs alone.

## Status and review behavior

- `PROJECT_RULES_PUBLISHED`: LangGraph returns the dedicated `PROJECT_RULES_READY`
  disposition. This means the rules handoff is ready for downstream adequacy
  assessment; it does **not** establish data sufficiency or authorize fitting.
  Clean faithful extraction of previously authorized requirements does not add
  another mandatory human gate.
- `RULES_REVISION_REQUIRED`: LangGraph returns `CONTEXT_REVISION_REQUIRED`, with
  final job status `REVISION_REQUIRED`. No main/rule handoff is published.
  Review the candidate, exact sources and review findings; clarify conflicts or
  authority, then use a new input and job. Compression is not silently rewritten.
- Execution/provider/schema failures remain `STOPPED_ON_ERROR`; they do not
  establish a faulty proposal or missing scientific data.
- A dry run validates the scheduling plan only. It does not publish rules or
  certify a model response.

## Integration boundary

No existing canvas session, historical review or active UI flow is migrated
automatically. New flows execute publication inside the context stage through
LangGraph/Prefect/Snakemake. Canvas collects the published rules, effective main,
audit and report for inspection. It forwards the published reference to adequacy.
The reviewed-context approval envelope can include `project_rules_ref` as a
path/hash reference to the published collection. The adequacy plan binds the
pack, effective main, audit, input, extraction, review, base main and original
sources; a changed dependency invalidates receipt reuse. A new-format main
without published rules is blocked; historical main formats remain readable.

## Context carried by each fresh model call

Both calls receive the project objective, study definition, inherited rules,
the original main artifact reference and version, admitted source text/locations,
read and authority permissions, the actual PRC processing-rule text, and a
request-specific response schema. The schema lists the exact original JSON
pointers and source-unit identifiers required for complete coverage.

The reviewer additionally receives the candidate, its content hash and the
extractor request hash. The review request has a different hash by design. The
host validates each response against its own request; neither model resumes the
other model's conversation. No raw observation tables or protected human
validation body content are loaded into these calls.

Classifications are `PROJECT_REQUIREMENT`, `PROJECT_OBJECTIVE`,
`LITERATURE_FACT`, `CANDIDATE_SUGGESTION`, and `UNRESOLVED`. Pure objectives remain
in `main.objective`, not in the published rules. Only project requirements enter
the separate `project_rules.json.rules`. Duplicate merging preserves all evidence and requires
identical text, conditions, exceptions and scope at the host layer. Semantic
grouping proposed by the extractor still requires independent review.

## Downstream consumption

`adequacy.import_reviewed_context` accepts `project_rules_ref` in the approved
context envelope, checks that its base main matches the approved artifact, and
imports the new effective main without changing the compression output. A
separate scope amendment cannot be silently combined with a pack reviewed
against another context. The provenance sidecar keeps the published pack ref.

Clinical routing reads that provenance and uses explicit reviewed stage/task/
source scope. `task_rules.project_rules` and subsequent scoped projections use
the new pack without legacy clause rewriting. Every selected rule carries its
full text, conditions, exceptions, applicability and evidence references; an
inherited subset preserves its published IDs. Unresolved task/source matching
is reported for confirmation. Further biological applicability must still be
checked by the scientific consumer; receiving a rule is not model acceptance.

At this pre-adequacy stage the extractor cannot invent downstream task or
dataset identifiers. Its `scope.task_ids` and `scope.source_ids` are therefore
empty, enforced by the response schema. Source IDs such as `S1` in citations
identify evidence, not a dataset filter. Stage applicability is explicit;
study/file-specific restrictions remain in the full rule text, conditions and
biological scope. Later allocation can qualify those restrictions against
actual metadata. This prevents an unknown or citation ID from silently
filtering a mandatory rule out of a downstream task.

## Verification scope

Fresh `prepare` inputs now freeze annotation **1.1** for atomic applicability,
source coverage, complete authority/form citations, faithful objective limits,
PTA missing-input alternatives and delivery to all applicable consumers. The
same annotation reaches extraction and independent review. Fresh review uses
`EXACT_DIGEST_V2`, binding known candidate/final hashes and candidate finding IDs
in its response schema. Historical inputs without annotations, annotation 1.0,
and V1 reviews keep their original requests unchanged.

Saved model outputs can be repaired without repeating extraction:
`repair_saved_contract` requests only missing authority/form citations;
`revise_candidate` replaces or splits explicit diagnosed parent items while
freezing all other items and restricting citations to parent source units.
All repairs retain raw outputs and replayable hashed proofs through publication
and downstream verification. A fresh full independent review remains required.
`reserve_existing_ids=True` protects existing siblings during repeated splits.
Explicit saved-output recovery permits only pre-existing exact field/coverage
links or discarding an exact extra out-of-scope citation that supplies neither
authority nor a field binding. These operations cannot invent scientific data,
project authority, validation results or approval.

`revise_input(input_ref, candidate_ref, review_ref, new_input_path)` freezes
annotation version 1.0 after a valid retained `REVISE`. It requires independently
applicable obligations to share scope, conditions and phase within each item,
and checks adopted directives inside source units. It preserves the original
sources, permissions and PRC policy. The extractor receives the prior review as
explicit non-evidence diagnostics; the independent reviewer receives only the
new annotation, original sources and current candidate. Historical inputs and
requests retain their original instruction payloads. Neither interface adds
project authority or changes any scientific approval gate.

`recover_evidence_index(input_ref, request_ref, response_ref, new_output_dir)` can
recover a saved extraction whose exact field citations were omitted from its
item evidence index. It only appends those existing spans to `item.evidence`,
requires the same item to already cite the source unit and its coverage link,
and runs the unchanged candidate validator. It cannot change text, fields,
scope, coverage, authority, or a review verdict. The returned candidate ref
includes a hashed replay proof; preserve that complete ref through `review`,
`publish`, and `verify_published`, which replay the proof. Raw responses and
prior errors remain immutable. An independent review is still required.

`tests/test_project_rule_agent.py` uses labeled synthetic responses to test
contracts, not LLM accuracy. `scripts/verify_project_rule_agent.py --out <new-dir>`
uses synthetic source text through the real LangGraph/Prefect/Snakemake path and
two fresh provider calls. It stores inputs, candidate, independent review,
publication or stop report, process logs, execution receipts and control trace.
It does not rerun a real proposal or scientific model. Use a new output directory
for every attempt; rejected responses remain available for inspection.
