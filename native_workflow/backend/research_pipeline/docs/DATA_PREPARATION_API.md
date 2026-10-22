# 数据检查模块 API 与 JSON 文件

## 新增接口

| 接口 | 输入 → 输出 |
|---|---|
| `POST /v1/modules/data_preparation/run` | 单个 data_preparation step 的 Main JSON + 已上传附件 → 报告和待审阅状态 |
| `POST /v1/runs` | data_preparation → PK / index 并行的 Main JSON → 汇总 JSON |
| `GET /v1/schemas/data-preparation` | 整理计划 JSON Schema |
| `GET /v1/schemas/data-review` | 人工决定 JSON Schema |
| `POST /v1/data-reviews` | 人工填写的决定 → 不可变审阅记录及新的附件 upload_id |
| `GET /v1/runs/{id}/files/steps/data/review_submission.template.json` | 下载待填写的人工确认模板 |

现有上传、结果下载、独立 PK/index 和文献接口继续可用。原来不带 data_preparation 的直接模块调用保留兼容，但不表示经过新数据审阅；**新 Main 只要包含数据 block，所有模型分支就必须从它获取数据，不能旁路原始附件。**

## 1. 提交数据与配置

完整示例：`examples/preparation_parallel.request.json`；真实数据示例：`examples/preparation_roberts.request.json`。

Main 中增加计划 JSON 和指定证据 MD 两个附件，再添加：

```json
{
  "steps":[
    {"id":"data","module":"data_preparation","input":{"preparation_attachment":"plan"},"options":{}},
    {"id":"pk","module":"pk_longitudinal","input":{"prepared_step":"data","prepared_dataset":"pk__001"},"options":{}},
    {"id":"index","module":"pkpd_index","input":{"prepared_step":"data","prepared_dataset":"index__001"},"options":{}}
  ]
}
```

第一步的 context JSON 仍通过 `context_attachment` 接入。各 dataset 的 metadata 和 analysis_options 放在计划 JSON 中，下游自动继承；不能审阅后偷偷换拟合选项。

计划包含：

- `schema_version: "1.0"`，`ruleset_version: "2026-09-16.1"`。
- `evidence_attachment` 及对应 `evidence_sha256`。
- `study_plan`：purpose 为 within_species_fit 或 human_translation；外推时填 target（药物、分析物、途径、基质、total/free、参数定义、人体群体、决策量）及 scaling（unknown_exponent 或 fixed_exponent）。
- `datasets[]`：id、kind（pk/index）、data_attachment、table（可选）、metadata、analysis_options。
- `precision_plans[]`：可选。没有时明确输出 NOT_CALCULABLE，不使用默认 CV/M/A。

按可比性拆分后的 ID 为 `原id__001` 等。原始数据分组变更后要重新检查 ID，不应盲目沿用旧组号。模型 step 引用人实际选中的组。

## 2. 读取结果和人工确认

首次运行预期状态是 WAITING_FOR_REVIEW，不是 SUCCEEDED。若全部数据组存在硬错误，则 BLOCKED。报告含：

- `datasets`：清洗候选、隔离记录、独立单位计数、每个单位的观测数。
- `issues`：id、code、severity（ERROR/REVIEW）、dataset、原行/单元格及说明。
- `change_log`：解析/单位换算前后值、系数和位置。
- `sample_size_status`、`precision_assessments`、`study_assessment`。
- `assessment_sha256`、规则和源附件 SHA、人工确认状态。

每组另存 candidate.json、quarantine.json；原始表另存 raw.json。候选不是已放行数据。

人工在模板中填写 decision=APPROVE/REQUEST_CHANGES/REJECT、reviewer、confirm_rules、selected_datasets、acknowledged_issues、rationale。默认模板为 PENDING，不能原样提交来放行。

```json
{
  "request_id":"本次评估运行ID",
  "step_id":"data",
  "schema_version":"1.0",
  "assessment_sha256":"报告中的64位值",
  "decision":"APPROVE",
  "reviewer":"由实际审阅人填写",
  "confirm_rules":true,
  "scope":"exploratory_fit_only",
  "selected_datasets":["pk__001"],
  "acknowledged_issues":["逐项填写报告中的适用REVIEW编号"],
  "rationale":"实际确认的处理、用途和限制"
}
```

这只是字段说明，不能把占位内容当作真实确认。未确认的分支继续 SKIPPED。对有 ERROR 的组，APPROVE 会被拒绝；需修正数据/模型计划并重新评估。

## 3. 确认后继续下游

`POST /v1/data-reviews` 返回 `attachment.upload_id`。新建 request_id，在原 Main 中增加该 review 附件，并把它的 ID 填入 data step 的 `input.review_attachment`。数据、计划与规则保持一致。重新运行会校验 fingerprint 后放行选中的分支，原始待审阅 run 保留。

CLI 同样支持：

```powershell
.\research_pipeline\run.ps1 --state outputs/data_review_demo run research_pipeline/examples/preparation_parallel.request.json
# 人工填写并保存模板后执行：
.\research_pipeline\run.ps1 --state outputs/data_review_demo review human_decision.json --out review_receipt.json
```

WAITING/BLOCKED 的 CLI 返回非零；调用者应以 JSON status 区分“等待人工”与程序异常。HTTP 成功返回 200 也不意味着模型已经获准运行。

## 可选精度计划字段

每项需 id、scope、sampling_design、variance_type、source、target。scope 与本次数据的 drug/analyte/species/route/matrix/concentration_basis/parameter_definition 对应。

| variance_type | 数据字段/条件 |
|---|---|
| individual_parameters | source.attachment 为个体参数表，指定 id_column/value_column；可声明 filter；独立 ID 不得重复 |
| arithmetic_sd | mean、sd、n0 |
| arithmetic_se | mean、se、n0 |
| log_t_ci | lower、upper、n0、source_confidence、ci_method=two_sided_t |
| arithmetic_t_ci | 同上，另给 mean |
| pop_iiv_variance | omega2，明确 iiv_definition |
| pop_iiv_cv | iiv_cv_percent，明确 iiv_definition |

IIV 定义字符串为 `parameter_i=typical*exp(eta); eta~N(0,omega2)`；该先验只能用于声明的同药物/同种属/同途径/同参数范围。当前闭式计算要求 sampling_design=serial_individual_parameters，不能声称已完成 PopPK 稀疏设计规划。

source 必须附 attachment 和 locator；target 必须有 multiplier、confidence、assurance、source_locator。这些数值全部来自研究者的实际方案。条件性 n 不是已完成的采样充分性证明；处理器不自动从浓度表反算个体 CL 或把 TVCL RSE 转成 IIV。
