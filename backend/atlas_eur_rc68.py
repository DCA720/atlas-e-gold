"""Atlas EUR RC6.8 — diagnostico de taxas BCE x Fed, somente leitura.

Nao calcula sinal ou score. Exige FRED_API_KEY e verifica metadados antes
 de comparar series. Valores sao observacoes atuais, nao vintages historicos.
"""
import json
import os
import sys
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen

VERSION = 'eur-rc6.8-ecb-fed-rates-audit-0.6.8'
API = 'https://api.stlouisfed.org/fred'
SERIES = {
    'ecb_deposit_facility': 'ECBDFR',
    'fed_target_lower': 'DFEDTARL',
    'fed_target_upper': 'DFEDTARU',
}


def fetch_json(endpoint, params):
    url = API + '/' + endpoint + '?' + urlencode(params)
    req = Request(url, headers={'User-Agent': 'AtlasEUR-RC68/0.6.8'})
    with urlopen(req, timeout=25) as response:
        return json.load(response)


def parse_rate(value):
    try:
        x = float(value)
        return x if x == x and abs(x) != float('inf') else None
    except (TypeError, ValueError):
        return None


def get_series(key, series_id, fetcher=fetch_json):
    common = {'api_key': key, 'file_type': 'json'}
    try:
        meta = fetcher('series', {**common, 'series_id': series_id})
        metadata = (meta.get('seriess') or [])[0]
        obs = fetcher('series/observations', {
            **common, 'series_id': series_id, 'sort_order': 'desc',
            'limit': 35, 'observation_start': '2026-01-01'
        })
        values = []
        for o in obs.get('observations', []):
            rate = parse_rate(o.get('value'))
            if rate is not None:
                values.append({'date': o['date'], 'rate_pct': rate})
        return {
            'status': 'ok' if values else 'no_valid_observations',
            'series_id': series_id, 'metadata': {
                'title': metadata.get('title'), 'units': metadata.get('units'),
                'frequency': metadata.get('frequency'), 'seasonal_adjustment': metadata.get('seasonal_adjustment'),
                'last_updated': metadata.get('last_updated'), 'notes': metadata.get('notes'),
            }, 'latest_observation': values[0] if values else None,
            'recent_observations': values[:15],
            'source_url': 'https://fred.stlouisfed.org/series/' + series_id,
            'observation_is_release_timestamp': False,
            'historical_vintage_verified': False,
        }
    except Exception as exc:
        return {'status': 'error', 'series_id': series_id,
                'error': str(exc)[:400], 'source_url': 'https://fred.stlouisfed.org/series/' + series_id}


def evaluate(api_key=None, fetcher=fetch_json, now=None):
    now = now or datetime.now(timezone.utc)
    key = api_key or os.getenv('FRED_API_KEY')
    series = {name: get_series(key, sid, fetcher) if key else
              {'status': 'missing_api_key', 'series_id': sid} for name, sid in SERIES.items()}
    rates = {name: (item.get('latest_observation') or {}).get('rate_pct') for name, item in series.items()}
    dates = {name: (item.get('latest_observation') or {}).get('date') for name, item in series.items()}
    ecb, lower, upper = (rates[n] for n in SERIES)
    valid_bounds = lower is not None and upper is not None and lower <= upper
    same_fed_date = dates['fed_target_lower'] is not None and dates['fed_target_lower'] == dates['fed_target_upper']
    # Comparacao descritiva somente quando os dois limites Fed sao da mesma data.
    midpoint = round((lower + upper) / 2, 6) if valid_bounds and same_fed_date else None
    diff = round(ecb - midpoint, 6) if ecb is not None and midpoint is not None else None
    return {
        'model_version': VERSION, 'asof_utc': now.isoformat().replace('+00:00', 'Z'), 'asset': 'EUR/USD',
        'module': 'ECB_FED_interest_rates', 'source_audit': series,
        'instrument_comparison': {
            'ecb_instrument': 'ECB deposit facility rate',
            'fed_instruments': 'Federal funds target range lower/upper bounds',
            'fed_bounds_same_observation_date': same_fed_date,
            'fed_bounds_valid': valid_bounds,
            'ecb_latest_pct': ecb, 'fed_lower_pct': lower, 'fed_upper_pct': upper,
            'fed_midpoint_pct': midpoint, 'ecb_minus_fed_midpoint_pp': diff,
            'observation_dates': dates,
            'same_reference_date_verified': len(set(dates.values())) == 1 and all(dates.values()),
            'instrument_methodology_equivalent': False,
            'spread_is_trading_signal': False,
            'note': 'Taxa de deposito BCE e centro da faixa Fed nao sao instrumentos identicos. Diferencial apenas descritivo.'
        },
        'release_and_vintage_audit': {
            'ecb_decision_release_timestamps_verified': False,
            'fed_fomc_release_timestamps_verified': False,
            'effective_dates_are_release_times': False,
            'point_in_time_values_verified': False,
            'historical_vintages_verified': False,
            'note': 'FRED observations sao dados de referencia, nao prova do instante em que a decisao se tornou publica.'
        },
        'rates_technical_diagnostic_ready': all(s['status'] == 'ok' for s in series.values()) and valid_bounds,
        'eligibility': {'inflation': False, 'rates': False, 'unemployment': False, 'activity': False},
        'eligible_count': 0, 'coverage': 0.0, 'relative_score': None,
        'horizons': {'1d': {'score': None}, '5d': {'score': None}},
        'point_in_time_backtest_authorized': False,
        'signals_generated': False, 'database_writes': False,
        'production_change_authorized': False, 'source_code_modified': False,
        'next_steps': [
            'Validar se as series FRED selecionadas representam exatamente os instrumentos pretendidos.',
            'Conferir datas de vigencia e publicacao das decisoes BCE/FOMC em fontes primarias.',
            'Construir historico point-in-time das taxas e mudancas de expectativas, sem look-ahead.',
            'Avaliar instrumentos e unidades antes de qualquer score.'
        ]
    }


def main():
    result = evaluate()
    path = os.getenv('EUR_RC68_OUTPUT', 'eur_rc68_result.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(json.dumps({'model_version': VERSION, 'status': {k:v['status'] for k,v in result['source_audit'].items()},
                      'rates_technical_diagnostic_ready': result['rates_technical_diagnostic_ready'],
                      'output': path}, ensure_ascii=False))
    if not result['rates_technical_diagnostic_ready']:
        sys.exit(2)


if __name__ == '__main__':
    main()
