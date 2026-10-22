"""Assemble separate species/index results and an explicit candidate coverage ledger."""
import argparse
import csv
import math
from pathlib import Path
import xml.etree.ElementTree as ET
from research_pipeline.common import PROJECT, read_json, write_json, sha256, utcnow
from research_pipeline.model_catalog import load_catalog


def ref(path):
    path=Path(path).resolve();return {'path':str(path),'sha256':sha256(path)}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run',type=Path,required=True);p.add_argument('--prepared',type=Path,required=True)
    p.add_argument('--catalog',type=Path,required=True);p.add_argument('--junit',type=Path,required=True)
    a=p.parse_args();run=a.run.resolve()
    pop=read_json(run/'rat_population/results/output.json');mouse=read_json(run/'mouse_plasma/results/output.json')
    index=read_json(run/'index/index_output.json');individual=read_json(run/'rat_individual/results/output.json')
    supplemental_path=run/'index/supplemental_input_audit.json'
    supplemental=read_json(supplemental_path) if supplemental_path.exists() else None
    rat_input=read_json(run/'rat_population/input.json')
    n_rat_rows=len(rat_input['records']);n_rats=len({r['subject_id'] for r in rat_input['records']})
    mouse_input=read_json(run/'mouse_plasma/input.json')
    n_mouse_rows=len(mouse_input['records']);n_mouse_times=len({r['time_h'] for r in mouse_input['records']})
    assert read_json(run/'verification/verification.json')['status']=='PASSED'
    for branch in ('rat_population','rat_individual','mouse_plasma'):
        e=read_json(run/branch/'execution.json')
        assert e['status'] in ('COMPLETED_PENDING_HUMAN_REVIEW','DESCRIPTIVE_COMPLETED_PENDING_HUMAN_REVIEW')
        assert sha256(run/branch/'results/output.json')==e['result_sha256']
        assert sha256(e['input_source']['path'])==e['input_source']['sha256']
        for path,h in e['code_sha256'].items():
            relative=Path(path).relative_to(PROJECT/'pkpd_r')
            assert sha256(run/branch/'code_snapshot'/relative)==h
    rabbit_sources=[];rabbit_series=[];rabbit_summaries=[]
    for path in sorted(a.prepared.glob('*.json')):
        d=read_json(path)
        if d.get('metadata',{}).get('species')!='rabbit':continue
        rabbit_sources.append(ref(path))
        for r in d.get('records',[]):
            if isinstance(r.get('concentration_mg_L'),(float,int)) and isinstance(r.get('time_h'),(float,int)):rabbit_series.append(r)
            if r.get('parameter') in ('AUC_0_12h','Cmax'):rabbit_summaries.append(r)
    assert not rabbit_series,'New rabbit profiles require reassessment before assembling an old gap conclusion'
    rabbit={'status':'BLOCKED_NO_SERIAL_PK','concentration_time_rows':len(rabbit_series),'source_files':rabbit_sources,
      'available_parameter_summaries':rabbit_summaries,'models_considered':['1C','2C','3C','saturable_elimination'],
      'reason':'Only AUC/Cmax summaries and PD/context records. Timing, concentration basis and serial PK observations are absent; no pseudo-timepoints or animals were created.',
      'fitted_models':[],'best_model':None,'human_review':{'decision':'PENDING','approved_for_downstream_use':False}}
    write_json(run/'rabbit_output.json',rabbit)
    elfpath=a.prepared/'mouse_ELF_SC.json';elf=read_json(elfpath)
    elf_status={'status':'BLOCKED_FOR_MECHANISTIC_PK','source':ref(elfpath),
      'quantified_records':sum(r.get('status')=='QUANTIFIED' for r in elf['records']),
      'reason':'ELF after SC 40 mg/kg has no paired plasma profile for the same regimen, unknown source concentration basis/identity, and BLQ without numeric censoring limit; it is not systemic plasma PK.',
      'candidate_models':['LUNG_ELF_EX1','LUNG_ELF_2C','LUNG_TISSUE_DEPOT'],'fitted_models':[]}
    write_json(run/'mouse_ELF_output.json',elf_status)
    catalog=load_catalog(a.catalog);ledger=[]
    for m in catalog['models']:
        mid=m['model_id'];status='NOT_RUN';reason='Not part of the executable eligible PK/index candidate set for these data.'
        if mid in ('PK_SYS_1C_LIN','PK_SYS_2C_LIN'):
            status='EXECUTED_RAT_AND_MOUSE_DESCRIPTIVE';reason='Rat individual and population candidates; mouse IP time-summary curves. Rabbit lacks serial data.'
        elif mid=='PK_SYS_3C_LIN':
            status='DEFERRED_NOT_IMPLEMENTED_OR_QUALIFIED';reason='Three-compartment implementation not added in this run; rich early-distribution/terminal support required by catalog has not been qualified. Not a fitted rejection.'
        elif mid in ('PK_SYS_1C_MM','PK_SYS_2C_MM','PK_SYS_DOSE_CL'):
            status='BLOCKED_CATALOG_DATA_REQUIREMENT';reason='Catalog requires multiple informative dose levels within comparable route/matrix. Rat IV and mouse IP each supply one level; differing species/routes/matrices cannot create a dose-ranging dataset.'
        elif mid=='INPUT_IV_INF':status='EXECUTED_RAT';reason='Explicit IV administration over one minute.'
        elif mid=='INPUT_IV_BOLUS':status='NOT_APPLICABLE_RAT';reason='Actual infusion duration retained.'
        elif mid in ('INPUT_SC_FO','INPUT_SC_PAR_SAT'):
            status='BLOCKED_MATCHED_SYSTEMIC_PROFILE';reason='Current mouse SC series is ELF; no matched systemic SC PK. Mouse IP is retained as IP and first-order input is an explicitly recorded extension.'
        elif mid.startswith('INPUT_PULM') or mid.startswith('LUNG_'):
            status='BLOCKED_FOR_MECHANISTIC_FIT';reason='Route/matrix-matched plasma-lung inputs and identifiable transfer information are absent. Whole lung and ELF are not merged.'
        elif mid.startswith('SCALE_'):
            status='BLOCKED_COMPARABLE_SPECIES_PK';reason='No three comparable identified species PK parameter sets; rabbit missing, mouse concentration basis and absorption/disposition labels unresolved.'
        elif mid in ('PD_EMAX','PD_SIGMOID'):
            status='BLOCKED_INDEX_INPUT';reason='Index branch checked five free-exposure candidates; no complete matched index-response rows. No fallback to static concentration response.'
        elif mid in ('PD_GROWTH_KILL','PD_ADAPT_RESIST'):
            status='NOT_RUN_DIFFERENT_ENDPOINT_TASK';reason='Time-kill dynamics are a separate model task; do not replace index screening.'
        elif mid=='ERR_PROP':status='EXECUTED_LOGNORMAL_VARIANT';reason='Constant log-scale error tested; declared lognormal variant, not identical to a Gaussian proportional error model.'
        elif mid=='ERR_ADD_PROP':status='EXECUTED_RAT';reason='varConstProp with variance a^2+b^2*Cpred^2 and fixed sigma=1.'
        elif mid=='ERR_MATRIX':status='NOT_APPLICABLE_WITHIN_COMPARISON';reason='Matrix-specific datasets not pooled.'
        elif mid=='BLQ_M3':status='BLOCKED_NUMERIC_LLOQ';reason='Numeric censoring thresholds missing; quantified-only exploratory fits and quarantine records retained.'
        elif mid=='LIK_GROUP_SUMMARY':status='NOT_RUN_LIKELIHOOD_UNSPECIFIED';reason='Mouse time means used for descriptive curve comparison; unknown dependence prevents calling this a qualified group-summary sampling likelihood.'
        elif mid=='UNC_BOOTSTRAP':status='NOT_RUN';reason='Leave-one-animal-out checks executed for top two eligible rat candidates; bootstrap was not executed.'
        elif mid=='UNC_PRIOR':status='NOT_RUN';reason='No unprovided prior used to force identification.'
        elif mid=='UNC_SCENARIO':status='NOT_RUN';reason='No scenario values substituted for missing observations.'
        ledger.append({'model_id':mid,'model_name':m['model_name'],'layer':m['layer'],'status':status,'reason':reason,
          'source_catalog_line':m['source_line'],'required_data':m['required_data'],'hard_rejection_rule':m['hard_rejection_rule']})
    write_json(run/'catalog_execution_ledger.json',{'catalog_source':catalog['source'],'models':ledger,
      'extensions':[{'id':'INPUT_IP_FO','status':'DESCRIPTIVE_MOUSE_ONLY','reason':'Retain actual IP route; no modification to original catalog CSV'}],
      'API_scope':'New population comparison is available through JSON-in/out review script; legacy single-model HTTP dispatch is not extended to every candidate.'})
    suites=ET.parse(a.junit).findall('.//testsuite');tests={k:sum(int(s.get(k,0)) for s in suites) for k in ('tests','failures','errors','skipped')}
    assert tests['failures']==tests['errors']==0
    chosen=pop['selection']['numerical_lowest_AIC'];model=read_json(run/'rat_population/results/models'/chosen/'result.json')
    rv=read_json(run/'rat_population/results/models'/chosen/'random_effects.json')
    cv=pop['cross_validation'].get(chosen,{})
    report=['# PMB：三物种 PK 与平行 index 重跑','',
      '## 结论','',
      f'- 大鼠：重新执行逐只一室/二室；另尝试 7 种群体 NLME 候选。通过初步数值筛查后，拟合 AIC 最低为 **{chosen}**（二室＋加性/比例联合误差，CL/Vc 独立随机效应）。',
      f'- 小鼠血浆：{n_mouse_rows} 个来源数值整理为 {n_mouse_times} 个时间均值，比较一室/二室一阶输入曲线。数值筛查后候选为 {mouse["numerical_best_after_screen"]}；保留 IP、total/free 未知及个体身份未知，不估计 IIV。',
      f'- 小鼠 ELF：有 {elf_status["quantified_records"]} 个定量值，但缺匹配的同方案血浆信息等，肺交换/系统 PK 模型未拟合。',
      '- 兔子：重新核查全部兔子拆分文件，浓度—时间记录为 0；停止房室拟合，未把 AUC/Cmax 汇总反推成假数据。',
      f'- Index：与大鼠群体拟合并行重筛 {len(index["requested_indices"])} 个游离指标；{index["datasets_screened"]} 个数据集中完整主指标—药效记录为 {index["primary_complete_rows"]} 行，正式回归状态为 {index["status"]}。',
      '- 全部结果待人工审核；没有最终批准模型或人体预测结果。','',
      '## 大鼠群体比较','',
      '| 候选 | AIC（共同浓度尺度） | BIC | log R²（条件拟合） | 数值筛查 |',
      '|---|---:|---:|---:|---|']
    fmt=lambda x:'不可用' if x is None else f'{x:.3f}'
    for r in pop['comparison']:
        report.append(f"| {r['candidate']} | {fmt(r.get('AIC'))} | {fmt(r.get('BIC'))} | {fmt(r.get('R2_log_conditional'))} | {r['status']} |")
    report+=['','模型缩写：DIAG=CL/V（或 Vc）独立随机效应；COR=允许它们相关；ALL=二室四个结构参数均设置独立随机效应；LOG=lognormal 残差；COMBINED=浓度尺度的加性＋比例残差。每个模型都以 ML 拟合。',
      '', '**信息准则的尺度已经统一。** lognormal 模型使用 `logLik_C = logLik_logC − sum(log(Cobs))` 后计算 AIC/BIC。旧报告一室 AIC=56.25 是原 log 浓度尺度，本表约 11.31；是尺度换算，不是参数突然变化。群体 AICc 保留为描述性附表，不作为小样本混合模型充分性保证。',
      '', '二室 ALL/LOG 的数值 AIC 更低，但方差不确定性和随机效应边界没有通过筛查；不能只按最小 AIC 将其宣布为最佳。二室 COR/LOG 的四个初值均失败；失败记录完整保留。','',
      '### 拟合最好的待审阅候选','',
      '| 参数 | 估计 | 95% 局部 Wald CI | RSE |','|---|---:|---|---:|']
    for r in model['parameters']:
        report.append(f"| {r['parameter']} ({r['unit']}) | {r['estimate']:.5f} | {r['CI_lower']:.5f}–{r['CI_upper']:.5f} | {r['RSE_percent']:.2f}% |")
    const=rv['variance_parameters']['const'];prop=rv['variance_parameters']['prop']
    report+=['',f'误差标准差：`sqrt({const:.6f}² + ({abs(prop):.6f} × Cpred)²)`。nlme 内部保存的 prop 为 {prop:.6f}，因进入平方，正负号给出相同方差；表述为误差幅度时取绝对值。sigma 固定为 1，避免重复估计尺度。',
      '',f'留一动物验证：{cv.get("folds_successful",0)}/{n_rats} 折收敛。失败折保留；汇总结果见 heldout_animal_validation.json。只验证了筛查后 AIC 最低的两个候选，并非嵌套模型选择验证。',
      '', '二室联合误差模型仍触发残差随时间模式的描述性提醒。当前结论是“筛查后样本内拟合最佳候选”，不是“预测最可靠模型”。',
      '',f'![Rat diagnostics]({(run/"verification/rat_population_diagnostics.png").as_posix()})','',
      '## 小鼠血浆描述性比较','', '| 曲线 | log R² | AIC | AICc | 状态 |','|---|---:|---:|---:|---|']
    for r in mouse['comparison']:
        report.append(f"| {r['candidate']} | {fmt(r.get('R2_log'))} | {fmt(r.get('AIC'))} | {fmt(r.get('AICc'))} | {r['status']} |")
    report+=['','拟合使用时间均值，未把 Mouse 1/2/3 当成确认的连续个体，也未把 27 个数值称为 27 只动物。普通一室曲线使用幅度和排序的快/慢速率；缺额外证据时不能给快慢速率强行分配吸收/消除角色。二室的参数相关性接近 1、区间失效。所有精度指标只在这套描述性误差假设下成立。',
      '',f'![Mouse curves]({(run/"mouse_plasma/results/mouse_composite_fits.png").as_posix()})','',
      '## Index 分支','',
      '主分析：fAUC/MIC、fCmax/MIC、%fT>MIC。探索：给药前 fCtrough/MIC、%fT>4MIC。各指标需要相同窗口、菌株 MIC、同一药效终点和匹配给药方案。Emax/Hill 是后续回归函数。',
      '大鼠 PK 没有匹配的药效；S21 小鼠终末肺数据每菌株仅一个 PMB 方案，未有对应的多方案游离暴露；兔子 PK 汇总与药效给药方案不同。静态 time-kill 不替代 index 比较。',
      '', '## 模型库覆盖与未完成范围','',
      '34 项目录均已登记到 catalog_execution_ledger.json，区分实际执行、数据不足、不同分析任务和未实现。**本次没有三室实现，也没有满足其目录要求的丰富分布相数据资格审查；不是声称三室已拟合后被淘汰。** 饱和消除和剂量依赖 CL 被目录的多剂量水平要求阻塞。没有 bootstrap、先验约束或三物种外推。',
      '', '## 执行与验证','',
      f'- 新增/相关测试 {tests["tests"]} 项通过。测试清单及结果见本次 JUnit 文件。',
      f'- 对 {len(read_json(run/"verification/verification.json")["candidate_checks"])} 个收敛群体模型，以 source record ID 核对 {n_rat_rows} 个观测并重算条件预测、共同尺度 AIC/BIC，均通过。',
      '- 已保存实际运行代码快照、输入、PID、命令、R 日志、RDS、参数表和优化起点记录。',
      '- 本报告使用 verification 下按拟合对象顺序及来源 ID 验证后的诊断图。',
      '', '方法依据：[nlme](https://stat.ethz.ch/R-manual/R-devel/library/nlme/html/nlme.html)；[加性＋比例误差](https://stat.ethz.ch/R-manual/R-devel/library/nlme/html/varConstProp.html)。','']
    if supplemental:
        report += ['', '## 新数据包与新增 index 输入', '',
          'proposal 与上次字节指纹一致，沿用已审核压缩内容并重新绑定新附件；数据处理与 R 拟合均重新执行。benchmark 文件仅保存并计算指纹，未解析其参数或重建暴露。',
          '', f'新增 {supplemental["same_study_MIC_records"]} 条菌株 MIC、{len(supplemental["binding_studies"])} 项研究内结合率、{supplemental["dose_fractionation_regimens"]} 个分次给药方案。',
          f'Table 3 有 {len(supplemental["matched_Table3_group_summaries"])} 个定量药效组均值及 {len(supplemental["nonquantitative_endpoints"])} 个 ND。按研究/菌株匹配了 MIC 与结合率来源，但匹配游离暴露仍缺失。',
          '', '| 研究 | 游离比例 fu | SD（比例尺度） |', '|---|---:|---:|']
        for study,b in supplemental['binding_studies'].items():
            report.append(f'| {study} | {b["fu_mean"]:.3f} | {b["fu_SD"]:.4f} |')
        report += ['', 'S01 与 S02 的结合率分开保留，未借给 S21 的小鼠或大鼠 PK，未用于 ELF。',
          '', 'S02 两株分别有 4 和 3 个定量组均值，且全部是 q8h。Hill 有 4 个均值参数，条件残差自由度分别为 0 和 −1；普通 Emax 分别为 1 和 0。reported n=4 的个体/双侧大腿对应关系未知，未将组均值扩成动物观测。',
          '29 个方案属于分次给药实验，其逐方案数值终点缺失。Table 3 是另一个实验，未仅按菌株和剂量将两者合并。',
          '', '本轮修复了来源拆表器对 DOI URL 的识别，防止新增表被并入最后一张小鼠终末表。错误拆分尝试已标记失效；正式结果使用修复后重新提取的数据。',
          f'完整匹配审计：[supplemental_input_audit.json]({supplemental_path.as_posix()})', '']
    (run/'REVIEW_REPORT.md').write_text('\n'.join(report),encoding='utf-8')
    review={'status':'PENDING','reviewer':'','approved_for_downstream_use':False,
      'proposed_rat_best_fit':chosen,'final_rat_model_decision':'PENDING',
      'mouse_scope':'Time-summary curve only; concentration basis and identities unresolved',
      'rabbit_decision':'BLOCKED_NO_SERIAL_PK','index_decision':index['status'],
      'required_review':['Rat random-effects/variance identifiability and time residual pattern','Incomplete held-out validation',
        'Quantified-only treatment of BLQ','Mouse composite assumptions and concentration basis','Rabbit and matched index data gaps'],
      'bound_results':{'rat':ref(run/'rat_population/results/output.json'),'mouse':ref(run/'mouse_plasma/results/output.json'),
        'rabbit':ref(run/'rabbit_output.json'),'index':ref(run/'index/index_output.json')}}
    if supplemental:
        review['bound_results']['index_supplement']=ref(supplemental_path)
        review['required_review'] += ['Study-specific MIC/binding linkage and Table 3 group-summary interpretation',
                                      'Missing full fractionation endpoints and primary matched free exposure']
    write_json(run/'human_review.template.json',review)
    main_result={'schema_version':'1.0','created_at':utcnow(),'status':'PARTIAL_PENDING_HUMAN_REVIEW',
      'branches':{'rat_population':ref(run/'rat_population/results/output.json'),'rat_individual':ref(run/'rat_individual/results/output.json'),
        'mouse_plasma':ref(run/'mouse_plasma/results/output.json'),'mouse_ELF':ref(run/'mouse_ELF_output.json'),
        'rabbit':ref(run/'rabbit_output.json'),'index':ref(run/'index/index_output.json')},
      'proposed_best_fit':{'rat_population':chosen,'mouse_descriptive':mouse['numerical_best_after_screen'],'rabbit':None,'index':None},
      'report':ref(run/'REVIEW_REPORT.md'),'catalog_coverage':ref(run/'catalog_execution_ledger.json'),
      'verification':ref(run/'verification/verification.json'),'tests':{'counts':tests,'junit':ref(a.junit)},
      'human_review':ref(run/'human_review.template.json'),'downstream_scientific_use_allowed':False,
      'human_translation':'NOT_ESTABLISHED'}
    if supplemental:
        main_result['index_supplemental_assessment']=ref(supplemental_path)
    if (run/'B1/main.json').exists():
        main_result['upstream']={'B1':ref(run/'B1/main.json'), 'data_preparation':ref(run/'data_preparation/main.json'),
                                'package_changes':ref(run/'package_changes.json')}
        main_result['execution_scope']='Fresh exploratory model rerun; reviewed unchanged proposal context reused; no automatic scientific release'
    write_json(run/'main.json',main_result)
    print('Assembled',run/'main.json')


if __name__=='__main__':main()
