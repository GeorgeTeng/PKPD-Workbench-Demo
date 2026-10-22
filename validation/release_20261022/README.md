# Release verification — 22 October 2026

Scope: code/configuration/tests/aggregate summaries only. No original research data, EDA images, per-study plotted rows, source documents or model-call payloads are added by this release.

The latest EDA review locally retained 58 datasets and 106 figures in six category pages. Its home contains a concise summary and previews; all full-size figures live on secondary pages. Before publication, 630 internal links, exact category accounting, unchanged source/figure hashes and the native page-generation entry point were checked. Human review remains pending; the historical ER was not rewritten as PASS.

Fresh isolated source checks are recorded in `checks.json`. They do not constitute a full scientific workflow rerun, new ER, production RAG acceptance or validation of every historical test.

The code selection and excluded experimental successors are explained in [version selection](../../docs/version_selection_20261022.md).

Fresh checks: 122 native context/presentation tests, 3 synthetic portal tests and 46 demo dispatch/context tests passed. The demo suite skipped 2 retired-path cases. Revision14 passed 37 tests with 1 Windows symlink-privilege skip. Native Rules/reference validation passed. All 778 upstream snapshot files match their original SHA-256 values; original snapshot whitespace is intentionally retained. No full workflow/model rerun was performed.
