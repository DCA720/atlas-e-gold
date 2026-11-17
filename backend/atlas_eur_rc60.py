"""Atlas EUR RC6.0: auditoria CPI EUA ajustado vs nao ajustado; sem sinais."""
import json
import math
import os
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from atlas_eur_rc58 import evaluate as euro_evaluate, month_number

VERSION = 'eur-rc6.0-us-cpi-seasonality-audit-0.6.0'
FRED_URL = 'https://api.stlouisfed.org/fred/series/observations'
SERIES = ('CPIAUCSL', 'CPIAUCNS')


def fetch_fred(series_id, api_key, timeout=35):
    if series_id not in SERIES:
        raise ValueError('Serie FRED nao permitida')
    if not api_key:
        return {'status': 'erro', 'reason': 'FRED_API_KEY ausente', 'observations': {}}
    params = {'series_id': series_id, 'api_key': api_key, 'file_type': 'json',
              'observation_start': '2022-01-01', 'sort_order': 'asc'}
    req = urllib.request.Request(FRED_URL + '?' + urllib.parse.urlencode(params),
                                 headers={'User-Agent': 'AtlasEUR-RC60/0.6.0'})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read(5_000_001)
    if len(raw) > 5_000_000:
        raise ValueError('Resposta FRED excedeu 5 MB')
    payload = json.loads(raw)
    if not isinstance(payload.get('observations'), list):
        raise ValueError('Resposta FRED sem lista observations')
    levels, missing = {}, []
    for item in payload['observations']:
        period = str(item.get('date', ''))[:7]
        try:
            month_number(period)
            value = float(item.get('value', '.'))
            if not math.isfinite(value) or value <= 0:
                raise ValueError('indice invalido')
            levels[period] = value
        except (ValueError, TypeError):
            if len(period) == 7:
                missing.append(period)
    yoy, missing_base = {}, []
    for period, value in sorted(levels.items()):
        n = month_number(period) - 12
        base = f'{n // 12:04d}-{n % 12 + 1:02d}'
        if base not in levels:
            missing_base.append({'period': period, 'missing_base': base})
        else:
            yoy[period] = round(100 * (value / levels[base] - 1), 8)
    return {'status': 'ok' if yoy else 'sem_dados', 'dataset': series_id,
            'seasonally_adjusted': series_id == 'CPIAUCSL',
            'index_count': len(levels), 'yoy_count': len(yoy),
            'last_index_period': max(levels) if levels else None,
            'last_yoy_period': max(yoy) if yoy else None,
            'missing_or_invalid_periods': sorted(set(missing)),
            'missing_base_periods': missing_base, 'observations': yoy}


def evaluate(euro_fetcher=euro_evaluate, fred_fetcher=fetch_fred, api_key=None):
    try:
        euro = euro_fetcher()
        candidate = euro.get('series_audit', {}).get('EA21', {})
        eu = candidate.get('observations', {}) if (candidate.get('source_verified') and candidate.get('continuity_verified')) else {}
        eu_status = 'ok' if eu else 'sem_dados'
    except Exception as exc:
        eu, eu_status = {}, f'erro: {type(exc).__name__}: {str(exc)[:250]}'
    key = os.environ.get('FRED_API_KEY') if api_key is None else api_key
    us = {}
    for series in SERIES:
        try:
            us[series] = fred_fetcher(series, key)
        except Exception as exc:
            us[series] = {'status': 'erro', 'reason': f'{type(exc).__name__}: {str(exc)[:350]}', 'observations': {}}
    sa = us['CPIAUCSL'].get('observations', {})
    nsa = us['CPIAUCNS'].get('observations', {})
    shared = sorted(set(sa) & set(nsa), key=month_number)
    comparisons = {}
    for series in SERIES:
        obs = us[series].get('observations', {})
        common = sorted(set(eu) & set(obs), key=month_number)
        comparisons[series] = {'common_period_count': len(common),
            'latest_common_period': common[-1] if common else None,
            'latest_common_eu': eu[common[-1]] if common else None,
            'latest_common_us': obs[common[-1]] if common else None,
            'latest_common_spread_pp': round(eu[common[-1]] - obs[common[-1]], 8) if common else None,
            'eu_periods_without_us_yoy': sorted(set(eu) - set(obs), key=month_number),
            'last_12_aligned': [{'period': p, 'eu': eu[p], 'us': obs[p],
                'eu_minus_us_pp': round(eu[p] - obs[p], 8)} for p in common[-12:]]}
    return {'model_version': VERSION, 'asof_utc': datetime.now(timezone.utc).isoformat(),
        'asset': 'EUR/USD', 'europe': {'status': eu_status, 'dataset': 'prc_hicp_minr',
            'geo': 'EA21', 'filters': {'coicop18': 'TOTAL', 'unit': 'RCH_A'},
            'observation_count': len(eu), 'last_period': max(eu) if eu else None},
        'us_series': us,
        'us_seasonality_comparison': {'common_period_count': len(shared),
            'latest_common_period': shared[-1] if shared else None,
            'last_12_differences_sa_minus_nsa_pp': [{'period': p, 'sa_yoy': sa[p],
                'nsa_yoy': nsa[p], 'difference_pp': round(sa[p] - nsa[p], 8)} for p in shared[-12:]]},
        'eu_us_alignment': comparisons,
        'methodology': {'candidate_us_series_for_further_review': 'CPIAUCNS',
            'candidate_is_not_approved': True,
            'reason': 'CPIAUCNS e nao ajustado sazonalmente; comparar com HICP requer confirmar metadados oficiais e definicoes.',
            'basket_equivalence_verified': False, 'release_timestamps_verified': False,
            'vintage_verified': False, 'point_in_time_backtest_possible': False},
        'eligible_factors': {k: False for k in ('inflation', 'unemployment', 'rates', 'activity')},
        'eligible_count': 0, 'coverage': 0.0, 'relative_score': None,
        'horizons': {'1d': {'score': None}, '5d': {'score': None}},
        'signals_generated': False, 'database_writes': False,
        'production_change_authorized': False, 'source_code_modified': False,
        'limitations': ['Comparacao descritiva por mes de referencia, nao por data de publicacao.',
            'CPI e HICP tem cestas e metodologias distintas.',
            'Valores ausentes e bases anuais ausentes nao sao interpolados.',
            'Nenhum score, sinal, escrita em banco ou alteracao em producao.']}


if __name__ == '__main__':
    print(json.dumps(evaluate(), ensure_ascii=False, indent=2))
