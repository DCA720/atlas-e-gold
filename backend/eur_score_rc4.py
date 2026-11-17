"""Atlas EUR RC4: diagnóstico comparativo EUR/EUA, sem sinais operacionais.

Depende dos módulos existentes backend/eur_score.py (RC3), eur_macro_sources.py
 e eur_rates.py. Usa FRED_API_KEY para séries dos EUA. Não grava no banco.
"""
import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from math import isfinite

from eur_score import evaluate as evaluate_rc3
from eur_macro_sources import collect_eur_macro
from eur_rates import collect_rate_differential

VERSION = 'eur-rc4-relative-diagnostic-experimental-0.4.1'
FRED_SERIES = {'cpi': 'CPIAUCSL', 'unemployment': 'UNRATE', 'gdp': 'GDPC1'}


def fetch_fred(series_id, key):
    params = urllib.parse.urlencode({
        'series_id': series_id, 'api_key': key, 'file_type': 'json',
        'sort_order': 'asc', 'observation_start': '2024-01-01',
    })
    req = urllib.request.Request(
        'https://api.stlouisfed.org/fred/series/observations?' + params,
        headers={'User-Agent': 'Atlas-EUR-RC4/0.4'},
    )
    with urllib.request.urlopen(req, timeout=20) as response:
        payload = json.load(response)
    result = []
    for row in payload.get('observations', []):
        try:
            value = float(row['value'])
            if isfinite(value) and row['date'] <= datetime.now(timezone.utc).date().isoformat():
                result.append({'date': row['date'], 'value': value})
        except (ValueError, TypeError, KeyError):
            continue
    if not result:
        raise ValueError('Nenhuma observação numérica válida')
    return sorted(result, key=lambda r: r['date'], reverse=True)


def month_shift(iso_date, months):
    year, month = map(int, iso_date[:7].split('-'))
    absolute = year * 12 + month - 1 - months
    return f'{absolute // 12:04d}-{absolute % 12 + 1:02d}'


def us_inflation(rows):
    by_month = {row['date'][:7]: row['value'] for row in rows}
    latest = max(by_month)
    previous_year = month_shift(latest, 12)
    if previous_year not in by_month or by_month[previous_year] <= 0:
        return {'status': 'indisponível', 'reason': 'Faltam 12 meses para calcular CPI anual'}
    return {'status': 'descritivo', 'period': latest,
            'value_pct': round(100 * (by_month[latest] / by_month[previous_year] - 1), 3),
            'method': 'CPIAUCSL: variação de 12 meses, sem ajuste de surpresa'}


def compare(rc3, us):
    factors = rc3['factors']
    result = {'model_version': VERSION, 'asof_utc': datetime.now(timezone.utc).isoformat(),
              'asset': 'EUR', 'base_rc3': rc3,
              'us_data': us, 'comparisons': {}, 'structural_score': rc3['structural_score'],
              'relative_score': None, 'horizons': {'1d': {'score': None}, '5d': {'score': None}},
              'status': 'Diagnóstico comparativo; sem sinal EUR/USD',
              'limitations': ['Não produz previsões, probabilidade de acerto ou sinais.',
                  'HICP e CPI têm metodologias diferentes; diferencial é descritivo.',
                  'Desemprego e PIB têm definições e calendários distintos.',
                  'Não há vintages históricas nem validação fora da amostra.',
                  'O score estrutural exibido é o RC3, não um novo score relativo.']}
    eu_inflation = factors.get('hicp_yoy', {})
    us_infl = us.get('inflation', {})
    if eu_inflation.get('status') == 'descritivo' and us_infl.get('status') == 'descritivo':
        result['comparisons']['inflation'] = {
            'status': 'descritivo', 'eur_hicp_yoy_pct': eu_inflation['value_pct'],
            'us_cpi_yoy_pct': us_infl['value_pct'],
            'difference_pp': round(eu_inflation['value_pct'] - us_infl['value_pct'], 3),
            'eur_period': eu_inflation['period'], 'us_period': us_infl['period'],
            'note': 'Diferencial entre índices distintos; não gera contribuição direcional.'}
    else:
        result['comparisons']['inflation'] = {'status': 'indisponível', 'reason': 'HICP ou CPI não disponível'}
    eu_unemp = factors.get('unemployment', {})
    us_unemp = us.get('unemployment', {})
    if eu_unemp.get('status') == 'descritivo' and us_unemp.get('status') == 'descritivo':
        result['comparisons']['unemployment'] = {
            'status': 'descritivo', 'eur_pct': eu_unemp['value_pct'],
            'us_pct': us_unemp['value_pct'],
            'difference_pp': round(eu_unemp['value_pct'] - us_unemp['value_pct'], 3),
            'eur_period': eu_unemp['period'], 'us_period': us_unemp['period'],
            'note': 'Níveis de desemprego, não surpresa nem sinal de câmbio.'}
    else:
        result['comparisons']['unemployment'] = {'status': 'indisponível', 'reason': 'Séries incompletas'}
    result['comparisons']['rates'] = {
        **factors.get('interest_rate_spread', {'status': 'indisponível'}),
        'note': 'Depósito BCE menos teto Fed: instrumentos diferentes, apenas proxy descritiva.'}
    result['comparisons']['activity'] = {
        'status': 'descritivo' if factors.get('activity', {}).get('status') == 'descritivo' and us.get('gdp', {}).get('status') == 'descritivo' else 'indisponível',
        'eur': factors.get('activity', {}), 'us': us.get('gdp', {}),
        'note': 'Comparação descritiva; crescimento trimestral EUA calculado sem anualização. Verificar definição da taxa europeia antes de subtrair.'}
    return result


def main():
    macro = collect_eur_macro()
    rates = collect_rate_differential()
    base = evaluate_rc3(macro, rates)
    key = os.getenv('FRED_API_KEY', '').strip()
    us = {}
    for name, sid in FRED_SERIES.items():
        if not key:
            us['inflation' if name == 'cpi' else name] = {'status': 'indisponível', 'reason': 'FRED_API_KEY não configurada'}
            continue
        try:
            rows = fetch_fred(sid, key)
            if name == 'cpi':
                us['inflation'] = us_inflation(rows)
                continue
            if name == 'unemployment':
                us[name] = {'status': 'descritivo', 'value_pct': rows[0]['value'],
                            'period': rows[0]['date'][:7]}
            else:
                if len(rows) < 2 or rows[1]['value'] <= 0:
                    us[name] = {'status': 'indisponível', 'reason': 'Faltam dois trimestres consecutivos de PIB'}
                else:
                    us[name] = {'status': 'descritivo', 'latest_level': rows[0]['value'],
                                'previous_level': rows[1]['value'],
                                'qoq_pct': round(100 * (rows[0]['value'] / rows[1]['value'] - 1), 3),
                                'period': rows[0]['date'], 'previous_period': rows[1]['date'],
                                'unit': 'bilhões de dólares encadeados',
                                'note': 'Variação trimestral não anualizada do PIB real GDPC1'}
        except Exception as exc:
            us['inflation' if name == 'cpi' else name] = {
                'status': 'indisponível', 'reason': type(exc).__name__}
    print(json.dumps(compare(base, us), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
