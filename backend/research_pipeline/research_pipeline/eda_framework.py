"""Read and check the EDA scaffold. No model calls or dataset execution."""
import argparse
import json
import re
import subprocess

from .common import BACKEND, PROJECT, RULES, PipelineError, read_json, sha256


def check_framework():
    """Check local configuration consistency, not scientific or runtime readiness."""
    rules = read_json(RULES / "eda/eda_rules.json")
    agents = rules["agents"]
    expected = ["EP", "EC", "EV", "EI", "ER"]
    if [a["id"] for a in agents] != expected:
        raise PipelineError("EDA_AGENT_ORDER", "Expected EP -> EC -> EV -> EI -> ER.")
    runtime = rules["runtime"]
    if runtime["implemented"] or runtime["enabled"]:
        raise PipelineError("EDA_SCAFFOLD_ONLY", "This checker cannot authorize runtime activation.")
    if [c["id"] for c in rules["calls"]] != ["EP-plan", "EI-findings", "ER-review"]:
        raise PipelineError("EDA_CALLS", "Only three model operation contracts are defined.")
    outputs = set(rules["artifact_contracts"])
    known = set(rules["external_inputs"])
    for agent in agents:
        if not set(agent["inputs"]).issubset(known):
            raise PipelineError("EDA_INPUT_CONTRACT", agent["id"])
        if not set(agent["outputs"]).issubset(outputs):
            raise PipelineError("EDA_OUTPUT_CONTRACT", agent["id"])
        if agent["execution"] not in {"MODEL", "R", "MODEL_REVIEW_HOST_HANDOFF"}:
            raise PipelineError("EDA_EXECUTION_CONTRACT", agent["id"])
        known.update(agent["outputs"])
    call_ids = {c["id"] for c in rules["calls"]}
    for rule in rules["rules"]:
        if not set(rule["calls"]).issubset(call_ids):
            raise PipelineError("EDA_RULE_CALL", rule["id"])
    prompt_dir = BACKEND / "prompts/stage_contracts/v1"
    manifest = read_json(prompt_dir / "manifest.json")
    prompt = (prompt_dir / manifest["stages"]["eda"]["file"]).read_text(encoding="utf-8")
    operations = re.findall(r"^\[OPERATION:([^\]]+)\]$", prompt, re.MULTILINE)
    if operations != ["plan", "findings", "review"] or operations != manifest["stages"]["eda"]["operations"]:
        raise PipelineError("EDA_PROMPT_OPERATIONS", "Prompt and call contracts differ.")
    reference = rules["source"]["scientific_reference"]
    ref_path = RULES / "eda" / reference["file"]
    if sha256(ref_path) != reference["sha256"]:
        raise PipelineError("EDA_REFERENCE_CHANGED", "Scientific reference differs from its recorded bytes.")
    for agent in agents:
        if agent["execution"] == "R" and not (PROJECT / agent["entrypoint"]["file"]).is_file():
            raise PipelineError("EDA_R_ENTRY_MISSING", agent["id"])
    return {
        "status": "SCAFFOLD_CONTRACTS_CHECKED", "version": rules["version"],
        "agents": [{k: a[k] for k in ("id", "name", "execution")} for a in agents],
        "model_operations": operations, "model_calls_run": 0,
        "runtime_implemented": False, "eda_enabled": False,
        "scientific_reference_sha256": reference["sha256"],
    }


def check_r_scaffold():
    """Use the existing Rscript resolver; invoke only the non-analysis check mode."""
    from .engine import rscript_path
    process = subprocess.run(
        [rscript_path(), "--vanilla", str(PROJECT / "pkpd_r/eda/worker.R"), "--check"],
        capture_output=True, text=True, encoding="utf-8", timeout=45,
    )
    if process.returncode:
        raise PipelineError("EDA_R_CHECK_FAILED", process.stderr.strip())
    result = json.loads(process.stdout)
    if result.get("status") != "SCAFFOLD_LOADED" or result.get("runtime_implemented") is not False:
        raise PipelineError("EDA_R_CHECK_INVALID", "Unexpected R scaffold response.")
    result["diagnostics"] = process.stderr.strip()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-r", action="store_true", help="Also load the R scaffold without data.")
    args = parser.parse_args()
    result = check_framework()
    if args.check_r:
        result["r_scaffold"] = check_r_scaffold()
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
