"""Default paired PK scales over existing source selectors, never new extraction."""
import copy
import json
from .eda_source_views import numeric, row

POLICY = (
    "For admitted animal PK concentration-time evidence, plan linear and semilog "
    "views by default: absolute profile/peak/sampling on linear axes and relative "
    "decline/low concentrations on log10 axes. Reuse the same source observations "
    "and verified grouping. Zeros, BLQ and missing values do not cancel a usable "
    "semilog view: preserve them in source records with concise per-figure status notes; do not create status subplots; "
    "never add offsets, substitute a limit or bridge unsupported observations. "
    "If no positive concentration with a supported numeric time exists, document "
    "the semilog exception and retain the supported linear/table view. Alternative "
    "time columns stay labeled in companion data; only a recorded source conflict or explicitly requested check offers a separate diagnostic figure. This default does not "
    "mandate paired views for explicitly scoped supplementary datasets. Chosen views still require valid coordinates. It does not apply to categorical endpoints, MIC, dosing designs, in-vitro response or "
    "already-log CFU. A straight segment does not establish a terminal phase or model."
)


def entries(spec, tables):
    """Only established PK selectors with explicit time/concentration semantics."""
    if spec.get("display_policy",{}).get("role")=="TIME_CHECK":return []
    if spec["kind"] == "source_projection":
        if spec["source_recipe"].get("categorical"):
            return []
        series = spec["source_recipe"]["series"]
    elif spec["kind"] == "summary_profile":
        series = [s for p in spec["panels"] for s in p["series"]]
    else:
        return []
    result = []
    for s in series:
        t = tables[s["dataset_id"]]
        is_pk = spec["kind"] == "summary_profile" or t.get("analysis_id") in {
            "A_PK_SOURCE_CURVES", "A_DIGITIZED_PK_CURVES"
        } or t.get("metadata", {}).get("role") in {"PK", "ANIMAL_PK"}
        if t.get('metadata',{}).get('observation_role') is False:
            is_pk = False  # A verified context/supplementary role is not observations.
        if t.get('metadata',{}).get('role_resolution') == 'UNRESOLVED':
            is_pk = False
        columns = {c["id"]: c for c in t["columns"]}
        x, y = columns.get(s.get("x")), columns.get(s["y"])
        if not (is_pk and x and y and x["meaning"] == "TIME"
                and y["meaning"] == "CONCENTRATION"):
            continue
        if "log" in (y["unit"] + " " + y["header"]).lower():
            continue
        # A different group/filter or source time field is a different scope.
        key = json.dumps([s["dataset_id"],s["x"],s["y"],s.get("group",""),
                          s.get("filters",{})],sort_keys=True)
        rows = [r for r in t["records"]
                if all(r["source_raw_values"].get(k)==v for k,v in s.get("filters",{}).items())
                and numeric(r,s["x"])]
        if spec["kind"]=="source_projection":
            projected=[row(t,r,s["y"],x=r["source_raw_values"][s["x"]],
                x_column=s["x"],panel=s["panel"],projection=s["projection"],
                error_column=s["error"],n_column=s["n"]) for r in rows]
            values=[z["y"] for z in projected if z["y"] is not None]
        else:
            values=[r["source_raw_values"][s["y"]] for r in rows if numeric(r,s["y"])]
        result.append((key,s,{"linear":bool(values),"log10":any(v>0 for v in values)}))
    return result


def defaults(candidates, tables):
    """Offer only missing scale/selector combinations; do not duplicate existing ones."""
    out=copy.deepcopy(candidates)
    present={(key,v["y_scale"]) for v in out.values() for key,_,ok in entries(v,tables)
             if ok[v["y_scale"]]}
    for source in candidates.values():
        indexed=entries(source,tables)
        for scale in ("linear","log10"):
            missing={key for key,_,ok in indexed if ok[scale] and (key,scale) not in present}
            if not missing:
                continue
            selected={id(s) for key,s,_ in indexed if key in missing}
            v=copy.deepcopy(source)
            v["id"]=source["id"]+"__DEFAULT_"+scale.upper()
            if v["id"] in out:
                raise ValueError("PK scale candidate ID collision")
            label="linear concentration" if scale=="linear" else "semilog concentration"
            v["title"]=source["title"]+" | default "+label
            v["subtitle"]="Default PK view: "+label+"; unchanged source observations."
            v["y_scale"]=scale
            v["caption"]=source["caption"]+" Display uses "+label+" scaling; no new estimates or substituted values."
            if source["kind"]=="source_projection":
                recipe=v["source_recipe"]
                recipe["series"]=[copy.deepcopy(s) for s in source["source_recipe"]["series"] if id(s) in selected]
                recipe.update(id=v["id"],title=v["title"],question=v["subtitle"],scale=scale,caption=v["caption"])
                v["panels"]=[{"series":[{"dataset_id":s["dataset_id"]} for s in recipe["series"]]}]
            else:
                v["panels"]=[]
                for p in source["panels"]:
                    keep=[copy.deepcopy(s) for s in p["series"] if id(s) in selected]
                    if keep:
                        v["panels"].append({**copy.deepcopy(p),"series":keep})
            out[v["id"]]=v
            present.update((key,scale) for key in missing)
    return out


def requirements(candidates,tables):
    groups={}
    for vid,v in candidates.items():
        for key,s,ok in entries(v,tables):
            g=groups.setdefault(key,dict(dataset_id=s["dataset_id"],time_column=s["x"],
                concentration_column=s["y"],group=s.get("group",""),filters=s.get("filters",{}),
                linear_views=[],log10_views=[],exception=""))
            for scale in ("linear","log10"):
                if scale==v["y_scale"] and ok[scale] and vid not in g[scale+"_views"]:
                    g[scale+"_views"].append(vid)
            if not ok["linear"]:
                g["exception"]="No supported numeric time-concentration pair; retain source table and scoped limitation."
            elif not ok["log10"]:
                g["exception"]="No positive quantified concentration at a supported time; retain linear view and original statuses."
    return list(groups.values())


def validate(selected,candidates,tables,optional_datasets=()):
    selected=set(selected)
    for vid in selected:
        v=candidates[vid];e=entries(v,tables)
        if e and not any(ok[v["y_scale"]] for _,_,ok in e):
            raise ValueError("No supported coordinates for selected PK view: "+vid)
    missing=[]
    for g in requirements(candidates,tables):
        if g["dataset_id"] in optional_datasets:
            continue  # Optional supplementary evidence does not mandate two displays.
        for scale in ("linear","log10"):
            offered=g[scale+"_views"]
            if offered and not selected.intersection(offered):
                missing.append(g["dataset_id"]+"/"+g["time_column"]+"/"+g["concentration_column"]+": "+scale)
    if missing:
        raise ValueError("Default PK scale coverage missing: "+"; ".join(missing))
