"""Run the release challenges independently of scientific benchmark expectations."""
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[2]
CHALLENGES = {
    "eda/review/tests/test_review_20261112.py::test_writer_cannot_replace_a_measurement_even_if_reviewer_confirms": 7,
    "eda/review/tests/test_review.py::test_missing_section_rules_stop_before_dispatch_or_cache": 4,
    "eda/review/tests/test_review.py::test_question_requires_its_own_rule_text": 6,
    "tools/eda/test_source_condition_and_spread.py::test_printed_meal_contrast_needs_matched_source_endpoints": 11,
    "tools/eda/test_source_condition_and_spread.py::test_repeat_individual_spread_uses_verified_animals_at_one_time_and_dose": 1,
    "tools/eda/test_statistical_config_snapshot.py::test_rejected_resume_preserves_every_file": 5,
    "tools/eda/test_late_area_share.py::test_iv_inventory_keeps_sparse_profiles_before_phase_eligibility": 1,
}


def main():
    with TemporaryDirectory() as tmp:
        report = Path(tmp) / "results.xml"
        proc = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                               "--junitxml", str(report), *CHALLENGES], cwd=ROOT)
        if proc.returncode:
            return proc.returncode
        cases = ElementTree.parse(report).findall(".//testcase")
        for node, minimum in CHALLENGES.items():
            name = node.rsplit("::", 1)[1]
            found = [c for c in cases if c.get("name", "").split("[", 1)[0] == name]
            if len(found) < minimum or any(c.find(tag) is not None for c in found for tag in ("skipped", "failure", "error")):
                print(f"Unverified release challenge: {node}", file=sys.stderr)
                return 1
        print(f"All {len(cases)} release challenges executed and passed.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
