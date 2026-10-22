"""Descriptive EDA human gate and scoped PK/PD intake; never fits or approves itself."""
import argparse
import copy
import html
from datetime import datetime
from pathlib import Path
from ctxcomp.io import digest
from . import context_builder as cb
from . import eda_dataset_routes as routes
from .common import read_json, write_json

def require(value,message):
    if not value:raise ValueError("EDA handoff: "+message)

def packet(root):
    root=Path(root);p=read_json(root/"human_review.json")
    expected=p.pop("content_sha256")
    require(digest(p)==expected,"review packet changed")
    cb.check_refs(p["bindings"])
    p["content_sha256"]=expected
    return p

def build(root,inputs,findings,review,bindings=None):
    root=Path(root)
    require(not (root/"human_review.json").exists(),"review packet already exists; create a new version")
    require(findings["version"]=="QUESTION_FINDINGS_3","descriptive findings required")
    require(all("model_advice" not in f for f in findings["findings"]),"model choices belong downstream")
    require(review["decision"]!="PASS" or not review["issues"],"PASS has unresolved issues")
    # One immutable shared context; branch contracts select source IDs rather than copying data.
    write_json(root/"handoff_context.json",inputs)
    write_json(root/"descriptive_findings.json",findings)
    write_json(root/"independent_review.json",review)
    refs=dict(bindings or {})
    refs.update(context=cb.file_ref(root/"handoff_context.json"),
                findings=cb.file_ref(root/"descriptive_findings.json"),
                review=cb.file_ref(root/"independent_review.json"))
    cb.check_refs({"table":inputs["figure_bundle"]["tables"]["host_file"]})
    tables_path=Path(inputs["figure_bundle"]["tables"]["host_file"]["path"])
    refs["source_tables"]=cb.file_ref(tables_path)
    tables=read_json(tables_path);table_ids={t['dataset_id'] for t in tables}
    from .eda_plot_policy import working_tables
    working=working_tables({t['dataset_id']:t for t in tables})
    write_json(root/'working_tables.json',list(working.values()))
    refs['working_tables']=cb.file_ref(root/'working_tables.json')
    ledger=routes.build(tables,inputs['eda_plan'].get('dataset_dispositions'),inputs['figure_bundle']['figures'])
    write_json(root/'dataset_routing.json',ledger)
    refs['dataset_routing']=cb.file_ref(root/'dataset_routing.json')
    figures=inputs["figure_bundle"]["figures"]
    for f in figures:
        refs["image:"+f["figure_id"]]=f["image_ref"]
    branches={}
    for branch in ("PK","PD"):
        routed=routes.branch(ledger,branch)
        branch_questions=({"Q_PK_SHAPE","Q_PK_VARIABILITY"} if branch=="PK" else {"Q_PD_EFFECT","Q_INDEX","Q_TIMEKILL"})
        branches[branch]={
            "branch":branch,"status":"BLOCKED_PENDING_HUMAN_APPROVAL",
            **routed,"dataset_routing_ref":refs["dataset_routing"],
            "figure_ids":sorted({fid for row in routed["dataset_routing"] for fid in row["figure_ids"]}),
            "finding_ids":[f["finding_id"] for f in findings["findings"] if set(f["analysis_ids"]) & (branch_questions|{"Q_CONTEXT"})],
            "context_ref":refs["context"],"source_tables_ref":refs["working_tables"],"original_source_tables_ref":refs["source_tables"],"findings_ref":refs["findings"],
            "rules_source":"task_context.project_rules in context_ref; carry clauses and exceptions unchanged",
            "open_items":findings["open_items"],"limitations":findings["limitations"],
            "excluded_sources":["Human target-drug observations and protected human benchmarks","Held-out horse PK"],
            "next_step":"Branch-specific input qualification, then model design and fitting within the qualified scope.",
            "model_selected":False,"fit_ready":False,"model_execution_started":False}
    write_json(root/"branch_drafts.json",branches)
    refs["branch_drafts"]=cb.file_ref(root/"branch_drafts.json")
    cb.check_refs(refs)
    p={"version":"EDA_QUESTION_HUMAN_PACKET_1","status":"WAITING_FOR_HUMAN_REVIEW" if review["decision"]=="PASS" else "REVIEW_REQUIRED",
       "bindings":refs,"review_decision":review["decision"],
       "summary":{"findings":findings["findings"],"limitations":findings["limitations"],
                  "open_items":findings["open_items"],"issues":review["issues"],"unreviewed_items":review["unreviewed_items"]},
       "required_figure_review_ids":[f["figure_id"] for f in figures],
       "branches":["PK","PD"],"human_confirmation":None,"fit_ready":False,"scientific_release":False,
       "handoff_eligible_after_human_confirmation":review["decision"]=="PASS"}
    p["content_sha256"]=digest(p)
    write_json(root/"human_review.json",p)
    write_json(root/"human_decision.template.json",{
        "actor_type":"HUMAN","reviewer":"","reviewed_at":"","packet_sha256":p["content_sha256"],
        "decision":"PENDING","images_inspected":False,"limitations_acknowledged":False,
        "accepted_open_items":[],"accepted_unreviewed_items":[],
        "figure_reviews":[{"figure_id":f["figure_id"],"decision":"PENDING"} for f in figures]})
    render(root,p,figures)
    return p

def render(root,p,figures):
    from .eda_review_ui import render as render_review
    return render_review(root,p,figures)

def confirm(root,decision_path):
    root=Path(root);p=packet(root);decision_ref=cb.file_ref(decision_path);d=read_json(decision_path)
    require(not (root/"approved_release.json").exists(),"already released")
    require(d.get("actor_type")=="HUMAN" and bool(str(d.get("reviewer","")).strip()),"explicit identified human required")
    require(bool(d.get("reviewed_at")),"review timestamp required")
    datetime.fromisoformat(d["reviewed_at"].replace("Z","+00:00"))
    require(d.get("decision")=="APPROVE_DESCRIPTIVE_EDA" and d.get("packet_sha256")==p["content_sha256"],"approval must name this packet")
    require(p["review_decision"]=="PASS" and not p["summary"]["issues"],"unresolved independent review")
    require(d.get("images_inspected") is True and d.get("limitations_acknowledged") is True,"visual and limitation acknowledgement required")
    if "required_figure_review_ids" in p:
        routes.validate_figure_review(p["required_figure_review_ids"],d)
    for key in ["open_items","unreviewed_items"]:
        require(d.get("accepted_"+key)==p["summary"][key],"scope acknowledgement differs: "+key)
    branches=read_json(root/"branch_drafts.json")
    # Final release marker is written last; branch readers cannot use partial drafts.
    approved=root/"approved";approved.mkdir(exist_ok=False)
    for branch,data in branches.items():
        item=copy.deepcopy(data);item.update(status="READY_FOR_INPUT_QUALIFICATION",
            human_decision_ref=decision_ref,review_packet_ref=cb.file_ref(root/"human_review.json"),
            review_packet_sha256=p["content_sha256"])
        for row in item.get("dataset_routing",[]):
            row["packaging_status"]="PACKAGED_FOR_INPUT_QUALIFICATION"
        write_json(approved/(branch+".json"),item)
    cb.check_refs(p["bindings"]);cb.check_refs({"decision":decision_ref})
    release={"version":"EDA_BRANCH_RELEASE_1","packet_sha256":p["content_sha256"],
             "packet_ref":cb.file_ref(root/"human_review.json"),"decision_ref":decision_ref,
             "branches":{b:cb.file_ref(approved/(b+".json")) for b in ["PK","PD"]},
             "model_execution_started":False,"fit_ready":False,"scientific_release":False}
    write_json(root/"approved_release.json",release)
    # Approval is immutable. Routing can be retried independently via
    # python -m research_pipeline.eda_task_assignment --run <root>.
    from .eda_task_assignment import build as assign_tasks
    assign_tasks(root)
    return release

def branch_input(root,branch):
    require(branch in {"PK","PD"},"unknown branch")
    root=Path(root);p=packet(root)
    require((root/"approved_release.json").is_file(),"human approval required")
    release=read_json(root/"approved_release.json")
    require(release["packet_sha256"]==p["content_sha256"],"release packet differs")
    cb.check_refs({"packet":release["packet_ref"],"decision":release["decision_ref"],**release["branches"]})
    return read_json(release["branches"][branch]["path"])

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root");parser.add_argument("--decision",required=True)
    args=parser.parse_args()
    confirm(args.root,args.decision)

if __name__=="__main__":main()
