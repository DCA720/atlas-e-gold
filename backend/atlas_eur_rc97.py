#!/usr/bin/env python3
"""Atlas EUR RC9.7: current Eurostat HICP dataset; read-only research diagnostics."""
import argparse, json, os
from pathlib import Path
from urllib.parse import urlencode
import atlas_eur_rc95 as base

VERSION='eur-rc9.7-current-hicp-dataset-0.9.7'
DATASET='prc_hicp_minr'


def describe_cube(data):
    dims={}
    for name in data.get('id',[]):
        try: codes=list(base.categories(data['dimension'][name]))
        except (KeyError,TypeError,ValueError): codes=[]
        dims[name]={'count':len(codes),'codes':codes[:75]}
    return {'label':data.get('label'),'updated':data.get('updated'),'dimensions':dims}


def collect_hicp(fetch):
    # New dataset may have revised COICOP classification; discover categories first.
    params={'freq':'M','coicop':'CP00','lang':'EN','sinceTimePeriod':'2025-01'}
    url=base.EU_BASE+DATASET+'?'+urlencode(params)
    report={'dataset':DATASET,'metadata_url':url,'status':'error','attempts':[]}
    try:
        cube,audit=fetch(url)
        report.update(metadata=describe_cube(cube),metadata_audit=audit,status='metadata_ok')
    except Exception as exc:
        report['error']=type(exc).__name__+': '+str(exc)[:240]
        return {'status':'error','error_type':type(exc).__name__,'error_message':str(exc)[:220]},report
    dimensions=cube.get('dimension',{})
    if not all(k in dimensions for k in ('geo','unit','coicop','time')):
        report['status']='unexpected_dimensions'
        return {'status':'error','error_message':'missing_required_dimensions'},report
    geos=base.categories(dimensions['geo']);units=base.categories(dimensions['unit']);coicops=base.categories(dimensions['coicop'])
    report['available_target_geographies']=[g for g in ('EA21','EA20','EA') if g in geos]
    report['available_total_categories']=[c for c in ('CP00','CP00-99','CP00_99') if c in coicops]
    report['available_index_units']=[u for u in ('I25','I15') if u in units]
    # Require exact EA21, never use EA20 or EA as a silent substitute.
    if 'EA21' not in geos:
        report['status']='ea21_unavailable'
        return {'status':'error','error_message':'EA21_not_in_current_dataset'},report
    # Prefer published annual rates if available, otherwise use index YoY.
    candidates=[]
    for code in ('CP00','CP00-99','CP00_99'):
        if code not in coicops:continue
        for unit in ('RCH_A','I25','I15'):
            if unit in units:candidates.append((code,unit))
    if not candidates:
        report['status']='total_hicp_unit_unavailable'
        return {'status':'error','error_message':'no_supported_total_hicp_unit'},report
    for coicop,unit in candidates:
        p={'freq':'M','geo':'EA21','coicop':coicop,'unit':unit,'lang':'EN','sinceTimePeriod':'2024-01'}
        candidate_url=base.EU_BASE+DATASET+'?'+urlencode(p)
        attempt={'geo':'EA21','coicop':coicop,'unit':unit,'url':candidate_url}
        try:
            data,req_audit=fetch(candidate_url)
            points,selection=base.decode_jsonstat(data,{'geo':'EA21','coicop':coicop,'unit':unit})
            if selection.get('geo')!='EA21' or selection.get('unit')!=unit or selection.get('coicop')!=coicop:
                raise ValueError('selection_mismatch')
            if not points:raise ValueError('no_observations')
            attempt.update(status='ok',latest_period=points[-1]['period'],count=len(points))
            report['attempts'].append(attempt)
            report['status']='ok'
            return {'status':'ok','dataset':DATASET,'region':'EA21','requested_selection':p,
                    'resolved_selection':selection,'source_url':candidate_url,'observations':points,
                    'unit_kind':'annual_rate_percent' if unit=='RCH_A' else 'index',
                    'audit':req_audit,'provider_updated':data.get('updated'),
                    'first_publication_time_verified':False},report
        except Exception as exc:
            attempt.update(status='error',error_type=type(exc).__name__,error_message=str(exc)[:160])
            report['attempts'].append(attempt)
    report['status']='all_candidates_failed'
    return {'status':'error','error_message':'all_hicp_candidates_failed'},report


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
    result=base.collect(key,fetch)
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
    # Metadata contains two regions and two unit types; annual-rate path selected.
    def cube(ids,categories,observations):
        return {'id':ids,'size':[len(categories[k]) for k in ids],
                'dimension':{k:{'category':{'index':{v:i for i,v in enumerate(categories[k])}}} for k in ids},
                'value':observations,'label':'mock HICP'}
    dims={'freq':['M'],'unit':['RCH_A','I25'],'coicop':['CP00'],'geo':['EA20','EA21'],
          'time':['2025-09','2026-09']}
    # offset: unit RCH_A, geo EA21, time 2026-09 => 3
    mock=cube(list(dims),dims,{'2':2.1,'3':2.4})
    def fetch(url):return mock,{'response_sha256':'mock','response_bytes':10}
    hicp,report=collect_hicp(fetch)
    assert hicp['status']=='ok' and hicp['region']=='EA21'
    assert hicp['unit_kind']=='annual_rate_percent' and hicp['observations'][-1]['value']==2.4
    assert report['status']=='ok'
    diagnostic=annual_diagnostic([{'period':'2025-09','value':100},{'period':'2026-09','value':103}],hicp)
    assert diagnostic['status']=='aligned_descriptive_only' and diagnostic['ea_change']==2.4
    missing=cube(list(dims),{**dims,'geo':['EA20']},{'0':1})
    def fetch_missing(url):return missing,{}
    h,d=collect_hicp(fetch_missing)
    assert h['status']=='error' and d['status']=='ea21_unavailable'
    print('RC97_SELF_TEST_OK')

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--self-test',action='store_true')
    parser.add_argument('--output',default='eur_rc97_result.json')
    args=parser.parse_args()
    if args.self_test:self_test()
    else:
        key=os.getenv('FRED_API_KEY','').strip()
        if not key:raise SystemExit('FRED_API_KEY is required')
        result=collect(key)
        Path(args.output).write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
        print('RC97_OK',result['successful_series'],'/',result['requested_series'],'pairs',result['complete_pairs'])
