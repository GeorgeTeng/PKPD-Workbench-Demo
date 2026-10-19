"""Normalize the explicit AMT_CMT/CENS static time-kill source schema.

Keep missing observations separate from structural not-applicable fields.
This prepares review candidates only; it neither imputes nor releases data.
"""

from collections import defaultdict
from copy import deepcopy
import math

from .common import PipelineError


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def missing(value):
    return value is None or (isinstance(value, str) and value.strip() in ("", "."))


def normalize_static_time_kill(table):
    table_id = table["table_id"]
    rows = table["records"]
    exposures = defaultdict(list)
    seen = set()

    def fail(code, row, field, message):
        cell = row.get("source_cells", {}).get(field, "NOT_FOUND")
        raise PipelineError(code, f"{table_id} / {row.get('record_id', 'NOT_FOUND')} / {cell}: {message}")

    for row in rows:
        rid = row["record_id"]
        if rid in seen:
            fail("TIME_KILL_DUPLICATE_RECORD", row, "c001_id", "Duplicate source record ID")
        seen.add(rid)
        group = row.get("c001_id")
        if not (finite(group) or (isinstance(group, str) and group.strip() not in ("", "."))):
            fail("TIME_KILL_INVALID_GROUP", row, "c001_id", f"Invalid group ID {group!r}")
        time = row.get("c004_time")
        if not finite(time) or time < 0:
            fail("TIME_KILL_INVALID_TIME", row, "c004_time", f"Expected finite nonnegative time, got {time!r}")
        cens = row.get("c006_cens")
        if not finite(cens) or cens not in (0, 1):
            fail("TIME_KILL_INVALID_CENS", row, "c006_cens", f"Expected numeric 0 or 1, got {cens!r}")
        kind = row.get("record_type")
        expected_cmt = {"EXPOSURE_EVENT": 2, "OBSERVATION": 1}.get(kind)
        if expected_cmt is None or not finite(row.get("c003_amt_cmt")) or row["c003_amt_cmt"] != expected_cmt:
            fail("TIME_KILL_INVALID_RECORD_TYPE", row, "c003_amt_cmt", "record_type and AMT_CMT must agree")
        if kind == "EXPOSURE_EVENT":
            amount = row.get("c002_amt")
            if not finite(amount) or amount < 0:
                fail("TIME_KILL_INVALID_EXPOSURE", row, "c002_amt", f"Invalid nominal concentration {amount!r}")
            if not missing(row.get("c005_y")):
                fail("TIME_KILL_EVENT_HAS_RESPONSE", row, "c005_y", "Exposure-event Y must be structurally not applicable")
            exposures[group].append(row)
        elif not missing(row.get("c002_amt")):
            fail("TIME_KILL_OBSERVATION_HAS_AMT", row, "c002_amt", "Observation AMT must be structurally not applicable")

    for group, events in exposures.items():
        if len(events) != 1:
            fail("TIME_KILL_AMBIGUOUS_EXPOSURE", events[0], "c001_id", f"Expected one exposure event for group {group!r}; got {len(events)}")

    events, observations = [], []
    provenance = ("record_id", "source_file_id", "source_sha256", "source_sheet", "source_row", "source_cells")
    for row in rows:
        common = {key: deepcopy(row[key]) for key in provenance if key in row}
        common.update(experiment_group_key=f"{table_id}::{row['c001_id']}",
                      independent_replicate_id=row.get("independent_replicate_id", "NOT_FOUND"),
                      time_h=row["c004_time"], fit_ready=False,
                      Y_raw=row["c005_y"], AMT_raw=row["c002_amt"], CENS=row["c006_cens"])
        if row["record_type"] == "EXPOSURE_EVENT":
            events.append({**common, "record_type": "EXPOSURE_EVENT",
                           "nominal_concentration_mg_L": row["c002_amt"],
                           "Y_status": "STRUCTURAL_NOT_APPLICABLE"})
            continue
        matches = exposures.get(row["c001_id"], [])
        if len(matches) != 1:
            fail("TIME_KILL_MISSING_EXPOSURE", row, "c001_id", "No unique exposure event in this source table")
        event = matches[0]
        if event["c004_time"] > row["c004_time"]:
            fail("TIME_KILL_EVENT_AFTER_OBSERVATION", row, "c004_time", "Exposure event occurs after observation")
        raw_y, cens = row["c005_y"], row["c006_cens"]
        if missing(raw_y):
            value = None
            status = "MISSING_CENSORED_OBSERVATION" if cens == 1 else "MISSING_OBSERVATION"
        elif finite(raw_y):
            value = raw_y
            status = "CENSORED" if cens == 1 else "QUANTIFIED"
        else:
            fail("TIME_KILL_INVALID_RESPONSE", row, "c005_y", f"Unrecognized response {raw_y!r}; not converted to missing")
        observations.append({**common, "record_type": "OBSERVATION", "log10_CFU_mL": value,
                             "status": status, "censor_limit": "NOT_FOUND",
                             "nominal_concentration_mg_L": event["c002_amt"],
                             "exposure_event_record_id": event["record_id"],
                             "exposure_event_source_cell": event["source_cells"]["c002_amt"],
                             "AMT_status": "STRUCTURAL_NOT_APPLICABLE"})
    return events, observations
