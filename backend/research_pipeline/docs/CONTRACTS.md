# JSON 输入输出契约 v1.0

v0.2 主流程在两个模型之前增加 data_preparation 和人工确认。其新增字段与状态见 [数据模块契约](DATA_PREPARATION_API.md)；原有直接模块契约继续兼容。

## Main 输入

权威结构：`research_pipeline/schemas/request.schema.json`。完整可运行示例：`examples/parallel.request.json`。

```json
{
  "schema_version": "1.0",
  "request_id": "my_analysis_001",
  "attachments": [
    {"id": "pk_data", "path": "pk.csv", "role": "pk_observations"},
    {"id": "endpoints", "path": "indices_and_response.csv", "role": "endpoint_data"}
  ],
  "steps": [
    {"id": "pk", "module": "pk_longitudinal", "input": {"data_attachment": "pk_data"}, "metadata": {}, "options": {}},
    {"id": "index", "module": "pkpd_index", "input": {"data_attachment": "endpoints"}, "metadata": {}, "options": {"mode": "compare_indices"}}
  ]
}
```

上面只展示拓扑，`metadata` 和 `options` 需按下文填写。**没有 `upstream_step`，两模块独立运行。** 不需要某一分支时，删除对应 step 即可。

附件支持 CSV、JSON、XLSX、PDF、TXT、MD，单个最大 64 MiB。数值表支持前三种；PDF 是参考材料，不能直接当作数值表。CLI 的相对路径以 request 文件目录为基准。HTTP 把 `path` 改为 `upload_id`。可附 `sha256` 校验预期文件；运行时复制附件快照。

可选：

- `context_attachment` 指向上游压缩 context JSON，原结构 `version/objective/study/data/rules/checks/uncertainties` 原样保留。
- `reference_policy: {"drug":"polymyxin_b","same_drug_only":true}`。
- `search: {"provider":"online","query":"pharmacokinetic model","limit":10,"required":false}`；需同时指定 `reference_policy.drug`。结果保存为 `literature_search.json`。
- 数值表可用 `input.table.column_map` 映射原列名；XLSX 必须明确 `sheet`，可指定 `header_row`。普通 XLSX 需要矩形长表；Roberts 另有专用适配器。

## A. PK longitudinal

必需 metadata：

```json
{
  "drug":"PMB", "species":"Sprague-Dawley rat", "matrix":"plasma",
  "concentration_unit":"mg/L", "time_unit":"h", "dose_unit":"mg/kg",
  "route":"IV", "concentration_basis":"total", "record_level":"individual",
  "data_origin":"observed", "regimen_type":"single_dose"
}
```

必需观测列：`subject_id,time_h,concentration_mg_L`。每个个体可以有多次采血；同个体同一时间的重复记录需事先明确处理。

| options.mode | 输入剂量 | 支持模型 |
|---|---|---|
| `individual` | `options.doses` 或 `input.doses_attachment`：time_h、dose_mg 或 dose_mg_kg、duration_h；当前一份 schedule 应用于该 step 的所有个体 | 一/二室 IV bolus 或 infusion；lognormal 或 additive 误差 |
| `population_bolus` | 观测行含 dose_mg、dose_time_h、duration_h=0 | 一室、单次 bolus、lognormal NLME |
| `population_infusion_per_kg` | 观测行含 dose_mg_kg、dose_time_h、duration_h；options.start 含正 CL/V | 一室、单次有限输注、lognormal NLME |

`compartments` 为 1 或 2；群体模式当前只实现一室。参数单位跟随 mg 或 mg/kg：L/h、L，或 L/h/kg、L/kg。mg/kg 参数不能缺少体重信息就当作绝对参数进行人体外推。

`status` 默认为 `QUANTIFIED`。BLQ、MISSING_CANNULA_BLOCKAGE、NOT_SAMPLED 必须在 `options.excluded_statuses` 中明确处理，否则失败；排除记录完整保留。没有自动 LLOQ/2 填补。

输出 `result.models[]`：`family,compartments,theta,parameter_units,parameter_basis,metadata,doses,parameters,diagnostics,observed_time_range_h,warnings`。

注意：可移植剂量内部沿用 `doses.dose_mg` 数值字段；真实单位看 `dose_coefficient_unit`，可为 mg 或 mg/kg，不能只凭字段名判断。该约定显式保存在 `dose_encoding`。群体预测为 eta=0 的典型曲线，不等于群体边际均值；不同个体给药不一致时不默认生成共同剂量。

## B. PK/PD index comparison

表格示例结构：

```text
unit_id,study_id,response,fAUC_MIC_h,fCmax_MIC,fT_MIC_percent
```

所有数值必须已按声明单位换算。每个独立实验单位只允许一个终点；多次药效测量需要另行指定重复测量模型。药效终点的变换（例如 log 尺度）需要预先说明，所有候选一致。多个暴露指标来自同一组单位，不能把各自不同的缺测子集用于 AIC 比较。

options：

```json
{
  "mode":"compare_indices",
  "index_columns":["fAUC_MIC_h","fCmax_MIC","fT_MIC_percent"],
  "response_column":"response", "id_column":"unit_id", "group_column":"study_id",
  "direction":"decreasing", "estimate_hill":true, "reference_mode":"baseline"
}
```

`index_columns` 需 2–8 个。`group_column` 可省略；省略时不计算 grouped CV。接口没有用 R² 阈值代替样本量设计。

metadata 需 `drug,data_origin,response_unit,endpoint_definition`，以及每个候选的 `index_definitions`：

```json
{
  "fAUC_MIC_h":{"unit":"h","concentration_basis":"free","window_h":[0,24]},
  "fCmax_MIC":{"unit":"1","concentration_basis":"free","window_h":[0,24]},
  "fT_MIC_percent":{"unit":"%","concentration_basis":"free","window_h":[0,24]}
}
```

24 小时只是示例，程序没有默认暴露窗口。不同 index 的单位可以不同，但 concentration_basis 和 window_h 必须一致；百分数应为 0–100。若表中有 `response_time_h`，全部记录须具有相同终点评估时间。候选 index 与 MIC/fu 的来源、计算方法及不确定性应在上游记录；本模块不重新推断它们。

输出：

- `result.ranking[]`：R2、AIC、AICc、delta_AIC、排名、训练 RMSE、grouped_CV_RMSE、折数、失败/警告原因。
- `result.selection`：best_by_R2、best_by_AIC、best_by_AICc，全部返回数组以保留并列；agreement_R2_AIC 表示一致性。
- `result.models[]`：每个成功候选的完整 `theta={E0,Emax,EC50,hill}`、direction、equation、参数 CI/RSE、诊断及 index 定义。下游可仅凭 JSON 计算预测。
- `result.index_correlation`、`fold_results`：判断指标是否难区分和 CV 是否完整。
- CSV、PNG、参数 JSON 为附件；RDS 仅为 R 使用者提供便利。

一个候选拟合失败会保留原因；其余可拟合候选仍可排名。所有候选失败则整个 index step 失败。最佳候选的选择受数据和候选集合限制，不自动赋予科学认可。

## 统一输出

`module-output.schema.json` 约束两模块的 envelope：

```json
{
  "schema_version":"1.0", "request_id":"my_analysis_001", "step_id":"index",
  "module":"pkpd_index", "status":"SUCCEEDED", "result":{},
  "artifacts":[], "provenance":{}, "warnings":[], "errors":[]
}
```

`status` 为 SUCCEEDED/FAILED/SKIPPED；错误具有 code/message。JSON 中不可用数值为 null 并附失败/范围说明，绝不写 NaN/Inf。`NOT_FOUND` 用于来源缺失的语义信息；数值分析必需字段不能以该字符串代替数字。

所有 artifact 路径相对该 run 根目录，附字节数及 SHA-256。Main 的 output 包含 steps 列表、状态及每个模块 output.json 的路径/hash。上下游应先检查状态、schema_version 和 hash，再读取参数。
