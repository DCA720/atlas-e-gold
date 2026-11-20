#!/usr/bin/env python3
"""Atlas EUR RC8.1: offline documentary integrity and temporal-evidence audit.
Reads RC7.9 and RC8.0 JSON only. Never authenticates PIT from hashes or date-only snapshots.
"""
import argparse
import datetime as dt
import json
import re
from pathlib import Path

VERSION = 'eur-rc8.1-document-integrity-and-release-provenance-0.8.1'
FACTORS = ('inflation', 'rates', 'unemployment', 'activity')
HEX64 = re.compile(r'^[0-9a-f]{64}$')


def audit(rc79, rc80):
    safe79 = (rc79.get('model_version', '').startswith('eur-rc7.9-')
              and rc79.get('input_valid') is True and rc79.get('documents_attempted') == 7
              and rc79.get('eligible_count') == 0 and rc79.get('relative_score') is None)
    safe80 = (rc80.get('model_version', '').startswith('eur-rc8.0-')
              and rc80.get('input_valid') is True and rc80.get('documents_checked') == 7
              and rc80.get('eligible_count') == 0 and rc80.get('relative_score') is None)
    d79 = {d.get('event_id'): d for d in rc79.get('documents', []) if d.get('event_id')}
    d80 = {d.get('event_id'): d for d in rc80.get('document_cross_checks', []) if d.get('event_id')}
    valid = safe79 and safe80 and len(d79) == len(d80) == 7 and set(d79) == set(d80)
    result = {
        'model_version': VERSION, 'asof_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
        'asset': 'EUR/USD', 'module': 'document_integrity_and_release_provenance',
        'input_versions': [rc79.get('model_version'), rc80.get('model_version')],
        'input_valid': valid, 'document_integrity': [], 'snapshot_provenance': [],
        'evidence_gaps': [], 'methodological_findings': [],
    }
    if valid:
        for eid in sorted(d79):
            a, b = d79[eid], d80[eid]
            ha, hb = a.get('sha256'), b.get('retrieved_sha256')
            both_valid = bool(HEX64.fullmatch(str(ha))) and bool(HEX64.fullmatch(str(hb)))
            url_match = a.get('source_url') == b.get('official_source_url')
            hash_match = both_valid and ha == hb
            if not both_valid:
                classification = 'hash_unavailable_or_invalid'
            elif not url_match:
                classification = 'source_url_mismatch'
            elif hash_match:
                classification = 'byte_identical_across_reports'
            else:
                classification = 'bytes_differ_cause_unresolved'
            result['document_integrity'].append({
                'event_id': eid, 'factor': a.get('factor'), 'source_url': a.get('source_url'),
                'source_url_matches': url_match, 'rc79_sha256': ha, 'rc80_sha256': hb,
                'hashes_well_formed': both_valid, 'hash_equal': hash_match,
                'classification': classification,
                'content_change_proven': False,
                'economic_data_revision_proven': False,
                'explanation': ('Byte-level equality is not proof of historical publication or original vintage.'
                                if hash_match else 'Different HTML bytes can reflect dynamic layout, scripts, tracking or content changes; raw bytes and normalized text are required to attribute cause.'),
                'source_identity_independently_verified': False,
                'release_timestamp_verified': False, 'first_release_vintage_verified': False,
                'point_in_time_usable': False,
            })
        for s in rc80.get('historical_snapshots', []):
            is_ok = s.get('status') == 'ok'
            result['snapshot_provenance'].append({
                'event_id': s.get('event_id'), 'series_id': s.get('series_id'),
                'observation_date': s.get('observation_date'), 'asof_date': s.get('asof_date'),
                'status': s.get('status'), 'value': s.get('value'),
                'numeric_match_candidate': s.get('numeric_match_candidate'),
                'date_granularity_only': True,
                'concept_equivalence_verified': False,
                'original_release_value_verified': False,
                'intraday_first_available_verified': False,
                'point_in_time_usable': False,
                'issue': ('Date-only ALFRED snapshot cannot establish original publication instant.'
                          if is_ok else 'Snapshot unavailable; no inference or interpolation permitted.'),
            })
        result['evidence_gaps'] = [
            {'factor': 'all', 'gap': 'Event-specific independently corroborated first dissemination timestamp in UTC'},
            {'factor': 'all', 'gap': 'Original release dataset vintage, with timestamped archival provenance'},
            {'factor': 'all', 'gap': 'Raw prior/current HTML bytes or canonical text snapshots for attributing hash changes'},
            {'factor': 'inflation', 'gap': 'Eurostat first-release historical dataset vintages, flash/full separation and EA composition'},
            {'factor': 'rates', 'gap': 'Decision announcement versus effective-date mapping and comparable rate definitions'},
            {'factor': 'unemployment', 'gap': 'US/EU survey universe, seasonal adjustments and first-release comparison'},
            {'factor': 'activity', 'gap': 'EU/US equivalent monthly percentage transformations and first-release vintages'},
        ]
        result['methodological_findings'] = [
            'A SHA-256 mismatch establishes different retrieved bytes, not an economic revision.',
            'A SHA-256 match establishes matching retrieved bytes, not historical authenticity.',
            'FRED/ALFRED real-time dates have day precision, not verified intraday dissemination times.',
            'An embargo or scheduled release time is not independently verified actual arrival time.',
            'INDPRO index level is not equivalent to Eurostat industrial production month-on-month percentage.',
        ]
    result['documents_compared'] = len(result['document_integrity'])
    result['hash_matches'] = sum(x['hash_equal'] for x in result['document_integrity'])
    result['hash_mismatches'] = sum(x['classification'] == 'bytes_differ_cause_unresolved' for x in result['document_integrity'])
    result['snapshots_reviewed'] = len(result['snapshot_provenance'])
    result['verified_point_in_time_events'] = 0
    result['historical_first_release_vintages_verified'] = False
    result['historical_release_timestamps_verified'] = False
    result['point_in_time_integrity_verified'] = False
    result['eligibility'] = {factor: False for factor in FACTORS}
    result['eligible_count'] = 0
    result['coverage'] = 0.0
    result['relative_score'] = None
    result['horizons'] = {'1d': {'score': None}, '5d': {'score': None}}
    result['point_in_time_backtest_authorized'] = False
    result['signals_generated'] = False
    result['database_writes'] = False
    result['production_change_authorized'] = False
    result['source_code_modified'] = False
    result['next_step'] = 'Capture raw versioned documents and obtain independently timestamped original release data before any PIT eligibility.'
    return result


def self_test():
    docs = [{'event_id': f'E{i}', 'factor': 'inflation', 'source_url': f'https://example.org/{i}', 'sha256': 'a'*64} for i in range(7)]
    cross = [{'event_id': f'E{i}', 'official_source_url': f'https://example.org/{i}', 'retrieved_sha256': ('a' if i == 0 else 'b')*64} for i in range(7)]
    r79 = {'model_version': 'eur-rc7.9-test', 'input_valid': True, 'documents_attempted': 7, 'eligible_count': 0, 'relative_score': None, 'documents': docs}
    r80 = {'model_version': 'eur-rc8.0-test', 'input_valid': True, 'documents_checked': 7, 'eligible_count': 0, 'relative_score': None, 'document_cross_checks': cross, 'historical_snapshots': [{'status':'ok', 'series_id':'UNRATE'}]}
    o = audit(r79, r80)
    assert o['input_valid'] and o['documents_compared'] == 7
    assert o['hash_matches'] == 1 and o['hash_mismatches'] == 6
    assert o['snapshots_reviewed'] == 1 and o['verified_point_in_time_events'] == 0
    assert not o['historical_first_release_vintages_verified'] and o['relative_score'] is None
    assert not any(o[k] for k in ('signals_generated', 'database_writes', 'production_change_authorized', 'point_in_time_backtest_authorized'))
    assert not audit({}, r80)['input_valid']
    print('RC81_SELF_TEST_OK')


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--rc79', default='eur_rc79_result.json')
    p.add_argument('--rc80', default='eur_rc80_result.json')
    p.add_argument('--output', default='eur_rc81_result.json')
    p.add_argument('--self-test', action='store_true')
    args = p.parse_args()
    if args.self_test:
        self_test()
        return
    r79 = json.loads(Path(args.rc79).read_text(encoding='utf-8'))
    r80 = json.loads(Path(args.rc80).read_text(encoding='utf-8'))
    out = audit(r79, r80)
    Path(args.output).write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('RC81_OK', out['input_valid'], 'docs', out['documents_compared'], 'matches', out['hash_matches'], 'mismatches', out['hash_mismatches'], 'PIT', out['verified_point_in_time_events'])
    if not out['input_valid']:
        raise SystemExit(2)


if __name__ == '__main__':
    main()
