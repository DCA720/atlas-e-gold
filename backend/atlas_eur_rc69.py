"""Atlas EUR RC6.9: auditoria de mudancas nas taxas BCE/Fed, somente leitura.

As datas de observacao FRED sao datas de vigencia, NAO horarios de anuncio.
Nao gera score, sinal, operacao ou escrita em banco.
"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

VERSION = 'eur-rc6.9-ecb-fed-decision-effective-date-audit-0.6.9'
API = 'https://api.stlouisfed.org/fred'
SERIES = {'ecb_deposit_facility': 'ECBDFR', 'fed_target_lower': 'DFEDTARL', 'fed_target_upper': 'DFEDTARU'}
OFFICIAL_SOURCES = {
    'ecb': 'https://www.ecb.europa.eu/press/pr/date/html/index.en.html',
    'fed': 'https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm',
}


def fetch_json(endpoint, params):
    req = Request(API + '/' + endpoint + '?' + urlencode(params), headers={'User-Agent': 'AtlasEUR-RC69/0.6.9'})
    with urlopen(req, timeout=30) as response:
        return json.load(response)


def parse_number(value):
    try:
        x = float(value)
        return x if x == x and abs(x) != float('inf') else None
    except (TypeError, ValueError):
        return None


def fetch_series(key, series_id, fetcher=fetch_json):
    params = {'api_key': key, 'file_type': 'json', 'series_id': series_id}
    try:
        meta = fetcher('series', params)
        info = (meta.get('seriess') or [])[0]
        obs = fetcher('series/observations', {**params, 'observation_start': '2025-01-01',
                                              'observation_end': '2026-11-18', 'limit': 100000})
        values = {}
        for item in obs.get('observations', []):
            val = parse_number(item.get('value'))
            if val is not None:
                values[item['date']] = val
        return {'status': 'ok' if values else 'empty', 'series_id': series_id,
                'metadata': {'title': info.get('title'), 'units': info.get('units'),
                             'frequency': info.get('frequency'), 'notes': info.get('notes')},
                'observations': values, 'count': len(values),
                'source_url': 'https://fred.stlouisfed.org/series/' + series_id}
    except Exception as exc:
        return {'status': 'error', 'series_id': series_id, 'error': str(exc)[:350],
                'observations': {}, 'count': 0}


def changes(values):
    """Detecta mudancas entre observacoes consecutivas; nao deduz horario de anuncio."""
    result = []
    previous = None
    for day, val in sorted(values.items()):
        if previous is not None and abs(val - previous[1]) > 1e-10:
            result.append({'effective_observation_date': day, 'previous_observation_date': previous[0],
                           'previous_rate_pct': previous[1], 'new_rate_pct': val,
                           'delta_pp': round(val - previous[1], 6),
                           'announcement_timestamp_verified': False,
                           'first_publication_vintage_verified': False})
        previous = (day, val)
    return result


def paired_fed_changes(lower, upper):
    """Exige ambas as faixas no mesmo dia; mudancas entre dias consecutivos disponiveis."""
    common = sorted(set(lower) & set(upper))
    events, previous = [], None
    for day in common:
        lo, hi = lower[day], upper[day]
        if lo > hi:
            continue
        current = {'date': day, 'lower': lo, 'upper': hi, 'midpoint': (lo + hi) / 2}
        if previous and (lo != previous['lower'] or hi != previous['upper']):
            events.append({'effective_observation_date': day,
                           'previous_observation_date': previous['date'],
                           'lower_before_pct': previous['lower'], 'lower_after_pct': lo,
                           'upper_before_pct': previous['upper'], 'upper_after_pct': hi,
                           'midpoint_before_pct': previous['midpoint'], 'midpoint_after_pct': current['midpoint'],
                           'midpoint_change_pp': round(current['midpoint'] - previous['midpoint'], 6),
                           'announcement_timestamp_verified': False,
                           'first_publication_vintage_verified': False})
        previous = current
    return events


def main():
    key = os.getenv('FRED_API_KEY', '').strip()
    output = Path(os.getenv('EUR_RC69_OUTPUT', 'eur_rc69_result.json'))
    result = {'model_version': VERSION, 'asof_utc': datetime.now(timezone.utc).isoformat(),
              'asset': 'EUR/USD', 'module': 'ECB_FED_decision_history',
              'official_reference_pages': OFFICIAL_SOURCES,
              'source_audit': {}, 'ecb_rate_changes': [], 'fed_range_changes': [],
              'publication_evidence_audit': {
                  'official_release_documents_retrieved': False,
                  'ecb_announcement_timestamps_verified': False,
                  'fed_announcement_timestamps_verified': False,
                  'historical_first_release_values_verified': False,
                  'note': 'Paginas de referencia nao sao evidencia de anuncios individuais. Datas FRED sao de vigencia.'},
              'rates_technical_diagnostic_ready': False,
              'eligibility': {'inflation': False, 'rates': False, 'unemployment': False, 'activity': False},
              'eligible_count': 0, 'coverage': 0.0, 'relative_score': None,
              'horizons': {'1d': {'score': None}, '5d': {'score': None}},
              'point_in_time_backtest_authorized': False, 'signals_generated': False,
              'database_writes': False, 'production_change_authorized': False,
              'source_code_modified': False,
              'limitations': ['Datas de vigencia nao comprovam horario de anuncio.',
                              'Amostra comeca em 2025; primeira observacao nao e mudanca comprovada.',
                              'Sem vintages originais ou expectativas monetarias, nao ha score.',
                              'Nenhum dado de producao e alterado.']}
    if not key:
        result['error'] = 'FRED_API_KEY ausente; nenhuma consulta executada.'
    else:
        series = {name: fetch_series(key, sid) for name, sid in SERIES.items()}
        result['source_audit'] = {name: {k: v for k, v in data.items() if k != 'observations'}
                                  for name, data in series.items()}
        if all(data['status'] == 'ok' for data in series.values()):
            ecb = series['ecb_deposit_facility']['observations']
            lower = series['fed_target_lower']['observations']
            upper = series['fed_target_upper']['observations']
            result['ecb_rate_changes'] = changes(ecb)
            result['fed_range_changes'] = paired_fed_changes(lower, upper)
            common = sorted(set(ecb) & set(lower) & set(upper))
            result['aligned_observation_days'] = len(common)
            if common:
                day = common[-1]
                result['latest_aligned_rates'] = {'date': day, 'ecb_pct': ecb[day],
                    'fed_lower_pct': lower[day], 'fed_upper_pct': upper[day],
                    'fed_midpoint_pct': (lower[day] + upper[day]) / 2,
                    'ecb_minus_fed_midpoint_pp': round(ecb[day] - (lower[day] + upper[day]) / 2, 6),
                    'descriptive_only': True}
            result['rates_technical_diagnostic_ready'] = bool(common)
        else:
            result['error'] = 'Uma ou mais series nao foram recuperadas.'
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Resultado: {output} | pronto={result["rates_technical_diagnostic_ready"]}')
    return 0 if result['rates_technical_diagnostic_ready'] else 1


if __name__ == '__main__':
    sys.exit(main())
