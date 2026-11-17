"""Atlas EUR RC5.5 — auditoria experimental de normalizacao geografica.

Somente leitura: consulta EA20 e EA21 diretamente no Eurostat, preserva
pontuacao e sinais bloqueados. Nao altera a coleta original nem USD/GOLD.
"""
import contextlib
import io
import json
import math
import urllib.parse
import urllib.request
from datetime import datetime, timezone

VERSION = 'eur-rc5.5-geography-normalization-audit-0.5.5'
BASE = 'https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/'
SPECS = {
    'inflation': ('prc_hicp_manr', {'coicop': 'CP00'}),
    'unemployment': ('une_rt_m', {'s_adj': 'SA', 'age': 'TOTAL', 'sex': 'T', 'unit': 'PC_ACT'}),
    'activity': ('namq_10_gdp', {'na_item': 'B1G', 's_adj': 'SCA', 'unit': 'CLV_PCH_PRE'}),
}


def fetch(dataset, filters, geo, timeout=30):
    params = {**filters, 'geo': geo, 'lastTimePeriod': 12, 'lang': 'EN'}
    url = BASE + dataset + '?' + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={'User-Agent': 'Atlas-EUR-RC55/0.5.5', 'Accept': 'application/json'})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read(3_000_001)
    if len(raw) > 3_000_000:
        raise ValueError('Resposta Eurostat excedeu 3 MB')
    data = json.loads(raw)
    ids, sizes = data['id'], data['size']
    if len(ids) != len(sizes) or 'time' not in ids:
        raise ValueError('Dimensoes invalidas ou tempo ausente')
    dims = data['dimension']
    for dim, size in zip(ids, sizes):
        if dim == 'time':
            continue
        index = dims[dim]['category']['index']
        codes = list(index)
        expected = geo if dim == 'geo' else filters.get(dim)
        if size != 1 or expected is None or codes != [expected]:
            raise ValueError(f'Dimensao {dim} inesperada: {codes}, esperado {expected}')
    time_index = dims['time']['category']['index']
    if isinstance(time_index, list):
        time_index = {key: i for i, key in enumerate(time_index)}
    time_pos = ids.index('time')
    stride = math.prod(sizes[time_pos + 1:])
    values = data.get('value', {})
    observations = {}
    for period, i in time_index.items():
        flat = i * stride
        val = values.get(str(flat)) if isinstance(values, dict) else (values[flat] if flat < len(values) else None)
        try:
            val = float(val)
        except (ValueError, TypeError):
            continue
        if math.isfinite(val):
            observations[period] = val
    if not observations:
        raise ValueError('Nenhuma observacao numerica encontrada')
    return {'geo': geo, 'dataset': dataset, 'filters_verified': True,
            'observation_count': len(observations), 'observations': observations,
            'latest_period': max(observations)}


def evaluate(rc54, fetcher=fetch):
    results = {}
    for factor, (dataset, filters) in SPECS.items():
        entries = {}
        for geo in ('EA20', 'EA21'):
            try:
                entries[geo] = {'status': 'ok', **fetcher(dataset, filters, geo)}
            except Exception as exc:
                entries[geo] = {'status': 'erro', 'geo': geo,
                                'error': f'{type(exc).__name__}: {str(exc)[:200]}'}
        a, b = entries['EA20'], entries['EA21']
        common = sorted(set(a.get('observations', {})) & set(b.get('observations', {})))
        latest = common[-1] if common else None
        va = a.get('observations', {}).get(latest) if latest else None
        vb = b.get('observations', {}).get(latest) if latest else None
        results[factor] = {
            'dataset': dataset, 'filters': filters, 'by_geo': entries,
            'both_available': a['status'] == b['status'] == 'ok',
            'common_period_count': len(common), 'latest_common_period': latest,
            'latest_common_ea20': va, 'latest_common_ea21': vb,
            'difference_ea21_minus_ea20': round(vb - va, 6) if va is not None and vb is not None else None,
            'geography_normalization_ready': a['status'] == b['status'] == 'ok' and bool(common),
            'score_eligible': False,
        }
    return {
        'model_version': VERSION, 'asof_utc': datetime.now(timezone.utc).isoformat(),
        'asset': 'EUR/USD', 'source_model_version': rc54.get('model_version'),
        'target_geography_experimental': 'EA21',
        'original_mismatch_detected': (rc54.get('geography') or {}).get('mismatch_detected'),
        'geography_audit': results,
        'full_pipeline_verified': False,
        'source_code_modified': False,
        'eligible_factors': {f: False for f in ('inflation', 'unemployment', 'rates', 'activity')},
        'eligible_count': 0, 'coverage': 0.0, 'relative_score': None,
        'horizons': {'1d': {'score': None}, '5d': {'score': None}},
        'signals_generated': False, 'database_writes': False,
        'status': 'Auditoria geografica experimental; nenhuma alteracao em producao',
        'limitations': [
            'Disponibilidade EA21 nao comprova consistencia de toda a cadeia de coleta',
            'Diferencas geograficas nao comprovam comparabilidade metodologica com EUA',
            'Sem vintages nem horario de publicacao nao ha backtest ponto-no-tempo',
        ],
    }


def main():
    from atlas_eur_rc54 import main as rc54_main
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc54_main()
    print(json.dumps(evaluate(json.loads(buf.getvalue())), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
