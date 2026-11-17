"""Atlas EUR RC5.8: padronização experimental HICP EA21, somente leitura."""
import json
import re
from datetime import datetime, timezone
from atlas_eur_rc57 import query

VERSION = 'eur-rc5.8-hicp-ea21-standardization-0.5.8'
DATASET = 'prc_hicp_minr'
FILTERS = {'coicop18': 'TOTAL', 'unit': 'RCH_A'}


def month_number(period):
    if not re.fullmatch(r'\d{4}-(0[1-9]|1[0-2])', period):
        raise ValueError(f'Período mensal inválido: {period}')
    year, month = map(int, period.split('-'))
    return year * 12 + month - 1


def inspect(result, geography):
    if result.get('status') != 'ok':
        return {'status': result.get('status', 'erro'), 'reason': result.get('reason', result.get('error')),
                'source_verified': False, 'continuity_verified': False}
    dims = result.get('dimensions', {})
    expected = {'freq': ['M'], 'unit': ['RCH_A'], 'coicop18': ['TOTAL'], 'geo': [geography]}
    filters_ok = all(dims.get(k) == v for k, v in expected.items())
    obs = result.get('observations', {})
    valid = {p: v for p, v in obs.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}
    periods = sorted(valid, key=month_number)
    missing = []
    if periods:
        observed = {month_number(p) for p in periods}
        for n in range(month_number(periods[0]), month_number(periods[-1]) + 1):
            if n not in observed:
                missing.append(f'{n // 12:04d}-{n % 12 + 1:02d}')
    return {'status': 'ok', 'source_verified': filters_ok, 'continuity_verified': bool(periods) and not missing,
            'missing_months': missing, 'observation_count': len(periods),
            'first_period': periods[0] if periods else None, 'last_period': periods[-1] if periods else None,
            'last_value': valid[periods[-1]] if periods else None,
            'source': {'dataset': DATASET, 'filters': FILTERS, 'geo': geography, 'window': 36},
            'observations': {p: valid[p] for p in periods}}


def evaluate(fetcher=query):
    result = {}
    for geo in ('EA20', 'EA21'):
        try:
            result[geo] = inspect(fetcher(DATASET, FILTERS, geo, 36), geo)
        except Exception as exc:
            result[geo] = {'status': 'erro', 'reason': f'{type(exc).__name__}: {str(exc)[:300]}',
                           'source_verified': False, 'continuity_verified': False}
    a = result['EA20'].get('observations', {})
    b = result['EA21'].get('observations', {})
    common = sorted(set(a) & set(b))
    differences = [{'period': p, 'ea20': a[p], 'ea21': b[p], 'difference_pp': round(b[p] - a[p], 6)}
                   for p in common if abs(b[p] - a[p]) > 1e-9]
    ea21 = result['EA21']
    candidate = ea21.get('source_verified', False) and ea21.get('continuity_verified', False)
    return {'model_version': VERSION, 'asof_utc': datetime.now(timezone.utc).isoformat(),
            'asset': 'EUR/USD', 'experimental_target_geo': 'EA21',
            'candidate_dataset': DATASET, 'candidate_filters': FILTERS,
            'series_audit': result,
            'geography_comparison': {'common_period_count': len(common), 'different_months': differences,
                'latest_common_period': common[-1] if common else None,
                'latest_common_values': {'EA20': a[common[-1]], 'EA21': b[common[-1]]} if common else None},
            'ea21_technical_candidate_ready': bool(candidate),
            'methodology_equivalence_us_verified': False, 'vintage_verified': False,
            'production_change_authorized': False, 'source_code_modified': False,
            'eligible_factors': {k: False for k in ('inflation', 'unemployment', 'rates', 'activity')},
            'eligible_count': 0, 'coverage': 0.0, 'relative_score': None,
            'horizons': {'1d': {'score': None}, '5d': {'score': None}},
            'signals_generated': False, 'database_writes': False,
            'limitations': ['Validação técnica da série não implica equivalência com CPI dos EUA.',
                            'Sem vintage e horário de divulgação não é possível backtest ponto-no-tempo.',
                            'Nenhuma migração de fonte ou geografia em produção.']}


if __name__ == '__main__':
    print(json.dumps(evaluate(), ensure_ascii=False, indent=2))
