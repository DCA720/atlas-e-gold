#!/usr/bin/env python3
"""Atlas EUR RC8.2: preserve retrieved official HTML and normalized text.
No scores, no backtests, no historical first-publication claims.
"""
import argparse
import datetime as dt
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import urllib.parse
import urllib.request

VERSION = 'eur-rc8.2-versioned-document-capture-0.8.2'
ALLOWED = {'ec.europa.eu', 'www.ecb.europa.eu', 'www.federalreserve.gov', 'www.bls.gov'}
FACTORS = ('inflation', 'rates', 'unemployment', 'activity')
MAX_BYTES = 8 * 1024 * 1024

class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.suppressed = 0
    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'noscript', 'svg'):
            self.suppressed += 1
    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'noscript', 'svg') and self.suppressed:
            self.suppressed -= 1
    def handle_data(self, data):
        if not self.suppressed:
            self.parts.append(data)

def normalized_text(raw):
    parser = TextExtractor()
    parser.feed(raw.decode('utf-8', errors='replace'))
    return re.sub(r'\s+', ' ', ' '.join(parser.parts)).strip()

def digest(raw):
    return hashlib.sha256(raw).hexdigest()

def safe_url(url):
    parsed = urllib.parse.urlsplit(url)
    return parsed.scheme == 'https' and parsed.hostname in ALLOWED and not parsed.username and not parsed.password

def fetch(url):
    if not safe_url(url):
        raise ValueError('Source URL outside official HTTPS allowlist')
    req = urllib.request.Request(url, headers={'User-Agent': 'AtlasEUR-Research-Audit/0.8.2', 'Accept': 'text/html'})
    # Redirects are verified again after resolution.
    with urllib.request.urlopen(req, timeout=25) as response:
        final_url = response.geturl()
        if not safe_url(final_url):
            raise ValueError('Redirect outside official HTTPS allowlist')
        content_type = response.headers.get('Content-Type', '')
        if 'text/html' not in content_type.lower():
            raise ValueError('Unexpected content type: ' + content_type)
        raw = response.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError('HTML exceeds 8 MiB limit')
        return raw, final_url, content_type

def audit(rc81, archive_dir, baseline=None, fetcher=fetch):
    valid = (rc81.get('model_version', '').startswith('eur-rc8.1-') and rc81.get('input_valid') is True
             and rc81.get('documents_compared') == 7 and rc81.get('eligible_count') == 0
             and rc81.get('relative_score') is None and rc81.get('verified_point_in_time_events') == 0)
    docs = rc81.get('document_integrity', [])
    ids = [d.get('event_id') for d in docs]
    valid = bool(valid and len(docs) == 7 and len(set(ids)) == 7
                 and all(d.get('point_in_time_usable') is False and safe_url(d.get('source_url', '')) for d in docs))
    archive_dir = Path(archive_dir)
    archive_dir.mkdir(parents=True, exist_ok=True)
    previous = {}
    if baseline is not None:
        base = json.loads(Path(baseline).read_text(encoding='utf-8'))
        if base.get('model_version', '').startswith('eur-rc8.2-'):
            previous = {x['event_id']: x for x in base.get('documents', []) if x.get('status') == 'retrieved'}
    report = {'model_version': VERSION, 'asof_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
              'asset': 'EUR/USD', 'module': 'versioned_document_capture', 'input_valid': valid,
              'documents_attempted': 7 if valid else 0, 'documents': [],
              'baseline_provided': baseline is not None, 'baseline_comparable': bool(previous),
              'comparison_scope': 'cross_run_only_if_baseline_manifest_provided',
              'notes': ['HTML and canonical text are preserved as retrieval-time evidence only.',
                        'A baseline manifest alone compares hashes; raw baseline files are needed to explain changed text.',
                        'Canonical text strips scripts/styles and collapses whitespace, but can retain dynamic navigation.',
                        'No retrieved page establishes the historical first-available timestamp.']}
    if valid:
        for d in sorted(docs, key=lambda x: x['event_id']):
            event_id = d['event_id']
            stem = re.sub(r'[^A-Za-z0-9_-]', '_', event_id)
            entry = {'event_id': event_id, 'factor': d.get('factor'), 'source_url': d['source_url'],
                     'status': 'failed', 'point_in_time_usable': False,
                     'release_timestamp_verified': False, 'first_release_vintage_verified': False}
            try:
                raw, final_url, content_type = fetcher(d['source_url'])
                canonical = normalized_text(raw).encode('utf-8')
                html_file = archive_dir / (stem + '.html')
                text_file = archive_dir / (stem + '.txt')
                html_file.write_bytes(raw)
                text_file.write_bytes(canonical)
                entry.update(status='retrieved', final_url=final_url, content_type=content_type,
                             retrieved_at_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
                             html_path=html_file.name, text_path=text_file.name,
                             html_bytes=len(raw), canonical_text_bytes=len(canonical),
                             html_sha256=digest(raw), canonical_text_sha256=digest(canonical))
                prior = previous.get(event_id)
                if prior:
                    entry['baseline_comparison'] = {
                        'baseline_html_sha256': prior.get('html_sha256'),
                        'baseline_text_sha256': prior.get('canonical_text_sha256'),
                        'html_hash_equal': prior.get('html_sha256') == entry['html_sha256'],
                        'canonical_text_hash_equal': prior.get('canonical_text_sha256') == entry['canonical_text_sha256'],
                        'economic_revision_proven': False}
                else:
                    entry['baseline_comparison'] = None
            except Exception as exc:
                entry['error'] = str(exc)[:300]
            report['documents'].append(entry)
    report['documents_retrieved'] = sum(d['status'] == 'retrieved' for d in report['documents'])
    report['baseline_comparisons'] = sum(d.get('baseline_comparison') is not None for d in report['documents'])
    report['verified_point_in_time_events'] = 0
    report['historical_first_release_vintages_verified'] = False
    report['historical_release_timestamps_verified'] = False
    report['point_in_time_integrity_verified'] = False
    report['eligibility'] = {f: False for f in FACTORS}
    report['eligible_count'] = 0
    report['coverage'] = 0.0
    report['relative_score'] = None
    report['horizons'] = {'1d': {'score': None}, '5d': {'score': None}}
    report['point_in_time_backtest_authorized'] = False
    report['signals_generated'] = False
    report['database_writes'] = False
    report['production_change_authorized'] = False
    report['source_code_modified'] = False
    report['next_step'] = 'Compare separately archived runs and corroborate original dissemination timestamps and dataset vintages.'
    return report

def self_test():
    from tempfile import TemporaryDirectory
    def fake(url):
        return b'<html><script>random</script><body>Rate <b>4.6%</b>  </body></html>', url, 'text/html'
    docs = [{'event_id': 'EV'+str(i), 'factor': 'rates', 'source_url': 'https://www.bls.gov/news.release/test'} for i in range(7)]
    inp = {'model_version': 'eur-rc8.1-test', 'input_valid': True, 'documents_compared': 7,
           'eligible_count': 0, 'relative_score': None, 'verified_point_in_time_events': 0,
           'document_integrity': [{**d, 'point_in_time_usable': False} for d in docs]}
    with TemporaryDirectory() as folder:
        a = audit(inp, Path(folder) / 'a', fetcher=fake)
        assert a['documents_retrieved'] == 7 and a['eligible_count'] == 0
        assert b'random' not in (Path(folder) / 'a' / 'EV0.txt').read_bytes()
        path = Path(folder) / 'baseline.json'
        path.write_text(json.dumps(a), encoding='utf-8')
        b = audit(inp, Path(folder) / 'b', baseline=path, fetcher=fake)
        assert b['baseline_comparisons'] == 7
        assert all(x['baseline_comparison']['canonical_text_hash_equal'] for x in b['documents'])
        assert not b['point_in_time_backtest_authorized']
        assert not audit({}, Path(folder) / 'invalid', fetcher=fake)['input_valid']
    print('RC82_SELF_TEST_OK')

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--input', default='eur_rc81_result.json')
    p.add_argument('--output', default='eur_rc82_result.json')
    p.add_argument('--archive-dir', default='eur_rc82_archive')
    p.add_argument('--baseline', default=None, help='Optional prior RC8.2 manifest; no auto-assumed history')
    p.add_argument('--self-test', action='store_true')
    args = p.parse_args()
    if args.self_test:
        self_test()
        return
    result = audit(json.loads(Path(args.input).read_text(encoding='utf-8')), args.archive_dir, args.baseline)
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('RC82_OK', result['input_valid'], result['documents_retrieved'], '/', result['documents_attempted'])
    if not result['input_valid']:
        raise SystemExit(2)

if __name__ == '__main__':
    main()
