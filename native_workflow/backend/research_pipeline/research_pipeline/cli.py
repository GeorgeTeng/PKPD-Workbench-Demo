import argparse
import json
from pathlib import Path
from .common import PipelineError, read_json, write_json, state_root
from .engine import run_pipeline, validate_request
from .literature import search,LocalLibrary


def main(argv=None):
    parser=argparse.ArgumentParser(description="JSON research pipeline with two R modules")
    parser.add_argument("--state",help="Run storage and local literature database")
    sub=parser.add_subparsers(dest="command",required=True)
    for action in ("run","validate"):
        p=sub.add_parser(action); p.add_argument("request")
    p=sub.add_parser("search"); p.add_argument("--provider",choices=["online","local"],required=True)
    p.add_argument("--query",required=True); p.add_argument("--drug",required=True); p.add_argument("--limit",type=int,default=10); p.add_argument("--out",required=True)
    p=sub.add_parser("index"); p.add_argument("files",nargs="+")
    p=sub.add_parser("serve"); p.add_argument("--port",type=int,default=8765)
    p=sub.add_parser('review'); p.add_argument('submission'); p.add_argument('--out',required=True)
    p=sub.add_parser('prepare-sources', help='B2: split B1 attachment snapshots into source-mapped candidate tables')
    p.add_argument('manifest', help='B1 handoff/main.json (or legacy intake manifest)'); p.add_argument('--out', required=True); p.add_argument('--plan')
    p=sub.add_parser('data-stages', help='Separate lightweight DR, independent coverage and gap disposition')
    from .data_staged_workflow import add_arguments, execute_args
    add_arguments(p)
    args=parser.parse_args(argv); state=state_root(args.state)
    try:
        if args.command == 'data-stages':
            print(json.dumps(execute_args(args), ensure_ascii=False, indent=2))
            return 0
        if args.command=="serve":
            import uvicorn
            from .api import create_app
            uvicorn.run(create_app(state),host="127.0.0.1",port=args.port)
            return 0
        if args.command == 'prepare-sources':
            from .source_preparation import prepare_sources
            value = prepare_sources(args.manifest, args.out, read_json(args.plan) if args.plan else None)
            print(json.dumps({'status':value['status'], 'tables':len(value['tables']),
                              'output':str(Path(args.out).resolve()/'output.json'), 'errors':value['errors']}, ensure_ascii=False, indent=2))
            return 2 if value['status']=='FAILED' else 0
        if args.command=="run":
            request_path=Path(args.request).resolve()
            value=run_pipeline(read_json(request_path),state,request_path.parent)
            print(json.dumps({"status":value["status"],"request_id":value["request_id"],"output":str(state/"runs"/value["request_id"]/"output.json"),"steps":value["steps"]},ensure_ascii=False,indent=2))
            return 0 if value["status"]=="SUCCEEDED" else 2
        if args.command=="validate":
            validate_request(read_json(args.request)); value={"status":"SCHEMA_VALID","scope":"Structure and references only; numerical data validation occurs during run."}
        elif args.command=="search":
            value=search(args.provider,args.query,state,args.limit,args.drug); write_json(args.out,value)
            value={"status":value["status"],"returned":len(value["results"]),"output":str(Path(args.out).resolve())}
        elif args.command=="index":
            library=LocalLibrary(state/"library.sqlite3"); value={"results":[library.index_file(f) for f in args.files]}
        elif args.command=='review':
            from .data_preparation import submit_review
            value=submit_review(state,read_json(args.submission)); write_json(args.out,value)
        print(json.dumps(value,ensure_ascii=False,indent=2)); return 0
    except Exception as exc:
        print(json.dumps({"status":"FAILED","errors":[{"code":getattr(exc,"code","ERROR"),"message":str(exc)}]},ensure_ascii=False,indent=2))
        return 2


if __name__=="__main__":
    raise SystemExit(main())
