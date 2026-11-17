"""Atlas EUR RC5.1: alinhamento temporal exploratório, sem pontuação nem sinais.

Depende de atlas_eur_rc5.py e eur_score_rc4.py na mesma pasta backend/.
Consulta FRED somente leitura; não modifica módulos existentes ou banco.
"""
import contextlib
import io
import json
import os
from datetime import datetime, timezone

from atlas_eur_rc5 import evaluate as evaluate_rc5
from eur_score_rc4 import main as rc4_main, fetch_fred

VERSION = 'eur-rc5.1-temporal-alignment-experimental-0.5.1'


def quarter_from_date(date):
    return f'{date[:4]}-Q{(int(date[5:7]) - 1) // 3 + 1}'


def yoy_at(rows, month):
    values = {r['date'][:7]: r['value'] for r in rows}
    year, mm = map(int, month.split('-'))
    base = f'{year - 1:04d}-{mm:02d}'
    if month not in values or base not in values or values[base] <= 0:
        return {'status': 'indisponível', 'period': month, 'reference_period': base,
                'reason': 'Par de 12 meses não disponível na série'}
    return {'status': 'descritivo', 'period': month, 'reference_period': base,
            'value_pct': round((values[month] / values[base] - 1) * 100, 3)}


def gdp_at_quarter(rows, quarter):
    indexed = {quarter_from_date(r['date']): r for r in rows}
    if quarter not in indexed:
        return {'status': 'indisponível', 'quarter': quarter, 'reason': 'Trimestre não encontrado'}
    year, q = map(int, quarter.split('-Q'))
    prev = f'{year-1}-Q4' if q == 1 else f'{year}-Q{q-1}'
    if prev not in indexed or indexed[prev]['value'] <= 0:
        return {'status': 'indisponível', 'quarter': quarter, 'reason': 'Trimestre anterior não encontrado'}
    return {'status': 'descritivo', 'quarter': quarter, 'previous_quarter': prev,
            'qoq_pct_nonannualized': round((indexed[quarter]['value'] / indexed[prev]['value'] - 1) * 100, 3),
            'series': 'GDPC1', 'definition': 'PIB real EUA, nível encadeado dessazonalizado'}


def safe_fetch(series, key):
    if not key:
        return None, 'FRED_API_KEY não configurada'
    try:
        return fetch_fred(series, key), None
    except Exception as exc:
        return None, type(exc).__name__


def evaluate(rc4, key, fetch=safe_fetch):
    rc5 = evaluate_rc5(rc4)
    factors = rc4.get('base_rc3', {}).get('factors', {})
    eu_gdp = factors.get('activity', {})
    eu_infl = factors.get('hicp_yoy', {})
    eu_unemp = factors.get('unemployment', {})
    us_gdp_rows, gdp_error = fetch('GDPC1', key)
    us_cpi_sa, cpi_error = fetch('CPIAUCSL', key)
    us_cpi_nsa, nsa_error = fetch('CPIAUCNS', key)
    us_unemp, unemp_error = fetch('UNRATE', key)
    quarter = eu_gdp.get('period')
    eu_infl_period = eu_infl.get('period')
    eu_unemp_period = eu_unemp.get('period')
    matched_gdp = gdp_at_quarter(us_gdp_rows, quarter) if us_gdp_rows and quarter else {'status': 'indisponível', 'reason': gdp_error or 'Trimestre europeu não informado'}
    sa = yoy_at(us_cpi_sa, eu_infl_period) if us_cpi_sa and eu_infl_period else {'status': 'indisponível', 'reason': cpi_error or 'Período europeu não informado'}
    nsa = yoy_at(us_cpi_nsa, eu_infl_period) if us_cpi_nsa and eu_infl_period else {'status': 'indisponível', 'reason': nsa_error or 'Período europeu não informado'}
    unemployment = next((r for r in (us_unemp or []) if r['date'][:7] == eu_unemp_period), None)
    unemp_match = ({'status': 'descritivo', 'period': eu_unemp_period, 'us_pct': unemployment['value'],
                    'eur_pct': eu_unemp.get('value_pct'),
                    'difference_pp': round(eu_unemp['value_pct'] - unemployment['value'], 3)}
                   if unemployment and isinstance(eu_unemp.get('value_pct'), (int, float)) else
                   {'status': 'indisponível', 'period': eu_unemp_period, 'reason': unemp_error or 'Observação coincidente ausente'})
    return {
        'model_version': VERSION, 'asof_utc': datetime.now(timezone.utc).isoformat(), 'asset': 'EUR/USD',
        'source_model_version': rc4.get('model_version'), 'rc5_quality': rc5['quality_checks'],
        'aligned_descriptive': {
            'inflation': {'eur_period': eu_infl_period, 'eur_hicp_yoy_pct': eu_infl.get('value_pct'),
                          'us_cpi_sa': sa, 'us_cpi_nsa': nsa,
                          'methodology_verified': False,
                          'note': 'HICP e CPI não são índices harmonizados; período coincidente não implica equivalência.'},
            'unemployment': {**unemp_match, 'methodology_verified': False,
                             'note': 'Alinhamento mensal apenas; definições ainda não validadas.'},
            'activity': {'eur_quarter': quarter, 'eur_reported_pct': eu_gdp.get('value_pct'),
                         'us_same_quarter': matched_gdp, 'eur_growth_definition_verified': False,
                         'note': 'Confirmar se o PIB europeu é variação trimestral dessazonalizada antes de subtrair.'},
            'rates': {'status': 'bloqueado', 'reason': 'BCE depósito e Fed teto não são instrumentos equivalentes'}
        },
        'eligible_factors': rc5['eligible_factors'], 'eligible_count': rc5['eligible_count'],
        'coverage': rc5['coverage'], 'relative_score': None,
        'horizons': {'1d': {'score': None}, '5d': {'score': None}},
        'signals_generated': False, 'database_writes': False,
        'status': 'Alinhamento temporal exploratório; elegibilidade RC5 preservada',
        'limitations': ['Alinhar datas não valida metodologia nem autoriza score.',
                        'FRED apresenta lacunas; valores ausentes não são interpolados.',
                        'Não calcula surpresas macro sem expectativas e horários de publicação.']
    }


def main():
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        rc4_main()
    rc4 = json.loads(buffer.getvalue())
    print(json.dumps(evaluate(rc4, os.getenv('FRED_API_KEY', '').strip()), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
