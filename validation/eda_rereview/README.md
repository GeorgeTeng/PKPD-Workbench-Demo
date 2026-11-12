# EDA review verification, 11 November 2026

## Release safeguards

The reviewer preserves each quantitative statement in its original field. A request to change a measurement returns to the calculation or source owner. Each reviewed section needs its own rules, verified before a model call or cached response can be used. The calculation runner checks resumability before writing to an existing run. Distribution records systemic IV observations separately from the profiles eligible for phase analysis.

The [acceptance command](check_safeguards.py) runs synthetic challenges covering evidence-preserving rewrites, per-question rule coverage, immutable resume checks, sparse IV data, matched exposure endpoints and individual observations. Missing, skipped and expected-failing acceptance cases fail the command. GitHub Actions runs it on relevant pull requests. The benchmark answers remain outside the production calculation and review inputs.

Local verification: 35 mandatory acceptance scenarios, 38 reviewer regressions and 367 calculation tests passed. The paper comparison has 21 checked items and eight documented items without an EDA conclusion. All 21 checked items passed. The real grepafloxacin run generated 180 figures. D9 retains the observed sparse IV profiles. A separate live PMB S07 challenge returned from ANSWERABLE to NOT_ANSWERABLE_YET and passed re-review citing items 35 and 36.

Run `python validation/eda_rereview/check_paper_followups.py PATH/TO/Grepafloxacin` to verify A5, A6, A8 and E10 on a supplied local run. It checks the monkey modeling alternatives, computes the nonfasted/fasted ratios from the original rat records, reconstructs all 12 oral dose/time ranges from the individual dog columns, and checks the monkey recovery subtotal against the separate cage wash.

## Earlier benchmark

The previous live benchmark covered 15 grepafloxacin requests and 25 PMB requests. On grepafloxacin the reviewer flagged at least one row with an expected issue type in all six fully visible known-error groups and one partially visible group. It did not recover the full scientific explanation of every error.

| PMB, 30 planted errors | Previous live reviewer | Same saved responses plus new status checks |
|---|---:|---:|
| Planted rows flagged | 29/30 | 30/30 |
| Planted error type identified | 21/30 | 24/30 |
| Overstated statuses correctly typed | 2/6 | 5/6 |
| Untouched rows flagged | 75/128 | 75/128 |

The four endpoint checks alone flagged four of six planted status errors and zero rows on the original 158-row PMB input. The replay uses the original model answers. It does not measure a change in the false-positive rate with the new study and arm information.

A separate live test used the S07 rat elimination Q7 row with its status deliberately raised to ANSWERABLE. The reviewer identified the inconsistency and returned keywords for excreta components and in vitro assays. The writer searched the supplied study tables, restored NOT_ANSWERABLE_YET and identified the missing measurements. Independent re-review confirmed that limited conclusion. The test took three model calls and one correction round.

The A1 paper comparison uses the historical different-support EV/IV exposure ratio with a tolerance of 0.10 against the published F for each of five species. It also checks two source-attributed statements. The common-window exposure ratio is a different measure. Run `python validation/eda_rereview/check_a1.py PATH/TO/absorption.json` against the local grepafloxacin result. The original in-place suite reported 341 passed, eight skipped and five expected failures.
