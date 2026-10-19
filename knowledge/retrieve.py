"""Portable offline draft retrieval. No model calls, production imports or writes."""
from pathlib import Path
import argparse, hashlib, json, re, sqlite3, math

ALIASES={'动物':'animal','清除率':'clearance','分布容积':'volume','蛋白结合':'protein binding unbound',
 '外推':'allometry translation','靶值':'target','达标':'target attainment','删失':'censor BLQ',
 '定量下限':'LLOQ BLQ','个体':'individual','稀疏':'sparse','不确定性':'uncertainty',
 '诊断':'diagnostic predictive','时间杀菌':'time kill','菌量':'bacterial count','剂量分割':'dose fractionation',
 '加权':'weighted cumulative fraction response','肾':'renal','实验单位':'experimental unit'}

ALIASES.update({'人体':'human prospective','安全':'safety','疗效':'efficacy','缺失':'missing','混样':'pooled','重复':'replicate','稳态':'steady state','中央':'central','基线':'baseline','抑菌':'stasis','检出限':'detection limit','尾部':'tail truncated','药敏':'MIC susceptibility','可识别':'identifiability','残差':'residual','变异':'variability','生物利用度':'bioavailability','清除':'clearance','采样':'sampling','校准':'calibration','不达标':'target unattained','达标率':'target attainment'})
STOP={'a','an','the','of','and','or','for','to','in','on','at','is','are','be','with','what','which','how','does','can','do','must','should','from','when','not'}
SYNONYMS={'cl':'clearance','vss':'volume','vz':'volume','vc':'volume','bql':'blq','lloq':'quantification','cfr':'weighted','pta':'attainment','fu':'unbound','iiv':'variability','bsv':'variability','pkpd':'exposure','nca':'noncompartmental','pcvpc':'diagnostic','vpc':'diagnostic'}

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

def tokens(text):
    text=normalize_notation(text)
    values=set(re.findall(r'[a-z][a-z0-9_]*',text.lower()))-STOP
    # Conservative morphology, without rewriting scientific abbreviations.
    values|={w[:-1] for w in values if len(w)>5 and w.endswith('s')}
    values|={SYNONYMS[w] for w in list(values) if w in SYNONYMS}
    return values

def ranked_candidates(db, query, stage, allowed):
    scope=set(allowed); q=tokens(query)
    candidates=[]
    for (encoded,) in db.execute('SELECT json FROM cards'):
        c=json.loads(encoded)
        if stage not in c['topics'] or not set(c['source_ids'])<=scope:continue
        fields=[tokens(c.get('retrieval_keywords','')),tokens(c['title']),tokens(c['claim']),tokens(' '.join(c['conditions']+c['required_inputs']+c['limitations']))]
        allwords=set().union(*fields)
        if q & allwords:candidates.append((encoded,c,fields,allwords))
    if not candidates:return []
    idf={w:math.log(1+len(candidates)/(1+sum(w in row[3] for row in candidates))) for w in q}
    scored=[]
    for encoded,c,fields,allwords in candidates:
        score=sum(idf[w]*max(weight for field,weight in zip(fields,[4.0,3.0,1.8,1.0]) if w in field) for w in q & allwords)
        # Bounded relevance preference, not a claim of scientific approval.
        coverage=len(q & allwords)/max(1,len(q))
        score*=0.6+coverage
        if c.get('kind')=='question_refinement':score*=1.12
        scored.append((score,c['id'],encoded))
    return [(encoded,) for score,cid,encoded in sorted(scored,key=lambda row:(-row[0],row[1]))]


def search(root, query, stage, allowed_source_ids, *, allow_draft=False, limit=6, character_budget=18000):
    root=Path(root)
    if not allow_draft:raise ValueError('This library is draft: explicit allow_draft required for local review')
    policy=json.loads((root/'retrieval_policy.json').read_text(encoding='utf-8'))
    if stage not in policy['topics']:raise ValueError('Unknown stage')
    if not allowed_source_ids:raise ValueError('Explicit source scope required')
    if not 1<=limit<=policy['max_cards']:raise ValueError('Limit outside policy')
    if not 1<=character_budget<=policy['background_character_budget']:raise ValueError('Budget outside policy')
    expanded=query
    for zh,en in ALIASES.items():
        if zh in query:expanded+=' '+en
    terms=list(dict.fromkeys(re.findall(r'[A-Za-z][A-Za-z0-9_]*',expanded)))
    if not terms:raise ValueError('No searchable terms; add a canonical English term')
    match=' OR '.join('"'+t+'"' for t in terms)
    dbpath=root/'knowledge.sqlite'
    db=sqlite3.connect(dbpath.resolve().as_uri()+'?mode=ro',uri=True)
    try:
        known={r[0] for r in db.execute('SELECT id FROM sources')}
        if not set(allowed_source_ids)<=known:raise ValueError('Unknown source IDs in allowed scope')
        selected=[];evidence={};used=0;budget_omitted=[]
        rows=ranked_candidates(db,expanded,stage,allowed_source_ids)
        for (encoded,) in rows:
            c=json.loads(encoded)
            if stage not in c['topics'] or not set(c['source_ids'])<=set(allowed_source_ids):continue
            # Skip near-identical evidence/claims already selected, preserving different conclusions.
            if any(set(c['evidence_chunk_ids'])==set(prev['evidence_chunk_ids']) and len(tokens(c['claim']) & tokens(prev['claim']))/max(1,len(tokens(c['claim']) | tokens(prev['claim'])))>0.65 for prev in selected):continue
            additions={}
            for cid in c['evidence_chunk_ids']:
                row=db.execute('SELECT source_id,locator,text,sha256 FROM chunks WHERE id=?',(cid,)).fetchone()
                if row is None:raise ValueError('Dangling source citation: '+cid)
                if hashlib.sha256(row[2].encode()).hexdigest()!=row[3]:raise ValueError('Changed evidence text')
                if cid not in evidence:additions[cid]=dict(id=cid,source_id=row[0],locator=row[1],text=row[2],sha256=row[3])
            size=len(encoded)+len(json.dumps(additions,ensure_ascii=False))
            if used+size>character_budget:budget_omitted.append(c['id']);continue
            selected.append(c);evidence.update(additions);used+=size
            if len(selected)>=limit:break
        refs={sid:json.loads(db.execute('SELECT json FROM sources WHERE id=?',(sid,)).fetchone()[0]) for sid in {c['source_id'] for c in evidence.values()}}
        for s in refs.values():
            path=(root/s['local_path']).resolve()
            if root.resolve() not in path.parents:raise ValueError('Source path escapes library')
            if hashlib.sha256(path.read_bytes()).hexdigest()!=s['sha256']:raise ValueError('Original source hash changed')
        return {'status':'DRAFT_FOR_LOCAL_REVIEW' if selected else 'NO_MATCH_NOT_EVIDENCE_OF_ABSENCE',
            'query':query,'stage':stage,'cards':selected,'evidence':list(evidence.values()),'sources':refs,
            'retrieval_method':'lexical_weighted_diversity_v2','budget_omitted':budget_omitted,'content_characters':used,
            'bindings':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in [dbpath,root/'retrieval_policy.json']},
            'scientific_approval':False,'production_dispatch_authorized':False}
    finally:db.close()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',default=str(Path(__file__).parent));p.add_argument('--query',required=True)
    p.add_argument('--stage',required=True);p.add_argument('--source-id',action='append',default=[])
    p.add_argument('--all-sources-for-review',action='store_true');p.add_argument('--allow-draft',action='store_true')
    p.add_argument('--limit',type=int,default=6);args=p.parse_args()
    allowed=args.source_id
    if args.all_sources_for_review:
        allowed=[s['id'] for s in json.loads((Path(args.root)/'source_registry.json').read_text(encoding='utf-8'))]
    print(json.dumps(search(args.root,args.query,args.stage,allowed,allow_draft=args.allow_draft,limit=args.limit),ensure_ascii=False,indent=2))
