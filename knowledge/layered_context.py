"""Offline three-layer ContextBuilder adapter. No production imports, writes or model calls."""
import sys
sys.dont_write_bytecode=True
from pathlib import Path
import hashlib,json,re,math
VERSION='pkpd-layered-context/0.4.0-offline-candidate'
STAGES={'data_eda','animal_pk','pkpd','translation','human_simulation','pta'}
BRANCHES={'antibacterial','hepatic_ivive','turnover_pd'}
STOP={'a','an','the','of','and','or','for','to','in','on','is','are','with','how','what','which','when','can','must','should'}
ALIASES={'浓度':'concentration','画图':'plot figure','绘图':'plot figure','时间':'time','缺失':'missing','删失':'censoring','破坏性取样':'destructive sampling','误差条':'uncertainty summary','剂量归一化':'dose normalized','基线':'baseline','分组':'grouping','散点':'scatterplots','清除率':'clearance','外推':'translation species','暴露':'exposure','效应':'effect response','不确定性':'uncertainty','变异':'variability','间接反应':'indirect response turnover','周转':'turnover','滞后':'delayed hysteresis','生物标志物':'biomarker','达标':'attainment','实验单位':'experimental units','蛋白结合':'binding unbound','分布容积':'volume'}
ALIASES.update({'非房室': 'noncompartmental NCA', '终末斜率': 'terminal slope', '稀疏': 'sparse', '残差': 'residual', '似然': 'likelihood', '可辨识性': 'identifiability', '预测检验': 'predictive VPC', '外部预测': 'external prediction', '收敛': 'convergence', '效应室': 'effect compartment', '直接效应': 'direct effect', '生成': 'production', '消除': 'loss elimination', '生物利用度': 'bioavailability', '群体': 'population', '典型个体': 'typical profile', '给药方案': 'regimen scenario', '敏感性': 'sensitivity', '加权': 'weighted', '分母': 'denominator', '尾部': 'tails', '再生长': 'regrowth', '耐药机制': 'resistance mechanism', '时间杀菌': 'time kill'})

ALIASES.update({'肝脏':'hepatic'})

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def canonical(x):return json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'))

# Lexical aliases only. They never alter returned scientific text, applicability or permissions.
ALIASES.update({'生理药动学':'PBPK','参数来源':'parameter provenance source','模型假设':'model assumptions','库模型':'library model','修改':'modifications','记录':'documentation'})
def normalize_notation(text):
    normalized=text
    for pattern,replacement in [
        (r'λ\s*[_ ,]?\s*z\b', 'lambda_z'),
        (r'\blambda\s*[_ ,]\s*z\b', 'lambda_z'),
        (r'\bclint\s*[, _]\s*u\b', 'clint_u'),
        (r'\bfu\s*[, _]?\s*b\b', 'fub'),
        (r'\bfu\s*[, _]?\s*inc\b', 'fuinc'),
        (r'\bcl\s*/\s*f\b', 'cl_over_f'),
        (r'\bauc\s*∞', 'aucinf'),
    ]:
        normalized=re.sub(pattern,replacement,normalized,flags=re.I)
    return text+' '+normalized

def words(text):
    text=normalize_notation(text)
    for a,b in ALIASES.items():
        if a in text:text+=' '+b
    found=set(re.findall(r'[a-z][a-z0-9_]*',text.lower()))-STOP
    return found|{t[:-1] for t in found if len(t)>5 and t.endswith('s')}
def load(root):
    root=Path(root).resolve()
    sources={s['id']:s for s in json.loads((root/'source_registry.json').read_text(encoding='utf-8'))}
    chunks={c['id']:c for c in map(json.loads,(root/'chunks.jsonl').read_text(encoding='utf-8').splitlines())}
    cards=json.loads((root/'cards.json').read_text(encoding='utf-8'))
    return root,sources,chunks,cards


# Explicit scope labels only; selecting a branch is never scientific approval.
BRANCHES.update({'renal_clearance','dynamic_time_kill'})
# Only lexical normalization; no permissions or scientific assumptions are inferred.
ALIASES.update({'动物编号':'subject identifier', '活性代谢物':'active metabolite',
                '母体药物':'parent drug', '预测校正':'prediction correction',
                '收缩':'shrinkage', '笼':'cage'})
ALIASES.update({'积分':'integration','对数梯形':'log trapezoidal',
                '观察尺度':'observation scale','加性':'additive','比例':'proportional',
                '组合误差':'combined error','标准差':'standard deviation','方差':'variance'})
ALIASES.update({'抗菌药':'antibacterial','指标判别':'index discrimination','靶值':'target'})
_legacy_words = words
_TERM_EQUIVALENTS = {'bql':'blq', 'censored':'censoring', 'censor':'censoring',
                     'modifications':'modification', 'predictive':'prediction'}
def words(text):
    return {_TERM_EQUIVALENTS.get(t,t) for t in _legacy_words(text)}

def _metadata(path, cards, root):
    if path is None:
        return {}, None
    obj=json.loads(Path(path).read_text(encoding='utf-8-sig'))
    if obj.get('schema')!='pkpd-reviewed-retrieval-metadata/1':
        raise ValueError('Unknown reviewed retrieval metadata schema')
    if obj.get('reviewed_against_final_cards_and_evidence') is not True:
        raise ValueError('Retrieval keyword evidence review required')
    for name in ['chunks.jsonl','source_registry.json']:
        if obj.get('library_bindings',{}).get(name)!=sha(root/name):
            raise ValueError('Stale retrieval evidence binding '+name)
    byid={c['id']:c for c in cards}; result={}
    for item in obj.get('cards',[]):
        cid=item['card_id']
        if cid not in byid or cid in result:
            raise ValueError('Unknown or duplicate retrieval metadata card')
        expected=hashlib.sha256(canonical(byid[cid]).encode()).hexdigest()
        if item.get('base_card_sha256')!=expected:
            raise ValueError('Stale retrieval metadata binding '+cid)
        for key in ('keyword_additions','dependency_card_ids'):
            values=item.get(key,[])
            if not isinstance(values,list) or not all(isinstance(v,str) and v.strip() for v in values):
                raise ValueError('Invalid retrieval metadata '+key)
        if not set(item.get('dependency_card_ids',[]))<=set(byid):
            raise ValueError('Unknown dependency card')
        result[cid]=item
    return result, sha(path)

def _rank(query, eligible, metadata):
    """IDF-weighted token overlap with mild length normalization; no card-ID rules."""
    q=words(query); documents={}
    for cid,c in eligible.items():
        keywords=c.get('method_keywords',[])+metadata.get(cid,{}).get('keyword_additions',[])
        documents[cid]=words(c['title']+' '+' '.join(keywords))
    n=len(documents); avg=sum(map(len,documents.values()))/max(1,n)
    df={t:sum(t in doc for doc in documents.values()) for t in q}
    idf={t:math.log(1+(n-v+.5)/(v+.5)) for t,v in df.items()}
    rows=[]
    for cid,tokens in documents.items():
        overlap=q & tokens
        if not overlap:continue
        score=sum(idf[t] for t in overlap)/(.75+.25*len(tokens)/max(1,avg))
        rows.append({'card_id':cid,'score':score,'matched_terms':sorted(overlap)})
    return sorted(rows,key=lambda x:(-x['score'],x['card_id']))

def _background(methods,evidence,refs,matches):
    return {'general_methods':methods,'applicability_and_examples':{
        'cited_originals':refs,'evidence':list(evidence.values()),
        'named_example_matches':matches,
        'applicability_status':'PROJECT_SPECIFIC_CHECKS_NOT_AUTOMATICALLY_RESOLVED'}}

def _background_size(methods,evidence,refs,matches):
    # No scientific payload costs zero; protocol envelopes are not evidence.
    if not (methods or evidence or refs or matches):return 0
    return len(canonical(_background(methods,evidence,refs,matches)))

def build_context(root, *, query, stage, project_context, allowed_source_ids,
                  branches=(), example_query=None, allow_draft=False,
                  consumer_route='method_background', max_methods=3,
                  character_budget=32768, metadata_path=None, method_ids=None):
    """Offline full-evidence packet. Follow-up requests require separate host execution.

    Optional method_ids explicitly selects already-known methods; it never bypasses filters.
    Dependencies are supplied only by bound reviewed metadata/card metadata. A dependency
    closure is atomic: missing permissions/branch/stage/budget never silently drops a member.
    No proposed round11 scientific card is loaded or approved by this adapter.
    """
    if not allow_draft:raise ValueError('Explicit draft opt-in required')
    if stage not in STAGES:raise ValueError('Unknown stage')
    if consumer_route not in {'method_background','data.requirements','data.necessity'}:
        raise ValueError('Consumer route must preserve full evidence or accepted summary; retrieval rejected')
    if not isinstance(project_context,dict) or not isinstance(project_context.get('objective'),str) or not project_context['objective'].strip():
        raise ValueError('Caller must provide current objective')
    if not 1<=max_methods<=6 or not 1<=character_budget<=48000:
        raise ValueError('Review budget outside contract')
    if not set(branches)<=BRANCHES:raise ValueError('Unimplemented branch; do not silently infer applicability')
    root,sources,chunks,cards=load(root);scope=set(allowed_source_ids)
    if not scope or not scope<=set(sources):raise ValueError('Explicit known source scope required')
    if not words(query):raise ValueError('No method terms; supply canonical terms')
    if metadata_path is None and (root/'reviewed_retrieval_metadata.json').is_file():
        metadata_path=root/'reviewed_retrieval_metadata.json'
    byid={c['id']:c for c in cards};metadata,metadata_hash=_metadata(metadata_path,cards,root)
    if method_ids is not None and (not isinstance(method_ids,(list,tuple)) or not method_ids
            or not all(isinstance(i,str) for i in method_ids) or len(set(method_ids))!=len(method_ids)
            or not set(method_ids)<=set(byid)):
        raise ValueError('Explicit methods must be unique known card IDs')
    def eligible(c):
        return (c.get('knowledge_layer') in {'general_method','conditional_method'}
            and stage in c['topics'] and set(c['source_ids'])<=scope
            and not any(s.startswith('IN_') for s in c['source_ids'])
            and set(c.get('required_branches',[]))<=set(branches))
    permitted={cid:c for cid,c in byid.items() if eligible(c)}
    ranking=_rank(query,permitted,metadata)
    ranking_byid={row['card_id']:row for row in ranking}
    anchors=list(method_ids) if method_ids is not None else [row['card_id'] for row in ranking]
    selected=[];selected_ids=set();evidence={};refs={};matches=[];omissions=[]
    def closure(cid,trail=()):
        if cid in trail:raise ValueError('Cyclic method dependencies')
        if cid not in permitted:raise PermissionError('dependency_not_eligible')
        result=[]
        deps=metadata.get(cid,{}).get('dependency_card_ids',byid[cid].get('dependency_card_ids',[]))
        if not isinstance(deps,list) or not all(isinstance(d,str) for d in deps):
            raise ValueError('Invalid card dependency metadata')
        for dep in deps:
            if dep not in byid:raise ValueError('Unknown dependency card')
            for member in closure(dep,trail+(cid,)):
                if member not in result:result.append(member)
        if cid not in result:result.append(cid)
        return result
    def verify_source(sid):
        s=sources[sid];p=(root/s['local_path']).resolve()
        if root not in p.parents or sha(p)!=s['sha256']:
            raise ValueError('Changed or unsafe original source '+sid)
        return {k:s[k] for k in ['id','title','url','document_url','local_path','sha256',
            'access_level','source_status','document_type','limitations','applicability','source_example'] if k in s}
    def verified_bundle(ids):
        ev={};sr={}
        for cid in ids:
            c=byid[cid]
            for eid in c['evidence_chunk_ids']:
                if eid not in chunks:raise ValueError('Dangling citation')
                chunk=chunks[eid]
                if chunk['source_id'] not in scope:raise ValueError('Evidence scope mismatch')
                if hashlib.sha256(chunk['text'].encode()).hexdigest()!=chunk['sha256']:
                    raise ValueError('Changed cited text')
                ev[eid]=chunk
                if chunk['source_id'] not in sr:sr[chunk['source_id']]=verify_source(chunk['source_id'])
            if {chunks[eid]['source_id'] for eid in c['evidence_chunk_ids']}!=set(c['source_ids']):
                raise ValueError('Citation/source mismatch')
        return ev,sr
    followups=[]
    for cid in anchors:
        if cid in selected_ids:continue
        try:ids=closure(cid)
        except PermissionError:
            omissions.append({'card_id':cid,'reason':'method_or_dependency_not_eligible'});continue
        new=[i for i in ids if i not in selected_ids]
        ev,sr=verified_bundle(ids)
        fullsize=_background_size([byid[i] for i in ids],ev,sr,[])
        trial_methods=selected+[byid[i] for i in new]
        trial_ev={**evidence,**ev};trial_refs={**refs,**sr}
        size=_background_size(trial_methods,trial_ev,trial_refs,matches)
        reason='method_limit' if len(trial_methods)>max_methods else ('character_budget' if size>character_budget else None)
        if reason:
            entry={'card_id':cid,'reason':reason,'dependency_closure':ids,
                   'standalone_background_characters':fullsize}
            omissions.append(entry)
            if fullsize<=48000 and len(ids)<=max_methods:
                # A plan only. It does not add hidden evidence or multiply this packet's budget.
                needs_budget_opt_in=fullsize>character_budget
                followups.append({'method_ids':[cid],'reason':reason,
                    'required_same_request_fields':['query','stage','project_context','allowed_source_ids',
                        'branches','allow_draft','consumer_route','max_methods','metadata_path'],
                    'current_character_budget':character_budget,
                    'required_character_budget':max(character_budget,fullsize),
                    'requires_explicit_budget_opt_in':needs_budget_opt_in,
                    'request_overrides':{'character_budget':fullsize} if needs_budget_opt_in else {},
                    'execute_automatically':False})
            else:entry['resolution']='closure_exceeds_hard_contract; packet unavailable without separately reviewed structural change'
            continue
        selected=trial_methods;selected_ids.update(new);evidence=trial_ev;refs=trial_refs
    if example_query:
        eq=example_query.casefold().strip()
        if not eq:raise ValueError('Empty named-example query')
        for sid,s in sources.items():
            if sid not in scope or sid.startswith('IN_'):continue
            if eq not in (s['title']+' '+canonical(s.get('source_example',{}))).casefold():continue
            s=verify_source(sid)
            record={'source_id':sid,'original_title':s['title'],'source_example':s.get('source_example'),
                'applicability':s.get('applicability'),'access_level':s['access_level'],'sha256':s['sha256'],
                'note':'Source lookup only; missing metadata unknown, not scientific qualification.'}
            if _background_size(selected,evidence,refs,matches+[record])>character_budget:continue
            matches.append(record)
            if len(matches)==3:break
    project=json.loads(canonical(project_context))
    bindings={name:sha(root/name) for name in ['cards.json','chunks.jsonl','source_registry.json','retrieval_policy.json']}
    bindings['adapter_sha256']=sha(__file__);bindings['retrieval_metadata_sha256']=metadata_hash
    bindings['request_sha256']=hashlib.sha256(canonical({'query':query,'stage':stage,'scope':sorted(scope),
        'branches':sorted(branches),'example_query':example_query,'route':consumer_route,
        'max_methods':max_methods,'character_budget':character_budget,'allow_draft':allow_draft,
        'project_context':project,'method_ids':method_ids,'retrieval_metadata_sha256':metadata_hash}).encode()).hexdigest()
    result=_background(selected,evidence,refs,matches)
    primary_omitted=bool(anchors and anchors[0] not in selected_ids and any(
        x['card_id']==anchors[0] and x['reason'] in {'character_budget','method_limit'} for x in omissions))
    status=('PARTIAL_METHOD_PACKET_REQUIRES_FOLLOWUP' if selected else 'NO_METHOD_DELIVERED_REQUIRES_FOLLOWUP') if primary_omitted else (
        'DRAFT_FOR_LOCAL_REVIEW' if selected else 'NO_METHOD_MATCH_NOT_PROOF_OF_ABSENCE')
    result.update({'interface_version':VERSION,'status':status,
        'project_context':project,'bindings':bindings,'scientific_approval':False,'production_dispatch_authorized':False,
        'selection':{'method_query':query,'stage':stage,'branches':list(branches),
            'background_characters':_background_size(selected,evidence,refs,matches),
            'budget_omitted':[x['card_id'] for x in omissions if x['reason']=='character_budget'],
            'omissions':omissions,'followup_packet_requests':followups,
            'ranking':ranking,'explicit_method_ids':method_ids,
            'primary_requested_method_omitted':primary_omitted,
            'retrieval_relevance_is_not_scientific_coverage':True}})
    return result

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--request',required=True)
    args=p.parse_args();request=json.loads(Path(args.request).read_text(encoding='utf-8-sig'))
    print(json.dumps(build_context(args.root,**request),ensure_ascii=False,indent=2))
