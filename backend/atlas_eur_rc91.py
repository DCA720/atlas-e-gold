#!/usr/bin/env python3
"""Atlas EUR RC9.1: prospective FRED collector, research-only, no fabricated macro bias."""
import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

VERSION = 'eur-rc9.1-prospective-macro-collection-0.9.1'
# Explicitly mapped series; none alone provides a defensible EUR/USD macro score.
SERIES = {
    'UNRATE': {'region':'US','factor':'unemployment','concept':'civilian unemployment rate','unit':'percent','frequency':'monthly'},
    'DFEDTARL': {'region':'US','factor':'rates','concept':'federal funds target range lower bound','unit':'percent','frequency':'daily'},
    'DFEDTARU': {'region':'US','factor':'rates','concept':'federal funds target range upper bound','unit':'percent','frequency':'daily'},
    'ECBDFR': {'region':'EA','factor':'rates','concept':'ECB deposit facility rate','unit':'percent','frequency':'daily'},
}

def get_observations(series_id, key, limit=5):
    params = urlencode({'series_id':series_id,'api_key':key,'file_type':'json','sort_order':'desc','limit':limit})
    url = 'https://api.stlouisfed.org/fred/series/observations?' + params
    request = Request(url, headers={'User-Agent':'Atlas-EUR-research/0.9.1','Accept':'application/json'})
    with urlopen(request, timeout=25) as response:
        payload = response.read(2_000_001)
        if len(payload)>2_000_000: raise ValueError('Oversized FRED response')
    doc = json.loads(payload)
    if not isinstance(doc.get('observations'),list): raise ValueError('No observations array')
    observations=[]
    for o in doc['observations']:
        if not isinstance(o,dict): continue
        date=o.get('date'); value=o.get('value')
        if isinstance(date,str) and isinstance(value,str):
            observations.append({'observation_date':date,'value':value,'realtime_start':o.get('realtime_start'),'realtime_end':o.get('realtime_end')})
    return observations, hashlib.sha256(payload).hexdigest(), len(payload)

def collect(key, fetch=get_observations, now=None):
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None: raise ValueError('now must have timezone')
    now=now.astimezone(timezone.utc)
    rows=[]
    for sid,meta in SERIES.items():
        start=datetime.now(timezone.utc)
        try:
            obs,digest,size=fetch(sid,key)
            end=datetime.now(timezone.utc)
            rows.append({'series_id':sid,**meta,'status':'ok','observations':obs,'response_sha256':digest,'response_bytes':size,
                         'request_started_at_utc':start.isoformat(),'response_received_at_utc':end.isoformat(),
                         'availability_interpretation':'Collector receive time is an upper bound, not original publication time'})
        except Exception as exc:
            rows.append({'series_id':sid,**meta,'status':'error','error_type':type(exc).__name__,
                         'error_message':str(exc)[:250],'request_started_at_utc':start.isoformat()})
    return {'model_version':VERSION,'asset':'EUR/USD','module':'prospective_macro_collection',
            'generated_at_utc':now.isoformat(),'generated_at_brt':now.astimezone(ZoneInfo('America/Sao_Paulo')).isoformat(),
            'reference_time_brt':'04:00','series':rows,'successful_series':sum(r['status']=='ok' for r in rows),
            'requested_series':len(rows),'macro_coverage_complete':False,'comparability_verified':False,
            'experimental_bias':{'day':'indisponivel','week':'indisponivel','month':'indisponivel'},
            'reason_no_bias':'Insufficient validated US/EA paired inflation, activity and employment inputs; no justified directional transformations',
            'immutable_prediction_written':False,'historical_pit_verified':False,'research_only':True,
            'signals_generated':False,'backtests_authorized':False,'database_writes':False,'production_change_authorized':False,
            'caveat':'GitHub artifact is a run-level snapshot, not durable append-only history. A separate persistence layer is required.'}

def self_test():
    def fake(sid,key): return ([{'observation_date':'2026-11-01','value':'2.5','realtime_start':'2026-11-01','realtime_end':'2026-11-20'}], 'a'*64, 100)
    r=collect('test',fake,datetime(2026,11,20,tzinfo=timezone.utc))
    assert r['successful_series']==4 and r['requested_series']==4
    assert r['experimental_bias']['day']=='indisponivel' and not r['signals_generated']
    assert not r['immutable_prediction_written'] and not r['macro_coverage_complete']
    print('RC91_SELF_TEST_OK')

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--output',default='eur_rc91_result.json')
    p.add_argument('--self-test',action='store_true')
    a=p.parse_args()
    if a.self_test: self_test(); return
    key=os.getenv('FRED_API_KEY','').strip()
    if not key: raise SystemExit('FRED_API_KEY missing: no request was made')
    result=collect(key)
    Path(a.output).write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print('RC91_COLLECTED',result['successful_series'],'/',result['requested_series'])
    if result['successful_series'] != result['requested_series']: raise SystemExit('Partial collection; inspect artifact')
if __name__=='__main__': main()
