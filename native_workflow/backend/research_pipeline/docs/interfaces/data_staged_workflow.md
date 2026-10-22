# Data 分阶段入口

**2026-10-13 更新：新的 Coverage → Necessity 运行入口已改为 [data_direct_workflow](data_direct_workflow.md)。** 它直接对照 DR 的原需求和原字段，不再使用下文旧版本的 scope × requirement × criterion 展开、100-fact 分包、历史生产代码/DP/DH 依赖或累计时间预算。原科学 Rules 和已完成提取/DR 不变。旧运行目录与下文接口仅保留历史回放，不用于启动本轮新测试。

以下记录的是历史 v4/v5/v6 分阶段入口和旧执行策略，不能作为新 direct 运行状态的依据。实际状态查看本次 `runner_status.json` 和 `report.json`。

| 阶段 | 职责 | 当前状态 |
|---|---|---|
| planning | 根据最新 main、原 Rules、MP、数据名称/种类/字段/设计/关键备注，提出方法输入需求、适用条件、首次需要阶段和来源。 | 使用 data_requirement_plan_v4.py；输出 plan.json。 |
| Coverage | 在允许的实际来源中核实输入与条件，保存证据、反证、搜索范围及不确定性。 | DR v4 新运行使用 data_coverage_v5.py + data_coverage_facts_v5.py；完整阶段才输出 coverage.json。 |
| Necessity | 根据 Coverage 的不足，按研究范围和分析任务解释影响并给出建议。 | Coverage v5 的新请求使用 data_necessity_v6.py；历史运行按保存的执行版本恢复，不迁移旧判断。 |

每条命令只执行所选阶段，不自动推进。统一入口根据 plan 和 coverage 版本选择匹配的执行器；necessity 是 disposition 阶段的可读别名。DR v4 不回落到早期逐表执行器，历史结果保留原接口。

## 增量核查与暂停

新 coverage 请求每包最多 100 个模型事实判断，同时限制输入和预估输出大小。只发送本包适用的完整原 Rules、条件、例外、objective 与来源片段；不能截断证据来凑预算。范围排除须有原规则及同范围原始来源证明，不能仅凭文件名或检索关键词。

同范围、同含义的共享字段复用一个判断，各方法条件与 SCOPE_ALIGNMENT 仍分别核查。模型不再重写 FULL_REQUIREMENT；宿主由组成事实生成汇总。若存在独立测量资格问题则单独保留，不能把备注数值与无关 CFU 正文拼接成 MIC 测量证据。纯汇总在 necessity 中不再变成另一条重复决策。

每次执行默认最多一次新模型调用，完成一包即保存原响应、校验回执和检查点。首次调用失败也保留可续跑入口。`--resume` 验证原绑定并跳过已接受部分；失败重试需要显式 `--retry-failed`，不自动重抽。`--pause` 在当前调用结束后的安全边界停止；`--status` 只读核对状态。部分结果只报告 CHECKPOINTED / PARTIAL，不能当作阶段完成传给 necessity。

累计模型预算包含历史、失败和中断；开始下一包前预估剩余时间是否足够并预留收尾时间。更换目录或切换代码版本不会清除已消耗预算。live06 已用约 1500.407 秒，导入后仍为预算耗尽；本次离线修改不授权增加预算或续跑模型。

检索关键词仅选择允许来源中的阅读候选。定向搜索实际读取相关片段后仍需证明同研究和范围的关联；一次无命中或目录未搜全不能自动判全局缺失。未决事实原样进入后续按动作的 necessity 判断。

定向补查为独立测量资格保留一个事实判断，即使其他字段已支持也不会生成零事实请求。旧反证必须在后续核查中保留；本轮新读来源若明确挑战已支持字段，可通过 `new_counterevidence` 指明该字段及原文证据。宿主保留旧正证和原判断，标记 CONFLICT 待复核，不重判全部已支持字段。跨来源仍须具有本范围与目标来源的原文关联证明，context 关系不能转移测量正文。请求预算同时计入新事实及潜在反证目标；单个完整单元超过 100 个判断或输入/输出限制时在调用前拒绝，要求显式较小分包，不截断原文或突破上限。

单独复核资格时，固定 DEFERRED 字段的原 producer/output 与独立保存的 `deferred_dependencies` 由宿主保留，不能被新响应的空 metadata 清除。定向结果保留实际搜索 round、可见来源和请求来源。v5 当前仍不产生全局 MISSING / TARGETED_COMPLETE，因此尚不能依据本版本新增事实通过 NEW_DATA 的全部先决条件；Necessity 的原必要条件保持不变。

后续补查可继续引用前轮已经准入的反证原文行与 source link 原证明；未引用的旧来源正文不会因此自动加入新请求。本轮新查来源仍单独记录，旧关联不需要模型重新批准，旧 scope 与证据角色权限保持原样。

### Necessity：不足的影响与建议

新运行的核心输出为“研究范围＋分析任务”的影响说明和建议。影响程度采用定性等级，不生成没有依据的百分比。解释哪些不足会阻止当前动作、限制某种分析，或仍待确认；给出可继续的工作、条件性方案及待补查条件。Model-based 优先，NCA 是备选，不要求两者同时成功。

同一任务按影响等级汇总解释；同等级中不同原因、适用条件和建议仍须说清楚。每条不足保留等级映射，建议和待补查项保留各自关联的不足。

模型不再为每个不足逐一填写全部动作的依赖矩阵。宿主保留到原 Coverage 条目和证据的对应关系；同范围同影响可以合并解释，不跨研究、物种、矩阵或给药范围借用事实。原 Rules、DR、Coverage 事实及前置产物记录保持不变。

Necessity 使用 DR 已引用的本地 MP，并可按具体不足选择其他本地 MP。方法资料是解释影响及提出候选方案的依据，不是实际数据满足条件的证明。运行时不联网、不打开整张数值表；知识库的文献补充与学习单独开展。

完整 Coverage 可以包含 PARTIAL、CONFLICT、UNRESOLVED、DEFERRED 等不足，不必先把所有不足确认为缺失才能解释影响。未完成的 Coverage 检查点仍不是完整输入。可提出“若补查后仍缺 X，则考虑 Y”的条件性建议，但不能据此宣称已确认需要新实验；正式新增数据结论仍须满足现有原规则。当前 v5 没有 MISSING / TARGETED_COMPLETE 收敛，不能把待确认事实冒充已确认缺失。

输出影响与建议报告即完成本阶段；不自动启动 Coverage 补查、重写 DR 或推进拟合。候选方法带来的新条件单列为待补查事项，选定方法后再检查。完成报告不代表数据充分、模型可运行或科学批准。

统计时区分检查条目、待确认、部分满足、冲突、等待前置产物和已确认缺失。非 SUPPORTED 条目数不是独立缺口数，scope/task 报告组数也不是缺口数。合成 UNRESOLVED 仅用于接口测试，不得混入真实项目缺失统计；原始检查矩阵的同范围重复字段与跨方法映射保留追溯，主报告按实际影响汇总。

历史 Necessity v4/v5 的逐项处置合同、证据与回放入口保留；新报告不覆盖或重新解释历史结果。历史预算不因接口升级而清零，失败与中断继续记账。


## 简化 DR

DR 将“适用于哪些方法”和“参考了哪些 MP 知识”分开表达。一条共享需求可以适用于多个方法；不再要求 LLM 维护 task_id、单一 analysis、group_id 和逐表 methods 关系图。需求标识和固定关联由宿主生成。

宿主保留完整的已许可来源概览清单和绑定，不强制每张表生成一个候选方法，也不把备注中的不确定性预先判成不足。逐表匹配、原始数值是否满足条件、跨表是否有真实配对关系，属于后续 coverage。

原科学 Rules 的文字、条件、例外与适用范围保持不变。项目明确要求必须有直接项目来源；方法资料库推导的需求保留候选身份与条件。仅引用总 objective 不能把任意方法条件升级为项目明确要求。参考资料不能代替原始数据证据。

Animal PK 优先 model-based，NCA 为可选替代路线；不能因某条路线缺项取消它本身的必要条件。PD index、PD target 和非人类 PTA 保留各自的输入与后续产物依赖。Human PK、Horse 和 benchmark 仍遵守原有隔离与权限。

## Coverage / Necessity 规则资料包

位置：backend/rules/data/staged_assessment/。包内分别保存 coverage policy、necessity policy、按分析动作组织的参考模板、假设例子、schema 和带哈希的 manifest。

已确认原则：

1. 对未找到的项目定向扩查其余许可来源；尚未搜清时为待确认，不能认定全局缺失。
2. 只阻断首次实际依赖缺项的动作。未来模型参数或 target 保留生产任务及依赖关系，不阻断无关当前动作。
3. 原规则明文例外且证据明确时，按原规则裁定；歧义、冲突和规则指定人工的情况另行处理。
4. 同研究、物种、矩阵、给药、窗口与记录层级等相同范围的事实核查一次；各方法额外条件分别判断，不同范围不能借证据。
5. 只有当前所选动作确实需要，且现有许可来源已确认不能补齐时，才建议新增数据。补查来源、补充定义、等待前置产物分别记录。

规则包保留编写时的 AUTHORED_NOT_ACTIVATED、NOT_CONNECTED 快照，不替代原 DC/G/项目科学 Rules。实际执行器显式读取该包，并在各自运行记录中绑定 policy 与实现版本；不要用旧编写报告推断运行状态。只读 loader 校验文件和来源哈希、引用 ID、schema 与假设例子的一致性，本身不检查数据、不调用模型或打开科学批准门槛。

Coverage 以原始来源范围保存事实；同表的共享需求只核一次，再按 method_uses 复用。未找到的项目需要实际定向补查后才能称为缺失，未读完保留待确认。Necessity 复用 coverage 证据，按分析任务解释不足影响；共享 DR 行的 required_by 不能覆盖更早的真实依赖，相关影响须说明并保留原值。

备注中明确报告的数值保留其原始 SOURCE_NOTE 身份，例如 MIC 字段可由精确备注支持。完整 DATA 需求还须遵守原 body 证据要求：若模型仅凭备注给 FULL_REQUIREMENT 正面判定，宿主将完整测量资格降为 UNRESOLVED，并在对应 criterion 的 host_qualification 中保留模型原判定与降级原因。原响应、字段数值和证据不改写；这不表示已报告的 MIC 缺失，也不授权新增实验。来源范围、精确引用及原始 body 校验继续生效。

Necessity 的建议区分资料整理与分析动作。Model-based PK 优先、NCA 为备选；PD index、PD target 和 PTA 按原计划分别说明不足的影响，不把尚未生成的 target 或模型输出变成当前所有任务的阻断项。能继续整理资料不等于模型输入已支持。新接口给出候选建议，不发布正式 NEW_DATA 裁定或授权实验；历史正式裁定仍须满足原必要性与来源查清条件。

## 来源与历史记录

已完成提取不重跑。每次 DR 使用新输出目录；旧失败响应、原请求、模型身份及输入哈希保留。inherited_unresolved.json 原样传递 main 中未决项和提取 findings，不在需求规划中关闭它们。

绑定重放和自动测试只能证明相应合同与来源一致性，不能证明实际数据达标或方法已获科学认可。所有 scientific_approval、can_enter_qc、fit_ready 保持 false。

执行记录原样保留 provider 的 `served_models`。仅当它报告唯一且一致的模型身份时生成单值 `served_model`；多模型或未报告仍记为未知，不能用请求模型推断实际服务模型。

## 使用

在仓库根目录执行。本轮用户已明确批准 coverage 与 necessity 评审临时使用精确的 gpt-6-sol，执行器显式绑定该模型；其他阶段的默认模型应读取当前配置确认，不能从历史 Luna 设置推断。请求模型与实际服务模型分别记录：实际服务身份仅以 provider 返回的字段为据，未返回时保持未知。复用的 Luna 结果保留原模型来源，不标记为 Sol 重新评审。

真实测试最初通过 `data_live_batch.Batch` 分配一次执行额度，Coverage 和 Necessity 共用 1,500 秒模型时间、从首次调用起 1,800 秒墙钟时间。用户随后明确要求“不用设置时间上限 跑通为止”，本次运行在第 5 包结束后追加该授权，并使用 `data_live_batch_unlimited.UnlimitedBatch` 取消整轮累计时限。原始授权、调用耗时、输入绑定及已接受结果保留。每次请求仍有传输超时及错误检测；这与整轮时限不同。其他未获得这项授权的运行保持原限额，普通 CLI 恢复不能通过更换输出目录绕开。

```powershell
# 仅构建请求，不调用模型。正式运行时去掉 --build-only 并改用新输出目录。
.venv-context/Scripts/python.exe -I -X utf8 -m research_pipeline.cli data-stages planning --source-run outputs/Codex_Agent_Run_20261009/data_test_06_dr_only/run --out outputs/new_data/planning_preflight --build-only

# 仅校验已编写的规则资料包；不激活、不评估数据。
.venv-context/Scripts/python.exe -I -X utf8 -m research_pipeline.staged_assessment_policy --out outputs/new_data/policy_verification.json

# 零模型迁移：完整重放并导入已经接受的 v4 结果及累计预算。
.venv-context/Scripts/python.exe -I -X utf8 -m research_pipeline.cli data-stages coverage --source-run outputs/Codex_Agent_Run_20261009/data_test_06_dr_only/run --plan outputs/Codex_Agent_Run_20261009/data_test_13_dr_simplified/live01/plan.json --import-from outputs/Codex_Agent_Run_20261009/data_test_13_dr_simplified/coverage/live06 --out outputs/new_data/coverage --build-only

# 只读核对；不会调用模型或清除累计预算。
.venv-context/Scripts/python.exe -I -X utf8 -m research_pipeline.cli data-stages coverage --out outputs/new_data/coverage --status

# 恢复运行获授权且累计预算允许时，最多执行一包；不会启动 necessity。
.venv-context/Scripts/python.exe -I -X utf8 -m research_pipeline.cli data-stages coverage --out outputs/new_data/coverage --resume --max-new-calls 1

# 完整 coverage 发布后，单独准备 necessity；此命令仍不调用模型。
.venv-context/Scripts/python.exe -I -X utf8 -m research_pipeline.cli data-stages necessity --plan outputs/Codex_Agent_Run_20261009/data_test_13_dr_simplified/live01/plan.json --coverage outputs/new_data/coverage/coverage.json --out outputs/new_data/necessity --build-only
```
