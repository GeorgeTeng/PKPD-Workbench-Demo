"""Versioned source renderer; reuse unchanged source projection and coverage contracts."""
from .eda_display_catalog import *
SOURCE_HANDLER=Path(__file__).parent/'resources/eda/source_displays.v5.R'

def render(out,specs,tables,bindings,rscript,legacy_handler,references):
    """One EV dispatch for selected views; no post-hoc supplemental planning."""
    from . import eda_plot_policy
    eda_plot_policy.validate(specs,tables)
    old=[s for s in specs if s["kind"]!="source_projection"]
    new=[s for s in specs if s["kind"]=="source_projection"]
    artifacts=[]
    def execute(handler,path):
        proc=subprocess.run([rscript,"--vanilla",str(handler),str(path),str(out),str(PROJECT/"pkpd_r/eda/plot_style.R")],capture_output=True,text=True,encoding="utf8")
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



def materialize(spec,tables):
    from .eda_display_catalog import materialize as source_materialize
    from .eda_quality_checks_v3 import annotate
    projection,excluded=source_materialize(spec,tables)
    return annotate(projection,tables),excluded

def verify_projection(out,artifact,spec,tables):
    projection,_=materialize(spec,tables)
    actual=read_json(out/artifact['data'])
    require(actual==projection['rows'],'changed source/display projection')
    count=verify_rows([projection],tables)
    require((out/artifact['png']).read_bytes().startswith(b'\x89PNG\r\n\x1a\n'),'invalid PNG')
    return count


def brief(spec):
    from .eda_display_catalog import brief as source_brief
    result=source_brief(spec)
    # Internal tick refinement is not executable/scientific permission. The
    # complete deterministic recipe remains in EV and its bound input.
    result.pop('axis_detail',None)
    result.pop('first_observation',None)
    return result
