"""Atlas EUR RC6.6: auditoria documental de comunicados HICP.
Somente leitura de paginas oficiais; nao calcula score nem altera producao.
"""
import json
import re
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser

VERSION = 'eur-rc6.6-eurostat-release-archive-audit-0.6.6'
RELEASES = [
    {'period':'2026-09','kind':'flash','publication_date':'2026-10-02','reported_yoy_pct':3.8,
     'url':'https://ec.europa.eu/eurostat/web/products-euro-indicators/w/2-02102026-ap'},
    {'period':'2026-09','kind':'full','publication_date':'2026-10-16','reported_yoy_pct':3.8,
     'url':'https://ec.europa.eu/eurostat/en/web/products-euro-indicators/w/2-16102026-ap'},
    {'period':'2026-10','kind':'flash','publication_date':'2026-11-04','reported_yoy_pct':4.0,
     'url':'https://ec.europa.eu/eurostat/en/web/products-euro-indicators/w/2-04112026-ap'},
]
PRIOR_SCHEDULE = {'2026-09':'2026-10-15','2026-10':'2026-11-17'}

class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(); self.parts=[]; self.skip=0
    def handle_starttag(self,tag,attrs):
        if tag in ('script','style','noscript'): self.skip+=1
    def handle_endtag(self,tag):
        if tag in ('script','style','noscript') and self.skip: self.skip-=1
    def handle_data(self,data):
        if not self.skip: self.parts.append(data)

def fetch_release(url):
    req=urllib.request.Request(url,headers={'User-Agent':'AtlasEUR-RC66/0.6.6 (research audit)','Accept':'text/html'})
    with urllib.request.urlopen(req,timeout=25) as response:
        final_url=response.geturl()
        raw=response.read(1_500_001)
        if len(raw)>1_500_000: raise ValueError('Pagina excede 1.5 MB')
        content_type=response.headers.get('Content-Type','')
    if 'html' not in content_type.lower(): raise ValueError('Resposta nao e HTML')
    p=TextExtractor(); p.feed(raw.decode('utf-8','replace'))
    return {'text':' '.join(' '.join(p.parts).split()),'final_url':final_url,'bytes':len(raw)}

def evaluate(fetcher=fetch_release,now=None):
    now=now or datetime.now(timezone.utc)
    records=[]
    for spec in RELEASES:
        record={**spec,'source':'Eurostat','publication_date_source':'official_press_release_page',
                'actual_intraday_publication_time_verified':False,
                'dataset_vintage_verified':False,'page_retrieved':False,
                'headline_rate_verified_in_page':False}
        try:
            page=fetcher(spec['url']); body=page['text']
            record['page_retrieved']=True
            record['resolved_url']=page.get('final_url',spec['url'])
            # Match a clearly labelled headline in the page; do not confuse with table values.
            patterns=[rf'(?:annual inflation (?:up to |is expected to be )){spec["reported_yoy_pct"]:.1f}%',
                      rf'(?:annual inflation rate was ){spec["reported_yoy_pct"]:.1f}%']
            record['headline_rate_verified_in_page']=any(re.search(p,body,re.I) for p in patterns)
            record['status']='headline_confirmed' if record['headline_rate_verified_in_page'] else 'retrieved_headline_not_confirmed'
        except Exception as exc:
            record['status']='retrieval_error'
            record['error']=f'{type(exc).__name__}: {str(exc)[:200]}'
        records.append(record)
    sep_full=next(r for r in records if r['period']=='2026-09' and r['kind']=='full')
    sep_flash=next(r for r in records if r['period']=='2026-09' and r['kind']=='flash')
    oct_flash=next(r for r in records if r['period']=='2026-10' and r['kind']=='flash')
    return {
        'model_version':VERSION,'asof_utc':now.isoformat().replace('+00:00','Z'),'asset':'EUR/USD',
        'official_release_archive':records,
        'historical_calendar_discrepancies':[
            {'period':'2026-09','rc65_scheduled_date':PRIOR_SCHEDULE['2026-09'],
             'official_full_release_page_date':sep_full['publication_date'],
             'dates_disagree':True,'explanation':'Calendario anterior e data do comunicado sao evidencias distintas; exige auditoria, nao substituicao silenciosa.'},
            {'period':'2026-10','rc65_scheduled_date':PRIOR_SCHEDULE['2026-10'],
             'official_full_release_page_date':None,'full_release_status':'not_identified_in_this_audit',
             'note':'Nao afirmar que o comunicado completo foi publicado.'}],
        'flash_vs_full':[
            {'period':'2026-09','flash_date':sep_flash['publication_date'],'full_date':sep_full['publication_date'],
             'flash_yoy_pct':sep_flash['reported_yoy_pct'],'full_yoy_pct':sep_full['reported_yoy_pct'],
             'headline_values_equal':sep_flash['reported_yoy_pct']==sep_full['reported_yoy_pct'],
             'both_pages_headline_confirmed':sep_flash['headline_rate_verified_in_page'] and sep_full['headline_rate_verified_in_page']},
            {'period':'2026-10','flash_date':oct_flash['publication_date'],'full_date':None,
             'flash_yoy_pct':oct_flash['reported_yoy_pct'],'full_yoy_pct':None}],
        'official_pages_retrieved':sum(r['page_retrieved'] for r in records),
        'official_headlines_confirmed':sum(r['headline_rate_verified_in_page'] for r in records),
        'eu_original_press_release_headlines_verified':all(r['headline_rate_verified_in_page'] for r in records),
        'eu_original_dataset_vintages_verified':False,
        'actual_intraday_release_times_verified':False,
        'historical_vintage_per_observation_verified':False,
        'point_in_time_backtest_authorized':False,
        'eligibility':{'inflation':False,'unemployment':False,'rates':False,'activity':False},
        'eligible_count':0,'coverage':0.0,'relative_score':None,
        'horizons':{'1d':{'score':None},'5d':{'score':None}},
        'signals_generated':False,'database_writes':False,
        'production_change_authorized':False,'source_code_modified':False,
        'limitations':['Comunicado de imprensa nao equivale a vintage integral da serie prc_hicp_minr EA21.',
                       'Data na pagina nao comprova o instante intradiario da publicacao.',
                       'Estimativa flash e divulgacao completa sao eventos distintos.',
                       'A divergencia entre calendario anterior e pagina oficial exige conciliacao documental.',
                       'Nenhum score, sinal, backtest ou escrita em banco.']}

if __name__=='__main__':
    print(json.dumps(evaluate(),ensure_ascii=False,indent=2))
