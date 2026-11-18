#!/usr/bin/env python3
"""Atlas EUR RC7.1: unemployment continuity and release evidence audit (read only)."""
import argparse, datetime as dt, json, os, urllib.parse, urllib.request
from pathlib import Path

VERSION = 'eur-rc7.1-unemployment-continuity-audit-0.7.1'
EU_URL = 'https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/une_rt_m?'+urllib.parse.urlencode({'freq':'M','s_adj':'SA','unit':'PC_ACT','age':'TOTAL','sex':'T','geo':'EA21','sinceTimePeriod':'2024-01','lang':'EN'})
BLS_SOURCE = 'https://www.bls.gov/cps/methods/2025-federal-government-shutdown-impact-cps.htm'
BLS_ARCHIVE = 'https://www.bls.gov/news.release/archives/empsit_12162025.htm'
FRED_ENDPOINT = 'https://api.stlouisfed.org/fred/series/observations'

def fetch_json(url):
    req=urllib.request.Request(url,headers={'User-Agent':'AtlasEUR-RC71/0.7.1 research audit','Accept':'application/json'})
    with urllib.request.urlopen(req,timeout=35) as response:
        return json.load(response)

def parse_eurostat(obj):
    dims=obj['id']; sizes=obj['size']; idx=obj['dimension']['time']['category']['index']
    if isinstance(idx,list): index={x:i for i,x in enumerate(idx)}
    else: index=idx
    tpos=dims.index('time'); values=obj.get('value',{})
    out={}
    for period,ti in index.items():
        # Other dimensions are singleton by the constrained query.
        stride=1
        for s in sizes[tpos+1:]: stride*=s
        raw=values.get(str(int(ti)*stride))
        if raw is not None: out[period]=float(raw)
    return dict(sorted(out.items()))

def parse_fred(obj):
    out={}
    for row in obj['observations']:
        val=row.get('value','.')
        if val not in ('.','',None):
            out[row['date'][:7]]=float(val)
    return dict(sorted(out.items()))

def next_month(month):
    y,m=map(int,month.split('-')); return f'{y+1:04d}-01' if m==12 else f'{y:04d}-{m+1:02d}'

def months_between(first,last):
    out=[]; cur=first
    while cur<=last:
        out.append(cur);cur=next_month(cur)
    return out

def audit_changes(series):
    result=[]; prev=None
    for month,value in sorted(series.items()):
        if prev:
            pm,pv=prev
            consecutive=next_month(pm)==month
            result.append({'from_period':pm,'to_period':month,'from_pct':pv,'to_pct':value,'delta_pp':round(value-pv,6),'consecutive_months':consecutive,'valid_month_over_month_change':consecutive})
        prev=(month,value)
    return result

def run():
    now=dt.datetime.now(dt.timezone.utc).isoformat()
    result={'model_version':VERSION,'asof_utc':now,'asset':'EUR/USD','module':'EU_US_unemployment_temporal_audit','source_audit':{},'missing_period_audit':{},'release_evidence':{},'eligibility':{'inflation':False,'rates':False,'unemployment':False,'activity':False},'eligible_count':0,'coverage':0.0,'relative_score':None,'horizons':{'1d':{'score':None},'5d':{'score':None}},'point_in_time_backtest_authorized':False,'signals_generated':False,'database_writes':False,'production_change_authorized':False,'source_code_modified':False}
    eu=us={}
    try:
        eu=parse_eurostat(fetch_json(EU_URL))
        result['source_audit']['eurostat']={'status':'ok','url':EU_URL,'count':len(eu),'latest_period':max(eu) if eu else None,'latest_rate_pct':eu[max(eu)] if eu else None}
    except Exception as exc: result['source_audit']['eurostat']={'status':'error','error':str(exc)[:350]}
    key=os.environ.get('FRED_API_KEY','')
    if not key:
        result['source_audit']['fred']={'status':'missing_api_key','series_id':'UNRATE'}
    else:
        url=FRED_ENDPOINT+'?'+urllib.parse.urlencode({'series_id':'UNRATE','api_key':key,'file_type':'json','observation_start':'2024-01-01','observation_end':dt.date.today().isoformat()})
        try:
            us=parse_fred(fetch_json(url))
            result['source_audit']['fred']={'status':'ok','series_id':'UNRATE','count':len(us),'latest_period':max(us) if us else None,'latest_rate_pct':us[max(us)] if us else None,'source_url':'https://fred.stlouisfed.org/series/UNRATE'}
        except Exception as exc: result['source_audit']['fred']={'status':'error','error':str(exc)[:350]}
    for label,series in [('eu',eu),('us',us)]:
        missing=sorted(set(months_between(min(series),max(series)))-set(series)) if series else []
        changes=audit_changes(series)
        result['missing_period_audit'][label]={'missing_months':missing,'nonconsecutive_comparisons':[x for x in changes if not x['consecutive_months']],'last_changes':changes[-12:],'all_changes_count':len(changes)}
    result['release_evidence']={'us_2025_10':{'period':'2025-10','classification':'officially_uncollected_household_survey','reason':'2025 federal government funding lapse','bls_source_url':BLS_SOURCE,'bls_archive_url':BLS_ARCHIVE,'verified_by_live_page_retrieval':False,'official_documentary_reference_identified':True,'imputation_permitted':False,'consecutive_mom_comparison_permitted':False},'eurostat_release_calendar_url':'https://ec.europa.eu/eurostat/news/euro-indicators/release-calendar','eu_release_timestamps_verified':False,'us_first_release_timestamps_verified':False,'historical_first_release_vintages_verified':False,'note':'Reference links do not prove retrieval, original publication time, or original first-release values.'}
    common=sorted(set(eu)&set(us))
    result['comparison']={'aligned_period_count':len(common),'latest_common_period':common[-1] if common else None,'latest_common_eu_pct':eu[common[-1]] if common else None,'latest_common_us_pct':us[common[-1]] if common else None,'eu_minus_us_pp':round(eu[common[-1]]-us[common[-1]],6) if common else None,'descriptive_only':True}
    result['quality_gates']={'source_data_both_ok':bool(eu and us),'us_2025_10_absent':bool(us) and '2025-10' not in us,'us_missing_month_explained_by_official_bls':True,'no_interpolation':True,'nonconsecutive_changes_excluded_from_mom':True,'historical_release_timestamps_verified':False,'point_in_time_backtest_authorized':False}
    result['limitations']=['October 2025 US CPS household survey data were not collected; no interpolation.','A reference URL is not proof of having fetched or verified a historical press release.','Observation periods are not release timestamps.','Current data are not first-release vintages.','EU and US unemployment survey populations differ.','No scoring, trading signals, backtests, or database writes.']
    return result

def test():
    assert next_month('2025-12')=='2026-01'
    assert months_between('2025-09','2025-11')==['2025-09','2025-10','2025-11']
    a=audit_changes({'2025-09':4.4,'2025-11':4.5,'2025-12':4.4})
    assert a[0]['consecutive_months'] is False and a[1]['consecutive_months'] is True
    assert parse_fred({'observations':[{'date':'2025-10-01','value':'.'},{'date':'2025-11-01','value':'4.5'}]})=={'2025-11':4.5}
    assert parse_eurostat({'id':['freq','time'],'size':[1,2],'dimension':{'time':{'category':{'index':{'2025-09':0,'2025-10':1}}}},'value':{'0':6.5,'1':6.4}})=={'2025-09':6.5,'2025-10':6.4}
    print('RC7.1 mock tests passed')

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--test',action='store_true');parser.add_argument('--output',default='eur_rc71_result.json');args=parser.parse_args()
    if args.test: test()
    else:
        data=run();Path(args.output).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps({'model_version':data['model_version'],'source_statuses':{k:v['status'] for k,v in data['source_audit'].items()},'output':args.output}))
