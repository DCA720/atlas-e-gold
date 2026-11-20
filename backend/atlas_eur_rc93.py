#!/usr/bin/env python3
"""Atlas EUR RC9.3: prospective Eurostat/FRED paired macro collection, no signals."""
import argparse, hashlib, json, os, re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

VERSION='eur-rc9.3-official-paired-macro-collection-0.9.3'
EU_BASE='https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/'
FRED_BASE='https://api.stlouisfed.org/fred/series/observations'
# EA21 is the 2026 euro area. Never silently substitute EA19 or EA20.
EU={
 'inflation':('prc_hicp_midx',{'freq':'M','geo':'EA21','coicop':'CP00','unit':'I25'}),
 'activity':('sts_inpr_m',{'freq':'M','geo':'EA21','indic_bt':'PRD','nace_r2':'B-D','s_adj':'SCA','unit':'I21'}),
 'unemployment':('une_rt_m',{'freq':'M','geo':'EA21','sex':'T','age':'TOTAL','s_adj':'SA','unit':'PC_ACT'}),
}
US={'inflation':'CPIAUCSL','activity':'INDPRO','unemployment':'UNRATE'}

def fetch_json(url):
    started=datetime.now(timezone.utc)
    req=Request(url,headers={'Accept':'application/json','User-Agent':'Atlas-EUR-Research/0.9.3'})
    with urlopen(req,timeout=40) as r: raw=r.read(2_500_001)
    received=datetime.now(timezone.utc)
    if len(raw)>2_500_000: raise ValueError('response_too_large')
    data=json.loads(raw)
    if not isinstance(data,dict): raise ValueError('unexpected_response')
    return data,{'request_started_at_utc':started.isoformat(),'response_received_at_utc':received.isoformat(),
                 'response_sha256':hashlib.sha256(raw).hexdigest(),'response_bytes':len(raw)}

def decode_jsonstat(data):
    ids=data.get('id'); sizes=data.get('size'); dimensions=data.get('dimension'); vals=data.get('value')
    if not isinstance(ids,list) or not isinstance(sizes,list) or not isinstance(dimensions,dict) or not isinstance(vals,(dict,list)) or len(ids)!=len(sizes):
        raise ValueError('invalid_jsonstat_shape')
    if 'time' not in ids: raise ValueError('missing_time_dimension')
    # Filtered requests should have a single category in every non-time dimension.
    for name,size in zip(ids,sizes):
        if name!='time' and size!=1: raise ValueError('ambiguous_dimension_'+name)
    dim=dimensions['time']['category']['index']
    if isinstance(dim,dict): pairs=sorted(dim.items(),key=lambda x:x[1])
    elif isinstance(dim,list): pairs=list(enumerate(dim)); pairs=[(v,i) for i,v in pairs]
    else: raise ValueError('invalid_time_index')
    time_pos=ids.index('time'); stride=1
    for size in sizes[time_pos+1:]: stride*=size
    result=[]
    for label,idx in pairs:
        offset=idx*stride
        value=vals.get(str(offset)) if isinstance(vals,dict) else (vals[offset] if offset<len(vals) else None)
        if value is not None and re.fullmatch(r'\d{4}-\d{2}',str(label)):
            result.append({'period':label,'value':float(value)})
    return sorted(result,key=lambda x:x['period'])[-15:]

def get_eu(factor,fetch):
    dataset,params=EU[factor]
    url=EU_BASE+dataset+'?'+urlencode({**params,'lang':'EN','sinceTimePeriod':'2024-01'})
    data,audit=fetch(url)
    points=decode_jsonstat(data)
    if not points: raise ValueError('no_matching_observations')
    return {'status':'ok','dataset':dataset,'region':'EA21','selection':params,'source_url':url,
            'observations':points,'audit':audit,'provider_updated':data.get('updated'),
            'first_publication_time_verified':False}

def get_us(factor,key,fetch):
    sid=US[factor]
    url=FRED_BASE+'?'+urlencode({'series_id':sid,'api_key':key,'file_type':'json','sort_order':'desc','limit':18})
    data,audit=fetch(url)
    if 'error_code' in data: raise ValueError('fred_api_error')
    points=[]
    for o in data.get('observations',[]):
        if re.fullmatch(r'\d{4}-\d{2}-\d{2}',str(o.get('date',''))) and o.get('value') not in ('.',None):
            points.append({'period':o['date'][:7],'value':float(o['value']),
                           'realtime_start':o.get('realtime_start')})
    points=sorted(points,key=lambda x:x['period'])[-15:]
    if not points: raise ValueError('no_matching_observations')
    return {'status':'ok','series_id':sid,'region':'US','source_url':FRED_BASE.split('?')[0],
            'observations':points,'audit':audit,'first_publication_time_verified':False}

def latest_change(points,mode):
    if len(points)<2: return None
    a,b=points[-2]['value'],points[-1]['value']
    if mode=='percentage_points': return round(b-a,5)
    if a==0: return None
    return round((b/a-1)*100,5)

def collect(key,fetch=fetch_json,now=None):
    now=(now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    rows={}; diagnostics={}
    for factor in US:
        rows[factor]={}
        for region in ('US','EA'):
            try:
                rows[factor][region]=get_us(factor,key,fetch) if region=='US' else get_eu(factor,fetch)
            except Exception as exc:
                rows[factor][region]={'status':'error','error_type':type(exc).__name__,'error_message':str(exc)[:200]}
        us,ea=rows[factor]['US'],rows[factor]['EA']
        if us['status']=='ok' and ea['status']=='ok':
            mode='percentage_points' if factor=='unemployment' else 'percentage_change'
            diagnostics[factor]={'status':'candidate_pair_collected','transformation':mode,
               'us_latest_period':us['observations'][-1]['period'],'ea_latest_period':ea['observations'][-1]['period'],
               'us_latest_change':latest_change(us['observations'],mode),
               'ea_latest_change':latest_change(ea['observations'],mode),
               'directional_score_authorized':False,
               'note':'Different release calendars and methods; changes are descriptive only, not directional signals.'}
        else: diagnostics[factor]={'status':'incomplete_pair','directional_score_authorized':False}
    return {'model_version':VERSION,'asset':'EUR/USD','generated_at_utc':now.isoformat(),
      'generated_at_brt':now.astimezone(ZoneInfo('America/Sao_Paulo')).isoformat(),
      'reference_time_brt':'04:00','official_sources':{'EA':'Eurostat','US':'FRED'},
      'series':rows,'paired_diagnostics':diagnostics,
      'successful_series':sum(v['status']=='ok' for r in rows.values() for v in r.values()),
      'requested_series':6,'comparability_verified':False,'first_publication_time_verified':False,
      'historical_pit_verified':False,'fixed_predictions_written':False,
      'experimental_bias':{'day':'indisponivel','week':'indisponivel','month':'indisponivel'},
      'research_only':True,'signals_generated':False,'backtests_authorized':False,
      'database_writes':False,'production_change_authorized':False,
      'limitations':['Eurostat live API does not provide historical revisions in this endpoint.',
       'Collector receive time does not establish original release time.',
       'US CPI and EA HICP have different definitions; comparisons are descriptive only.',
       'No retroactive 04:00 forecasts or persisted predictions.']}

def self_test():
    cube={'id':['geo','time'],'size':[1,3],'dimension':{'time':{'category':{'index':{'2026-08':0,'2026-09':1,'2026-10':2}}}},'value':{'0':101.0,'2':103.0}}
    assert decode_jsonstat(cube)==[{'period':'2026-08','value':101.0},{'period':'2026-10','value':103.0}]
    assert latest_change([{'value':100},{'value':102}],'percentage_change')==2
    assert latest_change([{'value':4.2},{'value':4.1}],'percentage_points')==-0.1
    assert all(v[1]['geo']=='EA21' for v in EU.values())
    print('RC93_SELF_TEST_OK')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--self-test',action='store_true');p.add_argument('--output',default='eur_rc93_result.json');a=p.parse_args()
    if a.self_test: self_test()
    else:
        key=os.getenv('FRED_API_KEY','').strip()
        if not key: raise SystemExit('FRED_API_KEY is required')
        result=collect(key);Path(a.output).write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
        print('RC93_OK',result['successful_series'],'/',result['requested_series'])
