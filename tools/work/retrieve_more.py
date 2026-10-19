import urllib.request, pathlib, concurrent.futures, xml.etree.ElementTree as ET
import re,html
root=pathlib.Path('work/mbm_review')
def fetch(p):
 try:
  data=urllib.request.urlopen('https://www.ebi.ac.uk/europepmc/webservices/rest/'+p+'/fullTextXML',timeout=35).read()
  doc=ET.fromstring(data); txt='\n\n'.join(' '.join(x.itertext()) for x in doc.findall('.//body//p'))
  (root/(p+'.xml')).write_bytes(data)
 except Exception:
  data=urllib.request.urlopen('https://pmc.ncbi.nlm.nih.gov/articles/'+p+'/',timeout=35).read()
  article=re.search(r'<article\b.*?</article>',data.decode('utf-8'),re.S)
  if article is None: raise ValueError('No article body '+p)
  txt=html.unescape(re.sub(r'<[^>]+>',' ',article.group(0)))
 (root/(p+'.txt')).write_text(txt,encoding='utf-8')
 return p,len(txt)
with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
 for f in concurrent.futures.as_completed([pool.submit(fetch,p) for p in ['PMC5826166','PMC4914682','PMC11608097','PMC11111785','PMC10190254','PMC10609266']]):
  try: print(f.result(),flush=True)
  except Exception as e: print(type(e).__name__,str(e),flush=True)
