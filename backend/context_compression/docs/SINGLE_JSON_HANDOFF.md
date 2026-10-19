# 单 JSON 下游交接：3.11.0

## 交付内容

Compression 输出 `handoff/main.json`；之后 Project Rules Agent 发布独立的 `project_rules.json`，并生成带 `project_rules_ref` 的新 `main.json`。只有 proposal 提取和审查通过后才发布；不能把文件登记、空字段模板或指向尚未生成文件的路径当作交付。

主文件保留 3.0 核心结构：

| 字段 | 内容 |
|---|---|
| `version` | `3.0`，科研 context 的结构版本 |
| `objective` | 从 proposal 提取的科研任务和研究问题 |
| `study` | drug、regimen、population、system、measurements、methods |
| `data.available` | proposal 报告的数据及获取状态；相关附件证据须区分来源，尚未经过 QC |
| `data.required` | 下一步需要的数据、字段、说明 |
| `data.files` | 本地读取的附件及接收模块 |
| `rules` | 保留的空数组；正式规则只由 Project Rules Agent 写入 project_rules.json |
| `checks` | 具体检查动作 |
| `uncertainties` | 缺失信息、待核实事项、冲突 |

`data.files` 中的每项包含 id、name、path、sha256、kind、role、receivers、read_status、qc_status、fit_ready。文件读取成功不等于通过科学 QC；所有附件的 fit_ready 仍为 false。

上传环节 IN001（原 CC013）：`READ_COMPLETE` 表示支持的解析器成功读取，不表示完成内容审核。显式留到验证阶段的文件使用 `BYTES_READ_ONLY`，仅验证字节可读并保留哈希，不提前解析内容；该状态只能用于 `REFERENCE_ONLY` 且只能分配给 `validation`。普通输入解析失败时停止，`intake/read_error.json` 保存文件名、失败原因及修正办法，不发布成功的 `main.json`。上传规则独立存放在 `ctxcomp/resources/intake_rules.json`，由首个 File intake 节点执行，不作为 compression agent 的指令注入。`agent_contract.json` 和 `readability_report.json` 可从该节点的文件列表查看。

Historical intake rules 2.0.0 contained only IN001 (check files) and IN002 (number files). At the user's request, version 1.1.0 IN006 was renumbered to IN002; version 1.0.0 IN002 meant proposal selection. Existing run snapshots retain their original rule versions. Format, capacity, path checks and deferred-reference protection remained in the host code; proposal selection remained governed by CC001.

Current intake rules 3.0.0 restore the full requirements as eight consecutive English rules. Relative to version 1.0.0: IN003 + IN005 are consolidated into current IN003 (formats and safe file handling); IN007 + IN009 into current IN006 (read-only scope and no scientific QC). Original IN001, IN002 and IN004 keep their meanings; original IN006, IN008 and IN010 map to current IN005, IN007 and IN008. The version 2.0.0 numbering rule IN002 is therefore current IN005. G001 is referenced by the intake pack and supplied once under governance. Runtime checks and limits are unchanged; historical contracts retain their original versions.

内部 `context.schema.json` 严格保留旧结构；对外 `main.schema.json` 在 data 下增加 files。旧消费者可忽略 data.files；使用严格旧 schema 的消费者需改用 main schema。没有声称新增字段与旧严格 schema 完全相同。

## 减少重复

模型提取时把每个事实放在最适合的位置：科研任务在 objective，药物和设计事实在 study，数据描述在 data，原文约束在合适的 study 字段或带来源的 checks，检查动作在 checks。合并同义内容时保留条件、否定、范围、数值和例外，不通过机械去重删除不同条件。

Compression 不提取正式规则或分配 R 编号。Project Rules Agent 重新检查原文及明确指定的项目材料，独立审核后在 project_rules.json 内编号。每条规则包含适用步骤、触发条件、例外和使用检查时点；main.json 只增加发布引用。

## 哈希的边界

`handoff_sha256` 不放在下游主文件里；请求、审核绑定和登记摘要留在内部审计。SHA-256 可检测与保存的摘要不一致的修改，不是数字签名，不保证科学正确性。附件 sha256 保留在 data.files，以便 B2 检查打开的文件是否仍为本次登记的文件。

## 下游接口

CLI：`research_pipeline prepare-sources <main.json> --out <新目录>`。

Python：`research_pipeline.source_preparation.prepare_sources(main_path, output)`。

B2 直接验证 main schema、规则编号、文件角色/接收方与附件哈希，再从原始附件读取数据。科学任务开始前验证 project_rules_ref 及其完整审核链；不能仅复制 main.json 后丢弃规则或证据文件。纯数据登记接口和科学规则审核仍是不同的检查。

对纯接口检查可调用 `ctxcomp.handoff.verify_main(value)`；它不执行拟合，也不声称完成科学审查。B2 整理后仍需数据 QC 和人工确认；PK 与 index 分支保持并行。

## 执行规则

模型调用默认无固定超时，输出字数/字符预算为 null；每五分钟保留本地进程心跳及事件日志。每阶段一次调用，异常或非 PASS 即停止。超时不会发布 main.json，也不会自行填入科研结果；CLI 事件和错误日志保存在 audit/model_calls，用于定位失败。

## 2026-10-06: bounded supporting evidence and review warnings

The proposal remains primary. Relevant authorized attachment excerpts may supplement missing details after a question-led search and citation check. Material unresolved items retain `[MIxxx]` IDs, why they matter and the consuming stage in uncertainties/data.required. Search details and complete CC processing rules stay in B1 audit records. The compression-specific CC rules (excluding former CC010, now G001) apply only to compression and its internal reviews; downstream modules use their own task contracts.

Shared governance 1.2.0 supplies G001-G007 to new workflow requests. G001 (formerly CC010) preserves rule identity and source-version references. G002-G007 define common evidence, scope, preservation, context, binding and release principles. Compression 1.11.0 retains its CC-specific extensions and all 13 CC005 categories. Project Rules Agent publishes explicit applicable requirements in a separate project_rules.json; main.json keeps rules=[] and its published reference; shared and compression processing rules remain in task contracts. Historical requests retain their frozen rule versions.
