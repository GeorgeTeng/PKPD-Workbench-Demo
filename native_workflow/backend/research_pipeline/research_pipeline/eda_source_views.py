"""Source-native display projections, never Data reclassification or model input."""
import math
import re

NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
MEAN_SD = re.compile(rf"^\s*({NUMBER})\s*±\s*({NUMBER})\s*$")
MIC = re.compile(rf"^\s*([<>]?)\s*({NUMBER})\s+([SIR])\s*$")


def numeric(record, column):
    value = record["source_raw_values"].get(column)
    return (record["value_status"].get(column) == "QUANTIFIED"
            and type(value) in (int, float) and math.isfinite(value))


def mean_sd(raw, notes):
    if not re.search(r"\bmeans?\s*(?:±|\+/-)\s*(?:SD\b|standard deviations?\b)", notes, re.I):
        raise ValueError("Source does not explicitly define mean and SD")
    match = MEAN_SD.fullmatch(str(raw).replace("−", "-"))
    if not match:
        return None
    mean, sd = map(float, match.groups())
    if not math.isfinite(mean) or not math.isfinite(sd) or sd < 0:
        raise ValueError("Invalid reported mean/SD")
    return mean, sd


def row(table, record, y_column, *, x, panel, group="", x_column="",
        category="", projection="numeric", error_column="", n_column=""):
    raw = record["source_raw_values"].get(y_column)
    result = dict(dataset_id=table["dataset_id"], record_id=record["record_id"],
        source_file_id=record["source_file_id"], source_sha256=record["source_sha256"],
        source_sheet=record["source_sheet"], source_row=record["source_row"],
        y_column=y_column, y_cell=record["source_cells"].get(y_column),
        raw_y=raw, original_status=record["value_status"].get(y_column),
        x=x, x_column=x_column, x_cell=record["source_cells"].get(x_column),
        raw_x=record["source_raw_values"].get(x_column),
        panel=panel, group=group, category=category, y=None, error=None, n=None,
        error_column=error_column, error_cell=record["source_cells"].get(error_column),
        n_column=n_column, n_cell=record["source_cells"].get(n_column),
        display_component=projection, bound="", source_annotation="",
        status_unchanged=True, usable_for_modeling=False)
    if projection == "numeric":
        if numeric(record, y_column):
            result["y"] = raw
    elif projection == "reported_mean_sd":
        parsed = mean_sd(raw, table["notes"])
        if parsed:
            if result["original_status"] != "SOURCE_TEXT_REQUIRES_REVIEW":
                raise ValueError("Reported-text projection cannot override another source status")
            result["y"], result["error"] = parsed
            result["error_cell"] = result["y_cell"]
    elif projection == "reported_mic":
        if result["original_status"] != "SOURCE_TEXT_REQUIRES_REVIEW":
            raise ValueError("MIC text projection cannot override another source status")
        match = MIC.fullmatch(str(raw))
        if not match:
            raise ValueError(f"Unrecognized MIC text: {raw!r}")
        bound, value, annotation = match.groups()
        result.update(y=float(value), bound=bound, source_annotation=annotation)
        if result["y"] <= 0:
            raise ValueError("MIC must be positive")
        # A bound is a threshold marker, NOT an observation at the threshold.
        if bound:
            result["display_component"] = "reported_mic_bound"
    else:
        raise ValueError(projection)
    if error_column:
        if not numeric(record, error_column) or record["source_raw_values"][error_column] < 0:
            raise ValueError("Reported uncertainty must be numeric and nonnegative")
        result["error"] = record["source_raw_values"][error_column]
    if n_column:
        if not numeric(record, n_column):
            raise ValueError("Reported n must be numeric")
        result["n"] = record["source_raw_values"][n_column]
    return result


def verify_rows(plots, tables):
    """Independently rebind every displayed coordinate and status to its source."""
    count = 0
    for plot in plots:
        for item in plot["rows"]:
            table = tables[item["dataset_id"]]
            record = next(r for r in table["records"] if r["record_id"] == item["record_id"])
            column = item["y_column"]
            assert item["raw_y"] == record["source_raw_values"][column]
            assert item["original_status"] == record["value_status"][column]
            assert item["y_cell"] == record["source_cells"][column]
            assert item["source_sha256"] == record["source_sha256"]
            if item["x_column"]:
                assert item["raw_x"] == record["source_raw_values"][item["x_column"]]
                assert item["x_cell"] == record["source_cells"][item["x_column"]]
                assert numeric(record, item["x_column"])
                assert item["x"] == item["raw_x"]
            if item["display_component"] == "numeric":
                assert item["y"] == (item["raw_y"] if numeric(record, column) else None)
            elif item["display_component"] == "reported_mean_sd":
                parsed = mean_sd(item["raw_y"], table["notes"])
                assert (item["y"], item["error"]) == (parsed or (None, None))
            else:
                bound, value, annotation = MIC.fullmatch(str(item["raw_y"])).groups()
                assert (item["bound"], item["y"], item["source_annotation"]) == (bound, float(value), annotation)
            if item["error_column"]:
                assert item["error"] == record["source_raw_values"][item["error_column"]]
            if item["n_column"]:
                assert item["n"] == record["source_raw_values"][item["n_column"]]
            if plot["scale"] == "log10" and item["y"] is not None:
                if item["y"] <= 0:
                    assert item.get("plot_eligible") is False
                    assert item.get("display_exclusion_reason") == "Nonpositive source value cannot use log10 axis"
                else:
                    assert item.get("plot_eligible", True) is True
            count += 1
    return count
