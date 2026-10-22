"""Verify actual fits and assemble one handoff; no automatic scientific approval."""
import argparse
import csv
import math
from pathlib import Path
from research_pipeline.common import PROJECT, read_json, write_json, sha256, utcnow


def ref(path):
    return {'path':str(Path(path).resolve()),'sha256':sha256(path)}


def csv_rows(path):
    with Path(path).open(encoding='utf-8-sig',newline='') as stream:
        return list(csv.DictReader(stream))


def verify_metrics(result, predictions, keys, is_pk=False):
    count=0
    for row in result['comparison']:
        if row['AIC'] is None: continue
        p=[r for r in predictions if all(r[k]==row[k] for k in keys)]
        assert len(p)==row['n']
        y=[float(r['observed']) for r in p]; yp=[float(r['predicted']) for r in p]
        if is_pk: y=list(map(math.log,y));yp=list(map(math.log,yp))
        n=len(y);k=(3 if row['model']=='1cpt' else 5) if is_pk else row['n_parameters']
        sse=sum((a-b)**2 for a,b in zip(y,yp));sst=sum((a-sum(y)/n)**2 for a in y)
        aic=n*(math.log(2*math.pi)+1+math.log(sse/n))+2*k
        targets={'AIC':aic,'BIC':aic-2*k+k*math.log(n),
                 'AICc':aic+2*k*(k+1)/(n-k-1) if n>k+1 else None,
                 'R2_log' if is_pk else 'R2':1-sse/sst}
        for name,target in targets.items():
            if target is None: assert row[name] is None
            else: assert math.isclose(row[name],target,rel_tol=1e-8,abs_tol=1e-8),(name,row,target)
        count+=1
    return count


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('pk','auxiliary','tests','out'): parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=False)
    pk=read_json(args.pk/'results/output.json');aux=read_json(args.auxiliary/'results/output.json')
    tests=read_json(args.tests/'execution.json')
    assert tests['status']=='PASSED' and tests['tests']['failures']==tests['tests']['errors']==0
    for folder,result in [(args.pk,pk),(args.auxiliary,aux)]:
        execution=read_json(folder/'execution.json')
        assert execution['status']=='COMPLETED_PENDING_HUMAN_REVIEW'
        for name in ('R_script','input','result'):
            assert sha256(execution[name]['path'])==execution[name]['sha256']
        assert result['human_review']['decision']=='PENDING' and not result['human_review']['approved_for_downstream_use']
        provenance=result['provenance']
        for item in provenance.get('sources',[provenance.get('source')])+[provenance['catalog']]:
            if item: assert sha256(item['path'])==item['sha256']
    checks={'pk_candidate_metrics_independently_recomputed':verify_metrics(pk,csv_rows(args.pk/'results/predictions.csv'),['subject_id','model'],True),
            'auxiliary_metrics_independently_recomputed':verify_metrics(aux,csv_rows(args.auxiliary/'results/predictions.csv'),['strain','model']),
            'source_input_result_hash_checks':'PASSED','human_review_not_granted':True}
    b2=PROJECT/'outputs/Data_Preparation_PMB_2026-09-18_retry_1628'
    gate=read_json(b2/'human_review_gate.json')
    assert not gate['model_execution_allowed'] and not gate['released_datasets']
    checks['original_B2_gate_still_pending']=True
    inventory=[]
    for path in sorted((b2/'normalized').glob('*.json')):
        d=read_json(path);fields=sorted({k for row in d.get('records',[]) for k in row})
        inventory.append({'file':ref(path),'records':len(d.get('records',[])),'fields':fields})
    write_json(out/'data_inventory.json',{'datasets':inventory})
    index={'status':'BLOCKED_MISSING_MATCHED_EXPOSURE_RESPONSE','analysis_type':'pkpd_index_comparison',
      'candidate_indices':['fAUC_MIC_h','fCmax_MIC','fT_MIC_percent'],
      'regression_models':['PD_EMAX','PD_SIGMOID'],'best_index':None,'ranking':[],
      'reason':'No eligible matched multi-regimen free-exposure, MIC and common efficacy endpoint dataset in the supplied package.',
      'evidence':[ref(b2/'table_assessments.json'),ref(PROJECT/'outputs/Model_Debug_XLSX_2026-09-18_01/workbook_audit/audit.json'),ref(out/'data_inventory.json')],
      'gaps':[
        {'source':'Rat IV plasma','gap':'11 rat PK profiles have no matched antibacterial efficacy outcomes or strain MIC/fu for an index-response comparison.'},
        {'source':'Mouse terminal lung burden','gap':'Only one PMB regimen per strain in extracted data; no matched exposure series with schedules separating candidate indices.'},
        {'source':'Rabbit exposure summaries','gap':'PK summary regimen 1 mg/kg q12h differs from efficacy loading 2.5 then 1.5 mg/kg q12h; no aligned full free-concentration profile.'},
        {'source':'BAA1705/KP619 static time-kill','gap':'Nominal static C is not measured free C; even if free C were known and constant, fAUC/MIC = window_duration * fCmax/MIC, so these indices cannot be distinguished by this design.'}],
      'required_input':{'join_keys':['study_id','regimen_id','strain','unit_id'],
        'regimen':['dose','dose_unit','route','dosing_times_h','administration_duration_h'],
        'exposure':'Measured free concentration-time profile, or suitable matched PK model plus documented binding conversion; alternatively already-computed indices with provenance.',
        'index_definition':['window_h','concentration_basis','unit','calculation_method'],
        'microbiology':['mic_mg_L','response','response_unit','endpoint_definition','response_time_h'],
        'design':'Several suitable regimens with differing exposure shapes, ideally dose fractionation; independent identities and replication documented.'},
      'auxiliary_concentration_fit_counts_as_index_result':False,
      'human_review':{'decision':'PENDING','approved_for_downstream_use':False}}
    write_json(out/'index_output.json',index)
    write_json(out/'verification.json',{'status':'PASSED','checked_at':utcnow(),**checks,'software_tests':tests['tests']})
    recommendations=pk['recommendations']
    n1=sum(r['recommended_after_screen']=='1cpt' for r in recommendations)
    n2=sum(r['recommended_after_screen']=='2cpt' for r in recommendations)
    report=['# PMB index 与动物 PK：待人工审核结果','',
      '## 1. Index 范围纠正','',
      '**真正的 index 是 fAUC/MIC、fCmax/MIC、%fT>MIC。Emax/Hill 是连接各 index 与共同药效终点的回归函数。**',
      '本次静态浓度—效应 Emax/Hill 拟合不属于该 index 比较，已归为范围外辅助结果；不产生最佳 index，不能交给下游当作 index 选择结论。',
      '已复核当前 26 个拆分数据集及原始工作簿审核记录：缺少匹配的多给药方案暴露—MIC—终点表，正式 index 分支停止，`best_index=null`。',
      '', '| 数据 | 阻碍 index 比较的具体缺口 |','|---|---|']
    report += [f"| {r['source']} | {r['gap']} |" for r in index['gaps']]
    report += ['', '若同一窗口内游离浓度恒定，则 fAUC/MIC = 窗口长度 × fCmax/MIC；两个指标只是缩放关系，Emax/Hill 改变 EC50 即可得到同样的拟合，不能判定哪一个驱动疗效。%fT>MIC 在这种理想静态情形通常只有 0% 或 100%。当前名义浓度也不能未经依据直接标成 free。',
      '', '## 2. 大鼠 PK 已完成','',
      f'11 只大鼠、102 个定量点，1 mg/kg IV 输注 1 分钟。8 个非定量记录单独保留，未填补。逐只比较一室与二室：初步筛查后按 AICc 最低，一室 {n1} 只、二室 {n2} 只。这不是物种总体结构选择，也不是已验证的人体外推。',
      '', '| 大鼠 | 一室 AICc | 二室 AICc | 二室状态 | 筛查后 AICc 最低 |','|---|---:|---:|---|---|']
    for r in sorted(recommendations,key=lambda x:int(x['subject_id'].rsplit('_',1)[1])):
        candidates={a['model']:a for a in pk['comparison'] if a['subject_id']==r['subject_id']}
        a,b=candidates['1cpt'],candidates['2cpt']
        fmt=lambda v:'不可用' if v is None else f'{v:.3f}'
        report.append(f"| {r['subject_id'].rsplit('_',1)[1]} | {fmt(a['AICc'])} | {fmt(b['AICc'])} | {b['status']} | {r['recommended_after_screen']} |")
    report += ['', '二室模型在 Rat 3/4/5/6 的参数相关性 >0.95，按目录规则排除；Rat 9 的全部预设起点失败。Rat 7 的两个 AICc 只差约 0.048，Rat 8 只差约 0.880，不能把数字最小解释成明确胜出。Rat 1/7 的二室模型仍有较大的参数 RSE，初步通过相关性筛查不代表充分可靠。',
      '', '一室群体模型作为参考：','', '| 参数 | 估计 | 95% 条件 Wald CI | RSE |','|---|---:|---|---:|']
    for p in pk['population_one_compartment']['parameters']:
        report.append(f"| {p['parameter']} ({p['unit']}) | {p['estimate']:.4f} | {p['CI_lower']:.4f}–{p['CI_upper']:.4f} | {p['RSE_percent']:.2f}% |")
    report += ['', '群体二室尚未实现和比较，故上述一室群体模型不能称为总体最佳。当前没有执行外部验证；BLQ 排除可能影响尾部参数。小鼠/兔数据的既有缺口没有被大鼠拟合成功消除。',
      '', f'![Rat PK fits]({(args.pk/"results/individual_fits.png").resolve().as_posix()})',
      '', '## 3. 范围外辅助结果（不可当作 index 结果）','',
      '两株各 6 个 1 小时终点的静态浓度—效应拟合，结果保留供追溯。BAA1705 的 Hill 虽然 R²/AIC 更好，但 EC50 区间溢出，予以排除；KP619 的 Emax AIC 较低。两株 Emax EC50 的 RSE 约 81% 和 75%，并非精确估计。Hill 的 AICc 因 n=6、k=5 无法计算。',
      '这只是同药物数据的简化再分析。[原论文](https://doi.org/10.1371/journal.pone.0171834) 使用完整 time-kill 的 PSP 模型；本次没有复现或独立验证该模型。',
      '', '## 4. 审核与执行证据','',
      '- MR-01：人工确认分析范围、来源、给药输入和 total/free 定义。',
      '- MR-02：确认相同动物/相同观测内的 AICc 比较；群体模型和逐只模型不混排。',
      '- MR-03：确认可识别性筛查、BLQ 处理影响、参数区间及未完成的预测验证。',
      '- MR-04：Index 维持 BLOCKED；补齐输入合同后重新评估，不用静态 C 代替。',
      '- MR-05：所有模型决定保持 PENDING；审核模板不会自动提交批准或改写 B2 gate。',
      f'- 软件测试 {tests["tests"]["tests"]} 通过。另从逐点预测值独立重算 {checks["pk_candidate_metrics_independently_recomputed"]} 个 PK 拟合和 {checks["auxiliary_metrics_independently_recomputed"]} 个辅助拟合的信息准则/R²，通过核对。',
      '- `execution.json` 保存实际 Python/R 进程号、时间、命令、输入和脚本摘要；RDS、预测表与日志保留。首次 rat 接口错误保留在 `_01`，成功运行位于 `_02`。',
      '- [R 的 AIC 说明](https://stat.ethz.ch/R-manual/R-devel/library/stats/html/AIC.html)：仅在可比数据与似然下比较，较低 AIC 不表示完成外部验证。','']
    (out/'REVIEW_REPORT.md').write_text('\n'.join(report),encoding='utf-8')
    template={'schema_version':'1.0','purpose':'Review record only; does not submit API approval',
      'decision':'PENDING','reviewer':'','reviewed_at':None,'results':{'pk':ref(args.pk/'results/output.json'),'index':ref(out/'index_output.json')},
      'confirmations':{'pk_scope_and_exclusions':False,'pk_parameter_uncertainty':False,'no_human_prediction':False,'index_data_gap_acknowledged':False},
      'per_animal_model_decisions':[{'subject_id':r['subject_id'],'proposed_candidate':r['recommended_after_screen'],'decision':'PENDING','rationale':''} for r in recommendations],
      'index_decision':'BLOCKED_PENDING_DATA','approved_for_downstream_use':False}
    write_json(out/'human_review.template.json',template)
    write_json(out/'main.json',{'schema_version':'1.0','created_at':utcnow(),'status':'PARTIAL_PENDING_HUMAN_REVIEW',
      'branches':{'pk':{'status':pk['status'],'result':ref(args.pk/'results/output.json'),'execution':ref(args.pk/'execution.json')},
        'index':{'status':index['status'],'result':ref(out/'index_output.json'),'best_index':None}},
      'out_of_scope_auxiliary':{'result':ref(args.auxiliary/'results/output.json'),'execution':ref(args.auxiliary/'execution.json'),
        'role':'Static concentration-response only; explicitly excluded from index selection'},
      'report':ref(out/'REVIEW_REPORT.md'),'verification':ref(out/'verification.json'),'software_tests':ref(args.tests/'execution.json'),
      'human_review_template':ref(out/'human_review.template.json'),'human_review':'PENDING',
      'downstream_scientific_use_allowed':False,'human_translation_status':'NOT_ESTABLISHED'})
    print('Verified and assembled:',out/'main.json')


if __name__=='__main__':
    main()
