# Clinical questions and scoped downstream contracts

The dispatch adapter reads the reviewed effective context, the independently reviewed data-adequacy tasks, approved QC metadata and completed EDA. It is a thin deterministic router: allocate tasks and permitted datasets, retain unknown assignments, and declare exposure dependencies. ContextBuilder assembles the separate PK and PK/PD handoffs through the branch projection adapter. Neither routing nor assembly calls an LLM.

`clinical_dispatch.build` calls `context_builder.build_branch_handoff` once per branch. `dispatch_context.prepare_branch` owns the existing scientific field/rule/evidence projection; ContextBuilder checks source hashes before and after assembly and binds each output in a compact manifest. These are downstream contracts, not model requests, so no synthetic model prompt or duplicate request payload is created. The existing clinical interpretation contract is retained for later study-wide work; it is not a third modeling branch.

The main canvas still stops at its existing disabled EDA gate. Offline synthetic integration tests exercise this refactor without enabling EDA or granting research-data approval.

## Workflow

### Proposal-dependent defaults (generator 2.0)

The 12 field names are stable; their contents are retrieved from each project's reviewed `main.json`, tasks and requirements. Task-specific endpoint windows, units and exposure basis stay labeled by task. Each definition or related statement has an exact quote and JSON pointer in an evidence catalog, also inspectable from the question form. Missing definitions stay UNKNOWN; related statements do not certify a complete or consistent answer. Human edits are separately identified from generated defaults.

Binding policies, safety endpoints and acceptance criteria are no longer supplied by the PMB example. Index candidates are recognized from current declarations; absent, excluded or ambiguous candidates are not filled from a default list. This is bounded deterministic retrieval of already model-reviewed context, not another semantic LLM interpretation. New terminology or unresolved task classification requires review. Fixed branch slots and adapter capabilities do not imply that every project requests every branch. Tasks without a reviewed branch allocation remain visible as unresolved.

Completed or confirmed historical outputs are retained. Upgrading the generator does not rewrite a scientific decision or inherit approval into new answers.

1. Prepare the draft after EDA completes. Earlier context, assessment and QC must be approved. Drafting never releases data for modeling.
2. Review the 12 question fields. Keep unresolved definitions as `UNKNOWN: reason`. Confirm whether index calculations need this PK model's predictions or separately qualified matched exposure data.
3. Confirm the question definitions against the current draft and upstream signatures.
4. After EDA approval, run Clinical questions. LangGraph reads the reviewed references, invokes Prefect, and Snakemake executes `clinical_dispatch` with hashed inputs and a receipt.
5. Review the generated routing artifacts through the existing LangGraph interrupt. The downstream consumer verifies the exact artifact signature, data references and any supplemental-input approvals.

The PK/index scientific execution adapters remain a separate implementation. Dispatch approval authorizes the scoped routing; it does not certify model-ready data, predictive validity or clinical efficacy.

## Branch outputs

| File | Contents |
|---|---|
| `pk_context.json` | Animal PK and human-exposure translation tasks, source-separated concentration/dosing/binding references, applicable rules, EDA findings, missing model qualifications and expected diagnostics |
| `index_context.json` | Permitted indices, endpoint/window/free-basis definitions, MIC/PD/dosing/binding candidates, exposure dependencies, separate calculation and matched-PD fitting gates |
| `clinical_context.json` | Validation, MIC distribution, PTA readiness, feasibility/safety and study-wide revision tasks; human holdout data stay reserved |
| `clinical_questions.json` | Question definitions, explicit unknowns, original draft defaults and source provenance |
| `routing_plan.json` | Per-file destinations and reasons, unassigned sources, parallel tasks and dependencies |
| `dispatch_report.json` | Branch counts, unresolved definitions and reasons scientific calculation cannot yet pass |
| `{branch}_context_manifest.json` | Context hash, task/data assignment, source and assembler bindings, and explicit zero model calls |

Each data reference includes a SHA-256 checksum. No datasets are combined or rewritten at dispatch. Metadata and quarantine references accompany the data. Unclassified source tables require QC role qualification; nonmatching pathogen sources remain outside the current index scope. Model libraries containing mixed permissions or published fitted parameters require a separately qualified structure/code subset.

## API

Prefix: `/ui-api/workflow/sessions/{session_id}`.

- `POST /clinical-questions/draft`: generate a versioned, nonreleased draft from the current inputs.
- `GET /clinical-questions/draft/files/{name}`: inspect a verified draft JSON.
- `POST /clinical-questions`: submit all question `values`, `reviewer`, `confirmed: true`, `index_exposure_source` and current `draft_signature`.
- `POST /nodes/dispatch/start`: execute a new dispatch job, or retry a failed job with corrected definitions. Earlier compression/QC/EDA are not rerun.
- `POST /nodes/dispatch/review`: approve or return the exact generated artifacts using the standard review contract.
- `GET /nodes/{pk|index|clinical}/assigned-context`: consume the approved scoped contract plus separately approved supplemental handoff references. Returns HTTP 409 until the routing review and upstream requirements are met. `model_release` stays false.

Failed execution records a structured reason and correction action. Definitions are versioned; changes after a completed dispatch require a new study cycle. This adapter does not implement selective downstream reruns.

## Validation

Latest 2026-10-20 verification after repairing the two message assertions:
69 passed, 8 skipped, 0 failures across the six suites below plus
`test_scientific_handoff`. Both expanded and compact scientific-context cases
now assert `PipelineError.code == PROJECT_RULES_CONTEXT_MISMATCH`, retaining
the rejection requirement without depending on user-facing wording.
Production validation behavior is unchanged. The eight skipped cases require
retired EDA fixtures. Latest report: workspace
`outputs/Task_Assignment_Verification_20261020/regression_after_assertion_fix.xml`.

2026-10-20 follow-up verification: 65 passed, 6 skipped across the six suites
listed below, including 26 dedicated dispatch/ContextBuilder cases. Additional
cases cover repeated draft generation, single/empty branches, published rules,
version-bound advisory evidence, invalid assignments and exact execution
confirmation. Repeated generation exposed a manifest self-reference: the old
`artifact_manifest.json` was included before being overwritten. It is now
excluded, and all references are checked on both generations in the regression
test. Reports: workspace `outputs/Task_Assignment_Verification_20261020/`.
At that checkpoint, the separate scientific-handoff suite reported 2 passed, 2
failed (the baseline message mismatches below), and 2 skipped. These counts do
not establish live EDA-to-model execution or scientific adequacy.

Initial 2026-10-20 refactor verification: 52 passed, 6 skipped across
`test_dispatch_context_builder`, `test_context_builder`, `test_clinical_dispatch`,
`test_clinical_questions_dynamic`, `test_animal_pk`, and `test_eda_disabled`.
The 13 new synthetic cases cover isolated assignments, typed scientific evidence
and method dependencies, question edits, changed inputs during assembly and
consumption, existing PK input compatibility, and the canvas handoff check.
The six skipped legacy integration cases require retired EDA fixtures.

An additional `test_scientific_handoff` run found two existing error-message
regex mismatches in the rule-publication tests. Both reproduce with all modified
tracked Python modules loaded from Git HEAD: the expected `scientific_context`
text differs from `The rule pack belongs to a different effective context.`
The changed input is rejected in both versions. The test assertions have since
been repaired as recorded above; rule-publication behavior remains unchanged.

Synthetic tests cover metadata routing independent of filenames, retained source boundaries, held-out/human input rejection, changed-file detection, pending-review blocking, signature-bound question confirmation and branch-specific requirements. A separate synthetic command-line run exercises LangGraph → Prefect → Snakemake without granting approval to actual research data.
