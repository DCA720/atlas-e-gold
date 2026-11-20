#!/usr/bin/env python3
"""Atlas EUR RC8.7: capture actual historical source evidence (research-only).

Never equates current retrieval, HTTP headers, or ALFRED daily vintage with
independently witnessed first dissemination. Writes local artifacts only.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.parse import urlencode
from urllib.error import HTTPError, URLError

VERSION = 'eur-rc8.7-historical-evidence-acquisition-0.8.7'
FACTORS = ('inflation','rates','unemployment','activity')
VINTAGES = [
 ('US_UNRATE_2025-11_BLS','UNRATE','2025-12-16','2025-11-01'),
 ('US_FOMC_2026-09-16','DFEDTARL','2026-09-18','2026-09-17'),
 ('US_FOMC_2026-09-16','DFEDTARU','2026-09-18','2026-09-17'),
 ('EU_ECB_2026-09-10','ECBDFR','2026-09-17','2026-09-16'),
 ('EU_INDUSTRY_2026-09','INDPRO','2026-11-18','2026-09-01'),
]

def utcnow():
    return datetime.now(timezone.utc).isoformat()

def fetch(url, *, timeout=18):
    start=utcnow()
    try:
        req=Request(url,headers={'User-Agent':'AtlasEUR-ResearchAudit/0.8.7 (historical-document-capture)','Accept':'text/html,application/json,application/pdf,*/*'})
        with urlopen(req,timeout=timeout) as resp:
            data=resp.read(8_000_001)
            if len(data)>8_000_000:
                return {'status':'too_large','requested_at_utc':start,'received_at_utc':utcnow()},None
            return {'status':'retrieved','http_status':resp.status,'requested_at_utc':start,'received_at_utc':utcnow(),
                    'final_url':resp.url.split('?')[0], 'content_type':resp.headers.get('Content-Type'),
                    'last_modified':resp.headers.get('Last-Modified')},data
    except (HTTPError,URLError,TimeoutError,OSError) as exc:
        return {'status':'request_failed','error_type':type(exc).__name__,'requested_at_utc':start,'received_at_utc':utcnow()},None

def store(rawdir, filename, data):
    path=rawdir/filename
    path.write_bytes(data)
    return {'path':str(path),'sha256':hashlib.sha256(data).hexdigest(),'size_bytes':len(data)}

def build(source, rawdir, online=False, api_key=None):
    matrix=source.get('event_matrix',[])
    ids=[e.get('event_id') for e in matrix]
    valid=(source.get('model_version','').startswith('eur-rc8.6-') and source.get('input_valid') is True
           and source.get('eligible_count')==0 and source.get('coverage')==0.0
           and source.get('relative_score') is None and len(matrix)==7 and len(set(ids))==7
           and all(not e.get('point_in_time_usable',True) for e in matrix))
    if not valid: raise ValueError('RC8.6 input invalid or safety gate failed')
    rawdir.mkdir(parents=True,exist_ok=True)
    records=[]
    for event in matrix:
        eid=event['event_id']
        # The prior RC8.5 event source URLs are specific official historical releases.
        url=event.get('prior_official_source_url')
        # The source catalog lists index pages, not the event-specific archived releases.
        url=url or RELEASE_URLS[eid]
        meta,body=fetch(url) if online else ({'status':'offline_not_attempted'},None)
        entry={'event_id':eid,'factor':event.get('factor'),'evidence_kind':'official_archived_release_page',
               'source_url':url,'retrieval':meta,'archived_at_audit_not_first_release':True,
               'original_full_dataset_verified':False,'independent_first_dissemination_verified':False,
               'point_in_time_usable':False}
        if body is not None: entry['raw_capture']=store(rawdir,'release_'+eid+'.bin',body)
        records.append(entry)
    for eid,series,vintage,observation in VINTAGES:
        if not api_key or not online:
            meta,body={'status':'missing_key_or_offline'},None
        else:
            params={'series_id':series,'api_key':api_key,'file_type':'json','realtime_start':vintage,
                    'realtime_end':vintage,'observation_start':observation,'observation_end':observation}
            meta,body=fetch('https://api.stlouisfed.org/fred/series/observations?'+urlencode(params))
        entry={'event_id':eid,'evidence_kind':'alfred_date_granularity_vintage','series_id':series,
               'vintage_date':vintage,'observation_date':observation,'retrieval':meta,
               'original_full_dataset_verified':False,'independent_first_dissemination_verified':False,
               'point_in_time_usable':False}
        if body is not None:
            entry['raw_capture']=store(rawdir,'alfred_'+series+'_'+vintage+'.json',body)
            try:
                parsed=json.loads(body)
                obs=parsed.get('observations',[])
                entry['observations']=[{'date':o.get('date'),'value':o.get('value')} for o in obs[:3]]
                entry['response_has_api_error']=bool(parsed.get('error_code'))
            except (ValueError,AttributeError): entry['response_parse_error']=True
        records.append(entry)
    return {'model_version':VERSION,'asset':'EUR/USD','module':'historical_evidence_acquisition',
            'asof_utc':utcnow(),'input_valid':True,'network_enabled':online,
            'records':records,'events_reviewed':len(matrix),'retrievals_attempted':len(records) if online else 0,
            'raw_evidence_files':sum('raw_capture' in r for r in records),
            'release_pages_captured':sum(r['evidence_kind']=='official_archived_release_page' and 'raw_capture' in r for r in records),
            'alfred_vintages_captured':sum(r['evidence_kind']=='alfred_date_granularity_vintage' and 'raw_capture' in r for r in records),
            'verified_point_in_time_events':0,'historical_first_release_vintages_verified':False,
            'historical_release_timestamps_verified':False,'point_in_time_integrity_verified':False,
            'eligibility':{f:False for f in FACTORS},'eligible_count':0,'coverage':0.0,'relative_score':None,
            'horizons':{'1d':{'score':None},'5d':{'score':None}},'point_in_time_backtest_authorized':False,
            'signals_generated':False,'database_writes':False,'production_change_authorized':False,
            'source_code_modified':False,'prospective_capture_active':False,
            'methodology_note':'Raw files are captured at audit time. Historical dates and ALFRED vintages do not prove intraday first dissemination or full original release datasets.',
            'next_step':'Inspect captured raw evidence and pursue timestamped third-party historical release archives; separately verify concept/unit and original release tables.'}

RELEASE_URLS={
 'US_UNRATE_2025-11_BLS':'https://www.bls.gov/news.release/archives/empsit_12162025.htm',
 'US_FOMC_2026-09-16':'https://www.federalreserve.gov/newsevents/pressreleases/monetary20260916a.htm',
 'EU_ECB_2026-09-10':'https://www.ecb.europa.eu/press/pr/date/2026/html/ecb.mp260910~314e508016.en.html',
 'EU_HICP_2026-09_FLASH':'https://ec.europa.eu/eurostat/web/products-euro-indicators/w/2-02102026-ap',
 'EU_HICP_2026-09_FULL':'https://ec.europa.eu/eurostat/en/web/products-euro-indicators/w/2-16102026-ap',
 'EU_HICP_2026-10_FLASH':'https://ec.europa.eu/eurostat/en/web/products-euro-indicators/w/2-04112026-ap',
 'EU_INDUSTRY_2026-09':'https://ec.europa.eu/eurostat/en/web/products-euro-indicators/w/4-16112026-ap',
}

def self_test():
    fake={'model_version':'eur-rc8.6-test','input_valid':True,'eligible_count':0,'coverage':0.0,
          'relative_score':None,'event_matrix':[{'event_id':k,'factor':'rates','point_in_time_usable':False} for k in RELEASE_URLS]}
    from tempfile import TemporaryDirectory
    with TemporaryDirectory() as d:
        r=build(fake,Path(d),False)
        assert r['events_reviewed']==7 and len(r['records'])==12 and r['raw_evidence_files']==0
        assert r['eligible_count']==0 and not r['signals_generated'] and not r['database_writes']
        assert all(not x['point_in_time_usable'] for x in r['records'])
    print('RC87_SELF_TEST_OK')

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--input',default='eur_rc86_result.json')
    p.add_argument('--output',default='eur_rc87_result.json')
    p.add_argument('--archive-dir',default='eur_rc87_archive')
    p.add_argument('--online',action='store_true')
    p.add_argument('--self-test',action='store_true')
    a=p.parse_args()
    if a.self_test: self_test();return
    src=json.loads(Path(a.input).read_text(encoding='utf-8'))
    result=build(src,Path(a.archive_dir),a.online,os.environ.get('FRED_API_KEY'))
    Path(a.output).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('RC87_OK',result['raw_evidence_files'],result['release_pages_captured'],result['alfred_vintages_captured'])

if __name__=='__main__':main()
