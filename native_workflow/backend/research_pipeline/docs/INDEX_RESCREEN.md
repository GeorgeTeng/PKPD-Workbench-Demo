# 游离 PK/PD index 候选与重新筛查

## 当前候选池

| 层级 | JSON 列名 | 定义 | 单位 |
|---|---|---|---|
| 主分析 | `fAUC_MIC_h` | 指定窗口内游离 AUC / MIC | h |
| 主分析 | `fCmax_MIC` | 同窗口内游离 Cmax / MIC | dimensionless |
| 主分析 | `fT_MIC_percent` | 游离浓度 > MIC 的时间占比 | % |
| 探索 | `fCtrough_MIC` | 指定下一次给药前左极限的游离浓度 / MIC | dimensionless |
| 探索 | `fT_4MIC_percent` | 同窗口内游离浓度 > 4×MIC 的时间占比 | % |

Emax/Hill 是连接这些 X 与同一药效终点 Y 的回归函数，不是 index 名称。主分析和探索分析分开；探索数据列缺失不否决已有主分析的资格。不按结果搜索最佳 k，再把它当作预设阈值；当前探索阈值预设 k=4。

主分析的同药物依据：[PMB/K. pneumoniae 鼠模型研究](https://pmc.ncbi.nlm.nih.gov/articles/PMC5890666/)用对应方案 PK、蛋白结合与 MIC 计算三项游离指标；[PMB/E. coli 与 K. pneumoniae 研究](https://pmc.ncbi.nlm.nih.gov/articles/PMC10377753/)也比较三项，E. coli 中 fCmax/MIC 的样本内 R² 最高，而 K. pneumoniae 中 fAUC/MIC 最高。因而不能在拟合前预定 AUC 获胜。新增两个是本项目探索假设，目前不声称它们已有优于三项标准指标的 PMB 证据。

## 上游输入合同

`records` 每个独立终点一行，包含 unit_id、regimen_id、strain、mic_mg_L、response、response_time_h 和候选列。输入只有 PK 曲线时，先由匹配的、经审核的上游暴露计算得到 index；不能按菌种名称把不同研究、动物、基质或方案直接拼接。

`metadata.index_definitions` 对每个候选声明 concentration_basis=free、unit、window_h；还需要 exposure_provenance。fCtrough 另声明 trough_definition=pre_dose_left_limit 和 trough_time_h；%fT>4MIC 另声明 threshold_mic_multiplier=4。观测到的最小值不自动等于 trough。total 数据需要对应来源的蛋白结合转换依据，不默认 fu=1，也不把别的物种 fu 当成已知。

## 判断规则

代码入口 `research_pipeline/index_screening.py::screen_index_dataset`：

- 检查完整匹配、单位、同一暴露窗口、同一终点时间、同一菌株、唯一实验单位、MIC 与百分比范围。
- 静态 nominal concentration/time-kill 归为支持性数据，不转换成 index 排名数据。
- 正比例关系的两个 index 会被标出：在 Emax/Hill 中改变 EC50 就能得到同样的曲线，不能独立区分驱动关系。
- 当前标准 Emax 实现至少需要 6 个终点、每项至少 4 个不同暴露值。这只是代码运行门槛，不是可靠性样本量结论。Hill 的支持度要另行检查。
- 此步骤完成的是资格检查。通过仍需人工确认、模型拟合、参数可识别性和预测验证；未通过不生成最佳 index。

## CLI / JSON 输出

```powershell
.\.venv-context\Scripts\python.exe -I -X utf8 research_pipeline/scripts/rescreen_pmb_indices.py --prepared outputs/Data_Preparation_PMB_2026-09-18_retry_1628/normalized --previous-inventory outputs/PMB_Model_Review_2026-09-18_01/data_inventory.json --expanded --out outputs/PMB_Index_Rescreen_NEW
```

输出 `index_output.json`、`candidate_specifications.json`、`dataset_screening.json` 和 `execution.json`。函数可供 API 适配器调用，本次没有新增 HTTP endpoint，也没有执行新的暴露计算。

2026-09-19 实际结果：26 个 JSON 数据集，来源未变化；主分析和全部五项完整 index-response 行数均为 0，`BLOCKED_NO_ELIGIBLE_MATCHED_DATA`，`best_index=null`。输入资格不足时停止，不转去拟合原始浓度。
