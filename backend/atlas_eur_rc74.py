#!/usr/bin/env python3
"""Atlas EUR RC7.4: auditoria temporal conservadora, somente leitura.

Consome o JSON integrado do RC7.3. Nao inventa timestamps nem vintages.
"""
import argparse
import datetime as dt
import json
from pathlib import Path

VERSION = 'eur-rc7.4-integrated-temporal-audit-0.7.4'
FACTORS = ('inflation', 'rates', 'unemployment', 'activity')


def valid_utc(value):
    if not isinstance(value, str) or not value:
        return False
    try:
        parsed = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed.tzinfo is not None and parsed.utcoffset() == dt.timedelta(0)
    except ValueError:
        return False


def event(factor, label, reference_period=None, release_date=None,
          release_timestamp_utc=None, first_release_value=None,
          first_release_verified=False, timestamp_verified=False,
          source_url=None, notes=None):
    # A publication date alone never becomes an intraday release timestamp.
    timestamp_ok = bool(timestamp_verified and valid_utc(release_timestamp_utc))
    vintage_ok = bool(first_release_verified and first_release_value is not None)
    return {
        'factor': factor, 'label': label, 'reference_period': reference_period,
        'release_date': release_date, 'release_timestamp_utc': release_timestamp_utc if timestamp_ok else None,
        'release_timestamp_verified': timestamp_ok,
        'first_release_value': first_release_value if vintage_ok else None,
        'first_release_value_verified': vintage_ok,
        'available_asof_utc': release_timestamp_utc if timestamp_ok and vintage_ok else None,
        'point_in_time_usable': timestamp_ok and vintage_ok,
        'source_url': source_url, 'notes': notes or []
    }


def audit(source):
    integration = source.get('integration', {})
    factors = integration.get('factors', {})
    safe = (source.get('asset') == 'EUR/USD'
            and str(source.get('model_version', '')).startswith('eur-rc7.3-')
            and integration.get('all_inputs_valid') is True
            and integration.get('integrated_count') == 4
            and source.get('relative_score', 'missing') is None
            and source.get('eligible_count') == 0
            and all(source.get('eligibility', {}).get(f) is False for f in FACTORS)
            and all(source.get(k) is False for k in ('signals_generated', 'database_writes',
                    'production_change_authorized', 'point_in_time_backtest_authorized'))
            and all(factors.get(f, {}).get('status') == 'integrated' for f in FACTORS))
    events = []
    per_factor = {}
    for name in FACTORS:
        f = factors.get(name, {})
        d = f.get('details', {})
        factor_events = []
        if name == 'inflation':
            for item in d.get('release_evidence', []):
                if not isinstance(item, dict):
                    continue
                factor_events.append(event(name, item.get('kind', 'publication'),
                    item.get('period'), item.get('publication_date'),
                    source_url=item.get('source_url'),
                    notes=['Headline confirmed is not full-series first-release vintage.',
                           'Date alone does not verify intraday publication time.']))
        elif name == 'rates':
            factor_events.append(event(name, 'ECB/Fed effective rate observation',
                d.get('reference', {}).get('date') if isinstance(d.get('reference'), dict) else None,
                notes=['Effective date is not the announcement timestamp.',
                       'Original announcement and expectations remain unverified.']))
        elif name == 'unemployment':
            reference = d.get('reference') or {}
            factor_events.append(event(name, 'EU/US latest common unemployment',
                reference.get('latest_common_period'),
                notes=['Observation month is not publication timestamp.',
                       'US 2025-10 missing survey must never be interpolated.']))
        elif name == 'activity':
            factor_events.append(event(name, 'EU/US latest common industrial production',
                d.get('reference_period'),
                notes=['Reference month is not release timestamp.',
                       'Index revisions and original vintages not verified.']))
        events.extend(factor_events)
        per_factor[name] = {
            'input_status': f.get('status', 'missing'),
            'event_count': len(factor_events),
            'verified_publication_timestamps': sum(e['release_timestamp_verified'] for e in factor_events),
            'verified_first_release_values': sum(e['first_release_value_verified'] for e in factor_events),
            'point_in_time_usable_events': sum(e['point_in_time_usable'] for e in factor_events),
            'eligible': False,
            'pending': ['Verify official release timestamp (UTC) for each historical observation.',
                        'Verify original first-release value and its source/vintage.',
                        'Validate statistical methodology and geography before score.']
        }
    output = {
        'model_version': VERSION, 'asof_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
        'asset': 'EUR/USD', 'module': 'integrated_temporal_audit',
        'input_model_version': source.get('model_version'),
        'input_asof_utc': source.get('asof_utc'),
        'input_valid': safe,
        'audit_policy': {
            'observation_period_is_release_timestamp': False,
            'effective_date_is_announcement_timestamp': False,
            'publication_date_is_verified_intraday_timestamp': False,
            'headline_is_full_dataset_first_release': False,
            'missing_period_imputation_allowed': False,
            'require_verified_timestamp_and_first_release_for_asof': True
        },
        'factor_audit': per_factor, 'publication_events': events,
        'verified_point_in_time_events': sum(e['point_in_time_usable'] for e in events),
        'historical_first_release_vintages_verified': False,
        'historical_release_timestamps_verified': False,
        'point_in_time_integrity_verified': False,
        'eligibility': {f: False for f in FACTORS}, 'eligible_count': 0,
        'coverage': 0.0, 'relative_score': None,
        'horizons': {'1d': {'score': None}, '5d': {'score': None}},
        'point_in_time_backtest_authorized': False, 'signals_generated': False,
        'database_writes': False, 'production_change_authorized': False,
        'source_code_modified': False,
        'next_step': 'Retrieve and verify official historical release times and first-release vintages by source.',
        'limitations': [
            'This release audits evidence carried by RC7.3; it does not fetch or independently verify official documents.',
            'Verified headline dates are not intraday timestamps.',
            'No verified first-release vintages; all historical as-of uses remain blocked.',
            'No scores, trading signals, backtests or production changes.'
        ]
    }
    return output


def selftest():
    assert not valid_utc('2026-10-16')
    assert not valid_utc('2026-10-16T10:00:00')
    assert valid_utc('2026-10-16T10:00:00Z')
    e = event('inflation', 'flash', '2026-09', '2026-10-02', source_url='https://example.org')
    assert e['available_asof_utc'] is None and not e['point_in_time_usable']
    e = event('inflation', 'flash', '2026-09', '2026-10-02',
              '2026-10-02T09:00:00Z', 3.8, True, True)
    assert e['point_in_time_usable'] and e['available_asof_utc'] == '2026-10-02T09:00:00Z'
    mock = {'asset': 'EUR/USD', 'model_version': 'eur-rc7.3-test',
            'integration': {'all_inputs_valid': True, 'integrated_count': 4,
                            'factors': {f: {'status': 'integrated', 'details': {}} for f in FACTORS}},
            'relative_score': None, 'eligible_count': 0,
            'eligibility': {f: False for f in FACTORS},
            'signals_generated': False, 'database_writes': False,
            'production_change_authorized': False, 'point_in_time_backtest_authorized': False}
    r = audit(mock)
    assert r['input_valid'] and r['verified_point_in_time_events'] == 0
    assert all(e['available_asof_utc'] is None for e in r['publication_events'])
    mock['signals_generated'] = True
    assert not audit(mock)['input_valid']
    print('SELFTEST_OK')


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--input', default='eur_rc73_result.json')
    p.add_argument('--output', default='eur_rc74_result.json')
    p.add_argument('--self-test', action='store_true')
    args = p.parse_args()
    if args.self_test:
        selftest()
        return
    source = json.loads(Path(args.input).read_text(encoding='utf-8'))
    result = audit(source)
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('RESULT_FILE=' + args.output)
    print('INPUT_VALID=' + str(result['input_valid']))
    print('VERIFIED_ASOF_EVENTS=' + str(result['verified_point_in_time_events']))
    if not result['input_valid']:
        raise SystemExit('RC7.3 input rejected; audit saved for inspection.')


if __name__ == '__main__':
    main()
