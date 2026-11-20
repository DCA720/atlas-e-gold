#!/usr/bin/env python3
"""Atlas EUR RC8.4: event-specific release chronology and evidence gates (read-only)."""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

VERSION = 'eur-rc8.4-first-dissemination-chronology-0.8.4'
FACTORS = ('inflation', 'rates', 'unemployment', 'activity')
# Times below are explicitly scheduled/embargo/press-conference times, NOT measured publication.
EVENTS = [
    {'id':'US_UNRATE_2025-11_BLS','factor':'unemployment','time':'2025-12-16T08:30:00','zone':'America/New_York','kind':'embargo_until','value':'4.6','concept':'US unemployment rate, November 2025, percent'},
    {'id':'US_FOMC_2026-09-16','factor':'rates','time':'2026-09-16T14:00:00','zone':'America/New_York','kind':'scheduled_press_release','value':'3.75-4.00','concept':'Federal funds target range, percent'},
    {'id':'EU_ECB_2026-09-10','factor':'rates','time':'2026-09-10T14:45:00','zone':'Europe/Berlin','kind':'scheduled_press_conference_not_decision_release','value':'2.50','concept':'ECB deposit facility, percent; effective 2026-09-16'},
    {'id':'EU_HICP_2026-09_FLASH','factor':'inflation','time':None,'zone':None,'kind':'historical_release_date_only','value':'3.8','concept':'Euro area HICP September 2026 flash annual rate, percent'},
    {'id':'EU_HICP_2026-09_FULL','factor':'inflation','time':None,'zone':None,'kind':'historical_release_date_only','value':'3.8','concept':'Euro area HICP September 2026 final annual rate, percent'},
    {'id':'EU_HICP_2026-10_FLASH','factor':'inflation','time':None,'zone':None,'kind':'historical_release_date_only','value':'4.0','concept':'Euro area HICP October 2026 flash annual rate, percent'},
    {'id':'EU_INDUSTRY_2026-09','factor':'activity','time':None,'zone':None,'kind':'historical_release_date_only','value':None,'concept':'Euro area industrial production September 2026 monthly percent change'},
]

def build(rc79, rc80, rc83):
    valid = (rc79.get('model_version','').startswith('eur-rc7.9-') and rc80.get('model_version','').startswith('eur-rc8.0-') and rc83.get('model_version','').startswith('eur-rc8.3-') and all(x.get('input_valid') is True for x in (rc79,rc80,rc83)) and all(x.get('eligible_count')==0 and x.get('relative_score') is None for x in (rc79,rc80,rc83)))
    docs = {d.get('event_id'):d for d in rc79.get('documents',[])}
    snapshots = {}
    for s in rc80.get('historical_snapshots',[]):
        snapshots.setdefault(s.get('event_id'),[]).append(s)
    diffs = {d.get('event_id'):d for d in rc83.get('comparisons',[])}
    out = {'model_version':VERSION,'asset':'EUR/USD','module':'first_dissemination_chronology','input_valid':valid,'evidence_events':[],'methodology':{'time_type_policy':'embargo/schedule/press-conference != observed first dissemination','date_only_vintage_policy':'ALFRED date snapshot != intraday first-release proof','ecb_policy':'press conference != monetary policy decision announcement; effective date separate','eurostat_policy':'headline text != original full dataset vintage','document_policy':'retrieval time/hash != historical release time'}}
    for e in EVENTS:
        d=docs.get(e['id'],{})
        t=None
        if e['time']:
            t=datetime.fromisoformat(e['time']).replace(tzinfo=ZoneInfo(e['zone'])).astimezone(timezone.utc).isoformat().replace('+00:00','Z')
        snap=snapshots.get(e['id'],[])
        diff=diffs.get(e['id'],{})
        out['evidence_events'].append({'event_id':e['id'],'factor':e['factor'],'official_document_retrieved':d.get('status')=='retrieved','official_source_url':d.get('source_url') or d.get('official_source_url'),'scheduled_or_embargo_local':e['time'],'scheduled_timezone':e['zone'],'scheduled_or_embargo_utc':t,'time_claim_type':e['kind'],'reported_value_candidate':e['value'],'indicator_concept':e['concept'],'historical_snapshots':[{'series_id':s.get('series_id'),'asof_date':s.get('asof_date'),'value':s.get('value'),'numeric_match_candidate':s.get('numeric_match_candidate')} for s in snap],'cross_run_document_classification':diff.get('classification'),'documentary_candidate_present':bool(d.get('evidence_candidates') or d.get('matching_excerpt_count') or d.get('status')=='retrieved'),'independent_actual_first_dissemination_verified':False,'original_dataset_vintage_verified':False,'same_concept_unit_confirmed':False,'point_in_time_usable':False,'evidence_grade':'document_and_schedule_only' if t else 'document_and_date_only','blocking_reasons':['No independently observed first public dissemination timestamp','No authenticated original complete dataset vintage','No independent concept/unit mapping']})
    out.update(events_reviewed=len(out['evidence_events']),documents_available=sum(e['official_document_retrieved'] for e in out['evidence_events']),events_with_time_claim=sum(e['scheduled_or_embargo_utc'] is not None for e in out['evidence_events']),verified_point_in_time_events=0,historical_first_release_vintages_verified=False,historical_release_timestamps_verified=False,point_in_time_integrity_verified=False,eligibility={f:False for f in FACTORS},eligible_count=0,coverage=0.0,relative_score=None,horizons={'1d':{'score':None},'5d':{'score':None}},point_in_time_backtest_authorized=False,signals_generated=False,database_writes=False,production_change_authorized=False,source_code_modified=False,next_step='Collect independently timestamped release capture and original archived full-series vintage; verify time claims per event.')
    return out

def self_test():
    a={'model_version':'eur-rc7.9-test','input_valid':True,'eligible_count':0,'relative_score':None,'documents':[{'event_id':e['id'],'status':'retrieved'} for e in EVENTS]}
    b={'model_version':'eur-rc8.0-test','input_valid':True,'eligible_count':0,'relative_score':None,'historical_snapshots':[]}
    c={'model_version':'eur-rc8.3-test','input_valid':True,'eligible_count':0,'relative_score':None,'comparisons':[]}
    r=build(a,b,c)
    assert r['input_valid'] and r['events_reviewed']==7 and r['events_with_time_claim']==3
    assert next(e for e in r['evidence_events'] if e['event_id']=='US_UNRATE_2025-11_BLS')['scheduled_or_embargo_utc']=='2025-12-16T13:30:00Z'
    assert next(e for e in r['evidence_events'] if e['event_id']=='US_FOMC_2026-09-16')['scheduled_or_embargo_utc']=='2026-09-16T18:00:00Z'
    assert r['verified_point_in_time_events']==0 and not any(r['eligibility'].values())
    print('RC84_SELF_TEST_OK')

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--rc79',default='eur_rc79_result.json');p.add_argument('--rc80',default='eur_rc80_result.json');p.add_argument('--rc83',default='eur_rc83_result.json');p.add_argument('--output',default='eur_rc84_result.json');p.add_argument('--self-test',action='store_true')
    args=p.parse_args()
    if args.self_test: return self_test()
    r=build(*(json.loads(Path(path).read_text(encoding='utf-8')) for path in (args.rc79,args.rc80,args.rc83)))
    Path(args.output).write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('RC84_OK',r['input_valid'],'events',r['events_reviewed'],'verified',r['verified_point_in_time_events'])
    if not r['input_valid']: raise SystemExit(2)
if __name__=='__main__':main()
