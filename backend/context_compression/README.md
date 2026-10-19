# Context Compression + Scientific Pipeline Planning

Windows 本地版 **3.11.0**，2026-09-18。内部 context schema 仍为 **3.0**。

## 精简 compression（LEAN_1.0）

新建 Workbench 作业默认选择 `compression_profile=LEAN_1.0`。该 profile 的流程与下文保留的历史多阶段流程不同：

```text
一次提取 context → 一次完整原文审核 context_review → handoff/main.json
                     ↓ REVISE
                定向修补 → 完整原文复核
```

- 正常通过需要两次模型调用；必要时增加一次定向修补和一次复核。只改审核指出的内容及其必要引用，不重复生成未受影响的条目。
- 概览只说明研究方向；详细科学事实、数值、条件和限制保留在 `scientific_context.items`。缺失信息只在 `missing_information.items` 完整表达，`uncertainties` 使用 `[MIxxx]` 引用。推断问题不能重复缺口。
- `data.available`、`data.required` 和 `rules` 为空；原始文件登记和来源仍保留在最终 `data.files`。数据内容的整理与充分性判断留给后续模块。
- 模型只收到完整 proposal 和显式选定的文本澄清。附件正文不进入此精简提取；文件登记不代表附件内容已经审核。
- 独立审核重新读取全部原文，逐条核对输出和原文覆盖，检查条件、否定、单位、数值、阶段限制、关系方向及重复表达。原文引文、响应、版本和哈希保留在运行目录中。
- 一个运行最多一次定向修补；跨恢复累计执行预算为 1500 秒。预算耗尽、`REVISE` 或 `NEEDS_REVIEW` 均不发布交接。工程暂停时间另计，真实测试同时报告端到端耗时。
- 新作业的 Context target 只执行到 `compress`。Project Rules 和 Data 是后续独立步骤；compression 通过不等于科学充分性、人工批准或下游模块通过。

直接调用 Python API 时，用 `init_run(..., compression_profile='LEAN_1.0')` 选择该流程；省略参数仍保留历史行为。每个运行冻结自己的 profile，修改代码不会重写旧请求或旧结果。现有运行只可按其冻结合同恢复。

最终输出为 `handoff/main.json`（schema 3.2，含 compact scientific context 2.0）；完整证据和审核分别保留在接受的响应及 `lean/last_review.json`。`compressed_context.json` 只是概览，不是全部科学内容。`verify_context(run)` 检查发布结果与已审核内容的一致性，不能取代科学判断。

从 profile **1.6** 起，每次提取、定向修补和独立审核都收到完整 G001–G008、适用 CC 条款、CC005 全部 13 类保真要求，以及科学分类和 PK 术语定义。`audit/lean_effective_rules.json` 保存原规则版本、哈希、条款路径和用户授权的流程调整：联合提取、合并审核、附件搜索后移、精简证据表示及明确的执行预算。原规则库不被改写，科学保真、来源边界、分类、缺口和发布条件继续适用。总目标缺失或没有明确来源证据时，不能发布 ready handoff。

Profile 1.0–1.5 保留其历史冻结合同；它们的 PASS 不证明完整原规则包曾被传给模型。Profile 1.6 的单次 PASS 也不等于完成 CC012 要求的独立人工标注评测，该正式 qualification 仍为 `DEFERRED_INSUFFICIENT_LABELLED_DOCUMENTS`。

Profile **1.7** 进一步要求每条缺口是一个可独立解决的问题，保留各自状态和首次使用阶段。审核要求拆分混合科学命题时，补丁可从同一已审核父条目生成子条目，但必须同时修改父条目、使用同一修补依据，并通过父条目及审核引用的精确原文范围检查；父子关系和哈希记录在修补证明中。它不开放任意新增条目，也不替代修补后的全文审核。

Profile **1.8** 将同样的来源检查用于缺口拆分：科学条目只能拆成科学条目，缺口只能拆成缺口，不能跨组借用修补依据。已知的缺失状态仍由缺口条目单独表达；科学条目保留独有事实并引用缺口 ID。PTA 人群和情景属于 `clinical` 阶段，`index` 只用于 PD 指标比较。

Profile **1.9** 要求科学条目之间也只有一个完整表达：即使原文重复，或同一操作分别出现在方法和要求中，也保留一处完整方法及条件，其他条目只保留独有约束并用 SC ID 引用。不同科学角色不能为减少条目而强行合并，独有条件不能被删除。

以下附件检索、requirements inventory 和分段审核说明适用于历史 profile；LEAN_1.0 不运行这些重复阶段。

**Compression 输出 `handoff/main.json`；Project Rules Agent 随后单独发布 `project_rules.json`。** Compression 保留科研任务、药物/研究信息、原文要求、数据要求、检查和不确定项，`rules` 保留为空数组；正式规则的提取、审核和编号交给 Project Rules Agent。其新 `main.json` 通过 `project_rules_ref` 引用规则文件，原始附件登记在 `data.files`。下游按步骤接收完整适用规则及其条件、例外和使用时点。proposal 是主要压缩对象；缺失信息先按问题检索相关授权附件并保留引用。详见 [交接接口](docs/SINGLE_JSON_HANDOFF.md)。

完成两项任务：

1. 从唯一选定的 proposal 提取关键研究信息，生成精简 JSON；相关补充证据保留来源和位置，原文件继续作为下游附件。
2. 以锁定的 context 为基础，参考方法文献，规划有输入、输出、依赖和完成条件的科研流程。

程序、依赖、示例和测试已放在本机。默认文件交接模式不调用外部模型；选择 `run --provider codex` 才发送相应阶段的 proposal、检索片段及规则。`init --package` / `--attachment` 在本地读取所有明确提交的附件、为副本统一编号并保存内容快照；新增 `attachment_plan` / `attachment_evidence` 两个内部步骤，先确定信息缺口，再检索并引用相关片段；不会把全部附件正文默认塞入压缩请求，受保护的验证数据不提前传入。B2 才拆表、重整、清洗和 QC。详见 [附件与数据交接接口](../research_pipeline/docs/ATTACHMENT_HANDOFF.md)。

ZIP 中默认查找唯一文件名含 proposal／研究计划／研究方案的文档。没有匹配或有多个时停止，用 `--proposal-entry 'PMB_project_proposal.docx'` 明确指定。选定项必须是可读且非 reference-only 的文档。旧版全附件压缩运行保留历史，重新运行须从原文件创建新目录。


## Complete compression rules (2026-10-06)

Shared governance **1.2.0** contains G001-G007. G001 (formerly CC010) defines rule identity; G002-G007 cover evidence authority, project alignment, scientific meaning/provenance, minimal task context, version-bound reviews and actionable failures. The compression **1.10.0** CC rules retain only their module-specific extensions, linked through `general_rules`. The full CC005 still contains all 13 preservation categories.

- [Concise reviewer guide](../research_pipeline/docs/interfaces/context_compression.review.json)
- [General rules for review](../research_pipeline/docs/interfaces/general_rules.review.json)
- [Active general/compression/project rule mapping](../research_pipeline/docs/interfaces/rule_layers.review.json)
- [Standalone runtime rules, including full CC005 and internal role contracts](../research_pipeline/docs/interfaces/context_compression.runtime.json)
- Shared processing policy: `../rules/general/workflow_governance.json`. Canonical compression rules: `../rules/compression/compression_rules.json`, `cc005_details.json`, and `compression_agents.json`. Every rule file is indexed in [backend/rules/README.md](../rules/README.md).

Each new run freezes the resolved rules in `inputs.json` and `audit/processing_rules.json`. Every applicable request carries the rules inline. File-handoff mode can send the same complete request and response schema to a different model/API; this update adds no vendor API adapter and makes no cross-model accuracy claim. Rule changes require a new run. Historical results and approvals are preserved.

Material gaps appear in `audit/missing_information_review.json`, the context Review tab, and concise `[MIxxx]` entries in `main.json` uncertainties/data.required. Search details stay in `audit/supporting_evidence.json`. From compression rules 1.20.0, model requests receive a summary of each warning's search (terms, per-file counts and the matched passages they were supplied); the full log stays in `audit/missing_information_review.json`. From 1.22.0, every compression stage after attachment evidence, each review branch included, also receives `supporting_questions`: which question each cited supporting passage answers, with cited proposal passages listed apart. These audit files do not become project R rules. Downstream requests receive G001-G008 and their own step rules, without importing the compression-specific CC pack. Faithful missing-information warnings may coexist with compression PASS; the consuming task decides scientific adequacy.

From compression rules 1.23.0, spreadsheet passages are named by sheet number and row (`F0004_S01R000209` holds row 209 of the first sheet) and CSV passages by row (`F0003_R000012`); record-index IDs such as `F0004_E000181` remain for documents, JSON and runs frozen with earlier rules. A model that cites "row 209" therefore writes the passage that holds it. An attachment citation whose quote is not in its cited passage gets one citation review. From compression rules 1.23.0, when the quote appears exactly in other passages already assigned to the same question, the review lists up to 10 of them, nearest first, and may move the citation to the one whose own sheet, study and table match the claim. The quote stays unchanged, and the original and corrected answers stay in the citation proof (`audit/attachment_evidence_proof.json`). Identical notes repeated under several tables are not treated as interchangeable; without a clear match the review returns UNRESOLVED and the run stops as before.

From compression rules 1.29.0 (CC002 `quote_matching`, `unconfirmed_citations`, `binding_locations`, `unconfirmed_bindings`, `automatic_revisions`), one item the host cannot confirm no longer stops the whole run. Quotes and binding values match their source after removing differences of letter case, spacing and the spelling of dashes, quotation marks and ± or +/-; digits, decimal points and words must still agree. A citation no review can confirm, or a finding without citations, is removed: a FOUND answer becomes SEARCH_INCOMPLETE, its reason says what the host removed, and a material question answered that way stays a missing-information warning. A binding value also counts when it appears in the title or header rows of the cited row's table; a binding still not found after its one repair, or with an invalid component selection, is dropped and its item keeps its statement. A component whose own quote is not in its source still stops the run. Every removal is listed in `audit/unconfirmed_evidence.json` for a person to check; nothing removed is treated as confirmed. When `requirements_review` returns REVISE, the host revises the inventory once by patch and reviews it again before stopping for a person. Before this, the 2026-10-09 PMB runs stopped seven times, each on one item. CC015, which every agent reads, names these host steps as the exceptions to stopping (wording aligned in 1.30.0).

From compression rules 1.30.0 (CC002 `model_payload`, `unknown_review_records`), the copy of a request sent to the model gives each source's text once, in `source_units`, and leaves out the source registry, unit and file hashes and the host's requirements evidence audit; the stored request, its hash and every host check are unchanged. On 2026-10-09 the PMB requirements_review request was 1 MB, about 40 percent of it repeated. The requirements review is asked for exactly one record per ID; a record whose ID the request does not have is moved into `limitations` with its verdict and reason, and an exact repeat is merged, both listed in `audit/unconfirmed_evidence.json`. The PMB run 4 review had added a note under an ID of its own and stopped before its REVISE could be revised. A missing ID, repeats with different verdicts, or an extra record reporting a defect under a PASS still stop the run.

From compression rules 1.31.0 (CC002 `requirements_parts` `PARALLEL`), the proposal part and the supporting parts of the requirements inventory start at the same time instead of the supporting parts waiting for the proposal part (12 of the 27 inventory minutes for PMB on 2026-10-09). Supporting parts read the proposal text instead of the proposal items, write only supporting facts the proposal does not state and link only to their own items; requirements_review reports a fact both sides wrote. Also from 1.31.0 (CC002 `review_parts`), requirements_review runs in up to three parts at the same time: each judges a contiguous run of proposal units and the items whose evidence first cites them, reading the whole inventory as context, and the host merges them into one review that gets every check of a single review. Runs frozen before 1.31.0 keep the sequential parts and the single review.

From compression rules 1.28.0 (`retry_policy.citation_repair.approved_excerpts`), when the citation review approves a passage for a question it was not retrieved for, a later answer to that question (usually its synthesis across files) may cite an exact excerpt of the approved quote from the same passage. Before this, the 2026-10-09 PMB run stopped because the MI012 synthesis kept two of the three sentences of an approved quote.

From compression rules 1.27.0 (CC002 `table_context`), a spreadsheet row travels with its table's title and column-header rows. A table is a run of consecutive rows of one sheet; a row's context is the table's first rows through the last header-like row above it (two or more cells, none numeric), at most 8 rows. Retrieval adds these rows to the question's passages and lists them in the row's `table_header_ids`; every evidence batch carries the header rows of the tables it holds; a citation review of a row receives them; and a cited row brings them into the supporting sources of later stages. Before this, a review could see `Mean ± SD | 24 ± 17` without the header that names the column as the free-drug AUC/MIC ratio.

The shared pack is supplied as actual text to each new independent agent request and snapshotted in new workflow contracts. Compression checks that each CC extension's shared dependencies are present before preparing a request. The shared principles do not impose compression's no-tool boundary on authorized retrieval or computation tasks. Compression preserves original constraints under CC007/CC009; Project Rules Agent separately extracts and publishes `project_rules.json`, referenced by the effective main; G/CC processing rules never become source-derived R rules. Existing frozen requests retain their original governance text and request identities. This migration changes instruction delivery, not the scientific workflow, and does not establish live-model accuracy or faster execution.

### Approved additions (compression rules 1.8.0; intake rules 3.1.0)

The four requirements confirmed during the final audit are merged into existing IDs:

- CC004: `main.json.objective` states this proposal's overall scientific question for its specified drug. An unresolved objective needs clarification before a ready handoff; no drug or analysis is added by default.
- IN001 / CC011: parser success is separate from source-content coverage. Detected unextracted content requires `SOURCE_INCOMPLETE` and correction or a source-bound human irrelevance decision before compression.
- CC019: the approved downstream contract requires structured unresolved items with `id`, `field`, `status`, `needed_at` and `impact`, plus the targeted clarification; detailed searches stay in audit.
- CC012: formal use after a model/API or major rule change requires human-labelled held-out live-model qualification. Error severity, sample size, repetitions and acceptance thresholds remain explicitly undefined until an evaluation plan is agreed.

This update records the rules and supplies them through the scoped contracts. It does **not** implement the objective-specific host gate, source-coverage detector/resolution interface, structured-handoff schema/consumer migration or model-qualification gate. Their per-rule `implementation_status` fields and the review guide identify this work as pending. Models must follow the supplied response schema rather than invent unsupported fields or claim host capabilities are implemented. Existing historical runs retain their frozen rules. CC005 remains the professional meaning-preservation checklist; scientific model suitability is assessed downstream.

### Rule order and explicit retries (introduced in rules 1.7.0)

CC018 is merged into `CC012.pass_meaning`: passing compression does not establish scientific adequacy, acceptable model fit, human predictive validity or clinical safety. Existing rule IDs are preserved. `logical_order` groups them after shared G001-G007:

1. Frame the task: CC016, CC003, CC001, CC002, CC004.
2. Complete and preserve evidence: CC006, CC005, CC007, CC009, CC011, CC019.
3. Write compact context: CC008, CC017.
4. Review and release or correct: CC012, CC015.

These are rule groups, not extra model calls. Rules remain scoped to the relevant internal agent. Faithfulness and completeness run in parallel; global-conflict review follows their validated outputs.

An explicit same-run `ctxcomp run --run <directory> --provider codex` invocation skips accepted upstream stages. Within parallel review it can reuse validated branches only for an identical full request, provider/model identity, validator code and unchanged audit artifacts. A global-call disconnect therefore needs one new call if both prerequisite reviews remain reusable. A changed candidate invalidates all three reviews. A changed prerequisite response invalidates global review. Contract-invalid or incomplete responses cannot be reused; valid REVISE/NEEDS_REVIEW responses retain their failing verdicts, preventing repeated sampling for PASS. Altered cached artifacts stop execution.

`review_branches/<invocation>/*.receipt.json` marks each branch GENERATED or REUSED and links the original receipt. The Python runner accepts `review_executor_id` for custom adapters; it must identify provider, model and configuration. Without it, custom-adapter branch reuse is disabled. The built-in CLI adapter supplies its provider/requested-model identity. Each pending call still has one attempt; five-minute local heartbeats and event timings remain, with no default model-call deadline.

Source or rule changes require a new run. The Workbench revision action still creates a new run and does not share cached branches across runs. This optimization covers explicit same-run compression resumes, not project-wide selective reruns. Tests measure call counts and gates using authored responses, not real-model speed or semantic accuracy.

## 先看当前研究的结果

- [精简 context JSON](/C:/Users/georg/Documents/Codex/2026-09-15/du/outputs/Context_Compression_Local_2026-09-16/demo_run/compressed_context.json)
- [完整 workflow JSON](/C:/Users/georg/Documents/Codex/2026-09-15/du/outputs/Context_Compression_Local_2026-09-16/demo_run/project_plan.candidate.json)
- [研究流程说明与图](/C:/Users/georg/Documents/Codex/2026-09-15/du/outputs/Context_Compression_Local_2026-09-16/demo_run/REPORT.md)
- [源码兼容说明](/C:/Users/georg/Documents/Codex/PMB-Translational-PKPD-code/backend/context_compression/docs/COMPATIBILITY.md)
- [方法与参考文献](/C:/Users/georg/Documents/Codex/PMB-Translational-PKPD-code/backend/context_compression/docs/METHODS.md)

示例依据本轮聊天整理，标记为 **assistant-compiled demonstration**。上下文和流程由本助手编写，再通过已安装程序完成保存响应回放和校验。没有假称程序已通过新 proposal 的独立准确率测试，也没有调用模型后台或执行 PK/PD 计算。

## 1. 本机启动

打开 PowerShell：

```powershell
Set-Location 'C:\Users\georg\Documents\Codex\2026-09-15\du\context_compression'
.\run.ps1 doctor
```

环境位于同级的 `.venv-context`。已有 `jsonschema`、`pytest`，并能使用本机 `pypdf`、`python-docx`。不用修改系统 Python。

迁移到另一台 Windows 电脑时，复制源码目录，安装 Python 3.11+ 后执行：

```powershell
.\setup.ps1 -Python 'C:\path\to\python.exe'
```

程序只需 JSON 校验依赖；PDF、Word 和测试依赖由安装脚本一起准备。不要复制虚拟环境作为跨电脑安装方式。

## 2. 输入新 proposal

支持 `.md`、`.txt`、可提取文本的 `.pdf` 和 `.docx`。扫描 PDF 需要先提供经核对的 OCR 文本。单文档上限 200,000 字符；超长会报错，不静默截断。PDF/Word 提取后仍应核对表格、公式和脚注。

```powershell
.\run.ps1 init --proposal 'C:\Research\proposal.md' --out 'C:\Research\runs\study01'
```

可选：`--clarification` 添加说明文档；`--inventory` 添加描述性数据清单；`--policy` 设置项目范围；`--literature` 提供已审读的方法库；`--budget` 修改长度预算。不要把浓度记录当作 inventory 上传。

数据清单例子：

```json
[
  {"id":"ANIMAL_RAW","description":"Rat PK records declared by the proposal; access and QC not yet verified"}
]
```

“声明拥有数据”与“数据已经检查合格”分别记录。程序不沿清单中的路径打开观测文件。

当前默认范围：排除 PBPK，该药人体 PK 仅用于后续验证，PD/CFR 及已有人体验证数据默认关闭。当前示例显式打开 PD。策略影响流程规划，不允许反过来把程序默认值伪装成 proposal 原文事实。

## 3. 两种运行方式

### A. 文件交接模式：适合在当前对话里继续工作

```powershell
.\run.ps1 prepare --run 'C:\Research\runs\study01' --stage requirements
```

读取 `requests/requirements.prompt.txt`，让模型按请求中的 schema 输出 JSON，保存为 `requirements.response.json`，然后：

```powershell
.\run.ps1 accept --run 'C:\Research\runs\study01' --stage requirements --response 'C:\Research\requirements.response.json'
```

第一部分依次完成前四个 stage；后续流程规划另有两个 stage：

```text
requirements → requirements_review → context → context_review
    → pipeline → pipeline_review
```

每一步都先 `prepare`，再由模型或审查者产生响应，再 `accept`。必须回传请求中的 `request_sha256`；不能把别的 proposal 或旧版本响应直接复用。

这一模式可直接使用本对话协作生成，无需配置额外 API key。保存响应不会自行改写；收到 REVISE 后重新 prepare 对应生成步骤。

### B. Codex 命令行自动模式

```powershell
.\run.ps1 run --run 'C:\Research\runs\study01' --provider codex
```

已实现实际 `codex exec` 调用和 JSON Schema 输出。默认到 `context_review` 停止；如需另外生成研究计划，显式添加 `--stop-after pipeline_review`。使用已安装 Codex CLI 的登录；无需在代码中写 API key。可以用 `--model` 明确指定可用模型；未指定时读取 `CTXCOMP_CODEX_MODEL`，未设置则使用 `gpt-6-sol`。调用隔离用户配置，避免载入无关 MCP 配置；请求使用只读 sandbox。

此模式会联网调用模型，使用账户配额。前四阶段只发送 proposal 与对应审查材料；可选 pipeline 阶段另外发送文件登记元数据和方法资料，不发送附件观测全文。代码不会读取或复制登录凭据。后台登录和模型可用性需要实际环境支持。软件测试、保存响应回放和真实模型运行分别记录，不能互相代替。

每个未完成阶段仅一次调用。错误、`REVISE` 或 `NEEDS_REVIEW` 立即停止，不自动修订或重试；CLI 返回非零状态码。失败响应和反馈保留。之后明确发起新的运行命令或文件提交才能继续；已接受的历史文件不被覆盖。`--attempts` 仅接受 1。

## 4. JSON 规则

压缩后的 `context` 保持：

```text
version / objective / study / data.available / data.required /
rules / checks / uncertainties
```

- `NOT_FOUND` 表示未提供，不补猜测。
- 保留影响后续决策的数值、单位、否定、条件、来源限定、total/free basis。
- `rules` 必须来自原文，适用于本项目，并约束具体技术决定。
- 推荐的新方法属于 pipeline；数据准备建议可以放在 `data.required` 或 `checks`，在审计记录中标注 PROPOSED。
- 来源原文、位置及审查明细保存在 `audit`、`accepted` 中，不传入精简 context。
- 证据路径以 `context` 为根：`/objective`、`/study/drug`、`/rules/0`；审查路径以被审查对象为根，流程审查使用 `/blocks/0`、`/data_files/0`。生成提示和 schema 均明确这一约定。
- 校验器兼容对应的单层 `/context/…`、`/pipeline/…` 前缀，且只接受确实存在的目标；证据审计记录规范路径及原始 `input_path`。原响应不改写，规范化后的重复路径、未知字段、错误前缀及缺失证据仍会报错。
- 默认不限制 content words 和 compact characters，仍记录长度统计。预算 JSON 中 `null` 表示无上限；只有显式设置的正整数才启用对应限制。这些计数不是 token 数。
- 输出总包为 `context + pipeline + review`；pipeline 包含 `blocks / data_files / connections`。
- 方法注明 `PROPOSAL` 或 `SUGGESTED`，引用须能在方法库找到。
- 不确定的输入必须保留；必要步骤不会因缺数据被删掉。
- 文件存在或被登记不代表通过 QC；生成文件始终标记 `TO_GENERATE`。

**兼容边界：**找到了旧聊天记录，没有找回旧 Mac 的 schema 与源码文件。因此保持记录中明确的顶层字段与规则，但不能声称与旧版未见子字段逐字兼容。详细说明见 `docs/COMPATIBILITY.md`。

## 5. 输出与审核

| 文件 | 用途 |
|---|---|
| `handoff/main.json` | 唯一下游交接 JSON；科研内容直接内嵌，附件位于 data.files；rules=[]；Project Rules Agent 单独发布正式规则 |
| `audit/file_registry.json` | 内部文件检查与路由记录，不是科研交接结果 |
| `critical_requirements.json` | 来源绑定的必要事实、未知项和规则；含关键与非关键必要项 |
| `audit/requirements_review.json` | 每个来源审核片段及每项要求的审查完整性 |
| `coverage_report.json` | 每项要求及其条件/动作/限制的输出映射、原子命题审查、清单内关键召回率 |
| `compressed_context.json` | 内部冻结的 proposal 提取结果；下游使用 handoff/main.json |
| `project_plan.candidate.json` | 两阶段审查通过后的候选计划 |
| `pipeline.mmd` | 从同一份 JSON 生成的 Mermaid 图 |
| `REPORT.md` | 易读的流程和文献说明 |
| `inputs.json` | 内部固定 proposal 内容、审核片段、配置、附件登记和指令；模型不接收附件观测正文 |
| `accepted/`、`audit/`、`reviews/`、`submissions/` | 来源位置、候选版本、审查及失败提交记录 |
| `stopped.json` | 最近一次停止事件；历史事件可能在明确重跑完成后仍保留，应结合当前状态查看 |
| `evaluation.json` | 结构检查与语义审查状态；缺独立标签时 F/R/A/总分为 null |

只完成第一部分时，检查清单、审查和输出是否仍对应同一版本：

```powershell
.\run.ps1 verify-context --run 'C:\Research\runs\study01'
```

完成全部六个阶段后检查研究计划：

```powershell
.\run.ps1 verify --run 'C:\Research\runs\study01'
```

专业人员实际审阅后可记录决策：

```powershell
.\run.ps1 review --run 'C:\Research\runs\study01' --decision PASS --reviewer 'Reviewer name' --reason 'Reviewed scope and assumptions'
```

FAIL 必须写理由。决定保存到 `human_review.json` 和完整的 `project_plan.reviewed.json`，绑定候选哈希。示例保持 Pending；这没有阻止本次程序交付，也没有自动批准科研分析。

输入快照或候选内容改变会使原审查失效。要使用修改后的 proposal，创建新 run。原文证据能定位不代表其语义一定支持输出；语义审查与独立专家评价仍然重要。

## 6. 联网文献检索

```powershell
.\run.ps1 search --query 'apramycin allometric human pharmacokinetics' --out 'C:\Research\literature_search.json'
```

只发送显式输入的公共检索词，使用 Europe PMC。记录查询、时间、结果、DOI 和引用量；全文、原始数据、代码与方法适用性分别标记，搜索结果不会自动晋升为已验证方法。用户指定的方法文献需整理成 `resources/literature.json` 的格式后，通过 `--literature` 提供给新 run。

当前实现是小型文献方法库和查询接口，**没有实现全文向量 RAG，也没有训练 RECOMP 模型**。

## 7. 重放和测试

```powershell
& '..\.venv-context\Scripts\python.exe' -X utf8 '.\examples\replay_demo.py' --out 'C:\Research\runs\demo02'
& '..\.venv-context\Scripts\python.exe' -X utf8 -m pytest '.\tests' -q
```

测试覆盖错误来源、清单与来源逐段覆盖、逐项和逐组件审查、未知项、长度预算、依赖环、数据泄漏、版本失效、首错停止、Pending/Fail/Pass 审查和模型调用适配层。针对删除恢复测试、OR 改 AND、> 改 >=、删除 sensitivity-only 的故障注入使用明确标注的审查结果，验证程序拒绝放行；不代表测得 LLM 对这些错误的识别率。独立专家/未见项目上的语义准确率仍待评价。

## CC012: three review agents and dedicated code tests

New Python, CLI and Workbench runs use `parallel_v3` by default: faithfulness is split into three parts that run concurrently with completeness and the global-conflict review, then recombined and checked as one review (see `PARALLEL_REVIEW.md`). `CTXCOMP_CONTEXT_REVIEW_MODE=parallel_v2` runs the global-conflict review after both validated branch responses instead, and `parallel_v1` also gives new runs a single faithfulness call. Faithfulness and completeness are separate fresh calls that run concurrently. `validate_branch` checks each response before aggregation; publication requires a verified three-branch proof. Historical runs retain their input snapshots. Explicit legacy mode remains for historical authored-response replay.


The three dedicated suites are `tests/test_review_faithfulness.py`, `tests/test_review_completeness.py`, and `tests/test_review_global_conflicts.py`. `tests/test_review_agent_wiring.py` verifies the default and isolated provider calls, using a stubbed remote response. Existing `tests/test_split_review.py` covers concurrency, branch failure and proof integrity. These tests do not measure live model accuracy. See the [JSON test and wiring manifest](../research_pipeline/docs/interfaces/context_review_tests.json).
# Proposal-led attachment evidence calls

Compression starts from the selected proposal. `attachment_plan` identifies relevant
missing or ambiguous information and selects authorized attachment IDs. An empty
question list skips attachment model calls.

`ctxcomp.supporting_agents` dispatches a fresh request for each relevant file. A large
file is processed in bounded transport batches with neighboring-record overlap.
The full retrieved evidence stays in the parent request; every question/passage
assignment is checked for coverage. Protected files are not read. A literal-search
miss remains an incomplete search, not proof that scientific information is absent.

Each question is reconciled using file findings and exact source quotations. The
original citation validator runs again before publication; unresolved conflicts
cannot become `FOUND`. No source text or model output is silently truncated. An
indivisible request that still cannot fit stops with a repairable size error.

Audit files: `audit/attachment_agents/<invocation>/plan.json`, individual requests
and responses, `coverage.json`, and the final response. Fresh CLI call telemetry
is under `audit/model_calls/<invocation>/attachment_evidence--<call>/`. Existing
faithfulness, completeness, global review, LangGraph/Prefect/Snakemake gates,
five-minute heartbeats, and no-default-timeout behavior remain in force.

At most `CTXCOMP_EVIDENCE_WORKERS` calls run at once (default 6). From compression rules 1.25.0 a large
file is read in batches of at most `evidence_batch_chars` request characters (250,000), so several calls
read one large table at the same time, and a question synthesis starts as soon as the file calls it needs
have returned. When one call fails, no further call starts and the calls already running finish. A response that passed validation
without repair is indexed in `evidence_cache/` by its exact request, the executor (provider
and requested model) and the validator code. A retry of the same run reuses it instead of
calling the model again: the indexed response must be unchanged and is validated again, its
call folder gains `reused.json` naming the original, and `coverage.json` counts
`reused_calls`. A changed indexed response stops the retry for inspection.

# Requirements in parts

From compression rules 1.25.0 (CC002 `requirements_parts`), a run with supporting passages writes its
requirements inventory in parts instead of one call. The proposal part writes every item whose subject is
a proposal statement (P01..., PQ01...). Then up to three supporting parts run at the same time; each owns
some attachment questions and their cited passages, sees the proposal items read-only and writes only the
supporting facts the proposal items do not carry (SA01..., PQA01...). The host checks each part, merges
them in a fixed order and runs the usual checks, binding repair and review on the merged inventory.
Requests, responses and receipts are under `requirements_parts/<invocation>/`, call telemetry under
`audit/model_calls/<invocation>/requirements--<part>/`, and `requirements_parts_proof.json` links the parts
to the accepted inventory. A validated part is indexed in `requirements_parts_cache/`; a retry of the same
run reuses it and calls only the failed part again. `CTXCOMP_REQUIREMENTS_WORKERS` caps how many supporting
parts run at once (default all).

# Revising a reviewed inventory

From compression rules 1.26.0 (CC002 `revision`), when requirements_review does not pass, the host keeps
the reviewed inventory in `feedback/requirements.reviewed.json`. After a revision is requested, the redo is
one call that receives that inventory with the review (and any person's guidance) and returns a patch: the
records it replaces (same ID), the records it adds (new IDs) and the IDs it removes. Every item the review
marked ALTERED or MISSING must be replaced or removed, or the run stops with
`MODEL_REQUIREMENTS_REVISION_INVALID` and a retry asks for the patch again. Every other record is kept as it
was. The patched inventory goes through the usual schema, evidence and binding checks and a full
requirements_review again. The patch call is under `requirements_revision/<invocation>/`, its telemetry
under `audit/model_calls/<invocation>/requirements--patch/`, and `requirements_revision_proof.json` links
the reviewed inventory, the review, the patch and the accepted inventory.

# Model providers

Every model call (compression, Data agents, adequacy, project rules) goes through
`ctxcomp.providers.codex_generate`. `CTXCOMP_MODEL_PROVIDER` chooses who answers:

| Value | Model | Settings |
|---|---|---|
| `codex` (default) | Codex CLI using its existing login | `CTXCOMP_CODEX_MODEL` (unset = `gpt-6-sol`); an explicit `--model` takes precedence |
| `claude` | Local Claude Code CLI (`claude -p`), using its own login | `CTXCOMP_CLAUDE_MODEL` (unset = `claude-opus-5`; any model name the CLI accepts, e.g. `opus`. Claude Fable 5.1 refuses this project's pharmacology material and Claude Code then answers with a fallback model; `call.json` lists the models that actually answered under `served_models`) |
| `openai` | An OpenAI-compatible chat server, such as a local Qwen in Ollama or LM Studio | `CTXCOMP_OPENAI_MODEL` (required, e.g. `qwen3:32b`), `CTXCOMP_OPENAI_BASE_URL` (default `http://127.0.0.1:11434/v1`), optional `CTXCOMP_OPENAI_API_KEY`, `CTXCOMP_OPENAI_CONTEXT_TOKENS` |

On Windows, set them once with `setx` (for example `setx CTXCOMP_MODEL_PROVIDER claude`)
and restart the calling process; `setx CTXCOMP_MODEL_PROVIDER codex` switches back.
The project's `start-workbench.cmd` pins Codex and `gpt-6-sol`. To use another
provider or model, set the corresponding environment variables and launch the Python module directly.

- Claude Code runs in an empty temporary folder with all tools disabled
  (`--tools "" --disallowedTools "*" --permission-mode dontAsk --no-session-persistence`);
  the request travels on stdin and the JSON object is taken from the final `result` event.
- The OpenAI-compatible call streams from the server in a child process
  (`ctxcomp/openai_stream.py`), so heartbeats, Pause and the silence limit work as for the CLIs.
  Reasoning blocks (`<think>…</think>`) and Markdown fences around the JSON are removed.
- Requests are large: in the October 2026 runs requirements requests reached about 390 KB and
  their review about 530 KB, i.e. well over 100k tokens. A local model needs a context window
  at least that large; set `CTXCOMP_OPENAI_CONTEXT_TOKENS` to the server's context length so an
  oversized request stops with `MODEL_INPUT_TOO_LARGE` instead of being silently cut by the
  server. A single local server usually handles one call at a time, so also set
  `CTXCOMP_EVIDENCE_WORKERS=1` and `CTXCOMP_REVIEW_WORKERS=1`.
- Reused calls are keyed by provider and model, so a retry never reuses another model's
  responses. Every output still passes the same validators and reviews.
