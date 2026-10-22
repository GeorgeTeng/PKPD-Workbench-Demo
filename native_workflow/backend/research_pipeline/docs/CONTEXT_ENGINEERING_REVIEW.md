# Context-engineering review and next priorities

Reviewed against the local implementation on 2026-09-20. This is a proposed development plan, not a scientific validation result or activation of new audit rules.

## What is implemented now

- Proposal-only compression preserves the original structured handoff; data travel as referenced attachments.
- LangGraph controls execution state and persistent human review, Prefect manages runs, and Snakemake executes file dependencies.
- Approval is selected by default. A human still submits it; a comment is optional for approval and required for changes/rejection.
- Clinical review spans the study. A completed output or valid QC issue report can trigger a proposal revision, additional data, further evidence, or revised analysis before final modeling is available.
- Each revision records its source node, output signature, evidence references, requested changes, reviewer, and target. It opens a blank cycle at intake and does not approve or overwrite the previous results.
- The workbench interface, EDA guidance, rule guidance, and presentation of framework errors are in English. Original research data and user-entered evidence remain source records.

## Priority 1 — Connect the remaining scientific adapters

Several nodes intentionally have no runnable target in `workflow_definition.py`. The new-data execution path in `workflow_runtime.py` still ends at preparation/mapping review. A functioning graph and passing engineering tests therefore do not establish an end-to-end scientific analysis.

Next deliverable: one vertical slice using reviewed normalized PK data, from adequacy through EDA, one PK branch, structured diagnostics, and human review. State exactly which inputs and analyses it supports. Then connect matched exposure/PD data and index screening. Human translation remains a separate intended use with its own evidence requirements.

Acceptance check: the same input versions reproduce the same output artifacts; missing required inputs produce a specific non-calculable result rather than fabricated parameters or silent defaults.

## Priority 2 — Turn each handoff into a validated task contract

The current context templates and 12 clinical fields provide useful structure, but many clinical definitions remain free text. A downstream model needs an unambiguous computational question.

Define a versioned TaskSpec with:

- Task and study-specification IDs and versions.
- Intended use and estimand: the quantity this task must estimate.
- Drug/analyte, species, route, dosing convention, matrix, and free/total basis.
- Endpoint, baseline, time window, and experimental unit.
- Assigned data references and permitted joins; explicit unit conversions.
- Applicable rule IDs and immutable rule versions.
- Assumptions, missing requirements, allowed outputs, and prohibited extrapolations.
- Review requirements and the evidence that can satisfy them.

Keep the common study definition in one versioned record. Send each branch only its required fields and references. Do not add a universal context-size cap that drops required information.

Acceptance check: an incompatible matrix, endpoint window, or unit cannot enter an otherwise successful fit unnoticed.

## Priority 3 — Replace project-specific routing shortcuts

`context_router.py` currently includes hard-coded rule-number sets, species branches, and dataset-name matching. These support the existing PMB package but are fragile when filenames, rule numbering, or projects change.

Route by validated dataset metadata: role, analyte, species, route, matrix, data level, endpoint, units, and provenance. Require model manifests to declare compatible inputs and outputs. Select rules by applicability and scope rather than their numerical position.

An LLM may propose a plan and explain ambiguous mappings. Deterministic checks should verify file existence, compatibility, dependencies, and review status before execution. Ambiguity should create an explicit mapping question for a human.

Acceptance check: renaming a valid dataset does not change its scientific route, and an incompatible dataset with a familiar name is rejected.

## Priority 4 — Plan revisions by their actual impact

The current safe policy opens an empty cycle and requires input registration and fresh review. It preserves history but does not yet decide which prior computations remain usable.

Add a change-set record comparing proposal, data, endpoint, rule, model, and intended-use versions. Use dependency tracking to identify affected computations and approvals.

Examples to evaluate under an explicit reuse policy:

| Change | Potentially reusable | Must be revisited |
|---|---|---|
| Interface language | Scientific data and numerical results | Presentation rendering |
| Editorial proposal correction | Computations whose assumptions and scope are unchanged | Revised proposal record and scope confirmation |
| PD endpoint or time window | PK estimates if their inputs and assumptions are unchanged | Exposure/PD matching, index fits, interpretation |
| New PK observations | Unchanged source evidence | Affected QC, EDA, PK fits, and dependent predictions |
| New clinical safety evidence | Model estimates if the model itself is unchanged | Feasibility, safety, benefit-risk, final acceptance |

These are conditional reuse candidates, not automatic approvals. Reusing a numerical artifact does not transfer clinical acceptance to a new intended use.

Also separate computational fingerprints from the full software audit. `make_plan()` currently fingerprints most Python modules, including workflow/presentation definitions. A wording or layout change can invalidate a run even when the fitting code is unchanged. Retain all software versions in the audit, but invalidate calculations using their actual computational dependencies.

## Priority 5 — Give findings and decisions a common schema

The execution graph currently separates runtime errors, pauses, and human scientific review, and reads selected report fields. It does not yet provide a comprehensive typed scientific-diagnostic contract.

Represent each finding with a stable ID, affected task/output, evidence references, calculability, scientific implications, proposed remediation, and review status. Keep engineering failures, source gaps, data adequacy, model adequacy, and predictive validity distinct.

For example, missing binding evidence may block a free-exposure conversion while leaving total-concentration descriptions available. Insufficient data for a precision target differs from missing metadata that prevents calculation. A converged model differs from a validated human prediction.

Acceptance check: a local gap blocks only the outputs that depend on it, while the report clearly limits the remaining conclusions. No generic numerical cutoff is activated without project review.

## Priority 6 — Trace evidence to its exact location and test semantic failures

File hashes establish which bytes were used. Add precise evidence locators where needed: article/DOI, page, table, worksheet, cell/range, source quote, and extraction method. Preserve labels for observed individual data, digitized points, group summaries, and derived estimates.

Extend tests beyond runnable files and HTTP success. Useful cases include mismatched free/total exposure, a shifted PD window, mg versus mg/kg, pooled animals mistaken for repeated individual profiles, changed MIC definitions, a revised proposal, and a missing required diagnostic report. Expected outcomes should be routing corrections, explicit non-calculability, or human review—not invented data.

## Suggested implementation order

1. Define TaskSpec and dataset metadata for one supported analysis.
2. Connect that analysis from QC through EDA and diagnostics.
3. Replace filename/rule-number routing for that path.
4. Add versioned change sets and selective result reuse.
5. Expand scientific-failure tests, then generalize to additional projects.

This sequence addresses the missing executable path and ambiguous handoffs before adding more autonomous planning.
