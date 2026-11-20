#!/usr/bin/env python3
"""Atlas EUR RC8.3: cross-run archived HTML/text comparison, research only."""
import argparse
import difflib
import hashlib
import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory

VERSION = 'eur-rc8.3-cross-run-economic-content-diff-0.8.3'
FACTORS = ('inflation', 'rates', 'unemployment', 'activity')
NUMBER = re.compile(r'(?<![\w])[-+]?\d+(?:[.,]\d+)?\s*(?:%|percent|basis points|bps)?', re.I)

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def safe_read(folder, name, expected):
    if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_-]+\.(?:html|txt)', name):
        raise ValueError('unsafe_archive_filename')
    path = Path(folder) / name
    raw = path.read_bytes()
    if sha(raw) != expected:
        raise ValueError('archive_hash_mismatch')
    return raw

def compare(previous, current, previous_dir, current_dir):
    valid = (previous.get('model_version', '').startswith('eur-rc8.2-') and
             current.get('model_version', '').startswith('eur-rc8.2-') and
             previous.get('input_valid') is True and current.get('input_valid') is True and
             previous.get('eligible_count') == current.get('eligible_count') == 0 and
             previous.get('relative_score') is None and current.get('relative_score') is None and
             previous.get('verified_point_in_time_events') == current.get('verified_point_in_time_events') == 0)
    old = {x['event_id']: x for x in previous.get('documents', []) if x.get('status') == 'retrieved'}
    new = {x['event_id']: x for x in current.get('documents', []) if x.get('status') == 'retrieved'}
    result = {'model_version': VERSION, 'asset': 'EUR/USD', 'module': 'cross_run_economic_content_diff',
              'input_valid': bool(valid), 'baseline_available': bool(old), 'comparisons': [],
              'notes': ['Both archives must be independent, preserved runs; manifest hashes alone cannot explain content.',
                        'Numeric text changes are candidates for review, not confirmed economic revisions.',
                        'Retrieval timestamps are not historical first-publication timestamps.']}
    if valid:
        for event in sorted(set(old) | set(new)):
            a, b = old.get(event), new.get(event)
            item = {'event_id': event, 'factor': (b or a).get('factor'), 'status': 'not_comparable',
                    'economic_revision_proven': False, 'original_release_verified': False,
                    'actual_release_timestamp_verified': False, 'point_in_time_usable': False}
            if not a or not b:
                item['reason'] = 'missing_document_in_one_run'
            elif a.get('source_url') != b.get('source_url'):
                item['reason'] = 'source_url_mismatch'
            else:
                try:
                    old_html = safe_read(previous_dir, a['html_path'], a['html_sha256'])
                    new_html = safe_read(current_dir, b['html_path'], b['html_sha256'])
                    old_text = safe_read(previous_dir, a['text_path'], a['canonical_text_sha256']).decode('utf-8')
                    new_text = safe_read(current_dir, b['text_path'], b['canonical_text_sha256']).decode('utf-8')
                    html_equal = old_html == new_html
                    text_equal = old_text == new_text
                    item.update(status='compared', html_equal=html_equal, canonical_text_equal=text_equal,
                                classification=('unchanged_bytes' if html_equal else 'html_only_change' if text_equal else 'canonical_text_change'),
                                baseline_retrieved_at_utc=a.get('retrieved_at_utc'), current_retrieved_at_utc=b.get('retrieved_at_utc'))
                    if not text_equal:
                        # Short context-only snippets, never assert a revised macro release.
                        changes = []
                        sm = difflib.SequenceMatcher(None, old_text.split(), new_text.split(), autojunk=False)
                        for op, i, j, k, l in sm.get_opcodes():
                            if op == 'equal':
                                continue
                            before = ' '.join(old_text.split()[i:j])
                            after = ' '.join(new_text.split()[k:l])
                            changes.append({'type': op, 'before_excerpt': before[:180], 'after_excerpt': after[:180],
                                            'numeric_candidate': bool(NUMBER.search(before) or NUMBER.search(after))})
                            if len(changes) >= 20:
                                break
                        item['diff_excerpts'] = changes
                        item['numeric_change_candidate'] = any(x['numeric_candidate'] for x in changes)
                        item['diff_truncated'] = len(changes) >= 20
                    else:
                        item['numeric_change_candidate'] = False
                except (OSError, KeyError, ValueError, UnicodeError) as exc:
                    item['reason'] = 'archive_integrity_or_access_error'
                    item['error'] = str(exc)[:160]
            result['comparisons'].append(item)
    result['documents_compared'] = sum(x['status'] == 'compared' for x in result['comparisons'])
    result['html_changes'] = sum(x.get('html_equal') is False for x in result['comparisons'])
    result['canonical_text_changes'] = sum(x.get('canonical_text_equal') is False for x in result['comparisons'])
    result['numeric_review_candidates'] = sum(x.get('numeric_change_candidate') is True for x in result['comparisons'])
    result.update(verified_point_in_time_events=0, historical_first_release_vintages_verified=False,
                  historical_release_timestamps_verified=False, point_in_time_integrity_verified=False,
                  eligibility={f: False for f in FACTORS}, eligible_count=0, coverage=0.0,
                  relative_score=None, horizons={'1d': {'score': None}, '5d': {'score': None}},
                  point_in_time_backtest_authorized=False, signals_generated=False, database_writes=False,
                  production_change_authorized=False, source_code_modified=False,
                  next_step='Review independent archived text diffs and obtain original release timestamp/vintage evidence.')
    return result

def self_test():
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        for sub, content in [('old', b'<p>Rate 4.6%</p>'), ('new', b'<p>Rate 4.7%</p>')]:
            p = root / sub
            p.mkdir()
            (p / 'EV.html').write_bytes(content)
            (p / 'EV.txt').write_bytes(content)
        def manifest(sub):
            p = root / sub
            return {'model_version': 'eur-rc8.2-test', 'input_valid': True, 'eligible_count': 0,
                    'relative_score': None, 'verified_point_in_time_events': 0,
                    'documents': [{'event_id': 'EV', 'factor': 'rates', 'status': 'retrieved',
                                   'source_url': 'https://example.org/ev', 'html_path': 'EV.html',
                                   'text_path': 'EV.txt', 'html_sha256': sha((p / 'EV.html').read_bytes()),
                                   'canonical_text_sha256': sha((p / 'EV.txt').read_bytes())}]}
        a, b = manifest('old'), manifest('new')
        r = compare(a, b, root / 'old', root / 'new')
        assert r['input_valid'] and r['documents_compared'] == 1 and r['numeric_review_candidates'] == 1
        assert r['eligible_count'] == 0 and not r['comparisons'][0]['economic_revision_proven']
        (root / 'new' / 'EV.txt').write_text('tampered')
        assert compare(a, b, root / 'old', root / 'new')['documents_compared'] == 0
    print('RC83_SELF_TEST_OK')

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--baseline', required=False)
    p.add_argument('--baseline-dir', default='eur_rc82_baseline_archive')
    p.add_argument('--current', default='eur_rc82_result.json')
    p.add_argument('--current-dir', default='eur_rc82_archive')
    p.add_argument('--output', default='eur_rc83_result.json')
    p.add_argument('--self-test', action='store_true')
    args = p.parse_args()
    if args.self_test:
        self_test()
        return
    current = json.loads(Path(args.current).read_text(encoding='utf-8'))
    if args.baseline and Path(args.baseline).is_file():
        baseline = json.loads(Path(args.baseline).read_text(encoding='utf-8'))
    else:
        baseline = {'model_version': 'eur-rc8.2-missing', 'input_valid': True, 'eligible_count': 0,
                    'relative_score': None, 'verified_point_in_time_events': 0, 'documents': []}
    result = compare(baseline, current, args.baseline_dir, args.current_dir)
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('RC83_OK', result['input_valid'], 'compared', result['documents_compared'], 'text_changes', result['canonical_text_changes'])
    if not result['input_valid']:
        raise SystemExit(2)

if __name__ == '__main__':
    main()
