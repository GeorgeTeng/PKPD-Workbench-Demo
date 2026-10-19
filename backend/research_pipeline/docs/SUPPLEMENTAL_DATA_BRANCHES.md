# Supplemental data branches

The Additional data panel adds a branch to a study without compressing its data into the proposal. It preserves the LangGraph → Prefect → Snakemake execution path. Numerical fitting does not run as part of this branch.

## Flow

Register files and destinations → clean/split → per-dataset metadata → QC/input adequacy → descriptive EDA → one human review → destination-specific handoff.

- Select Animal PK, PK/PD index, or Clinical interpretation (one or more).
- Supply CSV, rectangular XLSX tables with an explicit worksheet, or JSON records. Use the configuration editor for source-column mappings, endpoint/index definitions, dosing and evidence locators.
- Dataset roles and validated metadata govern compatibility. Filenames never select a destination.
- PK input checks reuse the current IV individual/population adapter requirements. Index checks reuse the Emax/Hill input contract. MIC, binding, PD observations and clinical evidence can be supplied as supporting tables; they are not promoted into matched exposure-response data.
- Unknown units, identities, model requirements and unsupported routes generate findings. No imputation or invented human exposure is performed.
- Corrections create a new branch, preserving the old branch and its findings. Only unaccepted branches may be superseded. Request changes keeps the target blocked; rejection explicitly disconnects that supplemental input.
- An already started downstream step requires a new study cycle. Selective reruns/result reuse are deliberately deferred.

## Actual output files

Each split dataset has `datasets/<id>.json`, `<id>.csv`, `<id>.metadata.json` and `<id>.quarantine.json`. The sidecar contains identity, units, record level, sampling design, source references, data hash and row summary. It remains a processing record marked PENDING; the separate signed handoff is the release authority.

The branch also generates:

- `prepared/preparation.json`: findings, changes and scoped input-adequacy assessment.
- `eda/eda.json` and PNG plots: linear/semilog PK, dose-normalized PK when doses are unambiguous, candidate-index scatter plots, or appropriate field-completeness summaries.
- `eda/feedback.json` and `feedback.md`: why release is blocked, affected datasets/targets, missing data/materials and review items.
- After human approval, `handoff_pk.json`, `handoff_index.json` and/or `handoff_clinical.json`, containing only compatible dataset references and a signed-review reference.

EDA does not automatically select compartment structure. AUC, terminal slopes and dose-proportionality estimates are not computed in this descriptive adapter. Input readiness is not proof of adequate sample size, model adequacy or predictive validity. Precision assessment requires a target parameter, precision/confidence specification and appropriate variability/design evidence.

## Review policy

File intake and result assembly use automatic technical verification. Adequacy/EDA may continue without another signature only when their processor explicitly reports sufficient scope, no findings and no need for human review; absence of a diagnostic report never counts as a pass. Scientific task definition, model-data release, clinical questions, model decisions and final clinical acceptance retain review gates.

The supplemental branch has one consolidated review after QC and EDA. Approval needs a reviewer and explicit confirmation; a comment is optional. Changes/rejection require a reason. Hard input errors cannot be approved away. Changed source/output bytes or review records invalidate the handoff.

## API

All endpoints are under `/ui-api/workflow/sessions/{session_id}` and use the existing same-origin/token controls.

| Endpoint | Purpose |
|---|---|
| `POST /supplements` | Register label, targets, datasets and optional supersedes branch ID |
| `POST /supplements/{branch_id}/start` | Execute preparation and EDA through the existing stack |
| `GET /supplements/{branch_id}` | Read status, datasets, findings, artifacts and review |
| `POST /supplements/{branch_id}/pause` | Stop this branch's active execution |
| `POST /supplements/{branch_id}/continue` | Continue an acknowledged pause |
| `POST /supplements/{branch_id}/review` | Artifact-bound human decision |
| `GET /supplements/{branch_id}/artifacts/{name}` | Verified artifact download |
| `GET /nodes/{target}/supplements` | Obtain approved, compatible supplemental input references |

Upload each file through `/pipeline/v1/attachments` first. Registration uses its returned upload_id; clients cannot submit arbitrary filesystem paths. See OpenAPI for request schemas.

Main-workflow prerequisites remain in force. General-purpose modeling adapters still require their separate integration; a released supplemental handoff does not automatically run a model or establish scientific acceptance.
