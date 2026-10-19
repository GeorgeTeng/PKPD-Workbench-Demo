"""JSON-in / file-out entry points for the animal PK subworkflow."""
import argparse
from pathlib import Path
from .common import read_json,write_json
from .adequacy import check_ref
from .animal_pk import build_plan
from .animal_pk_comparison import compare_results,begin_review,finish_review


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=['plan','compare','begin-review','review'])
    parser.add_argument('request');parser.add_argument('--out',required=True)
    args=parser.parse_args();request=read_json(args.request);out=Path(args.out)
    if args.action=='plan':
        write_json(out/'architecture.json',build_plan(request['pk_context'],request.get('options')))
    elif args.action=='compare':
        values=[]
        for ref in request['fit_results']:check_ref(ref);values.append(read_json(ref['path']))
        write_json(out/'comparison.json',compare_results(values))
    elif args.action=='begin-review':
        check_ref(request['comparison'])
        begin_review(read_json(request['comparison']['path']),out,request['session_id'],request['species'])
    else:finish_review(out,request)


if __name__=='__main__':main()
