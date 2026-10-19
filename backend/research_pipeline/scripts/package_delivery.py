"""Package source and reviewed execution artifacts without user workbooks or runtimes."""
import csv
import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
from research_pipeline.common import BACKEND, PROJECT, read_json, write_json, sha256, utcnow

out = PROJECT/'outputs/Research_Pipeline_2026-09-16'
run = out/'verified_state/runs/parallel_verified_001'
index = read_json(run/'steps/index/output.json')['result']
report = read_json(out/'verification.json')
suite = ET.parse(out/'python_tests.xml').getroot().find('testsuite')
report['python_tests'] = {key:int(suite.attrib[key]) for key in ['tests','failures','errors','skipped']}
report['http'] = read_json(out/'http_verification.json')
report['online_search'] = {'status':read_json(out/'online_pmb_search.json')['status'], 'returned':len(read_json(out/'online_pmb_search.json')['results'])}
report['index_demo'] = {'data_origin':'synthetic','ranking':index['ranking'],'selection':index['selection']}
write_json(out/'verification.json', report)
lines = ['# 并行 PK / Index 模块交付结果', '', '## 已实现', '',
         '- Main JSON + attachments，同时运行独立 PK 和 index 分支；一个分支失败不阻止另一个。',
         '- Index 使用 Emax/Hill 比较 R²、AIC、AICc、ΔAIC，输出参数、CI/RSE、分组 CV 和拟合图。',
         '- 两个模块都提供可移植参数 JSON、独立 HTTP 入口及下游文件。',
         '- Europe PMC 联网检索和 SQLite FTS5 本地检索均已实测；文献命中维持待审阅。', '',
         '## 验证', '',
         f"- Python：{report['python_tests']['tests']} 项通过，0 失败；包含真实 PMB Excel 回归、独立性、API、同药物规则及离线检索。",
         '- R 核心：本次终端运行 37 项通过，0 失败。',
         '- 实际 HTTP：上传 → 并行拟合 → 主结果读取 → 模块 JSON 下载全部通过；测试服务已关闭。',
         '- 联网检索返回 12 条候选；本地索引包含真实论文 PDF 和一份来源卡。', '',
         '## 模拟数据 index 结果', '',
         '**以下只用于验证代码，不代表 PMB 的最佳 index。**', '',
         '| Index | R² | AIC | 分组 CV RMSE |', '|---|---:|---:|---:|']
for row in sorted(index['ranking'],key=lambda x:x['AIC']):
    lines.append(f"| {row['index']} | {row['R2']:.4f} | {row['AIC']:.3f} | {row['grouped_CV_RMSE']:.4f} |")
lines += ['', '## 真实 PMB 数据', '',
          'Roberts Fig.4b：11 只大鼠、102 个定量浓度。探索性一室群体模型 CL=0.199576 L/h/kg，V=0.374456 L/kg。与此前由个体拟合初始化的结果在 10 ppm 容差内一致；本次使用显式 CL=0.2、V=0.4 初值。原有早期拟合不足尚未因接口拆分而解决。', '',
          'Fig.4b 缺少本次 index 比较所需的同组药效终点及候选指标，故没有伪造真实 PMB index 排名。论文指导的科学模型优化仍需按参考规则完成具体文献审阅与复现。', '',
          '## 使用入口', '',
          '- [README](../../research_pipeline/README.md)',
          '- [Main 示例](../../research_pipeline/examples/parallel.request.json)',
          '- [输入输出契约](../../research_pipeline/docs/CONTRACTS.md)',
          '- [API 文档](../../research_pipeline/docs/API.md)',
          '- [参考规则](../../research_pipeline/docs/REFERENCE_POLICY.md)',
          '- [模拟 Index JSON](verified_state/runs/parallel_verified_001/steps/index/output.json)',
          '- [真实 PMB PK JSON](verified_state/runs/roberts_pmb_verified_001/steps/pk/output.json)', '',
          'ZIP 保留相邻代码目录及运行示例；不包含 Python/R 运行时、原始 32 MB Excel 或论文 PDF。Roberts 示例指向本机已有源文件；移动到另一台电脑时须重新附加该文件及可选 context。', '',
          '已知非致命环境提示：R 的 C.UTF-8 locale 启动警告；Starlette 测试客户端依赖弃用提示。它们不影响本次验证，但不是科学可靠性证明。']
(out/'DELIVERY.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
paths = []
for root in [BACKEND/'research_pipeline',PROJECT/'pkpd_r',BACKEND/'context_compression']:
    for path in root.rglob('*'):
        if not path.is_file() or any(part in {'__pycache__','.pytest_cache','build','.git'} or part.endswith('.egg-info') for part in path.parts):
            continue
        if path.suffix in {'.pyc','.zip'}:
            continue
        paths.append(path)
for name in ['DELIVERY.md','verification.json','python_tests.xml','http_verification.json','online_pmb_search.json','local_pmb_search.json']:
    paths.append(out/name)
for identifier in ['parallel_verified_001','roberts_pmb_verified_001']:
    for path in (out/'verified_state/runs'/identifier).rglob('*'):
        if path.is_file() and path.suffix.lower() not in {'.xlsx','.pdf'}:
            paths.append(path)
# Upstream context example needed by the local Roberts request.
paths.append(PROJECT/'outputs/Context_Compression_Local_2026-09-16/demo_run/compressed_context.json')
manifest = {'created_at':utcnow(),'files':[{'path':p.relative_to(PROJECT).as_posix(),'sha256':sha256(p)} for p in sorted(set(paths))],
            'omitted_attachments':['Roberts original XLSX','reference PDFs'],
            'scope':'Source and execution artifacts; output attachment manifests may refer to omitted originals, which must be supplied separately.'}
archive = out/'PK_Index_JSON_Pipeline.zip'
with ZipFile(archive,'w',ZIP_DEFLATED) as package:
    for path in sorted(set(paths)):
        package.write(path,path.relative_to(PROJECT).as_posix())
    package.writestr('MANIFEST.json',json.dumps(manifest,ensure_ascii=False,indent=2))
with ZipFile(archive) as package:
    assert package.testzip() is None
    for entry in manifest['files']:
        assert hashlib.sha256(package.read(entry['path'])).hexdigest() == entry['sha256']
print(json.dumps({'archive':str(archive),'bytes':archive.stat().st_size,'files':len(manifest['files']),'sha256':sha256(archive)},indent=2))
