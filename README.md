# Translational PK/PD Workbench Demo

A Windows research workbench for file intake, project Context and Rules, and source-preserving Data preparation. The source checkout includes standalone exploratory data analysis (EDA) for prepared PK study tables.

## EDA human review

| Reviewer guide | Read |
| --- | --- |
| Shared rules s1.0 | [Online guide](https://georgeteng.github.io/PKPD-Workbench-Demo/shared-rules/) · [Markdown](examples/eda-review/guides/EDA_shared_rules_s1.0_reviewer_20261126.md) |
| Absorption r4.3 | [Study review guide](examples/eda-review/guides/EDA_absorption_rules_r4.3_review_guide_20261124.md) |
| Distribution r1.5b | [Study review guide](examples/eda-review/guides/EDA_distribution_rules_r1.5b_reviewed_20261124.md) |
| Elimination and metabolism r1.1 | [Study review guide](examples/eda-review/guides/EDA_elimination_rules_r1.1_reviewed_20261123.md) · [Updated EM-1a rules](tools/eda/rules/EDA_elimination_metabolism_rules_r1.2_consolidated_20261125.md#e011-data-card-figure-set-and-answer-status) |

| Case | Study design | Report |
| --- | --- | --- |
| DBG01 | Single IV dose in six horses | [Open HTML](https://georgeteng.github.io/PKPD-Workbench-Demo/DBG01/) · [Case summary](examples/eda-review/DBG01/README.md) |
| DBG03 | Repeated IM and single IV dosing in six horses | [Open HTML](https://georgeteng.github.io/PKPD-Workbench-Demo/DBG03/) · [Case summary](examples/eda-review/DBG03/README.md) |

Both examples completed descriptive EDA. Human scientific review is pending. [Reviewer checklist, ZIP downloads and rerun instructions](examples/eda-review/README.md)

## Exploratory data analysis (EDA)

<a id="current-eda-implementation"></a>

Start from a case directory containing `source_tables.json`. The standalone runner writes a study report at `index.html`, a figure gallery, input coverage and a modeling handoff. [Run or resume EDA](tools/eda/README.md) · [Run independent self-review](eda/review/README.md)

The case reports use shared rules **s1.0**, absorption **r4.4**, distribution **r1.6** and elimination/metabolism **r1.2**. The run record binds the input, rules, code and results by hash. [Active rule manifest](tools/eda/rules/rules_manifest.json)

For the portable PMB absorption report or a released native Data handoff, use the separate absorption workflow. [PMB absorption guide](eda/README.md)

## Start on Windows

1. Download the portable Windows ZIP from [Releases](https://github.com/GeorgeTeng/PKPD-Workbench-Demo/releases/latest). Extract it to a short, writable path such as `C:\PKPD`, then open its `demo` folder.
2. Double-click `START_DEMO.cmd` and open [the local workbench](http://127.0.0.1:8772). Use `STOP_DEMO.cmd` to stop the server.
3. Import PMB, Meropenem, Voriconazole or Imidocarb through **File intake**, then run Context and Data preparation through the review checkpoints. [Example input manifest](examples/inputs/manifest.json)

The portable ZIP includes Python. Live Context, Rules and Data labeling use a configured model provider. The default uses an authenticated Codex CLI on PATH. The local Knowledge & context workspace can be browsed without model calls.

The browser demo runs through Data preparation. Its EDA and PK views display recorded examples. [Recorded Data runs](examples/acceptance/index.html)

## Verify

- [Standalone EDA and reviewer checks](validation/eda_rereview/README.md) · [GitHub Actions workflow](.github/workflows/eda-safeguards.yml)
- [Fresh model-backed Data acceptance procedure](docs/fresh-acceptance.md)
- [Native workflow snapshot](native_workflow/README.md) · [Changes](CHANGES.md)

For a source checkout, use Python 3.12, install `requirements-demo.txt` and both backend packages in editable mode, then run `python -I -B app.py` from the repository root. [Launch options and API reference](https://github.com/GeorgeTeng/PKPD-Workbench-Demo/blob/c34329e8e9f766e70787bf3322cff684c78cae77/README.md#api-locations-and-configuration)
