"""Diagnostico somente leitura das series HICP Eurostat; nao gera sinais."""
import json
import urllib.parse
import urllib.request
from datetime import datetime, timezone

BASE = 'https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/'
CASES = [
    ('prc_hicp_manr', 'RCH_A', 'EA20'),
    ('prc_hicp_manr', 'RCH_A', 'EA21'),
    ('prc_hicp_midx', 'I15', 'EA20'),
    ('prc_hicp_midx', 'I15', 'EA21'),
]

def query(dataset, unit, geo, mode):
    params = {'geo': geo, 'coicop': 'CP00', 'freq': 'M', 'unit': unit, 'lang': 'EN'}
    if mode == 'since':
        params['sinceTimePeriod'] = '2025-01'
    elif mode == 'last':
        params['lastTimePeriod'] = 24
    url = BASE + dataset + '?' + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={'User-Agent': 'AtlasEUR-HICP-Diagnostic/3.0', 'Accept': 'application/json'})
    with urllib.request.urlopen(req, timeout=35) as resp:
        payload = resp.read(8_000_001)
    if len(payload) > 8_000_000:
        raise ValueError('Resposta maior que 8 MB')
    data = json.loads(payload)
    ids, sizes = data.get('id', []), data.get('size', [])
    dims = dict(zip(ids, sizes))
    out = {'dataset': dataset, 'unit': unit, 'geo': geo, 'mode': mode,
           'dimensions': dims, 'updated': data.get('updated'), 'status': 'diagnostico'}
    if 'time' not in dims:
        out['status'] = 'sem dimensao time'
        return out
    time_index = data['dimension']['time']['category']['index']
    if isinstance(time_index, list):
        time_index = {p: i for i, p in enumerate(time_index)}
    out['periods_returned'] = len(time_index)
    out['max_period_returned'] = max(time_index, default=None)
    out['min_period_returned'] = min(time_index, default=None)
    if any(n != 1 for k, n in dims.items() if k != 'time'):
        out['status'] = 'filtros sem serie unica'
        return out
    stride = 1
    for size in sizes[ids.index('time') + 1:]:
        stride *= size
    vals = data.get('value', {})
    observations = []
    for period, position in time_index.items():
        offset = position * stride
        val = vals.get(str(offset)) if isinstance(vals, dict) else (vals[offset] if offset < len(vals) else None)
        if val is not None:
            observations.append({'period': period, 'value': val})
    observations.sort(key=lambda row: row['period'], reverse=True)
    out['observations_count'] = len(observations)
    out['latest_five'] = observations[:5]
    out['latest_periods_missing_values'] = [p for p in sorted(time_index, reverse=True)[:8] if p not in {r['period'] for r in observations}]
    out['status'] = 'ok' if observations else 'sem observacoes'
    return out

if __name__ == '__main__':
    results = []
    for dataset, unit, geo in CASES:
        for mode in ('since', 'last'):
            try:
                results.append(query(dataset, unit, geo, mode))
            except Exception as exc:
                results.append({'dataset': dataset, 'unit': unit, 'geo': geo, 'mode': mode,
                                'status': 'erro', 'message': f'{type(exc).__name__}: {str(exc)[:200]}'})
    print(json.dumps({'checked_at_utc': datetime.now(timezone.utc).isoformat(), 'results': results}, ensure_ascii=False, indent=2))
    # Diagnostico nao falha por indisponibilidade de uma serie; analisar os dados do log.
