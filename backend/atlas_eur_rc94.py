#!/usr/bin/env python3
"""Atlas EUR RC9.4: Eurostat dimension repair and aligned macro diagnostics; research only."""
import argparse, hashlib, json, os, re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

VERSION='eur-rc9.4-eurostat-dimension-repair-0.9.4'
EU_BASE='https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/'
FRED_BASE='https://api.stlouisfed.org/fred/series/observations'
EU={
 'inflation':('prc_hicp_midx',{'freq':'M','geo':'EA21','coicop':'CP00'},'unit',['I25','I15']),
 'activity':('sts_inpr_m',{'freq':'M','geo':'EA21','indic_bt':'PRD','nace_r2':'B-D','s_adj':'SCA','unit':'I21'},None,[]),
 'unemployment':('une_rt_m',{'freq':'M','geo':'EA21','sex':'T','age':'TOTAL','s_adj':'SA','unit':'PC_ACT'},None,[]),
}
US={'inflation':'CPIAUCSL','activity':'INDPRO','unemployment':'UNRATE'}

def fetch_json(url):
    started=datetime.now(timezone.utc)
    with urlopen(Request(url,headers={'Accept':'application/json','User-Agent':'Atlas-EUR-Research/0.9.4'}),timeout=40) as response:
        raw=response.read(2_500_001)
    received=datetime.now(timezone.utc)
    if len(raw)>2_500_000: raise ValueError('response_too_large')
    data=json.loads(raw)
    if not isinstance(data,dict): raise ValueError('unexpected_response')
    return data,{'request_started_at_utc':started.isoformat(),'response_received_at_utc':received.isoformat(),
                 'response_sha256':hashlib.sha256(raw).hexdigest(),'response_bytes':len(raw)}

def categories(dimension):
    index=dimension['category']['index']
    if isinstance(index,dict): return {str(k):int(v) for k,v in index.items()}
    if isinstance(index,list): return {str(k):i for i,k in enumerate(index)}
    raise ValueError('invalid_category_index')

def decode_jsonstat(data, selected=None):
    ids=data.get('id');sizes=data.get('size');dims=data.get('dimension');values=data.get('value')
    if not isinstance(ids,list) or not isinstance(sizes,list) or len(ids)!=len(sizes) or not isinstance(dims,dict) or not isinstance(values,(dict,list)) or 'time' not in ids:
        raise ValueError('invalid_jsonstat_shape')
    selected=selected or {}
    fixed={}; selection={}
    for name,size in zip(ids,sizes):
        if name=='time':continue
        cats=categories(dims[name])
        if name in selected:
            preferred=selected[name]
            if isinstance(preferred,str):preferred=[preferred]
            choice=next((v for v in preferred if v in cats),None)
            if choice is None:raise ValueError('requested_category_not_found_'+name+':'+','.join(cats))
        elif size==1:
            choice=next(iter(cats))
        else:
            raise ValueError('ambiguous_dimension_'+name+':'+','.join(cats))
        fixed[name]=cats[choice];selection[name]=choice
    timecats=categories(dims['time']);points=[]
    for period,tidx in timecats.items():
        if not re.fullmatch(r'\d{4}-\d{2}',period):continue
        coords={**fixed,'time':tidx};offset=0
        for name,size in zip(ids,sizes):offset=offset*size+coords[name]
        value=values.get(str(offset)) if isinstance(values,dict) else (values[offset] if offset<len(values) else None)
        if value is None:continue
        points.append({'period':period,'value':float(value)})
    return sorted(points,key=lambda x:x['period'])[-18:],selection

def get_eu(factor,fetch):
    dataset,params,select_dim,preferred=EU[factor]
    url=EU_BASE+dataset+'?'+urlencode({**params,'lang':'EN','sinceTimePeriod':'2024-01'})
    data,audit=fetch(url)
    points,selection=decode_jsonstat(data,{select_dim:preferred} if select_dim else {})
    if not points:raise ValueError('no_matching_observations')
    return {'status':'ok','dataset':dataset,'region':'EA21','requested_selection':params,'resolved_selection':selection,
            'source_url':url,'observations':points,'audit':audit,'provider_updated':data.get('updated'),
            'first_publication_time_verified':False}

def get_us(factor,key,fetch):
    sid=US[factor]
    url=FRED_BASE+'?'+urlencode({'series_id':sid,'api_key':key,'file_type':'json','sort_order':'desc','limit':24})
    data,audit=fetch(url)
    if 'error_code' in data:raise ValueError('fred_api_error')
    points=[]
    for obs in data.get('observations',[]):
        if re.fullmatch(r'\d{4}-\d{2}-\d{2}',str(obs.get('date',''))) and obs.get('value') not in ('.',None):
            points.append({'period':obs['date'][:7],'value':float(obs['value']),'realtime_start':obs.get('realtime_start')})
    points=sorted(points,key=lambda x:x['period'])[-18:]
    if not points:raise ValueError('no_matching_observations')
    return {'status':'ok','series_id':sid,'region':'US','source_url':FRED_BASE,'observations':points,
            'audit':audit,'first_publication_time_verified':False}

def aligned_diagnostic(us,ea,factor):
    a={p['period']:p['value'] for p in us};b={p['period']:p['value'] for p in ea}
    common=sorted(set(a)&set(b))
    if len(common)<2:return {'status':'insufficient_aligned_periods','common_periods':common,'directional_score_authorized':False}
    last=common[-1]
    # For annual inflation, require exactly same month one year earlier; no approximation.
    if factor=='inflation':
        prev=f'{int(last[:4])-1:04d}-{last[5:]}'
        if prev not in a or prev not in b:return {'status':'insufficient_year_ago_observations','latest_aligned_period':last,'directional_score_authorized':False}
        if not a[prev] or not b[prev]:raise ValueError('zero_base_index')
        return {'status':'aligned_descriptive_only','latest_aligned_period':last,'comparison':'year_over_year_percent',
                'us_change':round((a[last]/a[prev]-1)*100,5),'ea_change':round((b[last]/b[prev]-1)*100,5),
                'directional_score_authorized':False}
    previous=common[-2]
    if factor=='unemployment':
        uc=round(a[last]-a[previous],5);ec=round(b[last]-b[previous],5);mode='percentage_points'
    else:
        if not a[previous] or not b[previous]:raise ValueError('zero_base_index')
        uc=round((a[last]/a[previous]-1)*100,5);ec=round((b[last]/b[previous]-1)*100,5);mode='percentage_change'
    return {'status':'aligned_descriptive_only','latest_aligned_period':last,'previous_common_period':previous,
            'comparison':mode,'us_change':uc,'ea_change':ec,'directional_score_authorized':False}

def collect(key,fetch=fetch_json,now=None):
    now=(now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    series={};diagnostics={}
    for factor in US:
        series[factor]={}
        for region in ('US','EA'):
            try:series[factor][region]=get_us(factor,key,fetch) if region=='US' else get_eu(factor,fetch)
            except Exception as exc:series[factor][region]={'status':'error','error_type':type(exc).__name__,'error_message':str(exc)[:220]}
        us=series[factor]['US'];ea=series[factor]['EA']
        if us['status']=='ok' and ea['status']=='ok':
            try:diagnostics[factor]=aligned_diagnostic(us['observations'],ea['observations'],factor)
            except Exception as exc:diagnostics[factor]={'status':'diagnostic_error','error_message':str(exc)[:150],'directional_score_authorized':False}
        else:diagnostics[factor]={'status':'incomplete_pair','directional_score_authorized':False}
    return {'model_version':VERSION,'asset':'EUR/USD','generated_at_utc':now.isoformat(),
            'generated_at_brt':now.astimezone(ZoneInfo('America/Sao_Paulo')).isoformat(),'reference_time_brt':'04:00',
            'official_sources':{'EA':'Eurostat','US':'FRED'},'series':series,'paired_diagnostics':diagnostics,
            'successful_series':sum(v['status']=='ok' for x in series.values() for v in x.values()),'requested_series':6,
            'complete_pairs':sum(all(v['status']=='ok' for v in x.values()) for x in series.values()),
            'comparability_verified':False,'first_publication_time_verified':False,'historical_pit_verified':False,
            'fixed_predictions_written':False,'experimental_bias':{'day':'indisponivel','week':'indisponivel','month':'indisponivel'},
            'research_only':True,'signals_generated':False,'backtests_authorized':False,'database_writes':False,
            'production_change_authorized':False,'limitations':['HICP and CPI are distinct measures; aligned changes are descriptive only.',
            'Index bases differ; compare rates of change, never index levels.',
            'FRED/Eurostat current snapshots do not establish precise historical first availability.',
            'No immutable predictions or historical backtests are generated.']}

def self_test():
    cube={'id':['geo','unit','time'],'size':[1,2,3],
          'dimension':{'geo':{'category':{'index':{'EA21':0}}},'unit':{'category':{'index':{'I15':0,'I25':1}}},
                       'time':{'category':{'index':{'2025-10':0,'2026-09':1,'2026-10':2}}}},
          'value':{'0':100,'1':101,'2':102,'3':110,'4':111,'5':112}}
    pts,sel=decode_jsonstat(cube,{'unit':['I25','I15']})
    assert sel['unit']=='I25' and pts[-1]['value']==112
    try:decode_jsonstat(cube)
    except ValueError as e:assert 'ambiguous_dimension_unit' in str(e)
    else:raise AssertionError('ambiguous unit accepted')
    assert aligned_diagnostic([{'period':'2026-08','value':100},{'period':'2026-09','value':102}],
           [{'period':'2026-08','value':100},{'period':'2026-09','value':101}],'activity')['us_change']==2
    assert all(x[1]['geo']=='EA21' for x in EU.values())
    print('RC94_SELF_TEST_OK')

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--self-test',action='store_true');parser.add_argument('--output',default='eur_rc94_result.json');args=parser.parse_args()
    if args.self_test:self_test()
    else:
        key=os.getenv('FRED_API_KEY','').strip()
        if not key:raise SystemExit('FRED_API_KEY is required')
        result=collect(key);Path(args.output).write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
        print('RC94_OK',result['successful_series'],'/',result['requested_series'],'pairs',result['complete_pairs'])
