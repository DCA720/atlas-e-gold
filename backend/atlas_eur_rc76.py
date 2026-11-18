#!/usr/bin/env python3
"""Atlas EUR RC7.6: extracao conservadora de evidencias documentais (somente leitura).
Nao transforma texto encontrado em timestamp autenticado ou vintage original.
"""
import argparse
import datetime as dt
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import urllib.request
import urllib.error
from urllib.parse import urlsplit

VERSION = 'eur-rc7.6-document-evidence-extraction-0.7.6'
FACTORS = ('inflation', 'rates', 'unemployment', 'activity')
HOSTS = {'ec.europa.eu','www.ecb.europa.eu','www.federalreserve.gov','www.bls.gov'}
MAX_BYTES = 8_000_000
PATTERNS = {
    'time_candidate': re.compile(r'(?<!\d)(?:[01]?\d|2[0-3]):[0-5]\d\s*(?:a\.?m\.?|p\.?m\.?|CET|CEST|ET|EST|EDT|UTC|GMT)?',re.I),
    'date_candidate': re.compile(r'\b(?:20\d{2}[-/]\d{1,2}[-/]\d{1,2}|(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+20\d{2})\b',re.I),
    'percent_candidate': re.compile(r'(?<![\w.])-?\d{1,3}(?:[.,]\d{1,3})?\s*(?:%|percent|per cent)\b',re.I),
}

class Extract(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.skip=0; self.parts=[]; self.title=[]; self.in_title=False
    def handle_starttag(self,tag,attrs):
        if tag in ('script','style','noscript'): self.skip+=1
        if tag=='title': self.in_title=True
    def handle_endtag(self,tag):
        if tag in ('script','style','noscript'): self.skip=max(0,self.skip-1)
        if tag=='title': self.in_title=False
    def handle_data(self,data):
        if self.in_title: self.title.append(data)
        if not self.skip and data.strip(): self.parts.append(data.strip())

def safe_url(url):
    p=urlsplit(url)
    return p.scheme=='https' and p.hostname in HOSTS

def fetch_extract(url,opener=None):
    if not safe_url(url):
        return {'status':'rejected_untrusted_url','error':'URL not on HTTPS allowlist'}
    opener=opener or urllib.request.urlopen
    try:
        req=urllib.request.Request(url,headers={'User-Agent':'AtlasEUR-ResearchAudit/0.7.6','Accept':'text/html,application/xhtml+xml'})
        with opener(req,timeout=25) as resp:
            final=resp.geturl()
            if not safe_url(final):
                return {'status':'rejected_redirect','error':'Redirect left allowlist'}
            ctype=resp.headers.get('Content-Type','')
            digest=hashlib.sha256(); chunks=[]; size=0
            while True:
                block=resp.read(65536)
                if not block: break
                size+=len(block)
                if size>MAX_BYTES:
                    return {'status':'oversize','http_status':getattr(resp,'status',None),
                            'size_bytes_at_least':size,'max_bytes':MAX_BYTES,'error':'Exceeds 8MB limit'}
                digest.update(block); chunks.append(block)
            raw=b''.join(chunks)
            if 'html' not in ctype.lower():
                return {'status':'unsupported_content_type','content_type':ctype,'size_bytes':size,
                        'sha256':digest.hexdigest(),'error':'Not HTML'}
            parser=Extract(); parser.feed(raw.decode('utf-8',errors='replace'))
            visible=' '.join(' '.join(parser.parts).split())
            candidates=[]
            for kind,regex in PATTERNS.items():
                for match in list(regex.finditer(visible))[:12]:
                    a=max(0,match.start()-85); b=min(len(visible),match.end()+85)
                    candidates.append({'kind':kind,'matched_text':match.group(),
                                       'context':visible[a:b], 'verification':'unverified_candidate'})
            return {'status':'retrieved','http_status':getattr(resp,'status',200),'final_url':final,
                    'content_type':ctype,'size_bytes':size,'sha256':digest.hexdigest(),
                    'title':' '.join(' '.join(parser.title).split())[:200],
                    'retrieved_at_utc':dt.datetime.now(dt.timezone.utc).isoformat(),
                    'candidates':candidates,'candidate_count':len(candidates),'error':None}
    except (urllib.error.URLError,TimeoutError,OSError,ValueError) as exc:
        return {'status':'fetch_error','error':str(exc)[:250]}

def audit(source,fetcher=fetch_extract):
    if (not source.get('input_valid') or not str(source.get('model_version','')).startswith('eur-rc7.5-')
        or source.get('eligible_count')!=0 or source.get('verified_point_in_time_events')!=0
        or source.get('relative_score') is not None
        or any(e.get('available_asof_utc') is not None or e.get('point_in_time_usable')
               for e in source.get('publication_events',[]))):
        raise ValueError('Unsafe or unexpected RC7.5 input')
    documents=[]
    for d in source.get('source_document_audit',[]):
        url=d.get('source_url')
        if not url: continue
        evidence=fetcher(url)
        documents.append({'factor':d.get('factor'),'label':d.get('label'),'source_url':url,
                          'previous_status':d.get('status'),**evidence,
                          'publication_timestamp_verified':False,
                          'first_release_value_verified':False,
                          'point_in_time_usable':False})
    events=[]
    for e in source.get('publication_events',[]):
        record=dict(e)
        record.update(release_timestamp_utc=None,release_timestamp_verified=False,
                      first_release_value=None,first_release_value_verified=False,
                      available_asof_utc=None,point_in_time_usable=False)
        events.append(record)
    return {'model_version':VERSION,'asof_utc':dt.datetime.now(dt.timezone.utc).isoformat(),
            'asset':'EUR/USD','module':'document_evidence_extraction',
            'input_model_version':source['model_version'],'input_valid':True,
            'documents_attempted':len(documents),
            'documents_retrieved':sum(d['status']=='retrieved' for d in documents),
            'documents':documents,'publication_events':events,
            'factor_audit':{f:{'documents_attempted':sum(d['factor']==f for d in documents),
                               'documents_retrieved':sum(d['factor']==f and d['status']=='retrieved' for d in documents),
                               'eligible':False} for f in FACTORS},
            'verified_point_in_time_events':0,'historical_first_release_vintages_verified':False,
            'historical_release_timestamps_verified':False,'point_in_time_integrity_verified':False,
            'eligibility':{f:False for f in FACTORS},'eligible_count':0,'coverage':0.0,
            'relative_score':None,'horizons':{'1d':{'score':None},'5d':{'score':None}},
            'point_in_time_backtest_authorized':False,'signals_generated':False,
            'database_writes':False,'production_change_authorized':False,'source_code_modified':False,
            'next_step':'Review event-specific candidate excerpts against original archived releases and first-release datasets.',
            'limitations':['Regex candidates may be unrelated to target economic event.',
                           'HTML retrieval today does not prove historical first-publication time.',
                           'General index pages are discovery only, not event-specific proof.',
                           'No timestamps or first-release values are automatically verified.',
                           'No scores, signals, backtests or production changes.']}

def self_test():
    from io import BytesIO
    class Response:
        status=200
        headers={'Content-Type':'text/html; charset=UTF-8'}
        def __init__(self,body): self.f=BytesIO(body)
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def geturl(self): return 'https://www.bls.gov/news.release/archives/empsit_12162025.htm'
        def read(self,n): return self.f.read(n)
    body=b'<html><title>Official Release</title><body>December 16, 2025 at 08:30 ET rate 4.5 percent</body></html>'
    result=fetch_extract('https://www.bls.gov/news.release/archives/empsit_12162025.htm',lambda req,timeout:Response(body))
    assert result['status']=='retrieved' and result['sha256']==hashlib.sha256(body).hexdigest()
    assert result['candidate_count']>=2
    assert fetch_extract('https://evil.example/')['status']=='rejected_untrusted_url'
    sample={'model_version':'eur-rc7.5-test','input_valid':True,'eligible_count':0,
            'verified_point_in_time_events':0,'relative_score':None,
            'source_document_audit':[{'factor':'unemployment','label':'BLS','source_url':'https://www.bls.gov/news.release/archives/empsit_12162025.htm','status':'oversize'}],
            'publication_events':[{'factor':'unemployment','available_asof_utc':None,'point_in_time_usable':False}]}
    out=audit(sample,lambda url:result)
    assert out['documents_retrieved']==1 and out['eligible_count']==0
    assert out['publication_events'][0]['available_asof_utc'] is None
    assert not out['point_in_time_backtest_authorized']
    print('RC76_SELF_TEST_OK')

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--input',default='eur_rc75_result.json')
    p.add_argument('--output',default='eur_rc76_result.json')
    p.add_argument('--self-test',action='store_true')
    args=p.parse_args()
    if args.self_test: self_test(); return
    source=json.loads(Path(args.input).read_text(encoding='utf-8'))
    out=audit(source)
    Path(args.output).write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(f"RC7.6: {out['documents_retrieved']}/{out['documents_attempted']} documents; 0 PIT verified")
if __name__=='__main__': main()
