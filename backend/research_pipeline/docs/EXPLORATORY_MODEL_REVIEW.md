# 实际 PMB 模型的探索性审核

这两个脚本调用本地 R 函数并保存进程号、脚本和输入摘要、R 日志、参数、预测值、拟合图。运行成功表示产生了待审阅结果，不表示数据充分或模型已获放行。人工审核状态保持 `PENDING`。

## Emax/Hill

**范围纠正：下面的静态浓度拟合仅作为辅助记录，不是用户要求的 fAUC/MIC、fCmax/MIC、%fT>MIC 比较。正式 index 使用 `compare_indices` 模式，缺匹配暴露时停止，不自动转成 `endpoint_emax`。**

Python 入口：`scripts/run_static_emax_review.py --catalog <model_library_catalog.csv> --out <新目录>`。
R 入口：`pkpd_r/scripts/review_static_emax.R <input.json> <新结果目录>`。

- 输入 JSON：`records` 为分菌株的 1 小时实际观测，包含 `record_id`、`experiment_group_key`、`nominal_concentration_mg_L`、`log10_CFU_mL`、`time_h`、`status`、`CENS`、`independent_replicate_id`、`strain`，另有 `provenance`。
- 模型：`Y = E0 - Emax*C^h/(EC50^h+C^h)`。普通 Emax 固定 h=1；Hill 估计 h。两者同一菌株、同一 6 个观测、同一响应和条件高斯误差；菌株间的 AIC 不直接比较。
- 当前只描述静态名义浓度与 1 小时菌量，不是三个 PK/PD index 的比较，也不是原论文 PSP 时序模型的复现。
- 每株 6 个浓度组的生物学独立重复 ID 为 `NOT_FOUND`，参数区间以条件独立误差为假设，不能当作已知生物学重复数。
- 核心函数 `fit_index_emax(..., sparse_exploratory=FALSE)` 的正式默认门槛不变（至少 3 个残差自由度）。这个独立审核脚本明确指定 Hill 的 `sparse_exploratory=TRUE`，允许 2 个残差自由度，仅供探索审核。它不是充分性证明；没有接入正式模块的自动放行。
- AIC/BIC 计入误差方差参数。Hill 的 n=6、k=5，使 AICc 分母 n-k-1 为 0，输出 null。不能用 Emax 的 AICc 与 Hill 的 AIC 做排名。
- 输出：`results/output.json`、`comparison.csv`、`parameters.csv`、`predictions.csv`、`emax_hill_fits.png`，每个模型的 RDS 与来源记录。非有限区间保留失败状态；JSON 对应值为 null，CSV/RDS 保留数值溢出证据。

## 大鼠 PK

Python 入口：`scripts/run_real_rat_review.py --catalog <model_library_catalog.csv> --out <新目录>`。
R 入口：`pkpd_r/scripts/review_rat_pk_candidates.R <input.json> <新结果目录>`。

- 输入 JSON：`records` 为个体浓度—时间数据，`metadata` 明确 total、mg/L、h、mg/kg、IV；`doses` 含给药时间、剂量与输注时间；另有 `provenance`。
- 逐只拟合线性一室/二室模型，均使用 1 mg/kg、1 分钟 IV 输注和 log 浓度高斯误差。CL/V 等按体重归一化，不补造体重。原来 8 个非定量记录独立保留，探索分析用 102 个定量点；排除 BLQ 的偏倚仍需审核。
- 在同一只动物、同一组观测内按 AICc 排名；同时看参数区间、协方差与模型库规定的二室参数相关性 >0.95 拒绝规则。
- 另外输出一室群体模型作为参考；没有二室群体对照，不把其 AIC 与逐只模型 AIC 混合排名。逐只选择也不能直接变成物种总体结构选择。
- 输出：`results/output.json`、逐只比较/参数/预测 CSV、多起点记录、RDS、拟合图及一室群体模型结果。数值起点失败是候选优化结果，完整保留；输入契约或程序错误使进程停止。

## 审核规则

1. **MR-01 来源和范围**：同药物、正确给药途径、单位和响应定义，来源定位可追溯。静态数据不替代动态 PK 暴露。
2. **MR-02 可比性**：只有相同观测、响应尺度、似然定义的模型才比较信息准则。
3. **MR-03 数值与可识别性**：检查收敛、参数相关性、有限 CI、边界、参数 RSE；不把“可运行”当成“可靠”。本次仅完成初步数值筛查，没有声称完成所有目录文本规则或文献模型认证。
4. **MR-04 精度**：报告实际区间，不设置通用 RSE 阈值；精度是否足够由研究目的决定。
5. **MR-05 预测**：本次没有独立验证/CV，不授予人体预测资格。可靠性结论保留为 `NOT_ESTABLISHED`。
6. **MR-06 人工决定**：结果、排除原因和未解决问题由人审核；运行脚本不填写 APPROVE，不改写原 B2 gate。

方法来源：[PMB 静态实验原论文](https://doi.org/10.1371/journal.pone.0171834)；[R AIC 官方说明](https://stat.ethz.ch/R-manual/R-devel/library/stats/html/AIC.html)。原论文建模对象是完整 time-kill 时序，其数据再利用不等于原模型被复现或独立验证。
