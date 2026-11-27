# EDA human review examples

Both cases start from mapped, blinded `source_tables.json` inputs. The three-section runner completed with R/ggplot2 figures. Human review is pending.

| Case | Study design | EDA gallery | Online report | Offline archive |
| --- | --- | ---: | --- | --- |
| [DBG01](DBG01/README.md) | Six horses, one IV dose per horse, 66 samples | 19 figures | [Open HTML](https://georgeteng.github.io/PKPD-Workbench-Demo/DBG01/) | [Download ZIP](https://raw.githubusercontent.com/GeorgeTeng/PKPD-Workbench-Demo/main/examples/eda-review/DBG01/DBG01-report.zip) |
| [DBG03](DBG03/README.md) | The same six horses on two occasions, three IM doses and one IV dose, 196 samples | 53 figures | [Open HTML](https://georgeteng.github.io/PKPD-Workbench-Demo/DBG03/) | [Download ZIP](https://raw.githubusercontent.com/GeorgeTeng/PKPD-Workbench-Demo/main/examples/eda-review/DBG03/DBG03-report.zip) |

Open the HTML report to browse online. For offline review, extract the ZIP and open `index.html`. Use `report.html` for the individual questions and `figures/index.html` to inspect all plots. The archive includes the mapped inputs, section JSON, coverage, frozen rules, and the modeling handoff. `run_record.json` retains source, rule, code and result hashes. Machine-specific paths in the public run and publication metadata were replaced with portable paths or a local-runtime label.

## Study review guides

Start with the Study review guides. They explain what to look for in the figures and how to review each study question. Use the linked active rules to check the calculation and display criteria applied in the example runs.

| Section | Study review guide | Active rules used in the examples |
| --- | --- | --- |
| Absorption | [Read guide r4.3](guides/EDA_absorption_rules_r4.3_review_guide_20261124.md) | [Rules r4.4](../../tools/eda/rules/EDA_absorption_rules_r4.4_consolidated_20261125.md) |
| Distribution | [Read guide r1.5b](guides/EDA_distribution_rules_r1.5b_reviewed_20261124.md) | [Rules r1.6](../../tools/eda/rules/EDA_distribution_rules_r1.6_consolidated_20261125.md) |
| Elimination and metabolism | [Read guide r1.1](guides/EDA_elimination_rules_r1.1_reviewed_20261123.md) | [Rules r1.2](../../tools/eda/rules/EDA_elimination_metabolism_rules_r1.2_consolidated_20261125.md) |

[Shared rules s1.0 · Reviewer guide](guides/EDA_shared_rules_s1.0_reviewer_20261126.md) covers all three sections. [Read online](https://georgeteng.github.io/PKPD-Workbench-Demo/shared-rules/). The [rule manifest](../../tools/eda/rules/rules_manifest.json) records the current bindings and the Git locations of superseded drafts named in the rules.

The updated elimination Q1 shows the semi-log terminal phase in DBG01 and DBG03. Both cases have one dose level per route.

## Review checklist

1. Compare animal ID, route, occasion, timing and dose units with `source_tables.json` and the coverage record.
2. Open the cited plots and check that each conclusion uses the matching animals, times, units and sampling window. Verify that the stated evidence supports the answer status.
3. Check that proposed mechanisms and model structures remain hypotheses and that the report identifies missing evidence. Flag any conclusion that exceeds what the measurements support.
4. Record any finding with the case, section, study, question and source or figure. State the correction and which conclusion it changes.

## Rerun either example

Extract the archive and use its case folder as the input to the [standalone EDA command](../../tools/eda/README.md). Use a new output folder. These examples cover descriptive EDA from mapped inputs. The exploratory exposure summaries and model suggestions leave final parameter estimation, model selection and scientific sign-off to downstream work.
