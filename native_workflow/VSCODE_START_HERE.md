# 在 VS Code 中使用全部代码

打开本目录的 `PMB_Translational_PKPD.code-workspace`。这是整理后的代码副本：前端在 `frontend/`，后端在 `backend/`，R 计算在 `pkpd_r/`。运行结果不在此副本中，首次运行会新建 `outputs/`。

## 代码位置

| 部分 | 目录 | 主要入口 |
|---|---|---|
| Context Compression | `backend/context_compression/ctxcomp/` | `engine.py`、`retention.py`、`schemas.py`、`resources/instructions.md` |
| 数据拆分、整理、QC 与人工确认 | `backend/research_pipeline/research_pipeline/` | `source_preparation.py`、`data_preparation.py`、`data_rules.py` |
| 主程序、JSON 和 API | `backend/research_pipeline/research_pipeline/` | `engine.py`、`cli.py`、`api.py` |
| PK longitudinal regression | `pkpd_r/R/`、`pkpd_r/modules/` | `pk_models.R`、`normalized_pk.R`、`pk_longitudinal.R` |
| PK/PD index 和 Emax/Hill 比较 | `pkpd_r/R/`、`pkpd_r/modules/` | `indices.R`、`endpoint.R`、`pkpd_index.R` |
| 本地/联网文献库 | `backend/research_pipeline/research_pipeline/` | `literature.py`、`references.py` |
| 输入示例、规则和 API 说明 | 各模块的 `examples/`、`docs/` | 示例 request JSON 和 schema |
| 前端工作台界面 | `frontend/` | `index.html`、`workbench-ui.js`、`canvas.js` |
| 实际运行及测试结果 | `outputs/` | 保留历次请求、响应、原文、审核和报告 |

## 已接入的环境

- Python：项目 `.venv-context/Scripts/python.exe`。
- R：`C:/Users/georg/Documents/Codex/ScienceEnv/R/bin/R.exe`。
- R 包库：`C:/Users/georg/Documents/Codex/ScienceEnv/R-library`。
- 扩展：Python、Pylance、Python Debugger、R。
- 工作区环境变量包含 `PKPD_RSCRIPT`、`PKPD_R_LIB`、`R_LIBS_USER`；不修改系统全局环境。
- 输出目录保留在文件树，默认不进入全文代码搜索；如需搜索输出，在搜索面板关闭排除规则。

## 常用操作

1. `Ctrl+Shift+P` → **Tasks: Run Task** → **00 · 检查 Python / R 环境**。
2. 选择 `B1 · 查看当前状态` 查看第一部分；`B1 · 调用模型（首错停止）` 才会真实调用模型。
3. `B1 · 从原始 ZIP 新建运行` 创建新输入快照；新目录必须为空。单阶段文件交接使用 `准备阶段 JSON` 和 `接收阶段 JSON`。
4. `B2 · 拆分原始表（候选文件）` 生成候选表。后续数据 QC 和模型分支由 request JSON 指定，保留人工确认流程。
5. `Pipeline · 校验 request JSON` 只检查接口结构；`执行 request JSON` 才执行指定步骤。
6. `API · 启动本机服务 8765` 后在浏览器打开 `http://127.0.0.1:8765/docs`；终端 `Ctrl+C` 停止服务。
7. `测试 · 全部 Python 测试` 和 `测试 · R 模型计算` 是软件验证，不是实际研究模型通过验证的证明。

任务均需手动启动。正在执行同一 B1 运行时，先查看状态，不要重复启动模型任务。原始实际运行目录的默认值已填入输入框；更换输入时创建新 run，不覆盖旧证据。

## 调试和 R 交互

`F5` 或左侧“运行和调试”可选择 Python 环境检查、阶段 prepare、request 校验/执行或 API。断点可设在 Python 源码中。

R 文件使用 R 扩展：命令面板运行 **R: Create R terminal**，然后执行：

```r
source("pkpd_r/load.R", encoding = "UTF-8")
```

在 R 文件中选中代码，使用 **Run Selection/Line** 执行；R 模型的 JSON 文件接口也已列入任务。R 交互与 Python 断点调试是不同入口，当前未配置 R 原生断点调试器。

## 当前真实模型运行

当前默认运行目录是 `outputs/Single_Main_JSON_2026-09-18/actual_run/`。proposal 提取并通过审查后，下游只接收 `handoff/main.json`：科研任务、药物/研究信息、数据需求、编号 rules、checks、uncertainties 与 data.files 附件全部合在该文件中。未完成时不发布空文件。实际状态查看上一级 `execution.json`；B2 默认读取 main.json。内部 file registry 不再作为交付物。

此前全附件压缩的日志保存在 `outputs/Context_Retention_Actual_2026-09-18/` 与 `outputs/Context_Retention_Retry_2026-09-18/`，属于旧范围的历史证据，不是当前运行结果。

实际执行链：`ctxcomp CLI → run_model → codex_generate → codex exec`。一旦错误或审查非 PASS，停止，不自动修订。默认在第一部分结束后停止。
