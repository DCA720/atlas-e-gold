#!/usr/bin/env python3
"""Atlas EUR RC7.2: industrial production source audit; read-only, no scoring."""
import argparse
import datetime as dt
import json
import os
import sys
import urllib.parse
import urllib.request

VERSION = 'eur-rc7.2-industrial-production-audit-0.7.2'
EU_PARAMS = {'freq':'M','indic_bt':'PRD','nace_r2':'B-D','s_adj':'SCA','unit':'I21','geo':'EA21','sinceTimePeriod':'2023-01','lang':'EN'}
EU_URL = 'https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/sts_inpr_m?' + urllib.parse.urlencode(EU_PARAMS)
US_SERIES = 'INDPRO'
US_URL = 'https://fred.stlouisfed.org/series/INDPRO'

def get_json(url):
    req=urllib.request.Request(url, headers={'User-Agent':'AtlasEUR-Research/0.7.2 (read-only)','Accept':'application/json'})
    with urllib.request.urlopen(req,timeout=35) as r:
        return json.load(r)

def extract_eurostat(data):
    dims=data.get('id',[]); sizes=data.get('size',[])
    if 'time' not in [str(x).lower() for x in dims]:
        raise ValueError('Eurostat time dimension absent')
    time_key=next(k for k in dims if str(k).lower()=='time')
    tpos=dims.index(time_key)
    for k in dims:
        if k==time_key: continue
        if int(sizes[dims.index(k)])!=1: raise ValueError('Ambiguous Eurostat dimension '+str(k))
    cats=data['dimension'][time_key]['category']['index']
    if isinstance(cats,dict): pairs=list(cats.items())
    elif isinstance(cats,list): pairs=[(v,i) for i,v in enumerate(cats)]
    else: raise ValueError('Invalid time index')
    values=data.get('value',{})
    output={}
    for period,i in pairs:
        flat=int(i)
        for sz in sizes[tpos+1:]: flat*=int(sz)
        raw=values.get(str(flat)) if isinstance(values,dict) else (values[flat] if flat<len(values) else None)
        if raw is not None: output[str(period)]=float(raw)
    return dict(sorted(output.items()))

def extract_fred(data):
    result={}
    for obs in data.get('observations',[]):
        val=obs.get('value')
        if val in (None,'.',''): continue
        result[obs['date'][:7]]=float(val)
    return dict(sorted(result.items()))

def month_number(s):
    y,m=map(int,s.split('-')); return y*12+m

def changes(series):
    keys=sorted(series)
    out=[]
    for a,b in zip(keys,keys[1:]):
        consecutive=month_number(b)-month_number(a)==1
        out.append({'from_period':a,'to_period':b,'consecutive':consecutive,
                    'mom_pct':round((series[b]/series[a]-1)*100,6) if consecutive and series[a] else None})
    return out

def yoy(series):
    out={}
    for p,v in series.items():
        y,m=map(int,p.split('-')); prev=f'{y-1:04d}-{m:02d}'
        if prev in series and series[prev]: out[p]=round((v/series[prev]-1)*100,6)
    return out

def audit(eu,us,eu_meta=None,us_meta=None):
    common=sorted(set(eu)&set(us)); e_yoy=yoy(eu); u_yoy=yoy(us)
    comparable=sorted(set(e_yoy)&set(u_yoy))
    latest=common[-1] if common else None
    latest_yoy=comparable[-1] if comparable else None
    return {
      'model_version':VERSION,'asof_utc':dt.datetime.now(dt.timezone.utc).isoformat(), 'asset':'EUR/USD','module':'EU_US_industrial_production',
      'methodology':{'eu':{'dataset':'sts_inpr_m','dimensions':EU_PARAMS,'index_base':'2021=100','adjustment':'seasonal_and_calendar_adjusted'},
                     'us':{'series':'INDPRO','index_base':'2017=100','adjustment':'seasonally_adjusted'},
                     'index_levels_directly_comparable':False,'growth_rates_methodologically_equivalent_verified':False,
                     'industry_scope_and_calendar_adjustment_equivalence_verified':False,
                     'historical_first_release_vintages_verified':False,'release_timestamps_verified':False},
      'sources':{'eu':{'status':'ok','url':EU_URL,'count':len(eu),'latest_period':max(eu) if eu else None,'latest_index':eu[max(eu)] if eu else None,'metadata_updated':(eu_meta or {}).get('updated')},
                 'us':{'status':'ok','url':US_URL,'count':len(us),'latest_period':max(us) if us else None,'latest_index':us[max(us)] if us else None,'metadata_title':(us_meta or {}).get('title'),'metadata_units':(us_meta or {}).get('units'),'metadata_frequency':(us_meta or {}).get('frequency'),'metadata_seasonal_adjustment':(us_meta or {}).get('seasonal_adjustment')}},
      'continuity':{'eu_nonconsecutive': [c for c in changes(eu) if not c['consecutive']], 'us_nonconsecutive':[c for c in changes(us) if not c['consecutive']]},
      'comparison':{'aligned_months':len(common),'latest_common_period':latest,
                    'latest_common_indices':{'eu':eu[latest],'us':us[latest]} if latest else None,
                    'latest_common_yoy_period':latest_yoy,
                    'latest_common_yoy_pct':{'eu':e_yoy[latest_yoy],'us':u_yoy[latest_yoy],'eu_minus_us_pp':round(e_yoy[latest_yoy]-u_yoy[latest_yoy],6)} if latest_yoy else None,
                    'recent_aligned_yoy':[{'period':p,'eu_yoy_pct':e_yoy[p],'us_yoy_pct':u_yoy[p]} for p in comparable[-12:]],
                    'descriptive_only':True,'trading_signal':False},
      'quality_gates':{'source_data_both_ok':True,'historical_first_release_vintages_verified':False,'release_timestamps_verified':False,
                       'point_in_time_backtest_authorized':False},
      'eligibility':{'inflation':False,'rates':False,'unemployment':False,'activity':False},
      'eligible_count':0,'coverage':0.0,'relative_score':None,'horizons':{'1d':{'score':None},'5d':{'score':None}},
      'point_in_time_backtest_authorized':False,'signals_generated':False,'database_writes':False,
      'production_change_authorized':False,'source_code_modified':False,
      'limitations':['Different index base years: compare growth rates, never raw index levels.',
                     'Eurostat seasonally and calendar adjusted; US seasonally adjusted; not identical.',
                     'Industrial coverage and statistical methods differ; no equivalence certified.',
                     'Observation month is not publication time; no point-in-time history established.',
                     'No scores, signals, backtests or database writes.']}

def selftest():
    toy={'id':['freq','time'],'size':[1,3],'dimension':{'time':{'category':{'index':{'2025-01':0,'2025-02':1,'2025-03':2}}}},'value':{'0':100,'1':101,'2':102}}
    assert extract_eurostat(toy)=={'2025-01':100.,'2025-02':101.,'2025-03':102.}
    assert extract_fred({'observations':[{'date':'2025-01-01','value':'100'},{'date':'2025-02-01','value':'.'}]})=={'2025-01':100.}
    assert changes({'2025-01':100,'2025-03':102})[0]['mom_pct'] is None
    assert yoy({'2025-01':100,'2026-01':105})['2026-01']==5
    x=audit({'2025-01':100,'2026-01':105},{'2025-01':100,'2026-01':102})
    assert x['comparison']['latest_common_yoy_pct']['eu_minus_us_pp']==3
    assert x['relative_score'] is None and not x['signals_generated']
    print('SELFTEST_OK')

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',default='eur_rc72_result.json');p.add_argument('--self-test',action='store_true');args=p.parse_args()
    if args.self_test: selftest();return
    key=os.environ.get('FRED_API_KEY','').strip()
    if not key: raise RuntimeError('FRED_API_KEY environment variable required')
    eu_data=get_json(EU_URL)
    eu=extract_eurostat(eu_data)
    base='https://api.stlouisfed.org/fred/'
    common={'api_key':key,'file_type':'json'}
    obs=get_json(base+'series/observations?'+urllib.parse.urlencode({**common,'series_id':US_SERIES,'observation_start':'2023-01-01'}))
    meta=get_json(base+'series?'+urllib.parse.urlencode({**common,'series_id':US_SERIES}))
    series_meta=(meta.get('seriess') or [{}])[0]
    us=extract_fred(obs)
    if not eu or not us: raise RuntimeError('Empty series: refusing to mark successful audit')
    report=audit(eu,us,eu_data,series_meta)
    with open(args.output,'w',encoding='utf-8') as f: json.dump(report,f,ensure_ascii=False,indent=2)
    print('RESULT_FILE='+args.output)
    print('EU_MONTHS='+str(len(eu))+' US_MONTHS='+str(len(us))+' ALIGNED='+str(report['comparison']['aligned_months']))
    print('LATEST_COMMON='+str(report['comparison']['latest_common_period']))
    print('SCORE_BLOCKED='+str(report['relative_score'] is None))

if __name__=='__main__':main()
