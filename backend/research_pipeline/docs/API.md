# HTTP API v1

v0.2 增加数据检查和人工确认入口，见 [数据模块 API](DATA_PREPARATION_API.md)。推荐主流程先运行 `data_preparation`，确认后再进入 PK/index；下面原有直接建模示例保留用于兼容和软件测试。

启动：`research_pipeline/run.ps1 --state outputs/research_pipeline_api serve --port 8765`。

Base URL 为 `http://127.0.0.1:8765`；Swagger `/docs`；机器可读 `/openapi.json`。请求均为 JSON，上传除外。可设置环境变量 `RESEARCH_PIPELINE_API_TOKEN`，调用端添加 `Authorization: Bearer ...`。

| 方法 | 路径 | 输入 → 输出 |
|---|---|---|
| GET | `/v1/health` | 版本、模块列表 |
| GET | `/v1/schemas/request` | Main 输入 JSON Schema |
| GET | `/v1/schemas/module-output` | 模块输出 envelope Schema |
| POST | `/v1/attachments` | multipart `file` → upload_id、SHA、字节数 |
| POST | `/v1/runs` | Main request → Main output；同步执行 |
| POST | `/v1/modules/{module}/run` | 相同 request，恰好一个指定模块 step → Main output |
| GET | `/v1/runs/{request_id}` | 已落盘 Main output |
| GET | `/v1/runs/{request_id}/files/{artifact_path}` | 按 Main 输出相对路径取文件 |
| POST | `/v1/search` | provider/query/drug/limit → 候选列表 JSON |
| POST | `/v1/library/index` | upload_ids 数组 → 本地索引结果 |
| GET | `/v1/library/status` | 文档/分块数量 |
| POST | `/v1/references/evaluate` | card_upload_id/source_upload_ids/drug/metadata → 证据条件检查 |

同步执行的客户端应允许至少 180 秒/波次，示例设置 240 秒。当前为本机研究服务，未提供任务队列、多用户隔离或自动部署。

## Python 接入示例

在工作区根目录运行，服务需已启动：

```python
import json
from pathlib import Path
from uuid import uuid4
import httpx

example = Path('research_pipeline/examples/parallel.request.json')
request = json.loads(example.read_text(encoding='utf-8'))
request['request_id'] = 'api_' + uuid4().hex[:12]
with httpx.Client(base_url='http://127.0.0.1:8765', timeout=240) as client:
    for item in request['attachments']:
        source = (example.parent / item.pop('path')).resolve()
        with source.open('rb') as file:
            response = client.post('/v1/attachments', files={'file': (source.name, file)})
        response.raise_for_status()
        upload = response.json()
        item.update(upload_id=upload['upload_id'], sha256=upload['sha256'])
    response = client.post('/v1/runs', json=request)
    response.raise_for_status()
    output = response.json()
    Path('main_output.json').write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
    # HTTP 200 only means the request was processed: inspect scientific step status.
    for step in output['steps']:
        artifact = step['output']['path']
        result = client.get(f"/v1/runs/{request['request_id']}/files/{artifact}").json()
        Path(f"{step['id']}_output.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
```

线上查询体：

```json
{"provider":"online","query":"pharmacokinetic model","drug":"polymyxin b","limit":10}
```

本地查询只需把 provider 改为 local；先经上传及 `/v1/library/index` 建库。独立 `/v1/search` 返回 JSON，调用端自行保存；Main 内置 search 自动保存文件。

## 错误与文件边界

- Main/模块拟合失败会以 FAILED/PARTIAL 状态及 errors 返回并落盘；不要只看 HTTP 200。
- 输入契约错误一般 HTTP 422；已存在 request_id 为 409；不存在的 run/artifact 为 404。
- 上传后内容变化或预期 SHA 不匹配会被阻止。
- API 不接受任意服务器本地路径，必须使用 upload_id。CLI 对本机文件可直接使用 path。
- `/files/` 路径限制在指定 run 目录内；没有执行用户提供 R/Python 代码的接口。
- 输入 context 可含 NOT_FOUND；数值必需字段缺失时明确失败，不自动补猜。
