"""Compare three complete native absorption replays of a frozen PMB checkpoint."""
import argparse
import hashlib
import json
from pathlib import Path

from verify_run import inspect


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def object_digest(value):
    data = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def verify(archive, runs):
    if len(runs) != 3 or len({p.resolve() for p in runs}) != 3:
        raise ValueError("Supply three distinct replay directories")
    signatures, counts = [], []
    for run in runs:
        verified = inspect(archive, run)
        folder = run / "absorption"
        inputs = json.loads((run / "replay_inputs.json").read_bytes())
        if inputs["source_manifest"] != "verified":
            raise ValueError("A registered input manifest is required")
        for name, expected in inputs["input_sha256"].items():
            if digest(run / name) != expected:
                raise ValueError(f"Changed replay input: {name}")
        ledger = json.loads((folder / "mechanism_candidates.json").read_bytes())
        files = {p.relative_to(folder).as_posix(): digest(p) for p in folder.rglob("*") if p.is_file()}
        signatures.append({"input_manifest": object_digest(inputs),
                           "numerical_rules": inputs["rule_sha256"],
                           "species_priority_rules": ledger["priority_rule_specification"]["sha256"],
                           "numerical_results": files["absorption.json"], "species_decisions": object_digest(ledger["species_priorities"]),
                           "html": files["mechanism_assessment.html"], "markdown": files["mechanism_assessment.md"],
                           "structured_context": files["mechanism_candidates.json"], "complete_absorption_tree": object_digest(files)})
        counts.append({"species": len(ledger["species_priorities"]), "studies": len(ledger["studies"]),
                       "assessments": verified["mechanism_handoff"]["assessments"], "absorption_files": len(files),
                       "png": sum(name.endswith(".png") for name in files)})
    changed = [key for key in signatures[0] if len({run[key] for run in signatures}) != 1]
    if changed or any(c != counts[0] for c in counts):
        raise ValueError("Replays differ. Inspect counts and signatures: " + json.dumps({"changed": changed, "counts": counts, "signatures": signatures}))
    return {"replays": 3, "comparison": "identical", "counts_per_replay": counts[0], "common_sha256": signatures[0],
            "scope": "Repeatability of the native absorption EDA on the same admitted inputs, rules and software environment."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archived_run", type=Path)
    parser.add_argument("replays", type=Path, nargs=3)
    args = parser.parse_args()
    print(json.dumps(verify(args.archived_run, args.replays), indent=2))
