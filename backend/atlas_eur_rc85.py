#!/usr/bin/env python3
"""Atlas EUR RC8.5: independent HTTP metadata probe and evidence provenance (read-only).

HTTP Date/Last-Modified are response metadata, NEVER historical publication proof.
"""
import argparse
import json
import re
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

VERSION = 'eur-rc8.5-independent-publication-provenance-0.8.5'
FACTORS = ('inflation', 'rates', 'unemployment', 'activity')
HOSTS = {'www.bls.gov', 'www.federalreserve.gov', 'www.ecb.europa.eu', 'ec.europa.eu'}

def probe(url, enabled=True):
    host = urlsplit(url or '').hostname
    if not url or urlsplit(url).scheme != 'https' or host not in HOSTS:
        return {'status':'rejected_url','independent_publication_proof':False}
    if not enabled:
        return {'status':'offline_not_queried','independent_publication_proof':False}
    req = urllib.request.Request(url, method='HEAD', headers={'User-Agent':'AtlasEUR-RC85-Research/0.8.5'})
    try:
        with urllib.request.urlopen(req, timeout=12) as response:
            headers = response.headers
            return {'status':'http_response','http_status':response.status,'response_date':headers.get('Date'),
                    'last_modified':headers.get('Last-Modified'),'etag':headers.get('ETag'),
                    'content_type':headers.get('Content-Type'),'final_host':urlsplit(response.url).hostname,
                    'independent_publication_proof':False,
                    'interpretation':'Response metadata at audit time, not first historical dissemination.'}
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as exc:
        return {'status':'request_failed','error_type':type(exc).__name__,
                'independent_publication_proof':False}

def build(rc84, online=False, probe_func=probe):
    events=rc84.get('evidence_events',[])
    valid=(rc84.get('model_version','').startswith('eur-rc8.4-') and rc84.get('input_valid') is True
           and rc84.get('eligible_count')==0 and rc84.get('relative_score') is None
           and len(events)==7 and all(not x.get('point_in_time_usable',True) for x in events))
    out={'model_version':VERSION,'asset':'EUR/USD','module':'independent_publication_provenance',
         'asof_utc':datetime.now(timezone.utc).isoformat(),'input_model_version':rc84.get('model_version'),
         'input_valid':valid,'network_probe_enabled':bool(online),'events':[]}
    for e in events:
        url=e.get('official_source_url')
        p=probe_func(url,online)
        types=[]
        if e.get('official_document_retrieved'): types.append('official_document_retrieved_at_audit')
        if e.get('scheduled_or_embargo_utc'): types.append(e.get('time_claim_type','scheduled_or_embargo'))
        if e.get('historical_snapshots'): types.append('alfred_date_granularity_snapshot')
        if p.get('status')=='http_response': types.append('current_http_response_metadata')
        out['events'].append({
            'event_id':e.get('event_id'),'factor':e.get('factor'),'source_url':url,
            'time_claim_type':e.get('time_claim_type'),'scheduled_or_embargo_utc':e.get('scheduled_or_embargo_utc'),
            'evidence_types':types,'http_metadata':p,
            'evidence_grade':'historical_document_plus_schedule_not_pit' if e.get('scheduled_or_embargo_utc') else 'historical_document_date_only_not_pit',
            'independent_first_dissemination_timestamp_utc':None,
            'independent_first_dissemination_verified':False,
            'original_full_dataset_vintage_verified':False,
            'concept_and_unit_mapping_verified':False,
            'point_in_time_usable':False,
            'missing_evidence':['Independently observed event-specific first dissemination timestamp',
                                'Timestamped authenticated first-release complete dataset vintage',
                                'Independently validated indicator concept and unit mapping']})
    out.update(events_reviewed=len(out['events']),http_responses=sum(x['http_metadata']['status']=='http_response' for x in out['events']),
               independent_dissemination_timestamps_verified=0,verified_point_in_time_events=0,
               historical_first_release_vintages_verified=False,historical_release_timestamps_verified=False,
               point_in_time_integrity_verified=False,eligibility={f:False for f in FACTORS},eligible_count=0,
               coverage=0.0,relative_score=None,horizons={'1d':{'score':None},'5d':{'score':None}},
               point_in_time_backtest_authorized=False,signals_generated=False,database_writes=False,
               production_change_authorized=False,source_code_modified=False,
               next_step='Obtain independent timestamped archived first-release feeds and full original dataset vintages; HTTP headers cannot prove these.')
    return out

def self_test():
    r={'model_version':'eur-rc8.4-test','input_valid':True,'eligible_count':0,'relative_score':None,
       'evidence_events':[{'event_id':str(i),'factor':FACTORS[i%4], 'official_source_url':'https://www.bls.gov/test',
                           'official_document_retrieved':True,'point_in_time_usable':False,
                           'scheduled_or_embargo_utc':'2026-09-16T18:00:00Z' if i<3 else None} for i in range(7)]}
    o=build(r,online=False)
    assert o['input_valid'] and o['events_reviewed']==7 and o['http_responses']==0
    assert o['eligible_count']==0 and o['relative_score'] is None
    assert not any(e['point_in_time_usable'] for e in o['events'])
    assert all(e['http_metadata']['status']=='offline_not_queried' for e in o['events'])
    print('RC85_SELF_TEST_OK')

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--input',default='eur_rc84_result.json')
    parser.add_argument('--output',default='eur_rc85_result.json')
    parser.add_argument('--online',action='store_true',help='Read-only official HTTP HEAD metadata requests')
    parser.add_argument('--self-test',action='store_true')
    args=parser.parse_args()
    if args.self_test: return self_test()
    r=build(json.loads(Path(args.input).read_text(encoding='utf-8')),online=args.online)
    Path(args.output).write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('RC85_OK',r['input_valid'],'events',r['events_reviewed'],'http',r['http_responses'])
    if not r['input_valid']: raise SystemExit(2)
if __name__=='__main__':main()
