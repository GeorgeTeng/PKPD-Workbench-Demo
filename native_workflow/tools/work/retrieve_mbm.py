import urllib.request, urllib.parse, json, pathlib, concurrent.futures, xml.etree.ElementTree as ET
root=pathlib.Path('work/mbm_review'); root.mkdir(exist_ok=True)
queries={
 'pk':'(TITLE_ABS:colistin OR TITLE_ABS:"polymyxin B") AND (TITLE_ABS:"physiologically based" OR TITLE_ABS:interspecies OR TITLE_ABS:allometric OR TITLE_ABS:humanized)',
 'semimech':'(TITLE_ABS:colistin OR TITLE_ABS:"polymyxin B") AND (TITLE_ABS:semimechanistic OR TITLE_ABS:"semi-mechanistic" OR TITLE_ABS:"mechanism based") AND TITLE_ABS:model'
}
def get(url):
 return urllib.request.urlopen(url,timeout=45).read()
def search(item):
 name,q=item
 url='https://www.ebi.ac.uk/europepmc/webservices/rest/search?'+urllib.parse.urlencode({'query':q,'format':'json','pageSize':100,'resultType':'core'})
 data=get(url); (root/(name+'.json')).write_bytes(data)
 return name,json.loads(data)['hitCount']
def full(pmc):
 data=get('https://www.ebi.ac.uk/europepmc/webservices/rest/'+pmc+'/fullTextXML')
 (root/(pmc+'.xml')).write_bytes(data)
 doc=ET.fromstring(data)
 pars=[' '.join(p.itertext()) for p in doc.findall('.//body//p')]
 (root/(pmc+'.txt')).write_text('\n\n'.join(pars),encoding='utf-8')
 return pmc,len(pars)
with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
 futures=[pool.submit(search,i) for i in queries.items()]+[pool.submit(full,p) for p in ['PMC5826166','PMC4914682','PMC4862466','PMC10014067','PMC12888851','PMC10609266']]
 for f in concurrent.futures.as_completed(futures):
  try: print(f.result(),flush=True)
  except Exception as e: print(type(e).__name__,str(e),flush=True)
