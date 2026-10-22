# Native PK/PD workflow — source snapshot, 22 October 2026

This directory preserves the current native Compression, Data, EDA, ContextBuilder, Rules and downstream handoff implementation. It is separate from the repository-root demonstration application, whose lightweight Data behavior and disabled downstream execution remain unchanged.

## Latest EDA presentation

`eda_figure_review_ui.render` delegates to `eda_review_portal.build`:

- Home: readable handoff summary, remaining limitations, category previews.
- Category pages: every full-size figure in that category, identifiers, explanations, source links and search.
- No ZIP/download interface. No data processing, plotting or model call is triggered by page generation.
- `review_overview.json`, when provided, must match the current packet digest. Full original findings remain accessible.
- Existing Rules, source rows, censoring, source conflicts and approval gates remain authoritative.

The local review package contained 58 datasets and 106 figures in six categories. Its data, images, individual model requests/responses and original documents are **not included** in this code publication. Generate a review from your own qualified local handoff; the repository does not contain a transferable approval.

## Context and retrieval selection

Use the native **ContextBuilder 2.1** entry points and versioned routes in this snapshot. The root demo also retains ContextBuilder 2.1 and its branch handoff adapter; these are distinct adapters with different callers, not interchangeable files.

The existing repository-root `rag_candidate/` corresponds byte-for-byte to the local **RAG v2.0** baseline. It remains optional methodological background, not authoritative project Rules or scientific acceptance. Later experimental retrieval/context strategies are compared in [the version decision](../docs/version_selection_20261022.md). No experimental strategy is activated by this publication.

## Running focused checks from source

Use Python 3.11+ and the dependencies declared in the two backend packages. From this directory in PowerShell:

```powershell
$env:PYTHONPATH="$PWD\backend\research_pipeline;$PWD\backend\context_compression"
python -B -m pytest -q -p no:cacheprovider backend/research_pipeline/tests/test_context_builder.py backend/research_pipeline/tests/test_eda_readable_headings.py backend/research_pipeline/tests/test_eda_timekill_annotations.py backend/research_pipeline/tests/test_binding_headings.py
python -B -m research_pipeline.eda_framework
```

This is a source distribution, not a newly validated portable installer. Scientific execution still requires local input qualification, dependencies and explicit gates. Some existing R scripts reference a workstation R-library path; configure your R libraries locally. Optional Pillow produces small review thumbnails; without it, the review uses original image files as previews.

Source-derived real-data examples and the real-data `eda_quality_cases.json` fixture remain local. Tests requiring those resources are not reproducible from this export alone. Synthetic tests and code contracts are included. `native_source_manifest.json` identifies the unmodified upstream files; publication-only additions are documented separately.
