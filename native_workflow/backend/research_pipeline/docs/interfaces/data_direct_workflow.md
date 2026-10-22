# Data assessment and human review

Production entry point: `python -m research_pipeline.data_direct_workflow`.

The sequence is **Coverage → Necessity recommendation → English human summary → human decision**. Completed extraction and DR are reused. Pass `--reuse-coverage <accepted coverage.json>` to skip the Coverage model call as well; the main, DR and source-view references must match.

## Stage responsibilities

- **Coverage:** compare permitted data with the existing DR fields and conditions. Preserve study, species, matrix, regimen and source identity. Do not add requirements, select methods, recommend experiments or run downstream work.
- **Necessity:** explain the impact of recorded shortages and recommend next actions. Give an aggregate `PASS`, `CONDITIONAL_PASS` or `NOT_PASS` opinion plus five separate action decisions: model-based animal PK, PD index comparison, PD target estimation, optional NCA and later PTA. Each gives readiness, exact source scope, a concrete finding and one next step. Each issue distinguishes a current requirement, analysis-specific limitation, future dependency, optional improvement or unresolved question. A positive opinion for input preparation does not imply readiness to fit a model.
- **Human summary:** a dedicated, bounded English prompt summarizes the accepted Necessity assessment. It cannot change the recommendation or add an audit, requirements or methods. It presents the three primary action decisions as a short table and mentions NCA/PTA in one short note. Per-action readiness cannot change during summarization. Source scope is displayed verbatim from Necessity. The full gap mapping stays in details rather than being repeated in the short table.
- **Human decision:** the reviewer accepts, requests changes or rejects the assessment. The model opinion is never substituted for this decision. No downstream modeling starts automatically.

Model-based animal PK remains the priority. NCA is an independent alternative, not its prerequisite. PD index, target estimation and PTA retain their own stage-specific dependencies. Unresolved support does not establish confirmed absence. New-data advice remains conditional on targeted search and action-specific necessity. Rules and their conditions/exceptions remain unchanged. Human/Horse measurements and restricted benchmarks remain excluded.

Necessity uses the provided local method profiles; it does not browse, reread whole datasets, rewrite Coverage/DR/Rules or invoke another Coverage loop. The summary consumes only the scoped assessment and grouped advice, without the raw data or method library.

## Execution and outputs

Explicit provider/model: Codex `gpt-6-sol`. There is no aggregate run limit; individual transport calls retain their timeout. Requested and reported served identity are recorded separately. An unreported served model is unknown, not verified.

Use a fresh output directory after code or input changes. Exact accepted calls can be reused; failed attempts are retained and never silently retried. Synthetic and real outputs cannot be interchanged.

```powershell
$env:CTXCOMP_MODEL_PROVIDER='codex'
.venv-context/Scripts/python.exe -I -X utf8 -m research_pipeline.data_direct_workflow --plan <plan.json> --source-view <source_view.json> --main <main.json> --local-mp <local profiles.json> --out <new output directory> --reuse-coverage <accepted coverage.json>
```

`--build-only` prepares the next request without dispatching a model. `--review-state` selects the existing workbench state directory; the default is `outputs/workbench_state`.

Artifacts include `necessity/necessity.json`, `human_summary/summary.json`, `report.json`, detailed `report.html`, `human_gate.json`, requests, raw responses, hashes, timings and usage. Reused Coverage stays at its original location and is referenced directly. The human-facing page is `/data-review/{id}`. Full original JSON is available under the collapsed evidence section.

The gate uses the existing LangGraph review controller and binds all displayed artifacts, summary, main, DR, source view and local method profiles to an exact review signature. Changed inputs or outputs invalidate review. Real completed runs stop at `AWAITING_HUMAN_REVIEW`; named, confirmed human submission is required. Existing paused Canvas flows are untouched.

Historical Necessity v1 artifacts and `run_legacy` remain available for replay. Fresh production runs use the v3 action-specific recommendation and short decision table. V1/v2 remain historical replay formats. Historical Chinese source text and quotations are retained verbatim as evidence; all new reviewer-facing prose is English.

For summary-only correction, pass both `--reuse-coverage` and `--reuse-necessity` with verified accepted results. Only the summary model is called. Version 2 summaries have at most six issue groups and 650 prose words. Preserve the distinction between input readiness to begin fitting and later evaluation of fitted-model performance. Superseded review records retain their audit history and original files but cannot accept a new decision.


## Concise decisions (v3)

The main review table has three rows: model-based animal PK, PD index comparison and PD target estimation. Each row shows `Analysis / source scope | Data recommendation | Specific problem and impact | Next action`. Primary statuses are READY, CONDITIONAL, NOT_READY or NOT_ESTABLISHED; PTA may be LATER. Aggregate PASS cannot conceal a conditional or held primary action.

Model structure selection, fitting, identifiability and predictive checks are work for the modeling stage, not missing input data. Human approval is an independent workflow gate. Uncertainty about rabbit evidence must not automatically stop unrelated rat/mouse work. Each detailed next_action names one action consistent with its impact.

Necessity prose is bounded at 1,100 words while copied source evidence remains complete. The short summary prompt targets 170–220 words and enforces at most 250 generated prose words; the UI also shows original source scopes verbatim. Full detail mappings are preserved. Concrete source conflicts and input gaps take priority over generic cautions. No additional Coverage audit is added.

The active authoring prompt is `research_pipeline/data_necessity_prompt.py`; it adds measured-quantity grouping, retention of distinct within-field conflicts, source-subset qualification and explicit word budgeting. The underlying v3 contract stays immutable for accepted-result replay. A frozen prepared Necessity request can be resumed only when its actual Coverage, main and local MP references match the run. Targeted corrections bind the previous request and raw draft rather than repeating the source-data review.
