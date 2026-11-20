#!/usr/bin/env python3
"""Atlas EUR RC9.0: experimental, fixed-horizon, no-lookahead macro bias.

This is a research prototype, NOT a trading signal or validated model.
Only explicitly supplied timestamped inputs can produce an experimental bias.
"""
import argparse
import hashlib
import json
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

VERSION = 'eur-rc9.0-fixed-horizon-experimental-bias-0.9.0'
TZ = ZoneInfo('America/Sao_Paulo')
FACTORS = ('rates', 'inflation', 'activity', 'unemployment', 'risk')
WEIGHTS = {'rates': 0.30, 'inflation': 0.20, 'activity': 0.20, 'unemployment': 0.15, 'risk': 0.15}
# Provisional analyst-supplied relative directional assessments, NOT derived or validated macro formulas.
# Each assessment is in [-1, 1], where positive means EUR strength relative to USD.

def utc_dt(value):
    if not isinstance(value, str):
        raise ValueError('UTC timestamp required')
    d = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if d.tzinfo is None:
        raise ValueError('Timezone required')
    return d.astimezone(timezone.utc)

def cutoff_for(now, horizon):
    local = now.astimezone(TZ)
    d = local.date()
    if horizon == 'day':
        if local.time() < time(4): d -= timedelta(days=1)
    elif horizon == 'week':
        d -= timedelta(days=d.weekday())
        if local.date() == d and local.time() < time(4): d -= timedelta(days=7)
    elif horizon == 'month':
        d = d.replace(day=1)
        if local.date() == d and local.time() < time(4):
            d = (d - timedelta(days=1)).replace(day=1)
    else: raise ValueError('Unsupported horizon')
    return datetime.combine(d, time(4), TZ).astimezone(timezone.utc)

def evaluate(snapshot, now, horizon):
    cutoff = cutoff_for(now, horizon)
    cutoff_local = cutoff.astimezone(TZ)
    rows = snapshot.get('factors', [])
    if not isinstance(rows, list): raise ValueError('factors must be an array')
    accepted = {}; rejected = []
    for i, item in enumerate(rows):
        if not isinstance(item, dict): raise ValueError('Invalid factor record')
        name = item.get('factor')
        if name not in FACTORS or name in accepted:
            rejected.append({'index':i, 'reason':'unknown_or_duplicate_factor'}); continue
        try:
            observed = utc_dt(item['available_at_utc'])
            val = item['relative_assessment']
            if isinstance(val, bool) or not isinstance(val, (float, int)) or not -1 <= val <= 1:
                raise ValueError('Assessment outside [-1,1]')
            if observed > cutoff:
                rejected.append({'index':i,'factor':name,'reason':'published_after_cutoff'}); continue
            if not isinstance(item.get('source_url'), str) or not item['source_url'].startswith('https://'):
                raise ValueError('source_url must be HTTPS')
            if not isinstance(item.get('rationale'), str) or not item['rationale'].strip():
                raise ValueError('rationale required')
            accepted[name] = {'relative_assessment':float(val),'available_at_utc':observed.isoformat(), 'source_url':item['source_url'], 'rationale':item['rationale']}
        except (KeyError, TypeError, ValueError) as exc:
            rejected.append({'index':i,'factor':name,'reason':'invalid_record','detail':str(exc)})
    coverage = round(sum(WEIGHTS[k] for k in accepted), 6)
    enough = coverage >= .8 and all(k in accepted for k in ('rates','inflation','activity'))
    score = round(100 * sum(WEIGHTS[k] * v['relative_assessment'] for k,v in accepted.items()) / coverage, 2) if enough else None
    direction = ('alta' if score >= 20 else 'baixa' if score <= -20 else 'neutro') if score is not None else 'indisponivel'
    # A prediction generated after its cutoff is never misrepresented as contemporaneous.
    delay = (now-cutoff).total_seconds()
    on_time = 0 <= delay <= 15*60
    official_research_record = bool(enough and on_time)
    return {'horizon':horizon,'cutoff_utc':cutoff.isoformat(),'cutoff_brt':cutoff_local.isoformat(), 'evaluated_at_utc':now.isoformat(), 'seconds_after_cutoff':round(delay), 'on_time_within_15_minutes':on_time, 'coverage':coverage, 'required_factors_present':all(k in accepted for k in ('rates','inflation','activity')), 'accepted_factors':accepted, 'rejected_factors':rejected, 'experimental_score':score, 'experimental_bias':direction, 'research_record_eligible':official_research_record, 'status':'experimental_on_time' if official_research_record else 'late_research_only' if enough else 'insufficient_data'}

def build(snapshot, now):
    if not isinstance(snapshot,dict) or snapshot.get('schema_version') != 'atlas-eur-macro-input-1':
        raise ValueError('Invalid snapshot schema')
    results = {h:evaluate(snapshot,now,h) for h in ('day','week','month')}
    canonical = json.dumps(snapshot,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()
    return {'model_version':VERSION,'asset':'EUR/USD','module':'experimental_fixed_macro_bias','generated_at_utc':now.isoformat(), 'reference_timezone':'America/Sao_Paulo','reference_time_local':'04:00','input_sha256':hashlib.sha256(canonical).hexdigest(), 'bias_method':'provisional weighted directional analyst assessments, not independently validated','factor_weights':WEIGHTS,'thresholds':{'alta_min':20,'baixa_max':-20},'horizons':results, 'research_only':True,'validated_predictive_accuracy':False,'historical_pit_verified':False,'production_change_authorized':False,'signals_generated':False,'backtests_authorized':False,'database_writes':False,'next_step':'Acquire timestamped real macro inputs, persist immutable on-time predictions and subsequently assess close-to-close outcomes.'}

def self_test():
    now=utc_dt('2026-11-23T07:05:00Z')
    assert cutoff_for(now,'day')==utc_dt('2026-11-23T07:00:00Z')
    assert cutoff_for(now,'week')==utc_dt('2026-11-23T07:00:00Z')
    assert cutoff_for(now,'month')==utc_dt('2026-11-01T07:00:00Z')
    example={'schema_version':'atlas-eur-macro-input-1','factors':[{'factor':k,'relative_assessment':0.6,'available_at_utc':'2026-10-30T12:00:00Z','source_url':'https://example.org/test','rationale':'synthetic test'} for k in FACTORS]}
    result=build(example,now)
    assert result['horizons']['day']['experimental_bias']=='alta'
    assert result['horizons']['day']['research_record_eligible']
    assert not result['horizons']['month']['research_record_eligible']
    example['factors'][0]['available_at_utc']='2026-11-23T07:01:00Z'
    assert 'rates' not in build(example,now)['horizons']['day']['accepted_factors']
    assert build({'schema_version':'atlas-eur-macro-input-1','factors':[]},now)['horizons']['day']['experimental_score'] is None
    print('RC90_SELF_TEST_OK')

def main():
    p=argparse.ArgumentParser();p.add_argument('--input',default='eur_rc90_macro_snapshot.json');p.add_argument('--output',default='eur_rc90_result.json');p.add_argument('--now-utc',help='FOR TESTING ONLY: manual evaluation time');p.add_argument('--self-test',action='store_true');a=p.parse_args()
    if a.self_test: self_test();return
    now=utc_dt(a.now_utc) if a.now_utc else datetime.now(timezone.utc)
    data=json.loads(Path(a.input).read_text(encoding='utf-8'))
    result=build(data,now)
    Path(a.output).write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print('RC90_OK', {k:(v['experimental_bias'],v['status']) for k,v in result['horizons'].items()})
if __name__=='__main__':main()
