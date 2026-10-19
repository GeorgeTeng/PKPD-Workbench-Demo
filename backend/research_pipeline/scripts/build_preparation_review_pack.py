"""Generate final PENDING reports and a review package. Does not approve any data."""
import hashlib
import argparse
import xml.etree.ElementTree as ET
import importlib.metadata
import json
from collections import Counter
from pathlib import Path
from zipfile import ZipFile,ZIP_DEFLATED
from research_pipeline.api import create_app
from research_pipeline.common import BACKEND, PROJECT,read_json,write_json,sha256,utcnow
from research_pipeline.data_rules import RULES,RULESET_VERSION
from research_pipeline.engine import run_pipeline

out=PROJECT/'outputs/Data_Preparation_2026-09-16'
parser=argparse.ArgumentParser()
parser.add_argument('--package-only',action='store_true')
args=parser.parse_args()
state=out/'final_state'
examples=BACKEND/'research_pipeline/examples'
verification={'created_at':utcnow(),'runs':[],'approval_status':'NO_PRODUCTION_APPROVAL_SUBMITTED'}
for filename in ['preparation_parallel.request.json','preparation_roberts.request.json']:
    request=read_json(examples/filename)
    path=state/'runs'/request['request_id']/'output.json'
    if path.exists() and not args.package_only: raise SystemExit('Immutable final run already exists: '+str(path))
    main=read_json(path) if args.package_only else run_pipeline(request,state,examples)
    assert main['status']=='WAITING_FOR_REVIEW',main
    step=read_json(path.parent/'steps/data/output.json')
    result=step['result']
    for key,relative in [('preparation','data_preparation.py'),('rules','data_rules.py'),('table_reader','tables.py')]:
        assert result['processor_sha256'][key]==sha256(BACKEND/'research_pipeline/research_pipeline'/relative),'Reports require a fresh assessment after processor changes.'
    assert result['review'] is None and result['released_datasets']==[]
    lines=['# 数据审阅报告：'+request['request_id'],'','状态：**WAITING_FOR_REVIEW**。尚未代替人工确认，后续模型未运行。','',
           '判断方法：[待确认规则](../../../../../research_pipeline/docs/DATA_PREPARATION_METHOD_FOR_REVIEW.md)。',
           '', '## 数据清点','', '| 数据集 | 原始记录 | 候选记录 | 隔离记录 | 独立单位 | 可运行性 |',
           '|---|---:|---:|---:|---:|---|']
    for group in result['datasets']:
        s=group['summary']
        lines.append(f"| {group['id']} | {s['input_rows']} | {s['candidate_rows']} | {s['quarantined_rows']} | {s['independent_units']} | {group['readiness']} |")
    lines += ['', '## 数据充分性','',f"- 正式动物数判断：`{result['sample_size_status']}`。没有填入假设 CV、M 或 A。",
              f"- 用途判断：`{result['study_assessment']['status']}`。",
              '- 人体外推验证：NOT_ESTABLISHED。技术上可运行不代表动物数足够或人体预测可靠。', '',
              '## 需审阅的问题','', '| 编号 | 数据集 | 类型 | 内容 |','|---|---|---|---|']
    for problem in result['issues']:
        lines.append(f"| {problem['id']} | {problem['dataset'] or '全局'} | {problem['severity']} / {problem['code']} | {problem['message'].replace('|','/')} |")
    lines += ['', '## 人工确认','',
              '请先确认判断方法，再逐项审阅数据处理建议和适用限制。需要补数据时提交 REQUEST_CHANGES；仅允许所选数据探索性拟合时填写 APPROVE、实际审阅人、理由、所选 dataset 及已确认 issue 编号。',
              '', '[人工确认模板](steps/data/review_submission.template.json) · [完整 JSON](steps/data/output.json)', '',
              '确认摘要 SHA：`'+result['assessment_sha256']+'`。修改数据、上游 context、计划、规则或处理器后需重新审阅。']
    (path.parent/'HUMAN_REVIEW.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    verification['runs'].append({'request_id':request['request_id'],'status':main['status'],'assessment_sha256':result['assessment_sha256'],
                                  'output':str(path),'groups':[{'id':g['id'],**g['summary'],'quarantine_reasons':dict(Counter(r['reason'] for r in g['quarantine']))} for g in result['datasets']]})
write_json(out/'method_proposal.json',{'status':'PENDING_HUMAN_CONFIRMATION','ruleset_version':RULESET_VERSION,'rules':RULES,
            'source':read_json(examples/'evidence_snapshot.provenance.json'),
            'required_decisions':['Confirm method','Review per-dataset changes and limitations','Select exploratory release or request more data']})
write_json(BACKEND/'research_pipeline/docs/openapi.json',create_app(state).openapi())
versions={name:importlib.metadata.version(name) for name in ['pkpd-research-pipeline','scipy','jsonschema','fastapi','uvicorn','python-multipart','openpyxl','pypdf','pytest','httpx','starlette']}
verification['dependencies']=versions
suite=ET.parse(out/'tests.xml').getroot().find('testsuite')
verification['tests']={k:int(suite.attrib[k]) for k in ['tests','failures','errors','skipped']}
write_json(out/'verification.json',verification)
(BACKEND/'research_pipeline/requirements-tested.txt').write_text('# Observed environment 2026-09-16; use setup.ps1 to install project.\n'+
 '\n'.join(f'{k}=={v}' for k,v in versions.items() if k!='pkpd-research-pipeline')+'\n',encoding='utf-8')
intro=['# 数据检查 block：交付与人工确认','',
       '位置：Context Compression → 数据检查与整理 → 人工确认 → PK / index 并行。', '',
       '- [判断方法草案](../../research_pipeline/docs/DATA_PREPARATION_METHOD_FOR_REVIEW.md)',
       '- [API / 输入输出](../../research_pipeline/docs/DATA_PREPARATION_API.md)',
       '- [新主程序示例](../../research_pipeline/examples/preparation_parallel.request.json)',
       '- [PMB 数据审阅报告](final_state/runs/preparation_roberts_pending_001/HUMAN_REVIEW.md)',
       '- [PMB 确认模板](final_state/runs/preparation_roberts_pending_001/steps/data/review_submission.template.json)',
       '- [模拟数据审阅报告](final_state/runs/preparation_synthetic_pending_001/HUMAN_REVIEW.md)', '',
       '正式动物数当前为 NOT_CALCULABLE；真实 PMB 数据的 11 个动物与 102 个定量浓度不被自动判作足够。仍需确认研究目标、变异依据、精度目标和外推范围。', '',
       '生产示例全部保持 WAITING_FOR_REVIEW。测试中的人工决定仅为合成测试 fixture，不代表实际人工认可。', '',
       '要提交本次报告的人工决定，请使用 --state outputs/Data_Preparation_2026-09-16/final_state；随后用新的 request_id 及返回的 review 附件再次调用 Main。', '',
       'ZIP 含源代码、schema、方法原文快照和待审阅结果；不含 Python/R 运行时或 32 MB 原始 Excel。原始附件 SHA 保留，重新运行真实数据需提供本机 Excel。']
(out/'README.md').write_text('\n'.join(intro)+'\n',encoding='utf-8')
paths=[]
for directory in [BACKEND/'research_pipeline',PROJECT/'pkpd_r',BACKEND/'context_compression']:
    for path in directory.rglob('*'):
        if path.is_file() and path.suffix not in {'.zip','.pyc'} and not any(p in {'__pycache__','.pytest_cache','build','.git'} or p.endswith('.egg-info') for p in path.parts): paths.append(path)
for path in out.rglob('*'):
    if path.is_file() and path.suffix not in {'.xlsx','.zip'} and ('state' not in path.relative_to(out).parts): paths.append(path)
paths.append(PROJECT/'outputs/Context_Compression_Local_2026-09-16/demo_run/compressed_context.json')
manifest={'created_at':utcnow(),'files':[{'path':p.relative_to(PROJECT).as_posix(),'sha256':sha256(p)} for p in sorted(set(paths))],
          'status':'PENDING_HUMAN_CONFIRMATION','omitted':'Original Excel, runtimes and development-state runs'}
archive=out/'Data_Preparation_Review_Pack_v020.zip'
with ZipFile(archive,'w',ZIP_DEFLATED) as zipped:
    for path in sorted(set(paths)): zipped.write(path,path.relative_to(PROJECT).as_posix())
    zipped.writestr('MANIFEST.json',json.dumps(manifest,ensure_ascii=False,indent=2))
with ZipFile(archive) as zipped:
    assert zipped.testzip() is None
    for entry in manifest['files']: assert hashlib.sha256(zipped.read(entry['path'])).hexdigest()==entry['sha256']
print(json.dumps({'archive':str(archive),'files':len(manifest['files']),'sha256':sha256(archive),'runs':verification['runs']},ensure_ascii=False,indent=2))
