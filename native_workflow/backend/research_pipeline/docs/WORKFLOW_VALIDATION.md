# 工作流与前端验证记录

日期：2026-09-20。测试仅使用隔离的工程合成输入，不代表真实研究结果的审核或接受。

## 结果

| 检查 | 结果 |
|---|---|
| 全部 Python 回归 | 288 passed，0 failed，0 skipped；32.05 秒 |
| LangGraph → Prefect → Snakemake 实际执行 | 接收 → PAUSED → 接收完成待审核，全部通过 |
| 已完成文件复用 | intake 仅执行 1 次，恢复前后 receipt 哈希不变 |
| 真正停止计算进程树 | 单元测试启动独立父/子进程，暂停后均退出，已完成收据保留 |
| LangGraph checkpoint | 新 Controller 对象恢复人工中断；错误签名不会消耗中断；历史可导出 |
| 浏览器只读验收 | 9 组通过；10 节点、12 连线、下载、EDA、规则、临床定义、移动端；无浏览器错误 |
| 浏览器实际执行 | 合成附件上传、真实 intake、JSON+CSV、计时、刷新与审核门控通过 |
| 默认首页 | 0 附件，0 已批准步骤，不自动加载测试或历史运行 |

仅有一个测试依赖弃用提示：Starlette TestClient 引用 anyio 的旧 BlockingPortal 别名，不影响本轮结果。

## 修复

- 在恢复 LangGraph interrupt 前校验审核签名，避免错误决定污染中断状态。
- 正常暂停返回 PAUSED 控制结果，不再被 Prefect 任务记为执行失败。
- 对变化后的 PK 产物，传播需要该暴露的 index 失效状态；恢复仍需依赖审核。
- 补充完整审计导出的执行合同、日志和 LangGraph 状态历史。

## 可复现入口

在工作区执行：

```powershell
.venv-context/Scripts/python.exe -I -X utf8 -m pytest research_pipeline/tests context_compression/tests -q --junitxml=outputs/Workflow_Canvas_Browser_Check/python-tests.xml
.venv-context/Scripts/python.exe -I -X utf8 research_pipeline/scripts/check_control_stack.py
```

浏览器脚本为 `scripts/check_canvas_browser.mjs`（只读）与 `scripts/check_canvas_execution.mjs`（在独立预览上创建合成测试会话，只运行 intake）。使用本机 Node/Playwright/Edge，可通过 CANVAS_URL 指定地址。

## 证据文件

- `outputs/Workflow_Canvas_Browser_Check/python-tests.xml`：真实 pytest JUnit 记录。
- `outputs/Workflow_Canvas_Browser_Check/report.json`：前端检查及网络请求记录。
- `outputs/Workflow_Canvas_Browser_Check/execution-report.json`：真实上传/接收操作。
- `outputs/Workflow_Canvas_Browser_Check/validation-summary.json`：汇总。
- `outputs/Workflow_Stack_Check/513e8996/report.json`：真实三层执行/暂停/恢复；同目录 job 保存 Prefect 状态、Snakemake 日志、receipt 与控制 trace。

## 明确边界

尚未为任意新项目接通所有科学适配器：充分性判据、字段映射后的 EDA 执行和新数据 PK/index/临床解释仍有接口待接入。此次没有发起真实 LLM 压缩调用，也没有新跑真实研究的动物→人体模型。现有压缩/数值模块回归与工程框架通过，不能称为完整科研链路已经端到端放行。

新版预览为 http://127.0.0.1:8769/ ，旧服务保留。通用规则草案 12 项全部未启用。
