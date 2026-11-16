"""Diagnostica códigos geo disponíveis para inflação HICP anual da Eurostat.
Não produz scores, não grava dados e não altera o Atlas em produção.
"""
import json
import urllib.parse
import urllib.request
from datetime import datetime, timezone

BASE = 'https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/prc_hicp_manr'
CANDIDATES = ('EA21', 'EA20', 'EA19', 'EA')

def probe(geo):
    params = {'geo': geo, 'coicop': 'CP00', 'lang': 'EN', 'lastTimePeriod': 15}
    url = BASE + '?' + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={'Accept': 'application/json', 'User-Agent': 'AtlasEUR-GeoDiagnostic/1.0'})
    with urllib.request.urlopen(request, timeout=30) as response:
        data = json.load(response)
    dims = dict(zip(data.get('id', []), data.get('size', [])))
    result = {'geo': geo, 'dimensions': dims}
    if not dims or any(size != 1 for key, size in dims.items() if key != 'time') or any(size == 0 for size in dims.values()):
        result['status'] = 'sem serie unica'
        return result
    periods = data['dimension']['time']['category']['index']
    if isinstance(periods, list):
        periods = {p: i for i, p in enumerate(periods)}
    stride = 1
    ids, sizes = data['id'], data['size']
    for size in sizes[ids.index('time') + 1:]:
        stride *= size
    values = data.get('value', {})
    rows = []
    for period, idx in periods.items():
        offset = idx * stride
        value = values.get(str(offset)) if isinstance(values, dict) else (values[offset] if offset < len(values) else None)
        if value is not None:
            rows.append((period, value))
    rows.sort(reverse=True)
    result['status'] = 'ok' if rows else 'sem observacoes'
    result['latest'] = {'period': rows[0][0], 'value': rows[0][1]} if rows else None
    result['previous'] = {'period': rows[1][0], 'value': rows[1][1]} if len(rows) > 1 else None
    if rows:
        year, month = map(int, rows[0][0].split('-'))
        now = datetime.now(timezone.utc).date()
        result['age_months'] = (now.year - year) * 12 + now.month - month
    return result

if __name__ == '__main__':
    results = []
    for geo in CANDIDATES:
        try:
            results.append(probe(geo))
        except Exception as exc:
            results.append({'geo': geo, 'status': 'erro', 'error': f'{type(exc).__name__}: {str(exc)[:180]}'})
    print(json.dumps({'dataset': 'prc_hicp_manr', 'results': results}, indent=2, ensure_ascii=False))
    if not any(r.get('status') == 'ok' and 0 <= r.get('age_months', 999) <= 4 for r in results):
        raise SystemExit('Nenhuma serie recente encontrada: nao alterar score sem diagnostico')
