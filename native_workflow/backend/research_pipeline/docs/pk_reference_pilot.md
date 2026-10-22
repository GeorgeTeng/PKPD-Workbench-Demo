# Animal-to-human PK reference pilot

## Scope

This optional pilot checks a reviewed proposal against four source-linked cards.
It excludes clinical design, efficacy, safety, PBPK and numerical modeling. Its
outputs are proposed advice, never project rules, parameter permissions or proof
that a dataset exists. Proposal-only compression and the 3.0 `main.json` keys
remain unchanged.

The initial library contains four primary papers (apramycin, polymyxin B, and
opposing interspecies-clearance comparisons). Full-text passages were available
through the primary-page search index for the first two; the other two were
checked at abstract level. These access limits, source locators and uncertainty
about data/code availability are included in each source record. The four cards
are an adapted checklist, not validated universal PK standards.

## Execution and connections

```
Reviewed main.json + pinned reference library
                  |
      pk_reference_prepare (deterministic)
                  |
      pk_reference_review (fresh LLM call)
                  |
      schema + exact citations + coverage checks
                  |
      advisory reference_context.json
                  |
      existing adequacy assessment + independent review
                  |
      existing preparation -> EDA -> PK and review gates
```

LangGraph controls state and reads diagnostics, Prefect schedules the job, and
Snakemake executes file dependencies with receipts. Numeric work remains in the
existing scientific adapters. A successful pilot is `REFERENCE_ADVICE_ONLY`, not
scientific acceptance. The LLM receives proposal scientific fields and cards,
not attachments, data rows, human benchmark values or previous conversation.

There is no new mandatory human gate. Method adoption and scientific decisions
remain at existing gates. External advice has no authority to change the
proposal. Initial adequacy reassesses every proposed requirement and its timing.
Deferred human validation inputs must not automatically block animal QC.

## Interfaces

The main Context and Data adequacy panels link to
`/assets/pk-reference-pilot.html?session=<session_id>`.

API prefix: `/ui-api/workflow/sessions/<session_id>/pk-reference-pilot`

- `GET`: library, run status, model progress, report and artifact links.
- `POST /start`: run a new isolated assessment using the reviewed effective
  context (including the existing reviewed scope amendment if available).
- `POST /configuration`, body `{"enabled": true}`: add the pilot to the next
  Data adequacy run. This does not rerun or modify completed steps.
- `POST /jobs/<job_id>/pause`: stop the owned job tree at the existing runtime
  boundary. A new attempt is available from the Run button.
- `GET /jobs/<job_id>/files/<name>`: original input, result or audit artifact.

The standalone workflow spec uses `mode: pk_reference_pilot`, `main_ref`, an
optional `reference_library` file/hash reference, and target `pk_reference_pilot`.
The integrated `reviewed_context` spec uses `pk_reference_pilot: true`.

## Files

| Artifact | Purpose |
| --- | --- |
| `pk_reference_library.json` | Exact library snapshot pinned to this job |
| `pk_references/input.json` | Scoped main fields, cards, source evidence and immutable references |
| `pk_references/review/reference_report.json` | Per-card applicability, gaps, proposed action and exact citations |
| `pk_references/review/reference_context.json` | Only relevant advice for the existing adequacy agents |
| `pk_references/review/reference_report.md` | Human-readable findings and source links |
| `pk_references/review/audit/` | Actual request, response, model events and timing |

The handoff includes only selected cards and their sources. It cannot activate
rules. It is checked against the actual main, frozen library and retained model
assessment before consumption. Downstream QC continues to receive the existing
task-specific `qc_context.json`, not the complete literature library.

## Search and library updates

The existing online and local search adapters are reused:

```
python -I -m research_pipeline.pk_reference_pilot --discover "PUBLIC QUERY" --output candidates.json
python -I -m research_pipeline.pk_reference_pilot --discover "SEARCH TERMS" --provider local --state LIBRARY_STATE --output candidates.json
```

Only the explicit public query is transmitted for online retrieval. No private
proposal is converted into a public search. Search results stay candidate sources;
indexing or a citation count never promotes a rule. Update a versioned library
only after checking source passages, conditions, contradictory evidence and
limits. This pilot uses a curated seed; it does not implement unattended learning
or automatic promotion from search results to active rules.

## Verification boundaries

Contract tests cover invalid quotes, missing cards, dropped counter-evidence,
unexpected rule fields, stale requests, changed libraries, tampered handoffs,
out-of-scope output and the existing adequacy file chain. They establish software
behavior, not scientific sensitivity or LLM reliability. Real-project model runs
are stored separately from synthetic fixtures. Human review must still assess
whether the proposed scientific questions are sensible.
# Version 0.2: evidence-backed main.json revision

The library now contains ten publications and ten method cards, including three PMB
papers and a methodological reply. Access depth, uncertainty and the two BWC0977
corrections are recorded. The apramycin card corrects the old blanket one-compartment
summary: dog data supported two compartments, but the source used a simplification for
scaling. Human-binding requirements are explicitly compared with the project's holdout.

`POST /ui-api/workflow/sessions/{id}/pk-reference-pilot/start` accepts
`{"revise_main": true}`. The existing LangGraph → Prefect → Snakemake path then runs:

1. Pin the effective reviewed main and reference library.
2. Fresh applicability agent, with exact context/source citations.
3. Fresh revision agent, restricted to appending proposed checks, conditional requirements
   and uncertainties. Proposal facts, rules, availability and files are immutable.
4. Fresh independent review, with an exhaustive checklist and actionable failures.

Outputs live in `pk_references/revised`: `main.json` (v3.0), `main_changes.json`,
`main_changes.md`, `main_review.json`. Rejected candidates and provider logs are retained
but no final main is released on a failed independent review. Proposal and review model
calls are isolated and have separate requests, responses, diagnostics and receipts.

This creates a proposed revision, not an automatic change to a completed workflow.
The UI permits inspecting and downloading every artifact. Adoption requires review for
the new context; previous scientific approvals never transfer automatically. The existing
next-adequacy option still supplies reference advice and does not silently adopt a draft.
