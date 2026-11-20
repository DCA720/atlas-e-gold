#!/usr/bin/env python3
"""RC8.9: conservative contextual triage of verified RC8.7 release captures."""
import argparse, hashlib, json, re
from pathlib import Path
from datetime import datetime, timezone
from html.parser import HTMLParser
VERSION='eur-rc8.9-contextual-release-triage-0.8.9'
FACTORS=('inflation','rates','unemployment','activity')
PATTERNS={
 'US_UNRATE_2025-11_BLS':[('unemployment_rate_4_6',r'\bunemployment rate\b.{0,220}?\b4[.,]6\b|\b4[.,]6\b.{0,220}?\bunemployment rate\b')],
 'US_FOMC_2026-09-16':[('target_range_3_75_to_4',r'\b3[.,]75\s*(?:to|[-–—])\s*4(?:[.,]0+)?\s*percent|\b3-3/4\s*(?:to|[-–—])\s*4\s*percent')],
 'EU_ECB_2026-09-10':[('deposit_rate_2_50',r'\bdeposit facility\b.{0,250}?\b2[.,]50\b|\b2[.,]50\b.{0,250}?\bdeposit facility\b')],
 'EU_HICP_2026-09_FLASH':[('inflation_3_8',r'\b(?:annual inflation|inflation rate|euro area inflation)\b.{0,250}?\b3[.,]8\b|\b3[.,]8\b.{0,250}?\b(?:annual inflation|inflation rate)\b')],
 'EU_HICP_2026-09_FULL':[('inflation_3_8',r'\b(?:annual inflation|inflation rate|euro area inflation)\b.{0,250}?\b3[.,]8\b|\b3[.,]8\b.{0,250}?\b(?:annual inflation|inflation rate)\b')],
 'EU_HICP_2026-10_FLASH':[('inflation_4_0',r'\b(?:annual inflation|inflation rate|euro area inflation)\b.{0,250}?\b4[.,]0\b|\b4[.,]0\b.{0,250}?\b(?:annual inflation|inflation rate)\b')],
 'EU_INDUSTRY_2026-09':[('industrial_production_0_2',r'\bindustrial production\b.{0,300}?\b0[.,]2\b|\b0[.,]2\b.{0,300}?\bindustrial production\b')]}
class Extract(HTMLParser):
 def __init__(self):super().__init__(convert_charrefs=True);self.parts=[];self.skip=0
 def handle_starttag(self,tag,attrs):
  if tag in ('script','style','noscript'):self.skip+=1
  if tag in ('p','tr','td','th','h1','h2','h3','li','div'):self.parts.append(' ')
 def handle_endtag(self,tag):
  if tag in ('script','style','noscript') and self.skip:self.skip-=1
  if tag in ('p','tr','td','th','h1','h2','h3','li','div'):self.parts.append(' ')
 def handle_data(self,data):
  if not self.skip:self.parts.append(data)
def contextual(raw,event):
 p=Extract();p.feed(raw.decode('utf-8','replace'));s=re.sub(r'\s+',' ',' '.join(p.parts))
 result=[]
 for name,pattern in PATTERNS.get(event,[]):
  matches=list(re.finditer(pattern,s,re.I))[:3]
  result.append({'check':name,'candidate_count':len(matches),'candidate_snippets':[s[max(0,m.start()-100):min(len(s),m.end()+100)][:550] for m in matches], 'human_review_required':True,'historical_first_release_proven':False,'concept_unit_verified':False})
 return result
def build(rc87,rc88,base):
 if not (rc87.get('model_version','').startswith('eur-rc8.7-') and rc88.get('model_version','').startswith('eur-rc8.8-') and rc87.get('input_valid') and rc88.get('input_valid') and rc88.get('raw_files_integrity_verified')==12 and rc88.get('raw_files_mismatched')==0 and rc88.get('eligible_count')==0 and rc88.get('coverage')==0 and rc88.get('relative_score') is None and not rc88.get('point_in_time_integrity_verified',True)):raise ValueError('Input RC8.7/RC8.8 or safety gates invalid')
 entries=[]
 for r in rc87['records']:
  if r.get('evidence_kind')!='official_archived_release_page':continue
  cap=r['raw_capture'];rel=Path(cap['path']);root=(base/'eur_rc87_archive').resolve();target=(base/rel).resolve()
  if rel.is_absolute() or '..' in rel.parts or not target.is_relative_to(root):raise ValueError('Unsafe archive path')
  if not target.is_file():entries.append({'event_id':r['event_id'],'integrity':'missing','candidates':[]});continue
  raw=target.read_bytes();valid=hashlib.sha256(raw).hexdigest()==cap['sha256'] and len(raw)==cap['size_bytes']
  entries.append({'event_id':r['event_id'],'integrity':'verified' if valid else 'mismatch','candidates':contextual(raw,r['event_id']) if valid else []})
 return {'model_version':VERSION,'asset':'EUR/USD','module':'contextual_release_triage','asof_utc':datetime.now(timezone.utc).isoformat(),'input_valid':True,'release_pages_reviewed':len(entries),'release_pages_integrity_verified':sum(e['integrity']=='verified' for e in entries),'contextual_candidates_found':sum(c['candidate_count'] for e in entries for c in e['candidates']),'records':entries,'review_notes':['Regex candidate snippets are triage only, not authenticated economic assertions.','BLS and Fed may express numbers as words or fractions; missing candidates do not mean absent economic data.','INDPRO US index and Eurostat EA monthly percent change are not equivalent.','Original first-dissemination timestamp and full first-release vintage remain unverified.'],'independent_first_dissemination_timestamps_verified':0,'original_full_first_release_datasets_verified':0,'concept_and_unit_mapping_verified':False,'verified_point_in_time_events':0,'point_in_time_integrity_verified':False,'eligibility':{f:False for f in FACTORS},'eligible_count':0,'coverage':0.0,'relative_score':None,'horizons':{'1d':{'score':None},'5d':{'score':None}},'point_in_time_backtest_authorized':False,'signals_generated':False,'database_writes':False,'production_change_authorized':False,'source_code_modified':False,'prospective_capture_active':False,'next_step':'Human review contextual candidates against complete release tables; seek independently timestamped original vintages.'}
def self_test():
 raw=b'<p>The unemployment rate was 4.6 percent in November.</p>'
 assert contextual(raw,'US_UNRATE_2025-11_BLS')[0]['candidate_count']==1
 assert contextual(b'<p>Nothing relevant</p>','US_FOMC_2026-09-16')[0]['candidate_count']==0
 print('RC89_SELF_TEST_OK')
def main():
 p=argparse.ArgumentParser();p.add_argument('--rc87',default='eur_rc87_result.json');p.add_argument('--rc88',default='eur_rc88_result.json');p.add_argument('--base-dir',default='.');p.add_argument('--output',default='eur_rc89_result.json');p.add_argument('--self-test',action='store_true');a=p.parse_args()
 if a.self_test:self_test();return
 out=build(json.loads(Path(a.rc87).read_text()),json.loads(Path(a.rc88).read_text()),Path(a.base_dir));Path(a.output).write_text(json.dumps(out,indent=2,ensure_ascii=False)+'\n');print('RC89_OK',out['release_pages_integrity_verified'],out['contextual_candidates_found'])
if __name__=='__main__':main()
