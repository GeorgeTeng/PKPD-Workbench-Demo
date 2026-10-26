"""Formal source-display recipes, deterministic coverage accounting and R dispatch."""
from __future__ import annotations
import copy
import hashlib
import json
import re
import subprocess
from pathlib import Path
from .common import PROJECT, read_json, write_json
from . import context_builder as cb
from .eda_source_views import numeric, row, verify_rows

RECIPES=Path(__file__).parent/"resources/eda/source_view_recipes.v1.json"
SOURCE_HANDLER=PROJECT/"pkpd_r/eda/source_displays.R"


def require(ok,message):
    if not ok: raise ValueError("EDA catalog: "+message)


def sources(spec):
    return sorted({s["dataset_id"] for p in spec["panels"] for s in p.get("series",[p])})


def augment(candidates,tables,*,match_report=None):
    """Match source semantics, not T-number alone. New records use the same selectors."""
    result=copy.deepcopy(candidates)
    for registered in read_json(RECIPES)["recipes"]:
        mapping={}; dependencies=[]
        for original,signature in registered["sources"].items():
            matches=[did for did,t in tables.items() if t["title"]==signature["title"]
                and [{k:c[k] for k in ("id","header","unit","meaning")} for c in t["columns"]]==signature["columns"]
                and hashlib.sha256(t["notes"].encode()).hexdigest()==signature["notes_sha256"]]
            dependencies.append({'source_id':original,'matched_dataset_ids':matches,
                'status':'MATCHED' if len(matches)==1 else 'MISSING' if not matches else 'AMBIGUOUS',
                'required_fields':['title','columns.id','columns.header','columns.unit','columns.meaning','notes_sha256']})
            if len(matches)==1:mapping[original]=matches[0]
        applied=len(mapping)==len(registered['sources']) and len(set(mapping.values()))==len(mapping)
        if match_report is not None:
            match_report.append({'recipe_id':registered['id'],'status':'MATCHED' if applied else 'NOT_APPLIED',
                'mapping':mapping,'dependencies':dependencies,
                'reason':'' if applied else 'Requires one unique source for every full title/column/notes signature; no guessed mapping.'})
        if not applied:continue
        recipe=copy.deepcopy(registered)
        for s in recipe["series"]:
            original=s["dataset_id"];actual=mapping[original];s["dataset_id"]=actual
            s["panel"]=s["panel"].replace(original,actual)
            s["category_prefix"]=s["category_prefix"].replace(original,actual)
        spec=dict(id=recipe["id"],kind="source_projection",title=recipe["title"],
            subtitle=recipe["question"],caption=recipe["caption"],y_scale=recipe["scale"],
            panels=[{"series":[{"dataset_id":s["dataset_id"]} for s in recipe["series"]]}],
            source_recipe=recipe)
        require(spec["id"] not in result,"duplicate registered view ID")
        # Refuse an invalid registered recipe before it becomes an EP option.
        materialize(spec,tables)
        result[spec["id"]]=spec
    return result


def materialize(spec,tables):
    recipe=copy.deepcopy(spec["source_recipe"]);rows=[];excluded=[];seen=set()
    for s in recipe["series"]:
        t=tables[s["dataset_id"]];ordinal=0
        for r in t["records"]:
            if recipe.get("record_scope") and r["record_id"] not in recipe["record_scope"].get(t["dataset_id"],[]):continue
            if not all(r["source_raw_values"].get(k)==v for k,v in s["filters"].items()):continue
            if s["x"] and not numeric(r,s["x"]):
                excluded.append(dict(dataset_id=t["dataset_id"],record_id=r["record_id"],
                    column=s["x"],reason="Non-numeric source X retained in companion table",raw=r["source_raw_values"].get(s["x"])))
                continue
            ordinal+=1
            if s["x"]:x=r["source_raw_values"][s["x"]]
            elif s["x_from_header"]:
                header=next(c["header"] for c in t["columns"] if c["id"]==s["y"])
                unit=s.get("x_header_unit","h")
                require(unit in {"h","min"},"unsupported source header time unit")
                require(re.search(r"\("+unit+r"(?:\s*;[^()]*)?\)",recipe["x_label"]) is not None,"source header unit must match displayed axis")
                match=re.fullmatch(r"(?:Residual % at )?(\d+(?:\.\d+)?)\s+"+unit,header)
                require(match is not None,"time must be explicit in source header")
                x=float(match.group(1))
            else:x=ordinal
            category=s["category_prefix"]+str(r["source_raw_values"][s["category_column"]]) if s["category_column"] else ""
            z=row(t,r,s["y"],x=x,panel=s["panel"],group=s["group"],x_column=s["x"],
                category=category,projection=s["projection"],error_column=s["error"],n_column=s["n"])
            if recipe["scale"]=="log10" and z["y"] is not None and z["y"] <= 0:
                z["plot_eligible"]=False
                z["display_exclusion_reason"]="Nonpositive source value cannot use log10 axis"
            if s["x_from_header"]:z["x_header"]=header
            key=(z["dataset_id"],z["record_id"],z["y_column"])
            require(key not in seen,"duplicate source coordinate within view")
            seen.add(key);rows.append(z)
    require(rows and any(z["y"] is not None for z in rows),"registered display has no usable coordinates")
    # Detect new groups/records silently omitted by a registered categorical selector.
    for did,y in {(s["dataset_id"],s["y"]) for s in recipe["series"]}:
        configured=[s for s in recipe["series"] if s["dataset_id"]==did and s["y"]==y]
        expected={r["record_id"] for r in tables[did]["records"]
                  if (not recipe.get("record_scope") or r["record_id"] in recipe["record_scope"].get(did,[]))
                  and any(not s["x"] or numeric(r,s["x"]) for s in configured)}
        actual={r["record_id"] for r in rows if r["dataset_id"]==did and r["y_column"]==y}
        require(actual==expected, did+": source groups/records are not fully represented by the registered selectors")
    recipe["rows"]=rows
    verify_rows([recipe],tables)
    return recipe,excluded


def fields(spec,did):
    if spec["kind"]=="source_projection":
        return {s[k] for s in spec["source_recipe"]["series"] if s["dataset_id"]==did for k in ("x","y","error","n") if s[k]}
    return {s[k] for p in spec["panels"] for s in p.get("series",[p]) if s["dataset_id"]==did
            for k in ("x","y","error","n","baseline") if s.get(k)} | {
            c for p in spec["panels"] for s in p.get("series",[p]) if s["dataset_id"]==did for c in s.get("value_columns",[])}


def relevant_fields(table):
    # No new scientific applicability decision: expose potential display fields for EP.
    return {c["id"] for c in table["columns"] if c["meaning"] in
            {"CONCENTRATION","RESPONSE","MIC","BINDING","DOSE"}}


def inventory(tables,candidates):
    return [dict(dataset_id=did,title=t["title"],candidate_ids=[v["id"] for v in candidates.values() if did in sources(v)],
        display_fields=sorted(relevant_fields(t)),
        fields_without_recipe=sorted(relevant_fields(t)-set().union(*(fields(v,did) for v in candidates.values()))))
        for did,t in tables.items()]


def brief(spec):
    out={k:copy.deepcopy(v) for k,v in spec.items() if k!="source_recipe"}
    if spec["kind"]=="source_projection":
        r=spec["source_recipe"]
        out["display_contract"]={k:r[k] for k in ("question","x_label","y_label","scale","categorical","facet_scales")}
        out["source_fields"]={did:sorted(fields(spec,did)) for did in sources(spec)}
        out["projection_modes"]=sorted({s["projection"] for s in r["series"]})
    return out


def coverage(dispositions,selected,candidates,tables,*,match_report=None):
    require(isinstance(dispositions,list),"dataset_dispositions required")
    ids=[d["dataset_id"] for d in dispositions]
    require(len(ids)==len(set(ids)) and set(ids)==set(tables),"every admitted dataset must be accounted for exactly once")
    output=[]
    for d in dispositions:
        did=d["dataset_id"]
        chosen=[vid for vid in selected if did in sources(candidates[vid])]
        offered=[vid for vid,v in candidates.items() if did in sources(v)]
        shown=set().union(*(fields(candidates[v],did) for v in chosen))
        unshown=relevant_fields(tables[did])-shown
        require(len(d["unshown_columns"])==len(set(d["unshown_columns"])) and set(d["unshown_columns"])==unshown,
                did+": unshown source fields must be disclosed exactly")
        require(not chosen or d["status"]=="DISPLAYED",did+": selected view mislabeled")
        require(d["status"]!="DISPLAYED" or chosen,did+": claimed display without a selected view")
        require(d["status"] in {"DISPLAYED","CONTEXT_ONLY","NEEDS_CAPABILITY"},did+": unknown disposition")
        require(bool(d["reason"].strip()) and (not unshown and chosen or len(d["reason"].strip())>=20),
                did+": scoped reason required for unshown data")
        require(not (d["status"]=="NEEDS_CAPABILITY" and offered and not (unshown-set().union(*(fields(candidates[v],did) for v in offered)))),
                did+": supported fields cannot be dismissed as unavailable renderer")
        output.append({**d,"selected_views":chosen,"offered_views":offered,
            "fields_without_recipe":sorted(relevant_fields(tables[did])-set().union(*(fields(candidates[v],did) for v in offered)))})
    from .eda_dose_normalization import coverage as dose_coverage
    return dict(status="ALL_DATASETS_ACCOUNTED",datasets=output,
        dose_normalization_assessment=dose_coverage(selected,candidates,tables),
        recipe_match_report=copy.deepcopy(match_report or []),
        candidate_gaps=[d["dataset_id"] for d in output if d["fields_without_recipe"]],
        graphical_coverage_is_not_scientific_adequacy=True)


def render(out,specs,tables,bindings,rscript,legacy_handler,references):
    """One EV dispatch for selected views; no post-hoc supplemental planning."""
    from . import eda_plot_policy
    eda_plot_policy.validate(specs,tables)
    old=[s for s in specs if s["kind"]!="source_projection"]
    new=[s for s in specs if s["kind"]=="source_projection"]
    artifacts=[]
    def execute(handler,path):
        proc=subprocess.run([rscript,"--vanilla",str(handler),str(path),str(out)],capture_output=True,text=True,encoding="utf8")
        (out/(path.stem+".log")).write_text(proc.stdout+"\n"+proc.stderr,encoding="utf8")
        require(proc.returncode==0,proc.stderr)
    if old:
        write_json(out/"legacy_render_request.json",dict(version="QUESTION_DISPLAYS_1",input_ref=bindings["completed_ec_result"],
            rules_ref=bindings.get("rules"),plots=old,references=references))
        execute(legacy_handler,out/"legacy_render_request.json")
        artifacts.extend(read_json(out/"manifest.json")["artifacts"])
    if new:
        projections=[materialize(s,tables) for s in new]
        write_json(out/"source_render_request.json",dict(version="SOURCE_DISPLAYS_1",plots=[p for p,_ in projections]))
        execute(SOURCE_HANDLER,out/"source_render_request.json")
        new_artifacts=read_json(out/"manifest.json")["artifacts"]
        for a,s,(_,excluded) in zip(new_artifacts,new,projections,strict=True):
            a["kind"]="source_projection";a["dataset_ids"]=sources(s);a["audit"]=a["id"]+".audit.json"
            write_json(out/a["audit"],dict(segments=[],excluded_x=excluded,
                source_status_unchanged=True,scientific_release=False))
        artifacts.extend(new_artifacts)
    write_json(out/"manifest.json",dict(version="QUESTION_DISPLAYS_2",artifacts=artifacts,scientific_release=False,model_calls=0))


def verify_projection(out,artifact,spec,tables):
    expected,_=materialize(spec,tables)
    actual=read_json(out/artifact["data"])
    require(actual==expected["rows"],"rendered source projection differs from formal recipe")
    verify_rows([{**expected,"rows":actual}],tables)
    require((out/artifact["png"]).read_bytes().startswith(b"\x89PNG\r\n\x1a\n"),"invalid PNG")
    return sum(r["y"] is not None and r.get("plot_eligible",True) for r in actual)
