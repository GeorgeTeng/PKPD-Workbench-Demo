"""Check a local PMB EV checkpoint. Print aggregate counts and hashes, never observations."""
import argparse
import hashlib
import json
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

from PIL import Image


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def require(ok, message):
    if not ok:
        raise ValueError(message)


class Links(HTMLParser):
    def __init__(self, file):
        super().__init__()
        self.urls, self.ids = [], set()
        self.feed(file.read_text(encoding="utf-8-sig"))
        self.close()

    def handle_starttag(self, tag, attrs):
        fields = dict(attrs)
        if "id" in fields:
            self.ids.add(fields["id"])
        for key in ("href", "src"):
            if fields.get(key):
                self.urls.append(fields[key])


def inspect(run):
    run = run.resolve()
    root = run / "eda" / "run"
    folder = root / "absorption"
    outer, eda = read(run / "e2e_status.json"), read(root / "status.json")
    require(outer["status"] == eda["status"] == "STOPPED_AFTER_EV", "EV checkpoint not reached")
    require(all(x["status"] == "COMPLETED" for x in outer["stages"]), "incomplete native stage")
    require(not (folder / "error.json").exists() and not (folder / "portal_error.json").exists(), "absorption error")
    for key in ("EI_run", "ER_run", "human_approval", "scientific_release", "fit_ready"):
        require(eda[key] is False, "unexpected stage or release: " + key)
    for key in ("reused_context", "reused_first_part"):
        item = outer[key]
        require(item["tree_sha256_before"] == item["tree_sha256_after"], key + " changed")
    require(outer["reused_context"]["verification"]["status"] == "VALID", "context verification failed")
    report = Path(outer["data_report"])
    handoff = report.parent / "handoffs" / "eda_context.json"
    for key, path in (("report", report), ("handoff", handoff)):
        require(sha(path) == eda["bindings"][key]["sha256"], "Data binding changed: " + key)
    data, dh = read(report), read(handoff)
    ids = data["ready_dataset_ids"]
    require(data["status"] == "TECHNICAL_DATA_READY" and dh["status"] == "READY_FOR_EDA", "Data readiness")
    require(sorted(ids) == sorted(f["id"] for f in dh["files"]), "handoff membership")
    require(sorted(t["dataset_id"] for t in read(root / "source_tables.json")) == sorted(ids), "EV input membership")
    result, plots = read(folder / "absorption.json"), read(folder / "plot_specs.json")
    require(plots["version"] == result["version"] == "EDA_ABSORPTION_R4_2", "wrong analysis revision")
    require(result["render"]["engine"] == "R_GGPLOT2", "R/ggplot2 did not render")
    expected = [fig["file"] for fig in plots["figures"]]
    images = set(folder.glob("*.png"))
    require(images and len(images) == len(expected) and images == {folder / x for x in expected}, "PNG/spec mismatch")
    for path in images:
        with Image.open(path) as im:
            require(im.format == "PNG", "invalid PNG")
            im.verify()
        with Image.open(path) as im:
            im.load()
    manifest = {k.replace(chr(92), "/"): v for k, v in read(root / "outputs.json").items()}
    local = [root / "report.html", root / "source_tables.json", root / "verification.json",
             *sorted(f for f in folder.rglob("*") if f.is_file())]
    for path in local:
        require(sha(path) == manifest[path.relative_to(root).as_posix()]["sha256"], "artifact checksum: " + path.name)
    tech = read(root / "verification.json")
    require(tech["status"] == "PASS" and tech["source_coordinates_checked"], "EV technical verification")
    pages = {p: Links(p) for p in [root / "report.html", *folder.glob("*.html")]}
    require("absorption/index.html" in pages[root / "report.html"].urls, "missing entry")
    count, referenced = 0, set()
    for page, links in list(pages.items()):
        if page.parent != folder:
            continue
        for link in links.urls:
            url = urlsplit(link)
            if url.scheme or url.netloc:
                continue
            dest = (page.parent / unquote(url.path)).resolve() if url.path else page
            require(dest.is_relative_to(root) and dest.is_file(), f"missing local target: {link}")
            if url.fragment and dest.suffix == ".html":
                if dest not in pages:
                    pages[dest] = Links(dest)
                require(unquote(url.fragment) in pages[dest].ids, "missing anchor: " + link)
            count += 1
            if dest in images:
                referenced.add(dest)
    require(referenced == images, "rendered PNG not reachable from an absorption page")
    counts = {}
    for study in result["presentation"]["questions"]:
        ids_on_page = pages[folder / study["page"]].ids
        require(set(study["statuses"]) == set(map(str, range(1, 10))), "nine statuses not found")
        require(all("q-" + study["study"].lower() + "-" + str(n) in ids_on_page for n in range(1, 10)), "question anchor")
        counts[study["study"]] = len(study["statuses"])
    require(counts and len(result["datasets"]) > 0, "no absorption observations or study questions")
    return {"run": run.name, "checkpoint": eda["status"], "requested_model": outer["model"],
            "execution_stages": [{k: row[k] for k in ("stage", "seconds", "status")} for row in outer["stages"]],
            "context_and_first_part_input_hashes_unchanged": True,
            "data_pass_ready_counts": [len(x["ready_dataset_ids"]) for x in outer["data"]["passes"]],
            "admitted_source_tables": len(ids), "EV_technical_verification": tech["status"], "main_EV_figures": tech["figures"],
            "absorption_version": result["version"], "absorption_renderer": result["render"],
            "extravascular_concentration_datasets": len(result["datasets"]),
            "species": [s["species"] for s in result["presentation"]["species"]],
            "questions_by_study": counts, "absorption_pages": len(list(folder.glob("*.html"))),
            "absorption_pngs_decoded": len(images), "absorption_pngs_linked_from_HTML": len(referenced),
            "absorption_page_local_links_checked": count, "artifact_manifest_hashes_checked": len(local),
            "source_tables_sha256": sha(root / "source_tables.json"), "data_report_sha256": sha(report),
            "handoff_sha256": sha(handoff), "absorption_json_sha256": sha(folder / "absorption.json"),
            "plot_specs_sha256": sha(folder / "plot_specs.json"), "EI_run": False, "ER_run": False,
            "human_approval": False, "scientific_release": False, "fit_ready": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    print(json.dumps(inspect(parser.parse_args().run), indent=2, ensure_ascii=False))
