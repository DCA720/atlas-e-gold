#!/usr/bin/env python3
"""Atlas EUR RC7.9: read-only targeted historical document evidence collection."""
import argparse, datetime as dt, hashlib, html, json, re, urllib.request, urllib.parse
from html.parser import HTMLParser
from pathlib import Path

VERSION='eur-rc7.9-targeted-historical-release-retrieval-0.7.9'
SOURCES=[
 ('EU_HICP_2026-09_FLASH','inflation','https://ec.europa.eu/eurostat/web/products-euro-indicators/w/2-02102026-ap','2026-09','flash'),
 ('EU_HICP_2026-09_FULL','inflation','https://ec.europa.eu/eurostat/en/web/products-euro-indicators/w/2-16102026-ap','2026-09','full'),
 ('EU_HICP_2026-10_FLASH','inflation','https://ec.europa.eu/eurostat/en/web/products-euro-indicators/w/2-04112026-ap','2026-10','flash'),
 ('US_UNRATE_2025-11_BLS','unemployment','https://www.bls.gov/news.release/archives/empsit_12162025.htm','2025-11','employment_situation'),
 ('US_FOMC_2026-09-16','rates','https://www.federalreserve.gov/newsevents/pressreleases/monetary20260916a.htm','2026-09-16','policy_statement'),
 ('EU_ECB_2026-09-10','rates','https://www.ecb.europa.eu/press/pr/date/2026/html/ecb.mp260910~314e508016.en.html','2026-09-10','policy_decision'),
 ('EU_INDUSTRY_2026-09','activity','https://ec.europa.eu/eurostat/en/web/products-euro-indicators/w/4-16112026-ap','2026-09','industrial_production'),
]
HOSTS={'ec.europa.eu','www.bls.gov','www.federalreserve.gov','www.ecb.europa.eu'}
class Visible(HTMLParser):
 def __init__(self):super().__init__();self.skip=0;self.parts=[];self.title=[];self.in_title=False
 def handle_starttag(self,t,a):
  if t in ('script','style','noscript','svg'):self.skip+=1
  if t=='title':self.in_title=True
 def handle_endtag(self,t):
  if t in ('script','style','noscript','svg'):self.skip=max(0,self.skip-1)
  if t=='title':self.in_title=False
 def handle_data(self,s):
  if self.in_title:self.title.append(s)
  if not self.skip:self.parts.append(s)

def fetch(url,max_bytes=8_000_000):
 assert urllib.parse.urlparse(url).scheme=='https' and urllib.parse.urlparse(url).hostname in HOSTS
 req=urllib.request.Request(url,headers={'User-Agent':'AtlasEUR-ResearchAudit/0.7.9 (read-only)','Accept':'text/html'})
 with urllib.request.urlopen(req,timeout=28) as r:
  final=r.geturl();p=urllib.parse.urlparse(final)
  if p.scheme!='https' or p.hostname not in HOSTS:raise ValueError('redirect_outside_official_allowlist')
  chunks=[];size=0
  while True:
   chunk=r.read(65536)
   if not chunk:break
   size+=len(chunk)
   if size>max_bytes:raise ValueError('oversize')
   chunks.append(chunk)
  raw=b''.join(chunks);charset=r.headers.get_content_charset() or 'utf-8'
  decoded=raw.decode(charset,errors='replace');parser=Visible();parser.feed(decoded)
  text=' '.join(' '.join(parser.parts).split())
  return {'status':'retrieved','http_status':r.status,'final_url':final,'content_type':r.headers.get('Content-Type'),'size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'title':' '.join(parser.title).strip()[:240],'text':text}

def evidence(text,factor,kind):
 patterns={
  'inflation':[('headline_hicp',r'(?i)(?:euro area annual inflation|annual inflation[^.]{0,60}euro area)[^.]{0,130}?\b\d+(?:[.,]\d+)?\s*%')],
  'unemployment':[('headline_unemployment',r'(?i)\bin november,?\s+(?:both\s+)?(?:the\s+)?unemployment rate[^.]{0,45}?\b\d+(?:\.\d+)?\s*percent'),('embargo',r'(?i)embargoed until.{0,110}?\b(?:December\s+16,\s+2025|8:30\s*a\.m\.)')],
  'rates':[('fomc_target',r'(?i)target range for the federal funds rate[^.]{0,120}'),('ecb_decision',r'(?i)(?:Governing Council today decided|deposit facility)[^.]{0,160}'),('scheduled_release',r'(?i)for release at\s+\d{1,2}:\d{2}\s*[ap]\.m\.?\s*(?:EDT|EST|ET)?')],
  'activity':[('industry_headline',r'(?i)(?:industrial production|in september 2026)[^.]{0,160}?\b\d+(?:[.,]\d+)?\s*%')]
 }
 out=[]
 for label,pattern in patterns.get(factor,[]):
  for m in list(re.finditer(pattern,text))[:4]:
   out.append({'kind':label,'excerpt':text[max(0,m.start()-65):min(len(text),m.end()+90)],'verification':'document_text_candidate_only'})
 return out

def audit(inp, fetcher=fetch):
 valid=inp.get('model_version','').startswith('eur-rc7.8-') and inp.get('input_valid') is True and inp.get('eligible_count')==0 and inp.get('relative_score') is None and inp.get('event_registry_candidate_count')==4
 result={'model_version':VERSION,'asof_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'asset':'EUR/USD','module':'targeted_historical_release_retrieval','input_model_version':inp.get('model_version'),'input_valid':valid,'documents_attempted':len(SOURCES),'documents':[]}
 for eid,factor,url,period,kind in SOURCES:
  d={'event_id':eid,'factor':factor,'reference_period':period,'release_kind':kind,'source_url':url,'retrieved_at_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'status':'not_attempted','document_event_link_verified':False,'actual_publication_timestamp_verified':False,'first_release_dataset_vintage_verified':False,'point_in_time_usable':False,'evidence':[]}
  if valid:
   try:
    r=fetcher(url);raw_text=r.pop('text','');d.update(r)
    if d['status']=='retrieved':d['evidence']=evidence(raw_text,factor,kind)
   except Exception as e:d['status']='fetch_error';d['error']=str(e)[:250]
  result['documents'].append(d)
 result['documents_retrieved']=sum(d['status']=='retrieved' for d in result['documents'])
 result['evidence_candidates']=sum(len(d['evidence']) for d in result['documents'])
 result['verified_point_in_time_events']=0
 result['historical_first_release_vintages_verified']=False
 result['historical_release_timestamps_verified']=False
 result['point_in_time_integrity_verified']=False
 result['eligibility']={f:False for f in ('inflation','rates','unemployment','activity')}
 result['eligible_count']=0;result['coverage']=0.0;result['relative_score']=None
 result['horizons']={'1d':{'score':None},'5d':{'score':None}}
 result['point_in_time_backtest_authorized']=False;result['signals_generated']=False;result['database_writes']=False;result['production_change_authorized']=False;result['source_code_modified']=False
 result['next_step']='Independently cross-check publication metadata and original data vintages before PIT eligibility.'
 result['limitations']=['Official document retrieval is not proof of historical first availability.','Text excerpts are candidates, not authenticated original series vintages.','A published/embargo time is not proof of actual dissemination.','No scores, signals, backtests or production writes.']
 return result

def self_test():
 mock={'model_version':'eur-rc7.8-event-document-linkage-0.7.8','input_valid':True,'eligible_count':0,'relative_score':None,'event_registry_candidate_count':4}
 def f(url):
  return {'status':'retrieved','http_status':200,'final_url':url,'sha256':'a'*64,'title':'mock','size_bytes':500,'text':'For release at 2:00 p.m. EDT. The Committee decided to raise the target range for the federal funds rate to 3-3/4 to 4 percent. In November, the unemployment rate, at 4.6 percent, was little changed.'}
 r=audit(mock,f)
 assert r['input_valid'] and r['documents_retrieved']==7 and r['evidence_candidates']>0
 assert r['eligible_count']==0 and r['relative_score'] is None and r['verified_point_in_time_events']==0
 assert not any(r[k] for k in ('database_writes','signals_generated','point_in_time_backtest_authorized','production_change_authorized'))
 assert all(not d['point_in_time_usable'] and not d['first_release_dataset_vintage_verified'] for d in r['documents'])
 assert audit({},f)['documents_retrieved']==0
 print('RC79_SELF_TEST_OK')

def main():
 p=argparse.ArgumentParser();p.add_argument('--input',default='eur_rc78_result.json');p.add_argument('--output',default='eur_rc79_result.json');p.add_argument('--self-test',action='store_true');a=p.parse_args()
 if a.self_test:self_test();return
 inp=json.loads(Path(a.input).read_text(encoding='utf-8'))
 out=audit(inp);Path(a.output).write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 print('RC79',out['documents_retrieved'],'/',out['documents_attempted'],'evidence',out['evidence_candidates'])
if __name__=='__main__':main()
