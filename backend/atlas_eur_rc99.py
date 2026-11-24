#!/usr/bin/env python3
"""Research-only macro score; no retrospective or fixed forecasts."""
import argparse, json, os, math
from datetime import datetime, timezone, date
from pathlib import Path
from urllib.parse import urlencode
import atlas_eur_rc98 as previous
from atlas_eur_rc95 import fetch_json, FRED_BASE

VERSION='eur-rc9.9-experimental-score-0.9.9'
WEIGHTS={'rates':30,'inflation':20,'activity':20,'unemployment':15,'risk':15}

def rate(sid,key,fetch=fetch_json):
    try:
        data,audit=fetch(FRED_BASE+'?'+urlencode(dict(series_id=sid,api_key=key,file_type='json',sort_order='desc',limit=90)))
        points={x['date']:float(x['value']) for x in data['observations'] if x['value'] not in ('.',None)}
        points={d:v for d,v in points.items() if math.isfinite(v) and date.fromisoformat(d)<=datetime.now(timezone.utc).date()}
        if not points: raise ValueError('empty')
        return dict(status='ok',series_id=sid,observations=points,audit=audit)
    except Exception as e:
        return dict(status='error',series_id=sid,error_type=type(e).__name__)

def score(result,rates):
    components={k:dict(weight=w,status='unavailable') for k,w in WEIGHTS.items()}
    def add(k,raw,scale,period,method):
        if not math.isfinite(raw): return
        normalized=max(-1,min(1,raw/scale))
        components[k].update(status='ok',raw_difference=raw,scale=scale,period=period,method=method,normalized=normalized,contribution=normalized*WEIGHTS[k])
    for k,scale,sign in [('inflation',2,1),('activity',2,1),('unemployment',0.5,-1)]:
        d=result['paired_diagnostics'][k]
        if d['status']!='aligned_descriptive_only': continue
        period=d['latest_aligned_period']
        if k!='inflation':
            y,m=map(int,period.split('-')); prev=f'{y-(m==1):04d}-{12 if m==1 else m-1:02d}'
            if d.get('previous_common_period')!=prev: continue
        add(k,sign*(d['ea_change']-d['us_change']),scale,period,{'inflation':'EA minus US annual inflation; assumed monetary response','activity':'EA minus US monthly industrial growth','unemployment':'US minus EA monthly unemployment change'}[k])
    if all(rates.get(s,{}).get('status')=='ok' for s in ('DFEDTARL','DFEDTARU','ECBDFR')):
        a,b,c=[rates[s]['observations'] for s in ('DFEDTARL','DFEDTARU','ECBDFR')]
        common=sorted(set(a)&set(b)&set(c))
        if common:
            d=common[-1]
            if a[d]<=b[d] and 0<=(datetime.now(timezone.utc).date()-date.fromisoformat(d)).days<=10:
                add('rates',c[d]-(a[d]+b[d])/2,3,d,'ECB deposit rate minus Fed target midpoint')
    coverage=sum(v['weight'] for v in components.values() if v['status']=='ok')
    valid=coverage>=80 and all(components[k]['status']=='ok' for k in ('rates','inflation','activity'))
    value=round(sum(v.get('contribution',0) for v in components.values())*100/coverage,4) if valid else None
    label='indisponivel' if value is None else 'altista_forte' if value>=60 else 'altista' if value>=20 else 'baixista_forte' if value<=-60 else 'baixista' if value<=-20 else 'neutro'
    return dict(score=value,bias=label,coverage_percent=coverage,components=components,calibrated=False,method='weighted normalized available components; fixed heuristic scales; not probability')

def collect(key):
    r=previous.collect(key)
    rates={s:rate(s,key) for s in ('DFEDTARL','DFEDTARU','ECBDFR')}
    r.update(model_version=VERSION,policy_rates=rates,macro_score=score(r,rates),score_calculated_at_utc=datetime.now(timezone.utc).isoformat())
    r['limitations'].append('Experimental snapshot only; no fixed daily, weekly or monthly forecast. Risk missing; inflation sign and scales are unvalidated hypotheses.')
    return r

def self_test():
    previous.self_test()
    r={'paired_diagnostics':{k:dict(status='aligned_descriptive_only',latest_aligned_period='2026-09',previous_common_period='2026-08',ea_change=1,us_change=0) for k in ('inflation','activity','unemployment')}}
    d=datetime.now(timezone.utc).date().isoformat()
    rates={s:dict(status='ok',observations={d:v}) for s,v in [('DFEDTARL',2),('DFEDTARU',3),('ECBDFR',4)]}
    x=score(r,rates); assert x['coverage_percent']==85 and x['score'] is not None
    assert score(r,{})['score'] is None
    r['paired_diagnostics']['inflation']['status']='error'; assert score(r,rates)['score'] is None
    print('RC99_SELF_TEST_OK')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--self-test',action='store_true');p.add_argument('--output',default='eur_rc99_result.json');a=p.parse_args()
    if a.self_test:self_test()
    else:
        key=os.getenv('FRED_API_KEY','').strip()
        if not key:raise SystemExit('FRED_API_KEY required')
        r=collect(key);Path(a.output).write_text(json.dumps(r,indent=2,ensure_ascii=False,allow_nan=False)+'\n',encoding='utf-8');print('RC99',r['macro_score']['bias'],r['macro_score']['coverage_percent'])
