"""Lossless preparation proposals with source-bound human release decisions."""
import copy
import hashlib
import io
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from uuid import uuid4
from jsonschema import Draft202012Validator
from .common import PipelineError, read_json, write_json, sha256, utcnow, require_id
from .attachments import store_upload
from .references import canonical_drug
from .tables import load_table
from .dataset_metadata import metadata_sidecar
from .data_rules import RULESET_VERSION, RULES, known, number, precision_assessment, assess_study

SCHEMAS=Path(__file__).parent/'schemas'
IDENTITY=('drug','analyte','species','route','matrix','concentration_basis','formulation','parameter_definition',
          'time_unit','concentration_unit','dose_unit','record_level')
TIME_FACTORS={'h':1,'min':1/60,'s':1/3600}
CONCENTRATION_FACTORS={'mg/L':1,'ug/mL':1,'µg/mL':1,'μg/mL':1,'ng/mL':.001,'ug/L':.001}


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode()).hexdigest()


def prepare_dataset(spec, attachment, directory, issue):
    records=load_table(attachment['path'],spec.get('table'))
    write_json(directory/(spec['id']+'_raw.json'),{'records':records})
    partitions=defaultdict(list); changes=[]
    for i,original in enumerate(records):
        row=copy.deepcopy(original)
        for key,value in list(row.items()):
            if isinstance(value,str) and value!=value.strip():
                row[key]=value.strip(); changes.append({'row':i+1,'column':key,'before':value,'after':row[key],'action':'trim_whitespace'})
        identity={k:row.get(k,spec['metadata'].get(k,'NOT_FOUND')) for k in IDENTITY}
        identity={k:v if isinstance(v,str) and known(v) else 'NOT_FOUND' for k,v in identity.items()}
        identity['drug']=canonical_drug(identity['drug']) if known(identity['drug']) else 'NOT_FOUND'
        row['_source']={'dataset':spec['id'],'row':i+1,'source_sha256':attachment['sha256'],
                        'cell':original.get('source_cell'),'sheet':original.get('source_sheet'),
                        'original_file_id':original.get('source_file_id'),
                        'original_file_sha256':original.get('source_sha256'),
                        'original_row':original.get('source_row'), 'field_cells':original.get('source_cells')}
        partitions[tuple(str(identity[k]) for k in IDENTITY)].append(row)
    groups=[]
    for count,(key,rows) in enumerate(sorted(partitions.items()),1):
        identifier=spec['id']+'__'+str(count).zfill(3)
        require_id(identifier)
        meta={**spec['metadata'],**dict(zip(IDENTITY,key))}; options=copy.deepcopy(spec['analysis_options'])
        kind=spec['kind']; cleaned=[]; quarantine=[]; seen={}
        def flag(code,severity,message,row=None):
            issue(code,severity,identifier,message,row['_source'] if row else None)
        for field in IDENTITY[:6]:
            if not known(meta.get(field)): flag('IDENTITY_MISSING','ERROR','分组身份字段缺失：'+field)
        if len(partitions)>1: flag('DATA_SPLIT','REVIEW','已按药物/分析物/物种/途径/基质/暴露定义拆分，需确认分组含义。')
        if any(not known(meta.get(k)) for k in ('formulation','parameter_definition')): flag('COMPARABILITY_METADATA_MISSING','REVIEW','制剂或参数定义不完整；不得自动认为跨研究可比。')
        idcol='subject_id' if kind=='pk' else options.get('id_column','unit_id')
        response=options.get('response_column','response')
        indices=options.get('index_columns',[])
        required=[idcol,'time_h','concentration_mg_L'] if kind=='pk' else [idcol,response]+indices
        numeric={'time_h','concentration_mg_L','dose_mg','dose_mg_kg','dose_time_h','duration_h','response_time_h','weight_kg'}
        if kind=='index': numeric.update(indices+[response])
        if kind=='index' and (len(indices)<2 or len(set(indices))!=len(indices)):
            flag('INDEX_CANDIDATES_MISSING','ERROR','至少提供两个不同候选 index。')
        time_unit=meta.get('time_unit','h' if kind=='index' else None)
        concentration_unit=meta.get('concentration_unit')
        tf=TIME_FACTORS.get(time_unit); cf=CONCENTRATION_FACTORS.get(concentration_unit)
        if kind=='pk' and (tf is None or cf is None): flag('UNIT_UNSUPPORTED','ERROR','缺失或不支持的时间/浓度单位，不能自动猜测转换。')
        if kind=='pk' and meta.get('dose_unit') not in {'mg','mg/kg'}: flag('DOSE_UNIT_UNSUPPORTED','ERROR','当前 PK 接口需要明确 mg 或 mg/kg 剂量。')
        if kind=='pk' and meta.get('route')!='IV': flag('ROUTE_MODEL_MISMATCH','ERROR','当前 PK 实现仅支持 IV；其他途径需相应模型后再放行。')
        for row in rows:
            invalid=False
            status=row.get('status','QUANTIFIED')
            if status!='QUANTIFIED':
                if status in {'BLQ','MISSING_CANNULA_BLOCKAGE','NOT_SAMPLED'}:
                    quarantine.append({'record':row,'reason':status})
                    flag('QUARANTINE_PROPOSED','REVIEW','建议隔离 '+status+' 记录；BLQ 不补为 0/LLOQ/2，须人工确认排除影响。',row)
                else:
                    quarantine.append({'record':row,'reason':'UNKNOWN_STATUS'}); flag('UNKNOWN_STATUS','ERROR','无法识别的观测状态。',row)
                continue
            if row.get('blq',False) not in (False,'FALSE','false','0',0):
                flag('BLQ_POLICY_REQUIRED','ERROR','请显式标记 status=BLQ 并审阅处理。',row); invalid=True
            for field in required:
                if not known(row.get(field)):
                    flag('REQUIRED_VALUE_MISSING','ERROR','必需值缺失：'+field,row); invalid=True
            for field in numeric.intersection(row):
                before=row[field]
                try:
                    value=number(before)
                    if field in {'concentration_mg_L','dose_mg','dose_mg_kg','duration_h','weight_kg'} and value<0:
                        raise ValueError('negative physical value')
                    if field in {'dose_mg','dose_mg_kg','weight_kg'} and value==0: raise ValueError('zero dose or weight')
                    if field in indices and value<0: raise ValueError('negative index')
                    factor=(tf or 1) if kind=='pk' and field in {'time_h','dose_time_h','duration_h'} else (cf or 1) if kind=='pk' and field=='concentration_mg_L' else 1
                    row[field]=value*factor
                    if not isinstance(before,(int,float)) or factor!=1:
                        changes.append({'row':row['_source']['row'],'dataset':identifier,'column':field,'before':before,'after':row[field],
                                        'action':'numeric_parse' if factor==1 else 'declared_unit_conversion','factor':factor})
                except (ValueError,TypeError):
                    flag('INVALID_NUMBER','ERROR','无效或不合理数值：'+field,row); invalid=True
            if kind=='pk' and row.get('concentration_mg_L')==0 and options.get('error_model','lognormal')=='lognormal':
                flag('ZERO_LOGNORMAL','ERROR','对数误差模型不能使用零浓度；需核实 BLQ 或模型。',row); invalid=True
            if invalid:
                quarantine.append({'record':row,'reason':'UNRESOLVED_ERROR'}); continue
            if kind=='pk' and tf is not None and cf is not None:
                row['_source']['units']={'time_unit':time_unit,'concentration_unit':concentration_unit}
                if 'time_unit' in row: row['time_unit']='h'
                if 'concentration_unit' in row: row['concentration_unit']='mg/L'
            observation=(str(row[idcol]),row.get('time_h')) if kind=='pk' else (str(row[idcol]),)
            content={k:v for k,v in row.items() if k not in {'_source','source_row','source_cell','source_raw_value'}}
            if observation in seen:
                if content==seen[observation]:
                    quarantine.append({'record':row,'reason':'EXACT_DUPLICATE'})
                    flag('DUPLICATE_REMOVAL_PROPOSED','REVIEW','完全重复行建议去重，原始行保留。',row)
                else:
                    cleaned.append(row); flag('CONFLICTING_DUPLICATE','ERROR','同一独立单位/时间出现冲突值或重复终点，不能自动平均。',row)
            else:
                seen[observation]=content; cleaned.append(row)
        if kind=='pk' and tf is not None and cf is not None:
            meta['time_unit']='h'; meta['concentration_unit']='mg/L'
            # Common schedules use the same explicitly declared source time unit.
            for dose in options.get('doses',[]):
                for field in ('time_h','duration_h'):
                    if field in dose: dose[field]=number(dose[field]) * tf
        cleaned.sort(key=lambda r:(str(r.get(idcol,'')),r.get('time_h',0)))
        by_id=defaultdict(list)
        for row in cleaned: by_id[str(row[idcol])].append(row)
        if not cleaned: flag('NO_USABLE_DATA','ERROR','没有可用于模型的观测。')
        if kind=='pk':
            if meta.get('record_level')!='individual': flag('INDEPENDENCE_UNVERIFIED','ERROR','当前 PK 分支需要个体数据；组均值不能作为独立动物。')
            if meta.get('sampling_design') in {'sparse','terminal'}:
                flag('SAMPLING_MODEL_REVIEW','REVIEW','稀疏/终末采样不能把时间点当作每只动物的完整曲线。')
                if options.get('mode','individual')=='individual': flag('INDIVIDUAL_PK_UNSUPPORTED','ERROR','此采样设计不支持逐动物完整 PK 拟合。')
            p=2 if options.get('compartments',1)==1 else 4
            mode=options.get('mode','individual')
            if mode=='individual' and any(len(v)<=p+1 for v in by_id.values()): flag('PK_SUPPORT_INSUFFICIENT','ERROR','至少一个个体不满足当前模型残差自由度要求；这是计算条件，不是可靠性动物数标准。')
            if mode.startswith('population') and (len(by_id)<3 or any(len(v)<3 for v in by_id.values())): flag('PK_SUPPORT_INSUFFICIENT','ERROR','不满足当前群体 PK 实现的最低可运行结构，需重新审阅采样和模型。')
            if mode=='individual' and not options.get('doses'): flag('DOSE_MISSING','ERROR','缺少明确剂量、给药时点与持续时间。')
            if mode=='individual' and options.get('doses'):
                dosekey='dose_mg_kg' if meta.get('dose_unit')=='mg/kg' else 'dose_mg'
                for dose in options['doses']:
                    if not all(k in dose for k in ('time_h','duration_h',dosekey)):
                        flag('DOSE_UNIT_MISMATCH','ERROR','共同给药表缺少与声明单位匹配的剂量或时间字段。')
                    else:
                        try:
                            number(dose[dosekey],True)
                            if number(dose['duration_h'])<0: raise ValueError()
                        except (ValueError,TypeError): flag('DOSE_INVALID','ERROR','剂量必须为正，持续时间不得为负。')
            if mode.startswith('population'):
                dose='dose_mg_kg' if mode=='population_infusion_per_kg' else 'dose_mg'
                if any(any(not known(r.get(k)) for k in (dose,'dose_time_h','duration_h')) for r in cleaned): flag('DOSE_MISSING','ERROR','群体 PK 观测缺少给药信息。')
            flag('PK_IDENTIFIABILITY_PENDING','REVIEW','采样覆盖、分布/消除相、参数可辨识性需拟合与模拟进一步判断。')
        else:
            p=4 if options.get('estimate_hill',False) else 3
            if len(cleaned)<=p+2 or any(len({r[x] for r in cleaned})<p+1 for x in indices):
                flag('EMAX_SUPPORT_INSUFFICIENT','ERROR','不满足当前 Emax/Hill 的观测数或独立暴露水平条件。')
            if cleaned and len({r[response] for r in cleaned})<2: flag('RESPONSE_CONSTANT','ERROR','响应无变化，不能识别 Emax/EC50。')
            groupcol=options.get('group_column')
            if groupcol and (any(not known(r.get(groupcol)) for r in cleaned) or len({r.get(groupcol) for r in cleaned})<3): flag('CV_GROUPS_INSUFFICIENT','ERROR','当前整组留出 CV 需要至少三个明确群组。')
            for field in ('response_unit','endpoint_definition'):
                if not known(meta.get(field)): flag('ENDPOINT_DEFINITION_MISSING','ERROR','缺少 '+field)
            definitions=meta.get('index_definitions',{})
            windows=[]; bases=[]
            for name in indices:
                definition=definitions.get(name,{})
                if not known(definition.get('unit')) or definition.get('concentration_basis') not in {'free','total'} or not isinstance(definition.get('window_h'),list) or len(definition['window_h'])!=2:
                    flag('INDEX_DEFINITION_MISSING','ERROR','缺少完整候选定义：'+name); continue
                windows.append(definition['window_h']); bases.append(definition['concentration_basis'])
                try:
                    start,end=[number(v) for v in definition['window_h']]
                    if start>=end: raise ValueError()
                except (ValueError,TypeError): flag('INDEX_WINDOW_INVALID','ERROR','暴露窗口必须为两个递增的有限时点。')
                if definition['unit']=='%' and any(r[name]>100 for r in cleaned): flag('PERCENT_RANGE','ERROR','百分数应在 0–100；不自动把比例改为百分数。')
            if len({digest(w) for w in windows})>1 or len(set(bases))>1: flag('INDEX_COMPARABILITY','ERROR','候选指标的窗口和 total/free 定义不一致。')
            if cleaned and 'response_time_h' in cleaned[0] and len({r.get('response_time_h') for r in cleaned})>1: flag('ENDPOINT_TIME_MISMATCH','ERROR','终点评估时间不同。')
            flag('INDEX_RELIABILITY_PENDING','REVIEW','暴露覆盖、指标相关性、独立性及拟合外预测仍需审阅；可运行不等于可靠。')
        # IDs are explicit; technical rows do not increase independent animal count.
        independent=sorted({str(r.get('study_id',meta.get('study_id','')))+'::'+str(r[idcol]) for r in cleaned})
        groups.append({'id':identifier,'source_dataset':spec['id'],'kind':kind,'metadata':meta,'analysis_options':options,
                       'records':cleaned,'quarantine':quarantine,'independent_ids':independent,
                       'summary':{'input_rows':len(rows),'candidate_rows':len(cleaned),'quarantined_rows':len(quarantine),
                                  'independent_units':len(independent),'observations_per_unit':{k:len(v) for k,v in by_id.items()}},
                       'readiness':'PENDING'})
    return groups,changes


def run_preparation(step, attachments, directory, context_attachment=None):
    source=step['input']; config_attachment=attachments[source['preparation_attachment']]
    config=read_json(config_attachment['path'])
    Draft202012Validator(read_json(SCHEMAS/'data-preparation.schema.json')).validate(config)
    if config['ruleset_version']!=RULESET_VERSION: raise PipelineError('RULESET_VERSION','Unsupported rules version.')
    evidence=attachments[config['evidence_attachment']]
    if sha256(evidence['path'])!=config['evidence_sha256']: raise PipelineError('EVIDENCE_CHANGED','Source markdown does not match the proposed rule source hash.')
    ids=[d['id'] for d in config['datasets']]
    if len(set(ids))!=len(ids): raise PipelineError('DUPLICATE_DATASET','Dataset IDs must be unique.')
    issues=[]; groups=[]; changes=[]
    def issue(code,severity,dataset,message,source=None):
        issues.append({'id':'issue_'+str(len(issues)+1).zfill(4),'code':code,'severity':severity,'dataset':dataset,'message':message,'source':source})
    for spec in config['datasets']:
        attachment=attachments[spec['data_attachment']]
        try:
            part,log=prepare_dataset(spec,attachment,directory,issue); groups.extend(part); changes.extend(log)
        except (PipelineError,ValueError,KeyError,TypeError) as exc:
            issue('DATASET_READ_FAILED','ERROR',spec['id'],str(exc))
    for g in groups:
        g['readiness']='BLOCKED' if any(i['severity']=='ERROR' and i['dataset']==g['id'] for i in issues) else 'READY_FOR_HUMAN_REVIEW'
    precision=[precision_assessment(p,attachments,groups) for p in config.get('precision_plans',[])]
    study=assess_study(config['study_plan'],groups,precision,issue)
    used={config['evidence_attachment']:evidence['sha256'],source['preparation_attachment']:config_attachment['sha256']}
    if context_attachment: used[context_attachment]=attachments[context_attachment]['sha256']
    for d in config['datasets']: used[d['data_attachment']]=attachments[d['data_attachment']]['sha256']
    for p in config.get('precision_plans',[]):
        aid=p.get('source',{}).get('attachment')
        if aid in attachments: used[aid]=attachments[aid]['sha256']
    result={'ruleset_version':RULESET_VERSION,'rule_status':'PROPOSED_PENDING_HUMAN_CONFIRMATION','rules':RULES,
            'source_evidence':{'attachment':config['evidence_attachment'],'sha256':evidence['sha256']},
            'datasets':groups,'issues':issues,'change_log':changes,'precision_assessments':precision,'study_assessment':study,
            'sample_size_status':'NOT_CALCULABLE' if not precision else 'INCOMPLETE' if any(p['status']!='CONDITIONAL_PLAN' for p in precision) else 'CONDITIONAL_PLANS_ONLY',
            'source_hashes':used,'processor_sha256':{'preparation':sha256(__file__),'rules':sha256(Path(__file__).with_name('data_rules.py')),
                                                   'table_reader':sha256(Path(__file__).with_name('tables.py')),
                                                   'plan_schema':sha256(SCHEMAS/'data-preparation.schema.json')},
            'release_scope':'Exploratory fitting only. No release establishes adequate animal numbers or validated human prediction.'}
    result['assessment_sha256']=digest(result)
    # Human review is separate from assessment hashing, so an identical rerun can consume it.
    review=None
    if source.get('review_attachment'):
        review=read_json(attachments[source['review_attachment']]['path'])
        check_review(review,result)
    result['review']=review
    result['released_datasets']=review['selected_datasets'] if review and review['decision']=='APPROVE' else []
    if result['released_datasets']: result['rule_status']='CONFIRMED_FOR_THIS_ASSESSMENT'
    for g in groups:
        candidate = write_json(directory/(g['id']+'_candidate.json'),{'records':g['records'],'metadata':g['metadata'],'analysis_options':g['analysis_options']})
        metadata_sidecar(candidate, g['id'], g['metadata'], summary=g['summary'],
            role='pk_observations' if g['kind']=='pk' else 'exposure_response',
            sources=[{'attachment': key, 'sha256': value} for key, value in used.items()])
        write_json(directory/(g['id']+'_quarantine.json'),{'records':g['quarantine']})
    write_json(directory/'data_report.json',result)
    status='SUCCEEDED' if result['released_datasets'] else 'WAITING_FOR_REVIEW'
    if review and review['decision'] in {'REQUEST_CHANGES','REJECT'}: status='BLOCKED'
    if not groups or all(g['readiness']=='BLOCKED' for g in groups): status='BLOCKED'
    return status,result


def check_review(review,result):
    payload={k:v for k,v in result.items() if k not in {'assessment_sha256','review','released_datasets'}}
    payload['rule_status']='PROPOSED_PENDING_HUMAN_CONFIRMATION'
    if digest(payload)!=result['assessment_sha256']:
        raise PipelineError('ASSESSMENT_CHANGED','Assessment content no longer matches its fingerprint.')
    Draft202012Validator(read_json(SCHEMAS/'data-review.schema.json')).validate(review)
    if review['assessment_sha256']!=result['assessment_sha256']: raise PipelineError('STALE_REVIEW','Data, rules, plan, or processor changed; a new human review is required.')
    if review['decision']!='APPROVE': return
    if not review['confirm_rules'] or not known(review['reviewer']) or not known(review['rationale']):
        raise PipelineError('HUMAN_CONFIRMATION_REQUIRED','Explicit human rule confirmation, name and rationale required.')
    if review['scope']!='exploratory_fit_only': raise PipelineError('REVIEW_SCOPE','This release cannot certify human extrapolation or sample-size adequacy.')
    groups={g['id']:g for g in result['datasets']}
    selected=set(review['selected_datasets'])
    if not selected or not selected.issubset(groups): raise PipelineError('REVIEW_DATASETS','Select existing datasets explicitly.')
    if any(groups[x]['readiness']=='BLOCKED' for x in selected): raise PipelineError('UNRESOLVED_DATA_ERRORS','Correct blocking data errors before approval; no override.')
    needed={i['id'] for i in result['issues'] if i['severity']=='REVIEW' and (i['dataset'] is None or i['dataset'] in selected)}
    if not needed.issubset(review['acknowledged_issues']): raise PipelineError('UNACKNOWLEDGED_ISSUES','Human must acknowledge each applicable data/design limitation.')


def submit_review(state,submission):
    # A submitted decision is a human attestation, not automatic evidence of identity.
    if not isinstance(submission,dict) or not {'request_id','step_id'}.issubset(submission):
        raise PipelineError('REVIEW_TARGET','Supply request_id and step_id.')
    request_id=require_id(submission['request_id']); step_id=require_id(submission['step_id'])
    path=Path(state)/'runs'/request_id/'steps'/step_id/'output.json'
    if not path.is_file(): raise PipelineError('REVIEW_TARGET','Preparation run/step not found.')
    output=read_json(path)
    if output.get('module')!='data_preparation' or not output.get('result'): raise PipelineError('REVIEW_TARGET','Target must be a completed data preparation assessment.')
    review={k:v for k,v in submission.items() if k not in {'request_id','step_id'}}
    check_review(review,output['result'])
    identifier='review_'+uuid4().hex
    review.update(review_id=identifier,reviewed_at=utcnow(),source_run=request_id,source_step=step_id,
                  identity_verification='Self-declared reviewer; local API authentication is not an institutional signature.')
    write_json(Path(state)/'reviews'/identifier/'decision.json',review)
    upload=store_upload(state,io.BytesIO(json.dumps(review,ensure_ascii=False).encode()),'human_review.json')
    return {'status':'RECORDED','review':review,'attachment':upload,
            'next':'Use this upload_id as review_attachment in an otherwise identical preparation request with a new request_id. Original run is preserved.'}


def review_template(request_id,step_id,result):
    return {'request_id':request_id,'step_id':step_id,'schema_version':'1.0',
            'assessment_sha256':result['assessment_sha256'],'decision':'PENDING','reviewer':'',
            'confirm_rules':False,'scope':'exploratory_fit_only','selected_datasets':[],
            'acknowledged_issues':[],'rationale':''}


def resolve_prepared(output,dataset,module):
    if output.get('module')!='data_preparation' or output.get('status')!='SUCCEEDED':
        raise PipelineError('DATA_REVIEW_PENDING','Data block has not released a dataset.')
    result=output['result']; check_review(result['review'],result)
    if dataset not in result['released_datasets']: raise PipelineError('DATASET_NOT_RELEASED','Selected dataset was not approved for modeling.')
    group=next(g for g in result['datasets'] if g['id']==dataset)
    expected='pk' if module=='pk_longitudinal' else 'index'
    if group['kind']!=expected: raise PipelineError('DATASET_MODULE_MISMATCH','Dataset type does not match downstream module.')
    return group
