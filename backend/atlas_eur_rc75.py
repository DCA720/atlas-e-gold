#!/usr/bin/env python3
"""Atlas EUR RC7.5 — auditoria documental oficial, somente leitura.

Busca documentos de fontes oficiais, registra evidencias verificaveis de
recuperacao (HTTP, hash, titulo), mas NAO confunde recuperacao com validacao
humana de horario, vintage ou valor original. Nunca autoriza score/backtest.
"""
import argparse
import datetime as dt
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import urllib.error
import urllib.request

VERSION = 'eur-rc7.5-official-document-retrieval-0.7.5'
FACTORS = ('inflation', 'rates', 'unemployment', 'activity')
OFFICIAL_HOSTS = {'ec.europa.eu', 'www.ecb.europa.eu', 'www.federalreserve.gov',
                  'www.bls.gov', 'www.census.gov', 'www.federalreserve.gov'}
EXTRA_DOCUMENTS = [
    ('rates', 'ECB monetary policy decisions', 'https://www.ecb.europa.eu/press/pr/date/html/index.en.html'),
    ('rates', 'Federal Reserve FOMC statements', 'https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm'),
    ('unemployment', 'BLS October 2025 survey methodology', 'https://www.bls.gov/cps/methods/2025-federal-government-shutdown-impact-cps.htm'),
    ('unemployment', 'BLS December 2025 employment release', 'https://www.bls.gov/news.release/archives/empsit_12162025.htm'),
    ('unemployment', 'Eurostat release calendar', 'https://ec.europa.eu/eurostat/news/euro-indicators/release-calendar'),
    ('activity', 'Eurostat industrial production news', 'https://ec.europa.eu/eurostat/web/products-euro-indicators'),
    ('activity', 'Federal Reserve G17 release', 'https://www.federalreserve.gov/releases/g17/'),
]

class TitleParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_title = False
        self.title = []
    def handle_starttag(self, tag, attrs):
        if tag.lower() == 'title': self.in_title = True
    def handle_endtag(self, tag):
        if tag.lower() == 'title': self.in_title = False
    def handle_data(self, data):
        if self.in_title: self.title.append(data)

def document_specs(source):
    specs = []
    for e in source.get('publication_events', []):
        if e.get('factor') == 'inflation' and e.get('source_url'):
            specs.append(('inflation', f"Eurostat {e.get('label')} {e.get('reference_period')}", e['source_url']))
    specs.extend(EXTRA_DOCUMENTS)
    return specs

def fetch_document(url, opener=None):
    from urllib.parse import urlsplit
    host = (urlsplit(url).hostname or '').lower()
    if urlsplit(url).scheme != 'https' or host not in OFFICIAL_HOSTS:
        return {'status': 'rejected_untrusted_host', 'http_status': None, 'sha256': None,
                'title': None, 'retrieved_at_utc': None, 'error': 'Non-allowlisted URL'}
    opener = opener or urllib.request.urlopen
    req = urllib.request.Request(url, headers={'User-Agent': 'AtlasEUR-ResearchAudit/0.7.5',
                                               'Accept': 'text/html,application/xhtml+xml,application/pdf'})
    try:
        with opener(req, timeout=18) as response:
            status = response.status
            final_url = response.geturl()
            final_host = (urlsplit(final_url).hostname or '').lower()
            if final_host not in OFFICIAL_HOSTS or urlsplit(final_url).scheme != 'https':
                return {'status': 'rejected_redirect', 'http_status': status, 'sha256': None,
                        'title': None, 'retrieved_at_utc': None, 'error': 'Redirect left official host allowlist'}
            data = response.read(1_000_001)
            if len(data) > 1_000_000:
                return {'status': 'oversize', 'http_status': status, 'sha256': None,
                        'title': None, 'retrieved_at_utc': None, 'error': 'Document exceeds 1MB audit limit'}
            ctype = response.headers.get('Content-Type', '')
            parser = TitleParser()
            if 'html' in ctype.lower():
                parser.feed(data.decode('utf-8', errors='replace'))
            return {'status': 'retrieved' if status == 200 else 'http_error',
                    'http_status': status, 'final_url': final_url, 'content_type': ctype,
                    'size_bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
                    'title': ' '.join(''.join(parser.title).split())[:240] or None,
                    'retrieved_at_utc': dt.datetime.now(dt.timezone.utc).isoformat(), 'error': None}
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        return {'status': 'fetch_error', 'http_status': getattr(exc, 'code', None),
                'sha256': None, 'title': None, 'retrieved_at_utc': None,
                'error': str(exc)[:300]}

def audit(source, fetcher=fetch_document):
    if (not source.get('input_valid') or not str(source.get('model_version','')).startswith('eur-rc7.4-')
            or source.get('eligible_count') != 0 or source.get('verified_point_in_time_events') != 0
            or any(e.get('point_in_time_usable') or e.get('available_asof_utc') is not None
                   for e in source.get('publication_events', []))):
        raise ValueError('RC7.4 input not in expected safe state')
    docs = []
    for factor, label, url in document_specs(source):
        result = fetcher(url)
        docs.append({'factor': factor, 'label': label, 'source_url': url, **result,
                     'publication_timestamp_verified': False,
                     'first_release_value_verified': False,
                     'point_in_time_usable': False,
                     'verification_note': 'Retrieval and content hash do not establish original publication time or dataset vintage.'})
    events = []
    for e in source['publication_events']:
        copy = dict(e)
        copy.update({'release_timestamp_utc': None, 'release_timestamp_verified': False,
                     'first_release_value': None, 'first_release_value_verified': False,
                     'available_asof_utc': None, 'point_in_time_usable': False})
        events.append(copy)
    by_factor = {f: {'documents_attempted': sum(d['factor']==f for d in docs),
                     'documents_retrieved': sum(d['factor']==f and d['status']=='retrieved' for d in docs),
                     'point_in_time_usable_events': 0, 'eligible': False} for f in FACTORS}
    return {'model_version': VERSION, 'asof_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
            'asset': 'EUR/USD', 'module': 'official_document_retrieval_audit',
            'input_model_version': source['model_version'], 'input_valid': True,
            'source_document_audit': docs, 'factor_audit': by_factor,
            'documents_attempted': len(docs),
            'documents_retrieved': sum(d['status']=='retrieved' for d in docs),
            'publication_events': events, 'verified_point_in_time_events': 0,
            'historical_first_release_vintages_verified': False,
            'historical_release_timestamps_verified': False,
            'point_in_time_integrity_verified': False,
            'eligibility': {f: False for f in FACTORS}, 'eligible_count': 0, 'coverage': 0.0,
            'relative_score': None, 'horizons': {'1d': {'score': None}, '5d': {'score': None}},
            'point_in_time_backtest_authorized': False, 'signals_generated': False,
            'database_writes': False, 'production_change_authorized': False,
            'source_code_modified': False,
            'next_step': 'Review retrieved official documents individually; verify event-specific publication timestamps and original first-release values.',
            'limitations': [
                'Successful HTTP retrieval and SHA-256 establish a fetched document, not an authenticated first-release vintage.',
                'Generic release calendars are not event-specific publication evidence.',
                'No timestamps or original values are inferred from URLs, HTTP headers, or reference dates.',
                'No scores, signals, backtests, or database writes.'
            ]}

def self_test():
    source = {'model_version':'eur-rc7.4-test','input_valid':True,'eligible_count':0,
              'verified_point_in_time_events':0,
              'publication_events':[{'factor':'inflation','label':'flash','reference_period':'2026-09',
                  'source_url':'https://ec.europa.eu/eurostat/example','point_in_time_usable':False,
                  'available_asof_utc':None}]}
    def fake(url):
        return {'status':'retrieved','http_status':200,'sha256':'0'*64,'title':'mock',
                'retrieved_at_utc':'2026-11-18T00:00:00+00:00','error':None}
    r = audit(source, fake)
    assert r['documents_retrieved'] == r['documents_attempted'] == 8
    assert r['verified_point_in_time_events'] == r['eligible_count'] == 0
    assert all(not e['point_in_time_usable'] and e['available_asof_utc'] is None for e in r['publication_events'])
    assert not r['point_in_time_backtest_authorized'] and r['relative_score'] is None
    assert fetch_document('https://example.com')['status']=='rejected_untrusted_host'
    print('RC75_SELF_TEST_OK')

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--input', default='eur_rc74_result.json')
    ap.add_argument('--output', default='eur_rc75_result.json')
    ap.add_argument('--self-test', action='store_true')
    args = ap.parse_args()
    if args.self_test: self_test(); return
    source = json.loads(Path(args.input).read_text(encoding='utf-8'))
    result = audit(source)
    Path(args.output).write_text(json.dumps(result, indent=2, ensure_ascii=False)+'\n', encoding='utf-8')
    print(f"RC7.5: retrieved {result['documents_retrieved']}/{result['documents_attempted']} official documents; verified PIT events: 0")

if __name__ == '__main__': main()
