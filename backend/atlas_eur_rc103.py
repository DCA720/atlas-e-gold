#!/usr/bin/env python3
"""Read-only prospective statistics for the RC102 ledger."""
import argparse, json, math, hashlib, tempfile
from pathlib import Path
from datetime import datetime, timedelta, timezone
from statistics import mean
import atlas_eur_rc102 as base
VERSION='eur-rc10.3-statistics-0.10.3'
H=('day','week','month')
B=('baixista_forte','baixista','neutro','altista','altista_forte')
NEUTRAL=0.10 # percent, experimental, inclusive

def label(s):
    return B[0] if s<=-60 else B[1] if s<=-20 else B[4] if s>=60 else B[3] if s>=20 else B[2]
def read(p): return json.loads(p.read_text())
def stamp(s):
    t=datetime.fromisoformat(s)
    if t.tzinfo is None: raise ValueError('timezone required')
    return t

def evaluate(root,now=None):
    now=now or datetime.now(timezone.utc); rows=[]
    for h in H:
        for p in sorted((root/h).glob('*.json')):
            row={'horizon':h,'period':p.stem,'status':'invalid'}; rows.append(row)
            try:
                r=read(p); s=r['score']; v=s['score']; t=stamp(r['effective_at_utc']); start=stamp(r['collection_started_at_utc']); end=base.deadline(r)
                if r['horizon']!=h or r['period']!=p.stem or r['asset']!='EUR/USD' or r['research_only'] is not True: raise ValueError('identity')
                if not math.isfinite(v) or not -100<=v<=100 or s['bias']!=label(v): raise ValueError('score')
                if (h,p.stem) not in base.prev.plan(start,t,s)[0] or t>now: raise ValueError('window')
                if hashlib.sha256(base.prev.encode(r['snapshot'])).hexdigest()!=r['source_snapshot_sha256'] or r['snapshot']['macro_score']!=s: raise ValueError('snapshot')
                row.update(score=v,bias=label(v),effective_at_utc=t.isoformat(),target_end_utc=end.isoformat(),coverage_percent=s['coverage_percent'])
                folder=root/'prices'/h/p.stem
                if not (folder/'entry.json').exists() or not (folder/'exit.json').exists():
                    row['status']='pending' if now<end else 'missing_prices'; continue
                a,b=read(folder/'entry.json'),read(folder/'exit.json'); ta,tb=stamp(a['bar_end_utc']),stamp(b['bar_end_utc']); pa,pb=a['price'],b['price']
                if not all(math.isfinite(x) and x>0 for x in (pa,pb)): raise ValueError('price')
                if not (t<=ta<=t+timedelta(minutes=15) and end-timedelta(minutes=15)<=tb<=end and ta<tb<=now and end<=now): raise ValueError('price timing')
                change=(pb/pa-1)*100; direction=0 if v>-20 and v<20 else (1 if v>0 else -1)
                outcome=('neutral_hit' if abs(change)<=NEUTRAL else 'neutral_miss') if direction==0 else ('hit' if direction*change>0 else 'miss' if direction*change<0 else 'flat')
                row.update(status='evaluated',entry=a,exit=b,return_percent=change,directional_return_percent=direction*change if direction else None,outcome=outcome)
            except (ValueError,TypeError,KeyError,OSError,OverflowError) as e: row.update(status='invalid',error=str(e)[:150])
    def stats(rs):
        done=[r for r in rs if r['status']=='evaluated']; d=[r for r in done if r['outcome'] in ('hit','miss','flat')]; n=[r for r in done if r['outcome'].startswith('neutral_')]; hits=sum(r['outcome']=='hit' for r in d); misses=sum(r['outcome']=='miss' for r in d); nh=sum(r['outcome']=='neutral_hit' for r in n)
        avg=lambda xs: mean(xs) if xs else None
        return dict(total=len(rs),evaluated=len(done),pending=sum(r['status']=='pending' for r in rs),missing_prices=sum(r['status']=='missing_prices' for r in rs),invalid=sum(r['status']=='invalid' for r in rs),directional_count=len(d),hits=hits,misses=misses,flat=len(d)-hits-misses,hit_rate_percent=100*hits/len(d) if d else None,neutral_count=len(n),neutral_hits=nh,neutral_hit_rate_percent=100*nh/len(n) if n else None,mean_return_percent=avg([r['return_percent'] for r in done]),mean_directional_return_percent=avg([r['directional_return_percent'] for r in d]))
    return dict(model_version=VERSION,generated_at_utc=now.isoformat(),research_only=True,production_change_authorized=False,neutral_band_percent=NEUTRAL,registered=len(rows),evaluated=sum(r['status']=='evaluated' for r in rows),horizons={h:{**stats([r for r in rows if r['horizon']==h]),'by_bias':{b:stats([r for r in rows if r['horizon']==h and r.get('bias')==b]) for b in B}} for h in H},history=rows,limitations=['RC102 reference prices, not executable quotes; no spread or costs.','04:00–04:15 actual issuance cohort, not exact 04:00 forecasts.','Neutral band experimental; flat directional returns count in denominator.','No historical backtest or calibrated probability; horizons may overlap; never pool them.','RC102 price timestamps are bar ends; provider retrieval time and commit publication time not independently verified.'])

def self_test():
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp); t=datetime(2026,12,1,7,3,tzinfo=timezone.utc); now=t+timedelta(hours=13)
        assert evaluate(root,now)['horizons']['day']['hit_rate_percent'] is None
        s={'macro_score':{'score':-30,'bias':'baixista','coverage_percent':100}}
        base.prev.register(s,t,t,root,True)
        assert evaluate(root,t)['horizons']['day']['pending']==1
        base.audit(root,[{'bar_end_utc':(t+timedelta(minutes=2)).isoformat(),'price':1.1},{'bar_end_utc':'2026-12-01T19:00:00+00:00','price':1.09}],True,now)
        x=evaluate(root,now); assert x['horizons']['day']['hit_rate_percent']==100 and x['horizons']['month']['evaluated']==0
        p=root/'prices/day/2026-12-01/entry.json'; a=read(p); a['bar_end_utc']=(t-timedelta(minutes=1)).isoformat(); p.write_bytes(base.prev.encode(a)); assert evaluate(root,now)['horizons']['day']['invalid']==1
    print('RC103_SELF_TEST_OK')
if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--self-test',action='store_true'); p.add_argument('--ledger',type=Path,default=base.ROOT); a=p.parse_args()
    if a.self_test: self_test()
    else: Path('eur_rc103_result.json').write_bytes(base.prev.encode(evaluate(a.ledger)))
