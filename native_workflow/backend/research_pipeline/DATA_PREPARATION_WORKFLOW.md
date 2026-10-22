# Data preparation & QC adapter

## Execution

The Workbench creates a new `reviewed_data` job from the artifact-bound adequacy
approval. It preserves the approved Context and all earlier jobs. LangGraph reads
references and dispatches Prefect; Snakemake executes:

`reviewed_data → partition_sources → clean_and_assess → human review`

No LLM edits numeric observations. The earlier independent adequacy review must
be valid and PASS. An approved `NOT_CALCULABLE` assessment may enter **diagnostic
preparation only** to investigate partitions and mappings. Its original status
is retained. `INSUFFICIENT`, invalid reviews and changed files cannot enter.

## Inputs

- Approved adequacy node and its exact output signature.
- `qc_context.json`: requirements and source references, with hashes.
- Registered candidate CSV/XLSX data; supporting files stay registry-only.
- Optional versioned `preparation_plan.json`: table ranges and exact header maps.

The original workbook is never overwritten. Human/validation, published
model-derived/benchmark and permission-unknown tables are withheld before body
export. Table metadata, not filenames, governs candidate classification. This
is conservative workflow isolation, not an OS security sandbox or independent
verification of the paper. Classification requires scientific review.

## Outputs

| Artifact | Purpose |
| --- | --- |
| `data_report.json` (`main.json` alias) | Execution scope, counts, findings, missing materials, review scope |
| `normalization_manifest.json` | Dataset references and hashes |
| `normalized/T*.csv`, `.json` | Retained records, source cell coordinates, QC annotations |
| `normalized/T*.metadata.json` | Source, candidate role/species/matrix/record level, unknowns |
| `normalized/T*.quarantine.json` | Excluded values with original status and reasons |
| `partition_manifest.json` | Locators and reasons for withheld tables; no restricted body values |
| `data_dictionary.json` | Source headers, missingness and supported normalized fields |
| `cleaning_log.json` | Whitespace and explicit unit transformations |
| `issues.csv`, `report.md` | Reasons and required corrections for reviewers |
| `handoffs/{eda,pk,index}_context.json` | Only assigned dataset references; PENDING_HUMAN_REVIEW |

Quarantine retains BLQ, sampling failures, formulas, source errors, unresolved
numeric fields and censored time-kill observations. Zero is retained. Repeated
value patterns are flagged, never averaged/deleted. Wide animal labels remain
identity candidates. Group summaries/digitized means are not individual animals.
Whole-lung µg/g is not converted to mg/L. General columns without an unambiguous
mapping remain intact and are reported for review. Mixed mean±SD columns are
retained as source strings; they require a declared transformation before fits.

No universal sample-size cutoff is applied. Precision and human predictive
validity remain NOT_CALCULABLE/unestablished. QC does not calculate or rank
indices: the current index scope is fAUC/MIC, fCmax/MIC, fT>MIC. Later comparisons
need matched PD observations and compatible exposure definitions.

## API and corrections

Base: `/ui-api/workflow/sessions/{session_id}`

- `POST /nodes/prepare/start`: create a new linked job; never rerun compression.
- `GET /preparation-plan`: current mapping or downloadable template.
- `POST /preparation-plan`: save `{output_signature, plan, rationale, confirmed:true}`.
- `POST /nodes/prepare/start`: retry with the saved plan, preserving prior outputs.
- `POST /nodes/prepare/review`: existing artifact-bound LangGraph human review.
- `GET /nodes/prepare/artifacts/{name}`: download verified artifacts.

Example plan (use actual identifiers and exact source headers):

```json
{
  "schema_version": "1.0",
  "ranges": {},
  "tables": {
    "T0001": {
      "columns": {
        "time_h": "Time (min)",
        "concentration_mg_L": "Mean concentration (ng/mL)"
      }
    }
  }
}
```

Units must be explicit and dimensionally compatible. The plan cannot override
source permissions or waive scientific review. Corrections invalidate approval
for the new preparation attempt. A pending downstream handoff is not executable
authorization. The separate general EDA execution adapter is outside this change.
