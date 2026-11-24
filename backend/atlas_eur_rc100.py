#!/usr/bin/env python3
"""RC10.0: experimental global risk, no fixed forecasts or production writes."""
import argparse, json, os, math
from datetime import datetime, timezone, date
from pathlib import Path
import atlas_eur_rc99 as prev

VERSION='eur-rc10.0-global-risk-0.10.0'

def risk_component(data, today):
    out=dict(weight=15,status='unavailable',subcomponents={})
    if not all(data.get(s,{}).get('status')=='ok' for s in ('VIXCLS','SP500')):
        out['reason']='missing_series'; return out
    a,b=[data[s]['observations'] for s in ('VIXCLS','SP500')]
    common=sorted(d for d in set(a)&set(b) if date.fromisoformat(d)<today and all(math.isfinite(x[d]) and x[d]>0 for x in (a,b)))
    if len(common)<6:
        out['reason']='insufficient_common_closes'; return out
    start,end=common[-6],common[-1]
    if (today-date.fromisoformat(end)).days>5 or (date.fromisoformat(end)-date.fromisoformat(start)).days>12:
        out['reason']='stale_or_sparse_closes'; return out
    for sid,values,sign,scale in [('VIXCLS',a,-1,20),('SP500',b,1,3)]:
        change=100*(values[end]/values[start]-1)
        normalized=max(-1,min(1,sign*change/scale))
        out['subcomponents'][sid]=dict(weight=7.5,start=start,end=end,start_value=values[start],end_value=values[end],change_percent=change,scale=scale,normalized=normalized,contribution=7.5*normalized)
    out.update(status='ok',period=end,contribution=sum(x['contribution'] for x in out['subcomponents'].values()),method='five common trading intervals; VIX inverse and SP500 direct; heuristic')
    return out

def combine(base,data,today):
    components={**base['components'],'risk':risk_component(data,today)}
    coverage=sum(x['weight'] for x in components.values() if x['status']=='ok')
    valid=coverage>=80 and all(components[k]['status']=='ok' for k in ('rates','inflation','activity'))
    raw=sum(x.get('contribution',0) for x in components.values() if x['status']=='ok')
    value=round(raw*100/coverage,4) if valid else None
    bias='indisponivel' if value is None else 'altista_forte' if value>=60 else 'altista' if value>=20 else 'baixista_forte' if value<=-60 else 'baixista' if value<=-20 else 'neutro'
    return dict(score=value,bias=bias,coverage_percent=coverage,raw_weighted_sum=raw,components=components,calibrated=False,method='weighted available components normalized by coverage; not probability')

def collect(key):
    r=prev.collect(key)
    data={s:prev.rate(s,key) for s in ('VIXCLS','SP500')}
    now=datetime.now(timezone.utc)
    r.update(model_version=VERSION,risk_series=data,macro_score=combine(r['macro_score'],data,now.date()),score_calculated_at_utc=now.isoformat())
    r['limitations'].append('Risk uses previous-date common closes, not live prices; heuristic signs and scales unvalidated. Both risk series required for the risk block.')
    return r

def self_test():
    prev.self_test()
    today=date(2026,11,24)
    dates=['2026-11-16','2026-11-17','2026-11-18','2026-11-19','2026-11-20','2026-11-23']
    data={s:dict(status='ok',observations=dict(zip(dates,vals))) for s,vals in [('VIXCLS',[20,21,22,23,24,24]),('SP500',[100,99,98,97,96,97])]}
    risk=risk_component(data,today)
    assert risk['status']=='ok' and abs(risk['contribution']+15)<1e-8
    assert risk_component(data,date(2026,12,1))['status']=='unavailable'
    assert risk_component({},today)['status']=='unavailable'
    base={'components':{k:dict(weight=w,status='ok' if k!='risk' else 'unavailable',contribution=0) for k,w in prev.WEIGHTS.items()}}
    assert combine(base,data,today)['coverage_percent']==100
    assert combine(base,{},today)['coverage_percent']==85
    base['components']['rates']['status']='unavailable'
    assert combine(base,data,today)['score'] is None
    print('RC100_SELF_TEST_OK')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--self-test',action='store_true');p.add_argument('--output',default='eur_rc100_result.json');a=p.parse_args()
    if a.self_test:self_test()
    else:
        key=os.getenv('FRED_API_KEY','').strip()
        if not key:raise SystemExit('FRED_API_KEY required')
        r=collect(key);Path(a.output).write_text(json.dumps(r,indent=2,ensure_ascii=False,allow_nan=False)+'\n',encoding='utf-8');print('RC100',r['macro_score']['bias'],r['macro_score']['coverage_percent'])
