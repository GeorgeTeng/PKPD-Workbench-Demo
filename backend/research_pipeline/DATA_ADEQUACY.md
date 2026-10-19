# Dynamic initial data adequacy

## Scope and execution

`POST /ui-api/workflow/sessions/{session}/nodes/adequacy/start` starts the registered adapter after Context approval. An execution failure can be retried through the same endpoint; the UI offers Retry data adequacy. Original context and decisions remain immutable. A linked downstream job imports the approved `main.json` byte-for-byte unless an explicit user scope amendment is present. An amendment creates a new effective Context; the approved original, exact before/after changes, user instruction, signature and parent job remain recorded. Publishing collects both jobs' execution records.

LangGraph resolves scope, calls Prefect, and reads structured diagnostics. Prefect invokes Snakemake with zero automatic retries. Snakemake executes:

`reviewed_context → adequacy_inventory → adequacy_assessment → adequacy_review`

The first model call derives task-specific requirements from all scientific main fields. The second separately checks every task, requirement and context scalar path. Schema, request hashes, complete checklists, exact quotations, file hashes and contradictory PASS decisions are checked deterministically. These checks do not prove semantic correctness. Both responses and event logs are retained; no LLM response means no release.

## Input boundary

- Approved main.json, its reviewed artifact signature and LangGraph approval.
- Registered attachment references and hashes.
- For DATA_CANDIDATE and MODEL_CATALOG CSV/XLSX files: table titles, headers, locations and candidate row counts. Counts are not animal counts or independent observations.
- REFERENCE_ONLY content is never parsed for this module. Body values, published estimates and human validation outcomes are not sent to the models. Other document formats remain registry-only and are reported when a structural adapter is missing.
- Availability claims in main.json and filenames cannot establish data availability.

## Outputs

- `adequacy.json`: project tasks/estimands, species, endpoint/window, units, exposure basis, each requirement's provenance, applicability, timing, evidence, status, missing materials and review findings.
- `evidence_gaps.csv` and `report.md`: actionable reasons and needed materials.
- `qc_context.json`: only QC/model-preparation requirements, verified data/supporting-file references and report/upstream references. No full proposal copy.
- `inventory.json`, `assessment.json`, model requests/responses, telemetry, Snakemake contracts/receipts and LangGraph trace: audit evidence.

Each requirement is assigned BEFORE_QC, BEFORE_MODELING, BEFORE_VALIDATION or BEFORE_SIMULATION. Proposed methodological requirements are labeled separately from explicit project requirements. Project rules are not rewritten.

## Meaning of statuses

SUFFICIENT_FOR_DEFINED_SCOPE authorizes entry to QC only. Missing later-stage information remains listed. Precision is NOT_CALCULABLE until appropriate quantitative assessment; fit_ready and human_prediction_validated stay false.

INSUFFICIENT identifies currently missing required inputs. NOT_CALCULABLE identifies unresolved interpretation or assessment issues. Neither can unlock QC merely by clicking Approve. Request a study revision with additional data, corrected definitions or narrowed scope, then reassess. A nonblocking, valid PASS assessment can be technically verified without an extra human signature. Scientific questions enter the existing LangGraph interrupt.

Starting QC creates a server-side gate bound to the adequacy artifacts. The source-preparation executor verifies it, the report and source hashes. Calling its Snakemake target directly without that gate fails. Fresh upload jobs stop at Context so they cannot bypass adequacy.

## Boundaries still open

This adapter inspects initial completeness; it does not clean observations, choose BLQ handling, estimate sample precision, fit PK/PD or validate human translation. Source splitting still ends at field-mapping/scientific-QC review where no approved preparation plan exists. Unsupported downstream modeling/EDA adapters remain explicit gaps. Broad selective rerun/caching is deferred.

The reusable backend dynamically generates task contracts and mappings using registered executors. New scientific algorithms require a tested adapter; the LLM cannot silently install an algorithm or change acceptance criteria.

## Validation

Synthetic tests exercise dynamic scope, exact evidence/checklist validation, source mutation, held-out-value isolation, empty/catalog-data rejection, a real LangGraph human checkpoint, file contracts/receipts and QC gate enforcement. They do not measure LLM scientific accuracy. See `outputs/Adequacy_Adapter_Check` for the live-run and UI checks.

## Checklist contract fix and explicit scope amendments

The model receives scientific Context without `/version` or registered file bodies. `required_context_paths` generates the allowed path enums and exact checklist length in the response schema; the validator enforces the same list, unique coverage and actual evidence quotations. Task-check IDs and requirement-check IDs have independent enums. Extra/missing/duplicate entries raise MODEL_CHECKLIST_MISMATCH, with structured validation_details and a clear message that this is not missing research data. Rejected outputs are never edited into acceptance.

`POST /ui-api/workflow/sessions/{session}/scope-amendments` accepts context_signature, instruction, submitted_by, confirmed=true and changes[{path,before,after}]. It requires a valid Context approval, exact original values, scientific scalar paths only, no running adequacy and no started downstream nodes. Version, file roles/paths and attachments cannot be altered through this endpoint. A superseding amendment is a complete patch against the original approved main; prior versions remain recorded. This targeted clarification mechanism does not implement general selective rerun/caching.

The next adequacy run applies the confirmed amendment, generates B1/main.json and context_provenance.json, and passes the effective fields to both LLM stages. Workflow rule review and downstream QC use the same effective rules. The UI displays confirmed changes and exposes effective_main.json, context_provenance.json and scope_amendment.json alongside completed outputs. Scope confirmation never signs scientific results or turns REVISE into PASS.
