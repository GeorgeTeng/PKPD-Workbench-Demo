# 同药物、适用范围和模型可靠性

这是项目的可执行证据规则，不是通用监管准入标准。低 RSE、高 R²、低 AIC、引用多或拟合收敛都不能单独证明动物到人的预测可靠。

## 三层区分

1. **检索候选**：找到提及目标药物的文章。可能只是比较药或背景引用，不能直接认为文章建立了该药模型。
2. **已审阅且适用于声明范围**：原始研究，确有对应模型、数据设计、参数可辨识性、诊断和验证证据，来源文件及位置可追溯。
3. **人体外推有效性**：需另外检验迁移假设、种属差异、预测区间及独立人体结果。本项目不会把第 2 层自动升级为第 3 层；无人体 PK 时可做前瞻预测和不确定性评估，不能声称已经完成临床外部验证。

## 已实现的筛选条件

- 药物身份：PMB ≠ colistin ≠ CMS ≠ FADDI-365。CMS 与活性 colistin 需明确前药/代谢物关系，不能仅按同类抗菌药合并。
- 原始研究；实际模型 family 要匹配配置，支持 one_compartment、two_compartment、endpoint_emax。
- 同药物还要检查给药途径、物种、基质、total/free。当前 paper_guided 要求这四项与声明范围逐项匹配；不同范围的论文可作为方法学背景，不能自动移入该层。
- 五类证据都要有 `status: SUPPORTED`、具体 locator、具体 finding：模型描述、数据设计、参数可辨识性、诊断、验证。
- 验证注明 bootstrap/cross_validation/external_prediction/simulation_based/prospective_prediction/posterior_predictive_check 之一。**bootstrap 和内部 CV 不等价于独立人体预测验证。** 审阅说明必须明确验证范围。
- 审阅记录含 reviewer、带时区时间戳、scope 和 source document SHA-256，绑定本次提供的原文附件。
- 引用量带数据库和检索时间，只是文献元数据；无硬性引用数门槛。

模型卡模板为 `examples/model_card.template.json`。缺证据维持 NOT_FOUND / NOT_VERIFIED / PENDING。不能为了运行而把空字段改为 SUPPORTED。

`paper_guided` 检查的是记录是否齐全、来源是否匹配和声明范围是否兼容，并不自动验证 finding 的真实性，也不自动导入论文公式、误差结构、参数值或代码。若论文与当前实现的随机效应、残差模型或估计方法不同，需要明确完成方法适配后才能视为复现。当前提供的真实文献卡没有冒充通过此审阅。

## 两条分支分别审阅

**PK**：采样是否覆盖分布/消除、个体层级是否明确、BLQ 是否合理处理、单位与分析物是否一致、CL/V 等参数是否可辨识；检查预测/残差、随机效应、bootstrap/VPC 或独立数据。少数时间点对二室模型拟合好不能证明额外参数有支持。

**Index**：比较是否使用同一组独立终点、指标范围是否充分、Emax/EC50/Hill 是否可辨识、候选指标是否高度相关；检查训练外预测和选择稳定性。不同实验条件/群组可改变最佳指标，不能在代码中预先固定 fAUC/MIC 胜出。

## 已找到的 PMB 参考线索

以下是待进一步全文/附件审阅的候选，不是本次已复现的模型：

| 分支 | 原始研究 | 对当前工作的意义与限制 |
|---|---|---|
| Index | [2018 PMB PK/PD research](https://pmc.ncbi.nlm.nih.gov/articles/PMC5890666/) | 使用 inhibitory sigmoid 模型比较指标；报告的 fAUC/MIC 与 fCmax/MIC R² 很接近。支持输出完整排名，不能把微小差别当成独立验证。 |
| Index | [2023 PMB PK/PD research](https://pmc.ncbi.nlm.nih.gov/articles/PMC10377753/) | 不同数据条件下，fCmax/MIC 可取得较高拟合；支持从本次数据选择候选，而非固定答案。 |
| PK | [Pharmacokinetics and Renal Disposition of Polymyxin B in an Animal Model](https://pmc.ncbi.nlm.nih.gov/articles/PMC3486600/) | PMB 动物房室模型候选；成分测量、serum/plasma 以及分析物定义需与 Roberts 数据核对。 |
| 数据来源 | [Roberts et al., 2022](https://doi.org/10.1038/s41467-022-29234-3) | 本机有 Fig.4b 原始浓度；论文 NCA 不能替代新建房室模型的验证。 |

本次通过搜索结果核实了前两篇的模型类型/比较结论线索；PMC 直接全文访问触发浏览器检查，尚未据此标记全文审阅完成。联网搜索结果保存候选、引用量及时间，本地库存放文件和定位信息；该边界与上游 NOT_FOUND/provenance 约定一致。

R² 与 AIC 的可比较条件参见 [R 官方文档](https://stat.ethz.ch/R-manual/R-devel/library/stats/html/AIC.html)。同数据、同响应尺度及相容似然是前提。当前无自动 PBPK 建模，也未实现动物到人缩放模块。
