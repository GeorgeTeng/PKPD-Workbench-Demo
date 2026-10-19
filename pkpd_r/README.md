# 第二步：PK/PD 指标与纵向 PK 回归（R 原型 0.1.1）

这版可以从合成浓度数据跑到 PK 参数、PK/PD 指标、暴露—终点回归和 JSON/RDS 结果。主线按 **PK longitudinal = 浓度—时间纵向建模** 实现，另提供通用连续药效反应的重复测量回归接口。

当前验证是程序计算检查与合成数据参数恢复。真实药物的预测可靠性，需要另用研究数据评价。

新增 Roberts 2022 Fig. 4b 的实际数据运行脚本 `scripts/run_roberts_fig4b.R`，以及 `R/normalized_pk.R` 中的 mg/kg 个体拟合和单次有限输注群体模型。此扩展按每 kg 报告 CL/V，不假设动物体重；低于定量限记录的处理在该次报告中单独说明。

## 1. 已实现的函数

| 模块 | 入口 | 当前范围 |
|---|---|---|
| 浓度曲线 → 指标 | `pkpd_indices()` | AUC/MIC、Cmax/MIC、%T>MIC；显式 total/free 和积分窗口 |
| 已拟合 PK → 指标 | `indices_from_pk_fit()` | 按给药事件分段积分，处理静脉推注的浓度跳变 |
| 个体纵向 PK | `fit_pk_individual()` | 一/二房室；单次或多次 IV bolus/infusion；加性或对数正态误差 |
| 群体纵向 PK | `fit_population_pk()` | 一房室、t=0 单次 IV bolus；log(CL)、log(V) 个体随机效应 |
| 指标 → 单个终点 | `fit_index_emax()` | Emax/Hill；固定或估计 Hill；上升或下降响应 |
| 比较候选指标 | `compare_pkpd_indices()` | 相同观测的 AIC/AICc、训练 RMSE、按研究/批次整组留出的交叉验证 |
| 通用纵向反应 | `fit_response_longitudinal()` | 时间样条 + 暴露项 + 个体随机截距；可选连续时间 AR(1) 残差 |
| 导出/交接 | `export_pkpd_fit()`、`read_pkpd_context()` | 参数 CSV、拟合值 CSV、模型 RDS、结果 JSON；读取前一步 compact context |

## 2. 在这台电脑上直接运行

PowerShell：

```powershell
# 自动创建带时间戳的新输出目录；不覆盖先前 demo。
& 'C:/Users/georg/Documents/Codex/PMB-Translational-PKPD-code/pkpd_r/run_demo.ps1'

# 运行计算与边界测试。
& 'C:/Users/georg/Documents/Codex/ScienceEnv/R/bin/Rscript.exe' --vanilla `
  'C:/Users/georg/Documents/Codex/PMB-Translational-PKPD-code/pkpd_r/tests/run_tests.R'
```

在 R / RStudio 中：

```r
source("C:/Users/georg/Documents/Codex/PMB-Translational-PKPD-code/pkpd_r/load.R")
```

依赖只有 `jsonlite`、`nlme`、`minpack.lm`，本机已具备。换电脑时可运行 `scripts/setup.R`；通过 `PKPD_R_LIB` 设置 R 包安装目录。本次运行的实际版本保存在 demo 的 `session_info.txt`。

## 3. 最小 R 示例：指标和纵向 PK

以下数值全部用于演示，未对应 PMB、colistin 或 apramycin 的研究参数。

```r
meta <- list(
  drug = "SyntheticDrug", species = "synthetic_animal", matrix = "plasma",
  concentration_unit = "mg/L", time_unit = "h", dose_unit = "mg", route = "IV",
  concentration_basis = "total", record_level = "individual",
  data_origin = "synthetic", regimen_type = "single_dose"
)

# 直接计算一段完整、连续的浓度曲线。
index <- pkpd_indices(
  time_h = c(0, 1, 2, 4, 8),
  concentration_mg_L = c(8, 6, 4.5, 2.5, 0.8),
  mic_mg_L = 1, window_h = c(0, 8), meta = meta,
  output_basis = "free", fu = 0.6, method = "linear_up_log_down"
)
index[c("AUC_MIC_h", "Cmax_MIC", "percent_time_above_MIC")]

# 一个个体：拟合浓度—时间数据。
doses <- data.frame(time_h = 0, dose_mg = 100, duration_h = 0)
times <- c(0.1, 0.25, 0.5, 1, 2, 4, 8, 12, 24)
set.seed(10)
pk <- data.frame(
  subject_id = "S1", time_h = times,
  concentration_mg_L = pk_1cpt(times, CL_L_h = 2, V_L = 12, doses) *
    exp(rnorm(length(times), 0, 0.03))
)
fit <- fit_pk_individual(pk, doses, meta, compartments = 1, error = "lognormal")
fit$parameters
predict_pk(fit, time_h = c(1, 3, 6))
indices_from_pk_fit(fit, mic_mg_L = 1, window_h = c(0, 24), fu = 0.6)
export_pkpd_fit(fit, "my_analysis/individual_pk",
  provenance = list(data_origin = "synthetic", source = "README example"))
```

`fu` 是当前曲线所适用的常数游离分数，程序不会从文献或物种名称猜测。输入已经是 free 浓度时，不再传入 `fu`。如果结合随浓度/时间变化，应先获得有依据的 free 曲线。

## 4. 数据怎么整理

数值输入统一使用 **mg、mg/L、h、L、L/h**。mg/kg 剂量必须先结合该个体体重换成 mg；µg/mL 即使数值等价，也需要明确转换并更改单位标记。

| 输入 | 必需列 | 每行含义 |
|---|---|---|
| 个体 PK | `subject_id,time_h,concentration_mg_L` | 某个体某时间的一次浓度观测 |
| 给药记录 | `time_h,dose_mg,duration_h` | 一次给药；`duration_h=0` 为推注，正数为输注 |
| 群体 PK | 个体 PK 列 + `dose_mg,dose_time_h,duration_h` | 观测行附该个体的单次给药信息；当前必须 t=0 推注 |
| Emax 终点 | `unit_id,某个指标列,response` | 每个独立单位一个、定义一致的终点 |
| 指标比较 | Emax 列 + 所有候选指标；可选 `study_id` | 所有模型使用完全相同的观测 |
| 通用纵向反应 | `subject_id,time_h,response,exposure` | 同一个体的重复反应；另显式传 `response_unit` |

机器可读契约见 `config/input_contract.json`；待填写元数据见 `config/metadata.template.json`。模板中的 `NOT_FOUND` 要保持到来源已明确，不能为了让拟合运行而随意填值。

群体 PK 使用示例：

```r
# population 是按上表整理好的个体长格式数据。
fit_pop <- fit_population_pk(population, meta)
fit_pop$parameters
fit_pop$variance_components

# 新个体：仅计算典型个体曲线，不需要提供待预测的实测浓度。
predict_population_pk(fit_pop, data.frame(time_h = c(1, 4, 8), dose_mg = 100))
# 已拟合个体：带上 subject_id，使用该个体估计的随机效应。
predict_population_pk(fit_pop, fitted_subject_rows, individual = TRUE)
```

不同物种目前分别建模，不能直接堆叠成一个无物种结构的群体模型。研究均值曲线可用于描述性个体曲线拟合，但其 RSE 不代表个体间变异，不能冒充个体重复测量数据。

## 5. 暴露—终点和纵向反应

```r
# 每个独立单位一个终点。response 的定义、单位、评估时间须一致。
emax <- fit_index_emax(endpoint, index_col = "fAUC_MIC_h",
                      direction = "decreasing", estimate_hill = FALSE)
predict_emax(emax, c(5, 10, 20))

comparison <- compare_pkpd_indices(
  endpoint, c("fAUC_MIC_h", "fCmax_MIC", "fT_MIC_percent"),
  group_col = "study_id"
)
comparison$comparison
comparison$index_correlation

# 通用连续反应的重复测量关联模型。
response_fit <- fit_response_longitudinal(
  response_data, response_unit = "explicit response units",
  spline_df = 3, serial_correlation = TRUE
)
```

Emax 的误差模型是独立的连续终点高斯误差；不会把同一个体的多次反应当成多个独立单位。同样，暴露值作为已知输入，尚未传播 PK 估计误差。纵向反应接口是统计关联模型，不包含效应室、周转过程或动态机制。

交叉验证只有全部留出组成功拟合时才给出整体 RMSE。候选指标高度相关时，单个较低 AIC 不足以证明它具有独立解释力。

## 6. JSON 与第一步的衔接

前一步 compact context 的顶层字段仍为：`version/objective/study/data/rules/checks/uncertainties`。本项目通过 `read_pkpd_context(path)` 读取它；该函数只检查交接字段，不替代原程序的完整 schema 验证。

数值模型结果放在单独的 `analysis_manifest.json` 和各模型的 `result.json`，不把大表或模型对象塞进 compact context。来源未找到仍用 `NOT_FOUND`；不可计算的数值用 JSON `null`，并结合状态、失败原因或诊断解释。命名参数保留名称，相关矩阵另存行列名。

每个模型输出：

- `parameters.csv`：估计值、SE、RSE、局部 Wald CI；PK 参数含单位。
- `fitted_values.csv`：输入观测与对应预测值。
- `model.rds`：完整 R 拟合对象；重新加载前先 `source(load.R)`。
- `result.json`：模型类型、元数据、来源、参数、诊断、警告和待复核标记。

## 7. 本版完成度与下一步

已完成可运行函数、合成示例、事件积分、模型导出以及 **37 项自动检查**。测试覆盖解析积分、阈值、单位、free/total、给药跳变、参数恢复、重复测量、新个体预测与失败处理，以及新增的 mg/kg 换算等价性与有限输注模型。

本版尚未包含：口服吸收、群体多次给药、群体输注期间的观测拟合、BLQ 删失似然、参数 bootstrap、VPC、个体随机效应收缩评价、跨物种 scaling、人体 PK 预测及 PTA/CFR。新增单次输注群体接口只拟合输注结束后的观测。不会用固定“3 个个体”之类的程序下限代替样本量论证。PBPK 不在本项目范围。

下一步接入真实数据时，先确定分析单位、给药记录、单位/游离分数和终点，再评价残差、参数可辨识性、重采样稳定性和独立数据预测。RSE 或训练拟合很好，本身不能证明动物到人的外推准确。

方法公式、原始文献和实现边界见 `METHODS.md`。完整可复现示例见 `scripts/run_demo.R`。
