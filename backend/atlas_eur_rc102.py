#!/usr/bin/env python3
"""Isolated prospective ledger and experimental Yahoo FX price audit."""
import argparse, json, os, math, tempfile
from pathlib import Path
from datetime import datetime, timedelta, timezone, time
from urllib.request import Request, urlopen
from urllib.parse import urlencode
import atlas_eur_rc101 as prev
VERSION='eur-rc10.2-ledger-price-0.10.2'
ROOT=Path('research/atlas-eur-ledger')
def fetch_prices():
    url='https://query1.finance.yahoo.com/v8/finance/chart/EURUSD=X?'+urlencode({'range':'5d','interval':'5m'})
    with urlopen(Request(url,headers={'User-Agent':'Mozilla/5.0'}),timeout=30) as r:
        data=json.loads(r.read(2000000))
    result=data['chart']['result'][0]
    if result['meta']['symbol']!='EURUSD=X': raise ValueError('wrong symbol')
    now=prev.utc(); rows=[]
    for t,p in zip(result['timestamp'],result['indicators']['quote'][0]['close']):
        end=datetime.fromtimestamp(t,timezone.utc)+timedelta(minutes=5)
        if isinstance(p,(float,int)) and math.isfinite(p) and p>0 and end<=now:
            rows.append({'bar_end_utc':end.isoformat(),'price':p})
    return sorted(rows,key=lambda x:x['bar_end_utc'])
def match(rows,target,after):
    candidates=[r for r in rows if (timedelta(0)<=datetime.fromisoformat(r['bar_end_utc'])-target<=timedelta(minutes=15) if after else timedelta(0)<=target-datetime.fromisoformat(r['bar_end_utc'])<=timedelta(minutes=15))]
    return (candidates[0] if after else candidates[-1]) if candidates else None
def deadline(record):
    d=datetime.fromisoformat(record['effective_at_utc']).astimezone(prev.BRT).date()
    if record['horizon']=='week': d+=timedelta(days=4-d.weekday())
    if record['horizon']=='month':
        d=(d.replace(day=28)+timedelta(days=4)).replace(day=1)-timedelta(days=1)
        while d.weekday()>4: d-=timedelta(days=1)
    return datetime.combine(d,time(16),prev.BRT).astimezone(timezone.utc)
def audit(root,rows,write=False,now=None):
    now=now or prev.utc(); results=[]
    for h in ('day','week','month'):
        for path in sorted((root/h).glob('*.json')):
            r=json.loads(path.read_text()); start=datetime.fromisoformat(r['effective_at_utc']); end=deadline(r)
            base=root/'prices'/h/r['period']; entry=base/'entry.json'; exit=base/'exit.json'
            a=json.loads(entry.read_text()) if entry.exists() else match(rows,start,True)
            b=json.loads(exit.read_text()) if exit.exists() else (match(rows,end,False) if now>=end else None)
            if write:
                for p,v in ((entry,a),(exit,b)):
                    if v and not p.exists():
                        p.parent.mkdir(parents=True,exist_ok=True)
                        with p.open('xb') as f: f.write(prev.encode(v))
            results.append({'horizon':h,'period':r['period'],'entry':a,'exit':b,'target_end_utc':end.isoformat(),'return_percent':(b['price']/a['price']-1)*100 if a and b else None})
    return results
def self_test():
    prev.self_test()
    t=datetime(2026,12,1,7,3,tzinfo=timezone.utc)
    rows=[{'bar_end_utc':(t+timedelta(minutes=i)).isoformat(),'price':1.1} for i in (-3,2,7,20)]
    assert match(rows,t,True)==rows[1]; assert match(rows,t,False)==rows[0]; assert match([],t,True) is None
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp); s={'macro_score':{'score':-30,'coverage_percent':100}}
        prev.register(s,t,t,root,True); assert len(audit(root,rows,True,t+timedelta(minutes=10)))==2
        assert len(list(root.glob('prices/*/*/entry.json')))==2
        assert len(prev.register(s,t,t,root,True)['duplicates'])==2
    print('RC102_SELF_TEST_OK')
def main():
    p=argparse.ArgumentParser(); p.add_argument('--self-test',action='store_true'); p.add_argument('--mode',choices=['diagnostic','record','audit'],default='diagnostic'); p.add_argument('--ledger',type=Path,default=ROOT); a=p.parse_args()
    if a.self_test: return self_test()
    out={'model_version':VERSION,'mode':a.mode,'research_only':True,'production_change_authorized':False,'price_source':'Yahoo Finance EURUSD=X, completed 5-minute bars, experimental','close_definition':'16:00 BRT on final weekday; not broker close'}
    if a.mode!='audit':
        start=prev.utc(); snapshot=prev.prev.collect(os.environ['FRED_API_KEY']); end=prev.utc()
        out['registration']=prev.register(snapshot,start,end,a.ledger,a.mode=='record')
    try:
        rows=fetch_prices(); out['price_status']='ok' if rows else 'empty'; out['latest_price']=rows[-1] if rows else None
    except Exception as e:
        rows=[]; out['price_status']='error'; out['price_error']=type(e).__name__
    out['price_audit']=audit(a.ledger,rows,a.mode!='diagnostic'); Path('eur_rc102_result.json').write_bytes(prev.encode(out))
if __name__=='__main__': main()
