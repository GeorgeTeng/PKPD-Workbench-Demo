# Native PK/PD workflow — source snapshot with absorption EDA

This directory retains the 22 October base with subsequent EDA source and presentation revisions. The historical base is available at commit `2b50eeb0db2f8c8930a236699c9d5a76427e290c`; current files and hashes are recorded in `native_source_manifest.json`. Source publication does not regenerate or approve historical evidence packets.

This directory preserves the current native Compression, Data, EDA, ContextBuilder, Rules and downstream handoff implementation. It is separate from the repository-root demonstration application, whose lightweight Data behavior and disabled downstream execution remain unchanged.

## EDA implementation and review

The [PMB r4.3 rerun](../validation/pmb_absorption_r43/README.md) documents the current EV checkpoint. Use the [standalone EDA entry](../eda/README.md) to open the portable package or rerun absorption from admitted tables. The report organizes nine questions per study and shows the source observations, scientific assumptions and reasons a comparison was withheld.

To generate the absorption section alone, use a **new working copy** of a qualified EDA run directory containing `source_tables.json` and, when available, `dose_normalization_assessment.json` and the linked EV plots. From `native_workflow/backend/research_pipeline`, run `python -m research_pipeline.eda_absorption <run-copy> --attach`. Set `PKPD_RSCRIPT` to Rscript and use an R library containing ggplot2 and jsonlite; the output records whether R or the matplotlib fallback rendered the figures. Open `absorption/index.html` and verify `absorption/absorption.json`: an EV exit status alone does not prove the section was produced. Keep the original run intact because changing an artifact invalidates its manifest.

See the main [EDA guide](../README.md#exploratory-data-analysis-eda) for EP/EC/EV/EI/ER responsibilities, figure categories, dose-normalization decisions and current verification limits. The source revision combines the [23 October intake safeguards](../docs/eda_revision_20261023.md), [category correction](../docs/eda_categories_20261026.md) and [25 October dose-normalization implementation](../docs/eda_dose_normalization_20261025.md).

`eda_figure_review_ui.render` delegates to `eda_review_portal.build`:

- Home: handoff summary, review status, category previews, explicit dose-normalization assessments and an audit link when that audit is supplied.
- Category pages: full-size figures, identifiers, captions, source details and search. Protein binding appears under Supporting context.
- `review_overview.json`, when supplied, must match the current packet digest. Original findings and unresolved restrictions remain accessible.
- Page generation does not run calculations, plotting, models or approval. Derived figures require the registered rendering and verification path.

The latest local package has **58 source tables and 107 figures in five categories**: 75 PK profiles, 11 PD endpoints, 6 exposure–response index panels, 5 time-kill panels and 10 supporting-context panels. It includes the mouse SC five-dose `C(t)/Dose` supplement. The former 106-figure package remains historical.

The implementation requires eligible source-bound dose-normalized views and records reasons when they cannot be drawn. It preserves raw values, dose basis, units, source restrictions and explicit metadata gaps. Unknown datasets require verified dose/comparison metadata; source compatibility is not inferred automatically.

The [verification record](../validation/eda_dose_release_20261025/checks.json) documents 182 passing publication tests, one deselected real-R test and the separately verified local R supplement. The [15-section coverage summary](../validation/eda_dose_release_20261025/scientific_coverage_summary.json) retains outstanding source and matching limitations. Full current Context → Data → EDA acceptance and independent/Human approval remain pending.

Research data, images, model requests/responses and original documents are **not included** in this source publication. Generate review pages from your own qualified local handoff; the repository does not contain a transferable approval.

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
