# Animal PK agent controls

## Open the controller

In the main workbench, open **Animal PK → Open agent controls**. The controller opens separately and retains the study ID. Select a species and source analysis; species are taken from validated metadata.

The main path is:

**Species scope → PK data check → Candidate model review → parallel 1C / 2C / conditional 3C → Model comparison → Human model selection → Species PK report.**

The cross-species report combines reviewed species handoffs. It does not fit human PK.

## Zoom into a model

Each model contains four fresh agent tasks:

1. Select the next reviewed configuration.
2. Check the explicit nlmixr2 estimation configuration.
3. Run trusted R fitting code and interpret its internal self-checks.
4. After all permitted configurations have been evaluated, summarize all attempts.

The controller iterates through the explicit configuration list, retaining multiple eligible results. Failed checks cannot be promoted by model prose. When no permitted configurations remain, the result explains the unresolved findings. Additional configurations require a new reviewed contract and a fresh attempt.

Each invocation creates a new ephemeral model process with a new request, response and execution record. No previous conversation is resumed. Only that task's contract, assigned data, applicable rules and verified upstream outputs enter its prompt. A container or deterministic graph transition is not counted as an LLM invocation.

## Execution layers

- **LangGraph:** task state, candidate loops and signature-bound human review interrupts.
- **Prefect:** job scheduling and run status.
- **Snakemake:** file dependencies, independent candidate branches, CPU resources and receipts.
- **R / nlmixr2:** numerical estimation; no LLM-authored R or shell commands are executed.

The controller supports run, parallel candidate execution, pause and a new attempt. Pausing interrupts active work and preserves completed evidence; retrying creates a new run, not an exact-line continuation. No 600-second model deadline is added. Model and R processes retain five-minute local-liveness heartbeats; these do not prove remote model progress.

## Current fitting contract

Use the **Qualification** tab to inspect the template. Supply normalized data references and explicit configurations, then confirm data identity, dosing, units and the permitted configuration set. This confirmation is distinct from final model selection.

The connected adapter currently supports:

- Individual longitudinal animal data, IV bolus or IV infusion.
- 1-, 2- or 3-compartment analytical models in nlmixr2.
- FOCEI, explicit initial values and bounds, optional configured diagonal random effects.
- Additive, proportional or combined residual error.
- Time in hours, dose in mg, concentration in mg/L; free/total and matrix remain explicit.

SC/PO, summary/composite observations, unresolved BLQ and unknown doses need a suitable qualified adapter. Group means cannot be relabeled as individual observations. Known source matrix and free/total definitions cannot silently change.

Normalized event JSON contains `metadata` and `records`. Records use `ID`, `TIME`, `DV`, `AMT`, `EVID`, `RATE` and `CMT`. The template also requires source evidence for identities, dose events and transformations. Saving a contract never fits or accepts a model.

## Outputs and review

### Species workspaces and file inspection

The primary UI navigation is one workspace per species. Each workspace contains its registered source datasets under **Data sources**, with a compact overview and the existing agent controls. A source curve is a provenance container, not an automatic scientific modelling unit. The current execution source remains explicit because the fitting contracts still require source-level qualification; the interface does not silently pool data.

Combining dose cohorts for a shared fit requires a reviewed analysis definition. Different study populations, routes, matrices, free/total definitions and individual versus summary observations must be qualified before any joint fit. A species workspace may therefore contain several justified analysis groups and competing models.

Context views show the task, scope, assigned references and rule counts, with the full contract available to open or download. File views use collapsible folders, and long labels are shortened only on screen. Verified output files can be previewed or downloaded as original bytes. The main workbench adds role-based display folders, file search, full-file opening, and compact input/output contracts. Display folders do not change execution paths or scientific routing. Templates, generated files and review status remain separately identified.

Each run retains JSON requests/responses, actual provider calls, R code, numerical results, parameter estimates, predictions, diagnostics and logs. Downloadable files are restricted to the run's verified artifact manifest.

Comparison uses matched observation sets, response scales, exposure basis, matrix and likelihood definitions. FOCEI metrics are explicitly approximate and are not mixed with exact ML. Engine AIC/BIC remain visible for diagnostic inspection even when a model is ineligible for ranking. Numerical eligibility is not biological adequacy or translational validity.

Human selection is a LangGraph interrupt bound to the current comparison signature. Approval does not require a comment; requested changes must say what needs revision. Only eligible models can be selected. Changed upstream evidence invalidates the previous review. This is an integrity safeguard, not an optimized partial-rerun system.

Species reports produce `species_handoff.json` containing the human-selected parameters and evidence references. The final report produces `animal_pk_handoff.json` containing the reviewed species handoffs. The values are copied from verified numerical results, never from generated narrative. Human prediction remains unvalidated.

## API

All routes below are relative to `/ui-api/workflow/sessions/{session}/animal-pk`.

| Route | Purpose |
|---|---|
| `GET /control` | Stable plan, agent eligibility, blockers and run history |
| `POST /control/plan` | Include conditional 3C candidates with a reason |
| `POST /agent-runs` | Start a fresh scoped agent or candidate loop |
| `POST /candidate-runs` | Start independent candidate loops in parallel |
| `GET /agent-runs/{job}?agent_id={id}` | Inspect the exact agent, including internal loop invocations |
| `POST /agent-runs/{job}/pause` | Request interruption of this run |
| `GET /qualifications/{candidate}` | Read the contract template and current qualification |
| `PUT /qualifications/{candidate}` | Validate and save an explicitly reviewed fitting contract |
| `GET /reviews?species={species}` | Inspect current comparison and human review requirements |
| `POST /reviews/{species}` | Submit a signature-bound human decision |

## Verification evidence

- Regression checks: `outputs/Animal_PK_Control_Verification/final-tests.xml`.
- Actual R bolus, infusion, 2C and 3C checks: `outputs/Animal_PK_Architecture_Verification/nlmixr2-final`.
- Real LangGraph → Prefect → Snakemake → model provider → R pilot: `outputs/PK_Agent_FinalPilot_20260922`.
- Live read-only desktop/mobile checks: `outputs/Animal_PK_Control_UI_Verification/live-browser-verification.json`.

The real provider pilot used synthetic data: four fresh model calls and one numerical fit. Covariance/gradient warnings led to `NEEDS_REVIEW`; no model was accepted. Passing software tests demonstrates execution and guard behavior, not scientific model adequacy. The live project's animal fits were not started by these verification scripts.
