"""Atlas EUR RC7.0 — unemployment source diagnostic (read-only)."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

VERSION = 'eur-rc7.0-unemployment-source-audit-0.7.0'
EU_API = 'https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/une_rt_m'
FRED_API = 'https://api.stlouisfed.org/fred'


def fetch(url):
    with urlopen(Request(url, headers={'User-Agent': 'AtlasEUR-RC70/0.7.0', 'Accept': 'application/json'}), timeout=45) as response:
        return json.load(response)


def numeric(x):
    try:
        v = float(x)
        return v if v == v and abs(v) != float('inf') else None
    except (TypeError, ValueError):
        return None


def decode_jsonstat(dataset):
    """Decode a single geo/sex/age/unit/frequency JSON-stat time series."""
    ids = dataset['id']
    sizes = dataset['size']
    assert len(ids) == len(sizes)
    time_dim = dataset['dimension']['time']['category']['index']
    assert isinstance(time_dim, dict)
    values = dataset.get('value', {})
    output = {}
    for period, pos in time_dim.items():
        coords = [0] * len(ids)
        coords[ids.index('time')] = pos
        flat = 0
        for index, size in zip(coords, sizes):
            flat = flat * size + index
        value = values.get(str(flat)) if isinstance(values, dict) else values[flat]
        val = numeric(value)
        if val is not None:
            output[period] = val
    return dict(sorted(output.items()))


def fred_observations(api_key):
    params = {'series_id': 'UNRATE', 'api_key': api_key, 'file_type': 'json', 'observation_start': '2024-01-01'}
    raw = fetch(FRED_API + '/series/observations?' + urlencode(params))
    out = {}
    for row in raw.get('observations', []):
        val = numeric(row.get('value'))
        if val is not None:
            out[row['date'][:7]] = val
    return dict(sorted(out.items()))


def changes(series):
    periods = sorted(series)
    return [{'period': b, 'previous_period': a, 'previous_pct': series[a], 'current_pct': series[b],
             'delta_pp': round(series[b] - series[a], 6)}
            for a, b in zip(periods, periods[1:]) if series[a] != series[b]]


def run():
    result = {
        'model_version': VERSION, 'asof_utc': datetime.now(timezone.utc).isoformat(), 'asset': 'EUR/USD',
        'module': 'EU_US_unemployment',
        'methodology': {
            'eu': {'source': 'Eurostat', 'dataset': 'une_rt_m', 'geo': 'EA21', 'freq': 'M',
                   's_adj': 'SA', 'unit': 'PC_ACT', 'age': 'TOTAL', 'sex': 'T',
                   'age_definition_note': 'Eurostat unemployment typically covers ages 15-74; verify chosen TOTAL category and current metadata.'},
            'us': {'source': 'BLS via FRED', 'series': 'UNRATE', 'frequency': 'Monthly',
                   'seasonal_adjustment': 'Seasonally adjusted', 'age_definition': 'Civilian labor force ages 16+'},
            'cross_region_methodology_equivalent': False,
            'release_timestamp_is_observation_date': False,
            'historical_first_release_vintages_verified': False,
            'geo_composition_historical_consistency_verified': False,
        },
        'source_audit': {}, 'comparison': {},
        'eligibility': {'inflation': False, 'rates': False, 'unemployment': False, 'activity': False},
        'eligible_count': 0, 'coverage': 0.0, 'relative_score': None,
        'horizons': {'1d': {'score': None}, '5d': {'score': None}},
        'point_in_time_backtest_authorized': False, 'signals_generated': False,
        'database_writes': False, 'production_change_authorized': False,
        'source_code_modified': False,
        'limitations': [
            'Eurostat and US BLS unemployment age populations and survey designs differ.',
            'Observation months do not prove when the numbers became public.',
            'Current Eurostat and FRED series are not historical first-release vintages.',
            'No score, trading signals, backtest, or database writes.'
        ],
    }
    eu = us = {}
    params = {'freq': 'M', 's_adj': 'SA', 'unit': 'PC_ACT', 'age': 'TOTAL', 'sex': 'T',
              'geo': 'EA21', 'sinceTimePeriod': '2024-01', 'lang': 'EN'}
    eu_url = EU_API + '?' + urlencode(params)
    try:
        raw = fetch(eu_url)
        eu = decode_jsonstat(raw)
        result['source_audit']['eurostat'] = {
            'status': 'ok' if eu else 'empty', 'url': eu_url, 'dataset_label': raw.get('label'),
            'updated': raw.get('updated'), 'period_count': len(eu),
            'latest_period': max(eu) if eu else None, 'latest_rate_pct': eu[max(eu)] if eu else None,
            'recent_observations': [{'period': p, 'rate_pct': eu[p]} for p in sorted(eu)[-12:]],
            'recent_changes': changes(eu)[-12:],
            'source_metadata_verified_for_exact_dimensions': bool(eu),
        }
    except Exception as exc:
        result['source_audit']['eurostat'] = {'status': 'error', 'url': eu_url,
            'error': f'{type(exc).__name__}: {str(exc)[:300]}'}
    key = os.getenv('FRED_API_KEY', '').strip()
    if not key:
        result['source_audit']['fred'] = {'status': 'missing_FRED_API_KEY'}
    else:
        try:
            us = fred_observations(key)
            result['source_audit']['fred'] = {
                'status': 'ok' if us else 'empty', 'series_id': 'UNRATE',
                'url': 'https://fred.stlouisfed.org/series/UNRATE', 'period_count': len(us),
                'latest_period': max(us) if us else None, 'latest_rate_pct': us[max(us)] if us else None,
                'recent_observations': [{'period': p, 'rate_pct': us[p]} for p in sorted(us)[-12:]],
                'recent_changes': changes(us)[-12:],
            }
        except Exception as exc:
            result['source_audit']['fred'] = {'status': 'error',
                'error': f'{type(exc).__name__}: {str(exc)[:300]}'}
    aligned = sorted(set(eu) & set(us))
    result['comparison'] = {
        'aligned_period_count': len(aligned),
        'latest_common_period': aligned[-1] if aligned else None,
        'latest_common_eu_pct': eu[aligned[-1]] if aligned else None,
        'latest_common_us_pct': us[aligned[-1]] if aligned else None,
        'eu_minus_us_pp': round(eu[aligned[-1]] - us[aligned[-1]], 6) if aligned else None,
        'latest_common_12_periods': [
            {'period': p, 'eu_pct': eu[p], 'us_pct': us[p], 'eu_minus_us_pp': round(eu[p] - us[p], 6)}
            for p in aligned[-12:]],
        'descriptive_only': True, 'trading_signal': False,
    }
    result['unemployment_technical_diagnostic_ready'] = bool(eu and us and aligned)
    return result


def main():
    output = Path(os.getenv('ATLAS_EUR_OUTPUT', 'eur_rc70_result.json'))
    result = run()
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'output': str(output), 'eu_status': result['source_audit'].get('eurostat', {}).get('status'),
        'us_status': result['source_audit'].get('fred', {}).get('status'),
        'aligned_periods': result['comparison']['aligned_period_count'],
        'diagnostic_ready': result['unemployment_technical_diagnostic_ready']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
