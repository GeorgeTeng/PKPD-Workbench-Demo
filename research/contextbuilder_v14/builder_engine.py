"""Deterministic demand origins, exact declared closure and whole-unit allocation.

No reference labels, card-ID rules, semantic rewrites or retrieval calls.
"""
import copy, hashlib, itertools, json

def canonical(x):
    return json.dumps(x, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)

def digest(x): return hashlib.sha256(canonical(x).encode("utf-8")).hexdigest()
def esc(s): return str(s).replace("~","~0").replace("/","~1")
def pointer(x, path):
    for part in path.split("/")[1:]:
        part=part.replace("~1","/").replace("~0","~")
        x=x[int(part)] if isinstance(x,list) else x[part]
    return x

def demand_ledger(base, task, request):
    docs={"base":base,"task":task,"request":request}
    rows=[]
    def add(kind,doc,path,outputs=(),depth="AUTHORITATIVE_EXACT"):
        value=pointer(docs[doc],path)
        rows.append({"kind":kind,"origin":{"document":doc,"pointer":path,"sha256":digest(value)},
                     "needed_for":list(outputs),"evidence_depth":depth,
                     "answer_status":"NOT_INFERRED","applicability":"NOT_ADJUDICATED"})
    for key in ("purpose","evidence_boundary"):
        if key in task:add("current_duty","task","/"+key)
    for i,_ in enumerate(task.get("model_needs",[])):add("current_duty","task",f"/model_needs/{i}")
    payload=base["request"]["payload"]
    for key in payload:
        add("authoritative_input","base","/request/payload/"+esc(key))
    schema=payload.get("schema",{})
    for key in schema.get("properties",{}):
        add("output_obligation","base","/request/payload/schema/properties/"+esc(key),[key])
    if "required" in schema:add("required_outputs","base","/request/payload/schema/required")
    for i,a in enumerate(request["assignments"]):
        add("upstream_assignment","request",f"/assignments/{i}",[a["output_id"]],"ASSIGNED_RECORD_AND_DECLARED_DEPENDENCIES")
    for i,n in enumerate(request["needs"]):
        add("method_need","request",f"/needs/{i}",n["needed_for"],n.get("criteria") or "UNKNOWN")
    if "artifacts" in request:add("upstream_source_bindings","request","/artifacts")
    return {"version":"BOUND_DEMAND_ORIGINS_1","rows":rows,
            "boundary":"Method topics are supplemental needs, not an exhaustive task inventory. Existing authoritative inputs remain in the original payload. No answered/coverage inference."}

def close(nodes, roots):
    """Return declared reachable nodes, missing targets and cycles separately."""
    reached=set();active=[];cycles=[];missing=set()
    def visit(n):
        if n in active:
            cycles.append(active[active.index(n):]+[n]);return
        if n in reached:return
        if n not in nodes:missing.add(n);return
        reached.add(n);active.append(n)
        for target in nodes[n]["requires"]:visit(target)
        active.pop()
    for root in roots:visit(root)
    return {"nodes":sorted(reached),"missing":sorted(missing),"cycles":cycles}

def compile_units(recalls, allowed_sources, branches=()):
    """Compile only explicit schema links; preserve prose dependencies as unknown."""
    nodes={}; cards=[]; issues={}
    def node(path,value,requires=(),kind="exact_field"):
        nodes[path]={"pointer":path,"sha256":digest(value),"requires":list(requires),"kind":kind}
        return path
    for ri,rec in enumerate(recalls):
        nid=rec["need_id"];issues.setdefault(nid,[])
        ctx=rec["packet"]["context"];app=ctx["applicability_and_examples"]
        prefix=f"/{ri}/packet/context"
        evidence={};bad_ids=set()
        for ei,e in enumerate(app["evidence"]):
            path=prefix+f"/applicability_and_examples/evidence/{ei}"
            sid=e.get("source_id")
            sourcepath=prefix+"/applicability_and_examples/cited_originals/"+esc(sid)
            node(path,e,[sourcepath],kind="source_excerpt")
            if sid in app["cited_originals"]:
                node(sourcepath,app["cited_originals"][sid],kind="source_record")
            if e["id"] in evidence and evidence[e["id"]][1]!=e:bad_ids.add(e["id"])
            evidence[e["id"]]=(path,e)
        for ci,card in enumerate(ctx["general_methods"]):
            path=prefix+f"/general_methods/{ci}";problems=[]
            required=list(dict.fromkeys(card.get("evidence_chunk_ids",[])+
                    [eid for c in card.get("claim_support",[]) for eid in c.get("evidence_chunk_ids",[])]))
            if not required:problems.append("MISSING_DECLARED_EXCERPTS")
            if not set(card.get("source_ids",[]))<=set(allowed_sources):problems.append("SOURCE_NOT_ALLOWED")
            if not set(card.get("required_branches",[]))<=set(branches):problems.append("BRANCH_NOT_ALLOWED")
            for f in ("conditions","limitations","required_inputs"):
                if not card.get(f):problems.append("MISSING_BOUNDARY:"+f)
            for eid in required:
                if eid not in evidence:problems.append("MISSING_EXCERPT:"+eid);continue
                _,e=evidence[eid]
                if eid in bad_ids:problems.append("CONFLICTING_EXCERPT_ID:"+eid)
                if not e.get("text") or not e.get("locator"):problems.append("MISSING_TEXT_OR_LOCATOR:"+eid)
                if e.get("source_id") not in allowed_sources:problems.append("EXCERPT_SOURCE_NOT_ALLOWED:"+eid)
                if e.get("source_id") not in app["cited_originals"]:problems.append("MISSING_SOURCE_RECORD:"+eid)
            for sid in card.get("source_ids",[]):
                if sid not in app["cited_originals"]:problems.append("MISSING_SOURCE_RECORD:"+sid)
            # Entire shared recipe and all unrecognized fields remain required.
            fields=[]
            for key,value in card.items():
                fp=path+"/"+esc(key);fields.append(fp)
                if key=="claim_support":
                    claims=[]
                    for i,claim in enumerate(value):
                        cp=fp+"/"+str(i);claims.append(cp)
                        deps=[path+"/"+f for f in ("conditions","limitations","required_inputs","method_recipe") if f in card]
                        deps += [evidence[e][0] if e in evidence else "MISSING:"+e for e in claim.get("evidence_chunk_ids",[])]
                        node(cp,claim,deps,"declared_claim")
                    node(fp,value,claims,"claim_collection")
                else:
                    deps=[evidence[e][0] if e in evidence else "MISSING:"+e for e in required] if key=="evidence_chunk_ids" else []
                    node(fp,value,deps)
            sourcepaths=[prefix+"/applicability_and_examples/cited_originals/"+esc(s) for s in card.get("source_ids",[])]
            node(path,card,fields+sourcepaths,"whole_card_fallback")
            closure=close(nodes,[path])
            if closure["missing"]:problems.append("DANGLING_DECLARED_REFERENCE")
            cards.append({"need_id":nid,"root":path,"card":copy.deepcopy(card),
                          "evidence":[copy.deepcopy(evidence[e][1]) for e in required if e in evidence],
                          "sources":{s:copy.deepcopy(app["cited_originals"][s]) for s in
                                     dict.fromkeys(card.get("source_ids",[])+[evidence[e][1]["source_id"] for e in required if e in evidence])
                                     if s in app["cited_originals"]},
                          "applicability":{k:copy.deepcopy(v) for k,v in app.items() if k not in ("evidence","cited_originals")},
                          "problems":sorted(set(problems)),"closure":closure})
            issues[nid].extend(problems)
    return {"nodes":nodes,"cards":cards,"issues":{k:sorted(set(v)) for k,v in issues.items()},
            "semantic_relationship_completeness":"UNKNOWN",
            "selection_boundary":"Broad real needs plus incomplete semantic maps require full-card fallback; explicit reference closure alone does not authorize selective deletion."}

def assemble(base,request,task,view,recalls,allowed_sources,branches=(),character_budget=64000,final_fits=lambda x:True):
    ledger=demand_ledger(base,task,request)
    graph=compile_units(recalls,allowed_sources,branches)
    eligible=[c for c in graph["cards"] if not c["problems"]]
    if len(eligible)>16:raise ValueError("Bounded allocator supports at most 16 full-card candidates")
    def build(selected):
        methods={};evidence={};sources={};contexts=[]
        def insert(target,key,value):
            if key in target and target[key]!=value:raise ValueError("Conflicting exact identity:"+key)
            target[key]=copy.deepcopy(value)
        for c in selected:
            insert(methods,c["card"]["id"],c["card"])
            for e in c["evidence"]:insert(evidence,e["id"],e)
            for sid,s in c["sources"].items():insert(sources,sid,s)
            entry={"need_id":c["need_id"],"values":[c["applicability"]]}
            if entry not in contexts:contexts.append(entry)
        resolutions=[]
        for n in request["needs"]:
            nid=n["id"];chosen=[c for c in selected if c["need_id"]==nid]
            excluded=[c for c in eligible if c["need_id"]==nid and c not in selected]
            reasons=graph["issues"].get(nid,[])[:]
            if excluded:reasons.append("WHOLE_CARD_OMITTED_BY_BUDGET")
            if not chosen and not reasons:reasons.append("NO_FROZEN_CANDIDATE")
            resolutions.append({
                "need_id":nid,"needed_for":n["needed_for"],"status":"LOCAL_LIMITATION",
                "content_delivered":bool(chosen),"method_ids":[c["card"]["id"] for c in chosen],
                "evidence_ids":list(dict.fromkeys(e["id"] for c in chosen for e in c["evidence"])),
                "declared_reference_closure":"VERIFIED_FOR_DELIVERED_UNITS" if chosen else "NOT_DELIVERED",
                "relationship_completeness":"UNKNOWN","scientific_sufficiency":"NOT_ASSESSED",
                "reason":("; ".join(reasons)+"; " if reasons else "")+
                    "Only affected method-dependent actions are restricted. Conditional planning and authoritative task evidence remain available; unknown semantic links are not complete."})
        outputs=[{"output_id":a["output_id"],"status":"LIMITED",
                  "unresolved_needs":[n["id"] for n in request["needs"] if a["output_id"] in n["needed_for"]],
                  "reason":"Optional method delivery does not qualify scientific execution. Unrelated authoritative work remains available."}
                 for a in request["assignments"]]
        return {"version":"CONTEXTBUILDER_DECLARED_CLOSURE_2","task_view":copy.deepcopy(view),
                "task_requirements":{"current_duties":copy.deepcopy(task["model_needs"]),"needs":copy.deepcopy(request["needs"])},
                "knowledge":{"methods":list(methods.values()),"evidence":list(evidence.values()),"sources":sources,
                             "applicability_contexts":contexts},
                "resolutions":resolutions,"outputs":outputs,
                "delivery_mode":"EXACT_WHOLE_CARD_FALLBACK_WITH_DECLARED_REFERENCE_CLOSURE",
                "boundary":"Unknown semantic dependencies require full allowed cards within budget. Card fields, recipe, exceptions and declared source excerpts are exact. Reference closure is not scientific sufficiency."}
    best=None
    # Score coverage first, respecting frozen order on ties; never select by card ID.
    for count in range(len(eligible),-1,-1):
        for indices in itertools.combinations(range(len(eligible)),count):
            selected=[eligible[i] for i in indices];support=build(selected)
            if len(canonical(support))>character_budget or not final_fits(support):continue
            score=(-len({c["need_id"] for c in selected}),-len(selected),indices)
            if best is None or score<best[0]:best=(score,support,indices)
        # A smaller set can cover more distinct needs; do not stop prematurely.
    if best is None:raise ValueError("Task view and required limitations exceed unchanged budget")
    audit={"demand_ledger":ledger,"unit_graph":graph,
           "selected_roots":[eligible[i]["root"] for i in best[2]],
           "exact_scope_fallback":True,"reference_only_closure":True}
    return best[1],audit

def choose_encoding(raw,packed,measure_full,decode):
    """Choose packing only on complete input bytes AND character non-regression."""
    if decode(packed)!=raw:raise ValueError("Packed content changed")
    a=measure_full(raw);b=measure_full(packed)
    take=(b["input_utf8_bytes"]<a["input_utf8_bytes"] and b["input_characters"]<=a["input_characters"])
    return (packed if take else raw),{"raw":a,"packed":b,"packed_selected":take,
             "basis":"Complete gateway input, not evidence-view length."}
