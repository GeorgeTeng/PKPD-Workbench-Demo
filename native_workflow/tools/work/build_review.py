"""Render the active review from the curated literature index."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUTPUTS = ROOT / "outputs"


def main():
    data = json.loads((OUTPUTS / "Colistin_PMB_MBM_Literature_Index.json").read_text(encoding="utf-8"))
    by_id = {article["id"]: article for article in data["articles"]}
    core = [by_id[key] for key in data["priority_pk_ids"]]
    background = [by_id[key] for key in data["background_ids"]]
    parts = ["""# Colistin and Polymyxin B: Animal and In Vitro Translation to Human PK

**Focused critical review · revised 15 September 2026**

## Current research question

How can animal PK or in vitro drug-disposition data predict human clearance, distribution volume, half-life and concentration-time profiles when drug-specific human in vivo PK is unavailable for calibration?

The current scope comprises **compartmental PK, interspecies allometric scaling and in vitro-in vivo extrapolation (IVIVE)**. Human-derived in vitro assays and general human scaling factors are eligible inputs. In the proposed evaluation design, human concentration observations would be reserved for comparison after the predictions are fixed.

The priority reading set contains a direct colistin IVIVE example, a PMB animal compartmental model and a general scaling methods paper. Together these provide learning material; they do not constitute an already validated PMB human-prediction model. Retained PK/PD studies provide supporting background for later questions about drug response.

## Evidence basis

This is a targeted narrative review of sources already checked during this project. This revision updates scope and reading priorities without reporting a new systematic search. Verification depth and data availability are recorded per study. No new digitization, model fitting or model execution was performed for this revision.

## Priority evidence map

| ID | Study | Role | Main output |
|---|---|---|---|
"""]
    for article in core:
        lead = article["authors"].split(",")[0]
        parts.append(f'| {article["id"]} | [{lead}, {article["year"]}]({article["url"]}) | {article["group"]} | {article["prediction_endpoint"]} |\n')

    def section(article):
        links = f'[Primary article]({article["url"]})'
        if article.get("pmid"):
            links += f' · [PubMed](https://pubmed.ncbi.nlm.nih.gov/{article["pmid"]}/)'
        result = [f'### {article["id"]}. {article["title"]}\n\n{article["authors"]} **{article["year"]}**. {links}\n\n']
        for label, key in [("Evidence and scale","evidence_units"),("Model role","translation_direction"),("Human PK role","human_pk_role"),("Critical review","critical_review"),("Reusability","availability"),("Verification","review_depth")]:
            result.append(f'- **{label}:** {article[key]}\n')
        return "".join(result) + "\n"

    parts.append("\n## Priority study review\n\n")
    parts.extend(section(article) for article in core)
    parts.append("""## Translation approaches

### Animal-to-human PK

Animal concentration-time data → animal compartmental parameters → justified cross-species scaling of clearance and distribution → human compartmental parameters → predicted human concentration-time profile.

PK2 supports the animal-model starting point. M1 provides a general clearance-scaling reference. Applying a scaling method to the PMB model would be a new analysis requiring independent evaluation. Distribution and, when relevant, absorption parameters also require evidence before a full concentration-time curve can be predicted.

### In vitro-to-human PK

In vitro drug disappearance and binding → intrinsic clearance → whole-liver scaling and hepatic clearance calculation → comparison with independent in vivo observations.

PK1 is the direct colistin example. Its output is hepatic clearance. Comparison with total plasma clearance must account for which elimination pathways are represented. Clearance agreement alone does not establish a complete human concentration-time model.

### Data and species requirements

The reviewed set does not establish a universal minimum number of species or samples. For a scaling relation with both coefficient and exponent estimated from species means, one species cannot identify both quantities. Two means can define a line but leave no residual degrees of freedom to assess its fit. More species add evaluation opportunities without guaranteeing human predictivity. These are mathematical design considerations, not a PMB-specific acceptance threshold.

Record animal counts, routes, sampling coverage, concentration basis, parameter uncertainty and independent evaluation evidence. Human-cell assays can supply human-specific disposition information without a human dosing study. Bacterial isolates and time-kill curves do not count as mammalian PK species or human PK observations.

### Interpretation rules

- Keep CMS, formed colistin and directly administered PMB distinct.
- Distinguish total from unbound concentrations and serum/plasma from other matrices.
- Separate calibration, internal checks and prediction of independent data.
- Record whether human PK influenced fitting, model selection, exposure matching or evaluation.
- Treat animal regimens matching known human exposure as a comparator with a different transfer direction.

## Supporting background

The following previously reviewed sources provide context on PK/PD, clinical evaluation and animal exposure matching. They are background material rather than priority evidence for predicting human PK from animal or in vitro data.

""")
    parts.extend(section(article) for article in background)
    parts.append("""## Reading order and current conclusion

1. **PK1 — Qi 2023:** colistin in vitro-to-human hepatic clearance prediction.
2. **PK2 — Abdelraouf 2012:** the PMB rat compartmental model and its disposition evidence.
3. **M1 — Mahmood and Balian 1996:** empirical interspecies clearance scaling and its conditional performance.

PK1 is the most direct verified translation example in the current set. PK2 is an animal PK starting point. M1 is a general methods reference. A PMB study completing the specified animal/in vitro-to-human prediction task has not yet been verified in this project. The supporting studies do not establish that missing validation.
""")
    path = OUTPUTS / "Colistin_PMB_Translational_MBM_Review.md"
    path.write_text("".join(parts), encoding="utf-8")
    print(f"Rendered {len(core)} priority sources and {len(background)} background sources.")
    print(path)


if __name__ == "__main__":
    main()
