#!/usr/bin/env python3
"""Atlas EUR RC7.3: integra quatro relatorios diagnosticos, somente leitura.

Nao produz sinais, scores, backtests, nem altera sistemas externos.
"""
import argparse
import datetime as dt
import json
from pathlib import Path

VERSION = 'eur-rc7.3-four-factor-integration-0.7.3'
FILES = {'inflation': 'eur_rc67_result.json', 'rates': 'eur_rc69_result.json',
         'unemployment': 'eur_rc71_result.json', 'activity': 'eur_rc72_result.json'}
VERSIONS = {'inflation': 'eur-rc6.7-', 'rates': 'eur-rc6.9-',
            'unemployment': 'eur-rc7.1-', 'activity': 'eur-rc7.2-'}
BLOCKED = ('signals_generated', 'database_writes', 'production_change_authorized',
           'source_code_modified', 'point_in_time_backtest_authorized')


def validate(name, data):
    issues = []
    if not isinstance(data, dict):
        return ['report_not_object']
    if data.get('asset') != 'EUR/USD':
        issues.append('unexpected_asset')
    if not str(data.get('model_version', '')).startswith(VERSIONS[name]):
        issues.append('unexpected_model_version')
    if data.get('relative_score', 'missing') is not None:
        issues.append('score_not_explicitly_null')
    if data.get('eligible_count') != 0 or data.get('coverage') != 0.0:
        issues.append('eligibility_not_zero')
    for factor in FILES:
        if data.get('eligibility', {}).get(factor) is not False:
            issues.append('eligibility_not_false_' + factor)
    for key in BLOCKED:
        if data.get(key, False) is not False:
            issues.append('unsafe_' + key)
    for horizon in ('1d', '5d'):
        if data.get('horizons', {}).get(horizon, {}).get('score', 'missing') is not None:
            issues.append('horizon_score_not_null_' + horizon)
    return issues


def details(name, data):
    if name == 'inflation':
        return {'source_checks': data.get('quality_gates', {}),
                'reference': data.get('descriptive_september_comparison'),
                'release_evidence': data.get('eu_release_events', []),
                'pending': data.get('outstanding', [])}
    if name == 'rates':
        return {'reference': data.get('latest_aligned_rates'),
                'aligned_observation_days': data.get('aligned_observation_days'),
                'ecb_change_count': len(data.get('ecb_rate_changes', [])),
                'fed_change_count': len(data.get('fed_range_changes', [])),
                'publication_evidence': data.get('publication_evidence_audit', {})}
    if name == 'unemployment':
        return {'reference': data.get('comparison'),
                'missing_periods': {k: data.get('missing_period_audit', {}).get(k, {}).get('missing_months', [])
                                    for k in ('eu', 'us')},
                'release_evidence': data.get('release_evidence', {}),
                'quality_gates': data.get('quality_gates', {})}
    return {'reference': data.get('comparison', {}).get('latest_common_yoy_pct'),
            'reference_period': data.get('comparison', {}).get('latest_common_yoy_period'),
            'aligned_months': data.get('comparison', {}).get('aligned_months'),
            'continuity': data.get('continuity', {}),
            'quality_gates': data.get('quality_gates', {})}


def integrate(reports):
    factors = {}
    for name in FILES:
        data = reports.get(name)
        if data is None:
            factors[name] = {'status': 'missing', 'input_file': FILES[name], 'issues': ['report_missing'],
                             'eligible': False, 'descriptive_only': True}
            continue
        issues = validate(name, data)
        factors[name] = {'status': 'integrated' if not issues else 'rejected',
                         'input_file': FILES[name], 'input_model_version': data.get('model_version'),
                         'input_asof_utc': data.get('asof_utc'), 'issues': issues,
                         'eligible': False, 'descriptive_only': True,
                         'details': details(name, data),
                         'limitations': data.get('limitations', [])}
    integrated = sum(x['status'] == 'integrated' for x in factors.values())
    return {'model_version': VERSION, 'asof_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
            'asset': 'EUR/USD', 'module': 'four_factor_diagnostic_integration',
            'integration': {'integrated_count': integrated, 'expected_count': 4,
                            'all_inputs_valid': integrated == 4,
                            'factors': factors},
            'methodological_policy': {'observation_period_is_release_timestamp': False,
                                     'historical_first_release_vintages_verified': False,
                                     'cross_region_methodological_equivalence_verified': False,
                                     'point_in_time_integrity_verified': False,
                                     'different_reference_periods_may_coexist': True},
            'eligibility': {name: False for name in FILES}, 'eligible_count': 0,
            'coverage': 0.0, 'relative_score': None,
            'horizons': {'1d': {'score': None}, '5d': {'score': None}},
            'point_in_time_backtest_authorized': False, 'signals_generated': False,
            'database_writes': False, 'production_change_authorized': False,
            'source_code_modified': False,
            'next_step': 'Audit historical publication timestamps and original vintages before enabling any score.',
            'limitations': ['Input reports are independently dated snapshots, not a synchronized historical as-of view.',
                            'No missing report is silently replaced or imputed.',
                            'Integration does not validate first-release values or methodology equivalence.',
                            'No score, signal, backtest, database write or production change.']}


def selftest():
    def mock(n):
        return {'asset': 'EUR/USD', 'model_version': VERSIONS[n]+'test',
                'relative_score': None, 'eligible_count': 0, 'coverage': 0.0,
                'eligibility': {k: False for k in FILES},
                'horizons': {'1d': {'score': None}, '5d': {'score': None}},
                'signals_generated': False, 'database_writes': False,
                'production_change_authorized': False, 'source_code_modified': False,
                'point_in_time_backtest_authorized': False}
    reports = {k: mock(k) for k in FILES}
    r = integrate(reports)
    assert r['integration']['all_inputs_valid'] and r['relative_score'] is None
    reports['activity']['signals_generated'] = True
    r = integrate(reports)
    assert not r['integration']['all_inputs_valid']
    assert r['integration']['factors']['activity']['status'] == 'rejected'
    del reports['rates']
    assert integrate(reports)['integration']['factors']['rates']['status'] == 'missing'
    print('SELFTEST_OK')


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--input-dir', default='.')
    p.add_argument('--output', default='eur_rc73_result.json')
    p.add_argument('--self-test', action='store_true')
    args = p.parse_args()
    if args.self_test:
        selftest(); return
    folder = Path(args.input_dir)
    reports = {}
    for name, filename in FILES.items():
        path = folder / filename
        if path.is_file():
            try:
                reports[name] = json.loads(path.read_text(encoding='utf-8'))
            except (ValueError, OSError) as exc:
                raise RuntimeError(f'Invalid input {filename}: {exc}') from exc
    result = integrate(reports)
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print('RESULT_FILE=' + args.output)
    print('INTEGRATED=' + str(result['integration']['integrated_count']) + '/4')
    print('SCORE_BLOCKED=' + str(result['relative_score'] is None))
    if not result['integration']['all_inputs_valid']:
        raise SystemExit('Incomplete or unsafe input reports; output saved for audit.')


if __name__ == '__main__':
    main()
