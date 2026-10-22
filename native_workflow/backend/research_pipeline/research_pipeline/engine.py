import os
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from jsonschema import Draft202012Validator
from . import __version__
from .attachments import snapshot_attachments
from .common import PROJECT, PipelineError, read_json, write_json, sha256, utcnow, state_root, verify_context
from .literature import search
from .references import canonical_drug, require_reference
from .model_catalog import load_catalog, require_catalog_models
from .tables import load_table, prepare_records
from .data_preparation import run_preparation, resolve_prepared, review_template

SCHEMAS = Path(__file__).parent / "schemas"


def validate_request(request):
    errors = sorted(Draft202012Validator(read_json(SCHEMAS/"request.schema.json")).iter_errors(request), key=lambda e: str(e.path))
    if errors:
        raise PipelineError("INVALID_REQUEST", "; ".join(f"{list(e.path)}: {e.message}" for e in errors[:5]))
    attachments = [a["id"] for a in request["attachments"]]
    if len(set(attachments)) != len(attachments):
        raise PipelineError("DUPLICATE_ATTACHMENT", "Attachment IDs must be unique.")
    seen = set()
    preparation_ids={s['id'] for s in request['steps'] if s['module']=='data_preparation'}
    for step in request["steps"]:
        if step["id"] in seen:
            raise PipelineError("DUPLICATE_STEP", step["id"])
        parent = step["input"].get("upstream_step")
        if parent and parent not in seen:
            raise PipelineError("DEPENDENCY_ORDER", "Steps must be ordered; upstream_step must identify an earlier step.")
        prep=step['input'].get('prepared_step')
        if prep and (prep not in seen or prep not in preparation_ids):
            raise PipelineError('PREPARATION_ORDER','prepared_step must reference an earlier data_preparation step.')
        if preparation_ids and step['module']!='data_preparation' and not prep:
            raise PipelineError('PREPARATION_BYPASS','With a data block present, both modeling branches must use prepared_step.')
        if prep and (not step['input'].get('prepared_dataset') or any(k in step['input'] for k in ['data_attachment','upstream_step','upstream_attachment','doses_attachment'])):
            raise PipelineError('PREPARATION_INPUT','Use a prepared_dataset with no competing raw/upstream data source.')
        if step['module']=='data_preparation' and ('preparation_attachment' not in step['input'] or prep or parent):
            raise PipelineError('PREPARATION_INPUT','Data preparation requires a configuration attachment and no modeling dependency.')
        if sum(k in step["input"] for k in ("upstream_step", "upstream_attachment")) > 1:
            raise PipelineError("AMBIGUOUS_UPSTREAM", step["id"])
        for key, value in step["input"].items():
            if key.endswith("_attachment") and value not in attachments:
                raise PipelineError("MISSING_ATTACHMENT", value)
        seen.add(step["id"])
    if request.get("context_attachment") and request["context_attachment"] not in attachments:
        raise PipelineError("MISSING_CONTEXT", request["context_attachment"])
    if request.get("search") and not request.get("reference_policy", {}).get("drug"):
        raise PipelineError("DRUG_REQUIRED", "Main search requires reference_policy.drug.")
    return request


def rscript_path():
    candidate = os.getenv("PKPD_RSCRIPT") or "C:/Users/georg/Documents/Codex/ScienceEnv/R/bin/Rscript.exe"
    if Path(candidate).is_file():
        return candidate
    found = shutil.which("Rscript")
    if not found:
        raise PipelineError("R_NOT_FOUND", "Set PKPD_RSCRIPT to Rscript.exe.")
    return found


def artifact_info(path, base):
    path = Path(path)
    return {"path": path.relative_to(base).as_posix(), "sha256": sha256(path), "bytes": path.stat().st_size}


def execute_step(step, request, attachments, run, completed):
    directory = run / "steps" / step["id"]
    directory.mkdir(parents=True)
    output = {"schema_version":"1.0", "request_id":request["request_id"], "step_id":step["id"],
              "module":step["module"], "status":"FAILED", "result":None, "artifacts":[], "provenance":{}, "warnings":[], "errors":[]}
    try:
        source = step["input"]; options = step["options"]; metadata = step.get("metadata", {})
        if step['module']=='data_preparation':
            output['status'],output['result']=run_preparation(step,attachments,directory,request.get('context_attachment'))
            output['provenance']={'created_at':utcnow(),'software_version':__version__,
                                  'source_hashes':output['result']['source_hashes']}
            write_json(directory/'review_submission.template.json',review_template(request['request_id'],step['id'],output['result']))
            return finish_step(output,directory,run)
        worker = {"schema_version":"1.0", "module":step["module"], "options":options, "metadata":metadata}
        used = {}
        if source.get('prepared_step'):
            path=run/'steps'/source['prepared_step']/'output.json'
            parent=read_json(path)
            if parent['status']!='SUCCEEDED':
                output['status']='SKIPPED'
                raise PipelineError('DATA_REVIEW_PENDING','Data preparation needs correction or explicit human confirmation.')
            if source['prepared_dataset'] not in parent['result']['released_datasets']:
                output['status']='SKIPPED'
                raise PipelineError('DATASET_NOT_RELEASED','Human review has not released this branch dataset.')
            group=resolve_prepared(parent,source['prepared_dataset'],step['module'])
            if (options and options!=group['analysis_options']) or (metadata and metadata!=group['metadata']):
                raise PipelineError('REVIEWED_CONFIGURATION_CHANGED','Keep approved metadata/options, or request a new assessment.')
            metadata=group['metadata']; options=group['analysis_options']
            worker.update(metadata=metadata,options=options,records=group['records'])
            write_json(directory/'prepared_records.json',{'records':group['records']})
            write_json(directory/'excluded_records.json',{'records':group['quarantine']})
            used['preparation:'+source['prepared_step']]=sha256(path)
            output['provenance']['data_assessment_sha256']=parent['result']['assessment_sha256']
            output['provenance']['human_review']=parent['result']['review']
        if "data_attachment" in source:
            attachment = attachments[source["data_attachment"]]; used[attachment["id"]] = attachment["sha256"]
            if Path(attachment['path']).suffix.lower() == '.json':
                candidate = read_json(attachment['path'])
                if isinstance(candidate, dict) and candidate.get('fit_ready') is False:
                    raise PipelineError('SOURCE_REVIEW_REQUIRED', 'Source-preparation candidates must enter data_preparation QC and human release before modeling.')
            records = load_table(attachment["path"], source.get("table"))
            columns = [options.get("index_column"), options.get("response_column")] + options.get("index_columns",[])
            records, excluded = prepare_records(records, options.get("excluded_statuses", []), [c for c in columns if c])
            worker["records"] = records
            write_json(directory/"prepared_records.json", {"records":records})
            write_json(directory/"excluded_records.json", {"records":excluded})
            if excluded:
                output["warnings"].append(f"Explicitly excluded {len(excluded)} marked records; no imputation. See excluded_records.json; BLQ exclusion may bias PK.")
            if any("drug" in r and canonical_drug(r["drug"]) != canonical_drug(metadata.get("drug", "")) for r in records):
                raise PipelineError("DRUG_MISMATCH", "Data drug must match explicit metadata; do not pool drugs.")
        if "doses_attachment" in source:
            attachment = attachments[source["doses_attachment"]]; used[attachment["id"]] = attachment["sha256"]
            worker["doses"], excluded = prepare_records(load_table(attachment["path"]))
        elif options.get("doses"):
            worker["doses"], _ = prepare_records(options["doses"])
        if "upstream_step" in source:
            parent = completed[source["upstream_step"]]
            if parent["status"] != "SUCCEEDED":
                output["status"] = "SKIPPED"
                raise PipelineError("UPSTREAM_FAILED", "Upstream step did not succeed.")
            # Deliberately read the persisted JSON, not the parent's in-memory R object.
            path = run / "steps" / source["upstream_step"] / "output.json"
            worker["upstream_result"] = read_json(path)
            used["upstream:"+source["upstream_step"]] = sha256(path)
        elif "upstream_attachment" in source:
            attachment = attachments[source["upstream_attachment"]]
            worker["upstream_result"] = read_json(attachment["path"])
            used[attachment["id"]] = attachment["sha256"]
        if "upstream_result" in worker:
            Draft202012Validator(read_json(SCHEMAS/"module-output.schema.json")).validate(worker["upstream_result"])
            for model in (worker["upstream_result"].get("result") or {}).get("models", []):
                target = request.get("reference_policy", {}).get("drug")
                if target and canonical_drug(model.get("metadata", {}).get("drug", "")) != canonical_drug(target):
                    raise PipelineError("UPSTREAM_DRUG_MISMATCH", "Upstream model is for a different drug.")
        policy = request.get("reference_policy", {})
        catalog_id = source.get('model_catalog_attachment')
        if catalog_id or options.get('model_catalog_ids'):
            if not catalog_id:
                raise PipelineError('CATALOG_ATTACHMENT_REQUIRED', 'model_catalog_ids require model_catalog_attachment')
            attachment = attachments[catalog_id]
            catalog = load_catalog(attachment['path'])
            assessment = require_catalog_models(catalog, options.get('model_catalog_ids'), step['module'], options, metadata, worker)
            write_json(directory/'catalog_assessment.json', assessment)
            used[catalog_id] = attachment['sha256']
            output['provenance']['model_catalog'] = assessment
            output['warnings'].append('Catalog rules preserved for review; configuration compatibility does not establish scientific acceptance.')
        if policy.get("drug") and metadata.get("drug") and canonical_drug(metadata["drug"]) != canonical_drug(policy["drug"]):
            raise PipelineError("REFERENCE_DRUG_MISMATCH", "Request drug and module metadata differ.")
        if options.get("reference_mode", "baseline") == "paper_guided":
            refid = source.get("reference_attachment")
            if not refid:
                raise PipelineError("REFERENCE_REQUIRED", "paper_guided mode requires a reviewed model card and its source document attachment.")
            attachment = attachments[refid]
            card = read_json(attachment["path"])
            verdict = require_reference(card, metadata.get("drug",policy.get("drug","")), metadata,
                [a["sha256"] for a in attachments.values()], options.get("compartments",1), step["module"])
            write_json(directory/"reference_assessment.json", verdict)
            used[refid] = attachment["sha256"]
            output["provenance"]["reference_assessment"] = verdict
        else:
            output["warnings"].append("Baseline analysis; no claim of a literature-validated model or accepted reference.")
        output["provenance"].update({"attachment_sha256":used, "created_at":utcnow(), "software_version":__version__,
                                     "reference_mode":options.get("reference_mode","baseline")})
        worker["provenance"] = output["provenance"]
        write_json(directory/"input.json", worker)
        process = subprocess.run([rscript_path(), "--vanilla", str(PROJECT/"pkpd_r/modules/worker.R"),
                    str(directory/"input.json"), str(directory/"r_result.json")],
                    cwd=PROJECT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180,
                    creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
        (directory/"R.stdout.log").write_text(process.stdout,encoding="utf-8")
        (directory/"R.stderr.log").write_text(process.stderr,encoding="utf-8")
        if not (directory/"r_result.json").exists():
            raise PipelineError("R_PROCESS_FAILED", "R did not produce a JSON result. See R.stderr.log.")
        result = read_json(directory/"r_result.json")
        if process.returncode or result.get("status") != "SUCCEEDED":
            raise PipelineError(result.get("error",{}).get("code","R_PROCESS_FAILED"),result.get("error",{}).get("message","R process failed."))
        output["result"] = result["result"]; output["status"] = "SUCCEEDED"
        write_json(directory/"model_review.template.json", {
            "schema_version":"1.0", "request_id":request["request_id"], "step_id":step["id"],
            "scope":"model_results", "result_sha256":sha256(directory/"r_result.json"),
            "decision":"PENDING", "reviewer":"", "rationale":"", "selected_models":[],
            "approved_for_downstream_use":False,
            "note":"Result review template only; this is separate from /v1/data-reviews and does not submit or enforce model approval."
        })
        for model in result["result"].get("models",[]):
            output["warnings"].extend(model.get("warnings",[]))
    except subprocess.TimeoutExpired:
        output["errors"].append({"code":"R_TIMEOUT","message":"R exceeded 180 seconds; no successful result is claimed."})
    except Exception as exc:
        output["errors"].append({"code":getattr(exc,"code","STEP_ERROR"),"message":str(exc)})
    return finish_step(output,directory,run)


def finish_step(output,directory,run):
    output["artifacts"] = [artifact_info(p,run) for p in sorted(directory.rglob("*")) if p.is_file() and p.name not in ("output.json",)]
    Draft202012Validator(read_json(SCHEMAS/"module-output.schema.json")).validate(output)
    write_json(directory/"output.json",output)
    return output


def run_pipeline(request, state=None, base=None, allow_paths=True):
    validate_request(request)
    state = state_root(state); run = state / "runs" / request["request_id"]
    try:
        run.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        raise PipelineError("RUN_EXISTS", "Use a new request_id; existing runs are immutable.")
    write_json(run/"request.json", request)
    output = {"schema_version":"1.0", "request_id":request["request_id"], "status":"RUNNING", "steps":[], "errors":[], "warnings":[], "artifacts":[], "context":None}
    write_json(run/"output.json",output)
    try:
        attachments = snapshot_attachments(request["attachments"],run/"attachments",state,base or Path.cwd(),allow_paths)
        write_json(run/"attachments.json",attachments)
        if request.get("context_attachment"):
            output["context"] = verify_context(read_json(attachments[request["context_attachment"]]["path"]))
            write_json(run/"context.json",output["context"])
        if request.get("search"):
            settings = request["search"]
            try:
                found = search(settings["provider"],settings["query"],state,settings.get("limit",10),request.get("reference_policy",{}).get("drug"))
                write_json(run/"literature_search.json",found)
            except PipelineError as exc:
                write_json(run/"literature_search.json",{"status":"FAILED","provider":settings["provider"],"error":{"code":exc.code,"message":str(exc)}})
                if settings.get("required",False):
                    raise
                output["warnings"].append("Optional literature search failed; see literature_search.json.")
        completed = {}; pending = list(request["steps"])
        # Independent branches run in the same wave; optional explicit helper
        # dependencies are honored without imposing PK -> index on the workflow.
        with ThreadPoolExecutor(max_workers=2) as executor:
            while pending:
                ready = [s for s in pending if all(s['input'][k] in completed for k in ('upstream_step','prepared_step') if k in s['input'])]
                if not ready:
                    raise PipelineError("UNRESOLVED_DEPENDENCY", "No runnable branch.")
                futures = {executor.submit(execute_step,s,request,attachments,run,dict(completed)):s for s in ready}
                for future in as_completed(futures):
                    step=futures[future]; completed[step["id"]]=future.result()
                    pending.remove(step)
        for step in request["steps"]:
            result=completed[step["id"]]
            output["steps"].append({"id":step["id"],"module":step["module"],"status":result["status"],
                                    "output":artifact_info(run/"steps"/step["id"]/"output.json",run)})
        successful = sum(s["status"]=="SUCCEEDED" for s in output["steps"])
        output["status"] = "SUCCEEDED" if successful==len(output["steps"]) else "PARTIAL" if successful else "FAILED"
        if any(s['status']=='WAITING_FOR_REVIEW' for s in output['steps']): output['status']='WAITING_FOR_REVIEW'
        elif any(s['status']=='BLOCKED' for s in output['steps']): output['status']='BLOCKED'
    except Exception as exc:
        output["status"] = "FAILED"
        output["errors"].append({"code":getattr(exc,"code","PIPELINE_ERROR"),"message":str(exc)})
    output["completed_at"] = utcnow()
    output["artifacts"] = [artifact_info(p,run) for p in sorted(run.rglob("*")) if p.is_file() and p != run/"output.json"]
    write_json(run/"output.json",output)
    return output
