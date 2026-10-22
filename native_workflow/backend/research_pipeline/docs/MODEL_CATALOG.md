# 模型目录接入与测试

## 输入与约束

使用用户指定的 `model_library_catalog.csv`，按 UTF-8/UTF-8-BOM 读取。七列为 `model_id, layer, model_name, required_data, eligible_use, hard_rejection_rule, selection_priority`。重复 ID、空字段、非法优先级或执行器层级冲突会明确报错，不自动填值。

目录是候选结构和筛选规则来源。优先级用于检索顺序，不等于拟合排名；文本拒绝规则保留给科研审核，不当作程序指令执行，也不因接入目录而标记其为已经验证的同药物模型。

当前有 6 个条目接入执行器：

| ID | 执行范围 |
|---|---|
| PK_SYS_1C_LIN | IV 一室；个体或已有的一室群体模式 |
| PK_SYS_2C_LIN | IV 二室；目前仅个体模式 |
| INPUT_IV_BOLUS | 明确 duration_h=0 |
| INPUT_IV_INF | 明确 duration_h>0 |
| PD_EMAX | 终点 Emax，Hill=1 |
| PD_SIGMOID | 终点 Emax，估计 Hill |

同一步 PK 必须选择一个结构模型和一个给药输入模型。Emax 或 sigmoid 必须与 `estimate_hill` 匹配。其他条目仍完整保留，选择未接入的条目会在调用 R 前返回 `CATALOG_MODEL_NOT_IMPLEMENTED`。例如 SCALE_EST_EXP 的存在不表示 allometry 执行器已经实现。

## JSON 接口

在既有 `/v1/runs` 或单模块请求中，把 CSV 作为附件上传，模型 step 增加：

```json
{
  "input": {
    "data_attachment": "observations",
    "model_catalog_attachment": "models"
  },
  "options": {
    "mode": "individual",
    "compartments": 1,
    "model_catalog_ids": ["PK_SYS_1C_LIN", "INPUT_IV_INF"]
  }
}
```

以上是接口片段，实际请求还需元数据和给药方案。HTTP 使用上传后的附件 ID，CLI 可使用本地路径。

有 data_preparation step 时继续使用 `prepared_step`/`prepared_dataset`，不能改用 raw data 绕开审核；目录模型 IDs 应写入准备计划的 `analysis_options`，与已审核配置一致。

Index 设置 `model_catalog_ids: ["PD_EMAX"]`、`estimate_hill: false`，或 `["PD_SIGMOID"]`、`estimate_hill: true`。

输出 `catalog_assessment.json` 保存所选规则、来源哈希、实现范围及审核状态。拟合结果继续输出 R²、AIC、AICc、BIC、ΔAIC、ΔAICc、ΔBIC、Akaike/AICc 权重、训练 RMSE、分组 CV RMSE、参数区间等。没有合格数据时不能生成研究排名。

`model_review.template.json` 是拟合后的待审文件，绑定结果哈希，默认 PENDING。它与既有 `/v1/data-reviews` 不同，尚无自动提交/强制执行模型结果批准的新接口。

## 本地目录检索

`research_pipeline.model_catalog.load_catalog(path)` 返回源信息及所有条目。`search_catalog(catalog, query, layer)` 按文本与层级筛选，再按原始优先级排序。此函数可由上游编排器调用；它不评定可靠性，独立于现有文献全文检索。

## 可复现测试

```powershell
.\.venv-context\Scripts\python.exe -I -X utf8 research_pipeline/scripts/run_model_tests.py --catalog 'C:/Users/georg/Documents/Transitioanl PKPD Context Engineering/PMB_Translational_PKPD_Project/PMB_project_proposal/model_library_catalog.csv'
```

命令创建新的运行目录，快照绑定目录文件，执行全部 research_pipeline 测试，并在第一个非预期错误停止。日志、JUnit、实际命令和 PID 存入 execution.json；不复用或删除旧测试目录。

测试中的 SYNTHETIC_TEST_FIXTURE 审批仅用于测试，不会批准真实 PMB 数据。合成数据的最佳 index 不能作为 PMB 结论。大鼠数据回归测试复现已有拟合，不证明人体预测准确。
