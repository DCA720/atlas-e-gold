"""Diagnóstico HICP Eurostat: compara taxa anual e índices, sem gerar sinais."""
import json
import urllib.parse
import urllib.request
from datetime import datetime, timezone

BASE = 'https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/'
TESTS = [
    ('prc_hicp_manr', 'RCH_A', 'EA20'),
    ('prc_hicp_manr', 'RCH_A', 'EA21'),
    ('prc_hicp_midx', 'I15', 'EA20'),
    ('prc_hicp_midx', 'I15', 'EA21'),
    ('prc_hicp_midx', 'I25', 'EA20'),
    ('prc_hicp_midx', 'I25', 'EA21'),
]

def inspect(dataset, unit, geo):
    params = {'geo': geo, 'coicop': 'CP00', 'freq': 'M', 'unit': unit,
              'sinceTimePeriod': '2025-01', 'lang': 'EN'}
    url = BASE + dataset + '?' + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={'User-Agent': 'AtlasEUR-HICP-Diagnostic/2.0', 'Accept': 'application/json'})
    with urllib.request.urlopen(req, timeout=35) as response:
        data = json.load(response)
    dims = dict(zip(data.get('id', []), data.get('size', [])))
    result = {'dataset': dataset, 'unit': unit, 'geo': geo, 'dimensions': dims}
    if not dims or 'time' not in dims or any(n != 1 for k, n in dims.items() if k != 'time'):
        result['status'] = 'sem serie unica'
        return result
    idx = data['dimension']['time']['category']['index']
    if isinstance(idx, list):
        idx = {period: i for i, period in enumerate(idx)}
    sizes, ids = data['size'], data['id']
    stride = 1
    for size in sizes[ids.index('time') + 1:]:
        stride *= size
    vals = data.get('value', {})
    rows = []
    for period, position in idx.items():
        offset = position * stride
        value = vals.get(str(offset)) if isinstance(vals, dict) else (vals[offset] if offset < len(vals) else None)
        if value is not None:
            rows.append({'period': period, 'value': value})
    rows.sort(key=lambda r: r['period'], reverse=True)
    result['status'] = 'ok' if rows else 'sem observacoes'
    result['latest_three'] = rows[:3]
    if rows:
        y, m = map(int, rows[0]['period'].split('-'))
        now = datetime.now(timezone.utc)
        result['age_months'] = (now.year - y) * 12 + now.month - m
    return result

if __name__ == '__main__':
    results = []
    for dataset, unit, geo in TESTS:
        try:
            results.append(inspect(dataset, unit, geo))
        except Exception as exc:
            results.append({'dataset': dataset, 'unit': unit, 'geo': geo,
                            'status': 'erro', 'message': f'{type(exc).__name__}: {str(exc)[:200]}'})
    print(json.dumps({'checked_at_utc': datetime.now(timezone.utc).isoformat(),
                      'results': results}, ensure_ascii=False, indent=2))
    if not any(r.get('status') == 'ok' and 0 <= r.get('age_months', 999) <= 4 for r in results):
        raise SystemExit('Sem serie HICP recente: manter score EUR desativado')
