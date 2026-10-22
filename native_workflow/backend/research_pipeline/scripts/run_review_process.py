"""Execute a JSON-in/JSON-out R review in a fresh folder, preserving audit evidence."""
import argparse
import os
from pathlib import Path
import subprocess
from research_pipeline.common import PROJECT, read_json, write_json, sha256, utcnow
from research_pipeline.engine import rscript_path


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input',type=Path,required=True)
    p.add_argument('--r-script',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();out=a.out.resolve();out.mkdir(parents=True,exist_ok=False)
    src=a.input.resolve();script=a.r_script.resolve()
    helpers=list((PROJECT/'pkpd_r/R').glob('*.R'))+[PROJECT/'pkpd_r/load.R',script]
    before={str(f):sha256(f) for f in helpers}
    for f in helpers:
        snapshot=out/'code_snapshot'/f.relative_to(PROJECT/'pkpd_r')
        snapshot.parent.mkdir(parents=True,exist_ok=True)
        snapshot.write_bytes(f.read_bytes())
        if sha256(snapshot)!=before[str(f)]:raise RuntimeError('Code snapshot mismatch')
    record={'status':'RUNNING','started_at':utcnow(),'pid':os.getpid(),
      'input_source':{'path':str(src),'sha256':sha256(src)},'code_sha256':before}
    write_json(out/'input.json',read_json(src))
    command=[rscript_path(),'--vanilla',str(script),str(out/'input.json'),str(out/'results')]
    record['command']=command;write_json(out/'execution.json',record)
    try:
        with (out/'R.stdout.log').open('w',encoding='utf-8') as stdout,(out/'R.stderr.log').open('w',encoding='utf-8') as stderr:
            proc=subprocess.Popen(command,cwd=PROJECT,stdout=stdout,stderr=stderr,
              creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            record['R_pid']=proc.pid;write_json(out/'execution.json',record)
            code=proc.wait()
        if code: raise RuntimeError(f'R exited {code}; see R.stderr.log')
        if any(sha256(f)!=h for f,h in before.items()):raise RuntimeError('Model code changed during execution')
        result=read_json(out/'results/output.json')
        record.update(status=result['status'],result_sha256=sha256(out/'results/output.json'))
    except Exception as exc:
        record.update(status='STOPPED_ON_ERROR',error=str(exc));raise
    finally:
        record['finished_at']=utcnow();write_json(out/'execution.json',record)
    print(record['status'],out)


if __name__=='__main__':main()
