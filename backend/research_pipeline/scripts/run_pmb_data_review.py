"""Source-bound PMB normalization adapter plus existing scientific QC gate.

Reads the B1 main handoff and B2 source tables. Never reads benchmark contents,
fits models, imputes measurements, estimates CL, or signs a human decision.
"""
import argparse
import collections
import copy
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
from datetime import datetime, timezone

from research_pipeline.engine import run_pipeline, validate_request
from research_pipeline.common import PipelineError, read_json, write_json, sha256
from research_pipeline.time_kill_preparation import normalize_static_time_kill
from research_pipeline.supplemental_preparation import normalize_supplemental
from research_pipeline.dataset_metadata import metadata_sidecar

ROOT = Path(__file__).resolve().parents[2]
OUT = None  # Set by --out. Never overwrite a previous run.
B1 = ROOT.parent / 'outputs/Single_Main_JSON_Retest_2026-09-18_0649/actual_run/handoff/main.json'
SOURCE = ROOT.parent / 'outputs/Data_Preparation_PMB_2026-09-18/source_preparation'
EVIDENCE = ROOT.parent / 'file-c-users-georg-downloads-s11095/cms_translational/species_selection_evidence.md'
NORMAL = None
REQUEST_ID = None
NF = 'NOT_FOUND'


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def ref(path):
    return {'path': str(Path(path).resolve()), 'sha256': sha256(path)}


def export(name, records, metadata):
    payload = {'schema_version': '1.0', 'fit_ready': False, 'metadata': metadata, 'records': records}
    path = NORMAL / (name + '.json')
    write_json(path, payload)
    keys = list(dict.fromkeys(k for r in records for k in r))
    csvpath = NORMAL / (name + '.csv')
    with csvpath.open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        for r in records:
            writer.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v for k, v in r.items()})
    sidecar = metadata_sidecar(path, name, metadata, sources=[{'source_table': metadata['source_table']}],
                              summary={'record_count': len(records)})
    normalized.append({'id': name, 'source_table': metadata['source_table'], 'record_count': len(records),
                       'json': ref(path), 'csv': ref(csvpath), 'metadata': metadata, 'metadata_file': sidecar, 'fit_ready': False})
    return path


def location(t, r):
    return {k: copy.deepcopy(r[k]) for k in ('record_id', 'source_file_id', 'source_sha256', 'source_sheet',
            'source_row', 'source_cell', 'source_cells', 'source_header_cell', 'source_anchor_cell') if k in r}


def issue(code, tables, impact, message, needed):
    issues.append({'id': f'DR{len(issues)+1:03d}', 'code': code, 'source_tables': tables,
                   'impact': impact, 'message': message, 'human_action': needed})


def meta(t, **more):
    return {'source_table': t['table_id'], 'source_title': t['title'], 'source_notes': t['source_notes'],
            'drug': 'polymyxin_b', 'data_origin': 'SUPPLIED_SOURCE_EXTRACTION_NOT_INDEPENDENTLY_REAUDITED', **more}


def change(t, action, rationale, source_record=None):
    changes.append({'table_id': t['table_id'], 'source_record': source_record,
                    'action': action, 'rationale': rationale})


def finite(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def main():
    global normalized, issues, changes
    normalized, issues, changes = [], [], []
    if NORMAL.exists():
        raise RuntimeError('Normalization directory exists; preserve previous output and use a new run.')
    NORMAL.mkdir(parents=True)
    b1 = read_json(B1)
    source = read_json(SOURCE / 'output.json')
    assert source['status'] == 'WAITING_FOR_REVIEW' and not source['errors']
    if Path(source['source_manifest']).resolve() != B1.resolve():
        raise PipelineError('UPSTREAM_MISMATCH', 'Source preparation does not reference this B1 handoff.')
    for item in source['tables']:
        for path_key, hash_key in [('records_path', 'sha256'), ('source_path', 'source_sha256')]:
            if sha256(SOURCE / item[path_key]) != item[hash_key]:
                raise PipelineError('SOURCE_TABLE_CHANGED', f'{item["id"]}: source table hash mismatch')
    for f in b1['data']['files']:
        assert sha256(f['path']) == f['sha256'], f'Attachment changed: {f["id"]}'
    # Verify identities using declared input metadata; do not load reference values.
    readme = Path(next(f['path'] for f in b1['data']['files'] if f['id'] == 'F0001')).read_text(encoding='utf-8')
    assert 'Rat serial plasma supports systemic PK' in readme
    tables = [read_json(f) for f in sorted((SOURCE / 'tables').glob('*.records.json'))]
    assert len(tables) >= 20
    expected_core_titles = ['Figure 4a — mouse plasma', 'Figure 4b — rat plasma', 'Figure 4c — mouse ELF',
        'Rat serum and whole-lung tissue', 'Rabbit PMB exposure summaries', 'Rabbit pulmonary infection outcomes',
        'Neonatal rabbit pulmonary PMB', 'Rabbit study record S09', 'Rabbit study record S10',
        'Rabbit study record S11', 'Rabbit study record S12', 'K. pneumoniae BAA1705 time-kill',
        'K. pneumoniae KP619 time-kill', 'K. pneumoniae surveillance MIC distribution',
        'Figure 3a — P. aeruginosa FADDI-PA038', 'Figure 3b — A. baumannii FADDI-AB051',
        'Figure 3c — K. pneumoniae FADDI-KP065', 'Figure 3d — P. aeruginosa FADDI-PA102',
        'Figure 3e — A. baumannii FADDI-AB156', 'Figure 3f — K. pneumoniae FADDI-KP132']
    assert [t['title'] for t in tables[:20]] == expected_core_titles, 'Core table order/schema changed; remap before normalization'
    cards, specs, attachments, missing_records = [], [], [], []
    pk_config = {
        'T0001': ('mouse_plasma_IP', 'mouse', 'IP', 'plasma', 5.0, None),
        'T0002': ('rat_plasma_IV', 'rat', 'IV', 'plasma', 1.0, 1/60),
        'T0003': ('mouse_ELF_SC', 'mouse', 'SC', 'ELF', 40.0, None),
    }
    terminal_config = {
        'T0015': ('P. aeruginosa', 'FADDI-PA038', 0.5, 'IP', 45.0),
        'T0016': ('A. baumannii', 'FADDI-AB051', 0.5, 'IP', 45.0),
        'T0017': ('K. pneumoniae', 'FADDI-KP065', 0.25, 'IP', 45.0),
        'T0018': ('P. aeruginosa', 'FADDI-PA102', 4.0, 'SC', 90.0),
        'T0019': ('A. baumannii', 'FADDI-AB156', 8.0, 'SC', 90.0),
        'T0020': ('K. pneumoniae', 'FADDI-KP132', 8.0, 'SC', 90.0),
    }
    for t in tables:
        tid, rows = t['table_id'], t['records']
        card = {'table_id': tid, 'title': t['title'], 'source_record_count': len(rows), 'source_kind': t['kind'],
                'source_region': t['region'], 'source_notes': t['source_notes'], 'source_table_file': ref(SOURCE/'tables'/f'{tid}.records.json'),
                'precision_adequacy': 'NOT_CALCULABLE', 'human_prediction_validity': 'NOT_ESTABLISHED', 'fit_ready': False}
        if tid in pk_config:
            name, species, route, matrix, dose, duration = pk_config[tid]
            md = meta(t, species=species, route=route, matrix=matrix, concentration_basis=NF,
                      time_unit='h', concentration_unit='mg/L', dose_unit='mg/kg', analyte='polymyxin_b',
                      formulation=NF, parameter_definition=NF, record_level='individual',
                      sampling_design='serial' if species == 'rat' else NF, regimen_type='single_dose',
                      dose_basis=NF, independent_identity_evidence='README rat serial statement; table rat labels; table note 11 rats' if species == 'rat' else NF)
            outrows=[]
            for r in rows:
                x=copy.deepcopy(r)
                x.update(drug='polymyxin_b', species=species, route=route, matrix=matrix, dose_mg_kg=dose, dose_time_h=0.0)
                if duration is not None:
                    x['duration_h']=duration
                if species=='rat':
                    x['subject_id']='S21_Fig4b_'+r['subject_label'].replace(' ','_')
                    x['identity_status']='SOURCE_SUPPORTED_SERIAL_ID_PENDING_HUMAN_CONFIRMATION'
                if r['status']!='QUANTIFIED':
                    missing_records.append({**location(t,r),'status':r['status'],'raw':r['source_raw_value'],'action':'PRESERVED_WITHOUT_IMPUTATION'})
                else:
                    if not finite(r['time_h']) or not finite(r['concentration_mg_L']) or r['concentration_mg_L']<0:
                        issue('INVALID_PK_VALUE',[tid],'BLOCK_MODEL','浓度或时间非法。','核对原单元格并重新评估。')
                outrows.append(x)
            path=export(name,outrows,md)
            by_status=dict(collections.Counter(r['status'] for r in rows))
            quant=[r for r in rows if r['status']=='QUANTIFIED']
            times=sorted({r['time_h'] for r in rows})
            card.update(status_counts=by_status, quantitative_records=len(quant), time_points=times,
                        concentration_range_mg_L=[min(r['concentration_mg_L'] for r in quant),max(r['concentration_mg_L'] for r in quant)],
                        independent_animals=11 if species=='rat' else NF,
                        independent_count_basis='source-supported serial labels, pending human verification' if species=='rat' else 'column slots do not verify cross-time identity',
                        mathematical_fit_assessment='STRUCTURAL_CANDIDATE_AFTER_METADATA_REVIEW' if species=='rat' else 'BLOCKED_IDENTITY_AND_ROUTE_SUPPORT')
            change(t,'wide_to_long','保留所有格位和状态；数字不变。')
            if species=='rat':
                change(t,'source_scoped_serial_ids','README 明确 serial；使用本来源 Rat 1–11 标签，不与其他表拼接。')
                change(t,'infusion_duration_min_to_h','原注释 1 minute；1/60 h，未从体重猜剂量。')
                card['observations_per_rat']=dict(collections.Counter(r['subject_id'] for r in outrows if r['status']=='QUANTIFIED'))
            aid=name
            attachments.append({'id':aid,'path':str(path),'sha256':sha256(path)})
            specs.append({'id':name,'kind':'pk','data_attachment':aid,'metadata':md,
                          'analysis_options':{'mode':'population_infusion_per_kg','compartments':1,'reference_mode':'baseline'}})
        elif tid=='T0004':
            for field,matrix,unit,factor in [('c002_serum_g_ml_mean_sd','serum','mg/L',1.0),('c003_lung_g_g_mean_sd','whole_lung','ug/g',1.0)]:
                rr=[]
                for r in rows:
                    value=r[field]
                    x={**location(t,r),'time_h':r['c001_time_h'],'matrix':matrix,'value_raw':value,'uncertainty_type':'SD','group_n':NF,'unit':unit}
                    x['source_value_cell']=r['source_cells'][field]
                    if isinstance(value,str) and '±' in value:
                        a,b=[float(v.strip()) for v in value.split('±')]
                        assert math.isfinite(a) and math.isfinite(b) and a>=0 and b>=0
                        x.update(mean=a*factor,sd=b*factor,status='QUANTIFIED')
                    elif value=='<LLOQ':
                        x.update(mean=None,sd=None,status='BLQ',lloq=NF)
                        missing_records.append({**location(t,r),'source_value_cell':x['source_value_cell'],'status':'BLQ','raw':value,'action':'PRESERVED_WITHOUT_IMPUTATION'})
                    else: raise ValueError(f'Unrecognized mean/SD text: {value!r}')
                    rr.append(x)
                export('rat_'+matrix+'_group_summary',rr,meta(t,species='rat',route='IV',matrix=matrix,record_level='group_summary',dose_mg_kg=3,unit=unit))
            change(t,'parse_mean_sd_and_split_matrix','仅拆分已明确的 mean ± SD；serum µg/mL→mg/L 因子1；肺组织保留 µg/g。')
            card.update(mathematical_fit_assessment='SUMMARY_LIKELIHOOD_ONLY_IF_DESIGN_RESOLVED',independent_animals=NF)
        elif tid=='T0005':
            for r in rows:
                x={**location(t,r),'parameter':r['c001_measure'],'value':r['c002_value'],
                   'reported_plus_minus':r['c003_reported'],'uncertainty_type':NF,'unit':r['c004_unit'],
                   'dose_mg_kg':1,'interval_h':12,'concentration_basis':NF,'independent_animals':NF}
                export('rabbit_'+re.sub('[^a-z0-9]+','_',r['c001_measure'].lower()),[x],meta(t,species='rabbit',route='IV',record_level='parameter_summary'))
            change(t,'split_parameters','AUC 与 Cmax 分开保存，不生成浓度曲线；± 类型不猜测。')
            card.update(mathematical_fit_assessment='NO_SERIAL_PK_PROFILE',independent_animals=NF)
        elif tid=='T0006':
            for endpoint in sorted({r['c003_endpoint'] for r in rows}):
                rr=[{**location(t,r),'treatment_course_days':r['c001_treatment_course_days'],'group':r['c002_group'],
                     'endpoint':endpoint,'mean':r['c004_mean'],'sem':r['c005_sem'],'uncertainty_type':'SEM',
                     'unit':r['c006_unit'],'group_n':NF,'strain_allocation':NF,'cohort_id':NF,
                     'pmb_loading_dose_mg_kg':2.5 if r['c002_group']=='PMB' else None,
                     'pmb_maintenance_dose_mg_kg':1.5 if r['c002_group']=='PMB' else None,
                     'pmb_interval_h':12 if r['c002_group']=='PMB' else None} for r in rows if r['c003_endpoint']==endpoint]
                export('rabbit_'+endpoint,rr,meta(t,species='rabbit',route='IV',record_level='group_summary',pathogen='K. pneumoniae',mic_mg_L=0.5))
            change(t,'split_endpoint_and_preserve_controls','区分细菌负荷、肺重和出血评分；重复对照均值不删除、不当新队列。')
            card.update(mathematical_fit_assessment='NO_MATCHED_REGIMEN_EXPOSURE',independent_animals=NF)
        elif tid=='T0007':
            rr=[{**location(t,r),'measure':r['c001_measure'],'value':r['c002_value'],'unit':r['c003_unit'],'comparator':r['c004_comparator']} for r in rows]
            export('neonatal_rabbit_relative_endpoint',rr,meta(t,species='rabbit',route='intratracheal',pathogen='E. coli',record_level='relative_summary'))
            card.update(mathematical_fit_assessment='CONTEXT_ONLY_DIFFERENT_PATHOGEN_AND_COMBINATION',independent_animals=NF)
        elif tid in {'T0008','T0009','T0010','T0011'}:
            export('rabbit_context_'+tid,copy.deepcopy(rows),meta(t,species='rabbit',record_level='context_only'))
            card.update(mathematical_fit_assessment='CONTEXT_ONLY_NO_NUMERIC_PK',independent_animals=NF)
        elif tid in {'T0012','T0013'}:
            strain,mic=('BAA1705',0.5) if tid=='T0012' else ('KP619',64.0)
            events,observations=normalize_static_time_kill(t)
            for x in events+observations:
                x.update(strain=strain,mic_mg_L=mic)
            for x in observations:
                if x['status']!='QUANTIFIED':
                    missing_records.append({**location(t,x),'status':x['status'],'raw':x['Y_raw'],
                                            'CENS':x['CENS'],'fit_ready':False,
                                            'action':'PRESERVE_RAW_AND_FLAG; EXCLUDE_FROM_EXACT_OBSERVATIONS; HUMAN_REVIEW_REQUIRED'})
            md=meta(t,species='in_vitro',pathogen='K. pneumoniae',strain=strain,mic_mg_L=mic,record_level='longitudinal_experiment_group',concentration_basis='nominal_not_measured_free')
            export('kp_'+strain+'_exposure_events',events,md)
            export('kp_'+strain+'_time_kill',observations,md)
            change(t,'separate_events_and_join_exposure','按来源表+ID匹配唯一浓度事件；点号在非适用字段保留，不填0；1e-8原值保留。')
            change(t,'classify_missing_observations','观测Y中的点号保留为Y_raw；数值字段null，状态MISSING_OBSERVATION；CENS不变，隔离待审。')
            card.update(exposure_events=len(events),observations=len(observations),censored_observations=sum(r['CENS']==1 for r in observations),
                        status_counts=dict(collections.Counter(r['status'] for r in observations)),
                        missing_observations=sum(r['status'].startswith('MISSING_') for r in observations),
                        experiment_groups=len(events),independent_replicates=NF,
                        observation_times=sorted({r['time_h'] for r in observations}),
                        mathematical_fit_assessment='TIME_KILL_MODEL_CANDIDATE_AFTER_REPLICATE_CENSOR_AND_EXPOSURE_REVIEW',
                        index_selection_status='NO_ELIGIBLE_ANIMAL_INDEX_DATASET')
        elif tid=='T0014':
            rr=[{**location(t,r),'mic_bin_as_reported':r['c001_mic_mg_l'],'percentage':r['c002_percentage'],'reported_isolate_count':652} for r in rows]
            total=math.fsum(r['percentage'] for r in rr)
            export('kp_MIC_population_distribution',rr,meta(t,pathogen='K. pneumoniae',record_level='population_frequency',use='DOWNSTREAM_ONLY',renormalized=False))
            card.update(percentage_total=total,percentage_shortfall=100-total,mathematical_fit_assessment='HOLD_FOR_LATER_MIC_DISTRIBUTION_REVIEW',independent_animals='NOT_APPLICABLE')
        elif tid in terminal_config:
            pathogen,strain,mic,route,daily=terminal_config[tid]
            rr=[]
            for r in rows:
                raw_group=r['group_label']
                group_map={'Pre-treatment':'Pre-treatment','Vehicle':'Vehicle','Veichle':'Vehicle',
                           f'Polymyxin B ({int(daily)}mg/kg/d)':'PMB'}
                assert raw_group in group_map, f'Unexpected group: {raw_group}'
                group=group_map[raw_group]
                if raw_group != group:
                    change(t,'normalize_group_label',f'{raw_group} -> {group}; 原始标签保留在group_label。',r['record_id'])
                x={**copy.deepcopy(r),'unit_id':r['unit_id_candidate'], 'identity_status':'SOURCE_DEFINED_TERMINAL_POINT_PENDING_REVIEW',
                   'group':group,'pathogen':pathogen,'strain':strain,'mic_mg_L':mic,'response':r['response_raw'] if r['status']=='QUANTIFIED' else None,
                   'response_time_h':0 if group=='Pre-treatment' else 24,'response_unit':'log10 CFU/lung',
                   'route':route if group=='PMB' else 'NOT_APPLICABLE',
                   'daily_dose_mg_kg':daily if group=='PMB' else None,'dose_basis':'free_base' if group=='PMB' else 'NOT_APPLICABLE',
                   'interval_h':8 if group=='PMB' else None}
                rr.append(x)
                if r['status']!='QUANTIFIED': missing_records.append({**location(t,r),'status':r['status'],'raw':r['response_raw'],'action':'EMPTY_SLOT_IS_NOT_AN_ANIMAL'})
            md=meta(t,species='mouse',pathogen=pathogen,strain=strain,mic_mg_L=mic,route=route,matrix='lung',
                    analyte='polymyxin_b',concentration_basis=NF,formulation=NF,parameter_definition=NF,
                    record_level='terminal_individual',response_unit='log10 CFU/lung',endpoint_definition='Terminal lung bacterial burden; baseline 0h, vehicle and PMB 24h')
            name='terminal_'+strain.replace('-','_')
            export(name,rr,md)
            # Native index eligibility only: no fabricated exposure columns or fitted indices.
            candidate=OUT/'qc_inputs'/f'{name}.json'
            write_json(candidate,{'records':[r for r in rr if r['status']=='QUANTIFIED']})
            attachments.append({'id':name,'path':str(candidate),'sha256':sha256(candidate)})
            specs.append({'id':name,'kind':'index','data_attachment':name,'metadata':md,
                          'analysis_options':{'mode':'compare_indices','id_column':'unit_id','response_column':'response','estimate_hill':False,'direction':'decreasing','reference_mode':'baseline'}})
            card.update(status_counts=dict(collections.Counter(r['status'] for r in rr)),
                        observed_terminal_points=sum(r['status']=='QUANTIFIED' for r in rr),
                        points_per_arm=dict(collections.Counter(r['group'] for r in rr if r['status']=='QUANTIFIED')),
                        primary_pathogen=pathogen=='K. pneumoniae',mathematical_fit_assessment='ENDPOINT_DESCRIPTIVE_ONLY_NO_MATCHED_EXPOSURE',
                        index_selection_status='NO_ELIGIBLE_ANIMAL_INDEX_DATASET')
            change(t,'terminal_long_table','一行一终末观测；0h基线和24h终点分开，空槽位不算动物；不计算未提供的暴露。')
        else:
            supplemental = normalize_supplemental(t)
            for d in supplemental:
                export(d['name'], d['records'], meta(t, **d['metadata']))
                for r in d['records']:
                    if r.get('status') == 'NOT_DETERMINED':
                        missing_records.append({**location(t, r), 'status': 'NOT_DETERMINED',
                            'raw': 'ND', 'action': 'PRESERVED_WITHOUT_IMPUTATION'})
            card.update(mathematical_fit_assessment='SUPPLEMENTAL_INPUT_REQUIRES_MATCHED_EXPOSURE_AND_REVIEW',
                        normalized_datasets=[d['name'] for d in supplemental], independent_animals=NF)
            change(t, 'normalize_supplemental', '保留来源字段；按研究/菌株拆分MIC、结合率、给药设计和药效汇总。ND不插补，不生成暴露。')
        cards.append(card)

    issue('CONCENTRATION_BASIS_UNDOCUMENTED',['T0001','T0002','T0003','T0005'],'BLOCK_MODEL','附件没有足够明确声明相关浓度/暴露为 total 或 free；不根据检测方式推断。','确认来源中的 total/free、分析物组成及盐/碱剂量基准。')
    issue('MOUSE_LONGITUDINAL_IDENTITY',['T0001','T0003'],'BLOCK_INDIVIDUAL_PK','Mouse 1–4 是表中列标签，不能证明跨时间为同一动物。','提供个体/时间映射与 serial、sparse 或 terminal 采样设计。')
    issue('ELF_REPLICATE_DISCREPANCY',['T0003'],'REVIEW','注释 n=3，早期行存在四个非空观测位置；空槽位与未采样必须分开。','核对图注、原始采样记录和实际每时间点动物数。')
    issue('ROUTE_IMPLEMENTATION_GAP',['T0001','T0003'],'BLOCK_CURRENT_PK_IMPLEMENTATION','当前 R PK 分支仅支持 IV；IP 及 SC 数据保留，但不能改成 IV。','先实现并审核匹配输入模型；IP 不能直接重标为 SC。')
    issue('PLASMA_ELF_NOT_PAIRED',['T0001','T0003'],'BLOCK_UNJUSTIFIED_COUPLING','小鼠 plasma 为5 mg/kg IP；ELF为40 mg/kg SC，不能直接视为配对同剂量资料。','明确系统/肺部连接模型与跨途径、剂量桥接依据。')
    issue('CENSOR_LIMITS_MISSING',['T0002','T0003','T0004','T0012'],'BLOCK_PRIMARY_CENSORED_LIKELIHOOD','BLQ及CENS标志保留，数值限值未明确；不能替换0或LLOQ/2。','提供各分析方法限值及删失定义；按基质/来源审核删失比例和时间分布。')
    issue('SUMMARY_NOT_INDIVIDUAL',['T0004','T0005','T0006'],'BLOCK_INDIVIDUAL_VARIANCE_INFERENCE','均值±SD/SEM不是个体曲线；兔PK±类型及多个汇总表的n未知。','提供n、误差定义、原始数据或合适的汇总似然。')
    issue('RABBIT_REGIMEN_MISMATCH',['T0005','T0006'],'BLOCK_PK_PD_JOIN','兔PK摘要1 mg/kg IV q12h；药效实验2.5 mg/kg负荷+1.5 mg/kg q12h。','不得直接配对；补同方案暴露或有依据的模型桥接。')
    issue('RABBIT_SERIAL_PK_MISSING',['T0005','T0007','T0008','T0009','T0010','T0011'],'BLOCK_THIRD_SPECIES_PK_FIT','保留了兔证据，但没有兔逐时间浓度曲线；AUC和Cmax不生成伪曲线。','兔暂作背景/有来源的约束候选，补可拟合PK数据后重新评估。')
    issue('REPEATED_CONTROL_SUMMARY',['T0006'],'REVIEW','7/14天部分对照均值重复，不能证明是独立对照队列。','确认队列分配与共享对照，避免双重计算。')
    issue('TIME_KILL_REPLICATION_EXPOSURE',['T0012','T0013'],'BLOCK_CONFIRMED_PD_PRECISION','每菌株6个浓度组不等于6个独立生物重复；暴露为nominal浓度事件。','补重复实验/批次ID、实际药物稳定性、free/total和删失限值。')
    for card in cards:
        if card.get('missing_observations',0):
            issue('TIME_KILL_MISSING_OBSERVATION',[card['table_id']],'REVIEW',
                  f"发现{card['missing_observations']}条缺失Y观测；保留原始值和CENS，未插补，已隔离。",
                  '核对原始实验记录及缺失原因；确认拟合时的排除/缺失处理方案。')
    issue('INDEX_DESIGN_INCOMPLETE',['T0012','T0013','T0015','T0016','T0017','T0018','T0019','T0020'],'BLOCK_INDEX_SELECTION','静态time-kill与单一PMB方案的终点不提供足够匹配暴露来区分三个index；不得预设fAUC/MIC获胜。','补同一终点对应的多方案暴露、菌株MIC、free定义/蛋白结合及暴露窗口；计划dose fractionation或有区分力设计。')
    if len(tables) > 20:
        issue('SUPPLEMENTAL_INDEX_INPUT_INCOMPLETE', [t['table_id'] for t in tables[20:]], 'BLOCK_INDEX_SELECTION',
              '新增菌株MIC、研究内fu与给药设计；S02 Table 3仅有每株3–4个定量汇总终点，缺同实验匹配暴露及动物关联，29方案表无逐方案药效。',
              '补同研究/实验PK观测及暴露桥接、完整dose-fractionation终点映射、动物聚类身份；不能借用S21 PK或benchmark暴露。')
    issue('MIC_FREQUENCY_TOTAL',['T0014'],'BLOCK_UNREVIEWED_CFR','报告百分比合计99.57%，缺0.43个百分点；未自动归一化或回推个体菌株数。','核对遗漏/分母/四舍五入，明确后续分布处理。')
    issue('SAMPLE_SIZE_PRECISION_MISSING',[t['table_id'] for t in tables],'NOT_CALCULABLE','没有匹配参数的个体间变异与预设CI宽度、置信度、assurance；不能计算唯一所需n。','选择目标参数和决策精度，补先导/个体参数或适用IIV；稀疏设计考虑模拟重估。')
    issue('HUMAN_TRANSLATION_NOT_ESTABLISHED',['T0001','T0002','T0003','T0005'],'BLOCK_HUMAN_VALIDITY_CLAIM','有3个物种的证据不等于3个可比PK物种点；目前仅大鼠提供明确serial IV plasma候选。','冻结分析物、参数定义、途径/基质、体重与外推方法；人体独立验证留到预测冻结后。')

    # Reconcile every source record; serum/lung and parameter splitting are intentional.
    expected={r['record_id'] for t in tables for r in t['records']}
    actual={r['record_id'] for item in normalized for r in read_json(item['json']['path'])['records']}
    assert expected==actual, {'unrepresented_source_records':sorted(expected-actual),'unexpected_records':sorted(actual-expected)}
    write_json(OUT/'table_assessments.json',{'tables':cards})
    write_json(OUT/'normalization_manifest.json',{'datasets':normalized,'source_records':len(expected),'normalized_records':sum(x['record_count'] for x in normalized),'all_source_records_represented':True})
    write_json(OUT/'missingness_and_quarantine.json',{'records':missing_records,'policy':'No imputation; quantified records with unresolved identities remain preserved but unfit for current model.'})
    write_json(OUT/'normalization_changes.json',{'changes':changes})
    write_json(OUT/'scientific_issues.json',{'issues':issues})
    # The existing data module accepts the B1 scientific context without its file registry.
    context_path=OUT/'qc_inputs/context_from_main.json'
    write_json(context_path,source['context'])
    evidence_copy=OUT/'qc_inputs/species_selection_evidence.snapshot.md'
    evidence_copy.parent.mkdir(parents=True,exist_ok=True)
    evidence_copy.write_bytes(EVIDENCE.read_bytes())
    plan={'schema_version':'1.0','ruleset_version':'2026-09-16.1','evidence_attachment':'evidence','evidence_sha256':sha256(evidence_copy),
          'study_plan':{'purpose':'human_translation','human_pk_available':False,
                        'target':{'drug':'polymyxin_b','analyte':'polymyxin_b','route':NF,'matrix':NF,'concentration_basis':NF,
                                  'parameter_definition':NF,'human_population':NF,'decision_quantity':'human plasma/ELF exposure and K. pneumoniae response'},
                        'scaling':{'mode':NF}},'datasets':specs,'precision_plans':[]}
    plan_path=OUT/'preparation.plan.json'
    write_json(plan_path,plan)
    attachments += [{'id':'context','path':str(context_path),'sha256':sha256(context_path)},
                    {'id':'evidence','path':str(evidence_copy),'sha256':sha256(evidence_copy)},
                    {'id':'plan','path':str(plan_path),'sha256':sha256(plan_path)}]
    request={'schema_version':'1.0','request_id':REQUEST_ID,'reference_policy':{'drug':'polymyxin_b','same_drug_only':True},
             'attachments':attachments,'context_attachment':'context',
             'steps':[{'id':'data','module':'data_preparation','input':{'preparation_attachment':'plan'},'options':{}}]}
    validate_request(request)
    write_json(OUT/'request.json',request)
    run_result=run_pipeline(request,OUT/'state',OUT)
    if run_result['status']=='FAILED':
        raise PipelineError('NATIVE_QC_EXECUTION_FAILED', f'Scientific QC failed; inspect state/runs/{REQUEST_ID}/output.json: {run_result.get("errors")}')
    step=read_json(OUT/'state/runs'/REQUEST_ID/'steps/data/output.json')
    if step['status']=='FAILED' or not step.get('result'):
        raise RuntimeError(f'Scientific QC program failed: {step.get("errors")}')
    result=step['result']
    read_failures=[i for i in result['issues'] if i['code']=='DATASET_READ_FAILED']
    if read_failures:
        raise PipelineError('NATIVE_DATASET_READ_FAILED', json.dumps(read_failures,ensure_ascii=False))
    assert not result['released_datasets']
    review_path=OUT/'human_review_submission.template.json'
    write_json(review_path,read_json(OUT/'state/runs'/REQUEST_ID/'steps/data/review_submission.template.json'))
    gate={'schema_version':'1.0','status':'PENDING_HUMAN_REVIEW','model_execution_allowed':False,'released_datasets':[],
          'approve_model_release_allowed':any(g['readiness']=='READY_FOR_HUMAN_REVIEW' for g in result['datasets']),
          'native_review_submission_ready':True,
          'request_id':REQUEST_ID,'step_id':'data','native_qc_status':step['status'],'assessment_sha256':result['assessment_sha256'],
          'normalization_fingerprint':digest({'datasets':normalized,'issues':issues}),
          'human_decision':{'reviewer':'','decision':'PENDING','confirm_rules':False,'rationale':''},
          'review_submission':ref(review_path),'scientific_issues':ref(OUT/'scientific_issues.json'),
          'note':'Human may review normalization now. Native ERROR issues require corrected metadata/data and reassessment before model release; APPROVE cannot waive them.'}
    write_json(OUT/'human_review_gate.json',gate)
    main_out={'schema_version':'1.0','module':'data_preparation','status':'WAITING_FOR_HUMAN_REVIEW',
              'cleaning_complete':True,
              'upstream_main':ref(B1),'source_preparation_status':source['status'],'native_qc_status':step['status'],
              'normalization_manifest':ref(OUT/'normalization_manifest.json'),'table_assessments':ref(OUT/'table_assessments.json'),
              'scientific_issues':ref(OUT/'scientific_issues.json'),'missingness':ref(OUT/'missingness_and_quarantine.json'),
              'native_data_report':ref(OUT/'state/runs'/REQUEST_ID/'steps/data/data_report.json'),
              'human_review_gate':ref(OUT/'human_review_gate.json'),'sample_size_status':result['sample_size_status'],
              'animal_index_status':'NO_ELIGIBLE_ANIMAL_INDEX_DATASET','human_translation_status':'NOT_ESTABLISHED',
              'fit_ready':False,'released_datasets':[],'pk_longitudinal':'NOT_RUN','pkpd_index':'NOT_RUN',
              'validation':'NOT_RUN','PTA_CFR':'NOT_RUN'}
    write_json(OUT/'main.json',main_out)
    return {'status':'B2_COMPLETE_PENDING_HUMAN_REVIEW','source_tables':len(tables),'normalized_datasets':len(normalized),
            'source_records':len(expected),'native_qc_status':step['status'],'native_issues':len(result['issues']),
            'native_groups':[{k:g[k] for k in ('id','readiness','summary')} for g in result['datasets']],
            'sample_size_status':result['sample_size_status'],'output':str(OUT/'main.json')}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True,help='New, non-existing output directory')
    parser.add_argument('--source-preparation',type=Path,default=SOURCE)
    parser.add_argument('--upstream-main',type=Path,default=B1)
    parser.add_argument('--request-id',default='pmb_b2_review_'+datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S'))
    args=parser.parse_args()
    OUT=args.out.resolve(); SOURCE=args.source_preparation.resolve(); B1=args.upstream_main.resolve()
    NORMAL=OUT/'normalized'; REQUEST_ID=args.request_id
    OUT.mkdir(parents=True,exist_ok=False)
    audit=OUT/'audit'; audit.mkdir()
    for source_code in [Path(__file__),ROOT/'research_pipeline/research_pipeline/time_kill_preparation.py',
                        ROOT/'research_pipeline/research_pipeline/supplemental_preparation.py']:
        (audit/source_code.name).write_bytes(source_code.read_bytes())
    record={'started_at':datetime.now(timezone.utc).isoformat(),'pid':os.getpid(),'script':str(Path(__file__).resolve()),
            'script_sha256':sha256(__file__),'command':[sys.executable,*sys.orig_argv[1:]],
            'source_preparation':ref(SOURCE/'output.json'),
            'time_kill_processor_sha256':sha256(ROOT/'research_pipeline/research_pipeline/time_kill_preparation.py'),
            'upstream_main':ref(B1),'source_splitter_sha256':sha256(ROOT/'research_pipeline/research_pipeline/source_preparation.py'),
            'native_qc_sha256':sha256(ROOT/'research_pipeline/research_pipeline/data_preparation.py'),
            'rules_sha256':sha256(ROOT/'research_pipeline/research_pipeline/data_rules.py'),'model_calls':0}
    write_json(OUT/'execution.json',record)
    try:
        result=main();record.update(result)
    except Exception as exc:
        record.update(status='STOPPED_ON_ERROR',error={'type':type(exc).__name__,'code':getattr(exc,'code','ADAPTER_ERROR'),'message':str(exc)})
        write_json(OUT/'execution.json',record)
        raise
    finally:
        record['finished_at']=datetime.now(timezone.utc).isoformat()
        write_json(OUT/'execution.json',record)
    print(json.dumps(record,ensure_ascii=False,indent=2))
