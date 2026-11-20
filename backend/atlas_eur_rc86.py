#!/usr/bin/env python3
"""Atlas EUR RC8.6 — source feasibility matrix and prospective capture specification.

Research-only. No network calls, orders, signals, scores, database writes, or schedulers.
Catalog entries are documented capabilities, NOT evidence that a vintage was obtained.
"""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

VERSION = 'eur-rc8.6-source-feasibility-prospective-plan-0.8.6'
FACTORS = ('inflation', 'rates', 'unemployment', 'activity')
CATALOG = {
    'BLS_ARCHIVE': {'name':'BLS archived news releases', 'url':'https://www.bls.gov/bls/news-release/home.htm',
        'capability':'archived_headline_and_release_text', 'limitation':'Archive content does not independently establish observed first dissemination second or full original dataset vintage.'},
    'ALFRED': {'name':'ALFRED/FRED historical vintages', 'url':'https://fred.stlouisfed.org/docs/api/fred/series_vintagedates.html',
        'capability':'historical_date_granularity_series_versions', 'limitation':'Vintage date granularity is daily; series revisions do not establish observed intraday dissemination.'},
    'FED_RELEASE': {'name':'Federal Reserve official FOMC releases', 'url':'https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm',
        'capability':'dated_official_decision_text', 'limitation':'Scheduled time and current HTTP Last-Modified do not independently prove original public availability.'},
    'ECB_RELEASE': {'name':'ECB monetary policy decisions', 'url':'https://www.ecb.europa.eu/press/pr/date/html/index.en.html',
        'capability':'dated_official_decision_text', 'limitation':'Press conference time, decision announcement, and effective date are distinct.'},
    'EUROSTAT_API': {'name':'Eurostat API latest datasets', 'url':'https://ec.europa.eu/eurostat/en/web/user-guides/data-browser/api-data-access/api-introduction',
        'capability':'current_dataset_and_metadata', 'limitation':'Official API states it retains latest data and does not provide historical dataset versioning.'},
    'EUROSTAT_RELEASE': {'name':'Eurostat archived euro-indicator releases', 'url':'https://ec.europa.eu/eurostat/web/products-euro-indicators',
        'capability':'dated_headline_release_text', 'limitation':'Archived release headline is not the authenticated complete original dataset.'},
}
SOURCE_MAP = {
    'US_UNRATE_2025-11_BLS':['BLS_ARCHIVE','ALFRED'],
    'US_FOMC_2026-09-16':['FED_RELEASE','ALFRED'],
    'EU_ECB_2026-09-10':['ECB_RELEASE','ALFRED'],
    'EU_HICP_2026-09_FLASH':['EUROSTAT_RELEASE','EUROSTAT_API'],
    'EU_HICP_2026-09_FULL':['EUROSTAT_RELEASE','EUROSTAT_API'],
    'EU_HICP_2026-10_FLASH':['EUROSTAT_RELEASE','EUROSTAT_API'],
    'EU_INDUSTRY_2026-09':['EUROSTAT_RELEASE','EUROSTAT_API','ALFRED'],
}

PROSPECTIVE = {
    'status':'specification_only_not_deployed',
    'trigger':'Future scheduled official releases, configured per source with a verified release calendar',
    'capture_fields':['event_id','indicator_concept','units','period','geography','seasonal_adjustment','source_url','request_started_at_utc','response_received_at_utc','response_status','server_date_header','content_sha256','raw_payload_path','parser_version','extracted_value','release_calendar_reference'],
    'timestamp_policy':'Client receipt time is an upper bound on observed availability to this collector, not the globally first publication instant.',
    'retention':'Immutable raw bytes and append-only manifest; independently timestamped external evidence needed for stronger historical claims.',
    'safety':'Do not store credentials in artifacts; no production writes, trading signals, scores, or backtests.',
    'deployment_authorized':False,
}

def build(rc85):
    events=rc85.get('events',[])
    ids=[e.get('event_id') for e in events]
    valid=(rc85.get('model_version','').startswith('eur-rc8.5-') and rc85.get('input_valid') is True
        and rc85.get('eligible_count')==0 and rc85.get('coverage')==0.0 and rc85.get('relative_score') is None
        and len(events)==7 and len(set(ids))==7 and set(ids)==set(SOURCE_MAP)
        and all(not e.get('point_in_time_usable',True) for e in events))
    matrix=[]
    for e in events:
        eid=e.get('event_id')
        matrix.append({
            'event_id':eid,'factor':e.get('factor'),
            'source_candidates':[{'source_id':sid,**CATALOG[sid], 'historical_evidence_retrieved_by_rc86':False} for sid in SOURCE_MAP.get(eid,[])],
            'prior_official_document':bool(e.get('source_url')),
            'prior_http_probe_status':e.get('http_metadata',{}).get('status'),
            'first_dissemination_timestamp_verified':False,
            'full_first_release_dataset_vintage_verified':False,
            'concept_unit_mapping_verified':False,
            'point_in_time_usable':False,
            'recommended_next_action':('Acquire original archived complete release tables and independently timestamped distribution record'
              if eid.startswith('US_') else 'Seek timestamped original release archive or begin prospective immutable capture'),
            'source_feasibility_not_proof':True,
        })
    return {
        'model_version':VERSION,'asset':'EUR/USD','module':'source_feasibility_and_prospective_capture_plan',
        'asof_utc':datetime.now(timezone.utc).isoformat(),'input_model_version':rc85.get('model_version'),
        'input_valid':valid,'source_catalog':CATALOG,'event_matrix':matrix,
        'events_reviewed':len(matrix),'source_candidates_mapped':sum(len(e['source_candidates']) for e in matrix),
        'new_historical_vintages_retrieved':0,'new_first_dissemination_timestamps_verified':0,
        'prospective_capture_plan':PROSPECTIVE,'prospective_capture_active':False,
        'verified_point_in_time_events':0,'historical_first_release_vintages_verified':False,
        'historical_release_timestamps_verified':False,'point_in_time_integrity_verified':False,
        'eligibility':{f:False for f in FACTORS},'eligible_count':0,'coverage':0.0,'relative_score':None,
        'horizons':{'1d':{'score':None},'5d':{'score':None}},
        'point_in_time_backtest_authorized':False,'signals_generated':False,'database_writes':False,
        'production_change_authorized':False,'source_code_modified':False,
        'next_step':'Prioritize independent historical evidence acquisition; separately approve and implement prospective capture if desired.'
    }

def self_test():
    example={'model_version':'eur-rc8.5-test','input_valid':True,'eligible_count':0,'coverage':0.0,'relative_score':None,
        'events':[{'event_id':k,'factor':'rates','point_in_time_usable':False,'source_url':'https://example.org',
                   'http_metadata':{'status':'request_failed'}} for k in SOURCE_MAP]}
    result=build(example)
    assert result['input_valid'] and result['events_reviewed']==7
    assert result['source_candidates_mapped']==15
    assert all(not x['point_in_time_usable'] for x in result['event_matrix'])
    assert not result['prospective_capture_active'] and not result['prospective_capture_plan']['deployment_authorized']
    assert result['relative_score'] is None and result['eligible_count']==0
    assert not any(result[k] for k in ('signals_generated','database_writes','production_change_authorized','point_in_time_backtest_authorized'))
    print('RC86_SELF_TEST_OK')

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--input',default='eur_rc85_result.json')
    p.add_argument('--output',default='eur_rc86_result.json')
    p.add_argument('--self-test',action='store_true')
    args=p.parse_args()
    if args.self_test:
        self_test();return
    result=build(json.loads(Path(args.input).read_text(encoding='utf-8')))
    Path(args.output).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('RC86_OK',result['input_valid'],'events',result['events_reviewed'])
    if not result['input_valid']:
        raise SystemExit(2)

if __name__=='__main__':main()
