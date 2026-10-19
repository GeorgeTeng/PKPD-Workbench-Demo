"""Write hand-authored example assets. This is NOT the general extraction algorithm.

The example is an assistant-authored, internally reviewed demonstration. Real proposals
use ctxcomp prepare/accept or the opt-in model backend. No PK observations are generated.
"""
from pathlib import Path
import json

ROOT = Path(__file__).parent / "current_research"


def save(name, value):
    (ROOT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


context = {
    "version": "3.0",
    "objective": "Plan animal/in vitro-to-human PK and conditional exposure-response; assess reliability, species selection and sample size.",
    "study": {
        "drug": "Polymyxin B or colistin; selection pending. Apramycin is the reference project.",
        "regimen": "NOT_FOUND",
        "population": "Humans; specific population pending.",
        "system": "Animal PK and in vitro disposition.",
        "measurements": "NOT_FOUND",
        "methods": "NOT_FOUND"
    },
    "data": {
        "available": ["Literature reviews, public-material inventories and statistical notes; no project animal observations supplied."],
        "required": ["Animal PK records with dose, time, subject, species, weight, units and concentration basis.",
                     "Target-population specification; disposition evidence; applicable PD evidence for response prediction."]
    },
    "rules": ["Exclude PBPK.", "Reserve drug-specific human PK for evaluation after prediction freeze.",
              "Identify historical human calibration; do not assume more species improve accuracy.",
              "Keep facts, external evidence and suggestions distinct; preserve qualifiers and known values."],
    "checks": ["B2: distinguish individual observations from summaries and verify availability, units and total/free basis.",
               "Specify estimand, precision, variability and sampling structure before sample-size planning."],
    "uncertainties": ["Compound, regimen, population, species, animal counts and concentration basis remain unspecified.",
                      "Precision threshold, transferable PD evidence and executable model/data availability remain unresolved."]
}
save("context.json", context)

ANY = {k: "ANY" for k in ("species", "matrix", "basis", "time_window", "units", "record_level")}
UNKNOWN = {k: "NOT_FOUND" for k in ANY}
files = []


def file(fid, description, kind, producer="EXTERNAL", role="DEVELOPMENT", attributes=None, fields=(), available=None):
    files.append({"id": fid, "description": description, "kind": kind,
                  "availability": available or ("MISSING" if producer == "EXTERNAL" else "TO_GENERATE"),
                  "path": "NOT_FOUND" if producer == "EXTERNAL" else f"analysis/{producer}/{fid}.json",
                  "producer": producer, "role": role, "attributes": UNKNOWN | (attributes or {}),
                  "required_fields": list(fields)})


file("S1", "Demonstration proposal; no research observations", "DOCUMENT", role="CONTEXT", available="LOCAL_DOCUMENT")
file("ANIMAL_RAW", "Animal individual PK observations or explicitly labelled study summaries", "DATASET",
     attributes={"species": "animal"}, fields=["subject_id", "species", "body_weight", "dose", "route", "sampling_time", "concentration", "units", "total_or_free", "study_id", "record_level"])
file("TARGET_SPEC", "Target population and hypothetical prediction scenario specification", "DOCUMENT",
     role="CONTEXT", fields=["population", "body_weight_distribution", "route", "prediction_endpoints"])
file("PD_EVIDENCE", "Applicable published exposure-response evidence, with source and transfer limitations", "DOCUMENT",
     fields=["endpoint", "experimental_system", "exposure_basis", "uncertainty", "applicability"])
file("HUMAN_HOLDOUT", "Future independent human PK observations reserved for validation", "DATASET", role="VALIDATION",
     attributes={"species": "human"}, fields=["subject_id", "dose_history", "sampling_time", "concentration", "population", "units"])
file("CONTEXT", "Reviewed compressed context and planning assumptions", "DOCUMENT", "B1", "CONTEXT")
file("ANIMAL_QC", "Prepared animal PK data with provenance and study-level grouping", "DATASET", "B2", attributes={"species": "animal"})
file("QC_REPORT", "QC limitations, exclusions and preserved measurement definitions", "REPORT", "B2")
file("ANIMAL_MODEL", "Animal compartmental model definitions and estimation objects", "MODEL", "B3")
file("ANIMAL_PARAMS", "Species parameters, covariance and estimand definitions", "REPORT", "B3")
file("PRECISION_PLAN", "Conditional species/design sample-size analysis", "REPORT", "B4")
file("HUMAN_PK", "Predicted human PK scenarios with uncertainty and scaling assumptions", "MODEL", "B5")
file("SCALING_REPORT", "Scaling alternatives, applicability, historical calibration and sensitivity", "REPORT", "B5")
file("PD_MAP", "Applicable PD evidence and explicit exposure-response translation assumptions", "MODEL", "B6")
file("RESPONSE", "Conditional human exposure-response predictions with transfer limitations", "REPORT", "B7")
file("PREDICTION_FREEZE", "Versioned prediction package, candidate model definitions and content hashes", "REPORT", "B8")
file("UNCERTAINTY", "Parameter and structural sensitivity results; no external accuracy claim", "REPORT", "B8")
file("HUMAN_VALIDATION", "Comparison of frozen predictions with held-out human PK", "REPORT", "B9", "VALIDATION")
file("FINAL_REPORT", "Answers, evidence boundaries, data gaps and next-study priorities", "REPORT", "B10")

blocks = []


def block(bid, title, purpose, category, method, refs, inputs, outputs, instructions, completion, when="ALWAYS", constraints=()):
    blocks.append({"id": bid, "title": title, "purpose": purpose, "category": category,
                   "method": {"name": method, "origin": "SUGGESTED", "reference_ids": refs},
                   "inputs": [{"file_id": f, "required": required, "expects": dict(ANY)} for f, required in inputs],
                   "outputs": outputs, "instructions": instructions, "completion_criteria": completion,
                   "constraints": list(constraints), "when": when})


block("B1", "Context and evidence handoff", "Fix the research question and preserve source-bound facts and missing information.",
      "PLANNING", "Question-dependent extraction and checked workflow planning", ["CTX2026", "RECOMP", "MODULO", "CWL"],
      [("S1", True)], ["CONTEXT"],
      ["Review the compact context against the proposal; keep evidence in the audit sidecar.",
       "Record required data and unresolved choices without treating literature access as ownership of observations."],
      ["Context and pipeline reviews complete; source bindings valid; human review recorded before downstream analysis."])
block("B2", "Data preparation and QC", "Establish what animal data can support parameter estimation.",
      "PREPARATION", "Study-aware PK data preparation", ["CTX2026", "PMB2012"],
      [("CONTEXT", True), ("ANIMAL_RAW", True)], ["ANIMAL_QC", "QC_REPORT"],
      ["Preserve subject and study grouping, route, dose/time definitions, matrix, units and total/free basis.",
       "Distinguish individual longitudinal records, sparse terminal observations, group means and duplicated file representations.",
       "Document missingness and measurement limits; do not infer animal count from file or concentration count."],
      ["Data dictionary and QC report match the actual data; unsupported conversions remain unresolved."])
block("B3", "Animal PK estimation", "Estimate species PK parameters and uncertainty using models supported by the available observations.",
      "ANALYSIS", "Compartmental or population PK estimation", ["PMB2012", "APR2021"],
      [("ANIMAL_QC", True), ("QC_REPORT", True)], ["ANIMAL_MODEL", "ANIMAL_PARAMS"],
      ["Choose model complexity supported by sampling and distinguish CL from CL/F.",
       "Evaluate parameter identifiability, residual patterns, uncertainty and study-level variability.",
       "Keep model files, covariance and units together; do not copy apramycin parameters to another drug."],
      ["Model diagnostics, uncertainty and limitations reviewed; every species estimate has a clear estimand."])
block("B4", "Species and sample-size adequacy", "Determine precision achievable under specified variability and sampling designs.",
      "ANALYSIS", "Simulation-based confidence-interval precision planning", ["PRECISION2008"],
      [("ANIMAL_MODEL", True), ("ANIMAL_PARAMS", True)], ["PRECISION_PLAN"],
      ["Prespecify estimand, confidence level, allowable CI width and width-assurance probability.",
       "Simulate and refit candidate sampling designs using sensitivity ranges for pilot variability.",
       "Report bias, coverage, failed fits and precision; distinguish independent animals from repeated samples.",
       "For sparse terminal sampling use a suitable population model; do not apply the individual-CL mean formula blindly."],
      ["Sample-size conclusions are conditional on documented assumptions; no universal species count is asserted."])
block("B5", "Human PK translation", "Predict human PK using suitable animal scaling methods and an explicit target population.",
      "ANALYSIS", "Compartmental PK with interspecies scaling comparators", ["APR2021", "TANG2007", "MAHMOOD2009"],
      [("ANIMAL_MODEL", True), ("ANIMAL_PARAMS", True), ("TARGET_SPEC", True)], ["HUMAN_PK", "SCALING_REPORT"],
      ["Check disposition, species combinations, body-weight leverage and compatible parameter definitions before selecting scaling candidates.",
       "Compare justified free-exponent, fixed-exponent or historically calibrated methods; record historical human calibration separately.",
       "Predict human CL and other supported parameters; a CL estimate alone does not determine a full concentration-time curve.",
       "Keep drug-specific human observations unavailable to model development and freeze candidate assumptions before validation."],
      ["Predictions retain method assumptions, parameter uncertainty and applicability limits."],
      constraints=["No PBPK.", "No drug-specific human PK fitting or tuning."])
block("B6", "PD evidence applicability", "Determine whether existing drug-effect evidence can support response translation.",
      "ANALYSIS", "Published exposure-response evidence mapping", ["APR2021"],
      [("CONTEXT", True), ("PD_EVIDENCE", True)], ["PD_MAP"],
      ["Match drug, endpoint, exposure basis, matrix and relevant experimental system.",
       "Choose reuse of published evidence or an explicitly justified model-development branch; do not assume a new PD fit is always required.",
       "Record uncertainty and cross-system assumptions; request missing evidence before producing response predictions."],
      ["Evidence scope and transfer assumptions are explicit and reviewed."], when="PD_REQUESTED")
block("B7", "Conditional response prediction", "Connect predicted human exposure with applicable drug-effect evidence.",
      "ANALYSIS", "Exposure-response integration", ["APR2021"],
      [("HUMAN_PK", True), ("PD_MAP", True)], ["RESPONSE"],
      ["Verify exposure definitions and units agree before connecting the models.",
       "Propagate uncertainty from both PK and the PD mapping; label outputs as conditional predictions.",
       "Do not claim patient efficacy has been validated by animal fit or healthy-volunteer PK."],
      ["PK-to-PD interface reviewed and response limitations reported."], when="PD_REQUESTED")
block("B8", "Uncertainty and prediction freeze", "Prepare a reproducible prediction package before any external human comparison.",
      "ANALYSIS", "Sensitivity analysis and versioned prediction freeze", ["APR2021", "BWC2024", "MODULO"],
      [("HUMAN_PK", True), ("SCALING_REPORT", True), ("ANIMAL_PARAMS", True)], ["PREDICTION_FREEZE", "UNCERTAINTY"],
      ["Propagate animal parameter covariance, scaling uncertainty and justified structural alternatives.",
       "Keep confidence intervals for typical parameters separate from individual predictive intervals.",
       "Freeze model files, parameters, target-population assumptions, outputs and evaluation criteria with content hashes."],
      ["Prediction package is reproducible and no human holdout observations were used for selection."])
block("B9", "Future human PK validation", "Evaluate the frozen prediction when independent human PK data become available.",
      "VALIDATION", "External prediction comparison", ["BWC2024"],
      [("PREDICTION_FREEZE", True), ("HUMAN_HOLDOUT", True)], ["HUMAN_VALIDATION"],
      ["Match population, dose, route, matrix and endpoints before comparing predicted and observed PK.",
       "Report bias, prediction error and interval calibration against prespecified criteria.",
       "Any later model tuning creates a new development version; the same data cannot remain an untouched test set."],
      ["Data separation and endpoint matching documented; no clinical efficacy claim from PK agreement."],
      when="HUMAN_VALIDATION_AVAILABLE")
block("B10", "Research answers and next steps", "Summarize what is supported and which data would reduce remaining uncertainty.",
      "SYNTHESIS", "Evidence-qualified synthesis", ["CTX2026", "MODULO"],
      [("PREDICTION_FREEZE", True), ("UNCERTAINTY", True), ("PRECISION_PLAN", True), ("RESPONSE", False), ("HUMAN_VALIDATION", False)],
      ["FINAL_REPORT"],
      ["Answer species and sample-size questions conditionally, separating parameter precision, animal fit and human accuracy.",
       "State explicitly when response prediction or human validation remains unavailable.",
       "List unresolved assumptions and prioritize further data by their effect on the intended prediction."],
      ["Every conclusion is tied to an available result or an explicit limitation; pending branches remain visible."])
save("pipeline.json", {"blocks": blocks, "data_files": files})

# This map was authored by the assistant against the demonstration brief.
quotes = {
    "/objective": "Objective: Plan prediction of human PK and, where evidence permits, exposure-response from animal or in vitro evidence. Assess model reliability, species selection and per-species sample-size requirements.",
    "/study/drug": "Polymyxin B and colistin are candidate drugs; the final compound is not selected. Apramycin is the preferred translational project template.",
    "/study/population": "The destination is humans; the particular target population is not selected.",
    "/study/system": "Eligible input systems are animal PK and in vitro disposition studies.",
    "/data/available/0": "Available materials consist of literature reviews, public-material inventories and statistical notes. No project-level animal concentration observations have been supplied.",
    "/rules/0": "Do not use PBPK.",
    "/rules/1": "If human PK becomes available, reserve it for evaluation after freezing predictions.",
    "/rules/2": "Historical scaling methods calibrated using other drugs' human PK must be identified as such.\n\nCompare species choices and sampling designs rather than assuming that more species must be better.",
    "/rules/3": "Preserve known values, units, total/free basis, negation and conditional scope. Keep unknown information as NOT_FOUND. Separate project facts, external evidence and proposed methods.",
    "/checks/1": "Plan sample size around an explicit estimand, acceptable confidence-interval precision, variability and sampling structure."
}
save("evidence_quotes.json", quotes)
print("Wrote hand-authored context, pipeline and evidence map (no model call).")
