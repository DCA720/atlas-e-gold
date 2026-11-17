"""Atlas EUR RC5.5.2: diagnostico geográfico Eurostat (somente leitura).

Corrige dimensoes implicitas (freq/unit), distingue ausencia de geo de erro
tecnico e preserva todos os bloqueios de score e escrita.
"""
import contextlib
import io
import json
import math
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from atlas_eur_rc551 import SPECS

VERSION = 'eur-rc5.5.2-geography-diagnostic-0.5.5.2'
BASE = 'https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/'


class NoData(Exception):
    """Resposta valida sem observacoes para os filtros/geografia solicitados."""


def _index_map(category):
    idx = category['index']
    return {code: i for i, code in enumerate(idx)} if isinstance(idx, list) else idx


def fetch(dataset, filters, geo, timeout=35):
    params = {**filters, 'geo': geo, 'lastTimePeriod': 12, 'lang': 'EN'}
    url = BASE + dataset + '?' + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={
        'User-Agent': 'Atlas-EUR-RC552/0.5.5.2', 'Accept': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read(3_000_001)
    except urllib.error.HTTPError as exc:
        # HTTP 400/404 podem ser filtro invalido OU serie vazia: nao assumir qual.
        detail = exc.read(1000).decode('utf-8', errors='replace')
        raise ValueError(f'HTTP {exc.code} Eurostat: {detail[:300]}') from exc
    if len(raw) > 3_000_000:
        raise ValueError('Resposta Eurostat excedeu 3 MB')
    data = json.loads(raw)
    ids, sizes, dims = data['id'], data['size'], data['dimension']
    if len(ids) != len(sizes) or 'time' not in ids:
        raise ValueError('Dimensoes JSON-stat invalidas ou tempo ausente')
    freq = 'Q' if dataset == 'namq_10_gdp' else 'M'
    # A API pode incluir dimensoes de tamanho 1 nao explicitadas na consulta.
    implicit = {'freq': freq}
    if dataset == 'prc_hicp_manr':
        implicit['unit'] = 'RCH_A'
    selected = {}
    dimensions_seen = {}
    for dim, size in zip(ids, sizes):
        if dim == 'time':
            continue
        index = _index_map(dims[dim]['category'])
        codes = list(index)
        expected = geo if dim == 'geo' else filters.get(dim, implicit.get(dim))
        dimensions_seen[dim] = codes
        if dim == 'geo' and (size == 0 or not codes):
            raise NoData(f'Geografia {geo} ausente na resposta Eurostat')
        if expected is None:
            raise ValueError(f'Dimensao adicional nao reconhecida: {dim}={codes}')
        if size != 1 or codes != [expected]:
            raise ValueError(f'Dimensao {dim} inesperada: {codes}, esperado {expected}')
        selected[dim] = index[expected]
    if 'geo' not in ids:
        raise ValueError('Dimensao geo ausente da resposta; filtro nao comprovado')
    time_index = _index_map(dims['time']['category'])
    values = data.get('value', {})
    observations = {}
    for period, time_i in time_index.items():
        flat = 0
        for dim, size in zip(ids, sizes):
            flat = flat * size + (time_i if dim == 'time' else selected[dim])
        val = values.get(str(flat)) if isinstance(values, dict) else (
            values[flat] if isinstance(values, list) and flat < len(values) else None)
        try:
            val = float(val)
        except (TypeError, ValueError):
            continue
        if math.isfinite(val):
            observations[period] = val
    if not observations:
        raise NoData('Resposta valida, mas sem observacoes numericas')
    return {'geo': geo, 'dataset': dataset, 'filters_verified': True,
            'dimensions_verified': dimensions_seen,
            'observation_count': len(observations), 'observations': observations,
            'latest_period': max(observations)}


def evaluate(rc54, fetcher=fetch):
    results = {}
    for factor, (dataset, filters) in SPECS.items():
        entries = {}
        for geo in ('EA20', 'EA21'):
            try:
                entries[geo] = {'status': 'ok', **fetcher(dataset, filters, geo)}
            except NoData as exc:
                entries[geo] = {'status': 'sem_dados', 'geo': geo, 'reason': str(exc)[:300]}
            except Exception as exc:
                entries[geo] = {'status': 'erro', 'geo': geo,
                                'error': f'{type(exc).__name__}: {str(exc)[:300]}'}
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
        'geography_audit': results, 'full_pipeline_verified': False,
        'source_code_modified': False,
        'eligible_factors': {f: False for f in ('inflation', 'unemployment', 'rates', 'activity')},
        'eligible_count': 0, 'coverage': 0.0, 'relative_score': None,
        'horizons': {'1d': {'score': None}, '5d': {'score': None}},
        'signals_generated': False, 'database_writes': False,
        'status': 'Auditoria geografica RC5.5.2; nenhuma alteracao em producao',
        'limitations': [
            'Dados ausentes nao sao tratados como zeros ou interpolados',
            'Disponibilidade geografica nao valida comparabilidade metodologica EUA/Europa',
            'Sem vintages e horarios de publicacao nao ha sinal nem backtest ponto-no-tempo',
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
