"""Generic task-origin records and offline annotation validation, no model calls."""
import copy, hashlib, json

def canonical(x):
    return json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False)
def digest(x):return hashlib.sha256(canonical(x).encode()).hexdigest()
def at(x,path):
    if not isinstance(path,str) or not path.startswith("/"):raise ValueError("Absolute JSON pointer required")
    for k in path.split("/")[1:]:
        k=k.replace("~1","/").replace("~0","~")
        x=x[int(k)] if isinstance(x,list) else x[k]
    return x

def bind_need_boundaries(support,request,ledger):
    """Attach only established origins; never invent a relation to a Rule."""
    out=copy.deepcopy(support)
    origins={r["origin"]["pointer"]:r["origin"] for r in ledger["rows"]
             if r["kind"]=="method_need" and r["origin"]["document"]=="request"}
    out["action_policy"]={
        "method_dependent_execution":"NOT_QUALIFIED_BY_CONTEXT_DELIVERY",
        "conditional_planning":"PRESERVE_WITH_EXPLICIT_LIMITATIONS",
        "unrelated_authoritative_work":"UNCHANGED",
        "interpretation":"Each resolution's reason and needed_for define its local scope. References are exact in-packet pointers, not omitted evidence."}
    needs={n["id"]:(i,n) for i,n in enumerate(request["needs"])}
    if set(needs)!={r["need_id"] for r in out["resolutions"]}:raise ValueError("Need membership mismatch")
    for row in out["resolutions"]:
        i,n=needs[row["need_id"]];p=f"/needs/{i}"
        if p not in origins or origins[p]["sha256"]!=digest(n):raise ValueError("Unbound need origin")
        if row["needed_for"]!=n["needed_for"]:raise ValueError("Changed action scope")
        row["origin"]=copy.deepcopy(origins[p])
        row["required_evidence_depth_ref"]=(f"/task_requirements/needs/{i}/criteria" if n.get("criteria") else "UNKNOWN")
        row["action_boundary"]={
            "affected_outputs":copy.deepcopy(n["needed_for"]),
            "policy_ref":"/action_policy"}
    return out

RELATIONS={"requires","shared_condition","local_condition","exception","counterevidence","source_support"}
def check_span(span,material):
    if set(span)!={"pointer","quote"}:raise ValueError("Unexpected span fields")
    text=at(material,span["pointer"])
    if not isinstance(text,str):raise ValueError("Span must address original string")
    quote=span["quote"]
    if not isinstance(quote,str) or not quote or text.count(quote)!=1:raise ValueError("Quote must occur exactly once")
    a=text.index(quote);b=a+len(quote)
    return {"pointer":span["pointer"],"string_sha256":digest(text),"start":a,"end":b,"quote":span["quote"]}

def validate_proposal(proposal,material,case_id):
    """Return a structural review packet, never an approved relationship map."""
    if proposal.get("case_id")!=case_id:raise ValueError("Wrong case")
    if set(proposal)!={"case_id","relations","counterexamples","unresolved"}:raise ValueError("Unexpected proposal fields")
    rows=[];ids=set()
    for r in proposal["relations"]:
        if set(r)!={"id","kind","from_span","to_span","state","explanation"}:raise ValueError("Unexpected relation fields")
        if not isinstance(r["id"],str) or not r["id"] or r["id"] in ids:raise ValueError("Ambiguous relation ID")
        ids.add(r["id"])
        if r["kind"] not in RELATIONS or r["state"] not in {"PROPOSED","UNKNOWN"}:raise ValueError("Model cannot approve relations")
        rows.append({**copy.deepcopy(r),"from_span":check_span(r["from_span"],material),
                     "to_span":check_span(r["to_span"],material),"review_status":"PENDING_INDEPENDENT_SEMANTIC_REVIEW"})
    for c in proposal["counterexamples"]:
        if set(c)!={"id","scenario","challenged_relation_ids","rationale"}:raise ValueError("Unexpected counterexample")
        if not set(c["challenged_relation_ids"])<=ids:raise ValueError("Counterexample references unknown relation")
    return {"case_id":case_id,"status":"STRUCTURAL_PASS_PENDING_INDEPENDENT_SEMANTIC_REVIEW",
            "material_sha256":digest(material),"proposal_sha256":digest(proposal),"relations":rows,
            "counterexamples":copy.deepcopy(proposal["counterexamples"]),"unresolved":copy.deepcopy(proposal["unresolved"]),
            "active_library_changed":False,"scientific_approval":False}

def validate_review(review,packet):
    """A separate local review must account for every proposed relation."""
    if review.get("proposal_sha256")!=packet["proposal_sha256"] or review.get("material_sha256")!=packet["material_sha256"]:
        raise ValueError("Review does not bind this proposal/material")
    if review.get("reviewer_role")!="INDEPENDENT_LOCAL_REVIEW" or not review.get("reviewer"):
        raise ValueError("Separate local reviewer identity required")
    proposed={r["id"] for r in packet["relations"]}
    decisions=review.get("decisions",[])
    if len(decisions)!=len(proposed) or {d["id"] for d in decisions}!=proposed:raise ValueError("Incomplete review denominator")
    for d in decisions:
        if d.get("decision") not in {"ACCEPT_SCOPED","REJECT","UNKNOWN"} or not d.get("evidence_and_scope"):
            raise ValueError("Evidence-backed scoped decision required")
    return {"status":"SCOPED_REVIEW_RECORDED","accepted_ids":[d["id"] for d in decisions if d["decision"]=="ACCEPT_SCOPED"],
            "unknown_or_rejected_ids":[d["id"] for d in decisions if d["decision"]!="ACCEPT_SCOPED"],
            "semantic_completeness":"UNKNOWN","scientific_approval":False}
