#!/usr/bin/env python3
"""Prospective research ledger; never backdate a forecast."""
import argparse, json, os, hashlib, math, tempfile
from pathlib import Path
from datetime import datetime, timezone, timedelta, time
from zoneinfo import ZoneInfo
import atlas_eur_rc100 as prev
BRT=ZoneInfo('America/Sao_Paulo')
VERSION='eur-rc10.1-prospective-0.10.1'
def utc(): return datetime.now(timezone.utc)
def encode(x): return (json.dumps(x,sort_keys=True,indent=2,ensure_ascii=False,allow_nan=False)+'\n').encode()
def plan(start,end,score):
    a,b=start.astimezone(BRT),end.astimezone(BRT)
    d=b.date(); cutoff=datetime.combine(d,time(4),BRT)
    if a<cutoff or b>cutoff+timedelta(minutes=15) or a>b or d.weekday()>4:
        return [],'outside_window'
    if score.get('coverage_percent',0)<80 or not isinstance(score.get('score'),(float,int)) or not math.isfinite(score['score']): return [],'insufficient_score'
    periods=[('day',d.isoformat())]
    if d.weekday()==0: periods.append(('week',f'{d.isocalendar().year}-W{d.isocalendar().week:02d}'))
    first=d.replace(day=1)
    while first.weekday()>4: first+=timedelta(days=1)
    if d==first: periods.append(('month',d.strftime('%Y-%m')))
    return periods,'eligible'
def register(snapshot,start,end,root,enabled):
    score=snapshot['macro_score']; periods,reason=plan(start,end,score)
    out=dict(model_version=VERSION,research_only=True,production_change_authorized=False,generated_at_utc=end.isoformat(),snapshot=snapshot,window_status=reason,recording_enabled=enabled,records=[],duplicates=[],fixed_predictions_written=False)
    if not enabled: return out
    for horizon,period in periods:
        path=Path(root)/horizon/(period+'.json'); path.parent.mkdir(parents=True,exist_ok=True)
        record=dict(model_version=VERSION,asset='EUR/USD',horizon=horizon,period=period,reference_time_brt='04:00',collection_started_at_utc=start.isoformat(),effective_at_utc=end.isoformat(),score=score,source_snapshot_sha256=hashlib.sha256(encode(snapshot)).hexdigest(),snapshot=snapshot,price_validation_pending=True,calendar='weekdays_only',research_only=True)
        try:
            with path.open('xb') as f: f.write(encode(record))
        except FileExistsError: out['duplicates'].append(str(path)); continue
        out['records'].append(str(path))
    out['fixed_predictions_written']=bool(out['records']); return out

def self_test():
    prev.self_test()
    a=datetime(2026,12,1,7,1,tzinfo=timezone.utc); b=a+timedelta(minutes=1)
    s={'macro_score':{'score':-30,'coverage_percent':100}}
    assert plan(a,b,s['macro_score'])[0]==[('day','2026-12-01'),('month','2026-12')]
    assert not plan(a,b+timedelta(minutes=20),s['macro_score'])[0]
    assert not plan(a,b,{'score':1,'coverage_percent':79})[0]
    with tempfile.TemporaryDirectory() as t:
        assert not register(s,a,b,t,False)['records']
        r=register(s,a,b,t,True); assert len(r['records'])==2
        before=Path(r['records'][0]).read_bytes()
        assert len(register(s,a,b,t,True)['duplicates'])==2
        assert Path(r['records'][0]).read_bytes()==before
    print('RC101_SELF_TEST_OK')
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--self-test',action='store_true');p.add_argument('--record',action='store_true');p.add_argument('--ledger',default='research/atlas-eur-ledger');p.add_argument('--output',default='eur_rc101_result.json');a=p.parse_args()
    if a.self_test: self_test()
    else:
        key=os.environ.get('FRED_API_KEY','').strip()
        if not key: raise SystemExit('FRED_API_KEY required')
        start=utc(); snapshot=prev.collect(key); end=utc()
        r=register(snapshot,start,end,a.ledger,a.record); Path(a.output).write_bytes(encode(r)); print(r['window_status'],r['records'])
