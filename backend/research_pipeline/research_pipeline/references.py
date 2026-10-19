"""Drug identity and evidence screening; search rank is never a reliability score."""
import re
from datetime import datetime
from .common import PipelineError

ALIASES = {
    "polymyxin_b": ["polymyxin b", "pmb"],
    "colistin": ["colistin", "polymyxin e"],
    "cms": ["cms", "colistimethate sodium", "colistin methanesulfonate", "colistimethate"],
    "faddi_365": ["faddi-365", "faddi 365", "f365", "qpx9003", "qpx 9003"],
    "apramycin": ["apramycin"],
    "spr206": ["spr206", "spr-206", "ever206", "ever-206"],
}
REQUIRED_EVIDENCE = ["model_description", "data_design", "parameter_identifiability", "diagnostics", "validation"]


def canonical_drug(value):
    text = str(value).strip().lower()
    for key, aliases in ALIASES.items():
        if text == key or text in aliases:
            return key
    return re.sub(r"[^a-z0-9]+", "_", text).strip("_")


def drug_mentions(text):
    text = text.lower()
    return [drug for drug, aliases in ALIASES.items()
            if any(re.search(r"(?<!\w)" + re.escape(alias) + r"(?!\w)", text) for alias in aliases)]


def evaluate_reference(card, target_drug, metadata=None, paper_hashes=()):
    target = canonical_drug(target_drug)
    checks = {}
    checks["same_drug"] = canonical_drug(card.get("drug_id", "")) == target and bool(target)
    checks["primary_research"] = card.get("publication_type") == "primary_research"
    spec = card.get("model_spec", {})
    known = lambda value: isinstance(value,str) and value.strip().upper() not in ("", "NOT_FOUND", "NOT_VERIFIED", "NOT_REVIEWED")
    checks["actual_model"] = spec.get("family") in {"one_compartment", "two_compartment", "endpoint_emax", "longitudinal_response"}
    for name in REQUIRED_EVIDENCE:
        evidence = card.get("evidence", {}).get(name, {})
        checks[name] = evidence.get("status") == "SUPPORTED" and known(evidence.get("locator")) and known(evidence.get("finding"))
    review = card.get("review", {})
    try:
        reviewed_at_valid = datetime.fromisoformat(review.get("reviewed_at", "").replace("Z", "+00:00")).tzinfo is not None
    except (ValueError, TypeError):
        reviewed_at_valid = False
    checks["review_record"] = (review.get("status") == "ACCEPTED_FOR_SCOPE" and
        known(review.get("reviewer")) and reviewed_at_valid and known(review.get("scope")))
    checks["source_binding"] = bool(re.fullmatch(r"[a-fA-F0-9]{64}", review.get("document_sha256", ""))) and review.get("document_sha256") in paper_hashes
    checks["validation_type"] = card.get("evidence",{}).get("validation",{}).get("kind") in {
        "bootstrap", "cross_validation", "external_prediction", "simulation_based", "prospective_prediction", "posterior_predictive_check"}
    if metadata:
        for key in ("route", "species", "matrix", "concentration_basis"):
            expected = metadata.get(key)
            actual = spec.get(key)
            # Exact declared scope match is conservative. Broader extrapolation
            # requires a separate reviewed adaptation, not an implicit match.
            checks["compatible_" + key] = known(expected) and known(actual) and str(expected).casefold() == str(actual).casefold()
    accepted = all(checks.values())
    return {"status": "ACCEPTED_FOR_DECLARED_SCOPE" if accepted else "NEEDS_EVIDENCE_OR_REVIEW",
            "target_drug": target, "checks": checks, "unmet": [k for k, v in checks.items() if not v],
            "validation_kind": card.get("evidence", {}).get("validation", {}).get("kind", "NOT_FOUND"),
            "limit": "Verifies recorded evidence and scope, not scientific truth. Citation count is not a pass criterion."}


def require_reference(card, target_drug, metadata, hashes, compartments=None, module="pk_longitudinal"):
    verdict = evaluate_reference(card, target_drug, metadata, hashes)
    if verdict["status"] != "ACCEPTED_FOR_DECLARED_SCOPE":
        raise PipelineError("REFERENCE_NOT_READY", ", ".join(verdict["unmet"]))
    expected = "endpoint_emax" if module == "pkpd_index" else {1: "one_compartment", 2: "two_compartment"}.get(compartments)
    if expected and card["model_spec"]["family"] != expected:
        raise PipelineError("REFERENCE_MODEL_MISMATCH", "Configured model family does not match the reviewed reference.")
    return verdict
