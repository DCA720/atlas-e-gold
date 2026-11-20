#!/usr/bin/env python3
"""Atlas EUR RC8.0 — read-only cross-source evidence and ALFRED historical snapshots.
No eligibility, score, trading, backtest, DB, or production writes.
"""
import argparse
import datetime as dt
import json
import os
import re
import urllib.parse
import urllib.request
from pathlib import Path

VERSION = 'eur-rc8.0-historical-cross-audit-0.8.0'
FRED_API = 'https://api.stlouisfed.org/fred/series/observations'
# ALFRED real-time date is NOT an intraday dissemination timestamp.
SERIES = [
    ('US_UNRATE_2025-11_BLS', 'UNRATE', '2025-11-01', '2025-12-16', '4.6', 'unemployment'),
    ('US_FOMC_2026-09-16', 'DFEDTARL', '2026-09-17', '2026-09-18', '3.75', 'rates'),
    ('US_FOMC_2026-09-16', 'DFEDTARU', '2026-09-17', '2026-09-18', '4.00', 'rates'),
    ('EU_ECB_2026-09-10', 'ECBDFR', '2026-09-16', '2026-09-17', '2.50', 'rates'),
    ('EU_INDUSTRY_2026-09', 'INDPRO', '2026-09-01', '2026-11-18', None, 'activity'),
]
HEADLINE = {
    'EU_HICP_2026-09_FLASH': ('inflation', r'3[.,]8\s*%'),
    'EU_HICP_2026-09_FULL': ('inflation', r'3[.,]8\s*%'),
    'EU_HICP_2026-10_FLASH': ('inflation', r'4[.,]0\s*%'),
    'US_UNRATE_2025-11_BLS': ('unemployment', r'4[.,]6\s*percent'),
    'US_FOMC_2026-09-16': ('rates', r'3-3/4\s+to\s+4\s+percent'),
    'EU_ECB_2026-09-10': ('rates', r'2[.,]50\s*%'),
    'EU_INDUSTRY_2026-09': ('activity', r'0[.,]2\s*%'),
}

def fred_query(series, observation_date, asof, api_key, requester=None):
    if not api_key:
        return {'status': 'missing_api_key', 'series_id': series, 'observation_date': observation_date, 'asof_date': asof}
    params = {'series_id': series, 'api_key': api_key, 'file_type': 'json',
              'observation_start': observation_date, 'observation_end': observation_date,
              'realtime_start': asof, 'realtime_end': asof}
    url = FRED_API + '?' + urllib.parse.urlencode(params)
    if requester is None:
        def requester(u):
            req = urllib.request.Request(u, headers={'User-Agent': 'AtlasEUR-RC80-Audit/0.8.0'})
            with urllib.request.urlopen(req, timeout=25) as resp:
                if urllib.parse.urlparse(resp.geturl()).hostname != 'api.stlouisfed.org':
                    raise ValueError('untrusted_redirect')
                raw = resp.read(1_000_001)
                if len(raw) > 1_000_000:
                    raise ValueError('response_too_large')
                return json.loads(raw)
    try:
        data = requester(url)
        obs = data.get('observations', [])
        matching = [o for o in obs if o.get('date') == observation_date]
        row = matching[0] if matching else None
        val = row.get('value') if row else None
        return {'status': 'ok' if row and val not in (None, '.') else 'missing_observation',
                'series_id': series, 'observation_date': observation_date, 'asof_date': asof,
                'value': val if val != '.' else None,
                'realtime_start': row.get('realtime_start') if row else None,
                'realtime_end': row.get('realtime_end') if row else None,
                'query_contract': 'date_only_realtime_snapshot_not_original_release_proof'}
    except Exception as exc:
        return {'status': 'fetch_error', 'series_id': series, 'observation_date': observation_date,
                'asof_date': asof, 'error': str(exc)[:180]}

def audit(source, api_key='', requester=None):
    valid = (source.get('model_version', '').startswith('eur-rc7.9-')
             and source.get('input_valid') is True and source.get('documents_attempted') == 7
             and source.get('eligible_count') == 0 and source.get('relative_score') is None)
    out = {'model_version': VERSION, 'asof_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
           'asset': 'EUR/USD', 'module': 'historical_cross_audit',
           'input_model_version': source.get('model_version'), 'input_valid': valid,
           'document_cross_checks': [], 'historical_snapshots': [], 'cross_source_findings': []}
    if valid:
        for doc in source.get('documents', []):
            eid = doc.get('event_id', '')
            factor, pattern = HEADLINE.get(eid, ('unknown', r'(?!)'))
            excerpts = [e.get('excerpt', '') for e in doc.get('evidence', [])]
            hits = [e for e in excerpts if re.search(pattern, e, re.I)]
            out['document_cross_checks'].append({
                'event_id': eid, 'factor': factor, 'document_status': doc.get('status'),
                'official_source_url': doc.get('source_url'), 'retrieved_sha256': doc.get('sha256'),
                'matching_excerpt_count': len(hits), 'headline_text_candidate_present': bool(hits),
                'source_identity_independently_verified': False,
                'original_dataset_vintage_verified': False,
                'actual_release_timestamp_verified': False,
                'point_in_time_usable': False})
        for eid, series, observation_date, asof, expected, factor in SERIES:
            snap = fred_query(series, observation_date, asof, api_key, requester)
            snap.update({'event_id': eid, 'factor': factor,
                         'expected_release_text_value': expected,
                         'same_unit_and_concept_confirmed': False,
                         'first_release_vintage_verified': False,
                         'intraday_publication_verified': False,
                         'point_in_time_usable': False})
            if snap.get('status') == 'ok' and expected is not None:
                try:
                    snap['numeric_match_candidate'] = abs(float(snap['value']) - float(expected)) < 0.0001
                except (ValueError, TypeError):
                    snap['numeric_match_candidate'] = False
            else:
                snap['numeric_match_candidate'] = None
            out['historical_snapshots'].append(snap)
    out['cross_source_findings'] = [
        {'source': 'FRED_ALFRED', 'finding': 'Historical realtime_start/end are date-granularity snapshots; not proof of intraday first dissemination.', 'status': 'methodological_limit'},
        {'source': 'EUROSTAT_API', 'finding': 'Public API presents current dataset; original full historical vintages require separate archived evidence.', 'status': 'historical_vintage_not_available_from_current_api'},
        {'source': 'OFFICIAL_PRESS_RELEASES', 'finding': 'Press release headline and scheduled time do not independently verify original full-series vintage or actual arrival time.', 'status': 'partial_evidence_only'},
        {'source': 'INDPRO', 'finding': 'US industrial production index cannot be directly compared to EU month-over-month press release percentage.', 'status': 'not_equivalent_measure'},
    ]
    out['documents_checked'] = len(out['document_cross_checks'])
    out['historical_queries_attempted'] = len(out['historical_snapshots'])
    out['historical_snapshots_returned'] = sum(s['status'] == 'ok' for s in out['historical_snapshots'])
    out['verified_point_in_time_events'] = 0
    out['historical_first_release_vintages_verified'] = False
    out['historical_release_timestamps_verified'] = False
    out['point_in_time_integrity_verified'] = False
    out['eligibility'] = {f: False for f in ('inflation', 'rates', 'unemployment', 'activity')}
    out['eligible_count'] = 0
    out['coverage'] = 0.0
    out['relative_score'] = None
    out['horizons'] = {'1d': {'score': None}, '5d': {'score': None}}
    out['point_in_time_backtest_authorized'] = False
    out['signals_generated'] = False
    out['database_writes'] = False
    out['production_change_authorized'] = False
    out['source_code_modified'] = False
    out['next_step'] = 'Acquire archived dataset vintages and independent event-specific publication timestamps; reconcile units and first-release timing.'
    return out

def self_test():
    mock = {'model_version': 'eur-rc7.9-targeted-historical-release-retrieval-0.7.9',
            'input_valid': True, 'documents_attempted': 7, 'eligible_count': 0, 'relative_score': None,
            'documents': [{'event_id': 'US_UNRATE_2025-11_BLS', 'status': 'retrieved',
                           'evidence': [{'excerpt': 'In November, the unemployment rate, at 4.6 percent'}]}]}
    def fake_request(_):
        return {'observations': [{'date': '2025-11-01', 'value': '4.6',
                                  'realtime_start': '2025-12-16', 'realtime_end': '2025-12-16'}]}
    result = audit(mock, 'x'*32, fake_request)
    assert result['input_valid'] and result['documents_checked'] == 1
    assert result['historical_queries_attempted'] == 5
    assert result['historical_snapshots'][0]['numeric_match_candidate'] is True
    assert result['historical_snapshots'][0]['first_release_vintage_verified'] is False
    assert result['eligible_count'] == 0 and result['relative_score'] is None
    assert result['verified_point_in_time_events'] == 0
    assert all(not v for v in result['eligibility'].values())
    assert not any(result[k] for k in ('signals_generated', 'database_writes', 'production_change_authorized', 'point_in_time_backtest_authorized'))
    assert audit({}, 'x'*32, fake_request)['historical_queries_attempted'] == 0
    print('RC80_SELF_TEST_OK')

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', default='eur_rc79_result.json')
    parser.add_argument('--output', default='eur_rc80_result.json')
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    inp = json.loads(Path(args.input).read_text(encoding='utf-8'))
    result = audit(inp, os.environ.get('FRED_API_KEY', ''))
    Path(args.output).write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print('RC80', 'documents', result['documents_checked'], 'ALFRED snapshots', result['historical_snapshots_returned'], '/', result['historical_queries_attempted'], 'PIT', result['verified_point_in_time_events'])

if __name__ == '__main__':
    main()
