# Literature-assisted context and routing

The installed library contains 23 publications and 17 advisory evidence checks.
Translation role distinguishes animal-to-human PK prediction (7 papers), human-informed
PK translation, PD translation with human inputs, animal studies and methods. These are
publication counts, not counts of independent projects or validated PMB models.

## Execution boundary

1. Intake registers the package and marks held-out attachments.
2. Context compression reads the proposal only and produces the source-bound `main.json`.
3. The optional reference pilot snapshots the installed library. A fresh model call
   assesses each evidence check against this proposal.
4. A separate call proposes additions only to checks, conditional data requirements
   and uncertainties. A third call independently reviews the complete candidate.
5. Proposed `main.json`, `main_changes.json` and `main_review.json` stop for human review.
   This does not overwrite the source handoff or carry an old approval forward.
6. When the reviewed workflow later reaches adequacy, the enabled pilot assesses
   the effective context used by that run. Adequacy retains a hash-bound reference to
   the exact advisory handoff it consumed.
7. Clinical questions consumes that reviewed reference, not a newer mutable library.
   The full question draft shows proposed advice separately from source-derived answers.
   Branch contracts receive only the applicable stages and their cited sources:
   PK receives PK/human-PK suggestions; final interpretation receives validation advice;
   index receives explicitly index-scoped advice if provided. Earlier QC/EDA advice is
   retained in the question audit but is not forwarded indiscriminately.

Library 0.4.1 adds `allowed_steps` metadata for narrowly scoped evidence checks.
The PD linkage check targets `index`; both the applicability contract and proposed
revision validate that destination. Older library snapshots without this metadata
retain their original request contract and remain readable.

The current pilot does not design new clinical studies, authorize new rules, transfer
published fitted parameters or execute models. Missing metadata remains unresolved.
Clinical question defaults still require the existing project-specific confirmation.

## Search and audit

Curated source JSON cards are indexed in the local literature database. Indexing a
summary is not downloading a full paper or qualifying a model. The separate animal
model library retains six candidates, with PMB first and related compounds conditional.
Candidate eligibility and fitting release require their existing reviews.

The library expansion audit is in `outputs/PK_Translation_Expansion_20260923/`.
The new ZIP test is recorded in `test_run.json`; the authorized stop is after context
compression plus proposed literature revision, before adequacy and human acceptance.
