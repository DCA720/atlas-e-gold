"""Atlas EUR RC5.9: auditoria HICP EA21 x CPI EUA (YoY), somente leitura."""
import json
import math
import os
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from atlas_eur_rc58 import evaluate as euro_evaluate, month_number

VERSION = 'eur-rc5.9-eu-us-inflation-comparison-0.5.9'
FRED_URL = 'https://api.stlouisfed.org/fred/series/observations'


def fred_cpi(api_key, timeout=35):
    if not api_key:
        return {'status': 'erro', 'reason': 'FRED_API_KEY ausente', 'observations': {}}
    params = {'series_id': 'CPIAUCSL', 'api_key': api_key, 'file_type': 'json',
              'observation_start': '2022-01-01', 'sort_order': 'asc'}
    req = urllib.request.Request(FRED_URL + '?' + urllib.parse.urlencode(params),
                                 headers={'User-Agent': 'AtlasEUR-RC59/0.5.9'})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = resp.read(5_000_001)
    if len(payload) > 5_000_000:
        raise ValueError('Resposta FRED excedeu 5 MB')
    data = json.loads(payload)
    levels, unavailable = {}, []
    for item in data.get('observations', []):
        period = str(item.get('date', ''))[:7]
        try:
            month_number(period)
            val = float(item.get('value', '.'))
            if not math.isfinite(val) or val <= 0:
                raise ValueError('valor invalido')
            levels[period] = val
        except (ValueError, TypeError):
            if len(period) == 7:
                unavailable.append(period)
    if not levels:
        return {'status': 'sem_dados', 'reason': 'Sem niveis CPI validos', 'observations': {},
                'missing_or_invalid_periods': sorted(set(unavailable))}
    yoy, missing_bases = {}, []
    for period in sorted(levels):
        index = month_number(period) - 12
        prior = f'{index // 12:04d}-{index % 12 + 1:02d}'
        if prior not in levels:
            missing_bases.append({'period': period, 'missing_base': prior})
            continue
        yoy[period] = round((levels[period] / levels[prior] - 1) * 100, 8)
    return {'status': 'ok', 'dataset': 'CPIAUCSL', 'unit': 'index_1982_84_100',
            'transformation': '12_month_percent_change_from_index_levels',
            'observation_count': len(levels), 'yoy_count': len(yoy),
            'last_index_period': max(levels), 'last_yoy_period': max(yoy) if yoy else None,
            'missing_or_invalid_periods': sorted(set(unavailable)),
            'missing_base_periods': missing_bases,
            'observations': yoy}


def evaluate(euro_fetcher=euro_evaluate, us_fetcher=fred_cpi, api_key=None):
    euro = euro_fetcher()
    candidate = euro.get('series_audit', {}).get('EA21', {})
    eu = candidate.get('observations', {}) if candidate.get('source_verified') and candidate.get('continuity_verified') else {}
    try:
        us = us_fetcher(os.environ.get('FRED_API_KEY') if api_key is None else api_key)
    except Exception as exc:
        us = {'status': 'erro', 'reason': f'{type(exc).__name__}: {str(exc)[:350]}', 'observations': {}}
    usa = us.get('observations', {})
    common = sorted(set(eu) & set(usa), key=month_number)
    pairs = [{'period': p, 'eu_hicp_yoy': eu[p], 'us_cpi_yoy': usa[p],
              'eu_minus_us_pp': round(eu[p] - usa[p], 8)} for p in common]
    eu_only = sorted(set(eu) - set(usa), key=month_number)
    us_only = sorted(set(usa) - set(eu), key=month_number)
    return {'model_version': VERSION, 'asof_utc': datetime.now(timezone.utc).isoformat(),
            'asset': 'EUR/USD',
            'europe': {'status': candidate.get('status', 'sem_dados'), 'dataset': 'prc_hicp_minr',
                       'geo': 'EA21', 'filters': {'coicop18': 'TOTAL', 'unit': 'RCH_A'},
                       'source_verified': candidate.get('source_verified', False),
                       'continuity_verified': candidate.get('continuity_verified', False),
                       'observation_count': len(eu), 'last_period': max(eu) if eu else None,
                       'observations': eu},
            'united_states': us,
            'alignment': {'common_period_count': len(common), 'first_common_period': common[0] if common else None,
                          'last_common_period': common[-1] if common else None,
                          'same_period_pairs': pairs, 'eu_periods_without_us_yoy': eu_only,
                          'us_yoy_periods_without_eu': us_only},
            'methodology': {'eu_measure': 'HICP headline annual rate Eurostat',
                            'us_measure': 'CPI-U all items seasonally adjusted index CPIAUCSL, computed 12m YoY',
                            'same_month_comparison_only': True,
                            'basket_and_methodology_equivalence_verified': False,
                            'seasonal_adjustment_harmonized': False,
                            'release_timestamps_verified': False,
                            'vintage_verified': False,
                            'spread_is_descriptive_not_trading_signal': True},
            'eligible_factors': {k: False for k in ('inflation', 'unemployment', 'rates', 'activity')},
            'eligible_count': 0, 'coverage': 0.0, 'relative_score': None,
            'horizons': {'1d': {'score': None}, '5d': {'score': None}},
            'signals_generated': False, 'database_writes': False,
            'production_change_authorized': False, 'source_code_modified': False,
            'limitations': ['CPIAUCSL e ajustado sazonalmente; HICP RCH_A nao foi harmonizado quanto ao ajuste sazonal.',
                            'CPI e HICP usam cestas e metodologias diferentes.',
                            'Dado FRED ausente ou base ausente nao e interpolado.',
                            'Sem horario de divulgacao e vintages nao existe backtest ponto-no-tempo.']}


if __name__ == '__main__':
    print(json.dumps(evaluate(), ensure_ascii=False, indent=2))
