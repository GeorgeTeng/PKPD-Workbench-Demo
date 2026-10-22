"""Versioned workflow contracts. Planned paths never imply existing research data."""

VERSION = '2.8'
# Technical checks do not need a human signature. Unknown scientific findings
# remain reviewable; approval is never inferred from absence of a report.
REVIEW_POLICIES = {'intake': 'AUTOMATIC_FILE_VALIDATION', 'results': 'AUTOMATIC_ASSEMBLY',
                   'adequacy': 'ON_SCIENTIFIC_FINDINGS', 'eda': 'ON_SCIENTIFIC_FINDINGS'}
CLINICAL_FIELDS = [
    ('decision_question', '研究决策问题', '本次分析要支持哪一个研究或临床决策？'),
    ('pd_endpoint', 'PD 终点与尺度', '终点名称、变化方向、单位；区分替代终点与临床结局'),
    ('endpoint_window', '终点时间窗', '观测时点、基线与随访时间窗'),
    ('experimental_unit', '实验单位与重复', '个体、动物、菌株、培养孔或组汇总；重复如何识别'),
    ('pathogen_infection_site', '病原体与感染部位', '菌株/病原体、感染模型、部位及采样基质'),
    ('target_population', '目标人群与适用范围', '目标人群、器官功能、临床情景及排除范围'),
    ('exposure_definition', '暴露定义', 'total/free、血浆/组织、AUC/Cmax/T>MIC 及积分时间窗'),
    ('mic_and_binding_source', 'MIC 与结合率来源', '测定方法、物种/基质匹配、文献或数据来源'),
    ('regimen_constraints', 'Regimen feasibility', '给药途径、剂量单位、频次、输注时长与操作约束'),
    ('safety_endpoints', 'Safety 终点与证据', '监测指标、毒性终点、阈值依据；无证据时保留缺口'),
    ('translation_assumptions', '转化假设与不确定性', '动物/体外到人体的桥接、物种差异、缺失 human PK'),
    ('decision_criteria', '判定标准与缺口处理', '通过标准、敏感性分析、不可评估项及补数据条件'),
]


def f(name, kind, description, to=None, source=None, required=True):
    return {'name': name, 'kind': kind, 'description': description, 'to': to or [],
            'from': source or [], 'required': required, 'status': 'PLANNED',
            'delivery': 'VERIFIED_FILE_REFERENCE' if kind in {'data', 'evidence', 'model', 'figure'} else 'JSON_OR_REPORT_FILE'}


def n(identifier, number, title, subtitle, deps, inputs, outputs, template, gates, x, y, target=None):
    return {'id': identifier, 'number': number, 'title': title, 'subtitle': subtitle,
            'depends_on': deps, 'input_contract': inputs, 'output_contract': outputs,
            'context_template': template, 'review_requirements': gates,
            'review_policy': REVIEW_POLICIES.get(identifier, 'HUMAN_SCIENTIFIC_DECISION'),
            'position': {'x': x, 'y': y}, 'target': target,
            'execution_adapter': 'CONNECTED' if target else 'AWAITING_APPROVED_DATA_ADAPTER'}


def context(module):
    return {'schema_version': '2.0', 'module': module, 'task': None, 'rule_ids': [],
            'data_files': [], 'data_dictionary': None, 'source_references': [],
            'clinical_spec_ref': None, 'unknowns': [], 'human_review': {'decision': 'PENDING'}}


NODES = [
    n('intake', '00', '资料接收', '登记文件 · 数据与来源同行', [],
      [f('proposal.docx / .pdf / .txt', 'evidence', '本轮研究方案，压缩的唯一内容来源'),
       f('source_data/*.csv / *.xlsx', 'data', '原始 PK、PD、给药、MIC、结合率等数据'),
       f('model_library / clinical_sources', 'evidence', '模型目录、文献、临床与安全性依据', required=False)],
      [f('manifest.json', 'context', '文件 ID、角色、版本与去向', ['context', 'prepare']),
       f('proposal 原文件', 'evidence', '传给压缩步骤的方案文件引用', ['context']),
       f('source_data 原文件', 'data', '保留原值，直接供数据准备读取', ['prepare']),
       f('model_library / clinical_sources', 'evidence', '模型目录与证据附件引用', ['dispatch', 'clinical'], required=False)],
      {'schema_version': '2.0', 'files': [], 'compression_scope': 'PROPOSAL_ONLY'},
      ['proposal 唯一且可读，文件类型与角色正确', '实际数据和文献附件已登记，保留来源及缺失状态'], 32, 80, 'intake'),
    n('context', '01', 'Context compression', '只压缩 proposal · 保留附件引用', ['intake'],
      [f('manifest.json', 'context', '附件登记信息', source=['intake']),
       f('proposal 原文件', 'evidence', '本轮方案全文', source=['intake'])],
      [f('main.json', 'context', '原 3.0 科研任务、药物、规则与缺口', ['prepare']),
       f('data.files → 原始附件', 'data', '只传文件引用，不把数据正文压缩进摘要', ['prepare'])],
      {'version': '3.0', 'objective': None, 'study': {'drug': None, 'regimen': None, 'population': None,
       'system': None, 'measurements': None, 'methods': None}, 'data': {'files': []},
       'rules': [], 'checks': {}, 'uncertainties': []},
      ['科研任务、药物、研究终点与约束提取完整', '规则编号稳定；缺失信息不补造；附件路径可核验'], 416, 80, 'context'),
    n('prepare', '02', '数据整理与 QC', '清洗 · 拆分 · 充分性判断', ['context'],
      [f('main.json', 'context', '本步任务与清洗规则', source=['context']),
       f('source_data/*.csv / *.xlsx', 'data', '实际原始观测与给药数据', source=['intake'])],
      [f('data_report.json', 'context', '数据问题、处理记录、充分性与审核', ['eda']),
       f('normalized_manifest.json', 'context', '各数据集与实际文件引用', ['eda', 'dispatch']),
       f('normalized/pk_observations.csv', 'data', '按物种、基质、个体、时间整理的浓度数据', ['eda', 'dispatch']),
       f('normalized/pd_observations.csv', 'data', 'PD 终点、时间、菌株及实验单位', ['eda', 'dispatch']),
       f('normalized/dosing_mic_binding.csv', 'data', '对应给药、MIC、结合率记录及来源', ['eda', 'dispatch']),
       f('data_dictionary.json', 'context', '字段、单位、BLQ/缺失定义与层级', ['eda', 'dispatch']),
       f('quarantine.csv', 'data', '隔离数据及原因；不进入拟合', ['eda'])],
      {**context('data_preparation'), 'datasets': [], 'issues': [], 'released_datasets': [], 'sample_size_status': 'NOT_CALCULABLE'},
      ['清洗、单位、给药、实验单位、缺失与 BLQ 处理已核对', '实际规范化文件存在；数据充分性经人工确认'], 800, 80, 'data_preparation'),
    n('eda', '03', 'EDA 探索性分析', '看分布 · 看覆盖 · 找数据缺口', ['prepare'],
      [f('data_report.json / normalized_manifest.json', 'context', '已审核数据范围与限制', source=['prepare']),
       f('normalized/*.csv + data_dictionary.json', 'data', '实际规范化数据和字段字典', source=['prepare'])],
      [f('eda_context.json', 'context', '分析发现、覆盖不足、异常及候选分析范围', ['dispatch']),
       f('eda_summary.csv', 'data', '样本量、重复、缺失、BLQ、时间/剂量覆盖统计', ['dispatch']),
       f('eda_plots/*.svg / *.png', 'figure', 'PK 时间曲线、PD 分布、暴露覆盖与变量关系', ['dispatch']),
       f('normalized/*.csv（原引用）', 'data', '经审核的数据继续同行；EDA 不暗中修改数据', ['dispatch'])],
      {**context('eda'), 'coverage': {}, 'missingness': {}, 'experimental_units': {}, 'findings': [], 'figures': []},
      ['按物种、个体/组汇总和基质分层，未把伪重复当样本量', '异常与覆盖缺口有证据；需要改数据时返回 QC 重新审核',
       'Review the context rule snapshot, relevant applicability and unresolved questions; importing guidance does not establish compliance'], 800, 295),
    n('dispatch', '04', '临床问题确认与分配', '确认 PD 终点 · 分配 context 和数据', ['eda'],
      [f('eda_context.json + eda_summary.csv', 'context', 'EDA 发现与数据可用范围', source=['eda']),
       f('normalized/*.csv + data_dictionary.json', 'data', '经过 QC 的对应数据', source=['prepare']),
       f('model_library + clinical_sources', 'evidence', '同药物模型、临床/安全性证据与来源', source=['intake'])],
      [f('clinical_questions.json', 'context', 'PD 终点、临床问题、方案、安全性和转化假设的人工确认', ['pk', 'index', 'clinical']),
       f('pk_context.json', 'context', 'PK 分支任务、模型范围与数据文件引用', ['pk']),
       f('pk_data/*.csv + dosing.csv', 'data', '只包含 PK 分支所需物种、基质和给药记录', ['pk']),
       f('index_context.json', 'context', 'index 分支终点、候选指标与比较规则', ['index']),
       f('index_data/exposure_pd_mic_binding.csv', 'data', '匹配暴露、PD、MIC、结合率、实验单位', ['index']),
       f('model_catalog_subset.csv', 'model', '各分支适用模型及对应文献引用', ['pk', 'index']),
       f('routing_plan.json', 'context', '文件去向、依赖和 CPU 配额；暴露需 PK 生成时增加依赖', ['pk', 'index'])],
      {**context('dispatch'), 'clinical_questions': {key: None for key, _, _ in CLINICAL_FIELDS},
       'tasks': [], 'file_routes': [], 'parallel_groups': [],
       'index_exposure_source': None, 'index_waits_for_pk_if_exposure_missing': True},
      ['PD 终点、时间窗、实验单位、暴露定义及临床问题由人确认',
       '临床与安全性证据不足标为 UNKNOWN，不编造阈值或人体参数',
       '对应数据文件和模型已分配；index 暴露依赖与并行条件正确'], 416, 295),
    n('pk', '05A', '动物 PK 建模', '拟合 · 不确定性 · 暴露预测', ['dispatch'],
      [f('pk_context.json + clinical_questions.json', 'context', '限定任务和已确认临床问题', source=['dispatch']),
       f('pk_data/*.csv + dosing.csv', 'data', '实际 PK 观测及给药数据', source=['dispatch']),
       f('model_catalog_subset.csv + model code', 'model', '已审核模型与来源', source=['dispatch'])],
      [f('pk_results.json', 'context', '拟合比较、诊断、参数与限制', ['results']),
       f('pk_parameters.csv / covariance.csv', 'data', '估计值与不确定性', ['results']),
       f('exposure_predictions.csv', 'data', '暴露预测及来源；缺少桥接时不生成人体值', ['results', 'index'], required=False),
       f('pk_diagnostics/*.svg + model.R', 'figure', '诊断图、执行模型与复现入口', ['results'])],
      context('pk_longitudinal'), ['模型收敛、可辨识性、诊断和预测检验经审核', '动物暴露、人体外推和缺口明确区分'], 151, 520),
    n('index', '05B', 'PK/PD index 筛选', '匹配 PD 终点 · Emax / Hill', ['dispatch'],
      [f('index_context.json + clinical_questions.json', 'context', '终点、时间窗与指标比较规则', source=['dispatch']),
       f('index_data/exposure_pd_mic_binding.csv', 'data', '实际匹配的暴露、PD、MIC、结合率', source=['dispatch']),
       f('exposure_predictions.csv', 'data', '仅当 index 依赖本轮 PK 暴露时接收', source=['pk'], required=False)],
      [f('index_results.json', 'context', '候选指标、最优模型与适用范围', ['results']),
       f('index_comparison.csv', 'data', 'R²、AIC/AICc/BIC、验证与不可计算项', ['results']),
       f('endpoint_predictions.csv + index_plots/*.svg', 'data', '效应预测、不确定性和诊断图', ['results'])],
      context('pkpd_index'), ['暴露、MIC、结合率和终点有可靠匹配', '同一响应和观测集比较；R²/AIC 最佳不等于已验证临床预测'], 681, 520),
    n('results', '06', '模型结果汇总', '汇合数据 · 图表 · 证据', ['pk', 'index'],
      [f('pk_results.json + index_results.json', 'context', '两个分支审核后的结论', source=['pk', 'index']),
       f('parameters / predictions / diagnostics', 'data', '参数表、预测表、模型比较与图表', source=['pk', 'index'])],
      [f('reviewed_results.json', 'context', '模型证据、限制与未解决问题', ['clinical']),
       f('model_evidence_tables.csv', 'data', '对应估计值、预测、不确定性和来源', ['clinical']),
       f('diagnostics + model code', 'figure', '审核后的诊断图与复现文件', ['clinical'])],
      {**context('results'), 'pk_result': None, 'index_result': None, 'limitations': []},
      ['两个并行分支均已完成且审核通过', '每个结论可追溯到实际数据、模型与不确定性'], 416, 745),
    n('clinical', '07', 'Clinical interpretation', 'Regimen feasibility · Safety · 外循环', ['results'],
      [f('reviewed_results.json + clinical_questions.json', 'context', '模型证据和原始临床决策问题', source=['results', 'dispatch']),
       f('model_evidence_tables.csv + predictions', 'data', '实际暴露/效应估计与不确定性', source=['results']),
       f('clinical_sources / safety data', 'evidence', '给药可行性与安全性原始证据；不足则不可评估', source=['intake'])],
      [f('clinical_interpretation.json', 'context', '临床相关性、获益风险、外推边界与缺口', []),
       f('regimen_feasibility.csv', 'data', '各候选方案与途径、频次、输注、操作约束的对应判断', []),
       f('safety_evidence.csv', 'data', '安全终点、阈值来源、适用人群和不确定性', []),
       f('clinical_report.md', 'report', '人工审核的解释；未验证项不视为临床推荐', []),
       f('next_cycle_request.json', 'context', '回到 QC / EDA / 问题分配的原因与改动，生成新轮次', ['prepare', 'eda', 'dispatch'], required=False)],
      {**context('clinical_interpretation'), 'regimen_feasibility': {'status': 'NOT_ASSESSED', 'scenarios': []},
       'safety': {'status': 'NOT_ASSESSED', 'evidence': [], 'unsupported_thresholds': []},
       'clinical_relevance': None, 'human_prediction_validated': False,
       'next_cycle': {'target': None, 'reason': None, 'requires_human_review': True}},
      ['PD 与临床结局的关系、适用人群和外推假设已审查',
       'Regimen feasibility 与 Safety 分别评价，未知保持不可评估',
       '接受、补数据或修改问题的决定有依据；返回上游需建立新轮次'], 32, 745),
]
# Preliminary task adequacy precedes cleaning; QC/EDA subsequently revisit adequacy.
NODES.insert(2, n('adequacy', '02', '数据充分性判断', '按任务与项目 rules · 不足则补证据', ['context'],
    [f('main.json + manifest.json', 'context', '明确估计目标、已知信息和证据缺口', source=['context', 'intake']),
     f('source_data 原文件 + 已确认项目 rules', 'data', '对照本次任务判断可计算性；没有通用样本量硬阈值', source=['intake'])],
    [f('adequacy.json', 'context', '逐任务 SUFFICIENT / INSUFFICIENT / NOT_CALCULABLE 与依据', ['prepare']),
     f('qc_context.json', 'context', 'Scoped QC tasks, requirements, assessment and verified data file references', ['prepare']),
     f('evidence_gaps.csv', 'data', '缺少哪些变量、时间点、实验单位、精度或来源', ['context']),
     f('source_data 原引用', 'data', '保留实际文件，足够时交给 QC', ['prepare'])],
    {**context('data_adequacy'), 'assessment_status': 'NOT_CALCULABLE', 'task_assessments': [],
     'criteria_rule_ids': [], 'evidence_requests': []},
    ['按明确任务与项目规则判断，缺少判据则 NOT_CALCULABLE', '不足返回补证据；足够仅表示可进入数据准备，后续仍需 QC / EDA'], 800, 80, 'adequacy'))
_layout_updates = {'prepare': ('03', 800, 295), 'eda': ('04', 416, 295), 'dispatch': ('05', 32, 295),
                   'pk': ('06A', 151, 520), 'index': ('06B', 681, 520), 'results': ('07', 416, 745), 'clinical': ('08', 32, 745)}
for item in NODES:
    if item['id'] in _layout_updates:
        item['number'], item['position']['x'], item['position']['y'] = _layout_updates[item['id']]
    if item['id'] == 'prepare':
        item['depends_on'] = ['adequacy']
        item['input_contract'] = [
            f('qc_context.json + approved assessment', 'context', 'Verified assessment, scoped tasks and data-file references', source=['adequacy']),
            f('registered source_data/*.csv / *.xlsx', 'data', 'Original sources; restricted tables are withheld before development export', source=['intake']),
            f('preparation_plan.json', 'context', 'Optional versioned boundary/header corrections', required=False)]
        item['output_contract'] = [
            f('data_report.json', 'context', 'Counts, limitations, reasons modeling cannot pass and missing materials', ['eda']),
            f('normalized_manifest.json', 'context', 'Verified references to every retained and quarantined dataset', ['eda']),
            f('normalized/T*.csv + T*.json', 'data', 'Separate source tables with cell provenance and explicit unit conversions', ['eda']),
            f('normalized/T*.metadata.json', 'context', 'Species, matrix, record level, basis, source and unresolved definitions', ['eda']),
            f('normalized/T*.quarantine.json', 'data', 'BLQ, missing and invalid records with reasons; no imputation', ['eda']),
            f('partition_manifest.json + data_dictionary.json', 'context', 'Development/validation/benchmark partitions and source field definitions', ['eda']),
            f('cleaning_log.json + issues.csv + report.md', 'evidence', 'Traceable changes and concrete required corrections', ['eda']),
            f('eda_context.json / pk_context.json / index_context.json', 'context', 'Separate pending handoffs; no fitting or scientific release', ['eda']),
            f('preparation_plan.template.json', 'context', 'Editable source-header mapping template for a new preparation attempt', required=False)]
        item['review_requirements'] = ['Confirm source partitions, missingness, units and sampling identity against their evidence.',
            'Accept technical preparation for descriptive EDA only; model sufficiency and human prediction remain unestablished.']
    if item['id'] == 'dispatch':
        item['target']='clinical_dispatch'
        item['execution_adapter']='CONNECTED'
        item['title']='Task assignment'
        item['subtitle']='Route tasks and data; ContextBuilder assembles branch context'
        item['input_contract']=[f('approved effective context + assessment','context','Reviewed objectives, task requirements and project rules',source=['adequacy']),
            f('approved QC + completed EDA','context','Verified source metadata, scoped files and descriptive findings',source=['prepare','eda']),
            f('confirmed_clinical_questions.json','context','Confirmed task definitions and exposure dependencies; unknowns stay explicit')]
        item['output_contract']=[f('clinical_questions.json','context','Task definitions, unknowns and provenance',['pk','index','clinical']),
            f('pk_context.json','context','Animal PK tasks, source-qualified files, assumptions and diagnostics',['pk']),
            f('index_context.json','context','Permitted free indices, endpoint/matching gaps and PK dependency',['index']),
            f('clinical_context.json','context','Validation, feasibility, safety and study-wide evidence needs',['clinical']),
            f('routing_plan.json + dispatch_report.json','context','Allocation reasons, parallel work, dependencies and unresolved materials',['pk','index','clinical']),
            f('assigned normalized data + metadata (unchanged references)','data','Only branch-assigned source-separated data; held-out data remain reserved',['pk','index','clinical'])]
    if item['id'] == 'clinical':
        item['subtitle'] = 'Study-wide feedback: proposal, data, evidence, and analysis'
        item['output_contract'][-1] = f('next_cycle_request.json', 'context',
            'Human-requested study revision: target, change type, evidence references, and proposal/data needs',
            ['intake', 'context', 'adequacy', 'prepare', 'eda', 'dispatch', 'pk', 'index', 'results'], required=False)
        item['context_template']['next_cycle'].update(scope='WHOLE_STUDY', source_node=None,
            change_type=None, proposal_revision=None, missing_data=[], evidence_refs=[],
            scientific_acceptance=False, requires_fresh_review=True)
    if item['id'] == 'eda':
        item['target'] = None
        item['execution_adapter'] = 'DISABLED'
        item['availability_reason'] = 'EDA is disabled. Its backend has been removed and will not be called.'
        item['input_contract'] = [f('approved QC + eda_context.json','context','Exact QC approval and only the assigned dataset references',source=['prepare']),
            f('normalized data + metadata + quarantine','data','Read-only source-separated values and QC exclusions',source=['prepare'])]
        item['output_contract'] = [f('eda_report.json + eda_context.json','context','Panel calculability, findings and pending clinical-dispatch handoff',['dispatch']),
            f('eda_summary.csv + exposure_metrics.csv','data','Record counts, coverage, observed maxima and eligible observed-window AUC',['dispatch']),
            f('dose_power_model.json','context','Strict independent-profile regression or explicit NOT_CALCULABLE reasons',['dispatch']),
            f('plots/*.png + *.svg','figure','Linear, semilog, source-dose-normalized PK and supported PD panels',['dispatch']),
            f('metadata_derivations.json + missing_materials.csv','evidence','Exact source dose labels and required definitions',['dispatch']),
            f('normalized data (unchanged references)','data','Approved datasets and metadata forwarded without editing',['dispatch'])]
        item['subtitle'] = 'Temporarily disabled'
        item['context_template'].update(protocol_id='PK_EDA_001', protocol_version='2026-09-20',
            calculability_by_panel=[], descriptive_findings=[], candidate_hypotheses=[],
            alternative_explanations=[], evidence_needed=[], limitations=[],
            eda_rules={'library_ref':None,'review_context_ref':None,'applicability_status':'UNASSESSED'})
        item['review_requirements'].extend([
            '完成线性、半对数、剂量标准化及 Cmax/AUC/Tmax–剂量检查；不能计算的图说明原因',
            'SC/PO 终末段排查 flip-flop；不凭曲线认定房室数或饱和机制',
            '幂模型报告斜率和 CI；剂量比例判据需事先确认，无判据不自动接受'])
    if item['id'] == 'context':
        item['subtitle'] = '检索证据 · 只压缩 proposal'
        item['output_contract'][0]['to'] = ['adequacy']
        item['output_contract'].append(f('evidence_index.json + 文献附件', 'evidence', '已有本地/联网检索接口；证据逐篇核验后引用', ['adequacy', 'dispatch']))
BY_ID = {item['id']: item for item in NODES}
# Data v2 replaces the old active descriptions; node IDs remain stable for saved links.
BY_ID['adequacy'].update(title='Define requirements & label data',
    subtitle='DR requirements → DC coverage/review → Human approval before DP',
    input_contract=[f('main.json + project_rules.json','context','Reviewed objective, definitions and published project rules',source=['context']),
        f('registered original files','data','All registered files accounted for; protected bodies remain deferred',source=['intake'])],
    output_contract=[f('requirements.json','context','Task-specific needs and timing',['prepare']),
        f('data_labels.json + inventory.json','context','Source-bound labels, requirement matches and full file coverage',['prepare']),
        f('adequacy.json + qc_context.json','context','Independent review, actionable gaps and scoped preparation inputs',['prepare']),
        f('requirement_matrix.json','evidence','Criterion-level coverage, exact evidence and documented deferred outputs'),
        f('evidence_gaps.csv + report.md','evidence','Reasons, affected tasks, required materials and timing')],
    review_requirements=['Every registered file and inspected table is accounted for.','Requirements and labels are source-bound and independently reviewed. Unresolved current prerequisites require correction.',
        'Explicitly approve the current checkpoint before DP, including clean PASS results. Review source scope, remaining issues and accepted limitations. Changed input versions invalidate approval.'])
BY_ID['prepare'].update(title='Prepare, validate & hand off',
    subtitle='Human-approved inputs → DP plan → Host QC/metadata → Independent DH review',
    review_policy='ON_SCIENTIFIC_FINDINGS',
    review_requirements=['Deterministic transformations preserve original values, provenance, missingness and quarantine.',
        'Metadata and handoff reviews pass; only descriptive EDA is eligible. Unresolved findings require human review.'])
BY_ID['intake']['output_contract'].extend([
    f('agent_contract.json', 'context', 'IN001-IN008: file checks, proposal selection, registration and release; shared G001 applies'),
    f('readability_report.json', 'evidence', 'Per-file parsing status and deferred reads; scientific QC remains NOT_RUN')])
EDGES = [
    {'id': a + '-' + b, 'from': a, 'to': b, 'label': label, 'kind': 'forward'}
    for a, b, label in [
        ('intake', 'context', 'manifest + proposal'), ('context', 'adequacy', 'context + 数据 + 证据'),
        ('adequacy', 'prepare', '足够 → 数据准备'), ('prepare', 'eda', 'QC + 规范化数据'), ('eda', 'dispatch', 'EDA + 数据 + 图表'),
        ('dispatch', 'pk', 'PK context + 数据'), ('dispatch', 'index', 'index context + 数据'),
        ('pk', 'results', '参数 + 预测 + 图表'), ('index', 'results', '指标比较 + 预测'),
        ('results', 'clinical', '模型证据 + 数据')]
] + [{'id': 'clinical-study-cycle', 'from': 'clinical', 'to': 'intake',
      'label': 'Clinical feedback → proposal / data / evidence / analysis', 'kind': 'feedback',
      'scope': 'WHOLE_STUDY', 'revision_targets': ['intake', 'context', 'adequacy', 'prepare', 'eda', 'dispatch', 'pk', 'index', 'results']},
     {'id': 'adequacy-context', 'from': 'adequacy', 'to': 'context', 'label': '不足 → 补证据 / NOT_CALCULABLE', 'kind': 'conditional'}]
