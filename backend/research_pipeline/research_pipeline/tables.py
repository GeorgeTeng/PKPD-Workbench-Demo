import csv
import math
from pathlib import Path
from .common import PipelineError, read_json


def load_table(path, options=None):
    options = options or {}
    path = Path(path)
    if options.get("adapter") == "roberts_fig4b":
        return roberts_fig4b(path, options.get("drug"))
    if path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as file:
            reader=csv.DictReader(file)
            names=reader.fieldnames or []
            if not names or any(not n or not n.strip() for n in names) or len(set(names))!=len(names):
                raise PipelineError('AMBIGUOUS_HEADER','CSV headers must be unique and nonempty; duplicate columns are not silently overwritten.')
            rows=list(reader)
            if any(None in row for row in rows):
                raise PipelineError('CSV_COLUMN_COUNT','A row has more fields than the declared CSV header.')
    elif path.suffix.lower() == ".json":
        rows = read_json(path)
        if isinstance(rows, dict):
            rows = rows.get("records")
        if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
            raise PipelineError("INVALID_TABLE", "JSON table must be an array or {records: [...]}.")
    elif path.suffix.lower() == ".xlsx":
        from openpyxl import load_workbook
        if not options.get("sheet"):
            raise PipelineError("MISSING_SHEET", "Select an XLSX sheet explicitly.")
        book = load_workbook(path, read_only=True, data_only=True)
        try:
            sheet = book[options["sheet"]]
            values = sheet.iter_rows(min_row=options.get("header_row", 1), values_only=True)
            names = next(values)
            if any(n is None for n in names) or len(set(names)) != len(names):
                raise PipelineError("AMBIGUOUS_HEADER", "Use a rectangular long table with unique nonempty headers.")
            rows = [dict(zip(names, values)) for values in values if any(v is not None for v in values)]
        finally:
            book.close()
    else:
        raise PipelineError("TABLE_TYPE", "Numerical input requires CSV, JSON records or XLSX.")
    if not rows or len(rows) > 100000:
        raise PipelineError("TABLE_SIZE", "Provide 1-100000 records.")
    mapping = options.get("column_map", {})
    result = []
    for index, row in enumerate(rows):
        converted = {mapping.get(str(k), str(k)): v for k, v in row.items()}
        if len(converted) != len(row):
            raise PipelineError("COLUMN_COLLISION", "Column mapping is not one-to-one.")
        converted.setdefault("source_row", index + options.get('header_row',1) + 1 if path.suffix.lower()=='.xlsx' else index+2)
        result.append(converted)
    return result


def roberts_fig4b(path, drug):
    from openpyxl import load_workbook
    if drug not in ("PMB", "FADDI-365"):
        raise PipelineError("DRUG_REQUIRED", "Select PMB or FADDI-365; do not pool both drugs.")
    book = load_workbook(path, read_only=True, data_only=True)
    try:
        sheet = book["Fig. 4b"]
        cells = {c.coordinate: c.value for row in sheet.iter_rows(min_row=1, max_row=29, min_col=2, max_col=13) for c in row if c.value is not None}
        if cells["B1"] != "Figure 4b Rat PK (Plasma)":
            raise PipelineError("ADAPTER_MISMATCH", "Not the expected Roberts Fig. 4b layout.")
        start, rats, title_cell, title = (4,11,"C2","Polymyxin B 1mg/kg IV") if drug == "PMB" else (17,5,"C15","FADDI-365 1mg/kg IV")
        if cells[title_cell] != title:
            raise PipelineError("ADAPTER_MISMATCH", "Drug/dose heading differs from the verified layout.")
        rows = []
        for rat in range(1, rats+1):
            col = chr(ord("C")+rat-1)
            for row in range(start, start+10):
                address = f"{col}{row}"; value = cells[address]
                status = "QUANTIFIED" if isinstance(value,(int,float)) else {
                    "*":"MISSING_CANNULA_BLOCKAGE", "No sampling":"NOT_SAMPLED", "<LLOQ":"BLQ"}.get(value,"UNKNOWN")
                rows.append({"drug":drug,"subject_id":f"{drug}_Rat{rat:02d}","time_h":cells[f"B{row}"],
                    "concentration_mg_L":value if status=="QUANTIFIED" else None,"status":status,
                    "source_raw_value":value,"source_sheet":"Fig. 4b","source_cell":address,
                    "dose_mg_kg":1,"dose_time_h":0,"duration_h":1/60})
        return rows
    finally:
        book.close()


NUMERIC = {"time_h", "concentration_mg_L", "dose_mg", "dose_mg_kg", "dose_time_h", "duration_h", "response", "exposure"}


def prepare_records(rows, excluded_statuses=(), extra_numeric=()):
    included, excluded = [], []
    for original in rows:
        row = dict(original)
        status = row.get("status", "QUANTIFIED")
        if status != "QUANTIFIED":
            if status not in excluded_statuses:
                raise PipelineError("UNHANDLED_OBSERVATION", f"Explicit handling required for {status} at {row.get('source_cell',row.get('source_row'))}.")
            excluded.append({**row, "exclusion_reason": status})
            continue
        for key in NUMERIC | set(extra_numeric):
            if key in row:
                try:
                    value = float(row[key])
                except (ValueError, TypeError):
                    raise PipelineError("INVALID_NUMBER", f"Invalid {key}; no missing values are silently dropped.")
                if not math.isfinite(value):
                    raise PipelineError("INVALID_NUMBER", f"Non-finite {key}.")
                row[key] = value
        if "blq" in row:
            if row["blq"] in (False,"FALSE","false","0",0):
                row["blq"] = False
            else:
                raise PipelineError("UNHANDLED_BLQ", "Use an explicit BLQ status and exclusion policy or a censoring model.")
        included.append(row)
    if not included:
        raise PipelineError("NO_USABLE_DATA", "No observations left for analysis.")
    return included, excluded
