# Compression rules - consolidated review

**CC pack 1.31.0 | 15 active CC rules | shared G001-G008 | existing IDs preserved**

The A/B/C changes extend existing rules. There is no second competing rule list. The host supplies complete applicable text and definition profiles to fresh agents.

## What changed

| Topic | Primary owner | Consolidated requirement |
|---|---|---|
| A: scientific classification | CC009 | Separate role, evidence status and retention bookkeeping; explicitly adopted assumptions differ from inferred pending questions. |
| Proposition boundaries | CC009 | Split independent results, requirements, metadata, gaps and conflicts before labeling; keep qualifying conditions together. The scientific_extraction proposition contract owns the examples and boundary tests. |
| B: extraction before compression | CC008, CC012 | Review propositions first; final reviewers inspect the core context and the exact typed projection that is published. |
| C: PK binding | CC005 | Preserve all 13 categories; use the mapped terminology appendix and check relationships within the correct analysis. |
| Missing information | CC006, CC019 | Search permitted sources; retain unresolved state, consuming stage, impact and targeted clarification. |
| Source requirements | CC007 | Preserve obligations; only Project Rules Agent publishes formal project rules. |
| Formal qualification | CC012 | Zero unblocked critical errors in the agreed acceptance set; live evaluation remains deferred, not satisfied by code tests. |

## Rules in workflow order

### 1. Frame the task and evidence boundary

| Rule | Requirement |
|---|---|
| **CC016** - Compression request binding and audit placement | Use the host-supplied compression request identity and keep binding metadata in the designated artifacts. |
| **CC003** - Compression model-call access boundary | Use only the source evidence supplied in this compression request. |
| **CC001** - Respect the selected proposal and intake result | Use the single proposal selected and checked at intake; verify the supplied selection record rather than choosing a version or repeating file intake. |
| **CC002** - Define compression scope and supporting evidence | Compress the proposal as the primary source. Search relevant authorized attachments for missing details; retain exact citations and distinguish supporting evidence from proposal statements. |
| **CC004** - Extract the overall scientific question | State the proposal-specific overall scientific question and intended outcome explicitly in main.json.objective. |

### 2. Extract, classify and bind source propositions

| Rule | Requirement |
|---|---|
| **CC006** - Search permitted attachments before NOT_FOUND | When the proposal lacks relevant details, use the question-led authorized attachment-search process before reporting NOT_FOUND. |
| **CC009** - Classify propositions before compression (A) | Before shortening, separate independently meaningful propositions, then assign each a coherent scientific role, evidence status and scope using scientific_extraction; preserve their method, assumption-adoption and relationship links. |
| **CC005** - Preserve scientific meaning with the PK terminology appendix | Apply all 13 CC005 preservation categories and their relevant PK terminology appendix. The categories define what must survive compression; terminology helps interpret it and is not an exhaustive required-data checklist. |
| **CC007** - Preserve source requirements without publishing project rules | Preserve every consequential original requirement as source content. Project Rules Agent rereads original materials and alone extracts, classifies and publishes formal project rules. |
| **CC011** - Keep exact evidence | Support core-context scalar leaves except version with exact evidence; bind scientific records and relationships to source components in the private audit. Keep original-source quotations, bindings, links and character offsets outside main.json; preserve required data-file and published-rule references. |
| **CC019** - Warn about important information still missing | If decision-relevant information remains unresolved after relevant authorized attachment searches, issue an explicit review warning rather than silently filling or omitting it. |

### 3. Compress the reviewed inventory

| Rule | Requirement |
|---|---|
| **CC008** - Compress into the reviewed handoff (B) | Write concise, independently understandable context and scientific statements. Publish the reviewed compact projection; original-source evidence machinery stays in audit. |
| **CC017** - Compression output and runtime policy | Write concise main.json scalar text and enforce the compression-specific output and progress policy. |

### 4. Review the exact handoff, release or correct

| Rule | Requirement |
|---|---|
| **CC012** - Review extraction and the exact final handoff (B) | Independently review the source proposition inventory, then require faithfulness, completeness and global-conflict reviews of the exact combined handoff before publication. |
| **CC015** - Bounded binding repair and explicit rerun policy | Block publication on invalid output or failed review. Permit one source-bounded binding repair for eligible extraction-format errors. Unresolved errors and semantic review failures stop for correction or an explicit rerun, except for the bounded host steps CC002 host_requirement enables: the host removes an unconfirmed citation or binding and lists it for a person (unconfirmed_citations, unconfirmed_bindings), sets aside a review record it cannot place and lists it (unknown_review_records), and revises a requirements_review REVISE by patch and reviews it again up to automatic_revisions times. |

## CC005: one checklist and its terminology appendix

[Open the complete integrated CC005 review](CC005_REVIEW.md). It includes all 13 preservation categories and the eight English terminology tables. Original checklist clauses are unchanged; the term definitions are stored once and referenced by category.

## Removed ambiguity and duplication

- Inventory kind FACT/UNKNOWN is bookkeeping. Scientific role FACT/RESULT/etc. and evidence_status OBSERVED/ESTIMATED/PREDICTED/etc. are separate fields. Core-field EXPLICIT/PROPOSED/NOT_FOUND attribution is another separate contract.
- The definition profile owns role meanings; CC009 owns their use. CC005 owns preservation; its appendix provides terms without creating extra requirements.
- Source-rule ownership belongs to CC007. Output placement belongs to CC008. Citations belong to CC011. Review gates and the formal qualification criterion belong to CC012.
- Generic governance remains G001-G008. CC010 and CC013 retain their historical move records; CC014 and CC018 retain their merge records. No inherited IDs are renumbered.

## Efficient correction and runtime policy

- Keep concise outputs without dropping consequential content; no default hard output-length cap or model-call timeout. Preserve five-minute local-process heartbeats and event timing.
- A/B/C reuse existing extraction/review calls. No new classification call is introduced.
- G004/G007 separate access permission, retrieval coverage and claim support throughout the workflow. Automatic correction requires a stage-specific executable adapter; sharing the rule alone does not enable one.
- Compression can send eligible defects to one fresh citation reviewer. Only supplied authorized evidence is used; the unchanged answer, source restrictions and later semantic gates remain binding. Original and corrected artifacts stay in the audit.
- Stop on a failed mandatory check. An explicit same-run retry can reuse unchanged, validated branches with matching bindings. A changed candidate needs all final reviews again; changed sources or rules require a new run. Do not resample unchanged failed semantics for PASS.

## Implementation limits

Scoped rule delivery, typed extraction contracts, exact-projection publication and existing review gates are active for new runs. The broad source-completeness detector, dedicated objective gate, full structured missing-information migration and formal live-model qualification gate retain their documented pending status. This consolidation does not implement them.

The approved zero-critical-error criterion is limited to an agreed acceptance set. There are insufficient labelled documents for the full benchmark; code tests establish contract behavior, not reliable semantic detection by a live model.

## Editable and generated artifacts

- Edit canonical rule files in `rules/general/`, `rules/intake/` and `rules/compression/`.
- Regenerate with `research_pipeline/scripts/export_compression_rules_review.py`; `--check` detects stale exports without writing.
- Human JSON: `research_pipeline/docs/interfaces/context_compression.review.json`.
- Complete runtime JSON: `research_pipeline/docs/interfaces/context_compression.runtime.json`.
- New runs snapshot the new pack. Historical runs and approvals are not rewritten.
