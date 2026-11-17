"""Atlas EUR RC5.7 — auditoria isolada de séries HICP Eurostat.
Somente leitura; nenhuma pontuação, sinal ou escrita em banco.
"""
import json
import math
import urllib.parse
import urllib.request
import urllib.error
from datetime import datetime, timezone

VERSION = 'eur-rc5.7-hicp-series-audit-0.5.7'
BASE = 'https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/'
# Manter filtros específicos de cada dataset: não presumir equivalência.
SOURCES = {
    'rc3_minr': {'dataset': 'prc_hicp_minr', 'filters': {'coicop18': 'TOTAL', 'unit': 'RCH_A'}},
    'rc56_manr': {'dataset': 'prc_hicp_manr', 'filters': {'coicop': 'CP00', 'unit': 'RCH_A'}},
}


def _indices(cat):
    raw = cat['index']
    return {v: i for i, v in enumerate(raw)} if isinstance(raw, list) else raw


def query(dataset, filters, geo, window, timeout=35):
    params = {**filters, 'geo': geo, 'lastTimePeriod': window, 'lang': 'EN'}
    url = BASE + dataset + '?' + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={'Accept': 'application/json', 'User-Agent': 'AtlasEUR-RC57/0.5.7'})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(4_000_001)
    except urllib.error.HTTPError as exc:
        msg = exc.read(500).decode('utf-8', 'replace')
        raise ValueError(f'HTTP {exc.code}: {msg[:300]}') from exc
    if len(raw) > 4_000_000:
        raise ValueError('Resposta Eurostat excedeu limite de 4MB')
    data = json.loads(raw)
    ids, sizes, dims = data['id'], data['size'], data['dimension']
    if len(ids) != len(sizes) or 'time' not in ids or 'geo' not in ids:
        raise ValueError('Estrutura JSON-stat inválida ou sem geo/time')
    selected, dimensions = {}, {}
    for dim, size in zip(ids, sizes):
        if dim == 'time':
            continue
        indices = _indices(dims[dim]['category'])
        codes = list(indices)
        dimensions[dim] = codes
        expected = geo if dim == 'geo' else filters.get(dim, 'M' if dim == 'freq' else None)
        if not codes and dim == 'geo':
            return {'status': 'sem_dados', 'reason': f'Geo {geo} não retornada', 'dimensions': dimensions}
        if expected is None or size != 1 or codes != [expected]:
            raise ValueError(f'Dimensão {dim}: retornou {codes}; esperado {expected}')
        selected[dim] = indices[expected]
    time_idx = _indices(dims['time']['category'])
    vals = data.get('value', {})
    obs = {}
    for period, ti in time_idx.items():
        pos = 0
        for dim, size in zip(ids, sizes):
            pos = pos * size + (ti if dim == 'time' else selected[dim])
        val = vals.get(str(pos)) if isinstance(vals, dict) else (vals[pos] if isinstance(vals, list) and pos < len(vals) else None)
        try:
            val = float(val)
        except (TypeError, ValueError):
            continue
        if math.isfinite(val):
            obs[period] = val
    if not obs:
        return {'status': 'sem_dados', 'reason': 'Sem observações numéricas', 'dimensions': dimensions}
    periods = sorted(obs)
    return {'status': 'ok', 'dimensions': dimensions, 'observation_count': len(obs),
            'earliest_period': periods[0], 'latest_period': periods[-1],
            'latest_value': obs[periods[-1]], 'observations': obs}


def evaluate(fetcher=query):
    out = {}
    for key, spec in SOURCES.items():
        cases = {}
        for geo in ('EA20', 'EA21'):
            for window in (12, 36):
                name = f'{geo}_last{window}'
                try:
                    cases[name] = fetcher(spec['dataset'], spec['filters'], geo, window)
                except Exception as exc:
                    cases[name] = {'status': 'erro', 'error': f'{type(exc).__name__}: {str(exc)[:300]}'}
        comparisons = {}
        for geo in ('EA20', 'EA21'):
            a, b = cases[f'{geo}_last12'], cases[f'{geo}_last36']
            oa, ob = a.get('observations', {}), b.get('observations', {})
            common = sorted(set(oa) & set(ob))
            mismatches = [{'period': p, 'last12': oa[p], 'last36': ob[p]} for p in common if abs(oa[p]-ob[p]) > 1e-9]
            comparisons[geo] = {'common_period_count': len(common), 'different_values_same_period': mismatches,
                                'latest12': a.get('latest_period'), 'latest36': b.get('latest_period')}
        out[key] = {'dataset': spec['dataset'], 'requested_filters': spec['filters'],
                    'cases': cases, 'window_comparison': comparisons}
    a = out['rc3_minr']['cases']['EA20_last36'].get('observations', {})
    b = out['rc56_manr']['cases']['EA20_last36'].get('observations', {})
    common = sorted(set(a) & set(b))
    return {'model_version': VERSION, 'asof_utc': datetime.now(timezone.utc).isoformat(),
            'asset': 'EUR/USD', 'sources': out,
            'cross_dataset_ea20': {'common_period_count': len(common),
                'last_common_period': common[-1] if common else None,
                'last_common_values': {'minr': a[common[-1]], 'manr': b[common[-1]]} if common else None,
                'same_series_definition_verified': False},
            'interpretation': 'Datasets e classificações COICOP diferentes; não inferir equivalência apenas de valores ou unidades.',
            'eligible_factors': {x: False for x in ('inflation','unemployment','rates','activity')},
            'eligible_count': 0, 'coverage': 0.0, 'relative_score': None,
            'horizons': {'1d': {'score': None}, '5d': {'score': None}},
            'signals_generated': False, 'database_writes': False, 'source_code_modified': False,
            'production_change_authorized': False,
            'limitations': ['Sem metadados oficiais de definição e vintage não há harmonização metodológica.',
                            'Erros de consulta e dados ausentes são preservados, sem interpolação.']}


if __name__ == '__main__':
    print(json.dumps(evaluate(), ensure_ascii=False, indent=2))
