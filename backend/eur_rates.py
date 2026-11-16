"""Atlas EUR — coleta isolada de juros oficiais (sem score ou persistência).

BCE: facilidade de depósito (DFR), série FM; Fed: limite superior da faixa-alvo
(DFEDTARU) via FRED. Taxas não são instrumentos idênticos; diferencial descritivo.
"""
import csv
import io
import json
import math
import os
import urllib.parse
import urllib.request
from datetime import datetime, timezone

ECB_RATE_URL = ('https://data-api.ecb.europa.eu/service/data/FM/'
                'B.U2.EUR.4F.KR.DFR.LEV?format=csvdata&lastNObservations=30')
FRED_URL = 'https://api.stlouisfed.org/fred/series/observations'


def _read(url, accept, timeout=25, max_bytes=2_000_000):
    request = urllib.request.Request(url, headers={'User-Agent': 'AtlasEURRates/0.1', 'Accept': accept})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        content = response.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise ValueError('Resposta excedeu limite permitido')
    return content.decode('utf-8-sig')


def _normalize(rows, label):
    unique = {}
    for day, value in rows:
        try:
            parsed = datetime.strptime(day, '%Y-%m-%d').date()
            numeric = float(value)
            if math.isfinite(numeric) and -10 <= numeric <= 30 and parsed <= datetime.now(timezone.utc).date():
                unique[parsed.isoformat()] = numeric
        except (TypeError, ValueError):
            continue
    result = [{'date': d, 'value': unique[d]} for d in sorted(unique, reverse=True)]
    if not result:
        raise ValueError(f'Sem observações válidas: {label}')
    return result


def collect_ecb_deposit_rate(timeout=25):
    raw = _read(ECB_RATE_URL, 'text/csv', timeout)
    reader = csv.DictReader(io.StringIO(raw))
    if not reader.fieldnames or not {'TIME_PERIOD', 'OBS_VALUE'}.issubset(reader.fieldnames):
        raise ValueError('CSV BCE sem TIME_PERIOD/OBS_VALUE')
    recent = _normalize(((r.get('TIME_PERIOD'), r.get('OBS_VALUE')) for r in reader), 'BCE DFR')
    return {'source': 'ECB FM', 'series': 'B.U2.EUR.4F.KR.DFR.LEV',
            'description': 'Taxa da facilidade de depósito do BCE', 'unit': '% ao ano',
            'latest': recent[0], 'previous': recent[1] if len(recent) > 1 else None,
            'recent': recent, 'collected_at_utc': datetime.now(timezone.utc).isoformat()}


def collect_fed_upper_target(timeout=25, api_key=None):
    key = api_key or os.getenv('FRED_API_KEY', '').strip()
    if not key:
        raise ValueError('FRED_API_KEY ausente; comparação com Fed não disponível')
    url = FRED_URL + '?' + urllib.parse.urlencode({
        'series_id': 'DFEDTARU', 'api_key': key, 'file_type': 'json',
        'sort_order': 'desc', 'limit': 30})
    payload = json.loads(_read(url, 'application/json', timeout))
    recent = _normalize(((r.get('date'), r.get('value')) for r in payload.get('observations', [])), 'Fed')
    return {'source': 'FRED', 'series': 'DFEDTARU',
            'description': 'Limite superior da faixa-alvo dos Fed Funds', 'unit': '% ao ano',
            'latest': recent[0], 'previous': recent[1] if len(recent) > 1 else None,
            'recent': recent, 'collected_at_utc': datetime.now(timezone.utc).isoformat()}


def collect_rate_differential(timeout=25, api_key=None):
    result = {'asset': 'EUR', 'ecb': None, 'fed': None, 'differential_pp': None,
              'score': None, 'errors': {}, 'status': 'diagnóstico sem sinal direcional'}
    try:
        result['ecb'] = collect_ecb_deposit_rate(timeout)
    except Exception as exc:
        result['errors']['ecb'] = f'{type(exc).__name__}: {str(exc)[:160]}'
    try:
        result['fed'] = collect_fed_upper_target(timeout, api_key)
    except Exception as exc:
        result['errors']['fed'] = f'{type(exc).__name__}: {str(exc)[:160]}'
    if result['ecb'] and result['fed']:
        result['differential_pp'] = round(result['ecb']['latest']['value'] - result['fed']['latest']['value'], 4)
    result['note'] = ('Diferencial entre taxa de depósito BCE e limite superior da faixa-alvo Fed; '
                      'taxas não idênticas. Datas de observação não comprovam horário de divulgação. '
                      'Não é previsão EUR/USD nem sinal de negociação.')
    return result


if __name__ == '__main__':
    print(json.dumps(collect_rate_differential(), ensure_ascii=False, indent=2))
