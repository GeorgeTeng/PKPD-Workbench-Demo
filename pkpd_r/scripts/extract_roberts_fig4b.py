"""Read the requested worksheet without modifying the source workbook."""
import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path
from zipfile import ZipFile
import xml.etree.ElementTree as ET

parser = argparse.ArgumentParser()
parser.add_argument("source", type=Path)
parser.add_argument("output", type=Path)
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=True)
ns = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
with ZipFile(args.source) as archive:
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    sheets = workbook.find("s:sheets", ns)
    selected = next(s for s in sheets if s.attrib["name"] == "Fig. 4b")
    rid = selected.attrib["{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"]
    relations = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    target = next(r.attrib["Target"] for r in relations if r.attrib["Id"] == rid)
    strings = ["".join(s.itertext()) for s in ET.fromstring(archive.read("xl/sharedStrings.xml"))]
    cells = {}
    sheet = ET.fromstring(archive.read("xl/" + target))
    for cell in sheet.findall(".//s:sheetData/s:row/s:c", ns):
        value = cell.find("s:v", ns)
        if value is None:
            continue
        cells[cell.attrib["r"]] = strings[int(value.text)] if cell.get("t") == "s" else float(value.text)

assert cells["B1"] == "Figure 4b Rat PK (Plasma)"
assert cells["C2"] == "Polymyxin B 1mg/kg IV"
assert cells["C15"] == "FADDI-365 1mg/kg IV"
records = []
for drug, header_row, first_row, last_row, n_rats in [
    ("PMB", 3, 4, 13, 11), ("FADDI-365", 16, 17, 26, 5)
]:
    for rat in range(1, n_rats + 1):
        col = chr(ord("C") + rat - 1)
        assert cells[f"{col}{header_row}"] == f"Rat {rat}"
        for row in range(first_row, last_row + 1):
            address = f"{col}{row}"
            raw = cells.get(address)
            status = "QUANTIFIED" if isinstance(raw, (int, float)) else {
                "*": "MISSING_CANNULA_BLOCKAGE", "No sampling": "NOT_SAMPLED", "<LLOQ": "BLQ"
            }.get(raw, "UNRECOGNIZED")
            if status == "UNRECOGNIZED":
                raise ValueError(f"Unrecognized source value {address}: {raw}")
            records.append(dict(drug=drug, subject_id=f"{drug}_Rat{rat:02d}", rat_number=rat,
                time_h=cells[f"B{row}"], concentration_mg_L=raw if status == "QUANTIFIED" else "",
                status=status, source_raw_value=raw, source_sheet="Fig. 4b", source_cell=address,
                source_time_cell=f"B{row}", dose_mg_kg=1, duration_h=1/60))

assert len(records) == 160
for name, rows in [("source_records.csv", records),
                   ("quantified_records.csv", [r for r in records if r["status"] == "QUANTIFIED"]),
                   ("excluded_records.csv", [r for r in records if r["status"] != "QUANTIFIED"])]:
    with (args.output / name).open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(rows)

manifest = dict(source_file=str(args.source.resolve()), source_sha256=hashlib.sha256(args.source.read_bytes()).hexdigest(),
    source_sheet="Fig. 4b", source_ranges=["B3:M13", "B16:G26", "B28:B29"],
    doi="10.1038/s41467-022-29234-3", article_url="https://www.nature.com/articles/s41467-022-29234-3",
    records=len(records), counts=dict(Counter(r["status"] for r in records)),
    per_drug={d: dict(Counter(r["status"] for r in records if r["drug"] == d)) for d in ["PMB", "FADDI-365"]},
    source_notes={a: cells[a] for a in ["B28", "B29"]},
    metadata=dict(species="Sprague-Dawley rat", sex="male", matrix="plasma", concentration_basis="total",
      concentration_unit="mg/L", dose_unit="mg/kg", dose=1, administration="IV over 1 minute",
      individual_weights_kg="NOT_FOUND", numerical_LLOQ_mg_L="NOT_FOUND",
      study_weight_range_kg=[0.280,0.330],
      source="Article Fig. 4b and Pharmacokinetic studies; source workbook labels and footnotes"),
    preparation="Keep all source values and statuses. Quantifiable-only fitting is explicit; no numeric replacement of BLQ.",
    pkpd_indices_status="NOT_COMPUTED: Fig. 4b has no specified MIC or efficacy endpoint.")
(args.output / "source_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({"counts": manifest["counts"], "per_drug": manifest["per_drug"]}, indent=2))
