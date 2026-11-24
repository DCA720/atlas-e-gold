#!/usr/bin/env python3
"""Atlas EUR RC9.8: current Eurostat HICP dataset; read-only research diagnostics."""
import argparse, json, os
from pathlib import Path
from urllib.parse import urlencode
import atlas_eur_rc95 as base

VERSION='eur-rc9.8-targeted-hicp-0.9.8'
DATASET='prc_hicp_minr'


def describe_cube(data):
    dims={}
    for name in data.get('id',[]):
        try: codes=list(base.categories(data['dimension'][name]))
        except (KeyError,TypeError,ValueError): codes=[]
        dims[name]={'count':len(codes),'codes':codes[:75]}
    return {'label':data.get('label'),'updated':data.get('updated'),'dimensions':dims}


def collect_hicp(fetch):
    report={'dataset':DATASET,'attempts':[],'status':'error'}
    for dataset in (DATASET,'teicp000'):
        selected={'freq':'M','geo':'EA21','coicop18':'TOTAL','unit':'RCH_A'}
        p={**selected,'lang':'EN','sinceTimePeriod':'2025-01'}
        url=base.EU_BASE+dataset+'?'+urlencode(p)
        attempt={'dataset':dataset,'url':url}
        try:
            data,audit=fetch(url)
            attempt.update(metadata=describe_cube(data),audit=audit)
            points,selection=base.decode_jsonstat(data,selected)
            if any(selection.get(k)!=v for k,v in selected.items()):
                raise ValueError('selection_mismatch')
            if not points or points[-1]['period']<'2026-01':
                raise ValueError('missing_2026_observations')
            attempt.update(status='ok',latest_period=points[-1]['period'])
            report['attempts'].append(attempt)
            report['status']='ok'
            return {'status':'ok','dataset':dataset,'region':'EA21','requested_selection':p,
                    'resolved_selection':selection,'source_url':url,'observations':points,
                    'unit_kind':'annual_rate_percent','audit':audit,'provider_updated':data.get('updated'),
                    'first_publication_time_verified':False},report
        except Exception as exc:
            attempt.update(status='error',error_type=type(exc).__name__,error_message=str(exc)[:240])
            report['attempts'].append(attempt)
    return {'status':'error','error_message':'all_targeted_hicp_queries_failed'},report


def annual_diagnostic(us,ea):
    u={x['period']:x['value'] for x in us};e={x['period']:x['value'] for x in ea['observations']}
    common=sorted(set(u)&set(e))
    for month in reversed(common):
        yearago=f'{int(month[:4])-1:04d}-{month[5:]}'
        if yearago not in u or not u[yearago]:continue
        if ea['unit_kind']=='index':
            if yearago not in e or not e[yearago]:continue
            ea_yoy=(e[month]/e[yearago]-1)*100
        else:ea_yoy=e[month]
        return {'status':'aligned_descriptive_only','latest_aligned_period':month,
                'comparison':'annual_inflation_rates_percent','us_change':round((u[month]/u[yearago]-1)*100,5),
                'ea_change':round(ea_yoy,5),'ea_source_unit':ea['resolved_selection']['unit'],
                'directional_score_authorized':False}
    return {'status':'insufficient_aligned_year_ago_observations','directional_score_authorized':False}


def collect(key,fetch=base.fetch_json):
    def current_only(url):
        if '/prc_hicp_midx?' in url:
            raise ValueError('legacy_hicp_disabled')
        return fetch(url)
    result=base.collect(key,current_only)
    # Replace legacy HICP result with current-dataset attempt, leaving other series untouched.
    hicp,diag=collect_hicp(fetch)
    result['model_version']=VERSION
    result['hicp_current_dataset_diagnostics']=diag
    result['series']['inflation']['EA']=hicp
    us=result['series']['inflation']['US']
    if us['status']=='ok' and hicp['status']=='ok':
        result['paired_diagnostics']['inflation']=annual_diagnostic(us['observations'],hicp)
    else:result['paired_diagnostics']['inflation']={'status':'incomplete_pair','directional_score_authorized':False}
    result['successful_series']=sum(v['status']=='ok' for p in result['series'].values() for v in p.values())
    result['complete_pairs']=sum(all(v['status']=='ok' for v in p.values()) for p in result['series'].values())
    result['limitations'].extend(['Current Eurostat dataset prc_hicp_minr replaces discontinued prc_hicp_midx.',
                                  'Annual inflation rates compare CPI US and HICP EA, distinct price baskets.',
                                  'No fixed predictions, validated accuracy, or production writes.'])
    return result


def self_test():
    base.self_test()
    dims={'freq':['M'],'unit':['RCH_A'],'coicop18':['TOTAL'],'geo':['EA21'],'time':['2026-09']}
    mock={'id':list(dims),'size':[1]*5,'dimension':{k:{'category':{'index':{v:i for i,v in enumerate(vals)}}} for k,vals in dims.items()},'value':{'0':2.4}}
    from urllib.parse import parse_qs,urlsplit
    def fetch(url):
        q=parse_qs(urlsplit(url).query)
        assert q['coicop18']==['TOTAL'] and q['geo']==['EA21'] and q['unit']==['RCH_A']
        assert 'coicop' not in q
        return mock,{}
    h,d=collect_hicp(fetch)
    assert h['status']=='ok' and h['observations'][0]['value']==2.4
    from urllib.error import HTTPError
    def fallback(url):
        if DATASET in url:raise HTTPError(url,413,'too large',None,None)
        return fetch(url)
    h,d=collect_hicp(fallback)
    assert h['dataset']=='teicp000' and len(d['attempts'])==2
    mock['dimension']['geo']['category']['index']={'EA20':0}
    assert collect_hicp(fetch)[0]['status']=='error'
    print('RC98_SELF_TEST_OK')

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--self-test',action='store_true')
    parser.add_argument('--output',default='eur_rc98_result.json')
    args=parser.parse_args()
    if args.self_test:self_test()
    else:
        key=os.getenv('FRED_API_KEY','').strip()
        if not key:raise SystemExit('FRED_API_KEY is required')
        result=collect(key)
        Path(args.output).write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
        print('RC98_OK',result['successful_series'],'/',result['requested_series'],'pairs',result['complete_pairs'])
