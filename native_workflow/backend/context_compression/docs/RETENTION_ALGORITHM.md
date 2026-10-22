# B1 retention algorithm and JSON interfaces — 3.11.0

Originally implemented 2026-09-18; extended 2026-10-06 with complete compression-only processing rules, bounded supporting evidence and material missing-information warnings. This is a source-bound extraction and review workflow, not a trained RECOMP model or a reproduction of a published end-to-end algorithm. Context schema `3.0` stays unchanged internally; the only downstream JSON is `handoff/main.json`, with the 3.0 scientific fields, numbered rules and data.files attachments. New runs use workflow `proposal-single-handoff-v3`. Earlier runs remain historical evidence.

## Paper attribution

| Reference | Adaptation | Boundary |
|---|---|---|
| [RECOMP](https://arxiv.org/abs/2310.04408) | Select information for the downstream question | No training, model weights, or downstream utility calibration reproduced |
| [FActScore](https://aclanthology.org/2023.emnlp-main.741/) | Decompose output claims and check evidence | Custom review contract; no FActScore package or calibrated accuracy |
| [SummHay](https://aclanthology.org/2024.emnlp-main.552/) | Check expected source information against summaries | Our source inventory must itself be reviewed; it is not known benchmark ground truth |
| [LLM-Modulo](https://arxiv.org/abs/2402.01817) | Separate candidate generation from external checks | Python checks contracts and provenance, not complete natural-language entailment |

The selection criteria, JSON schemas, hard release gate and default stop policy are project engineering decisions. A proposal's BLQ threshold is retained as a proposal rule, not promoted to a scientifically universal threshold. A rule saying tests are required does not establish that tests have been performed.

## Algorithm

1. Read/check all explicitly attached files locally and retain originals, snapshots and hashes. Select exactly one proposal. Its full text is the primary compression source. Before requirements extraction, attachment_plan identifies project-specific gaps and attachment_evidence assesses host-retrieved passages. Only cited authorized supporting passages enter later extraction/review requests; protected validation data are withheld. Literal search misses do not prove semantic absence. Material unresolved items become structured CC019 review warnings. Internal audit/file_registry.json records file checks and routing. After a passing proposal review, publish the scientific fields themselves together with data.files in one main.json. B2 reconciles proposal claims against actual data and decides scientific table/branch allocation.
2. `requirements`: without a candidate summary, extract necessary facts, explicit unknowns and applicable technical requirements. Each requirement has an ID, source-backed components, selection criteria and a downstream consequence. Preserve conditions together, including negation, units, operators, OR/AND, scope, prerequisites and exceptions. Cross-unit requirements may cite multiple units. Undefined terms remain unresolved; do not invent a denominator or definition.
3. `requirements_review`: a separate call reviews every requirement and every source unit. Units with no selected content still need a judgment and reason. From compression rules 1.20.0 (CC002) the unit verdicts cover the proposal's own units, sent as `review_source_unit_ids`; cited supporting passages are checked wherever an item cites them, and the completeness review uses the same scope. Source-to-requirement links must exactly match actual citations. A missing source obligation, a conflict, altered meaning or an unresolved judgment stops the run before generation. A separate model call is not an independent expert.
4. `context`: generate the historical compact JSON using full sources plus the reviewed inventory; produce the existing field evidence sidecar. Code validates the schema, every field's evidence status, exact source quote and optional limits. Defaults impose no output word/character cap.
5. `context_review`: receive sources, source units, reviewed inventory, candidate, evidence and evidence locations. Review every field; decompose into atomic propositions and review decomposition completeness. Then review every requirement and every component against exact candidate spans. The semantic judgments are made by the reviewer; code validates IDs, paths, evidence locations, complete coverage and internally consistent verdicts. Existing source-driven retention checks remain to catch omissions from the inventory itself.
6. Publish only after PASS. Any MISSING, ALTERED or UNRESOLVED in claims, decomposition, coverage, components or retention, or any critical error, blocks publication. Failures and rejected candidates are retained. No automatic retry. A later explicit run/response submission can resume. Same-run resumes reuse exact validated parallel-review branches, including their failed verdicts, only with matching request, executor, validator and audit hashes. Changed candidates require all three reviews again; changed sources/rules require a new run. CC018 is merged into CC012: PASS establishes reviewed compression, not scientific predictive validity. See the README rule-order/retry section for interface limits and audit files.

### Critical selection

For a RULE: `critical = explicit AND applicable AND technical AND material`.
For a FACT/explicit UNKNOWN: `critical = explicit AND applicable AND material`.
Every selected item must be explicit and applicable. Noncritical required items are still reviewed and can block PASS. Selection is a semantic judgment with a recorded rationale, not a learned or validated importance score. Background content need not become a requirement.

### Metrics

`critical_recall = preserved_critical_items / reviewed_critical_items`, only when that inventory is nonempty and its coverage judgments are resolved. Otherwise null. Altered or missing items count as not preserved. A partially preserved requirement is not preserved. This is coverage of this specific reviewed inventory, not absolute completeness or independent accuracy.

`independent_accuracy`, independent F/R/A and aggregate scores remain null. The historical 0.50/0.35/0.15 weights are uncalibrated metadata, not a training loss or a way to override a critical error.

## JSON stages and functions

| Stage | Response envelope | Prerequisite |
|---|---|---|
| requirements | request_sha256 + requirements | immutable input sources |
| requirements_review | request_sha256 + review | accepted requirements |
| context | request_sha256 + context + evidence | passing requirements_review |
| context_review | request_sha256 + review | accepted context |
| pipeline | request_sha256 + pipeline | passing, verified context_review |
| pipeline_review | request_sha256 + review | accepted pipeline |

`ctxcomp.engine.init_run(...)`, `prepare(run, stage)` and `accept(run, stage, response)` remain public Python interfaces. `prepare` saves the JSON request and exact response schema. Callers may use any model or a human-authored response; `accept` never generates a response itself. `verify_context(run)` verifies B1 without requiring later planning. `schemas/*.response.schema.json` are generated from the runtime schemas.

`run_model(run, ..., attempts=1, stop_after='context_review')` is the opt-in model orchestrator. Its B1 sequence is attachment plan, attachment evidence, requirements, requirements review, context and context review (three reviewer calls in parallel-review mode). Explicit `stop_after='pipeline_review'` adds two planning stages; neither option runs B2, PK or index fitting. It stops immediately on an invalid response or non-PASS review. A changed response, source or inventory cannot reuse an old request hash. Historical runs without the current input/rule snapshots must be recreated from original inputs to use the new rules; their artifacts are preserved.

## Artifact contract

* `critical_requirements.json`: all necessary inventory items (critical and noncritical), components and original quotes. Canonical values must match accepted history.
* `inputs.json`: full source snapshots, source audit units, workflow version, instructions and configuration.
* `accepted/requirements.*.json`: immutable generated inventory and request hash.
* `accepted/requirements_review.*.json`: requirement and source-unit judgments, including empty selections.
* `audit/requirements.json`: source evidence positions; repeated source quotes retain all possible matches.
* `coverage_report.json`: candidate/inventory/evidence hashes, per-item and per-component judgments, atomic claims and decomposition, critical recall and limitations. This can exist for a rejected candidate; its decision must be checked.
* `submissions/`, `responses/`, `reviews/`: original attempted/returned responses and rejection history.
* `stopped.json`: latest stopping event, not a permanent prohibition on an explicitly requested rerun.
* `compressed_context.json`: published only after all B1 gates pass. Keeps objective/study/data/rules/checks/uncertainties/version; no internal evidence graph is added.

All review contracts require exact coverage; duplicates, unknown IDs, fabricated spans, absent components, and contradictory PASS decisions are rejected. An explicit source requirement cannot count as retained if it only appears as PROPOSED or NOT_FOUND. Hashes bind artifacts but are not cryptographic signatures against malicious edits to both data and manifests.

## Verification boundary

Regression tests use saved fixtures and deliberately corrupted contracts. PMB rule mutations cover deletion of simulated recovery, OR-to-AND, >-to->= and loss of sensitivity-only. Authored judgments demonstrate the gate, not automatic LLM recognition. The code does not claim to prove semantic equivalence by matching words. A blind expert-labeled set of unseen proposals is still needed to compare omission, alteration and false-release rates before and after this change. Test fixtures and demonstration reviews must not be described as expert approval or production scientific validation.

Shared governance 1.2.0 supplies G001-G007 to new workflow requests. G001 (formerly CC010) preserves rule identity and source-version references. G002-G007 define common evidence, scope, preservation, context, binding and release principles. Compression 1.10.0 retains its CC-specific extensions and all 13 CC005 categories; inherited rule subsets keep their original IDs. Project scientific R rules remain distinct from both processing-rule layers.
