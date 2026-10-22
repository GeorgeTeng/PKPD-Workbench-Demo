"""Run against an explicitly started local service; saves a JSON verification record."""
import argparse
from uuid import uuid4
import httpx
from research_pipeline.common import BACKEND, PROJECT, read_json, write_json, utcnow

parser = argparse.ArgumentParser()
parser.add_argument('--base-url',default='http://127.0.0.1:8765')
args = parser.parse_args()
source = BACKEND/'research_pipeline/examples/parallel.request.json'
request = read_json(source)
request['request_id'] = 'http_' + uuid4().hex[:12]
with httpx.Client(base_url=args.base_url,timeout=240) as client:
    assert client.get('/v1/health').json()['status'] == 'OK'
    for item in request['attachments']:
        path = (source.parent/item.pop('path')).resolve()
        with path.open('rb') as file:
            reply = client.post('/v1/attachments',files={'file':(path.name,file)})
        reply.raise_for_status()
        uploaded = reply.json()
        item.update(upload_id=uploaded['upload_id'],sha256=uploaded['sha256'])
    reply = client.post('/v1/runs',json=request)
    reply.raise_for_status()
    main = reply.json()
    assert main['status'] == 'SUCCEEDED', main
    results = {}
    for step in main['steps']:
        result = client.get(f"/v1/runs/{request['request_id']}/files/{step['output']['path']}").json()
        assert result['status'] == 'SUCCEEDED'
        results[step['id']] = result['status']
    assert client.get('/v1/runs/'+request['request_id']).json()['status'] == 'SUCCEEDED'
    report = {'checked_at':utcnow(),'base_url':args.base_url,'request_id':request['request_id'],
              'status':'SUCCEEDED','verified':['health','multipart upload','parallel run','result fetch','artifact fetch'], 'modules':results}
    write_json(PROJECT/'outputs/Research_Pipeline_2026-09-16/http_verification.json',report)
    print(report)
