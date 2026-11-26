# EDA human review examples

Both cases start from mapped, blinded `source_tables.json` inputs. The three-section runner completed with R/ggplot2 figures. Human review is pending.

| Case | Study design | EDA gallery | Report archive |
| --- | --- | ---: | --- |
| [DBG01](DBG01/README.md) | Six horses, one IV dose per horse, 66 samples | 19 figures | [Download DBG01 report](DBG01/DBG01-report.zip?raw=true) |
| [DBG03](DBG03/README.md) | The same six horses on two occasions, three IM doses and one IV dose, 196 samples | 53 figures | [Download DBG03 report](DBG03/DBG03-report.zip?raw=true) |

Extract the selected ZIP and open `index.html`. Use `report.html` for the individual questions and `figures/index.html` to inspect all plots. The archive includes the mapped inputs, section JSON, coverage, frozen rules, and the modeling handoff. `run_record.json` retains source, rule, code and result hashes. Machine-specific paths in the public run and publication metadata were replaced with portable paths or a local-runtime label.

## Human review rules

- [Shared rules s1.0](../../tools/eda/rules/EDA_shared_rules_s1.0_consolidated_20261125.md)
- [Absorption r4.4](../../tools/eda/rules/EDA_absorption_rules_r4.4_consolidated_20261125.md)
- [Distribution r1.6](../../tools/eda/rules/EDA_distribution_rules_r1.6_consolidated_20261125.md)
- [Elimination and metabolism r1.2](../../tools/eda/rules/EDA_elimination_metabolism_rules_r1.2_consolidated_20261125.md)

## Review checklist

1. Compare animal ID, route, occasion, timing and dose units with `source_tables.json` and the coverage record.
2. Open the cited plots and check that each conclusion uses the matching animals, times, units and sampling window. Verify that the stated evidence supports the answer status.
3. Check that proposed mechanisms and model structures remain hypotheses and that the report identifies missing evidence. Flag any conclusion that exceeds what the measurements support.
4. Record any finding with the case, section, study, question and source or figure. State the correction and which conclusion it changes.

## Rerun either example

Extract the archive and use its case folder as the input to the [standalone EDA command](../../tools/eda/README.md). Use a new output folder. These examples cover descriptive EDA from mapped inputs. The exploratory exposure summaries and model suggestions leave final parameter estimation, model selection and scientific sign-off to downstream work.
