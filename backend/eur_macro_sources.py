"""Atlas EUR — coleta experimental Eurostat, isolada do Atlas em produção.

Não gera sinais, não grava em bancos e não altera USD/GOLD.
Requer Python 3.11+; sem dependências externas.
"""
import json
import math
import urllib.parse
import urllib.request
from datetime import datetime, timezone

BASE = 'https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/'
SERIES = {
    'hicp_yoy': {
        'dataset': 'prc_hicp_manr',
        'filters': {'geo': 'EA21', 'coicop': 'CP00'},
        'description': 'Inflação harmonizada anual, índice geral, área do euro (EA21)',
        'unit': '% ao ano',
    },
    'unemployment': {
        'dataset': 'une_rt_m',
        'filters': {'geo': 'EA21', 's_adj': 'SA', 'age': 'TOTAL', 'sex': 'T', 'unit': 'PC_ACT'},
        'description': 'Taxa de desemprego mensal dessazonalizada, idade total, área do euro (EA21)',
        'unit': '% da população ativa',
    },
    'activity': {
        'dataset': 'namq_10_gdp',
        'filters': {'geo': 'EA21', 'na_item': 'B1G', 's_adj': 'SCA', 'unit': 'CLV_PCH_PRE'},
        'description': 'PIB real trimestral, variação percentual frente ao trimestre anterior, área do euro (EA21)',
        'unit': '% trimestre contra trimestre',
    },
}


def _get_json(url, timeout=25):
    request = urllib.request.Request(url, headers={'User-Agent': 'AtlasMacro-EUR/0.2', 'Accept': 'application/json'})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        content = response.read(5_000_001)
    if len(content) > 5_000_000:
        raise ValueError('Resposta Eurostat excedeu 5 MB')
    return json.loads(content.decode('utf-8-sig'))


def _extract_series(data):
    """Lê observações de uma série filtrada em formato JSON-stat 2.0.

    Recusa respostas com dimensões não temporais contendo mais de uma categoria:
    nunca mistura países, faixas etárias ou séries diferentes silenciosamente.
    """
    ids = data['id']
    sizes = data['size']
    dimensions = data['dimension']
    if len(ids) != len(sizes) or 'time' not in ids:
        raise ValueError('Dimensões Eurostat inesperadas')
    if any(size == 0 for size in sizes):
        raise ValueError('Série sem categorias: ' + ', '.join(dim for dim, size in zip(ids, sizes) if size == 0))
    for dim, size in zip(ids, sizes):
        if dim != 'time' and size == 0:
            raise ValueError(f'Série não encontrada: dimensão {dim} sem categorias; confira filtros e disponibilidade no Eurostat')
        if dim != 'time' and size != 1:
            raise ValueError(f'Filtro insuficiente: dimensão {dim} possui {size} categorias')
    time_dim = dimensions['time']['category']['index']
    if isinstance(time_dim, list):
        time_index = {key: i for i, key in enumerate(time_dim)}
    else:
        time_index = time_dim
    time_pos = ids.index('time')
    stride = math.prod(sizes[time_pos + 1:])
    values = data.get('value', {})
    rows = []
    for date, idx in time_index.items():
        flat_index = idx * stride
        value = values.get(str(flat_index)) if isinstance(values, dict) else (values[flat_index] if flat_index < len(values) else None)
        if value is None:
            continue
        try:
            value = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(value):
            rows.append({'date': date, 'value': value})
    rows.sort(key=lambda x: x['date'], reverse=True)
    if len(rows) < 2:
        raise ValueError('Menos de duas observações válidas')
    return rows[:36]


def collect_eurostat(name, timeout=25):
    spec = SERIES[name]
    params = {**spec['filters'], 'lang': 'EN', 'lastTimePeriod': 36}
    url = BASE + spec['dataset'] + '?' + urllib.parse.urlencode(params)
    data = _get_json(url, timeout=timeout)
    rows = _extract_series(data)
    # Recusa séries antigas, inclusive quando o código geográfico foi descontinuado.
    from datetime import date
    today = datetime.now(timezone.utc).date()
    period = rows[0]['date']
    if name == 'activity':
        year, quarter = int(period[:4]), int(period[-1])
        age = (today.year - year) * 4 + (today.month - 1) // 3 + 1 - quarter
        if not 0 <= age <= 3:
            raise ValueError(f'Atividade desatualizada: última observação {period}')
    else:
        year, month = map(int, period.split('-'))
        age = (today.year - year) * 12 + today.month - month
        if not 0 <= age <= 4:
            raise ValueError(f'Série {name} desatualizada: última observação {period}')
    return {
        'indicator': name, 'asset': 'EUR', 'source': 'Eurostat',
        'dataset': spec['dataset'], 'filters': spec['filters'],
        'description': spec['description'], 'unit': spec['unit'],
        'collected_at_utc': datetime.now(timezone.utc).isoformat(),
        'latest': rows[0], 'previous': rows[1], 'recent': rows,
        'score': None, 'status': 'observações coletadas; sem pontuação direcional',
        'note': 'Data de referência estatística não é horário de divulgação; dados sujeitos a revisões.'
    }


def collect_eur_macro(timeout=25):
    result = {'asset': 'EUR', 'collected_at_utc': datetime.now(timezone.utc).isoformat(),
              'indicators': {}, 'errors': {}, 'score': None,
              'status': 'coleta experimental; sem viés macro calculado'}
    for name in SERIES:
        try:
            result['indicators'][name] = collect_eurostat(name, timeout)
        except (KeyError, ValueError, TypeError, OSError, TimeoutError, json.JSONDecodeError) as exc:
            result['errors'][name] = f'{type(exc).__name__}: {str(exc)[:200]}'
        except Exception as exc:
            # Falha isolada por indicador, sem impedir o diagnóstico do restante.
            result['errors'][name] = f'{type(exc).__name__}: {str(exc)[:200]}'
    return result


if __name__ == '__main__':
    print(json.dumps(collect_eur_macro(), ensure_ascii=False, indent=2))
