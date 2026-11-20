#!/usr/bin/env python3
"""Atlas EUR RC9.2: candidate macro series discovery and snapshot audit (research only)."""
import argparse, hashlib, json, os, re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

VERSION='eur-rc9.2-paired-macro-candidate-discovery-0.9.2'
BASE='https://api.stlouisfed.org/fred/'
# Explicit US benchmark candidates; euro-area counterparts require metadata review.
BENCHMARKS={'CPIAUCSL':('US','inflation'),'INDPRO':('US','activity'),'UNRATE':('US','unemployment'),
            'DFEDTARL':('US','rates'),'DFEDTARU':('US','rates'),'ECBDFR':('EA','rates')}
SEARCHES={
 'EA_inflation': 'Harmonized Index of Consumer Prices All Items Euro Area',
 'EA_activity': 'Industrial Production Euro Area',
 'EA_unemployment': 'Unemployment Rate Euro Area',
}

def request_json(endpoint,params,key):
    query=urlencode({**params,'api_key':key,'file_type':'json'})
    req=Request(BASE+endpoint+'?'+query,headers={'User-Agent':'Atlas-EUR-research/0.9.2','Accept':'application/json'})
    start=datetime.now(timezone.utc)
    with urlopen(req,timeout=30) as response:
        raw=response.read(1_500_001)
    end=datetime.now(timezone.utc)
    if len(raw)>1_500_000: raise ValueError('response_too_large')
    doc=json.loads(raw)
    if not isinstance(doc,dict) or 'error_code' in doc: raise ValueError('invalid_fred_response')
    return doc,{'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),
                'request_started_at_utc':start.isoformat(),'response_received_at_utc':end.isoformat()}

def sanitize_metadata(s):
    return {k:s.get(k) for k in ('id','title','units','frequency','seasonal_adjustment','observation_start','observation_end','last_updated','notes') if k in s and k!='notes'}

def collect(key,fetch=request_json,now=None):
    now=(now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    results=[]; discoveries=[]
    for sid,(region,factor) in BENCHMARKS.items():
        row={'series_id':sid,'region':region,'factor':factor,'status':'error'}
        try:
            meta,meta_audit=fetch('series',{'series_id':sid},key)
            entries=meta.get('seriess',[])
            if not entries or entries[0].get('id')!=sid: raise ValueError('series_metadata_missing')
            obs,obs_audit=fetch('series/observations',{'series_id':sid,'sort_order':'desc','limit':6},key)
            values=[]
            for o in obs.get('observations',[]):
                if isinstance(o,dict) and re.fullmatch(r'\d{4}-\d\d-\d\d',str(o.get('date',''))):
                    values.append({'date':o['date'],'value':o.get('value'),'realtime_start':o.get('realtime_start'),'realtime_end':o.get('realtime_end')})
            row.update(status='ok',metadata=sanitize_metadata(entries[0]),observations=values,metadata_response=meta_audit,observations_response=obs_audit)
        except Exception as exc: row.update(error_type=type(exc).__name__,error_message=str(exc)[:180])
        results.append(row)
    for target,term in SEARCHES.items():
        row={'target':target,'query':term,'status':'error','candidate_only':True}
        try:
            doc,audit=fetch('series/search',{'search_text':term,'limit':8,'order_by':'search_rank','sort_order':'asc'},key)
            candidates=[sanitize_metadata(s) for s in doc.get('seriess',[]) if isinstance(s,dict)]
            row.update(status='ok',candidates=candidates,response_audit=audit)
        except Exception as exc: row.update(error_type=type(exc).__name__,error_message=str(exc)[:180])
        discoveries.append(row)
    return {'model_version':VERSION,'asset':'EUR/USD','generated_at_utc':now.isoformat(),
        'generated_at_brt':now.astimezone(ZoneInfo('America/Sao_Paulo')).isoformat(),
        'reference_time_brt':'04:00','benchmark_series':results,'euro_area_discovery':discoveries,
        'successful_benchmarks':sum(r['status']=='ok' for r in results),
        'successful_searches':sum(r['status']=='ok' for r in discoveries),
        'metadata_verified_by_provider':False,'paired_comparability_verified':False,
        'first_publication_time_verified':False,'historical_pit_verified':False,
        'fixed_predictions_written':False,'experimental_bias':{'day':'indisponivel','week':'indisponivel','month':'indisponivel'},
        'research_only':True,'signals_generated':False,'backtests_authorized':False,'database_writes':False,
        'production_change_authorized':False,
        'limitations':['Search results are candidates, not confirmed equivalent indicators.',
        'US CPI and industrial-production indices are not directly comparable to euro-area growth rates.',
        'ALFRED realtime dates are day-granularity; collection timestamps do not prove first publication.',
        'No fixed 04:00 predictions are retroactively generated from this run.']}

def self_test():
    def fake(endpoint,params,key):
        stamp={'sha256':'a'*64,'bytes':99,'request_started_at_utc':'2026-11-20T07:00:00+00:00','response_received_at_utc':'2026-11-20T07:00:01+00:00'}
        if endpoint=='series': return {'seriess':[{'id':params['series_id'],'title':'Test','units':'Percent'}]},stamp
        if endpoint=='series/observations': return {'observations':[{'date':'2026-11-19','value':'3.1'}]},stamp
        return {'seriess':[{'id':'CANDIDATE','title':'Test candidate'}]},stamp
    r=collect('test',fake,datetime(2026,11,20,tzinfo=timezone.utc))
    assert r['successful_benchmarks']==6 and r['successful_searches']==3
    assert not r['fixed_predictions_written'] and not r['signals_generated']
    assert all(x=='indisponivel' for x in r['experimental_bias'].values())
    print('RC92_SELF_TEST_OK')

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',default='eur_rc92_result.json');p.add_argument('--self-test',action='store_true');a=p.parse_args()
    if a.self_test: self_test();return
    key=os.getenv('FRED_API_KEY','').strip()
    if not key: raise SystemExit('FRED_API_KEY missing')
    result=collect(key)
    Path(a.output).write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print('RC92_RESULTS',result['successful_benchmarks'],'benchmarks',result['successful_searches'],'searches')
    if result['successful_benchmarks']!=len(BENCHMARKS) or result['successful_searches']!=len(SEARCHES):
        raise SystemExit('Partial collection: inspect artifact')
if __name__=='__main__':main()
