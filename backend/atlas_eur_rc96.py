#!/usr/bin/env python3
"""Atlas EUR RC9.6: diagnose Eurostat HICP geography and units without silent substitutions."""
import argparse, json, os
from pathlib import Path
from urllib.parse import urlencode
import atlas_eur_rc95 as base

VERSION='eur-rc9.6-hicp-metadata-diagnostics-0.9.6'
DATASET='prc_hicp_midx'

def metadata(data):
    out={'dataset_label':data.get('label'),'updated':data.get('updated'),'dimensions':{},'observations_count':len(data.get('value',{}))}
    for name in data.get('id',[]):
        d=data.get('dimension',{}).get(name,{})
        try: codes=list(base.categories(d))
        except Exception: codes=[]
        out['dimensions'][name]={'size':len(codes),'codes':codes[:100], 'truncated':len(codes)>100}
    return out

def diagnose(fetch):
    # Deliberately omit geo and unit to inspect what the dataset actually exposes.
    url=base.EU_BASE+DATASET+'?'+urlencode({'freq':'M','coicop':'CP00','lang':'EN','sinceTimePeriod':'2025-01'})
    report={'metadata_request_url':url,'metadata_status':'error','candidates':[]}
    try:
        data,audit=fetch(url)
        report.update(metadata_status='ok',metadata=metadata(data),metadata_audit=audit)
        geos=set(base.categories(data['dimension']['geo'])) if 'geo' in data.get('dimension',{}) else set()
        units=set(base.categories(data['dimension']['unit'])) if 'unit' in data.get('dimension',{}) else set()
    except Exception as exc:
        report['metadata_error']=type(exc).__name__+': '+str(exc)[:220]
        return report,None
    # Candidate geography EA20 is *not* automatically substituted for EA21.
    selected=None
    for geo in ('EA21','EA20'):
        for unit in ('I25','I15'):
            item={'geo':geo,'unit':unit,'geography_matches_requested':geo=='EA21',
                  'category_present_in_metadata':geo in geos and unit in units}
            if not item['category_present_in_metadata']:
                item['status']='not_listed_in_metadata';report['candidates'].append(item);continue
            candidate_url=base.EU_BASE+DATASET+'?'+urlencode({'freq':'M','coicop':'CP00','geo':geo,'unit':unit,'lang':'EN','sinceTimePeriod':'2024-01'})
            item['source_url']=candidate_url
            try:
                cube,audit=fetch(candidate_url)
                obs,selection=base.decode_jsonstat(cube,{'geo':geo,'unit':unit})
                item.update(status='ok' if obs else 'no_observations',resolved_selection=selection,
                            latest_period=obs[-1]['period'] if obs else None,
                            observation_count=len(obs),audit=audit)
                if geo=='EA21' and obs and selected is None:
                    selected={'status':'ok','dataset':DATASET,'region':geo,'resolved_selection':selection,
                              'source_url':candidate_url,'observations':obs,'audit':audit,
                              'provider_updated':cube.get('updated'),'first_publication_time_verified':False}
            except Exception as exc:
                item.update(status='error',error_type=type(exc).__name__,error_message=str(exc)[:220])
            report['candidates'].append(item)
    return report,selected

def collect(key,fetch=base.fetch_json):
    result=base.collect(key,fetch)
    diag,selected=diagnose(fetch)
    result['model_version']=VERSION
    result['hicp_metadata_diagnostics']=diag
    if selected:
        result['series']['inflation']['EA']=selected
        us=result['series']['inflation']['US']
        if us['status']=='ok':
            result['paired_diagnostics']['inflation']=base.aligned_diagnostic(us['observations'],selected['observations'],'inflation')
    result['successful_series']=sum(x['status']=='ok' for pair in result['series'].values() for x in pair.values())
    result['complete_pairs']=sum(all(x['status']=='ok' for x in pair.values()) for pair in result['series'].values())
    result['hicp_ea21_collected']=selected is not None
    result['limitations'].append('EA20 is diagnostic only and is never silently used as EA21.')
    return result

def self_test():
    base.self_test()
    cube={'id':['geo','unit','time'],'size':[2,2,2],
          'dimension':{'geo':{'category':{'index':{'EA20':0,'EA21':1}}},
                       'unit':{'category':{'index':{'I15':0,'I25':1}}},
                       'time':{'category':{'index':{'2025-09':0,'2026-09':1}}}},
          'value':{'0':100,'1':103,'2':100,'3':104,'4':100,'5':105,'6':100,'7':106}}
    def fetch(url):return cube,{'response_sha256':'mock','response_bytes':10}
    d,s=diagnose(fetch)
    assert d['metadata_status']=='ok' and s['region']=='EA21' and s['observations'][-1]['value']==106
    assert len(d['candidates'])==4
    print('RC96_SELF_TEST_OK')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--self-test',action='store_true');p.add_argument('--output',default='eur_rc96_result.json');args=p.parse_args()
    if args.self_test:self_test()
    else:
        key=os.getenv('FRED_API_KEY','').strip()
        if not key:raise SystemExit('FRED_API_KEY is required')
        result=collect(key)
        Path(args.output).write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
        print('RC96_OK',result['successful_series'],'/',result['requested_series'],'pairs',result['complete_pairs'])
