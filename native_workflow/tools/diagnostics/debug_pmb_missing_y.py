r"""Read-only reproduction of the stopped PMB adapter's missing-Y assertion.

Run from the workspace:
  .\.venv-context\Scripts\python.exe -I -X utf8 diagnostics/debug_pmb_missing_y.py

Does not import/run the adapter, write datasets, or change the review gate.
"""

import ast
from collections import Counter
import json
import math
from pathlib import Path


RUN = Path(__file__).resolve().parents[2] / "outputs/Data_Preparation_PMB_2026-09-18"
ADAPTER = RUN / "run_pmb_data_review.py"


def read_table(table_id):
    path = RUN / "source_preparation/tables" / f"{table_id}.records.json"
    return json.loads(path.read_text(encoding="utf-8-sig"))["records"]


def main():
    # Extract only the original predicate and finite() helper; never execute main().
    tree = ast.parse(ADAPTER.read_text(encoding="utf-8-sig"))
    finite_node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "finite")
    assertion = next(n for n in ast.walk(tree) if isinstance(n, ast.Assert) and "c005_y" in ast.unparse(n.test))
    namespace = {"math": math}
    exec(compile(ast.Module(body=[finite_node], type_ignores=[]), str(ADAPTER), "exec"), namespace)
    finite = namespace["finite"]
    rows = read_table("T0012")
    r = next(row for row in rows if row["record_id"] == "T0012_R161")
    events = [row for row in rows if row["record_type"] == "EXPOSURE_EVENT" and row["c001_id"] == r["c001_id"]]
    if len(events) != 1:
        raise ValueError(f"Expected one exposure event; found {len(events)}")
    e = events[0]
    namespace.update(r=r, e=e)
    predicates = {
        "event_time_le_observation_time": e["c004_time"] <= r["c004_time"],
        "Y_is_finite_number": finite(r["c005_y"]),
        "CENS_in_0_1": r["c006_cens"] in (0, 1),
    }
    try:
        exec(compile(ast.Module(body=[assertion], type_ignores=[]), str(ADAPTER), "exec"), namespace)
    except AssertionError:
        reproduced = True
    else:
        reproduced = False

    # These are diagnostic counts, not cleaned datasets or approval decisions.
    counts = {}
    for table_id in ("T0012", "T0013"):
        counts[table_id] = Counter()
        for row in read_table(table_id):
            y, cens = row["c005_y"], row["c006_cens"]
            if row["record_type"] == "EXPOSURE_EVENT":
                label = "EXPOSURE_EVENT"
            elif row["record_type"] != "OBSERVATION":
                raise ValueError(f"Unknown record type: {row['record_id']}")
            elif y == "." and cens == 0:
                label = "MISSING_OBSERVATION"
            elif finite(y) and cens in (0, 1):
                label = "CENSORED" if cens == 1 else "QUANTIFIED"
            else:
                raise ValueError(f"Unclassified observation: {row['record_id']}")
            counts[table_id][label] += 1

    print(json.dumps({
        "adapter_path": str(ADAPTER), "assertion_line": assertion.lineno,
        "record_id": r["record_id"], "source_cell": r["source_cells"]["c005_y"],
        "Y_raw": r["c005_y"], "CENS": r["c006_cens"],
        "event_time_h": e["c004_time"], "observation_time_h": r["c004_time"],
        "predicate_results": predicates, "original_assertion_reproduced": reproduced,
        "diagnostic_counts": counts, "production_adapter_modified": False,
        "pipeline_restarted": False,
    }, indent=2, ensure_ascii=False))
    if not reproduced:
        raise RuntimeError("The original assertion no longer fails; inspect changed input/code.")


if __name__ == "__main__":
    main()
